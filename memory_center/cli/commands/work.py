"""Work 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import json
from typing import List, Optional

import typer

from memory_center.cli.output import print_data as print
from memory_center.core.orchestrator import (
    memory_eval_regression_suite,
    memory_tool_usage_report,
    workspace_end_session,
    workspace_handoff_packet,
    workspace_log_session_event,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_record_case,
    workspace_record_close_feedback,
    workspace_resume_packet,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_suggest_case,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_task_resume_check,
    workspace_unresolved_items,
)

from ._options import OPTIONAL_VERIFIED_BY
from .session import _parse_event_payload


def register_work_commands(app: typer.Typer) -> None:
    @app.command("work-start")
    def work_start_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(...),
        limit: int = typer.Option(8),
        auto_sync_mode: str = typer.Option("balanced"),
        sync_task_space: bool = typer.Option(
            True, help="Automatically sync context/plan when sniff recommends it or resolves a task."
        ),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Start one task workflow: sniff, optional sync, then start session."""
        sniff_result = workspace_sniff(
            workspace, intent, limit=limit, auto_sync_mode=auto_sync_mode, view="compact", budget=budget
        )
        synced = None
        resolved_task = sniff_result.get("resolved_task", {}) or {}
        auto_sync = sniff_result.get("auto_sync_recommendation", {}) or {}
        if sync_task_space and (auto_sync.get("recommended") or resolved_task.get("task_id")):
            synced = workspace_sync_sniff_to_artifacts(
                workspace,
                intent,
                limit=limit,
                task_id=str(resolved_task.get("task_id", "") or ""),
                title=str(resolved_task.get("title", "") or ""),
                auto_sync_mode=auto_sync_mode,
            )
        session = workspace_start_session(workspace, intent)
        print(
            {
                "workflow": "work-start",
                "workspace": workspace,
                "sniff": sniff_result,
                "sync_sniff": synced,
                "session": session,
            }
        )

    @app.command("work-log")
    def work_log_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(...),
        event_type: str = typer.Option("note"),
        payload: str = typer.Option("{}", help="JSON payload or plain text."),
    ):
        """Append one workflow event into session memory."""
        parsed_payload = _parse_event_payload(payload)
        print(
            {
                "workflow": "work-log",
                "result": workspace_log_session_event(workspace, session_id, event_type, parsed_payload),
            }
        )

    @app.command("work-sync")
    def work_sync_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option(""),
        session_id: str = typer.Option(""),
        task_id: str = typer.Option(""),
        title: str = typer.Option(""),
        limit: int = typer.Option(8),
        auto_sync_mode: str = typer.Option("balanced"),
    ):
        """Sync current task context or case back into task space."""
        if session_id.strip():
            print(
                {
                    "workflow": "work-sync",
                    "mode": "case",
                    "result": workspace_sync_case_to_artifacts(
                        workspace,
                        session_id,
                        task_id=task_id,
                        title=title,
                        auto_sync_mode=auto_sync_mode,
                    ),
                }
            )
            return
        if intent.strip():
            print(
                {
                    "workflow": "work-sync",
                    "mode": "sniff",
                    "result": workspace_sync_sniff_to_artifacts(
                        workspace,
                        intent,
                        limit=limit,
                        task_id=task_id,
                        title=title,
                        auto_sync_mode=auto_sync_mode,
                    ),
                }
            )
            return
        raise typer.BadParameter("work-sync requires either --session-id or --intent")

    @app.command("work-resume")
    def work_resume_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(8),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Resume one task with compact packet, next actions, and unresolved items."""
        print(
            {
                "workflow": "work-resume",
                "resume_packet": workspace_resume_packet(
                    workspace,
                    task_id=task_id,
                    session_id=session_id,
                    intent=intent,
                    limit=limit,
                    view="compact",
                    budget=budget,
                ),
                "next_actions": workspace_next_actions(
                    workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit
                ),
                "unresolved_items": workspace_unresolved_items(
                    workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit
                ),
                "recent_evidence": workspace_recent_evidence(
                    workspace, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"
                ),
            }
        )

    @app.command("work-resume-check")
    def work_resume_check_cmd(
        workspace: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(8),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Check whether one task is ready to resume, with health and repair hints."""
        payload = workspace_task_resume_check(
            workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit, budget=budget
        )
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))

    @app.command("work-handoff")
    def work_handoff_cmd(
        workspace: str = typer.Option(...),
        target_model: str = typer.Option(...),
        task_id: str = typer.Option(""),
        session_id: str = typer.Option(""),
        intent: str = typer.Option(""),
        limit: int = typer.Option(8),
        budget: str = typer.Option("medium", help="small|medium|large"),
    ):
        """Build one compact handoff package for the target model."""
        print(
            {
                "workflow": "work-handoff",
                "handoff_packet": workspace_handoff_packet(
                    workspace,
                    target_model=target_model,
                    task_id=task_id,
                    session_id=session_id,
                    intent=intent,
                    limit=limit,
                    view="compact",
                    budget=budget,
                ),
                "recent_evidence": workspace_recent_evidence(
                    workspace, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"
                ),
                "tool_usage_report": memory_tool_usage_report(workspace, limit=50),
            }
        )

    @app.command("work-close")
    def work_close_cmd(
        workspace: str = typer.Option(...),
        session_id: str = typer.Option(...),
        outcome: str = typer.Option(""),
        task_id: str = typer.Option(""),
        title: str = typer.Option(""),
        auto_sync_mode: str = typer.Option("balanced"),
        record_case: bool = typer.Option(True, help="Auto record the suggested case after syncing."),
        verified_by: Optional[List[str]] = OPTIONAL_VERIFIED_BY,
        validation_command: str = typer.Option("", help="Completed validation command; recorded only, never executed."),
        validation_exit_code: Optional[int] = typer.Option(None, help="Exit code from the completed validation command."),
        validation_summary: str = typer.Option("", help="Bounded validation result summary."),
        validation_status: str = typer.Option("", help="passed|failed|skipped|not_run|recorded"),
    ):
        """Close one task workflow: end session, sync case, optionally record case."""
        ended = workspace_end_session(
            workspace,
            session_id,
            outcome=outcome,
            verified_by=verified_by,
            validation_command=validation_command,
            validation_exit_code=validation_exit_code,
            validation_summary=validation_summary,
            validation_status=validation_status,
        )
        synced = workspace_sync_case_to_artifacts(
            workspace, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode
        )
        draft = workspace_suggest_case(workspace, session_id)
        recorded = None
        candidate_feedback = None
        case = draft.get("draft_case", {}) if draft.get("found") else {}
        if record_case and case.get("projects") and case.get("files"):
            recorded = workspace_record_case(
                workspace,
                case.get("task", outcome or "work-close"),
                case.get("projects", []),
                case.get("files", []),
                case.get("flow", ""),
                case.get("risk_points", []),
                verified_by=case.get("verified_by", []) or verified_by,
                source_session_id=session_id,
                source_task_id=task_id,
            )
        candidate_feedback = workspace_record_close_feedback(
            workspace,
            session_id,
            task_id=task_id,
            source="work_close_auto",
        )
        print(
            {
                "workflow": "work-close",
                "ended": ended,
                "sync_case": synced,
                "suggested_case": draft,
                "record_case": recorded,
                "candidate_feedback": candidate_feedback,
            }
        )

    @app.command("work-health")
    def work_health_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option("Memory Center work health"),
        target_model: str = typer.Option("codex"),
        limit: int = typer.Option(5),
    ):
        """Run one compact health check for workflow readiness."""
        from memory_center.core.benchmark.trending import generate_benchmark_report

        print(
            {
                "workflow": "work-health",
                "status": workspace_status(workspace, view="compact", budget="medium"),
                "tool_usage_report": memory_tool_usage_report(workspace, limit=50),
                "regression_suite": memory_eval_regression_suite(
                    workspace, intent=intent, target_model=target_model, limit=limit
                ),
                "benchmark_trend": generate_benchmark_report(workspace),
            }
        )

