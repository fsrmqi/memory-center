"""Learned Heuristics Register — store and recall agent-learned patterns.

Implements ECC-4 from NEXT_PHASE_MASTER_PLAN.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..store import WorkspaceStore

HEURISTICS_FILE = "learned-heuristics.jsonl"


class HeuristicsRegister:
    """Store and query learned heuristics from agent experience."""

    def __init__(self, workspace_file: str | Path):
        self._store = WorkspaceStore(workspace_file)

    def record(self, category: str, pattern: str, trigger: str, outcome: str, confidence: float = 0.5) -> Dict[str, Any]:
        """Record a learned heuristic."""
        entry = {
            "heuristic_id": f"heur-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "category": category,
            "pattern": pattern,
            "trigger": trigger,
            "outcome": outcome,
            "confidence": confidence,
            "usage_count": 0,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self._store.append_jsonl(HEURISTICS_FILE, entry)
        return entry

    def query(self, category: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        """Query learned heuristics by category."""
        rows = self._store.read_jsonl_prefer_backend(HEURISTICS_FILE, limit=200)
        if category:
            rows = [r for r in rows if r.get("category") == category]
        rows.sort(key=lambda r: r.get("confidence", 0), reverse=True)
        return rows[:limit]

    def update_confidence(self, heuristic_id: str, delta: float) -> Dict[str, Any]:
        """Update confidence based on observed outcomes."""
        entry = {
            "heuristic_id": heuristic_id,
            "confidence_delta": delta,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._store.append_jsonl(HEURISTICS_FILE, entry)
        return entry
