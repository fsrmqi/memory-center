from __future__ import annotations

import json
import re
import statistics
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .models import GoldenCase

CaseRunner = Callable[[GoldenCase], dict[str, Any]]


_INVALID_SEARCH_TOOL_RE = re.compile(r"\b(find|grep(?:\s+-l)?|rg\s+--files|sed\s+-n|idea\s+search)\b", re.I)
_NEGATED_SEARCH_HINTS = (
    "do_not",
    "avoid",
    "anti-pattern",
    "anti_patterns",
    "不需要",
    "不要",
    "避免",
    "无需",
    "禁止",
    "直接读",
    "directly",
    "instead of",
    "rather than",
)


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


def load_golden_performance_baseline(path: str | Path) -> dict[str, Any]:
    baseline_path = Path(path).expanduser().resolve()
    data = json.loads(baseline_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("golden performance baseline must be a JSON object")
    return data


def build_golden_performance_baseline(result: dict[str, Any], *, label: str = "current") -> dict[str, Any]:
    summary = result.get("summary", {}) or {}
    performance = result.get("performance", {}) or {}
    return {
        "schema_version": 1,
        "label": str(label or "current"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "case_count": int(summary.get("case_count", 0) or 0),
            "anchor_recall": float(summary.get("anchor_recall", 0.0) or 0.0),
            "edge_recall": float(summary.get("edge_recall", 0.0) or 0.0),
            "forbidden_hit_rate": float(summary.get("forbidden_hit_rate", 0.0) or 0.0),
            "agent_invalid_search_suggestion_count": int(summary.get("agent_invalid_search_suggestion_count", 0) or 0),
            "agent_invalid_search_reduction_rate": float(summary.get("agent_invalid_search_reduction_rate", 0.0) or 0.0),
        },
        "performance": {
            "median_latency_ms": float(performance.get("median_latency_ms", 0.0) or 0.0),
            "p95_latency_ms": float(performance.get("p95_latency_ms", 0.0) or 0.0),
            "token_estimate": int(performance.get("token_estimate", 0) or 0),
        },
    }


def _improvement_pct(baseline_value: float, current_value: float) -> float:
    if baseline_value <= 0:
        return 0.0
    return round((baseline_value - current_value) / baseline_value * 100.0, 2)


def compare_golden_performance(
    current_result: dict[str, Any],
    *,
    baseline: dict[str, Any] | None,
    latency_improvement_threshold_pct: float = -10.0,
    token_improvement_threshold_pct: float = 0.0,
) -> dict[str, Any]:
    current_baseline = build_golden_performance_baseline(current_result, label="current")
    if not baseline:
        return {
            "status": "baseline_missing",
            "passed": None,
            "reason": "No Golden performance baseline was provided.",
            "current_baseline": current_baseline,
            "required": {
                "latency_improvement_pct": latency_improvement_threshold_pct,
                "token_improvement_pct": token_improvement_threshold_pct,
            },
        }

    baseline_perf = baseline.get("performance", {}) or {}
    current_perf = current_baseline["performance"]
    base_latency = float(baseline_perf.get("median_latency_ms", 0.0) or 0.0)
    base_tokens = float(baseline_perf.get("token_estimate", 0.0) or 0.0)
    current_latency = float(current_perf.get("median_latency_ms", 0.0) or 0.0)
    current_tokens = float(current_perf.get("token_estimate", 0.0) or 0.0)
    latency_improvement = _improvement_pct(base_latency, current_latency)
    token_improvement = _improvement_pct(base_tokens, current_tokens)
    latency_passed = latency_improvement >= latency_improvement_threshold_pct
    token_passed = token_improvement >= token_improvement_threshold_pct
    return {
        "status": "pass" if latency_passed and token_passed else "fail",
        "passed": latency_passed and token_passed,
        "baseline_label": baseline.get("label", ""),
        "current_baseline": current_baseline,
        "latency": {
            "baseline_median_ms": base_latency,
            "current_median_ms": current_latency,
            "improvement_pct": latency_improvement,
            "threshold_pct": latency_improvement_threshold_pct,
            "passed": latency_passed,
        },
        "token": {
            "baseline_token_estimate": int(base_tokens),
            "current_token_estimate": int(current_tokens),
            "improvement_pct": token_improvement,
            "threshold_pct": token_improvement_threshold_pct,
            "passed": token_passed,
        },
    }


def score_golden_case(
    *,
    expected_anchors: Iterable[str],
    actual_anchors: Iterable[str],
    forbidden_anchors: Iterable[str] = (),
    expected_edges: Iterable[str] = (),
    actual_edges: Iterable[str] = (),
    latency_ms: float = 0.0,
    max_latency_ms: float = 5000.0,
) -> dict[str, Any]:
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


def _agent_guidance_strings(payload: Any) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                visit(nested, f"{path}.{key}" if path else str(key))
        elif isinstance(value, (list, tuple)):
            for index, nested in enumerate(value):
                visit(nested, f"{path}[{index}]")
        elif isinstance(value, str):
            items.append((path, value.strip()))

    guidance_roots = {
        "next_actions",
        "agent_usage_policy",
        "anti_patterns",
        "completion_status",
        "limitations",
        "summary_lines",
        "answer_markdown",
    }
    if isinstance(payload, dict):
        for key in guidance_roots:
            if key in payload:
                visit(payload[key], key)
    else:
        visit(payload, "")
    return [(path, text) for path, text in items if text]


def _is_negated_search_guidance(path: str, text: str) -> bool:
    haystack = f"{path} {text}".lower()
    return any(token in haystack for token in _NEGATED_SEARCH_HINTS)


def evaluate_agent_guidance(payload: Any) -> dict[str, Any]:
    """Score whether agent-facing output still encourages unnecessary repo search."""

    invalid: list[str] = []
    search_reference_count = 0
    for path, text in _agent_guidance_strings(payload):
        if not _INVALID_SEARCH_TOOL_RE.search(text):
            continue
        search_reference_count += 1
        if _is_negated_search_guidance(path, text):
            continue
        invalid.append(f"{path}: {text}")

    completion = payload.get("completion_status", {}) if isinstance(payload, dict) else {}
    policy = payload.get("agent_usage_policy", {}) if isinstance(payload, dict) else {}
    completion_stop_signal = (
        isinstance(completion, dict)
        and completion.get("state") == "complete"
        and completion.get("recommended_action") == "use_current_evidence"
    )
    policy_stop_signal = isinstance(policy, dict) and bool(policy.get("do_not_search_when_absolute_path_present"))
    valid_stop_signal = completion_stop_signal or policy_stop_signal
    reduction_rate = 1.0 if valid_stop_signal and not invalid else 0.0
    return {
        "completion_stop_signal": completion_stop_signal,
        "policy_stop_signal": policy_stop_signal,
        "search_reference_count": search_reference_count,
        "invalid_search_suggestion_count": len(invalid),
        "invalid_search_suggestions": invalid,
        "invalid_search_reduction_rate": reduction_rate,
        "passed": len(invalid) == 0 and reduction_rate >= 0.5,
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


def extract_logical_evidence(payload: Any) -> dict[str, list[str]]:
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
    def run(case: GoldenCase) -> dict[str, Any]:
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
    performance_baseline: dict[str, Any] | str | Path | None = None,
) -> dict[str, Any]:
    cases = load_golden_cases(cases_file)
    runner = case_runner or _default_case_runner(workspace_file)
    case_results: list[dict[str, Any]] = []
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
        agent_guidance = evaluate_agent_guidance(execution.get("payload", {}))
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
            "agent_guidance": agent_guidance,
            **score,
        })
    anchor_recall = sum(row["anchor_recall"] for row in case_results) / len(case_results)
    edge_recall = sum(row["edge_recall"] for row in case_results) / len(case_results)
    forbidden_count = sum(row["forbidden_hit_count"] for row in case_results)
    forbidden_total = sum(len(case.forbidden_anchors) for case in cases)
    forbidden_rate = forbidden_count / forbidden_total if forbidden_total else 0.0
    invalid_search_count = sum(row["agent_guidance"]["invalid_search_suggestion_count"] for row in case_results)
    reduction_rates = [row["agent_guidance"]["invalid_search_reduction_rate"] for row in case_results]
    invalid_search_reduction_rate = sum(reduction_rates) / len(reduction_rates) if reduction_rates else 1.0
    summary = {
        "case_count": len(cases),
        "passed_cases": sum(1 for row in case_results if row["passed"]),
        "anchor_recall": round(anchor_recall, 4),
        "edge_recall": round(edge_recall, 4),
        "forbidden_hit_rate": round(forbidden_rate, 4),
        "agent_invalid_search_suggestion_count": invalid_search_count,
        "agent_invalid_search_reduction_rate": round(invalid_search_reduction_rate, 4),
        "passed": (
            anchor_recall >= 0.90
            and edge_recall >= 0.85
            and forbidden_rate == 0.0
            and invalid_search_count == 0
            and invalid_search_reduction_rate >= 0.5
        ),
    }
    result = {
        "schema_version": 1,
        "summary": summary,
        "performance": {
            "median_latency_ms": round(float(statistics.median(latencies)), 3),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "token_estimate": token_estimate,
        },
        "cases": case_results,
    }
    if isinstance(performance_baseline, (str, Path)):
        baseline = load_golden_performance_baseline(performance_baseline)
    else:
        baseline = performance_baseline
    result["performance_gate"] = compare_golden_performance(result, baseline=baseline)
    return result
