from __future__ import annotations

from typing import Any


def evaluate_walkthrough_result(result: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, weight: int, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "weight": weight, "detail": detail})

    text = "\n".join(result.get("summary_lines", []) or []) + "\n" + str(result.get("answer_markdown", ""))
    add("found", bool(result.get("found")), 20)
    add("has_target_absolute_path", bool((result.get("target", {}) or {}).get("absolute_file_path")), 10)
    add("has_summary_lines", bool(result.get("summary_lines")), 10)
    add("has_feign_or_impl_continuation", bool(result.get("feign_continuations") or result.get("local_service_continuations")), 15)
    add("has_agent_usage_policy", bool(result.get("agent_usage_policy")), 10)
    add("has_schema_contract", result.get("schema_version", 0) >= 2 and bool(result.get("fields_contract")), 10)
    add("has_mermaid", str(result.get("mermaid_flow", "")).startswith("flowchart"), 5)
    add("has_branch_outline", bool(result.get("branch_outline")), 5)
    add("has_risk_or_scope_context", bool(result.get("performance_risks") or result.get("data_scope_guards")), 5)
    forbidden = ["tool-results", "grep -l", "find /", "sed -n"]
    add("does_not_recommend_low_signal_tools", not any(token in text for token in forbidden), 10, ", ".join(forbidden))

    max_score = sum(item["weight"] for item in checks)
    score = sum(item["weight"] for item in checks if item["passed"])
    return {
        "score": score,
        "max_score": max_score,
        "grade": "pass" if score >= 80 else "warn" if score >= 60 else "fail",
        "checks": checks,
    }
