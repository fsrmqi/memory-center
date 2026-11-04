"""Evidence Index projection (progressive disclosure, P0 of MEMORY_ENRICHMENT_DESIGN.md).

`memory_query_hybrid` returns agent-oriented rich blocks (guidance, next steps,
chain analysis). Some consumers only need a compact ordered evidence index —
evaluations that render ``{{memories}}`` from a ``selected`` list, UI surfaces,
or agents that expand details lazily via ``mc_lookup(mode="ref")``.

The projection is read-only over an already-finalized lookup result. It never
mutates the source result, strips absolute private paths from text, caps list
lengths, and preserves the negative-claim gates in scalar form so an empty
index can still be distinguished from a verified absence.
"""
from __future__ import annotations

import re
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

EVIDENCE_INDEX_SCHEMA_VERSION = 1
EVIDENCE_INDEX_DEFAULT_LIMIT = 20
EVIDENCE_INDEX_MAX_LIMIT = 50
EVIDENCE_ITEM_MAX_CHARS = 240
# Same fail-closed polarity as the Observation Inbox: evidence text must not
# carry absolute private paths (Unix root, Windows drive, or home expansion).
_ABSOLUTE_PATH_RE = re.compile(r"(^|[\s\"'`(])((?:/[A-Za-z0-9._-])|(?:[A-Za-z]:\\)|(?:~/?[A-Za-z0-9_.]))")


def _redact_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _has_absolute_path(text: str) -> bool:
    return bool(_ABSOLUTE_PATH_RE.search(text))


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _node_evidence_text(item: dict[str, Any]) -> str:
    """Project one hybrid result into a single-line natural-language fact."""
    node = item.get("node") if isinstance(item.get("node"), dict) else {}
    name = str(node.get("name", "") or item.get("name", "") or "").strip()
    node_type = str(node.get("type", "") or "").strip()
    project = str(node.get("project", "") or "").strip()
    file_path = str(node.get("file_path", "") or "").strip()
    parts: list[str] = []
    if name:
        parts.append(f"{node_type} {name}".strip() if node_type else name)
    if project:
        parts.append(f"service {project}")
    # Relative-looking paths only; absolute paths are dropped by the guard below.
    if file_path and not _has_absolute_path(file_path):
        parts.append(file_path)
    text = _redact_text(" · ".join(parts)) or _redact_text(str(item.get("summary", "") or ""))
    return text[:EVIDENCE_ITEM_MAX_CHARS]


def _item_ref_id(item: dict[str, Any], index: int) -> str:
    """Best-effort stable ref for the second-hop expansion via mc_lookup(mode="ref")."""
    node_id = str(item.get("node_id", "") or "").strip()
    if node_id:
        return f"node:{node_id}"
    payload_ref = str(item.get("payload_ref", "") or "").strip()
    if payload_ref:
        return payload_ref
    return f"hit:{index}"


def _note_evidence_entry(item: dict[str, Any], index: int) -> dict[str, Any] | None:
    """Project one merged Session Note hit into an evidence index entry."""
    node = item.get("node") if isinstance(item.get("node"), dict) else {}
    text = _redact_text(str(node.get("name", "") or ""))
    if not text or _has_absolute_path(text):
        return None
    return {
        "ref_id": f"note:{item.get('node_id', '')}",
        "created_at": _item_created_at(item),
        "text": text[:EVIDENCE_ITEM_MAX_CHARS],
        "source_layer": "L0.5_session_notes",
        "source_kind": "note",
        "score": item.get("score", 0.0),
        "approx_tokens": _approx_tokens(text),
        "estimated_tokens": True,
    }


def _item_created_at(item: dict[str, Any]) -> str:
    for key in ("created_at", "updated_at", "event_time", "time"):
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    node = item.get("node") if isinstance(item.get("node"), dict) else {}
    return str(node.get("created_at", "") or "")


def build_evidence_index(
    result: dict[str, Any],
    *,
    store: WorkspaceStore,
    query: str,
    limit: int = EVIDENCE_INDEX_DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Project a finalized hybrid lookup result into a compact evidence index.

    The source result is not mutated. ``selected`` carries at most ``limit``
    items (bounded by EVIDENCE_INDEX_MAX_LIMIT), each with a single-line text,
    a ref for lazy expansion, an optional timestamp, and an estimated token
    cost. ``claim_boundary``/``knowledge_state`` are preserved as scalars so
    the negative-claim gates survive the projection.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = EVIDENCE_INDEX_DEFAULT_LIMIT
    limit = max(1, min(limit, EVIDENCE_INDEX_MAX_LIMIT))

    raw_results = list(result.get("results", []) or [])
    selected: list[dict[str, Any]] = []
    for index, item in enumerate(raw_results):
        if not isinstance(item, dict):
            continue
        if item.get("source_kind") == "note" or item.get("sources") == ["note"]:
            entry = _note_evidence_entry(item, index)
        else:
            text = _node_evidence_text(item)
            entry = None
            if text and not _has_absolute_path(text):
                entry = {
                    "ref_id": _item_ref_id(item, index),
                    "created_at": _item_created_at(item),
                    "text": text,
                    "source_layer": "graph_index",
                    "source_kind": str(item.get("semantic_strength", "") or "inferred"),
                    "score": item.get("score", 0.0),
                    "approx_tokens": _approx_tokens(text),
                    "estimated_tokens": True,
                }
        if entry:
            selected.append(entry)
        if len(selected) >= limit:
            break

    selected.sort(key=lambda entry: (-float(entry.get("score", 0.0) or 0.0), str(entry.get("ref_id", ""))))

    claim_boundary = result.get("claim_boundary") if isinstance(result.get("claim_boundary"), dict) else {}
    knowledge_state = result.get("knowledge_state") if isinstance(result.get("knowledge_state"), dict) else {}
    freshness = result.get("freshness") if isinstance(result.get("freshness"), dict) else {}
    freshness_status = str((freshness.get("freshness", {}) or {}).get("status", "") or "")

    return {
        "schema_version": EVIDENCE_INDEX_SCHEMA_VERSION,
        "kind": "evidence_index",
        "workspace": result.get("workspace", ""),
        "query": query,
        "selected": selected,
        "total_candidates": int(result.get("total_found", len(raw_results)) or len(raw_results)),
        "returned": len(selected),
        "truncated": len(raw_results) > len(selected),
        "approx_total_tokens": sum(entry["approx_tokens"] for entry in selected),
        "claim_boundary": {
            "negative_claim_allowed": bool(claim_boundary.get("negative_claim_allowed", False)),
            "evidence_level": str(claim_boundary.get("evidence_level", "") or ""),
        },
        "knowledge_state": str(knowledge_state.get("state", "") or knowledge_state.get("knowledge_state", "") or ""),
        "freshness_status": freshness_status,
        "expand_hint": 'Use mc_lookup(mode="ref", ref_ids=[...]) to expand selected items.',
    }


__all__ = [
    "EVIDENCE_INDEX_DEFAULT_LIMIT",
    "EVIDENCE_INDEX_MAX_LIMIT",
    "EVIDENCE_INDEX_SCHEMA_VERSION",
    "build_evidence_index",
]
