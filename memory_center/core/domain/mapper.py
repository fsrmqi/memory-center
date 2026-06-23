"""Code entity → business domain mapper.

Maps individual code entities (classes, methods, endpoints) to their
business domain based on naming conventions, package structure, and
graph relationships.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..storage.unified import UnifiedStore
from .extractor import _DOMAIN_KEYWORDS


@dataclass
class DomainMapping:
    """Mapping result for a single code entity."""
    node_id: str
    node_name: str
    node_type: str
    domain: str
    confidence: float
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "domain": self.domain,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
        }


class CodeEntityDomainMapper:
    """Map code entities to business domains.

    Uses multiple signals:
    1. Name/path keyword matching
    2. Service-level domain inference
    3. Graph neighborhood domain propagation
    """

    def __init__(self, store: UnifiedStore):
        self._store = store
        self._service_domain_cache: Dict[str, str] = {}

    def map_entity(self, node_id: str) -> Optional[DomainMapping]:
        """Map a single code entity to its business domain."""
        node = self._store.node_by_id(node_id)
        if not node:
            return None

        name = node.get("name", "")
        file_path = node.get("file_path", "")
        project = node.get("project", "")
        node_type = node.get("type", "")
        meta = node.get("metadata", {})
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                meta = {}

        # 1. Direct name/path matching
        domain, confidence, evidence = self._match_name(name, file_path, project, meta)

        # 2. If low confidence, check service-level mapping
        if confidence < 0.5 and project:
            svc_domain = self._infer_service_domain(project)
            if svc_domain:
                domain = svc_domain
                confidence = 0.6
                evidence = f"服务级推断: {project}"

        # 3. If still low, check graph neighbors
        if confidence < 0.5:
            neighbor_domain = self._infer_from_neighbors(node_id)
            if neighbor_domain:
                domain = neighbor_domain
                confidence = 0.5
                evidence = "图邻居推断"

        if not domain:
            domain = "general"
            confidence = 0.1
            evidence = "无法推断"

        return DomainMapping(
            node_id=node_id,
            node_name=name,
            node_type=node_type,
            domain=domain,
            confidence=confidence,
            evidence=evidence,
        )

    def map_batch(
        self,
        node_ids: Optional[List[str]] = None,
        node_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[DomainMapping]:
        """Map multiple entities to domains."""
        if node_ids:
            results = []
            for nid in node_ids[:limit]:
                mapping = self.map_entity(nid)
                if mapping:
                    results.append(mapping)
            return results

        nodes = self._store.all_nodes()
        if node_type:
            nodes = [n for n in nodes if n.get("type") == node_type]

        results = []
        for node in nodes[:limit]:
            nid = node.get("id", "")
            if nid:
                mapping = self.map_entity(nid)
                if mapping:
                    results.append(mapping)
        return results

    def domain_summary(self) -> Dict[str, Any]:
        """Get a summary of domain distribution across all entities."""
        all_mappings = self.map_batch(limit=1000)
        domain_counts: Dict[str, int] = {}
        domain_entities: Dict[str, List[str]] = {}

        for m in all_mappings:
            domain_counts[m.domain] = domain_counts.get(m.domain, 0) + 1
            domain_entities.setdefault(m.domain, []).append(m.node_name)

        return {
            "total_entities": len(all_mappings),
            "domain_counts": domain_counts,
            "domains": sorted(domain_counts.keys()),
            "top_entities_per_domain": {
                d: names[:5] for d, names in domain_entities.items()
            },
        }

    def _match_name(self, name: str, file_path: str, project: str, meta: Dict) -> tuple:
        """Match entity name against domain keywords."""
        combined = f"{name} {file_path} {project}".lower()
        annotations = meta.get("annotations", [])
        if isinstance(annotations, list):
            combined += " " + " ".join(str(a).lower() for a in annotations)

        best_domain = ""
        best_score = 0
        for domain_name, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in combined)
            if score > best_score:
                best_score = score
                best_domain = domain_name

        if best_score >= 2:
            return best_domain, 0.8, f"关键词匹配: {best_score} 个关键词"
        elif best_score == 1:
            return best_domain, 0.5, "关键词匹配: 1 个关键词"
        return "", 0.0, ""

    def _infer_service_domain(self, project: str) -> str:
        """Infer domain from service name."""
        if project in self._service_domain_cache:
            return self._service_domain_cache[project]

        project_lower = project.lower()
        for domain_name, keywords in _DOMAIN_KEYWORDS.items():
            for kw in keywords:
                if kw in project_lower:
                    self._service_domain_cache[project] = domain_name
                    return domain_name

        return ""

    def _infer_from_neighbors(self, node_id: str, max_depth: int = 1) -> str:
        """Infer domain from graph neighbors."""
        neighbors = self._store.neighbors(node_id, direction="both", max_depth=max_depth, limit=10)
        domain_votes: Dict[str, int] = {}

        for neighbor in neighbors:
            n_name = neighbor.get("name", "")
            n_project = neighbor.get("project", "")
            n_file = neighbor.get("file_path", "")
            domain, conf, _ = self._match_name(n_name, n_file, n_project, {})
            if domain and conf >= 0.5:
                domain_votes[domain] = domain_votes.get(domain, 0) + 1

        if domain_votes:
            return max(domain_votes, key=domain_votes.get)
        return ""
