"""多会话 → L1 case / L3 记忆块候选整合（consolidate-session）。

设计依据：docs/MEMORY_LANDSCAPE_RESEARCH.md §3.2 与 §4 —— 外部记忆项目提示
"会话沉淀不应无条件追加"。本模块提供显式、默认 dry-run 的离线整合命令：

- 把一组已结束会话的 `workspace_suggest_case` 草稿聚合成候选列表；
- 每条候选都带来源 event/evidence ref、冲突理由和预期写操作；
- 对同主题的既有或同批 case 给出 REVIEW 建议，避免基于文本相似度自动覆盖；
- 可选把稳定经验提炼为 L3 memory-block 追加草稿；
- 默认 dry-run，只有 `apply=True` 时才通过既有 `workspace_record_case` 写入。

本模块不改变 MCP tool schema，不进入查询热路径，属于显式离线维护路径。
"""
from __future__ import annotations

import difflib
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.tasks.artifacts import CORE_MEMORY_BLOCKS

from .rules import _choose_l3_artifact_name
from .session import workspace_session_summary, workspace_suggest_case
from .shared import (
    LAYER_L1,
    TOOL_WORKSPACE_RECORD_CASE,
    load_context,
)
from .write import workspace_record_case

CASE_MEMORY_FILE = "cross-service-task-memory.jsonl"
CONSOLIDATION_CANDIDATES_FILE = "session-consolidation-candidates.jsonl"

# 归一化阈值：高于该相似度判定为"同一主题"，要求维护者 REVIEW。
CONSOLIDATE_SIMILARITY_THRESHOLD = 0.72
# 冲突候选来源引用上限，控制返回体积。
CONSOLIDATE_SOURCE_REF_LIMIT = 12


def _normalize_case_key(task: str, projects: list[str], files: list[str]) -> str:
    """构建 case 的可比文本（用于去重/冲突判断），归一化空白与大小写。"""
    tokens = []
    tokens.append(str(task or "").strip().lower())
    for item in (projects or [])[:4]:
        tokens.append(str(item or "").strip().lower())
    for item in (files or [])[:8]:
        tokens.append(str(Path(str(item or "")).name).lower())
    return " ".join(token for token in tokens if token)


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _existing_cases(store) -> list[dict[str, Any]]:
    return store.read_jsonl_prefer_backend(CASE_MEMORY_FILE, limit=5000)


def _candidate_id(session_id: str, draft: dict[str, Any]) -> str:
    """Derive a stable candidate id so review decisions remain append-only."""
    key = _normalize_case_key(draft.get("task", ""), draft.get("projects", []), draft.get("files", []))
    digest = hashlib.sha256(f"{session_id}|{key}".encode("utf-8")).hexdigest()[:16]
    return f"session-consolidation-{digest}"


def _find_conflicting_cases(
    draft: dict[str, Any],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """在既有 case 中寻找同主题候选，返回带相似度的冲突项（升序保留最强）。"""
    key = _normalize_case_key(
        draft.get("task", ""),
        draft.get("projects", []),
        draft.get("files", []),
    )
    conflicts: list[dict[str, Any]] = []
    for row in existing:
        row_key = _normalize_case_key(
            row.get("task", ""),
            row.get("projects", []),
            row.get("files", []),
        )
        score = _similarity(key, row_key)
        if score >= CONSOLIDATE_SIMILARITY_THRESHOLD:
            conflicts.append(
                {
                    "score": round(score, 3),
                    "case": {
                        "task": row.get("task", ""),
                        "projects": row.get("projects", []),
                        "valid_from": row.get("valid_from", ""),
                        "valid_to": row.get("valid_to", ""),
                        "superseded_by": row.get("superseded_by", ""),
                        "current_truth": row.get("current_truth", False),
                        "source_session_id": row.get("source_session_id", ""),
                    },
                }
            )
    conflicts.sort(key=lambda item: item["score"], reverse=True)
    return conflicts[:3]


def _suggest_l3_draft(session_id: str, draft: dict[str, Any]) -> dict[str, Any] | None:
    """把单会话草稿提炼为 L3 memory-block 追加候选（仅当任务文本命中规则）。"""
    text = str(draft.get("task", "") or "")
    if not text.strip():
        return None
    block_key = _choose_l3_artifact_name(text)
    if block_key not in CORE_MEMORY_BLOCKS:
        block_key = "workspace_profile"
    lines = [
        f"- {text.strip()}",
        f"  - source session: {session_id}",
        f"  - projects: {', '.join(str(p) for p in (draft.get('projects') or [])[:4])}",
    ]
    evidence = (draft.get("evidence_refs") or [])[:CONSOLIDATE_SOURCE_REF_LIMIT]
    return {
        "block_key": block_key,
        "file": CORE_MEMORY_BLOCKS[block_key],
        "draft_entry": "\n".join(lines),
        "evidence_refs": evidence,
        "reason": "跨会话稳定经验，建议由维护者确认后追加到 L3 memory block。",
    }


def _candidate_projection(store, *, status: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """Materialize candidate state from append-only candidate and decision rows."""
    records = store.read_jsonl_prefer_backend(CONSOLIDATION_CANDIDATES_FILE, limit=5000)
    candidates: dict[str, dict[str, Any]] = {}
    decisions: dict[str, dict[str, Any]] = {}
    for row in records:
        candidate_id = str(row.get("candidate_id", "") or "")
        if not candidate_id:
            continue
        if row.get("record_type") == "candidate":
            candidates[candidate_id] = row
        elif row.get("record_type") == "decision":
            decisions[candidate_id] = row
    result = []
    for candidate_id, row in candidates.items():
        decision = decisions.get(candidate_id, {})
        lifecycle = str(decision.get("status", "pending") or "pending")
        if status and lifecycle != status:
            continue
        result.append(
            {
                **dict(row.get("candidate", {}) or {}),
                "candidate_id": candidate_id,
                "lifecycle": lifecycle,
                "staged_at": row.get("staged_at", ""),
                "decision": decision,
            }
        )
    result.sort(key=lambda item: (str(item.get("staged_at", "")), str(item.get("candidate_id", ""))), reverse=True)
    return result[: max(1, min(limit, 500))]


def workspace_list_consolidation_candidates(
    workspace_file: str | Path, *, status: str = "pending", limit: int = 50
) -> dict[str, Any]:
    """List reviewable session-consolidation candidates without writing."""
    config, store = load_context(workspace_file)
    candidates = _candidate_projection(store, status=status.strip(), limit=limit)
    return {
        "workspace": config.workspace,
        "status": status.strip() or "all",
        "candidate_count": len(candidates),
        "candidates": candidates,
        "next_action": "审核 pending 候选后运行 decide-consolidation-candidate。" if candidates else "暂无匹配候选。",
    }


def workspace_consolidate_sessions(
    workspace_file: str | Path,
    session_ids: list[str] | None = None,
    *,
    limit: int = 10,
    include_l3: bool = False,
    stage: bool = False,
    apply: bool = False,
    source: str = "consolidate_session",
) -> dict[str, Any]:
    """把多个已结束会话整合为 L1 case / L3 记忆块候选。

    默认 dry-run：只返回候选（含来源引用、冲突理由、预期写操作），不写盘。
    `stage=True` 时把候选持久化为待审核记录；`apply=True` 保留为直接显式写入模式。
    两者不可同时使用。`apply=True` 时才通过 `workspace_record_case` 写入 L1（保守追加语义），
    L3 候选始终只产出草稿，即使 apply 也不自动写入（需维护者走 artifact 更新）。
    """
    config, store = load_context(workspace_file)
    if stage and apply:
        raise ValueError("stage 与 apply 不可同时使用；请先 stage，再逐条 decide-consolidation-candidate。")

    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    existing = _existing_cases(store)
    batch_keys: dict[str, str] = {}

    ids = [str(item).strip() for item in (session_ids or []) if str(item).strip()]
    if not ids:
        # 默认取最近结束的会话（读取 summary 反序后取前 limit 个）。
        summaries = store.read_jsonl_via_backend("session-summaries.jsonl", limit=max(limit, 1))
        ids = [str(row.get("session_id", "") or "") for row in reversed(summaries[-limit:]) if row.get("session_id")]
    ids = ids[:limit]

    for session_id in ids:
        session = workspace_session_summary(workspace_file, session_id)
        if not session.get("found"):
            skipped.append({"session_id": session_id, "reason": "session_not_found"})
            continue
        if not session.get("summary"):
            skipped.append({"session_id": session_id, "reason": "session_not_finished"})
            continue
        case_result = workspace_suggest_case(workspace_file, session_id)
        if not case_result.get("found") or not case_result.get("draft_case"):
            skipped.append({"session_id": session_id, "reason": "no_draft"})
            continue
        draft = case_result["draft_case"]
        draft_key = _normalize_case_key(
            draft.get("task", ""),
            draft.get("projects", []),
            draft.get("files", []),
        )

        conflicts = _find_conflicting_cases(draft, existing)
        duplicate_session_id = batch_keys.get(draft_key)
        if duplicate_session_id:
            operation = "REVIEW"
            reason = f"与本批 session {duplicate_session_id} 属于同一主题，需人工合并或选择保留项。"
        elif conflicts:
            best = conflicts[0]
            score = float(best.get("score", 0.0))
            existing_case = best.get("case", {})
            if existing_case.get("current_truth"):
                operation = "REVIEW"
                reason = f"与既有 current-truth case 高度相似（score={score:.2f}），需人工确认是重复、更新还是替代。"
            else:
                operation = "ADD"
                reason = (
                    f"与既有 case 高度相似（score={score:.2f}），"
                    f"但既有 case 已失效（superseded_by={existing_case.get('superseded_by', '') or 'n/a'}），"
                    "可作为新的 current-truth case 追加。"
                )
        else:
            operation = "ADD"
            reason = "未发现同主题既有 case，建议作为新 L1 case 写入。"

        expected_write = {
            "action": TOOL_WORKSPACE_RECORD_CASE if operation == "ADD" else "review_required",
            "layer": LAYER_L1,
            "target": CASE_MEMORY_FILE,
            "current_truth": operation == "ADD",
        }

        candidate = {
            "candidate_id": _candidate_id(session_id, draft),
            "session_id": session_id,
            "operation": operation,
            "reason": reason,
            "conflicts": conflicts,
            "expected_write": expected_write,
            "draft_case": draft,
            "source_refs": (draft.get("source_refs") or [])[:CONSOLIDATE_SOURCE_REF_LIMIT],
            "evidence_refs": (draft.get("evidence_refs") or [])[:CONSOLIDATE_SOURCE_REF_LIMIT],
            "l3_draft": _suggest_l3_draft(session_id, draft) if include_l3 else None,
        }
        candidates.append(candidate)
        batch_keys.setdefault(draft_key, session_id)

    applied: list[dict[str, Any]] = []
    if apply:
        for candidate in candidates:
            op = candidate.get("operation")
            if op != "ADD":
                candidate["write_receipt"] = None
                continue
            draft = candidate.get("draft_case", {})
            result = workspace_record_case(
                workspace_file,
                task=str(draft.get("task", "") or ""),
                projects=list(draft.get("projects") or []),
                files=list(draft.get("files") or [])[:30],
                flow=str(draft.get("flow", "") or ""),
                risk_points=list(draft.get("risk_points") or []),
                verified_by=list(draft.get("verified_by") or []),
                source_session_id=str(draft.get("source_session_id", "") or candidate.get("session_id", "") or ""),
                source_task_id=str(draft.get("source_task_id", "") or ""),
                source_refs=list(draft.get("source_refs") or []),
                current_truth=True,
            )
            candidate["write_receipt"] = result.get("write_receipt")
            applied.append(candidate)

    staged: list[str] = []
    if stage:
        prior = {item.get("candidate_id", "") for item in _candidate_projection(store, status="", limit=500)}
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            if candidate_id in prior:
                continue
            store.append_jsonl(
                CONSOLIDATION_CANDIDATES_FILE,
                {
                    "record_type": "candidate",
                    "candidate_id": candidate_id,
                    "staged_at": datetime.now(timezone.utc).isoformat(),
                    "candidate": candidate,
                },
            )
            staged.append(candidate_id)

    return {
        "workspace": config.workspace,
        "dry_run": not apply and not stage,
        "applied": bool(apply),
        "staged": bool(stage),
        "staged_candidate_ids": staged,
        "candidate_count": len(candidates),
        "skipped_count": len(skipped),
        "candidates": candidates,
        "skipped": skipped,
        "l3_enabled": bool(include_l3),
        "source": source,
        "summary": {
            "operations": {
                op: sum(1 for c in candidates if c.get("operation") == op)
                for op in ("ADD", "REVIEW")
            },
            "applied_count": len(applied),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def workspace_decide_consolidation_candidate(
    workspace_file: str | Path,
    candidate_id: str,
    *,
    decision: str,
    actor: str,
    note: str = "",
) -> dict[str, Any]:
    """Apply or reject one staged candidate after explicit human review."""
    normalized_decision = decision.strip().lower()
    if normalized_decision not in {"approve", "reject"}:
        raise ValueError("decision 仅支持 approve 或 reject")
    config, store = load_context(workspace_file)
    candidates = _candidate_projection(store, status="", limit=500)
    candidate = next((item for item in candidates if item.get("candidate_id") == candidate_id), None)
    if candidate is None:
        return {"workspace": config.workspace, "applied": False, "reason": "candidate_not_found"}
    if candidate.get("lifecycle") != "pending":
        return {"workspace": config.workspace, "applied": False, "reason": f"candidate_already_{candidate.get('lifecycle')}", "candidate": candidate}

    now = datetime.now(timezone.utc).isoformat()
    if normalized_decision == "reject":
        store.append_jsonl(
            CONSOLIDATION_CANDIDATES_FILE,
            {"record_type": "decision", "candidate_id": candidate_id, "status": "rejected", "actor": actor[:120], "note": note[:500], "decided_at": now},
        )
        return {"workspace": config.workspace, "applied": False, "rejected": True, "candidate_id": candidate_id}

    if candidate.get("operation") != "ADD":
        return {
            "workspace": config.workspace,
            "applied": False,
            "reason": "candidate_requires_manual_resolution",
            "candidate": candidate,
            "next_action": "REVIEW 候选需先人工处理既有 case，再重新生成候选。",
        }
    draft = dict(candidate.get("draft_case", {}) or {})
    conflicts = _find_conflicting_cases(draft, _existing_cases(store))
    if any(conflict.get("case", {}).get("current_truth") for conflict in conflicts):
        return {
            "workspace": config.workspace,
            "applied": False,
            "reason": "candidate_conflict_changed",
            "conflicts": conflicts,
            "next_action": "候选暂存后已有 current-truth case 变化，需重新审核。",
        }
    result = workspace_record_case(
        workspace_file,
        task=str(draft.get("task", "") or ""),
        projects=list(draft.get("projects") or []),
        files=list(draft.get("files") or [])[:30],
        flow=str(draft.get("flow", "") or ""),
        risk_points=list(draft.get("risk_points") or []),
        verified_by=list(draft.get("verified_by") or []),
        source_session_id=str(draft.get("source_session_id", "") or candidate.get("session_id", "") or ""),
        source_task_id=str(draft.get("source_task_id", "") or ""),
        source_refs=list(draft.get("source_refs") or []),
        current_truth=True,
    )
    store.append_jsonl(
        CONSOLIDATION_CANDIDATES_FILE,
        {"record_type": "decision", "candidate_id": candidate_id, "status": "applied", "actor": actor[:120], "note": note[:500], "decided_at": now, "write_receipt": result.get("write_receipt")},
    )
    return {"workspace": config.workspace, "applied": True, "candidate_id": candidate_id, "write_receipt": result.get("write_receipt")}
