"""Stable internal IR boundary (Phase D).

Defines the serializable intermediate records every parser adapter must
produce between parsing and graph projection
(docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md §5.1):

- ``FileRecord`` / ``SymbolRecord`` / ``RelationCandidate`` are the only
  contract between parsers and projection; they are *not* the MCP schema.
- ``stable_id`` is derived purely from workspace facts (project + path +
  kind + qualified name + signature) — never a SQLite rowid.
- Candidates whose target cannot be proven are never dropped: they keep
  ``target_ref=None`` and surface as aggregated unresolved diagnostics so
  the pipeline can improve specific failure categories without fabricating
  edges.
- Evidence levels at the IR boundary are EXTRACTED, INFERRED, or AMBIGUOUS;
  UNRESOLVED targets always stay AMBIGUOUS (never a confirmed call).
"""
from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

EVIDENCE_EXTRACTED = "EXTRACTED"
EVIDENCE_INFERRED = "INFERRED"
EVIDENCE_AMBIGUOUS = "AMBIGUOUS"

PARSED = "parsed"
PARTIAL = "partial"
SKIPPED = "skipped"
FAILED = "failed"


def stable_id(*parts: Any) -> str:
    """Deterministic identity over normalized string parts."""
    canonical = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class FileRecord:
    path: str                      # workspace-relative logical path
    content_hash: str
    language: str
    parse_status: str              # parsed | partial | skipped | failed
    skip_reason: str | None = None


@dataclass(frozen=True)
class SymbolRecord:
    stable_key: str                # deterministic; see stable_id()
    kind: str                      # Class, Interface, Method, Function, Endpoint...
    qualified_name: str
    range_start_line: int = 0
    evidence_level: str = EVIDENCE_EXTRACTED


@dataclass(frozen=True)
class RelationCandidate:
    source_key: str
    relation: str                  # CALLS_METHOD, IMPORTS, EXPOSES_ENDPOINT...
    target_ref: str | None         # None => unproven target, kept as diagnostic
    confidence: float
    resolution_reason: str         # e.g. same_class, explicit_import, receiver_type_missing
    evidence_level: str            # EXTRACTED | INFERRED | AMBIGUOUS
    source_file: str = ""


def _evidence_for_resolution(resolution_level: str, inferred_target: bool) -> str:
    if resolution_level == "unresolved":
        return EVIDENCE_AMBIGUOUS
    if inferred_target:
        return EVIDENCE_INFERRED
    return EVIDENCE_EXTRACTED


def call_edges_to_relation_candidates(
    edges: list[dict[str, Any]],
    *,
    source_file_by_id: dict[str, str] | None = None,
) -> list[RelationCandidate]:
    """Project stored CALLS_METHOD edge rows (with metadata) into IR candidates.

    Accepts either raw ``RuntimeStore.traverse_edges``/SQL rows (dicts with
    ``source_id``/``target_id``/``confidence``/``metadata``) or plain graph
    projections where those fields are top-level. Unresolvable calls map to
    ``target_ref=None`` diagnostics instead of being silently dropped.
    ``source_file_by_id`` optionally supplies node-id -> logical-path facts
    for per-file diagnostic breakdowns.
    """
    file_map = source_file_by_id or {}
    candidates: list[RelationCandidate] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if isinstance(edge.get("metadata"), dict):
            meta = edge["metadata"]
        elif isinstance(edge.get("metadata_json"), str):
            try:
                import json

                meta = json.loads(edge["metadata_json"])
            except Exception:
                meta = {}
        else:
            meta = edge
        resolution_level = str(meta.get("resolution_level") or "unresolved")
        source_key = str(edge.get("source_id") or "")
        target_id = str(edge.get("target_id") or "")
        key = (source_key, f"{target_id}:{str(meta.get('line', '') )}")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            RelationCandidate(
                source_key=source_key,
                relation="CALLS_METHOD",
                target_ref=target_id if resolution_level != "unresolved" else None,
                confidence=float(edge.get("confidence", meta.get("confidence", 0.0)) or 0.0),
                resolution_reason=str(meta.get("unresolved_reason") or resolution_level),
                evidence_level=_evidence_for_resolution(resolution_level, bool(meta.get("inferred_target"))),
                source_file=file_map.get(source_key, ""),
            )
        )
    return candidates


def summarize_unresolved(candidates: list[RelationCandidate]) -> dict[str, Any]:
    """Aggregate unproven candidates by reason code and evidence level.

    Counts and short reason codes only — never source snippets or prompt
    text — so the summary is safe for diagnostics and exports.
    """
    reason_counts: Counter[str] = Counter()
    level_counts: Counter[str] = Counter()
    total_resolved = 0
    total_unresolved = 0
    for candidate in candidates:
        level_counts[candidate.evidence_level] += 1
        if candidate.target_ref is None:
            total_unresolved += 1
            reason_counts[candidate.resolution_reason] += 1
        else:
            total_resolved += 1
    return {
        "total_calls": len(candidates),
        "resolved": total_resolved,
        "unresolved": total_unresolved,
        "evidence_levels": dict(sorted(level_counts.items())),
        "unresolved_reasons": [
            {"code": code, "count": count}
            for code, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def unresolved_by_file(candidates: list[RelationCandidate], *, max_files: int = 200) -> dict[str, dict[str, int]]:
    """Per-file unresolved breakdown for locating failure categories.

    Bounded output: paths are already-persisted workspace-relative logical
    paths, and the map is capped at ``max_files`` entries sorted by
    descending unresolved count then path.
    """
    per_file: dict[str, Counter[str]] = {}
    # call_edges_to_relation_candidates drops the file unless callers kept
    # it on the row; tolerate empty strings gracefully.
    for candidate in candidates:
        if candidate.target_ref is not None:
            continue
        bucket = per_file.setdefault(candidate.source_file or "(unknown)", Counter())
        bucket[candidate.resolution_reason] += 1
    ranked = sorted(per_file.items(), key=lambda item: (-sum(item[1].values()), item[0]))
    return {
        path: dict(sorted(counts.items(), key=lambda item: -item[1]))
        for path, counts in ranked[:max_files]
    }
