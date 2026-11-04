#!/usr/bin/env bash
# 真实工作区验收脚本 / Real-workspace verification entrypoint.
#
# 本脚本不内置任何私有路径：workspace.yaml 与 golden cases.yaml 必须由环境变量提供，
# 缺失时打印用法并以非 0 退出。
# This script ships no private paths: the workspace and golden cases must be supplied
# through environment variables; when missing it prints usage and exits non-zero.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

usage() {
  cat >&2 <<'EOF'
用法 / Usage:
  MEMORY_CENTER_REAL_WORKSPACE=/path/to/workspace/.memory-center/workspace.yaml \
  MEMORY_CENTER_REAL_CASES=/path/to/workspace/.memory-center/golden/cases.yaml \
  scripts/verify_real_workspace.sh

必填环境变量 / Required:
  MEMORY_CENTER_REAL_WORKSPACE  已初始化的 workspace.yaml 路径
  MEMORY_CENTER_REAL_CASES      golden cases.yaml 路径

可选环境变量 / Optional:
  MEMORY_CENTER_REAL_BASELINE   golden 性能基线 json
                                （默认取 cases 同目录的 performance-baseline.json）
  MEMORY_CENTER_SAVE_REAL_BASELINE  置 1 时把当前指标写回基线
  MEMORY_CENTER_REAL_QUERY      走查查询（默认中性示例查询）
  MEMORY_CENTER_REAL_PROJECT    限定 project（默认空，即全工作区）
EOF
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "缺少必填环境变量：${name}" >&2
    echo "Missing required environment variable: ${name}" >&2
    usage
    exit 2
  fi
}

require_env MEMORY_CENTER_REAL_WORKSPACE
require_env MEMORY_CENTER_REAL_CASES

export MEMORY_CENTER_REAL_WORKSPACE
export MEMORY_CENTER_REAL_CASES
export MEMORY_CENTER_REAL_BASELINE="${MEMORY_CENTER_REAL_BASELINE:-$(dirname "${MEMORY_CENTER_REAL_CASES}")/performance-baseline.json}"
export MEMORY_CENTER_SAVE_REAL_BASELINE="${MEMORY_CENTER_SAVE_REAL_BASELINE:-0}"
export MEMORY_CENTER_REAL_QUERY="${MEMORY_CENTER_REAL_QUERY:-梳理下 com.example.order.OrderQueryService#queryOrder 全链路，一直到最底层的逻辑处理}"
export MEMORY_CENTER_REAL_PROJECT="${MEMORY_CENTER_REAL_PROJECT:-}"

python3 - <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from memory_center.application.golden import run_golden_suite
from memory_center.core.benchmark.golden import build_golden_performance_baseline, summarize_golden_case_coverage
from memory_center.core.orchestrator import memory_query_hybrid
from memory_center.core.workspace.doctor import doctor


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
            "scenario": "real-workspace",
            "passed": False,
            "status": "real_case_missing",
            "missing": missing,
            "hint": "Set MEMORY_CENTER_REAL_WORKSPACE and MEMORY_CENTER_REAL_CASES to the real validation files, e.g. /path/to/workspace/.memory-center/workspace.yaml and /path/to/workspace/.memory-center/golden/cases.yaml.",
        },
        code=2,
    )

try:
    doctor_result = doctor(workspace, self_test=True)
    golden_coverage = summarize_golden_case_coverage(cases)
    golden = run_golden_suite(workspace, cases, performance_baseline=baseline_path if baseline_path.exists() else None)
    if save_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline = build_golden_performance_baseline(golden, label="real-workspace")
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
            "scenario": "real-workspace",
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
    "scenario": "real-workspace",
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
        "coverage": golden_coverage,
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
