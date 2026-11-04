"""Governance assertions projected from existing decision and validation events."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

GOVERNANCE_ASSERTIONS_FILE = "governance-assertions.jsonl"
GOVERNANCE_ASSERTION_INDEX_FILE = "governance-assertion-index.json"
GOVERNANCE_ENTITIES_FILE = "governance-entities.jsonl"
GOVERNANCE_MODEL_INDEX_FILE = "governance-model-index.json"


def project_change_feedback(store: WorkspaceStore, report: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    """Create bounded Decision/Validation assertions from a confirmed report."""
    report_id = str(report.get("report_id", "") or "")
    feedback_id = str(feedback.get("feedback_id", "") or "")
    decision = str(feedback.get("decision", "") or "").upper()
    validation = str(feedback.get("validation_status", "") or "not_run").upper()
    now = datetime.now(timezone.utc).isoformat()
    relation = "VERIFIES" if decision in {"CONFIRMED", "RESOLVED"} else "REJECTS" if decision == "FALSE_POSITIVE" else "REQUESTS_ANALYSIS"
    rows = [
        _row(f"Decision:{feedback_id}", relation, f"ChangeReport:{report_id}", now, feedback),
        _row(f"Validation:{feedback_id}", "VALIDATES", f"Decision:{feedback_id}", now, {"status": validation, "evidence_level": feedback.get("evidence_level", "EXTRACTED")}),
    ]
    store.append_jsonl_batch(GOVERNANCE_ASSERTIONS_FILE, rows)
    index = store.read_json_prefer_backend(GOVERNANCE_ASSERTION_INDEX_FILE, {"recent": []})
    recent = (list(index.get("recent", [])) if isinstance(index, dict) else []) + rows
    store.write_json(GOVERNANCE_ASSERTION_INDEX_FILE, {"schema_version": 2, "updated_at": now, "recent": recent[-100:]})
    _record_model(store, rows, now)
    return {"projected": len(rows), "relations": [row["predicate"] for row in rows]}


def project_session_validation(store: WorkspaceStore, session_id: str, validation: dict[str, Any]) -> dict[str, Any]:
    """Project mc_close validation without persisting its raw command or output."""
    session_id = session_id.strip()
    if not session_id:
        return {"projected": 0, "reason": "missing_session_id"}
    status = str(validation.get("status", "not_run") or "not_run").lower()
    if status in {"not_run", "skipped"}:
        return {"projected": 0, "reason": status}
    now = datetime.now(timezone.utc).isoformat()
    evidence_level = "VERIFIED" if validation.get("verified") or status == "passed" else "EXTRACTED"
    evidence = {
        "validation_status": status,
        "evidence_level": evidence_level,
        "summary_hash": sha256(str(validation.get("summary", "")).encode()).hexdigest()[:16],
        "verification_source": str(validation.get("verification_source", "") or ""),
    }
    row = _row(f"Validation:session:{session_id}", "VALIDATES", f"Session:{session_id}", now, evidence)
    store.append_jsonl(GOVERNANCE_ASSERTIONS_FILE, row)
    index = store.read_json_prefer_backend(GOVERNANCE_ASSERTION_INDEX_FILE, {"recent": []})
    recent = (list(index.get("recent", [])) if isinstance(index, dict) else []) + [row]
    store.write_json(GOVERNANCE_ASSERTION_INDEX_FILE, {"schema_version": 2, "updated_at": now, "recent": recent[-100:]})
    _record_model(store, [row], now)
    return {"projected": 1, "relations": [row["predicate"]], "evidence_level": evidence_level}


def _row(subject_id: str, predicate: str, object_id: str, created_at: str, evidence: dict[str, Any]) -> dict[str, Any]:
    assertion_id = sha256(f"{subject_id}|{predicate}|{object_id}|{created_at}".encode()).hexdigest()[:32]
    return {
        "assertion_id": assertion_id,
        "type": "governance_assertion",
        "subject_id": subject_id,
        "predicate": predicate,
        "object_id": object_id,
        "status": "VERIFIED" if str(evidence.get("evidence_level", "")) == "VERIFIED" else "EXTRACTED",
        "source_kind": "GOVERNANCE",
        "provenance_kind": "HUMAN",
        "relation_mode": "STRUCTURAL",
        "evidence_refs": [value for value in (str(evidence.get("verification_source", "") or ""),) if value],
        "event_at": created_at,
        "observed_at": created_at,
        "valid_from": created_at,
        "valid_to": "",
        "created_at": created_at,
        "evidence": {key: evidence.get(key) for key in ("decision", "validation_status", "task_id", "session_id", "evidence_level", "summary_hash", "verification_source")},
    }


def record_action(store: WorkspaceStore, *, assertion_id: str, status: str, action: dict[str, Any], task_id: str = "", session_id: str = "", actor: str = "") -> dict[str, Any]:
    """Persist one bounded, traceable Action for an assertion detail view."""
    now = datetime.now(timezone.utc).isoformat()
    action_id = _action_id(assertion_id, status, action)
    row = {
        "entity_id": f"Action:{action_id}", "entity_type": "Action", "action_id": action_id,
        "assertion_id": assertion_id, "status": status, "task_id": task_id, "session_id": session_id,
        "actor": actor[:120], "created_at": now, "event_at": now, "observed_at": now,
        "action": action,
    }
    store.append_jsonl(GOVERNANCE_ENTITIES_FILE, row)
    index = store.read_json_prefer_backend(GOVERNANCE_MODEL_INDEX_FILE, {"entities": [], "relations": []}) or {}
    entities = list(index.get("entities", [])) + [row]
    relation = {"subject_id": row["entity_id"], "subject_type": "Action", "predicate": "EXPLAINS", "object_id": f"Assertion:{assertion_id}", "object_type": "Assertion", "created_at": now}
    relations = list(index.get("relations", [])) + [relation]
    store.write_json(GOVERNANCE_MODEL_INDEX_FILE, {"schema_version": 1, "updated_at": now, "entities": entities[-200:], "relations": relations[-400:]})
    return row


def record_actions(store: WorkspaceStore, *, origin: str, actions: list[Any], task_id: str = "", session_id: str = "", actor: str = "") -> list[dict[str, Any]]:
    """Persist each stable public-query action once, then reuse its ID.

    Query recommendations are derived read-model output. Re-appending the same
    action on every lookup made hot reads perform redundant JSONL and index
    writes. The read model keeps the latest 200 actions, which is sufficient
    to deduplicate active recommendations without storing query bodies.
    """

    now = datetime.now(timezone.utc).isoformat()
    index = store.read_json_prefer_backend(GOVERNANCE_MODEL_INDEX_FILE, {"entities": [], "relations": []}) or {}
    entities = list(index.get("entities", []) or [])
    relations = list(index.get("relations", []) or [])
    existing_ids = {
        str(entity.get("action_id", "") or "")
        for entity in entities
        if isinstance(entity, dict) and entity.get("entity_type") == "Action"
    }
    persisted: list[dict[str, Any]] = []
    new_rows: list[dict[str, Any]] = []
    new_relations: list[dict[str, Any]] = []
    for item in actions[:20]:
        action = dict(item) if isinstance(item, dict) else {"action_type": "follow_recommendation", "label": str(item)}
        key = sha256(f"{origin}|{action}".encode()).hexdigest()[:16]
        assertion_id = f"lookup:{key}"
        action_id = _action_id(assertion_id, "EXTRACTED", action)
        persisted.append({**action, "action_id": action_id})
        if action_id in existing_ids:
            continue
        row = {
            "entity_id": f"Action:{action_id}", "entity_type": "Action", "action_id": action_id,
            "assertion_id": assertion_id, "status": "EXTRACTED", "task_id": task_id, "session_id": session_id,
            "actor": actor[:120], "created_at": now, "event_at": now, "observed_at": now,
            "action": action,
        }
        new_rows.append(row)
        new_relations.append({
            "subject_id": row["entity_id"], "subject_type": "Action", "predicate": "EXPLAINS",
            "object_id": f"Assertion:{assertion_id}", "object_type": "Assertion", "created_at": now,
        })
        existing_ids.add(action_id)
    if new_rows:
        store.append_jsonl_batch(GOVERNANCE_ENTITIES_FILE, new_rows)
        store.write_json(
            GOVERNANCE_MODEL_INDEX_FILE,
            {"schema_version": 1, "updated_at": now, "entities": (entities + new_rows)[-200:], "relations": (relations + new_relations)[-400:]},
        )
    return persisted


def _action_id(assertion_id: str, status: str, action: dict[str, Any]) -> str:
    return sha256(f"{assertion_id}|{action.get('action_type', '')}|{status}".encode()).hexdigest()[:32]


def _record_model(store: WorkspaceStore, rows: list[dict[str, Any]], now: str) -> None:
    entities: list[dict[str, Any]] = []
    for row in rows:
        for value in (row.get("subject_id", ""), row.get("object_id", "")):
            entity_type = str(value).split(":", 1)[0] if value else ""
            if entity_type:
                entities.append({"entity_id": value, "entity_type": entity_type, "created_at": now})
    if entities:
        store.append_jsonl_batch(GOVERNANCE_ENTITIES_FILE, entities)
    current = store.read_json_prefer_backend(GOVERNANCE_MODEL_INDEX_FILE, {"entities": [], "relations": []}) or {}
    store.write_json(GOVERNANCE_MODEL_INDEX_FILE, {"schema_version": 1, "updated_at": now, "entities": (list(current.get("entities", [])) + entities)[-200:], "relations": (list(current.get("relations", [])) + rows)[-400:]})
