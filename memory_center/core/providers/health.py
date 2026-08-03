"""Provider 的进程内健康、延迟和成本观测。"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from statistics import quantiles
from time import monotonic


@dataclass(frozen=True)
class ProviderObservation:
    duration_ms: float
    status: str
    observed_at: float


class ProviderHealthMonitor:
    """仅保留最近调用摘要；不扫描仓库、不写入工作区。"""

    def __init__(self, window_size: int = 64) -> None:
        self._window_size = max(8, min(window_size, 512))
        self._records: dict[str, deque[ProviderObservation]] = defaultdict(lambda: deque(maxlen=self._window_size))

    def record(self, provider: str, duration_ms: float, status: str) -> None:
        self._records[provider].append(
            ProviderObservation(max(0.0, float(duration_ms or 0.0)), str(status or "unavailable"), monotonic())
        )

    def snapshot(self, provider: str) -> dict[str, float | int | str]:
        rows = list(self._records.get(provider, ()))
        if not rows:
            return {"status": "unknown", "samples": 0, "p95_ms": 0.0, "error_rate": 0.0, "cost_score": 0.0}
        durations = sorted(row.duration_ms for row in rows)
        p95 = durations[-1] if len(durations) < 20 else quantiles(durations, n=20, method="inclusive")[18]
        errors = sum(row.status != "ready" for row in rows)
        error_rate = errors / len(rows)
        return {
            "status": "healthy" if error_rate < 0.2 else "degraded",
            "samples": len(rows),
            "p95_ms": round(p95, 2),
            "error_rate": round(error_rate, 4),
            "cost_score": round((p95 / 1000.0) + (error_rate * 10.0), 4),
        }

    def routing_penalty(self, provider: str) -> float:
        snapshot = self.snapshot(provider)
        return float(snapshot["cost_score"]) * 10.0
