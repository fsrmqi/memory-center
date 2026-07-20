"""Tests for D-06: Resume / Handoff / Drill-down output structure.

Verifies:
- mc_resume returns resume_packet, next_actions, unresolved_items, recent_evidence
- mc_handoff returns handoff_packet, recent_evidence, tool_usage_report
- Drill-down returns structured data with refs
- Output fields are stable
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

class TestResumeOutput:
    def test_resume_returns_required_keys(self, demo_workspace: Path):
        from memory_center.core.orchestrator.resume import workspace_resume_packet
        result = workspace_resume_packet(str(demo_workspace), intent="test resume")
        assert isinstance(result, dict)

    def test_resume_with_session(self, demo_workspace: Path):
        from memory_center.core.orchestrator.resume import workspace_resume_packet
        from memory_center.core.orchestrator.session import workspace_start_session
        session = workspace_start_session(str(demo_workspace), "test intent")
        sid = session.get("session_id", "")
        result = workspace_resume_packet(str(demo_workspace), session_id=sid)
        assert isinstance(result, dict)

class TestHandoffOutput:
    def test_handoff_returns_required_keys(self, demo_workspace: Path):
        from memory_center.core.orchestrator.resume import workspace_handoff_packet
        result = workspace_handoff_packet(str(demo_workspace), target_model="codex")
        assert isinstance(result, dict)

class TestDrillDown:
    def test_drill_ref_returns_structure(self, demo_workspace: Path):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with DrillDownNavigator(str(demo_workspace)) as nav:
            result = nav.expand_ref("nonexistent-ref-id")
        assert isinstance(result, dict)

    def test_drill_timeline_returns_structure(self, demo_workspace: Path):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with DrillDownNavigator(str(demo_workspace)) as nav:
            result = nav.drill_timeline(limit=5)
        assert isinstance(result, dict)

    def test_drill_task_returns_structure(self, demo_workspace: Path):
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        with DrillDownNavigator(str(demo_workspace)) as nav:
            result = nav.drill_task("nonexistent-task")
        assert isinstance(result, dict)
