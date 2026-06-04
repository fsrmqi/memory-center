"""Benchmark trending — long-term monitoring of token usage and performance.

This module implements Phase B of NEXT_PHASE_MASTER_PLAN:
- Expand token benchmark to trend records
- Fixed high-frequency function benchmark baselines
- Token change curves per budget
- Integration with work-health/mc_admin/workbench
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..store import WorkspaceStore

BENCHMARK_BASELINE_FILE = "benchmark-baselines.jsonl"
BENCHMARK_TREND_FILE = "benchmark-trends.jsonl"


def record_benchmark_baseline(
    workspace_file: str | Path,
    function_name: str,
    raw_tokens: int,
    compact_tokens: int,
    *,
    budget: str = "medium",
    view: str = "compact",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record a benchmark baseline for a specific function.

    This captures the "expected" token usage for high-frequency functions.
    """
    store = WorkspaceStore(workspace_file)
    saved = raw_tokens - compact_tokens
    pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0.0

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "function_name": function_name,
        "budget": budget,
        "view": view,
        "raw_tokens": raw_tokens,
        "compact_tokens": compact_tokens,
        "saved_tokens": saved,
        "savings_pct": round(pct, 1),
        "metadata": metadata or {},
    }

    store.append_jsonl(BENCHMARK_BASELINE_FILE, entry)

    return {
        "recorded": True,
        "function_name": function_name,
        "savings_pct": round(pct, 1),
        "entry": entry,
    }


def record_benchmark_trend(
    workspace_file: str | Path,
    function_name: str,
    raw_tokens: int,
    compact_tokens: int,
    *,
    budget: str = "medium",
    view: str = "compact",
    session_id: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """Record a benchmark trend point for time-series analysis.

    Each invocation appends to the trend log for regression detection.
    """
    store = WorkspaceStore(workspace_file)
    saved = raw_tokens - compact_tokens
    pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0.0

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "function_name": function_name,
        "budget": budget,
        "view": view,
        "raw_tokens": raw_tokens,
        "compact_tokens": compact_tokens,
        "saved_tokens": saved,
        "savings_pct": round(pct, 1),
        "session_id": session_id,
        "model": model,
    }

    store.append_jsonl(BENCHMARK_TREND_FILE, entry)

    return {
        "recorded": True,
        "function_name": function_name,
        "trend_point": entry,
    }


def get_benchmark_baselines(
    workspace_file: str | Path,
    function_name: str = "",
    budget: str = "",
    limit: int = 100,
) -> Dict[str, Any]:
    """Retrieve benchmark baselines with optional filtering."""
    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(BENCHMARK_BASELINE_FILE, limit=max(limit, 1000))

    if function_name:
        rows = [r for r in rows if r.get("function_name") == function_name]
    if budget:
        rows = [r for r in rows if r.get("budget") == budget]

    # Aggregate by function
    function_stats: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        fn = row.get("function_name", "")
        stats = function_stats.setdefault(fn, {
            "count": 0,
            "raw_tokens_total": 0,
            "compact_tokens_total": 0,
            "saved_tokens_total": 0,
            "savings_pcts": [],
        })
        stats["count"] += 1
        stats["raw_tokens_total"] += row.get("raw_tokens", 0)
        stats["compact_tokens_total"] += row.get("compact_tokens", 0)
        stats["saved_tokens_total"] += row.get("saved_tokens", 0)
        stats["savings_pcts"].append(row.get("savings_pct", 0.0))

    # Calculate averages
    for fn, stats in function_stats.items():
        if stats["count"] > 0:
            stats["avg_raw_tokens"] = stats["raw_tokens_total"] // stats["count"]
            stats["avg_compact_tokens"] = stats["compact_tokens_total"] // stats["count"]
            stats["avg_savings_pct"] = round(sum(stats["savings_pcts"]) / len(stats["savings_pcts"]), 1)
            del stats["savings_pcts"]  # Clean up

    return {
        "total_records": len(rows),
        "function_stats": function_stats,
        "recent_baselines": rows[:20],
    }


def get_benchmark_trends(
    workspace_file: str | Path,
    function_name: str = "",
    budget: str = "",
    days: int = 30,
    limit: int = 500,
) -> Dict[str, Any]:
    """Retrieve benchmark trends with time-series analysis.

    Returns trend data for regression detection.
    """
    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(BENCHMARK_TREND_FILE, limit=max(limit, 5000))

    # Filter by time window
    cutoff = datetime.now(timezone.utc).isoformat()
    if days > 0:
        from datetime import timedelta
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff = cutoff_dt.isoformat()
        rows = [r for r in rows if r.get("timestamp", "") >= cutoff]

    if function_name:
        rows = [r for r in rows if r.get("function_name") == function_name]
    if budget:
        rows = [r for r in rows if r.get("budget") == budget]

    # Build time series per function
    function_trends: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        fn = row.get("function_name", "")
        function_trends.setdefault(fn, []).append({
            "timestamp": row.get("timestamp", ""),
            "raw_tokens": row.get("raw_tokens", 0),
            "compact_tokens": row.get("compact_tokens", 0),
            "savings_pct": row.get("savings_pct", 0.0),
            "budget": row.get("budget", ""),
        })

    # Detect regressions
    regressions = _detect_regressions(function_trends)

    return {
        "total_records": len(rows),
        "time_range": {
            "from": cutoff,
            "to": datetime.now(timezone.utc).isoformat(),
            "days": days,
        },
        "function_trends": {fn: points[-50:] for fn, points in function_trends.items()},  # Last 50 points per function
        "regressions": regressions,
        "summary": _build_trend_summary(function_trends),
    }


def _detect_regressions(
    function_trends: Dict[str, List[Dict[str, Any]]],
    threshold_pct: float = 10.0,
) -> List[Dict[str, Any]]:
    """Detect regressions where token usage increased significantly."""
    regressions = []

    for fn, points in function_trends.items():
        if len(points) < 5:
            continue

        # Compare recent vs historical
        recent = points[-5:]
        historical = points[:-5]

        if not historical:
            continue

        recent_avg_raw = sum(p.get("raw_tokens", 0) for p in recent) / len(recent)
        historical_avg_raw = sum(p.get("raw_tokens", 0) for p in historical) / len(historical)

        if historical_avg_raw > 0:
            change_pct = ((recent_avg_raw - historical_avg_raw) / historical_avg_raw) * 100

            if change_pct > threshold_pct:
                regressions.append({
                    "function_name": fn,
                    "change_pct": round(change_pct, 1),
                    "recent_avg_raw": int(recent_avg_raw),
                    "historical_avg_raw": int(historical_avg_raw),
                    "severity": "high" if change_pct > 25 else "medium",
                    "recommendation": f"检查 {fn} 最近的变更，token 使用量增加了 {round(change_pct, 1)}%",
                })

    regressions.sort(key=lambda x: x["change_pct"], reverse=True)
    return regressions


def _build_trend_summary(
    function_trends: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Build summary of all trends."""
    total_points = sum(len(points) for points in function_trends.values())
    function_count = len(function_trends)

    # Find most/least efficient functions
    function_efficiency = []
    for fn, points in function_trends.items():
        if points:
            avg_savings = sum(p.get("savings_pct", 0) for p in points) / len(points)
            function_efficiency.append((fn, avg_savings))

    function_efficiency.sort(key=lambda x: x[1], reverse=True)

    return {
        "total_trend_points": total_points,
        "functions_tracked": function_count,
        "most_efficient": [{"function": fn, "avg_savings_pct": round(pct, 1)} for fn, pct in function_efficiency[:5]],
        "least_efficient": [{"function": fn, "avg_savings_pct": round(pct, 1)} for fn, pct in function_efficiency[-5:]],
    }


def check_regression_alerts(workspace_file: str | Path, threshold_pct: float = 10.0) -> Dict[str, Any]:
    """Check for benchmark regressions and generate alerts.

    Returns alert summary suitable for mc_admin / workbench display.
    """
    trends = get_benchmark_trends(workspace_file)
    regressions = trends.get("regressions", [])

    alerts = []
    for reg in regressions:
        change_pct = reg.get("change_pct", 0)
        severity = "critical" if change_pct > 25 else "warning" if change_pct > threshold_pct else "ok"
        if severity != "ok":
            alerts.append({
                "function": reg.get("function_name", ""),
                "change_pct": change_pct,
                "severity": severity,
                "recent_avg": reg.get("recent_avg_raw", 0),
                "historical_avg": reg.get("historical_avg_raw", 0),
                "message": f"{reg.get('function_name', '')} token usage increased {change_pct}%",
                "recommendation": reg.get("recommendation", ""),
            })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_regressions": len(alerts),
        "critical_count": sum(1 for a in alerts if a["severity"] == "critical"),
        "warning_count": sum(1 for a in alerts if a["severity"] == "warning"),
        "alerts": alerts,
        "health": "critical" if any(a["severity"] == "critical" for a in alerts) else "warning" if alerts else "healthy",
    }

def generate_benchmark_report(
    workspace_file: str | Path,
    function_name: str = "",
) -> Dict[str, Any]:
    """Generate comprehensive benchmark report for workbench/admin views."""
    baselines = get_benchmark_baselines(workspace_file, function_name=function_name)
    trends = get_benchmark_trends(workspace_file, function_name=function_name)

    return {
        "baselines": baselines,
        "trends": trends,
        "health_score": _calculate_health_score(baselines, trends),
        "recommendations": _generate_recommendations(baselines, trends),
    }


def _calculate_health_score(
    baselines: Dict[str, Any],
    trends: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate overall benchmark health score."""
    score = 100
    issues = []

    # Penalize for regressions
    regressions = trends.get("regressions", [])
    if regressions:
        high_count = sum(1 for r in regressions if r.get("severity") == "high")
        medium_count = sum(1 for r in regressions if r.get("severity") == "medium")
        score -= high_count * 15
        score -= medium_count * 8
        issues.append(f"发现 {len(regressions)} 个回归问题")

    # Penalize for low savings
    function_stats = baselines.get("function_stats", {})
    low_savings_count = sum(1 for stats in function_stats.values() if stats.get("avg_savings_pct", 0) < 20)
    if low_savings_count > 0:
        score -= low_savings_count * 5
        issues.append(f"{low_savings_count} 个函数的 token 节省率低于 20%")

    score = max(0, min(100, score))

    return {
        "score": score,
        "quality": "high" if score >= 85 else "medium" if score >= 60 else "low",
        "issues": issues,
    }


def _generate_recommendations(
    baselines: Dict[str, Any],
    trends: Dict[str, Any],
) -> List[str]:
    """Generate actionable recommendations."""
    recommendations = []

    # Check for regressions
    regressions = trends.get("regressions", [])
    if regressions:
        recommendations.append(f"优先处理 {len(regressions)} 个 token 回归问题")

    # Check baseline coverage
    function_stats = baselines.get("function_stats", {})
    if len(function_stats) < 5:
        recommendations.append("增加更多高频函数的基准测试")

    # Check for inconsistencies
    for fn, stats in function_stats.items():
        if stats.get("avg_savings_pct", 0) < 10:
            recommendations.append(f"函数 {fn} 的 token 节省率过低，检查 compact 逻辑")

    if not recommendations:
        recommendations.append("基准测试健康，继续保持")

    return recommendations


@dataclass
class RegressionThresholdConfig:
    """Configurable regression thresholds per function/budget (Phase D).

    Allows operators to set per-function or global thresholds
    instead of relying on hardcoded defaults.
    """
    default_threshold_pct: float = 10.0
    critical_threshold_pct: float = 25.0
    min_data_points: int = 5
    per_function_thresholds: Dict[str, float] = field(default_factory=dict)

    def threshold_for(self, function_name: str) -> float:
        """Return threshold for a specific function, falling back to default."""
        return self.per_function_thresholds.get(function_name, self.default_threshold_pct)


def check_regression_alerts_configurable(
    workspace_file: str | Path,
    config: RegressionThresholdConfig | None = None,
) -> Dict[str, Any]:
    """Enhanced regression check with configurable per-function thresholds (Phase D).

    Wraps the existing check_regression_alerts with per-function threshold support.
    """
    if config is None:
        config = RegressionThresholdConfig()

    trends = get_benchmark_trends(workspace_file)
    regressions = trends.get("regressions", [])

    alerts = []
    for reg in regressions:
        fn = reg.get("function_name", "")
        change_pct = reg.get("change_pct", 0)
        threshold = config.threshold_for(fn)

        if change_pct > config.critical_threshold_pct:
            severity = "critical"
        elif change_pct > threshold:
            severity = "warning"
        else:
            continue  # Below threshold, not an alert

        alerts.append({
            "function": fn,
            "change_pct": change_pct,
            "threshold": threshold,
            "severity": severity,
            "recent_avg": reg.get("recent_avg_raw", 0),
            "historical_avg": reg.get("historical_avg_raw", 0),
            "message": f"{fn} token usage increased {change_pct}% (threshold: {threshold}%)",
            "recommendation": reg.get("recommendation", ""),
        })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "default_threshold": config.default_threshold_pct,
            "critical_threshold": config.critical_threshold_pct,
            "min_data_points": config.min_data_points,
        },
        "total_regressions": len(alerts),
        "critical_count": sum(1 for a in alerts if a["severity"] == "critical"),
        "warning_count": sum(1 for a in alerts if a["severity"] == "warning"),
        "alerts": alerts,
        "health": "critical" if any(a["severity"] == "critical" for a in alerts) else "warning" if alerts else "healthy",
    }
