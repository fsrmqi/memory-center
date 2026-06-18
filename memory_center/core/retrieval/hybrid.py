"""Hybrid retrieval engine — combines graph, sparse (FTS), and semantic search with intelligent routing.

This module implements the hybrid retrieval strategy from NEXT_PHASE_MASTER_PLAN Phase A:
- Graph traversal for structural relationships (callers, callees, chains)
- Sparse/FTS search for exact matches and keyword lookup
- Semantic search for fuzzy/conceptual matches
- Intelligent routing based on query characteristics
- Summary layer for cross-workspace links
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..graph import GraphStore
from ..semantic import semantic_query
from ..diagnostics import DIAG, diag_entry
from ..ontology import (
    EntityValidator,
    annotate_semantic_strength,
    EDGE_SEMANTIC_STRENGTH,
    multi_hop_confidence,
)

__all__ = [
    "EntityValidator",
    "HybridRetrievalConfig",
    "RetrievalResult",
    "annotate_semantic_strength",
    "detect_query_intent",
    "hybrid_retrieve",
    "multi_hop_confidence",
]


def _get_common_functions():
    """Lazy import to avoid circular dependency."""
    from ..orchestrator.common import tokenize, _rrf, _best_match
    return tokenize, _rrf, _best_match



# Ontology semantic strength mapping (from docs/ONTOLOGY.md §3.1)
_EDGE_SEMANTIC_STRENGTH = {
    # Ontology semantic strength — now sourced from ontology module (§3.1)
}
# Merge ontology module's edge strength into local lookup
_EDGE_SEMANTIC_STRENGTH.update(EDGE_SEMANTIC_STRENGTH)


@dataclass
class RetrievalResult:
    """Unified retrieval result with provenance tracking."""
    node_id: str
    node: Dict[str, Any]
    score: float = 0.0
    sources: List[str] = field(default_factory=list)  # graph, sparse, semantic
    evidence: Dict[str, Any] = field(default_factory=dict)
    neighbors: List[Dict[str, Any]] = field(default_factory=list)
    cross_workspace_refs: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class HybridRetrievalConfig:
    """Configuration for hybrid retrieval routing."""
    # Weight for each retrieval source
    graph_weight: float = 0.4
    sparse_weight: float = 0.35
    semantic_weight: float = 0.25

    # Thresholds
    min_confidence: float = 0.3
    max_results: int = 20
    neighbor_depth: int = 2
    neighbor_limit: int = 50

    # Vector retrieval weight
    vector_weight: float = 0.15

    # Feature flags
    enable_cross_workspace: bool = True
    enable_summary_layer: bool = True
    enable_type_boosting: bool = True
    enable_sparse_bm25: bool = True
    enable_vector: bool = False


# Query pattern detection
_QUERY_PATTERNS = {
    "feign": re.compile(r"feign|fegin|远程调用|rpc", re.IGNORECASE),
    "mq": re.compile(r"kafka|rocketmq|topic|consumer|producer|消息队列|mq", re.IGNORECASE),
    "endpoint": re.compile(r"/[a-z]|controller|api|接口|endpoint", re.IGNORECASE),
    "config": re.compile(r"config|配置|properties|yaml|yml", re.IGNORECASE),
    "chain": re.compile(r"调用链|call.?chain|trace|跟踪", re.IGNORECASE),
    "class": re.compile(r"class|类|service|impl|dao|mapper|repository", re.IGNORECASE),
    "method": re.compile(r"方法|method|function|函数", re.IGNORECASE),
}

# Java 命名模式推断
_JAVA_PATTERNS = {
    "feign": re.compile(
        r"(^Fegin[A-Z][a-zA-Z]*Service$)|"
        r"(^Feign[A-Z][a-zA-Z]*Service$)|"
        r"(^[A-Z][a-zA-Z]*Feign(Client|Service)?$)",
        re.IGNORECASE,
    ),
    "endpoint": re.compile(r"Controller$|Resource$|Api$", re.IGNORECASE),
    "class": re.compile(r"Service$|ServiceImpl$|Impl$|Dao$|Mapper$|Repository$", re.IGNORECASE),
    "method": re.compile(r"^[a-z][a-zA-Z0-9_]*([A-Z][a-z0-9_]*)+$"),
}


def _normalize_java_symbol_query(query: str) -> str:
    normalized = (query or "").strip().replace("#", ".")
    if not normalized:
        return ""
    return normalized.split(".")[-1]


def _looks_like_java_symbol_query(query: str) -> bool:
    token = _normalize_java_symbol_query(query)
    if not token:
        return False
    if any(ch.isspace() for ch in query):
        return False
    return bool(re.match(r"^[A-Z][A-Za-z0-9_]*$", token))


def _node_matches_query_name(node: Dict[str, Any], query: str) -> bool:
    target = _normalize_java_symbol_query(query).lower()
    if not target:
        return False
    name = str(node.get("name", "") or "").strip()
    if not name:
        return False
    short = name.split(".")[-1].lower()
    return short == target or name.lower() == target


def _has_exact_like_source(item: RetrievalResult) -> bool:
    return any(source in {"graph_exact", "graph_token", "sparse_fts", "sparse_bm25"} for source in item.sources)


def detect_query_intent(query: str) -> Dict[str, Any]:
    """Detect query intent from natural language input.

    Returns intent classification with confidence scores.
    """
    query_lower = query.lower()
    intents: Dict[str, float] = {}
    matched_patterns: List[str] = []

    # Phase 1: Keyword pattern matching
    for intent, pattern in _QUERY_PATTERNS.items():
        if pattern.search(query_lower):
            intents[intent] = 1.0
            matched_patterns.append(intent)

    # Phase 2: Java naming convention inference
    # 提取类名（取最后一段，例如 com.Foo.bar -> bar）
    parts = query.replace(".", " ").replace("/", " ").split()
    for part in parts:
        for intent, pattern in _JAVA_PATTERNS.items():
            if intent == "method" and len(parts) == 1 and "." not in query and "#" not in query:
                continue
            if pattern.search(part):
                intents.setdefault(intent, 0)
                intents[intent] = max(intents[intent], 0.8)

    # Phase 2b: Ontology-aware entity classification (§5.1)
    # Use EntityValidator to distinguish Service ≠ FeignClient
    for part in parts:
        if EntityValidator.is_feign_entity(part):
            intents["feign"] = max(intents.get("feign", 0), 1.5)
        elif EntityValidator.is_local_service(part):
            intents["class"] = max(intents.get("class", 0), 1.0)
    # Phase 3: Structure inference
    if "/" in query and not query.startswith("/"):
        intents.setdefault("endpoint", 0.8)
    if "." in query and "::" not in query:
        intents.setdefault("config", 0.6)
    if "::" in query or "." in query:
        intents.setdefault("class", 0.7)

    # Phase 4: 优先级调整 — 更具体的实体类型优先
    # feign/mq/endpoint 是契约级实体，优先级高于通用 class
    is_feign_confirmed = any(EntityValidator.is_feign_entity(p) for p in parts)
    is_service_confirmed = any(EntityValidator.is_local_service(p) for p in parts)
    has_java_class_hint = any(_JAVA_PATTERNS["class"].search(p) for p in parts)

    if "feign" in intents:
        intents["feign"] = max(intents["feign"], 2.0)
    if "mq" in intents:
        intents["mq"] = max(intents["mq"], 2.0)
    if "endpoint" in intents:
        # endpoint 意图从命名约定或路径模式中检测到时也应提升
        if query_lower.startswith("/") or any(
            p.endswith("Controller") or p.endswith("Resource") or p.endswith("Api")
            for p in parts
        ):
            intents["endpoint"] = max(intents["endpoint"], 2.0)

    # class 意图只在以下情况提升到高位：
    # - 看起来像 Java 符号名，且没有被 ontology 确认为 feign 或 endpoint
    if _looks_like_java_symbol_query(query):
        if is_feign_confirmed:
            # ontology 确认是 Feign，降低 class 权重避免混淆
            intents["class"] = max(intents.get("class", 0), 1.0)
        elif any(p.endswith("Controller") or p.endswith("Resource") or p.endswith("Api") for p in parts):
            # 命名约定表明是 endpoint，降低 class 权重
            intents["class"] = max(intents.get("class", 0), 1.0)
        elif is_service_confirmed or has_java_class_hint:
            intents["class"] = max(intents.get("class", 0), 2.2)

    # 当 ontology 确认是 feign 但 class 分数也高时，确保 feign 优先
    if is_feign_confirmed and intents.get("feign", 0) > 0:
        intents["feign"] = max(intents["feign"], intents.get("class", 0) + 0.5)

    primary = max(intents.items(), key=lambda x: x[1])[0] if intents else "general"

    return {
        "primary_intent": primary,
        "all_intents": intents,
        "matched_patterns": matched_patterns,
        "is_cross_service": any(k in query_lower for k in ["feign", "fegin", "远程", "rpc", "服务间"]),
        "is_chain_query": "chain" in intents or "调用链" in query_lower,
        "query_shape": "java_symbol" if _looks_like_java_symbol_query(query) else "general",
        "prefer_class_symbol": _looks_like_java_symbol_query(query),
    }


def hybrid_retrieve(
    graph: GraphStore,
    workspace_file: str,
    query: str,
    config: Optional[HybridRetrievalConfig] = None,
    node_types: Optional[List[str]] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Execute hybrid retrieval combining graph, sparse, and semantic search.

    This is the main entry point for intelligent code retrieval.
    """
    if config is None:
        config = HybridRetrievalConfig()

    intent = detect_query_intent(query)
    tokenize, _rrf, _best_match = _get_common_functions()
    tokens = tokenize(query)

    # Phase 1: Retrieval from all sources (FTS call shared between graph+sparse)
    exact_nodes = graph.find_nodes(query, types=node_types, limit=limit * 2)
    graph_hits = _graph_retrieval_from_nodes(exact_nodes, tokens, graph, node_types, limit * 2, _rrf)
    sparse_hits = _sparse_retrieval_from_nodes(exact_nodes, limit * 2, _rrf)
    semantic_hits = _semantic_retrieval(workspace_file, query, limit * 2)
    retrieval_diagnostics: Dict[str, Any] = {}
    vector_hits: List[RetrievalResult] = []
    if config.enable_vector:
        vector_hits = _vector_retrieval(
            workspace_file,
            query,
            tokens,
            limit * 2,
            diagnostics=retrieval_diagnostics,
        )
    else:
        retrieval_diagnostics["vector"] = {"status": "disabled", "reason": "configured_off"}
    bm25_hits: List[RetrievalResult] = []
    if config.enable_sparse_bm25:
        bm25_hits = _bm25_sparse_retrieval(workspace_file, query, limit * 2, diagnostics=retrieval_diagnostics)
    else:
        retrieval_diagnostics["bm25"] = {"status": "disabled", "reason": "configured_off"}

    # Phase 2: Merge and rank results
    merged = _merge_retrieval_results(
        graph_hits, sparse_hits, semantic_hits, vector_hits=vector_hits,
        config=config,
        intent=intent,
        bm25_hits=bm25_hits,
        query=query,
    )

    # Phase 3: Type-based boosting
    if config.enable_type_boosting:
        merged = _apply_type_boosting(merged, intent)

    # Phase 4: Neighbor enrichment (top results only for performance)
    top_n = min(limit, 10)  # Only enrich top-10 to avoid N+1 BFS on large result sets
    for item in merged[:top_n]:
        item.neighbors = graph.neighbors(
            item.node_id,
            direction="both",
            max_depth=config.neighbor_depth,
            limit=config.neighbor_limit,
        )

    # Phase 5: Cross-workspace resolution
    if config.enable_cross_workspace:
        _resolve_cross_workspace_refs(merged[:limit], graph, workspace_file)

    # Phase 6: Build summary
    results = [item for item in merged if item.score >= config.min_confidence][:limit]

    return {
        "query": query,
        "intent": intent,
        "results": [_result_to_dict(r) for r in results],
        "total_found": len(merged),
        "returned": len(results),
        "retrieval_summary": _build_retrieval_summary(results, intent),
        "progressive": _build_progressive_summary(results, intent),
        "retrieval_diagnostics": retrieval_diagnostics,
        "config": {
            "graph_weight": config.graph_weight,
            "sparse_weight": config.sparse_weight,
            "semantic_weight": config.semantic_weight,
            "vector_weight": config.vector_weight,
            "enable_sparse_bm25": config.enable_sparse_bm25,
            "enable_vector": config.enable_vector,
        },
    }


def _graph_retrieval(
    graph: GraphStore,
    query: str,
    tokens: List[str],
    node_types: Optional[List[str]],
    limit: int,
    _rrf: Any,
) -> List[RetrievalResult]:
    """Retrieve nodes via graph structure (neighbors of exact matches)."""
    results: Dict[str, RetrievalResult] = {}

    # Find exact matches first
    exact_nodes = graph.find_nodes(query, types=node_types, limit=limit)
    for rank, node in enumerate(exact_nodes, start=1):
        node_id = node["id"]
        results[node_id] = RetrievalResult(
            node_id=node_id,
            node=node,
            score=_rrf(rank) * 1.5,  # Boost exact matches
            sources=["graph_exact"],
        )

    # Token-based fallback
    if len(results) < limit // 2:
        for token in tokens:
            token_nodes = graph.find_nodes(token, types=node_types, limit=limit)
            for rank, node in enumerate(token_nodes, start=1):
                node_id = node["id"]
                if node_id not in results:
                    results[node_id] = RetrievalResult(
                        node_id=node_id,
                        node=node,
                        score=_rrf(rank + 100),
                        sources=["graph_token"],
                    )

    return list(results.values())


def _sparse_retrieval(
    graph: GraphStore,
    query: str,
    tokens: List[str],
    node_types: Optional[List[str]],
    limit: int,
    _rrf: Any,
) -> List[RetrievalResult]:
    """Retrieve nodes via FTS/sparse search."""
    results: Dict[str, RetrievalResult] = {}

    # Use FTS if available
    fts_nodes = graph.find_nodes(query, types=node_types, limit=limit)
    for rank, node in enumerate(fts_nodes, start=1):
        node_id = node["id"]
        results[node_id] = RetrievalResult(
            node_id=node_id,
            node=node,
            score=_rrf(rank + 50),  # Lower priority than graph exact
            sources=["sparse_fts"],
        )

    return list(results.values())



def _graph_retrieval_from_nodes(
    exact_nodes: list,
    tokens: List[str],
    graph: GraphStore,
    node_types: Optional[List[str]],
    limit: int,
    _rrf: Any,
) -> List[RetrievalResult]:
    """Retrieve nodes via graph structure using pre-fetched exact matches."""
    results: Dict[str, RetrievalResult] = {}
    for rank, node in enumerate(exact_nodes, start=1):
        node_id = node["id"]
        results[node_id] = RetrievalResult(
            node_id=node_id,
            node=node,
            score=_rrf(rank) * 1.5,
            sources=["graph_exact"],
        )
    # Token-based fallback only if needed
    if len(results) < limit // 2:
        for token in tokens:
            token_nodes = graph.find_nodes(token, types=node_types, limit=limit)
            for rank, node in enumerate(token_nodes, start=1):
                node_id = node["id"]
                if node_id not in results:
                    results[node_id] = RetrievalResult(
                        node_id=node_id,
                        node=node,
                        score=_rrf(rank + 100),
                        sources=["graph_token"],
                    )
    return list(results.values())


def _sparse_retrieval_from_nodes(
    exact_nodes: list,
    limit: int,
    _rrf: Any,
) -> List[RetrievalResult]:
    """Retrieve nodes via FTS using pre-fetched exact matches (avoids duplicate FTS)."""
    results: Dict[str, RetrievalResult] = {}
    for rank, node in enumerate(exact_nodes, start=1):
        node_id = node["id"]
        results[node_id] = RetrievalResult(
            node_id=node_id,
            node=node,
            score=_rrf(rank + 50),
            sources=["sparse_fts"],
        )
    return list(results.values())


def _semantic_retrieval(
    workspace_file: str,
    query: str,
    limit: int,
) -> List[RetrievalResult]:
    """Retrieve nodes via semantic/embedding search."""
    results: List[RetrievalResult] = []

    try:
        semantic_hits = semantic_query(workspace_file, query, limit=limit)
        for rank, hit in enumerate(semantic_hits, start=1):
            node_id = hit.get("node_id", "")
            if not node_id:
                continue
            results.append(RetrievalResult(
                node_id=node_id,
                node={
                    "id": node_id,
                    "type": hit.get("type", ""),
                    "name": hit.get("name", ""),
                    "project": hit.get("project", ""),
                    "file_path": hit.get("file_path", ""),
                },
                score=float(hit.get("score", 0.0)) * 0.8,  # Scale semantic scores
                sources=["semantic"],
                evidence={"semantic_rank": rank, "raw_score": hit.get("score", 0.0)},
            ))
    except Exception:
        # Semantic search is optional; degrade gracefully
        pass

    return results


def _vector_retrieval(
    workspace_file: str,
    query: str,
    tokens: List[str],
    limit: int,
    diagnostics: Dict[str, Any] | None = None,
) -> List[RetrievalResult]:
    """Retrieve nodes via ANN vector search when VectorIndex is available."""
    results: List[RetrievalResult] = []
    vector_diag: Dict[str, Any] = {"status": "disabled", "reason": "not_checked"}
    try:
        from ..store import WorkspaceStore
        from ..storage.unified import UnifiedStore
        from ..storage.vector_index import VectorIndex
        from ..semantic import (
            DEFAULT_SENTENCE_TRANSFORMER_MODEL,
            _load_sentence_transformer_model,
            semantic_index_stats,
        )

        workspace_store = WorkspaceStore(workspace_file)
        unified = UnifiedStore(workspace_store.graph_db_path)
        try:
            vec = VectorIndex(unified)
            status = vec.stats()
            vector_diag = {"status": "empty", **status}
            if status.get("embedding_count", 0) == 0:
                return results

            semantic_stats = semantic_index_stats(workspace_file)
            model_name = (
                semantic_stats.get("model")
                or semantic_stats.get("requested_model")
                or DEFAULT_SENTENCE_TRANSFORMER_MODEL
            )
            model = _load_sentence_transformer_model(model_name)
            if model is None:
                vector_diag = {
                    "status": "unavailable",
                    "reason": "sentence-transformers model unavailable for query embedding",
                    "model": model_name,
                    **status,
                }
                return results

            query_vector = [float(value) for value in model.encode([query], normalize_embeddings=True)[0]]
            vector_results = vec.query(query_vector, limit=limit)
            if not vector_results:
                vector_diag = {"status": "active", "returned": 0, **status}
                return results

            from ..graph import GraphStore
            with GraphStore(workspace_store.graph_db_path) as graph:
                for rank, hit in enumerate(vector_results[:limit], start=1):
                    node_id = hit.get("node_id", "")
                    if not node_id:
                        continue
                    node = graph.node_by_id(node_id)
                    if not node:
                        continue
                    score = float(hit.get("score", 0.0) or max(0.0, 1.0 - float(hit.get("distance", 1.0))))
                    results.append(RetrievalResult(
                        node_id=node_id,
                        node=node,
                        score=score,
                        sources=["vector_ann"],
                        evidence={"vector_rank": rank, "backend": hit.get("backend", "")},
                    ))
            vector_diag = {"status": "active", "returned": len(results), **status}
        finally:
            unified.close()
    except Exception as exc:
        vector_diag = diag_entry(DIAG.UNAVAILABLE, exc=exc)
    finally:
        if diagnostics is not None:
            diagnostics["vector"] = vector_diag
    return results



def _bm25_sparse_retrieval(
    workspace_file: str,
    query: str,
    limit: int,
    diagnostics: Dict[str, Any] | None = None,
) -> List[RetrievalResult]:
    """Retrieve nodes via BM25 InvertedIndex when available."""
    results: List[RetrievalResult] = []
    bm25_diag: Dict[str, Any] = {"status": "disabled", "reason": "not_checked"}
    try:
        from ..store import WorkspaceStore
        from ..storage.unified import UnifiedStore
        from ..retrieval.inverted import InvertedIndex

        workspace_store = WorkspaceStore(workspace_file)
        unified = UnifiedStore(workspace_store.graph_db_path)
        try:
            idx = InvertedIndex(unified)
            stats = idx.stats()
            if stats.get("doc_count", 0) == 0:
                bm25_diag = {"status": "empty", **stats}
                return results

            bm25_results = idx.query(query, limit=limit)
            if not bm25_results:
                bm25_diag = {"status": "active", "returned": 0, **stats}
                return results

            from ..graph import GraphStore
            with GraphStore(workspace_store.graph_db_path) as graph:
                for hit in bm25_results:
                    node_id = hit.get("node_id", "")
                    if not node_id:
                        continue
                    node = graph.node_by_id(node_id)
                    if not node:
                        continue
                    results.append(RetrievalResult(
                        node_id=node_id,
                        node=node,
                        score=float(hit.get("score", 0.0)),
                        sources=["sparse_bm25"],
                        evidence={"bm25_backend": hit.get("backend", "bm25_inverted")},
                    ))
            bm25_diag = {"status": "active", "returned": len(results), **stats}
        finally:
            unified.close()
    except Exception as exc:
        bm25_diag = {"status": "unavailable", "reason": str(exc)[:200]}
    finally:
        if diagnostics is not None:
            diagnostics["bm25"] = bm25_diag
    return results


def _merge_retrieval_results(
    graph_hits: List[RetrievalResult],
    sparse_hits: List[RetrievalResult],
    semantic_hits: List[RetrievalResult],
    config: HybridRetrievalConfig,
    intent: Dict[str, Any],
    query: str = "",
    vector_hits: List[RetrievalResult] | None = None,
    bm25_hits: List[RetrievalResult] | None = None,
) -> List[RetrievalResult]:
    """Merge results from all retrieval sources using RRF-inspired scoring.

    Each source's scores are normalized to [0, 1] before weighting, so no
    single source can dominate purely by scale.

    The function is pure: caller-owned ``RetrievalResult`` instances are not
    mutated, and the returned list contains freshly constructed objects.  This
    matters when the same hit list is reused across multiple fusion calls
    (e.g. in tests, ablations, or staged retrieval pipelines).
    """
    def _normalize(hits: List[RetrievalResult]) -> List[RetrievalResult]:
        if not hits:
            return hits
        normalized = [copy.deepcopy(h) for h in hits]
        max_score = max(h.score for h in normalized) or 1.0
        for h in normalized:
            h.score = h.score / max_score
        return normalized

    graph_hits = _normalize(graph_hits)
    sparse_hits = _normalize(sparse_hits)
    semantic_hits = _normalize(semantic_hits)
    if vector_hits:
        vector_hits = _normalize(vector_hits)
    if bm25_hits:
        bm25_hits = _normalize(bm25_hits)

    merged: Dict[str, RetrievalResult] = {}

    # Process graph hits
    for rank, item in enumerate(graph_hits, start=1):
        if item.node_id in merged:
            existing = merged[item.node_id]
            existing.score += item.score * config.graph_weight
            existing.sources.extend(item.sources)
        else:
            merged[item.node_id] = RetrievalResult(
                node_id=item.node_id,
                node=item.node,
                score=item.score * config.graph_weight,
                sources=item.sources.copy(),
                evidence={"graph_rank": rank},
            )

    # Process sparse hits
    for rank, item in enumerate(sparse_hits, start=1):
        if item.node_id in merged:
            existing = merged[item.node_id]
            existing.score += item.score * config.sparse_weight
            if "sparse" not in str(existing.sources):
                existing.sources.extend(item.sources)
        else:
            merged[item.node_id] = RetrievalResult(
                node_id=item.node_id,
                node=item.node,
                score=item.score * config.sparse_weight,
                sources=item.sources.copy(),
                evidence={"sparse_rank": rank},
            )

    # Process vector hits
    if vector_hits:
        for rank, item in enumerate(vector_hits, start=1):
            if item.node_id in merged:
                existing = merged[item.node_id]
                existing.score += item.score * config.vector_weight
                existing.sources.extend(item.sources)
                existing.evidence["vector_rank"] = rank
            else:
                merged[item.node_id] = RetrievalResult(
                    node_id=item.node_id,
                    node=item.node,
                    score=item.score * config.vector_weight,
                    sources=item.sources[:],
                    evidence={"vector_rank": rank},
                )

    # Process BM25 hits as a sparse retrieval source.
    if bm25_hits:
        for rank, item in enumerate(bm25_hits, start=1):
            if item.node_id in merged:
                existing = merged[item.node_id]
                existing.score += item.score * config.sparse_weight
                existing.sources.extend(item.sources)
                existing.evidence["bm25_rank"] = rank
            else:
                merged[item.node_id] = RetrievalResult(
                    node_id=item.node_id,
                    node=item.node,
                    score=item.score * config.sparse_weight,
                    sources=item.sources.copy(),
                    evidence={"bm25_rank": rank},
                )

    # Process semantic hits
    for rank, item in enumerate(semantic_hits, start=1):
        if item.node_id in merged:
            existing = merged[item.node_id]
            existing.score += item.score * config.semantic_weight
            if "semantic" not in str(existing.sources):
                existing.sources.extend(item.sources)
        else:
            merged[item.node_id] = RetrievalResult(
                node_id=item.node_id,
                node=item.node,
                score=item.score * config.semantic_weight,
                sources=item.sources.copy(),
                evidence={"semantic_rank": rank},
            )

    # Multi-source bonus
    for item in merged.values():
        source_set = set(item.sources)
        if len(source_set) >= 3:
            item.score *= 1.3  # Triple-source bonus
        elif len(source_set) >= 2:
            item.score *= 1.15  # Dual-source bonus

    strong_exact_hit = any(
        _has_exact_like_source(item) and _node_matches_query_name(item.node, query)
        for item in merged.values()
    )
    prefer_class_symbol = bool(intent.get("prefer_class_symbol"))
    for item in merged.values():
        source_set = set(item.sources)
        semantic_only = source_set == {"semantic"}
        if strong_exact_hit and semantic_only:
            item.score *= 0.35 if not item.node.get("file_path") else 0.55
            item.evidence["semantic_penalty"] = "strong_exact_present"
        if semantic_only and (not item.node.get("project") or not item.node.get("file_path")):
            item.score *= 0.7
            item.evidence["semantic_penalty"] = "weak_locator"
        if prefer_class_symbol and item.node.get("type") == "Class" and _node_matches_query_name(item.node, query):
            item.score *= 1.8
            item.evidence["symbol_exact_class_boost"] = 1.8

    return sorted(merged.values(), key=lambda x: x.score, reverse=True)


def _apply_type_boosting(
    results: List[RetrievalResult],
    intent: Dict[str, Any],
) -> List[RetrievalResult]:
    """Boost node types that match the detected query intent.

    Uses ontology-aware type boosting: when intent is a specific contract type
    (feign/mq/endpoint), unrelated structural types (Class/Service/Impl) are
    not boosted, preventing confusion between e.g. a FeignClient and a local
    Service with a similar name.

    The function is pure: caller-owned ``RetrievalResult`` objects are not
    mutated.  The returned list is a freshly sorted list of deep copies so
    repeated calls produce stable input/output objects.
    """
    primary_intent = intent.get("primary_intent", "general")

    type_boost_map = {
        "feign": {"FeignClient": 1.5, "FeignMethod": 1.4, "Endpoint": 1.2},
        "mq": {"MQTopic": 1.5, "MQConsumer": 1.4, "ConfigKey": 1.1},
        "endpoint": {"Endpoint": 1.5, "Controller": 1.3, "Method": 1.2},
        "config": {"ConfigKey": 1.5, "Field": 1.2},
        "class": {"Class": 1.4, "Interface": 1.3, "Method": 1.2},
        "method": {"Method": 1.4, "Function": 1.3},
    }

    # Contract-specific intents should penalize unrelated structural types
    _contract_intents = {"feign", "mq", "endpoint"}
    _contract_penalty_types = {"Class", "Service", "Impl", "Interface"}

    boosts = type_boost_map.get(primary_intent, {})

    cloned: List[RetrievalResult] = [copy.deepcopy(item) for item in results]
    for item in cloned:
        node_type = item.node.get("type", "")
        boost = boosts.get(node_type, 1.0)

        # Contract intent: penalize unrelated structural types to avoid confusion
        if primary_intent in _contract_intents and node_type in _contract_penalty_types:
            item.score *= 0.75
            item.evidence["contract_penalty"] = 0.75

        if intent.get("prefer_class_symbol"):
            if node_type == "Class":
                boost = max(boost, 1.8)
            elif node_type == "Method":
                item.score *= 0.82
                item.evidence["symbol_method_penalty"] = 0.82
        if boost > 1.0:
            item.score *= boost
            item.evidence["type_boost"] = boost

    # Re-sort after boosting
    cloned.sort(key=lambda x: x.score, reverse=True)
    return cloned


def _resolve_cross_workspace_refs(
    results: List[RetrievalResult],
    graph: GraphStore,
    workspace_file: str,
) -> None:
    """Resolve cross-workspace references and add summary layer."""
    # Load service topology for cross-workspace detection
    try:
        from ..store import WorkspaceStore
        store = WorkspaceStore(workspace_file)
        topology = store.read_json_prefer_backend("service-topology.json", {})
        local_services = {svc.get("service_name") or svc.get("name") for svc in topology.get("services", [])}
    except Exception:
        local_services = set()

    for item in results:
        node = item.node
        project = node.get("project", "")

        # Check if this is a cross-workspace reference
        if project and project not in local_services:
            item.cross_workspace_refs.append({
                "type": "external_service",
                "project": project,
                "node_name": node.get("name", ""),
            })


def _result_to_dict(result: RetrievalResult) -> Dict[str, Any]:
    """Convert RetrievalResult to dictionary.

    Includes ontology-aware fields:
    - semantic_strength: fact / inferred / derived (from _EDGE_SEMANTIC_STRENGTH)
    - confidence_label: high / medium / low based on score and edge strength
    """
    # Determine semantic strength from evidence edges
    strengths = set()
    evidence_items: List[Any]
    if isinstance(result.evidence, dict):
        evidence_items = [result.evidence]
    elif isinstance(result.evidence, list):
        evidence_items = list(result.evidence)
    else:
        evidence_items = []

    for ev in evidence_items:
        if isinstance(ev, dict):
            edge_type = ev.get("edge_type", "")
        elif isinstance(ev, str):
            # evidence may be a plain string like "CALLS_METHOD: Foo->Bar"
            edge_type = ev.split(":")[0].strip() if ":" in ev else ev
        else:
            continue
        if edge_type in _EDGE_SEMANTIC_STRENGTH:
            strengths.add(_EDGE_SEMANTIC_STRENGTH[edge_type])

    if strengths:
        # Normalize extended ontology strengths to the public output contract.
        normalized_strengths = []
        for strength in strengths:
            if strength == "confirmed":
                normalized_strengths.append("fact")
            elif strength == "runtime":
                normalized_strengths.append("inferred")
            elif strength in {"fact", "inferred", "derived"}:
                normalized_strengths.append(strength)
            else:
                normalized_strengths.append("inferred")
        priority = {"fact": 3, "inferred": 2, "derived": 1}
        semantic_strength = max(normalized_strengths, key=lambda s: priority.get(s, 0))
    else:
        semantic_strength = "inferred"

    # Map score to confidence label
    if result.score >= 0.7:
        confidence_label = "high"
    elif result.score >= 0.4:
        confidence_label = "medium"
    else:
        confidence_label = "low"

    return {
        "node_id": result.node_id,
        "node": result.node,
        "score": round(result.score, 4),
        "sources": result.sources,
        "evidence": result.evidence,
        "neighbor_count": len(result.neighbors),
        "cross_workspace_refs": result.cross_workspace_refs,
        "semantic_strength": semantic_strength,
        "confidence_label": confidence_label,
    }


def _build_retrieval_summary(
    results: List[RetrievalResult],
    intent: Dict[str, Any],
) -> Dict[str, Any]:
    """Build summary of retrieval results."""
    source_counts = {"graph": 0, "sparse": 0, "semantic": 0, "vector": 0}
    type_counts: Dict[str, int] = {}

    for item in results:
        for source in item.sources:
            if "graph" in source:
                source_counts["graph"] += 1
            elif "sparse" in source or "fts" in source:
                source_counts["sparse"] += 1
            elif "semantic" in source:
                source_counts["semantic"] += 1
            elif "vector" in source:
                source_counts["vector"] += 1

        node_type = item.node.get("type", "unknown")
        type_counts[node_type] = type_counts.get(node_type, 0) + 1

    return {
        "total_results": len(results),
        "source_distribution": source_counts,
        "type_distribution": type_counts,
        "primary_intent": intent.get("primary_intent", "general"),
        "is_cross_service": intent.get("is_cross_service", False),
        "avg_score": round(sum(r.score for r in results) / max(len(results), 1), 4),
    }


def _build_progressive_summary(
    results: List[RetrievalResult],
    intent: Dict[str, Any],
) -> Dict[str, Any]:
    """Build progressive disclosure summary for quick understanding."""
    top_nodes = results[:3]

    return {
        "level_1_quick": {
            "count": len(results),
            "top_matches": [
                {
                    "type": r.node.get("type", ""),
                    "name": r.node.get("name", ""),
                    "project": r.node.get("project", ""),
                    "score": round(r.score, 2),
                }
                for r in top_nodes
            ],
            "intent": intent.get("primary_intent", "general"),
        },
        "level_2_details": {
            "sources_breakdown": {
                "graph_exact": sum(1 for r in results if "graph_exact" in r.sources),
                "graph_token": sum(1 for r in results if "graph_token" in r.sources),
                "sparse_fts": sum(1 for r in results if "sparse_fts" in r.sources),
                "semantic": sum(1 for r in results if "semantic" in r.sources),
                "vector": sum(1 for r in results if any("vector" in source for source in r.sources)),
            },
            "cross_workspace_count": sum(1 for r in results if r.cross_workspace_refs),
            "has_chain_results": intent.get("is_chain_query", False),
        },
        "level_3_next_actions": _suggest_next_actions(results, intent),
    }


def _suggest_next_actions(
    results: List[RetrievalResult],
    intent: Dict[str, Any],
) -> List[str]:
    """Suggest next actions based on retrieval results."""
    actions = []

    if not results:
        actions.append("尝试更具体的查询词")
        return actions

    primary_intent = intent.get("primary_intent", "general")

    if primary_intent == "feign":
        actions.append("调用 memory_context 查看 Feign 客户端详情")
        actions.append("调用 memory_callers 查找谁在调用这个 Feign")
    elif primary_intent == "mq":
        actions.append("调用 memory_context 查看 Topic/Consumer 详情")
        actions.append("检查 mq-index.json 获取完整消息链路")
    elif primary_intent == "endpoint":
        actions.append("调用 memory_context 查看 API 端点详情")
        actions.append("调用 memory_callers 查找前端调用方")
    elif primary_intent == "chain":
        actions.append("调用 memory_callers 或 memory_callees 追踪完整调用链")
    else:
        actions.append("对 top 结果调用 memory_context 深挖")
        actions.append("修改代码前调用 mc_analyze 检查影响面")

    if intent.get("is_cross_service"):
        actions.append("注意跨服务边界，可能需要查看多个项目的索引")

    return actions
