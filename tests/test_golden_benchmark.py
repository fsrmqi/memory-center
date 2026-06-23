from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from memory_center.core.benchmark.golden import (
    extract_logical_evidence,
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
            "payload": {"summary_lines": ["one", "two"]},
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
    assert first["summary"] == second["summary"]


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

    def fake_run(workspace_file: str | Path, cases_file: str | Path) -> dict:
        assert Path(workspace_file) == workspace
        assert Path(cases_file) == cases
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

    def fake_run(workspace_file: str | Path, cases_file: str | Path) -> dict:
        assert Path(workspace_file) == workspace
        assert Path(cases_file) == cases
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

    def fake_run(workspace_file: str | Path, cases_file: str | Path) -> dict:
        assert Path(workspace_file) == workspace
        assert Path(cases_file) == cases
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
