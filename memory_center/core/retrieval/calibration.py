"""基于人工验证回放的检索融合权重校准。

仅使用 ``retrieval-source`` 的带证据验证记录。agent guidance 是否被执行不等于
检索结果正确，因此不会参与此处的权重学习。
"""
from __future__ import annotations

import hashlib
import json
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
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    discarded = {"outside_window": 0, "unverified": 0, "invalid": 0, "duplicate": 0}
    seen_samples: set[str] = set()

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
        sample_ref = _sample_ref(row, target)
        if sample_ref in seen_samples:
            discarded["duplicate"] += 1
            continue
        seen_samples.add(sample_ref)
        grouped[(intent, source)].append(
            {
                "timestamp": timestamp,
                "positive": outcome in _SUCCESS_OUTCOMES,
                "weight_before": float(row.get("weight_before", 0.5) or 0.5),
            }
        )

    total_samples = sum(len(values) for values in grouped.values())
    proposals: dict[str, dict[str, dict[str, Any]]] = {}
    applied_weights: dict[str, dict[str, float]] = {}
    for (intent, source), samples in sorted(grouped.items()):
        samples.sort(key=lambda item: item["timestamp"])
        sample_count = len(samples)
        validation_count = max(2, (sample_count + 3) // 4) if sample_count >= 6 else 0
        train = samples[:-validation_count] if validation_count else samples
        validation = samples[-validation_count:] if validation_count else []
        positive = sum(1 for item in train if item["positive"])
        negative = len(train) - positive
        baseline = float(train[-1]["weight_before"] if train else load_retrieval_source_weights(workspace_file, intent=intent).get(source, 0.5))
        posterior_success = (positive + 1.0) / (len(train) + 2.0)
        observed_weight = 0.35 + posterior_success * 0.4
        shrinkage = len(train) / (len(train) + _PRIOR_STRENGTH)
        proposed = baseline + (observed_weight - baseline) * shrinkage
        proposed_weight = bounded_retrieval_source_weights({source: proposed})[source]
        baseline_brier = _brier(validation, baseline)
        proposed_brier = _brier(validation, proposed_weight)
        validated = bool(validation) and proposed_brier <= baseline_brier
        entry = {
            "positive": positive,
            "negative": negative,
            "sample_count": sample_count,
            "training_count": len(train),
            "validation_count": len(validation),
            "baseline_weight": round(baseline, 4),
            "posterior_success_rate": round(posterior_success, 4),
            "shrinkage": round(shrinkage, 4),
            "proposed_weight": proposed_weight,
            "baseline_brier": baseline_brier,
            "proposed_brier": proposed_brier,
            "validated": validated,
            "eligible": len(train) >= _MIN_SOURCE_SAMPLES and len(validation) >= 2 and validated,
        }
        proposals.setdefault(intent, {})[source] = entry
        if entry["eligible"]:
            applied_weights.setdefault(intent, {})[source] = entry["proposed_weight"]

    sufficient = total_samples >= max(1, min_samples) and bool(applied_weights)
    result = {
        "schema_version": 2,
        "status": "ready" if sufficient else "insufficient_replay",
        "lookback_days": max(1, lookback_days),
        "minimum_samples": max(1, min_samples),
        "minimum_source_samples": _MIN_SOURCE_SAMPLES,
        "total_verified_samples": total_samples,
        "evaluation_mode": "chronological_holdout",
        "temporal_integrity": "training_samples_strictly_precede_validation_samples",
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
            "schema_version": 2,
            "generated_at": now.isoformat(),
            "lookback_days": result["lookback_days"],
            "total_verified_samples": total_samples,
            "weights": applied_weights,
            "proposals": proposals,
            "evaluation_mode": result["evaluation_mode"],
            "temporal_integrity": result["temporal_integrity"],
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


def _sample_ref(row: dict[str, Any], target: str) -> str:
    task_id = str(row.get("task_id", "") or "")
    session_id = str(row.get("session_id", "") or "")
    evidence = json.dumps(row.get("evidence", []), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    identity = f"task:{task_id}" if task_id else f"session:{session_id}:{evidence}" if session_id else f"evidence:{evidence}"
    return hashlib.sha256(f"{target}:{identity}".encode("utf-8", errors="replace")).hexdigest()


def _brier(samples: list[dict[str, Any]], probability: float) -> float:
    if not samples:
        return 0.0
    bounded = max(0.0, min(1.0, float(probability)))
    return round(sum((bounded - (1.0 if item["positive"] else 0.0)) ** 2 for item in samples) / len(samples), 6)
