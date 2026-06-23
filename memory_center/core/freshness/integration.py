"""Freshness integration helper — unified freshness for main-chain facades.

Provides:
- ``get_freshness_with_actions()``: single-call freshness check with recommended actions
- ``freshness_action_hint()``: map freshness status to actionable next steps
- ``freshness_risk_escalation()``: escalate risk when freshness is stale

Key constraints (D-01):
- Freshness is no longer just an independent tool — it enters start/lookup/analyze
- Pending/stale suggests reading live files or reindexing
- Avoid duplicate freshness queries within same call chain
"""
from __future__ import annotations

from typing import Any

from ..diagnostics import DIAG, diag_entry

# Stable semantics for freshness statuses
FRESH = "fresh"
PENDING = "pending"
STALE = "stale"
UNKNOWN = "unknown"

_FRESHNESS_SEMANTICS = {
    FRESH: "索引新鲜，可信任检索结果",
    PENDING: "索引可能过期，关键文件建议读取实时内容",
    STALE: "索引较旧，建议先运行 reindex 再操作",
    UNKNOWN: "无法判断索引状态",
}

_RECOMMENDED_ACTIONS = {
    FRESH: [],
    PENDING: [
        "对关键文件使用 mc_lookup(mode='code') 或直接读取实时文件内容",
        "如果涉及重要变更，建议先运行 reindex",
    ],
    STALE: [
        "运行 reindex 更新索引后再进行检索和分析",
        "当前检索结果可能不完整，不要基于此做重要变更",
    ],
    UNKNOWN: [
        "检查 workspace 配置是否正确",
        "尝试运行 reindex 初始化索引",
    ],
}


def get_freshness_with_actions(workspace_file: str) -> dict[str, Any]:
    """Get freshness status with recommended actions. Never raises."""
    from pathlib import Path as _Path
    ws_path = _Path(workspace_file)
    if not ws_path.parent.exists():
        return {
            "status": UNKNOWN,
            "semantics": _FRESHNESS_SEMANTICS[UNKNOWN],
            "recommended_actions": _RECOMMENDED_ACTIONS[UNKNOWN],
            "staleness_level": "unknown",
            "banner": None,
            "last_indexed_at": "",
            "message": "",
            "_diagnostics": diag_entry(DIAG.UNAVAILABLE, reason="workspace directory does not exist"),
        }
    try:
        from ..freshness.status import IndexFreshnessService
        svc = IndexFreshnessService(workspace_file)
        banner = svc.banner()
        freshness_data = banner.get("freshness", {})
        status = freshness_data.get("status", UNKNOWN)
        return {
            "status": status,
            "semantics": _FRESHNESS_SEMANTICS.get(status, _FRESHNESS_SEMANTICS[UNKNOWN]),
            "recommended_actions": _RECOMMENDED_ACTIONS.get(status, _RECOMMENDED_ACTIONS[UNKNOWN]),
            "staleness_level": freshness_data.get("staleness_level", "unknown"),
            "banner": banner.get("banner"),
            "last_indexed_at": freshness_data.get("last_indexed_at", ""),
            "message": freshness_data.get("message", ""),
        }
    except Exception as exc:
        return {
            "status": UNKNOWN,
            "semantics": _FRESHNESS_SEMANTICS[UNKNOWN],
            "recommended_actions": _RECOMMENDED_ACTIONS[UNKNOWN],
            "staleness_level": "unknown",
            "banner": None,
            "last_indexed_at": "",
            "message": "",
            "_diagnostics": diag_entry(DIAG.UNAVAILABLE, exc=exc),
        }


def freshness_action_hint(status: str) -> str:
    """Return a concise action hint for the given freshness status."""
    hints = {
        FRESH: "索引新鲜，可放心使用检索结果。",
        PENDING: "索引可能过期，关键操作前建议读取实时文件。",
        STALE: "索引较旧，请先 reindex 再操作。",
        UNKNOWN: "索引状态未知，建议检查 workspace 配置。",
    }
    return hints.get(status, hints[UNKNOWN])


def freshness_risk_escalation(current_risk: str, freshness_status: str) -> str:
    """Escalate risk level when freshness is stale/pending.

    Returns the higher of current_risk and freshness-implied risk.
    Does NOT downgrade risk.
    """
    risk_order = {"low": 0, "medium": 1, "high": 2, "unknown": -1}
    freshness_risk = {
        FRESH: 0,
        PENDING: 1,
        STALE: 2,
        UNKNOWN: 0,
    }
    current = risk_order.get(current_risk, 0)
    freshness = freshness_risk.get(freshness_status, 0)
    max_risk = max(current, freshness)
    for name, level in risk_order.items():
        if level == max_risk:
            return name
    return current_risk


def stale_file_alert(file_freshness: dict[str, str]) -> list[dict[str, str]]:
    """Generate alerts for stale files in query results."""
    alerts = []
    for path, status in file_freshness.items():
        if status in (STALE, PENDING):
            alerts.append({
                "file": path,
                "freshness": status,
                "alert": freshness_action_hint(status),
            })
    return alerts
