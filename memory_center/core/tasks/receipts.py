from __future__ import annotations

from typing import Any

from memory_center.core.foundation.schemas import with_schema
from memory_center.core.storage.workspace import WorkspaceStore

WRITE_RECEIPTS_FILE = "write-receipts.jsonl"


def _receipt_id(layer: str, action: str, target: str) -> str:
    return f"wr:{layer}:{action}:{target}"[:160]


def _receipt_summary(layer: str, action: str, target: str) -> str:
    text = " | ".join(part for part in [layer, action, target] if part)
    return text[:140]


def build_write_receipt(
    layer: str,
    action: str,
    scope: str,
    target: str,
    target_file: str,
    task_id: str = "",
    session_id: str = "",
    source_session_id: str = "",
    updated_artifacts: list[str] | None = None,
    payload_ref: str = "",
    bytes_written: int = 0,
    write_mode: str = "",
    audit_ref: str = "",
) -> dict[str, Any]:
    return with_schema(
        "write_receipt",
        {
        "receipt_id": _receipt_id(layer, action, target),
        "summary": _receipt_summary(layer, action, target),
        "layer": layer,
        "action": action,
        "scope": scope,
        "target": target,
        "target_file": target_file,
        "task_id": task_id,
        "session_id": session_id,
        "source_session_id": source_session_id,
        "updated_artifacts": updated_artifacts or [],
        "payload_ref": payload_ref,
        "bytes_written": bytes_written,
        "write_mode": write_mode,
        "audit_ref": audit_ref,
        },
    )


def persist_write_receipt(store: WorkspaceStore, receipt: dict[str, Any]) -> dict[str, Any]:
    store.append_jsonl(WRITE_RECEIPTS_FILE, receipt)
    rows = store.read_jsonl(WRITE_RECEIPTS_FILE, limit=1)
    created_at = rows[-1].get("created_at", "") if rows else ""
    persisted = dict(receipt)
    persisted["receipt_ref"] = f"memory/{WRITE_RECEIPTS_FILE}#{created_at}" if created_at else f"memory/{WRITE_RECEIPTS_FILE}"
    return persisted


def query_write_receipts(
    workspace_file: str,
    *,
    layer: str = "",
    action: str = "",
    scope: str = "",
    task_id: str = "",
    session_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    backend_rows = store.read_jsonl_via_backend(WRITE_RECEIPTS_FILE, limit=5000)
    rows = backend_rows or store.read_jsonl(WRITE_RECEIPTS_FILE, limit=5000)
    matched = []
    for row in rows:
        if layer and row.get("layer") != layer:
            continue
        if action and row.get("action") != action:
            continue
        if scope and row.get("scope") != scope:
            continue
        if task_id and row.get("task_id") != task_id:
            continue
        if session_id and row.get("session_id") != session_id and row.get("source_session_id") != session_id:
            continue
        matched.append(row)
    return {
        "receipts": matched[-limit:],
        "summary": {
            "total": len(matched),
            "layers": sorted({row.get("layer", "") for row in matched if row.get("layer")}),
            "actions": sorted({row.get("action", "") for row in matched if row.get("action")}),
        },
    }
