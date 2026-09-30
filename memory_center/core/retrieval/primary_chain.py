"""Bounded primary service-chain search (long task: cross-service main chain).

For a Method anchor that `mc_lookup(auto)` resolved, find a bounded,
deterministic, cross-service main path that explains *what this entry point
calls into next* — Feign method → downstream endpoint, HTTP handler →
route, MQ producer → topic → consumer — when such graph evidence exists.

Contract (docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md §7 + task):

- bounded: layered BFS with hard node/edge/depth ceilings; no full-graph
  materialization;
- allowed main-path relations are the cross-service / contract edges only;
  structural edges (CONTAINS/DECLARES/IMPORTS) are never chain body;
- deterministic: EXTRACTED > INFERRED, cross-service chain > local chain,
  higher score > lower, shorter path first, stable id tie-break;
- never fabricates: without provable cross-service evidence the result is
  ``insufficient_evidence`` / ``not_found``, and the caller must phrase the
  answer accordingly.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.storage.workspace import WorkspaceStore

# Allowed main-path relations, ordered by how strongly they signal a
# real cross-service / contract step.
MAIN_RELATION_WEIGHTS = {
    "CALLS_SERVICE": 1.0,
    "IMPLEMENTS_FEIGN": 0.95,
    "HANDLES_ENDPOINT": 0.9,
    "PRODUCES_TOPIC": 0.85,
    "CONSUMES_TOPIC": 0.85,
    "CALLS_METHOD": 0.55,  # intra-service step, only as part of a longer chain
}
# Structural / non-chain edges are never the chain body.
FORBIDDEN_CHAIN_RELATIONS = frozenset(
    {"CONTAINS", "DECLARES", "IMPORTS", "RELATED_TO_MEMORY", "INJECTS_BEAN", "READS_FIELD", "READS_CONFIG", "DISPATCHES_TO"}
)
# Evidence factors: EXTRACTED > INFERRED > AMBIGUOUS.
_EVIDENCE_FACTOR = {"EXTRACTED": 1.0, "INFERRED": 0.7, "AMBIGUOUS": 0.35}
_DEPTH_DECAY = 0.8
_MAX_DEPTH = 3
_MAX_NODES = 40
_MAX_EDGES = 60
_DEADLINE_MS = 8_000


def _evidence_level(edge: dict[str, Any]) -> str:
    meta = edge.get("metadata") or {}
    relation = _relation(edge)
    # An unresolved CALLS_METHOD is never proven, even if metadata carries a
    # default evidence_level of EXTRACTED.
    resolution = str(meta.get("resolution_level") or "")
    if relation == "CALLS_METHOD" and resolution == "unresolved":
        return "AMBIGUOUS"
    if isinstance(meta.get("evidence_level"), str) and meta["evidence_level"] != "AMBIGUOUS":
        return meta["evidence_level"]
    # Contract edges (Feign/HTTP/MQ/endpoint) are extracted directly from
    # annotations and config by the parser; they are facts, not inferences.
    if relation in ("CALLS_SERVICE", "IMPLEMENTS_FEIGN", "HANDLES_ENDPOINT", "PRODUCES_TOPIC", "CONSUMES_TOPIC", "EXPOSES_ENDPOINT"):
        return "EXTRACTED"
    # A bridge step is our retrieval-layer inference and must never be EXTRACTED.
    if edge.get("bridge") or meta.get("bridge"):
        return "INFERRED"
    if resolution and resolution != "unresolved":
        return "EXTRACTED"
    return "AMBIGUOUS"


def _relation(edge: dict[str, Any]) -> str:
    return str(edge.get("type") or edge.get("relation") or "")


def _path_score(steps: list[dict[str, Any]]) -> float:
    """path_score = prod(relation_weight * confidence * evidence * freshness) * depth_decay^len"""
    score = 1.0
    for step in steps:
        rel = _relation(step)
        weight = MAIN_RELATION_WEIGHTS.get(rel, 0.3)
        confidence = float(step.get("confidence", 0.5) or 0.5)
        evidence = _EVIDENCE_FACTOR.get(_evidence_level(step), 0.35)
        freshness = 1.0  # generation-level freshness already gated upstream
        score *= weight * confidence * evidence * freshness
    return round(score * (_DEPTH_DECAY ** len(steps)), 6)


def _is_cross_service(edge: dict[str, Any]) -> bool:
    return _relation(edge) in ("CALLS_SERVICE", "IMPLEMENTS_FEIGN", "PRODUCES_TOPIC", "CONSUMES_TOPIC")


def _stable_sort_key(path: dict[str, Any]) -> tuple[Any, ...]:
    """Deterministic ordering: evidence > cross-service > score > length > id."""
    evidence = -int(path.get("evidence_level") == "EXTRACTED")
    cross = -int(path.get("cross_service"))
    score = -float(path.get("score", 0.0))
    length = int(path.get("length", 0))
    last_id = str(path.get("steps", [{}])[-1].get("target_id", ""))
    return (evidence, cross, score, length, last_id)


def _looks_like_feign_interface(method_id: str, method_name: str) -> bool:
    """Cheap pre-filter before any FTS: only Feign-like interface methods can
    bridge to a FeignClient/FeignMethod. Avoids a find_nodes call for every
    ordinary Method node (the dominant cost on large graphs)."""
    name = str(method_name or "")
    lower = (name + " " + str(method_id)).lower()
    return any(tok in lower for tok in ("feign", "client", "wrapper", "remote", "service"))


def _bridge_feign_method(graph, method_node: dict[str, Any], *, cap: int) -> list[dict[str, Any]]:
    """Bridge a Feign interface Method to its owning FeignClient and its
    FeignMethod, so both CALLS_SERVICE (downstream service) and
    IMPLEMENTS_FEIGN (downstream endpoint) become reachable.

    The graph does not edge Feign-interface Methods to their FeignClient /
    FeignMethod; this is a retrieval-layer name/ownership match, not a
    schema change. The bridge step is marked ``bridge=True`` and carries
    INFERRED evidence so it never outranks a real extracted edge.
    """
    name = str(method_node.get("name", ""))
    short = name.rsplit(".", 1)[-1]  # FeignUserWrapperService.getUser -> getUser
    method_full = str(method_node.get("id", ""))
    parts = method_full.split(":")
    if not short or len(parts) < 3 or not _looks_like_feign_interface(method_full, name):
        return []
    owner_project = parts[1]
    bridges: list[dict[str, Any]] = []
    # Bridge to the owning FeignClient (its CALLS_SERVICE edge is the
    # cross-service evidence), matched by interface name in the id.
    for cand in graph.find_nodes(short, types=["FeignClient"], limit=cap):
        cid = str(cand.get("id", ""))
        # FeignClient id embeds the interface name: FeignClient:<proj>:<Iface>
        if cid.startswith(f"FeignClient:{owner_project}:") and cid.rsplit(":", 1)[-1] == short:
            bridges.append({
                "type": "CALLS_METHOD",  # logical bridge: entry calls the client
                "source_id": method_full,
                "target_id": cid,
                "confidence": 0.5,
                "metadata": {"resolution_level": "feign_client_bridge", "evidence_level": "INFERRED"},
                "bridge": True,
            })
    # Bridge to FeignMethods of the same interface so IMPLEMENTS_FEIGN →
    # Endpoint is reachable.
    for cand in graph.find_nodes(short, types=["FeignMethod"], limit=cap):
        cid = str(cand.get("id", ""))
        if cid.startswith(f"FeignMethod:{owner_project}:") and cid.rsplit(":", 1)[-1] == short:
            bridges.append({
                "type": "CALLS_METHOD",  # logical bridge
                "source_id": method_full,
                "target_id": cid,
                "confidence": 0.5,
                "metadata": {"resolution_level": "feign_method_bridge", "evidence_level": "INFERRED"},
                "bridge": True,
            })
    return bridges


def find_primary_service_chain(
    workspace_file: str,
    anchor_method: dict[str, Any],
    *,
    project: str = "",
    max_depth: int = _MAX_DEPTH,
    max_nodes: int = _MAX_NODES,
    max_edges: int = _MAX_EDGES,
    deadline_ms: int = _DEADLINE_MS,
) -> dict[str, Any]:
    """Search a bounded cross-service main chain from a Method anchor.

    Returns the ``primary_chain`` contract block. Never fabricates a chain:
    without provable cross-service edges the status is ``not_found`` or
    ``insufficient_evidence``.
    """
    from memory_center.core.storage.runtime import RuntimeStore

    store = WorkspaceStore(workspace_file)
    generation = str(index_control_status(store).get("active_generation", "") or "")
    anchor_id = str(anchor_method.get("id", ""))
    # find_symbols best_match often carries no node id; when the anchor is a
    # Method whose name is `Class.method`, resolve the real node id from the
    # graph by exact name so the chain search can start. Pure retrieval-layer
    # resolution, never a schema change.
    if not anchor_id and str(anchor_method.get("type", "")).startswith("Method"):
        name = str(anchor_method.get("name", ""))
        if name:
            from memory_center.core.storage.runtime import RuntimeStore

            try:
                with RuntimeStore(WorkspaceStore(workspace_file).graph_db_path) as graph:
                    node = graph.node_by_name_exact(name, types=["Method"])
                    if node is not None and node.get("id"):
                        anchor_id = str(node["id"])
                        anchor_method = {**anchor_method, "id": anchor_id}
            except Exception:
                pass
    # MQ Producer anchor: report why a consumer chain cannot be proven before
    # the Method-only gate, so the answer is insufficient_evidence with a
    # specific MQ reason, never a fabricated consumer or a misleading
    # anchor_not_method.
    if not anchor_id or not str(anchor_method.get("type", "")).startswith("Method"):
        if str(anchor_method.get("type", "")).startswith("MQProducer"):
            mq_reason = _detect_mq_producer_without_provable_consumer(workspace_file, anchor_id)
            return {
                "status": "insufficient_evidence",
                "reason_codes": [mq_reason or "mq_topic_bridge_unsupported"],
                "anchor": anchor_method,
                "steps": [],
                "score": 0.0,
                "evidence_level": "AMBIGUOUS",
                "generation": generation,
            }
        return {"status": "insufficient_evidence", "reason_codes": ["anchor_not_method"], "anchor": anchor_method, "steps": [], "score": 0.0, "evidence_level": "AMBIGUOUS", "generation": generation}

    started = time.perf_counter()
    reason_codes: list[str] = []
    best_paths: list[dict[str, Any]] = []
    seen_nodes = {anchor_id}
    # state: (node_id, path_steps, depth)
    frontier = deque([(anchor_id, [], 0)])
    edge_budget = max(1, min(int(max_edges), 200))

    def timed_out() -> bool:
        return (time.perf_counter() - started) * 1000 > max(1, int(deadline_ms))

    with RuntimeStore(WorkspaceStore(workspace_file).graph_db_path) as graph:
        while frontier and not timed_out() and len(seen_nodes) <= max_nodes:
            node_id, steps, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            edges = graph.edges_for_node(node_id, direction="downstream", limit=edge_budget)
            # A Feign-interface Method reaches its cross-service evidence
            # (CALLS_SERVICE on the client, IMPLEMENTS_FEIGN on the method)
            # only through a retrieval-layer bridge. Always attempt it for
            # Method nodes so the chain can cross the service boundary.
            if str(node_id).startswith("Method:"):
                node_row = graph.node_by_id(node_id)
                if node_row is not None:
                    bridge_edges = _bridge_feign_method(graph, node_row, cap=edge_budget)
                    if bridge_edges:
                        edges = list(edges) + bridge_edges
            # Beam: among non-cross-service successors, expand only the top-K
            # by score to avoid fanning out across every sibling CALLS_METHOD
            # of a wide method (the dominant latency on large graphs).
            non_cross: list[tuple[float, dict[str, Any]]] = []
            for edge in edges:
                rel = _relation(edge)
                if rel in FORBIDDEN_CHAIN_RELATIONS:
                    continue
                if rel not in MAIN_RELATION_WEIGHTS and not edge.get("bridge"):
                    continue
                target = str(edge.get("target_id", ""))
                if target in seen_nodes:
                    continue
                step = dict(edge)
                step["relation"] = rel or str(edge.get("type", ""))
                new_steps = steps + [step]
                score = _path_score(new_steps)
                cross = any(_is_cross_service(s) for s in new_steps) or str(target).startswith(("Endpoint:", "MQTopic:"))
                candidate = {
                    "anchor": anchor_method,
                    "steps": new_steps,
                    "score": score,
                    "length": len(new_steps),
                    "cross_service": cross,
                    "evidence_level": "EXTRACTED" if all(_evidence_level(s) == "EXTRACTED" for s in new_steps) else ("INFERRED" if any(_evidence_level(s) == "INFERRED" for s in new_steps) else "AMBIGUOUS"),
                    "target_id": target,
                }
                if cross or len(new_steps) >= 2:
                    best_paths.append(candidate)
                if not cross:
                    non_cross.append((score, (target, new_steps, depth + 1)))
                if len(best_paths) >= max_nodes:
                    break
            # Expand only the top-K non-cross successors (beam width 3).
            non_cross.sort(key=lambda item: -item[0])
            for _score, state in non_cross[:3]:
                target, new_steps, next_depth = state
                if target not in seen_nodes and len(seen_nodes) < max_nodes:
                    seen_nodes.add(target)
                    frontier.append((target, new_steps, next_depth))
            if len(best_paths) >= max_nodes:
                break
            if len(seen_nodes) >= max_nodes:
                reason_codes.append("query_budget_exceeded")

    # Deterministic selection of the single best main path.
    if best_paths:
        best_paths.sort(key=_stable_sort_key)
        best = best_paths[0]
        truncated = len(best_paths) >= max_nodes or timed_out()
        status = "found" if best["cross_service"] else ("truncated" if truncated else "not_found")
        return {
            "status": status,
            "anchor": anchor_method,
            "steps": best["steps"],
            "score": best["score"],
            "evidence_level": best["evidence_level"],
            "generation": generation,
            "reason_codes": reason_codes,
            "truncated": truncated,
        }

    status = "not_found" if not reason_codes else "insufficient_evidence"
    # MQ Producer anchor: a PRODUCES_TOPIC edge to a Topic whose consumers
    # cannot be proven (binding/destination mapping lives outside the local
    # index, e.g. a config center) must be reported as insufficient_evidence,
    # never as not_found — not_found would imply "no consumer exists".
    mq_marker = _detect_mq_producer_without_provable_consumer(workspace_file, anchor_id)
    if mq_marker:
        status = "insufficient_evidence"
        reason_codes = reason_codes or []
        if mq_marker not in reason_codes:
            reason_codes.append(mq_marker)
    return {
        "status": status,
        "anchor": anchor_method,
        "steps": [],
        "score": 0.0,
        "evidence_level": "AMBIGUOUS",
        "generation": generation,
        "reason_codes": reason_codes or ["no_cross_service_edge"],
    }


def _detect_mq_producer_without_provable_consumer(workspace_file: str, node_id: str) -> str:
    """Return a reason code when the node is an MQ Producer whose topic has
    consumers that cannot be proven from local index evidence.

    The MQ topic bridge (canonicalize producer topic == consumer binding) is
    intentionally NOT implemented: on real workspaces the consumer's
    destination mapping lives in a config center and the naming spaces do not
    normalize under fixed prefix rules. This keeps the answer honest instead
    of fabricating a consumer.
    """
    if not str(node_id).startswith("MQProducer:"):
        return ""
    from memory_center.core.storage.runtime import RuntimeStore

    try:
        with RuntimeStore(WorkspaceStore(workspace_file).graph_db_path) as graph:
            topics = [
                str(e.get("target_id", ""))
                for e in graph.edges_for_node(node_id, direction="downstream", limit=20)
                if str(e.get("type", "")) == "PRODUCES_TOPIC"
            ]
            if not topics:
                return "mq_producer_no_topic_edge"
            for topic in topics:
                consumers = [
                    str(e.get("source_id", ""))
                    for e in graph.edges_for_node(topic, direction="upstream", limit=20)
                    if str(e.get("type", "")) == "CONSUMES_TOPIC"
                ]
                if not consumers:
                    return "mq_topic_consumer_unprovable"
    except Exception:
        return "mq_topic_bridge_unavailable"
    return ""
