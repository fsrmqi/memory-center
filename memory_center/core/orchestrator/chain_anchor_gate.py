"""P1-A: chain 锚定与范围负向结论门禁。

真实会话复盘中，`mc_lookup(mode="chain")` 曾把包含明确类名的 query 锚定到
不相关符号（如 `NoSuchClassXYZ` 解析到 `Result`），shard 路由也可能遗漏锚点
所在项目。此时 chain 为空只是"锚定失败/范围缺失"的副作用，不是"目标没有
调用方"的证据。本模块构建锚点校验与范围校验的纯投影，供 claim boundary
把 `anchor_mismatch` / `scope_incomplete` 纳入 reason codes，强制空 chain
结果降级为 AMBIGUOUS。

纯函数、无 workspace 状态：数据由调用方（lookup_navigation / finalize_lookup）
从已解析的节点与路由结果中提取。
"""
from __future__ import annotations

from typing import Any

from memory_center.core.foundation.claim_boundary import gate_reasons_from_chain  # noqa: F401 - re-exported

ANCHOR_MATCHED = "matched"
ANCHOR_MISMATCH = "mismatch"
ANCHOR_MISSING = "missing"



def _normalise_symbol(name: str) -> str:
    token = (name or "").strip().replace("#", ".")
    if not token:
        return ""
    return token.split(".")[-1].lower()


def _anchor_matches_request(anchor_name: str, requested: str) -> bool:
    target = _normalise_symbol(requested)
    if not target:
        return False
    name = (anchor_name or "").strip()
    if not name:
        return False
    short = name.split(".")[-1].lower()
    return short == target or name.lower() == target


def build_chain_anchor_validation(
    requested: str,
    anchor: dict[str, Any] | None,
    *,
    explicit_symbol: str = "",
) -> dict[str, Any]:
    """Compare the requested symbol with the anchor the resolver selected.

    ``explicit_symbol`` (mc_lookup 的 symbol 参数) 优先作为校验目标；中文意图
    词混入 query 时，只要显式 symbol 与锚点一致仍视为 matched。
    """
    request_target = (explicit_symbol or "").strip() or requested
    if not request_target.strip():
        return {
            "requested_symbol": requested,
            "explicit_symbol": explicit_symbol,
            "resolved_anchor": "",
            "status": ANCHOR_MISSING,
            "reason": "no_resolvable_request_symbol",
        }
    if not anchor:
        return {
            "requested_symbol": requested,
            "explicit_symbol": explicit_symbol,
            "resolved_anchor": "",
            "status": ANCHOR_MISSING,
            "reason": "symbol_not_found_in_index",
        }
    anchor_name = str(anchor.get("name", "") or "")
    if _anchor_matches_request(anchor_name, request_target):
        return {
            "requested_symbol": requested,
            "explicit_symbol": explicit_symbol,
            "resolved_anchor": anchor_name,
            "status": ANCHOR_MATCHED,
            "reason": "",
        }
    return {
        "requested_symbol": requested,
        "explicit_symbol": explicit_symbol,
        "resolved_anchor": anchor_name,
        "status": ANCHOR_MISMATCH,
        "reason": f"resolved anchor '{anchor_name}' does not match requested '{request_target.strip()}'",
    }


def build_chain_scope_validation(
    anchor: dict[str, Any] | None,
    *,
    routed_projects: list[str],
    route_available: bool,
) -> dict[str, Any]:
    """Check that the shard route covers the anchor's project.

    路由不可用、或锚点项目不在 selected_projects 中时视为范围不完整，
    空结果不得作为负向结论依据。
    """
    anchor_project = str((anchor or {}).get("project", "") or "")
    projects = [str(item or "") for item in routed_projects or []]
    covered = bool(anchor_project) and any(
        _project_same(anchor_project, project) for project in projects
    )
    incomplete = not route_available or not covered
    if route_available and covered:
        reason = ""
    elif not route_available:
        reason = "route_unavailable"
    else:
        reason = "anchor_project_not_covered"
    return {
        "anchor_project": anchor_project,
        "routed_projects": projects,
        "anchor_project_covered": covered,
        "scope_incomplete": incomplete,
        "reason": reason,
    }


def _project_same(left: str, right: str) -> bool:
    return bool(left) and bool(right) and left.strip().lower() == right.strip().lower()


def build_empty_chain_fallback(
    requested: str,
    *,
    direction: str,
    anchor_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bounded fallback actions for an empty chain result.

    空 chain 不得自动生成"确认不存在调用方"的结论；返回可执行的下一步查询。
    """
    status = str((anchor_validation or {}).get("status", ANCHOR_MISSING))
    reasons: list[dict[str, str]] = [
        {
            "mode": "symbol",
            "action": f"mc_lookup(mode='symbol', query='{requested}') 重新确认锚点",
        },
        {
            "mode": "code",
            "action": f"mc_lookup(mode='code', query='{requested}') 做有界文件搜索",
        },
    ]
    return {
        "chain_empty": True,
        "direction": direction,
        "anchor_status": status,
        "requested_symbol": requested,
        "actions": reasons,
        "note": "空调用链可能是锚定失败或路由范围不足；请勿直接得出“不存在调用方”的结论。",
    }


__all__ = [
    "ANCHOR_MATCHED",
    "ANCHOR_MISSING",
    "ANCHOR_MISMATCH",
    "build_chain_anchor_validation",
    "build_chain_scope_validation",
    "build_empty_chain_fallback",
    "gate_reasons_from_chain",
]
