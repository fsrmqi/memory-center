"""Write 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
from typing import List, Optional

import typer
from rich import print

from memory_center.core.orchestrator import (
    memory_execute_write,
    memory_plan_write,
    memory_write_judge,
    workspace_record_case,
    workspace_replay_write_chain,
    workspace_suggest_case,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_write_receipts,
)

from ._options import (
    OPTIONAL_FILES,
    OPTIONAL_PROJECTS,
    OPTIONAL_RISK_POINTS,
    OPTIONAL_VERIFIED_BY,
    REQUIRED_FILES,
    REQUIRED_PROJECTS,
)


def register_write_commands(app: typer.Typer) -> None:
    @app.command("memory-write-judge")
    def memory_write_judge_cmd(
        workspace: str = typer.Option(...),
        text: str = typer.Option(...),
        source: str = typer.Option("note"),
        intent: str = typer.Option(""),
        prefer_layer: str = typer.Option(""),
        project: Optional[List[str]] = OPTIONAL_PROJECTS,
        file: Optional[List[str]] = OPTIONAL_FILES,
    ):
        """Judge which memory layer (L0/L1/L2/L3) the input should be written to."""
        print(
            memory_write_judge(
                workspace,
                text=text,
                source=source,
                intent=intent,
                prefer_layer=prefer_layer,
                projects=project,
                files=file,
            )
        )

    @app.command("memory-plan-write")
    def memory_plan_write_cmd(
        workspace: str = typer.Option(...),
        text: str = typer.Option(...),
        source: str = typer.Option("note"),
        intent: str = typer.Option(""),
        session_id: str = typer.Option(""),
        task_id: str = typer.Option(""),
        title: str = typer.Option(""),
        prefer_layer: str = typer.Option(""),
        project: Optional[List[str]] = OPTIONAL_PROJECTS,
        file: Optional[List[str]] = OPTIONAL_FILES,
    ):
        """Build an executable write plan after memory layer judgment."""
        print(
            memory_plan_write(
                workspace,
                text=text,
                source=source,
                intent=intent,
                session_id=session_id,
                task_id=task_id,
                title=title,
                prefer_layer=prefer_layer,
                projects=project,
                files=file,
            )
        )

    @app.command("memory-execute-write")
    def memory_execute_write_cmd(
        workspace: str = typer.Option(...),
        text: str = typer.Option(...),
        source: str = typer.Option("note"),
        intent: str = typer.Option(""),
        session_id: str = typer.Option(""),
        task_id: str = typer.Option(""),
        title: str = typer.Option(""),
        prefer_layer: str = typer.Option(""),
        project: Optional[List[str]] = OPTIONAL_PROJECTS,
        file: Optional[List[str]] = OPTIONAL_FILES,
    ):
        """Execute the ready steps from memory_plan_write."""
        print(
            memory_execute_write(
                workspace,
                text=text,
                source=source,
                intent=intent,
                session_id=session_id,
                task_id=task_id,
                title=title,
                prefer_layer=prefer_layer,
                projects=project,
                files=file,
            )
        )

    @app.command("write-receipts")
    def write_receipts_cmd(
        workspace: str = typer.Option(...),
        layer: str = typer.Option(""),
        action: str = typer.Option(""),
        scope: str = typer.Option(""),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(50),
    ):
        """Query persisted write receipts."""
        print(
            workspace_write_receipts(
                workspace,
                layer=layer,
                action=action,
                scope=scope,
                task_id=task_id,
                session_id=session_id,
                limit=limit,
            )
        )

    @app.command("replay-write-chain")
    def replay_write_chain_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        limit: int = typer.Option(100),
    ):
        """Replay one write chain by task_id or session_id."""
        print(workspace_replay_write_chain(workspace, task_id=task_id, session_id=session_id, limit=limit))

    @app.command("record-case")
    def record_case_cmd(
        workspace: str = typer.Option(...),
        task: str = typer.Option(...),
        project: List[str] = REQUIRED_PROJECTS,
        file: List[str] = REQUIRED_FILES,
        flow: str = typer.Option(""),
        risk_point: Optional[List[str]] = OPTIONAL_RISK_POINTS,
        verified_by: Optional[List[str]] = OPTIONAL_VERIFIED_BY,
        source_session_id: str = typer.Option(""),
        source_task_id: str = typer.Option(""),
        valid_from: str = typer.Option(""),
        valid_to: str = typer.Option(""),
        superseded_by: str = typer.Option(""),
        current_truth: bool = typer.Option(True),
    ):
        """Record a validated task into workspace historical memory."""
        print(
            workspace_record_case(
                workspace,
                task,
                project,
                file,
                flow,
                risk_point,
                verified_by,
                source_session_id=source_session_id,
                source_task_id=source_task_id,
                valid_from=valid_from,
                valid_to=valid_to,
                superseded_by=superseded_by,
                current_truth=current_truth,
            )
        )

    @app.command("suggest-case")
    def suggest_case_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(...),
    ):
        """Suggest one record-case draft from a finished session."""
        print(workspace_suggest_case(workspace, session_id))

    @app.command("sync-sniff-artifacts")
    def sync_sniff_artifacts_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(...),
        limit: int = typer.Option(12),
        task_id: str = typer.Option(""),
        title: str = typer.Option(""),
        auto_sync_mode: str = typer.Option("balanced", help="Auto sync recommendation mode: strict|balanced|aggressive"),
    ):
        """Sync sniff result into shared context.md and plan.md."""
        print(
            workspace_sync_sniff_to_artifacts(
                workspace,
                intent,
                limit=limit,
                task_id=task_id,
                title=title,
                auto_sync_mode=auto_sync_mode,
            )
        )

    @app.command("sync-case-artifacts")
    def sync_case_artifacts_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(...),
        task_id: str = typer.Option(""),
        title: str = typer.Option(""),
        auto_sync_mode: str = typer.Option("balanced", help="Auto sync recommendation mode: strict|balanced|aggressive"),
    ):
        """Sync one suggested case into design.md and change-log.md."""
        print(
            workspace_sync_case_to_artifacts(
                workspace,
                session_id,
                task_id=task_id,
                title=title,
                auto_sync_mode=auto_sync_mode,
            )
        )

