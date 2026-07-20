"""P1 / P1.5 regression tests.

Locks in two gaps fixed during the P1 expansion:

1. ``RegexJavaParser`` previously treated abstract interface method
   declarations (and ``@interface`` element declarations) as method
   bodies, causing the bare-call regex pass to match the method's own
   signature inside ``start..end`` and emit a fake self-call. After the
   fix declaration-only spans carry ``is_declaration=True`` and the
   bare-call pass skips them, so an interface file produces zero
   ``method_calls``.

2. ``GoldenCase`` now supports an optional ``enable_vector`` flag so
   concept-style queries can lock the dense-vector retrieval gains
   documented in ``docs/benchmarks/P0_5_VECTOR_VALIDATION.md`` into the
   long-term golden suite. The flag is forwarded to ``memory_query_hybrid``
   only for ``mode=hybrid`` cases.

3. ``_sync_retrieval_indexes`` must not wipe out an existing
   ``VectorIndex`` when the rebuilt semantic index has zero dense
   vectors (e.g. a ``MEMORY_CENTER_SEMANTIC_BACKEND=sparse`` reindex run
   after a previous ST run). Previously every reindex called
   ``vector_index.clear()`` unconditionally and silently invalidated the
   dense embeddings.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from memory_center.core.benchmark.cases import GoldenCase
from memory_center.core.indexing.java_regex_parser import RegexJavaParser


class TestInterfaceMethodSelfLoopFix:
    def test_interface_declarations_produce_no_method_calls(self) -> None:
        src = """
package com.example;

public interface FooService {
    PageVo pageByDto(QueryDto dto);
    Vo getById(QueryDto dto);
    Boolean updateByDto(SaveDto dto);
}
"""
        parser = RegexJavaParser()
        result = parser.parse(src, "FooService.java")
        # Abstract interface methods are declarations, not call sites.
        # The bare-call pass should skip them entirely.
        assert result.method_calls == [], (
            f"interface declarations should produce 0 method_calls, "
            f"got {result.method_calls}"
        )

    def test_default_method_body_still_emits_calls(self) -> None:
        # ``default`` and ``static`` interface methods *do* have bodies
        # and should keep producing call edges. The fix must not regress
        # these.
        src = """
package com.example;

public interface FooService {
    default void doIt(QueryDto dto) {
        helper(dto);
    }
    Vo getById(QueryDto dto);
}
"""
        result = RegexJavaParser().parse(src, "FooService.java")
        method_names = [c["method_name"] for c in result.method_calls]
        assert "helper" in method_names, (
            f"default method body should still produce bare-call edges, "
            f"got method_calls={result.method_calls}"
        )


class TestGoldenCaseEnableVector:
    def test_default_enable_vector_is_false(self) -> None:
        case = GoldenCase.from_mapping({
            "case_id": "demo",
            "query": "Class#m",
            "mode": "walkthrough",
        })
        assert case.enable_vector is False

    def test_enable_vector_round_trips(self) -> None:
        case = GoldenCase.from_mapping({
            "case_id": "demo",
            "query": "概念查询",
            "mode": "hybrid",
            "enable_vector": True,
        })
        assert case.enable_vector is True
        payload = case.to_dict()
        assert payload["enable_vector"] is True

    def test_enable_vector_in_supported_fields(self) -> None:
        # Adding the flag must not break the unknown-field validator.
        GoldenCase.from_mapping({
            "case_id": "demo",
            "query": "Class#m",
            "mode": "hybrid",
            "enable_vector": False,
            "expected_anchors": ["Class#m"],
        })


class TestSyncRetrievalPreservesExistingVectors:
    def test_empty_semantic_index_does_not_clear_existing_embeddings(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Build a minimal workspace + graph + a VectorIndex with one
        # embedding, then call _sync_retrieval_indexes with a
        # semantic_index that has no ``dense_vector``. The embedding
        # should still be there afterwards.
        from memory_center.core.indexing.reindex import _sync_retrieval_indexes
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex

        graph_db = tmp_path / "graph.db"
        # Seed graph with one node
        with RuntimeStore(graph_db) as graph:
            graph.rebuild([], [])
            from memory_center.core.storage.graph import GraphNode

            graph.bulk_write([GraphNode(id="n1", type="Method", name="m", project="p")], [])

        # Seed VectorIndex with one embedding
        unified = RuntimeStore(graph_db)
        index = VectorIndex(unified, dimension=4)
        index.upsert_embedding("n1", [0.1, 0.2, 0.3, 0.4])
        before = index.stats()["embedding_count"]
        unified.close()
        assert before == 1

        class _Store:
            graph_db_path = graph_db
            workspace_file = tmp_path / "workspace.yaml"

        # semantic_index payload without dense vectors (sparse-only rebuild)
        semantic_index = {"docs": [{"node_id": "n1"}]}
        counts = _sync_retrieval_indexes(_Store(), semantic_index)
        assert counts["vector_embeddings"] == 0

        unified = RuntimeStore(graph_db)
        after = VectorIndex(unified, dimension=4).stats()["embedding_count"]
        unified.close()
        assert after == 1, "sparse-only sync must not wipe existing dense embeddings"

    def test_partial_sync_upserts_changed_dense_doc_and_preserves_others(
        self, tmp_path: Path
    ) -> None:
        from memory_center.core.indexing.reindex import _sync_retrieval_indexes
        from memory_center.core.storage.graph import GraphNode
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex

        graph_db = tmp_path / "graph.db"
        with RuntimeStore(graph_db) as graph:
            graph.rebuild(
                [
                    GraphNode(id="n1", type="Method", name="changed", project="p"),
                    GraphNode(id="n2", type="Method", name="kept", project="p"),
                ],
                [],
            )

        unified = RuntimeStore(graph_db)
        index = VectorIndex(unified, dimension=4)
        index.upsert_embedding("n1", [0.1, 0.2, 0.3, 0.4])
        index.upsert_embedding("n2", [0.4, 0.3, 0.2, 0.1])
        unified.close()

        class _Store:
            graph_db_path = graph_db
            workspace_file = tmp_path / "workspace.yaml"

        semantic_index = {
            "docs": [
                {"node_id": "n1", "dense_vector": [0.9, 0.8, 0.7, 0.6]},
                # n2 is kept in VectorIndex because it is not in changed_node_ids.
                {"node_id": "n2", "dense_vector": [0.4, 0.3, 0.2, 0.1]},
            ]
        }
        counts = _sync_retrieval_indexes(_Store(), semantic_index, changed_node_ids={"n1"})
        assert counts["vector_sync_mode"] == "partial"
        assert counts["vector_embeddings"] == 1
        assert counts["vector_deleted"] == 1

        unified = RuntimeStore(graph_db)
        stats = VectorIndex(unified, dimension=4).stats()
        with unified.pool.connection() as conn:
            blob = conn.execute("SELECT embedding FROM vec_fallback WHERE node_id='n1'").fetchone()[0]
        unified.close()
        assert stats["embedding_count"] == 2
        assert struct.unpack("4f", bytes(blob)) == pytest.approx((0.9, 0.8, 0.7, 0.6))
