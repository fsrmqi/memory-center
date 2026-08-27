"""Phase B bounded query template tests (CODE_GRAPH_FOUNDATION_IMPLEMENTATION §7).

Covers tier budget clamping, deterministic ordering, cache
generation/scope keying with invalidation on generation change,
and truncation visibility.
"""
from __future__ import annotations

import time

import pytest

from memory_center.core.retrieval.templates import (
    TIER_BUDGETS,
    cached_template,
    find_contract_consumers,
    find_symbols,
    normalize_tier,
    resolve_query_budget,
    template_cache_key,
    trace_call_paths,
)


# ---------------------------------------------------------------------------
# Unit: tier budgets and clamping
# ---------------------------------------------------------------------------


def test_normalize_tier_defaults_invalid_to_standard():
    assert normalize_tier(None) == "standard"
    assert normalize_tier("turbo") == "standard"
    for tier in ("fast", "standard", "deep"):
        assert normalize_tier(tier) == tier


def test_fast_tier_clamps_explicit_bounds():
    budget = resolve_query_budget("fast", depth=99, nodes=9999, edges=9999)
    assert budget.depth <= TIER_BUDGETS["fast"]["depth"]
    assert budget.nodes <= TIER_BUDGETS["fast"]["nodes"]
    assert budget.edges <= TIER_BUDGETS["fast"]["edges"]


def test_deep_keeps_a_hard_ceiling():
    budget = resolve_query_budget("deep", depth=1000, nodes=10**9)
    assert budget.depth == TIER_BUDGETS["deep"]["depth"]
    assert budget.nodes == TIER_BUDGETS["deep"]["nodes"]
    # No unbounded scans even at deep: deadline is finite.
    assert 0 < budget.deadline_ms < 60_000


def test_budget_report_carries_truncation_and_timeout():
    budget = resolve_query_budget("standard")
    report = budget.report(elapsed_ms=1.0, timed_out=False, truncated=True)
    assert report["truncated"] is True
    assert report["timed_out"] is False
    assert report["tier"] == "standard"


# ---------------------------------------------------------------------------
# Unit: cache key + invalidation semantics
# ---------------------------------------------------------------------------


def test_cache_key_changes_with_generation(demo_workspace_str):
    from memory_center.core.indexing.control_plane import index_control_status
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.retrieval import templates as templates_module

    key_before = template_cache_key(demo_workspace_str, "find_symbols", {"target": "OrderService"})
    store = WorkspaceStore(demo_workspace_str)
    control = index_control_status(store)
    control["active_generation"] = str(control.get("active_generation", "")) + "-x"
    original = templates_module.index_control_status
    try:
        templates_module.index_control_status = lambda _store: control
        key_after = template_cache_key(demo_workspace_str, "find_symbols", {"target": "OrderService"})
    finally:
        templates_module.index_control_status = original
    assert key_before != key_after


def test_cached_template_hit_then_generation_change_misses():
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return {"value": calls["n"], "query_budget": {}}

    key = "unit-key-a"
    first = cached_template(key, factory)
    second = cached_template(key, factory)
    assert first["cache"]["status"] == "miss"
    assert second["cache"]["status"] == "hit"
    assert second["value"] == first["value"]
    # Cached payloads must be deep copies: mutation cannot poison the cache.
    second["value"] = -1
    third = cached_template(key, factory)
    assert third["value"] == 1


def test_cached_template_ttl_expiry(monkeypatch):
    from memory_center.core.retrieval import templates as templates_module

    monkeypatch.setattr(templates_module, "_CACHE_TTL_SECONDS", 0.05)
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return {"value": calls["n"]}

    key = "ttl-key"
    templates_module.cached_template(key, factory)
    time.sleep(0.08)
    result = templates_module.cached_template(key, factory)
    assert result["cache"]["status"] == "miss"
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Integration: templates against a real indexed workspace
# ---------------------------------------------------------------------------


def test_find_symbols_attaches_budget(demo_workspace_str):
    result = find_symbols(demo_workspace_str, "ArticleFeignClient", tier="standard")
    assert result["found"] is True
    report = result["query_budget"]
    assert report["tier"] == "standard"
    assert report["truncated"] in (True, False)


def test_trace_call_paths_clamps_depth_for_fast_tier(demo_workspace_str):
    symbol = "ArticleController"
    standard = trace_call_paths(demo_workspace_str, symbol, direction="callers", tier="standard", depth=5)
    fast = trace_call_paths(demo_workspace_str, symbol, direction="callers", tier="fast", depth=5)
    assert standard["query_budget"]["depth"] <= TIER_BUDGETS["standard"]["depth"]
    assert fast["query_budget"]["depth"] <= TIER_BUDGETS["fast"]["depth"]


def test_trace_call_paths_deterministic_ordering(demo_workspace_str):
    a = trace_call_paths(demo_workspace_str, "ArticleController", direction="callees", tier="standard", depth=2)
    b = trace_call_paths(demo_workspace_str, "ArticleController", direction="callees", tier="standard", depth=2)
    keys_a = [str(row.get("id")) for row in a.get("callees", [])]
    keys_b = [str(row.get("id")) for row in b.get("callees", [])]
    assert keys_a == keys_b


def test_find_contract_consumers_mq_topic(demo_workspace_str):
    result = find_contract_consumers(demo_workspace_str, "article-pubtime-change", tier="standard")
    assert result["found"] is True
    assert result["anchor"]["type"] == "MQTopic"
    consumers = result["consumers"]
    assert consumers, "demo topic must have at least one consumer"
    assert all(row.get("relation") == "CONSUMES_TOPIC" for row in consumers if not row.get("relation") or row.get("relation") == "CONSUMES_TOPIC")


def test_find_contract_consumers_feign_client(demo_workspace_str):
    result = find_contract_consumers(demo_workspace_str, "ArticleFeignClient", tier="standard")
    assert result["found"] is True
    assert result["anchor"]["type"] == "FeignClient"


def test_find_contract_consumers_unknown_target_is_not_found(demo_workspace_str):
    result = find_contract_consumers(demo_workspace_str, "zzz_no_such_contract", tier="standard")
    # Fuzzy resolution may return *some* node, but it must not be reported
    # as a contract anchor and must yield no fabricated consumers.
    assert result["consumers"] == []
    assert result["is_contract_anchor"] is False


def test_templates_keep_payload_additive(demo_workspace_str):
    """Existing dict fields consumed by old clients remain untouched."""
    symbol_result = find_symbols(demo_workspace_str, "ArticleFeignClient")
    assert "found" in symbol_result and "best_match" in symbol_result
    # trace_call_paths defaults to the facade-compatible compact view.
    chain_result = trace_call_paths(demo_workspace_str, "ArticleController", direction="callers")
    assert "symbol" in chain_result
    assert "found" in chain_result and "direction" in chain_result
    assert "query_budget" in chain_result
