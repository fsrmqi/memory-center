from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory_center.application.admin import build_admin_registry
from memory_center.application.golden import run_golden_suite
from memory_center.core.benchmark.golden import (
    build_golden_performance_baseline,
    compare_golden_performance,
    evaluate_agent_guidance,
    extract_logical_evidence,
    load_golden_cases,
    load_golden_performance_baseline,
    save_golden_performance_baseline,
    score_golden_case,
    summarize_golden_case_coverage,
)


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

    cases.write_text(
        "cases:\n"
        "  - case_id: unsafe-project\n"
        "    query: DemoService\n"
        "    mode: context\n"
        "    project: /private/project\n"
        "    expected_anchors: [DemoService#run]\n"
        "    expected_edges: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="golden project"):
        load_golden_cases(cases)


def test_golden_cases_support_impact_and_context_modes_with_project_scope(tmp_path: Path) -> None:
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        "cases:\n"
        "  - case_id: impact\n"
        "    query: OrderService\n"
        "    mode: impact\n"
        "    project: order-service\n"
        "    expected_anchors: [OrderService#submit]\n"
        "    expected_edges: [CALLS_METHOD]\n"
        "  - case_id: context\n"
        "    query: OrderService\n"
        "    mode: context\n"
        "    project: order-service\n"
        "    expected_anchors: [OrderService#submit]\n"
        "    expected_edges: []\n",
        encoding="utf-8",
    )

    loaded = load_golden_cases(cases)

    assert [(case.mode, case.project) for case in loaded] == [
        ("impact", "order-service"),
        ("context", "order-service"),
    ]


def test_golden_default_runner_dispatches_impact_and_context_modes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import memory_center.core.orchestrator as orchestrator

    workspace = _workspace(tmp_path)
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        "cases:\n"
        "  - case_id: impact\n"
        "    query: OrderService\n"
        "    mode: impact\n"
        "    project: order-service\n"
        "    expected_anchors: [OrderService#submit]\n"
        "    expected_edges: []\n"
        "  - case_id: context\n"
        "    query: OrderService\n"
        "    mode: context\n"
        "    project: order-service\n"
        "    expected_anchors: [OrderService#submit]\n"
        "    expected_edges: []\n",
        encoding="utf-8",
    )
    calls: list[tuple[str, str, str]] = []

    def fake_impact(_workspace, target, *, project="", **_kwargs):
        calls.append(("impact", target, project))
        return {"affected": [{"class": "OrderService", "method": "submit"}]}

    def fake_context(_workspace, name, *, project="", **_kwargs):
        calls.append(("context", name, project))
        return {"matches": [{"class": "OrderService", "method": "submit"}]}

    monkeypatch.setattr(orchestrator, "memory_impact", fake_impact)
    monkeypatch.setattr(orchestrator, "memory_context", fake_context)

    result = run_golden_suite(workspace, cases)

    assert result["summary"]["passed"] is True
    assert calls == [("impact", "OrderService", "order-service"), ("context", "OrderService", "order-service")]


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
                "agent_next_steps": [
                    {
                        "action": "use_read_targets",
                        "command": "read read_targets[].absolute_file_path directly; do not run find/grep-l",
                    }
                ],
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
    assert first["summary"]["agent_next_step_count"] == 1
    assert first["summary"]["agent_next_step_action_counts"] == {"use_read_targets": 1}
    assert first["cases"][0]["agent_guidance"]["completion_stop_signal"] is True
    assert first["cases"][0]["agent_guidance"]["agent_next_step_actions"] == ["use_read_targets"]
    assert first["performance_gate"]["status"] == "baseline_missing"
    assert first["performance_gate"]["current_baseline"]["performance"]["token_estimate"] > 0
    assert first["summary"] == second["summary"]


def test_golden_case_coverage_summary_is_portable(tmp_path: Path) -> None:
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        "cases:\n"
        "  - case_id: full-chain\n"
        "    query: Entry#run\n"
        "    mode: walkthrough\n"
        "    expected_anchors: [Entry#run, RemoteController#list]\n"
        "    expected_edges: [CALLS_METHOD, HANDLES_ENDPOINT]\n"
        "  - case_id: hybrid-query\n"
        "    query: UserService\n"
        "    mode: hybrid\n"
        "    expected_anchors: [UserService#list]\n"
        "    expected_edges: []\n",
        encoding="utf-8",
    )

    coverage = summarize_golden_case_coverage(cases)

    assert coverage["case_count"] == 2
    assert coverage["modes"] == {"hybrid": 1, "walkthrough": 1}
    assert coverage["expected_anchor_count"] == 3
    assert coverage["expected_edge_count"] == 2
    assert coverage["portable"] is True
    assert "mq" in coverage["recommended_additions"]


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


def test_agent_guidance_checks_agent_next_steps_for_invalid_search_advice() -> None:
    payload = {
        "agent_next_steps": [
            {
                "action": "use_read_targets",
                "command": "read read_targets[].absolute_file_path directly; do not run find/grep-l",
            },
            {
                "action": "bad_search",
                "command": "run grep -l across the repository to locate the same controller",
            },
        ]
    }

    guidance = evaluate_agent_guidance(payload)

    assert guidance["invalid_search_suggestion_count"] == 1
    assert guidance["agent_next_step_count"] == 2
    assert guidance["agent_next_step_actions"] == ["use_read_targets", "bad_search"]
    assert guidance["invalid_search_suggestions"] == [
        "agent_next_steps[1].command: run grep -l across the repository to locate the same controller"
    ]
    assert guidance["passed"] is False


def test_agent_guidance_accepts_payload_without_search_advice() -> None:
    guidance = evaluate_agent_guidance({"matches": [{"name": "ConfigKey"}]})

    assert guidance["invalid_search_suggestion_count"] == 0
    assert guidance["invalid_search_reduction_rate"] == 1.0
    assert guidance["passed"] is True


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
        "summary": {
            "case_count": 2,
            "anchor_recall": 1.0,
            "edge_recall": 1.0,
            "agent_next_step_count": 2,
            "agent_next_step_action_counts": {"use_read_targets": 2},
            "agent_invalid_search_suggestion_count": 0,
            "agent_invalid_search_reduction_rate": 1.0,
        },
        "performance": {"median_latency_ms": 80.0, "token_estimate": 700},
    }
    baseline = {
        "schema_version": 1,
        "label": "v3.2.0",
        "summary": {
            "case_count": 2,
            "agent_next_step_count": 2,
            "agent_next_step_action_counts": {"use_read_targets": 2},
            "agent_invalid_search_suggestion_count": 0,
            "agent_invalid_search_reduction_rate": 1.0,
        },
        "performance": {"median_latency_ms": 100.0, "token_estimate": 1000},
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    gate = compare_golden_performance(current, baseline=load_golden_performance_baseline(baseline_path))

    assert gate["status"] == "pass"
    assert gate["passed"] is True
    assert gate["latency"]["improvement_pct"] == 20.0
    assert gate["token"]["improvement_pct"] == 30.0
    assert gate["agent_guidance"]["passed"] is True
    assert gate["agent_guidance"]["current_steps_per_case"] == 1.0


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


def test_golden_performance_gate_normalizes_tokens_when_case_coverage_expands() -> None:
    baseline = {
        "schema_version": 1,
        "label": "v3.5.7-real-ucap",
        "summary": {"case_count": 1},
        "performance": {"median_latency_ms": 100.0, "token_estimate": 1000},
    }
    current = {
        "summary": {"case_count": 4},
        "performance": {"median_latency_ms": 95.0, "token_estimate": 3600},
    }

    gate = compare_golden_performance(current, baseline=baseline)

    assert gate["status"] == "pass"
    assert gate["passed"] is True
    assert gate["token"]["comparison_scope"] == "per_case"
    assert gate["token"]["baseline_token_estimate"] == 1000
    assert gate["token"]["current_token_estimate"] == 900


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


def test_golden_performance_gate_rejects_agent_guidance_regression() -> None:
    current = {
        "summary": {
            "case_count": 2,
            "anchor_recall": 1.0,
            "edge_recall": 1.0,
            "agent_next_step_count": 1,
            "agent_next_step_action_counts": {"refine_query": 1},
            "agent_invalid_search_suggestion_count": 1,
            "agent_invalid_search_reduction_rate": 0.0,
        },
        "performance": {"median_latency_ms": 90.0, "token_estimate": 900},
    }
    baseline = {
        "schema_version": 1,
        "label": "v3.5-agent-guidance",
        "summary": {
            "case_count": 2,
            "agent_next_step_count": 2,
            "agent_next_step_action_counts": {"use_read_targets": 2},
            "agent_invalid_search_suggestion_count": 0,
            "agent_invalid_search_reduction_rate": 1.0,
        },
        "performance": {"median_latency_ms": 100.0, "token_estimate": 1000},
    }

    gate = compare_golden_performance(current, baseline=baseline)

    assert gate["status"] == "fail"
    assert gate["passed"] is False
    assert gate["latency"]["passed"] is True
    assert gate["token"]["passed"] is True
    assert gate["agent_guidance"]["passed"] is False
    assert gate["agent_guidance"]["step_coverage_passed"] is False
    assert gate["agent_guidance"]["invalid_search_passed"] is False
    assert gate["agent_guidance"]["reduction_rate_passed"] is False


def test_golden_performance_baseline_is_portable() -> None:
    result = {
        "summary": {
            "case_count": 1,
            "anchor_recall": 1.0,
            "edge_recall": 1.0,
            "agent_next_step_count": 2,
            "agent_next_step_action_counts": {"use_read_targets": 2},
            "agent_invalid_search_suggestion_count": 0,
            "agent_invalid_search_reduction_rate": 1.0,
        },
        "performance": {"median_latency_ms": 80.0, "p95_latency_ms": 90.0, "token_estimate": 700},
        "cases": [{"payload": {"absolute_file_path": "/private/path/Demo.java"}}],
    }

    baseline = build_golden_performance_baseline(result, label="current")

    assert set(baseline) == {"schema_version", "label", "created_at", "summary", "performance"}
    assert "cases" not in baseline
    assert "path" not in json.dumps(baseline, ensure_ascii=False).lower()
    assert baseline["summary"]["agent_next_step_count"] == 2
    assert baseline["summary"]["agent_next_step_action_counts"] == {"use_read_targets": 2}


def test_save_golden_performance_baseline_writes_portable_snapshot(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "golden-baseline.json"
    saved = save_golden_performance_baseline(
        {"summary": {"case_count": 1, "anchor_recall": 1.0}, "performance": {"median_latency_ms": 12.0, "token_estimate": 50}},
        output,
        label="test",
    )

    assert saved["saved"] is True
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["label"] == "test"


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


def test_extract_logical_evidence_includes_mq_topics_and_config_keys() -> None:
    evidence = extract_logical_evidence({"contracts": [{"topic": "orders.created"}, {"values": {"spring.application.name": "demo"}}]})

    assert "MQTopic#orders.created" in evidence["anchors"]
    assert "ConfigKey#spring.application.name" in evidence["anchors"]


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_eval_golden_cli_command_dispatches_suite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


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


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_eval_golden_http_route_dispatches_suite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


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
