"""Java IR boundary + differential gate tests (task steps 3 & 4).

Verifies that the Java adapter emits explicit IR records, that the legacy
graph projection and the IR projection are produced by the same resolver
(so the diff gate compares like-for-like), and that the gate reports
anchor/edge recall >= 0.999 and zero forbidden hits for a real indexed
workspace.
"""
from __future__ import annotations

import pytest

from memory_center.core.indexing.diff_gate import ir_candidates_to_edges, run_diff_gate
from memory_center.core.indexing.ir import EVIDENCE_AMBIGUOUS, EVIDENCE_EXTRACTED
from memory_center.core.indexing.java_call_resolver import JavaCallResolver, build_java_class_index
from memory_center.core.indexing.java_ir import (
    build_java_ir_index,
    resolve_symbol_candidates,
    symbol_to_file_record,
    symbol_to_symbol_records,
)


def _sym(project="api", file="Order.java", methods=("submit",), calls=(), package="com.example"):
    return {
        "project": project,
        "file": file,
        "package": package,
        "classes": ["Order"],
        "interfaces": [],
        "methods": list(methods),
        "method_signatures": [],
        "fields": [],
        "imports": [],
        "bean_injections": [],
        "method_calls": list(calls),
    }


# ---------------------------------------------------------------------------
# Unit: IR records
# ---------------------------------------------------------------------------


def test_symbol_to_file_record():
    rec = symbol_to_file_record(_sym())
    assert rec.path == "Order.java"
    assert rec.language == "java"
    assert rec.parse_status == "parsed"


def test_symbol_to_symbol_records_has_class_and_methods():
    sym = _sym(methods=("submit", "ship"))
    records = symbol_to_symbol_records(sym)
    kinds = [r.kind for r in records]
    assert kinds.count("Class") == 1
    assert kinds.count("Method") == 2
    names = {r.qualified_name for r in records if r.kind == "Method"}
    assert "com.example.Order.submit" in names


def test_resolve_symbol_candidates_uses_legacy_alignment():
    """Candidates must carry node_id-formatted keys matching the legacy
    projection so the diff gate can align against real graph edges."""
    call = {"method_name": "submit", "receiver": "this", "owner_method": "run"}
    sym = _sym(methods=("submit", "run"), calls=[call])
    resolver = JavaCallResolver(build_java_class_index([sym]))
    candidates = resolve_symbol_candidates(sym, resolver)
    assert candidates
    candidate = candidates[0]
    # source key must be the legacy Method node id for this method
    assert candidate.source_key == "Method:api:Order:run"
    # same-class resolution lands on the real method node id
    assert candidate.target_ref == "Method:api:Order:submit"
    assert candidate.evidence_level == EVIDENCE_EXTRACTED


def test_unresolved_target_stays_ambiguous_with_fallback_edge():
    """An unresolved call keeps its fallback target (matching the legacy
    projection) but is flagged AMBIGUOUS, so downstream never treats it as
    a proven call."""
    call = {"method_name": "now", "receiver": "DateUtil", "owner_method": "run"}
    sym = _sym(methods=("run",), calls=[call])
    resolver = JavaCallResolver(build_java_class_index([sym]))
    candidates = resolve_symbol_candidates(sym, resolver)
    assert candidates[0].target_ref is not None
    assert candidates[0].evidence_level == EVIDENCE_AMBIGUOUS
    # Ambiguous edges materialize (like legacy) but carry the AMBIGUOUS flag.
    edges = ir_candidates_to_edges([c.__dict__ for c in candidates])
    assert len(edges) == 1
    assert edges[0]["evidence_level"] == EVIDENCE_AMBIGUOUS


# ---------------------------------------------------------------------------
# Unit: IR projection + gate
# ---------------------------------------------------------------------------


def test_ir_candidates_to_edges_only_materializes_resolved():
    resolved = {
        "source_key": "Method:api:Order:run",
        "target_ref": "Method:api:Order:submit",
        "relation": "CALLS_METHOD",
        "confidence": 0.9,
        "evidence_level": EVIDENCE_EXTRACTED,
    }
    ambiguous = {
        "source_key": "Method:api:Order:run",
        "target_ref": None,
        "relation": "CALLS_METHOD",
        "confidence": 0.3,
        "evidence_level": EVIDENCE_AMBIGUOUS,
    }
    edges = ir_candidates_to_edges([resolved, ambiguous])
    assert len(edges) == 1
    assert edges[0]["id"] == "CALLS_METHOD:Method:api:Order:run->Method:api:Order:submit"
    assert edges[0]["type"] == "CALLS_METHOD"


# ---------------------------------------------------------------------------
# Integration: pipeline produces IR + gate passes on real data
# ---------------------------------------------------------------------------


def test_reindex_produces_ir_index(demo_workspace_indexed):
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(demo_workspace_indexed)
    ir = store.read_json_prefer_backend("java-ir-index.json", {})
    assert ir.get("schema_version") == 1
    assert ir["file_count"] > 0
    assert ir["symbol_count"] > 0
    # each symbol with a call produced a candidate
    assert "relation_candidates" in ir
    gs = store.read_json_prefer_backend("graph-summary.json", {})
    assert gs.get("ir_index", {}).get("candidate_count", 0) == ir["candidate_count"]


def test_diff_gate_passes_on_real_workspace(demo_workspace_indexed):
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(demo_workspace_indexed)
    ir = store.read_json_prefer_backend("java-ir-index.json", {})
    gate = run_diff_gate(ir, graph_db_path=str(store.graph_db_path))
    # Same resolver -> IR projection must match legacy edges exactly.
    assert gate["gate_passed"] is True
    assert gate["anchor_recall"] >= 0.999
    assert gate["edge_coverage"] >= 0.999
    assert gate["forbidden_hit"] == 0.0
    # ambiguous is evidence-level based (may overlap resolved via fallback
    # targets); candidates is the full set.
    assert gate["ambiguous"] <= gate["candidates"]
    assert gate["resolved"] <= gate["candidates"]
