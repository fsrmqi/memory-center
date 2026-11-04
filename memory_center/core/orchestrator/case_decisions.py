"""L1 case 替代决策：追加式决策行 + current truth 投影（吸收计划 G1）。

设计取舍（见 docs/WRITE_GOVERNANCE_ABSORPTION_PLAN.md）：
- 替代不 UPDATE 既有 case 行，而是向 case-decisions.jsonl 追加决策记录；
  与 Utopia 台账同向：忘读决策行 = 替代不生效（安全方向），而非未确认状态混入图。
- current_truth 是投影而非存储字段：基础值来自旧行字段（兼容历史数据），
  最新决策胜出。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..tasks.receipts import build_write_decision, build_write_receipt, persist_write_receipt
from .shared import (
    LAYER_L1,
    TOOL_WORKSPACE_CASE_REINSTATE,
    TOOL_WORKSPACE_CASE_SUPERSEDE,
    load_context,
)

CASE_DECISIONS_FILE = "case-decisions.jsonl"
_CASES_FILE = "cross-service-task-memory.jsonl"
_CASE_SCAN_LIMIT = 5000


def project_case_truth(
    cases: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, bool]:
    """按 case_id 计算 current truth 投影：旧行字段打底，最新决策胜出。"""
    projection: dict[str, bool] = {}
    for case in cases:
        case_id = str(case.get("case_id", "")).strip()
        if not case_id:
            continue
        projection[case_id] = (
            bool(case.get("current_truth", True))
            and not str(case.get("superseded_by", "")).strip()
            and not str(case.get("valid_to", "")).strip()
        )
    for decision in decisions:
        case_id = str(decision.get("case_id", "")).strip()
        if case_id not in projection:
            continue
        if decision.get("decision") == "supersede":
            projection[case_id] = False
        elif decision.get("decision") == "reinstate":
            projection[case_id] = True
    return projection


def _load_cases_and_decisions(store: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cases = store.read_jsonl_prefer_backend(_CASES_FILE, limit=_CASE_SCAN_LIMIT)
    decisions = store.read_jsonl_prefer_backend(CASE_DECISIONS_FILE, limit=_CASE_SCAN_LIMIT)
    return cases, decisions


def _append_decision(
    store: Any,
    *,
    case_id: str,
    decision: str,
    superseded_by: str,
    actor: str,
    note: str,
    action: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    record = {
        "record_type": "case_decision",
        "decision_id": f"case-decision-{uuid4().hex[:16]}",
        "case_id": case_id,
        "decision": decision,
        "superseded_by": superseded_by,
        "actor": actor.strip(),
        "note": note.strip(),
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    store.append_jsonl(CASE_DECISIONS_FILE, record)
    receipt = persist_write_receipt(
        store,
        build_write_receipt(
            layer=LAYER_L1,
            action=action,
            scope="memory",
            target=CASE_DECISIONS_FILE,
            target_file=f"memory/{CASE_DECISIONS_FILE}",
            decision=build_write_decision(
                actor=actor,
                reason=note or f"case_{decision}",
                refs=[case_id] + ([superseded_by] if superseded_by else []),
            ),
        ),
    )
    return record, receipt


def supersede_case(
    workspace_file: str | Path,
    case_id: str,
    superseded_by: str = "",
    actor: str = "",
    note: str = "",
) -> dict[str, Any]:
    """用决策行把一条 current truth case 标记为被替代（不改写原行）。"""
    _, store = load_context(workspace_file)
    case_id = str(case_id).strip()
    cases, decisions = _load_cases_and_decisions(store)
    if not any(str(c.get("case_id", "")).strip() == case_id for c in cases):
        return {"superseded": False, "reason": "case_not_found", "case_id": case_id}
    successor = str(superseded_by).strip()
    if successor and successor == case_id:
        return {
            "superseded": False,
            "reason": "successor_is_self",
            "case_id": case_id,
            "superseded_by": successor,
        }
    if successor and not any(str(c.get("case_id", "")).strip() == successor for c in cases):
        return {
            "superseded": False,
            "reason": "successor_not_found",
            "case_id": case_id,
            "superseded_by": successor,
        }
    projection = project_case_truth(cases, decisions)
    if not projection.get(case_id, False):
        return {"superseded": False, "reason": "case_not_current_truth", "case_id": case_id}
    if successor and not projection.get(successor, False):
        return {
            "superseded": False,
            "reason": "successor_not_current_truth",
            "case_id": case_id,
            "superseded_by": successor,
        }
    record, receipt = _append_decision(
        store,
        case_id=case_id,
        decision="supersede",
        superseded_by=successor,
        actor=actor,
        note=note,
        action=TOOL_WORKSPACE_CASE_SUPERSEDE,
    )
    return {
        "superseded": True,
        "case_id": case_id,
        "decision_id": record["decision_id"],
        "decision": record,
        "write_receipt": receipt,
    }


def reinstate_case(
    workspace_file: str | Path,
    case_id: str,
    actor: str = "",
    note: str = "",
) -> dict[str, Any]:
    """撤销替代决策：追加 reinstate 决策行，恢复 current truth 投影。"""
    _, store = load_context(workspace_file)
    case_id = str(case_id).strip()
    cases, decisions = _load_cases_and_decisions(store)
    if not any(str(c.get("case_id", "")).strip() == case_id for c in cases):
        return {"reinstated": False, "reason": "case_not_found", "case_id": case_id}
    projection = project_case_truth(cases, decisions)
    if projection.get(case_id, False):
        return {"reinstated": False, "reason": "case_already_current_truth", "case_id": case_id}
    record, receipt = _append_decision(
        store,
        case_id=case_id,
        decision="reinstate",
        superseded_by="",
        actor=actor,
        note=note,
        action=TOOL_WORKSPACE_CASE_REINSTATE,
    )
    return {
        "reinstated": True,
        "case_id": case_id,
        "decision_id": record["decision_id"],
        "decision": record,
        "write_receipt": receipt,
    }


def workspace_case_decisions(
    workspace_file: str | Path,
    case_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """列出 case 决策行（最新在前），可按 case_id 过滤。"""
    _, store = load_context(workspace_file)
    wanted = str(case_id).strip()
    bounded = max(1, min(int(limit), 500))
    decisions = store.read_jsonl_prefer_backend(CASE_DECISIONS_FILE, limit=5000 if wanted else bounded)
    if wanted:
        decisions = [d for d in decisions if str(d.get("case_id", "")).strip() == wanted]
    decisions.reverse()
    return {"case_id": wanted, "decision_count": len(decisions), "decisions": decisions[:bounded]}
