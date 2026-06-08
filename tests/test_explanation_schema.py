"""Tests for D-03: Unified Explanation Schema helpers."""
from __future__ import annotations
import shutil
from pathlib import Path
import pytest

from memory_center.core.explanation import (
    Explanation,
    explanation_entry,
    merge_explanations,
    backward_compat_wrapper,
)

class TestExplanationEntry:
    def test_basic_entry(self):
        e = explanation_entry(summary="test", confidence=0.8)
        assert e["summary"] == "test"
        assert e["confidence"] == 0.8
        assert e["semantic_strength"] == "inferred"
        assert e["evidence"] == []
        assert e["next_actions"] == []

    def test_all_fields(self):
        e = explanation_entry(subject="s", summary="s", evidence=[{"k": "v"}], semantic_strength="fact", confidence=0.95, next_actions=["a1"])
        assert e["semantic_strength"] == "fact"
        assert len(e["evidence"]) == 1
        assert e["next_actions"] == ["a1"]

    def test_invalid_strength_fallback(self):
        e = explanation_entry(summary="s", semantic_strength="bogus")
        assert e["semantic_strength"] == "inferred"

    def test_confidence_clamped_low(self):
        e = explanation_entry(summary="s", confidence=-0.5)
        assert e["confidence"] == 0.0

    def test_confidence_clamped_high(self):
        e = explanation_entry(summary="s", confidence=1.5)
        assert e["confidence"] == 1.0

class TestMergeExplanations:
    def test_empty_list(self):
        result = merge_explanations([])
        assert result["summary"] == "No explanations available"

    def test_single_entry(self):
        e = explanation_entry(summary="only one", confidence=0.7)
        result = merge_explanations([e])
        assert "only one" in result["summary"]

    def test_weakest_strength(self):
        e1 = explanation_entry(summary="a", semantic_strength="fact", confidence=0.9)
        e2 = explanation_entry(summary="b", semantic_strength="derived", confidence=0.5)
        result = merge_explanations([e1, e2])
        assert result["semantic_strength"] == "derived"
        assert result["confidence"] == 0.5

    def test_evidence_merged(self):
        e1 = explanation_entry(summary="a", evidence=[{"k": 1}])
        e2 = explanation_entry(summary="b", evidence=[{"k": 2}, {"k": 3}])
        result = merge_explanations([e1, e2])
        assert len(result["evidence"]) == 3

class TestBackwardCompat:
    def test_already_new_format(self):
        new = explanation_entry(summary="new")
        result = backward_compat_wrapper(new)
        assert result is new

    def test_old_format_preserved(self):
        old = {"confirmed": ">=0.80", "probable": ">=0.55"}
        result = backward_compat_wrapper(old)
        assert result["confirmed"] == ">=0.80"
        assert result["semantic_strength"] == "inferred"

class TestExplanationDataclass:
    def test_to_compact(self):
        e = Explanation(subject="test", summary="summary", confidence=0.8)
        c = e.to_compact()
        assert c["subject"] == "test"
        assert c["strength"] == "inferred"

    def test_adapt_for_persona(self):
        e = Explanation(subject="test", summary="s", next_actions=["check architecture risk"])
        a = e.adapt_for_persona("architect")
        assert "[architect]" in a.summary or "[架构视角]" in a.summary
