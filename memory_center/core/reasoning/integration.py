"""Unified reasoning integration — safe bridge from main-chain to reasoning engines.

Provides ``run_reasoning_patterns()`` which orchestrates:
- GraphPatternEngine (structural patterns)
- TransitiveInferenceEngine (transitive relationships)
- RiskPatternEngine (change-risk patterns)

Key constraints (per C-07 acceptance criteria):
- At least one reasoning pattern group enters the main chain (context/impact/analyze).
- Reasoning results carry explanation (``evidence``, ``semantic_strength``, ``confidence``).
- Reasoning never overrides factual results — appended as ``_reasoning`` field.
- No-match returns empty list; execution failure returns diagnostics (never silent).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..diagnostics import DIAG, diag_entry

# Semantic strength constants aligned with ONTOLOGY.md
SEMANTIC_STRENGTH_FACT = "fact"
SEMANTIC_STRENGTH_INFERRED = "inferred"
SEMANTIC_STRENGTH_DERIVED = "derived"

# Reasoning pattern groups
PATTERN_GROUP_GRAPH = "graph_patterns"
PATTERN_GROUP_TRANSITIVE = "transitive_inference"
PATTERN_GROUP_RISK = "risk_patterns"


def _serialize_pattern_match(match: Any) -> Dict[str, Any]:
    if isinstance(match, dict):
        return match
    return {
        "pattern_name": getattr(match, "pattern_name", "unknown"),
        "matched_nodes": getattr(match, "matched_nodes", []),
        "risk_level": getattr(match, "risk_level", "medium"),
        "description": getattr(match, "description", ""),
        "evidence": getattr(match, "evidence", {}),
    }


def _serialize_risk_finding(finding: Any) -> Dict[str, Any]:
    if isinstance(finding, dict):
        return finding
    return {
        "pattern": getattr(finding, "pattern", "unknown"),
        "severity": getattr(finding, "severity", "medium"),
        "description": getattr(finding, "description", ""),
        "affected_nodes": [n if isinstance(n, dict) else {"id": str(n)} for n in getattr(finding, "affected_nodes", [])],
        "checklist": getattr(finding, "checklist", []),
        "evidence": getattr(finding, "evidence", {}),
    }


def _serialize_transitive(rel: Any) -> Dict[str, Any]:
    if isinstance(rel, dict):
        return rel
    return {
        "source_id": getattr(rel, "source_id", ""),
        "target_id": getattr(rel, "target_id", ""),
        "path": getattr(rel, "path", []),
        "edge_types": getattr(rel, "edge_types", []),
        "confidence": getattr(rel, "confidence", 0.5),
    }


def run_reasoning_patterns(
    workspace_file: str,
    target_id: str = "",
    target_name: str = "",
    max_transitive_depth: int = 3,
    max_pattern_limit: int = 20,
) -> Dict[str, Any]:
    """Run all reasoning engines safely.

    Returns dict with keys: patterns, transitive, risk, optionally _diagnostics.
    Each entry carries _semantic_strength, _confidence, _pattern_group, _evidence.
    """
    from ..storage.unified import UnifiedStore
    from ..store import WorkspaceStore

    result: Dict[str, Any] = {
        "patterns": [],
        "transitive": [],
        "risk": [],
    }
    diagnostics: Dict[str, Any] = {}

    ws_path = Path(workspace_file)

    # Validate that the workspace directory actually exists on disk
    # Must happen BEFORE WorkspaceStore which auto-creates directories
    if not ws_path.parent.exists():
        diagnostics["workspace"] = diag_entry(DIAG.UNAVAILABLE, reason="workspace directory does not exist")
        result["_diagnostics"] = diagnostics
        return result

    try:
        ws = WorkspaceStore(workspace_file)
    except Exception as exc:
        diagnostics["workspace"] = diag_entry(DIAG.UNAVAILABLE, exc=exc)
        result["_diagnostics"] = diagnostics
        return result

    graph_db_path = ws.graph_db_path

    # GraphPatternEngine
    try:
        from .patterns import GraphPatternEngine
        with UnifiedStore(graph_db_path) as store:
            engine = GraphPatternEngine(store)
            all_matches = engine.run_all_patterns()
            for pattern_name, matches in all_matches.items():
                for m in matches[:max_pattern_limit]:
                    entry = _serialize_pattern_match(m)
                    entry["_semantic_strength"] = SEMANTIC_STRENGTH_INFERRED
                    entry["_confidence"] = _risk_level_to_confidence(entry.get("risk_level", "medium"))
                    entry["_pattern_group"] = PATTERN_GROUP_GRAPH
                    entry["_evidence"] = "graph pattern: " + entry.get("pattern_name", pattern_name)
                    result["patterns"].append(entry)
    except Exception as exc:
        diagnostics[PATTERN_GROUP_GRAPH] = diag_entry(DIAG.UNAVAILABLE, exc=exc)

    # TransitiveInferenceEngine
    if target_id:
        try:
            from .transitive import TransitiveInferenceEngine
            with UnifiedStore(graph_db_path) as store:
                engine = TransitiveInferenceEngine(store)
                rels = engine.find_transitive_calls(source_id=target_id, max_depth=max_transitive_depth, limit=max_pattern_limit)
                for rel in rels:
                    entry = _serialize_transitive(rel)
                    entry["_semantic_strength"] = SEMANTIC_STRENGTH_DERIVED
                    entry["_confidence"] = entry.get("confidence", 0.5)
                    entry["_pattern_group"] = PATTERN_GROUP_TRANSITIVE
                    entry["_evidence"] = "transitive chain depth=" + str(len(entry.get("path", [])))
                    result["transitive"].append(entry)
        except Exception as exc:
            diagnostics[PATTERN_GROUP_TRANSITIVE] = diag_entry(DIAG.UNAVAILABLE, exc=exc)

    # RiskPatternEngine
    if target_id:
        try:
            from .risk import RiskPatternEngine
            with UnifiedStore(graph_db_path) as store:
                engine = RiskPatternEngine(store, workspace_store=ws)
                risks = engine.analyze_change_risk(target_id)
                for r in risks[:max_pattern_limit]:
                    entry = _serialize_risk_finding(r)
                    entry["_semantic_strength"] = SEMANTIC_STRENGTH_INFERRED
                    entry["_confidence"] = _severity_to_confidence(entry.get("severity", "medium"))
                    entry["_pattern_group"] = PATTERN_GROUP_RISK
                    entry["_evidence"] = "risk pattern: " + entry.get("pattern", "unknown")
                    result["risk"].append(entry)
        except Exception as exc:
            diagnostics[PATTERN_GROUP_RISK] = diag_entry(DIAG.UNAVAILABLE, exc=exc)

    if diagnostics:
        result["_diagnostics"] = diagnostics

    return result


def summarize_reasoning(reasoning: Dict[str, Any]) -> Dict[str, Any]:
    patterns = reasoning.get("patterns", [])
    transitive = reasoning.get("transitive", [])
    risk = reasoning.get("risk", [])
    all_items = patterns + transitive + risk
    if not all_items:
        return {"total_findings": 0, "groups": {}, "diagnostics": reasoning.get("_diagnostics")}
    high_risk = [x for x in all_items if x.get("_confidence", 0) >= 0.8]
    return {
        "total_findings": len(all_items),
        "high_risk_count": len(high_risk),
        "groups": {
            "graph_patterns": len(patterns),
            "transitive_inference": len(transitive),
            "risk_patterns": len(risk),
        },
        "diagnostics": reasoning.get("_diagnostics"),
    }


def _risk_level_to_confidence(risk_level: str) -> float:
    return {"high": 0.9, "medium": 0.6, "low": 0.3}.get(risk_level, 0.5)


def _severity_to_confidence(severity: str) -> float:
    return {"high": 0.9, "medium": 0.6, "low": 0.3}.get(severity, 0.5)
