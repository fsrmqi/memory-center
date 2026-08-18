"""Structured, evidence-first delivery workflow for a task space.

The workflow intentionally owns only delivery state and contracts.  Code
discovery, impact analysis, task artifacts, and verification execution remain
in their existing domains.  This keeps a reusable workflow pack from turning
into a second orchestrator or a project-specific Skill.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock

from memory_center.core.storage.memory_backend import DELIVERY_RECEIPT_PROJECTION_VERSION
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

from .artifacts import _resolve_task_dir, touch_task_activity, update_task_status

DELIVERY_FILE = "delivery.json"
REQUIREMENTS_FILE = "requirements.json"
SUBTASKS_FILE = "subtasks.json"
ACCEPTANCE_FILE = "acceptance.json"
VALIDATION_RECEIPTS_FILE = "verification-receipts.jsonl"
GATE_RESULTS_FILE = "delivery-gate-results.jsonl"
DELIVERY_MATRIX_FILE = "delivery-matrix.json"
TECH_SPEC_FILE = "TECH_SPEC.md"
DELIVERY_POLICY_FILE = "delivery-policy.json"
DELIVERY_SKILL_CANDIDATES_DIR = "skills/delivery-candidates"
DELIVERY_SKILL_PUBLISHED_DIR = "skills/delivery-published"
DELIVERY_SKILL_CANARY_DIR = "skills/delivery-canary"
DELIVERY_SKILL_REGISTRY_FILE = "skills/delivery-skill-registry.json"
DELIVERY_SKILL_OBSERVATIONS_FILE = "skills/delivery-skill-observations.jsonl"
DELIVERY_SKILL_REPLAYS_DIR = "skills/delivery-replays"
DELIVERY_SKILL_FAILURES_FILE = "skills/delivery-failure-candidates.json"
DELIVERY_SKILL_SYNTHESIS_FILE = "skills/delivery-skill-synthesis.json"
WAIVER_FILE = "delivery-waivers.jsonl"
FAILURE_CLASSIFICATION_FILE = "delivery-failure-classifications.jsonl"
DELIVERY_METRICS_FILE = "delivery-metrics.json"
WORKFLOW_PROFILE = "feature_delivery_v2"
STAGES = ("intake", "breakdown", "locate", "implement", "verify", "close")
SUBTASK_STATUSES = {"pending", "located", "implemented", "blocked", "skipped"}
VALIDATION_STATUSES = {"passed", "failed", "skipped", "not_run", "recorded"}
EVIDENCE_KINDS = {"recorded_external", "manual_verified", "executor"}
SKILL_OUTCOMES = {"passed", "failed", "bypassed", "unobservable"}
SKILL_LIFECYCLES = {"candidate", "canary", "published", "superseded", "rejected", "rolled_back"}
FAILURE_CATEGORIES = {
    "auto_repairable": "可自动修复：重试或回滚后继续。",
    "environment_blocked": "配置/环境阻塞：检查运行环境、依赖或权限后重试。",
    "requirement_path_error": "需求/路径错误：需求范围或代码目标有误，需重新定位。",
    "human_decision_required": "人工决策：超出自动处理范围，需人工判断。",
}
WAIVER_STATUSES = {"pending", "approved", "expired", "revoked"}


class DeliverySkillRegistryCorruptionError(RuntimeError):
    """Skill registry cannot be recovered without risking historical data loss."""


class DeliveryArtifactCorruptionError(RuntimeError):
    """A delivery artifact is present but cannot be decoded safely."""


def initialize_delivery_workflow(
    workspace_file: str | Path,
    task_id: str,
    *,
    actor: str = "",
    include_status: bool = True,
    touch_activity: bool = True,
) -> dict[str, Any]:
    """Create the delivery contract for one existing task space, idempotently."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    now = _now()
    created: list[str] = []
    defaults: dict[str, Any] = {
        DELIVERY_FILE: {
            "schema_version": 2,
            "profile": WORKFLOW_PROFILE,
            "task_id": meta["task_id"],
            "stage": "intake",
            "state": "active",
            "created_at": now,
            "updated_at": now,
            "history": [{"stage": "intake", "event": "initialized", "at": now, "actor": _bounded(actor)}],
        },
        REQUIREMENTS_FILE: {"schema_version": 2, "items": []},
        SUBTASKS_FILE: {"schema_version": 2, "items": []},
        ACCEPTANCE_FILE: {"schema_version": 2, "items": []},
    }
    with FileLock(str(store.lock_file)):
        for filename, payload in defaults.items():
            path = task_dir / filename
            if not path.exists():
                _write_json(path, payload)
                created.append(filename)
            else:
                _read_json(path, {})
        receipts_path = task_dir / VALIDATION_RECEIPTS_FILE
        if not receipts_path.exists():
            receipts_path.touch()
    if touch_activity:
        touch_task_activity(workspace_file, meta["task_id"], "delivery_initialize")
    result = {"initialized": True, "task_id": meta["task_id"], "created": created}
    return {**result, **delivery_workflow_status(workspace_file, meta["task_id"])} if include_status else result


def update_delivery_contract(workspace_file: str | Path, task_id: str, *, kind: str, items: list[dict[str, Any]], actor: str = "") -> dict[str, Any]:
    """Replace one small, schema-checked contract collection by stable IDs."""
    if kind not in {"requirements", "subtasks", "acceptance"}:
        raise ValueError("kind must be requirements, subtasks, or acceptance")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor, include_status=False, touch_activity=False)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    normalized = [_normalize_item(kind, item, index) for index, item in enumerate(items, start=1)]
    ids = [item["id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{kind} contains duplicate ids")
    filename = {"requirements": REQUIREMENTS_FILE, "subtasks": SUBTASKS_FILE, "acceptance": ACCEPTANCE_FILE}[kind]
    with FileLock(str(store.lock_file)):
        _atomic_write_json(task_dir / filename, {"schema_version": 2, "items": normalized, "updated_at": _now(), "actor": _bounded(actor)})
    _append_history(store, task_dir, event=f"{kind}_updated", actor=actor, details={"count": len(normalized)})
    touch_task_activity(workspace_file, meta["task_id"], f"delivery_{kind}")
    return {"updated": True, "task_id": meta["task_id"], "kind": kind, "items": normalized, "delivery": delivery_workflow_status(workspace_file, meta["task_id"])}


def update_delivery_subtask_status(workspace_file: str | Path, task_id: str, subtask_id: str, status: str, *, actor: str = "") -> dict[str, Any]:
    normalized_status = status.strip().lower()
    if normalized_status not in SUBTASK_STATUSES:
        raise ValueError(f"unknown subtask status: {status}")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor, include_status=False, touch_activity=False)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    with FileLock(str(store.lock_file)):
        payload = _read_json(task_dir / SUBTASKS_FILE, {"schema_version": 2, "items": []})
        items = list(payload.get("items", []))
        for item in items:
            if str(item.get("id", "")) == subtask_id:
                item["status"] = normalized_status
                item["updated_at"] = _now()
                item["actor"] = _bounded(actor)
                break
        else:
            raise ValueError(f"unknown subtask: {subtask_id}")
        _atomic_write_json(task_dir / SUBTASKS_FILE, {"schema_version": 2, "items": items, "updated_at": _now()})
    _append_history(store, task_dir, event="subtask_status", actor=actor, details={"subtask_id": subtask_id, "status": normalized_status})
    touch_task_activity(workspace_file, meta["task_id"], "delivery_subtask_status")
    return {"updated": True, "task_id": meta["task_id"], "subtask_id": subtask_id, "status": normalized_status, "delivery": delivery_workflow_status(workspace_file, meta["task_id"])}


def record_delivery_validation(workspace_file: str | Path, task_id: str, *, status: str, summary: str = "", command: str = "", exit_code: int | None = None, acceptance_ids: list[str] | None = None, evidence_refs: list[str] | None = None, actor: str = "", actor_source: str = "core", evidence_kind: str = "recorded_external") -> dict[str, Any]:
    """Record bounded external evidence; supplied commands are never executed."""
    normalized_status = status.strip().lower()
    if normalized_status not in VALIDATION_STATUSES:
        raise ValueError(f"unknown validation status: {status}")
    normalized_kind = evidence_kind.strip().lower()
    if normalized_kind not in EVIDENCE_KINDS - {"executor"}:
        raise ValueError("evidence_kind must be recorded_external or manual_verified")
    normalized_actor = _bounded(actor)
    if normalized_kind == "manual_verified" and not normalized_actor:
        raise ValueError("actor is required for manual_verified evidence")
    normalized_acceptance_ids = _require_string_list(acceptance_ids, "acceptance_ids")
    normalized_evidence_refs = _require_string_list(evidence_refs, "evidence_refs")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor, include_status=False, touch_activity=False)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    receipt = {
        "receipt_id": f"vr-{uuid4().hex[:12]}",
        "recorded_at": _now(),
        "status": normalized_status,
        "command": _bounded(command, 500),
        "exit_code": exit_code,
        "summary": _bounded(summary, 2000),
        "evidence_kind": normalized_kind,
        "acceptance_ids": _bounded_refs(normalized_acceptance_ids),
        "evidence_refs": _bounded_refs(normalized_evidence_refs),
        "actor": normalized_actor,
        "reported_actor": normalized_actor,
        "actor_source": _bounded(actor_source, 80) or "core",
        "identity_assurance": "self_asserted",
    }
    if normalized_kind == "manual_verified":
        canonical_ref = f"delivery-validation:{_task_evidence_ref(meta['task_id'])}:{receipt['receipt_id']}"
        receipt["evidence_refs"] = _bounded_refs([
            canonical_ref,
            *receipt["evidence_refs"],
        ])
    with FileLock(str(store.lock_file)):
        _ensure_delivery_receipt_index(store, task_dir, acquire_lock=False)
        with (task_dir / VALIDATION_RECEIPTS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _index_delivery_receipts(store, task_dir, [receipt])
    _append_history(store, task_dir, event="validation_recorded", actor=actor, details={"receipt_id": receipt["receipt_id"], "status": normalized_status, "evidence_kind": normalized_kind})
    touch_task_activity(workspace_file, meta["task_id"], "delivery_validation")
    return {"recorded": True, "task_id": meta["task_id"], "receipt": receipt, "delivery": delivery_workflow_status(workspace_file, meta["task_id"])}


def delivery_policy_status(workspace_file: str | Path) -> dict[str, Any]:
    """Return the bounded workspace policy used by delivery gates and executor."""
    store = WorkspaceStore(workspace_file)
    path = store.artifacts_dir / DELIVERY_POLICY_FILE
    value = _read_json(path, _default_policy())
    return _normalize_policy(value)


def update_delivery_policy(workspace_file: str | Path, policy: dict[str, Any], *, actor: str = "") -> dict[str, Any]:
    """Persist a reviewed profile policy. Profiles contain argv, never shell text."""
    store = WorkspaceStore(workspace_file)
    normalized = _normalize_policy(policy)
    normalized["updated_at"] = _now()
    normalized["actor"] = _bounded(actor)
    with FileLock(str(store.lock_file)):
        _write_json(store.artifacts_dir / DELIVERY_POLICY_FILE, normalized)
    return {"updated": True, "policy": normalized}


def execute_delivery_validation(workspace_file: str | Path, task_id: str, *, profile_id: str, acceptance_ids: list[str] | None = None, actor: str = "") -> dict[str, Any]:
    """Run one pre-registered argv profile and create cryptographically linked evidence."""
    policy = delivery_policy_status(workspace_file)
    profile = next((item for item in policy["validation_profiles"] if item["id"] == profile_id), None)
    if profile is None:
        return {"executed": False, "reason": "profile_not_allowed", "profile_id": profile_id, "next_action": "先由工作区维护者在 delivery-policy.json 注册验证 profile。"}
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    normalized_acceptance_ids = _require_string_list(acceptance_ids, "acceptance_ids")
    timeout = int(profile["timeout_sec"])
    try:
        completed = subprocess.run(profile["argv"], cwd=load_workspace_config(workspace_file).root, capture_output=True, text=True, timeout=timeout, check=False)
        output = (completed.stdout + "\n" + completed.stderr).strip()[:8192]
        status = "passed" if completed.returncode == 0 else "failed"
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()[:8192]
        status, completed, timed_out = "failed", None, True
    except (OSError, UnicodeError) as exc:
        return {
            "executed": False,
            "reason": "environment_error",
            "profile_id": profile_id,
            "error_type": type(exc).__name__,
            "next_action": "检查验证 profile 的可执行文件、工作目录、权限和输出编码后重试。",
        }
    digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
    receipt_id = f"vr-{uuid4().hex[:12]}"
    evidence_path = task_dir / "verification-evidence" / f"{receipt_id}.json"
    evidence_path.parent.mkdir(exist_ok=True)
    evidence = {"schema_version": 1, "receipt_id": receipt_id, "profile_id": profile_id, "argv": profile["argv"], "timeout_sec": timeout, "status": status, "exit_code": None if timed_out else completed.returncode, "timed_out": timed_out, "output_sha256": digest, "output_excerpt": output, "recorded_at": _now()}
    _write_json(evidence_path, evidence)
    receipt = {"receipt_id": receipt_id, "recorded_at": evidence["recorded_at"], "status": status, "command": profile_id, "exit_code": evidence["exit_code"], "summary": _bounded(output, 2000), "evidence_kind": "executor", "acceptance_ids": _bounded_refs(normalized_acceptance_ids), "evidence_refs": [f"delivery-evidence:{receipt_id}"], "actor": _bounded(actor), "profile_id": profile_id, "output_sha256": digest, "timed_out": timed_out}
    with FileLock(str(store.lock_file)):
        _ensure_delivery_receipt_index(store, task_dir, acquire_lock=False)
        with (task_dir / VALIDATION_RECEIPTS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _index_delivery_receipts(store, task_dir, [receipt])
    _append_history(store, task_dir, event="validation_executed", actor=actor, details={"receipt_id": receipt_id, "profile_id": profile_id, "status": status, "timed_out": timed_out})
    touch_task_activity(workspace_file, meta["task_id"], "delivery_validation_execute")
    return {"executed": True, "task_id": meta["task_id"], "receipt": receipt, "evidence_path": str(evidence_path), "delivery": delivery_workflow_status(workspace_file, meta["task_id"])}


def propose_delivery_breakdown(workspace_file: str | Path, task_id: str, *, source_refs: list[str], summary: str = "") -> dict[str, Any]:
    """Produce a deterministic, non-writing breakdown candidate from bounded input.

    Enhanced to check index freshness and suggest targeted refresh when stale.
    """
    store = WorkspaceStore(workspace_file)
    _, meta = _resolve_task_dir(store, task_id)
    terms = _search_terms(summary)
    config = load_workspace_config(workspace_file)
    modules = [service.name for service in config.services]
    freshness_hint = _breakdown_freshness_hint(workspace_file)
    ambiguities: list[str] = []
    if not source_refs:
        ambiguities.append("请确认需求范围和验收标准。")
    if freshness_hint.get("stale"):
        ambiguities.append(f"索引可能过期（{freshness_hint.get('stale_count', 0)} 个文件），建议先执行定向刷新再定位代码目标。")
    return {
        "task_id": meta["task_id"],
        "applied": False,
        "source_refs": _bounded_refs(source_refs),
        "freshness": freshness_hint,
        "candidate": {
            "id": "REQ-1",
            "title": _bounded(summary, 160) or "待确认需求",
            "scope": "待人工确认",
            "out_of_scope": [],
            "source_refs": _bounded_refs(source_refs),
            "evidence_refs": _bounded_refs(source_refs),
            "search_terms": terms,
            "candidate_modules": modules[:20],
            "ambiguities": ambiguities,
            "decision_required": not bool(source_refs) or bool(freshness_hint.get("stale")),
        },
        "next_action": "确认候选后通过 delivery-contract 写入 requirements，并补齐 acceptance。" + (" 索引较旧，建议先执行 reindex 或定向刷新。" if freshness_hint.get("stale") else ""),
    }


def delivery_matrix(workspace_file: str | Path, task_id: str, *, write: bool = True) -> dict[str, Any]:
    """Derive the requirement-to-evidence matrix and human-readable TECH_SPEC from task contracts."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    requirements, subtasks, acceptance, receipts = (_items(task_dir / REQUIREMENTS_FILE), _items(task_dir / SUBTASKS_FILE), _items(task_dir / ACCEPTANCE_FILE), _recent_receipts(store, task_dir, trusted_passed_only=True))
    verified = _verified_acceptance_ids(receipts, task_dir)
    rows = []
    for requirement in requirements:
        requirement_id = str(requirement.get("id", ""))
        linked_subtasks = [item for item in subtasks if requirement_id in item.get("requirement_ids", [])]
        required_acceptance = [item for item in acceptance if str(item.get("id", "")) in requirement.get("acceptance_ids", [])]
        rows.append({"requirement_id": requirement_id, "title": requirement.get("title", ""), "scope": requirement.get("scope", ""), "out_of_scope": requirement.get("out_of_scope", []), "source_refs": requirement.get("source_refs", []), "ambiguities": requirement.get("ambiguities", []), "subtasks": [{"id": item.get("id", ""), "status": item.get("status", ""), "code_targets": item.get("code_targets", []), "read_targets": item.get("read_targets", []), "write_targets": item.get("write_targets", []), "stop_conditions": item.get("stop_conditions", [])} for item in linked_subtasks], "acceptance": [{"id": item.get("id", ""), "title": item.get("title", ""), "verified": str(item.get("id", "")) in verified} for item in required_acceptance]})
    scoped_subtasks = [item for item in subtasks if item.get("read_targets") and item.get("write_targets") and item.get("stop_conditions")]
    payload = {"schema_version": 2, "task_id": meta["task_id"], "generated_at": _now(), "rows": rows, "coverage": {"requirements": len(requirements), "located_requirements": sum(bool(row["subtasks"]) for row in rows), "scoped_subtasks": len(scoped_subtasks), "total_subtasks": len(subtasks), "verified_acceptance": len(verified), "required_acceptance": sum(bool(item.get("required", True)) for item in acceptance)}}
    if write:
        with FileLock(str(store.lock_file)):
            _atomic_write_json(task_dir / DELIVERY_MATRIX_FILE, payload)
            _atomic_write_text(task_dir / TECH_SPEC_FILE, _tech_spec_markdown(meta, payload))
    return {"generated": write, "matrix": payload, "path": str(task_dir / DELIVERY_MATRIX_FILE), "tech_spec_path": str(task_dir / TECH_SPEC_FILE)}


def transition_delivery_stage(workspace_file: str | Path, task_id: str, stage: str, *, actor: str = "", force: bool = False) -> dict[str, Any]:
    """Move one stage forward only after the preceding contract gate passes."""
    target = stage.strip().lower()
    if target not in STAGES:
        raise ValueError(f"unknown delivery stage: {stage}")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor, include_status=False, touch_activity=False)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    with FileLock(str(store.lock_file)):
        delivery = _read_json(task_dir / DELIVERY_FILE, {})
        current = str(delivery.get("stage", "intake"))
        if STAGES.index(target) < STAGES.index(current):
            raise ValueError("delivery stage cannot move backwards")
        gate = _gate_for_target(store, task_dir, target, task_id=str(meta["task_id"]), sync_lock=False)
        waived = not gate["passed"] and _has_approved_waiver_for_gate(task_dir, gate["code"])
        _record_gate_result(task_dir, task_id=meta["task_id"], target=target, gate=gate, actor=actor, forced=force or waived)
        if not gate["passed"] and not force and not waived:
            return {"transitioned": False, "task_id": meta["task_id"], "from_stage": current, "target_stage": target, "gate": gate, "next_action": gate["next_action"] + (" 已有生效 waiver 可跳过此门禁。" if waived and not force else "")}
        if target != current:
            event_kind = "transitioned" if gate["passed"] else ("waived_transition" if waived else "forced_transition")
            delivery["stage"] = target
            delivery["state"] = "done" if target == "close" else "active"
            delivery["updated_at"] = _now()
            delivery.setdefault("history", []).append({"stage": target, "event": event_kind, "at": _now(), "actor": _bounded(actor), "gate": gate["code"]})
            delivery["history"] = delivery["history"][-200:]
            _atomic_write_json(task_dir / DELIVERY_FILE, delivery)
    if target == "close" and target != current:
        update_task_status(workspace_file, meta["task_id"], "done", source="delivery_transition")
    touch_task_activity(workspace_file, meta["task_id"], "delivery_transition")
    return {"transitioned": True, "task_id": meta["task_id"], "from_stage": current, "stage": target, "gate": gate, "delivery": delivery_workflow_status(workspace_file, meta["task_id"])}


def delivery_workflow_status(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    if not (task_dir / DELIVERY_FILE).exists():
        return {"initialized": False, "task_id": meta["task_id"], "next_action": "初始化需求交付工作流。"}
    delivery = _read_json(task_dir / DELIVERY_FILE, {})
    stage = str(delivery.get("stage", "intake"))
    next_stage = STAGES[min(STAGES.index(stage) + 1, len(STAGES) - 1)]
    requirements = _items(task_dir / REQUIREMENTS_FILE)
    subtasks = _items(task_dir / SUBTASKS_FILE)
    acceptance = _items(task_dir / ACCEPTANCE_FILE)
    gate = _gate_for_target(store, task_dir, next_stage, task_id=str(meta["task_id"])) if stage != "close" else {"passed": True, "code": "complete", "next_action": "任务已完成。", "missing": []}
    receipts = _recent_receipts(store, task_dir, limit=100)
    verified_acceptance = _indexed_verified_acceptance_ids(store, task_dir, str(meta["task_id"]))
    return {
        "initialized": True,
        "profile": delivery.get("profile", WORKFLOW_PROFILE),
        "task_id": meta["task_id"],
        "stage": stage,
        "state": delivery.get("state", "active"),
        "next_stage": next_stage if stage != "close" else "",
        "gate": gate,
        "counts": {"requirements": len(requirements), "subtasks": len(subtasks), "acceptance": len(acceptance), "validation_receipts": store.memory_backend().delivery_receipt_count(task_dir.name), "verified_acceptance": len(verified_acceptance)},
        "stage_history": list(delivery.get("history", []))[-12:],
        "recent_validation_receipts": receipts[-5:],
        "next_action": gate["next_action"],
    }


def delivery_skill_candidate(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    """Create a bounded, reviewable Skill candidate from one proven delivery."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    status = delivery_workflow_status(workspace_file, task_id)
    requirements = _items(task_dir / REQUIREMENTS_FILE)
    subtasks = _items(task_dir / SUBTASKS_FILE)
    acceptance = _items(task_dir / ACCEPTANCE_FILE)
    receipts = _recent_receipts(store, task_dir, trusted_passed_only=True)
    passed = [
        row
        for row in receipts
        if row.get("status") == "passed"
        and row.get("evidence_kind") in {"executor", "manual_verified"}
        and _receipt_has_resolvable_evidence(task_dir, row)
    ]
    required_ids = {str(item.get("id", "")) for item in acceptance if bool(item.get("required", True))}
    passed_ids = {identifier for row in passed for identifier in row.get("acceptance_ids", [])}
    missing = sorted(required_ids - passed_ids)
    located = [item for item in subtasks if item.get("code_targets")]
    eligible = status.get("state") == "done" and not missing and bool(located) and bool(passed)
    score = min(100, 35 + min(25, len(requirements) * 5) + min(25, len(located) * 5) + min(15, len(passed) * 3)) if eligible else 0
    signature = _skill_signature(requirements, located, acceptance)
    contract = _default_skill_contract(workspace_file, subtasks, signature, acceptance)
    registry = _read_skill_registry(store)
    similar = _similar_skills(signature, registry.get("skills", []))
    candidate = {
        "schema_version": 3,
        "candidate_id": f"delivery-skill-{meta['task_id']}",
        "skill_id": _skill_id(meta["task_id"]),
        "task_id": meta["task_id"],
        "title": str(meta.get("title", "")),
        "created_at": _now(),
        "eligible": eligible,
        "quality_score": score,
        "lifecycle": "candidate",
        "version": 1,
        "signature": signature,
        "contract": contract,
        "evidence_refs": _bounded_refs([ref for row in passed for ref in row.get("evidence_refs", [])]),
        "similar_skills": similar,
        "recommended_disposition": "merge" if similar and similar[0]["similarity"] >= 0.8 else "add",
        "missing": missing,
        "requirements": [{"id": item["id"], "title": item["title"], "scope": item.get("scope", "")} for item in requirements[:30]],
        "code_targets": [target for item in located for target in item.get("code_targets", [])][:80],
        "acceptance": [{"id": item["id"], "title": item["title"], "verification_type": item.get("verification_type", "test")} for item in acceptance[:30]],
        "validation": [
            {
                "receipt_id": row.get("receipt_id", ""),
                "evidence_kind": row.get("evidence_kind", ""),
                "evidence_refs": _bounded_refs(row.get("evidence_refs", [])),
                "summary": str(row.get("summary", ""))[:500],
                "acceptance_ids": row.get("acceptance_ids", [])[:30],
            }
            for row in passed[-20:]
        ],
    }
    path = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR / f"{meta['task_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(path, candidate)
    return {"generated": True, "candidate": candidate, "path": str(path), "next_action": "eligible 时先执行 delivery-skill-canary；否则先补齐缺失验收或定位证据。"}


def publish_delivery_skill(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    """Publish a canary only after objective, referenced observations pass."""
    store = WorkspaceStore(workspace_file)
    candidate_path = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR / f"{task_id}.json"
    if not candidate_path.exists():
        return {"published": False, "reason": "candidate_not_found", "next_action": "先执行 delivery-skill-candidate。"}
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not candidate.get("eligible"):
        return {"published": False, "reason": "candidate_not_eligible", "missing": candidate.get("missing", []), "next_action": "补齐交付门禁后重新生成候选。"}
    contract = _normalize_skill_contract(candidate.get("contract"))
    if not _skill_contract_valid(contract):
        return {"published": False, "reason": "skill_contract_invalid", "contract": contract, "next_action": "通过 delivery-skill-contract-update 声明适用、禁止、验收证据、停止、回滚和输入输出契约。"}
    if not _candidate_acceptance_evidence_matches(store, candidate, contract):
        return {"published": False, "reason": "candidate_acceptance_evidence_missing", "acceptance_evidence": contract["acceptance_evidence"], "next_action": "补充与契约匹配的真实验证回执和证据引用后重新生成候选。"}
    with FileLock(str(store.lock_file)):
        registry = _read_skill_registry(store)
        skill = _registry_skill(registry, str(candidate.get("skill_id", "")))
        if not skill or skill.get("lifecycle") != "canary":
            return {"published": False, "reason": "canary_required", "next_action": "先执行 delivery-skill-canary，再记录带证据引用的真实使用结果。"}
        if _skill_contract_hash(contract) != _skill_contract_hash(_normalize_skill_contract(skill.get("contract"))):
            return {
                "published": False,
                "reason": "candidate_contract_outdated",
                "next_action": "候选契约与当前灰度契约不一致；请重新生成候选并重新灰度，避免以不同契约复用证据。",
            }
        evaluation = evaluate_delivery_skill(workspace_file, skill_id=str(skill["skill_id"]))
        metrics = evaluation["metrics"]
        minimum_verified = int(contract["replay_policy"]["minimum_verified_passed"])
        if metrics["verified_passed"] < minimum_verified or metrics["redacted_replays"] < minimum_verified or metrics["failed"] > 0:
            return {"published": False, "reason": "canary_evidence_insufficient", "metrics": metrics, "minimum_verified_passed": minimum_verified, "next_action": f"至少记录 {minimum_verified} 条带证据引用的成功观测和脱敏 replay，且没有失败后再发布。"}
        slug = _skill_slug(str(candidate.get("skill_id", "delivery-skill")))
        path = store.artifacts_dir / DELIVERY_SKILL_PUBLISHED_DIR / slug / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, _delivery_skill_markdown(candidate))
        manifest_path = path.parent / "manifest.json"
        published_at = _now()
        _atomic_write_json(manifest_path, {"schema_version": 3, "skill_id": skill["skill_id"], "task_id": candidate["task_id"], "candidate_id": candidate["candidate_id"], "quality_score": candidate["quality_score"], "version": skill["version"], "published_at": published_at, "evidence_refs": skill.get("evidence_refs", []), "contract": contract, "replay_set": _skill_replay_path(store, str(skill["skill_id"])).name})
        skill.update({"lifecycle": "published", "contract": contract, "published_at": published_at, "updated_at": published_at, "published_path": str(path)})
        _write_skill_registry(store, registry, changed_skill_ids={str(skill["skill_id"])}, lock=False)
    from memory_center.core.knowledge.assets import AssetRegistryCorruptionError, register_collaboration_asset

    asset_payload: dict[str, Any] = {}
    asset_registered = False
    asset_diagnostic: dict[str, str] = {}
    try:
        asset = register_collaboration_asset(
            workspace_file,
            kind="skill",
            title=str(skill.get("title", "Delivery Skill")),
            owner=str(skill.get("actor", "")) or "workspace-owner",
            source_ref=f"skill:{skill['skill_id']}",
            metadata={"skill_id": skill["skill_id"], "contract": contract, "evidence_refs": skill.get("evidence_refs", [])[:30]},
            context_excerpt="已发布交付 Skill：读取其契约、停止条件和验证证据后再使用。",
            asset_id=f"asset-skill-{_skill_slug(str(skill['skill_id']))}",
            actor=str(skill.get("actor", "")) or "workspace-owner",
        )
        asset_payload = asset["asset"]
        asset_registered = True
    except (OSError, ValueError, PermissionError, AssetRegistryCorruptionError) as exc:
        asset_diagnostic = {"error_type": type(exc).__name__, "recovery_action": "artifact asset-sync"}
    next_action = (
        "已进入默认检索范围；持续记录效果，失败时执行 delivery-skill-rollback。"
        if asset_registered
        else "Skill 已发布；执行 artifact asset-sync 补齐协作资产，并持续记录效果。"
    )
    return {"published": True, "skill_id": skill["skill_id"], "task_id": candidate["task_id"], "quality_score": candidate["quality_score"], "path": str(path), "metrics": metrics, "asset_registered": asset_registered, "asset": asset_payload, "asset_diagnostic": asset_diagnostic, "next_action": next_action}


def delivery_skill_status(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    candidate = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR / f"{task_id}.json"
    payload = _read_json(candidate, {}) if candidate.exists() else {}
    skill = _registry_skill(_read_skill_registry(store), str(payload.get("skill_id", ""))) if payload else None
    published = str(skill.get("published_path", "")) if skill else ""
    lifecycle = str(skill.get("lifecycle", "candidate")) if skill else "candidate"
    next_actions = {
        "candidate": "delivery-skill-canary",
        "canary": "delivery-skill-observe",
        "published": "use_published_skill",
        "rolled_back": "delivery-skill-canary",
        "rejected": "delivery-skill-candidate",
        "superseded": "delivery-skill-candidate",
    }
    next_action = "delivery-skill-candidate" if not candidate.exists() else next_actions.get(lifecycle, "delivery-skill-status")
    return {"task_id": task_id, "candidate": str(candidate) if candidate.exists() else "", "published_skill": published, "skill_id": str(payload.get("skill_id", "")), "lifecycle": lifecycle, "contract": _normalize_skill_contract((skill or payload).get("contract")), "replay": delivery_skill_replay_set(workspace_file, skill_id=str(payload.get("skill_id", "")), limit=20), "next_action": next_action}


def update_delivery_skill_contract(workspace_file: str | Path, task_id: str, *, contract: dict[str, Any], actor: str = "") -> dict[str, Any]:
    """为一个已生成候选声明可评测 Skill 契约，并同步活跃 canary。"""
    store = WorkspaceStore(workspace_file)
    candidate_path = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR / f"{task_id}.json"
    if not candidate_path.exists():
        return {"updated": False, "reason": "candidate_not_found", "next_action": "先执行 delivery-skill-candidate，再声明契约。"}
    normalized = _normalize_skill_contract(contract)
    if not _skill_contract_valid(normalized):
        return {"updated": False, "reason": "skill_contract_invalid", "contract": normalized, "next_action": "至少声明适用条件、禁止条件、验收证据、停止条件、回滚方式和输入输出字段。"}
    with FileLock(str(store.lock_file)):
        candidate = _read_json(candidate_path, {})
        registry = _read_skill_registry(store)
        skill = _registry_skill(registry, str(candidate.get("skill_id", "")))
        if skill and skill.get("lifecycle") == "published":
            return {
                "updated": False,
                "reason": "published_skill_contract_immutable",
                "skill_id": str(candidate.get("skill_id", "")),
                "next_action": "已发布 Skill 的契约不可原地修改；请从新的已验证交付生成候选并重新灰度。",
            }
        contract_changed = _normalize_skill_contract(candidate.get("contract")) != normalized
        candidate["contract"] = normalized
        candidate["updated_at"] = _now()
        candidate["contract_actor"] = _bounded(actor)
        _atomic_write_json(candidate_path, candidate)
        if skill and skill.get("lifecycle") == "canary":
            skill.update({
                "contract": normalized,
                "contract_revision": int(skill.get("contract_revision", 1)) + int(contract_changed),
                "contract_updated_at": _now(),
                "updated_at": _now(),
                "actor": _bounded(actor),
            })
            canary_path_value = str(skill.get("canary_path", ""))
            if canary_path_value:
                canary_path = Path(canary_path_value)
                canary_path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write_text(canary_path, _delivery_skill_markdown(candidate))
            _write_skill_registry(store, registry, changed_skill_ids={str(skill["skill_id"])}, lock=False)
    return {
        "updated": True,
        "task_id": task_id,
        "skill_id": str(candidate.get("skill_id", "")),
        "contract": normalized,
        "next_action": "契约已更新；当前契约需要重新积累 canary 证据，使用 delivery-skill-observe 自动生成脱敏 replay。",
    }


def delivery_skill_replay_set(workspace_file: str | Path, *, skill_id: str, limit: int = 100) -> dict[str, Any]:
    """读取某个 Skill 的脱敏 replay 集，不读取需求、源码、日志或工具正文。"""
    store = WorkspaceStore(workspace_file)
    skill = _registry_skill(_read_skill_registry(store), skill_id)
    contract_hash = _skill_contract_hash(_normalize_skill_contract(skill.get("contract"))) if skill else ""
    activation_id = str((skill or {}).get("activation_id", ""))
    rows = _recent_skill_replays(
        store,
        skill_id=skill_id,
        contract_hash=contract_hash,
        activation_id=activation_id,
        limit=limit,
    )
    return {
        "skill_id": skill_id,
        "contract_sha256": contract_hash,
        "replays": rows,
        "count": len(rows),
        "privacy": "仅包含契约哈希、语言、结果、证据引用、时延和 token 指标；不包含源码、需求正文、日志、工具正文或操作人。",
        "next_action": "将 replay 用于离线评测和人工复核；不得直接据此自动发布或调权。",
    }


def start_delivery_skill_canary(workspace_file: str | Path, task_id: str, *, actor: str = "") -> dict[str, Any]:
    """Explicitly expose one eligible candidate to a bounded shadow/canary cohort."""
    store = WorkspaceStore(workspace_file)
    candidate_path = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR / f"{task_id}.json"
    if not candidate_path.exists():
        return {"started": False, "reason": "candidate_not_found", "next_action": "先执行 delivery-skill-candidate。"}
    with FileLock(str(store.lock_file)):
        candidate = _read_json(candidate_path, {})
        if not candidate.get("eligible"):
            return {"started": False, "reason": "candidate_not_eligible", "next_action": "补齐交付门禁后重新生成候选。"}
        registry = _read_skill_registry(store)
        skill_id = str(candidate.get("skill_id", ""))
        existing = _registry_skill(registry, skill_id)
        if existing and existing.get("lifecycle") in {"canary", "published"}:
            return {"started": False, "reason": "already_active", "skill": existing, "next_action": "记录观测或查看效果评估。"}
        if candidate.get("recommended_disposition") == "merge":
            return {"started": False, "reason": "merge_review_required", "similar_skills": candidate.get("similar_skills", []), "next_action": "先人工确认是否合并，避免重复 Skill 进入灰度。"}
        now = _now()
        contract = _normalize_skill_contract(candidate.get("contract"))
        if not _skill_contract_valid(contract):
            return {"started": False, "reason": "skill_contract_invalid", "contract": contract, "next_action": "先通过 delivery-skill-contract-update 补齐 Skill 契约。"}
        if not _candidate_acceptance_evidence_matches(store, candidate, contract):
            return {"started": False, "reason": "candidate_acceptance_evidence_missing", "acceptance_evidence": contract["acceptance_evidence"], "next_action": "补充与验收证据契约匹配的真实回执后再进入 canary。"}
        activation_id = f"activation-{uuid4().hex[:16]}"
        skill_payload = {"schema_version": 3, "skill_id": skill_id, "task_id": task_id, "candidate_id": candidate.get("candidate_id", ""), "title": _bounded(str(candidate.get("title", "")), 160), "lifecycle": "canary", "version": int((existing or {}).get("version", 0)) + 1, "activation_id": activation_id, "signature": candidate.get("signature", {}), "contract": contract, "contract_revision": 1, "evidence_refs": _bounded_refs(candidate.get("evidence_refs", [])), "created_at": (existing or {}).get("created_at", now), "updated_at": now, "canary_started_at": now, "actor": _bounded(actor), "lifecycle_history": list((existing or {}).get("lifecycle_history", []))[-20:]}
        if existing:
            existing.clear()
            existing.update(skill_payload)
            skill = existing
        else:
            skill = skill_payload
            registry.setdefault("skills", []).append(skill)
        canary_path = store.artifacts_dir / DELIVERY_SKILL_CANARY_DIR / _skill_slug(skill_id) / "SKILL.md"
        canary_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(canary_path, _delivery_skill_markdown(candidate))
        skill["canary_path"] = str(canary_path)
        _write_skill_registry(store, registry, changed_skill_ids={skill_id}, lock=False)
    return {"started": True, "skill": skill, "path": str(canary_path), "next_action": "在真实相似任务中以 shadow/canary 方式使用，并用 delivery-skill-observe 记录结果。"}


def record_delivery_skill_observation(workspace_file: str | Path, skill_id: str, *, outcome: str, evidence_refs: list[str] | None = None, latency_ms: int | None = None, token_count: int | None = None, actor: str = "") -> dict[str, Any]:
    """Append a privacy-safe, evidence-referenced Skill outcome observation."""
    normalized = outcome.strip().lower()
    if normalized not in SKILL_OUTCOMES:
        raise ValueError(f"unknown skill outcome: {outcome}")
    store = WorkspaceStore(workspace_file)
    skill = _registry_skill(_read_skill_registry(store), skill_id)
    if not skill or skill.get("lifecycle") not in {"canary", "published"}:
        return {"recorded": False, "reason": "skill_not_active", "next_action": "只能为 canary 或 published Skill 记录观测。"}
    refs = _bounded_refs(evidence_refs)
    if normalized == "passed" and not refs:
        return {"recorded": False, "reason": "evidence_required", "next_action": "成功观测必须提供验证证据引用，不能用模型自评替代。"}
    resolved_refs = _resolved_delivery_evidence_refs(store, refs, source_task_id=str(skill.get("task_id", "")))
    if normalized == "passed" and len(resolved_refs) != len(refs):
        return {
            "recorded": False,
            "reason": "evidence_not_resolvable",
            "invalid_evidence_refs": [ref for ref in refs if ref not in resolved_refs],
            "next_action": "使用 delivery-validation:<task-ref>:<receipt-id> 或当前任务执行器生成的 delivery-evidence 引用。",
        }
    with FileLock(str(store.lock_file)):
        skill = _registry_skill(_read_skill_registry(store), skill_id)
        if not skill or skill.get("lifecycle") not in {"canary", "published"}:
            return {"recorded": False, "reason": "skill_not_active", "next_action": "只能为 canary 或 published Skill 记录观测。"}
        contract_hash = _skill_contract_hash(_normalize_skill_contract(skill.get("contract")))
        activation_id = str(skill.get("activation_id", ""))
        used_refs = {
            ref
            for existing in _recent_skill_observations(store)
            if existing.get("skill_id") == skill_id
            and existing.get("contract_sha256") == contract_hash
            and existing.get("activation_id", "") == activation_id
            and existing.get("outcome") == "passed"
            for ref in existing.get("evidence_refs", [])
        }
        if normalized == "passed" and used_refs.intersection(resolved_refs):
            return {"recorded": False, "reason": "evidence_already_used", "next_action": "每条成功观测必须引用新的真实验证回执。"}
        row = {"schema_version": 3, "observation_id": f"sobs-{uuid4().hex[:12]}", "skill_id": skill_id, "activation_id": activation_id, "contract_sha256": contract_hash, "outcome": normalized, "evidence_refs": resolved_refs if normalized == "passed" else refs, "latency_ms": _bounded_metric(latency_ms), "token_count": _bounded_metric(token_count), "actor": _bounded(actor), "observed_at": _now()}
        row["replay"] = _skill_replay_row(skill, row)
        with (store.artifacts_dir / DELIVERY_SKILL_OBSERVATIONS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return {"recorded": True, "observation": row, "metrics": evaluate_delivery_skill(workspace_file, skill_id=skill_id)["metrics"]}


def evaluate_delivery_skill(workspace_file: str | Path, *, skill_id: str = "") -> dict[str, Any]:
    """Read bounded observations; evaluation never changes lifecycle automatically."""
    store = WorkspaceStore(workspace_file)
    rows = [row for row in _recent_skill_observations(store) if not skill_id or row.get("skill_id") == skill_id]
    skill = _registry_skill(_read_skill_registry(store), skill_id) if skill_id else None
    contract_hash = _skill_contract_hash(_normalize_skill_contract(skill.get("contract"))) if skill else ""
    if contract_hash:
        rows = [row for row in rows if row.get("contract_sha256") == contract_hash]
    activation_id = str((skill or {}).get("activation_id", ""))
    if activation_id:
        rows = [row for row in rows if row.get("activation_id", "") == activation_id]
    outcomes = {name: sum(row.get("outcome") == name for row in rows) for name in SKILL_OUTCOMES}
    source_task_id = str((skill or {}).get("task_id", ""))
    observation_refs = list(dict.fromkeys(
        str(ref).strip()[:240]
        for row in rows
        for ref in row.get("evidence_refs", [])
        if str(ref).strip()
    ))[:10_000]
    resolvable_refs = set(_resolved_delivery_evidence_refs(store, observation_refs, source_task_id=source_task_id))
    verified_passed = sum(
        row.get("outcome") == "passed"
        and bool(row.get("evidence_refs"))
        and set(row.get("evidence_refs", [])) <= resolvable_refs
        for row in rows
    )
    measured_latency = [int(row["latency_ms"]) for row in rows if isinstance(row.get("latency_ms"), int)]
    measured_tokens = [int(row["token_count"]) for row in rows if isinstance(row.get("token_count"), int)]
    replay_rows = _recent_skill_replays(
        store,
        skill_id=skill_id,
        contract_hash=contract_hash,
        activation_id=activation_id,
    )
    metrics = {"observations": len(rows), **outcomes, "verified_passed": verified_passed, "redacted_replays": len(replay_rows), "success_rate": round(outcomes["passed"] / max(1, outcomes["passed"] + outcomes["failed"]), 4), "bypass_rate": round(outcomes["bypassed"] / max(1, len(rows)), 4), "avg_latency_ms": round(sum(measured_latency) / len(measured_latency), 2) if measured_latency else None, "avg_token_count": round(sum(measured_tokens) / len(measured_tokens), 2) if measured_tokens else None}
    contract = _normalize_skill_contract((skill or {}).get("contract"))
    minimum_verified = int(contract["replay_policy"]["minimum_verified_passed"])
    publishable = bool(
        skill
        and _skill_contract_valid(contract)
        and metrics["verified_passed"] >= minimum_verified
        and metrics["redacted_replays"] >= minimum_verified
        and metrics["failed"] == 0
    )
    return {
        "skill_id": skill_id,
        "activation_id": activation_id,
        "metrics": metrics,
        "minimum_verified_passed": minimum_verified,
        "publishable": publishable,
        "recommendation": "可以发布" if publishable else "继续灰度并记录真实验证证据",
    }


def rollback_delivery_skill(workspace_file: str | Path, skill_id: str, *, reason: str, actor: str = "") -> dict[str, Any]:
    """Remove a published Skill from default recommendation without deleting evidence."""
    store = WorkspaceStore(workspace_file)
    with FileLock(str(store.lock_file)):
        registry = _read_skill_registry(store)
        skill = _registry_skill(registry, skill_id)
        if not skill or skill.get("lifecycle") not in {"canary", "published"}:
            return {"rolled_back": False, "reason": "skill_not_active", "next_action": "只能回滚当前 canary 或 published Skill。"}
        skill.setdefault("lifecycle_history", []).append({"lifecycle": skill.get("lifecycle", ""), "activation_id": skill.get("activation_id", ""), "ended_at": _now(), "reason": _bounded(reason, 500)})
        skill["lifecycle_history"] = skill["lifecycle_history"][-20:]
        skill.update({"lifecycle": "rolled_back", "rollback_reason": _bounded(reason, 500), "updated_at": _now(), "actor": _bounded(actor)})
        _write_skill_registry(store, registry, changed_skill_ids={skill_id}, lock=False)
    return {"rolled_back": True, "skill": skill, "next_action": "历史观测和证据仍保留；需要修订时从新的已验证交付生成候选。"}


def recommend_delivery_skills(workspace_file: str | Path, intent: str, *, language: str = "", limit: int = 5) -> dict[str, Any]:
    """Retrieve only published Skills using bounded structural token overlap."""
    store = WorkspaceStore(workspace_file)
    query_terms = set(_search_terms(intent))
    matches = []
    skipped_invalid_contract = 0
    for skill in _read_skill_registry(store).get("skills", []):
        if skill.get("lifecycle") != "published":
            continue
        contract = _normalize_skill_contract(skill.get("contract"))
        if not _skill_contract_valid(contract):
            skipped_invalid_contract += 1
            continue
        if language.strip() and language.strip().lower() not in {item.lower() for item in contract["languages"]}:
            continue
        terms = set(skill.get("signature", {}).get("terms", []))
        overlap = len(query_terms & terms) / max(1, len(query_terms | terms))
        if overlap:
            matches.append({"skill_id": skill.get("skill_id", ""), "title": skill.get("title", ""), "version": skill.get("version", 1), "score": round(overlap, 4), "path": skill.get("published_path", ""), "languages": contract["languages"], "applicability_conditions": contract["applicability_conditions"], "prohibited_conditions": contract["prohibited_conditions"], "preconditions": contract["preconditions"], "acceptance_evidence": contract["acceptance_evidence"], "stop_conditions": contract["stop_conditions"], "rollback": contract["rollback"], "evidence_refs": skill.get("evidence_refs", [])[:10]})
    matches.sort(key=lambda item: (-item["score"], item["skill_id"]))
    next_action = (
        "先迁移或重新生成无完整边界契约的已发布 Skill；有效 Skill 可继续使用。"
        if skipped_invalid_contract
        else "读取命中的 published Skill；没有命中时按正常交付流程处理，不得把空结果理解为不存在经验。"
    )
    return {"intent_terms": sorted(query_terms)[:20], "language": _bounded(language, 80), "skills": matches[:max(1, min(limit, 20))], "skipped_invalid_contract": skipped_invalid_contract, "next_action": next_action}


def derive_delivery_failure_candidates(workspace_file: str | Path, *, limit_tasks: int = 200) -> dict[str, Any]:
    """Offline-only failure clustering; stores no validation summaries or source text."""
    store = WorkspaceStore(workspace_file)
    groups: dict[str, dict[str, Any]] = {}
    task_root = store.artifacts_dir / "tasks"
    for task_dir in sorted((path for path in task_root.glob("*") if path.is_dir()), key=lambda path: path.name)[-max(1, min(limit_tasks, 500)):]:
        for receipt in _recent_receipts(store, task_dir):
            if receipt.get("status") != "failed":
                continue
            profile = _bounded(str(receipt.get("profile_id") or receipt.get("command") or "external"), 80)
            acceptance = sorted(_bounded_refs(receipt.get("acceptance_ids", [])))
            key = hashlib.sha256((profile + "|" + ",".join(acceptance)).encode("utf-8")).hexdigest()[:16]
            row = groups.setdefault(key, {"pattern_id": f"failure-{key}", "profile_id": profile, "acceptance_ids": acceptance, "task_refs": [], "evidence_refs": []})
            row["task_refs"].append(hashlib.sha256(task_dir.name.encode("utf-8")).hexdigest()[:12])
            row["evidence_refs"].extend(_bounded_refs(receipt.get("evidence_refs", [])))
    candidates = []
    for row in groups.values():
        support = len(set(row["task_refs"]))
        if support < 2:
            continue
        candidates.append({"schema_version": 1, "pattern_id": row["pattern_id"], "profile_id": row["profile_id"], "acceptance_ids": row["acceptance_ids"], "support": support, "task_refs": sorted(set(row["task_refs"]))[:50], "evidence_refs": _bounded_refs(row["evidence_refs"]), "proposed_action": "先检查验证 profile、环境和验收范围；确认根因后再形成可审核的反模式或修复 Skill。"})
    candidates.sort(key=lambda row: (-row["support"], row["pattern_id"]))
    payload = {"schema_version": 1, "generated_at": _now(), "candidates": candidates[:100], "privacy": "仅保存哈希任务引用、验证 profile、验收标识和证据引用；不保存原始日志、源码或需求正文。"}
    _write_json(store.artifacts_dir / DELIVERY_SKILL_FAILURES_FILE, payload)
    return {"generated": True, "path": str(store.artifacts_dir / DELIVERY_SKILL_FAILURES_FILE), **payload}


def synthesize_delivery_skill_trajectories(workspace_file: str | Path, *, min_support: int = 3) -> dict[str, Any]:
    """Offline horizontal synthesis across proven candidates, never on query hot paths."""
    store = WorkspaceStore(workspace_file)
    clusters: dict[str, list[dict[str, Any]]] = {}
    candidates_dir = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR
    for path in candidates_dir.glob("*.json"):
        candidate = _read_json(path, {})
        if not candidate.get("eligible"):
            continue
        terms = candidate.get("signature", {}).get("terms", [])
        key = hashlib.sha256("|".join(terms[:8]).encode("utf-8")).hexdigest()[:16]
        clusters.setdefault(key, []).append(candidate)
    syntheses = []
    for key, candidates in clusters.items():
        if len(candidates) < max(2, min_support):
            continue
        common_targets = sorted(set.intersection(*(set(item.get("code_targets", [])) for item in candidates))) if candidates else []
        syntheses.append({"schema_version": 1, "synthesis_id": f"synthesis-{key}", "support": len(candidates), "candidate_refs": [str(item.get("candidate_id", "")) for item in candidates][:50], "terms": candidates[0].get("signature", {}).get("terms", [])[:20], "common_code_targets": common_targets[:30], "invariant": "多个独立且已验证交付共享相同结构特征；仅作为候选经验，需人工审核后才可形成 Skill。"})
    payload = {"schema_version": 1, "generated_at": _now(), "min_support": max(2, min_support), "syntheses": sorted(syntheses, key=lambda row: (-row["support"], row["synthesis_id"]))[:100], "execution": "offline_only"}
    _write_json(store.artifacts_dir / DELIVERY_SKILL_SYNTHESIS_FILE, payload)
    return {"generated": True, "path": str(store.artifacts_dir / DELIVERY_SKILL_SYNTHESIS_FILE), **payload}


def create_delivery_waiver(workspace_file: str | Path, task_id: str, *, gate_code: str, reason: str, expires_at: str = "", actor: str = "") -> dict[str, Any]:
    """Create a pending waiver for one gate failure; requires explicit approval before it takes effect."""
    normalized_gate = _bounded(gate_code, 80)
    if not normalized_gate:
        raise ValueError("gate_code is required")
    normalized_reason = _bounded(reason, 500)
    if not normalized_reason:
        raise ValueError("reason is required")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor, include_status=False, touch_activity=False)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    waiver_id = f"waiver-{uuid4().hex[:12]}"
    now = _now()
    waiver = {
        "waiver_id": waiver_id,
        "task_id": meta["task_id"],
        "gate_code": normalized_gate,
        "status": "pending",
        "reason": normalized_reason,
        "expires_at": _bounded(expires_at, 80) if expires_at else "",
        "created_at": now,
        "approved_at": "",
        "revoked_at": "",
        "actor": _bounded(actor),
    }
    with FileLock(str(store.lock_file)):
        with (task_dir / WAIVER_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(waiver, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    _append_history(store, task_dir, event="waiver_created", actor=actor, details={"waiver_id": waiver_id, "gate_code": normalized_gate})
    touch_task_activity(workspace_file, meta["task_id"], "delivery_waiver")
    return {"created": True, "waiver_id": waiver_id, "waiver": waiver, "next_action": "Waiver 已创建，状态为 pending；通过 approve-delivery-waiver 审批后才可生效。"}


def approve_delivery_waiver(workspace_file: str | Path, task_id: str, *, waiver_id: str, actor: str = "") -> dict[str, Any]:
    """Approve one pending waiver so the associated gate can be bypassed."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    waivers = _read_waivers(task_dir)
    target = next((w for w in waivers if w.get("waiver_id") == waiver_id), None)
    if target is None:
        return {"approved": False, "reason": "waiver_not_found", "next_action": "确认 waiver_id 是否正确。"}
    if target.get("status") != "pending":
        return {"approved": False, "reason": f"waiver_already_{target['status']}", "next_action": f"Waiver 已为 {target['status']} 状态，不可重复审批。"}
    if _waiver_expired(target):
        target["status"] = "expired"
        return {"approved": False, "reason": "waiver_expired", "waiver": target, "next_action": "Waiver 已过期，需创建新的。"}
    target["status"] = "approved"
    target["approved_at"] = _now()
    target["approver"] = _bounded(actor)
    _write_waivers(task_dir, waivers)
    _append_history(store, task_dir, event="waiver_approved", actor=actor, details={"waiver_id": waiver_id})
    return {"approved": True, "waiver_id": waiver_id, "waiver": target, "next_action": "Waiver 已生效；可尝试重新推进被豁免的门禁阶段。"}


def revoke_delivery_waiver(workspace_file: str | Path, task_id: str, *, waiver_id: str, reason: str = "", actor: str = "") -> dict[str, Any]:
    """Revoke an approved or pending waiver."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    waivers = _read_waivers(task_dir)
    target = next((w for w in waivers if w.get("waiver_id") == waiver_id), None)
    if target is None:
        return {"revoked": False, "reason": "waiver_not_found"}
    if target.get("status") in {"expired", "revoked"}:
        return {"revoked": False, "reason": f"waiver_already_{target['status']}"}
    target["status"] = "revoked"
    target["revoked_at"] = _now()
    target["revoke_reason"] = _bounded(reason, 300)
    target["revoker"] = _bounded(actor)
    _write_waivers(task_dir, waivers)
    _append_history(store, task_dir, event="waiver_revoked", actor=actor, details={"waiver_id": waiver_id})
    return {"revoked": True, "waiver_id": waiver_id, "waiver": target, "next_action": "Waiver 已撤销；相关门禁需重新满足。"}


def list_delivery_waivers(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    """List all waivers for one task, with expired ones auto-marked."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    waivers = _read_waivers(task_dir)
    changed = False
    for waiver in waivers:
        if waiver.get("status") == "approved" and _waiver_expired(waiver):
            waiver["status"] = "expired"
            changed = True
    if changed:
        _write_waivers(task_dir, waivers)
    active = [w for w in waivers if w.get("status") in {"pending", "approved"}]
    return {"task_id": meta["task_id"], "total": len(waivers), "active": active, "all": waivers[-50:]}


def classify_delivery_failure(workspace_file: str | Path, task_id: str, *, receipt_id: str = "", failure_type: str = "", context: str = "", actor: str = "") -> dict[str, Any]:
    """Classify one delivery failure into one of four actionable categories.

    Categories:
    - auto_repairable: retry or rollback then continue
    - environment_blocked: environment/dependency/permission issue
    - requirement_path_error: requirement scope or code target is wrong
    - human_decision_required: beyond automatic handling
    """
    normalized_type = _bounded(failure_type, 80).lower()
    category = _classify_failure_category(normalized_type, context)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    classification = {
        "classification_id": f"fc-{uuid4().hex[:12]}",
        "task_id": meta["task_id"],
        "receipt_id": _bounded(receipt_id, 80),
        "category": category,
        "description": FAILURE_CATEGORIES[category],
        "input_type": normalized_type,
        "context": _bounded(context, 500),
        "classified_at": _now(),
        "actor": _bounded(actor),
        "retry_allowed": category == "auto_repairable",
        "max_retries": delivery_policy_status(workspace_file).get("retry_limits", {}).get("auto_repair", 2) if category == "auto_repairable" else 0,
    }
    with FileLock(str(store.lock_file)):
        with (task_dir / FAILURE_CLASSIFICATION_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(classification, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    _append_history(store, task_dir, event="failure_classified", actor=actor, details={"category": category, "receipt_id": _bounded(receipt_id, 80)})
    return {"classified": True, "classification": classification, "next_action": classification["description"]}


def delivery_task_metrics(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    """Compute task-level effectiveness metrics from delivery artifacts.

    Metrics: requirement coverage, location coverage, acceptance coverage,
    verification success rate, human block rate, stage duration, suggestion bypass rate.
    """
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    requirements = _items(task_dir / REQUIREMENTS_FILE)
    subtasks = _items(task_dir / SUBTASKS_FILE)
    acceptance = _items(task_dir / ACCEPTANCE_FILE)
    receipts = _recent_receipts(store, task_dir, limit=500)
    gate_results = _read_gate_results(task_dir)
    waivers = _read_waivers(task_dir)
    classifications = _read_classifications(task_dir)
    requirements_count = len(requirements)
    located_requirements = sum(1 for req in requirements if any(
        str(req.get("id", "")) in sub.get("requirement_ids", [])
        for sub in subtasks if sub.get("code_targets")
    ))
    acceptance_count = sum(1 for item in acceptance if item.get("required", True))
    verified_acceptance = len(_indexed_verified_acceptance_ids(store, task_dir, str(meta["task_id"])))
    passed_receipts = sum(1 for r in receipts if r.get("status") == "passed")
    failed_receipts = sum(1 for r in receipts if r.get("status") == "failed")
    total_receipts = passed_receipts + failed_receipts
    forced_gates = sum(1 for g in gate_results if g.get("forced"))
    total_gates = len(gate_results)
    approved_waivers = sum(1 for w in waivers if w.get("status") == "approved")
    auto_repair_count = sum(1 for c in classifications if c.get("category") == "auto_repairable")
    env_blocked_count = sum(1 for c in classifications if c.get("category") == "environment_blocked")
    requirement_error_count = sum(1 for c in classifications if c.get("category") == "requirement_path_error")
    human_decision_count = sum(1 for c in classifications if c.get("category") == "human_decision_required")
    stage_history = []
    delivery = _read_json(task_dir / DELIVERY_FILE, {})
    for entry in delivery.get("history", []):
        if entry.get("event") == "transitioned":
            stage_history.append({"stage": entry.get("stage", ""), "at": entry.get("at", "")})
    return {
        "task_id": meta["task_id"],
        "generated_at": _now(),
        "coverage": {
            "requirements": requirements_count,
            "located_requirements": located_requirements,
            "requirement_coverage": round(located_requirements / max(1, requirements_count), 4),
            "acceptance": acceptance_count,
            "verified_acceptance": verified_acceptance,
            "acceptance_coverage": round(verified_acceptance / max(1, acceptance_count), 4),
        },
        "verification": {
            "total_receipts": total_receipts,
            "passed": passed_receipts,
            "failed": failed_receipts,
            "success_rate": round(passed_receipts / max(1, total_receipts), 4),
        },
        "gates": {
            "total_gates": total_gates,
            "forced_transitions": forced_gates,
            "approved_waivers": approved_waivers,
            "force_rate": round(forced_gates / max(1, total_gates), 4),
        },
        "failure_classification": {
            "auto_repairable": auto_repair_count,
            "environment_blocked": env_blocked_count,
            "requirement_path_error": requirement_error_count,
            "human_decision_required": human_decision_count,
        },
        "stage_timeline": stage_history[-20:],
    }


def _breakdown_freshness_hint(workspace_file: str | Path) -> dict[str, Any]:
    """Return a bounded freshness hint for the breakdown candidate."""
    try:
        from .freshness.targeted_refresh import hot_refresh_status
        status = hot_refresh_status(workspace_file)
        dirty_count = len(status.get("dirty_paths", []))
        return {"stale": dirty_count > 0, "stale_count": dirty_count, "detail": "hot_refresh" if dirty_count else "fresh"}
    except Exception:
        return {"stale": False, "stale_count": 0, "detail": "unknown"}


def _classify_failure_category(failure_type: str, context: str) -> str:
    """Map a failure type string to one of the four actionable categories."""
    lower_type = failure_type.lower()
    lower_context = context.lower()
    combined = lower_type + " " + lower_context
    if any(keyword in combined for keyword in ("timeout", "retry", "transient", "flaky", "network")):
        return "auto_repairable"
    if any(keyword in combined for keyword in ("permission", "dependency", "environment", "config", "missing_binary", "os_error")):
        return "environment_blocked"
    if any(keyword in combined for keyword in ("wrong_target", "scope_mismatch", "not_found", "stale_index", "requirement_error")):
        return "requirement_path_error"
    return "human_decision_required"


def _read_waivers(task_dir: Path) -> list[dict[str, Any]]:
    path = task_dir / WAIVER_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict) and value.get("waiver_id"):
                rows.append(value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return rows


def _write_waivers(task_dir: Path, waivers: list[dict[str, Any]]) -> None:
    path = task_dir / WAIVER_FILE
    content = "\n".join(json.dumps(w, ensure_ascii=False) for w in waivers) + "\n" if waivers else ""
    _atomic_write_text(path, content)


def _waiver_expired(waiver: dict[str, Any]) -> bool:
    expires_at = waiver.get("expires_at", "")
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def _read_gate_results(task_dir: Path) -> list[dict[str, Any]]:
    path = task_dir / GATE_RESULTS_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return rows


def _read_classifications(task_dir: Path) -> list[dict[str, Any]]:
    path = task_dir / FAILURE_CLASSIFICATION_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    return rows


def _has_approved_waiver_for_gate(task_dir: Path, gate_code: str) -> bool:
    """Check if there is an approved, non-expired waiver for the given gate code."""
    waivers = _read_waivers(task_dir)
    return any(
        w.get("gate_code") == gate_code
        and w.get("status") == "approved"
        and not _waiver_expired(w)
        for w in waivers
    )


def _read_skill_registry(store: WorkspaceStore) -> dict[str, Any]:
    path = store.artifacts_dir / DELIVERY_SKILL_REGISTRY_FILE
    backup = path.with_name(f"{path.name}.bak")
    primary = _parse_skill_registry(path)
    if primary is not None:
        return primary
    recovered = _parse_skill_registry(backup)
    if recovered is not None:
        _atomic_write_json(path, recovered)
        return recovered
    if path.exists() or backup.exists():
        raise DeliverySkillRegistryCorruptionError("delivery Skill registry and backup are both invalid")
    return {"schema_version": 2, "skills": []}


def _write_skill_registry(store: WorkspaceStore, registry: dict[str, Any], *, changed_skill_ids: set[str] | None = None, lock: bool = True) -> None:
    registry["schema_version"] = 2
    registry["updated_at"] = _now()
    deduplicated: dict[str, dict[str, Any]] = {}
    for item in registry.get("skills", []):
        if isinstance(item, dict) and item.get("skill_id") and item.get("lifecycle") in SKILL_LIFECYCLES:
            deduplicated[str(item["skill_id"])] = item
    registry["skills"] = list(deduplicated.values())[-500:]
    if lock:
        with FileLock(str(store.lock_file)):
            _write_skill_registry(store, registry, changed_skill_ids=changed_skill_ids, lock=False)
        return
    path = store.artifacts_dir / DELIVERY_SKILL_REGISTRY_FILE
    backup = path.with_name(f"{path.name}.bak")
    current = _parse_skill_registry(path)
    if path.exists() and current is None:
        current = _parse_skill_registry(backup)
        if current is None:
            raise DeliverySkillRegistryCorruptionError("refusing to overwrite an invalid delivery Skill registry")
    if current is not None:
        _atomic_write_json(backup, current)
        if changed_skill_ids is not None:
            merged = {
                str(item["skill_id"]): item
                for item in current.get("skills", [])
                if isinstance(item, dict) and item.get("skill_id")
            }
            incoming = {
                str(item["skill_id"]): item
                for item in registry.get("skills", [])
                if isinstance(item, dict) and item.get("skill_id")
            }
            for skill_id in changed_skill_ids:
                if skill_id in incoming:
                    merged[skill_id] = incoming[skill_id]
                else:
                    merged.pop(skill_id, None)
            registry["skills"] = list(merged.values())[-500:]
    _atomic_write_json(path, registry)


def _registry_skill(registry: dict[str, Any], skill_id: str) -> dict[str, Any] | None:
    return next((item for item in reversed(registry.get("skills", [])) if item.get("skill_id") == skill_id), None)


def _parse_skill_registry(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("skills"), list):
        return None
    return {**value, "skills": [item for item in value["skills"] if isinstance(item, dict)]}


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _recent_skill_observations(store: WorkspaceStore) -> list[dict[str, Any]]:
    path = store.artifacts_dir / DELIVERY_SKILL_OBSERVATIONS_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in _read_jsonl_tail(path, 10_000):
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeliveryArtifactCorruptionError(f"delivery observation log is invalid: {path.name}") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _default_skill_contract(
    workspace_file: str | Path,
    subtasks: list[dict[str, Any]],
    signature: dict[str, Any],
    acceptance: list[dict[str, Any]],
) -> dict[str, Any]:
    config = load_workspace_config(workspace_file)
    languages = sorted({service.resolved_language() for service in config.services if service.resolved_language()})
    stop_conditions = [
        str(condition)
        for item in subtasks
        for condition in item.get("stop_conditions", [])
        if str(condition).strip()
    ]
    return _normalize_skill_contract({
        "languages": languages or ["unknown"],
        "preconditions": [
            "需求、范围和验收标准已明确。",
            "代码目标已定位且索引未标记为 STALE。",
        ],
        "applicability_conditions": [
            "任务语言、目标范围和验收模式与已验证交付相符。",
            "该流程已在至少三次带证据的真实使用中稳定通过后才可发布。",
        ],
        "prohibited_conditions": [
            "一次性探索、未定位代码目标或需求边界不清时不得使用。",
            "禁止把源码、密钥、外部工具正文或未验证结论作为输入输出。",
        ],
        "acceptance_evidence": {
            "accepted_kinds": ["executor", "manual_verified"],
            "required_fields": ["acceptance_ids", "evidence_refs"],
        },
        "stop_conditions": stop_conditions or [
            "出现未决歧义、索引陈旧、越出声明语言范围或缺少验证证据时停止并重新分析。",
        ],
        "rollback": {
            "triggers": ["出现失败观测", "验收证据失效", "适用边界被违反"],
            "action": "立即执行 delivery-skill-rollback，并回退到常规交付流程。",
        },
        "input_contract": {
            "required_fields": ["intent", "task_id", "acceptance_ids"],
            "optional_fields": ["target", "project", "evidence_refs"],
            "forbidden_fields": ["raw_source", "secret", "external_tool_body"],
        },
        "output_contract": {
            "required_fields": ["requirements", "subtasks", "acceptance", "validation_evidence", "next_action"],
            "forbidden_fields": ["raw_source", "secret", "unverified_fact"],
        },
        "replay_policy": {
            "redacted": True,
            "max_samples": 200,
            "minimum_verified_passed": 3,
            "signature_terms": len(signature.get("terms", [])),
            "verification_types": signature.get("verification_types", [])[:10],
        },
    })


def _normalize_skill_contract(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    input_raw = raw.get("input_contract", {}) if isinstance(raw.get("input_contract"), dict) else {}
    output_raw = raw.get("output_contract", {}) if isinstance(raw.get("output_contract"), dict) else {}
    replay_raw = raw.get("replay_policy", {}) if isinstance(raw.get("replay_policy"), dict) else {}
    evidence_raw = raw.get("acceptance_evidence", {}) if isinstance(raw.get("acceptance_evidence"), dict) else {}
    rollback_raw = raw.get("rollback", {}) if isinstance(raw.get("rollback"), dict) else {}
    return {
        "schema_version": 2,
        "languages": _bounded_string_list(raw.get("languages"), 20, 40),
        "applicability_conditions": _bounded_string_list(raw.get("applicability_conditions"), 20, 300),
        "prohibited_conditions": _bounded_string_list(raw.get("prohibited_conditions"), 20, 300),
        "preconditions": _bounded_string_list(raw.get("preconditions"), 20, 300),
        "stop_conditions": _bounded_string_list(raw.get("stop_conditions"), 20, 300),
        "input_contract": _normalize_io_contract(input_raw),
        "output_contract": _normalize_io_contract(output_raw),
        "acceptance_evidence": {
            "accepted_kinds": [item.lower() for item in _bounded_string_list(evidence_raw.get("accepted_kinds"), 10, 80)],
            "required_fields": _bounded_string_list(evidence_raw.get("required_fields"), 10, 80),
        },
        "rollback": {
            "triggers": _bounded_string_list(rollback_raw.get("triggers"), 20, 300),
            "action": _bounded(str(rollback_raw.get("action", "")), 300),
        },
        "replay_policy": {
            "redacted": bool(replay_raw.get("redacted", True)),
            "max_samples": min(500, max(1, _safe_int(replay_raw.get("max_samples"), 200))),
            "minimum_verified_passed": min(10, max(1, _safe_int(replay_raw.get("minimum_verified_passed"), 3))),
        },
    }


def _normalize_io_contract(value: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "required_fields": _bounded_string_list(value.get("required_fields"), 30, 80),
        "optional_fields": _bounded_string_list(value.get("optional_fields"), 30, 80),
        "forbidden_fields": _bounded_string_list(value.get("forbidden_fields"), 30, 80),
    }


def _skill_contract_valid(contract: dict[str, Any]) -> bool:
    evidence_policy = contract.get("acceptance_evidence", {})
    allowed_receipt_fields = {"receipt_id", "evidence_kind", "evidence_refs", "summary", "acceptance_ids"}
    return bool(
        contract.get("languages")
        and "unknown" not in {str(item).lower() for item in contract.get("languages", [])}
        and contract.get("applicability_conditions")
        and contract.get("prohibited_conditions")
        and contract.get("preconditions")
        and contract.get("stop_conditions")
        and contract.get("input_contract", {}).get("required_fields")
        and contract.get("output_contract", {}).get("required_fields")
        and evidence_policy.get("accepted_kinds")
        and set(evidence_policy["accepted_kinds"]) <= {"executor", "manual_verified"}
        and evidence_policy.get("required_fields")
        and set(evidence_policy["required_fields"]) <= allowed_receipt_fields
        and contract.get("rollback", {}).get("triggers")
        and contract.get("rollback", {}).get("action")
        and bool(contract.get("replay_policy", {}).get("redacted"))
    )


def _candidate_acceptance_evidence_matches(store: WorkspaceStore, candidate: dict[str, Any], contract: dict[str, Any]) -> bool:
    """Require a real candidate receipt compatible with the declared evidence policy."""

    accepted_kinds = set(contract.get("acceptance_evidence", {}).get("accepted_kinds", []))
    required_fields = set(contract.get("acceptance_evidence", {}).get("required_fields", []))
    for receipt in candidate.get("validation", []) or []:
        if str(receipt.get("evidence_kind", "")) not in accepted_kinds:
            continue
        present_fields = {name for name, value in receipt.items() if value}
        refs = _bounded_refs(receipt.get("evidence_refs", []))
        if required_fields <= present_fields and _resolved_delivery_evidence_refs(store, refs, source_task_id=str(candidate.get("task_id", ""))):
            return True
    return False


def _resolved_delivery_evidence_refs(store: WorkspaceStore, refs: Any, *, source_task_id: str = "") -> list[str]:
    """Return only references backed by a passed validation receipt in this workspace."""

    resolved: list[str] = []
    task_root = (store.artifacts_dir / "tasks").resolve()
    task_dirs_by_ref = {
        _task_evidence_ref(path.name): path
        for path in task_root.iterdir()
        if path.is_dir()
    } if task_root.is_dir() else {}
    receipt_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    values = refs if isinstance(refs, list) else []
    normalized_refs = list(dict.fromkeys(str(ref).strip()[:240] for ref in values if str(ref).strip()))[:10_000]
    for ref in normalized_refs:
        task_id = ""
        task_ref = ""
        receipt_id = ""
        if ref.startswith("delivery-validation:"):
            parts = ref.split(":", 2)
            if len(parts) == 3:
                _, task_ref, receipt_id = parts
                task_id = task_dirs_by_ref.get(task_ref, Path()).name
        elif ref.startswith("delivery-evidence:") and source_task_id:
            task_id, receipt_id = source_task_id, ref.split(":", 1)[1]
        if not task_id or not receipt_id:
            continue
        task_dir = (task_root / task_id).resolve()
        if task_dir.parent != task_root or not task_dir.is_dir():
            continue
        cache_key = (task_id, receipt_id)
        if cache_key not in receipt_cache:
            rows = _recent_receipts(store, task_dir, receipt_ids=[receipt_id])
            receipt_cache[cache_key] = next(
                (row for row in rows if row.get("receipt_id") == receipt_id and row.get("status") == "passed"),
                None,
            )
        receipt = receipt_cache[cache_key]
        if receipt is None:
            continue
        receipt_refs = _bounded_refs(receipt.get("evidence_refs", []))
        if ref.startswith("delivery-validation:"):
            if receipt.get("evidence_kind") != "manual_verified" or ref not in receipt_refs:
                continue
        elif (
            receipt.get("evidence_kind") != "executor"
            or ref not in receipt_refs
            or not (task_dir / "verification-evidence" / f"{receipt_id}.json").is_file()
        ):
            continue
        resolved.append(ref)
    return resolved


def _task_evidence_ref(task_id: str) -> str:
    return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:16]


def _skill_replay_row(skill: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    contract = _normalize_skill_contract(skill.get("contract"))
    if not _skill_contract_valid(contract):
        return {}
    skill_id = str(skill.get("skill_id", ""))
    contract_hash = _skill_contract_hash(contract)
    return {
        "schema_version": 3,
        "replay_id": f"sreplay-{uuid4().hex[:12]}",
        "observation_id": str(observation.get("observation_id", "")),
        "skill_id": skill_id,
        "activation_id": str(skill.get("activation_id", "")),
        "contract_sha256": contract_hash,
        "languages": contract["languages"],
        "outcome": observation.get("outcome", ""),
        "evidence_refs": _bounded_refs(observation.get("evidence_refs", [])),
        "latency_ms": observation.get("latency_ms"),
        "token_count": observation.get("token_count"),
        "observed_at": observation.get("observed_at", ""),
        "privacy": "redacted_contract_metrics_only",
    }


def _recent_skill_replays(
    store: WorkspaceStore,
    *,
    skill_id: str,
    contract_hash: str = "",
    activation_id: str = "",
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    if not skill_id:
        return []
    bounded_limit = max(1, min(limit, 10_000))

    def matches(row: dict[str, Any]) -> bool:
        return bool(
            row.get("privacy") == "redacted_contract_metrics_only"
            and (not contract_hash or row.get("contract_sha256") == contract_hash)
            and (not activation_id or row.get("activation_id", "") == activation_id)
        )

    rows = [
        replay
        for observation in _recent_skill_observations(store)
        if observation.get("skill_id") == skill_id
        and isinstance((replay := observation.get("replay")), dict)
        and matches(replay)
    ]
    observation_ids = {str(row.get("observation_id", "")) for row in rows if row.get("observation_id")}
    path = _skill_replay_path(store, skill_id)
    if path.exists():
        for line in _read_jsonl_tail(path, 10_000):
            try:
                row = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DeliveryArtifactCorruptionError(f"delivery replay log is invalid: {path.name}") from exc
            if (
                isinstance(row, dict)
                and matches(row)
                and str(row.get("observation_id", "")) not in observation_ids
            ):
                rows.append(row)
    return rows[-bounded_limit:]


def _read_jsonl_tail(path: Path, limit: int) -> list[str]:
    if limit <= 0 or not path.exists():
        return []
    block_size = 64 * 1024
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        blocks: list[bytes] = []
        newlines = 0
        while position > 0 and newlines <= limit:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            block = handle.read(read_size)
            blocks.append(block)
            newlines += block.count(b"\n")
    data = b"".join(reversed(blocks))
    if position > 0:
        _, separator, data = data.partition(b"\n")
        if not separator:
            return []
    try:
        return data.decode("utf-8").splitlines()[-limit:]
    except UnicodeDecodeError as exc:
        raise DeliveryArtifactCorruptionError(f"delivery JSONL is not UTF-8: {path.name}") from exc


def _skill_replay_path(store: WorkspaceStore, skill_id: str) -> Path:
    return store.artifacts_dir / DELIVERY_SKILL_REPLAYS_DIR / f"{_skill_slug(skill_id)}.jsonl"


def _skill_contract_hash(contract: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(contract, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def _bounded_string_list(value: Any, limit: int, item_limit: int) -> list[str]:
    values = value if isinstance(value, list) else []
    return list(dict.fromkeys(_bounded(str(item), item_limit) for item in values if str(item).strip()))[:limit]


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _skill_id(task_id: str) -> str:
    return f"dskill-{hashlib.sha256(task_id.encode('utf-8')).hexdigest()[:16]}"


def _skill_signature(requirements: list[dict[str, Any]], subtasks: list[dict[str, Any]], acceptance: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(
        [str(item.get("title", "")) + " " + str(item.get("scope", "")) for item in requirements]
        + [str(target) for item in subtasks for target in item.get("code_targets", [])]
        + [str(item.get("verification_type", "")) for item in acceptance]
    )
    terms = _search_terms(text)
    return {"terms": terms, "target_kinds": sorted({_bounded(str(target).split("#", 1)[0], 120) for item in subtasks for target in item.get("code_targets", []) if str(target).strip()})[:30], "verification_types": sorted({_bounded(str(item.get("verification_type", "test")), 80) for item in acceptance})[:10]}


def _similar_skills(signature: dict[str, Any], skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source = set(signature.get("terms", []))
    matches = []
    for skill in skills:
        if skill.get("lifecycle") not in {"canary", "published"}:
            continue
        other = set(skill.get("signature", {}).get("terms", []))
        similarity = len(source & other) / max(1, len(source | other))
        if similarity >= 0.35:
            matches.append({"skill_id": skill.get("skill_id", ""), "title": skill.get("title", ""), "lifecycle": skill.get("lifecycle", ""), "similarity": round(similarity, 4)})
    return sorted(matches, key=lambda row: (-row["similarity"], row["skill_id"]))[:5]


def _bounded_metric(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        return min(10_000_000, max(0, int(value)))
    except (TypeError, ValueError):
        return None


def _gate_for_target(
    store: WorkspaceStore,
    task_dir: Path,
    target: str,
    *,
    task_id: str,
    sync_lock: bool = True,
) -> dict[str, Any]:
    requirements = _items(task_dir / REQUIREMENTS_FILE)
    subtasks = _items(task_dir / SUBTASKS_FILE)
    acceptance = _items(task_dir / ACCEPTANCE_FILE)
    if target == "intake":
        return _gate("ready", [], "补充任务目标后进入需求拆解。")
    if target == "breakdown":
        missing = [str(item.get("id", "")) for item in requirements if not item.get("source_refs") or not item.get("scope") or item.get("decision_required")]
        if not requirements:
            missing.append("requirements")
        return _gate("requirements_evidence_required", missing, "先录入带来源、范围、验收关联且不存在未决歧义的需求项。")
    if target == "locate":
        missing = []
        if not requirements:
            missing.append("requirements")
        if not acceptance:
            missing.append("acceptance")
        return _gate("breakdown_contract_required", missing, "补齐需求项与可验证验收标准，再做代码定位。")
    if target == "implement":
        missing = [str(item.get("id", "")) for item in subtasks if not item.get("code_targets")]
        if not subtasks:
            missing.append("subtasks")
        policy = _delivery_scope_policy(task_dir)
        if policy["enforce_scope_contract"]:
            missing.extend(str(item.get("id", "")) for item in subtasks if not item.get("read_targets") or not item.get("write_targets") or not item.get("stop_conditions"))
            return _gate("scoped_subtasks_required", sorted(set(missing)), "为每个子任务补齐已定位代码目标、读范围、写范围和停止条件后再实现。")
        return _gate("located_subtasks_required", missing, "为每个子任务关联已定位的代码目标后再实现；建议同时补齐读范围、写范围和停止条件。")
    if target == "verify":
        missing = [str(item.get("id", "")) for item in subtasks if item.get("status") not in {"implemented", "skipped"}]
        return _gate("implementation_required", missing, "将所有子任务标记为已实现或跳过，并记录原因。")
    required_ids = {str(item.get("id", "")) for item in acceptance if bool(item.get("required", True))}
    passed_ids = _indexed_verified_acceptance_ids(store, task_dir, task_id, acquire_lock=sync_lock)
    return _gate("verified_evidence_required", sorted(required_ids - passed_ids), "执行已注册验证 profile，或记录带证据引用的人工验证，并关联每一项必需验收标准。")


def _gate(code: str, missing: list[str], next_action: str) -> dict[str, Any]:
    return {"passed": not missing, "code": code, "missing": missing[:50], "next_action": "可以推进下一阶段。" if not missing else next_action}


def _normalize_item(kind: str, raw: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{kind} item {index} must be an object")
    item_id = str(raw.get("id", "")).strip() or f"{kind[:3]}-{index}"
    title = str(raw.get("title", "")).strip()
    if not title:
        raise ValueError(f"{kind} item {item_id} requires title")
    base = {"id": item_id, "title": title, "evidence_refs": _bounded_refs(raw.get("evidence_refs", []))}
    if kind == "requirements":
        ambiguities = [_bounded(str(item), 240) for item in raw.get("ambiguities", []) if str(item).strip()][:20] if isinstance(raw.get("ambiguities", []), list) else []
        return {**base, "scope": _bounded(str(raw.get("scope", "")), 1000), "out_of_scope": _bounded_refs(raw.get("out_of_scope", [])), "source_refs": _bounded_refs(raw.get("source_refs", raw.get("evidence_refs", []))), "search_terms": _bounded_refs(raw.get("search_terms", [])), "candidate_modules": _bounded_refs(raw.get("candidate_modules", [])), "acceptance_ids": _bounded_refs(raw.get("acceptance_ids", [])), "ambiguities": ambiguities, "decision_required": bool(raw.get("decision_required", bool(ambiguities))), "status": str(raw.get("status", "planned"))}
    if kind == "subtasks":
        status = str(raw.get("status", "pending")).lower()
        if status not in SUBTASK_STATUSES:
            raise ValueError(f"unknown subtask status: {status}")
        return {**base, "requirement_ids": _bounded_refs(raw.get("requirement_ids", [])), "code_targets": _bounded_refs(raw.get("code_targets", [])), "read_targets": _bounded_refs(raw.get("read_targets", raw.get("code_targets", []))), "write_targets": _bounded_refs(raw.get("write_targets", [])), "stop_conditions": _bounded_refs(raw.get("stop_conditions", [])), "status": status}
    return {**base, "required": bool(raw.get("required", True)), "verification_type": str(raw.get("verification_type", "test")), "status": str(raw.get("status", "pending"))}


def _append_history(store: WorkspaceStore, task_dir: Path, *, event: str, actor: str, details: dict[str, Any]) -> None:
    with FileLock(str(store.lock_file)):
        delivery = _read_json(task_dir / DELIVERY_FILE, {})
        delivery["updated_at"] = _now()
        delivery.setdefault("history", []).append({"stage": delivery.get("stage", "intake"), "event": event, "at": _now(), "actor": _bounded(actor), "details": details})
        delivery["history"] = delivery["history"][-200:]
        _atomic_write_json(task_dir / DELIVERY_FILE, delivery)


def _record_gate_result(task_dir: Path, *, task_id: str, target: str, gate: dict[str, Any], actor: str, forced: bool) -> None:
    row = {"schema_version": 1, "entity_type": "GateResult", "gate_result_id": f"gate-{uuid4().hex[:12]}", "policy_id": "feature_delivery_v2", "task_id": task_id, "stage": target, "passed": bool(gate.get("passed")), "code": gate.get("code", ""), "missing": list(gate.get("missing", []))[:50], "forced": forced, "actor": _bounded(actor), "event_at": _now(), "observed_at": _now()}
    with (task_dir / GATE_RESULTS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _verified_acceptance_ids(receipts: list[dict[str, Any]], task_dir: Path) -> set[str]:
    return {
        str(identifier)
        for row in receipts
        if row.get("status") == "passed"
        and row.get("evidence_kind") in {"executor", "manual_verified"}
        and _receipt_has_resolvable_evidence(task_dir, row)
        for identifier in row.get("acceptance_ids", [])
    }


def _indexed_verified_acceptance_ids(
    store: WorkspaceStore,
    task_dir: Path,
    task_id: str,
    *,
    acquire_lock: bool = True,
) -> set[str]:
    _ensure_delivery_receipt_index(store, task_dir, acquire_lock=acquire_lock)
    rows = store.memory_backend().delivery_verified_acceptance_candidates(
        task_dir.name,
        _task_evidence_ref(task_id),
    )
    return {
        row["acceptance_id"]
        for row in rows
        if row["evidence_kind"] == "manual_verified"
        or (task_dir / "verification-evidence" / f"{row['receipt_id']}.json").is_file()
    }


def _receipt_has_resolvable_evidence(task_dir: Path, receipt: dict[str, Any]) -> bool:
    receipt_id = str(receipt.get("receipt_id", ""))
    refs = _bounded_refs(receipt.get("evidence_refs", []))
    if receipt.get("evidence_kind") == "executor":
        return f"delivery-evidence:{receipt_id}" in refs and (task_dir / "verification-evidence" / f"{receipt_id}.json").is_file()
    expected = f"delivery-validation:{_task_evidence_ref(task_dir.name)}:{receipt_id}"
    return expected in refs


def _default_policy() -> dict[str, Any]:
    return {"schema_version": 2, "policy_id": "feature_delivery_v2", "validation_profiles": [], "retry_limits": {"auto_repair": 2}, "enforce_scope_contract": False, "updated_at": ""}


def _normalize_policy(value: dict[str, Any]) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    profiles: list[dict[str, Any]] = []
    for item in raw.get("validation_profiles", []) if isinstance(raw.get("validation_profiles", []), list) else []:
        if not isinstance(item, dict):
            continue
        profile_id = _bounded(str(item.get("id", "")), 80)
        argv = item.get("argv", [])
        if not profile_id or not isinstance(argv, list) or not argv or not all(isinstance(part, str) and part.strip() for part in argv):
            continue
        profiles.append({"id": profile_id, "argv": [part.strip()[:500] for part in argv][:30], "timeout_sec": min(3600, max(1, int(item.get("timeout_sec", 900)))), "description": _bounded(str(item.get("description", "")), 300)})
    ids = [item["id"] for item in profiles]
    if len(ids) != len(set(ids)):
        raise ValueError("validation profile ids must be unique")
    retries = raw.get("retry_limits", {}) if isinstance(raw.get("retry_limits", {}), dict) else {}
    return {"schema_version": 2, "policy_id": _bounded(str(raw.get("policy_id", "feature_delivery_v2")), 80) or "feature_delivery_v2", "validation_profiles": profiles, "retry_limits": {"auto_repair": min(10, max(0, int(retries.get("auto_repair", 2))))}, "enforce_scope_contract": bool(raw.get("enforce_scope_contract", False)), "updated_at": _bounded(str(raw.get("updated_at", "")), 80), "actor": _bounded(str(raw.get("actor", "")), 120)}


def _delivery_scope_policy(task_dir: Path) -> dict[str, Any]:
    workspace_artifacts = task_dir.parent.parent
    return _normalize_policy(_read_json(workspace_artifacts / DELIVERY_POLICY_FILE, _default_policy()))


def _search_terms(text: str) -> list[str]:
    chunks = [part.strip().lower() for part in text.replace("/", " ").replace("_", " ").replace("-", " ").split()]
    terms = [part[:80] for part in chunks if len(part) >= 2]
    # CJK text commonly has no whitespace. Add bounded two-character terms so
    # a query such as "发布接口" can retrieve a Skill tagged as "发布 接口".
    for chunk in chunks:
        cjk = "".join(char for char in chunk if "\u4e00" <= char <= "\u9fff")
        terms.extend(cjk[index:index + 2] for index in range(max(0, len(cjk) - 1)))
    return list(dict.fromkeys(term for term in terms if len(term) >= 2))[:20]


def _tech_spec_markdown(meta: dict[str, Any], matrix: dict[str, Any]) -> str:
    rows = matrix.get("rows", [])
    body = [f"# {meta.get('title', '需求交付')} / 交付说明", "", "本文件由结构化交付工件派生，请通过 requirements、subtasks、acceptance 和验证回执更新事实。", "", "## 需求与证据", ""]
    for row in rows:
        targets = ", ".join(target for item in row.get("subtasks", []) for target in item.get("code_targets", [])) or "未定位"
        accepted = ", ".join(f"{item.get('id')}={'已验证' if item.get('verified') else '待验证'}" for item in row.get("acceptance", [])) or "未定义"
        body.extend([f"### {row.get('requirement_id')} {row.get('title')}", f"- 范围：{row.get('scope') or '未定义'}", f"- 代码目标：{targets}", f"- 验收：{accepted}"])
        for subtask in row.get("subtasks", []):
            read_targets = ", ".join(subtask.get("read_targets", [])) or "未声明"
            write_targets = ", ".join(subtask.get("write_targets", [])) or "未声明"
            stop_conditions = "; ".join(subtask.get("stop_conditions", [])) or "未声明"
            body.append(f"- 子任务 {subtask.get('id')}: 读范围={read_targets}; 写范围={write_targets}; 停止条件={stop_conditions}")
        if row.get("ambiguities"):
            body.append(f"- 未决事项：{'; '.join(row['ambiguities'])}")
        body.append("")
    coverage = matrix.get("coverage", {})
    body.extend(["## 覆盖率", "", f"- 需求：{coverage.get('requirements', 0)}", f"- 已定位需求：{coverage.get('located_requirements', 0)}", f"- 已声明范围的子任务：{coverage.get('scoped_subtasks', 0)}/{coverage.get('total_subtasks', 0)}", f"- 已验证验收：{coverage.get('verified_acceptance', 0)}/{coverage.get('required_acceptance', 0)}", ""])
    return "\n".join(body)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryArtifactCorruptionError(f"delivery artifact is invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise DeliveryArtifactCorruptionError(f"delivery artifact must be a JSON object: {path.name}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_json(path, value)


def _items(path: Path) -> list[dict[str, Any]]:
    value = _read_json(path, {"items": []}).get("items", [])
    return [item for item in value if isinstance(item, dict)]


def _ensure_delivery_receipt_index(store: WorkspaceStore, task_dir: Path, *, acquire_lock: bool = True) -> None:
    path = task_dir / VALIDATION_RECEIPTS_FILE
    if acquire_lock:
        if _delivery_receipt_index_current(store, task_dir, path):
            return
        with FileLock(str(store.lock_file)):
            _ensure_delivery_receipt_index(store, task_dir, acquire_lock=False)
        return
    if not path.exists():
        store.memory_backend().upsert_delivery_receipts(
            task_dir.name,
            [],
            source_size=0,
            source_mtime_ns=0,
            synced_at=_now(),
        )
        return
    stat = path.stat()
    state = store.memory_backend().delivery_receipt_sync_state(task_dir.name)
    if (
        state["source_size"] == stat.st_size
        and state["source_mtime_ns"] == stat.st_mtime_ns
        and state["projection_version"] == DELIVERY_RECEIPT_PROJECTION_VERSION
    ):
        return

    def rows() -> Any:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise DeliveryArtifactCorruptionError(f"delivery receipt log is invalid: {path.name}") from exc
                if not isinstance(value, dict):
                    raise DeliveryArtifactCorruptionError(f"delivery receipt log contains an invalid row: {path.name}")
                if not str(value.get("receipt_id", "")):
                    value["receipt_id"] = f"legacy-{hashlib.sha256(line.encode('utf-8')).hexdigest()[:16]}"
                    value.setdefault("evidence_kind", "recorded_external")
                yield value

    # Register the snapshot observed before reading. If an uncooperative writer
    # appends concurrently, the next query sees a size/mtime mismatch and repairs it.
    store.memory_backend().replace_delivery_receipts(
        task_dir.name,
        rows(),
        source_size=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        synced_at=_now(),
    )


def _delivery_receipt_index_current(store: WorkspaceStore, task_dir: Path, path: Path) -> bool:
    if not path.exists():
        return False
    stat = path.stat()
    state = store.memory_backend().delivery_receipt_sync_state(task_dir.name)
    return bool(
        state["source_size"] == stat.st_size
        and state["source_mtime_ns"] == stat.st_mtime_ns
        and state["projection_version"] == DELIVERY_RECEIPT_PROJECTION_VERSION
    )


def _index_delivery_receipts(store: WorkspaceStore, task_dir: Path, receipts: list[dict[str, Any]]) -> None:
    path = task_dir / VALIDATION_RECEIPTS_FILE
    stat = path.stat()
    store.memory_backend().upsert_delivery_receipts(
        task_dir.name,
        receipts,
        source_size=stat.st_size,
        source_mtime_ns=stat.st_mtime_ns,
        synced_at=_now(),
    )


def _recent_receipts(
    store: WorkspaceStore,
    task_dir: Path,
    *,
    receipt_ids: list[str] | None = None,
    trusted_passed_only: bool = False,
    limit: int = 0,
) -> list[dict[str, Any]]:
    _ensure_delivery_receipt_index(store, task_dir)
    return store.memory_backend().query_delivery_receipts(
        task_dir.name,
        receipt_ids=receipt_ids,
        trusted_passed_only=trusted_passed_only,
        limit=limit,
    )


def _bounded_refs(value: Any) -> list[str]:
    values = value if isinstance(value, list) else []
    return [str(item).strip()[:240] for item in values if str(item).strip()][:50]


def _require_string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON array")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must contain only strings")
    return value


def _bounded(value: str, limit: int = 120) -> str:
    return value.strip()[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _skill_slug(value: str) -> str:
    return "-".join("".join(char.lower() if char.isalnum() else " " for char in value).split()) or "delivery-skill"


def _delivery_skill_markdown(candidate: dict[str, Any]) -> str:
    targets = "\n".join(f"- `{item}`" for item in candidate.get("code_targets", [])) or "- 先通过 Memory Center 定位代码目标。"
    acceptance = "\n".join(f"- `{item.get('id', '')}` {item.get('title', '')} ({item.get('verification_type', 'test')})" for item in candidate.get("acceptance", [])) or "- 为每项需求定义可验证验收标准。"
    contract = _normalize_skill_contract(candidate.get("contract"))
    languages = ", ".join(contract["languages"]) or "未声明"
    preconditions = "\n".join(f"- {item}" for item in contract["preconditions"]) or "- 未声明"
    applicability = "\n".join(f"- {item}" for item in contract["applicability_conditions"]) or "- 未声明"
    prohibited = "\n".join(f"- {item}" for item in contract["prohibited_conditions"]) or "- 未声明"
    stop_conditions = "\n".join(f"- {item}" for item in contract["stop_conditions"]) or "- 未声明"
    input_fields = ", ".join(contract["input_contract"]["required_fields"]) or "未声明"
    output_fields = ", ".join(contract["output_contract"]["required_fields"]) or "未声明"
    evidence_kinds = ", ".join(contract["acceptance_evidence"]["accepted_kinds"]) or "未声明"
    evidence_fields = ", ".join(contract["acceptance_evidence"]["required_fields"]) or "未声明"
    rollback_triggers = "\n".join(f"- {item}" for item in contract["rollback"]["triggers"]) or "- 未声明"
    return f"""# {candidate.get('title', '已验证需求交付')} / Verified Delivery Skill

## 适用场景 / When to use

当新需求与该已验证交付的范围和代码目标相似时使用。本 Skill 来自已关闭任务及其通过的验证回执，质量分为 `{candidate.get('quality_score', 0)}`。

## 适用与契约 / Applicability and Contract

- 适用语言：`{languages}`
- 必需输入：`{input_fields}`
- 必需输出：`{output_fields}`

### 前置条件

{preconditions}

### 适用条件

{applicability}

### 禁止条件

{prohibited}

### 验收证据

- 可接受证据类型：`{evidence_kinds}`
- 必须包含：`{evidence_fields}`

### 停止条件

{stop_conditions}

### 回滚方式

触发信号：
{rollback_triggers}

处置动作：{contract["rollback"]["action"] or "未声明"}

Skill 观测会自动形成仅含契约哈希、语言、结果、证据引用、时延和 Token 指标的脱敏 replay；不得将源码、需求正文、日志、外部工具正文或密钥写入 replay。

## 执行流程 / Workflow

1. 初始化 `feature_delivery_v2`，录入需求和验收标准。
2. 为每个子任务关联确切 `code_targets` 后再进入实现。
3. 实现完成后记录真实验证回执；每个必需验收项必须有 `passed` 回执。
4. 仅在所有门禁通过后关闭任务，并生成下一轮 Skill 候选。

## 历史代码目标 / Proven Code Targets

{targets}

## 验收清单 / Acceptance Checklist

{acceptance}

## 约束 / Guardrails

- 不将未验证的推断发布为正式经验。
- 不把大段日志或源码写入任务工件；使用证据引用。
- Skill 发布需要显式执行 `artifact delivery-skill-publish`。
"""
