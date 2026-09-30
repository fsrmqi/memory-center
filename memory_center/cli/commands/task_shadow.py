"""Task Shadow 命令族：Session-first 会话影子的观察、快照、绑定与交接。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import json
from typing import Optional

import typer

from memory_center.cli.output import print_data as print
from memory_center.core.tasks.shadow import (
    bind_shadow_to_task,
    build_merged_shadow,
    discard_shadow,
    promote_shadow_to_task,
    shadow_retention_cleanup,
)
from memory_center.core.tasks.shadow_handoff import (
    claim_handoff,
    close_handoff,
    create_handoff,
    get_handoff,
    list_handoffs,
    mark_handed_off,
)
from memory_center.core.tasks.shadow_observations import (
    list_observations,
    record_observation,
    set_shadow_authority,
)


def _parse_json_object(payload: str) -> dict:
    try:
        value = json.loads(payload)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def register_task_shadow_commands(app: typer.Typer) -> None:
    @app.command("task-shadow-record-snapshot")
    def task_shadow_record_snapshot_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        snapshot: str = typer.Option(..., help="Durable TaskShadowSnapshot as JSON."),
        shadow_id: str = typer.Option("", help="Override shadow_id; defaults to snapshot.shadow_id."),
    ):
        """Record one durable (observed==durable) shadow snapshot; volatile input is rejected."""
        try:
            parsed = json.loads(snapshot)
        except json.JSONDecodeError as exc:
            print({"accepted": False, "reason": "invalid_json", "detail": str(exc)[:160]})
            return
        try:
            print(record_shadow_snapshot_entry(workspace, parsed, shadow_id=shadow_id))
        except Exception as exc:
            code = getattr(exc, "code", "snapshot_rejected")
            print({"accepted": False, "reason": code, "detail": str(exc)[:200]})

    @app.command("task-shadow-status")
    def task_shadow_status_cmd(
        workspace: str = typer.Option(...),
        shadow_id: str = typer.Option(...),
    ):
        """Show the merged Task Shadow projection for one shadow_id."""
        shadow = build_merged_shadow(workspace, shadow_id)
        print(shadow or {"found": False, "shadow_id": shadow_id})

    @app.command("task-shadow-bind")
    def task_shadow_bind_cmd(
        workspace: str = typer.Option(...),
        shadow_id: str = typer.Option(...),
        task_id: str = typer.Option(...),
        expected_revision: Optional[int] = typer.Option(None, help="CAS revision; omit to force."),
    ):
        """Bind a Task Shadow to a formal task space (CAS on revision)."""
        print(bind_shadow_to_task(workspace, shadow_id, task_id, expected_revision=expected_revision, source="cli"))

    @app.command("task-shadow-discard")
    def task_shadow_discard_cmd(
        workspace: str = typer.Option(...),
        shadow_id: str = typer.Option(...),
        reason: str = typer.Option("user_requested"),
    ):
        """Discard a Task Shadow; L0 receipts and L2 artifacts are untouched."""
        print(discard_shadow(workspace, shadow_id, reason=reason))

    @app.command("task-shadow-promote")
    def task_shadow_promote_cmd(
        workspace: str = typer.Option(...),
        shadow_id: str = typer.Option(...),
        task_id: str = typer.Option("", help="Optional task override; defaults to the bound task."),
    ):
        """Promote a bound shadow's summary/evidence into its task's context artifact."""
        print(promote_shadow_to_task(workspace, shadow_id, task_id=task_id))

    @app.command("task-shadow-retention")
    def task_shadow_retention_cmd(
        workspace: str = typer.Option(...),
        older_than_days: int = typer.Option(14),
        apply: bool = typer.Option(False, help="Apply cleanup; default is dry-run."),
    ):
        """Clean up old unbound shadows; bound shadows are never touched."""
        print(shadow_retention_cleanup(workspace, older_than_days=older_than_days, apply=apply))

    @app.command("task-shadow-observation")
    def task_shadow_observation_cmd(
        workspace: str = typer.Option(...),
        observation: str = typer.Option(..., help="Observation JSON (allowlist-fail-closed payload)."),
        fold: bool = typer.Option(True, help="Fold into the source-local shadow contribution."),
    ):
        """Record one Observation into the inbox; duplicate event_seq is a no-op."""
        try:
            parsed = json.loads(observation)
        except json.JSONDecodeError as exc:
            print({"recorded": False, "reason": "invalid_json", "detail": str(exc)[:160]})
            return
        try:
            print(record_observation(workspace, parsed, fold_into_shadow=fold))
        except Exception as exc:
            code = getattr(exc, "code", "observation_rejected")
            print({"recorded": False, "reason": code, "detail": str(exc)[:200]})

    @app.command("task-shadow-observation-list")
    def task_shadow_observation_list_cmd(
        workspace: str = typer.Option(...),
        source_kind: str = typer.Option("", help="dsh|codex|claude|other"),
        source_session_id: str = typer.Option(""),
        kind: str = typer.Option(""),
        limit: int = typer.Option(50),
    ):
        """List recorded observations (L0 audit evidence)."""
        print(list_observations(workspace, source_kind=source_kind, source_session_id=source_session_id, kind=kind, limit=limit))

    @app.command("task-shadow-authority")
    def task_shadow_authority_cmd(
        workspace: str = typer.Option(...),
        shadow_id: str = typer.Option(...),
        authority: str = typer.Option(..., help="observation|snapshot"),
    ):
        """Switch shadow_authority for one shadow; snapshot disposes observation contributions."""
        print(set_shadow_authority(workspace, shadow_id, authority))

    @app.command("task-shadow-handoff-create")
    def task_shadow_handoff_create_cmd(
        workspace: str = typer.Option(...),
        from_session_id: str = typer.Option(...),
        shadow_id: str = typer.Option(""),
        to_agent_hint: str = typer.Option(""),
    ):
        """Create a handoff draft (never creates a formal task)."""
        print(create_handoff(workspace, from_session_id=from_session_id, shadow_id=shadow_id, to_agent_hint=to_agent_hint))

    @app.command("task-shadow-handoff-hand-off")
    def task_shadow_handoff_hand_off_cmd(
        workspace: str = typer.Option(...),
        handoff_id: str = typer.Option(...),
        expected_revision: int = typer.Option(..., help="CAS revision."),
    ):
        """draft → handed_off (CAS)."""
        print(mark_handed_off(workspace, handoff_id, expected_revision=expected_revision))

    @app.command("task-shadow-handoff-claim")
    def task_shadow_handoff_claim_cmd(
        workspace: str = typer.Option(...),
        handoff_id: str = typer.Option(...),
        claimed_by_session_id: str = typer.Option(...),
        expected_revision: int = typer.Option(..., help="CAS revision."),
    ):
        """handed_off → claimed (claim-once CAS; stale revision conflicts)."""
        print(claim_handoff(workspace, handoff_id, claimed_by_session_id=claimed_by_session_id, expected_revision=expected_revision))

    @app.command("task-shadow-handoff-close")
    def task_shadow_handoff_close_cmd(
        workspace: str = typer.Option(...),
        handoff_id: str = typer.Option(...),
        expected_revision: int = typer.Option(...),
        outcome: str = typer.Option("completed"),
    ):
        """claimed/handed_off → closed (CAS)."""
        print(close_handoff(workspace, handoff_id, expected_revision=expected_revision, outcome=outcome))

    @app.command("task-shadow-handoff-get")
    def task_shadow_handoff_get_cmd(
        workspace: str = typer.Option(...),
        handoff_id: str = typer.Option(...),
    ):
        """Show one handoff claim record."""
        print(get_handoff(workspace, handoff_id))

    @app.command("task-shadow-handoff-list")
    def task_shadow_handoff_list_cmd(
        workspace: str = typer.Option(...),
        status: str = typer.Option(""),
        limit: int = typer.Option(20),
    ):
        """List handoff claims."""
        print(list_handoffs(workspace, status=status, limit=limit))


def record_shadow_snapshot_entry(workspace: str, snapshot: dict, *, shadow_id: str = "") -> dict:
    from memory_center.core.tasks.shadow import record_shadow_snapshot

    return record_shadow_snapshot(workspace, snapshot, shadow_id=shadow_id)
