from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.application.golden import run_golden_suite
from memory_center.core.contracting.runtime import RUNTIME_SAMPLES_FILE, runtime_contract_compatibility
from memory_center.core.contracting.static import CONTRACT_DIFF_FILE, CONTRACT_SNAPSHOT_FILE, contract_semantic_report
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.orchestrator import (
    memory_eval_java_call_resolution,
    memory_eval_parser_benchmark,
    memory_query_hybrid,
)
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


def load_release_gate_baseline(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("release gate baseline must be a schema_version=1 JSON object")
    return data


def build_release_gate_baseline(result: dict[str, Any], *, label: str = "current") -> dict[str, Any]:
    """Extract portable release metrics without queries, paths, cases, or payloads."""
    components = result.get("components", {}) or {}
    portable_components: dict[str, dict[str, Any]] = {}
    for name, component in components.items():
        if component.get("status") == "skipped":
            continue
        metrics = component.get("metrics", {}) or {}
        portable_components[str(name)] = {
            "status": str(component.get("status", "unknown")),
            "duration_ms": round(float(metrics.get("duration_ms", 0.0) or 0.0), 3),
            "result_count": max(0, int(metrics.get("result_count", 0) or 0)),
            "quality_score": round(min(1.0, max(0.0, float(metrics.get("quality_score", 0.0) or 0.0))), 4),
        }
    return {
        "schema_version": 1,
        "label": str(label or "current"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "components": portable_components,
    }


def save_release_gate_baseline(
    result: dict[str, Any], output_file: str | Path, *, label: str = "current"
) -> dict[str, Any]:
    baseline = build_release_gate_baseline(result, label=label)
    path = Path(output_file).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"saved": True, "baseline_file": str(path), "baseline": baseline}


def compare_release_gate_baseline(
    result: dict[str, Any],
    *,
    baseline: dict[str, Any] | None,
    max_latency_regression_pct: float = 15.0,
    max_quality_drop: float = 0.02,
) -> dict[str, Any]:
    if not baseline:
        return {"status": "baseline_missing", "passed": None, "components": {}}
    current = build_release_gate_baseline(result)
    comparisons: dict[str, dict[str, Any]] = {}
    for name, current_row in current["components"].items():
        baseline_row = (baseline.get("components", {}) or {}).get(name)
        if not baseline_row:
            comparisons[name] = {"status": "baseline_missing", "passed": None}
            continue
        previous_duration = float(baseline_row.get("duration_ms", 0.0) or 0.0)
        current_duration = float(current_row.get("duration_ms", 0.0) or 0.0)
        latency_change = (
            ((current_duration - previous_duration) / previous_duration * 100.0)
            if previous_duration > 0
            else 0.0
        )
        quality_drop = float(baseline_row.get("quality_score", 0.0) or 0.0) - float(
            current_row.get("quality_score", 0.0) or 0.0
        )
        passed = latency_change <= max_latency_regression_pct and quality_drop <= max_quality_drop
        comparisons[name] = {
            "status": "pass" if passed else "fail",
            "passed": passed,
            "latency_change_pct": round(latency_change, 2),
            "quality_drop": round(quality_drop, 4),
        }
    failures = [name for name, row in comparisons.items() if row.get("passed") is False]
    return {
        "status": "pass" if not failures else "fail",
        "passed": not failures,
        "baseline_label": str(baseline.get("label", "")),
        "thresholds": {
            "max_latency_regression_pct": max_latency_regression_pct,
            "max_quality_drop": max_quality_drop,
        },
        "components": comparisons,
    }


def run_release_gate(
    workspace_file: str | Path,
    *,
    queries: list[str] | None = None,
    golden_cases: str | Path | None = None,
    java_call_cases: str | Path | None = None,
    parser_limit: int = 0,
    baseline: dict[str, Any] | str | Path | None = None,
    max_latency_regression_pct: float = 15.0,
    max_quality_drop: float = 0.02,
    ontology_paths: list[str] | None = None,
    ontology_full: bool = False,
) -> dict[str, Any]:
    """Run a publish-ready index and retrieval gate with optional private suites.

    Returned data intentionally omits source paths, query strings, case ids, and
    result payloads, so the result can safely become a portable baseline.
    """
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    components: dict[str, dict[str, Any]] = {}

    if ontology_paths or ontology_full:
        from memory_center.core.knowledge.benchmark import evaluate_assertion_reindex_gate, evaluate_ontology_hot_path

        ontology_started = time.perf_counter()
        hot = evaluate_ontology_hot_path(str(workspace_file))
        reindex_gate = evaluate_assertion_reindex_gate(
            str(workspace_file), paths=ontology_paths, full=ontology_full
        )
        ontology_passed = bool(hot["passed"]) and bool(reindex_gate["passed"])
        components["ontology_performance"] = _component(
            passed=ontology_passed,
            duration_ms=(time.perf_counter() - ontology_started) * 1000,
            result_count=int(reindex_gate.get("written_assertions", 0) or 0),
            quality_score=1.0 if ontology_passed else 0.0,
            reason="ontology_budget_exceeded" if not ontology_passed else "",
        )

    started = time.perf_counter()
    counts = reindex_workspace(config, store)
    reindex_duration = (time.perf_counter() - started) * 1000
    indexed = int(counts.get("files", 0) or 0)
    components["reindex"] = _component(
        passed=indexed > 0,
        duration_ms=reindex_duration,
        result_count=indexed,
        quality_score=1.0 if indexed > 0 else 0.0,
        reason="indexed_files_missing" if indexed <= 0 else "",
    )
    contract_snapshot = store.read_json_prefer_backend(CONTRACT_SNAPSHOT_FILE, {})
    if contract_snapshot:
        contract_report = contract_semantic_report(
            contract_snapshot,
            store.read_json_prefer_backend(CONTRACT_DIFF_FILE, {}),
            store.read_json_prefer_backend("service-topology.json", {}),
        )
        contract_blocking = len(contract_report.get("breaking_changes", []) or [])
        components["contract_compatibility"] = _component(
            passed=contract_report.get("status") != "block",
            duration_ms=0.0,
            result_count=contract_blocking,
            quality_score=1.0 if contract_report.get("status") == "pass" else 0.7 if contract_report.get("status") == "attention" else 0.0,
            reason="breaking_contract_change" if contract_report.get("status") == "block" else "",
        )
    runtime_samples = store.read_jsonl_prefer_backend(RUNTIME_SAMPLES_FILE, limit=1)
    if runtime_samples:
        runtime_report = runtime_contract_compatibility(workspace_file)
        runtime_blocks = len([item for item in runtime_report.get("breaking_runtime_findings", []) if item.get("status") == "block"])
        components["runtime_contract_compatibility"] = _component(
            passed=runtime_report.get("status") != "block",
            duration_ms=0.0,
            result_count=runtime_blocks,
            quality_score=1.0 if runtime_report.get("status") == "pass" else 0.7 if runtime_report.get("status") == "attention" else 0.0,
            reason="active_runtime_contract_break" if runtime_report.get("status") == "block" else "",
        )

    query_rows: list[dict[str, Any]] = []
    for query in queries or []:
        query_started = time.perf_counter()
        payload = memory_query_hybrid(workspace_file, query, limit=10)
        duration_ms = (time.perf_counter() - query_started) * 1000
        matches = payload.get("matches", []) or []
        query_rows.append({"duration_ms": duration_ms, "match_count": len(matches)})
    if query_rows:
        positive = sum(1 for row in query_rows if row["match_count"] > 0)
        components["retrieval"] = _component(
            passed=positive == len(query_rows),
            duration_ms=sum(row["duration_ms"] for row in query_rows) / len(query_rows),
            result_count=sum(int(row["match_count"]) for row in query_rows),
            quality_score=positive / len(query_rows),
            reason="query_returned_no_matches" if positive != len(query_rows) else "",
        )
    else:
        components["retrieval"] = _skipped("no_queries_provided")

    if golden_cases:
        golden_started = time.perf_counter()
        golden = run_golden_suite(workspace_file, golden_cases)
        components["golden"] = _component(
            passed=bool((golden.get("summary", {}) or {}).get("passed")),
            duration_ms=(time.perf_counter() - golden_started) * 1000,
            result_count=int((golden.get("summary", {}) or {}).get("case_count", 0) or 0),
            quality_score=float((golden.get("summary", {}) or {}).get("anchor_recall", 0.0) or 0.0),
        )
    else:
        components["golden"] = _skipped("no_golden_cases_provided")

    if java_call_cases:
        java_started = time.perf_counter()
        java_gate = memory_eval_java_call_resolution(
            workspace_file,
            java_call_cases,
            fail_on_forbidden_high_confidence=True,
        )
        summary = java_gate.get("summary", {}) or {}
        components["java_call_resolution"] = _component(
            passed=bool(summary.get("passed")),
            duration_ms=(time.perf_counter() - java_started) * 1000,
            result_count=int(summary.get("case_count", 0) or 0),
            quality_score=float(summary.get("edge_recall", 0.0) or 0.0),
        )
    else:
        components["java_call_resolution"] = _skipped("no_java_call_cases_provided")

    if parser_limit > 0:
        parser_started = time.perf_counter()
        parser = memory_eval_parser_benchmark(workspace_file, limit=parser_limit, max_findings=0)
        parser_score = float(parser.get("score", 0.0) or 0.0) / 100.0
        parser_passed = parser.get("quality") in {"high", "medium"}
        components["parser_precision"] = _component(
            passed=parser_passed,
            duration_ms=(time.perf_counter() - parser_started) * 1000,
            result_count=int(parser.get("files_scanned", 0) or 0),
            quality_score=parser_score,
            reason="parser_quality_insufficient" if not parser_passed else "",
        )
    else:
        components["parser_precision"] = _skipped("parser_benchmark_disabled")

    if isinstance(baseline, (str, Path)):
        baseline_data = load_release_gate_baseline(baseline)
    else:
        baseline_data = baseline
    provisional = {"schema_version": 1, "components": components}
    baseline_gate = compare_release_gate_baseline(
        provisional,
        baseline=baseline_data,
        max_latency_regression_pct=max_latency_regression_pct,
        max_quality_drop=max_quality_drop,
    )
    failed_components = [name for name, component in components.items() if component.get("passed") is False]
    passed = not failed_components and baseline_gate.get("passed") is not False
    return {
        "schema_version": 1,
        "suite": "release_gate",
        "status": "pass" if passed else "fail",
        "passed": passed,
        "failed_components": failed_components,
        "components": components,
        "baseline_gate": baseline_gate,
    }


def _component(*, passed: bool, duration_ms: float, result_count: int, quality_score: float, reason: str = "") -> dict[str, Any]:
    row = {
        "status": "pass" if passed else "fail",
        "passed": passed,
        "metrics": {
            "duration_ms": round(max(0.0, duration_ms), 3),
            "result_count": max(0, int(result_count)),
            "quality_score": round(min(1.0, max(0.0, quality_score)), 4),
        },
    }
    if reason:
        row["reason"] = reason
    return row


def _skipped(reason: str) -> dict[str, Any]:
    return {"status": "skipped", "passed": None, "reason": reason, "metrics": {}}
