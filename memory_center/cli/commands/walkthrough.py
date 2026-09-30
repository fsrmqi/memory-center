"""Walkthrough 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

import typer

from memory_center.cli.output import print_data as print
from memory_center.core.foundation.dispatch import CommandRegistry
from memory_center.core.orchestrator import (
    memory_eval_walkthrough_quality,
    memory_export_walkthrough_artifact,
    memory_method_walkthrough,
    memory_walkthrough_health,
)


def _dispatch_walkthrough_cli(action: str, **kwargs):
    registry = CommandRegistry(label="walkthrough CLI command").register_many(
        {
            "method_walkthrough": lambda: memory_method_walkthrough(
                kwargs["workspace"],
                kwargs["symbol"],
                depth=kwargs.get("depth", 4),
                limit=kwargs.get("limit", 80),
                project=kwargs.get("project", ""),
                view=kwargs.get("view", "full"),
                budget=kwargs.get("budget", "medium"),
                report_level=kwargs.get("report_level", "standard"),
            ),
            "walkthrough_health": lambda: memory_walkthrough_health(
                kwargs["workspace"],
                symbol=kwargs.get("symbol", ""),
                project=kwargs.get("project", ""),
                report_level=kwargs.get("report_level", "standard"),
            ),
            "walkthrough_export": lambda: memory_export_walkthrough_artifact(
                kwargs["workspace"],
                symbol=kwargs["symbol"],
                project=kwargs.get("project", ""),
                report_level=kwargs.get("report_level", "deep"),
                title=kwargs.get("title", ""),
            ),
            "eval_walkthrough_quality": lambda: memory_eval_walkthrough_quality(
                kwargs["workspace"],
                symbol=kwargs["symbol"],
                project=kwargs.get("project", ""),
                report_level=kwargs.get("report_level", "standard"),
            ),
        }
    )
    return registry.dispatch(action)


def register_walkthrough_commands(app: typer.Typer) -> None:
    @app.command("method-walkthrough")
    def method_walkthrough_cmd(
        workspace: str = typer.Option(...),
        symbol: str = typer.Option(..., help="Method symbol, e.g. com.example.ArticleService#listByDto"),
        depth: int = typer.Option(4),
        limit: int = typer.Option(80),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
        report_level: str = typer.Option("standard", help="summary|standard|deep|risk-focused"),
    ):
        """Explain indexed method steps, downstream calls, and Feign continuations."""
        print(
            _dispatch_walkthrough_cli(
                "method_walkthrough",
                workspace=workspace,
                symbol=symbol,
                depth=depth,
                limit=limit,
                project=project,
                view=view,
                budget=budget,
                report_level=report_level,
            )
        )

    @app.command("walkthrough-health")
    def walkthrough_health_cmd(
        workspace: str = typer.Option(...),
        symbol: str = typer.Option("", help="Optional Method symbol for sample walkthrough validation."),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        report_level: str = typer.Option("standard", help="summary|standard|deep|risk-focused"),
    ):
        """Check method walkthrough readiness and output contract."""
        print(
            _dispatch_walkthrough_cli(
                "walkthrough_health",
                workspace=workspace,
                symbol=symbol,
                project=project,
                report_level=report_level,
            )
        )

    @app.command("walkthrough-export")
    def walkthrough_export_cmd(
        workspace: str = typer.Option(...),
        symbol: str = typer.Option(..., help="Method symbol, e.g. com.example.ArticleService#listByDto"),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        report_level: str = typer.Option("deep", help="summary|standard|deep|risk-focused"),
        title: str = typer.Option("", help="Optional artifact title."),
    ):
        """Export a method walkthrough Markdown artifact under artifacts/walkthroughs."""
        print(
            _dispatch_walkthrough_cli(
                "walkthrough_export",
                workspace=workspace,
                symbol=symbol,
                project=project,
                report_level=report_level,
                title=title,
            )
        )

    @app.command("walkthrough-eval")
    def walkthrough_eval_cmd(
        workspace: str = typer.Option(...),
        symbol: str = typer.Option(..., help="Method symbol, e.g. com.example.ArticleService#listByDto"),
        project: str = typer.Option("", help="Filter by project name for disambiguation."),
        report_level: str = typer.Option("standard", help="summary|standard|deep|risk-focused"),
    ):
        """Evaluate whether a method walkthrough result is agent-ready."""
        print(
            _dispatch_walkthrough_cli(
                "eval_walkthrough_quality",
                workspace=workspace,
                symbol=symbol,
                project=project,
                report_level=report_level,
            )
        )

