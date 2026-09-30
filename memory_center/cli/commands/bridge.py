"""Bridge 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

import json

import typer

from memory_center.cli.output import print_data as print
from memory_center.core.orchestrator import (
    bootstrap_workspace_context,
    execute_mcp_bridge_action,
    execute_provider_action,
    fuse_provider_evidence,
    mcp_bridge_status,
    memory_eval_regression_suite,
    memory_ref_get,
    workspace_dashboard,
    workspace_end_session,
    workspace_log_session_event,
    workspace_recent_evidence,
    workspace_resume_packet,
    workspace_start_session,
    workspace_status,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
)
from memory_center.core.tasks.artifacts import create_task_space, update_task_artifact


def register_bridge_commands(app: typer.Typer) -> None:
    @app.command("discover")
    def discover_cmd(
        workspace: str = typer.Option(...),
        limit: int = typer.Option(50, help="Number of recent events to analyze."),
    ):
        """Discover hot commands and recommend next actions."""
        from memory_center.core.orchestrator import memory_discover

        print(memory_discover(workspace, limit=limit))

    @app.command("constraint")
    def constraint_cmd(
        template: str = typer.Option("coding_agent", help="Template: coding_agent, review_agent, quick_lookup."),
        context: str = typer.Option("", help="Context for auto-select."),
    ):
        """Show constraint template or auto-select action."""
        from memory_center.core.governance.templates import auto_select_action, get_constraint_template

        if context:
            action = auto_select_action(context, template)
            print({"context": context, "template": template, "recommended_action": action})
        else:
            tmpl = get_constraint_template(template)
            if tmpl:
                print(tmpl)
            else:
                print(f"Unknown template: {template}. Available: coding_agent, review_agent, quick_lookup")

    @app.command("regression-smoke")
    def regression_smoke_cmd(
        workspace: str = typer.Option(...),
        intent: str = typer.Option("Memory Center regression smoke"),
        target_model: str = typer.Option("codex"),
        limit: int = typer.Option(5),
    ):
        """Run one end-to-end smoke check across write, resume, handoff, refs, and compact views."""
        task = create_task_space(workspace, title="regression-smoke")
        update = update_task_artifact(workspace, task["task_id"], "context", "## Context\n\nRegression smoke")
        session = workspace_start_session(workspace, intent)
        workspace_log_session_event(
            workspace,
            session["session_id"],
            "tool_call",
            {"tool_name": "mc_lookup", "query": "ArticleFeignClient", "project": "task-service"},
        )
        workspace_end_session(workspace, session["session_id"], outcome="smoke complete")
        sync_sniff = workspace_sync_sniff_to_artifacts(
            workspace, "ArticleFeignClient 调用链", task_id=task["task_id"], limit=limit
        )
        sync_case = workspace_sync_case_to_artifacts(workspace, session["session_id"], task_id=task["task_id"])
        refs = workspace_recent_evidence(workspace, session_id=session["session_id"], limit=3)
        first_ref = (refs.get("evidence", []) or [{}])[0].get("ref_id", "")
        report = {
            "workspace": workspace,
            "task_id": task["task_id"],
            "task_artifact_write": bool(update.get("write_receipt")),
            "sync_sniff": bool(sync_sniff.get("synced")),
            "sync_case": bool(sync_case.get("synced")),
            "recent_evidence_count": len(refs.get("evidence", [])),
            "first_ref": memory_ref_get(workspace, first_ref) if first_ref else None,
            "regression_suite": memory_eval_regression_suite(
                workspace,
                task_id=task["task_id"],
                session_id=session["session_id"],
                intent=intent,
                target_model=target_model,
                limit=limit,
            ),
            "status_compact": workspace_status(workspace, view="compact"),
            "resume_compact": workspace_resume_packet(
                workspace, task_id=task["task_id"], session_id=session["session_id"], intent=intent, view="compact"
            ),
            "dashboard_compact": workspace_dashboard(workspace, intent=intent, limit=limit, view="compact"),
        }
        print(report)

    @app.command("bootstrap-context")
    def bootstrap_context_cmd(
        path: str = typer.Option(
            ".", help="Project directory or workspace.yaml; no workspace initialization is performed."
        ),
        intent: str = typer.Option(""),
        query: str = typer.Option(""),
        target: str = typer.Option(""),
        limit: int = typer.Option(8, min=1, max=12),
    ):
        """Use Memory Center when initialized, otherwise query the optional GitNexus read-only provider."""
        print(bootstrap_workspace_context(path, intent=intent, query=query, target=target, limit=limit))

    @app.command("provider-action")
    def provider_action_cmd(
        path: str = typer.Option(".", help="Project directory or workspace.yaml."),
        action: str = typer.Option(
            ..., help="Registered provider action, such as impact, detect-changes, analyze, or clean."
        ),
        provider: str = typer.Option("gitnexus"),
        query: str = typer.Option(""),
        target: str = typer.Option(""),
        confirm: bool = typer.Option(False, help="Required for controlled-write and destructive actions."),
        force: bool = typer.Option(False, help="Only applies to registered actions that support force."),
        limit: int = typer.Option(8, min=1, max=12),
        depth: int = typer.Option(3, min=1, max=5),
    ):
        """Run a registered external-provider action with fixed arguments and confirmation gates."""
        print(
            execute_provider_action(
                path,
                provider=provider,
                action=action,
                query=query,
                target=target,
                confirm=confirm,
                force=force,
                limit=limit,
                depth=depth,
            )
        )

    @app.command("mcp-bridge-status")
    def mcp_bridge_status_cmd(
        path: str = typer.Option(
            ".", help="Project directory or workspace.yaml; no workspace initialization is performed."
        ),
    ):
        """Show the explicitly allowed external HTTP MCP bridge actions for a project."""
        print(mcp_bridge_status(path))

    @app.command("mcp-bridge-action")
    def mcp_bridge_action_cmd(
        path: str = typer.Option(".", help="Project directory or workspace.yaml."),
        provider: str = typer.Option(..., help="Provider id declared in provider-mcp-policy.json."),
        action: str = typer.Option(..., help="Whitelisted external MCP action."),
        query: str = typer.Option(""),
        target: str = typer.Option(""),
        confirm: bool = typer.Option(False, help="Required for controlled-write and destructive actions."),
    ):
        """Invoke one policy-whitelisted external HTTP MCP tool with fixed argument templates."""
        print(
            execute_mcp_bridge_action(path, provider=provider, action=action, query=query, target=target, confirm=confirm)
        )

    @app.command("provider-evidence-fuse")
    def provider_evidence_fuse_cmd(
        path: str = typer.Option(
            ".", help="Project directory or workspace.yaml; no workspace initialization is performed."
        ),
        evidence_json: str = typer.Option(..., help="JSON array of redacted EvidenceRef objects returned by providers."),
    ):
        """Fuse external EvidenceRef claims without storing external tool bodies."""
        try:
            evidence_refs = json.loads(evidence_json)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter("evidence-json must be a JSON array") from exc
        if not isinstance(evidence_refs, list) or not all(isinstance(item, dict) for item in evidence_refs):
            raise typer.BadParameter("evidence-json must be a JSON array of objects")
        print(fuse_provider_evidence(path, evidence_refs))

