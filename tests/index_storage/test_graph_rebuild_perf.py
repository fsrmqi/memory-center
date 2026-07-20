"""Tests for the executemany rewrite of RuntimeStore.rebuild /
rebuild_search_index plus the fast_write_mode wrapping behaviour.

Functional parity is the main concern: the rewrite must produce the
same persisted rows as the previous loop-of-INSERT path and must still
restore synchronous=NORMAL after a successful rebuild.
"""
from __future__ import annotations

from pathlib import Path

from memory_center.core.storage.graph import GraphEdge, GraphNode
from memory_center.core.storage.pragmas import read_pragma_state
from memory_center.core.storage.runtime import RuntimeStore


def _node(i: int) -> GraphNode:
    return GraphNode(
        id=f"n{i}",
        type="Function",
        name=f"func_{i}",
        project="demo",
        file_path=f"src/file_{i % 7}.py",
        line=i,
        metadata={"index": i},
    )


def _edge(i: int) -> GraphEdge:
    return GraphEdge(
        id=f"e{i}",
        source_id=f"n{i}",
        target_id=f"n{(i + 1) % 100}",
        type="CALLS",
        confidence=0.9,
        metadata={"index": i},
    )


# ── rebuild ────────────────────────────────────────────────────────────────


def test_rebuild_persists_all_rows(tmp_path: Path) -> None:
    """The executemany rewrite must persist every node/edge it is given."""
    nodes = [_node(i) for i in range(100)]
    edges = [_edge(i) for i in range(100)]

    with RuntimeStore(tmp_path / "g.sqlite") as graph:
        graph.rebuild(nodes, edges)
        counts = graph.counts()

    assert counts["nodes"] == 100
    assert counts["edges"] == 100


def test_rebuild_with_empty_inputs(tmp_path: Path) -> None:
    """Empty input must not raise — and must clear existing rows so
    callers can rely on rebuild for a hard reset."""
    with RuntimeStore(tmp_path / "g.sqlite") as graph:
        # First fill with some data.
        graph.rebuild([_node(0)], [_edge(0)])
        assert graph.counts() == {"nodes": 1, "edges": 1}

        # Then rebuild with empty iterables — should leave us with nothing.
        graph.rebuild([], [])
        assert graph.counts() == {"nodes": 0, "edges": 0}


def test_rebuild_restores_synchronous_pragma(tmp_path: Path) -> None:
    """fast_write_mode wraps rebuild; once it returns we must be back
    on NORMAL so accidental subsequent user writes are durable."""
    with RuntimeStore(tmp_path / "g.sqlite") as graph:
        graph.rebuild([_node(0)], [_edge(0)])
        state = read_pragma_state(graph.connect())
    assert state["synchronous"] == "NORMAL"


def test_rebuild_idempotent(tmp_path: Path) -> None:
    """Running rebuild twice with the same data should be a no-op for
    counts (and prove the ON CONFLICT DO UPDATE path works under
    executemany)."""
    nodes = [_node(i) for i in range(50)]
    edges = [_edge(i) for i in range(50)]

    with RuntimeStore(tmp_path / "g.sqlite") as graph:
        graph.rebuild(nodes, edges)
        graph.rebuild(nodes, edges)
        counts = graph.counts()
    assert counts == {"nodes": 50, "edges": 50}


# ── rebuild_search_index ──────────────────────────────────────────────────


def test_rebuild_search_index_populates_fts(tmp_path: Path) -> None:
    """After rebuild_search_index every node should be searchable via
    find_nodes (which prefers the FTS path)."""
    nodes = [_node(i) for i in range(20)]

    with RuntimeStore(tmp_path / "g.sqlite") as graph:
        graph.rebuild(nodes, [])
        graph.rebuild_search_index()

        matches = graph.find_nodes("func_3", limit=5)
        names = {row["name"] for row in matches}
        assert "func_3" in names


def test_rebuild_search_index_empty_graph_no_raise(tmp_path: Path) -> None:
    """An empty graph must not blow up the FTS path."""
    with RuntimeStore(tmp_path / "g.sqlite") as graph:
        graph.rebuild_search_index()  # should be a no-op
        assert graph.counts() == {"nodes": 0, "edges": 0}


def test_neighbors_edge_type_filter_applies_before_limit(tmp_path: Path) -> None:
    """A type-filtered neighbor query must limit matching edges, not all edges.

    Large real graphs often have many mixed edge types from one anchor.
    If ``LIMIT`` is applied before the edge-type predicate, callers can
    miss the first matching relationship entirely.
    """
    nodes = [GraphNode("anchor", "Class", "Anchor")]
    nodes.extend(GraphNode(f"noise_{i}", "Class", f"Noise{i}") for i in range(20))
    nodes.append(GraphNode("target", "Class", "Target"))
    edges = [
        GraphEdge(
            f"noise_edge_{i}",
            "anchor",
            f"noise_{i}",
            "AAAA_NOISE",
        )
        for i in range(20)
    ]
    edges.append(GraphEdge("target_edge", "anchor", "target", "CALLS_METHOD"))

    with RuntimeStore(tmp_path / "g.sqlite") as graph:
        graph.rebuild(nodes, edges)
        results = graph.traverse_edges(
            "anchor",
            direction="downstream",
            max_depth=1,
            limit=1,
            edge_types=["CALLS_METHOD"],
        )

    assert [row["id"] for row in results] == ["target_edge"]
