"""Project glossary extractor — discover domain-specific terms from code.

Scans class names, method names, annotations, and configuration keys to
build a project-specific glossary that helps newcomers understand domain
terminology.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..storage.unified import UnifiedStore


@dataclass
class GlossaryEntry:
    """A single glossary term."""
    term: str
    category: str  # service | class | annotation | config | domain
    frequency: int = 1
    examples: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "term": self.term,
            "category": self.category,
            "frequency": self.frequency,
            "examples": self.examples[:3],
            "description": self.description,
        }


def _split_camel(name: str) -> List[str]:
    """Split CamelCase into words."""
    return [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", name) if len(w) > 1]


class GlossaryExtractor:
    """Extract project-specific glossary from the code knowledge graph."""

    def __init__(self, store: UnifiedStore):
        self._store = store

    def extract(self, limit: int = 50) -> List[GlossaryEntry]:
        """Extract glossary terms sorted by frequency."""
        terms: Dict[str, GlossaryEntry] = {}
        counter: Counter = Counter()

        nodes = self._store.all_nodes()

        for node in nodes:
            node_type = node.get("type", "")
            name = node.get("name", "")

            # Service names
            if node_type == "Service" and name:
                key = f"service:{name}"
                counter[key] += 1
                if key not in terms:
                    terms[key] = GlossaryEntry(
                        term=name, category="service",
                        description=f"服务: {name}",
                    )
                terms[key].frequency = counter[key]

            # Class names → split CamelCase for domain terms
            if node_type in ("Class", "Interface"):
                words = _split_camel(name)
                for w in words:
                    if len(w) >= 3:
                        key = f"class:{w}"
                        counter[key] += 1
                        if key not in terms:
                            terms[key] = GlossaryEntry(term=w, category="class")
                        terms[key].frequency = counter[key]
                        if name not in terms[key].examples:
                            terms[key].examples.append(name)

            # Annotations
            meta = node.get("metadata", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            annotations = meta.get("annotations", []) if isinstance(meta, dict) else []
            for ann in annotations:
                ann_str = str(ann)
                key = f"annotation:{ann_str}"
                counter[key] += 1
                if key not in terms:
                    terms[key] = GlossaryEntry(term=ann_str, category="annotation")
                terms[key].frequency = counter[key]

            # Config keys
            if node_type == "ConfigKey" and name:
                parts = name.split(".")
                for part in parts:
                    if len(part) >= 3:
                        key = f"config:{part}"
                        counter[key] += 1
                        if key not in terms:
                            terms[key] = GlossaryEntry(term=part, category="config")
                        terms[key].frequency = counter[key]
                        terms[key].examples = [name]

        # Sort by frequency and return top entries
        sorted_terms = sorted(terms.values(), key=lambda e: -e.frequency)
        return sorted_terms[:limit]

    def search(self, query: str, limit: int = 10) -> List[GlossaryEntry]:
        """Search glossary by partial term match."""
        query_lower = query.lower()
        all_terms = self.extract(limit=200)
        matches = [t for t in all_terms if query_lower in t.term.lower()]
        return matches[:limit]
