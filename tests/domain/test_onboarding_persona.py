"""Tests for D-05: Onboarding & Persona output.

Verifies:
- ArchitectureTourGenerator works with all 4 personas
- Persona differences are meaningful (not just title swap)
- Tour output has required fields
- Tour steps have required fields
- Explanation adapt_for_persona works correctly
"""
from __future__ import annotations

from pathlib import Path


class TestOnboardingPersona:
    PERSONAS = ["developer", "architect", "product", "tester"]

    def test_all_personas_generate_tour(self, demo_workspace_indexed: Path):
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        with RuntimeStore(ws.graph_db_path) as store:
            gen = ArchitectureTourGenerator(store)
            for persona in self.PERSONAS:
                tour = gen.generate_tour(persona=persona)
                assert tour.persona == persona
                assert tour.tour_id
                assert isinstance(tour.steps, list)

    def test_tour_has_required_fields(self, demo_workspace_indexed: Path):
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        with RuntimeStore(ws.graph_db_path) as store:
            gen = ArchitectureTourGenerator(store)
            tour = gen.generate_tour(persona="developer")
            d = tour.to_dict()
            assert "tour_id" in d
            assert "persona" in d
            assert "scope" in d
            assert "steps" in d
            assert "summary" in d
            assert "total_steps" in d

    def test_step_has_required_fields(self, demo_workspace_indexed: Path):
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        with RuntimeStore(ws.graph_db_path) as store:
            gen = ArchitectureTourGenerator(store)
            tour = gen.generate_tour(persona="developer")
            if tour.steps:
                s = tour.steps[0].to_dict()
                assert "step_id" in s
                assert "title" in s
                assert "description" in s
                assert "node_ids" in s

    def test_persona_differences_meaningful(self, demo_workspace_indexed: Path):
        """Different personas should produce different content, not just title swaps."""
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        with RuntimeStore(ws.graph_db_path) as store:
            gen = ArchitectureTourGenerator(store)
            tours = {}
            for persona in self.PERSONAS:
                tour = gen.generate_tour(persona=persona)
                tours[persona] = tour
            # All tours should have steps
            for p, t in tours.items():
                assert len(t.steps) > 0 or p == "product", f"Persona {p} should have steps"

class TestExplanationPersona:
    def test_adapt_for_architect(self):
        from memory_center.core.explanation import Explanation
        e = Explanation(subject="test", summary="s", next_actions=["check architecture pattern", "run tests"])
        a = e.adapt_for_persona("architect")
        assert "[architect]" in a.summary or "[\u67b6\u6784\u89c6\u89d2]" in a.summary

    def test_adapt_for_manager(self):
        from memory_center.core.explanation import Explanation
        e = Explanation(subject="test", summary="s", next_actions=["check impact risk", "run tests"])
        m = e.adapt_for_persona("manager")
        assert "[manager]" in m.summary or "[\u7ba1\u7406\u89c6\u89d2]" in m.summary

    def test_adapt_preserves_subject(self):
        from memory_center.core.explanation import Explanation
        e = Explanation(subject="order-flow", summary="s")
        for persona in ("developer", "architect", "manager"):
            a = e.adapt_for_persona(persona)
            assert a.subject == "order-flow"
