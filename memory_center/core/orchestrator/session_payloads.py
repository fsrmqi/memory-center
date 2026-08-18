"""会话事件载荷的内联/压缩/ref 摘要构建。

从 shared.py 按独立职责拆出(ADR-0002):L0 事件 payload 的压缩与证据 ref 构建。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore


def _summarize_ref(ref: dict[str, Any]) -> str:
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


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _prepare_session_event_payload(
    store: WorkspaceStore,
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str, int]:
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


def _compact_session_payload(payload: dict[str, Any]) -> dict[str, Any]:
    # Try tool-specific compressor first; fall back to generic extraction
    tool_name = str(payload.get("tool_name", "") or "").lower()
    compressed = _compact_tool_payload(payload, tool_name)
    if compressed:
        return compressed
    # Generic fallback: extract preferred keys
    compact: dict[str, Any] = {}
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


def _compact_tool_payload(payload: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
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


def _compact_git_stats(payload: dict[str, Any]) -> dict[str, Any]:
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


def _compact_test_result(payload: dict[str, Any]) -> dict[str, Any]:
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


def _compact_search_result(payload: dict[str, Any]) -> dict[str, Any]:
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
        files: dict[str, int] = {}
        for m in matches[:20]:
            f = str(m.get("file", m.get("path", "")) or "")[:60]
            if f:
                files[f] = files.get(f, 0) + 1
        if files:
            compact["files_with_matches"] = dict(sorted(files.items(), key=lambda kv: -kv[1])[:5])
    return compact


def _build_case_evidence_refs(events: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
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


def _build_event_source_refs(events: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
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


def _classify_case_evidence_ref(ref: dict[str, Any]) -> str:
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


EVENT_PAYLOAD_INLINE_LIMIT = 4000
