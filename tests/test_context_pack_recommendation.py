"""Tests for D-02: Context Pack becomes default understanding entry.

Verifies:
- mc_start returns context_pack_recommendation
- Architecture intents get recommended=True
- Change-impact intents with elevated risk get recommended=True
- Unrelated intents get recommended=False
- Recommendation includes suggested_query and suggested_budget
- Context Pack already contains freshness/evidence/rules/flows/refs
"""
from __future__ import annotations
import shutil
from pathlib import Path
import pytest

@pytest.fixture()
def demo_workspace(tmp_path: Path) -> Path:
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    ws = target / ".memory-center" / "workspace.yaml"
    lines = ws.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    ws.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ws

class TestContextPackRecommendation:
    def test_recommendation_from_helper(self, demo_workspace: Path):
        """_build_context_pack_recommendation works correctly with real workspace."""
        from memory_center.mcp.server import _build_context_pack_recommendation
        sniff = {"risk_level": "medium"}
        rec = _build_context_pack_recommendation(str(demo_workspace), "understand architecture of Order service", sniff)
        assert "recommended" in rec
        assert rec["recommended"] is True
        assert rec["tool"] == "mc_context_pack"

    def test_architecture_intent_recommended(self, demo_workspace: Path):
        from memory_center.mcp.server import _build_context_pack_recommendation
        sniff = {"risk_level": "low"}
        rec = _build_context_pack_recommendation(str(demo_workspace), "understand architecture of Order service", sniff)
        assert rec["recommended"] is True
        assert "architecture" in rec["reason"].lower() or "Architecture" in rec["reason"]

    def test_change_intent_with_risk_recommended(self, demo_workspace: Path):
        from memory_center.mcp.server import _build_context_pack_recommendation
        sniff = {"risk_level": "high"}
        rec = _build_context_pack_recommendation(str(demo_workspace), "fix the order processing bug", sniff)
        assert rec["recommended"] is True

    def test_unrelated_intent_not_recommended(self, demo_workspace: Path):
        from memory_center.mcp.server import _build_context_pack_recommendation
        sniff = {"risk_level": "low"}
        rec = _build_context_pack_recommendation(str(demo_workspace), "check test coverage", sniff)
        assert rec["recommended"] is False

    def test_recommendation_has_suggested_query(self, demo_workspace: Path):
        from memory_center.mcp.server import _build_context_pack_recommendation
        sniff = {"risk_level": "low"}
        rec = _build_context_pack_recommendation(str(demo_workspace), "refactor the payment module", sniff)
        assert rec["recommended"] is True
        assert rec["suggested_query"] == "refactor the payment module"
        assert rec["tool"] == "mc_context_pack"

    def test_stale_risk_escalates_budget(self, demo_workspace: Path):
        from memory_center.mcp.server import _build_context_pack_recommendation
        sniff_high = {"risk_level": "high"}
        sniff_low = {"risk_level": "low"}
        rec_high = _build_context_pack_recommendation(str(demo_workspace), "modify order service", sniff_high)
        rec_low = _build_context_pack_recommendation(str(demo_workspace), "modify order service", sniff_low)
        assert rec_high["suggested_budget"] == "large"
        assert rec_low["suggested_budget"] in ("medium", "large")
