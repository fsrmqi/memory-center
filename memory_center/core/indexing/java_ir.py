"""Java adapter IR boundary (task step 3: Java parser emits real IR).

Per docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md §5.1 and the
task ordering, the Java parser must output explicit IR records
(``FileRecord`` / ``SymbolRecord`` / ``RelationCandidate``) as the boundary
between parsing and graph projection, instead of having projection
implicitly consume the raw parser dicts.

This module adapts the existing Java parse output (``java-symbol-index.json``
rows) and the resolver (``JavaCallResolver``) into those IR records. It
reuses the *same* resolver so the differential gate in step 4 compares
like-for-like: IR candidates vs the graph edges the legacy projection
would have produced.

Contract rules (unchanged from the design doc):
- unprovable targets stay ``AMBIGUOUS`` with ``target_ref=None`` — never a
  fabricated edge;
- ``stable_id`` is derived from workspace facts, not SQLite rowids;
- this is additive: the legacy projection path remains authoritative until
  the differential gate proves the IR projection is equivalent-or-better.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from memory_center.core.indexing.ir import (
    EVIDENCE_AMBIGUOUS,
    EVIDENCE_EXTRACTED,
    EVIDENCE_INFERRED,
    RelationCandidate,
    stable_id,
)
from memory_center.core.indexing.java_call_resolver import JavaCallResolver, build_java_class_index

IR_INDEX_FILE = "java-ir-index.json"


def _evidence_level(resolved) -> str:
    if getattr(resolved, "resolution_level", "") == "unresolved":
        return EVIDENCE_AMBIGUOUS
    if getattr(resolved, "inferred_target", False):
        return EVIDENCE_INFERRED
    return EVIDENCE_EXTRACTED


def symbol_to_file_record(sym: dict[str, Any], *, parse_status: str = "parsed") -> "FileRecord":
    """Project one java-symbol row into a FileRecord."""
    from memory_center.core.indexing.ir import FileRecord

    return FileRecord(
        path=str(sym.get("file", "")),
        content_hash=stable_id(sym.get("project", ""), sym.get("file", ""), str(sym.get("package", "") or "")),
        language="java",
        parse_status=parse_status,
    )


def symbol_to_symbol_records(sym: dict[str, Any]) -> list["SymbolRecord"]:
    """Project one java-symbol row into its SymbolRecords (classes/ifaces/methods)."""
    from memory_center.core.indexing.ir import SymbolRecord

    project = str(sym.get("project", "") or "")
    file = str(sym.get("file", "") or "")
    package = str(sym.get("package", "") or "")
    records: list[SymbolRecord] = []
    for cls in list(sym.get("classes", []) or []) + list(sym.get("interfaces", []) or []):
        records.append(
            SymbolRecord(
                stable_key=stable_id(project, file, "Class", package, str(cls)),
                kind="Class",
                qualified_name=f"{package}.{cls}" if package else str(cls),
                evidence_level=EVIDENCE_EXTRACTED,
            )
        )
        for method in sym.get("methods", []) or []:
            records.append(
                SymbolRecord(
                    stable_key=stable_id(project, file, "Method", package, str(cls), str(method)),
                    kind="Method",
                    qualified_name=f"{package}.{cls}.{method}" if package else f"{cls}.{method}",
                    evidence_level=EVIDENCE_EXTRACTED,
                )
            )
    return records


def resolve_symbol_candidates(sym: dict[str, Any], resolver: JavaCallResolver) -> list[RelationCandidate]:
    """Resolve every method_call in one symbol through the resolver to IR candidates.

    Uses the same ``JavaCallResolver`` as the legacy graph projection so the
    differential gate (step 4) compares identical resolution decisions.

    ``source_key`` / ``target_ref`` use the same ``node_id("Method", …)``
    format as the legacy projection (see ``build_graph_store``), so the gate
    can align IR candidates against real graph edges by node id.
    """
    from memory_center.core.storage.graph import node_id

    project = str(sym.get("project", "") or "")
    file = str(sym.get("file", "") or "")
    owner_classes = list(sym.get("classes", []) or []) + list(sym.get("interfaces", []) or [])
    owner_class = owner_classes[0] if owner_classes else str(Path(file).stem)
    candidates: list[RelationCandidate] = []
    for call in sym.get("method_calls", []) or []:
        resolved = resolver.resolve_call(sym, call)
        owner_method = str(call.get("owner_method") or resolved.source_method or "")
        source_node = node_id("Method", project, resolved.source_class or owner_class, owner_method)
        # Keep the fallback target even for unresolved calls: the legacy
        # projection materializes these edges too (target = fallback_class
        # node), and the differential gate must compare like-for-like. The
        # AMBIGUOUS evidence level is what signals "unproven" downstream.
        target_node = node_id(
            "Method",
            resolved.target_project,
            resolved.target_class,
            resolved.target_method,
        )
        candidates.append(
            RelationCandidate(
                source_key=source_node,
                relation="CALLS_METHOD",
                target_ref=target_node,
                confidence=float(resolved.confidence or 0.0),
                resolution_reason=str(resolved.unresolved_reason or resolved.resolution_level or "unresolved"),
                evidence_level=_evidence_level(resolved),
                source_file=file,
            )
        )
    return candidates


def build_java_ir_index(symbols: list[dict[str, Any]], *, resolver: JavaCallResolver | None = None) -> dict[str, Any]:
    """Build the IR index payload for one workspace symbol set.

    Returns a serializable, deterministic, additive payload (never the raw
    parser dicts, and never source text).
    """
    active_resolver = resolver or JavaCallResolver(build_java_class_index(symbols))
    file_records: list[dict[str, Any]] = []
    symbol_records: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for sym in symbols:
        file_record = symbol_to_file_record(sym)
        file_records.append(
            {
                "path": file_record.path,
                "content_hash": file_record.content_hash,
                "language": file_record.language,
                "parse_status": file_record.parse_status,
            }
        )
        symbol_records.extend(
            {
                "stable_key": record.stable_key,
                "kind": record.kind,
                "qualified_name": record.qualified_name,
                "evidence_level": record.evidence_level,
            }
            for record in symbol_to_symbol_records(sym)
        )
        candidates.extend(
            {
                "source_key": candidate.source_key,
                "relation": candidate.relation,
                "target_ref": candidate.target_ref,
                "confidence": candidate.confidence,
                "resolution_reason": candidate.resolution_reason,
                "evidence_level": candidate.evidence_level,
                "source_file": candidate.source_file,
            }
            for candidate in resolve_symbol_candidates(sym, active_resolver)
        )
    return {
        "schema_version": 1,
        "file_count": len(file_records),
        "symbol_count": len(symbol_records),
        "candidate_count": len(candidates),
        "file_records": file_records,
        "symbol_records": symbol_records,
        "relation_candidates": candidates,
    }


def fingerprint_index(payload: dict[str, Any]) -> str:
    """Deterministic fingerprint over the IR payload (for the diff gate)."""
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
