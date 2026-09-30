"""Setup 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP035,UP045
import json
from inspect import signature
from typing import List, Optional

import typer

from memory_center.cli.output import print_data as print
from memory_center.core.governance.instructions import write_agent_instructions
from memory_center.core.governance.rules import ensure_default_rules
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.orchestrator import (
    memory_detect_changes,
    memory_query_hybrid,
    workspace_check_contract,
    workspace_check_rules,
    workspace_sniff,
    workspace_status,
)
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.artifacts import ensure_default_artifacts
from memory_center.core.workspace.config import load_workspace_config, write_default_workspace
from memory_center.core.workspace.doctor import doctor as run_doctor
from memory_center.hooks.spec import ensure_default_hooks

from ._options import OPTIONAL_FILES, OPTIONAL_PATH_FILTER, OPTIONAL_PROJECT_FILTER, OPTIONAL_PROJECTS


def register_setup_commands(app: typer.Typer) -> None:
    @app.command()
    def init(
        workspace_root: str = typer.Option(...),
        name: str = typer.Option("dev-workspace"),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Show what would be written without creating any file.",
        ),
    ):
        """Initialize a .memory-center workspace under a multi-project root."""
        workspace_file, report = write_default_workspace(workspace_root, name, dry_run=dry_run)
        services = report.get("services", [])

        if dry_run:
            print(f"[yellow]Dry run:[/yellow] {workspace_file}")
            print(f"  detection_mode={report['detection_mode']} service_count={report['service_count']}")
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
        if services:
            print(f"  Detected {len(services)} service(s):")
            for svc in services:
                print(f"    - {svc['name']:<20} type={svc['type']} path={svc['path']}")
        else:
            print("  [yellow]No recognizable services detected.[/yellow] Edit workspace.yaml and add entries by hand.")
        print("Edit workspace.yaml services, then run: memory-center reindex --workspace <workspace.yaml>")

    @app.command()
    def reindex(
        workspace: str = typer.Option(...),
        project: Optional[List[str]] = OPTIONAL_PROJECT_FILTER,
        path: Optional[List[str]] = OPTIONAL_PATH_FILTER,
        changed_only: bool = typer.Option(False, help="Use changed files from memory-detect-changes as reindex scope."),
        scope: str = typer.Option("staged", help="When --changed-only is set: staged|head|all"),
        parallel: bool = typer.Option(
            True, "--parallel/--no-parallel", help="Parse Java files in parallel during reindex."
        ),
        lock_timeout: float = typer.Option(0.0, min=0.0, help="Seconds to wait for another workspace reindex writer."),
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
        from memory_center.core.indexing.reindex_state import ReindexBusyError

        try:

            def report_progress(stage: str, percent: int, message: str) -> None:
                typer.echo(
                    json.dumps(
                        {"progress": {"stage": stage, "percent": percent, "message": message}},
                        ensure_ascii=False,
                    ),
                    err=True,
                )

            reindex_kwargs = {
                "projects": project,
                "paths": selected_paths,
                "parallel": parallel,
            }
            if "progress" in signature(reindex_workspace).parameters:
                reindex_kwargs["progress"] = report_progress
            if lock_timeout > 0:
                reindex_kwargs["lock_timeout"] = lock_timeout
            counts = reindex_workspace(config, store, **reindex_kwargs)
        except ReindexBusyError as exc:
            typer.echo(exc.to_cli_message(), err=True)
            raise typer.Exit(code=exc.cli_exit_code) from exc
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

    @app.command("inspect")
    def inspect_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        thread_id: str = typer.Option("", help="Optional host thread id; falls back to MEMORY_CENTER_THREAD_ID."),
    ):
        """Show the effective MCP, Hook, session, history, and index runtime state."""
        from memory_center.core.audit.inspect import inspect_runtime

        typer.echo(json.dumps(inspect_runtime(workspace, thread_id=thread_id), ensure_ascii=False, indent=2))

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

    @app.command("check-contract")
    def check_contract(
        workspace: str = typer.Option(...),
        contract_file: str = typer.Option(...),
        change_type: str = typer.Option("modify"),
    ):
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

    @app.command()
    def doctor(
        workspace: str = typer.Option(...), self_test: bool = typer.Option(False, help="Run lightweight query smoke tests.")
    ):
        """Validate workspace configuration, index health and optional smoke tests."""
        print(
            run_doctor(
                workspace, self_test=self_test, query_probe=lambda path, text: memory_query_hybrid(path, text, limit=5)
            )
        )

