"""Eval 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import json
from typing import List

import typer
from rich import print

from memory_center.core.orchestrator import (
    memory_eval_agent_guidance,
    memory_eval_agent_guidance_adoption,
    memory_eval_agent_guidance_adoption_trend,
    memory_eval_agent_guidance_replay,
    memory_eval_agent_guidance_replay_trend,
    memory_eval_agent_guidance_trend,
    memory_eval_context_weight,
    memory_eval_handoff,
    memory_eval_index_freshness,
    memory_eval_regression_suite,
    memory_eval_resume,
    memory_eval_token_gain,
    memory_eval_tool_adoption,
    memory_eval_workflow_orchestration,
    memory_eval_write_quality,
)


def register_eval_commands(app: typer.Typer) -> None:
    @app.command("eval-session-recall")
    def eval_session_recall_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        cases: str = typer.Option(..., help="Local private session-recall cases YAML."),
        limit: int = typer.Option(5, min=1, max=20, help="Maximum related cases returned per replay."),
    ):
        """Replay private cases through resume and classify L1 recall misses without changing retrieval."""
        from memory_center.core.benchmark.session_recall import evaluate_session_recall

        print(evaluate_session_recall(workspace, cases, limit=limit))

    @app.command("eval-reasoning-prompts")
    def eval_reasoning_prompts_cmd(
        cases: str = typer.Option("", help="Optional local reasoning prompt cases YAML."),
        observations: str = typer.Option("", help="Optional local redacted manual observations YAML."),
    ):
        """Evaluate static reasoning-prompt contracts and separate real behavior evidence."""
        from memory_center.core.benchmark.reasoning_prompts import evaluate_reasoning_prompts

        typer.echo(
            json.dumps(
                evaluate_reasoning_prompts(cases or None, observations or None),
                ensure_ascii=False,
                indent=2,
            )
        )

    @app.command("eval-cochange")
    def eval_cochange_cmd(
        workspace: str = typer.Option(...),
        max_commits: int = typer.Option(20, min=1, max=100),
        warmup_commits: int = typer.Option(5, min=1, max=50),
        apply: bool = typer.Option(False, help="Apply hashed priors only when the walk-forward gate passes."),
    ):
        """Evaluate and optionally apply leakage-free Git co-change priors."""
        from memory_center.core.benchmark.cochange import evaluate_git_cochange

        print(evaluate_git_cochange(workspace, max_commits=max_commits, warmup_commits=warmup_commits, apply=apply))

    @app.command("eval-write-quality")
    def eval_write_quality_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(100),
    ):
        """Evaluate write quality from persisted receipts."""
        print(memory_eval_write_quality(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit))

    @app.command("eval-resume")
    def eval_resume_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(20),
    ):
        """Evaluate resume packet quality."""
        print(memory_eval_resume(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit))

    @app.command("eval-handoff")
    def eval_handoff_cmd(
        workspace: str = typer.Option(...),
        target_model: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(20),
    ):
        """Evaluate handoff packet quality."""
        print(
            memory_eval_handoff(
                workspace, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit
            )
        )

    @app.command("eval-regression-suite")
    def eval_regression_suite_cmd(
        workspace: str = typer.Option(...),
        target_model: str = typer.Option("codex"),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(20),
    ):
        """Run the aggregated write/resume/handoff regression suite."""
        print(
            memory_eval_regression_suite(
                workspace,
                target_model=target_model,
                task_id=task_id,
                session_id=session_id,
                intent=intent,
                limit=limit,
            )
        )

    @app.command("eval-index-freshness")
    def eval_index_freshness_cmd(
        workspace: str = typer.Option(...),
        scope: str = typer.Option("all"),
    ):
        """Evaluate whether indexes look stale relative to current git changes."""
        print(memory_eval_index_freshness(workspace, scope=scope))

    @app.command("eval-tool-adoption")
    def eval_tool_adoption_cmd(
        workspace: str = typer.Option(...),
        limit: int = typer.Option(200),
    ):
        """Evaluate recent Memory Center tool adoption quality."""
        print(memory_eval_tool_adoption(workspace, limit=limit))

    @app.command("eval-context-weight")
    def eval_context_weight_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(""),
        limit: int = typer.Option(8),
    ):
        """Evaluate whether compact budgeted payloads are still too heavy."""
        print(memory_eval_context_weight(workspace, intent=intent, limit=limit))

    @app.command("eval-agent-guidance")
    def eval_agent_guidance_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(""),
        limit: int = typer.Option(20),
    ):
        """Evaluate whether lookup output gives bounded agent next steps."""
        print(memory_eval_agent_guidance(workspace, intent=intent, limit=limit))

    @app.command("eval-agent-guidance-trend")
    def eval_agent_guidance_trend_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(""),
        limit: int = typer.Option(20),
    ):
        """Evaluate agent next-step guidance and record one trend point."""
        print(memory_eval_agent_guidance_trend(workspace, intent=intent, limit=limit))

    @app.command("eval-agent-guidance-adoption")
    def eval_agent_guidance_adoption_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(200),
    ):
        """Evaluate whether recorded agent guidance was followed by later tool calls."""
        print(memory_eval_agent_guidance_adoption(workspace, session_id=session_id, limit=limit))

    @app.command("eval-agent-guidance-adoption-trend")
    def eval_agent_guidance_adoption_trend_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(200),
    ):
        """Evaluate agent guidance adoption and record one trend point."""
        print(memory_eval_agent_guidance_adoption_trend(workspace, session_id=session_id, limit=limit))

    @app.command("eval-agent-guidance-replay")
    def eval_agent_guidance_replay_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(200),
    ):
        """Replay agent guidance events and classify missed, bypassed, and unobservable recommendations."""
        print(memory_eval_agent_guidance_replay(workspace, session_id=session_id, limit=limit))

    @app.command("eval-agent-guidance-replay-campaign")
    def eval_agent_guidance_replay_campaign_cmd(
        workspace: str = typer.Option(...),
        min_events: int = typer.Option(20, min=1),
        limit: int = typer.Option(500, min=1),
    ):
        """Check whether real replay coverage is sufficient for retrieval-policy review."""
        from memory_center.core.orchestrator import memory_eval_agent_guidance_replay_campaign

        typer.echo(
            json.dumps(
                memory_eval_agent_guidance_replay_campaign(workspace, min_events=min_events, limit=limit),
                ensure_ascii=False,
                indent=2,
            )
        )

    @app.command("eval-agent-guidance-replay-trend")
    def eval_agent_guidance_replay_trend_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(200),
    ):
        """Replay agent guidance events and record one trend point."""
        print(memory_eval_agent_guidance_replay_trend(workspace, session_id=session_id, limit=limit))

    @app.command("eval-retrieval-replay")
    def eval_retrieval_replay_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        lookback_days: int = typer.Option(30, min=1, max=365),
        min_samples: int = typer.Option(20, min=1, max=100_000),
        apply: bool = typer.Option(False, help="Persist eligible calibrated weights after reporting the proposal."),
    ):
        """Calibrate retrieval fusion weights from human-verified replay evidence only."""
        from memory_center.core.retrieval.calibration import evaluate_retrieval_replay_calibration

        result = evaluate_retrieval_replay_calibration(
            workspace,
            lookback_days=lookback_days,
            min_samples=min_samples,
            apply=apply,
        )
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))

    @app.command("eval-workflow-orchestration")
    def eval_workflow_orchestration_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option("", help="Evaluate workflow for a specific task."),
        session_id: str = typer.Option("", help="Evaluate workflow for a specific session."),
        intent: str = typer.Option("", help="Intent for evaluation context."),
        limit: int = typer.Option(20),
    ):
        """Evaluate whether a workflow follows the recommended start→log→sync→close pattern."""
        print(
            memory_eval_workflow_orchestration(
                workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit
            )
        )

    @app.command("eval-token-gain")
    def eval_token_gain_cmd(
        workspace: str = typer.Option(...),
        tool_name: str = typer.Option("", help="Filter by tool name."),
        budget: str = typer.Option("", help="Filter by budget."),
        model: str = typer.Option("", help="Filter by model."),
        limit: int = typer.Option(200),
    ):
        """Evaluate token savings from compact operations (similar to rtk gain)."""
        print(memory_eval_token_gain(workspace, tool_name=tool_name, budget=budget, model=model, limit=limit))

    @app.command("eval-token-benchmark")
    def eval_token_benchmark_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option("token benchmark"),
        limit: int = typer.Option(8),
    ):
        """Run token benchmark: measure all 7 high-freq returns at small/medium/large budgets."""
        from memory_center.core.orchestrator import memory_eval_token_benchmark

        print(memory_eval_token_benchmark(workspace, intent=intent, limit=limit))

    @app.command("eval-parser-benchmark")
    def eval_parser_benchmark_cmd(
        workspace: str = typer.Option(...),
        limit: int = typer.Option(200, help="Maximum number of Java files to compare."),
        max_findings: int = typer.Option(20, help="Maximum number of regression/improvement findings to return."),
    ):
        """Compare regex and tree-sitter parser outputs on a real workspace."""
        from memory_center.core.orchestrator import memory_eval_parser_benchmark

        print(
            json.dumps(
                memory_eval_parser_benchmark(workspace, limit=limit, max_findings=max_findings),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    @app.command("eval-ontology-gate")
    def eval_ontology_gate_cmd(
        workspace: str = typer.Option(...),
        samples: int = typer.Option(20, help="Number of bounded assertion-summary reads."),
        budget_ms: float = typer.Option(10.0, help="P95 hot-path budget in milliseconds."),
    ):
        """Validate the ontology sidecar's default-query hot-path budget."""
        from memory_center.core.knowledge.benchmark import evaluate_ontology_hot_path

        print(
            json.dumps(
                evaluate_ontology_hot_path(workspace, samples=samples, budget_ms=budget_ms), ensure_ascii=False, indent=2
            )
        )

    @app.command("eval-assertion-scope-gate")
    def eval_assertion_scope_gate_cmd(
        workspace: str = typer.Option(...),
        path: List[str] = typer.Option(..., help="Logical indexed path; repeat for multiple paths."),  # noqa: B008
        apply: bool = typer.Option(False, help="Publish one real partial reindex generation."),
        max_scope_edges: int = typer.Option(200_000, help="Maximum permitted selected assertion edges."),
    ):
        """Check that a partial reindex only materializes its scoped assertions."""
        from memory_center.core.knowledge.benchmark import evaluate_assertion_scope_gate

        print(
            json.dumps(
                evaluate_assertion_scope_gate(workspace, paths=path, apply=apply, max_scope_edges=max_scope_edges),
                ensure_ascii=False,
                indent=2,
            )
        )

    @app.command("eval-assertion-reindex-gate")
    def eval_assertion_reindex_gate_cmd(
        workspace: str = typer.Option(...),
        path: List[str] = typer.Option([], help="Logical indexed path; required unless --full."),  # noqa: B008
        full: bool = typer.Option(False, help="Measure a full reindex in temporary stores."),
    ):
        """Measure graph-only versus assertion-sidecar indexing in isolated storage."""
        from memory_center.core.knowledge.benchmark import evaluate_assertion_reindex_gate

        print(json.dumps(evaluate_assertion_reindex_gate(workspace, paths=path, full=full), ensure_ascii=False, indent=2))

    @app.command("eval-golden")
    def eval_golden_cmd(
        workspace: str = typer.Option(..., help="Workspace yaml file."),
        cases: str = typer.Option(..., help="Golden cases yaml file."),
        baseline: str = typer.Option("", help="Optional Golden performance baseline JSON file."),
    ):
        """Run Golden Benchmark against a workspace and a portable cases file."""
        from memory_center.application.golden import run_golden_suite

        print(
            json.dumps(
                run_golden_suite(workspace, cases, performance_baseline=baseline or None),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

    @app.command("eval-golden-baseline-save")
    def eval_golden_baseline_save_cmd(
        workspace: str = typer.Option(..., help="Workspace yaml file."),
        cases: str = typer.Option(..., help="Golden cases yaml file."),
        output: str = typer.Option(..., help="Portable baseline JSON output path."),
        label: str = typer.Option("current", help="Baseline label."),
    ):
        """Run Golden Benchmark and save a portable performance baseline."""
        from memory_center.application.golden import run_golden_suite
        from memory_center.core import benchmark as benchmark_module

        result = run_golden_suite(workspace, cases)
        saved = benchmark_module.save_golden_performance_baseline(result, output, label=label)
        print(json.dumps({"result": result, **saved}, ensure_ascii=False, indent=2, default=str))

    @app.command("eval-java-call-resolution")
    def eval_java_call_resolution_cmd(
        workspace: str = typer.Option(..., help="Workspace yaml file."),
        cases: str = typer.Option(..., help="Java call resolution cases yaml file."),
        min_recall: float = typer.Option(0.90, help="Minimum expected-edge recall."),
        min_confidence_rate: float = typer.Option(0.85, help="Minimum high-confidence expected-edge rate."),
        min_resolution_level_rate: float = typer.Option(1.0, help="Minimum expected resolution-level match rate."),
        max_unresolved_rate: float = typer.Option(0.10, help="Maximum unresolved case rate."),
        fail_on_unexpected_high_confidence: bool = typer.Option(
            False, help="Fail on non-expected high-confidence CALLS_METHOD edges."
        ),
        fail_on_forbidden_high_confidence: bool = typer.Option(
            False, help="Fail on high-confidence CALLS_METHOD edges listed in forbidden_targets."
        ),
    ):
        """Run Java CALLS_METHOD resolution gate against logical real-workspace cases."""
        from memory_center.core.orchestrator import memory_eval_java_call_resolution

        result = memory_eval_java_call_resolution(
            workspace,
            cases,
            min_recall=min_recall,
            min_confidence_rate=min_confidence_rate,
            min_resolution_level_rate=min_resolution_level_rate,
            max_unresolved_rate=max_unresolved_rate,
            fail_on_unexpected_high_confidence=fail_on_unexpected_high_confidence,
            fail_on_forbidden_high_confidence=fail_on_forbidden_high_confidence,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    @app.command("eval-java-call-resolution-metrics")
    def eval_java_call_resolution_metrics_cmd(
        workspace: str = typer.Option(..., help="Workspace yaml file."),
    ):
        """Report aggregate Java call-resolution metrics without source details."""
        from memory_center.core.orchestrator import memory_eval_java_call_resolution_metrics

        result = memory_eval_java_call_resolution_metrics(workspace)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    @app.command("eval-java-call-resolution-review")
    def eval_java_call_resolution_review_cmd(
        workspace: str = typer.Option(..., help="Workspace yaml file."),
        cases: str = typer.Option(..., help="Java call resolution cases yaml file."),
        limit: int = typer.Option(200, help="Maximum unclassified high-confidence edges to return."),
    ):
        """Review unclassified Java CALLS_METHOD edges without exposing file paths."""
        from memory_center.core.orchestrator import memory_eval_java_call_resolution_review

        result = memory_eval_java_call_resolution_review(workspace, cases, limit=limit)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    @app.command("eval-java-call-resolution-unresolved")
    def eval_java_call_resolution_unresolved_cmd(
        workspace: str = typer.Option(..., help="Workspace yaml file."),
        limit: int = typer.Option(30, min=0, help="Maximum logical-anchor samples to return."),
    ):
        """Classify unresolved Java CALLS_METHOD edges without source paths."""
        from memory_center.core.orchestrator import memory_eval_java_call_resolution_unresolved

        result = memory_eval_java_call_resolution_unresolved(workspace, limit=limit)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    @app.command("eval-token-benchmark-save")
    def eval_token_benchmark_save_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option("token benchmark"),
        limit: int = typer.Option(8),
    ):
        """Save current token benchmark as regression baseline."""
        from memory_center.core.orchestrator import memory_eval_token_benchmark_save

        print(memory_eval_token_benchmark_save(workspace, intent=intent, limit=limit))

    @app.command("eval-token-benchmark-compare")
    def eval_token_benchmark_compare_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option("token benchmark"),
        limit: int = typer.Option(8),
        regression_threshold: int = typer.Option(15),
    ):
        """Compare token benchmark against stored baseline. Exit 1 on high-severity regression."""
        from memory_center.core.orchestrator import memory_eval_token_benchmark_compare

        result = memory_eval_token_benchmark_compare(
            workspace, intent=intent, limit=limit, regression_threshold=regression_threshold
        )
        print(result)
        regressions = result.get("regressions", [])
        if regressions:
            raise typer.Exit(code=1)

    @app.command("eval-token-benchmark-trend")
    def eval_token_benchmark_trend_cmd(
        workspace: str = typer.Option(...),
        function_name: str = typer.Option("", help="Filter by function name."),
    ):
        """Show benchmark trend data, regressions, and health score."""
        from memory_center.core.benchmark.trending import generate_benchmark_report

        print(generate_benchmark_report(workspace, function_name=function_name))
