"""Session 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
from typing import List, Optional

import typer
from rich import print

from memory_center.core.orchestrator import (
    workspace_end_session,
    workspace_log_session_event,
    workspace_recent_sessions,
    workspace_session_summary,
    workspace_start_session,
)

from ._options import OPTIONAL_VERIFIED_BY


def _parse_event_payload(payload: str):
    try:
        import json

        value = json.loads(payload)
        return value if isinstance(value, dict) else {"value": value}
    except Exception:
        return {"text": payload}


def register_session_commands(app: typer.Typer) -> None:
    @app.command("start-session")
    def start_session_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(...),
        session_id: Optional[str] = typer.Option(None),
    ):
        """Start a lightweight session-memory record for the current task."""
        print(workspace_start_session(workspace, intent, session_id=session_id))

    @app.command("log-session-event")
    def log_session_event_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(...),
        event_type: str = typer.Option(...),
        payload: str = typer.Option("{}", help="JSON payload or plain text."),
    ):
        """Append one session event into session memory."""
        parsed_payload = _parse_event_payload(payload)
        print(workspace_log_session_event(workspace, session_id, event_type, parsed_payload))

    @app.command("end-session")
    def end_session_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(...),
        outcome: str = typer.Option(""),
        verified_by: Optional[List[str]] = OPTIONAL_VERIFIED_BY,
        validation_command: str = typer.Option("", help="Completed validation command; recorded only, never executed."),
        validation_exit_code: Optional[int] = typer.Option(None, help="Exit code from the completed validation command."),
        validation_summary: str = typer.Option("", help="Bounded validation result summary."),
        validation_status: str = typer.Option("", help="passed|failed|skipped|not_run|recorded"),
    ):
        """Finalize one session and generate a summary record."""
        print(
            workspace_end_session(
                workspace,
                session_id,
                outcome=outcome,
                verified_by=verified_by,
                validation_command=validation_command,
                validation_exit_code=validation_exit_code,
                validation_summary=validation_summary,
                validation_status=validation_status,
            )
        )

    @app.command("recent-sessions")
    def recent_sessions_cmd(
        workspace: str = typer.Option(...),
        limit: int = typer.Option(10),
    ):
        """Show recent summarized sessions for this workspace."""
        print(workspace_recent_sessions(workspace, limit=limit))

    @app.command("session-summary")
    def session_summary_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(...),
    ):
        """Show one session summary with raw recorded events."""
        print(workspace_session_summary(workspace, session_id))

