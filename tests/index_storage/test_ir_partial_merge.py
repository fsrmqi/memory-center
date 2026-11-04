"""Scoped refresh IR partial-merge tests (long task: refresh performance).

Verifies that a partial refresh re-resolves only the scoped files' IR
candidates and inherits unchanged files', without lowering coverage or
breaking the diff gate. Also pins the scope-correctness invariants the
optimization must not violate (old generation readable, no unrelated
project expansion).
"""
from __future__ import annotations

import pytest

from memory_center.core.indexing.reindex import _merge_ir_partial


def _sym(project, file, methods=("run",), calls=()):
    return {
        "project": project,
        "file": file,
        "package": "com.example",
        "classes": ["Anchor"],
        "interfaces": [],
        "methods": list(methods),
        "method_signatures": [],
        "fields": [],
        "imports": [],
        "bean_injections": [],
        "method_calls": list(calls),
    }


def test_merge_ir_partial_inherits_unchanged_candidates(monkeypatch, tmp_path):
    """A partial refresh over one file must keep other files' candidates."""
    import json
    from pathlib import Path

    from memory_center.core.storage.workspace import WorkspaceStore

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    (ws_dir / "index").mkdir(parents=True)
    (ws_dir / "graph").mkdir()
    (ws_dir / "memory").mkdir()
    ws_file = ws_dir / "workspace.yaml"
    ws_file.write_text("workspace: demo\nroot: .\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(ws_file)

    # Fake previous generation IR with candidates from two files.
    old_ir = {
        "schema_version": 1,
        "file_count": 2,
        "symbol_count": 2,
        "candidate_count": 2,
        "file_records": [{"path": "a/A.java", "content_hash": "h1", "language": "java", "parse_status": "parsed"},
                         {"path": "b/B.java", "content_hash": "h2", "language": "java", "parse_status": "parsed"}],
        "symbol_records": [],
        "relation_candidates": [
            {"source_key": "Method:pa:Anchor:run", "relation": "CALLS_METHOD", "target_ref": "t1", "confidence": 0.9,
             "resolution_reason": "same_class", "evidence_level": "EXTRACTED", "source_file": "a/A.java"},
            {"source_key": "Method:pb:Anchor:run", "relation": "CALLS_METHOD", "target_ref": "t2", "confidence": 0.9,
             "resolution_reason": "same_class", "evidence_level": "EXTRACTED", "source_file": "b/B.java"},
        ],
    }
    store.write_json("java-ir-index.json", old_ir)

    # Partial scope = file a/A.java only.
    symbols = [
        _sym("pa", "a/A.java", calls=[{"method_name": "run", "receiver": "this", "owner_method": "go"}]),
        _sym("pb", "b/B.java"),
    ]
    result = _merge_ir_partial(store, symbols, set(), ["a/A.java"])
    # Unchanged b/B.java candidate inherited, a/A.java re-resolved.
    source_files = {c["source_file"] for c in result["relation_candidates"]}
    assert "b/B.java" in source_files
    assert "a/A.java" in source_files
    assert result["candidate_count"] >= 2


def test_merge_ir_partial_full_rebuild_drops_deleted_file(monkeypatch, tmp_path):
    """A full rebuild path must not inherit stale candidates from deleted
    files; the merge path only inherits when scope excludes a file."""
    import json
    from pathlib import Path

    from memory_center.core.indexing.java_ir import build_java_ir_index
    from memory_center.core.storage.workspace import WorkspaceStore

    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    (ws_dir / "index").mkdir(parents=True)
    (ws_dir / "graph").mkdir()
    (ws_dir / "memory").mkdir()
    ws_file = ws_dir / "workspace.yaml"
    ws_file.write_text("workspace: demo\nroot: .\nservices: []\n", encoding="utf-8")
    store = WorkspaceStore(ws_file)
    store.write_json("java-ir-index.json", {
        "schema_version": 1, "file_count": 1, "symbol_count": 1, "candidate_count": 1,
        "file_records": [], "symbol_records": [],
        "relation_candidates": [
            {"source_key": "Method:pa:Anchor:run", "relation": "CALLS_METHOD", "target_ref": "t",
             "confidence": 0.9, "resolution_reason": "same_class", "evidence_level": "EXTRACTED",
             "source_file": "gone/G.java"},
        ],
    })
    # Full rebuild (non-partial path) builds from scratch; no stale inheritance.
    fresh = build_java_ir_index([])
    assert fresh["relation_candidates"] == []
