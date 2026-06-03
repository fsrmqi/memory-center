"""ContextPackBuilder — build compact, evidence-backed context for coding agents.

This is the V3 "agent reads less files" layer.  Instead of returning raw node
lists, it assembles a self-contained context package with:
- entrypoints (top matching nodes)
- relationships (neighbors)
- snippets (minimal code excerpts)
- risks (matched risk patterns)
- checklist (actionable verification steps)
- freshness (index staleness warnings)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage.unified import UnifiedStore
from ..graph import GraphStore
from ..retrieval.hybrid import hybrid_retrieve, HybridRetrievalConfig, detect_query_intent
from ..rules import match_rules


@dataclass
class ContextPack:
    """Self-contained context package for a coding agent."""
    query: str
    intent: str
    entrypoints: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    snippets: List[Dict[str, Any]] = field(default_factory=list)
    risks: List[Dict[str, Any]] = field(default_factory=list)
    checklist: List[str] = field(default_factory=list)
    freshness: Dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0
    progressive: Dict[str, Any] = field(default_factory=dict)


class ContextPackBuilder:
    """Build compact context packs that reduce Agent grep/read cycles."""

    def __init__(self, workspace_file: str | Path):
        self._workspace_file = str(workspace_file)
        from ..store import WorkspaceStore
        self._store = WorkspaceStore(workspace_file)
        self._config = self._store._config if hasattr(self._store, '_config') else None

    def build(
        self,
        query: str,
        intent: str = "auto",
        budget_tokens: int = 8000,
        limit: int = 10,
    ) -> ContextPack:
        """Build a context pack for the given query."""
        # 1. Detect intent
        if intent == "auto":
            intent_info = detect_query_intent(query)
            primary_intent = intent_info.get("primary_intent", "general")
        else:
            primary_intent = intent

        # 2. Retrieve entrypoints via hybrid retrieval
        retrieval = hybrid_retrieve(
            graph=self._get_graph(),
            workspace_file=self._workspace_file,
            query=query,
            config=HybridRetrievalConfig(max_results=limit),
            limit=limit,
        )
        results = retrieval.get("results", [])

        # 3. Expand relationships for top entrypoints
        relationships = []
        for item in results[:5]:
            node = item.get("node", {})
            node_id = node.get("id", "")
            if node_id:
                with GraphStore(self._store.graph_db_path) as graph:
                    incoming = graph.neighbors(node_id, direction="upstream", max_depth=1, limit=10)
                    outgoing = graph.neighbors(node_id, direction="downstream", max_depth=1, limit=10)
                relationships.extend(incoming[:5])
                relationships.extend(outgoing[:5])

        # 4. Match risk patterns / rules
        files = list({item.get("node", {}).get("file_path", "") for item in results[:5] if item.get("node", {}).get("file_path")})
        risks = match_rules(self._store, intent=query, files=files)[:5]

        # 5. Build checklist from risks
        checklist = []
        for risk in risks:
            for item in risk.get("checklist", []):
                if item not in checklist:
                    checklist.append(item)

        # 6. Estimate token usage
        total_text = json.dumps(results[:5], ensure_ascii=False) + json.dumps(relationships, ensure_ascii=False)
        token_estimate = len(total_text) // 4  # rough estimate

        # 7. Build progressive disclosure
        progressive = {
            "level_1_quick": {
                "entrypoint_count": len(results),
                "top_matches": [
                    {"type": item.get("node", {}).get("type", ""), "name": item.get("node", {}).get("name", ""), "score": round(item.get("score", 0), 2)}
                    for item in results[:3]
                ],
                "intent": primary_intent,
            },
            "level_2_relationships": {
                "relationship_count": len(relationships),
                "risk_count": len(risks),
                "checklist_items": len(checklist),
            },
            "level_3_next_actions": _suggest_next_actions(primary_intent, results, risks),
        }

        return ContextPack(
            query=query,
            intent=primary_intent,
            entrypoints=[{"node": item.get("node", {}), "score": item.get("score", 0), "sources": item.get("sources", [])} for item in results],
            relationships=relationships,
            snippets=[],  # TODO: extract code snippets from files
            risks=risks,
            checklist=checklist,
            freshness={},  # TODO: integrate freshness service
            token_estimate=token_estimate,
            progressive=progressive,
        )

    def _get_graph(self) -> GraphStore:
        gs = GraphStore(self._store.graph_db_path)
        return gs


def _suggest_next_actions(intent: str, results: list, risks: list) -> list[str]:
    actions = []
    if intent == "feign":
        actions.append("调用 mc_lookup(mode='context') 查看 Feign 客户端详情")
        actions.append("调用 mc_analyze 检查跨服务影响面")
    elif intent == "mq":
        actions.append("检查 mq-index.json 获取完整消息链路")
        actions.append("确认消费幂等性")
    elif intent == "endpoint":
        actions.append("调用 mc_lookup(mode='chain') 追踪调用链")
    else:
        actions.append("对 top 结果调用 mc_context 深挖")
    if risks:
        actions.append(f"注意 {len(risks)} 条风险规则已触发")
    return actions
