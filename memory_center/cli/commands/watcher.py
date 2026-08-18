"""Watcher 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

import json

import typer

from memory_center.core.freshness.daemon import (
    run_watcher_daemon,
    start_watcher_daemon,
    stop_watcher_daemon,
    watcher_daemon_status,
)


def register_watcher_commands(app: typer.Typer) -> None:
    @app.command("watcher-start")
    def watcher_start(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        poll_interval: float = typer.Option(5.0, min=0.2, help="File scan interval in seconds."),
        debounce_seconds: float = typer.Option(2.0, min=0.0, help="Quiet period before one partial reindex."),
    ):
        """Start one persistent watcher that queues targeted reindex jobs."""
        typer.echo(
            json.dumps(
                start_watcher_daemon(workspace, poll_interval=poll_interval, debounce_seconds=debounce_seconds),
                ensure_ascii=False,
                indent=2,
            )
        )

    @app.command("watcher-status")
    def watcher_status(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    ):
        """Show persistent watcher state and its latest targeted reindex job."""
        typer.echo(json.dumps(watcher_daemon_status(workspace), ensure_ascii=False, indent=2))

    @app.command("watcher-stop")
    def watcher_stop(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    ):
        """Stop the persistent watcher for this workspace."""
        typer.echo(json.dumps(stop_watcher_daemon(workspace), ensure_ascii=False, indent=2))

    @app.command("watcher-run", hidden=True)
    def watcher_run(
        workspace: str = typer.Option(...),
        poll_interval: float = typer.Option(5.0, min=0.2),
        debounce_seconds: float = typer.Option(2.0, min=0.0),
    ):
        """Internal detached watcher process entrypoint."""
        run_watcher_daemon(workspace, poll_interval=poll_interval, debounce_seconds=debounce_seconds)

