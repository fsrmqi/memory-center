"""Audit 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from memory_center.application.presentation import export_workspace_dashboard_markdown
from memory_center.cli.output import print_data as print


def register_audit_commands(app: typer.Typer) -> None:
    @app.command("agent-execution-import")
    def agent_execution_import_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        inbox: str = typer.Option("", help="Optional local DSH inbox directory."),
        max_files: int = typer.Option(50, min=1, max=500),
        max_events: int = typer.Option(20_000, min=1, max=100_000),
    ):
        """Import sanitized local DSH execution events with idempotent event IDs."""
        from memory_center.core.observability.agent_execution import import_agent_execution_inbox

        print(import_agent_execution_inbox(workspace, inbox_dir=inbox, max_files=max_files, max_events=max_events))

    @app.command("agent-execution-summary")
    def agent_execution_summary_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        limit_events: int = typer.Option(20_000, min=1, max=100_000),
        limit_sessions: int = typer.Option(20, min=1, max=200),
    ):
        """Summarize local DSH turn, model, tool, token, and failure metadata."""
        from memory_center.core.observability.agent_execution import summarize_agent_execution

        print(summarize_agent_execution(workspace, limit_events=limit_events, limit_sessions=limit_sessions))

    @app.command("audit")
    def audit_cmd(
        workspace: str = typer.Option(...),
        work_package: str = typer.Option("", help="Work package to audit."),
    ):
        """Run completion audit for documentation, tests, and implementation."""
        from memory_center.core.audit.reports import run_completion_audit

        print(run_completion_audit(workspace, work_package=work_package))

    @app.command("drill-ref")
    def drill_ref_cmd(
        workspace: str = typer.Option(...),
        ref_id: str = typer.Option(..., help="Ref ID to expand (e.g. ev:session:type:0)."),
    ):
        """Expand a ref with progressive disclosure."""
        from memory_center.core.navigation.drilldown import DrillDownNavigator

        with DrillDownNavigator(workspace) as nav:
            print(nav.expand_ref(ref_id))

    @app.command("drill-timeline")
    def drill_timeline_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option("", help="Filter by session ID."),
        task_id: str = typer.Option("", help="Filter by task ID."),
        limit: int = typer.Option(50),
    ):
        """Drill into timeline with context preservation."""
        from memory_center.core.navigation.drilldown import DrillDownNavigator

        with DrillDownNavigator(workspace) as nav:
            print(nav.drill_timeline(session_id=session_id, task_id=task_id, limit=limit))

    @app.command("drill-task")
    def drill_task_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(..., help="Task ID to drill into."),
    ):
        """Drill into a task's full context."""
        from memory_center.core.navigation.drilldown import DrillDownNavigator

        with DrillDownNavigator(workspace) as nav:
            print(nav.drill_task(task_id))

    @app.command("backend-consistency")
    def backend_consistency_cmd(
        workspace: str = typer.Option(...),
        repair_exports: bool = typer.Option(False, help="Inspect recoverable JSONL exports."),
        apply: bool = typer.Option(False, help="Repair dirty or stale JSONL exports; requires --repair-exports."),
    ):
        """Check consistency between JSONL files and SQLite backend."""
        if apply and not repair_exports:
            raise typer.BadParameter("--apply requires --repair-exports")
        from memory_center.application.admin import backend_consistency

        print(backend_consistency(workspace, repair_exports=repair_exports, apply=apply))

    @app.command("export-workspace-dashboard")
    def export_workspace_dashboard_cmd(
        workspace: str = typer.Option(...),
        output: str = typer.Option(...),
        format: str = typer.Option("markdown", help="markdown"),
        intent: str = typer.Option(""),
        limit: int = typer.Option(10),
    ):
        """Export one workspace dashboard to Markdown (HTML export removed; UI lives in the DSH plugin)."""
        fmt = format.strip().lower()
        if fmt not in {"md", "markdown"}:
            raise typer.BadParameter("format must be markdown (HTML export removed; use the DSH plugin UI)")
        content = export_workspace_dashboard_markdown(workspace, intent=intent, limit=limit)
        Path(output).write_text(content, encoding="utf-8")
        print({"exported": True, "format": "markdown", "output": output})

    @app.command("runtime-audit")
    def runtime_audit_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        fix: bool = typer.Option(False, help="Write or refresh missing agent MCP bindings before auditing."),
    ):
        """Audit agent runtime configuration (hooks, MCP, agent profile)."""
        from memory_center.core.audit.runtime import audit_agent_runtime

        result = audit_agent_runtime(workspace, fix=fix)
        typer.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))

    @app.command("metrics-summary")
    def metrics_summary_cmd():
        """Show metrics summary."""
        from memory_center.core.observability.metrics import MetricsCollector

        mc = MetricsCollector()
        print(json.dumps(mc.summary(), indent=2, default=str))

    @app.command("regression-alerts")
    def regression_alerts_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        threshold_pct: float = typer.Option(10.0, help="Token regression warning threshold percentage"),
    ):
        """Check for benchmark regression alerts."""
        from memory_center.core.benchmark.trending import check_regression_alerts

        result = check_regression_alerts(workspace, threshold_pct=threshold_pct)
        print(json.dumps(result, indent=2, default=str))
