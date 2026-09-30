"""Change 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import json
from typing import List, Optional

import typer

from memory_center.cli.output import print_data as print
from memory_center.core.freshness.change_reports import recent_change_impact_reports, record_change_impact_feedback

from ._options import OPTIONAL_VERIFIED_BY


def register_change_commands(app: typer.Typer) -> None:
    @app.command("change-impact-reports")
    def change_impact_reports(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        limit: int = typer.Option(20, min=1, max=100, help="Maximum recent reports to return."),
        pending_only: bool = typer.Option(False, help="Only show reports without a final human decision."),
    ):
        """Show lightweight watcher change impact reports after partial reindex jobs finish."""
        typer.echo(
            json.dumps(
                recent_change_impact_reports(workspace, limit=limit, pending_only=pending_only),
                ensure_ascii=False,
                indent=2,
            )
        )

    @app.command("change-impact-confirm")
    def change_impact_confirm(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        report_id: str = typer.Option(..., help="Change impact report id."),
        decision: str = typer.Option(..., help="confirmed|false_positive|deep_analysis_required|resolved"),
        task_id: str = typer.Option("", help="Optional related task id."),
        session_id: str = typer.Option("", help="Optional related session id."),
        validation_status: str = typer.Option("not_run", help="passed|failed|skipped|not_run|recorded"),
        validation_summary: str = typer.Option("", help="Structured validation conclusion only; no raw output."),
        verified_by: Optional[List[str]] = OPTIONAL_VERIFIED_BY,
        note: str = typer.Option("", help="Short structured conclusion; no source or conversation body."),
    ):
        """Record a human decision for one watcher change impact report."""
        typer.echo(
            json.dumps(
                record_change_impact_feedback(
                    workspace,
                    report_id,
                    decision=decision,
                    task_id=task_id,
                    session_id=session_id,
                    validation_status=validation_status,
                    validation_summary=validation_summary,
                    verified_by=verified_by,
                    note=note,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )

    @app.command("change-review")
    def change_review_cmd(
        workspace: str = typer.Option(...),
        scope: str = typer.Option("all", help="Git change scope: staged, head, or all."),
        file: List[str] = typer.Option([], "--file", help="Explicit logical changed path; repeatable."),  # noqa: B008
        detail_level: str = typer.Option("minimal", help="minimal, standard, or deep."),
        no_refresh: bool = typer.Option(False, help="Read the published generation without scoped refresh."),
        max_depth: int = typer.Option(3, min=1, max=5),
    ):
        """Build one bounded graph-aware change review plan."""
        from memory_center.core.orchestrator.templates import plan_change_risk

        print(
            plan_change_risk(
                workspace,
                scope=scope,
                files=list(file) or None,
                detail_level=detail_level,
                refresh=not no_refresh,
                max_depth=max_depth,
            )
        )
