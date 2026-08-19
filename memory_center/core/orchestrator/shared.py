from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from memory_center.core.governance.rules import (
    DEFAULT_AUTO_SYNC_RULES,
)
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

from .rules import _load_auto_sync_rules
from .session_payloads import _classify_case_evidence_ref, _event_payload, _summarize_ref

SESSION_EVENTS_FILE = "session-events.jsonl"
SESSION_SUMMARIES_FILE = "session-summaries.jsonl"
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


def summarize_chain_edges(edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the shared compact representation of graph edges."""
    items: list[dict[str, Any]] = []
    type_counts: dict[str, int] = {}
    for edge in edges:
        edge_type = str(edge.get("type", "") or "")
        type_counts[edge_type] = type_counts.get(edge_type, 0) + 1
        source = edge.get("source", {}) or {}
        target = edge.get("target", {}) or {}

        def endpoint(node: dict[str, Any]) -> str:
            name = str(node.get("name", "") or "?")
            line = int(node.get("line", 0) or 0)
            return f"{name}:{line}" if line > 0 else name

        items.append(
            {
                "text": f"{endpoint(source)} --{edge_type}--> {endpoint(target)}",
                "type": edge_type,
                "depth": int(edge.get("depth", 0) or 0),
                "source": {
                    "name": source.get("name", ""),
                    "line": int(source.get("line", 0) or 0),
                    "project": source.get("project", ""),
                },
                "target": {
                    "name": target.get("name", ""),
                    "line": int(target.get("line", 0) or 0),
                    "project": target.get("project", ""),
                },
            }
        )
    return {
        "items": items,
        "total_edges": len(edges),
        "depth_reached": max((int(edge.get("depth", 0) or 0) for edge in edges), default=0),
        "type_counts": type_counts,
    }


def _normalize_budget(budget: str) -> str:
    value = (budget or "medium").strip().lower()
    return value if value in {"tiny", "small", "medium", "large"} else "medium"


MODEL_BUDGET_PROFILES: dict[str, dict[str, int]] = {
    "codex": {"services": 3, "files": 4, "refs": 4, "steps": 3, "tasks": 3, "events": 3, "findings": 3},
    "claude-code": {"services": 5, "files": 5, "refs": 5, "steps": 4, "tasks": 5, "events": 4, "findings": 4},
    "gemini": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "deepseek": {"services": 3, "files": 3, "refs": 3, "steps": 2, "tasks": 3, "events": 2, "findings": 2},
    "cursor-agent": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "glm": {"services": 3, "files": 3, "refs": 3, "steps": 2, "tasks": 3, "events": 2, "findings": 2},
    "qwen": {"services": 4, "files": 4, "refs": 4, "steps": 3, "tasks": 4, "events": 3, "findings": 3},
    "generic-mcp-agent": {"services": 5, "files": 5, "refs": 5, "steps": 4, "tasks": 5, "events": 4, "findings": 4},
}


def _budget_limits(budget: str, model: str = "") -> dict[str, int]:
    normalized = _normalize_budget(budget)
    model_profile = MODEL_BUDGET_PROFILES.get(_normalize_model_name(model or ""), MODEL_BUDGET_PROFILES["generic-mcp-agent"])
    if normalized == "tiny":
        return {k: 1 for k in model_profile}
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


def _trim_summary(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _render_ref_label(ref: dict[str, Any]) -> str:
    return (
        str(ref.get("summary", "") or "")
        or str(ref.get("name", "") or ref.get("task", "") or ref.get("query", "") or ref.get("target", "") or ref.get("file_path", "") or ref.get("path", "") or ref.get("payload_ref", "") or ref.get("ref_id", "") or "ref")
    )


def _build_sniff_source_refs(
    matched_files: list[dict[str, Any]],
    related_feigns: list[dict[str, Any]],
    related_apis: list[dict[str, Any]],
    related_mq: list[dict[str, Any]],
    related_cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
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


def _suggest_risk_points(summary: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    text = json.dumps(summary, ensure_ascii=False).lower()
    for event in events:
        text += " " + json.dumps(_event_payload(event), ensure_ascii=False).lower()
    points: list[str] = []
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
    related_sessions: list[dict[str, Any]],
    related_cases: list[dict[str, Any]],
    entrypoints: list[dict[str, Any]],
) -> list[str]:
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
    task_resolution: dict[str, Any] | None = None,
    risk_level: str = "low",
    auto_sync_mode: str = "balanced",
) -> dict[str, Any]:
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


_INBOUND_PREFERRED = {"CALLS_METHOD", "CALLS_SERVICE", "IMPLEMENTS_FEIGN", "CONSUMES_TOPIC", "READS_FIELD", "READS_CONFIG", "INJECTS_BEAN", "IMPORTS", "DISPATCHES_TO"}
_OUTBOUND_PREFERRED = {"HANDLES_ENDPOINT", "PRODUCES_TOPIC", "CALLS_METHOD", "CALLS_SERVICE", "IMPLEMENTS_FEIGN", "INJECTS_BEAN", "DISPATCHES_TO"}
_ALL_PREFERRED = _INBOUND_PREFERRED | _OUTBOUND_PREFERRED
_UPSTREAM_EDGE_PRIORITY = {
    "INJECTS_BEAN": 0,
    "CALLS_METHOD": 1,
    "CALLS_SERVICE": 2,
    "IMPLEMENTS_FEIGN": 3,
    "DISPATCHES_TO": 3,
    "READS_FIELD": 4,
    "READS_CONFIG": 5,
    "CONSUMES_TOPIC": 6,
    "IMPORTS": 9,
}
_DOWNSTREAM_EDGE_PRIORITY = {
    "HANDLES_ENDPOINT": 0,
    "CALLS_METHOD": 1,
    "CALLS_SERVICE": 2,
    "IMPLEMENTS_FEIGN": 3,
    "DISPATCHES_TO": 3,
    "PRODUCES_TOPIC": 4,
    "INJECTS_BEAN": 5,
    "IMPORTS": 9,
}

_NOISE_METHODS = {
    "getId", "setId", "getName", "setName", "getType", "setType",
    "getCode", "setCode", "getData", "setData", "getUrl", "setUrl",
    "getStatus", "setStatus", "getValue", "setValue", "getKey", "setKey",
    "getTitle", "setTitle", "getContent", "setContent", "getMsg", "setMsg",
    "getParentUrl", "setParentUrl", "getRemark", "setRemark",
    "ok", "of", "empty", "stream", "map", "filter", "collect",
}


def preferred_edge_types(direction: str) -> list[str] | None:
    if direction in {"upstream", "incoming"}:
        return list(_INBOUND_PREFERRED)
    if direction in {"downstream", "outgoing"}:
        return list(_OUTBOUND_PREFERRED)
    return None


def _is_noise_call(edge: dict[str, Any]) -> bool:
    if edge.get("type") != "CALLS_METHOD":
        return False
    name = edge.get("target", {}).get("name", "")
    short = name.split(".")[-1] if "." in name else name
    if short in _NOISE_METHODS:
        return True
    # JavaBean getter/setter/boolean pattern: getFoo, setFoo, isFoo, hasFoo
    # Only match short names (no class prefix) — prefixed names are real calls
    if "." not in name and len(short) > 3:
        if short.startswith(("get", "set")) and len(short) > 3 and short[3:4].isupper():
            return True
        if short.startswith(("is", "has")) and len(short) > 2 and short[2:3].isupper():
            return True
    return False


def _is_redundant_import_edge(edge: dict[str, Any], edges: list[dict[str, Any]]) -> bool:
    if edge.get("type") != "IMPORTS":
        return False
    source = edge.get("source", {}) or {}
    target = edge.get("target", {}) or {}
    source_file = source.get("file_path", "") or source.get("name", "")
    target_file = target.get("file_path", "") or target.get("name", "")
    if not source_file:
        return False
    for other in edges:
        if other is edge or other.get("type") == "IMPORTS":
            continue
        other_source = other.get("source", {}) or {}
        other_target = other.get("target", {}) or {}
        other_source_file = other_source.get("file_path", "") or other_source.get("name", "")
        other_target_file = other_target.get("file_path", "") or other_target.get("name", "")
        same_source = other_source_file == source_file
        same_target = (
            (target_file and other_target_file == target_file)
            or (
                target.get("project", "")
                and target.get("project", "") == other_target.get("project", "")
                and target.get("name", "")
                and target.get("name", "") in {other_target.get("name", ""), other_target_file}
            )
        )
        if same_source and same_target:
            return True
    return False


def _filter_call_edges(edges: list[dict[str, Any]], direction: str) -> list[dict[str, Any]]:
    if direction in {"upstream", "incoming"}:
        edge_types = _INBOUND_PREFERRED
        edge_priority = _UPSTREAM_EDGE_PRIORITY
    elif direction in {"downstream", "outgoing"}:
        edge_types = _OUTBOUND_PREFERRED
        edge_priority = _DOWNSTREAM_EDGE_PRIORITY
    else:
        edge_types = _ALL_PREFERRED
        edge_priority = {}
    filtered = [
        item for item in edges
        if item.get("type") in edge_types
        and not _is_noise_call(item)
        and not _is_redundant_import_edge(item, edges)
    ]
    if any(item.get("type") != "IMPORTS" for item in filtered):
        filtered = [item for item in filtered if item.get("type") != "IMPORTS"]
    filtered.sort(
        key=lambda item: (
            edge_priority.get(item.get("type", ""), 20),
            -float(item.get("confidence", 0.0)),
            int(item.get("depth", 99)),
            item.get("type", ""),
            -(int((item.get("source", {}) or {}).get("line", 0) or 0) > 0),
            -(int((item.get("target", {}) or {}).get("line", 0) or 0) > 0),
        )
    )
    # Deduplicate carefully: resolved Java calls are class-prefixed, so
    # ``InvoiceService.create`` and ``MissingService.create`` are distinct
    # targets. Only bare method names are collapsed against a class-prefixed
    # target with the same short name.
    seen_full_names: set[str] = set()
    seen_prefixed_shorts: set[str] = set()
    bare_by_short: dict[str, dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for item in filtered:
        tgt = item.get("target", {})
        name = tgt.get("name", "")
        short = name.split(".")[-1] if "." in name else name
        has_class = "." in name
        if has_class:
            if name in seen_full_names:
                continue
            seen_full_names.add(name)
            seen_prefixed_shorts.add(short)
            if short in bare_by_short:
                deduped = [d for d in deduped if d is not bare_by_short[short]]
                bare_by_short.pop(short, None)
            deduped.append(item)
        elif short in seen_prefixed_shorts or short in bare_by_short:
            continue
        else:
            bare_by_short[short] = item
            deduped.append(item)
    return deduped


def _build_progressive_levels(summary: dict[str, Any], evidence: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "level": "summary-evidence-detail",
        "summary": summary,
        "evidence": evidence,
        "detail": detail,
    }


def _unknown_static_analysis_risks() -> list[str]:
    return [
        "反射、动态代理、AOP 切面、运行时生成调用链未做精确解析",
        "MyBatis XML / SQL 字段引用当前只做轻量级索引，未做完整 SQL 语义分析",
        "远程 Nacos 配置未默认拉取；只分析本地 application/bootstrap 配置",
        "泛型、重载、继承分派和条件 Bean 的类型解析仍可能存在保守估计",
    ]


def _impact_checklist(node: dict[str, Any], risk_level: str) -> list[str]:
    base = ["确认上游调用方", "确认下游实现方", "确认是否需要联调或回放历史消息"]
    node_type = node.get("type", "")
    if node_type in {"FeignClient", "FeignMethod", "DTO"}:
        base += ["公共契约变更必须检查所有消费者", "字段删除/改义必须保留兼容周期"]
    if node_type in {"MQTopic", "MQConsumer"}:
        base += ["检查重复消费幂等", "检查失败重试/死信/补偿", "检查历史消息反序列化兼容"]
    if risk_level == "high":
        base += ["建议生成变更影响报告并在 PR 中附上"]
    return base


def _resolve_memory_ref(store: WorkspaceStore, ref_id: str) -> dict[str, Any] | None:
    from ..tasks.receipts import WRITE_RECEIPTS_FILE

    if not ref_id:
        return None
    rows = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=5000)
    if ref_id.startswith("ev:") or ref_id.startswith("src:"):
        parts = ref_id.split(":")
        if len(parts) >= 4:
            _, session_id, event_type, ordinal_text = parts[:4]
            try:
                ordinal = int(ordinal_text)
            except ValueError:
                ordinal = 0
            # The ordinal in ref_id is a position within the session+type subset,
            # not a global position. Resolve by filtering to the matching session+type.
            filtered = [
                ev for ev in rows
                if str(ev.get("session_id", "") or "") == session_id
                and str(ev.get("event_type", "") or "") == event_type
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
    receipt_rows = store.read_jsonl_prefer_backend(WRITE_RECEIPTS_FILE, limit=5000)
    for row in receipt_rows:
        if ref_id in {row.get("receipt_id", ""), row.get("receipt_ref", "")}:
            return {"kind": "write_receipt", "summary": row.get("summary", ""), "raw": row}
    if ref_id.startswith("memory/refs/") or ref_id.startswith("refs/"):
        raw = store.read_memory_ref_json(ref_id, default=None)
        if raw is not None:
            return {"kind": "payload_ref", "summary": str(ref_id), "raw": raw}
    return None


def _case_risk_level(case: dict[str, Any]) -> str:
    return _case_risk_profile(case)["risk_level"]


def _case_risk_profile(case: dict[str, Any]) -> dict[str, Any]:
    risk_points = case.get("risk_points", [])
    raw_refs = case.get("evidence_refs", [])
    refs = raw_refs if isinstance(raw_refs, list) else []
    score = 0
    matched_signals: list[str] = []
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
    counted_ref_types: dict[str, int] = {}
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


def _merge_artifact_section(existing: str, section_title: str, body: str) -> str:
    marker = f"## {section_title}"
    replacement = f"{marker}\n\n{body.strip()}\n"
    if not existing.strip():
        return replacement

    lines = existing.splitlines()
    target_start = None
    target_end = None

    for idx, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not match:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        if target_start is None:
            if level == 2 and title == section_title:
                target_start = idx
            continue
        if level <= 2:
            target_end = idx
            break

    if target_start is None:
        return existing.rstrip() + f"\n\n{replacement}"

    if target_end is None:
        target_end = len(lines)

    prefix = "\n".join(lines[:target_start]).rstrip()
    suffix = "\n".join(lines[target_end:]).lstrip()

    parts = []
    if prefix:
        parts.append(prefix)
    parts.append(replacement.rstrip())
    if suffix:
        parts.append(suffix)
    return "\n\n".join(parts).rstrip() + "\n"


def _sniff_risk_level(
    intent: str,
    matched_files: list[dict[str, Any]],
    related_feigns: list[dict[str, Any]],
    related_apis: list[dict[str, Any]],
    related_mq: list[dict[str, Any]],
    rules: list[dict[str, Any]],
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


