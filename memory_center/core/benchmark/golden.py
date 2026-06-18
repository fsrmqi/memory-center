from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable

import yaml

from .models import GoldenCase


CaseRunner = Callable[[GoldenCase], Dict[str, Any]]


def load_golden_cases(cases_file: str | Path) -> list[GoldenCase]:
    path = Path(cases_file).expanduser().resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if set(data) - {"cases", "schema_version"}:
        raise ValueError("golden suite only supports schema_version and cases")
    rows = data.get("cases", [])
    if not isinstance(rows, list):
        raise ValueError("cases must be a list")
    cases = [GoldenCase.from_mapping(row) for row in rows if isinstance(row, dict)]
    if not cases:
        raise ValueError("golden suite requires at least one case")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("golden case_id values must be unique")
    return cases


def score_golden_case(
    *,
    expected_anchors: Iterable[str],
    actual_anchors: Iterable[str],
    forbidden_anchors: Iterable[str] = (),
    expected_edges: Iterable[str] = (),
    actual_edges: Iterable[str] = (),
    latency_ms: float = 0.0,
    max_latency_ms: float = 5000.0,
) -> Dict[str, Any]:
    expected_anchor_set = set(expected_anchors)
    actual_anchor_set = set(actual_anchors)
    expected_edge_set = set(expected_edges)
    actual_edge_set = set(actual_edges)
    forbidden = set(forbidden_anchors)
    anchor_hits = expected_anchor_set & actual_anchor_set
    edge_hits = expected_edge_set & actual_edge_set
    forbidden_hits = forbidden & actual_anchor_set
    anchor_recall = len(anchor_hits) / len(expected_anchor_set) if expected_anchor_set else 1.0
    edge_recall = len(edge_hits) / len(expected_edge_set) if expected_edge_set else 1.0
    latency_passed = latency_ms <= max_latency_ms
    passed = anchor_recall == 1.0 and edge_recall == 1.0 and not forbidden_hits and latency_passed
    return {
        "anchor_recall": round(anchor_recall, 4),
        "edge_recall": round(edge_recall, 4),
        "anchor_hits": sorted(anchor_hits),
        "missing_anchors": sorted(expected_anchor_set - actual_anchor_set),
        "edge_hits": sorted(edge_hits),
        "missing_edges": sorted(expected_edge_set - actual_edge_set),
        "forbidden_hits": sorted(forbidden_hits),
        "forbidden_hit_count": len(forbidden_hits),
        "latency_passed": latency_passed,
        "passed": passed,
    }


def _canonical_anchor(class_name: Any, method_name: Any) -> str:
    cls = str(class_name or "").strip()
    method = str(method_name or "").strip()
    return f"{cls}#{method}" if cls and method else ""


def _anchor_from_name(name: Any, node_type: Any = "") -> str:
    text = str(name or "").strip()
    if not text or "/" in text or "\\" in text:
        return ""
    if "#" in text:
        return text
    if str(node_type or "").strip() in {"Method", "FeignMethod"} and "." in text:
        owner, method = text.rsplit(".", 1)
        simple_owner = owner.rsplit(".", 1)[-1].strip()
        return _canonical_anchor(simple_owner, method)
    return ""


def extract_logical_evidence(payload: Any) -> Dict[str, list[str]]:
    anchors: set[str] = set()
    edges: set[str] = set()
    continuation_edges = {
        "same_class_method_continuations": "CALLS_METHOD",
        "local_service_continuations": "CALLS_METHOD",
        "feign_continuations": "IMPLEMENTS_FEIGN",
        "server_walkthroughs": "HANDLES_ENDPOINT",
        "service_impl_continuations": "CALLS_METHOD",
    }

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            anchor = _canonical_anchor(
                value.get("class") or value.get("controller") or value.get("interface") or value.get("owner_class"),
                value.get("method") or value.get("method_name") or value.get("owner_method"),
            )
            if anchor:
                anchors.add(anchor)
            node = value.get("node")
            if isinstance(node, dict):
                visit(node)
            inline_anchor = _anchor_from_name(value.get("name"), value.get("type"))
            if inline_anchor:
                anchors.add(inline_anchor)
            edge_type = str(value.get("type", "") or "")
            if edge_type and edge_type.upper() == edge_type and "_" in edge_type:
                edges.add(edge_type)
            for key, nested in value.items():
                if key not in {"absolute_file_path", "file_path", "source", "snippet", "raw"}:
                    inferred_edge = continuation_edges.get(key)
                    if inferred_edge and nested:
                        edges.add(inferred_edge)
                    visit(nested)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(payload)
    return {"anchors": sorted(anchors), "edges": sorted(edges)}


def _default_case_runner(workspace_file: str | Path) -> CaseRunner:
    def run(case: GoldenCase) -> Dict[str, Any]:
        if case.mode == "walkthrough":
            from ..orchestrator import memory_method_walkthrough

            payload = memory_method_walkthrough(
                workspace_file,
                case.query,
                depth=6,
                limit=160,
                view="full",
                budget="large",
                report_level="deep",
            )
        else:
            from ..orchestrator import memory_query_hybrid

            payload = memory_query_hybrid(workspace_file, case.query, limit=80)
        evidence = extract_logical_evidence(payload)
        return {**evidence, "payload": payload}

    return run


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return round(float(ordered[index]), 3)


def run_golden_suite(
    workspace_file: str | Path,
    cases_file: str | Path,
    *,
    case_runner: CaseRunner | None = None,
) -> Dict[str, Any]:
    cases = load_golden_cases(cases_file)
    runner = case_runner or _default_case_runner(workspace_file)
    case_results: list[Dict[str, Any]] = []
    latencies: list[float] = []
    token_estimate = 0
    for case in cases:
        started = time.perf_counter()
        execution = runner(case)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        latencies.append(latency_ms)
        anchors = list(execution.get("anchors", []) or [])
        edges = list(execution.get("edges", []) or [])
        token_estimate += max(1, len(json.dumps(execution.get("payload", {}), ensure_ascii=False, default=str)) // 4)
        score = score_golden_case(
            expected_anchors=case.expected_anchors,
            actual_anchors=anchors,
            forbidden_anchors=case.forbidden_anchors,
            expected_edges=case.expected_edges,
            actual_edges=edges,
            latency_ms=latency_ms,
            max_latency_ms=case.max_latency_ms,
        )
        case_results.append({
            "case_id": case.case_id,
            "mode": case.mode,
            "actual_anchors": anchors,
            "actual_edges": edges,
            "latency_ms": latency_ms,
            **score,
        })
    anchor_recall = sum(row["anchor_recall"] for row in case_results) / len(case_results)
    edge_recall = sum(row["edge_recall"] for row in case_results) / len(case_results)
    forbidden_count = sum(row["forbidden_hit_count"] for row in case_results)
    forbidden_total = sum(len(case.forbidden_anchors) for case in cases)
    forbidden_rate = forbidden_count / forbidden_total if forbidden_total else 0.0
    summary = {
        "case_count": len(cases),
        "passed_cases": sum(1 for row in case_results if row["passed"]),
        "anchor_recall": round(anchor_recall, 4),
        "edge_recall": round(edge_recall, 4),
        "forbidden_hit_rate": round(forbidden_rate, 4),
        "passed": anchor_recall >= 0.90 and edge_recall >= 0.85 and forbidden_rate == 0.0,
    }
    return {
        "schema_version": 1,
        "summary": summary,
        "performance": {
            "median_latency_ms": round(float(statistics.median(latencies)), 3),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "token_estimate": token_estimate,
        },
        "cases": case_results,
    }
