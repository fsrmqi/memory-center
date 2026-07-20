"""Append-only assertion sidecar for versioned ontology facts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from memory_center.core.assessment.quality import evidence_level_for
from memory_center.core.knowledge.ontology import edge_strength
from memory_center.core.storage.graph import GraphStore
from memory_center.core.storage.workspace import WorkspaceStore

ASSERTIONS_FILE = "assertions.jsonl"
ASSERTION_INDEX_FILE = "assertion-index.json"
ASSERTION_EVENTS_FILE = "assertion-events.jsonl"
ASSERTION_MAINTENANCE_FILE = "assertion-maintenance.json"
ASSERTION_STATUS_EXTRACTED = "EXTRACTED"
ASSERTION_RETENTION_DAYS = 90
ASSERTION_CLOSED_MAX_RECORDS = 2_000_000


def materialize_static_assertions(
    store: WorkspaceStore,
    generation: str,
    *,
    batch_size: int = 1000,
    paths: list[str] | None = None,
    projects: list[str] | None = None,
) -> dict[str, int | str]:
    """Mirror the published graph as immutable, generation-scoped assertions.

    This runs after generation publication. Failure is intentionally isolated
    from graph availability; a later reindex can reconstruct the sidecar.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    partial = bool(paths or projects)
    if partial:
        store.memory_backend().supersede_assertions_in_scope(
            paths=paths,
            projects=projects,
            generation=generation,
            valid_to=created_at,
        )
    total = 0
    with GraphStore(store.graph_db_path) as graph:
        batch: list[dict[str, Any]] = []
        for edge in graph.iter_assertion_rows(batch_size=batch_size, paths=paths, projects=projects):
            payload = _assertion_from_edge(edge, generation=generation, created_at=created_at)
            batch.append(payload)
            if len(batch) >= batch_size:
                _persist_batch(store, batch)
                total += len(batch)
                batch = []
        if batch:
            _persist_batch(store, batch)
            total += len(batch)
    summary = store.memory_backend().assertion_summary(limit=20)
    store.write_json(
        ASSERTION_INDEX_FILE,
        {
            "schema_version": 1,
            "generation": generation,
            "active": summary["active"],
            "by_status": summary["by_status"],
            "recent": summary["recent"],
            "updated_at": created_at,
        },
    )
    _maybe_maintain_assertions(store)
    return {"written": total, "active": int(summary["active"]), "generation": generation, "mode": "partial" if partial else "full"}


def query_assertions(
    store: WorkspaceStore,
    *,
    as_of_generation: str = "",
    as_of_time: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Bounded temporal read API for current or historical assertions."""
    return store.memory_backend().query_assertions(
        as_of_generation=as_of_generation,
        as_of_time=as_of_time,
        limit=limit,
    )


def update_assertion_status(
    store: WorkspaceStore,
    assertion_id: str,
    *,
    status: str,
    verification_ref: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Explicitly verify or reject an assertion without deleting its history."""
    normalized = status.strip().upper()
    if normalized == "VERIFIED" and not verification_ref.strip():
        raise ValueError("VERIFIED assertions require verification_ref")
    updated = store.memory_backend().set_assertion_status(assertion_id, normalized, verification_ref=verification_ref)
    if not updated:
        return {"updated": False, "reason": "assertion_not_found", "assertion_id": assertion_id}
    event = {
        "type": "assertion_status_changed",
        "assertion_id": assertion_id,
        "status": normalized,
        "verification_ref": verification_ref[:240],
        "actor": actor[:120],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    store.append_jsonl(ASSERTION_EVENTS_FILE, event)
    return {"updated": True, "event": event}


def inspect_assertion(store: WorkspaceStore, assertion_id: str) -> dict[str, Any]:
    """Return one assertion by stable ref without scanning the audit stream."""
    assertion = store.memory_backend().assertion_by_id(assertion_id)
    return {"found": assertion is not None, "assertion": assertion, "assertion_ref": assertion_id}


def _persist_batch(store: WorkspaceStore, assertions: list[dict[str, Any]]) -> None:
    store.memory_backend().upsert_assertions(assertions)
    store.append_jsonl_batch(ASSERTIONS_FILE, assertions)


def _maybe_maintain_assertions(store: WorkspaceStore) -> None:
    """Run low-frequency cleanup outside the ordinary query path."""
    maintenance = store.read_json(ASSERTION_MAINTENANCE_FILE, {}) or {}
    now = datetime.now(timezone.utc)
    if (now.timestamp() - float(maintenance.get("pruned_at", 0) or 0)) < 24 * 60 * 60:
        return
    cutoff = now - timedelta(days=ASSERTION_RETENTION_DAYS)
    backend = store.memory_backend().prune_closed_assertions(
        valid_before=cutoff.isoformat(), max_closed=ASSERTION_CLOSED_MAX_RECORDS
    )
    journal = store.prune_jsonl(
        ASSERTIONS_FILE,
        created_before=cutoff,
        max_records=ASSERTION_CLOSED_MAX_RECORDS,
    )
    store.write_json(
        ASSERTION_MAINTENANCE_FILE,
        {"pruned_at": now.timestamp(), "cutoff": cutoff.isoformat(), "backend": backend, "journal": journal},
    )


def _assertion_from_edge(edge: dict[str, Any], *, generation: str, created_at: str) -> dict[str, Any]:
    subject_id = str(edge["source_id"])
    predicate = str(edge["type"])
    object_id = str(edge["target_id"])
    assertion_id = assertion_id_for(subject_id, predicate, object_id, generation)
    evidence_level = evidence_level_for({}, semantic_strength=edge_strength(predicate))
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
        "valid_from": created_at,
        "valid_to": "",
        "created_at": created_at,
    }


def assertion_id_for(subject_id: str, predicate: str, object_id: str, generation: str) -> str:
    return sha256(f"{subject_id}|{predicate}|{object_id}|{generation}|STATIC".encode()).hexdigest()[:32]
