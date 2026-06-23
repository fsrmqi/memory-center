from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..store import WorkspaceStore

PORTABLE_BASELINE_FILE = "portable-benchmark-baselines.jsonl"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def record_baseline_sample(
    workspace_file: str | Path,
    *,
    operation: str,
    topology_size: int,
    duration_ms: float,
    result_count: int,
    quality_score: float,
    parser: str = "",
) -> dict[str, Any]:
    if not _SAFE_NAME.fullmatch(operation or ""):
        raise ValueError("operation must be a portable identifier")
    if parser and not _SAFE_NAME.fullmatch(parser):
        raise ValueError("parser must be a portable identifier")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "topology_size": max(0, int(topology_size)),
        "duration_ms": round(max(0.0, float(duration_ms)), 3),
        "result_count": max(0, int(result_count)),
        "quality_score": round(min(1.0, max(0.0, float(quality_score))), 4),
        "parser": parser,
    }
    WorkspaceStore(workspace_file).append_jsonl(PORTABLE_BASELINE_FILE, entry)
    return {"recorded": True, "entry": entry}


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return float(ordered[index])


def _summary(samples: Iterable[dict[str, Any]]) -> dict[str, float]:
    rows = list(samples)
    durations = [float(row.get("duration_ms", 0.0) or 0.0) for row in rows]
    qualities = [float(row.get("quality_score", 0.0) or 0.0) for row in rows]
    return {
        "count": float(len(rows)),
        "median_ms": float(statistics.median(durations)) if durations else 0.0,
        "p95_ms": _percentile(durations, 0.95),
        "quality_avg": (sum(qualities) / len(qualities)) if qualities else 0.0,
    }


def compare_baseline_samples(
    baseline: Iterable[dict[str, Any]],
    current: Iterable[dict[str, Any]],
    *,
    latency_threshold_pct: float = 20.0,
    quality_drop_threshold: float = 0.1,
) -> dict[str, Any]:
    base = _summary(baseline)
    now = _summary(current)
    base_latency = base["median_ms"]
    latency_change = ((now["median_ms"] - base_latency) / base_latency * 100.0) if base_latency else 0.0
    quality_drop = base["quality_avg"] - now["quality_avg"]
    latency_regressed = latency_change > latency_threshold_pct
    quality_regressed = quality_drop > quality_drop_threshold
    return {
        "status": "regression" if latency_regressed or quality_regressed else "pass",
        "baseline": base,
        "current": now,
        "latency": {"change_pct": round(latency_change, 2), "regressed": latency_regressed},
        "quality": {"drop": round(quality_drop, 4), "regressed": quality_regressed},
    }
