"""Pattern Promotion — promote reusable patterns from cases/rules/decisions.

Implements ECC-3 from NEXT_PHASE_MASTER_PLAN.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

PROMOTION_LOG_FILE = "pattern-promotions.jsonl"


class PatternPromotion:
    """Promote reusable patterns from experience."""

    def __init__(self, workspace_file: str | Path):
        self._store = WorkspaceStore(workspace_file)

    def propose(self, source_type: str, source_id: str, pattern_name: str, description: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
        """Propose a pattern for promotion."""
        proposal = {
            "promotion_id": f"promo-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "source_type": source_type,  # case | rule | decision
            "source_id": source_id,
            "pattern_name": pattern_name,
            "description": description,
            "evidence_count": len(evidence),
            "evidence_sample": evidence[:5],
            "status": "proposed",
            "proposed_at": datetime.now(timezone.utc).isoformat(),
        }
        self._store.append_jsonl(PROMOTION_LOG_FILE, proposal)
        return proposal

    def promote(self, promotion_id: str, scope: str = "workspace") -> dict[str, Any]:
        """Promote a proposed pattern to active status."""
        entry = {
            "promotion_id": promotion_id,
            "action": "promoted",
            "scope": scope,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        }
        self._store.append_jsonl(PROMOTION_LOG_FILE, entry)
        return entry

    def list_proposals(self, status: str = "proposed", limit: int = 50) -> list[dict[str, Any]]:
        """List pattern promotion proposals."""
        rows = self._store.read_jsonl_prefer_backend(PROMOTION_LOG_FILE, limit=200)
        return [r for r in rows if r.get("status") == status or r.get("action") == "promoted"][-limit:]
