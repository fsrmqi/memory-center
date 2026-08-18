"""Resume 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

import typer
from rich import print

from memory_center.core.orchestrator import (
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_handoff_history,
    workspace_handoff_packet,
    workspace_model_profile,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_resume_context,
    workspace_resume_packet,
    workspace_unresolved_items,
)


def register_resume_commands(app: typer.Typer) -> None:
    @app.command("resume-context")
    def resume_context_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(...),
        limit: int = typer.Option(5),
    ):
        """Retrieve related sessions, cases and entrypoints for a new session."""
        print(workspace_resume_context(workspace, intent, limit=limit))

    @app.command("recent-evidence")
    def recent_evidence_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(10),
        budget: str = typer.Option("medium", help="small|medium|large"),
        view: str = typer.Option("full", help="compact|full"),
    ):
        """Show recent evidence from task receipts and session events."""
        print(
            workspace_recent_evidence(
                workspace, task_id=task_id, session_id=session_id, limit=limit, budget=budget, view=view
            )
        )

    @app.command("unresolved-items")
    def unresolved_items_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(10),
    ):
        """List unresolved items for one task/session."""
        print(workspace_unresolved_items(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit))

    @app.command("next-actions")
    def next_actions_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(8),
    ):
        """Suggest next actions for one task/session."""
        print(workspace_next_actions(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit))

    @app.command("resume-packet")
    def resume_packet_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(10),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Build one resume packet for the next model/session."""
        print(
            workspace_resume_packet(
                workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view=view, budget=budget
            )
        )

    @app.command("model-profile")
    def model_profile_cmd(
        model: str = typer.Option(...),
    ):
        """Show one normalized model profile for handoff."""
        print(workspace_model_profile(model))

    @app.command("handoff-packet")
    def handoff_packet_cmd(
        workspace: str = typer.Option(...),
        target_model: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(10),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Build one handoff packet for the target model."""
        print(
            workspace_handoff_packet(
                workspace,
                target_model=target_model,
                task_id=task_id,
                session_id=session_id,
                intent=intent,
                limit=limit,
                view=view,
                budget=budget,
            )
        )

    @app.command("handoff-history")
    def handoff_history_cmd(
        workspace: str = typer.Option(...),
        target_model: str = typer.Option(""),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(50),
    ):
        """Query persisted handoff history."""
        print(
            workspace_handoff_history(
                workspace, target_model=target_model, task_id=task_id, session_id=session_id, limit=limit
            )
        )

    @app.command("continuity-dashboard")
    def continuity_dashboard_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(""),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(10),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Build one continuity dashboard for daily work."""
        print(
            workspace_continuity_dashboard(
                workspace, intent=intent, task_id=task_id, session_id=session_id, limit=limit, view=view, budget=budget
            )
        )

    @app.command("workspace-dashboard")
    def workspace_dashboard_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(""),
        limit: int = typer.Option(10),
        view: str = typer.Option("full", help="full|compact"),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Build one workspace-level dashboard for daily work."""
        print(workspace_dashboard(workspace, intent=intent, limit=limit, view=view, budget=budget))

