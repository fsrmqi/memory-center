from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from ..config import load_workspace_config
from ..rules import (
    DEFAULT_AUTO_SYNC_RULES,
    DEFAULT_EVAL_RULES,
    DEFAULT_HANDOFF_PROFILES,
    DEFAULT_HANDOFF_RULES,
    DEFAULT_RESUME_RULES,
    DEFAULT_WRITE_POLICY_RULES,
    ensure_default_rules,
    load_yaml_rule_config,
    match_rules,
)
from ..store import WorkspaceStore

SESSION_EVENTS_FILE = "session-events.jsonl"
SESSION_SUMMARIES_FILE = "session-summaries.jsonl"
EVENT_PAYLOAD_INLINE_LIMIT = 4000
LAYER_L0 = "L0_session_events"
LAYER_L1 = "L1_case_atoms"
LAYER_L2 = "L2_task_spaces"
LAYER_L3 = "L3_workspace_profile"
MEMORY_LAYER_ORDER = [LAYER_L0, LAYER_L1, LAYER_L2, LAYER_L3]
TOOL_WORKSPACE_LOG_SESSION_EVENT = "workspace_log_session_event"
TOOL_WORKSPACE_START_SESSION = "workspace_start_session"
TOOL_WORKSPACE_RECORD_CASE = "workspace_record_case"
TOOL_WORKSPACE_SUGGEST_CASE = "workspace_suggest_case"
TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS = "workspace_sync_sniff_artifacts"
TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS = "workspace_sync_case_artifacts"
TOOL_WORKSPACE_ARTIFACT_UPDATE = "workspace_artifact_update"


def load_context(workspace_file: str | Path):
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    return config, store


def _new_session_id() -> str:
    return f"session-{uuid4().hex[:12]}"


def _is_compact_view(view: str) -> bool:
    return (view or "").strip().lower() == "compact"


def _normalize_budget(budget: str) -> str:
    value = (budget or "medium").strip().lower()
    return value if value in {"small", "medium", "large"} else "medium"


MODEL_BUDGET_PROFILES: Dict[str, Dict[str, int]] = {
    "codex": {"services": 3, "files": 4, "refs": 4, "steps": 3, "tasks": 3, "events": 3, "findings": 3},
    "claude-code": {"services": 5, "files": 5, "refs": 5, "steps": 4, "tasks": 5, "events": 4, "findings": 4},
    "gemini": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "deepseek": {"services": 3, "files": 3, "refs": 3, "steps": 2, "tasks": 3, "events": 2, "findings": 2},
    "cursor-agent": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "glm": {"services": 3, "files": 3, "refs": 3, "steps": 2, "tasks": 3, "events": 2, "findings": 2},
    "qwen": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "generic-mcp-agent": {"services": 5, "files": 5, "refs": 5, "steps": 4, "tasks": 5, "events": 4, "findings": 4},
}


def _budget_limits(budget: str, model: str = "") -> Dict[str, int]:
    normalized = _normalize_budget(budget)
    model_profile = MODEL_BUDGET_PROFILES.get(_normalize_model_name(model or ""), MODEL_BUDGET_PROFILES["generic-mcp-agent"])
    if normalized == "small":
        return {k: max(1, v // 2) for k, v in model_profile.items()}
    if normalized == "large":
        return model_profile
    return {k: max(2, int(v * 0.7)) for k, v in model_profile.items()}


def _normalize_model_name(model_name: str) -> str:
    raw = (model_name or "").strip().lower()
    if raw in {"codex", "openai-codex"}:
        return "codex"
    if raw in {"claude", "claude-code", "claudecode"}:
        return "claude-code"
    if raw in {"cursor", "cursor-agent", "cursorai"}:
        return "cursor-agent"
    if raw.startswith("gemini"):
        return "gemini"
    if raw.startswith("deepseek"):
        return "deepseek"
    if raw.startswith("glm") or raw.startswith("chatglm"):
        return "glm"
    if raw.startswith("qwen"):
        return "qwen"
    if raw.startswith("minimax"):
        return "minimax"
    if raw.startswith("mimo"):
        return "mimo"
    return "generic-mcp-agent"


def _summarize_ref(ref: Dict[str, Any]) -> str:
    parts = [
        str(ref.get("tool_name", "") or ""),
        str(ref.get("query", "") or ref.get("target", "") or ref.get("name", "") or ref.get("task", "") or ""),
        str(ref.get("file_path", "") or ref.get("path", "") or ""),
        str(ref.get("payload_ref", "") or ref.get("receipt_ref", "") or ""),
    ]
    text = " | ".join(part for part in parts if part).strip()
    if not text:
        text = str(ref.get("type", "") or ref.get("event_type", "") or ref.get("source", "") or "ref")
    return text[:140]


def _trim_summary(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _render_ref_label(ref: Dict[str, Any]) -> str:
    return (
        str(ref.get("summary", "") or "")
        or str(ref.get("name", "") or ref.get("task", "") or ref.get("query", "") or ref.get("target", "") or ref.get("file_path", "") or ref.get("path", "") or ref.get("payload_ref", "") or ref.get("ref_id", "") or "ref")
    )


def _choose_l3_artifact_name(text: str) -> str:
    normalized = (text or "").lower()
    if any(k in normalized for k in ["团队", "协作", "code review", "评审", "规范", "rules", "约定"]):
        return "team_rules"
    if any(k in normalized for k in ["架构", "invariant", "分层", "模块边界", "边界", "design principle"]):
        return "architecture_invariants"
    if any(k in normalized for k in ["迁移", "migration", "cutover", "灰度", "兼容期"]):
        return "active_migration_policy"
    return "workspace_profile"


def _score_threshold_for_sync_mode(auto_sync_mode: str) -> int:
    mode = (auto_sync_mode or "balanced").strip().lower()
    if mode == "strict":
        return 4
    if mode == "aggressive":
        return 1
    return 3


def _load_resume_rules(store: WorkspaceStore, text: str) -> Dict[str, Any]:
    data = load_yaml_rule_config(store, "resume-rules.yaml", DEFAULT_RESUME_RULES)
    default = dict(DEFAULT_RESUME_RULES.get("default", {}))
    default.update(data.get("default", {}))
    normalized = (text or "").lower()
    for profile_name, profile in (data.get("profiles", {}) or {}).items():
        triggers = [str(item).lower() for item in profile.get("trigger_keywords", [])]
        if triggers and any(token in normalized for token in triggers):
            merged = dict(default)
            merged.update(profile)
            merged["profile_name"] = profile_name
            return merged
    default["profile_name"] = "default"
    return default


def _load_handoff_rules(store: WorkspaceStore, normalized_model: str) -> Dict[str, Any]:
    data = load_yaml_rule_config(store, "handoff-rules.yaml", DEFAULT_HANDOFF_RULES)
    default = dict(DEFAULT_HANDOFF_RULES.get("default", {}))
    default.update(data.get("default", {}))
    for profile_name, profile in (data.get("profiles", {}) or {}).items():
        trigger_models = [str(item).lower() for item in profile.get("trigger_models", [])]
        if trigger_models and normalized_model in trigger_models:
            merged = dict(default)
            merged.update(profile)
            merged["profile_name"] = profile_name
            return merged
    default["profile_name"] = "default"
    return default


def _load_write_policy_rules(store: WorkspaceStore) -> Dict[str, Any]:
    return load_yaml_rule_config(store, "write-policy-rules.yaml", DEFAULT_WRITE_POLICY_RULES).get("default", {})


def _load_auto_sync_rules(store: WorkspaceStore) -> Dict[str, Any]:
    return load_yaml_rule_config(store, "auto-sync-rules.yaml", DEFAULT_AUTO_SYNC_RULES).get("default", {})


def _load_eval_rules(store: WorkspaceStore) -> Dict[str, Any]:
    return load_yaml_rule_config(store, "eval-rules.yaml", DEFAULT_EVAL_RULES)


def _event_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    payload = event.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _prepare_session_event_payload(
    store: WorkspaceStore,
    session_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> tuple[Dict[str, Any], str, int]:
    safe_payload = payload if isinstance(payload, dict) else {}
    payload_bytes = len(json.dumps(safe_payload, ensure_ascii=False).encode("utf-8"))
    if payload_bytes <= EVENT_PAYLOAD_INLINE_LIMIT:
        return safe_payload, "", payload_bytes
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    ref_name = f"refs/sessions/{session_id}/{timestamp}-{event_type}.json"
    payload_ref = store.write_memory_ref_json(ref_name, safe_payload)
    compact = _compact_session_payload(safe_payload)
    compact["_payload_offloaded"] = True
    compact["_payload_ref"] = payload_ref
    compact["_payload_keys"] = sorted(safe_payload.keys())[:20]
    compact["_payload_bytes"] = payload_bytes
    return compact, payload_ref, payload_bytes


def _compact_session_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Try tool-specific compressor first; fall back to generic extraction
    tool_name = str(payload.get("tool_name", "") or "").lower()
    compressed = _compact_tool_payload(payload, tool_name)
    if compressed:
        return compressed
    # Generic fallback: extract preferred keys
    compact: Dict[str, Any] = {}
    preferred_keys = [
        "tool_name", "query", "target", "name", "project", "file", "file_path", "path",
        "intent", "outcome", "text", "summary", "note",
    ]
    for key in preferred_keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            compact[key] = value[:300]
        elif isinstance(value, (int, float, bool)):
            compact[key] = value
    if "verified_by" in payload and isinstance(payload.get("verified_by"), list):
        compact["verified_by"] = payload.get("verified_by", [])[:10]
    return compact


def _compact_tool_payload(payload: Dict[str, Any], tool_name: str) -> Dict[str, Any] | None:
    """Tool-specific payload compressor, inspired by rtk's per-command compression strategies.

    Returns None if no specialized compressor matches, causing fallback to generic extraction.
    """
    text = json.dumps(payload, ensure_ascii=False).lower()

    # Strategy: Stats Extraction — git status / git diff
    if tool_name in {"git", "bash"} and ("git status" in text or "git diff" in text):
        return _compact_git_stats(payload)

    # Strategy: Failure Focus — pytest / cargo test / go test
    if any(marker in tool_name for marker in ["pytest", "test", "vitest", "cargo"]):
        return _compact_test_result(payload)

    # Strategy: Grouping by Pattern — grep / rg / search
    if any(marker in tool_name for marker in ["grep", "rg", "search", "find"]):
        return _compact_search_result(payload)

    return None


def _compact_git_stats(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Stats Extraction for git commands: keep only summary counts."""
    compact = {"tool_name": payload.get("tool_name", ""), "command": "git"}
    # Try to extract common git fields
    for key in ["branch", "ahead", "behind", "staged", "unstaged", "untracked", "insertions", "deletions", "files_changed", "conflicts"]:
        value = payload.get(key)
        if value is not None:
            compact[key] = value
    # If raw output exists, try to extract a short summary
    output = str(payload.get("output", "") or payload.get("stdout", "") or "")
    if output and len(output) > 200:
        compact["output_summary"] = output[:200]
    return compact


def _compact_test_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Failure Focus for test commands: keep only failures + totals."""
    compact = {"tool_name": payload.get("tool_name", "")}
    # Extract test result summary fields
    for key in ["passed", "failed", "errors", "skipped", "total", "test_count", "failure_count", "duration", "exit_code", "status"]:
        value = payload.get(key)
        if value is not None:
            compact[key] = value
    # Keep failed test names only (truncate list)
    failed_names = payload.get("failed_tests", payload.get("failures", []))
    if isinstance(failed_names, list) and failed_names:
        compact["failed_tests"] = [str(n)[:80] for n in failed_names[:8]]
    return compact


def _compact_search_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Grouping by Pattern for search commands: keep counts + top matches."""
    compact = {"tool_name": payload.get("tool_name", ""), "query": str(payload.get("query", "") or payload.get("pattern", "") or "")[:120]}
    # Extract count fields
    for key in ["total_matches", "match_count", "file_count", "count"]:
        value = payload.get(key)
        if value is not None:
            compact[key] = value
    # Keep top matches grouped by file
    matches = payload.get("matches", payload.get("results", []))
    if isinstance(matches, list) and matches:
        files: Dict[str, int] = {}
        for m in matches[:20]:
            f = str(m.get("file", m.get("path", "")) or "")[:60]
            if f:
                files[f] = files.get(f, 0) + 1
        if files:
            compact["files_with_matches"] = dict(sorted(files.items(), key=lambda kv: -kv[1])[:5])
    return compact


def _build_case_evidence_refs(events: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for idx, event in enumerate(events[-limit:], start=max(len(events) - limit, 0) + 1):
        payload = _event_payload(event)
        ref = {
            "ref_id": f"ev:{event.get('session_id', '')}:{event.get('event_type', '')}:{idx}",
            "event_index": idx,
            "event_type": event.get("event_type", ""),
            "created_at": event.get("created_at", ""),
        }
        payload_ref = event.get("payload_ref", "")
        if isinstance(payload_ref, str) and payload_ref:
            ref["payload_ref"] = payload_ref
        for key in ["tool_name", "query", "target", "name", "project", "file_path", "path"]:
            value = payload.get(key)
            if isinstance(value, str) and value:
                ref[key] = value
        ref["summary"] = _summarize_ref(ref)
        refs.append(ref)
    return refs


def _build_event_source_refs(events: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for idx, event in enumerate(events[-limit:], start=max(len(events) - limit, 0) + 1):
        payload = _event_payload(event)
        event_type = str(event.get("event_type", "") or "")
        payload_ref = str(event.get("payload_ref", "") or "")
        entry = {
            "ref_id": f"src:{event.get('session_id', '')}:{event_type}:{idx}",
            "type": "session_event",
            "event_type": event_type,
            "created_at": event.get("created_at", ""),
        }
        for key in ["tool_name", "query", "target", "project", "file_path", "path"]:
            value = payload.get(key)
            if isinstance(value, str) and value:
                entry[key] = value
        if payload_ref:
            entry["payload_ref"] = payload_ref
        if len(entry) > 3:
            entry["summary"] = _summarize_ref(entry)
            refs.append(entry)
    return refs


def _build_sniff_source_refs(
    matched_files: List[Dict[str, Any]],
    related_feigns: List[Dict[str, Any]],
    related_apis: List[Dict[str, Any]],
    related_mq: List[Dict[str, Any]],
    related_cases: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for idx, item in enumerate(matched_files[:6], start=1):
        path = item.get("path", "")
        if path:
            ref = {"ref_id": f"src:file:{idx}", "type": "file", "path": path, "project": item.get("project", ""), "score": item.get("score", 0)}
            ref["summary"] = _summarize_ref(ref)
            refs.append(ref)
    for idx, item in enumerate(related_feigns[:4], start=1):
        if item.get("interface"):
            ref = {"ref_id": f"src:feign:{idx}", "type": "feign", "name": item.get("interface", ""), "project": item.get("project", ""), "path": item.get("file", "")}
            ref["summary"] = _summarize_ref(ref)
            refs.append(ref)
    for idx, item in enumerate(related_apis[:4], start=1):
        if item.get("path"):
            ref = {"ref_id": f"src:api:{idx}", "type": "api", "name": f"{item.get('http_method', '')} {item.get('path', '')}".strip(), "project": item.get("project", ""), "path": item.get("file", "")}
            ref["summary"] = _summarize_ref(ref)
            refs.append(ref)
    for idx, item in enumerate(related_mq[:4], start=1):
        if item.get("topic"):
            ref = {"ref_id": f"src:mq:{idx}", "type": "mq", "name": item.get("topic", ""), "project": item.get("project", ""), "path": item.get("file", "")}
            ref["summary"] = _summarize_ref(ref)
            refs.append(ref)
    for idx, item in enumerate(related_cases[-3:], start=1):
        if item.get("task"):
            ref = {"ref_id": f"src:case:{idx}", "type": "case", "task": item.get("task", ""), "created_at": item.get("created_at", "")}
            ref["summary"] = _summarize_ref(ref)
            refs.append(ref)
    return refs


def _suggest_risk_points(summary: Dict[str, Any], events: List[Dict[str, Any]]) -> List[str]:
    text = json.dumps(summary, ensure_ascii=False).lower()
    for event in events:
        text += " " + json.dumps(_event_payload(event), ensure_ascii=False).lower()
    points: List[str] = []
    if any(token in text for token in ["feign", "endpoint", "controller"]):
        points.append("Feign/API 契约兼容性")
    if any(token in text for token in ["kafka", "rocketmq", "topic", "consumer"]):
        points.append("MQ 消息兼容与消费幂等")
    if any(token in text for token in ["config", "bootstrap", "application.yml", "nacos"]):
        points.append("配置键变更与环境一致性")
    if any(token in text for token in ["dto", "field", "request", "response"]):
        points.append("DTO 字段变更兼容性")
    if not points:
        points.append("跨服务影响面复核")
    return points


def _suggest_resume_context(
    intent: str,
    related_sessions: List[Dict[str, Any]],
    related_cases: List[Dict[str, Any]],
    entrypoints: List[Dict[str, Any]],
) -> List[str]:
    hints = [f"当前意图：{intent}"]
    if related_sessions:
        latest = related_sessions[0]
        hints.append(f"最近相关会话：{latest.get('summary') or latest.get('intent')}")
    if related_cases:
        latest_case = related_cases[-1]
        hints.append(f"最近相关经验：{latest_case.get('task')}")
    if entrypoints:
        top = entrypoints[0].get("node", {})
        if top.get("name"):
            hints.append(f"优先入口：{top.get('type', 'Node')} {top.get('name')}")
    return hints


def _build_sniff_auto_sync_recommendation(
    store: WorkspaceStore | None,
    task_resolution: Dict[str, Any] | None = None,
    risk_level: str = "low",
    auto_sync_mode: str = "balanced",
) -> Dict[str, Any]:
    # Support calling without store (e.g. from tests with just task_resolution, risk_level)
    if not isinstance(store, WorkspaceStore):
        # Called as (task_resolution, risk_level, auto_sync_mode=...)
        if isinstance(store, dict):
            risk_level = task_resolution if isinstance(task_resolution, str) else risk_level
            task_resolution = store
        store = None
    if task_resolution is None:
        task_resolution = {}
    if store is not None:
        policy = _load_auto_sync_rules(store)
    else:
        policy = dict(DEFAULT_AUTO_SYNC_RULES.get("default", {}))
    aliases = policy.get("mode_aliases", {}) or {}
    raw_mode = (auto_sync_mode or "balanced").strip().lower()
    mode = str(aliases.get(raw_mode, raw_mode) or "balanced")
    modes = policy.get("modes", {}) or {}
    if mode not in modes:
        mode = "balanced"
    mode_policy = modes.get(mode, {})
    resolved = bool(task_resolution.get("resolved"))
    task_id = str(task_resolution.get("task_id", "") or "")
    score = int(task_resolution.get("score", 0) or 0)
    score_threshold = int(task_resolution.get("score_threshold", 3) or 3)
    candidates = task_resolution.get("candidates", []) or []
    recommendation = {
        "recommended": False,
        "confidence": "low",
        "task_id": task_id if resolved else "",
        "score": score,
        "score_threshold": score_threshold,
        "reason": "",
        "mode": mode,
        "fallback": str(mode_policy.get("fallback", "未满足自动同步条件时，建议先人工确认 task_candidates 再同步。")),
    }
    if not resolved or not task_id:
        recommendation["reason"] = "未命中明确任务空间，建议先人工确认候选任务。"
        return recommendation
    delta = score - score_threshold
    allowed_risks = {str(item) for item in mode_policy.get("allowed_risk_levels", [])}
    min_delta = int(mode_policy.get("min_delta", 0) or 0)
    if delta >= 2:
        recommendation["recommended"] = True
        recommendation["confidence"] = "high"
        recommendation["reason"] = "匹配分数明显高于阈值，可自动同步到已命中任务空间。"
        return recommendation
    if delta >= min_delta and risk_level in allowed_risks:
        recommendation["recommended"] = True
        recommendation["confidence"] = "high" if mode == "strict" else "medium"
        recommendation["reason"] = f"{mode} 模式命中 auto-sync-rules 条件，建议自动同步。"
        return recommendation
    recommendation["confidence"] = "medium" if delta >= 0 else "low"
    if risk_level == "high":
        recommendation["reason"] = "当前风险等级较高，建议先人工确认再同步。"
    else:
        recommendation["reason"] = "匹配分数接近阈值，建议优先确认候选任务。"
    if candidates:
        recommendation["fallback"] = "可优先检查 task_candidates[0] 的 match_reasons，再决定是否同步。"
    return recommendation


def _best_match(matches: List[Dict[str, Any]], query: str = "") -> Dict[str, Any]:
    q = (query or "").lower()

    def key(item: Dict[str, Any]):
        name = (item.get("name") or "").lower()
        exact = 0 if name == q or name.endswith("." + q) else 1
        return (exact, _node_type_priority(item.get("type")), len(item.get("id", "")))

    return sorted(matches, key=key)[0]


def _node_type_priority(node_type: str = "") -> int:
    priority = {
        "Class": 0, "FeignClient": 1, "FeignMethod": 2, "Method": 3,
        "Field": 4, "Endpoint": 5, "MQTopic": 6, "MQConsumer": 7,
        "ConfigKey": 8, "File": 20,
    }
    return priority.get(node_type, 10)


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _filter_call_edges(edges: List[Dict[str, Any]], direction: str) -> List[Dict[str, Any]]:
    preferred = {
        "CALLS_METHOD", "CALLS_SERVICE", "IMPLEMENTS_FEIGN", "HANDLES_ENDPOINT",
        "CONSUMES_TOPIC", "READS_FIELD", "READS_CONFIG", "INJECTS_BEAN", "IMPORTS",
    }
    filtered = [item for item in edges if item.get("type") in preferred]
    filtered.sort(
        key=lambda item: (
            -float(item.get("confidence", 0.0)),
            int(item.get("depth", 99)),
            item.get("type", ""),
        )
    )
    return filtered


def _build_progressive_levels(summary: Dict[str, Any], evidence: Dict[str, Any], detail: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "level": "summary-evidence-detail",
        "summary": summary,
        "evidence": evidence,
        "detail": detail,
    }


def _unknown_static_analysis_risks() -> List[str]:
    return [
        "反射、动态代理、AOP 切面、运行时生成调用链未做精确解析",
        "MyBatis XML / SQL 字段引用当前只做轻量级索引，未做完整 SQL 语义分析",
        "远程 Nacos 配置未默认拉取；只分析本地 application/bootstrap 配置",
        "泛型、重载、继承分派和条件 Bean 的类型解析仍可能存在保守估计",
    ]


def _impact_checklist(node: Dict[str, Any], risk_level: str) -> List[str]:
    base = ["确认上游调用方", "确认下游实现方", "确认是否需要联调或回放历史消息"]
    if node["type"] in {"FeignClient", "FeignMethod", "DTO"}:
        base += ["公共契约变更必须检查所有消费者", "字段删除/改义必须保留兼容周期"]
    if node["type"] in {"MQTopic", "MQConsumer"}:
        base += ["检查重复消费幂等", "检查失败重试/死信/补偿", "检查历史消息反序列化兼容"]
    if risk_level == "high":
        base += ["建议生成变更影响报告并在 PR 中附上"]
    return base


def _resolve_memory_ref(store: WorkspaceStore, ref_id: str) -> Dict[str, Any] | None:
    from ..write_receipts import WRITE_RECEIPTS_FILE

    if not ref_id:
        return None
    rows = store.read_jsonl(SESSION_EVENTS_FILE, limit=5000)
    if ref_id.startswith("ev:") or ref_id.startswith("src:"):
        parts = ref_id.split(":")
        if len(parts) >= 4:
            _, session_id, event_type, ordinal_text = parts[:4]
            try:
                ordinal = int(ordinal_text)
            except ValueError:
                ordinal = 0
            filtered = [
                event for event in rows
                if str(event.get("session_id", "") or "") == session_id
                and str(event.get("event_type", "") or "") == event_type
            ]
            if ordinal > 0 and ordinal <= len(filtered):
                event = filtered[ordinal - 1]
                payload = _event_payload(event)
                raw = {"event": event, "payload": payload}
                return {"kind": "session_event", "summary": _summarize_ref({**payload, "event_type": event.get("event_type", ""), "payload_ref": event.get("payload_ref", "")}), "raw": raw}
    for event in rows:
        payload = _event_payload(event)
        raw = {"event": event, "payload": payload}
        if ref_id == str(event.get("payload_ref", "") or ""):
            return {"kind": "payload_ref", "summary": str(event.get("payload_ref", "")), "raw": raw}
    receipt_rows = store.read_jsonl(WRITE_RECEIPTS_FILE, limit=5000)
    for row in receipt_rows:
        if ref_id in {row.get("receipt_id", ""), row.get("receipt_ref", "")}:
            return {"kind": "write_receipt", "summary": row.get("summary", ""), "raw": row}
    if ref_id.startswith("memory/refs/") or ref_id.startswith("refs/"):
        raw = store.read_memory_ref_json(ref_id, default=None)
        if raw is not None:
            return {"kind": "payload_ref", "summary": str(ref_id), "raw": raw}
    return None


def _case_risk_level(case: Dict[str, Any]) -> str:
    return _case_risk_profile(case)["risk_level"]


def _case_risk_profile(case: Dict[str, Any]) -> Dict[str, Any]:
    risk_points = case.get("risk_points", [])
    refs = case.get("evidence_refs", []) if isinstance(case.get("evidence_refs", []), list) else []
    score = 0
    matched_signals: List[str] = []
    point_text = json.dumps(risk_points, ensure_ascii=False).lower()
    for token, weight, label in [
        ("contract", 3, "risk_points:contract"),
        ("feign", 3, "risk_points:feign"),
        ("mq", 3, "risk_points:mq"),
        ("topic", 2, "risk_points:topic"),
        ("dto", 2, "risk_points:dto"),
        ("config", 2, "risk_points:config"),
        ("兼容", 3, "risk_points:compatibility"),
        ("breaking", 3, "risk_points:breaking"),
    ]:
        if token in point_text:
            score += weight
            matched_signals.append(label)
    high_ref_types = {"contract", "mq", "dto", "config"}
    medium_ref_types = {"impact", "cross_service", "symbol"}
    counted_ref_types: Dict[str, int] = {}
    for ref in refs:
        ref_type = _classify_case_evidence_ref(ref)
        counted_ref_types[ref_type] = counted_ref_types.get(ref_type, 0) + 1
        if ref_type in high_ref_types:
            score += 2
            matched_signals.append(f"evidence:{ref_type}")
        elif ref_type in medium_ref_types:
            score += 1
            matched_signals.append(f"evidence:{ref_type}")
    if score >= 5:
        level = "high"
    elif score >= 2:
        level = "medium"
    else:
        level = "low"
    return {
        "risk_level": level,
        "score": score,
        "signals": matched_signals[:20],
        "evidence_type_counts": counted_ref_types,
    }


def _classify_case_evidence_ref(ref: Dict[str, Any]) -> str:
    haystack = json.dumps(ref, ensure_ascii=False).lower()
    tool_name = str(ref.get("tool_name", "")).lower()
    event_type = str(ref.get("event_type", "")).lower()
    if any(mark in tool_name for mark in ["check_contract", "contract"]) or any(mark in haystack for mark in ["feign", "contract", "endpoint"]):
        return "contract"
    if any(mark in haystack for mark in ["kafka", "rocketmq", "mq", "topic", "consumer"]):
        return "mq"
    if any(mark in haystack for mark in ["dto", "request", "response", "field"]):
        return "dto"
    if any(mark in haystack for mark in ["application.yml", "bootstrap.yml", "config", "nacos"]):
        return "config"
    if any(mark in tool_name for mark in ["impact", "plan_change"]):
        return "impact"
    if "tool_call" in event_type and any(mark in haystack for mark in ["service", "client"]):
        return "cross_service"
    if any(mark in tool_name for mark in ["symbol", "query", "context", "callers", "callees"]):
        return "symbol"
    return "other"


def _merge_artifact_section(existing: str, section_title: str, body: str) -> str:
    marker = f"## {section_title}"
    if marker in existing:
        prefix = existing.split(marker, 1)[0].rstrip()
        return f"{prefix}\n\n{marker}\n\n{body.strip()}\n"
    suffix = f"\n\n{marker}\n\n{body.strip()}\n"
    return existing.rstrip() + suffix if existing.strip() else f"{marker}\n\n{body.strip()}\n"


def _sniff_risk_level(
    intent: str,
    matched_files: List[Dict[str, Any]],
    related_feigns: List[Dict[str, Any]],
    related_apis: List[Dict[str, Any]],
    related_mq: List[Dict[str, Any]],
    rules: List[Dict[str, Any]],
) -> str:
    text = intent.lower()
    paths = " ".join(item.get("path", "").lower() for item in matched_files)
    must_rules = sum(1 for item in rules if item.get("severity") == "must")
    if related_feigns or related_apis or related_mq:
        return "high"
    if any(token in text for token in ["dto", "feign", "mq", "message", "contract", "topic", "config"]):
        return "high"
    if any(token in paths for token in ["feign", "controller", "consumer", "message", "dto", "config"]):
        return "high"
    if must_rules >= 2:
        return "medium"
    return "low"


def tokenize(text: str) -> List[str]:
    from ..text_utils import base_tokenize

    words = base_tokenize(text)
    for token in ["kafka", "rocketmq", "feign", "controller", "oldpubtime", "newpubtime", "es", "mongo", "redis", "nacos"]:
        if token in text.lower() and token not in words:
            words.append(token)
    return sorted(set(words))


def rank_files(file_index: List[Dict], symbols: List[Dict], keywords: List[str]) -> List[Dict]:
    symbol_by_file = {s["file"]: s for s in symbols}
    ranked = []
    for item in file_index:
        haystack = (item.get("path", "") + " " + json.dumps(symbol_by_file.get(item.get("path"), {}), ensure_ascii=False)).lower()
        score = sum(1 for k in keywords if k in haystack)
        path = item.get("path", "")
        if any(mark in path for mark in ["Consumer", "Listener", "Feign", "Controller", "Service", "Repository", "Mapper"]):
            score += 1
        if score > 0:
            ranked.append({**item, "score": score, "symbols": symbol_by_file.get(path, {})})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked