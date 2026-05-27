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
    backend: str = "auto",
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
        backend=backend,
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
                "backend": backend,
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
    backend: str = "auto",
) -> List[Dict[str, Any]]:
    wanted = set(kinds or ["session_event", "write_receipt", "handoff"])
    items: List[Dict[str, Any]] = []
    use_backend = backend in {"auto", "sqlite"} and bool(store.memory_backend_stats().get("collections"))

    if "session_event" in wanted:
        session_rows = _load_collection_rows(store, SESSION_EVENTS_FILE, use_backend=use_backend)
        for row in session_rows:
            item = _map_session_event(row)
            if _match_timeline_item(item, task_id=task_id, session_id=session_id, layer=layer, action=action, scope=scope, target_contains=target_contains):
                items.append(item)

    if "write_receipt" in wanted:
        receipt_rows = _load_collection_rows(store, WRITE_RECEIPTS_FILE, use_backend=use_backend)
        for row in receipt_rows:
            item = _map_write_receipt(row)
            if _match_timeline_item(item, task_id=task_id, session_id=session_id, layer=layer, action=action, scope=scope, target_contains=target_contains):
                items.append(item)

    if "handoff" in wanted:
        handoff_rows = _load_collection_rows(store, HANDOFF_HISTORY_FILE, use_backend=use_backend)
        for row in handoff_rows:
            item = _map_handoff(row)
            if _match_timeline_item(item, task_id=task_id, session_id=session_id, layer=layer, action=action, scope=scope, target_contains=target_contains):
                items.append(item)
    return items


def _load_collection_rows(store: WorkspaceStore, collection: str, *, use_backend: bool) -> List[Dict[str, Any]]:
    if use_backend:
        rows = store.memory_backend_query_records(collection=collection, limit=5000).get("records", [])
        return [item.get("payload", {}) if isinstance(item.get("payload"), dict) else item for item in rows]
    return store.read_jsonl(collection, limit=5000)


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
    # Support both formats: full record (from JSONL) and unwrapped payload (from backend)
    payload = row.get("payload", {}) if isinstance(row.get("payload"), dict) else {}
    session_id = row.get("session_id", "") or payload.get("session_id", "")
    event_type = row.get("event_type", "") or payload.get("event_type", "")
    created_at = row.get("created_at", "") or payload.get("created_at", "")
    payload_ref = row.get("payload_ref", "") or payload.get("payload_ref", "")
    effective_payload = payload if payload or row.get("payload") is None else row
    return with_schema(
        "timeline_item",
        {
        "kind": "session_event",
        "ref_id": f"ev:{session_id}:{event_type}:{created_at}",
        "summary": " | ".join(
            part for part in [
                str(effective_payload.get("tool_name", "") or ""),
                str(effective_payload.get("query", "") or effective_payload.get("target", "") or event_type or ""),
                str(payload_ref or ""),
            ] if part
        )[:140],
        "created_at": created_at,
        "task_id": "",
        "session_id": session_id,
        "layer": "L0_session_events",
        "action": event_type,
        "scope": "memory",
        "target": effective_payload.get("tool_name", "") or effective_payload.get("query", "") or effective_payload.get("target", "") or event_type,
        "payload_ref": payload_ref,
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
