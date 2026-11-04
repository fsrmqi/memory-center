"""Bounded, additive knowledge-state envelope for public read APIs."""
from __future__ import annotations

from typing import Any

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.storage.workspace import WorkspaceStore


def attach_knowledge_state(
    store: WorkspaceStore,
    payload: dict[str, Any],
    *,
    query: str = "",
    project: str = "",
    mode: str = "query",
) -> dict[str, Any]:
    """Add a non-breaking explanation for the current knowledge result."""
    if isinstance(payload.get("knowledge_state"), dict):
        return payload
    index = store.read_json_prefer_backend("index-summary.json", {}) or {}
    control = index_control_status(store)
    matches = payload.get("matches", []) or payload.get("results", []) or []
    assertion = payload.get("assertion_summary", {}) or {}
    stale = int(assertion.get("stale", 0) or 0) > 0 or bool(payload.get("index_freshness", {}).get("index_stale"))
    indexed_files = int(index.get("files", 0) or 0)
    if payload.get("index_scope_unavailable"):
        state, reason = "NOT_INDEXED", "requested_service_shard_not_published"
    elif matches:
        state, reason = "FOUND", "matched_indexed_evidence"
    elif not indexed_files:
        state, reason = "NOT_INDEXED", "no_published_index_for_workspace"
    elif stale:
        state, reason = "STALE", "no_current_match_and_related_index_is_stale"
    elif str(control.get("status", "")) == "failed":
        state, reason = "UNKNOWN", "latest_index_generation_failed"
    else:
        state, reason = "NOT_FOUND", "not_found_within_checked_scope"
    next_action = {
        "NOT_INDEXED": "运行 reindex 生成当前范围索引",
        "STALE": "刷新关联索引后再次查询",
        "UNKNOWN": "检查 runtime-inspect 的索引诊断",
        "NOT_FOUND": "缩小或细化查询范围",
        "FOUND": "按需展开证据",
        "REJECTED": "查看否定决策",
    }[state]
    payload["knowledge_state"] = {
        "state": state,
        "absence_reason": "" if state == "FOUND" else reason,
        "scope_checked": {
            "query": query[:240],
            "project": project,
            "paths": [],
            "index_generation": str(control.get("active_generation", "") or ""),
            "query_mode": mode,
        },
        "next_action": next_action,
    }
    return payload
