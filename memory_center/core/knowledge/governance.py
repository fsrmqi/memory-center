"""Governance assertions projected from existing decision and validation events."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

GOVERNANCE_ASSERTIONS_FILE = "governance-assertions.jsonl"
GOVERNANCE_ASSERTION_INDEX_FILE = "governance-assertion-index.json"


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
    store.write_json(GOVERNANCE_ASSERTION_INDEX_FILE, {"schema_version": 1, "updated_at": now, "recent": recent[-100:]})
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
    store.write_json(GOVERNANCE_ASSERTION_INDEX_FILE, {"schema_version": 1, "updated_at": now, "recent": recent[-100:]})
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
        "created_at": created_at,
        "evidence": {key: evidence.get(key) for key in ("decision", "validation_status", "task_id", "session_id", "evidence_level", "summary_hash", "verification_source")},
    }
