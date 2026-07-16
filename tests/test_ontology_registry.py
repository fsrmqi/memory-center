"""C-01: Ontology registry consistency tests.

Verifies that the ontology registry in ontology.py is self-consistent,
handles unknown types correctly, and that documentation matches code.
"""
from __future__ import annotations

import pytest

from memory_center.core.knowledge.ontology import (
    ALL_EDGE_TYPES,
    ALL_NODE_TYPES,
    EDGE_CONFIDENCE_RANGES,
    EDGE_SEMANTIC_STRENGTH,
    EntityValidator,
    annotate_semantic_strength,
    edge_confidence_range,
    edge_strength,
    multi_hop_confidence,
    validate_edge_type,
    validate_node_type,
)

# ============================================================
# TestRegistryCompleteness: all edges have required metadata
# ============================================================

class TestRegistryCompleteness:
    def test_all_edges_have_semantic_strength(self):
        """Every edge in ALL_EDGE_TYPES must have a strength entry."""
        missing = ALL_EDGE_TYPES - set(EDGE_SEMANTIC_STRENGTH.keys())
        assert not missing, f"Edges missing semantic strength: {missing}"

    def test_semantic_strength_valid_values(self):
        """Semantic strength must be one of: confirmed, derived, inferred, runtime."""
        valid = {"confirmed", "derived", "inferred", "runtime"}
        for edge_type, strength in EDGE_SEMANTIC_STRENGTH.items():
            assert strength in valid, f"{edge_type}: invalid strength {strength!r}"

    def test_confidence_range_subset_of_edges(self):
        """EDGE_CONFIDENCE_RANGES keys must be subset of ALL_EDGE_TYPES."""
        unknown = set(EDGE_CONFIDENCE_RANGES.keys()) - ALL_EDGE_TYPES
        assert not unknown, f"Confidence ranges for unknown edges: {unknown}"

    def test_confidence_range_values_valid(self):
        """Confidence ranges must be (low, high) with 0 <= low <= high <= 1."""
        for edge_type, (low, high) in EDGE_CONFIDENCE_RANGES.items():
            assert 0.0 <= low <= high <= 1.0, f"{edge_type}: invalid range ({low}, {high})"

    def test_all_node_types_nonempty(self):
        """ALL_NODE_TYPES should have at least the 8 core types."""
        core_types = {"Service", "Class", "Method", "Endpoint", "FeignClient", "MQTopic", "MQConsumer", "MQProducer"}
        missing = core_types - ALL_NODE_TYPES
        assert not missing, f"Core node types missing: {missing}"

    def test_all_edge_types_nonempty(self):
        """ALL_EDGE_TYPES should have at least 14 types (docs §3.1 baseline)."""
        assert len(ALL_EDGE_TYPES) >= 14, f"Expected >=14 edge types, got {len(ALL_EDGE_TYPES)}"

    def test_edge_type_count_matches_strength_count(self):
        """Every edge in ALL_EDGE_TYPES must have exactly one strength mapping."""
        for edge in ALL_EDGE_TYPES:
            assert edge in EDGE_SEMANTIC_STRENGTH, f"{edge} not in EDGE_SEMANTIC_STRENGTH"


# ============================================================
# TestUnknownTypeHandling: unknown types return safe defaults
# ============================================================

class TestUnknownTypeHandling:
    def test_unknown_edge_strength_returns_unknown(self):
        """Unknown edge type must return 'unknown', not 'fact'."""
        assert edge_strength("NONEXISTENT_EDGE") == "unknown"

    def test_unknown_edge_confidence_range_returns_full(self):
        """Unknown edge type returns (0.0, 1.0) — broad default, not crash."""
        low, high = edge_confidence_range("NONEXISTENT_EDGE")
        assert low == 0.0
        assert high == 1.0

    def test_validate_unknown_edge_type(self):
        assert validate_edge_type("NONEXISTENT") is False

    def test_validate_unknown_node_type(self):
        assert validate_node_type("NONEXISTENT") is False

    def test_annotate_unknown_edge_type(self):
        """annotate_semantic_strength should mark unknown edges as 'unknown'."""
        results = [{"edge_type": "FAKE_EDGE", "name": "test"}]
        annotated = annotate_semantic_strength(results)
        assert annotated[0]["semantic_strength"] == "unknown"

    def test_annotate_missing_edge_type(self):
        """annotate_semantic_strength should handle missing edge_type gracefully."""
        results = [{"name": "test", "type": "UnknownNodeType"}]
        annotated = annotate_semantic_strength(results)
        # No edge_type, unknown node type → should get "unknown"
        assert annotated[0]["semantic_strength"] == "unknown"

    def test_classify_unknown_entity_category(self):
        """EntityValidator.classify_entity_category returns 'unknown' for unknown types."""
        assert EntityValidator.classify_entity_category("WeirdNewType") == "unknown"


# ============================================================
# TestKnownEdgeStrengths: verify specific edge strengths match semantics
# ============================================================

class TestKnownEdgeStrengths:
    @pytest.mark.parametrize("edge_type", [
        "CONTAINS", "DECLARES", "EXPOSES_ENDPOINT",
        "PRODUCES_TOPIC", "CONSUMES_TOPIC",
    ])
    def test_structural_edges_are_confirmed(self, edge_type):
        assert EDGE_SEMANTIC_STRENGTH[edge_type] == "confirmed"

    @pytest.mark.parametrize("edge_type", [
        "CALLS_METHOD", "CALLS_SERVICE", "INJECTS", "IMPORTS",
        "READS_CONFIG",
    ])
    def test_intra_workspace_edges_are_confirmed(self, edge_type):
        """These edges are directly observed in source code."""
        assert EDGE_SEMANTIC_STRENGTH[edge_type] == "confirmed"

    @pytest.mark.parametrize("edge_type", [
        "TRANSITIVELY_CALLS", "HISTORICALLY_RELATED",
        "SEMANTIC_SIMILAR", "RISK_CORRELATED", "EXPLAINS",
    ])
    def test_derived_edges(self, edge_type):
        assert EDGE_SEMANTIC_STRENGTH[edge_type] == "derived"

    @pytest.mark.parametrize("edge_type", [
        "DATA_FLOWS_TO", "CONFIG_PROPAGATES",
        "IMPLEMENTS_FLOW_STEP", "NEXT_STEP",
    ])
    def test_inferred_edges(self, edge_type):
        assert EDGE_SEMANTIC_STRENGTH[edge_type] == "inferred"

    def test_stale_for_is_runtime(self):
        assert EDGE_SEMANTIC_STRENGTH["STALE_FOR"] == "runtime"


# ============================================================
# TestMultiHopConfidence: decay rules
# ============================================================

class TestMultiHopConfidence:
    def test_single_hop_no_decay(self):
        assert multi_hop_confidence(0.9, 1) == 0.9

    def test_two_hop_decay(self):
        assert multi_hop_confidence(1.0, 2) == 0.9

    def test_three_hop_decay(self):
        assert multi_hop_confidence(1.0, 3) == 0.8

    def test_four_plus_hop_decay(self):
        assert multi_hop_confidence(1.0, 4) == 0.7
        assert multi_hop_confidence(1.0, 10) == 0.7

    def test_decay_preserves_low_confidence(self):
        result = multi_hop_confidence(0.5, 2)
        assert result == 0.45  # 0.5 * 0.9

    def test_zero_hops_returns_base(self):
        assert multi_hop_confidence(0.8, 0) == 0.8


# ============================================================
# TestConfidenceLabel: unified confidence label helper
# ============================================================

class TestConfidenceLabel:
    """Tests for confidence_label() — maps numeric confidence to human label."""

    def test_high_confidence(self):
        from memory_center.core.knowledge.ontology import confidence_label
        assert confidence_label(1.0) == "high"
        assert confidence_label(0.9) == "high"
        assert confidence_label(0.8) == "high"

    def test_medium_confidence(self):
        from memory_center.core.knowledge.ontology import confidence_label
        assert confidence_label(0.79) == "medium"
        assert confidence_label(0.6) == "medium"
        assert confidence_label(0.5) == "medium"

    def test_low_confidence(self):
        from memory_center.core.knowledge.ontology import confidence_label
        assert confidence_label(0.49) == "low"
        assert confidence_label(0.1) == "low"
        assert confidence_label(0.0) == "low"

    def test_boundary_values(self):
        from memory_center.core.knowledge.ontology import confidence_label
        assert confidence_label(0.8) == "high"
        assert confidence_label(0.5) == "medium"
        assert confidence_label(0.0) == "low"


# ============================================================
# TestEntityValidator: entity classification
# ============================================================

class TestEntityValidator:
    def test_feign_detection(self):
        assert EntityValidator.is_feign_entity("ArticleFeignClient") is True
        assert EntityValidator.is_feign_entity("FeginAutomaticReviewTaskService") is True
        assert EntityValidator.is_feign_entity("ArticleService") is False

    def test_local_service_detection(self):
        assert EntityValidator.is_local_service("ArticleService", node_type="Class") is True
        assert EntityValidator.is_local_service("ArticleFeignClient", node_type="Class") is False

    def test_endpoint_path_validation(self):
        result = EntityValidator.validate_endpoint_path("/api/users")
        assert result["is_specific"] is True
        assert result["confidence"] == 0.9

    def test_single_segment_endpoint_is_low_confidence(self):
        result = EntityValidator.validate_endpoint_path("/")
        assert result["is_specific"] is False
        assert result["confidence"] == 0.1

    def test_structural_types(self):
        assert EntityValidator.classify_entity_category("Service") == "structural"
        assert EntityValidator.classify_entity_category("File") == "structural"

    def test_declarative_types(self):
        assert EntityValidator.classify_entity_category("Class") == "declarative"
        assert EntityValidator.classify_entity_category("Method") == "declarative"

    def test_contractual_types(self):
        assert EntityValidator.classify_entity_category("Endpoint") == "contractual"
        assert EntityValidator.classify_entity_category("FeignClient") == "contractual"
        assert EntityValidator.classify_entity_category("MQTopic") == "contractual"

    def test_memory_types(self):
        assert EntityValidator.classify_entity_category("SessionEvent") == "memory"
        assert EntityValidator.classify_entity_category("WriteReceipt") == "memory"
        assert EntityValidator.classify_entity_category("Task") == "memory"


# ============================================================
# TestValidateTypes: known types validate correctly
# ============================================================

class TestValidateTypes:
    def test_known_node_types_validate(self):
        for node_type in list(ALL_NODE_TYPES)[:5]:
            assert validate_node_type(node_type) is True

    def test_known_edge_types_validate(self):
        for edge_type in list(ALL_EDGE_TYPES)[:5]:
            assert validate_edge_type(edge_type) is True
