"""Business domain extractor — infer business domains from code structure.

Maps code entities (controllers, services, MQ consumers) to business domains
based on naming conventions, package structure, and annotation metadata.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..storage.unified import UnifiedStore


# Domain keywords derived from common Spring Cloud patterns
_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "user": ["user", "account", "auth", "login", "register", "member", "profile", "person"],
    "order": ["order", "purchase", "trade", "checkout", "cart", "payment"],
    "payment": ["payment", "pay", "refund", "billing", "charge", "transaction", "wallet"],
    "notification": ["notification", "message", "sms", "email", "push", "alert"],
    "product": ["product", "item", "goods", "inventory", "stock", "catalog"],
    "logistics": ["logistics", "shipping", "delivery", "express", "tracking", "warehouse"],
    "config": ["config", "setting", "preference", "option", "param"],
    "audit": ["audit", "log", "trace", "monitor", "metric"],
    "gateway": ["gateway", "route", "proxy", "filter", "rate-limit"],
    "scheduler": ["scheduler", "job", "task", "cron", "timer"],
}


@dataclass
class BusinessDomain:
    """A discovered business domain."""
    domain_id: str
    name: str
    description: str = ""
    services: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)  # node IDs
    confidence: float = 0.7
    keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "name": self.name,
            "description": self.description,
            "services": self.services,
            "entities": self.entities,
            "confidence": self.confidence,
            "keywords": self.keywords,
        }


@dataclass
class BusinessFlow:
    """A business flow through the system."""
    flow_id: str
    name: str
    domain: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "name": self.name,
            "domain": self.domain,
            "steps": self.steps,
            "confidence": self.confidence,
        }


class BusinessDomainExtractor:
    """Extract business domains from the code knowledge graph."""

    def __init__(self, store: UnifiedStore):
        self._store = store

    def extract_domains(self) -> List[BusinessDomain]:
        """Extract business domains from node names, packages, and annotations."""
        nodes = self._store.all_nodes()
        domain_map: Dict[str, BusinessDomain] = {}

        for node in nodes:
            node_type = node.get("type", "")
            node_name = node.get("name", "")
            project = node.get("project", "")
            file_path = node.get("file_path", "")
            metadata = node.get("metadata", {})

            # Infer domain from name/path/project
            domain_name = self._infer_domain(node_name, file_path, project, metadata)
            if not domain_name:
                continue

            if domain_name not in domain_map:
                domain_map[domain_name] = BusinessDomain(
                    domain_id=f"domain:{domain_name}",
                    name=domain_name,
                    description=f"业务域: {domain_name}",
                    keywords=_DOMAIN_KEYWORDS.get(domain_name, []),
                )

            domain = domain_map[domain_name]
            domain.entities.append(node.get("id", ""))
            if project and project not in domain.services:
                domain.services.append(project)

        # Calculate confidence based on entity count
        for domain in domain_map.values():
            entity_count = len(domain.entities)
            if entity_count >= 10:
                domain.confidence = 0.9
            elif entity_count >= 5:
                domain.confidence = 0.7
            else:
                domain.confidence = 0.5

        return sorted(domain_map.values(), key=lambda d: -d.confidence)

    def extract_flows(self) -> List[BusinessFlow]:
        """Extract business flows by tracing endpoint → service → MQ chains."""
        flows: List[BusinessFlow] = []

        # Find all endpoints
        endpoints = [
            n for n in self._store.all_nodes()
            if n.get("type") in ("Endpoint",)
        ]

        for ep in endpoints:
            ep_id = ep.get("id", "")
            ep_name = ep.get("name", "")
            project = ep.get("project", "")

            # Trace upstream from endpoint to find the controller that exposes it,
            # then trace downstream from the controller through the service layer.
            upstream = self._store.neighbors(ep_id, direction="upstream", max_depth=1, limit=10)
            downstream: list = []
            for parent in upstream:
                parent_id = parent.get("id", "")
                if parent_id:
                    downstream.extend(
                        self._store.neighbors(parent_id, direction="downstream", max_depth=2, limit=15)
                    )

            all_related = upstream + downstream
            if not all_related:
                continue

            steps: list[dict] = [{"node_id": ep_id, "name": ep_name, "type": "endpoint", "order": 0}]
            seen_ids: set = {ep_id}
            order = 1
            for node in all_related[:10]:
                nid = node.get("id", "")
                if nid in seen_ids:
                    continue
                seen_ids.add(nid)
                steps.append({
                    "node_id": nid,
                    "name": node.get("name", ""),
                    "type": node.get("type", ""),
                    "order": order,
                })
                order += 1

            # Infer flow name from endpoint
            flow_name = self._infer_flow_name(ep_name, project)
            domain = self._infer_domain(ep_name, ep.get("file_path", ""), project, ep.get("metadata", {}))

            flows.append(BusinessFlow(
                flow_id=f"flow:{project}:{ep_name}",
                name=flow_name,
                domain=domain or "general",
                steps=steps,
                confidence=min(0.9, 0.5 + 0.1 * len(steps)),
            ))

        return sorted(flows, key=lambda f: -f.confidence)

    def _infer_domain(self, name: str, file_path: str, project: str, metadata: Dict[str, Any]) -> str:
        """Infer the business domain from node attributes."""
        combined = f"{name} {file_path} {project}".lower()
        annotations = metadata.get("annotations", [])
        if isinstance(annotations, list):
            combined += " " + " ".join(str(a).lower() for a in annotations)

        best_domain = ""
        best_score = 0
        for domain_name, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in combined)
            if score > best_score:
                best_score = score
                best_domain = domain_name

        return best_domain if best_score >= 1 else ""

    def _infer_flow_name(self, endpoint_name: str, project: str) -> str:
        """Generate a human-readable flow name."""
        # e.g. "POST /api/users" → "用户创建流程"
        method_path = endpoint_name.strip()
        parts = method_path.split()
        if len(parts) >= 2:
            path = parts[1]
            segments = [s for s in path.split("/") if s and not s.startswith("{")]
            if segments:
                return f"{project}:{ '/'.join(segments) }"
        return f"{project}:{endpoint_name}"
