"""End-to-end tests for the multi-language indexer glue.

Verifies that ``emit_graph_elements`` translates a StructuralParseResult
into the same node/edge conventions used by the Java pipeline, and that
``parse_structural`` correctly routes files to the right walker.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from memory_center.core.indexing.multilang_indexer import (
    emit_graph_elements,
    is_structurally_indexable,
    parse_structural,
)
from memory_center.core.indexing.parse_result import (
    CallSite,
    StructuralParseResult,
    SymbolSpan,
)


def _has(mod: str) -> bool:
    try:
        importlib.import_module(mod)
        return True
    except ImportError:
        return False


# ── is_structurally_indexable ──────────────────────────────────────────────


def test_java_is_excluded_to_avoid_dual_emission(tmp_path: Path) -> None:
    """Java still flows through tree_sitter_parser.py; the structural
    pass must skip it so we don't emit duplicate Class/Function nodes."""
    assert not is_structurally_indexable(tmp_path / "Foo.java")


def test_python_typescript_go_kotlin_are_indexable(tmp_path: Path) -> None:
    for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".kt"):
        assert is_structurally_indexable(tmp_path / f"x{ext}"), ext


def test_unknown_extension_is_skipped(tmp_path: Path) -> None:
    assert not is_structurally_indexable(tmp_path / "x.md")
    assert not is_structurally_indexable(tmp_path / "x.txt")


# ── emit_graph_elements ────────────────────────────────────────────────────


def test_emit_module_and_class_and_function_nodes() -> None:
    result = StructuralParseResult(
        language="python",
        module="svc.orders",
        imports=["os", "pathlib.Path"],
        classes=[
            SymbolSpan(
                name="OrderService",
                qualified_name="OrderService",
                line=3,
                end_line=20,
                kind="class",
            )
        ],
        functions=[
            SymbolSpan(
                name="find_one",
                qualified_name="OrderService.find_one",
                line=5,
                end_line=10,
                parent_qualified_name="OrderService",
                kind="method",
            )
        ],
        calls=[
            CallSite(
                caller_qualified_name="OrderService.find_one",
                callee_text="fetch",
                line=7,
                receiver_text="self.client",
            )
        ],
    )

    nodes, edges = emit_graph_elements("orders-svc", "src/svc/orders.py", result)
    node_types = {n.type for n in nodes}
    assert {"Module", "Class", "Function"}.issubset(node_types)

    edge_types = {e.type for e in edges}
    assert {"DEFINES", "IMPORTS", "CALLS"}.issubset(edge_types)

    # The method's DEFINES edge should point at the Class node, not the
    # Module node (so callers/walkers can navigate class membership).
    class_node = next(n for n in nodes if n.type == "Class" and n.name == "OrderService")
    method_node = next(n for n in nodes if n.type == "Function" and n.name == "find_one")
    method_define_edges = [e for e in edges if e.type == "DEFINES" and e.target_id == method_node.id]
    assert len(method_define_edges) == 1
    assert method_define_edges[0].source_id == class_node.id


def test_emit_imports_creates_stub_module_targets() -> None:
    result = StructuralParseResult(
        language="python",
        module="svc.orders",
        imports=["os", "pathlib.Path"],
    )
    nodes, edges = emit_graph_elements("orders-svc", "svc/orders.py", result)
    import_edges = [e for e in edges if e.type == "IMPORTS"]
    assert len(import_edges) == 2
    targets = {e.target_id for e in import_edges}
    stub_modules = {n.id for n in nodes if n.type == "Module" and (n.metadata or {}).get("stub")}
    assert stub_modules == targets


def test_emit_call_edges_have_unresolved_low_confidence() -> None:
    """Calls land as low-confidence edges pointing at a synthetic
    Function node. The P1-1 resolver will rewrite both later."""
    result = StructuralParseResult(
        language="python",
        functions=[
            SymbolSpan(
                name="find_one",
                qualified_name="find_one",
                line=1,
                kind="function",
            )
        ],
        calls=[
            CallSite(
                caller_qualified_name="find_one",
                callee_text="fetch",
                line=2,
            )
        ],
    )
    _, edges = emit_graph_elements("svc", "f.py", result)
    call_edges = [e for e in edges if e.type == "CALLS"]
    assert len(call_edges) == 1
    assert call_edges[0].confidence < 0.5
    assert (call_edges[0].metadata or {}).get("resolution_level") == "unresolved"


def test_empty_result_still_emits_only_module() -> None:
    result = StructuralParseResult(language="python", module="empty")
    nodes, edges = emit_graph_elements("svc", "empty.py", result)
    # Even an empty file gets a Module node so other tools can refer to it.
    assert len(nodes) == 1
    assert nodes[0].type == "Module"
    assert edges == []


# ── parse_structural end-to-end ────────────────────────────────────────────


@pytest.mark.skipif(not _has("tree_sitter_python"), reason="tree-sitter-python not installed")
def test_parse_structural_python_end_to_end(tmp_path: Path) -> None:
    source = "import os\n\ndef hello():\n    print(os.getcwd())\n"
    py = tmp_path / "h.py"
    py.write_text(source, encoding="utf-8")
    result = parse_structural(py)
    assert result is not None
    assert not result.is_empty()
    assert result.language == "python"
    assert any(f.name == "hello" for f in result.functions)


def test_parse_structural_returns_none_for_unsupported_path(tmp_path: Path) -> None:
    md = tmp_path / "README.md"
    md.write_text("# hi", encoding="utf-8")
    assert parse_structural(md) is None


def test_parse_structural_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert parse_structural(tmp_path / "no.py") is None
