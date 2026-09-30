"""Private-case evaluation for L1 case recall through the actual resume path."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import yaml

from memory_center.core.retrieval.scoring import tokenize_with_domain_terms
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

CASE_MEMORY_FILE = "cross-service-task-memory.jsonl"
SCHEMA_VERSION = 1


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _load_cases(cases_file: str | Path) -> list[dict[str, Any]]:
    path = Path(cases_file).expanduser().resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        raise ValueError("session recall case file must be a schema_version=1 YAML object")
    cases = raw.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("session recall case file cases must be a list")
    return [item for item in cases if isinstance(item, dict)]


def _classify_case(
    *,
    query: str,
    expected_source_session_id: str,
    all_cases: list[dict[str, Any]],
    returned_cases: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    if not query or not expected_source_session_id:
        return "evidence_insufficient", []
    expected_exists = any(str(item.get("source_session_id", "") or "") == expected_source_session_id for item in all_cases)
    returned_source_ids = [str(item.get("source_session_id", "") or "") for item in returned_cases]
    if not expected_exists:
        return "case_not_indexed", returned_source_ids
    if expected_source_session_id in returned_source_ids:
        return "hit", returned_source_ids
    tokens = tokenize_with_domain_terms(query)
    raw_matches = [
        item
        for item in all_cases
        if any(token in json.dumps(item, ensure_ascii=False).lower() for token in tokens)
    ]
    if any(str(item.get("source_session_id", "") or "") == expected_source_session_id for item in raw_matches):
        return "ranking_miss", returned_source_ids
    return "retrieval_miss", returned_source_ids


def evaluate_session_recall(
    workspace_file: str | Path,
    cases_file: str | Path,
    *,
    limit: int = 5,
    resume_runner: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Replay private cases through an injected resume runner without writing state.

    ``resume_runner`` 由调用方注入（CLI / 测试等适配层负责传入编排层的
    ``workspace_resume_context``）：benchmark 属 core 引擎层，不得反向依赖
    orchestrator（ADR-0002 §4.4）。

    Results deliberately contain only case IDs and hashes, never query text, task
    text, source-session IDs, or case bodies. Keep the YAML input outside git.
    """
    config, store = load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
    input_cases = _load_cases(cases_file)
    bounded_limit = max(1, min(limit, 20))
    all_cases = store.read_jsonl_prefer_backend(CASE_MEMORY_FILE, limit=300)
    results: list[dict[str, Any]] = []
    counts = {name: 0 for name in ("hit", "case_not_indexed", "retrieval_miss", "ranking_miss", "evidence_insufficient")}
    match_modes: dict[str, int] = {}
    precision_labeled_cases = 0
    allowed_returned = 0
    returned_labeled = 0
    unexpected_returned = 0

    for index, item in enumerate(input_cases, start=1):
        case_id = str(item.get("id", "") or f"case-{index}")[:120]
        query = str(item.get("query", "") or "").strip()
        expected_source_session_id = str(item.get("expected_source_session_id", "") or "").strip()
        allowed_source_session_ids = {
            str(value).strip()
            for value in (item.get("allowed_source_session_ids", []) or [])
            if str(value).strip()
        }
        if query:
            resume = resume_runner(workspace_file, query, limit=bounded_limit)
            returned_cases = list(resume.get("related_cases", []) or [])
            match_mode = str(resume.get("related_case_match_mode", "none") or "none")
        else:
            returned_cases = []
            match_mode = "none"
        classification, returned_source_ids = _classify_case(
            query=query,
            expected_source_session_id=expected_source_session_id,
            all_cases=all_cases,
            returned_cases=returned_cases,
        )
        counts[classification] += 1
        match_modes[match_mode] = match_modes.get(match_mode, 0) + 1
        precision_assessed = bool(allowed_source_session_ids)
        unexpected_source_ids = []
        if precision_assessed:
            precision_labeled_cases += 1
            returned_labeled += len(returned_source_ids)
            allowed_returned += sum(1 for value in returned_source_ids if value in allowed_source_session_ids)
            unexpected_source_ids = [value for value in returned_source_ids if value not in allowed_source_session_ids]
            unexpected_returned += len(unexpected_source_ids)
        results.append(
            {
                "case_id": case_id,
                "query_sha256": _digest(query) if query else "",
                "expected_source_session_sha256": _digest(expected_source_session_id) if expected_source_session_id else "",
                "classification": classification,
                "related_case_match_mode": match_mode,
                "returned_source_session_sha256": [_digest(value) for value in returned_source_ids if value][:bounded_limit],
                "precision_assessed": precision_assessed,
                "unexpected_source_session_sha256": [_digest(value) for value in unexpected_source_ids][:bounded_limit],
            }
        )

    evaluable = len(input_cases) - counts["evidence_insufficient"]
    hits = counts["hit"]
    status = "ready" if len(input_cases) >= 3 else "insufficient_cases"
    if unexpected_returned:
        next_action = "先人工审核 unexpected 返回项并补充 allowed_source_session_ids；只有确认存在过多不相关候选时，才收紧 CJK fallback 的评分或结果上限。"
    elif status == "insufficient_cases":
        next_action = "样本不足；继续积累至少 3 个脱敏真实 case，不改变检索策略。"
    else:
        next_action = "仅当 retrieval_miss 或 ranking_miss 在多轮真实 case 中稳定出现时，才评审检索字段或排序。"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "session_recall_eval",
        "workspace": config.workspace,
        "status": status,
        "case_count": len(input_cases),
        "evaluable_case_count": evaluable,
        "recall": round(hits / evaluable, 4) if evaluable else None,
        "classifications": counts,
        "related_case_match_modes": match_modes,
        "precision_review": {
            "labeled_case_count": precision_labeled_cases,
            "returned_count": returned_labeled,
            "allowed_returned_count": allowed_returned,
            "unexpected_return_count": unexpected_returned,
            "precision": round(allowed_returned / returned_labeled, 4) if returned_labeled else None,
            "note": "unexpected means human review required, not an automatic false-positive judgment",
        },
        "limit": bounded_limit,
        "cases": results,
        "next_action": next_action,
        "privacy": "input YAML is local-only; output hashes queries and source session ids",
    }
