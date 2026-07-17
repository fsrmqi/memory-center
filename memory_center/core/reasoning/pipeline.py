from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from memory_center.core.assessment.quality import evidence_level_for
from memory_center.core.observability.diagnostics import DIAG, diag_entry

from ..explanation import explanation_entry
from .patterns import GraphPatternEngine
from .request import ReasoningRequest
from .risk import RiskPatternEngine
from .transitive import TransitiveInferenceEngine


class ReasoningPipeline:
    """Evidence-bounded orchestration for the existing reasoning engines."""

    def __init__(self, graph_store: Any, *, workspace_store: Any = None, enabled: bool = True):
        self._store = graph_store
        self._workspace_store = workspace_store
        self._enabled = enabled

    def analyze(self, request: ReasoningRequest) -> dict[str, Any]:
        result = _empty_result(request.evidence_budget, status="ok" if self._enabled else "disabled")
        if not self._enabled:
            return result

        diagnostics: dict[str, Any] = {}
        facts = self._collect_facts(request)
        patterns = []
        if not request.target_id or request.intent in {"workspace", "audit", "scan", "legacy"}:
            patterns = self._collect_safely(
                "graph_patterns", lambda: self._collect_patterns(request), diagnostics
            )
        risks = self._collect_safely(
            "risk_patterns", lambda: self._collect_risks(request), diagnostics
        )
        transitive = self._collect_safely(
            "transitive_inference", lambda: self._collect_transitive(request), diagnostics
        )

        relevant_patterns = [
            item for item in patterns if _pattern_matches_target(item, request.target_id)
        ]
        inferences = [_pattern_inference(item) for item in relevant_patterns]
        inferences.extend(_risk_inference(item, request.target_id) for item in risks)
        derived = [_transitive_derivation(item) for item in transitive]
        candidates = _dedupe(facts + inferences + derived)
        selected = candidates[: request.evidence_budget]

        result.update(
            {
                "facts": [item for item in selected if item["semantic_strength"] == "fact"],
                "inferences": [item for item in selected if item["semantic_strength"] == "inferred"],
                "derived": [item for item in selected if item["semantic_strength"] == "derived"],
                "patterns": patterns,
                "transitive": transitive,
                "risk": risks,
            }
        )
        result["quality"].update(
            {
                "status": "partial" if diagnostics else "ok",
                "evidence_count": len(selected),
                "candidate_count": len(candidates),
                "truncated": len(candidates) > len(selected),
                "verification_required": any(
                    item["semantic_strength"] != "fact" for item in selected
                ),
            }
        )
        if diagnostics:
            result["_diagnostics"] = diagnostics
        return result

    @staticmethod
    def _collect_safely(
        group: str,
        collector: Any,
        diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            return collector()
        except Exception as exc:
            diagnostics[group] = diag_entry(DIAG.UNAVAILABLE, exc=exc)
            return []

    def _collect_facts(self, request: ReasoningRequest) -> list[dict[str, Any]]:
        if not request.target_id:
            return []
        facts: list[dict[str, Any]] = []
        node = self._store.node_by_id(request.target_id)
        if node:
            facts.append(
                _canonical_item(
                    kind="target_node",
                    semantic_strength="fact",
                    source_id=request.target_id,
                    target_id=request.target_id,
                    relations=["INDEXED_NODE"],
                    confidence=1.0,
                    why=f"索引中存在目标节点 {node.get('name', request.target_id)}。",
                    evidence={"node_type": node.get("type", ""), "project": node.get("project", "")},
                )
            )
        for edge in self._store.edges_for_node(
            request.target_id, direction="both", limit=request.evidence_budget
        ):
            facts.append(
                _canonical_item(
                    kind="direct_relation",
                    semantic_strength="fact",
                    source_id=str(edge.get("source_id", "")),
                    target_id=str(edge.get("target_id", "")),
                    relations=[str(edge.get("type", "RELATED"))],
                    confidence=float(edge.get("confidence", 1.0) or 1.0),
                    why=f"图索引记录了直接关系 {edge.get('type', 'RELATED')}。",
                    evidence={"edge_id": edge.get("id", "")},
                )
            )
        return facts

    def _collect_patterns(self, request: ReasoningRequest) -> list[dict[str, Any]]:
        matches = GraphPatternEngine(self._store).run_all_patterns()
        result: list[dict[str, Any]] = []
        for pattern_name, items in matches.items():
            for match in items:
                entry = _serialize_pattern(match)
                entry["_semantic_strength"] = "inferred"
                entry["_confidence"] = _level_confidence(entry.get("risk_level", "medium"))
                entry["_pattern_group"] = "graph_patterns"
                entry["_evidence"] = f"graph pattern: {entry.get('pattern_name', pattern_name)}"
                entry["_explanation"] = explanation_entry(
                    subject=f"reasoning:graph_patterns:{entry.get('pattern_name', pattern_name)}",
                    summary=entry.get("description", "") or entry.get("pattern_name", pattern_name),
                    evidence=_evidence_list(entry.get("evidence")),
                    semantic_strength="inferred",
                    confidence=entry["_confidence"],
                    next_refs=_node_refs(entry.get("matched_nodes", [])),
                )
                result.append(entry)
                if len(result) >= request.evidence_budget:
                    return result
        return result

    def _collect_risks(self, request: ReasoningRequest) -> list[dict[str, Any]]:
        if not request.target_id:
            return []
        findings = RiskPatternEngine(
            self._store, workspace_store=self._workspace_store
        ).analyze_change_risk(request.target_id)
        result = []
        for finding in findings[: request.evidence_budget]:
            entry = _serialize_risk(finding)
            entry["_semantic_strength"] = "inferred"
            entry["_confidence"] = _level_confidence(entry.get("severity", "medium"))
            entry["_pattern_group"] = "risk_patterns"
            entry["_evidence"] = f"risk pattern: {entry.get('pattern', 'unknown')}"
            entry["_explanation"] = explanation_entry(
                subject=f"reasoning:risk_patterns:{entry.get('pattern', 'unknown')}",
                summary=entry.get("description", "") or entry.get("pattern", "unknown"),
                evidence=_evidence_list(entry.get("evidence")),
                semantic_strength="inferred",
                confidence=entry["_confidence"],
                next_refs=_node_refs(entry.get("affected_nodes", []))
                or [{"id": request.target_id, "name": request.target_id}],
            )
            result.append(entry)
        return result

    def _collect_transitive(self, request: ReasoningRequest) -> list[dict[str, Any]]:
        if not request.target_id:
            return []
        relations = TransitiveInferenceEngine(self._store).find_transitive_calls(
            source_id=request.target_id,
            max_depth=request.max_depth,
            limit=request.evidence_budget,
        )
        result = []
        for relation in relations:
            entry = _serialize_transitive(relation)
            entry["_semantic_strength"] = "derived"
            entry["_confidence"] = float(entry.get("confidence", 0.5) or 0.5)
            entry["_pattern_group"] = "transitive_inference"
            entry["_evidence"] = f"transitive chain depth={len(entry.get('path', []))}"
            entry["_explanation"] = explanation_entry(
                subject=f"reasoning:transitive_inference:{entry.get('source_id', '')}",
                summary=f"传递链路 depth={len(entry.get('path', []))}",
                evidence=[{"path": entry.get("path", []), "edge_types": entry.get("edge_types", [])}],
                semantic_strength="derived",
                confidence=entry["_confidence"],
                next_refs=[{"id": item, "name": item} for item in entry.get("path", [])[:10]],
            )
            result.append(entry)
        return result


def _empty_result(evidence_budget: int, *, status: str) -> dict[str, Any]:
    return {
        "facts": [],
        "inferences": [],
        "derived": [],
        "patterns": [],
        "transitive": [],
        "risk": [],
        "quality": {
            "status": status,
            "evidence_budget": evidence_budget,
            "evidence_count": 0,
            "candidate_count": 0,
            "truncated": False,
            "verification_required": False,
        },
    }


def _canonical_item(
    *,
    kind: str,
    semantic_strength: str,
    source_id: str,
    target_id: str,
    relations: list[str],
    confidence: float,
    why: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "semantic_strength": semantic_strength,
        "evidence_level": evidence_level_for({"semantic_strength": semantic_strength}),
        "source_id": source_id,
        "target_id": target_id,
        "relations": relations,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "why": why,
        "evidence": evidence,
    }


def _pattern_inference(entry: dict[str, Any]) -> dict[str, Any]:
    refs = _node_refs(entry.get("matched_nodes", []))
    source_id = refs[0]["id"] if refs else f"pattern:{entry.get('pattern_name', 'unknown')}"
    return _canonical_item(
        kind="graph_pattern",
        semantic_strength="inferred",
        source_id=source_id,
        target_id=source_id,
        relations=["MATCHES_PATTERN"],
        confidence=float(entry.get("_confidence", 0.5)),
        why=entry.get("description", "") or f"命中图模式 {entry.get('pattern_name', 'unknown')}。",
        evidence=entry.get("evidence", {}) or {},
    )


def _pattern_matches_target(entry: dict[str, Any], target_id: str) -> bool:
    if not target_id:
        return True
    return any(
        isinstance(node, dict) and str(node.get("id", "")) == target_id
        for node in entry.get("matched_nodes", []) or []
    )


def _risk_inference(entry: dict[str, Any], target_id: str) -> dict[str, Any]:
    return _canonical_item(
        kind="risk_pattern",
        semantic_strength="inferred",
        source_id=target_id,
        target_id=target_id,
        relations=["HAS_RISK"],
        confidence=float(entry.get("_confidence", 0.5)),
        why=entry.get("description", "") or f"命中风险模式 {entry.get('pattern', 'unknown')}。",
        evidence=entry.get("evidence", {}) or {},
    )


def _transitive_derivation(entry: dict[str, Any]) -> dict[str, Any]:
    relations = [str(item) for item in entry.get("edge_types", []) if item]
    return _canonical_item(
        kind="transitive_relation",
        semantic_strength="derived",
        source_id=str(entry.get("source_id", "")),
        target_id=str(entry.get("target_id", "")),
        relations=relations or ["TRANSITIVE"],
        confidence=float(entry.get("_confidence", 0.5)),
        why=f"由 {' -> '.join(relations or ['TRANSITIVE'])} 关系链推导。",
        evidence={"path": entry.get("path", [])},
    )


def _dedupe(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in items:
        key = (
            item.get("kind", ""),
            item.get("source_id", ""),
            item.get("target_id", ""),
            tuple(item.get("relations", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _serialize_pattern(match: Any) -> dict[str, Any]:
    if isinstance(match, dict):
        return dict(match)
    return {
        "pattern_name": getattr(match, "pattern_name", "unknown"),
        "matched_nodes": getattr(match, "matched_nodes", []),
        "risk_level": getattr(match, "risk_level", "medium"),
        "description": getattr(match, "description", ""),
        "evidence": getattr(match, "evidence", {}),
    }


def _serialize_risk(finding: Any) -> dict[str, Any]:
    if isinstance(finding, dict):
        return dict(finding)
    return {
        "pattern": getattr(finding, "pattern", "unknown"),
        "severity": getattr(finding, "severity", "medium"),
        "description": getattr(finding, "description", ""),
        "affected_nodes": [
            node if isinstance(node, dict) else {"id": str(node)}
            for node in getattr(finding, "affected_nodes", [])
        ],
        "checklist": getattr(finding, "checklist", []),
        "evidence": getattr(finding, "evidence", {}),
    }


def _serialize_transitive(relation: Any) -> dict[str, Any]:
    if isinstance(relation, dict):
        return dict(relation)
    return {
        "source_id": getattr(relation, "source_id", ""),
        "target_id": getattr(relation, "target_id", ""),
        "path": getattr(relation, "path", []),
        "edge_types": getattr(relation, "edge_types", []),
        "confidence": getattr(relation, "confidence", 0.5),
    }


def _level_confidence(level: str) -> float:
    return {"high": 0.9, "medium": 0.6, "low": 0.3}.get(str(level), 0.5)


def _evidence_list(evidence: Any) -> list[dict[str, Any]]:
    return [evidence] if isinstance(evidence, dict) and evidence else []


def _node_refs(nodes: Any) -> list[dict[str, str]]:
    refs = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", "") or "")
        if node_id:
            refs.append({"id": node_id, "name": str(node.get("name", "") or "")})
    return refs[:10]
