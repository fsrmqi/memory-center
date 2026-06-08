"""Tests for D-03: Unified Explanation Schema -- multi-entry integration.

Verifies that impact, reasoning, domain, and onboarding all produce
explanation entries conforming to the standard schema.
Old fields are preserved for backward compatibility.
"""
from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from memory_center.core.explanation import (
    DISPLAY_RULES,
    Explanation,
    backward_compat_wrapper,
    display_rule_for_strength,
    explanation_entry,
    merge_explanations,
)

# ---------------------------------------------------------------------------
# Schema-level tests (new fields)
# ---------------------------------------------------------------------------

class TestExplanationSchemaEnhancements:
    """Test new D-03 fields: next_refs, display rules."""

    def test_explanation_entry_with_next_refs(self):
        refs = [{"id": "n1", "name": "ServiceA"}]
        e = explanation_entry(summary="test", next_refs=refs)
        assert e["next_refs"] == refs

    def test_explanation_entry_without_next_refs(self):
        e = explanation_entry(summary="test")
        assert e["next_refs"] == []

    def test_display_rules_all_strengths(self):
        for strength in ("fact", "inferred", "derived"):
            rule = display_rule_for_strength(strength)
            assert "label" in rule
            assert "prominence" in rule
            assert "require_evidence" in rule

    def test_display_rules_unknown_falls_back(self):
        rule = display_rule_for_strength("bogus")
        assert rule == DISPLAY_RULES["inferred"]

    def test_explanation_dataclass_next_refs(self):
        ex = Explanation(subject="t", summary="s", next_refs=[{"id": "x", "name": "y"}])
        assert ex.next_refs == [{"id": "x", "name": "y"}]
        full = ex.to_full()
        assert "next_refs" in full
        compact = ex.to_compact()
        assert "next_refs" in compact

    def test_explanation_dataclass_display_rule_in_full(self):
        ex = Explanation(subject="t", summary="s", semantic_strength="fact")
        full = ex.to_full()
        assert "display_rule" in full
        assert full["display_rule"]["label"] == "事实"

    def test_backward_compat_preserves_old_fields(self):
        old = {"confirmed": ">=0.80", "probable": ">=0.55"}
        result = backward_compat_wrapper(old)
        assert result["confirmed"] == ">=0.80"
        assert result["semantic_strength"] == "inferred"

    def test_backward_compat_new_format_passthrough(self):
        new = explanation_entry(summary="new", semantic_strength="fact")
        result = backward_compat_wrapper(new)
        assert result is new

    def test_merge_explanations_preserves_structure(self):
        e1 = explanation_entry(summary="a", next_refs=[{"id": "1", "name": "n1"}])
        e2 = explanation_entry(summary="b", next_refs=[{"id": "2", "name": "n2"}])
        merged = merge_explanations([e1, e2])
        assert "summary" in merged
        assert "evidence" in merged
        assert "semantic_strength" in merged
        assert "confidence" in merged
        assert merged["next_refs"] == [
            {"id": "1", "name": "n1"},
            {"id": "2", "name": "n2"},
        ]


# ---------------------------------------------------------------------------
# Impact integration
# ---------------------------------------------------------------------------

class TestImpactExplanationEntries:
    """Test _build_impact_explanation_entries helper."""

    def _make_impact(self, name: str = "Svc") -> dict[str, Any]:
        from memory_center.core.orchestrator.impact import _build_impact_explanation_entries
        confirmed = [
            {"type": "CALLS", "source": {"name": "a", "id": "a1"}, "target": {"name": "b", "id": "b1"}, "confidence": 0.95},
        ]
        probable = [
            {"type": "USES", "source": {"name": "c", "id": "c1"}, "target": {"name": "d", "id": "d1"}, "confidence": 0.65},
        ]
        possible = []
        node = {"type": "Service", "name": name}
        return _build_impact_explanation_entries(confirmed, probable, possible, node)

    def test_has_entries_and_merged(self):
        result = self._make_impact()
        assert "entries" in result
        assert "merged" in result

    def test_entries_count(self):
        result = self._make_impact()
        assert len(result["entries"]) == 2

    def test_entry_schema_fields(self):
        result = self._make_impact()
        entry = result["entries"][0]
        for key in ("subject", "summary", "evidence", "semantic_strength", "confidence"):
            assert key in entry, f"Missing {key}"

    def test_confirmed_strength_comes_from_edge_ontology(self):
        result = self._make_impact()
        confirmed_entry = result["entries"][0]
        assert confirmed_entry["semantic_strength"] == "inferred"

    def test_probable_is_inferred(self):
        result = self._make_impact()
        probable_entry = result["entries"][1]
        assert probable_entry["semantic_strength"] == "inferred"

    def test_merged_has_summary(self):
        result = self._make_impact()
        assert result["merged"]["summary"]

    def test_no_impacts_returns_explanation(self):
        from memory_center.core.orchestrator.impact import _build_impact_explanation_entries
        result = _build_impact_explanation_entries([], [], [], {"type": "Service", "name": "Empty"})
        assert result["merged"]["semantic_strength"] == "fact"

    def test_old_explanation_field_preserved(self):
        import inspect

        from memory_center.core.orchestrator.impact import memory_impact
        src = inspect.getsource(memory_impact)
        assert '"explanation":' in src


# ---------------------------------------------------------------------------
# Reasoning integration
# ---------------------------------------------------------------------------

class TestReasoningExplanationEntries:
    """Test that reasoning patterns carry _explanation field."""

    def test_pattern_entry_has_explanation(self):
        from memory_center.core.reasoning.integration import SEMANTIC_STRENGTH_INFERRED, _risk_level_to_confidence
        entry = {
            "pattern_name": "cycle",
            "description": "circular dependency",
            "evidence": {"nodes": ["a", "b"]},
            "risk_level": "high",
        }
        entry["_semantic_strength"] = SEMANTIC_STRENGTH_INFERRED
        entry["_confidence"] = _risk_level_to_confidence(entry.get("risk_level", "medium"))
        entry["_explanation"] = explanation_entry(
            subject=f"reasoning:graph_patterns:{entry.get('pattern_name', '')}",
            summary=entry.get("description", ""),
            evidence=[entry.get("evidence", {})],
            semantic_strength=SEMANTIC_STRENGTH_INFERRED,
            confidence=entry["_confidence"],
        )
        assert "_explanation" in entry
        assert entry["_explanation"]["semantic_strength"] == "inferred"
        assert entry["_explanation"]["confidence"] == 0.9

    def test_transitive_entry_has_explanation(self):
        from memory_center.core.reasoning.integration import SEMANTIC_STRENGTH_DERIVED
        entry = {
            "source_id": "s1",
            "target_id": "t1",
            "path": ["s1", "m1", "t1"],
            "edge_types": ["CALLS", "CALLS"],
            "confidence": 0.4,
        }
        entry["_semantic_strength"] = SEMANTIC_STRENGTH_DERIVED
        entry["_confidence"] = entry.get("confidence", 0.5)
        entry["_explanation"] = explanation_entry(
            subject=f"reasoning:transitive_inference:{entry.get('source_id', '')}",
            summary=f"传递链路 depth={len(entry.get('path', []))}",
            evidence=[{"path": entry.get("path", []), "edge_types": entry.get("edge_types", [])}],
            semantic_strength=SEMANTIC_STRENGTH_DERIVED,
            confidence=entry["_confidence"],
            next_refs=[{"id": entry.get("target_id", ""), "name": entry.get("target_id", "")}],
        )
        assert entry["_explanation"]["semantic_strength"] == "derived"
        assert len(entry["_explanation"]["next_refs"]) == 1

    def test_risk_entry_has_explanation(self):
        from memory_center.core.reasoning.integration import SEMANTIC_STRENGTH_INFERRED, _severity_to_confidence
        entry = {
            "pattern": "shared_dto",
            "severity": "high",
            "description": "shared DTO risk",
            "affected_nodes": [{"id": "n1"}],
            "evidence": {"file": "Dto.java"},
        }
        entry["_semantic_strength"] = SEMANTIC_STRENGTH_INFERRED
        entry["_confidence"] = _severity_to_confidence(entry.get("severity", "medium"))
        entry["_explanation"] = explanation_entry(
            subject=f"reasoning:risk_patterns:{entry.get('pattern', 'unknown')}",
            summary=entry.get("description", ""),
            evidence=[entry.get("evidence", {})],
            semantic_strength=SEMANTIC_STRENGTH_INFERRED,
            confidence=entry["_confidence"],
        )
        assert entry["_explanation"]["subject"].startswith("reasoning:risk_patterns:")

    def test_reasoning_integration_has_explanation_fields(self):
        """Verify the source code of run_reasoning_patterns includes _explanation."""
        import inspect

        from memory_center.core.reasoning.integration import run_reasoning_patterns
        src = inspect.getsource(run_reasoning_patterns)
        assert "_explanation" in src

    def test_real_reasoning_serializers_produce_traceable_refs(self):
        from memory_center.core.reasoning.integration import _node_refs, _non_empty_evidence
        from memory_center.core.reasoning.patterns import PatternMatch

        match = PatternMatch(
            pattern_name="cycle",
            matched_nodes=[{"id": "node:a", "name": "A"}],
            evidence={"edge": "CALLS"},
        )
        assert _node_refs(match.matched_nodes) == [{"id": "node:a", "name": "A"}]
        assert _non_empty_evidence(match.evidence) == [{"edge": "CALLS"}]
        assert _non_empty_evidence({}) == []

    def test_run_reasoning_patterns_produces_traceable_explanations(self, tmp_path, monkeypatch):
        from memory_center.core.reasoning.integration import run_reasoning_patterns
        from memory_center.core.reasoning.patterns import GraphPatternEngine, PatternMatch
        from memory_center.core.reasoning.risk import RiskFinding, RiskPatternEngine
        from memory_center.core.reasoning.transitive import TransitiveInferenceEngine, TransitiveRelation

        monkeypatch.setattr(
            GraphPatternEngine,
            "run_all_patterns",
            lambda _self: {
                "test": [
                    PatternMatch(
                        pattern_name="test",
                        matched_nodes=[{"id": "node:a", "name": "A"}],
                        evidence={"edge": "CALLS"},
                    )
                ]
            },
        )
        monkeypatch.setattr(
            TransitiveInferenceEngine,
            "find_transitive_calls",
            lambda _self, **_kwargs: [
                TransitiveRelation("node:a", "node:c", ["node:a", "node:b", "node:c"], ["CALLS", "CALLS"], 0.6)
            ],
        )
        monkeypatch.setattr(
            RiskPatternEngine,
            "analyze_change_risk",
            lambda _self, _target_id: [
                RiskFinding("test-risk", "high", "risk", affected_nodes=[{"id": "node:c", "name": "C"}])
            ],
        )

        workspace = tmp_path / ".memory-center" / "workspace.yaml"
        workspace.parent.mkdir(parents=True)
        result = run_reasoning_patterns(str(workspace), target_id="node:a")

        assert result["patterns"][0]["_explanation"]["next_refs"] == [{"id": "node:a", "name": "A"}]
        assert result["patterns"][0]["_explanation"]["evidence"] == [{"edge": "CALLS"}]
        assert result["transitive"][0]["_explanation"]["next_refs"][-1]["id"] == "node:c"
        assert result["risk"][0]["_explanation"]["next_refs"] == [{"id": "node:c", "name": "C"}]


# ---------------------------------------------------------------------------
# Domain / Flow integration
# ---------------------------------------------------------------------------

class TestDomainExplanationEntries:
    """Test BusinessDomain and BusinessFlow produce _explanation."""

    def test_domain_to_dict_has_explanation(self):
        from memory_center.core.domain.extractor import BusinessDomain
        d = BusinessDomain(domain_id="d:user", name="user", confidence=0.7, entities=["e1", "e2", "e3"])
        dd = d.to_dict()
        assert "_explanation" in dd
        exp = dd["_explanation"]
        assert exp["subject"] == "domain:user"
        assert exp["semantic_strength"] == "inferred"
        assert exp["confidence"] == 0.7
        assert len(exp["next_refs"]) == 3

    def test_domain_old_fields_preserved(self):
        from memory_center.core.domain.extractor import BusinessDomain
        d = BusinessDomain(domain_id="d:order", name="order", confidence=0.9)
        dd = d.to_dict()
        assert "domain_id" in dd
        assert "name" in dd
        assert "confidence" in dd
        assert "entities" in dd

    def test_flow_to_dict_has_explanation(self):
        from memory_center.core.domain.extractor import BusinessFlow
        steps = [
            {"node_id": "ep1", "name": "POST /api/orders", "type": "endpoint", "order": 0},
            {"node_id": "svc1", "name": "OrderService", "type": "Class", "order": 1},
        ]
        f = BusinessFlow(flow_id="f:order", name="order:create", domain="order", steps=steps, confidence=0.8)
        fd = f.to_dict()
        assert "_explanation" in fd
        exp = fd["_explanation"]
        assert "order:create" in exp["subject"]
        assert exp["semantic_strength"] == "inferred"
        assert len(exp["evidence"]) == 2
        assert len(exp["next_refs"]) == 2

    def test_flow_old_fields_preserved(self):
        from memory_center.core.domain.extractor import BusinessFlow
        f = BusinessFlow(flow_id="f:x", name="x", domain="d", steps=[], confidence=0.5)
        fd = f.to_dict()
        assert "flow_id" in fd
        assert "name" in fd
        assert "steps" in fd


# ---------------------------------------------------------------------------
# Onboarding / Tour integration
# ---------------------------------------------------------------------------

class TestTourExplanationEntries:
    """Test TourStep produces _explanation."""

    def test_tour_step_has_explanation(self):
        from memory_center.core.onboarding.tour import TourStep
        ts = TourStep(step_id=1, title="概览", description="项目概览", node_ids=["n1", "n2"])
        td = ts.to_dict()
        assert "_explanation" in td
        exp = td["_explanation"]
        assert exp["subject"] == "tour:step:1"
        assert exp["semantic_strength"] == "derived"
        assert exp["confidence"] == 0.8
        assert exp["evidence"]
        assert len(exp["next_refs"]) == 2

    def test_tour_step_old_fields_preserved(self):
        from memory_center.core.onboarding.tour import TourStep
        ts = TourStep(step_id=1, title="概览", description="项目概览")
        td = ts.to_dict()
        assert "step_id" in td
        assert "title" in td
        assert "description" in td
        assert "node_ids" in td
        assert "depth" in td


# ---------------------------------------------------------------------------
# Cross-entry consistency
# ---------------------------------------------------------------------------

class TestCrossEntryConsistency:
    """Verify all entries use the same explanation schema structure."""

    def test_all_entries_have_required_fields(self):
        from memory_center.core.domain.extractor import BusinessDomain, BusinessFlow
        from memory_center.core.onboarding.tour import TourStep
        from memory_center.core.orchestrator.impact import _build_impact_explanation_entries

        entries_to_check: list[dict[str, Any]] = []

        # Domain
        d = BusinessDomain(domain_id="d:x", name="x", confidence=0.7)
        entries_to_check.append(d.to_dict()["_explanation"])

        # Flow
        f = BusinessFlow(flow_id="f:x", name="x", domain="d", steps=[], confidence=0.5)
        entries_to_check.append(f.to_dict()["_explanation"])

        # Tour
        ts = TourStep(step_id=1, title="t", description="d")
        entries_to_check.append(ts.to_dict()["_explanation"])

        # Impact
        impact_result = _build_impact_explanation_entries(
            [{"type": "CALLS", "source": {"name": "a"}, "target": {"name": "b"}, "confidence": 0.9}],
            [], [],
            {"type": "Service", "name": "S"},
        )
        entries_to_check.extend(impact_result["entries"])
        entries_to_check.append(impact_result["merged"])

        # Standalone
        entries_to_check.append(explanation_entry(summary="standalone", semantic_strength="derived"))

        required = {"subject", "summary", "evidence", "semantic_strength", "confidence", "next_actions"}
        for entry in entries_to_check:
            for key in required:
                assert key in entry, f"Missing '{key}' in {entry.get('subject', '?')}"
            assert entry["semantic_strength"] in ("fact", "inferred", "derived"), \
                f"Invalid strength: {entry['semantic_strength']}"
            assert 0.0 <= entry["confidence"] <= 1.0, \
                f"Confidence out of range: {entry['confidence']}"


class TestExplanationPublicEntries:
    def test_http_explanation_entry(self):
        from memory_center.http.server import _route_request

        result = _route_request(
            "/workspace/explanation",
            {"text": ["impact summary"], "persona": ["architect"]},
            None,
        )
        assert result["subject"] == "explanation"
        assert result["persona"] == "architect"
        assert "架构视角" in result["summary"]

    def test_cli_explanation_entry(self):
        from memory_center.cli.main import app

        result = CliRunner().invoke(
            app,
            ["explanation", "--text", "impact summary", "--persona", "manager"],
        )
        assert result.exit_code == 0, result.output
        assert '"subject": "explanation"' in result.output
        assert "管理视角" in result.output
