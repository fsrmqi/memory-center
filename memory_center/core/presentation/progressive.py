"""Progressive disclosure helpers — build level 1/2/3 views for any result set.

Extracted from orchestrator/common.py to reduce file size and enable reuse.
"""
from __future__ import annotations

from typing import Any, Dict, List


def build_progressive_levels(
    level_1: Dict[str, Any],
    level_2: Dict[str, Any],
    level_3: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a 3-level progressive disclosure structure.

    Level 1: Quick summary (always shown in compact mode)
    Level 2: Details (shown on request or in full mode)
    Level 3: Full context (shown only when explicitly requested)
    """
    return {
        "level_1_quick": level_1,
        "level_2_details": level_2,
        "level_3_full": level_3,
    }


def build_query_progressive_view(
    query: str,
    matches: List[Dict[str, Any]],
    semantic_hits: List[Dict[str, Any]],
    related_cases: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build progressive view for query results."""
    top_nodes = [item.get("node", {}) for item in matches[:3]]
    return build_progressive_levels(
        {
            "query": query,
            "top_nodes": [f"{item.get('type', '')}:{item.get('name', '')}" for item in top_nodes if item.get("name")],
            "top_sources": [item.get("retrieval_sources", []) for item in matches[:3]],
        },
        {
            "entrypoints": [
                {
                    "id": item.get("node", {}).get("id", ""),
                    "type": item.get("node", {}).get("type", ""),
                    "name": item.get("node", {}).get("name", ""),
                    "score": item.get("exact_score", item.get("score", 0.0)),
                }
                for item in matches[:5]
            ],
            "semantic_candidates": [
                {"node_id": item.get("node_id", ""), "name": item.get("node", {}).get("name", ""), "score": item.get("score", 0.0)}
                for item in semantic_hits[:5]
            ],
        },
        {
            "neighbor_preview": {
                item.get("node", {}).get("name", ""): [edge.get("type", "") for edge in item.get("neighbors", [])[:4]]
                for item in matches[:3]
            },
            "related_case_tasks": [item.get("task", "") for item in related_cases[-3:]],
        },
    )


def build_context_progressive_view(
    node: Dict[str, Any],
    incoming: List[Dict[str, Any]],
    outgoing: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build progressive view for context (node + neighbors)."""
    return build_progressive_levels(
        {
            "node": f"{node.get('type', '')}:{node.get('name', '')}",
            "incoming_count": len(incoming),
            "outgoing_count": len(outgoing),
        },
        {
            "incoming_edge_types": sorted({item.get("type", "") for item in incoming if item.get("type")}),
            "outgoing_edge_types": sorted({item.get("type", "") for item in outgoing if item.get("type")}),
        },
        {
            "incoming_preview": [f"{item.get('source', {}).get('name', '')} -> {item.get('type', '')}" for item in incoming[:8]],
            "outgoing_preview": [f"{item.get('type', '')} -> {item.get('target', {}).get('name', '')}" for item in outgoing[:8]],
        },
    )
