"""Canonical identity aliases kept separately from immutable graph IDs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

ALIASES_FILE = "identity-aliases.jsonl"
ALIAS_INDEX_FILE = "identity-alias-index.json"
_MAX_ALIASES = 100_000
_MERGE_RELATIONS = {"ALIAS_OF", "SAME_AS", "RENAMED_FROM"}
_VALID_RELATIONS = _MERGE_RELATIONS | {"REPLACES"}


def record_identity_alias(
    store: WorkspaceStore,
    *,
    alias_id: str,
    canonical_id: str,
    relation: str = "RENAMED_FROM",
    evidence_ref: str = "",
    identity_confidence: float = 1.0,
    valid_to: str = "",
    verification_status: str = "VERIFIED",
) -> dict[str, Any]:
    """Record a verified identity transition without rewriting prior facts."""
    alias_id, canonical_id = alias_id.strip(), canonical_id.strip()
    if not alias_id or not canonical_id:
        raise ValueError("alias_id and canonical_id are required")
    if alias_id == canonical_id:
        raise ValueError("alias_id and canonical_id must differ")
    now = datetime.now(timezone.utc).isoformat()
    normalized_relation = relation.strip().upper() or "RENAMED_FROM"
    if normalized_relation == "RENAMED_TO":
        normalized_relation = "RENAMED_FROM"
    if normalized_relation not in _VALID_RELATIONS:
        raise ValueError(f"unsupported identity relation: {normalized_relation}")
    confidence = min(1.0, max(0.0, float(identity_confidence)))
    verified = verification_status.strip().upper() == "VERIFIED" and bool(evidence_ref.strip())
    event = {
        "type": "identity_alias",
        "alias_id": alias_id,
        "canonical_id": canonical_id,
        "relation": normalized_relation,
        "evidence_ref": evidence_ref[:240],
        "identity_confidence": confidence,
        "valid_to": valid_to[:64],
        "verification_status": "VERIFIED" if verified else "UNVERIFIED",
        "created_at": now,
    }
    current = store.read_json_prefer_backend(ALIAS_INDEX_FILE, {"aliases": {}})
    aliases = dict(current.get("aliases", {}) if isinstance(current, dict) else {})
    aliases[alias_id] = {key: event[key] for key in ("canonical_id", "relation", "evidence_ref", "identity_confidence", "valid_to", "verification_status", "created_at")}
    if len(aliases) > _MAX_ALIASES:
        ordered = sorted(aliases.items(), key=lambda item: str(item[1].get("created_at", "")), reverse=True)[:_MAX_ALIASES]
        aliases = dict(ordered)
    store.append_jsonl(ALIASES_FILE, event)
    store.write_json(ALIAS_INDEX_FILE, {"schema_version": 1, "updated_at": now, "aliases": aliases})
    return event


def resolve_canonical_identity(store: WorkspaceStore, entity_id: str, *, max_hops: int = 8) -> dict[str, Any]:
    """Resolve an alias chain defensively and expose loops as ambiguity."""
    index = store.read_json_prefer_backend(ALIAS_INDEX_FILE, {"aliases": {}})
    aliases: dict[str, Any] = index.get("aliases", {}) if isinstance(index, dict) else {}
    current = entity_id.strip()
    chain = [current] if current else []
    for _ in range(min(max(1, max_hops), 16)):
        item = aliases.get(current)
        target = str(item.get("canonical_id", "") or "") if isinstance(item, dict) else ""
        relation = str(item.get("relation", "") or "") if isinstance(item, dict) else ""
        verified = bool(isinstance(item, dict) and item.get("verification_status") == "VERIFIED" and item.get("evidence_ref"))
        if not target:
            return {"entity_id": entity_id, "canonical_id": current, "chain": chain, "ambiguous": False, "auto_merged": len(chain) > 1}
        if target in chain:
            return {"entity_id": entity_id, "canonical_id": current, "chain": chain + [target], "ambiguous": True, "reason": "alias_cycle"}
        if relation == "REPLACES" or relation not in _MERGE_RELATIONS or not verified:
            return {"entity_id": entity_id, "canonical_id": current, "chain": chain, "ambiguous": False, "auto_merged": False, "reason": "unverified_or_non_equivalent_alias"}
        current = target
        chain.append(current)
    return {"entity_id": entity_id, "canonical_id": current, "chain": chain, "ambiguous": True, "reason": "max_hops"}
