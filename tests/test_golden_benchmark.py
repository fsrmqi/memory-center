from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memory_center.core.benchmark.golden import (
    build_golden_performance_baseline,
    compare_golden_performance,
    evaluate_agent_guidance,
    extract_logical_evidence,
    load_golden_performance_baseline,
    load_golden_cases,
    run_golden_suite,
    score_golden_case,
)
from memory_center.mcp.admin_actions import build_admin_registry


def _workspace(tmp_path: Path) -> Path:
    path = tmp_path / ".memory-center" / "workspace.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("workspace: golden-test\nroot: ..\nservices: []\n", encoding="utf-8")
    return path


def test_golden_case_scores_anchor_recall_and_forbidden_hits() -> None:
    result = score_golden_case(
        expected_anchors=["Entry#run", "RemoteController#list"],
        actual_anchors=["Entry#run", "WrongController#list"],
        forbidden_anchors=["WrongController#list"],
    )
    assert result["anchor_recall"] == 0.5
    assert result["forbidden_hit_count"] == 1
    assert result["passed"] is False


def test_load_golden_cases_rejects_private_path_fields(tmp_path: Path) -> None:
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        "cases:\n"
        "  - case_id: unsafe\n"
        "    query: Demo#run\n"
        "    mode: walkthrough\n"
        "    expected_anchors: [Demo#run]\n"
        "    expected_edges: []\n"
        "    source_path: /private/project/Demo.java\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported fields"):
        load_golden_cases(cases)


def test_run_golden_suite_reports_stable_quality_and_latency(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        "cases:\n"
        "  - case_id: full-chain\n"
        "    query: Entry#run\n"
        "    mode: walkthrough\n"
        "    expected_anchors: [Entry#run, RemoteController#list]\n"
        "    expected_edges: [CALLS_METHOD, IMPLEMENTS_FEIGN]\n"
        "    forbidden_anchors: [WrongController#list]\n",
        encoding="utf-8",
    )

    def runner(case):
        return {
            "anchors": ["Entry#run", "RemoteController#list"],
            "edges": ["CALLS_METHOD", "IMPLEMENTS_FEIGN"],
            "payload": {
                "completion_status": {
                    "state": "complete",
                    "recommended_action": "use_current_evidence",
                    "missing_layers": [],
                },
                "agent_usage_policy": {"do_not_search_when_absolute_path_present": True},
                "next_actions": ["使用当前 read_targets 证据继续总结，不需要 find"],
                "summary_lines": ["one", "two"],
            },
        }

    first = run_golden_suite(workspace, cases, case_runner=runner)
    second = run_golden_suite(workspace, cases, case_runner=runner)

    assert first["summary"]["anchor_recall"] == 1.0
    assert first["summary"]["edge_recall"] == 1.0
    assert first["summary"]["forbidden_hit_rate"] == 0.0
    assert first["summary"]["passed"] is True
    assert first["performance"]["median_latency_ms"] >= 0
    assert first["performance"]["p95_latency_ms"] >= first["performance"]["median_latency_ms"]
    assert first["performance"]["token_estimate"] > 0
    assert first["summary"]["agent_invalid_search_suggestion_count"] == 0
    assert first["summary"]["agent_invalid_search_reduction_rate"] >= 0.5
    assert first["cases"][0]["agent_guidance"]["completion_stop_signal"] is True
    assert first["performance_gate"]["status"] == "baseline_missing"
    assert first["performance_gate"]["current_baseline"]["performance"]["token_estimate"] > 0
    assert first["summary"] == second["summary"]


def test_agent_guidance_counts_only_positive_invalid_search_advice() -> None:
    payload = {
        "completion_status": {"state": "complete", "recommended_action": "use_current_evidence"},
        "agent_usage_policy": {
            "do_not_search_when_absolute_path_present": True,
            "avoid_tools": ["find", "grep -l", "rg --files"],
        },
        "anti_patterns": [
            {"avoid": "repo_wide_find_before_read_targets", "reason": "不要 find，直接读 absolute_file_path"}
        ],
        "next_actions": [
            "优先读 read_targets，不需要 find",
            "继续用 grep -l 全仓库搜索 Controller",
            "run sed -n 1,200p on guessed files",
        ],
    }

    guidance = evaluate_agent_guidance(payload)

    assert guidance["completion_stop_signal"] is True
    assert guidance["invalid_search_suggestion_count"] == 2
    assert guidance["invalid_search_suggestions"] == [
        "next_actions[1]: 继续用 grep -l 全仓库搜索 Controller",
        "next_actions[2]: run sed -n 1,200p on guessed files",
    ]
    assert guidance["invalid_search_reduction_rate"] == 0.0


def test_golden_performance_gate_reports_missing_baseline_without_failing() -> None:
    current = {
        "summary": {"anchor_recall": 1.0, "edge_recall": 1.0},
        "performance": {"median_latency_ms": 120.0, "token_estimate": 900},
    }

    gate = compare_golden_performance(current, baseline=None)

    assert gate["status"] == "baseline_missing"
    assert gate["passed"] is None
    assert gate["current_baseline"]["performance"]["median_latency_ms"] == 120.0
    assert gate["current_baseline"]["performance"]["token_estimate"] == 900


def test_golden_performance_gate_scores_latency_and_token_improvement(tmp_path: Path) -> None:
    current = {
        "summary": {"anchor_recall": 1.0, "edge_recall": 1.0},
        "performance": {"median_latency_ms": 80.0, "token_estimate": 700},
    }
    baseline = {
        "schema_version": 1,
        "label": "v3.2.0",
        "performance": {"median_latency_ms": 100.0, "token_estimate": 1000},
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    gate = compare_golden_performance(current, baseline=load_golden_performance_baseline(baseline_path))

    assert gate["status"] == "pass"
    assert gate["passed"] is True
    assert gate["latency"]["improvement_pct"] == 20.0
    assert gate["token"]["improvement_pct"] == 30.0


def test_golden_performance_gate_accepts_no_regression_against_current_baseline() -> None:
    current = {
        "summary": {"anchor_recall": 1.0, "edge_recall": 1.0},
        "performance": {"median_latency_ms": 100.0, "token_estimate": 1000},
    }
    baseline = {
        "schema_version": 1,
        "label": "v3.5.7-real-ucap",
        "performance": {"median_latency_ms": 100.0, "token_estimate": 1000},
    }

    gate = compare_golden_performance(current, baseline=baseline)

    assert gate["status"] == "pass"
    assert gate["passed"] is True
    assert gate["latency"]["improvement_pct"] == 0.0
    assert gate["token"]["improvement_pct"] == 0.0


def test_golden_performance_gate_allows_latency_jitter_but_not_token_growth() -> None:
    baseline = {
        "schema_version": 1,
        "label": "v3.5.7-real-ucap",
        "performance": {"median_latency_ms": 100.0, "token_estimate": 1000},
    }
    current = {
        "summary": {"anchor_recall": 1.0, "edge_recall": 1.0},
        "performance": {"median_latency_ms": 108.0, "token_estimate": 1000},
    }

    gate = compare_golden_performance(current, baseline=baseline)

    assert gate["status"] == "pass"
    assert gate["passed"] is True
    assert gate["latency"]["improvement_pct"] == -8.0
    assert gate["token"]["improvement_pct"] == 0.0


def test_golden_performance_gate_rejects_regression_against_current_baseline() -> None:
    current = {
        "summary": {"anchor_recall": 1.0, "edge_recall": 1.0},
        "performance": {"median_latency_ms": 121.0, "token_estimate": 1101},
    }
    baseline = {
        "schema_version": 1,
        "label": "v3.5.7-real-ucap",
        "performance": {"median_latency_ms": 100.0, "token_estimate": 1000},
    }

    gate = compare_golden_performance(current, baseline=baseline)

    assert gate["status"] == "fail"
    assert gate["passed"] is False
    assert gate["latency"]["passed"] is False
    assert gate["token"]["passed"] is False


def test_golden_performance_baseline_is_portable() -> None:
    result = {
        "summary": {"case_count": 1, "anchor_recall": 1.0, "edge_recall": 1.0},
        "performance": {"median_latency_ms": 80.0, "p95_latency_ms": 90.0, "token_estimate": 700},
        "cases": [{"payload": {"absolute_file_path": "/private/path/Demo.java"}}],
    }

    baseline = build_golden_performance_baseline(result, label="current")

    assert set(baseline) == {"schema_version", "label", "created_at", "summary", "performance"}
    assert "cases" not in baseline
    assert "path" not in json.dumps(baseline, ensure_ascii=False).lower()


def test_extract_logical_evidence_infers_walkthrough_edges_and_method_anchors() -> None:
    payload = {
        "target": {"class": "EntryService", "method": "run"},
        "same_class_method_continuations": [
            {"target": {"class": "EntryService", "method": "prepare"}}
        ],
        "feign_continuations": [
            {
                "interface": "RemoteClient",
                "server_walkthroughs": [
                    {
                        "controller": "RecordController",
                        "method": "list",
                        "service_impl_continuations": [
                            {
                                "target": {"class": "RecordServiceImpl", "method": "list"},
                                "same_class_method_continuations": [
                                    {
                                        "node": {
                                            "type": "Method",
                                            "name": "RecordRepository.fetch",
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    evidence = extract_logical_evidence(payload)

    assert "EntryService#run" in evidence["anchors"]
    assert "EntryService#prepare" in evidence["anchors"]
    assert "RecordController#list" in evidence["anchors"]
    assert "RecordServiceImpl#list" in evidence["anchors"]
    assert "RecordRepository#fetch" in evidence["anchors"]
    assert "CALLS_METHOD" in evidence["edges"]
    assert "IMPLEMENTS_FEIGN" in evidence["edges"]
    assert "HANDLES_ENDPOINT" in evidence["edges"]


def test_eval_golden_cli_command_dispatches_suite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from memory_center.cli.main import app
    from memory_center.core import benchmark as benchmark_module

    workspace = _workspace(tmp_path)
    cases = tmp_path / "cases.yaml"
    cases.write_text("cases:\n  - case_id: c1\n    query: Entry#run\n    mode: walkthrough\n    expected_anchors: []\n    expected_edges: []\n", encoding="utf-8")

    def fake_run(workspace_file: str | Path, cases_file: str | Path, performance_baseline=None) -> dict:
        assert Path(workspace_file) == workspace
        assert Path(cases_file) == cases
        assert performance_baseline is None
        return {"summary": {"passed": True}, "cases": []}

    monkeypatch.setattr(benchmark_module, "run_golden_suite", fake_run)
    result = CliRunner().invoke(app, ["eval-golden", "--workspace", str(workspace), "--cases", str(cases)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["summary"]["passed"] is True


def test_eval_golden_admin_action_dispatches_suite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from memory_center.core import benchmark as benchmark_module

    workspace = _workspace(tmp_path)
    cases = tmp_path / "cases.yaml"
    cases.write_text("cases:\n  - case_id: c1\n    query: Entry#run\n    mode: walkthrough\n    expected_anchors: []\n    expected_edges: []\n", encoding="utf-8")

    def fake_run(workspace_file: str | Path, cases_file: str | Path, performance_baseline=None) -> dict:
        assert Path(workspace_file) == workspace
        assert Path(cases_file) == cases
        assert performance_baseline is None
        return {"summary": {"passed": True}, "cases": []}

    monkeypatch.setattr(benchmark_module, "run_golden_suite", fake_run)
    registry = build_admin_registry(workspace_file=str(workspace), name=str(cases))

    payload = registry.dispatch("eval_golden")

    assert payload["summary"]["passed"] is True


def test_eval_golden_http_route_dispatches_suite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from memory_center.core import benchmark as benchmark_module
    from memory_center.http.server import _route_request

    workspace = _workspace(tmp_path)
    cases = tmp_path / "cases.yaml"
    cases.write_text("cases:\n  - case_id: c1\n    query: Entry#run\n    mode: walkthrough\n    expected_anchors: []\n    expected_edges: []\n", encoding="utf-8")

    def fake_run(workspace_file: str | Path, cases_file: str | Path, performance_baseline=None) -> dict:
        assert Path(workspace_file) == workspace
        assert Path(cases_file) == cases
        assert performance_baseline is None
        return {"summary": {"passed": True}, "cases": []}

    monkeypatch.setattr(benchmark_module, "run_golden_suite", fake_run)
    payload = _route_request(
        "/workspace/eval-golden",
        {"workspace": [str(workspace)], "cases": [str(cases)]},
        None,
    )

    assert payload["summary"]["passed"] is True


def test_public_golden_benchmark_suite_runs_on_demo_workspace(demo_workspace_indexed: Path) -> None:
    cases = Path("examples/golden-benchmark/cases.yaml")

    result = run_golden_suite(demo_workspace_indexed, cases)

    assert result["summary"]["passed"] is True, [
        (row["case_id"], row["missing_anchors"], row["actual_anchors"])
        for row in result["cases"]
    ]
    assert result["summary"]["anchor_recall"] >= 0.90
    assert result["summary"]["edge_recall"] >= 0.85
    assert result["summary"]["forbidden_hit_rate"] == 0.0
    assert {row["case_id"] for row in result["cases"]} >= {
        "article-move-full-chain",
        "article-move-hybrid-policy",
    }
