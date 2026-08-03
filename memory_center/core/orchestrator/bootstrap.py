"""零初始化工作区的联邦上下文引导。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from memory_center.core.providers import GitNexusProvider

from .workspace_ops import workspace_status

_SESSION_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 30.0


def bootstrap_workspace_context(
    path: str | Path,
    *,
    intent: str = "",
    query: str = "",
    target: str = "",
    limit: int = 8,
    provider: GitNexusProvider | None = None,
) -> dict[str, Any]:
    """优先使用已存在的 Memory Center，否则以 GitNexus 只读结果建立会话上下文。"""
    root, workspace_file = _resolve_root_and_workspace(path)
    if workspace_file:
        status = workspace_status(str(workspace_file), view="compact", budget="small")
        return {
            "schema_version": 1,
            "context_state": "READY",
            "provider": "memory_center",
            "workspace": str(workspace_file),
            "root": str(root),
            "freshness": status.get("freshness", status.get("index_freshness", {})),
            "evidence": _evidence("memory_center", root, "published_generation", scope={"workspace": str(workspace_file)}),
            "tool_plan": [
                {"tool": "mc_start", "arguments": {"intent": intent or query}},
                {"tool": "mc_lookup", "arguments": {"query": query or intent, "mode": "auto"}},
            ],
            "persistence": "existing_memory_center",
            "next_action": "使用当前已发布的 Memory Center 索引；索引过期时按返回的新鲜度建议定向刷新。",
        }

    key = (str(root), query or intent, target)
    cached = _SESSION_CACHE.get(key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        result = dict(cached[1])
        result["cache"] = {"hit": True, "ttl_seconds": int(_CACHE_TTL_SECONDS - (now - cached[0]))}
        return result

    external = (provider or GitNexusProvider()).lookup(root, query or intent, target=target, intent=intent, limit=limit)
    if external.get("status") == "ready":
        result = {
            "schema_version": 1,
            "context_state": "FEDERATED",
            "provider": "gitnexus",
            "workspace": "",
            "root": str(root),
            "freshness": {"status": "provider_reported", "provider": "gitnexus"},
            "evidence": _evidence("gitnexus", root, "external_extracted", scope=external.get("scope_checked", {}), details=external),
            "tool_plan": [{"tool": "mc_bootstrap_context", "arguments": {"path": str(root), "query": query or intent}}],
            "result_summary": external.get("output", ""),
            "persistence": "session_ephemeral_no_workspace_write",
            "next_action": "已使用 GitNexus 只读上下文；需要跨服务图谱、任务记忆或验证治理时，再显式执行 Memory Center 初始化。",
            "cache": {"hit": False, "ttl_seconds": int(_CACHE_TTL_SECONDS)},
        }
    else:
        result = {
            "schema_version": 1,
            "context_state": "LIVE_SEARCH",
            "provider": "local_search",
            "workspace": "",
            "root": str(root),
            "freshness": {"status": "not_indexed"},
            "evidence": _evidence("local_search", root, "unavailable", scope=external.get("scope_checked", {}), details=external),
            "tool_plan": [{"tool": "rg", "arguments": {"query": query or target or intent, "root": str(root), "scope": "bounded"}}],
            "persistence": "none",
            "next_action": "GitNexus 不可用或未索引；先做小范围实时搜索。需要连续任务与跨服务治理时，显式初始化 Memory Center。",
            "cache": {"hit": False, "ttl_seconds": int(_CACHE_TTL_SECONDS)},
        }
    _SESSION_CACHE[key] = (now, result)
    return result


def _resolve_root_and_workspace(path: str | Path) -> tuple[Path, Path | None]:
    source = Path(path or ".").expanduser().resolve()
    start = source.parent if source.is_file() else source
    for candidate_root in [start, *start.parents]:
        workspace = candidate_root / ".memory-center" / "workspace.yaml"
        if workspace.is_file():
            return candidate_root, workspace
    return start, None


def _evidence(provider: str, root: Path, kind: str, *, scope: dict[str, Any], details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "provider": provider,
        "provenance_kind": kind,
        "root": str(root),
        "scope_checked": scope,
        "observed_at": int(time.time()),
        "duration_ms": (details or {}).get("duration_ms", 0.0),
        "persistence": "ephemeral" if provider != "memory_center" else "published_generation",
    }
