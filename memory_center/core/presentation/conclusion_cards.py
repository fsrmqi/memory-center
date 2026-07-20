"""Small, actionable conclusion cards shared by presentation entry points."""
from __future__ import annotations

from typing import Any


def build_conclusion_cards(edges: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    """Convert bounded evidence edges into user-facing, action-oriented cards."""
    cards: list[dict[str, Any]] = []
    for edge in edges[: min(max(1, limit), 20)]:
        level = str(edge.get("assertion_status", edge.get("evidence_level", "AMBIGUOUS")) or "AMBIGUOUS")
        confidence = float(edge.get("confidence", 0.0) or 0.0)
        status = "VERIFIED" if level == "VERIFIED" else "REJECTED" if level == "REJECTED" else "STALE" if level == "STALE" else "INFERRED" if level == "INFERRED" else "EXTRACTED" if level == "EXTRACTED" else "AMBIGUOUS"
        cards.append(
            {
                "conclusion": f"{edge.get('source_id', '')} {edge.get('type', '')} {edge.get('target_id', '')}",
                "status": status,
                "evidence": edge.get("assertion_ref", "graph_edge"),
                "freshness": "current_generation" if edge.get("assertion_ref") else "index_only",
                "risk": "high" if confidence < 0.7 or status in {"INFERRED", "AMBIGUOUS"} else "low",
                "next_action": _next_action(status),
                "action": _action(status),
            }
        )
    return cards


def _next_action(status: str) -> str:
    if status == "VERIFIED":
        return "查看验证来源"
    if status == "INFERRED":
        return "验证高风险推断"
    if status == "AMBIGUOUS":
        return "补充证据或刷新相关索引"
    if status == "STALE":
        return "刷新关联索引"
    if status == "REJECTED":
        return "查看否定决策"
    return "按需展开证据"


def _action(status: str) -> dict[str, Any]:
    if status == "VERIFIED":
        return {"action_type": "inspect_validation", "preconditions": ["status=VERIFIED"], "stop_condition": "validation_source_viewed", "fallback": "inspect_evidence"}
    if status == "INFERRED":
        return {"action_type": "verify_contract", "preconditions": ["status=INFERRED"], "stop_condition": "validation_recorded", "fallback": "request_deep_analysis"}
    if status == "AMBIGUOUS":
        return {"action_type": "refresh_or_collect_evidence", "preconditions": ["status=AMBIGUOUS"], "stop_condition": "evidence_level_resolved", "fallback": "mark_unknown"}
    if status == "STALE":
        return {"action_type": "refresh_index", "preconditions": ["status=STALE"], "stop_condition": "generation_updated", "fallback": "inspect_evidence"}
    if status == "REJECTED":
        return {"action_type": "inspect_rejection", "preconditions": ["status=REJECTED"], "stop_condition": "decision_reviewed", "fallback": "request_deep_analysis"}
    return {"action_type": "inspect_evidence", "preconditions": ["status=EXTRACTED"], "stop_condition": "evidence_reviewed", "fallback": "verify_contract"}
