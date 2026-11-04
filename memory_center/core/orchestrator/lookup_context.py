"""Context lookup aggregation separated from the hybrid-query facade."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from .lookup_shared import ContextLookupPort, build_context_evidence, build_context_progressive


def build_context(workspace_file: str | Path, name: str, *, max_depth: int = 2, project: str = "", view: str = "full", budget: str = "medium", deps: ContextLookupPort) -> dict[str, Any]:
    from memory_center.core.observability.diagnostics import DIAG, diag_entry
    from memory_center.core.observability.tracking import log_token_gain
    from memory_center.core.storage.runtime import RuntimeStore
    _, store = deps.load_context(workspace_file)
    symbol_info = deps.symbol_resolver(workspace_file, name, limit=8, project=project)
    if not symbol_info.get("found"):
        return {"name": name, "found": False, "matches": [], "lookup": symbol_info.get("lookup", {})}
    node = symbol_info.get("best_match", {}) or {}
    with RuntimeStore(store.graph_db_path) as graph:
        incoming = graph.traverse_edges(node["id"], direction="upstream", max_depth=max_depth, limit=100)
        outgoing = graph.traverse_edges(node["id"], direction="downstream", max_depth=max_depth, limit=100)
    reasoning: dict[str, Any] = {"patterns": [], "transitive": [], "risk": []}; diagnostics: dict[str, Any] = {}
    try:
        from ..reasoning.integration import run_reasoning_patterns
        reasoning = run_reasoning_patterns(str(workspace_file), target_id=node.get("id", ""), target_name=name, intent="context")
    except Exception as exc:
        diagnostics["reasoning"] = diag_entry(DIAG.UNAVAILABLE, exc=exc)
    freshness = {}
    try:
        from ..freshness.status import IndexFreshnessService
        freshness = IndexFreshnessService(workspace_file).banner()
    except Exception as exc:
        diagnostics["freshness"] = diag_entry(DIAG.UNAVAILABLE, exc=exc)
    result = {"name": name, "found": True, "node": node, "incoming": incoming, "outgoing": outgoing,
              "lookup": symbol_info.get("lookup", {}), "project_scope": deps.build_project_scope(project, node),
              "project_evidence": deps.project_evidence(symbol_info.get("matches", []), node, project),
              "evidence_summary": build_context_evidence(incoming, outgoing),
              "progressive": build_context_progressive(node, incoming, outgoing),
              "risk_patterns": reasoning.get("risk", []), "freshness": freshness, "_reasoning": reasoning}
    if diagnostics: result["_diagnostics"] = diagnostics
    if deps.is_compact(view):
        compact = deps.compact_context(result, budget=budget); gain = deps.measure_compact(result, compact)
        log_token_gain(workspace_file, "memory_context", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result
