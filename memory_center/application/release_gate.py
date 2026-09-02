from __future__ import annotations

import json
import math
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
        row = {
            "status": str(component.get("status", "unknown")),
            "duration_ms": round(float(metrics.get("duration_ms", 0.0) or 0.0), 3),
            "result_count": max(0, int(metrics.get("result_count", 0) or 0)),
            "quality_score": round(min(1.0, max(0.0, float(metrics.get("quality_score", 0.0) or 0.0))), 4),
        }
        for key in ("cold_duration_ms", "hot_p95_duration_ms"):
            if key in metrics:
                row[key] = round(float(metrics.get(key, 0.0) or 0.0), 3)
        stage_p95 = metrics.get("stage_p95_ms")
        if isinstance(stage_p95, dict):
            row["stage_p95_ms"] = {
                str(stage): round(float(duration or 0.0), 3)
                for stage, duration in sorted(stage_p95.items())
                if isinstance(duration, (int, float))
            }
        portable_components[str(name)] = row
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
        previous_duration = float(baseline_row.get("hot_p95_duration_ms", baseline_row.get("duration_ms", 0.0)) or 0.0)
        current_duration = float(current_row.get("hot_p95_duration_ms", current_row.get("duration_ms", 0.0)) or 0.0)
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
    lookup_contract_cases: str | Path | None = None,
    lookup_contract_baseline: str | Path | None = None,
    lookup_facade_cases: str | Path | None = None,
    lookup_facade_baseline: str | Path | None = None,
    java_call_cases: str | Path | None = None,
    parser_limit: int = 0,
    baseline: dict[str, Any] | str | Path | None = None,
    max_latency_regression_pct: float = 15.0,
    max_quality_drop: float = 0.02,
    query_samples: int = 1,
    max_hot_query_p95_ms: float = 2000.0,
    ontology_paths: list[str] | None = None,
    ontology_full: bool = False,
    cochange_commits: int = 0,
) -> dict[str, Any]:
    """Run a publish-ready index and retrieval gate with optional private suites.

    Returned data intentionally omits source paths, query strings, case ids, and
    result payloads, so the result can safely become a portable baseline.
    """
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    components: dict[str, dict[str, Any]] = {}
    if cochange_commits > 0:
        from memory_center.core.benchmark.cochange import evaluate_git_cochange

        cochange_started = time.perf_counter()
        cochange = evaluate_git_cochange(workspace_file, max_commits=cochange_commits)
        cochange_summary = cochange.get("summary", {}) or {}
        cochange_calibration = cochange.get("calibration", {}) or {}
        cochange_ready = (
            cochange.get("status") == "ready"
            and int(cochange_summary.get("case_count", 0) or 0) > 0
            and cochange.get("temporal_integrity") == "train_commits_strictly_precede_each_evaluation_commit"
            and bool(cochange_calibration.get("eligible"))
        )
        components["cochange_impact"] = _component(
            passed=cochange_ready,
            duration_ms=(time.perf_counter() - cochange_started) * 1000,
            result_count=int(cochange_summary.get("case_count", 0) or 0),
            quality_score=float(cochange_summary.get("mean_recall", 0.0) or 0.0),
            reason="cochange_walk_forward_gate_failed" if not cochange_ready else "",
            extra_metrics={
                "mean_precision": float(cochange_summary.get("mean_precision", 0.0) or 0.0),
                "baseline_mean_precision": float(cochange_summary.get("baseline_mean_precision", 0.0) or 0.0),
                "baseline_mean_recall": float(cochange_summary.get("baseline_mean_recall", 0.0) or 0.0),
                "evaluated_commit_count": int(cochange_summary.get("evaluated_commit_count", 0) or 0),
                "environment_error_count": int(cochange_summary.get("environment_error_count", 0) or 0),
            },
        )
    assertion_index = store.read_json_prefer_backend("assertion-index.json", {}) or {}
    if assertion_index:
        diagnostics = store.memory_backend().assertion_diagnostics(str(assertion_index.get("generation", "") or ""))
        private_fields = 0
        with store.memory_backend().connect() as conn:
            for key in ("source_code", "raw_payload", "tool_payload", "conversation"):
                private_fields += int(conn.execute("SELECT COUNT(*) FROM assertions WHERE payload_json LIKE ?", (f'%\"{key}\"%',)).fetchone()[0])
        ontology_integrity_passed = not diagnostics.get("verified_without_source") and not diagnostics.get("active_old_generation") and private_fields == 0
        components["ontology_integrity"] = _component(
            passed=ontology_integrity_passed,
            duration_ms=0.0,
            result_count=int(diagnostics.get("verified_without_source", 0) or 0) + int(diagnostics.get("active_old_generation", 0) or 0) + private_fields,
            quality_score=1.0 if ontology_integrity_passed else 0.0,
            reason="ontology_integrity_violation" if not ontology_integrity_passed else "",
        )

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
    query_samples = max(1, int(query_samples))
    for query in queries or []:
        samples: list[float] = []
        timing_samples: list[dict[str, float]] = []
        match_count = 0
        for _ in range(query_samples):
            query_started = time.perf_counter()
            payload = memory_query_hybrid(workspace_file, query, limit=10)
            samples.append((time.perf_counter() - query_started) * 1000)
            timings = ((payload.get("retrieval_diagnostics", {}) or {}).get("timing_ms", {}) or {})
            timing_samples.append({
                str(name): float(value)
                for name, value in timings.items()
                if isinstance(value, (int, float))
            })
            match_count = max(match_count, len(payload.get("matches", []) or []))
        query_rows.append({"samples": samples, "timing_samples": timing_samples, "match_count": match_count})
    if query_rows:
        positive = sum(1 for row in query_rows if row["match_count"] > 0)
        cold_samples = [row["samples"][0] for row in query_rows]
        hot_samples = [sample for row in query_rows for sample in row["samples"][1:]] or cold_samples
        stage_samples: dict[str, list[float]] = {}
        for row in query_rows:
            hot_timings = row["timing_samples"][1:] or row["timing_samples"][:1]
            for timings in hot_timings:
                for stage, duration in timings.items():
                    stage_samples.setdefault(stage, []).append(duration)
        stage_p95 = {stage: _percentile(samples, 0.95) for stage, samples in sorted(stage_samples.items())}
        hot_p95 = _percentile(hot_samples, 0.95)
        retrieval_passed = positive == len(query_rows) and (
            max_hot_query_p95_ms <= 0 or hot_p95 <= max_hot_query_p95_ms
        )
        components["retrieval"] = _component(
            passed=retrieval_passed,
            duration_ms=hot_p95,
            result_count=sum(int(row["match_count"]) for row in query_rows),
            quality_score=positive / len(query_rows),
            reason=(
                "query_returned_no_matches" if positive != len(query_rows)
                else "hot_query_p95_budget_exceeded" if max_hot_query_p95_ms > 0 and hot_p95 > max_hot_query_p95_ms
                else ""
            ),
            extra_metrics={
                "cold_duration_ms": _percentile(cold_samples, 0.95),
                "hot_p95_duration_ms": hot_p95,
                "query_samples": query_samples,
                "max_hot_query_p95_ms": max_hot_query_p95_ms,
                "stage_p95_ms": stage_p95,
            },
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

    if lookup_contract_cases:
        from memory_center.core.benchmark.lookup_contract import evaluate_lookup_contract

        lookup_started = time.perf_counter()
        lookup_contract = evaluate_lookup_contract(
            workspace_file, lookup_contract_cases, baseline_file=lookup_contract_baseline,
        )
        changed_ids = list(lookup_contract.get("changed_case_ids", []) or [])
        baseline_status = str(lookup_contract.get("baseline_status", "") or "")
        if baseline_status == "no_baseline":
            components["lookup_contract"] = {
                "status": "attention", "passed": None, "reason": "lookup_contract_baseline_missing",
                "metrics": {"duration_ms": round((time.perf_counter() - lookup_started) * 1000, 3),
                            "result_count": int(lookup_contract.get("case_count", 0) or 0), "quality_score": 1.0,
                            "changed_case_count": 0, "changed_case_ids": []},
            }
        else:
            components["lookup_contract"] = _component(
                passed=not changed_ids,
                duration_ms=(time.perf_counter() - lookup_started) * 1000,
                result_count=int(lookup_contract.get("case_count", 0) or 0),
                quality_score=1.0 if not changed_ids else 0.0,
                reason="lookup_contract_drift" if changed_ids else "",
                extra_metrics={"changed_case_count": len(changed_ids), "changed_case_ids": changed_ids},
            )
    else:
        components["lookup_contract"] = _skipped("no_lookup_contract_cases_provided")

    if lookup_facade_cases:
        from memory_center.core.benchmark.lookup_contract import evaluate_live_lookup_facades

        facade_started = time.perf_counter()
        facade = evaluate_live_lookup_facades(workspace_file, lookup_facade_cases, baseline_file=lookup_facade_baseline)
        mismatches = list(facade.get("mismatched_case_ids", []) or [])
        session_failures = list(facade.get("session_failure_case_ids", []) or [])
        baseline_changes = list(facade.get("changed_case_ids", []) or [])
        components["lookup_facades"] = _component(
            passed=not mismatches and not session_failures and not baseline_changes,
            duration_ms=(time.perf_counter() - facade_started) * 1000,
            result_count=int(facade.get("case_count", 0) or 0),
            quality_score=1.0 if not mismatches and not session_failures and not baseline_changes else 0.0,
            reason="lookup_facade_baseline_drift" if baseline_changes else "lookup_session_contract_drift" if session_failures else "lookup_facade_contract_drift" if mismatches else "",
            extra_metrics={"mismatched_case_count": len(mismatches), "mismatched_case_ids": mismatches,
                           "facades": list(facade.get("facades", []) or [])},
        )
    else:
        components["lookup_facades"] = _skipped("no_lookup_facade_cases_provided")

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
            quality_score=min(
                float(summary.get("edge_recall", 0.0) or 0.0),
                float(summary.get("resolution_level_rate", 1.0) or 0.0),
            ),
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


def _component(
    *,
    passed: bool,
    duration_ms: float,
    result_count: int,
    quality_score: float,
    reason: str = "",
    extra_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    if extra_metrics:
        row["metrics"].update(extra_metrics)
    return row


def _skipped(reason: str) -> dict[str, Any]:
    return {"status": "skipped", "passed": None, "reason": reason, "metrics": {}}


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(max(0.0, float(value)) for value in values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]
