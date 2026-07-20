"""C-05: Chain / Callers / Callees behavior tests.

Verifies edge filtering, noise removal, deduplication,
and compress_chain_tree behavior for memory_callers/memory_callees.
"""
from __future__ import annotations

from memory_center.core.orchestrator.query import _compress_chain_tree
from memory_center.core.orchestrator.shared import (
    _INBOUND_PREFERRED,
    _OUTBOUND_PREFERRED,
    _filter_call_edges,
    _is_noise_call,
)

# Sample edges for testing
EDGE_CALLS_METHOD = {"type": "CALLS_METHOD", "target": {"name": "com.example.OrderService.getOrder"}, "confidence": 0.9, "depth": 1}
EDGE_CALLS_SERVICE = {"type": "CALLS_SERVICE", "target": {"name": "com.example.UserService"}, "confidence": 0.8, "depth": 1}
EDGE_DECLARES = {"type": "DECLARES", "target": {"name": "com.example.Order"}, "confidence": 1.0, "depth": 1}
EDGE_CONTAINS = {"type": "CONTAINS", "target": {"name": "com.example.order-service"}, "confidence": 1.0, "depth": 1}
EDGE_HANDLES_ENDPOINT = {"type": "HANDLES_ENDPOINT", "target": {"name": "com.example.OrderController.getOrder"}, "confidence": 0.9, "depth": 1}
EDGE_PRODUCES_TOPIC = {"type": "PRODUCES_TOPIC", "target": {"name": "order-events"}, "confidence": 1.0, "depth": 1}
EDGE_CONSUMES_TOPIC = {"type": "CONSUMES_TOPIC", "target": {"name": "order-events"}, "confidence": 1.0, "depth": 1}
EDGE_READS_FIELD = {"type": "READS_FIELD", "target": {"name": "com.example.OrderService.totalAmount"}, "confidence": 0.7, "depth": 1}
EDGE_READS_CONFIG = {"type": "READS_CONFIG", "target": {"name": "spring.datasource.url"}, "confidence": 0.8, "depth": 1}
EDGE_INJECTS = {"type": "INJECTS", "target": {"name": "com.example.OrderRepository"}, "confidence": 0.8, "depth": 1}
EDGE_IMPORTS = {"type": "IMPORTS", "target": {"name": "com.example.common"}, "confidence": 0.6, "depth": 1}
EDGE_TRANSITIVELY = {"type": "TRANSITIVELY_CALLS", "target": {"name": "com.example.InventoryService.check"}, "confidence": 0.5, "depth": 2}
EDGE_SEMANTIC = {"type": "SEMANTIC_SIMILAR", "target": {"name": "com.example.OrderValidator"}, "confidence": 0.3, "depth": 1}

# Noise edges
EDGE_GETTER = {"type": "CALLS_METHOD", "target": {"name": "getName"}, "confidence": 0.9, "depth": 1}
EDGE_SETTER = {"type": "CALLS_METHOD", "target": {"name": "setName"}, "confidence": 0.9, "depth": 1}
EDGE_IS_CHECK = {"type": "CALLS_METHOD", "target": {"name": "isActive"}, "confidence": 0.9, "depth": 1}
EDGE_EQUALS = {"type": "CALLS_METHOD", "target": {"name": "equals"}, "confidence": 0.9, "depth": 1}
EDGE_STREAM = {"type": "CALLS_METHOD", "target": {"name": "stream"}, "confidence": 0.9, "depth": 1}
EDGE_CLASS_PREFIXED_REAL = {"type": "CALLS_METHOD", "target": {"name": "com.example.OrderService.process"}, "confidence": 0.9, "depth": 1}


# ============================================================
# TestNoiseFiltering: _is_noise_call behavior
# ============================================================

class TestNoiseFiltering:
    def test_getter_is_noise(self):
        assert _is_noise_call(EDGE_GETTER) is True

    def test_setter_is_noise(self):
        assert _is_noise_call(EDGE_SETTER) is True

    def test_boolean_getter_is_noise(self):
        assert _is_noise_call(EDGE_IS_CHECK) is True

    def test_equals_is_not_noise(self):
        # equals is not in _NOISE_METHODS
        assert _is_noise_call(EDGE_EQUALS) is False

    def test_stream_is_noise(self):
        # stream is in _NOISE_METHODS
        assert _is_noise_call(EDGE_STREAM) is True

    def test_class_prefixed_real_method_is_not_noise(self):
        """Class-prefixed real methods (e.g. OrderService.process) are not noise."""
        assert _is_noise_call(EDGE_CLASS_PREFIXED_REAL) is False

    def test_real_method_is_not_noise(self):
        assert _is_noise_call(EDGE_CALLS_METHOD) is False

    def test_non_calls_method_is_not_noise(self):
        assert _is_noise_call(EDGE_DECLARES) is False


# ============================================================
# TestEdgeFiltering: _filter_call_edges behavior
# ============================================================

class TestEdgeFiltering:
    def test_upstream_excludes_declares_and_contains(self):
        """Callers should not include DECLARES or CONTAINS (structural edges)."""
        edges = [EDGE_CALLS_METHOD, EDGE_DECLARES, EDGE_CONTAINS, EDGE_CALLS_SERVICE]
        result = _filter_call_edges(edges, direction="upstream")
        types = {e["type"] for e in result}
        assert "DECLARES" not in types
        assert "CONTAINS" not in types
        assert "CALLS_METHOD" in types or "CALLS_SERVICE" in types

    def test_downstream_excludes_declares_and_contains(self):
        """Callees should not include DECLARES or CONTAINS."""
        edges = [EDGE_HANDLES_ENDPOINT, EDGE_DECLARES, EDGE_CONTAINS, EDGE_PRODUCES_TOPIC]
        result = _filter_call_edges(edges, direction="downstream")
        types = {e["type"] for e in result}
        assert "DECLARES" not in types
        assert "CONTAINS" not in types

    def test_upstream_includes_preferred_types(self):
        edges = [EDGE_CALLS_METHOD, EDGE_CALLS_SERVICE, EDGE_READS_FIELD, EDGE_READS_CONFIG, EDGE_CONSUMES_TOPIC]
        result = _filter_call_edges(edges, direction="upstream")
        types = {e["type"] for e in result}
        for t in types:
            assert t in _INBOUND_PREFERRED

    def test_downstream_includes_preferred_types(self):
        edges = [EDGE_HANDLES_ENDPOINT, EDGE_PRODUCES_TOPIC, EDGE_CALLS_METHOD]
        result = _filter_call_edges(edges, direction="downstream")
        types = {e["type"] for e in result}
        for t in types:
            assert t in _OUTBOUND_PREFERRED

    def test_noise_edges_filtered_out(self):
        edges = [EDGE_GETTER, EDGE_SETTER, EDGE_IS_CHECK, EDGE_CALLS_METHOD]
        result = _filter_call_edges(edges, direction="upstream")
        names = [e.get("target", {}).get("name", "") for e in result]
        assert "getName" not in names
        assert "setName" not in names
        assert "isActive" not in names
        assert "com.example.OrderService.getOrder" in names

    def test_results_sorted_by_confidence_desc(self):
        edges = [EDGE_READS_FIELD, EDGE_CALLS_METHOD, EDGE_CALLS_SERVICE]
        result = _filter_call_edges(edges, direction="upstream")
        confidences = [float(e.get("confidence", 0)) for e in result]
        assert confidences == sorted(confidences, reverse=True)

    def test_empty_edges_returns_empty(self):
        result = _filter_call_edges([], direction="upstream")
        assert result == []

    def test_unrelated_edge_types_filtered_out(self):
        edges = [EDGE_TRANSITIVELY, EDGE_SEMANTIC]
        result = _filter_call_edges(edges, direction="upstream")
        assert len(result) == 0


# ============================================================
# TestDeduplication: keep class-prefixed over short name
# ============================================================

class TestDeduplication:
    def test_class_prefixed_wins_over_short(self):
        """When both short and class-prefixed names exist, keep class-prefixed."""
        short = {"type": "CALLS_METHOD", "target": {"name": "getOrder"}, "confidence": 0.7, "depth": 1}
        prefixed = {"type": "CALLS_METHOD", "target": {"name": "com.example.OrderService.getOrder"}, "confidence": 0.9, "depth": 1}
        result = _filter_call_edges([short, prefixed], direction="upstream")
        names = [e.get("target", {}).get("name", "") for e in result]
        assert "com.example.OrderService.getOrder" in names
        assert "getOrder" not in names

    def test_no_duplicates_in_output(self):
        edges = [EDGE_CALLS_METHOD, EDGE_CALLS_METHOD.copy()]
        result = _filter_call_edges(edges, direction="upstream")
        names = [e.get("target", {}).get("name", "") for e in result]
        assert len(names) == len(set(names))


# ============================================================
# TestCompressChainTree: _compress_chain_tree behavior
# ============================================================

class TestCompressChainTree:
    def test_compress_returns_summary(self):
        edges = [EDGE_CALLS_METHOD, EDGE_CALLS_SERVICE]
        result = _compress_chain_tree(edges)
        assert "total_edges" in result
        assert "tree" in result
        assert "depth_reached" in result
        assert "unique_sources" in result

    def test_compress_counts_edges(self):
        edges = [EDGE_CALLS_METHOD, EDGE_CALLS_SERVICE, EDGE_CALLS_METHOD.copy()]
        result = _compress_chain_tree(edges)
        assert result["total_edges"] == 3
        assert result["unique_sources"] >= 1

    def test_compress_empty_edges(self):
        result = _compress_chain_tree([])
        assert result["total_edges"] == 0

    def test_compress_tracks_depth_reached(self):
        deep = {"type": "CALLS_METHOD", "target": {"name": "deep"}, "confidence": 0.5, "depth": 5}
        shallow = {"type": "CALLS_METHOD", "target": {"name": "shallow"}, "confidence": 0.9, "depth": 1}
        result = _compress_chain_tree([deep, shallow])
        assert result["depth_reached"] == 5


# ============================================================
# TestInboundOutboundPreferred: edge type membership
# ============================================================

class TestPreferredEdgeTypes:
    def test_inbound_excludes_structural(self):
        assert "DECLARES" not in _INBOUND_PREFERRED
        assert "CONTAINS" not in _INBOUND_PREFERRED

    def test_outbound_excludes_structural(self):
        assert "DECLARES" not in _OUTBOUND_PREFERRED
        assert "CONTAINS" not in _OUTBOUND_PREFERRED

    def test_inbound_includes_call_edges(self):
        assert "CALLS_METHOD" in _INBOUND_PREFERRED
        assert "CALLS_SERVICE" in _INBOUND_PREFERRED

    def test_outbound_includes_endpoint_and_topic(self):
        assert "HANDLES_ENDPOINT" in _OUTBOUND_PREFERRED
        assert "PRODUCES_TOPIC" in _OUTBOUND_PREFERRED
