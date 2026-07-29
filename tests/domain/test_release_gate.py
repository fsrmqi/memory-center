from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memory_center.application import release_gate
from memory_center.cli.main import app


def _workspace(tmp_path: Path) -> Path:
    path = tmp_path / ".memory-center" / "workspace.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("workspace: release-gate-test\nroot: ..\nservices: []\n", encoding="utf-8")
    return path


def _patch_successful_components(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_gate, "reindex_workspace", lambda *_: {"files": 3})
    monkeypatch.setattr(release_gate, "memory_query_hybrid", lambda *_args, **_kwargs: {"matches": [{"id": "safe"}]})
    monkeypatch.setattr(
        release_gate,
        "run_golden_suite",
        lambda *_args, **_kwargs: {"summary": {"passed": True, "case_count": 2, "anchor_recall": 1.0}},
    )
    monkeypatch.setattr(
        release_gate,
        "memory_eval_java_call_resolution",
        lambda *_args, **_kwargs: {"summary": {"passed": True, "case_count": 2, "edge_recall": 1.0}},
    )
    monkeypatch.setattr(
        release_gate,
        "memory_eval_parser_benchmark",
        lambda *_args, **_kwargs: {"quality": "high", "score": 95, "files_scanned": 10},
    )


def test_release_gate_runs_all_configured_checks_without_private_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_successful_components(monkeypatch)

    result = release_gate.run_release_gate(
        _workspace(tmp_path),
        queries=["private query text"],
        golden_cases=tmp_path / "private-golden.yaml",
        java_call_cases=tmp_path / "private-java.yaml",
        parser_limit=10,
    )

    assert result["passed"] is True
    assert set(result["components"]) == {"reindex", "retrieval", "golden", "java_call_resolution", "parser_precision"}
    serialized = json.dumps(result, ensure_ascii=False)
    assert "private query text" not in serialized
    assert "private-golden.yaml" not in serialized
    assert "private-java.yaml" not in serialized


def test_release_gate_baseline_is_portable_and_detects_regression() -> None:
    result = {
        "components": {
            "reindex": {"status": "pass", "metrics": {"duration_ms": 100, "result_count": 3, "quality_score": 1.0}},
            "retrieval": {"status": "skipped", "metrics": {}},
        }
    }
    baseline = release_gate.build_release_gate_baseline(result, label="v1")
    comparison = release_gate.compare_release_gate_baseline(
        {"components": {"reindex": {"status": "pass", "metrics": {"duration_ms": 130, "result_count": 3, "quality_score": 0.95}}}},
        baseline=baseline,
        max_latency_regression_pct=15.0,
        max_quality_drop=0.02,
    )

    assert baseline["components"]["reindex"] == {
        "status": "pass",
        "duration_ms": 100.0,
        "result_count": 3,
        "quality_score": 1.0,
    }
    assert comparison["passed"] is False
    assert comparison["components"]["reindex"]["latency_change_pct"] == 30.0


def test_release_gate_records_and_compares_hot_query_p95(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_successful_components(monkeypatch)
    durations = iter(index / 100.0 for index in range(20))
    monkeypatch.setattr(release_gate.time, "perf_counter", lambda: next(durations))

    result = release_gate.run_release_gate(
        _workspace(tmp_path),
        queries=["stable logical query"],
        query_samples=2,
    )
    metrics = result["components"]["retrieval"]["metrics"]
    baseline = release_gate.build_release_gate_baseline(result)

    assert metrics["query_samples"] == 2
    assert "cold_duration_ms" in metrics
    assert "hot_p95_duration_ms" in metrics
    assert baseline["components"]["retrieval"]["hot_p95_duration_ms"] == round(metrics["hot_p95_duration_ms"], 3)


def test_release_gate_percentile_uses_upper_rank_for_small_samples() -> None:
    assert release_gate._percentile([10.0, 20.0], 0.95) == 20.0


def test_release_gate_baseline_round_trip(tmp_path: Path) -> None:
    output = tmp_path / "release-gate-baseline.json"
    saved = release_gate.save_release_gate_baseline(
        {
            "components": {
                "retrieval": {
                    "status": "pass",
                    "metrics": {"duration_ms": 12.5, "result_count": 2, "quality_score": 1.0},
                    "private_query": "must not persist",
                }
            }
        },
        output,
        label="v1",
    )

    loaded = release_gate.load_release_gate_baseline(output)

    assert saved["saved"] is True
    assert loaded["label"] == "v1"
    assert "private_query" not in output.read_text(encoding="utf-8")


def test_release_gate_fails_low_parser_precision(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_successful_components(monkeypatch)
    monkeypatch.setattr(
        release_gate,
        "memory_eval_parser_benchmark",
        lambda *_args, **_kwargs: {"quality": "low", "score": 0, "files_scanned": 10},
    )

    result = release_gate.run_release_gate(_workspace(tmp_path), parser_limit=10)

    assert result["passed"] is False
    assert result["failed_components"] == ["parser_precision"]
    assert result["components"]["parser_precision"]["reason"] == "parser_quality_insufficient"


def test_release_gate_cli_does_not_save_failed_baseline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "portable.json"
    monkeypatch.setattr(
            "memory_center.application.release_gate.run_release_gate",
        lambda *_args, **_kwargs: {
            "passed": False,
            "components": {"reindex": {"status": "fail", "metrics": {"duration_ms": 1, "result_count": 0, "quality_score": 0}}},
        },
    )
    monkeypatch.setattr(
            "memory_center.application.release_gate.save_release_gate_baseline",
        lambda result, path, *, label: {"saved": True, "baseline_file": str(path), "baseline": {"label": label, "components": result["components"]}},
    )

    invoked = CliRunner().invoke(app, ["release-gate", "--workspace", "demo.yaml", "--save-baseline", str(output), "--label", "v1"])

    assert invoked.exit_code == 1
    assert '"saved": false' in invoked.output
    assert "release_gate_failed" in invoked.output
