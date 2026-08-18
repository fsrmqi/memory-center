"""Audit 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print

from memory_center.application.presentation import export_workspace_dashboard_html, export_workspace_dashboard_markdown


def register_audit_commands(app: typer.Typer) -> None:
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
    ):
        """Check consistency between JSONL files and SQLite backend."""
        from memory_center.core.backend.query import UnifiedBackendQuery
        from memory_center.core.storage.workspace import WorkspaceStore

        store = WorkspaceStore(workspace)
        with UnifiedBackendQuery(store.runtime_db_path) as backend:
            print(backend.check_consistency(store.base_dir))

    @app.command("export-workspace-dashboard")
    def export_workspace_dashboard_cmd(
        workspace: str = typer.Option(...),
        output: str = typer.Option(...),
        format: str = typer.Option("html", help="html|markdown"),
        intent: str = typer.Option(""),
        limit: int = typer.Option(10),
    ):
        """Export one workspace dashboard to HTML or Markdown."""
        fmt = format.strip().lower()
        if fmt == "html":
            content = export_workspace_dashboard_html(workspace, intent=intent, limit=limit)
        elif fmt in {"md", "markdown"}:
            content = export_workspace_dashboard_markdown(workspace, intent=intent, limit=limit)
        else:
            raise typer.BadParameter("format must be html or markdown")
        Path(output).write_text(content, encoding="utf-8")
        print({"exported": True, "format": fmt, "output": output})

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

