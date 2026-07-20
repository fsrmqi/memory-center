"""Explicit, recoverable sidecar migration for ontology v2 fields."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

MIGRATION_FILE = "ontology-migration.json"


def migrate_ontology(store: WorkspaceStore, *, apply: bool = False) -> dict[str, Any]:
    """Inspect or backfill additive assertion fields without reindexing code."""
    backend = store.memory_backend()
    with backend.connect() as conn:
        pending = int(conn.execute("SELECT COUNT(*) FROM assertions WHERE event_at='' OR observed_at='' OR provenance_kind='' ").fetchone()[0])
        total = int(conn.execute("SELECT COUNT(*) FROM assertions").fetchone()[0])
        if apply and pending:
            conn.execute("UPDATE assertions SET event_at=CASE WHEN event_at='' THEN valid_from ELSE event_at END, observed_at=CASE WHEN observed_at='' THEN valid_from ELSE observed_at END, provenance_kind=CASE WHEN provenance_kind='' THEN 'STATIC' ELSE provenance_kind END, relation_mode=CASE WHEN relation_mode='' THEN 'STRUCTURAL' ELSE relation_mode END, evidence_refs_json=CASE WHEN evidence_refs_json='' THEN '[]' ELSE evidence_refs_json END")
    result = {"schema_version": 2, "apply": apply, "total_assertions": total, "pending_backfill": pending, "backfilled": pending if apply else 0, "read_model": "v2" if apply or pending == 0 else "v1_compatible"}
    if apply:
        result["migrated_at"] = datetime.now(timezone.utc).isoformat()
        store.write_json(MIGRATION_FILE, result)
    return result
