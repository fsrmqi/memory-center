"""全局注册表、工作区组与工作区配置 CLI 命令。"""
from __future__ import annotations

# Typer evaluates command annotations at runtime in Python 3.9 environments.
# ruff: noqa: UP006,UP045
import typing
from pathlib import Path

import typer
from rich import print

from memory_center.core.governance.registry import add_to_group, create_group, list_workspaces, register_workspace
from memory_center.core.orchestrator import group_impact, group_query, group_status
from memory_center.core.workspace.config import add_workspace_service, load_workspace_config, remove_workspace_service


def register_registry_commands(app: typer.Typer) -> None:
    """注册全局工作区注册表命令。"""

    @app.command("add")
    def registry_add(name: str = typer.Option(...), workspace: str = typer.Option(...)):
        """在全局 registry.json 中注册一个工作区。"""
        print(register_workspace(name, workspace))

    @app.command("list")
    def registry_list():
        """列出已全局注册的工作区。"""
        print(list_workspaces())


def register_group_commands(app: typer.Typer) -> None:
    """注册跨工作区逻辑组命令。"""

    @app.command("create")
    def group_create(name: str = typer.Option(...)):
        """为多个已注册工作区创建逻辑组。"""
        print(create_group(name))

    @app.command("add")
    def group_add(name: str = typer.Option(...), repo: str = typer.Option(...)):
        """将一个已注册工作区加入逻辑组。"""
        print(add_to_group(name, repo))

    @app.command("status")
    def group_status_cmd(name: str = typer.Option(...)):
        """查看逻辑组内所有工作区的聚合状态。"""
        print(group_status(name))

    @app.command("query")
    def group_query_cmd(name: str = typer.Option(...), text: str = typer.Option(...), limit: int = typer.Option(20)):
        """在逻辑组内执行合并查询。"""
        print(group_query(name, text, limit))

    @app.command("impact")
    def group_impact_cmd(
        name: str = typer.Option(...),
        target: str = typer.Option(...),
        direction: str = typer.Option("upstream"),
        max_depth: int = typer.Option(3),
    ):
        """对逻辑组执行跨工作区影响分析。"""
        print(group_impact(name, target, direction, max_depth))


def register_workspace_commands(app: typer.Typer) -> None:
    """注册 workspace.yaml 维护命令。"""

    @app.command("list-services")
    def workspace_list_services(workspace: str = typer.Option(...)):
        """列出 workspace.yaml 中的服务配置。"""
        config = load_workspace_config(workspace)
        print({"workspace": config.workspace, "root": str(config.root_path), "services": [item.__dict__ for item in config.services]})

    @app.command("add-service")
    def workspace_add_service(
        workspace: str = typer.Option(...),
        name: str = typer.Option(...),
        path: str = typer.Option(...),
        service_type: str = typer.Option("spring-boot-service", "--type"),
        service_name: typing.Optional[str] = typer.Option(None),  # noqa: B008
        tag: typing.Optional[typing.List[str]] = typer.Option(None),  # noqa: B008
    ):
        """向 workspace.yaml 添加或覆盖一个服务条目。"""
        result = add_workspace_service(workspace, name, path, service_type, service_name, tag)
        result["next_steps"] = _workspace_next_steps(workspace)
        print(result)

    @app.command("remove-service")
    def workspace_remove_service(workspace: str = typer.Option(...), name: str = typer.Option(..., help="要移除的服务名或路径。")):
        """按服务名或路径移除 workspace.yaml 的一个服务条目。"""
        result = remove_workspace_service(workspace, name)
        result["next_steps"] = _workspace_next_steps(workspace)
        print(result)


def _workspace_next_steps(workspace: str) -> list[str]:
    resolved = Path(workspace).expanduser().resolve()
    return [
        f"memory-center reindex --workspace {resolved}",
        f"memory-center doctor --workspace {resolved} --self-test",
    ]
