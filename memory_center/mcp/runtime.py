"""MCP 服务启动、工作区解析与统一错误边界。"""
from __future__ import annotations

import inspect
from functools import wraps
from pathlib import Path
from typing import Any

from memory_center.core.foundation.errors import normalize_exception
from memory_center.core.governance.registry import load_registry
from memory_center.core.storage.workspace import WorkspaceStore


def find_groups_for_workspace(workspace_file: str) -> list[str]:
    """返回包含当前工作区的全局逻辑组名称。"""
    registry = load_registry()
    workspace_name = _find_workspace_name_in_registry(workspace_file, registry)
    if not workspace_name:
        return []
    return [group.get("name", "") for group in registry.get("groups", []) if workspace_name in group.get("members", [])]


class WorkspaceContext:
    """每个 MCP Server 实例的工作区上下文，不使用模块级可变状态。"""

    def __init__(self, workspace_file: str):
        self.workspace_input = workspace_file
        self.workspace_file = resolve_workspace_input(workspace_file)
        self.startup_diagnostics = build_startup_diagnostics(self.workspace_input, self.workspace_file)


def build_startup_diagnostics(workspace_input: str, workspace_file: str) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "workspace_input": workspace_input,
        "workspace_file": workspace_file,
        "resolved_from_directory": str(workspace_input or "").strip() != workspace_file,
        "ok": False,
        "checks": [],
        "next_actions": [],
    }
    try:
        from memory_center.core.governance.instructions import inspect_agent_mcp_bindings
        from memory_center.core.workspace.config import load_workspace_config

        config = load_workspace_config(workspace_file)
        bindings = inspect_agent_mcp_bindings(WorkspaceStore(workspace_file), config.root_path)
        diagnostics.update(
            {
                "ok": bool(bindings.get("ok")) and bool(bindings.get("command_available")),
                "workspace": config.workspace,
                "workspace_root": str(Path(config.root_path).expanduser().resolve()),
                "mcp_bindings": bindings,
            }
        )
        diagnostics["checks"].extend(
            [
                {"name": "workspace_resolved", "ok": True},
                {"name": "mcp_bindings", "ok": bool(bindings.get("ok"))},
                {"name": "mcp_command_available", "ok": bool(bindings.get("command_available"))},
            ]
        )
        if not bindings.get("ok"):
            diagnostics["next_actions"].append("运行 `memory-center setup-agent --workspace <workspace.yaml>` 自动刷新根目录和子项目 MCP 绑定。")
        if not bindings.get("command_available"):
            diagnostics["next_actions"].append("确认 memory-center-mcp 已安装且在宿主 PATH 中。")
    except Exception as exc:
        diagnostics["error"] = str(exc)
        diagnostics["checks"].append({"name": "workspace_resolved", "ok": False})
        diagnostics["next_actions"].append("确认 --workspace 指向 .memory-center/workspace.yaml，或传入聚合 workspace / 子项目目录。")
    return diagnostics


def resolve_workspace_input(workspace_input: str) -> str:
    """将文件或目录入参尽力解析为 workspace.yaml，解析失败时保持可诊断。"""
    raw = (workspace_input or ".").strip() or "."
    path = Path(raw).expanduser()
    if path.is_file():
        return str(path.resolve())
    start = path.resolve() if path.exists() else Path.cwd().resolve()
    if start.name == ".memory-center":
        candidate = start / "workspace.yaml"
        if candidate.exists():
            return str(candidate.resolve())
    for parent in [start, *start.parents]:
        candidate = parent / ".memory-center" / "workspace.yaml"
        if candidate.exists():
            return str(candidate.resolve())
    return str(path.resolve())


def safe_mcp_tool(mcp):
    """注册保持原始 schema 的统一异常边界。"""

    def decorator(fn):
        return mcp.tool()(_mcp_error_boundary(fn))

    return decorator


def _find_workspace_name_in_registry(workspace_file: str, registry: dict[str, Any]) -> str | None:
    resolved = str(Path(workspace_file).expanduser().resolve())
    for repo in registry.get("repos", []):
        if str(Path(repo.get("workspace_file", "")).expanduser().resolve()) == resolved:
            return repo.get("name")
    return None


def _mcp_error_boundary(fn):
    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrapped(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                return normalize_exception(exc).to_mcp_dict()

        return async_wrapped

    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return normalize_exception(exc).to_mcp_dict()

    return wrapped
