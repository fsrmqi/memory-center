"""Lightweight, post-reindex change impact summaries for watcher batches."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

CHANGE_IMPACT_REPORTS_FILE = "change-impact-reports.jsonl"
CHANGE_IMPACT_FEEDBACK_FILE = "change-impact-feedback.jsonl"
CHANGE_IMPACT_FEEDBACK_INDEX_FILE = "change-impact-feedback-index.json"
CHANGE_IMPACT_REPORTS_MAINTENANCE_FILE = "change-impact-reports-maintenance.json"
CHANGE_IMPACT_REPORT_RETENTION_DAYS = 30
CHANGE_IMPACT_REPORT_MAX_RECORDS = 100_000
_HIGH_RISK_CATEGORIES = frozenset({"dto_contract", "feign_contract", "mq_contract", "http_contract", "configuration"})
_FEEDBACK_DECISIONS = frozenset({"confirmed", "false_positive", "deep_analysis_required", "resolved"})
_FINAL_DECISIONS = frozenset({"confirmed", "false_positive", "resolved"})
_VALIDATION_STATUSES = frozenset({"passed", "failed", "skipped", "not_run", "recorded"})


def record_change_impact_report(
    workspace_file: str | Path,
    *,
    changed_paths: list[str],
    trigger_result: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    """Persist a bounded summary using only watcher and index control metadata."""
    store = WorkspaceStore(workspace_file)
    invalidation = ((trigger_result.get("dirty_journal", {}) or {}).get("invalidation", {}) or {})
    categories = sorted({str(value) for value in invalidation.get("categories", []) if value})
    impacted_paths = _bounded_paths(invalidation.get("impacted_paths", []) or changed_paths)
    changed_paths = _bounded_paths(changed_paths)
    services = _services_for_paths(workspace_file, impacted_paths)
    completed = str(job.get("status", "") or "") == "completed"
    risk_level = "high" if set(categories) & _HIGH_RISK_CATEGORIES else ("medium" if len(impacted_paths) > len(changed_paths) else "low")
    control = index_control_status(store)
    report = {
        "schema_version": 1,
        "report_id": f"change-{uuid4().hex[:12]}",
        "kind": "watcher_change_impact",
        "status": "ready" if completed else "reindex_failed",
        "generated_at": time.time(),
        "changed_paths": changed_paths,
        "impacted_paths": impacted_paths,
        "change_categories": categories,
        "impacted_services": services,
        "risk_level": risk_level,
        "evidence_level": "EXTRACTED",
        "dependency_evidence_level": "INFERRED" if len(impacted_paths) > len(changed_paths) else "EXTRACTED",
        "evidence_sources": ["watcher_event", "bounded_invalidation_plan", "reindex_job", "index_control"],
        "job": _compact_job(job),
        "generation": {
            "active": control.get("active_generation", ""),
            "status": control.get("status", "unknown"),
        },
        "next_action": _next_action(risk_level, completed),
    }
    store.append_jsonl(CHANGE_IMPACT_REPORTS_FILE, report)
    _maybe_prune_reports(store)
    return report


def recent_change_impact_reports(workspace_file: str | Path, limit: int = 20, *, pending_only: bool = False) -> dict[str, Any]:
    """Return bounded recent watcher reports without loading code or graph indexes."""
    store = WorkspaceStore(workspace_file)
    bounded_limit = min(max(1, limit), 100)
    candidate_limit = min(max(bounded_limit * 5, 100), 500)
    feedback_index = store.read_json(CHANGE_IMPACT_FEEDBACK_INDEX_FILE, {}) or {}
    reports = [_with_feedback(report, feedback_index) for report in reversed(store.read_jsonl_prefer_backend(CHANGE_IMPACT_REPORTS_FILE, limit=candidate_limit))]
    if pending_only:
        reports = [report for report in reports if report["feedback"]["status"] == "pending"]
    reports = reports[:bounded_limit]
    return {"reports": reports, "count": len(reports), "limit": bounded_limit, "pending_only": pending_only, "feedback_summary": _feedback_summary(feedback_index)}


def pending_change_impact_reports(workspace_file: str | Path, limit: int = 20) -> dict[str, Any]:
    """Return unresolved reports and a bounded high-risk subset for Workbench."""
    result = recent_change_impact_reports(workspace_file, limit=limit, pending_only=True)
    result["high_risk_reports"] = [report for report in result["reports"] if report.get("risk_level") == "high"]
    return result


def record_change_impact_feedback(
    workspace_file: str | Path,
    report_id: str,
    *,
    decision: str,
    task_id: str = "",
    session_id: str = "",
    validation_status: str = "",
    validation_summary: str = "",
    verified_by: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Append a human decision and update the compact feedback read model."""
    normalized_decision = decision.strip().lower()
    if normalized_decision not in _FEEDBACK_DECISIONS:
        allowed = ", ".join(sorted(_FEEDBACK_DECISIONS))
        raise ValueError(f"decision must be one of: {allowed}")
    normalized_validation = validation_status.strip().lower() or "not_run"
    if normalized_validation not in _VALIDATION_STATUSES:
        allowed = ", ".join(sorted(_VALIDATION_STATUSES))
        raise ValueError(f"validation_status must be one of: {allowed}")
    store = WorkspaceStore(workspace_file)
    if not _find_report(store, report_id):
        return {"recorded": False, "report_id": report_id, "reason": "report_not_found"}
    reviewers = sorted({item.strip() for item in (verified_by or []) if item and item.strip()})[:10]
    evidence_level = "VERIFIED" if normalized_validation == "passed" or reviewers else "EXTRACTED"
    feedback = {
        "schema_version": 1,
        "feedback_id": f"change-feedback-{uuid4().hex[:12]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": report_id,
        "decision": normalized_decision,
        "status": "closed" if normalized_decision in _FINAL_DECISIONS else "pending",
        "task_id": task_id.strip(),
        "session_id": session_id.strip(),
        "validation_status": normalized_validation,
        "validation_summary": _structured_summary(validation_summary),
        "verified_by": reviewers,
        "note": _structured_summary(note),
        "evidence_level": evidence_level,
    }
    store.append_jsonl(CHANGE_IMPACT_FEEDBACK_FILE, feedback)
    index = store.read_json(CHANGE_IMPACT_FEEDBACK_INDEX_FILE, {}) or {}
    index[report_id] = feedback
    _trim_feedback_index(index)
    store.write_json(CHANGE_IMPACT_FEEDBACK_INDEX_FILE, index)
    _maybe_prune_feedback(store)
    return {"recorded": True, "feedback": feedback}


def _bounded_paths(paths: list[Any]) -> list[str]:
    return sorted({str(path).replace("\\", "/").lstrip("/") for path in paths if path})[:48]


def _services_for_paths(workspace_file: str | Path, paths: list[str]) -> list[str]:
    config = load_workspace_config(workspace_file)
    matches: set[str] = set()
    for path in paths:
        for service in config.services:
            prefix = config.service_logical_prefix(service)
            if path == prefix or path.startswith(prefix + "/"):
                matches.add(service.name)
    return sorted(matches)[:24]


def _compact_job(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result", {}) or {}
    return {
        "job_id": job.get("job_id", ""),
        "status": job.get("status", "unknown"),
        "progress": job.get("progress", {}),
        "updated_at": job.get("updated_at", 0),
        "error": job.get("error", ""),
        "counts": {key: result.get(key) for key in ("mode", "files", "symbols", "apis", "feigns", "mq", "semantic_docs") if key in result},
    }


def _next_action(risk_level: str, completed: bool) -> str:
    if not completed:
        return "检查后台 reindex 任务失败原因，修复后重新触发局部索引。"
    if risk_level == "high":
        return "建议显式执行 mc_analyze(depth=\"full\")，复核契约和跨服务影响。"
    if risk_level == "medium":
        return "建议查看受影响服务和依赖路径；需要变更时再执行定向分析。"
    return "局部索引已更新，无需自动执行深度影响分析。"


def _with_feedback(report: dict[str, Any], feedback_index: dict[str, Any]) -> dict[str, Any]:
    feedback = feedback_index.get(str(report.get("report_id", "") or ""), {}) if isinstance(feedback_index, dict) else {}
    if not isinstance(feedback, dict):
        feedback = {}
    return {
        **report,
        "feedback": feedback or {"status": "pending", "decision": "", "evidence_level": "AMBIGUOUS"},
    }


def _feedback_summary(feedback_index: dict[str, Any]) -> dict[str, Any]:
    decisions: dict[str, int] = {}
    verified = 0
    for feedback in feedback_index.values() if isinstance(feedback_index, dict) else []:
        if not isinstance(feedback, dict):
            continue
        decision = str(feedback.get("decision", "") or "")
        if decision:
            decisions[decision] = decisions.get(decision, 0) + 1
        if feedback.get("evidence_level") == "VERIFIED":
            verified += 1
    return {"feedback_count": sum(decisions.values()), "decision_counts": decisions, "verified_count": verified}


def _find_report(store: WorkspaceStore, report_id: str) -> dict[str, Any] | None:
    if not report_id.strip():
        return None
    rows = store.find_jsonl_prefer_backend(CHANGE_IMPACT_REPORTS_FILE, lambda item: item.get("report_id") == report_id, limit=1)
    return rows[-1] if rows else None


def _structured_summary(value: str) -> str:
    return " ".join(str(value or "").replace("\n", " ").replace("\r", " ").split())[:240]


def _trim_feedback_index(index: dict[str, Any]) -> None:
    if len(index) <= CHANGE_IMPACT_REPORT_MAX_RECORDS:
        return
    oldest = sorted(index, key=lambda report_id: str((index[report_id] or {}).get("created_at", "")))[: len(index) - CHANGE_IMPACT_REPORT_MAX_RECORDS]
    for report_id in oldest:
        index.pop(report_id, None)


def _maybe_prune_reports(store: WorkspaceStore) -> None:
    maintenance = store.read_json(CHANGE_IMPACT_REPORTS_MAINTENANCE_FILE, {}) or {}
    now = time.time()
    if now - float(maintenance.get("pruned_at", 0) or 0) < 24 * 60 * 60:
        return
    result = store.prune_jsonl(
        CHANGE_IMPACT_REPORTS_FILE,
        created_before=datetime.now(timezone.utc) - timedelta(days=CHANGE_IMPACT_REPORT_RETENTION_DAYS),
        max_records=CHANGE_IMPACT_REPORT_MAX_RECORDS,
    )
    store.write_json(CHANGE_IMPACT_REPORTS_MAINTENANCE_FILE, {"pruned_at": now, "result": result})


def _maybe_prune_feedback(store: WorkspaceStore) -> None:
    maintenance = store.read_json(CHANGE_IMPACT_REPORTS_MAINTENANCE_FILE, {}) or {}
    now = time.time()
    if now - float(maintenance.get("feedback_pruned_at", 0) or 0) < 24 * 60 * 60:
        return
    result = store.prune_jsonl(
        CHANGE_IMPACT_FEEDBACK_FILE,
        created_before=datetime.now(timezone.utc) - timedelta(days=CHANGE_IMPACT_REPORT_RETENTION_DAYS),
        max_records=CHANGE_IMPACT_REPORT_MAX_RECORDS,
    )
    store.write_json(CHANGE_IMPACT_REPORTS_MAINTENANCE_FILE, {**maintenance, "feedback_pruned_at": now, "feedback_result": result})
