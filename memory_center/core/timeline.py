from __future__ import annotations

from typing import Any, Dict, List

from .schemas import with_schema
from .store import WorkspaceStore
from .write_receipts import WRITE_RECEIPTS_FILE

SESSION_EVENTS_FILE = "session-events.jsonl"
HANDOFF_HISTORY_FILE = "handoff-history.jsonl"


def timeline_query(
    workspace_file: str,
    *,
    task_id: str = "",
    session_id: str = "",
    kinds: List[str] | None = None,
    limit: int = 100,
) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    wanted = set(kinds or ["session_event", "write_receipt", "handoff"])
    items: List[Dict[str, Any]] = []

    if "session_event" in wanted:
        for row in store.read_jsonl(SESSION_EVENTS_FILE, limit=5000):
            row_session = str(row.get("session_id", "") or "")
            if session_id and row_session != session_id:
                continue
            items.append(_map_session_event(row))

    if "write_receipt" in wanted:
        for row in store.read_jsonl(WRITE_RECEIPTS_FILE, limit=5000):
            row_task = str(row.get("task_id", "") or "")
            row_session = str(row.get("session_id", "") or row.get("source_session_id", "") or "")
            if task_id and row_task != task_id:
                continue
            if session_id and row_session != session_id:
                continue
            items.append(_map_write_receipt(row))

    if "handoff" in wanted:
        for row in store.read_jsonl(HANDOFF_HISTORY_FILE, limit=5000):
            row_task = str(row.get("task_id", "") or "")
            row_session = str(row.get("session_id", "") or "")
            if task_id and row_task != task_id:
                continue
            if session_id and row_session != session_id:
                continue
            items.append(_map_handoff(row))

    items.sort(key=lambda item: (str(item.get("created_at", "") or ""), str(item.get("kind", "") or ""), str(item.get("target", "") or "")))
    trimmed = items[-limit:]
    return with_schema(
        "timeline_result",
        {
            "timeline": trimmed,
            "summary": {
                "total": len(trimmed),
                "kinds": sorted({item.get("kind", "") for item in trimmed if item.get("kind")}),
            },
        },
    )


def _map_session_event(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}
    return with_schema(
        "timeline_item",
        {
        "kind": "session_event",
        "created_at": row.get("created_at", ""),
        "task_id": "",
        "session_id": row.get("session_id", ""),
        "layer": "L0_session_events",
        "action": row.get("event_type", ""),
        "scope": "memory",
        "target": payload.get("tool_name", "") or payload.get("query", "") or payload.get("target", "") or row.get("event_type", ""),
        "payload_ref": row.get("payload_ref", ""),
        "raw": row,
        },
    )


def _map_write_receipt(row: Dict[str, Any]) -> Dict[str, Any]:
    return with_schema(
        "timeline_item",
        {
        "kind": "write_receipt",
        "created_at": row.get("created_at", ""),
        "task_id": row.get("task_id", ""),
        "session_id": row.get("session_id", "") or row.get("source_session_id", ""),
        "layer": row.get("layer", ""),
        "action": row.get("action", ""),
        "scope": row.get("scope", ""),
        "target": row.get("target", ""),
        "receipt_ref": row.get("receipt_ref", ""),
        "raw": row,
        },
    )


def _map_handoff(row: Dict[str, Any]) -> Dict[str, Any]:
    return with_schema(
        "timeline_item",
        {
        "kind": "handoff",
        "created_at": row.get("created_at", ""),
        "task_id": row.get("task_id", ""),
        "session_id": row.get("session_id", ""),
        "layer": "",
        "action": "handoff",
        "scope": "memory",
        "target": row.get("normalized_model", "") or row.get("target_model", ""),
        "receipt_ref": "memory/handoff-history.jsonl",
        "raw": row,
        },
    )
