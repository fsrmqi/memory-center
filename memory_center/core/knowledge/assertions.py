"""Append-only assertion sidecar for versioned ontology facts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from memory_center.core.assessment.quality import evidence_level_for
from memory_center.core.knowledge.ontology import edge_strength
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

ASSERTIONS_FILE = "assertions.jsonl"
ASSERTION_INDEX_FILE = "assertion-index.json"
ASSERTION_EVENTS_FILE = "assertion-events.jsonl"
ASSERTION_MAINTENANCE_FILE = "assertion-maintenance.json"
ASSERTION_STATUS_EXTRACTED = "EXTRACTED"


def materialize_static_assertions(
    store: WorkspaceStore,
    generation: str,
    *,
    batch_size: int = 1000,
    paths: list[str] | None = None,
    projects: list[str] | None = None,
) -> dict[str, int | str]:
    """Publish a compact manifest; static assertions are derived from graph edges."""
    created_at = datetime.now(timezone.utc).isoformat()
    partial = bool(paths or projects)
    with RuntimeStore(store.graph_db_path) as graph:
        counts = graph.counts()
    summary = sparse_assertion_summary(store, static_count=int(counts.get("edges", 0)))
    summary["recent"] = _derived_assertion_slice(store, generation=generation, created_at=created_at, limit=20)
    store.write_json(
        ASSERTION_INDEX_FILE,
        {
            "schema_version": 1,
            "generation": generation,
            "active": summary["active"],
            "by_status": summary["by_status"],
            "recent": summary["recent"],
            "updated_at": created_at,
            "written": 0,
            "derived_static_count": int(counts.get("edges", 0)),
            "mode": "partial" if partial else "full",
        },
    )
    return {"written": 0, "active": int(summary["active"]), "generation": generation, "mode": "derived_partial" if partial else "derived"}


def query_assertions(
    store: WorkspaceStore,
    *,
    as_of_generation: str = "",
    as_of_time: str = "",
    time_axis: str = "valid",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Derive current static facts from the graph; history remains sparse overrides."""
    if as_of_generation:
        return store.memory_backend().query_assertions(as_of_generation=as_of_generation, as_of_time=as_of_time, time_axis=time_axis, limit=limit)
    generation = str(store.read_json_prefer_backend(ASSERTION_INDEX_FILE, {}).get("generation", "") or "")
    created_at = str(store.read_json_prefer_backend(ASSERTION_INDEX_FILE, {}).get("updated_at", "") or "")
    derived = _derived_assertion_slice(store, generation=generation, created_at=created_at, limit=limit)
    return derived


def _derived_assertion_slice(store: WorkspaceStore, *, generation: str, created_at: str, limit: int) -> list[dict[str, Any]]:
    derived: list[dict[str, Any]] = []
    with RuntimeStore(store.graph_db_path) as graph:
        for edge in graph.iter_assertion_rows(batch_size=min(max(1, limit), 500)):
            derived.append(_assertion_from_edge(edge, generation=generation, created_at=created_at))
            if len(derived) >= min(max(1, limit), 500):
                break
    statuses = store.memory_backend().assertion_statuses([item["assertion_id"] for item in derived])
    for item in derived:
        item["status"] = statuses.get(item["assertion_id"], ASSERTION_STATUS_EXTRACTED)
    return derived


def update_assertion_status(
    store: WorkspaceStore,
    assertion_id: str,
    *,
    status: str,
    verification_ref: str = "",
    actor: str = "",
    task_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """Explicitly verify or reject an assertion without deleting its history."""
    normalized = status.strip().upper()
    if normalized == "VERIFIED" and not verification_ref.strip():
        raise ValueError("VERIFIED assertions require verification_ref")
    if assertion_id.startswith("static:") and store.memory_backend().assertion_by_id(assertion_id) is None:
        derived = _derived_assertion_by_id(store, assertion_id)
        if derived is None:
            return {"updated": False, "reason": "assertion_not_found", "assertion_id": assertion_id}
        store.memory_backend().upsert_assertions([derived])
    updated = store.memory_backend().set_assertion_status(assertion_id, normalized, verification_ref=verification_ref)
    if not updated:
        return {"updated": False, "reason": "assertion_not_found", "assertion_id": assertion_id}
    event = {
        "type": "assertion_status_changed",
        "assertion_id": assertion_id,
        "status": normalized,
        "verification_ref": verification_ref[:240],
        "actor": actor[:120],
        "task_id": task_id[:120],
        "session_id": session_id[:120],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    store.append_jsonl(ASSERTION_EVENTS_FILE, event)
    return {"updated": True, "event": event}


def inspect_assertion(store: WorkspaceStore, assertion_id: str) -> dict[str, Any]:
    """Return one assertion by stable ref without scanning the audit stream."""
    assertion = store.memory_backend().assertion_by_id(assertion_id) or _derived_assertion_by_id(store, assertion_id)
    if assertion is None:
        return {"found": False, "assertion": None, "assertion_ref": assertion_id}
    from memory_center.core.knowledge.aliases import resolve_canonical_identity
    from memory_center.core.knowledge.governance import record_action
    from memory_center.core.presentation.conclusion_cards import _action

    status = str(assertion.get("status", "EXTRACTED") or "EXTRACTED")
    action = _action(status)
    persisted = record_action(store, assertion_id=assertion_id, status=status, action=action)
    return {
        "found": True,
        "assertion": assertion,
        "assertion_ref": assertion_id,
        "identity_resolution": {
            "subject": resolve_canonical_identity(store, str(assertion.get("subject_id", ""))),
            "object": resolve_canonical_identity(store, str(assertion.get("object_id", ""))),
        },
        "action": {**action, "action_id": persisted["action_id"], "assertion_ref": assertion_id},
        "state_change_notice": "此操作仅改变断言状态，不会修改源码或删除历史证据。",
    }


def sparse_assertion_summary(store: WorkspaceStore, *, static_count: int = 0) -> dict[str, Any]:
    summary = store.memory_backend().assertion_summary(limit=0)
    statuses = dict(summary.get("by_status", {}))
    overrides = sum(int(value) for value in statuses.values())
    statuses[ASSERTION_STATUS_EXTRACTED] = max(0, static_count - overrides) + int(statuses.get(ASSERTION_STATUS_EXTRACTED, 0))
    return {"active": static_count, "by_status": statuses, "recent": []}


def _derived_assertion_by_id(store: WorkspaceStore, assertion_id: str) -> dict[str, Any] | None:
    if not assertion_id.startswith("static:"):
        return None
    with RuntimeStore(store.graph_db_path) as graph:
        edge = graph.assertion_row_by_edge_id(assertion_id.removeprefix("static:"))
    if edge is None:
        return None
    generation = str(store.read_json_prefer_backend(ASSERTION_INDEX_FILE, {}).get("generation", "") or "")
    return _assertion_from_edge(edge, generation=generation, created_at="")


def _assertion_from_edge(edge: dict[str, Any], *, generation: str, created_at: str) -> dict[str, Any]:
    subject_id = str(edge["source_id"])
    predicate = str(edge["type"])
    object_id = str(edge["target_id"])
    assertion_id = f"static:{edge.get('id', '')}"
    evidence_level = evidence_level_for({}, semantic_strength=edge_strength(predicate))
    event_at = created_at
    return {
        "assertion_id": assertion_id,
        "type": "static_assertion",
        "subject_id": subject_id,
        "subject_type": str(edge["subject_type"]),
        "predicate": predicate,
        "object_id": object_id,
        "object_type": str(edge["object_type"]),
        "source_file": str(edge.get("source_file", "") or ""),
        "target_file": str(edge.get("target_file", "") or ""),
        "source_project": str(edge.get("source_project", "") or ""),
        "target_project": str(edge.get("target_project", "") or ""),
        "status": ASSERTION_STATUS_EXTRACTED,
        "evidence_level": evidence_level,
        "confidence": float(edge.get("confidence", 1.0) or 1.0),
        "generation": generation,
        "source_kind": "STATIC",
        "provenance_kind": "STATIC",
        "relation_mode": str(edge.get("relation_mode", "STRUCTURAL") or "STRUCTURAL"),
        "evidence_refs": [f"ev:graph-edge:{edge.get('id', '')}"],
        "event_at": event_at,
        "observed_at": created_at,
        "event_time_source": "observed_at_fallback",
        "valid_from": created_at,
        "valid_to": "",
        "created_at": created_at,
    }


def assertion_id_for(subject_id: str, predicate: str, object_id: str, generation: str) -> str:
    """Deprecated endpoint-based helper; graph exports use `static:<edge_id>`."""
    return f"static:{subject_id}|{predicate}|{object_id}"
