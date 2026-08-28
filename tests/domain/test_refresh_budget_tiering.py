"""Scoped-refresh budget tiering tests (refresh-budget calibration).

Verifies per-bucket classification, per-bucket budgets, by-bucket P50/P95
aggregation, legacy (pre-bucket) sample exclusion from the over-budget gate,
and the >=5-sample rule before a bucket can flag over budget.
"""
from __future__ import annotations

from memory_center.core.retrieval.planner import (
    BUCKET_BUDGETS_MS,
    bucket_budget_ms,
    classify_refresh_bucket,
)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_plain_java_single_file():
    b = classify_refresh_bucket(paths=["a/b/SomeService.java"], projects=["p"], scanned_files=1)
    assert b == "plain_java/single_file"


def test_contract_controller_classified():
    b = classify_refresh_bucket(paths=["a/Controller.java"], projects=["p"], scanned_files=1)
    assert b == "contract/single_file"


def test_contract_feign_classified():
    b = classify_refresh_bucket(paths=["a/FeignClient.java"], projects=["p"], scanned_files=1)
    assert b == "contract/single_file"


def test_multi_file_single_service():
    b = classify_refresh_bucket(paths=["a/A.java", "a/B.java"], projects=["p"], scanned_files=2)
    assert b == "plain_java/multi_file_single_service"


def test_multi_service():
    b = classify_refresh_bucket(paths=["a/A.java"], projects=["p1", "p2"], scanned_files=2)
    assert b == "plain_java/multi_service"


def test_delete_marker_classified():
    b = classify_refresh_bucket(paths=["a/Deleted.java", "deleted_old"], projects=["p"], scanned_files=1)
    assert b == "delete_or_move/single_file"


def test_zero_scan_with_paths_is_unknown_not_delete():
    """Paths given but nothing scanned (scope mismatch) must not be treated as
    a delete (a real delete is only claimed by an explicit marker)."""
    b = classify_refresh_bucket(paths=["a/SomeService.java"], projects=["p"], scanned_files=0)
    assert b.startswith("unknown/")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def test_every_bucket_has_a_budget():
    for bucket in BUCKET_BUDGETS_MS:
        assert bucket_budget_ms(bucket) > 0
    # single-file low-risk is tighter than multi-service contract
    assert BUCKET_BUDGETS_MS["plain_java/single_file"] < BUCKET_BUDGETS_MS["contract/multi_service"]
    assert BUCKET_BUDGETS_MS["contract/single_file"] >= BUCKET_BUDGETS_MS["plain_java/single_file"]


def test_unknown_bucket_falls_back():
    assert bucket_budget_ms("no/such/bucket") == 15_000.0


# ---------------------------------------------------------------------------
# Aggregation & legacy exclusion
# ---------------------------------------------------------------------------


def _sample(bucket: str, total_ms: float, dominant: str = "generation_publish") -> dict:
    return {
        "bucket": bucket,
        "timing_ms": {"total": total_ms},
        "dominant_stage": dominant,
        "status": "warning" if total_ms > 10_000 else "healthy",
    }


def test_status_excludes_legacy_unknown_bucket(monkeypatch, tmp_path):
    """Legacy observations (unknown/multi_file, no real bucket) must not gate
    the over-budget decision; only real buckets with >=5 samples do."""
    import json
    from pathlib import Path

    from memory_center.core.retrieval import planner

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    (ws_dir / "index").mkdir(parents=True)
    (ws_dir / "graph").mkdir()
    (ws_dir / "memory").mkdir()
    ws_file = ws_dir / "workspace.yaml"
    ws_file.write_text("workspace: demo\nroot: .\nservices: []\n", encoding="utf-8")

    ledger = ws_dir / "memory" / planner.SCOPED_REFRESH_PERFORMANCE_FILE
    # 60 legacy (unknown/multi_file) + 4 real contract/single_file (under 5)
    rows = [_sample("unknown/multi_file", 40_000.0) for _ in range(60)]
    rows += [_sample("contract/single_file", 30_000.0) for _ in range(4)]
    with open(ledger, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    r = planner.scoped_refresh_performance_status(str(ws_file), limit=100)
    # No real bucket has >=5 samples -> no over_budget bucket.
    assert r["over_budget_buckets"] == []
    # by_bucket still reports the legacy bucket as legacy.
    assert r["by_bucket"]["unknown/multi_file"]["legacy"] is True
    assert r["by_bucket"]["contract/single_file"]["samples"] == 4


def test_real_bucket_over_budget_only_with_5_samples(monkeypatch, tmp_path):
    """A real bucket with <5 samples must NOT flag over budget even if P95 is
    high; with >=5 and P95 over its own budget it must."""
    import json
    from pathlib import Path

    from memory_center.core.retrieval import planner

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    (ws_dir / "index").mkdir(parents=True)
    (ws_dir / "graph").mkdir()
    (ws_dir / "memory").mkdir()
    ws_file = ws_dir / "workspace.yaml"
    ws_file.write_text("workspace: demo\nroot: .\nservices: []\n", encoding="utf-8")

    ledger = ws_dir / "memory" / planner.SCOPED_REFRESH_PERFORMANCE_FILE
    rows = [_sample("contract/single_file", 30_000.0) for _ in range(4)]
    with open(ledger, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    r = planner.scoped_refresh_performance_status(str(ws_file), limit=100)
    assert r["by_bucket"]["contract/single_file"]["over_budget"] is False  # n=4

    rows = [_sample("contract/single_file", 30_000.0) for _ in range(5)]
    with open(ledger, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    r2 = planner.scoped_refresh_performance_status(str(ws_file), limit=100)
    assert r2["by_bucket"]["contract/single_file"]["over_budget"] is True  # n=5 over 15s
    assert r2["over_budget_buckets"] == ["contract/single_file"]


def test_dominant_stage_aggregated_per_bucket(monkeypatch, tmp_path):
    import json
    from pathlib import Path

    from memory_center.core.retrieval import planner

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    (ws_dir / "index").mkdir(parents=True)
    (ws_dir / "graph").mkdir()
    (ws_dir / "memory").mkdir()
    ws_file = ws_dir / "workspace.yaml"
    ws_file.write_text("workspace: demo\nroot: .\nservices: []\n", encoding="utf-8")
    ledger = ws_dir / "memory" / planner.SCOPED_REFRESH_PERFORMANCE_FILE
    rows = [_sample("contract/single_file", 5_000.0, dominant="generation_publish") for _ in range(5)]
    with open(ledger, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    r = planner.scoped_refresh_performance_status(str(ws_file), limit=100)
    assert r["by_bucket"]["contract/single_file"]["dominant_stage"] == "generation_publish"
