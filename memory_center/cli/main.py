from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich import print

from memory_center import __version__
from memory_center.core.artifacts import (
    append_task_change_log,
    archive_task_space,
    append_change_log,
    auto_archive_task_spaces,
    artifact_context,
    artifact_outline,
    compact_change_log,
    create_task_space,
    ensure_default_artifacts,
    get_artifact,
    get_task_artifact,
    list_artifacts,
    list_task_spaces,
    resolve_task_space,
    touch_task_activity,
    update_task_status,
    update_task_artifact,
    update_artifact,
)
from memory_center.core.config import add_workspace_service, load_workspace_config, remove_workspace_service, write_default_workspace
from memory_center.core.exporters import export_mermaid, export_workspace_dashboard_html, export_workspace_dashboard_markdown
from memory_center.core.indexer import reindex_workspace
from memory_center.core.instructions import write_agent_instructions
from memory_center.core.orchestrator import (
    group_impact,
    group_query,
    group_status,
    memory_callers,
    memory_callees,
    memory_context,
    memory_contracts,
    memory_detect_changes,
    memory_impact,
    memory_plan_change,
    memory_query,
    memory_backend_query,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    memory_plan_write,
    memory_tool_usage_report,
    memory_execute_write,
    memory_write_judge,
    workspace_check_contract,
    workspace_check_rules,
    workspace_lookup_hint,
    workspace_record_case,
    workspace_recent_sessions,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_session_summary,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_trace,
    workspace_log_session_event,
    workspace_end_session,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_handoff_packet,
    workspace_handoff_history,
    workspace_model_profile,
    workspace_resume_packet,
    workspace_resume_context,
    workspace_suggest_case,
    workspace_unresolved_items,
    workspace_write_receipts,
    workspace_replay_write_chain,
    memory_eval_write_quality,
    memory_eval_regression_suite,
    memory_eval_index_freshness,
    memory_eval_tool_adoption,
    memory_eval_context_weight,
    memory_eval_workflow_orchestration,
    memory_eval_resume,
    memory_eval_handoff,
)
from memory_center.core.rules import ensure_default_rules
from memory_center.core.store import WorkspaceStore
from memory_center.core.validators import doctor as run_doctor
from memory_center.core.registry import add_to_group, create_group, list_workspaces, register_workspace, resolve_workspace
from memory_center.core.wiki import generate_skills, generate_wiki
from memory_center.http.server import serve_http

app = typer.Typer(help="Memory Center CLI")
registry_app = typer.Typer(help="Global registry commands")
group_app = typer.Typer(help="Workspace group commands")
workspace_app = typer.Typer(help="Workspace config maintenance commands")
artifact_app = typer.Typer(help="Shared workspace artifacts commands")
app.add_typer(registry_app, name="registry")
app.add_typer(group_app, name="group")
app.add_typer(workspace_app, name="workspace")
app.add_typer(artifact_app, name="artifact")


def _version_callback(value: bool):
    if value:
        print({"name": "memory-center", "version": __version__})
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(False, "--version", help="Show Memory Center version and exit.", is_eager=True, callback=_version_callback),
):
    """Memory Center CLI entrypoint."""


@app.command()
def init(workspace_root: str = typer.Option(...), name: str = typer.Option("dev-workspace")):
    """Initialize a .memory-center workspace under a multi-project root."""
    workspace_file = write_default_workspace(workspace_root, name)
    store = WorkspaceStore(workspace_file)
    ensure_default_rules(store)
    ensure_default_artifacts(workspace_file)
    write_agent_instructions(store, workspace_root)
    print(f"[green]Initialized:[/green] {workspace_file}")
    print("Edit workspace.yaml services, then run: memory-center reindex --workspace <workspace.yaml>")


@app.command()
def reindex(
    workspace: str = typer.Option(...),
    project: Optional[List[str]] = typer.Option(None, help="Only rebuild indexes for these projects."),
    path: Optional[List[str]] = typer.Option(None, help="Only rebuild indexes for these logical or absolute paths."),
    changed_only: bool = typer.Option(False, help="Use changed files from memory-detect-changes as reindex scope."),
    scope: str = typer.Option("staged", help="When --changed-only is set: staged|head|all"),
):
    """Rebuild file, symbol, API, Feign, MQ, config and topology indexes."""
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    selected_paths = list(path or [])
    if changed_only:
        change_scope = "unstaged" if scope == "all" else scope
        changed = memory_detect_changes(workspace, change_scope)
        selected_paths.extend(changed.get("changed_files", []))
        selected_paths.extend(changed.get("deleted_files", []))
    counts = reindex_workspace(config, store, projects=project, paths=selected_paths)
    ensure_default_rules(store)
    ensure_default_artifacts(workspace)
    write_agent_instructions(store, config.root_path)
    print({"reindexed": True, "counts": counts})


@app.command()
def status(
    workspace: str = typer.Option(...),
    view: str = typer.Option("full", help="full|compact"),
    budget: str = typer.Option("medium", help="small|medium|large"),
):
    """Print workspace index and memory status."""
    print(workspace_status(workspace, view=view, budget=budget))


@app.command()
def sniff(
    workspace: str = typer.Option(...),
    intent: str = typer.Option(...),
    limit: int = typer.Option(12),
    auto_sync_mode: str = typer.Option("balanced", help="Auto sync recommendation mode: strict|balanced|aggressive"),
    view: str = typer.Option("full", help="full|compact"),
    budget: str = typer.Option("medium", help="small|medium|large"),
):
    """Retrieve workspace context for a coding task intent."""
    print(workspace_sniff(workspace, intent, limit, auto_sync_mode=auto_sync_mode, view=view, budget=budget))


@app.command()
def trace(workspace: str = typer.Option(...), entry: str = typer.Option(...)):
    """Trace cross-service candidates by class, Feign client, endpoint or topic."""
    print(workspace_trace(workspace, entry))


@app.command("check-contract")
def check_contract(workspace: str = typer.Option(...), contract_file: str = typer.Option(...), change_type: str = typer.Option("modify")):
    """Check impact before modifying shared DTO, Feign or MQ message contracts."""
    print(workspace_check_contract(workspace, contract_file, change_type))


@app.command("check-rules")
def check_rules(
    workspace: str = typer.Option(...),
    change_type: str = typer.Option("general"),
    project: Optional[List[str]] = typer.Option(None),
    file: Optional[List[str]] = typer.Option(None),
):
    """Match architecture rules for a proposed change."""
    print(workspace_check_rules(workspace, project, change_type, file))


@app.command("export-mermaid")
def export_mermaid_cmd(workspace: str = typer.Option(...), output: Optional[str] = typer.Option(None)):
    """Export service topology as a Mermaid flowchart."""
    diagram = export_mermaid(workspace)
    if output:
        Path(output).write_text(diagram, encoding="utf-8")
        print(f"[green]Wrote:[/green] {output}")
    else:
        print(diagram)


@app.command()
def doctor(workspace: str = typer.Option(...), self_test: bool = typer.Option(False, help="Run lightweight query smoke tests.")):
    """Validate workspace configuration, index health and optional smoke tests."""
    print(run_doctor(workspace, self_test=self_test))


@app.command("query")
def query_cmd(workspace: str = typer.Option(...), text: str = typer.Option(...), limit: int = typer.Option(20)):
    """Graph-aware query across services, files, symbols, contracts and memory."""
    print(memory_query(workspace, text, limit))


@app.command("search-code")
def search_code_cmd(
    workspace: str = typer.Option(...),
    text: str = typer.Option(...),
    scope: str = typer.Option(""),
    limit: int = typer.Option(20),
):
    """Keyword search over indexed files/symbol hints."""
    print(memory_search_code(workspace, text, scope=scope, limit=limit))


@app.command("symbol")
def symbol_cmd(
    workspace: str = typer.Option(...),
    name: str = typer.Option(...),
    limit: int = typer.Option(10),
):
    """Resolve one symbol and return best match candidates."""
    print(memory_symbol(workspace, name, limit=limit))


@app.command("callers")
def callers_cmd(
    workspace: str = typer.Option(...),
    symbol: str = typer.Option(...),
    depth: int = typer.Option(2),
    limit: int = typer.Option(80),
):
    """Find upstream callers for one symbol."""
    print(memory_callers(workspace, symbol, depth=depth, limit=limit))


@app.command("callees")
def callees_cmd(
    workspace: str = typer.Option(...),
    symbol: str = typer.Option(...),
    depth: int = typer.Option(2),
    limit: int = typer.Option(80),
):
    """Find downstream callees for one symbol."""
    print(memory_callees(workspace, symbol, depth=depth, limit=limit))


@app.command("context")
def context_cmd(workspace: str = typer.Option(...), name: str = typer.Option(...), max_depth: int = typer.Option(2)):
    """Return 360-degree context for a symbol, endpoint, topic, service or file."""
    print(memory_context(workspace, name, max_depth))


@app.command("impact")
def impact_cmd(
    workspace: str = typer.Option(...),
    target: str = typer.Option(...),
    direction: str = typer.Option("upstream"),
    max_depth: int = typer.Option(3),
):
    """Analyze upstream/downstream impact for a changed symbol or contract."""
    print(memory_impact(workspace, target, direction, max_depth))


@app.command("detect-changes")
def detect_changes_cmd(workspace: str = typer.Option(...), scope: str = typer.Option("staged")):
    """Map local git changes to affected projects, rules and risk level."""
    print(memory_detect_changes(workspace, scope))


@app.command("contracts")
def contracts_cmd(workspace: str = typer.Option(...)):
    """List Feign/API/MQ contracts discovered in the workspace."""
    print(memory_contracts(workspace))


@app.command("plan-change")
def plan_change_cmd(
    workspace: str = typer.Option(...),
    target: str = typer.Option(...),
    direction: str = typer.Option("upstream"),
    max_depth: int = typer.Option(3),
):
    """Generate one actionable change plan from impact evidence."""
    print(memory_plan_change(workspace, target, direction=direction, max_depth=max_depth))


@app.command("verify-checklist")
def verify_checklist_cmd(
    workspace: str = typer.Option(...),
    target: str = typer.Option(...),
):
    """Generate one verification checklist for a target change."""
    print(memory_verify_checklist(workspace, target))


@app.command("memory-write-judge")
def memory_write_judge_cmd(
    workspace: str = typer.Option(...),
    text: str = typer.Option(...),
    source: str = typer.Option("note"),
    intent: str = typer.Option(""),
    prefer_layer: str = typer.Option(""),
    project: Optional[List[str]] = typer.Option(None),
    file: Optional[List[str]] = typer.Option(None),
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
    project: Optional[List[str]] = typer.Option(None),
    file: Optional[List[str]] = typer.Option(None),
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
    project: Optional[List[str]] = typer.Option(None),
    file: Optional[List[str]] = typer.Option(None),
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


@app.command("eval-write-quality")
def eval_write_quality_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(""),
    session_id: str = typer.Option(""),
    intent: str = typer.Option(""),
    limit: int = typer.Option(100),
):
    """Evaluate write quality from persisted receipts."""
    print(memory_eval_write_quality(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit))


@app.command("eval-resume")
def eval_resume_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(""),
    session_id: str = typer.Option(""),
    intent: str = typer.Option(""),
    limit: int = typer.Option(20),
):
    """Evaluate resume packet quality."""
    print(memory_eval_resume(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit))


@app.command("eval-handoff")
def eval_handoff_cmd(
    workspace: str = typer.Option(...),
    target_model: str = typer.Option(...),
    task_id: str = typer.Option(""),
    session_id: str = typer.Option(""),
    intent: str = typer.Option(""),
    limit: int = typer.Option(20),
):
    """Evaluate handoff packet quality."""
    print(memory_eval_handoff(workspace, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit))


@app.command("eval-regression-suite")
def eval_regression_suite_cmd(
    workspace: str = typer.Option(...),
    target_model: str = typer.Option("codex"),
    task_id: str = typer.Option(""),
    session_id: str = typer.Option(""),
    intent: str = typer.Option(""),
    limit: int = typer.Option(20),
):
    """Run the aggregated write/resume/handoff regression suite."""
    print(
        memory_eval_regression_suite(
            workspace,
            target_model=target_model,
            task_id=task_id,
            session_id=session_id,
            intent=intent,
            limit=limit,
        )
    )


@app.command("eval-index-freshness")
def eval_index_freshness_cmd(
    workspace: str = typer.Option(...),
    scope: str = typer.Option("all"),
):
    """Evaluate whether indexes look stale relative to current git changes."""
    print(memory_eval_index_freshness(workspace, scope=scope))


@app.command("eval-tool-adoption")
def eval_tool_adoption_cmd(
    workspace: str = typer.Option(...),
    limit: int = typer.Option(200),
):
    """Evaluate recent Memory Center tool adoption quality."""
    print(memory_eval_tool_adoption(workspace, limit=limit))


@app.command("eval-context-weight")
def eval_context_weight_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option(""),
    limit: int = typer.Option(8),
):
    """Evaluate whether compact budgeted payloads are still too heavy."""
    print(memory_eval_context_weight(workspace, intent=intent, limit=limit))


@app.command("eval-workflow-orchestration")
def eval_workflow_orchestration_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option("", help="Evaluate workflow for a specific task."),
    session_id: str = typer.Option("", help="Evaluate workflow for a specific session."),
    intent: str = typer.Option("", help="Intent for evaluation context."),
    limit: int = typer.Option(20),
):
    """Evaluate whether a workflow follows the recommended start→log→sync→close pattern."""
    print(memory_eval_workflow_orchestration(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit))


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
        {"tool_name": "memory_query_tool", "query": "ArticleFeignClient", "project": "task-service"},
    )
    workspace_end_session(workspace, session["session_id"], outcome="smoke complete")
    sync_sniff = workspace_sync_sniff_to_artifacts(workspace, "ArticleFeignClient 调用链", task_id=task["task_id"], limit=limit)
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
        "regression_suite": memory_eval_regression_suite(workspace, task_id=task["task_id"], session_id=session["session_id"], intent=intent, target_model=target_model, limit=limit),
        "status_compact": workspace_status(workspace, view="compact"),
        "resume_compact": workspace_resume_packet(workspace, task_id=task["task_id"], session_id=session["session_id"], intent=intent, view="compact"),
        "dashboard_compact": workspace_dashboard(workspace, intent=intent, limit=limit, view="compact"),
    }
    print(report)


@app.command("lookup-hint")
def lookup_hint_cmd(
    workspace: str = typer.Option(...),
    query: str = typer.Option(...),
    intent: str = typer.Option(""),
    limit: int = typer.Option(8),
):
    """Suggest whether to use Memory Center lookup tools or local search first."""
    print(workspace_lookup_hint(workspace, query=query, intent=intent, limit=limit))


@app.command("tool-usage-report")
def tool_usage_report_cmd(
    workspace: str = typer.Option(...),
    limit: int = typer.Option(200),
):
    """Summarize recent Memory Center vs external tool usage and lookup adoption."""
    print(memory_tool_usage_report(workspace, limit=limit))


@app.command("ref-get")
def ref_get_cmd(
    workspace: str = typer.Option(...),
    ref_id: str = typer.Option(...),
):
    """Resolve one short memory reference id into full raw content."""
    print(memory_ref_get(workspace, ref_id=ref_id))


@app.command("ref-batch")
def ref_batch_cmd(
    workspace: str = typer.Option(...),
    ref_id: List[str] = typer.Option(...),
):
    """Resolve multiple short memory reference ids."""
    print(memory_ref_batch(workspace, ref_ids=ref_id))


@app.command("memory-backend-query")
def memory_backend_query_cmd(
    workspace: str = typer.Option(...),
    collection: str = typer.Option(""),
    record_id: str = typer.Option(""),
    created_after: str = typer.Option(""),
    ref_path: str = typer.Option(""),
    project: str = typer.Option("", help="Filter records by project name."),
    payload_type: str = typer.Option("", help="Filter records by payload type."),
    limit: int = typer.Option(50),
):
    """Query mirrored SQLite memory backend records and refs."""
    print(memory_backend_query(workspace, collection=collection, record_id=record_id, created_after=created_after, ref_path=ref_path, project=project, payload_type=payload_type, limit=limit))


@app.command("generate-wiki")
def generate_wiki_cmd(workspace: str = typer.Option(...), output: Optional[str] = typer.Option(None)):
    """Generate bilingual Markdown architecture wiki from indexes and memory."""
    print(generate_wiki(workspace, output))


@app.command("generate-skills")
def generate_skills_cmd(workspace: str = typer.Option(...), output: Optional[str] = typer.Option(None)):
    """Generate Claude/agent skills from historical task memory."""
    print(generate_skills(workspace, output))


@app.command("record-case")
def record_case_cmd(
    workspace: str = typer.Option(...),
    task: str = typer.Option(...),
    project: List[str] = typer.Option(...),
    file: List[str] = typer.Option(...),
    flow: str = typer.Option(""),
    risk_point: Optional[List[str]] = typer.Option(None),
    verified_by: Optional[List[str]] = typer.Option(None),
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
    verified_by: Optional[List[str]] = typer.Option(None),
):
    """Finalize one session and generate a summary record."""
    print(workspace_end_session(workspace, session_id, outcome=outcome, verified_by=verified_by))


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
):
    """Show recent evidence from task receipts and session events."""
    print(workspace_recent_evidence(workspace, task_id=task_id, session_id=session_id, limit=limit, budget=budget))


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
    print(workspace_resume_packet(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view=view, budget=budget))


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
    print(workspace_handoff_packet(workspace, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view=view, budget=budget))


@app.command("handoff-history")
def handoff_history_cmd(
    workspace: str = typer.Option(...),
    target_model: str = typer.Option(""),
    task_id: str = typer.Option(""),
    session_id: str = typer.Option(""),
    limit: int = typer.Option(50),
):
    """Query persisted handoff history."""
    print(workspace_handoff_history(workspace, target_model=target_model, task_id=task_id, session_id=session_id, limit=limit))


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
    print(workspace_continuity_dashboard(workspace, intent=intent, task_id=task_id, session_id=session_id, limit=limit, view=view, budget=budget))


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


@app.command("work-start")
def work_start_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option(...),
    limit: int = typer.Option(8),
    auto_sync_mode: str = typer.Option("balanced"),
    sync_task_space: bool = typer.Option(True, help="Automatically sync context/plan when sniff recommends it or resolves a task."),
    budget: str = typer.Option("medium", help="small|medium|large"),
):
    """Start one task workflow: sniff, optional sync, then start session."""
    sniff_result = workspace_sniff(workspace, intent, limit=limit, auto_sync_mode=auto_sync_mode, view="compact", budget=budget)
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
    print({"workflow": "work-log", "result": workspace_log_session_event(workspace, session_id, event_type, parsed_payload)})


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
            "resume_packet": workspace_resume_packet(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "next_actions": workspace_next_actions(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "unresolved_items": workspace_unresolved_items(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "recent_evidence": workspace_recent_evidence(workspace, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget),
        }
    )


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
            "handoff_packet": workspace_handoff_packet(workspace, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "recent_evidence": workspace_recent_evidence(workspace, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget),
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
    verified_by: Optional[List[str]] = typer.Option(None),
):
    """Close one task workflow: end session, sync case, optionally record case."""
    ended = workspace_end_session(workspace, session_id, outcome=outcome, verified_by=verified_by)
    synced = workspace_sync_case_to_artifacts(workspace, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)
    draft = workspace_suggest_case(workspace, session_id)
    recorded = None
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
    print(
        {
            "workflow": "work-close",
            "ended": ended,
            "sync_case": synced,
            "suggested_case": draft,
            "record_case": recorded,
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
    print(
        {
            "workflow": "work-health",
            "status": workspace_status(workspace, view="compact", budget="medium"),
            "tool_usage_report": memory_tool_usage_report(workspace, limit=50),
            "regression_suite": memory_eval_regression_suite(workspace, intent=intent, target_model=target_model, limit=limit),
        }
    )


@app.command("export-workspace-dashboard")
def export_workspace_dashboard_cmd(
    workspace: str = typer.Option(...),
    output: str = typer.Option(...),
    format: str = typer.Option("html", help="html|markdown"),
    intent: str = typer.Option(""),
    limit: int = typer.Option(10),
):
    """Export one workspace dashboard to HTML or Markdown."""
    fmt = format.strip().lower()
    if fmt == "html":
        content = export_workspace_dashboard_html(workspace, intent=intent, limit=limit)
    elif fmt in {"md", "markdown"}:
        content = export_workspace_dashboard_markdown(workspace, intent=intent, limit=limit)
    else:
        raise typer.BadParameter("format must be html or markdown")
    Path(output).write_text(content, encoding="utf-8")
    print({"exported": True, "format": fmt, "output": output})


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


@registry_app.command("add")
def registry_add(name: str = typer.Option(...), workspace: str = typer.Option(...)):
    """Register a workspace globally under ~/.memory-center/registry.json."""
    print(register_workspace(name, workspace))


@registry_app.command("list")
def registry_list():
    """List globally registered workspaces."""
    print(list_workspaces())


@group_app.command("create")
def group_create(name: str = typer.Option(...)):
    """Create a logical group for multiple registered workspaces."""
    print(create_group(name))


@group_app.command("add")
def group_add(name: str = typer.Option(...), repo: str = typer.Option(...)):
    """Add a registered workspace to a logical group."""
    print(add_to_group(name, repo))


@group_app.command("status")
def group_status_cmd(name: str = typer.Option(...)):
    """Show aggregated status for all workspaces in a logical group."""
    print(group_status(name))


@group_app.command("query")
def group_query_cmd(name: str = typer.Option(...), text: str = typer.Option(...), limit: int = typer.Option(20)):
    """Run a merged query across all workspaces in a logical group."""
    print(group_query(name, text, limit))


@group_app.command("impact")
def group_impact_cmd(
    name: str = typer.Option(...),
    target: str = typer.Option(...),
    direction: str = typer.Option("upstream"),
    max_depth: int = typer.Option(3),
):
    """Run cross-workspace impact analysis for a logical group."""
    print(group_impact(name, target, direction, max_depth))


@workspace_app.command("list-services")
def workspace_list_services(workspace: str = typer.Option(...)):
    """List configured services in workspace.yaml."""
    config = load_workspace_config(workspace)
    print({"workspace": config.workspace, "root": str(config.root_path), "services": [item.__dict__ for item in config.services]})


@workspace_app.command("add-service")
def workspace_add_service(
    workspace: str = typer.Option(...),
    name: str = typer.Option(...),
    path: str = typer.Option(...),
    service_type: str = typer.Option("spring-boot-service", "--type"),
    service_name: Optional[str] = typer.Option(None),
    tag: Optional[List[str]] = typer.Option(None),
):
    """Add or replace one service entry in workspace.yaml."""
    result = add_workspace_service(workspace, name, path, service_type, service_name, tag)
    result["next_steps"] = [
        f"memory-center reindex --workspace {Path(workspace).expanduser().resolve()}",
        f"memory-center doctor --workspace {Path(workspace).expanduser().resolve()} --self-test",
    ]
    print(result)


@workspace_app.command("remove-service")
def workspace_remove_service(
    workspace: str = typer.Option(...),
    name: str = typer.Option(..., help="Service name or path to remove."),
):
    """Remove one service entry from workspace.yaml by name or path."""
    result = remove_workspace_service(workspace, name)
    result["next_steps"] = [
        f"memory-center reindex --workspace {Path(workspace).expanduser().resolve()}",
        f"memory-center doctor --workspace {Path(workspace).expanduser().resolve()} --self-test",
    ]
    print(result)


@artifact_app.command("list")
def artifact_list_cmd(workspace: str = typer.Option(...)):
    """List shared workspace artifacts."""
    print(list_artifacts(workspace))


@artifact_app.command("get")
def artifact_get_cmd(
    workspace: str = typer.Option(...),
    name: str = typer.Option(...),
):
    """Read one shared artifact."""
    print(get_artifact(workspace, name))


@artifact_app.command("outline")
def artifact_outline_cmd(
    workspace: str = typer.Option(...),
    name: str = typer.Option(...),
):
    """Read one artifact outline instead of full content."""
    print(artifact_outline(workspace, name))


@artifact_app.command("context")
def artifact_context_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option(...),
    limit: int = typer.Option(6),
):
    """Retrieve only relevant artifact snippets for the current intent."""
    print(artifact_context(workspace, intent, limit=limit))


@artifact_app.command("update")
def artifact_update_cmd(
    workspace: str = typer.Option(...),
    name: str = typer.Option(...),
    content: str = typer.Option(...),
):
    """Replace one shared artifact content."""
    print(update_artifact(workspace, name, content))


@artifact_app.command("append-change-log")
def artifact_append_change_log_cmd(
    workspace: str = typer.Option(...),
    entry: str = typer.Option(...),
):
    """Append one timestamped entry into change-log.md."""
    print(append_change_log(workspace, entry))


@artifact_app.command("compact-change-log")
def artifact_compact_change_log_cmd(
    workspace: str = typer.Option(...),
    keep_recent: int = typer.Option(30),
):
    """Archive older change-log entries to avoid oversized shared context."""
    print(compact_change_log(workspace, keep_recent=keep_recent))


@artifact_app.command("create-task")
def artifact_create_task_cmd(
    workspace: str = typer.Option(...),
    title: str = typer.Option(""),
    intent: str = typer.Option(""),
    owner: str = typer.Option(""),
    tag: Optional[List[str]] = typer.Option(None),
    priority: str = typer.Option("medium"),
):
    """Create one task-specific artifact space from a custom title or intent."""
    print(create_task_space(workspace, title=title, intent=intent, owner=owner, tags=tag, priority=priority))


@artifact_app.command("list-tasks")
def artifact_list_tasks_cmd(
    workspace: str = typer.Option(...),
    include_archived: bool = typer.Option(False),
):
    """List active or archived task artifact spaces."""
    print(list_task_spaces(workspace, include_archived=include_archived))


@artifact_app.command("resolve-task")
def artifact_resolve_task_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option(...),
    title: str = typer.Option(""),
    create_if_missing: bool = typer.Option(True),
    include_archived: bool = typer.Option(False),
    limit_candidates: int = typer.Option(3),
    score_threshold: int = typer.Option(3, help="Minimum score to auto-match an existing task space."),
):
    """Resolve one task space from natural language; create one if needed."""
    print(resolve_task_space(workspace, intent=intent, title=title, create_if_missing=create_if_missing, include_archived=include_archived, limit_candidates=limit_candidates, score_threshold=score_threshold))


@artifact_app.command("get-task")
def artifact_get_task_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
    name: str = typer.Option(...),
):
    """Read one task-space artifact."""
    print(get_task_artifact(workspace, task_id, name))


@artifact_app.command("update-task")
def artifact_update_task_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
    name: str = typer.Option(...),
    content: str = typer.Option(...),
):
    """Replace one task-space artifact content."""
    print(update_task_artifact(workspace, task_id, name, content))


@artifact_app.command("append-task-change-log")
def artifact_append_task_change_log_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
    entry: str = typer.Option(...),
    keep_recent: int = typer.Option(30),
):
    """Append one timestamped entry into a task-space change log."""
    print(append_task_change_log(workspace, task_id, entry, keep_recent=keep_recent))


@artifact_app.command("archive-task")
def artifact_archive_task_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
    reason: str = typer.Option(""),
):
    """Archive one task artifact space manually."""
    print(archive_task_space(workspace, task_id, reason=reason))


@artifact_app.command("update-task-status")
def artifact_update_task_status_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
    status: str = typer.Option(...),
):
    """Update one task space status: draft/active/blocked/done/archived."""
    print(update_task_status(workspace, task_id, status))


@artifact_app.command("auto-archive-tasks")
def artifact_auto_archive_tasks_cmd(
    workspace: str = typer.Option(...),
    retention_days: int = typer.Option(30),
):
    """Auto-archive stale task artifact spaces by retention days."""
    print(auto_archive_task_spaces(workspace, retention_days=retention_days))


@artifact_app.command("touch-task-activity")
def artifact_touch_task_activity_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
    source: str = typer.Option(..., help="Caller identifier, e.g. sync-sniff, sync-case, mcp."),
):
    """Record last activity source for a task space."""
    print(touch_task_activity(workspace, task_id, source))


@app.command("serve-http")
def serve_http_cmd(
    workspace: Optional[str] = typer.Option(None, help="Default workspace.yaml for workspace routes."),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765),
):
    """Serve a lightweight local HTTP bridge for workspace and group queries."""
    print({"http": "starting", "host": host, "port": port, "workspace": workspace})
    serve_http(workspace, host=host, port=port)


def _parse_event_payload(payload: str):
    try:
        import json

        value = json.loads(payload)
        return value if isinstance(value, dict) else {"value": value}
    except Exception:
        return {"text": payload}

if __name__ == "__main__":
    app()
