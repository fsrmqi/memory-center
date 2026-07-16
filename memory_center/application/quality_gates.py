"""质量门禁汇总用例。"""
from __future__ import annotations

from typing import Any

from memory_center.core.benchmark.trending import check_regression_alerts, generate_benchmark_report
from memory_center.core.orchestrator import (
    memory_eval_agent_guidance_replay_campaign,
    memory_eval_java_call_resolution_unresolved,
)


def quality_gates_summary(workspace_file: str, min_events: int) -> dict[str, Any]:
    benchmark = generate_benchmark_report(workspace_file)
    alerts = check_regression_alerts(workspace_file)
    campaign = memory_eval_agent_guidance_replay_campaign(workspace_file, min_events=min_events)
    unresolved = memory_eval_java_call_resolution_unresolved(workspace_file, limit=0)
    return {
        "schema_version": 1,
        "health": alerts.get("health", "unknown"),
        "benchmark": {"score": (benchmark.get("health_score", {}) or {}).get("score", 0), "quality": (benchmark.get("health_score", {}) or {}).get("quality", "unknown"), "recommendations": (benchmark.get("recommendations", []) or [])[:5]},
        "regression_alerts": {"total": alerts.get("total_regressions", 0), "critical": alerts.get("critical_count", 0), "warning": alerts.get("warning_count", 0), "items": [{key: alert.get(key, "") for key in ("severity", "code", "message", "recommendation")} for alert in (alerts.get("alerts", []) or [])[:10]]},
        "replay_campaign": {"passed": campaign.get("passed", False), "total_guidance_events": ((campaign.get("replay", {}) or {}).get("summary", {}) or {}).get("total_guidance_events", 0), "missing_intents": ((campaign.get("coverage", {}) or {}).get("missing_intents", []) or [])},
        "java_call_resolution": {"call_edge_count": (unresolved.get("summary", {}) or {}).get("call_edge_count", 0), "unresolved_call_edge_count": (unresolved.get("summary", {}) or {}).get("unresolved_call_edge_count", 0), "unresolved_rate": (unresolved.get("summary", {}) or {}).get("unresolved_rate", 0.0), "top_categories": (unresolved.get("categories", []) or [])[:3]},
    }
