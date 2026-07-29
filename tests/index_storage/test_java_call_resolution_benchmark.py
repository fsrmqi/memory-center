from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import yaml
from typer.testing import CliRunner

from memory_center.cli.main import app
from memory_center.core.benchmark.java_call_resolution import (
    load_java_call_resolution_cases,
    review_java_call_resolution_suite,
    run_java_call_resolution_suite,
    summarize_unresolved_java_calls,
)
from memory_center.core.storage.graph import GraphEdge, GraphNode, edge_id, node_id
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.http.server import create_handler


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True)
    workspace.write_text(
        yaml.safe_dump({
            "workspace": "test",
            "root": str(tmp_path),
            "services": [],
        }),
        encoding="utf-8",
    )
    return workspace


def _write_cases(path: Path, rows: list[dict]) -> Path:
    path.write_text(yaml.safe_dump({"schema_version": 1, "cases": rows}), encoding="utf-8")
    return path


def test_java_call_resolution_suite_scores_expected_edges(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    source_id = node_id("Method", "OrderController.submit", "api", "OrderController.java")
    target_id = node_id("Method", "OrderService.submit", "api", "OrderService.java")
    allowed_id = node_id("Method", "AuditService.record", "api", "AuditService.java")
    forbidden_id = node_id("Method", "WrongService.submit", "api", "WrongService.java")
    with RuntimeStore(store.graph_db_path) as graph:
        graph.bulk_write(
            [
                GraphNode(source_id, "Method", "OrderController.submit", "api", "OrderController.java"),
                GraphNode(target_id, "Method", "OrderService.submit", "api", "OrderService.java"),
                GraphNode(allowed_id, "Method", "AuditService.record", "api", "AuditService.java"),
                GraphNode(forbidden_id, "Method", "WrongService.submit", "api", "WrongService.java"),
            ],
            [
                GraphEdge(
                    edge_id(source_id, target_id, "CALLS_METHOD"),
                    source_id,
                    target_id,
                    "CALLS_METHOD",
                    confidence=0.9,
                    metadata={"resolution_level": "import", "target_fqcn": "com.example.OrderService"},
                ),
                GraphEdge(
                    edge_id(source_id, allowed_id, "CALLS_METHOD"),
                    source_id,
                    allowed_id,
                    "CALLS_METHOD",
                    confidence=0.9,
                    metadata={"resolution_level": "import"},
                ),
                GraphEdge(
                    edge_id(source_id, forbidden_id, "CALLS_METHOD"),
                    source_id,
                    forbidden_id,
                    "CALLS_METHOD",
                    confidence=0.9,
                    metadata={"resolution_level": "import"},
                ),
            ],
        )
    cases = _write_cases(
        tmp_path / "java-call-cases.yaml",
        [{
            "case_id": "controller-to-service",
            "source": "OrderController#submit",
            "expected_target": "OrderService#submit",
            "project": "api",
            "min_confidence": 0.85,
            "expected_resolution_levels": ["import"],
            "allowed_targets": ["AuditService#record"],
            "forbidden_targets": ["WrongService#submit"],
        }],
    )

    result = run_java_call_resolution_suite(workspace, cases)

    assert result["summary"]["passed"] is True
    assert result["summary"]["edge_recall"] == 1.0
    assert result["summary"]["high_confidence_expected_rate"] == 1.0
    assert result["summary"]["allowed_high_confidence_edge_count"] == 1
    assert result["summary"]["forbidden_high_confidence_edge_count"] == 1
    assert result["summary"]["unexpected_high_confidence_edge_count"] == 0
    assert result["cases"][0]["matched_edge"]["target"] == "OrderService#submit"
    assert result["cases"][0]["allowed_high_confidence_edges"][0]["target"] == "AuditService#record"
    assert result["cases"][0]["forbidden_high_confidence_edges"][0]["target"] == "WrongService#submit"

    strict_result = run_java_call_resolution_suite(
        workspace,
        cases,
        fail_on_forbidden_high_confidence=True,
    )
    assert strict_result["summary"]["passed"] is False


def test_java_call_resolution_suite_reports_unresolved_missing_target(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    source_id = node_id("Method", "OrderController.submit", "api", "OrderController.java")
    unresolved_id = node_id("Method", "UnknownService.submit", "api", "OrderController.java")
    with RuntimeStore(store.graph_db_path) as graph:
        graph.bulk_write(
            [
                GraphNode(source_id, "Method", "OrderController.submit", "api", "OrderController.java"),
                GraphNode(unresolved_id, "Method", "UnknownService.submit", "api", "OrderController.java"),
            ],
            [
                GraphEdge(
                    edge_id(source_id, unresolved_id, "CALLS_METHOD"),
                    source_id,
                    unresolved_id,
                    "CALLS_METHOD",
                    confidence=0.2,
                    metadata={"resolution_level": "unresolved"},
                ),
            ],
        )
    cases = _write_cases(
        tmp_path / "java-call-cases.yaml",
        [{
            "case_id": "missing-service",
            "source": "OrderController#submit",
            "expected_target": "OrderService#submit",
        }],
    )

    result = run_java_call_resolution_suite(workspace, cases)

    assert result["summary"]["passed"] is False
    assert result["summary"]["edge_recall"] == 0.0
    assert result["summary"]["unresolved_rate"] == 1.0
    assert result["cases"][0]["target_found"] is False


def test_java_call_resolution_cases_reject_filesystem_paths(tmp_path: Path) -> None:
    cases = _write_cases(
        tmp_path / "java-call-cases.yaml",
        [{
            "case_id": "bad",
            "source": "/tmp/OrderController.java",
            "expected_target": "OrderService#submit",
        }],
    )

    try:
        load_java_call_resolution_cases(cases)
    except ValueError as exc:
        assert "filesystem path" in str(exc)
    else:
        raise AssertionError("expected filesystem path rejection")


def test_java_call_resolution_cases_reject_non_list_edge_contracts(tmp_path: Path) -> None:
    cases = _write_cases(
        tmp_path / "java-call-cases.yaml",
        [{
            "case_id": "bad-contract",
            "source": "OrderController#submit",
            "expected_target": "OrderService#submit",
            "allowed_targets": "AuditService#record",
        }],
    )

    try:
        load_java_call_resolution_cases(cases)
    except ValueError as exc:
        assert "allowed_targets must be a list" in str(exc)
    else:
        raise AssertionError("expected edge contract validation failure")


def test_java_call_resolution_review_deduplicates_unclassified_edges(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    source_id = node_id("Method", "OrderController.submit", "api", "OrderController.java")
    target_id = node_id("Method", "OrderService.submit", "api", "OrderService.java")
    side_id = node_id("Method", "AuditService.record", "api", "AuditService.java")
    with RuntimeStore(store.graph_db_path) as graph:
        graph.bulk_write(
            [
                GraphNode(source_id, "Method", "OrderController.submit", "api", "OrderController.java"),
                GraphNode(target_id, "Method", "OrderService.submit", "api", "OrderService.java"),
                GraphNode(side_id, "Method", "AuditService.record", "api", "AuditService.java"),
            ],
            [
                GraphEdge(edge_id(source_id, target_id, "CALLS_METHOD"), source_id, target_id, "CALLS_METHOD", 0.9, {}),
                GraphEdge(edge_id(source_id, side_id, "CALLS_METHOD"), source_id, side_id, "CALLS_METHOD", 0.9, {"resolution_level": "import"}),
            ],
        )
    cases = _write_cases(
        tmp_path / "java-call-review-cases.yaml",
        [
            {"case_id": "same-source-a", "source": "OrderController#submit", "expected_target": "OrderService#submit", "project": "api"},
            {"case_id": "same-source-b", "source": "OrderController#submit", "expected_target": "OrderService#submit", "project": "api"},
        ],
    )

    result = review_java_call_resolution_suite(workspace, cases, limit=10)

    assert result["summary"]["unclassified_high_confidence_edge_count"] == 1
    assert result["items"] == [{
        "source": "OrderController#submit",
        "target": "AuditService#record",
        "resolution_level": "import",
        "confidence": 0.9,
        "case_ids": ["same-source-a", "same-source-b"],
        "expected_targets": ["OrderService#submit"],
        "review_status": "unclassified",
    }]


def test_unresolved_java_call_report_groups_reasons_without_paths(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    source_id = node_id("Method", "OrderController.submit", "api", "src/OrderController.java")
    external_id = node_id("Method", "RemoteClient.send", "api", "src/OrderController.java")
    polymorphic_id = node_id("Method", "OrderHandler.handle", "api", "src/OrderController.java")
    resolved_id = node_id("Method", "OrderService.submit", "api", "src/OrderService.java")
    with RuntimeStore(store.graph_db_path) as graph:
        graph.bulk_write(
            [
                GraphNode(source_id, "Method", "OrderController.submit", "api", "src/OrderController.java"),
                GraphNode(external_id, "Method", "RemoteClient.send", "api", "src/OrderController.java"),
                GraphNode(polymorphic_id, "Method", "OrderHandler.handle", "api", "src/OrderController.java"),
                GraphNode(resolved_id, "Method", "OrderService.submit", "api", "src/OrderService.java"),
            ],
            [
                GraphEdge(edge_id(source_id, external_id, "CALLS_METHOD"), source_id, external_id, "CALLS_METHOD", 0.3, {"resolution_level": "unresolved", "unresolved_reason": "receiver_type_not_indexed"}),
                GraphEdge(edge_id(source_id, polymorphic_id, "CALLS_METHOD"), source_id, polymorphic_id, "CALLS_METHOD", 0.3, {"resolution_level": "unresolved", "unresolved_reason": "target_method_not_indexed"}),
                GraphEdge(edge_id(source_id, resolved_id, "CALLS_METHOD"), source_id, resolved_id, "CALLS_METHOD", 0.9, {"resolution_level": "import"}),
            ],
        )

    result = summarize_unresolved_java_calls(workspace, sample_limit=10)

    assert result["summary"]["call_edge_count"] == 3
    assert result["summary"]["unresolved_call_edge_count"] == 2
    assert result["summary"]["category_counts"] == {
        "external_or_missing_source": 1,
        "missing_method_or_polymorphism": 1,
    }
    assert result["samples"] == [
        {"source": "OrderController#submit", "target": "OrderHandler#handle", "category": "missing_method_or_polymorphism", "reason": "target_method_not_indexed", "receiver_shape": "unqualified_or_dynamic", "confidence": 0.3},
        {"source": "OrderController#submit", "target": "RemoteClient#send", "category": "external_or_missing_source", "reason": "receiver_type_not_indexed", "receiver_shape": "unqualified_or_dynamic", "confidence": 0.3},
    ]
    assert "src/" not in str(result)


def test_unresolved_java_call_report_reclassifies_legacy_static_receivers(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    source_id = node_id("Method", "OrderController.submit", "api", "src/OrderController.java")
    target_id = node_id("Method", "Assert.notNull", "api", "src/OrderController.java")
    with RuntimeStore(store.graph_db_path) as graph:
        graph.bulk_write(
            [
                GraphNode(source_id, "Method", "OrderController.submit", "api", "src/OrderController.java"),
                GraphNode(target_id, "Method", "Assert.notNull", "api", "src/OrderController.java"),
            ],
            [
                GraphEdge(
                    edge_id(source_id, target_id, "CALLS_METHOD"),
                    source_id,
                    target_id,
                    "CALLS_METHOD",
                    0.3,
                    {"resolution_level": "unresolved", "unresolved_reason": "receiver_type_missing", "receiver": "Assert", "receiver_type": ""},
                ),
            ],
        )

    result = summarize_unresolved_java_calls(workspace, sample_limit=1)

    assert result["summary"]["category_counts"] == {"external_or_missing_source": 1}
    assert result["summary"]["reason_counts"] == {"static_receiver_not_indexed": 1}
    assert result["summary"]["receiver_shape_counts"] == {"static_class_receiver": 1}
    assert result["samples"][0]["reason"] == "static_receiver_not_indexed"


def test_unresolved_java_call_report_is_available_from_cli_and_http(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    cli = CliRunner().invoke(
        app,
        ["eval-java-call-resolution-unresolved", "--workspace", str(workspace), "--limit", "0"],
    )

    assert cli.exit_code == 0
    assert json.loads(cli.output)["suite"] == "java_call_resolution_unresolved"

    server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(workspace))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = json.loads(urlopen(
            f"http://127.0.0.1:{server.server_address[1]}/workspace/eval-java-call-resolution-unresolved?limit=0"
        ).read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert response["suite"] == "java_call_resolution_unresolved"
    assert response["summary"]["returned_sample_count"] == 0
