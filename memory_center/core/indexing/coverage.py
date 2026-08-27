"""Per-file index coverage ledger and aggregation.

Phase A of CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md requires every query
response to carry an explicit coverage contract so agents can never treat
"not found in the graph" as "does not exist". This module is the writer
side: during reindex it records one coverage row per discovered file
(``parsed`` | ``partial`` | ``skipped`` | ``failed`` plus a bounded
machine-readable reason), and publishes an aggregate ``coverage_summary``
next to the graph summary when the staging generation activates.

The ledger never stores source content, absolute private paths beyond the
workspace-relative logical path already persisted in ``file-index.json``,
or prompts.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

COVERAGE_FILE = "index-coverage.json"

STATUS_PARSED = "parsed"
STATUS_PARTIAL = "partial"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


class CoverageLedger:
    """Bounded per-file coverage bookkeeping for one indexing run."""

    def __init__(self) -> None:
        # file_path -> {"status": str, "reason": str}
        self._files: dict[str, dict[str, str]] = {}

    def record(self, file_path: str, status: str, reason: str = "") -> None:
        """Record or update one file's coverage status."""
        if not file_path:
            return
        self._files[file_path] = {"status": status, "reason": reason[:120]}

    def update_status(self, file_path: str, status: str, reason: str = "") -> None:
        self.record(file_path, status, reason)

    def summary(self) -> dict[str, Any]:
        """Aggregate counts plus deduplicated reason codes with frequencies."""
        counts: Counter[str] = Counter()
        reasons: Counter[str] = Counter()
        for entry in self._files.values():
            counts[entry["status"]] += 1
            if entry["reason"]:
                reasons[entry["reason"]] += 1
        return {
            "parsed": counts[STATUS_PARSED],
            "partial": counts[STATUS_PARTIAL],
            "skipped": counts[STATUS_SKIPPED],
            "failed": counts[STATUS_FAILED],
            "total_files": sum(counts.values()),
            "reasons": [{"code": code, "count": count} for code, count in sorted(reasons.items())],
        }

    def to_rows(self) -> list[dict[str, Any]]:
        """Deterministically sorted per-file rows for persistence."""
        return [
            {"path": path, "status": entry["status"], "reason": entry["reason"]}
            for path, entry in sorted(self._files.items())
        ]

    def __len__(self) -> int:
        return len(self._files)


def write_coverage(
    store,
    generation: str,
    ledger: CoverageLedger,
    *,
    mode: str = "full",
) -> dict[str, Any]:
    """Persist per-file coverage and return the published aggregate."""
    aggregate = ledger.summary()
    snapshot = {
        "schema_version": 1,
        "generation": generation,
        "mode": mode,
        **aggregate,
        "files": ledger.to_rows(),
    }
    store.write_json(COVERAGE_FILE, snapshot)
    return aggregate


def attach_coverage_summary(target: dict[str, Any], aggregate: dict[str, Any] | None) -> dict[str, Any]:
    """Attach a compact aggregate onto a summary/control payload (additive)."""
    if aggregate:
        target["coverage_summary"] = {
            key: aggregate[key]
            for key in ("parsed", "partial", "skipped", "failed", "total_files")
            if key in aggregate
        }
        target["coverage_reasons"] = aggregate.get("reasons", [])
    return target
