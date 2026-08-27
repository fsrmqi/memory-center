"""Bounded internal query templates (Phase B).

The design doc (docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md §7)
requires graph capability to be productized as a fixed set of internal
templates routed through the task-level facade instead of scattered direct
graph calls:

- ``find_symbols``            -> mc_lookup
- ``trace_call_paths``        -> mc_lookup / mc_analyze
- ``find_contract_consumers`` -> mc_analyze
- ``plan_change_risk``        -> mc_admin(change_review)

Every template enforces a per-tier hard budget (fast/standard/deep),
returns deterministically ordered results for the same generation and
arguments, reports its effective ``query_budget`` (including truncation
and timeout facts), and caches under
``source_signature + active_generation + normalized args + tier`` so a
generation change always invalidates.

No new MCP tools: facades call these services directly.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_center.core.indexing.control_plane import index_control_status
from memory_center.core.storage.workspace import WorkspaceStore

# Hard budgets per request tier. Explicit user arguments are clamped to
# these ceilings; deep keeps a hard ceiling too (no unbounded scans).
TIER_BUDGETS: dict[str, dict[str, int]] = {
    "fast": {"depth": 1, "nodes": 20, "edges": 30, "limit": 20},
    "standard": {"depth": 3, "nodes": 80, "edges": 120, "limit": 50},
    "deep": {"depth": 5, "nodes": 300, "edges": 500, "limit": 100},
}

_CACHE_TTL_SECONDS = 15.0
_CACHE_MAX_ENTRIES = 256
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, str, Any]] = {}


@dataclass(frozen=True)
class QueryBudget:
    """Effective bounds for one template execution."""

    tier: str = "standard"
    depth: int = 3
    nodes: int = 80
    edges: int = 120
    deadline_ms: int = 10_000
    started_at: float = 0.0

    def report(self, *, elapsed_ms: float, timed_out: bool, truncated: bool) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "depth": self.depth,
            "nodes": self.nodes,
            "edges": self.edges,
            "elapsed_ms": round(elapsed_ms, 2),
            "timed_out": bool(timed_out),
            "truncated": bool(truncated),
        }


def normalize_tier(tier: str | None) -> str:
    value = str(tier or "").strip().lower()
    return value if value in TIER_BUDGETS else "standard"


def resolve_query_budget(
    tier: str | None,
    *,
    depth: int | None = None,
    nodes: int | None = None,
    edges: int | None = None,
) -> QueryBudget:
    """Clamp requested bounds to the tier's hard ceilings."""
    resolved_tier = normalize_tier(tier)
    caps = TIER_BUDGETS[resolved_tier]
    return QueryBudget(
        tier=resolved_tier,
        depth=min(int(depth), caps["depth"]) if depth else caps["depth"],
        nodes=min(int(nodes), caps["nodes"]) if nodes else caps["nodes"],
        edges=min(int(edges), caps["edges"]) if edges else caps["edges"],
        deadline_ms={"fast": 2_000, "standard": 10_000, "deep": 30_000}[resolved_tier],
        started_at=time.perf_counter(),
    )


def source_signature(store: WorkspaceStore) -> str:
    """Cheap index-level signature: control file mtime wins over file scans."""
    try:
        updated_at = store.memory_backend().index_updated_at("file-index.json")
    except Exception:
        updated_at = ""
    return f"{updated_at}"


def template_cache_key(workspace_file: str | Path, template: str, args: dict[str, Any]) -> str:
    """``source_signature + active_generation + normalized args`` based key."""
    store = WorkspaceStore(workspace_file)
    payload = {
        "signature": source_signature(store),
        "generation": str(index_control_status(store).get("active_generation", "") or ""),
        "template": template,
        "args": args,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cached_template(key: str, factory):
    """Return a deep-copied cached payload or run ``factory`` and store it."""
    now = time.monotonic()
    with _CACHE_LOCK:
        row = _CACHE.get(key)
        if row is not None:
            stored_at, stored_generation_key, value = row
            fresh = now - stored_at <= _CACHE_TTL_SECONDS
            if fresh:
                payload = copy.deepcopy(value)
                payload["cache"] = {"status": "hit"}
                return payload
            _CACHE.pop(key, None)
    payload = factory()
    generation_marker = {
        "source_signature_and_generation": key,
    }
    payload["cache"] = {"status": "miss"}
    payload.setdefault("internal", {})["template_cache_key"] = generation_marker["source_signature_and_generation"]
    with _CACHE_LOCK:
        # Generation invalidation relies on the key hashing the active
        # generation; old keys simply age out via TTL/max size.
        if len(_CACHE) >= _CACHE_MAX_ENTRIES:
            oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])
            for stale_key, _ in oldest[: len(_CACHE) // 4]:
                _CACHE.pop(stale_key, None)
        _CACHE[key] = (time.monotonic(), "", payload)
    return payload


def _deterministic_sort(items: list[dict[str, Any]], score_key: str = "") -> list[dict[str, Any]]:
    """Sort by descending optional score then stable id/path for tie-breaks."""

    def sort_key(row: dict[str, Any]):
        score = -float(row.get(score_key, 0.0) or 0.0) if score_key else 0.0
        stable = str(row.get("id") or row.get("path") or row.get("name") or "")
        depth = int(row.get("depth", 0) or 0)
        return (score, stable, depth)

    return sorted(items, key=sort_key)


def _budget_outcome(budget: QueryBudget) -> tuple[float, bool]:
    elapsed_ms = (time.perf_counter() - budget.started_at) * 1000.0
    timed_out = elapsed_ms > budget.deadline_ms
    return elapsed_ms, timed_out


# ---------------------------------------------------------------------------
# Template: find_symbols
# ---------------------------------------------------------------------------


def find_symbols(
    workspace_file: str | Path,
    target: str,
    *,
    tier: str = "standard",
    limit: int | None = None,
    project: str = "",
) -> dict[str, Any]:
    """Locate symbols/endpoints/config keys with a bounded candidate list."""
    from memory_center.core.orchestrator.query import memory_symbol

    budget = resolve_query_budget(tier, nodes=limit)
    effective_limit = min(int(limit) if limit else budget.nodes, budget.nodes, TIER_BUDGETS[budget.tier]["limit"] * 2)

    def _run() -> dict[str, Any]:
        result = memory_symbol(workspace_file, target, limit=effective_limit, project=project, view="compact", budget="small")
        matches = result.get("matches", []) or []
        ordered = _deterministic_sort(matches)
        truncated = len(ordered) >= effective_limit
        elapsed_ms, timed_out = _budget_outcome(budget)
        result["query_budget"] = budget.report(elapsed_ms=elapsed_ms, timed_out=timed_out, truncated=truncated)
        return result

    key = template_cache_key(workspace_file, "find_symbols", {"target": target, "limit": effective_limit, "project": project, "tier": budget.tier})
    return cached_template(key, _run)


# ---------------------------------------------------------------------------
# Template: trace_call_paths
# ---------------------------------------------------------------------------


def trace_call_paths(
    workspace_file: str | Path,
    symbol: str,
    *,
    direction: str = "callers",
    tier: str = "standard",
    depth: int | None = None,
    limit: int | None = None,
    project: str = "",
    min_confidence: float = 0.85,
    view: str = "compact",
) -> dict[str, Any]:
    """Upstream/downstream call paths with tier-clamped bounds.

    ``view`` defaults to ``compact`` so facade payloads stay byte-compatible
    with the previous direct ``memory_callers``/``memory_callees`` calls;
    deterministic ordering is applied before compaction so both views
    inherit it.
    """
    from memory_center.core.orchestrator.query import memory_callers, memory_callees

    requested_depth = depth or TIER_BUDGETS[normalize_tier(tier)]["depth"]
    budget = resolve_query_budget(tier, depth=requested_depth, nodes=limit)
    runner = memory_callers if direction == "callers" else memory_callees

    def _run() -> dict[str, Any]:
        result = runner(
            workspace_file,
            symbol,
            depth=budget.depth,
            limit=budget.nodes,
            project=project,
            view=view,
            budget="small" if view == "compact" else "medium",
            min_confidence=min_confidence,
        )
        items_key = "callers" if direction == "callers" else "callees"
        items = result.get(items_key)
        if items is not None:
            result[items_key] = _deterministic_sort(items if isinstance(items, list) else [])
        truncated = bool(isinstance(items, list) and len(items) >= budget.nodes)
        elapsed_ms, timed_out = _budget_outcome(budget)
        # Compact results may nest the list under "result"; keep the budget
        # report at the top level of whatever the runner returned.
        result["query_budget"] = budget.report(elapsed_ms=elapsed_ms, timed_out=timed_out, truncated=truncated)
        return result

    args = {"symbol": symbol, "direction": direction, "depth": budget.depth, "limit": budget.nodes, "project": project, "min_confidence": min_confidence, "tier": budget.tier}
    key = template_cache_key(workspace_file, "trace_call_paths", args)
    return cached_template(key, _run)


# ---------------------------------------------------------------------------
# Template: find_contract_consumers
# ---------------------------------------------------------------------------

_CONTRACT_EDGE_CATEGORIES = ("IMPLEMENTS_FEIGN", "CALLS_SERVICE", "CONSUMES_TOPIC", "HANDLES_ENDPOINT")
_CONTRACT_NODE_TYPES = ("FeignClient", "MQTopic", "Endpoint", "ConfigKey")


def _consumer_edges_for_target(
    workspace_file: str | Path,
    target: str,
    *,
    categories: tuple[str, ...],
    edge_cap: int,
    project: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Resolve the contract anchor and its bounded contract-category consumers.

    ``RuntimeStore.traverse_edges`` filtered by ``edge_types`` yields edge
    rows touching the anchor; each row becomes a consumer record pointing
    at the opposite endpoint of the anchor.
    """
    from memory_center.core.orchestrator.query import memory_symbol
    from memory_center.core.orchestrator.shared import load_context
    from memory_center.core.storage.runtime import RuntimeStore

    info = memory_symbol(workspace_file, target, limit=5, project=project)
    anchor = info["best_match"] if info.get("found") else None
    anchor_types: tuple[str, ...] = _CONTRACT_NODE_TYPES
    # Contract consumers must anchor on the contract node itself (FeignClient,
    # MQTopic, Endpoint, ConfigKey). The generic resolver often prefers a
    # Class/Method with the same name, so contract node types win over the
    # generic best-match. Dotted binding names (MQ/Spring) defeat FTS token
    # matching, so an exact node-name lookup runs first before any fuzzy path.
    with RuntimeStore(load_context(workspace_file)[1].graph_db_path) as graph:
        exact = graph.node_by_name_exact(target, types=list(anchor_types))
        if exact is not None:
            anchor = exact
        else:
            for candidate in graph.find_nodes(target, types=list(anchor_types), limit=8):
                candidate_name = str(candidate.get("name", ""))
                if candidate_name == target:
                    anchor = candidate
                    break
        if anchor is None or str(anchor.get("type", "")) not in anchor_types:
            # No matching contract node: keep the generic best-match only if
            # it is already a contract type; otherwise there is no anchor.
            anchor = anchor if anchor is not None and str(anchor.get("type", "")) in anchor_types else None
    if anchor is None:
        return [], None
    anchor_id = str(anchor.get("id", ""))
    category_list = [str(item) for item in categories]
    with RuntimeStore(load_context(workspace_file)[1].graph_db_path) as graph:
        edge_rows = graph.traverse_edges(anchor_id, direction="both", max_depth=1, limit=edge_cap, edge_types=category_list)
        if not edge_rows:
            return [], anchor
        anchor_edges = graph.edges_for_node(anchor_id, direction="both", limit=edge_cap * 4)
    # Enrich each consumer row with its connecting relation, resolved from
    # one bounded read of all edges around the anchor.
    relation_by_neighbor: dict[str, str] = {}
    for edge in anchor_edges:
        relation = str(edge.get("type") or "")
        if relation not in categories:
            continue
        neighbor = str(edge.get("target_id") or "") if str(edge.get("source_id") or "") == anchor_id else str(edge.get("source_id") or "")
        relation_by_neighbor.setdefault(neighbor, relation)
    rows = []
    for edge in edge_rows:
        source = str(edge.get("source_id") or "")
        consumer_id = source if str(edge.get("target_id") or "") == anchor_id else str(edge.get("target_id") or "")
        rows.append({
            **edge,
            "consumer_id": consumer_id,
            "relation": str(edge.get("type") or "") or relation_by_neighbor.get(consumer_id, ""),
        })
        if len(rows) >= edge_cap:
            break
    return rows, anchor


def find_contract_consumers(
    workspace_file: str | Path,
    target: str,
    *,
    tier: str = "standard",
    project: str = "",
) -> dict[str, Any]:
    """Consumers of a DTO/Feign/MQ/HTTP contract, bounded and deterministic."""
    budget = resolve_query_budget(tier, edges=TIER_BUDGETS[normalize_tier(tier)]["edges"])

    def _run() -> dict[str, Any]:
        edges, anchor = _consumer_edges_for_target(
            workspace_file,
            target,
            categories=_CONTRACT_EDGE_CATEGORIES,
            edge_cap=budget.edges,
            project=project,
        )
        ordered = _deterministic_sort(edges)
        truncated = len(ordered) >= budget.edges
        elapsed_ms, timed_out = _budget_outcome(budget)
        anchor_type = str((anchor or {}).get("type", ""))
        is_contract_anchor = anchor_type in _CONTRACT_NODE_TYPES
        return {
            "target": target,
            "found": bool(anchor),
            "is_contract_anchor": is_contract_anchor,
            "anchor": anchor,
            "consumers": ordered[: budget.edges],
            "query_budget": budget.report(elapsed_ms=elapsed_ms, timed_out=timed_out, truncated=truncated),
        }

    args = {"target": target, "project": project, "tier": budget.tier}
    key = template_cache_key(workspace_file, "find_contract_consumers", args)
    return cached_template(key, _run)


def plan_change_risk(workspace_file: str | Path, *, scope: str = "all", files: list[str] | None = None,
                     detail_level: str = "minimal", refresh: bool = True, max_depth: int = 3) -> dict[str, Any]:
    """Generation-keyed bounded template behind the existing change-review facade."""
    normalized_files = sorted({str(item).strip() for item in (files or []) if str(item).strip()})
    tier = "deep" if detail_level == "deep" else ("standard" if detail_level == "standard" else "fast")
    budget = resolve_query_budget(tier, depth=max_depth)

    def _run() -> dict[str, Any]:
        from memory_center.core.orchestrator.change_review import build_change_review_plan
        result = build_change_review_plan(workspace_file, scope=scope, files=normalized_files or None,
                                          detail_level=detail_level, refresh=refresh, max_depth=budget.depth)
        current = result.get("query_budget") if isinstance(result.get("query_budget"), dict) else {}
        elapsed_ms, timed_out = _budget_outcome(budget)
        result["query_budget"] = {**budget.report(elapsed_ms=elapsed_ms,
            timed_out=bool(current.get("timed_out", False) or timed_out),
            truncated=bool(current.get("truncated", False))), "template": "plan_change_risk"}
        return result

    args = {"scope": scope, "files": normalized_files, "detail_level": detail_level,
            "refresh": refresh, "max_depth": budget.depth}
    return cached_template(template_cache_key(workspace_file, "plan_change_risk", args), _run)
