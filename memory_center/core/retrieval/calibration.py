"""基于人工验证回放的检索融合权重校准。

仅使用 ``retrieval-source`` 的带证据验证记录。agent guidance 是否被执行不等于
检索结果正确，因此不会参与此处的权重学习。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.verification.heuristics import (
    HEURISTICS_FILE,
    RETRIEVAL_CALIBRATION_FILE,
    bounded_retrieval_source_weights,
    load_retrieval_source_weights,
)

_SUCCESS_OUTCOMES = {"confirmed"}
_FAILURE_OUTCOMES = {"rejected", "demoted", "rollback"}
_MIN_SOURCE_SAMPLES = 4
_PRIOR_STRENGTH = 10.0


def evaluate_retrieval_replay_calibration(
    workspace_file: str | Path,
    *,
    lookback_days: int = 30,
    min_samples: int = 20,
    apply: bool = False,
) -> dict[str, Any]:
    """从真实、带证据的检索结果回放生成受约束权重提案。

    ``apply`` 只写入一份可审查的覆盖配置，不修改历史反馈，也不会自动执行。
    """
    store = WorkspaceStore(workspace_file)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, lookback_days))
    rows = store.read_jsonl_prefer_backend(HEURISTICS_FILE, limit=100_000)
    grouped: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"positive": 0, "negative": 0})
    discarded = {"outside_window": 0, "unverified": 0, "invalid": 0}

    for row in rows:
        if not isinstance(row, dict) or str(row.get("candidate_type", "") or "") != "retrieval-source":
            continue
        outcome = str(row.get("outcome", "") or "").strip().lower()
        if outcome not in _SUCCESS_OUTCOMES | _FAILURE_OUTCOMES:
            discarded["unverified"] += 1
            continue
        evidence = row.get("evidence", []) or []
        if not evidence:
            discarded["unverified"] += 1
            continue
        timestamp = _parse_timestamp(row.get("recorded_at") or row.get("updated_at") or row.get("created_at"))
        if timestamp is None or timestamp < cutoff:
            discarded["outside_window"] += 1
            continue
        target = str(row.get("target", "") or "")
        if ":" not in target:
            discarded["invalid"] += 1
            continue
        intent, source = (value.strip().lower() for value in target.split(":", 1))
        if not intent or not source or not bounded_retrieval_source_weights({source: 0.5}):
            discarded["invalid"] += 1
            continue
        bucket = grouped[(intent, source)]
        bucket["positive" if outcome in _SUCCESS_OUTCOMES else "negative"] += 1

    total_samples = sum(values["positive"] + values["negative"] for values in grouped.values())
    proposals: dict[str, dict[str, dict[str, Any]]] = {}
    applied_weights: dict[str, dict[str, float]] = {}
    for (intent, source), counts in sorted(grouped.items()):
        sample_count = counts["positive"] + counts["negative"]
        baseline = float(load_retrieval_source_weights(workspace_file, intent=intent).get(source, 0.5))
        posterior_success = (counts["positive"] + 1.0) / (sample_count + 2.0)
        observed_weight = 0.35 + posterior_success * 0.4
        shrinkage = sample_count / (sample_count + _PRIOR_STRENGTH)
        proposed = baseline + (observed_weight - baseline) * shrinkage
        entry = {
            "positive": counts["positive"],
            "negative": counts["negative"],
            "sample_count": sample_count,
            "baseline_weight": round(baseline, 4),
            "posterior_success_rate": round(posterior_success, 4),
            "shrinkage": round(shrinkage, 4),
            "proposed_weight": bounded_retrieval_source_weights({source: proposed})[source],
            "eligible": sample_count >= _MIN_SOURCE_SAMPLES,
        }
        proposals.setdefault(intent, {})[source] = entry
        if entry["eligible"]:
            applied_weights.setdefault(intent, {})[source] = entry["proposed_weight"]

    sufficient = total_samples >= max(1, min_samples) and bool(applied_weights)
    result = {
        "schema_version": 1,
        "status": "ready" if sufficient else "insufficient_replay",
        "lookback_days": max(1, lookback_days),
        "minimum_samples": max(1, min_samples),
        "minimum_source_samples": _MIN_SOURCE_SAMPLES,
        "total_verified_samples": total_samples,
        "discarded": discarded,
        "proposals": proposals,
        "applied_weights": applied_weights if sufficient else {},
        "applied": False,
        "next_action": (
            "review proposal and run again with --apply after enough verified retrieval outcomes"
            if sufficient else
            "record more human-verified retrieval-source feedback with evidence; guidance adoption alone is not calibration evidence"
        ),
    }
    if apply and sufficient:
        payload = {
            "schema_version": 1,
            "generated_at": now.isoformat(),
            "lookback_days": result["lookback_days"],
            "total_verified_samples": total_samples,
            "weights": applied_weights,
            "proposals": proposals,
        }
        store.write_json(RETRIEVAL_CALIBRATION_FILE, payload)
        result["applied"] = True
        result["next_action"] = "calibrated weights are active; rerun evaluation after additional verified replay data"
    return result


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
