from __future__ import annotations

# Typer evaluates command annotations at runtime in environments that may still
# use Python 3.9, so keep CLI option annotations on typing.List/Optional.
# ruff: noqa: UP006,UP035,UP045
import json
import pprint
from pathlib import Path
from typing import List, Optional

import typer
from rich import print

from memory_center import __version__
from memory_center.core.artifacts import (
    append_change_log,
    append_task_change_log,
    archive_task_space,
    artifact_context,
    artifact_outline,
    auto_archive_task_spaces,
    compact_change_log,
    create_task_space,
    ensure_default_artifacts,
    get_artifact,
    get_task_artifact,
    list_artifacts,
    list_task_spaces,
    resolve_task_space,
    task_space_health,
    task_space_repair_execute,
    task_space_repair_plan,
    task_spaces_health,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
    update_task_status,
)
from memory_center.core.config import (
    add_workspace_service,
    load_workspace_config,
    remove_workspace_service,
    write_default_workspace,
)
from memory_center.core.dispatch import CommandRegistry
from memory_center.core.errors import normalize_exception
from memory_center.core.exporters import (
    export_mermaid,
    export_workspace_dashboard_html,
    export_workspace_dashboard_markdown,
)
from memory_center.core.indexer import reindex_workspace
from memory_center.core.instructions import write_agent_instructions
from memory_center.core.orchestrator import (
    group_impact,
    group_query,
    group_status,
    memory_backend_query,
    memory_callees,
    memory_callers,
    memory_context,
    memory_contracts,
    memory_detect_changes,
    memory_eval_agent_guidance,
    memory_eval_agent_guidance_adoption,
    memory_eval_agent_guidance_adoption_trend,
    memory_eval_agent_guidance_replay,
    memory_eval_agent_guidance_replay_trend,
    memory_eval_agent_guidance_trend,
    memory_eval_context_weight,
    memory_eval_handoff,
    memory_eval_index_freshness,
    memory_eval_regression_suite,
    memory_eval_resume,
    memory_eval_token_gain,
    memory_eval_tool_adoption,
    memory_eval_walkthrough_quality,
    memory_eval_workflow_orchestration,
    memory_eval_write_quality,
    memory_execute_write,
    memory_export_walkthrough_artifact,
    memory_impact,
    memory_method_walkthrough,
    memory_plan_change,
    memory_plan_write,
    memory_query_hybrid,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_tool_usage_report,
    memory_verify_checklist,
    memory_walkthrough_health,
    memory_write_judge,
    workspace_check_contract,
    workspace_check_rules,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_end_session,
    workspace_handoff_history,
    workspace_handoff_packet,
    workspace_log_session_event,
    workspace_lookup_hint,
    workspace_model_profile,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_recent_sessions,
    workspace_record_agent_guidance,
    workspace_record_case,
    workspace_record_close_feedback,
    workspace_replay_write_chain,
    workspace_resume_context,
    workspace_resume_packet,
    workspace_session_summary,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_suggest_case,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_task_resume_check,
    workspace_trace,
    workspace_unresolved_items,
    workspace_write_receipts,
)
from memory_center.core.registry import add_to_group, create_group, list_workspaces, register_workspace
from memory_center.core.rules import ensure_default_rules
from memory_center.core.store import WorkspaceStore
from memory_center.core.validators import doctor as run_doctor
from memory_center.core.wiki import generate_skills, generate_wiki
from memory_center.hooks.adapters.claude_code import generate_claude_code_hooks, write_claude_code_settings
from memory_center.hooks.adapters.codex import generate_codex_scripts
from memory_center.hooks.adapters.cursor import generate_cursor_rules
from memory_center.hooks.runner import run_hook_cli
from memory_center.hooks.spec import ensure_default_hooks, load_hooks_config
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

OPTIONAL_PROJECT_FILTER = typer.Option(None, help="Only rebuild indexes for these projects.")
OPTIONAL_PATH_FILTER = typer.Option(None, help="Only rebuild indexes for these logical or absolute paths.")
OPTIONAL_PROJECTS = typer.Option(None)
OPTIONAL_FILES = typer.Option(None)
REQUIRED_REF_IDS = typer.Option(...)
REQUIRED_PROJECTS = typer.Option(...)
REQUIRED_FILES = typer.Option(...)
OPTIONAL_RISK_POINTS = typer.Option(None)
OPTIONAL_VERIFIED_BY = typer.Option(None)
OPTIONAL_TAGS = typer.Option(None)


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
def init(
    workspace_root: str = typer.Option(...),
    name: str = typer.Option("dev-workspace"),
    detect: bool = typer.Option(
        True,
        "--detect/--no-detect",
        help="Auto-detect service types under workspace-root (default). "
        "Pass --no-detect to write the legacy Spring template "
        "(gateway/common-api/common-core).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be written without creating any file.",
    ),
):
    """Initialize a .memory-center workspace under a multi-project root."""
    workspace_file, report = write_default_workspace(
        workspace_root, name, detect=detect, dry_run=dry_run
    )
    services = report.get("services", [])

    if dry_run:
        print(f"[yellow]Dry run:[/yellow] {workspace_file}")
        print(f"  detection_mode={report['detection_mode']} "
              f"service_count={report['service_count']}")
        for svc in services:
            tags = svc.get("tags") or []
            tag_str = f" tags={tags}" if tags else ""
            print(f"    - {svc['name']:<20} type={svc['type']} path={svc['path']}{tag_str}")
        print("Nothing written. Re-run without --dry-run to create the file.")
        return

    if report.get("already_exists") and not report.get("written"):
        print(f"[yellow]Workspace already exists:[/yellow] {workspace_file}")
        print("Leaving the existing file untouched. Edit it manually if needed.")
        return

    store = WorkspaceStore(workspace_file)
    ensure_default_rules(store)
    ensure_default_hooks(store)
    ensure_default_artifacts(workspace_file)
    write_agent_instructions(store, workspace_root)
    print(f"[green]Initialized:[/green] {workspace_file}")
    if detect:
        if services:
            print(f"  Detected {len(services)} service(s):")
            for svc in services:
                print(f"    - {svc['name']:<20} type={svc['type']} path={svc['path']}")
        else:
            print("  [yellow]No recognizable services detected.[/yellow] "
                  "Edit workspace.yaml and add entries by hand.")
    print("Edit workspace.yaml services, then run: memory-center reindex --workspace <workspace.yaml>")


@app.command()
def reindex(
    workspace: str = typer.Option(...),
    project: Optional[List[str]] = OPTIONAL_PROJECT_FILTER,
    path: Optional[List[str]] = OPTIONAL_PATH_FILTER,
    changed_only: bool = typer.Option(False, help="Use changed files from memory-detect-changes as reindex scope."),
    scope: str = typer.Option("staged", help="When --changed-only is set: staged|head|all"),
    parallel: bool = typer.Option(True, "--parallel/--no-parallel", help="Parse Java files in parallel during reindex."),
):
    """Rebuild file, symbol, API, Feign, MQ, config and topology indexes."""
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    selected_paths = list(path or [])
    if changed_only:
        # "all" scope means both staged and unstaged changes; use "all" directly
        # since memory_detect_changes handles "all" to combine both
        change_scope = scope
        changed = memory_detect_changes(workspace, change_scope)
        selected_paths.extend(changed.get("changed_files", []))
        selected_paths.extend(changed.get("deleted_files", []))
    counts = reindex_workspace(config, store, projects=project, paths=selected_paths, parallel=parallel)
    ensure_default_rules(store)
    ensure_default_hooks(store)
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


def _dispatch_walkthrough_cli(action: str, **kwargs):
    registry = CommandRegistry(label="walkthrough CLI command").register_many({
        "method_walkthrough": lambda: memory_method_walkthrough(
            kwargs["workspace"],
            kwargs["symbol"],
            depth=kwargs.get("depth", 4),
            limit=kwargs.get("limit", 80),
            project=kwargs.get("project", ""),
            view=kwargs.get("view", "full"),
            budget=kwargs.get("budget", "medium"),
            report_level=kwargs.get("report_level", "standard"),
        ),
        "walkthrough_health": lambda: memory_walkthrough_health(
            kwargs["workspace"],
            symbol=kwargs.get("symbol", ""),
            project=kwargs.get("project", ""),
            report_level=kwargs.get("report_level", "standard"),
        ),
        "walkthrough_export": lambda: memory_export_walkthrough_artifact(
            kwargs["workspace"],
            symbol=kwargs["symbol"],
            project=kwargs.get("project", ""),
            report_level=kwargs.get("report_level", "deep"),
            title=kwargs.get("title", ""),
        ),
        "eval_walkthrough_quality": lambda: memory_eval_walkthrough_quality(
            kwargs["workspace"],
            symbol=kwargs["symbol"],
            project=kwargs.get("project", ""),
            report_level=kwargs.get("report_level", "standard"),
        ),
    })
    return registry.dispatch(action)


@app.command("check-contract")
def check_contract(workspace: str = typer.Option(...), contract_file: str = typer.Option(...), change_type: str = typer.Option("modify")):
    """Check impact before modifying shared DTO, Feign or MQ message contracts."""
    print(workspace_check_contract(workspace, contract_file, change_type))


@app.command("check-rules")
def check_rules(
    workspace: str = typer.Option(...),
    change_type: str = typer.Option("general"),
    project: Optional[List[str]] = OPTIONAL_PROJECTS,
    file: Optional[List[str]] = OPTIONAL_FILES,
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
def query_cmd(
    workspace: str = typer.Option(...),
    text: str = typer.Option(...),
    limit: int = typer.Option(20),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    session_id: str = typer.Option("", help="Record returned agent_next_steps into this session."),
    vector: bool = typer.Option(False, "--vector/--no-vector", help="Enable ANN vector retrieval when dense embeddings are available."),
    vector_weight: float = typer.Option(0.15, help="Fusion weight for vector retrieval when --vector is enabled."),
):
    """Graph-aware query across services, files, symbols, contracts and memory."""
    result = memory_query_hybrid(
        workspace,
        text,
        limit,
        project=project,
        enable_vector=vector,
        vector_weight=vector_weight,
    )
    if session_id.strip():
        workspace_record_agent_guidance(workspace, session_id, query=text, mode="query", source="cli.query", payload=result)
    typer.echo(
        pprint.pformat(
            result,
            width=240,
            sort_dicts=False,
        ),
    )


@app.command("search-code")
def search_code_cmd(
    workspace: str = typer.Option(...),
    text: str = typer.Option(...),
    scope: str = typer.Option(""),
    limit: int = typer.Option(20),
    project: str = typer.Option("", help="Filter by project name."),
):
    """Keyword search over indexed files/symbol hints."""
    print(memory_search_code(workspace, text, scope=scope, limit=limit, project=project))


@app.command("symbol")
def symbol_cmd(
    workspace: str = typer.Option(...),
    name: str = typer.Option(...),
    limit: int = typer.Option(10),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    view: str = typer.Option("full", help="full|compact"),
    budget: str = typer.Option("medium", help="small|medium|large"),
):
    """Resolve one symbol and return best match candidates."""
    print(memory_symbol(workspace, name, limit=limit, project=project, view=view, budget=budget))


@app.command("callers")
def callers_cmd(
    workspace: str = typer.Option(...),
    symbol: str = typer.Option(...),
    depth: int = typer.Option(2),
    limit: int = typer.Option(80),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    view: str = typer.Option("full", help="full|compact"),
    budget: str = typer.Option("medium", help="small|medium|large"),
    min_confidence: float = typer.Option(0.85, help="Minimum edge confidence; use 0 to include unresolved calls."),
):
    """Find upstream callers for one symbol."""
    print(memory_callers(workspace, symbol, depth=depth, limit=limit, project=project, view=view, budget=budget, min_confidence=min_confidence))


@app.command("callees")
def callees_cmd(
    workspace: str = typer.Option(...),
    symbol: str = typer.Option(...),
    depth: int = typer.Option(2),
    limit: int = typer.Option(80),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    view: str = typer.Option("full", help="full|compact"),
    budget: str = typer.Option("medium", help="small|medium|large"),
    min_confidence: float = typer.Option(0.85, help="Minimum edge confidence; use 0 to include unresolved calls."),
):
    """Find downstream callees for one symbol."""
    print(memory_callees(workspace, symbol, depth=depth, limit=limit, project=project, view=view, budget=budget, min_confidence=min_confidence))


@app.command("method-walkthrough")
def method_walkthrough_cmd(
    workspace: str = typer.Option(...),
    symbol: str = typer.Option(..., help="Method symbol, e.g. com.example.ArticleService#listByDto"),
    depth: int = typer.Option(4),
    limit: int = typer.Option(80),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    view: str = typer.Option("full", help="full|compact"),
    budget: str = typer.Option("medium", help="small|medium|large"),
    report_level: str = typer.Option("standard", help="summary|standard|deep|risk-focused"),
):
    """Explain indexed method steps, downstream calls, and Feign continuations."""
    print(_dispatch_walkthrough_cli(
        "method_walkthrough",
        workspace=workspace,
        symbol=symbol,
        depth=depth,
        limit=limit,
        project=project,
        view=view,
        budget=budget,
        report_level=report_level,
    ))


@app.command("walkthrough-health")
def walkthrough_health_cmd(
    workspace: str = typer.Option(...),
    symbol: str = typer.Option("", help="Optional Method symbol for sample walkthrough validation."),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    report_level: str = typer.Option("standard", help="summary|standard|deep|risk-focused"),
):
    """Check method walkthrough readiness and output contract."""
    print(_dispatch_walkthrough_cli(
        "walkthrough_health",
        workspace=workspace,
        symbol=symbol,
        project=project,
        report_level=report_level,
    ))


@app.command("walkthrough-export")
def walkthrough_export_cmd(
    workspace: str = typer.Option(...),
    symbol: str = typer.Option(..., help="Method symbol, e.g. com.example.ArticleService#listByDto"),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    report_level: str = typer.Option("deep", help="summary|standard|deep|risk-focused"),
    title: str = typer.Option("", help="Optional artifact title."),
):
    """Export a method walkthrough Markdown artifact under artifacts/walkthroughs."""
    print(_dispatch_walkthrough_cli(
        "walkthrough_export",
        workspace=workspace,
        symbol=symbol,
        project=project,
        report_level=report_level,
        title=title,
    ))


@app.command("walkthrough-eval")
def walkthrough_eval_cmd(
    workspace: str = typer.Option(...),
    symbol: str = typer.Option(..., help="Method symbol, e.g. com.example.ArticleService#listByDto"),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    report_level: str = typer.Option("standard", help="summary|standard|deep|risk-focused"),
):
    """Evaluate whether a method walkthrough result is agent-ready."""
    print(_dispatch_walkthrough_cli(
        "eval_walkthrough_quality",
        workspace=workspace,
        symbol=symbol,
        project=project,
        report_level=report_level,
    ))


@app.command("context")
def context_cmd(
    workspace: str = typer.Option(...),
    name: str = typer.Option(...),
    max_depth: int = typer.Option(2),
    project: str = typer.Option("", help="Filter by project name for disambiguation."),
    view: str = typer.Option("full", help="full|compact"),
    budget: str = typer.Option("medium", help="small|medium|large"),
):
    """Return 360-degree context for a symbol, endpoint, topic, service or file."""
    print(memory_context(workspace, name, max_depth, project=project, view=view, budget=budget))


@app.command("impact")
def impact_cmd(
    workspace: str = typer.Option(...),
    target: str = typer.Option(...),
    direction: str = typer.Option("upstream"),
    max_depth: int = typer.Option(3),
    project: str = typer.Option("", help="Filter by project name for local evidence while keeping declaration anchor."),
    view: str = typer.Option("full", help="full|compact"),
    budget: str = typer.Option("medium", help="small|medium|large"),
):
    """Analyze upstream/downstream impact for a changed symbol or contract."""
    print(memory_impact(workspace, target, direction, max_depth, project=project, view=view, budget=budget))


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


@app.command("eval-agent-guidance")
def eval_agent_guidance_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option(""),
    limit: int = typer.Option(20),
):
    """Evaluate whether lookup output gives bounded agent next steps."""
    print(memory_eval_agent_guidance(workspace, intent=intent, limit=limit))


@app.command("eval-agent-guidance-trend")
def eval_agent_guidance_trend_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option(""),
    limit: int = typer.Option(20),
):
    """Evaluate agent next-step guidance and record one trend point."""
    print(memory_eval_agent_guidance_trend(workspace, intent=intent, limit=limit))


@app.command("eval-agent-guidance-adoption")
def eval_agent_guidance_adoption_cmd(
    workspace: str = typer.Option(...),
    session_id: str = typer.Option(""),
    limit: int = typer.Option(200),
):
    """Evaluate whether recorded agent guidance was followed by later tool calls."""
    print(memory_eval_agent_guidance_adoption(workspace, session_id=session_id, limit=limit))


@app.command("eval-agent-guidance-adoption-trend")
def eval_agent_guidance_adoption_trend_cmd(
    workspace: str = typer.Option(...),
    session_id: str = typer.Option(""),
    limit: int = typer.Option(200),
):
    """Evaluate agent guidance adoption and record one trend point."""
    print(memory_eval_agent_guidance_adoption_trend(workspace, session_id=session_id, limit=limit))


@app.command("eval-agent-guidance-replay")
def eval_agent_guidance_replay_cmd(
    workspace: str = typer.Option(...),
    session_id: str = typer.Option(""),
    limit: int = typer.Option(200),
):
    """Replay agent guidance events and classify missed, bypassed, and unobservable recommendations."""
    print(memory_eval_agent_guidance_replay(workspace, session_id=session_id, limit=limit))


@app.command("eval-agent-guidance-replay-trend")
def eval_agent_guidance_replay_trend_cmd(
    workspace: str = typer.Option(...),
    session_id: str = typer.Option(""),
    limit: int = typer.Option(200),
):
    """Replay agent guidance events and record one trend point."""
    print(memory_eval_agent_guidance_replay_trend(workspace, session_id=session_id, limit=limit))


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


@app.command("eval-token-gain")
def eval_token_gain_cmd(
    workspace: str = typer.Option(...),
    tool_name: str = typer.Option("", help="Filter by tool name."),
    budget: str = typer.Option("", help="Filter by budget."),
    model: str = typer.Option("", help="Filter by model."),
    limit: int = typer.Option(200),
):
    """Evaluate token savings from compact operations (similar to rtk gain)."""
    print(memory_eval_token_gain(workspace, tool_name=tool_name, budget=budget, model=model, limit=limit))


@app.command("eval-token-benchmark")
def eval_token_benchmark_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option("token benchmark"),
    limit: int = typer.Option(8),
):
    """Run token benchmark: measure all 7 high-freq returns at small/medium/large budgets."""
    from memory_center.core.orchestrator import memory_eval_token_benchmark
    print(memory_eval_token_benchmark(workspace, intent=intent, limit=limit))


@app.command("eval-parser-benchmark")
def eval_parser_benchmark_cmd(
    workspace: str = typer.Option(...),
    limit: int = typer.Option(200, help="Maximum number of Java files to compare."),
    max_findings: int = typer.Option(20, help="Maximum number of regression/improvement findings to return."),
):
    """Compare regex and tree-sitter parser outputs on a real workspace."""
    from memory_center.core.orchestrator import memory_eval_parser_benchmark

    print(json.dumps(memory_eval_parser_benchmark(workspace, limit=limit, max_findings=max_findings), ensure_ascii=False, indent=2, default=str))


@app.command("parser-status")
def parser_status_cmd():
    """Show tree-sitter Java activation status and install hints."""
    from memory_center.core.parser_precision import tree_sitter_activation_status

    print(json.dumps(tree_sitter_activation_status(), ensure_ascii=False, indent=2, default=str))


@app.command("bench-profile")
def bench_profile_cmd(
    workspace: str = typer.Option(..., help="Workspace yaml file."),
    top: int = typer.Option(50, help="How many top functions to print."),
    sort_by: str = typer.Option(
        "cumulative",
        help="pstats sort key: cumulative | tottime | calls | pcalls.",
    ),
    by_module: bool = typer.Option(
        False,
        "--by-module/--by-function",
        help="Also print a module-level rollup (helpful for P1-0 diagnostics).",
    ),
    label: str = typer.Option("", help="Free-form tag appended to the .prof filename."),
):
    """Profile a full reindex with cProfile and print the hot functions.

    The raw ``.prof`` file is saved under
    ``$workspace/.memory-center/perf-profiles/`` so it can be re-analysed
    with ``snakeviz`` / ``pyprof2calltree``. Use this command before
    designing a perf optimisation so the proposed work targets the
    actual dominant cost (see ``docs/benchmarks/`` for the original P0
    motivation).
    """
    from memory_center.core.perf import aggregate_by_module, profile_reindex

    workspace_path = Path(workspace).expanduser().resolve()
    result = profile_reindex(workspace_path, top_n=top, sort_by=sort_by, label=label)
    print(f"[green]reindex elapsed:[/green] {result.elapsed_s:.2f}s")
    print(f"[green]pstats:[/green] {result.pstats_path}")
    print(f"  total_calls={result.total_calls} primitive_calls={result.primitive_calls}")
    print(f"\n=== top {top} by {sort_by} ===")
    print(result.top_summary)
    if by_module:
        print(f"\n=== top {min(20, top)} by module (cumulative time) ===")
        rows = aggregate_by_module(result.pstats_path, limit=min(20, top))
        for row in rows:
            print(
                f"{row['cumulative_s']:>8.2f}s  "
                f"tot={row['tottime_s']:>7.2f}s  "
                f"calls={row['calls']:>8}  "
                f"{row['module']}"
            )


@app.command("eval-golden")
def eval_golden_cmd(
    workspace: str = typer.Option(..., help="Workspace yaml file."),
    cases: str = typer.Option(..., help="Golden cases yaml file."),
    baseline: str = typer.Option("", help="Optional Golden performance baseline JSON file."),
):
    """Run Golden Benchmark against a workspace and a portable cases file."""
    from memory_center.core import benchmark as benchmark_module

    print(json.dumps(benchmark_module.run_golden_suite(workspace, cases, performance_baseline=baseline or None), ensure_ascii=False, indent=2, default=str))


@app.command("eval-java-call-resolution")
def eval_java_call_resolution_cmd(
    workspace: str = typer.Option(..., help="Workspace yaml file."),
    cases: str = typer.Option(..., help="Java call resolution cases yaml file."),
    min_recall: float = typer.Option(0.90, help="Minimum expected-edge recall."),
    min_confidence_rate: float = typer.Option(0.85, help="Minimum high-confidence expected-edge rate."),
    max_unresolved_rate: float = typer.Option(0.10, help="Maximum unresolved case rate."),
    fail_on_unexpected_high_confidence: bool = typer.Option(False, help="Fail on non-expected high-confidence CALLS_METHOD edges."),
    fail_on_forbidden_high_confidence: bool = typer.Option(False, help="Fail on high-confidence CALLS_METHOD edges listed in forbidden_targets."),
):
    """Run Java CALLS_METHOD resolution gate against logical real-workspace cases."""
    from memory_center.core.orchestrator import memory_eval_java_call_resolution

    result = memory_eval_java_call_resolution(
        workspace,
        cases,
        min_recall=min_recall,
        min_confidence_rate=min_confidence_rate,
        max_unresolved_rate=max_unresolved_rate,
        fail_on_unexpected_high_confidence=fail_on_unexpected_high_confidence,
        fail_on_forbidden_high_confidence=fail_on_forbidden_high_confidence,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("eval-token-benchmark-save")
def eval_token_benchmark_save_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option("token benchmark"),
    limit: int = typer.Option(8),
):
    """Save current token benchmark as regression baseline."""
    from memory_center.core.orchestrator import memory_eval_token_benchmark_save
    print(memory_eval_token_benchmark_save(workspace, intent=intent, limit=limit))


@app.command("eval-token-benchmark-compare")
def eval_token_benchmark_compare_cmd(
    workspace: str = typer.Option(...),
    intent: str = typer.Option("token benchmark"),
    limit: int = typer.Option(8),
    regression_threshold: int = typer.Option(15),
):
    """Compare token benchmark against stored baseline. Exit 1 on high-severity regression."""
    from memory_center.core.orchestrator import memory_eval_token_benchmark_compare
    result = memory_eval_token_benchmark_compare(workspace, intent=intent, limit=limit, regression_threshold=regression_threshold)
    print(result)
    regressions = result.get("regressions", [])
    if regressions:
        raise typer.Exit(code=1)


@app.command("eval-token-benchmark-trend")
def eval_token_benchmark_trend_cmd(
    workspace: str = typer.Option(...),
    function_name: str = typer.Option("", help="Filter by function name."),
):
    """Show benchmark trend data, regressions, and health score."""
    from memory_center.core.benchmark.trending import generate_benchmark_report
    print(generate_benchmark_report(workspace, function_name=function_name))


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
    from memory_center.core.templates import auto_select_action, get_constraint_template
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
    ref_id: List[str] = REQUIRED_REF_IDS,
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
    view: str = typer.Option("full", help="compact|full"),
):
    """Show recent evidence from task receipts and session events."""
    print(workspace_recent_evidence(workspace, task_id=task_id, session_id=session_id, limit=limit, budget=budget, view=view))


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
            "recent_evidence": workspace_recent_evidence(workspace, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
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
    payload = workspace_task_resume_check(workspace, task_id=task_id, session_id=session_id, intent=intent, limit=limit, budget=budget)
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
            "handoff_packet": workspace_handoff_packet(workspace, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "recent_evidence": workspace_recent_evidence(workspace, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
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
):
    """Close one task workflow: end session, sync case, optionally record case."""
    ended = workspace_end_session(workspace, session_id, outcome=outcome, verified_by=verified_by)
    synced = workspace_sync_case_to_artifacts(workspace, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)
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


@app.command("audit")
def audit_cmd(
    workspace: str = typer.Option(...),
    work_package: str = typer.Option("", help="Work package to audit."),
):
    """Run completion audit for documentation, tests, and implementation."""
    from memory_center.core.audit.completion import run_completion_audit
    print(run_completion_audit(workspace, work_package=work_package))


@app.command("drill-ref")
def drill_ref_cmd(
    workspace: str = typer.Option(...),
    ref_id: str = typer.Option(..., help="Ref ID to expand (e.g. ev:session:type:0)."),
):
    """Expand a ref with progressive disclosure."""
    from memory_center.core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace) as nav:
        print(nav.expand_ref(ref_id))


@app.command("drill-timeline")
def drill_timeline_cmd(
    workspace: str = typer.Option(...),
    session_id: str = typer.Option("", help="Filter by session ID."),
    task_id: str = typer.Option("", help="Filter by task ID."),
    limit: int = typer.Option(50),
):
    """Drill into timeline with context preservation."""
    from memory_center.core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace) as nav:
        print(nav.drill_timeline(session_id=session_id, task_id=task_id, limit=limit))


@app.command("drill-task")
def drill_task_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(..., help="Task ID to drill into."),
):
    """Drill into a task's full context."""
    from memory_center.core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace) as nav:
        print(nav.drill_task(task_id))


@app.command("backend-consistency")
def backend_consistency_cmd(
    workspace: str = typer.Option(...),
):
    """Check consistency between JSONL files and SQLite backend."""
    from memory_center.core.backend.query import UnifiedBackendQuery
    from memory_center.core.store import WorkspaceStore
    store = WorkspaceStore(workspace)
    with UnifiedBackendQuery(store.memory_db_path) as backend:
        print(backend.check_consistency(store.base_dir))


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
            "regression_suite": memory_eval_regression_suite(workspace, intent=intent, target_model=target_model, limit=limit),
            "benchmark_trend": generate_benchmark_report(workspace),
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
    tag: Optional[List[str]] = OPTIONAL_TAGS,
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
    tag: Optional[List[str]] = OPTIONAL_TAGS,
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


@artifact_app.command("health-task")
def artifact_health_task_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
):
    """Check one task-space health and repair suggestions."""
    print(task_space_health(workspace, task_id))


@artifact_app.command("health-tasks")
def artifact_health_tasks_cmd(
    workspace: str = typer.Option(...),
    include_archived: bool = typer.Option(False),
    limit: int = typer.Option(50),
):
    """Check task-space health across the workspace."""
    print(task_spaces_health(workspace, include_archived=include_archived, limit=limit))


@artifact_app.command("repair-plan-task")
def artifact_repair_plan_task_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
):
    """Build a read-only repair plan for one task-space health report."""
    print(task_space_repair_plan(workspace, task_id))


@artifact_app.command("repair-task")
def artifact_repair_task_cmd(
    workspace: str = typer.Option(...),
    task_id: str = typer.Option(...),
    apply: bool = typer.Option(False, "--apply/--dry-run", help="Apply supported low-risk repairs. Default is dry-run."),
    intent: str = typer.Option("", help="Required when applying current_summary repair through sync-sniff-artifacts."),
):
    """Dry-run or apply supported low-risk task-space repairs."""
    print(task_space_repair_execute(workspace, task_id, apply=apply, intent=intent))


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


@app.command("run-hook")
def run_hook_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    hook: str = typer.Option(..., help="Hook event name: session_start, pre_edit, session_stop, user_prompt_submit"),
):
    """Execute a hook defined in hooks.yaml. Host-agnostic lifecycle event runner.

    Reads stdin JSON from the host, resolves parameters, dispatches to
    the appropriate Memory Center facade, and outputs a structured result.
    Process exit code: 0=allow, 2=block (guard mode), 1=error.
    """
    exit_code = run_hook_cli(workspace, hook)
    raise typer.Exit(code=exit_code)


@app.command("generate-hooks")
def generate_hooks_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    host: str = typer.Option("claude-code", help="Target host: claude-code, codex, cursor"),
    output: str = typer.Option("", help="Output path. Default: auto-detect based on host."),
):
    """Generate host-specific hook configuration from hooks.yaml.

    For claude-code: writes .claude/settings.local.json with hooks section.
    For codex: generates shell wrapper scripts in .codex-hooks/.
    For cursor: generates .cursorrules additions.
    """
    config = load_hooks_config(workspace)
    if host == "claude-code":
        result = write_claude_code_settings(workspace, output_path=output or None, hooks_config=config)
        print({"host": "claude-code", "output_path": str(result), "hooks": generate_claude_code_hooks(workspace, config)})
    elif host == "codex":
        scripts = generate_codex_scripts(workspace, output_dir=output or None, hooks_config=config)
        print({"host": "codex", "generated_scripts": [str(s) for s in scripts]})
    elif host == "cursor":
        rules_path = generate_cursor_rules(workspace, output_path=output or None, hooks_config=config)
        print({"host": "cursor", "output_path": str(rules_path)})
    else:
        print({"error": f"Unknown host: {host}. Valid hosts: claude-code, codex, cursor"})
        raise typer.Exit(code=1)



# ===================== Next-Phase CLI Commands (ECC/UA/CG) =====================

@app.command("verification-loop")
def verification_loop_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    task_type: str = typer.Option("general", help="Task type: code_change, feature, bugfix, general"),
    task_id: str = typer.Option("default", help="Task identifier"),
):
    """Generate verification checklist for a task."""
    from memory_center.core.verification.loop import VerificationLoop
    vl = VerificationLoop(workspace)
    analysis = {"task_type": task_type, "workspace": workspace}
    checklist = vl.generate_checklist(analysis)
    status = vl.get_status(task_id)
    print(json.dumps({"checklist": checklist, "status": status}, indent=2, default=str))


@app.command("pattern-promotion")
def pattern_promotion_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    action: str = typer.Option("list", help="Action: propose, list, promote"),
    text: str = typer.Option("", help="Pattern text for propose/promote"),
):
    """Manage pattern promotion pipeline."""
    from memory_center.core.verification.pattern_promotion import PatternPromotion
    pp = PatternPromotion(workspace)
    if action == "propose":
        result = pp.propose({"rule_text": text, "source": "cli"})
    elif action == "list":
        result = {"proposals": pp.list_proposals()}
    elif action == "promote":
        result = pp.promote(text)
    else:
        result = {"error": f"Unknown action: {action}"}
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


@app.command("heuristics")
def heuristics_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    action: str = typer.Option("query", help="Action: query, record, feedback, explain"),
    text: str = typer.Option("", help="Query text or JSON record data"),
):
    """Query or record learned heuristics."""
    import json as _json

    from memory_center.core.verification.heuristics import HeuristicsRegister
    hr = HeuristicsRegister(workspace)
    if action == "query":
        result = {"heuristics": hr.query(text)}
    elif action in {"record", "feedback", "explain"}:
        try:
            data = _json.loads(text) if text else {}
        except _json.JSONDecodeError:
            data = {"pattern": text}
        if action == "record":
            entry = hr.record(data)
            result = {"status": "recorded", "entry": entry}
        elif action == "explain":
            result = hr.explain(
                candidate_type=str(data.get("candidate_type", "") or ""),
                target=str(data.get("target", "") or ""),
                category=str(data.get("category", "") or "candidate-path"),
                heuristic_id=str(data.get("heuristic_id", "") or ""),
                pattern=str(data.get("pattern", "") or ""),
                limit=int(data.get("limit", 10) or 10),
            )
        else:
            feedback = hr.record_candidate_path_feedback(
                candidate_type=str(data.get("candidate_type", "") or ""),
                target=str(data.get("target", "") or ""),
                outcome=str(data.get("outcome", "") or ""),
                evidence=data.get("evidence") or [],
                source=str(data.get("source", "") or "cli"),
                task_id=str(data.get("task_id", "") or ""),
                session_id=str(data.get("session_id", "") or ""),
                weight_before=data.get("weight_before"),
                weight_delta=data.get("weight_delta"),
                why=str(data.get("why", "") or ""),
                next_action=str(data.get("next_action", "") or ""),
                verification_cost=str(data.get("verification_cost", "") or ""),
                category=str(data.get("category", "") or "candidate-path"),
                pattern=str(data.get("pattern", "") or ""),
                trigger=str(data.get("trigger", "") or ""),
            )
            result = {"status": "recorded", "feedback": feedback}
    else:
        result = {"error": f"Unknown action: {action}"}
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


@app.command("workflow-profile")
def workflow_profile_cmd(
    profile: str = typer.Option("quick-fix", help="Profile name: quick-fix, contract-change, long-task, architecture"),
):
    """Get a workflow protocol profile."""
    import dataclasses as _dc

    from memory_center.core.verification.workflow_profiles import get_workflow_profile
    result = get_workflow_profile(profile)
    if _dc.is_dataclass(result) and not isinstance(result, type):
        result = _dc.asdict(result)
    print(json.dumps(result, indent=2, default=str))


@app.command("workflow-recommend")
def workflow_recommend_cmd(
    workspace: str = typer.Option("", help="Optional path to .memory-center/workspace.yaml for learned recommendation"),
    description: str = typer.Option(..., help="Task description to match"),
):
    """Recommend a workflow profile based on task description."""
    from memory_center.core.verification.workflow_profiles import recommend_workflow, recommend_workflow_with_learning
    result = recommend_workflow_with_learning(workspace, description) if workspace else recommend_workflow(description)
    print(json.dumps(result, indent=2, default=str))


@app.command("bundle-export")
def bundle_export_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    agent: str = typer.Option("codex", help="Target agent: codex, claude, cursor"),
    output: str = typer.Option("", help="Output directory"),
):
    """Export agent usage bundle for the specified platform."""
    from memory_center.core.verification.bundle_export import generate_agent_bundle
    result = generate_agent_bundle(workspace, agent=agent)
    print(json.dumps(result, indent=2, default=str))


@app.command("runtime-audit")
def runtime_audit_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    fix: bool = typer.Option(False, help="Write or refresh missing agent MCP bindings before auditing."),
):
    """Audit agent runtime configuration (hooks, MCP, agent profile)."""
    from memory_center.core.audit.runtime import audit_agent_runtime
    result = audit_agent_runtime(workspace, fix=fix)
    typer.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))


@app.command("setup-agent")
def setup_agent_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
):
    """Generate instructions, repair MCP bindings, and audit host-agent readiness."""
    from memory_center.core.audit.runtime import setup_agent_runtime
    result = setup_agent_runtime(workspace)
    typer.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))


@app.command("explanation")
def explanation_cmd(
    text: str = typer.Option(..., help="Content to explain"),
    persona: str = typer.Option("developer", help="Target persona: developer, architect, manager"),
):
    """Generate persona-adapted explanation."""
    from memory_center.core.explanation.schema import Explanation
    exp = Explanation(subject="explanation", summary=text, persona=persona)
    result = exp.adapt_for_persona(persona).to_full()
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


@app.command("business-flow")
def business_flow_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    seed: str = typer.Option(..., help="Seed node ID to extract flows from"),
    max_depth: int = typer.Option(4, help="Maximum traversal depth"),
):
    """Extract business flows from a seed node."""
    from memory_center.core.domain.flow import extract_business_flows_for_workspace
    result = extract_business_flows_for_workspace(workspace, seed, max_depth=max_depth)
    print(json.dumps(result, indent=2, default=str))


@app.command("business-flow-impact")
def business_flow_impact_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    node_id: str = typer.Option(..., help="Node ID to check impact for"),
    max_depth: int = typer.Option(3, help="Maximum depth"),
):
    """Find impacted nodes along business flows."""
    from memory_center.core.domain.flow import business_flow_impact_for_workspace
    result = business_flow_impact_for_workspace(workspace, node_id, max_depth=max_depth)
    print(json.dumps(result, indent=2, default=str))


@app.command("metrics-summary")
def metrics_summary_cmd():
    """Show metrics summary."""
    from memory_center.core.metrics import MetricsCollector
    mc = MetricsCollector()
    print(json.dumps(mc.summary(), indent=2, default=str))


@app.command("regression-alerts")
def regression_alerts_cmd(
    workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    threshold_pct: float = typer.Option(10.0, help="Token regression warning threshold percentage"),
):
    """Check for benchmark regression alerts."""
    from memory_center.core.benchmark.trending import check_regression_alerts
    result = check_regression_alerts(workspace, threshold_pct=threshold_pct)
    print(json.dumps(result, indent=2, default=str))


def main() -> None:
    """Installed CLI entrypoint with a unified runtime error boundary."""
    try:
        app(standalone_mode=False)
    except typer.Exit:
        raise
    except Exception as exc:
        error = normalize_exception(exc)
        typer.echo(error.to_cli_message(), err=True)
        raise SystemExit(error.cli_exit_code) from None


if __name__ == "__main__":
    main()
