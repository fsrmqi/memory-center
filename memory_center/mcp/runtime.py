"""MCP 服务启动、工作区解析与统一错误边界。"""
from __future__ import annotations

import inspect
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any

from memory_center.core.audit.interactions import (
    bind_active_session,
    redact_interaction_text,
    refresh_effect_summary,
    resolve_active_session,
    unbind_active_session,
)
from memory_center.core.foundation.errors import normalize_exception
from memory_center.core.governance.registry import load_registry
from memory_center.core.storage.workspace import WorkspaceStore

MCP_INVOCATIONS_FILE = "mcp-invocations.jsonl"
MCP_AUDIT_RETENTION_DAYS = 30
MCP_AUDIT_MAX_RECORDS = 100_000
MCP_AUDIT_PRUNE_INTERVAL_SECONDS = 300
MCP_AUDIT_SYNC_PRUNE_MAX_BYTES = 64 * 1024
_AUDIT_PRUNE_IN_FLIGHT: set[str] = set()
_AUDIT_PRUNE_GUARD = threading.Lock()
_SAFE_MCP_INPUT_FIELDS = (
    "action", "budget", "change_type", "depth", "direction", "intent", "limit",
    "mode", "name", "project", "query", "request_tier", "scope", "target",
    "task_id", "title", "session_id", "execution_mode",
)


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
        self.thread_id = os.environ.get("MEMORY_CENTER_THREAD_ID", "").strip()
        self.turn_id = os.environ.get("MEMORY_CENTER_TURN_ID", "").strip()
        self.trace_id = os.environ.get("MEMORY_CENTER_TRACE_ID", "").strip() or uuid.uuid4().hex
        self.active_session_id = resolve_active_session(self.workspace_file, self.thread_id)
        self.mcp_audit_entry_count: int | None = None
        self.mcp_audit_last_pruned_at = 0.0


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


def safe_mcp_tool(mcp, workspace_context: WorkspaceContext | None = None):
    """注册保持原始 schema 的统一异常边界和调用审计。"""

    def decorator(fn):
        return mcp.tool()(_mcp_error_boundary(fn, workspace_context))

    return decorator


def _find_workspace_name_in_registry(workspace_file: str, registry: dict[str, Any]) -> str | None:
    resolved = str(Path(workspace_file).expanduser().resolve())
    for repo in registry.get("repos", []):
        if str(Path(repo.get("workspace_file", "")).expanduser().resolve()) == resolved:
            return repo.get("name")
    return None


def _mcp_error_boundary(fn, workspace_context: WorkspaceContext | None = None):
    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrapped(*args, **kwargs):
            started_at = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
                _record_mcp_invocation(workspace_context, fn, args, kwargs, result, "success", started_at)
                return result
            except Exception as exc:
                result = normalize_exception(exc).to_mcp_dict()
                _record_mcp_invocation(workspace_context, fn, args, kwargs, result, "error", started_at)
                return result

        return async_wrapped

    @wraps(fn)
    def wrapped(*args, **kwargs):
        started_at = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
            _record_mcp_invocation(workspace_context, fn, args, kwargs, result, "success", started_at)
            return result
        except Exception as exc:
            result = normalize_exception(exc).to_mcp_dict()
            _record_mcp_invocation(workspace_context, fn, args, kwargs, result, "error", started_at)
            return result

    return wrapped


def _record_mcp_invocation(
    workspace_context: WorkspaceContext | None,
    fn: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
    status: str,
    started_at: float,
) -> None:
    """持久化精简的 MCP 审计事件，不保留请求或响应正文。"""
    if workspace_context is None:
        return
    try:
        inputs = _bound_mcp_inputs(fn, args, kwargs)
        session_id = _resolve_mcp_session_id(workspace_context, inputs, result)
        store = WorkspaceStore(workspace_context.workspace_file)
        event = {
            "event_type": "mcp_tool_call",
            "tool_name": fn.__name__,
            "source": "mcp",
            "status": status,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "session_id": session_id,
            "task_id": str(inputs.get("task_id", "") or ""),
            "trace_id": workspace_context.trace_id,
            "thread_id": workspace_context.thread_id,
            "turn_id": workspace_context.turn_id,
            "runtime": _audit_runtime_context(store),
            "inputs": _safe_mcp_inputs(inputs),
            "result": _safe_mcp_result(result),
        }
        store.append_jsonl(MCP_INVOCATIONS_FILE, event)
        _maintain_mcp_audit_retention(workspace_context, store)
        if fn.__name__ == "mc_close":
            unbind_active_session(workspace_context.workspace_file, workspace_context.thread_id, session_id)
            refresh_effect_summary(workspace_context.workspace_file)
        elif session_id:
            bind_active_session(
                workspace_context.workspace_file,
                workspace_context.thread_id,
                session_id,
                workspace_context.trace_id,
            )
        if session_id and fn.__name__ != "mc_close":
            from memory_center.core.orchestrator.session import workspace_log_session_event

            workspace_log_session_event(
                workspace_context.workspace_file,
                session_id,
                "tool_call",
                {
                    "tool_name": fn.__name__,
                    "source": "mcp",
                    "status": status,
                    "duration_ms": event["duration_ms"],
                    "mode": str(inputs.get("mode", "") or ""),
                    "action": str(inputs.get("action", "") or ""),
                    "query": _safe_mcp_text(inputs.get("query", "")),
                    "target": _safe_mcp_text(inputs.get("target", "")),
                },
            )
    except Exception:
        # 审计失败不得改变 MCP 的公开响应和错误语义。
        return


def _maintain_mcp_audit_retention(workspace_context: WorkspaceContext, store: WorkspaceStore) -> None:
    """在小日志上立即收口，大日志异步物理压缩。"""
    now = time.monotonic()
    if workspace_context.mcp_audit_entry_count is not None:
        workspace_context.mcp_audit_entry_count += 1
    needs_prune = (
        workspace_context.mcp_audit_entry_count is None
        or workspace_context.mcp_audit_entry_count > MCP_AUDIT_MAX_RECORDS
        or now - workspace_context.mcp_audit_last_pruned_at >= MCP_AUDIT_PRUNE_INTERVAL_SECONDS
    )
    if not needs_prune:
        return
    workspace_context.mcp_audit_last_pruned_at = now
    cutoff = datetime.now(timezone.utc) - timedelta(days=MCP_AUDIT_RETENTION_DAYS)
    audit_path = store.memory_dir / MCP_INVOCATIONS_FILE
    # 首次使用和测试/轻量工作区常只有极少量记录。同步裁剪可保证调用返回后
    # 过期数据不可见；大日志仍完全移出 MCP 请求线程。
    if not audit_path.exists() or audit_path.stat().st_size <= MCP_AUDIT_SYNC_PRUNE_MAX_BYTES:
        summary = store.prune_jsonl(
            MCP_INVOCATIONS_FILE,
            created_before=cutoff,
            max_records=MCP_AUDIT_MAX_RECORDS,
        )
        workspace_context.mcp_audit_entry_count = summary["kept"]
        return
    key = str(store.memory_dir.resolve())
    with _AUDIT_PRUNE_GUARD:
        if key in _AUDIT_PRUNE_IN_FLIGHT:
            return
        _AUDIT_PRUNE_IN_FLIGHT.add(key)

    def prune() -> None:
        try:
            worker_store = WorkspaceStore(workspace_context.workspace_file)
            summary = worker_store.prune_jsonl(
                MCP_INVOCATIONS_FILE,
                created_before=cutoff,
                max_records=MCP_AUDIT_MAX_RECORDS,
            )
            workspace_context.mcp_audit_entry_count = summary["kept"]
        finally:
            with _AUDIT_PRUNE_GUARD:
                _AUDIT_PRUNE_IN_FLIGHT.discard(key)

    threading.Thread(target=prune, name="memory-center-audit-prune", daemon=True).start()


def _bound_mcp_inputs(fn: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        return dict(inspect.signature(fn).bind_partial(*args, **kwargs).arguments)
    except TypeError:
        return dict(kwargs)


def _resolve_mcp_session_id(workspace_context: WorkspaceContext, inputs: dict[str, Any], result: Any) -> str:
    explicit = str(inputs.get("session_id", "") or "").strip()
    discovered = _session_id_from_result(result)
    session_id = explicit or discovered or workspace_context.active_session_id
    if session_id:
        workspace_context.active_session_id = session_id
    return session_id


def _session_id_from_result(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    direct = str(result.get("session_id", "") or "").strip()
    if direct:
        return direct
    for key in ("session", "ended", "result"):
        nested = result.get(key)
        if isinstance(nested, dict):
            value = str(nested.get("session_id", "") or "").strip()
            if value:
                return value
    return ""


def _safe_mcp_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in _SAFE_MCP_INPUT_FIELDS:
        value = inputs.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, str):
            safe[key] = _safe_mcp_text(value)
        elif isinstance(value, (int, float, bool)):
            safe[key] = value
        elif isinstance(value, (list, tuple)):
            safe[f"{key}_count"] = len(value)
    return safe


def _safe_mcp_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"kind": type(result).__name__}
    summary: dict[str, Any] = {"top_level_keys": sorted(str(key) for key in result)[:16]}
    for key in ("workflow", "mode", "action", "execution_mode"):
        value = result.get(key)
        if isinstance(value, str) and value:
            summary[key] = _safe_mcp_text(value)
    for key in ("results", "matches", "findings", "next_actions"):
        value = result.get(key)
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    error = result.get("error")
    if error:
        summary["error"] = True
    return summary


def _safe_mcp_text(value: Any, limit: int = 240) -> str:
    return redact_interaction_text(value, limit=limit)


def _audit_runtime_context(store: WorkspaceStore) -> dict[str, str]:
    from memory_center import __version__

    control = store.read_json_prefer_backend("index-control.json", {})
    return {
        "memory_center_version": __version__,
        "index_generation": str(control.get("active_generation", "") or "") if isinstance(control, dict) else "",
    }
