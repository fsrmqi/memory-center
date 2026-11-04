"""宿主交互历史、会话关联与效果摘要。"""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

MCP_INVOCATIONS_FILE = "mcp-invocations.jsonl"
HOST_INTERACTIONS_FILE = "host-interactions.jsonl"
ACTIVE_SESSION_BINDINGS_FILE = "active-session-bindings.json"
EFFECT_SUMMARY_FILE = "mcp-effect-summary.json"
HISTORY_RETENTION_STATE_FILE = "interaction-history-retention.json"
HOST_INTERACTION_RETENTION_DAYS = 30
SESSION_EVENT_RETENTION_DAYS = 90
SESSION_SUMMARY_RETENTION_DAYS = 365
HISTORY_MAX_RECORDS = 100_000
HISTORY_PRUNE_INTERVAL_SECONDS = 300
_TEXT_LIMIT = 160
_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization)\b\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_ABSOLUTE_PATH = re.compile(r"(?<!\w)(?:/Users/|/home/|/private/|[A-Za-z]:\\\\)[^\s,;]+")
_ALLOWED_HOST_FIELDS = {
    "action", "event_type", "mode", "outcome", "query", "status", "target", "title", "tool_name",
    "trace_id", "thread_id", "turn_id", "duration_ms", "session_id", "task_id", "source",
}


def redact_interaction_text(value: Any, *, limit: int = _TEXT_LIMIT) -> str:
    """将敏感键值和绝对路径替换为稳定但不可逆的标记。"""
    text = " ".join(str(value or "").split())
    text = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _ABSOLUTE_PATH.sub(_path_marker, text)
    return text[:limit]


def sanitize_interaction_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """只保留可用于验证的白名单元数据。"""
    safe: dict[str, Any] = {}
    for key in _ALLOWED_HOST_FIELDS:
        value = payload.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "duration_ms" and isinstance(value, (int, float)):
            safe[key] = round(float(value), 2)
        elif isinstance(value, (str, int, float, bool)):
            safe[key] = redact_interaction_text(value)
    return safe


def resolve_active_session(workspace_file: str, thread_id: str) -> str:
    """按宿主线程恢复活跃 session，未绑定时返回空字符串。"""
    if not thread_id:
        return ""
    bindings = WorkspaceStore(workspace_file).read_json_prefer_backend(ACTIVE_SESSION_BINDINGS_FILE, {})
    entry = bindings.get(thread_id, {}) if isinstance(bindings, dict) else {}
    return str(entry.get("session_id", "") or "") if isinstance(entry, dict) else ""


def bind_active_session(workspace_file: str, thread_id: str, session_id: str, trace_id: str = "") -> None:
    """持久化 thread 到 session 的轻量绑定，支持 MCP 进程重启后续接。"""
    if not thread_id or not session_id:
        return
    store = WorkspaceStore(workspace_file)
    bindings = store.read_json_prefer_backend(ACTIVE_SESSION_BINDINGS_FILE, {})
    bindings = dict(bindings) if isinstance(bindings, dict) else {}
    bindings[thread_id] = {
        "session_id": session_id,
        "trace_id": trace_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    store.write_json(ACTIVE_SESSION_BINDINGS_FILE, bindings)


def unbind_active_session(workspace_file: str, thread_id: str, session_id: str = "") -> None:
    """只移除匹配的活跃绑定，避免结束旧会话误删新绑定。"""
    if not thread_id:
        return
    store = WorkspaceStore(workspace_file)
    bindings = store.read_json_prefer_backend(ACTIVE_SESSION_BINDINGS_FILE, {})
    if not isinstance(bindings, dict):
        return
    entry = bindings.get(thread_id, {})
    if session_id and isinstance(entry, dict) and entry.get("session_id") != session_id:
        return
    if thread_id in bindings:
        bindings.pop(thread_id)
        store.write_json(ACTIVE_SESSION_BINDINGS_FILE, bindings)


def record_host_interaction(
    workspace_file: str,
    payload: dict[str, Any],
    *,
    session_id: str = "",
    task_id: str = "",
) -> dict[str, Any]:
    """记录宿主对话轮次或非 MCP 工具事件，不持久化原始正文。"""
    store = WorkspaceStore(workspace_file)
    fields = sanitize_interaction_fields(payload)
    resolved_session = session_id or str(fields.get("session_id", "") or "")
    event = {
        "event_type": "host_interaction",
        "source": str(fields.get("source", "host") or "host"),
        "session_id": resolved_session,
        "task_id": task_id or str(fields.get("task_id", "") or ""),
        "trace_id": str(fields.get("trace_id", "") or ""),
        "thread_id": str(fields.get("thread_id", "") or ""),
        "turn_id": str(fields.get("turn_id", "") or ""),
        "interaction": fields,
    }
    store.append_jsonl(HOST_INTERACTIONS_FILE, event)
    maintain_history_retention(workspace_file)
    if event["thread_id"] and resolved_session:
        bind_active_session(workspace_file, event["thread_id"], resolved_session, event["trace_id"])
    return {"recorded": True, "event": event}


def build_effect_summary(workspace_file: str, *, limit: int = 100_000) -> dict[str, Any]:
    """汇总调用可靠性、会话关联和已关闭会话的结果质量。"""
    store = WorkspaceStore(workspace_file)
    calls = store.read_jsonl_via_backend(MCP_INVOCATIONS_FILE, limit=max(1, limit))
    host_events = store.read_jsonl_via_backend(HOST_INTERACTIONS_FILE, limit=max(1, limit))
    sessions = store.read_jsonl_via_backend("session-summaries.jsonl", limit=max(1, limit))
    durations = sorted(float(item.get("duration_ms", 0) or 0) for item in calls if item.get("duration_ms") is not None)
    status_counts = _count_values(calls, "status")
    tool_counts = _count_values(calls, "tool_name")
    linked_calls = sum(1 for item in calls if item.get("session_id"))
    outcome_counts = _count_values(sessions, "outcome")
    successful_outcomes = sum(count for outcome, count in outcome_counts.items() if _is_positive_outcome(outcome))
    closed_sessions = len(sessions)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "retention": {"days": 30, "max_records": 100_000},
        "calls": {
            "total": len(calls),
            "status_counts": status_counts,
            "tool_counts": tool_counts,
            "session_link_rate": round(linked_calls / len(calls), 3) if calls else 0.0,
            "latency_ms": _latency_summary(durations),
        },
        "host_interactions": {"total": len(host_events), "session_link_rate": _linked_rate(host_events)},
        "outcomes": {
            "closed_sessions": closed_sessions,
            "outcome_counts": outcome_counts,
            "verified_success_rate": round(successful_outcomes / closed_sessions, 3) if closed_sessions else 0.0,
        },
    }


def refresh_effect_summary(workspace_file: str) -> dict[str, Any]:
    """刷新可快速读取的效果摘要快照。"""
    maintain_history_retention(workspace_file)
    summary = build_effect_summary(workspace_file)
    WorkspaceStore(workspace_file).write_json(EFFECT_SUMMARY_FILE, summary)
    return summary


def maintain_history_retention(workspace_file: str, *, force: bool = False) -> dict[str, Any]:
    """以低频批量方式维护宿主和 session 历史，避免每次交互全量扫描。"""
    store = WorkspaceStore(workspace_file)
    now = time.time()
    state = store.read_json_prefer_backend(HISTORY_RETENTION_STATE_FILE, {})
    last = float(state.get("last_pruned_epoch", 0) or 0) if isinstance(state, dict) else 0.0
    if not force and now - last < HISTORY_PRUNE_INTERVAL_SECONDS:
        return {"pruned": False}
    current = datetime.now(timezone.utc)
    summary = {
        "host_interactions": store.prune_jsonl(
            HOST_INTERACTIONS_FILE,
            created_before=current - timedelta(days=HOST_INTERACTION_RETENTION_DAYS),
            max_records=HISTORY_MAX_RECORDS,
        ),
        "session_events": store.prune_jsonl(
            "session-events.jsonl",
            created_before=current - timedelta(days=SESSION_EVENT_RETENTION_DAYS),
            max_records=HISTORY_MAX_RECORDS,
        ),
        "session_summaries": store.prune_jsonl(
            "session-summaries.jsonl",
            created_before=current - timedelta(days=SESSION_SUMMARY_RETENTION_DAYS),
            max_records=HISTORY_MAX_RECORDS,
        ),
    }
    store.write_json(HISTORY_RETENTION_STATE_FILE, {"last_pruned_epoch": now, "updated_at": current.isoformat()})
    return {"pruned": True, "summary": summary}


def _path_marker(match: re.Match[str]) -> str:
    digest = hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:12]
    return f"<PATH:{digest}>"


def _count_values(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "") or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0}
    p95_index = min(len(values) - 1, max(0, int(len(values) * 0.95) - 1))
    return {"p50": round(float(median(values)), 2), "p95": round(values[p95_index], 2), "max": round(values[-1], 2)}


def _linked_rate(items: list[dict[str, Any]]) -> float:
    return round(sum(1 for item in items if item.get("session_id")) / len(items), 3) if items else 0.0


def _is_positive_outcome(outcome: str) -> bool:
    normalized = outcome.lower()
    return normalized in {"confirmed", "resolved", "success", "passed", "完成", "已解决", "通过"}
