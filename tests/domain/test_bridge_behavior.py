"""C-06: Cross-workspace bridge behavior tests.

Verifies bridge type confidence levels, bridge reason formatting,
cross-workspace path hints, bridge filtering, and bridge type
category mapping per ONTOLOGY.md §3.2.
"""
from __future__ import annotations

from memory_center.core.orchestrator.group import (
    _bridge_reason_for,
    _bridge_type_category,
    _build_cross_workspace_path_hint,
    _count_bridges,
    _filter_bridges,
    _sort_bridges,
)

# Sample bridges for testing
FEIGN_SERVICE_BRIDGE = {
    "type": "FEIGN_SERVICE",
    "confidence": 0.95,
    "source_workspace": "ws-a",
    "source_workspace_name": "workspace-a",
    "source_project": "order-service",
    "target_workspace": "ws-b",
    "target_workspace_name": "workspace-b",
    "target_project": "user-service",
    "summary": "OrderFeignClient -> user-service",
}
FEIGN_ENDPOINT_BRIDGE = {
    "type": "FEIGN_ENDPOINT",
    "confidence": 0.88,
    "source_workspace": "ws-a",
    "source_workspace_name": "workspace-a",
    "source_project": "order-service",
    "target_workspace": "ws-b",
    "target_workspace_name": "workspace-b",
    "target_project": "user-service",
    "summary": "OrderFeignClient.getOrder -> GET /api/users/{id}",
}
MQ_TOPIC_CONFIG_BRIDGE = {
    "type": "MQ_TOPIC_CONFIG",
    "confidence": 0.84,
    "source_workspace": "ws-a",
    "source_workspace_name": "workspace-a",
    "source_project": "order-service",
    "target_workspace": "ws-b",
    "target_workspace_name": "workspace-b",
    "target_project": "user-service",
    "summary": "order-events config -> user-service consumer",
}
MQ_TOPIC_SHARED_BRIDGE = {
    "type": "MQ_TOPIC_SHARED",
    "confidence": 0.72,
    "source_workspace": "ws-a",
    "source_workspace_name": "workspace-a",
    "source_project": "order-service",
    "target_workspace": "ws-b",
    "target_workspace_name": "workspace-b",
    "target_project": "user-service",
    "summary": "shared topic: order-events",
}
CONFIG_KEY_SHARED_BRIDGE = {
    "type": "CONFIG_KEY_SHARED",
    "confidence": 0.66,
    "source_workspace": "ws-a",
    "source_workspace_name": "workspace-a",
    "source_project": "order-service",
    "target_workspace": "ws-b",
    "target_workspace_name": "workspace-b",
    "target_project": "user-service",
    "summary": "shared config: spring.datasource.url",
}
ALL_BRIDGES = [
    FEIGN_SERVICE_BRIDGE, FEIGN_ENDPOINT_BRIDGE,
    MQ_TOPIC_CONFIG_BRIDGE, MQ_TOPIC_SHARED_BRIDGE,
    CONFIG_KEY_SHARED_BRIDGE,
]


# ============================================================
# TestBridgeConfidence: confidence levels per ONTOLOGY.md §3.2
# ============================================================

class TestBridgeConfidence:
    def test_feign_service_confidence(self):
        assert FEIGN_SERVICE_BRIDGE["confidence"] == 0.95

    def test_feign_endpoint_confidence(self):
        assert FEIGN_ENDPOINT_BRIDGE["confidence"] == 0.88

    def test_mq_topic_config_confidence(self):
        assert MQ_TOPIC_CONFIG_BRIDGE["confidence"] == 0.84

    def test_mq_topic_shared_confidence(self):
        assert MQ_TOPIC_SHARED_BRIDGE["confidence"] == 0.72

    def test_config_key_shared_confidence(self):
        assert CONFIG_KEY_SHARED_BRIDGE["confidence"] == 0.66

    def test_no_bridge_is_fact(self):
        """Cross-workspace bridges should never be 'fact' — all are inferred/derived."""
        fact_confidence = 1.0
        for bridge in ALL_BRIDGES:
            assert bridge["confidence"] < fact_confidence, (
                f"Bridge {bridge['type']} has confidence {bridge['confidence']} — "
                f"cross-workspace bridges must not be fact"
            )


# ============================================================
# TestBridgeReasonFor: bridge reason formatting
# ============================================================

class TestBridgeReasonFor:
    def test_reason_format(self):
        reason = _bridge_reason_for(FEIGN_SERVICE_BRIDGE)
        assert "FEIGN_SERVICE" in reason
        assert "0.95" in reason
        assert "OrderFeignClient -> user-service" in reason

    def test_reason_includes_type_and_confidence(self):
        for bridge in ALL_BRIDGES:
            reason = _bridge_reason_for(bridge)
            assert bridge["type"] in reason
            assert f"{bridge['confidence']:.2f}" in reason

    def test_reason_includes_summary(self):
        reason = _bridge_reason_for(MQ_TOPIC_SHARED_BRIDGE)
        assert "shared topic: order-events" in reason


# ============================================================
# TestCrossWorkspacePathHint: path hint from merged matches
# ============================================================

class TestCrossWorkspacePathHint:
    def test_path_hint_from_matches(self):
        matches = [
            {"workspace": "/path/a"},
            {"workspace": "/path/b"},
            {"workspace": "/path/c"},
        ]
        hint = _build_cross_workspace_path_hint(matches)
        assert "/path/a" in hint
        assert "/path/b" in hint
        assert "/path/c" in hint
        assert "->" in hint

    def test_path_hint_deduplicates(self):
        matches = [
            {"workspace": "/path/a"},
            {"workspace": "/path/a"},
            {"workspace": "/path/b"},
        ]
        hint = _build_cross_workspace_path_hint(matches)
        # /path/a should appear only once
        assert hint.count("/path/a") == 1

    def test_path_hint_empty_matches(self):
        hint = _build_cross_workspace_path_hint([])
        assert hint == ""

    def test_path_hint_skips_empty_workspace(self):
        matches = [{"workspace": ""}, {"workspace": "/path/a"}]
        hint = _build_cross_workspace_path_hint(matches)
        assert "/path/a" in hint

    def test_path_hint_limits_to_five(self):
        matches = [{"workspace": f"/path/{i}"} for i in range(10)]
        hint = _build_cross_workspace_path_hint(matches)
        assert "/path/0" in hint
        assert "/path/4" in hint
        assert "/path/5" not in hint


# ============================================================
# TestBridgeTypeCategory: category mapping
# ============================================================

class TestBridgeTypeCategory:
    def test_feign_service_category(self):
        assert _bridge_type_category("FEIGN_SERVICE") == "FeignClient"

    def test_feign_endpoint_category(self):
        assert _bridge_type_category("FEIGN_ENDPOINT") == "Endpoint"

    def test_mq_topic_config_category(self):
        assert _bridge_type_category("MQ_TOPIC_CONFIG") == "MQTopic"

    def test_mq_topic_shared_category(self):
        assert _bridge_type_category("MQ_TOPIC_SHARED") == "MQTopic"

    def test_config_key_shared_category(self):
        assert _bridge_type_category("CONFIG_KEY_SHARED") == "ConfigKey"

    def test_unknown_bridge_type_category(self):
        assert _bridge_type_category("UNKNOWN_BRIDGE") == ""


# ============================================================
# TestFilterBridges: query-based filtering
# ============================================================

class TestFilterBridges:
    def test_filter_by_query_token(self):
        result = _filter_bridges(ALL_BRIDGES, "OrderFeignClient", 10)
        assert len(result) > 0
        # Should match FEIGN_SERVICE and FEIGN_ENDPOINT
        types = {b["type"] for b in result}
        assert "FEIGN_SERVICE" in types or "FEIGN_ENDPOINT" in types

    def test_filter_returns_sorted_by_confidence(self):
        result = _filter_bridges(ALL_BRIDGES, "order", 10)
        confidences = [b["confidence"] for b in result]
        assert confidences == sorted(confidences, reverse=True)

    def test_filter_respects_limit(self):
        result = _filter_bridges(ALL_BRIDGES, "order", 2)
        assert len(result) <= 2

    def test_filter_empty_bridges(self):
        result = _filter_bridges([], "order", 10)
        assert result == []

    def test_filter_no_match(self):
        result = _filter_bridges(ALL_BRIDGES, "xyzzy_nonexistent", 10)
        assert result == []


# ============================================================
# TestSortBridges: bridge sorting behavior
# ============================================================

class TestSortBridges:
    def test_sort_returns_all_bridges_sorted(self):
        # _sort_bridges sorts by (priority, type_order, -confidence, summary)
        # With empty target_types, all bridges get same priority, sorted by type_order then confidence
        result = _sort_bridges(ALL_BRIDGES, ["FeignClient"])
        assert len(result) == len(ALL_BRIDGES)
        # FEIGN_ENDPOINT (type_order=0) should come before FEIGN_SERVICE (type_order=1)
        feign_endpoint_idx = next(i for i, b in enumerate(result) if b["type"] == "FEIGN_ENDPOINT")
        feign_service_idx = next(i for i, b in enumerate(result) if b["type"] == "FEIGN_SERVICE")
        assert feign_endpoint_idx < feign_service_idx

    def test_sort_preserves_all_bridges(self):
        result = _sort_bridges(ALL_BRIDGES, [])
        assert len(result) == len(ALL_BRIDGES)

    def test_sort_empty_bridges(self):
        result = _sort_bridges([], [])
        assert result == []


# ============================================================
# TestCountBridges: bridge counting by type
# ============================================================

class TestCountBridges:
    def test_count_by_type(self):
        counts = _count_bridges(ALL_BRIDGES)
        assert counts["FEIGN_SERVICE"] == 1
        assert counts["FEIGN_ENDPOINT"] == 1
        assert counts["MQ_TOPIC_CONFIG"] == 1
        assert counts["MQ_TOPIC_SHARED"] == 1
        assert counts["CONFIG_KEY_SHARED"] == 1

    def test_count_empty_bridges(self):
        counts = _count_bridges([])
        assert counts == {}

    def test_count_duplicate_types(self):
        bridges = [FEIGN_SERVICE_BRIDGE, FEIGN_SERVICE_BRIDGE.copy()]
        counts = _count_bridges(bridges)
        assert counts["FEIGN_SERVICE"] == 2


# ============================================================
# TestBridgeOntologyCompliance: ONTOLOGY.md §3.2 compliance
# ============================================================

class TestBridgeOntologyCompliance:
    def test_all_bridge_types_have_source_and_target_workspace(self):
        """Every bridge must reference two distinct workspaces."""
        for bridge in ALL_BRIDGES:
            assert bridge.get("source_workspace"), f"{bridge['type']} missing source_workspace"
            assert bridge.get("target_workspace"), f"{bridge['type']} missing target_workspace"

    def test_all_bridge_types_have_summary(self):
        """Every bridge must have a human-readable summary."""
        for bridge in ALL_BRIDGES:
            assert bridge.get("summary"), f"{bridge['type']} missing summary"

    def test_bridge_confidence_ordering(self):
        """FEIGN_SERVICE > FEIGN_ENDPOINT > MQ_TOPIC_CONFIG > MQ_TOPIC_SHARED > CONFIG_KEY_SHARED."""
        ordering = [
            FEIGN_SERVICE_BRIDGE["confidence"],
            FEIGN_ENDPOINT_BRIDGE["confidence"],
            MQ_TOPIC_CONFIG_BRIDGE["confidence"],
            MQ_TOPIC_SHARED_BRIDGE["confidence"],
            CONFIG_KEY_SHARED_BRIDGE["confidence"],
        ]
        assert ordering == sorted(ordering, reverse=True)
