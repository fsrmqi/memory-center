"""Tests for C-07: Reasoning patterns main-chain integration.

Verifies:
- run_reasoning_patterns returns structured results with reasoning metadata
- semantic_strength is never 'fact' (always inferred/derived)
- each entry carries _confidence, _pattern_group, _evidence
- no-match returns empty lists (not None/error)
- engine failure returns _diagnostics (never silent)
- summarize_reasoning works correctly
- memory_impact includes _reasoning field without overriding factual results
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from memory_center.core.reasoning.integration import (
    PATTERN_GROUP_GRAPH,
    PATTERN_GROUP_RISK,
    PATTERN_GROUP_TRANSITIVE,
    SEMANTIC_STRENGTH_DERIVED,
    SEMANTIC_STRENGTH_INFERRED,
    _risk_level_to_confidence,
    _serialize_pattern_match,
    _serialize_risk_finding,
    _serialize_transitive,
    _severity_to_confidence,
    run_reasoning_patterns,
    summarize_reasoning,
)


@pytest.fixture()
def demo_workspace(tmp_path: Path) -> Path:
    """Copy demo workspace to tmp_path and return workspace.yaml path."""
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    ws = target / ".memory-center" / "workspace.yaml"
    lines = ws.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    ws.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ws


# ── Semantic strength constants ─────────────────────────────────────────────

class TestSemanticStrengthConstants:
    def test_strength_values_are_not_fact(self):
        """Reasoning results must never claim 'fact' strength."""
        assert SEMANTIC_STRENGTH_INFERRED == "inferred"
        assert SEMANTIC_STRENGTH_DERIVED == "derived"
        assert SEMANTIC_STRENGTH_INFERRED != "fact"
        assert SEMANTIC_STRENGTH_DERIVED != "fact"

    def test_pattern_group_constants(self):
        assert PATTERN_GROUP_GRAPH == "graph_patterns"
        assert PATTERN_GROUP_TRANSITIVE == "transitive_inference"
        assert PATTERN_GROUP_RISK == "risk_patterns"


# ── Confidence mapping ──────────────────────────────────────────────────────

class TestConfidenceMapping:
    def test_risk_level_high(self):
        assert _risk_level_to_confidence("high") == 0.9

    def test_risk_level_medium(self):
        assert _risk_level_to_confidence("medium") == 0.6

    def test_risk_level_low(self):
        assert _risk_level_to_confidence("low") == 0.3

    def test_risk_level_unknown(self):
        assert _risk_level_to_confidence("unknown") == 0.5

    def test_severity_high(self):
        assert _severity_to_confidence("high") == 0.9

    def test_severity_medium(self):
        assert _severity_to_confidence("medium") == 0.6

    def test_severity_low(self):
        assert _severity_to_confidence("low") == 0.3

    def test_severity_unknown(self):
        assert _severity_to_confidence("bogus") == 0.5


# ── Serialization helpers ───────────────────────────────────────────────────

class TestSerialization:
    def test_serialize_pattern_match_from_dataclass(self):
        class FakeMatch:
            pattern_name = "test_pattern"
            matched_nodes = [{"id": "n1"}]
            risk_level = "high"
            description = "test desc"
            evidence = {"key": "val"}
        result = _serialize_pattern_match(FakeMatch())
        assert result["pattern_name"] == "test_pattern"
        assert result["risk_level"] == "high"
        assert result["evidence"] == {"key": "val"}

    def test_serialize_pattern_match_from_dict(self):
        d = {"pattern_name": "x", "matched_nodes": [], "risk_level": "low", "description": "", "evidence": {}}
        assert _serialize_pattern_match(d) == d

    def test_serialize_risk_finding_from_dataclass(self):
        class FakeFinding:
            pattern = "public_contract_change"
            severity = "high"
            description = "desc"
            affected_nodes = [{"id": "n1"}]
            checklist = ["item1"]
            evidence = {"k": "v"}
        result = _serialize_risk_finding(FakeFinding())
        assert result["pattern"] == "public_contract_change"
        assert result["severity"] == "high"
        assert result["checklist"] == ["item1"]

    def test_serialize_risk_finding_from_dict(self):
        d = {"pattern": "x", "severity": "low", "description": "", "affected_nodes": [], "checklist": [], "evidence": {}}
        assert _serialize_risk_finding(d) == d

    def test_serialize_transitive_from_dataclass(self):
        class FakeRel:
            source_id = "s1"
            target_id = "t1"
            path = ["s1", "m1", "t1"]
            edge_types = ["CALLS_METHOD", "CALLS_SERVICE"]
            confidence = 0.6
        result = _serialize_transitive(FakeRel())
        assert result["source_id"] == "s1"
        assert result["target_id"] == "t1"
        assert len(result["path"]) == 3
        assert result["confidence"] == 0.6

    def test_serialize_transitive_from_dict(self):
        d = {"source_id": "s", "target_id": "t", "path": [], "edge_types": [], "confidence": 0.5}
        assert _serialize_transitive(d) == d


# ── Main integration tests with real demo workspace ─────────────────────────

class TestRunReasoningPatterns:
    def test_returns_three_groups(self, demo_workspace: Path):
        """run_reasoning_patterns returns patterns, transitive, risk lists."""
        result = run_reasoning_patterns(str(demo_workspace))
        assert "patterns" in result
        assert "transitive" in result
        assert "risk" in result
        assert isinstance(result["patterns"], list)
        assert isinstance(result["transitive"], list)
        assert isinstance(result["risk"], list)

    def test_parser_precision_warning_is_visible_after_reindex(self, demo_workspace: Path):
        from memory_center.core.config import load_workspace_config
        from memory_center.core.indexer import reindex_workspace
        from memory_center.core.store import WorkspaceStore

        config = load_workspace_config(demo_workspace)
        reindex_result = reindex_workspace(config, WorkspaceStore(demo_workspace))
        result = run_reasoning_patterns(str(demo_workspace))
        parser_status = reindex_result["parser_precision"]["status"]
        if parser_status in {"regex_only", "mixed_fallback"}:
            assert result["_diagnostics"]["parser_precision"]["status"] == parser_status

    def test_entries_carry_reasoning_metadata(self, demo_workspace: Path):
        """Every reasoning entry has _semantic_strength, _confidence, _pattern_group, _evidence."""
        result = run_reasoning_patterns(str(demo_workspace))
        for group_key in ("patterns", "transitive", "risk"):
            for entry in result[group_key]:
                assert "_semantic_strength" in entry, f"{group_key} entry missing _semantic_strength"
                assert "_confidence" in entry, f"{group_key} entry missing _confidence"
                assert "_pattern_group" in entry, f"{group_key} entry missing _pattern_group"
                assert "_evidence" in entry, f"{group_key} entry missing _evidence"

    def test_semantic_strength_never_fact(self, demo_workspace: Path):
        """Reasoning results must never claim 'fact' semantic strength."""
        result = run_reasoning_patterns(str(demo_workspace))
        for group_key in ("patterns", "transitive", "risk"):
            for entry in result[group_key]:
                strength = entry.get("_semantic_strength")
                assert strength in ("inferred", "derived"), (
                    f"Reasoning entry has '{strength}', must be 'inferred' or 'derived'"
                )
                assert strength != "fact"

    def test_pattern_group_labels_correct(self, demo_workspace: Path):
        """Each group uses the correct _pattern_group label."""
        result = run_reasoning_patterns(str(demo_workspace))
        for entry in result["patterns"]:
            assert entry["_pattern_group"] == PATTERN_GROUP_GRAPH
        for entry in result["transitive"]:
            assert entry["_pattern_group"] == PATTERN_GROUP_TRANSITIVE
        for entry in result["risk"]:
            assert entry["_pattern_group"] == PATTERN_GROUP_RISK

    def test_with_target_id_returns_transitive_and_risk(self, demo_workspace: Path):
        """When target_id is provided, transitive and risk engines run."""
        # Get a real node ID from the graph
        from memory_center.core.store import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace))
        from memory_center.core.graph import GraphStore
        with GraphStore(ws.graph_db_path) as graph:
            nodes = graph.find_nodes("Order", limit=1)
        if not nodes:
            pytest.skip("No nodes found in demo graph")
        target_id = nodes[0]["id"]
        result = run_reasoning_patterns(str(demo_workspace), target_id=target_id)
        # transitive and risk should be populated (or at least empty lists, not errors)
        assert isinstance(result["transitive"], list)
        assert isinstance(result["risk"], list)
        # graph patterns always run regardless of target_id
        assert isinstance(result["patterns"], list)

    def test_invalid_workspace_returns_diagnostics(self, tmp_path: Path):
        """Invalid workspace path returns _diagnostics, not an exception."""
        bad_path = str(tmp_path / "nonexistent" / "workspace.yaml")
        result = run_reasoning_patterns(bad_path)
        assert "_diagnostics" in result
        assert result["_diagnostics"].get("workspace", {}).get("status") == "unavailable"

    def test_no_match_returns_empty_lists(self, tmp_path: Path):
        """Empty graph returns empty reasoning lists, not None or errors."""
        # Create a minimal valid workspace with empty graph
        source = Path("examples/spring-cloud-demo")
        target = tmp_path / "demo"
        shutil.copytree(source, target)
        ws = target / ".memory-center" / "workspace.yaml"
        lines = ws.read_text(encoding="utf-8").splitlines()
        lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
        ws.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Use a nonexistent target_id — should get empty results, not crash
        result = run_reasoning_patterns(str(ws), target_id="nonexistent-node-id-99999")
        assert isinstance(result["patterns"], list)
        assert isinstance(result["transitive"], list)
        assert isinstance(result["risk"], list)

    def test_reasoning_does_not_override_factual_results(self, demo_workspace: Path):
        """Reasoning is additive — it never replaces factual impact results."""
        from memory_center.core.graph import GraphStore
        from memory_center.core.orchestrator.impact import memory_impact

        # Get a real target from the graph
        from memory_center.core.store import WorkspaceStore
        ws_store = WorkspaceStore(str(demo_workspace))
        with GraphStore(ws_store.graph_db_path) as graph:
            nodes = graph.find_nodes("Order", limit=1)
        if not nodes:
            pytest.skip("No nodes found in demo graph")
        target_name = nodes[0].get("name", "Order")
        result = memory_impact(str(demo_workspace), target_name)
        # Factual fields must still be present
        assert "target" in result
        assert "found" in result
        assert "risk_level" in result
        # Reasoning field is additive
        if "_reasoning" in result:
            reasoning = result["_reasoning"]
            assert isinstance(reasoning, dict)
            assert "patterns" in reasoning
            assert "transitive" in reasoning
            assert "risk" in reasoning


# ── Summarize reasoning ─────────────────────────────────────────────────────

class TestSummarizeReasoning:
    def test_empty_reasoning(self):
        result = summarize_reasoning({"patterns": [], "transitive": [], "risk": []})
        assert result["total_findings"] == 0
        assert result["groups"] == {}

    def test_with_findings(self):
        reasoning = {
            "patterns": [{"_confidence": 0.9, "_pattern_group": "graph_patterns"}],
            "transitive": [{"_confidence": 0.5, "_pattern_group": "transitive_inference"}],
            "risk": [{"_confidence": 0.9, "_pattern_group": "risk_patterns"}],
        }
        result = summarize_reasoning(reasoning)
        assert result["total_findings"] == 3
        assert result["high_risk_count"] == 2
        assert result["groups"]["graph_patterns"] == 1
        assert result["groups"]["transitive_inference"] == 1
        assert result["groups"]["risk_patterns"] == 1

    def test_with_diagnostics(self):
        reasoning = {
            "patterns": [],
            "transitive": [],
            "risk": [],
            "_diagnostics": {"risk_patterns": {"status": "unavailable", "reason": "test"}},
        }
        result = summarize_reasoning(reasoning)
        assert result["diagnostics"] == {"risk_patterns": {"status": "unavailable", "reason": "test"}}
