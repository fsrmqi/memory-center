"""Lightweight structured metrics collector for Memory Center.

Provides query latency, index timing, and recall quality metrics
without external dependencies. Stores metrics in JSONL for
observability and regression detection.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

METRICS_FILE = "metrics.jsonl"


class MetricsCollector:
    """Thread-safe metrics collector backed by JSONL."""

    def __init__(self, workspace_file: str | Path):
        self._path = Path(workspace_file).parent / METRICS_FILE

    def record(self, metric_name: str, value: float, unit: str = "ms", tags: Optional[Dict[str, str]] = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metric": metric_name,
            "value": value,
            "unit": unit,
            "tags": tags or {},
        }
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # metrics are best-effort

    @contextmanager
    def timer(self, metric_name: str, tags: Optional[Dict[str, str]] = None) -> Generator[Dict[str, Any], None, None]:
        """Context manager to time an operation and record the metric."""
        start = time.monotonic()
        info: Dict[str, Any] = {}
        try:
            yield info
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            self.record(metric_name, elapsed_ms, unit="ms", tags=tags)

    def query(self, metric_name: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        """Read recent metrics."""
        if not self._path.exists():
            return []
        rows = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        if not metric_name or row.get("metric") == metric_name:
                            rows.append(row)
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return rows[-limit:]

    def summary(self, metric_name: str, limit: int = 100) -> Dict[str, Any]:
        """Summarize a metric (avg, p50, p95, p99)."""
        rows = [r for r in self.query(metric_name, limit=limit) if r.get("unit") == "ms"]
        if not rows:
            return {"metric": metric_name, "count": 0}
        values = sorted(r["value"] for r in rows)
        count = len(values)
        return {
            "metric": metric_name,
            "count": count,
            "avg_ms": round(sum(values) / count, 2),
            "p50_ms": round(values[count // 2], 2),
            "p95_ms": round(values[int(count * 0.95)], 2),
            "p99_ms": round(values[int(count * 0.99)], 2),
            "min_ms": round(values[0], 2),
            "max_ms": round(values[-1], 2),
        }
