"""Write 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
from typing import List, Optional

import typer

from memory_center.cli.output import print_data as print
from memory_center.core.orchestrator import (
    memory_execute_write,
    memory_plan_write,
    memory_write_judge,
    reinstate_case,
    supersede_case,
    workspace_case_decisions,
    workspace_consolidate_sessions,
    workspace_decide_consolidation_candidate,
    workspace_list_consolidation_candidates,
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
    OPTIONAL_SESSION_IDS,
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
        actor: str = typer.Option("", help="Decision actor recorded in the write receipt."),
        valid_from: str = typer.Option(""),
        valid_to: str = typer.Option(""),
        superseded_by: str = typer.Option(""),
        current_truth: bool = typer.Option(True),
        extra_fields: str = typer.Option("{}", help="JSON object for schema extension fields."),
        case_type: str = typer.Option("engineering_case", help="Case schema type from rules/case-schemas.yaml."),
    ):
        """Record a validated task into workspace historical memory."""
        try:
            import json
            parsed_extra_fields = json.loads(extra_fields)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter("extra_fields must be a JSON object") from exc
        if not isinstance(parsed_extra_fields, dict):
            raise typer.BadParameter("extra_fields must be a JSON object")
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
                actor=actor,
                valid_from=valid_from,
                valid_to=valid_to,
                superseded_by=superseded_by,
                current_truth=current_truth,
                extra_fields=parsed_extra_fields,
                case_type=case_type,
            )
        )

    @app.command("suggest-case")
    def suggest_case_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(...),
    ):
        """Suggest one record-case draft from a finished session."""
        print(workspace_suggest_case(workspace, session_id))

    @app.command("consolidate-session")
    def consolidate_session_cmd(
        workspace: str = typer.Option(...),
        session_id: Optional[List[str]] = OPTIONAL_SESSION_IDS,
        limit: int = typer.Option(10, help="Max sessions to consider."),
        include_l3: bool = typer.Option(False, help="Also emit L3 memory-block draft candidates."),
        stage: bool = typer.Option(False, help="Persist candidates for explicit per-item review."),
        apply: bool = typer.Option(False, help="Write ADD/SUPERSEDE candidates into L1. Default is dry-run only."),
    ):
        """Consolidate multiple finished sessions into L1 case / L3 memory-block candidates.

        Dry-run by default: only produces candidates with source refs, conflict reasons,
        and expected write operations. Use --apply to write via record-case (conservative).
        """
        print(
            workspace_consolidate_sessions(
                workspace,
                list(session_id) if session_id else None,
                limit=limit,
                include_l3=include_l3,
                stage=stage,
                apply=apply,
            )
        )

    @app.command("consolidation-candidates")
    def consolidation_candidates_cmd(
        workspace: str = typer.Option(...),
        status: str = typer.Option("pending", help="pending, applied, rejected, or empty for all."),
        limit: int = typer.Option(50, help="Maximum candidates to return."),
    ):
        """List staged multi-session consolidation candidates."""
        print(workspace_list_consolidation_candidates(workspace, status=status, limit=limit))

    @app.command("decide-consolidation-candidate")
    def decide_consolidation_candidate_cmd(
        workspace: str = typer.Option(...),
        candidate_id: str = typer.Option(...),
        decision: str = typer.Option(..., help="approve or reject"),
        actor: str = typer.Option(...),
        note: str = typer.Option(""),
    ):
        """Apply or reject one staged candidate after human review."""
        print(workspace_decide_consolidation_candidate(workspace, candidate_id, decision=decision, actor=actor, note=note))

    @app.command("case-supersede")
    def case_supersede_cmd(
        workspace: str = typer.Option(...),
        case_id: str = typer.Option(...),
        superseded_by: str = typer.Option("", help="Optional successor case_id."),
        actor: str = typer.Option(""),
        note: str = typer.Option(""),
    ):
        """Append a supersede decision row so the case leaves current truth."""
        print(
            supersede_case(
                workspace,
                case_id,
                superseded_by=superseded_by,
                actor=actor,
                note=note,
            )
        )

    @app.command("case-reinstate")
    def case_reinstate_cmd(
        workspace: str = typer.Option(...),
        case_id: str = typer.Option(...),
        actor: str = typer.Option(""),
        note: str = typer.Option(""),
    ):
        """Append a reinstate decision row to restore current truth."""
        print(reinstate_case(workspace, case_id, actor=actor, note=note))

    @app.command("case-decisions")
    def case_decisions_cmd(
        workspace: str = typer.Option(...),
        case_id: str = typer.Option("", help="Filter by case_id."),
        limit: int = typer.Option(50),
    ):
        """List case supersede/reinstate decision rows (latest first)."""
        print(workspace_case_decisions(workspace, case_id=case_id, limit=limit))

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
