from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.indexing.differential import compare_parser_corpus, compare_parsers
from memory_center.core.indexing.java_regex_parser import RegexJavaParser
from memory_center.core.indexing.tree_sitter_parser import TreeSitterJavaParser

CORPUS = Path("examples/parser-corpus")


def test_parsers_agree_on_public_method_identity() -> None:
    if not TreeSitterJavaParser().available:
        pytest.skip("tree-sitter Java dependency is optional")

    report = compare_parsers(CORPUS / "OverloadedService.java")

    assert report["missing_in_tree_sitter"] == []
    assert report["critical_disagreements"] == []
    assert {item["identity"] for item in report["method_identities"]} >= {
        "find(String)",
        "find(String,Map<String,List<Long>>)",
        "convert(List<T>)",
        "run()",
    }


def test_differential_compares_controller_and_feign_mappings() -> None:
    if not TreeSitterJavaParser().available:
        pytest.skip("tree-sitter Java dependency is optional")

    controller = compare_parsers(CORPUS / "GenericController.java")
    contract = compare_parsers(CORPUS / "ContractApi.java")

    assert controller["controller_mappings"] == [
        {
            "controller": "GenericController",
            "method_name": "save",
            "http_method": "POST",
            "path": "/generic/items",
        }
    ]
    assert contract["feign_mappings"] == [
        {
            "interface": "ContractApi",
            "method_name": "getById",
            "http_method": "GET",
            "path": "/articles/{id}",
        }
    ]
    assert controller["critical_disagreements"] == []
    assert contract["critical_disagreements"] == []


def test_parser_corpus_meets_precision_gate() -> None:
    if not TreeSitterJavaParser().available:
        pytest.skip("tree-sitter Java dependency is optional")

    report = compare_parser_corpus(CORPUS)

    assert report["critical_disagreements"] == []
    assert report["entity_recall"] >= 0.98
    assert report["max_line_delta"] <= 1


def test_interface_default_method_has_one_correct_identity() -> None:
    parsed = RegexJavaParser().parse(
        (CORPUS / "ContractApi.java").read_text(encoding="utf-8"),
        "ContractApi.java",
    )

    identities = {item["identity"] for item in parsed.method_signatures}
    assert "normalize(String)" in identities
    assert "normalize()" not in identities


def test_nested_generic_parameter_keeps_receiver_type() -> None:
    parsed = RegexJavaParser().parse(
        (CORPUS / "OverloadedService.java").read_text(encoding="utf-8"),
        "OverloadedService.java",
    )

    call = next(item for item in parsed.method_calls if item["method_name"] == "size")
    assert call["receiver"] == "options"
    assert call["receiver_type"] == "Map"


def test_regex_parser_excludes_control_flow_and_constructors_from_methods() -> None:
    parsed = RegexJavaParser().parse(
        """
        class FlowService {
            FlowService() {}
            void process(boolean enabled) {
                if (enabled) {
                    for (int i = 0; i < 1; i++) {
                        while (false) {}
                    }
                } else {
                    switch (enabled ? 1 : 0) { default: break; }
                }
            }
        }
        """,
        "FlowService.java",
    )

    assert parsed.methods == ["process"]
    assert {signature["identity"] for signature in parsed.method_signatures} == {"process(boolean)"}


def test_annotation_constants_build_composite_paths() -> None:
    if not TreeSitterJavaParser().available:
        pytest.skip("tree-sitter Java dependency is optional")

    report = compare_parsers(CORPUS / "ConstantPaths.java")

    assert report["controller_mappings"] == [
        {
            "controller": "ConstantController",
            "method_name": "getById",
            "http_method": "GET",
            "path": "/catalog/{id}",
        }
    ]
    assert report["feign_mappings"] == [
        {
            "interface": "ConstantClient",
            "method_name": "getById",
            "http_method": "GET",
            "path": "/catalog/{id}",
        }
    ]


def test_tree_sitter_fallback_reason_is_observable() -> None:
    parser = TreeSitterJavaParser()
    parser._parser = None
    parser.reset_diagnostics()

    parsed = parser.parse("public class Demo {}", "Demo.java")

    assert parsed.classes == ["Demo"]
    assert parser.selected_parser == "regex"
    assert parser.diagnostics["fallback_count"] == 1
    assert parser.diagnostics["fallback_reasons"] == {"tree_sitter_unavailable": 1}


def test_reindex_returns_parser_selection_diagnostics(demo_workspace: Path) -> None:
    from memory_center.core.indexing.reindex import reindex_workspace
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.workspace.config import load_workspace_config

    config = load_workspace_config(demo_workspace)
    result = reindex_workspace(config, WorkspaceStore(demo_workspace))

    assert result["parser"] in {"tree-sitter", "regex"}
    assert result["parser_fallback_count"] >= 0
    assert result["parser_critical_disagreement_count"] >= 0
    assert result["parser_diagnostics"]["parse_count"] > 0
    assert "fallback_reasons" in result["parser_diagnostics"]
    assert result["parser_precision"]["status"] in {
        "regex_only",
        "mixed_fallback",
        "tree_sitter_active",
        "unknown",
    }
    assert "recommended_action" in result["parser_precision"]

    graph_summary = WorkspaceStore(demo_workspace).read_json_prefer_backend("graph-summary.json", {})
    assert graph_summary["parser_precision"]["status"] == result["parser_precision"]["status"]


def test_retrieval_exposes_parser_precision_diagnostics(demo_workspace: Path) -> None:
    from memory_center.core.indexing.reindex import reindex_workspace
    from memory_center.core.orchestrator import memory_query_hybrid
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.workspace.config import load_workspace_config

    config = load_workspace_config(demo_workspace)
    reindex_workspace(config, WorkspaceStore(demo_workspace))

    result = memory_query_hybrid(str(demo_workspace), "UserService", limit=5)
    diagnostics = result.get("retrieval_diagnostics", {})
    assert "parser_precision" in diagnostics
    assert diagnostics["parser_precision"]["recommended_action"]


def test_java_symbol_preserves_overloaded_method_signatures() -> None:
    from memory_center.core.indexing.reindex import parse_java_symbols

    text = (CORPUS / "OverloadedService.java").read_text(encoding="utf-8")
    symbol = parse_java_symbols("parser-corpus", "OverloadedService.java", text)

    identities = {item["identity"] for item in symbol.method_signatures}
    assert "find(String)" in identities
    assert "find(String,Map<String,List<Long>>)" in identities
