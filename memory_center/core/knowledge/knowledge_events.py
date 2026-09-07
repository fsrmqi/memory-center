"""Bounded observability events for the KnowledgeLink integration (Phase 4).

Events cover candidate exposure, manual attachment, confirmed promotion, and
link status changes. Payloads carry references and bounded summaries only —
never Wiki bodies, prompts, or tool payloads (plan: Safety gates).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

KNOWLEDGE_EVENTS_FILE = "knowledge-link-events.jsonl"
SCHEMA_VERSION = 1
EVENT_TYPES = {"candidate_exposure", "manual_attach", "promotion_confirmed", "link_status_changed"}
_MAX_PAYLOAD_CHARS = 1200


def record_knowledge_event(
    workspace_file: str | Path,
    *,
    event_type: str,
    payload: dict[str, Any],
    actor: str = "",
) -> dict[str, Any]:
    """Append one bounded observability event; unknown event types fail loud."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"event_type must be one of: {', '.join(sorted(EVENT_TYPES))}")
    store = WorkspaceStore(workspace_file)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    bounded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)[:_MAX_PAYLOAD_CHARS]
    identity = f"{event_type}\0{now_ms}\0{bounded}"
    event_id = f"kle-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    event = {
        "schema_version": SCHEMA_VERSION,
        "id": event_id,
        "type": "knowledge_link_event",
        "event_type": event_type,
        "actor": str(actor).strip()[:120],
        "time_ms": now_ms,
        "payload": {"payload_sha256": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest(), "payload_chars": len(bounded)},
    }
    inserted = store.append_jsonl_batch(KNOWLEDGE_EVENTS_FILE, [event])
    return {"recorded": bool(inserted), "event_id": event_id, "event": event}


def read_knowledge_events(workspace_file: str | Path, *, limit: int = 200) -> list[dict[str, Any]]:
    """Read the most recent bounded window of KnowledgeLink observability events."""
    store = WorkspaceStore(workspace_file)
    bounded = max(1, min(limit, 1000))
    events = store.read_jsonl_prefer_backend(KNOWLEDGE_EVENTS_FILE, limit=bounded)
    return [event for event in events if isinstance(event, dict) and event.get("type") == "knowledge_link_event"]
