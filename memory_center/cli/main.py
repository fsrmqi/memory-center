from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich import print

from memory_center.core.config import load_workspace_config, write_default_workspace
from memory_center.core.exporters import export_mermaid
from memory_center.core.indexer import reindex_workspace
from memory_center.core.instructions import write_agent_instructions
from memory_center.core.orchestrator import (
    group_query,
    group_status,
    memory_context,
    memory_contracts,
    memory_detect_changes,
    memory_impact,
    memory_query,
    workspace_check_contract,
    workspace_check_rules,
    workspace_sniff,
    workspace_status,
    workspace_trace,
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
app.add_typer(registry_app, name="registry")
app.add_typer(group_app, name="group")


@app.command()
def init(workspace_root: str = typer.Option(...), name: str = typer.Option("dev-workspace")):
    """Initialize a .memory-center workspace under a multi-project root."""
    workspace_file = write_default_workspace(workspace_root, name)
    store = WorkspaceStore(workspace_file)
    ensure_default_rules(store)
    write_agent_instructions(store, workspace_root)
    print(f"[green]Initialized:[/green] {workspace_file}")
    print("Edit workspace.yaml services, then run: memory-center reindex --workspace <workspace.yaml>")


@app.command()
def reindex(workspace: str = typer.Option(...)):
    """Rebuild file, symbol, API, Feign, MQ, config and topology indexes."""
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    counts = reindex_workspace(config, store)
    ensure_default_rules(store)
    write_agent_instructions(store, config.root_path)
    print({"reindexed": True, "counts": counts})


@app.command()
def status(workspace: str = typer.Option(...)):
    """Print workspace index and memory status."""
    print(workspace_status(workspace))


@app.command()
def sniff(workspace: str = typer.Option(...), intent: str = typer.Option(...), limit: int = typer.Option(12)):
    """Retrieve workspace context for a coding task intent."""
    print(workspace_sniff(workspace, intent, limit))


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


@app.command("generate-wiki")
def generate_wiki_cmd(workspace: str = typer.Option(...), output: Optional[str] = typer.Option(None)):
    """Generate bilingual Markdown architecture wiki from indexes and memory."""
    print(generate_wiki(workspace, output))


@app.command("generate-skills")
def generate_skills_cmd(workspace: str = typer.Option(...), output: Optional[str] = typer.Option(None)):
    """Generate Claude/agent skills from historical task memory."""
    print(generate_skills(workspace, output))


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


@app.command("serve-http")
def serve_http_cmd(
    workspace: Optional[str] = typer.Option(None, help="Default workspace.yaml for workspace routes."),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765),
):
    """Serve a lightweight local HTTP bridge for workspace and group queries."""
    print({"http": "starting", "host": host, "port": port, "workspace": workspace})
    serve_http(workspace, host=host, port=port)

if __name__ == "__main__":
    app()
