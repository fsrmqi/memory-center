"""基于工作区注册表的跨工作区查询用例。"""
from __future__ import annotations

from typing import Any

from memory_center.core.governance.registry import load_registry
from memory_center.core.orchestrator import group_chain, group_impact, group_query, group_status


def workspace_group_status(workspace_file: str) -> dict[str, Any]:
    return group_status(load_registry(workspace_file))


def workspace_group_query(workspace_file: str, query: str, limit: int) -> dict[str, Any]:
    return group_query(load_registry(workspace_file), query=query, limit=limit)


def workspace_group_impact(workspace_file: str, target: str) -> dict[str, Any]:
    return group_impact(load_registry(workspace_file), target=target)


def workspace_group_chain(workspace_file: str, symbol: str) -> dict[str, Any]:
    return group_chain(load_registry(workspace_file), symbol=symbol)
