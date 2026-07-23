"""Structured, evidence-first delivery workflow for a task space.

The workflow intentionally owns only delivery state and contracts.  Code
discovery, impact analysis, task artifacts, and verification execution remain
in their existing domains.  This keeps a reusable workflow pack from turning
into a second orchestrator or a project-specific Skill.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from filelock import FileLock

from memory_center.core.storage.workspace import WorkspaceStore

from .artifacts import _resolve_task_dir, touch_task_activity, update_task_status

DELIVERY_FILE = "delivery.json"
REQUIREMENTS_FILE = "requirements.json"
SUBTASKS_FILE = "subtasks.json"
ACCEPTANCE_FILE = "acceptance.json"
VALIDATION_RECEIPTS_FILE = "verification-receipts.jsonl"
DELIVERY_SKILL_CANDIDATES_DIR = "skills/delivery-candidates"
DELIVERY_SKILL_PUBLISHED_DIR = "skills/delivery-published"
WORKFLOW_PROFILE = "feature_delivery_v1"
STAGES = ("intake", "breakdown", "locate", "implement", "verify", "close")
SUBTASK_STATUSES = {"pending", "located", "implemented", "blocked", "skipped"}
VALIDATION_STATUSES = {"passed", "failed", "skipped", "not_run", "recorded"}


def initialize_delivery_workflow(workspace_file: str | Path, task_id: str, *, actor: str = "") -> dict[str, Any]:
    """Create the delivery contract for one existing task space, idempotently."""
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    now = _now()
    created: list[str] = []
    defaults: dict[str, Any] = {
        DELIVERY_FILE: {
            "schema_version": 1,
            "profile": WORKFLOW_PROFILE,
            "task_id": meta["task_id"],
            "stage": "intake",
            "state": "active",
            "created_at": now,
            "updated_at": now,
            "history": [{"stage": "intake", "event": "initialized", "at": now, "actor": _bounded(actor)}],
        },
        REQUIREMENTS_FILE: {"schema_version": 1, "items": []},
        SUBTASKS_FILE: {"schema_version": 1, "items": []},
        ACCEPTANCE_FILE: {"schema_version": 1, "items": []},
    }
    with FileLock(str(store.lock_file)):
        for filename, payload in defaults.items():
            path = task_dir / filename
            if not path.exists():
                _write_json(path, payload)
                created.append(filename)
        (task_dir / VALIDATION_RECEIPTS_FILE).touch(exist_ok=True)
    touch_task_activity(workspace_file, meta["task_id"], "delivery_initialize")
    return {"initialized": True, "task_id": meta["task_id"], "created": created, **delivery_workflow_status(workspace_file, meta["task_id"])}


def update_delivery_contract(workspace_file: str | Path, task_id: str, *, kind: str, items: list[dict[str, Any]], actor: str = "") -> dict[str, Any]:
    """Replace one small, schema-checked contract collection by stable IDs."""
    if kind not in {"requirements", "subtasks", "acceptance"}:
        raise ValueError("kind must be requirements, subtasks, or acceptance")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    normalized = [_normalize_item(kind, item, index) for index, item in enumerate(items, start=1)]
    ids = [item["id"] for item in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{kind} contains duplicate ids")
    filename = {"requirements": REQUIREMENTS_FILE, "subtasks": SUBTASKS_FILE, "acceptance": ACCEPTANCE_FILE}[kind]
    with FileLock(str(store.lock_file)):
        _write_json(task_dir / filename, {"schema_version": 1, "items": normalized, "updated_at": _now(), "actor": _bounded(actor)})
    _append_history(task_dir, event=f"{kind}_updated", actor=actor, details={"count": len(normalized)})
    touch_task_activity(workspace_file, meta["task_id"], f"delivery_{kind}")
    return {"updated": True, "task_id": meta["task_id"], "kind": kind, "items": normalized, "delivery": delivery_workflow_status(workspace_file, meta["task_id"])}


def update_delivery_subtask_status(workspace_file: str | Path, task_id: str, subtask_id: str, status: str, *, actor: str = "") -> dict[str, Any]:
    normalized_status = status.strip().lower()
    if normalized_status not in SUBTASK_STATUSES:
        raise ValueError(f"unknown subtask status: {status}")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    payload = _read_json(task_dir / SUBTASKS_FILE, {"schema_version": 1, "items": []})
    items = list(payload.get("items", []))
    for item in items:
        if str(item.get("id", "")) == subtask_id:
            item["status"] = normalized_status
            item["updated_at"] = _now()
            item["actor"] = _bounded(actor)
            break
    else:
        raise ValueError(f"unknown subtask: {subtask_id}")
    with FileLock(str(store.lock_file)):
        _write_json(task_dir / SUBTASKS_FILE, {"schema_version": 1, "items": items, "updated_at": _now()})
    _append_history(task_dir, event="subtask_status", actor=actor, details={"subtask_id": subtask_id, "status": normalized_status})
    touch_task_activity(workspace_file, meta["task_id"], "delivery_subtask_status")
    return {"updated": True, "task_id": meta["task_id"], "subtask_id": subtask_id, "status": normalized_status, "delivery": delivery_workflow_status(workspace_file, meta["task_id"])}


def record_delivery_validation(workspace_file: str | Path, task_id: str, *, status: str, summary: str = "", command: str = "", exit_code: int | None = None, acceptance_ids: list[str] | None = None, evidence_refs: list[str] | None = None, actor: str = "") -> dict[str, Any]:
    """Record a completed validation result; it never executes a command."""
    normalized_status = status.strip().lower()
    if normalized_status not in VALIDATION_STATUSES:
        raise ValueError(f"unknown validation status: {status}")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    receipt = {
        "receipt_id": f"vr-{uuid4().hex[:12]}",
        "recorded_at": _now(),
        "status": normalized_status,
        "command": _bounded(command, 500),
        "exit_code": exit_code,
        "summary": _bounded(summary, 2000),
        "acceptance_ids": _bounded_refs(acceptance_ids),
        "evidence_refs": _bounded_refs(evidence_refs),
        "actor": _bounded(actor),
    }
    with FileLock(str(store.lock_file)):
        with (task_dir / VALIDATION_RECEIPTS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    _append_history(task_dir, event="validation_recorded", actor=actor, details={"receipt_id": receipt["receipt_id"], "status": normalized_status})
    touch_task_activity(workspace_file, meta["task_id"], "delivery_validation")
    return {"recorded": True, "task_id": meta["task_id"], "receipt": receipt, "delivery": delivery_workflow_status(workspace_file, meta["task_id"])}


def transition_delivery_stage(workspace_file: str | Path, task_id: str, stage: str, *, actor: str = "", force: bool = False) -> dict[str, Any]:
    """Move one stage forward only after the preceding contract gate passes."""
    target = stage.strip().lower()
    if target not in STAGES:
        raise ValueError(f"unknown delivery stage: {stage}")
    initialize_delivery_workflow(workspace_file, task_id, actor=actor)
    store = WorkspaceStore(workspace_file)
    task_dir, meta = _resolve_task_dir(store, task_id)
    delivery = _read_json(task_dir / DELIVERY_FILE, {})
    current = str(delivery.get("stage", "intake"))
    if STAGES.index(target) < STAGES.index(current):
        raise ValueError("delivery stage cannot move backwards")
    gate = _gate_for_target(task_dir, target)
    if not gate["passed"] and not force:
        return {"transitioned": False, "task_id": meta["task_id"], "from_stage": current, "target_stage": target, "gate": gate, "next_action": gate["next_action"]}
    if target != current:
        delivery["stage"] = target
        delivery["state"] = "done" if target == "close" else "active"
        delivery["updated_at"] = _now()
        delivery.setdefault("history", []).append({"stage": target, "event": "transitioned" if gate["passed"] else "forced_transition", "at": _now(), "actor": _bounded(actor), "gate": gate["code"]})
        with FileLock(str(store.lock_file)):
            _write_json(task_dir / DELIVERY_FILE, delivery)
        if target == "close":
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
    gate = _gate_for_target(task_dir, next_stage) if stage != "close" else {"passed": True, "code": "complete", "next_action": "任务已完成。", "missing": []}
    requirements = _items(task_dir / REQUIREMENTS_FILE)
    subtasks = _items(task_dir / SUBTASKS_FILE)
    acceptance = _items(task_dir / ACCEPTANCE_FILE)
    receipts = _recent_receipts(task_dir)
    return {
        "initialized": True,
        "profile": delivery.get("profile", WORKFLOW_PROFILE),
        "task_id": meta["task_id"],
        "stage": stage,
        "state": delivery.get("state", "active"),
        "next_stage": next_stage if stage != "close" else "",
        "gate": gate,
        "counts": {"requirements": len(requirements), "subtasks": len(subtasks), "acceptance": len(acceptance), "validation_receipts": len(receipts)},
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
    receipts = _recent_receipts(task_dir)
    passed = [row for row in receipts if row.get("status") == "passed"]
    required_ids = {str(item.get("id", "")) for item in acceptance if bool(item.get("required", True))}
    passed_ids = {identifier for row in passed for identifier in row.get("acceptance_ids", [])}
    missing = sorted(required_ids - passed_ids)
    located = [item for item in subtasks if item.get("code_targets")]
    eligible = status.get("state") == "done" and not missing and bool(located) and bool(passed)
    score = min(100, 35 + min(25, len(requirements) * 5) + min(25, len(located) * 5) + min(15, len(passed) * 3)) if eligible else 0
    candidate = {
        "schema_version": 1,
        "candidate_id": f"delivery-skill-{meta['task_id']}",
        "task_id": meta["task_id"],
        "title": str(meta.get("title", "")),
        "created_at": _now(),
        "eligible": eligible,
        "quality_score": score,
        "missing": missing,
        "requirements": [{"id": item["id"], "title": item["title"], "scope": item.get("scope", "")} for item in requirements[:30]],
        "code_targets": [target for item in located for target in item.get("code_targets", [])][:80],
        "acceptance": [{"id": item["id"], "title": item["title"], "verification_type": item.get("verification_type", "test")} for item in acceptance[:30]],
        "validation": [{"receipt_id": row.get("receipt_id", ""), "summary": str(row.get("summary", ""))[:500], "acceptance_ids": row.get("acceptance_ids", [])[:30]} for row in passed[-20:]],
    }
    path = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR / f"{meta['task_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"generated": True, "candidate": candidate, "path": str(path), "next_action": "eligible 时执行 delivery-skill-publish；否则先补齐缺失验收或定位证据。"}


def publish_delivery_skill(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    """Publish an approved candidate as an agent-readable Skill artifact."""
    store = WorkspaceStore(workspace_file)
    candidate_path = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR / f"{task_id}.json"
    if not candidate_path.exists():
        return {"published": False, "reason": "candidate_not_found", "next_action": "先执行 delivery-skill-candidate。"}
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not candidate.get("eligible"):
        return {"published": False, "reason": "candidate_not_eligible", "missing": candidate.get("missing", []), "next_action": "补齐交付门禁后重新生成候选。"}
    slug = _skill_slug(str(candidate.get("task_id", "delivery-skill")))
    path = store.artifacts_dir / DELIVERY_SKILL_PUBLISHED_DIR / slug / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_delivery_skill_markdown(candidate), encoding="utf-8")
    manifest_path = path.parent / "manifest.json"
    manifest_path.write_text(json.dumps({"schema_version": 1, "task_id": candidate["task_id"], "candidate_id": candidate["candidate_id"], "quality_score": candidate["quality_score"], "published_at": _now()}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"published": True, "task_id": candidate["task_id"], "quality_score": candidate["quality_score"], "path": str(path), "next_action": "将该 Skill 加入 Agent 指令的按需读取列表；后续仅从新的已验证交付生成候选。"}


def delivery_skill_status(workspace_file: str | Path, task_id: str) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    candidate = store.artifacts_dir / DELIVERY_SKILL_CANDIDATES_DIR / f"{task_id}.json"
    published = store.artifacts_dir / DELIVERY_SKILL_PUBLISHED_DIR / _skill_slug(task_id) / "SKILL.md"
    return {"task_id": task_id, "candidate": str(candidate) if candidate.exists() else "", "published_skill": str(published) if published.exists() else "", "next_action": "delivery-skill-candidate" if not candidate.exists() else ("delivery-skill-publish" if not published.exists() else "use_published_skill")}


def _gate_for_target(task_dir: Path, target: str) -> dict[str, Any]:
    requirements, subtasks, acceptance, receipts = (_items(task_dir / REQUIREMENTS_FILE), _items(task_dir / SUBTASKS_FILE), _items(task_dir / ACCEPTANCE_FILE), _recent_receipts(task_dir))
    if target == "intake":
        return _gate("ready", [], "补充任务目标后进入需求拆解。")
    if target == "breakdown":
        return _gate("requirements_required", ["requirements"] if not requirements else [], "先录入带范围与证据引用的需求项。")
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
        return _gate("located_subtasks_required", missing, "为每个子任务关联已定位的代码目标后再实现。")
    if target == "verify":
        missing = [str(item.get("id", "")) for item in subtasks if item.get("status") not in {"implemented", "skipped"}]
        return _gate("implementation_required", missing, "将所有子任务标记为已实现或跳过，并记录原因。")
    required_ids = {str(item.get("id", "")) for item in acceptance if bool(item.get("required", True))}
    passed_ids = {identifier for row in receipts if row.get("status") == "passed" for identifier in row.get("acceptance_ids", [])}
    return _gate("verification_required", sorted(required_ids - passed_ids), "记录通过的验证回执，并关联每一项必需验收标准。")


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
        return {**base, "scope": _bounded(str(raw.get("scope", "")), 1000), "acceptance_ids": _bounded_refs(raw.get("acceptance_ids", [])), "status": str(raw.get("status", "planned"))}
    if kind == "subtasks":
        status = str(raw.get("status", "pending")).lower()
        if status not in SUBTASK_STATUSES:
            raise ValueError(f"unknown subtask status: {status}")
        return {**base, "requirement_ids": _bounded_refs(raw.get("requirement_ids", [])), "code_targets": _bounded_refs(raw.get("code_targets", [])), "status": status}
    return {**base, "required": bool(raw.get("required", True)), "verification_type": str(raw.get("verification_type", "test")), "status": str(raw.get("status", "pending"))}


def _append_history(task_dir: Path, *, event: str, actor: str, details: dict[str, Any]) -> None:
    delivery = _read_json(task_dir / DELIVERY_FILE, {})
    delivery["updated_at"] = _now()
    delivery.setdefault("history", []).append({"stage": delivery.get("stage", "intake"), "event": event, "at": _now(), "actor": _bounded(actor), "details": details})
    _write_json(task_dir / DELIVERY_FILE, delivery)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _items(path: Path) -> list[dict[str, Any]]:
    value = _read_json(path, {"items": []}).get("items", [])
    return [item for item in value if isinstance(item, dict)]


def _recent_receipts(task_dir: Path) -> list[dict[str, Any]]:
    path = task_dir / VALIDATION_RECEIPTS_FILE
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-100:]:
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
        except json.JSONDecodeError:
            continue
    return rows


def _bounded_refs(value: Any) -> list[str]:
    values = value if isinstance(value, list) else []
    return [str(item).strip()[:240] for item in values if str(item).strip()][:50]


def _bounded(value: str, limit: int = 120) -> str:
    return value.strip()[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _skill_slug(value: str) -> str:
    return "-".join("".join(char.lower() if char.isalnum() else " " for char in value).split()) or "delivery-skill"


def _delivery_skill_markdown(candidate: dict[str, Any]) -> str:
    targets = "\n".join(f"- `{item}`" for item in candidate.get("code_targets", [])) or "- 先通过 Memory Center 定位代码目标。"
    acceptance = "\n".join(f"- `{item.get('id', '')}` {item.get('title', '')} ({item.get('verification_type', 'test')})" for item in candidate.get("acceptance", [])) or "- 为每项需求定义可验证验收标准。"
    return f"""# {candidate.get('title', '已验证需求交付')} / Verified Delivery Skill

## 适用场景 / When to use

当新需求与该已验证交付的范围和代码目标相似时使用。本 Skill 来自已关闭任务及其通过的验证回执，质量分为 `{candidate.get('quality_score', 0)}`。

## 执行流程 / Workflow

1. 初始化 `feature_delivery_v1`，录入需求和验收标准。
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
