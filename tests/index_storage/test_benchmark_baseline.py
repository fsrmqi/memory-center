from __future__ import annotations

from pathlib import Path

from memory_center.core.benchmark.baseline import (
    compare_baseline_samples,
    record_baseline_sample,
)
from memory_center.core.storage.workspace import WorkspaceStore


def _workspace(tmp_path: Path) -> Path:
    path = tmp_path / ".memory-center" / "workspace.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("workspace: test\nroot: ..\nservices: []\n", encoding="utf-8")
    return path


def test_record_baseline_sample_contains_only_portable_fields(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    result = record_baseline_sample(
        workspace,
        operation="walkthrough",
        topology_size=120,
        duration_ms=42.5,
        result_count=8,
        quality_score=0.9,
        parser="tree-sitter",
    )
    entry = result["entry"]
    assert set(entry) == {
        "timestamp", "operation", "topology_size", "duration_ms",
        "result_count", "quality_score", "parser",
    }
    persisted = WorkspaceStore(workspace).read_jsonl("portable-benchmark-baselines.jsonl", 1)[0]
    assert not any("path" in key or "payload" in key for key in persisted)


def test_compare_baseline_samples_detects_latency_and_quality_regression() -> None:
    baseline = [
        {"duration_ms": 100, "quality_score": 0.9},
        {"duration_ms": 110, "quality_score": 0.88},
        {"duration_ms": 90, "quality_score": 0.92},
    ]
    current = [
        {"duration_ms": 150, "quality_score": 0.7},
        {"duration_ms": 160, "quality_score": 0.72},
    ]
    result = compare_baseline_samples(baseline, current, latency_threshold_pct=20, quality_drop_threshold=0.1)
    assert result["status"] == "regression"
    assert result["latency"]["regressed"] is True
    assert result["quality"]["regressed"] is True
