from __future__ import annotations

from memory_center.core.assessment.quality import build_quality_summary


def test_quality_summary_classifies_fact_inferred_and_derived() -> None:
    summary = build_quality_summary(
        [
            {"evidence_type": "fact", "confidence": 1.0},
            {"confidence": 0.7},
            {"confidence": 0.3},
        ],
        freshness_status="stale",
    )
    assert summary["evidence_counts"] == {"fact": 1, "inferred": 1, "derived": 1}
    assert summary["verification_required"] is True
    assert "refresh_index" in summary["recommended_actions"]


def test_quality_summary_marks_high_confidence_fresh_evidence_ready() -> None:
    summary = build_quality_summary(
        [{"evidence_type": "fact", "confidence": 0.95}],
        freshness_status="fresh",
    )
    assert summary["verification_required"] is False
    assert summary["confidence"] == 0.95
