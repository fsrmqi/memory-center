"""任务证据引用的解析，不依赖任务编排。"""
from __future__ import annotations

from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

from .receipts import WRITE_RECEIPTS_FILE

SESSION_EVENTS_FILE = "session-events.jsonl"


def resolve_memory_ref(store: WorkspaceStore, ref_id: str) -> dict[str, Any] | None:
    if not ref_id:
        return None
    events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=5000)
    for event in events:
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        raw = {"event": event, "payload": payload}
        if ref_id == str(event.get("payload_ref", "") or ""):
            return {"kind": "payload_ref", "summary": str(event.get("payload_ref", "")), "raw": raw}
    for receipt in store.read_jsonl_prefer_backend(WRITE_RECEIPTS_FILE, limit=5000):
        if ref_id in {receipt.get("receipt_id", ""), receipt.get("receipt_ref", "")}:
            return {"kind": "write_receipt", "summary": receipt.get("summary", ""), "raw": receipt}
    if ref_id.startswith(("memory/refs/", "refs/")):
        raw = store.read_memory_ref_json(ref_id, default=None)
        if raw is not None:
            return {"kind": "payload_ref", "summary": ref_id, "raw": raw}
    return None
