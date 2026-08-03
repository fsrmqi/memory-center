"""零初始化工作区的联邦上下文引导。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from memory_center.core.providers import (
    DEFAULT_PROVIDER_REGISTRY,
    GitNexusProvider,
    McpBridgeProvider,
    ProviderRegistry,
    build_external_evidence_ref,
    load_mcp_bridge_policy,
    mcp_bridge_policy_status,
)

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
    registry: ProviderRegistry | None = None,
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
            "provider_selection": {
                "capability": "code_navigation",
                "selected": "memory_center",
                "attempted": [{"provider": "memory_center", "status": "ready"}],
                "registry": DEFAULT_PROVIDER_REGISTRY.descriptors(),
            },
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

    if provider is not None:
        external = provider.lookup(root, query or intent, target=target, intent=intent, limit=limit)
        provider_selection = {
            "capability": "code_navigation",
            "selected": getattr(provider, "name", "external"),
            "attempted": [{"provider": getattr(provider, "name", "external"), "status": external.get("status", "unavailable")}],
            "registry": [],
        }
    else:
        external, provider_selection = (registry or DEFAULT_PROVIDER_REGISTRY).lookup(
            root, query or intent, target=target, intent=intent, limit=limit
        )
    if external.get("status") == "ready":
        provider_name = str(external.get("provider", provider_selection["selected"]) or provider_selection["selected"])
        evidence_ref = build_external_evidence_ref(provider_name, root, external)
        result = {
            "schema_version": 1,
            "context_state": "FEDERATED",
            "provider": provider_name,
            "workspace": "",
            "root": str(root),
            "freshness": {"status": "provider_reported", "provider": provider_name},
            "evidence": _evidence(provider_name, root, "external_extracted", scope=external.get("scope_checked", {}), details=external),
            "evidence_ref": evidence_ref,
            "provider_selection": provider_selection,
            "tool_plan": [{"tool": "mc_bootstrap_context", "arguments": {"path": str(root), "query": query or intent}}],
            "result_summary": external.get("output", ""),
            "persistence": "session_ephemeral_no_workspace_write",
            "next_action": "已使用 GitNexus 只读上下文；需要跨服务图谱、任务记忆或验证治理时，再显式执行 Memory Center 初始化。",
            "cache": {"hit": False, "ttl_seconds": int(_CACHE_TTL_SECONDS)},
        }
    else:
        action_cards = _external_index_action_cards(external, root)
        external_status = str(external.get("status", "unavailable") or "unavailable")
        result = {
            "schema_version": 1,
            "context_state": "LIVE_SEARCH",
            "provider": "local_search",
            "workspace": "",
            "root": str(root),
            "freshness": {
                "status": "stale" if external_status == "stale" else "not_indexed",
                "provider": str(external.get("provider", "") or ""),
                "reason": str(external.get("reason", "") or ""),
            },
            "evidence": _evidence("local_search", root, "unavailable", scope=external.get("scope_checked", {}), details=external),
            "evidence_ref": build_external_evidence_ref("local_search", root, external, provenance_kind="AMBIGUOUS"),
            "provider_selection": provider_selection,
            "action_cards": action_cards,
            "tool_plan": [{"tool": "rg", "arguments": {"query": query or target or intent, "root": str(root), "scope": "bounded"}}],
            "persistence": "none",
            "next_action": _external_next_action(external, action_cards),
            "cache": {"hit": False, "ttl_seconds": int(_CACHE_TTL_SECONDS)},
        }
    _SESSION_CACHE[key] = (now, result)
    return result


def _external_index_action_cards(external: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """仅针对可诊断的外部索引状态返回确认后的最小升级动作。"""
    provider = str(external.get("provider", "") or "")
    reason = str(external.get("reason", "") or "")
    if provider != "gitnexus" or reason not in {"gitnexus_index_not_found", "gitnexus_index_stale"}:
        return []
    return [{
        "action_id": f"provider-index-{provider}",
        "title": "建立或刷新 GitNexus 索引",
        "provider": provider,
        "action": "analyze",
        "arguments": {"path": str(root), "provider": provider, "action": "analyze", "confirm": True},
        "mode": "controlled_write",
        "requires_confirmation": True,
        "reason": "GitNexus 索引未建立或已陈旧；仅在确认后执行受限 index-only 分析。",
        "stop_condition": "Provider status 恢复为 ready，或用户取消操作。",
    }]


def _external_next_action(external: dict[str, Any], action_cards: list[dict[str, Any]]) -> str:
    if action_cards:
        return "GitNexus 索引未建立或已陈旧；可先做小范围实时搜索，或确认行动卡后定向建立/刷新外部索引。"
    if str(external.get("reason", "")) == "gitnexus_not_installed":
        return "GitNexus 未安装；先做小范围实时搜索。需要外部索引能力时安装并配置 GitNexus。"
    return "外部 Provider 不可用；先做小范围实时搜索。需要连续任务与跨服务治理时，显式初始化 Memory Center。"


def execute_provider_action(
    path: str | Path,
    *,
    provider: str = "gitnexus",
    action: str,
    query: str = "",
    target: str = "",
    confirm: bool = False,
    force: bool = False,
    limit: int = 8,
    depth: int = 3,
    registry: ProviderRegistry | None = None,
) -> dict[str, Any]:
    """执行 Provider 注册的固定动作；写入或破坏性动作必须显式确认。"""
    root, workspace_file = _resolve_root_and_workspace(path)
    result = (registry or DEFAULT_PROVIDER_REGISTRY).execute(
        root,
        provider_id=provider,
        action=action,
        query=query,
        target=target,
        confirm=confirm,
        force=force,
        limit=limit,
        depth=depth,
    )
    result.update(
        root=str(root),
        workspace=str(workspace_file) if workspace_file else "",
        persistence="external_provider_managed",
    )
    return result


def mcp_bridge_status(path: str | Path) -> dict[str, Any]:
    """返回外部 MCP Bridge 的策略状态；不创建工作区目录。"""
    root, workspace_file = _resolve_root_and_workspace(path)
    result = mcp_bridge_policy_status(root)
    result.update(
        root=str(root),
        workspace=str(workspace_file) if workspace_file else "",
        persistence="none",
    )
    return result


def execute_mcp_bridge_action(
    path: str | Path,
    *,
    provider: str,
    action: str,
    query: str = "",
    target: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    """按工作区策略调用一个外部 MCP 工具，外部正文仅在本次响应中存在。"""
    root, workspace_file = _resolve_root_and_workspace(path)
    policies = load_mcp_bridge_policy(root)
    policy = policies.get(provider)
    if policy is None:
        return {
            "provider": provider,
            "action": action,
            "status": "provider_not_configured",
            "reason": "mcp_bridge_policy_missing_or_provider_not_allowed",
            "root": str(root),
            "workspace": str(workspace_file) if workspace_file else "",
            "policy": mcp_bridge_policy_status(root),
            "persistence": "none",
            "next_action": "在 .memory-center/provider-mcp-policy.json 显式登记受信任的 HTTP MCP Server、工具和参数模板。",
        }
    result = McpBridgeProvider(policy).execute(action, query=query, target=target, confirm=confirm)
    result.update(
        root=str(root),
        workspace=str(workspace_file) if workspace_file else "",
        persistence="session_ephemeral_external_mcp",
    )
    if result.get("status") == "ready":
        result["evidence_ref"] = build_external_evidence_ref(
            policy.provider_id, root, result, provenance_kind="EXTRACTED"
        )
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
