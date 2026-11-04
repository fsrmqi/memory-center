"""Dependency contract shared by decomposed lookup modules.

The query facade supplies these callbacks; lookup modules never import the
facade back, keeping the dependency direction acyclic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .shared import _build_progressive_levels, summarize_chain_edges


def compress_chain_tree(edges: list[dict[str, Any]]) -> dict[str, Any]:
    tree: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        tree.setdefault(edge.get("source", {}).get("name", "?"), []).append({"target": edge.get("target", {}).get("name", "?"), "type": edge.get("type", ""), "project": edge.get("target", {}).get("project", ""), "depth": edge.get("depth", 0)})
    return {"tree": tree, "depth_reached": max((edge.get("depth", 0) for edge in edges), default=0), "total_edges": len(edges), "unique_sources": len(tree)}


def summarize_chain(edges: list[dict[str, Any]]) -> dict[str, Any]:
    return summarize_chain_edges(edges)


def build_context_evidence(incoming: list[dict[str, Any]], outgoing: list[dict[str, Any]]) -> dict[str, Any]:
    edges = incoming + outgoing
    return {"incoming_edges": len(incoming), "outgoing_edges": len(outgoing), "high_confidence_edges": sum(float(item.get("confidence", 0.0)) >= .8 for item in edges), "edge_types": sorted({item.get("type", "") for item in edges if item.get("type")})}


def build_context_progressive(node: dict[str, Any], incoming: list[dict[str, Any]], outgoing: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_progressive_levels({"node": f"{node.get('type','')}:{node.get('name','')}", "incoming_count": len(incoming), "outgoing_count": len(outgoing)}, {"incoming_edge_types": sorted({item.get("type", "") for item in incoming if item.get("type")}), "outgoing_edge_types": sorted({item.get("type", "") for item in outgoing if item.get("type")}), "high_confidence_edges": [item.get("type", "") for item in incoming + outgoing if float(item.get("confidence", 0.0)) >= .8][:8]}, {"incoming_preview": [f"{item.get('source',{}).get('name','')} -> {item.get('type','')}" for item in incoming[:8]], "outgoing_preview": [f"{item.get('type','')} -> {item.get('target',{}).get('name','')}" for item in outgoing[:8]]})


def build_search_progressive(query: str, scope: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_progressive_levels({"query": query, "scope": scope, "top_hit_count": len(hits), "top_paths": [item.get("path", "") for item in hits[:3]]}, {"top_projects": sorted({item.get("project", "") for item in hits[:5] if item.get("project")}), "scored_hits": [{"path": item.get("path", ""), "score": item.get("score", 0)} for item in hits[:5]]}, {"next_action": "对 top_paths 调用 memory_symbol / memory_context 深挖。", "full_paths": [item.get("path", "") for item in hits]})


@dataclass(frozen=True)
class SymbolLookupPort:
    load_context: Callable[..., Any]
    hybrid_query: Callable[..., dict[str, Any]]
    infer_active_project: Callable[..., str]
    project_matches: Callable[..., bool]
    build_lookup_payload: Callable[..., dict[str, Any]]
    dedupe_symbols: Callable[..., list[dict[str, Any]]]
    rerank_symbols: Callable[..., list[dict[str, Any]]]
    best_match: Callable[..., dict[str, Any]]
    fallback_symbol: Callable[..., dict[str, Any] | None]
    project_evidence: Callable[..., list[dict[str, Any]]]
    augmented_lookup: Callable[..., dict[str, Any]]
    is_compact: Callable[..., bool]
    compact_symbol: Callable[..., dict[str, Any]]
    measure_compact: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ContextLookupPort:
    load_context: Callable[..., Any]
    symbol_resolver: Callable[..., dict[str, Any]]
    build_project_scope: Callable[..., dict[str, Any]]
    project_evidence: Callable[..., list[dict[str, Any]]]
    is_compact: Callable[..., bool]
    compact_context: Callable[..., dict[str, Any]]
    measure_compact: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class NavigationLookupPort:
    load_context: Callable[..., Any]
    symbol_resolver: Callable[..., dict[str, Any]]
    resolve_project: Callable[..., dict[str, Any]]
    project_matches: Callable[..., bool]
    project_evidence: Callable[..., list[dict[str, Any]]]
    build_project_scope: Callable[..., dict[str, Any]]
    preferred_edges: Callable[..., list[str]]
    filter_edges: Callable[..., list[dict[str, Any]]]
    is_compact: Callable[..., bool]
    compact_chain: Callable[..., dict[str, Any]]
    measure_compact: Callable[..., dict[str, Any]]
    symbol_search_text: Callable[..., str]


@dataclass(frozen=True)
class DiagnosticsLookupPort:
    load_context: Callable[..., Any]
    event_payload: Callable[..., dict[str, Any]]
    resolve_ref: Callable[..., dict[str, Any] | None]
    with_schema: Callable[..., dict[str, Any]]
