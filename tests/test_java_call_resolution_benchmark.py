from __future__ import annotations

from pathlib import Path

import yaml

from memory_center.core.benchmark.java_call_resolution import (
    load_java_call_resolution_cases,
    run_java_call_resolution_suite,
)
from memory_center.core.graph import GraphEdge, GraphNode, GraphStore, edge_id, node_id
from memory_center.core.store import WorkspaceStore


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
    noise_id = node_id("Method", "AuditService.record", "api", "AuditService.java")
    with GraphStore(store.graph_db_path) as graph:
        graph.bulk_write(
            [
                GraphNode(source_id, "Method", "OrderController.submit", "api", "OrderController.java"),
                GraphNode(target_id, "Method", "OrderService.submit", "api", "OrderService.java"),
                GraphNode(noise_id, "Method", "AuditService.record", "api", "AuditService.java"),
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
                    edge_id(source_id, noise_id, "CALLS_METHOD"),
                    source_id,
                    noise_id,
                    "CALLS_METHOD",
                    confidence=0.4,
                    metadata={"resolution_level": "unresolved"},
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
        }],
    )

    result = run_java_call_resolution_suite(workspace, cases)

    assert result["summary"]["passed"] is True
    assert result["summary"]["edge_recall"] == 1.0
    assert result["summary"]["high_confidence_expected_rate"] == 1.0
    assert result["cases"][0]["matched_edge"]["target"] == "OrderService#submit"


def test_java_call_resolution_suite_reports_unresolved_missing_target(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)
    source_id = node_id("Method", "OrderController.submit", "api", "OrderController.java")
    unresolved_id = node_id("Method", "UnknownService.submit", "api", "OrderController.java")
    with GraphStore(store.graph_db_path) as graph:
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
