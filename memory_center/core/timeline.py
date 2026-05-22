from __future__ import annotations

from typing import Any, Dict, Iterable, List

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
    layer: str = "",
    action: str = "",
    scope: str = "",
    target_contains: str = "",
    limit: int = 100,
) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    wanted = set(kinds or ["session_event", "write_receipt", "handoff"])
    items = collect_timeline_items(
        store,
        task_id=task_id,
        session_id=session_id,
        kinds=wanted,
        layer=layer,
        action=action,
        scope=scope,
        target_contains=target_contains,
    )

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
            "filters": {
                "task_id": task_id,
                "session_id": session_id,
                "kinds": sorted(wanted),
                "layer": layer,
                "action": action,
                "scope": scope,
                "target_contains": target_contains,
                "limit": limit,
            },
        },
    )


def collect_timeline_items(
    store: WorkspaceStore,
    *,
    task_id: str = "",
    session_id: str = "",
    kinds: Iterable[str] | None = None,
    layer: str = "",
    action: str = "",
    scope: str = "",
    target_contains: str = "",
) -> List[Dict[str, Any]]:
    wanted = set(kinds or ["session_event", "write_receipt", "handoff"])
    items: List[Dict[str, Any]] = []

    if "session_event" in wanted:
        for row in store.read_jsonl(SESSION_EVENTS_FILE, limit=5000):
            item = _map_session_event(row)
            if _match_timeline_item(item, task_id=task_id, session_id=session_id, layer=layer, action=action, scope=scope, target_contains=target_contains):
                items.append(item)

    if "write_receipt" in wanted:
        for row in store.read_jsonl(WRITE_RECEIPTS_FILE, limit=5000):
            item = _map_write_receipt(row)
            if _match_timeline_item(item, task_id=task_id, session_id=session_id, layer=layer, action=action, scope=scope, target_contains=target_contains):
                items.append(item)

    if "handoff" in wanted:
        for row in store.read_jsonl(HANDOFF_HISTORY_FILE, limit=5000):
            item = _map_handoff(row)
            if _match_timeline_item(item, task_id=task_id, session_id=session_id, layer=layer, action=action, scope=scope, target_contains=target_contains):
                items.append(item)
    return items


def _match_timeline_item(
    item: Dict[str, Any],
    *,
    task_id: str = "",
    session_id: str = "",
    layer: str = "",
    action: str = "",
    scope: str = "",
    target_contains: str = "",
) -> bool:
    row_task = str(item.get("task_id", "") or "")
    row_session = str(item.get("session_id", "") or "")
    row_layer = str(item.get("layer", "") or "")
    row_action = str(item.get("action", "") or "")
    row_scope = str(item.get("scope", "") or "")
    row_target = str(item.get("target", "") or "")
    if task_id and row_task != task_id:
        return False
    if session_id and row_session != session_id:
        return False
    if layer and row_layer != layer:
        return False
    if action and row_action != action:
        return False
    if scope and row_scope != scope:
        return False
    if target_contains and target_contains.lower() not in row_target.lower():
        return False
    return True


def _map_session_event(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}
    return with_schema(
        "timeline_item",
        {
        "kind": "session_event",
        "ref_id": f"ev:{row.get('session_id', '')}:{row.get('event_type', '')}:{row.get('created_at', '')}",
        "summary": " | ".join(
            part for part in [
                str(payload.get("tool_name", "") or ""),
                str(payload.get("query", "") or payload.get("target", "") or row.get("event_type", "") or ""),
                str(row.get("payload_ref", "") or ""),
            ] if part
        )[:140],
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
        "ref_id": row.get("receipt_id", "") or row.get("receipt_ref", ""),
        "summary": row.get("summary", ""),
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
        "ref_id": f"handoff:{row.get('session_id', '')}:{row.get('normalized_model', '')}:{row.get('created_at', '')}",
        "summary": " | ".join(
            part for part in [
                str(row.get("normalized_model", "") or row.get("target_model", "") or ""),
                str(row.get("current_phase", "") or ""),
                str(row.get("quality", "") or ""),
            ] if part
        )[:140],
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
