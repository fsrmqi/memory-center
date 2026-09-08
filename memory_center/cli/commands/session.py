"""Session 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
from typing import List, Optional

import typer
from rich import print

from memory_center.core.orchestrator import (
    archive_session_events,
    plan_session_archive,
    workspace_end_session,
    workspace_capture_dsh_delivery_summary,
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
    @app.command("dsh-delivery-capture")
    def dsh_delivery_capture_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        source_session_id: str = typer.Option(..., help="DSH source session ID."),
        summary: str = typer.Option(..., help="Bounded DSH assistant completion summary."),
        turn: Optional[int] = typer.Option(None),
        step: Optional[int] = typer.Option(None),
        task_id: str = typer.Option("", help="Bound L2 task ID anchor (required for delivery capture)."),
    ):
        """Persist one completion-signalled DSH delivery summary, never a full transcript."""
        print(workspace_capture_dsh_delivery_summary(workspace, source_session_id, summary, turn=turn, step=step, task_id=task_id))

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

    @app.command("session-archive-plan")
    def session_archive_plan_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option("", help="Plan one session; empty plans all events."),
        keep_recent_turns: int = typer.Option(None, help="Turns always kept live (default 3)."),
        max_archive_tokens: int = typer.Option(None, help="Token budget for one archive run (default 20000)."),
    ):
        """Plan rolling session-event archive (dry-run): turn layout and archive/live boundary."""
        kwargs = {}
        if keep_recent_turns is not None:
            kwargs["keep_recent_turns"] = keep_recent_turns
        if max_archive_tokens is not None:
            kwargs["max_archive_tokens"] = max_archive_tokens
        print(plan_session_archive(workspace, session_id, **kwargs))

    @app.command("session-archive")
    def session_archive_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option("", help="Archive one session; empty archives all events."),
        keep_recent_turns: int = typer.Option(None, help="Turns always kept live (default 3)."),
        max_archive_tokens: int = typer.Option(None, help="Token budget for one archive run (default 20000)."),
    ):
        """Archive old session events beyond the planned boundary into session-events-archive.jsonl."""
        kwargs = {}
        if keep_recent_turns is not None:
            kwargs["keep_recent_turns"] = keep_recent_turns
        if max_archive_tokens is not None:
            kwargs["max_archive_tokens"] = max_archive_tokens
        print(archive_session_events(workspace, session_id, **kwargs))
