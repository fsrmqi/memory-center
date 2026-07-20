from __future__ import annotations

from memory_center.core.assessment.quality import (
    EVIDENCE_LEVEL_AMBIGUOUS,
    EVIDENCE_LEVEL_EXTRACTED,
    EVIDENCE_LEVEL_INFERRED,
    EVIDENCE_LEVEL_VERIFIED,
    build_quality_summary,
    evidence_level_for,
)
from memory_center.core.explanation import explanation_entry, merge_explanations
from memory_center.core.storage.graph import GraphEdge, GraphNode
from memory_center.core.storage.runtime import RuntimeStore


def test_evidence_level_preserves_verified_as_explicit_opt_in() -> None:
    assert evidence_level_for({"semantic_strength": "fact", "confidence": 1.0}) == EVIDENCE_LEVEL_EXTRACTED
    assert evidence_level_for({"semantic_strength": "inferred", "confidence": 0.99}) == EVIDENCE_LEVEL_INFERRED
    assert evidence_level_for({"_is_fallback": True, "semantic_strength": "fact"}) == EVIDENCE_LEVEL_AMBIGUOUS
    assert evidence_level_for({"semantic_strength": "fact", "verified": True}) == EVIDENCE_LEVEL_VERIFIED


def test_explanation_entry_adds_compatible_evidence_level() -> None:
    extracted = explanation_entry(summary="direct", semantic_strength="fact")
    verified = explanation_entry(summary="checked", semantic_strength="fact", evidence_level="VERIFIED")

    assert extracted["semantic_strength"] == "fact"
    assert extracted["evidence_level"] == EVIDENCE_LEVEL_EXTRACTED
    assert verified["evidence_level"] == EVIDENCE_LEVEL_VERIFIED


def test_merged_explanation_uses_the_weakest_evidence_level() -> None:
    merged = merge_explanations(
        [
            explanation_entry(summary="checked", semantic_strength="fact", evidence_level="VERIFIED"),
            explanation_entry(summary="candidate", semantic_strength="derived"),
        ]
    )

    assert merged["evidence_level"] == EVIDENCE_LEVEL_INFERRED


def test_quality_summary_counts_evidence_levels_without_changing_legacy_counts() -> None:
    summary = build_quality_summary(
        [
            {"semantic_strength": "fact", "confidence": 1.0},
            {"semantic_strength": "inferred", "confidence": 0.8},
            {"_is_fallback": True, "semantic_strength": "fact", "confidence": 0.9},
            {"semantic_strength": "fact", "verified": True, "confidence": 1.0},
        ]
    )

    assert summary["evidence_level_counts"] == {
        "AMBIGUOUS": 1,
        "EXTRACTED": 1,
        "INFERRED": 1,
        "VERIFIED": 1,
    }
    assert summary["verification_required"] is True


def test_graph_edge_read_and_write_expose_evidence_level(tmp_path) -> None:
    graph = RuntimeStore(tmp_path / "graph.db")
    graph.rebuild(
        [
            GraphNode("Method:a", "Method", "a"),
            GraphNode("Method:b", "Method", "b"),
        ],
        [GraphEdge("CALLS_METHOD:a-b", "Method:a", "Method:b", "CALLS_METHOD")],
    )

    edge = graph.traverse_edges("Method:a", direction="downstream", max_depth=1)[0]

    assert edge["evidence_level"] == EVIDENCE_LEVEL_EXTRACTED
    assert edge["metadata"]["evidence_level"] == EVIDENCE_LEVEL_EXTRACTED
