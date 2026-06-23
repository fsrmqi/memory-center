#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

export MEMORY_CENTER_REAL_WORKSPACE="${MEMORY_CENTER_REAL_WORKSPACE:-/Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml}"
export MEMORY_CENTER_REAL_CASES="${MEMORY_CENTER_REAL_CASES:-/Users/cuijiaqi/javaworkspace/ucap/.memory-center/golden/cases.yaml}"
export MEMORY_CENTER_REAL_BASELINE="${MEMORY_CENTER_REAL_BASELINE:-/Users/cuijiaqi/javaworkspace/ucap/.memory-center/golden/performance-baseline.json}"
export MEMORY_CENTER_SAVE_REAL_BASELINE="${MEMORY_CENTER_SAVE_REAL_BASELINE:-0}"
export MEMORY_CENTER_REAL_QUERY="${MEMORY_CENTER_REAL_QUERY:-梳理下 cn.kaipuyun.cloud.openapi.biz.service.impl.website.safe.WebsiteInfoLeakageMasterServiceImpl#listByDto 全链路 一直到最底层的逻辑处理}"
export MEMORY_CENTER_REAL_PROJECT="${MEMORY_CENTER_REAL_PROJECT:-}"

python3 - <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from memory_center.core.benchmark.golden import build_golden_performance_baseline, run_golden_suite
from memory_center.core.orchestrator import memory_query_hybrid
from memory_center.core.validators import doctor


workspace = Path(os.environ["MEMORY_CENTER_REAL_WORKSPACE"]).expanduser()
cases = Path(os.environ["MEMORY_CENTER_REAL_CASES"]).expanduser()
baseline_path = Path(os.environ["MEMORY_CENTER_REAL_BASELINE"]).expanduser()
save_baseline = os.environ.get("MEMORY_CENTER_SAVE_REAL_BASELINE", "0") == "1"
query = os.environ["MEMORY_CENTER_REAL_QUERY"]
project = os.environ.get("MEMORY_CENTER_REAL_PROJECT", "")


def emit(payload: dict[str, Any], *, code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    raise SystemExit(code)


missing = []
if not workspace.exists():
    missing.append({"kind": "workspace", "status": "real_case_missing"})
if not cases.exists():
    missing.append({"kind": "golden_cases", "status": "real_case_missing"})
if missing:
    emit(
        {
            "scenario": "ucap-real",
            "passed": False,
            "status": "real_case_missing",
            "missing": missing,
            "hint": "Set MEMORY_CENTER_REAL_WORKSPACE and MEMORY_CENTER_REAL_CASES to the real validation files.",
        },
        code=2,
    )

try:
    doctor_result = doctor(workspace, self_test=True)
    golden = run_golden_suite(workspace, cases, performance_baseline=baseline_path if baseline_path.exists() else None)
    if save_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline = build_golden_performance_baseline(golden, label="v3.5.7-real-ucap")
        baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        golden["performance_gate"] = {
            "status": "baseline_saved",
            "passed": True,
            "baseline_path": str(baseline_path),
            "current_baseline": baseline,
        }
    walkthrough = memory_query_hybrid(workspace, query, limit=20, project=project)
except Exception as exc:
    emit(
        {
            "scenario": "ucap-real",
            "passed": False,
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        },
        code=1,
    )

failed_checks = [item.get("name", "") for item in doctor_result.get("checks", []) if not item.get("ok")]
golden_summary = golden.get("summary", {}) or {}
golden_performance = golden.get("performance", {}) or {}
performance_gate = golden.get("performance_gate", {}) or {}
performance_gate_passed = performance_gate.get("passed")
completion_status = walkthrough.get("completion_status", {}) or {}
target = walkthrough.get("target", {}) or {}

payload = {
    "scenario": "ucap-real",
    "passed": bool(
        doctor_result.get("ok")
        and golden_summary.get("passed")
        and (performance_gate_passed is not False)
        and walkthrough.get("found")
        and completion_status.get("state") == "complete"
    ),
    "doctor": {
        "ok": bool(doctor_result.get("ok")),
        "check_count": len(doctor_result.get("checks", []) or []),
        "failed_checks": failed_checks,
        "self_test": doctor_result.get("self_test"),
    },
    "golden": {
        "case_count": golden_summary.get("case_count"),
        "passed": golden_summary.get("passed"),
        "anchor_recall": golden_summary.get("anchor_recall"),
        "edge_recall": golden_summary.get("edge_recall"),
        "forbidden_hit_rate": golden_summary.get("forbidden_hit_rate"),
        "agent_invalid_search_suggestion_count": golden_summary.get("agent_invalid_search_suggestion_count"),
        "agent_invalid_search_reduction_rate": golden_summary.get("agent_invalid_search_reduction_rate"),
        "median_latency_ms": golden_performance.get("median_latency_ms"),
        "p95_latency_ms": golden_performance.get("p95_latency_ms"),
        "token_estimate": golden_performance.get("token_estimate"),
        "performance_gate_status": performance_gate.get("status"),
        "performance_gate_passed": performance_gate.get("passed"),
        "baseline_configured": baseline_path.exists(),
    },
    "walkthrough": {
        "mode_used": walkthrough.get("mode_used"),
        "found": bool(walkthrough.get("found")),
        "target": {
            "project": target.get("project"),
            "class": target.get("class"),
            "method": target.get("method"),
        },
        "completion_status": completion_status,
        "summary_line_count": len(walkthrough.get("summary_lines", []) or []),
        "has_answer_markdown": bool(walkthrough.get("answer_markdown")),
    },
}
emit(payload, code=0 if payload["passed"] else 1)
PY
