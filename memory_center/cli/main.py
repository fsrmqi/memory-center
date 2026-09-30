from __future__ import annotations

import typer

from memory_center import __version__
from memory_center.cli.commands.artifacts import register_artifact_commands
from memory_center.cli.commands.audit import register_audit_commands
from memory_center.cli.commands.bridge import register_bridge_commands
from memory_center.cli.commands.change import register_change_commands
from memory_center.cli.commands.eval import register_eval_commands
from memory_center.cli.commands.gate import register_gate_commands
from memory_center.cli.commands.lookup import register_lookup_commands
from memory_center.cli.commands.ops import register_ops_commands
from memory_center.cli.commands.resume import register_resume_commands
from memory_center.cli.commands.retrieval import register_retrieval_commands
from memory_center.cli.commands.session import register_session_commands
from memory_center.cli.commands.setup import register_setup_commands
from memory_center.cli.commands.task_shadow import register_task_shadow_commands
from memory_center.cli.commands.tooling import register_tooling_commands
from memory_center.cli.commands.walkthrough import register_walkthrough_commands
from memory_center.cli.commands.watcher import register_watcher_commands
from memory_center.cli.commands.work import register_work_commands
from memory_center.cli.commands.workspaces import (
    register_group_commands,
    register_registry_commands,
    register_workspace_commands,
)
from memory_center.cli.commands.write import register_write_commands
from memory_center.cli.output import print_data as print
from memory_center.core.foundation.errors import normalize_exception

app = typer.Typer(help="Memory Center CLI")
registry_app = typer.Typer(help="Global registry commands")
group_app = typer.Typer(help="Workspace group commands")
workspace_app = typer.Typer(help="Workspace config maintenance commands")
artifact_app = typer.Typer(help="Shared workspace artifacts commands")
app.add_typer(registry_app, name="registry")
app.add_typer(group_app, name="group")
app.add_typer(workspace_app, name="workspace")
app.add_typer(artifact_app, name="artifact")
register_artifact_commands(artifact_app)
register_registry_commands(registry_app)
register_group_commands(group_app)
register_workspace_commands(workspace_app)
register_setup_commands(app)
register_retrieval_commands(app)
register_ops_commands(app)
register_watcher_commands(app)
register_change_commands(app)
register_lookup_commands(app)
register_walkthrough_commands(app)
register_write_commands(app)
register_eval_commands(app)
register_gate_commands(app)
register_session_commands(app)
register_task_shadow_commands(app)
register_resume_commands(app)
register_work_commands(app)
register_audit_commands(app)
register_bridge_commands(app)
register_tooling_commands(app)


def _version_callback(value: bool):
    if value:
        print({"name": "memory-center", "version": __version__})
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False, "--version", help="Show Memory Center version and exit.", is_eager=True, callback=_version_callback
    ),
):
    """Memory Center CLI entrypoint."""


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
