"""Benchmark trending — long-term monitoring of token usage and performance.

This module implements Phase B of NEXT_PHASE_MASTER_PLAN:
- Expand token benchmark to trend records
- Fixed high-frequency function benchmark baselines
- Token change curves per budget
- Integration with work-health/mc_admin/workbench
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

BENCHMARK_BASELINE_FILE = "benchmark-baselines.jsonl"
BENCHMARK_TREND_FILE = "benchmark-trends.jsonl"
AGENT_GUIDANCE_TREND_FILE = "agent-guidance-trends.jsonl"
AGENT_GUIDANCE_ADOPTION_TREND_FILE = "agent-guidance-adoption-trends.jsonl"
AGENT_GUIDANCE_REPLAY_TREND_FILE = "agent-guidance-replay-trends.jsonl"


def record_benchmark_baseline(
    workspace_file: str | Path,
    function_name: str,
    raw_tokens: int,
    compact_tokens: int,
    *,
    budget: str = "medium",
    view: str = "compact",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
) -> dict[str, Any]:
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


def record_agent_guidance_trend(
    workspace_file: str | Path,
    *,
    intent: str = "",
    agent_next_step_count: int = 0,
    invalid_search_suggestion_count: int = 0,
    invalid_search_reduction_rate: float = 0.0,
    score: int = 0,
    quality: str = "",
    passed: bool = False,
    agent_next_step_actions: list[str] | None = None,
) -> dict[str, Any]:
    """Record an agent guidance quality trend point."""

    store = WorkspaceStore(workspace_file)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "intent": intent,
        "agent_next_step_count": int(agent_next_step_count or 0),
        "agent_next_step_actions": list(agent_next_step_actions or []),
        "invalid_search_suggestion_count": int(invalid_search_suggestion_count or 0),
        "invalid_search_reduction_rate": round(float(invalid_search_reduction_rate or 0.0), 4),
        "score": int(score or 0),
        "quality": quality,
        "passed": bool(passed),
    }
    store.append_jsonl(AGENT_GUIDANCE_TREND_FILE, entry)
    return {
        "recorded": True,
        "trend_point": entry,
    }


def record_agent_guidance_adoption_trend(
    workspace_file: str | Path,
    *,
    total_guidance_events: int = 0,
    adopted_count: int = 0,
    missed_count: int = 0,
    adoption_rate: float = 0.0,
    score: int = 0,
    quality: str = "",
    session_id: str = "",
    missed_action_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Record an agent guidance adoption trend point."""

    store = WorkspaceStore(workspace_file)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "total_guidance_events": int(total_guidance_events or 0),
        "adopted_count": int(adopted_count or 0),
        "missed_count": int(missed_count or 0),
        "adoption_rate": round(float(adoption_rate or 0.0), 4),
        "score": int(score or 0),
        "quality": quality,
        "missed_action_counts": {
            str(action): int(count or 0)
            for action, count in (missed_action_counts or {}).items()
            if str(action) and int(count or 0) > 0
        },
    }
    store.append_jsonl(AGENT_GUIDANCE_ADOPTION_TREND_FILE, entry)
    return {
        "recorded": True,
        "trend_point": entry,
    }


def record_agent_guidance_replay_trend(
    workspace_file: str | Path,
    *,
    total_guidance_events: int = 0,
    adopted_count: int = 0,
    missed_count: int = 0,
    bypassed_count: int = 0,
    unobservable_count: int = 0,
    adoption_rate: float = 0.0,
    bypass_rate: float = 0.0,
    unobservable_rate: float = 0.0,
    score: int = 0,
    quality: str = "",
    session_id: str = "",
    reason_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Record an agent guidance replay trend point."""

    store = WorkspaceStore(workspace_file)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "total_guidance_events": int(total_guidance_events or 0),
        "adopted_count": int(adopted_count or 0),
        "missed_count": int(missed_count or 0),
        "bypassed_count": int(bypassed_count or 0),
        "unobservable_count": int(unobservable_count or 0),
        "adoption_rate": round(float(adoption_rate or 0.0), 4),
        "bypass_rate": round(float(bypass_rate or 0.0), 4),
        "unobservable_rate": round(float(unobservable_rate or 0.0), 4),
        "score": int(score or 0),
        "quality": quality,
        "reason_counts": {
            str(reason): int(count or 0)
            for reason, count in (reason_counts or {}).items()
            if str(reason) and int(count or 0) > 0
        },
    }
    store.append_jsonl(AGENT_GUIDANCE_REPLAY_TREND_FILE, entry)
    return {
        "recorded": True,
        "trend_point": entry,
    }


def get_benchmark_baselines(
    workspace_file: str | Path,
    function_name: str = "",
    budget: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    """Retrieve benchmark baselines with optional filtering."""
    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(BENCHMARK_BASELINE_FILE, limit=max(limit, 1000))

    if function_name:
        rows = [r for r in rows if r.get("function_name") == function_name]
    if budget:
        rows = [r for r in rows if r.get("budget") == budget]

    # Aggregate by function
    function_stats: dict[str, dict[str, Any]] = {}
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
    for stats in function_stats.values():
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
) -> dict[str, Any]:
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
    function_trends: dict[str, list[dict[str, Any]]] = {}
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


def get_agent_guidance_trends(
    workspace_file: str | Path,
    *,
    days: int = 30,
    limit: int = 500,
) -> dict[str, Any]:
    """Retrieve agent guidance trend data and regression signals."""

    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(AGENT_GUIDANCE_TREND_FILE, limit=max(limit, 5000))
    cutoff = datetime.now(timezone.utc).isoformat()
    if days > 0:
        from datetime import timedelta
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff = cutoff_dt.isoformat()
        rows = [row for row in rows if row.get("timestamp", "") >= cutoff]

    rows = rows[-limit:]
    regressions = _detect_agent_guidance_regressions(rows)
    return {
        "total_records": len(rows),
        "time_range": {
            "from": cutoff,
            "to": datetime.now(timezone.utc).isoformat(),
            "days": days,
        },
        "trend_points": rows[-50:],
        "regressions": regressions,
        "summary": _build_agent_guidance_trend_summary(rows),
    }


def get_agent_guidance_adoption_trends(
    workspace_file: str | Path,
    *,
    days: int = 30,
    limit: int = 500,
) -> dict[str, Any]:
    """Retrieve agent guidance adoption trend data and regression signals."""

    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(AGENT_GUIDANCE_ADOPTION_TREND_FILE, limit=max(limit, 5000))
    cutoff = datetime.now(timezone.utc).isoformat()
    if days > 0:
        from datetime import timedelta
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff = cutoff_dt.isoformat()
        rows = [row for row in rows if row.get("timestamp", "") >= cutoff]

    rows = rows[-limit:]
    regressions = _detect_agent_guidance_adoption_regressions(rows)
    return {
        "total_records": len(rows),
        "time_range": {
            "from": cutoff,
            "to": datetime.now(timezone.utc).isoformat(),
            "days": days,
        },
        "trend_points": rows[-50:],
        "regressions": regressions,
        "summary": _build_agent_guidance_adoption_trend_summary(rows),
    }


def get_agent_guidance_replay_trends(
    workspace_file: str | Path,
    *,
    days: int = 30,
    limit: int = 500,
) -> dict[str, Any]:
    """Retrieve agent guidance replay trend data and regression signals."""

    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(AGENT_GUIDANCE_REPLAY_TREND_FILE, limit=max(limit, 5000))
    cutoff = datetime.now(timezone.utc).isoformat()
    if days > 0:
        from datetime import timedelta
        cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff = cutoff_dt.isoformat()
        rows = [row for row in rows if row.get("timestamp", "") >= cutoff]

    rows = rows[-limit:]
    regressions = _detect_agent_guidance_replay_regressions(rows)
    return {
        "total_records": len(rows),
        "time_range": {
            "from": cutoff,
            "to": datetime.now(timezone.utc).isoformat(),
            "days": days,
        },
        "trend_points": rows[-50:],
        "regressions": regressions,
        "summary": _build_agent_guidance_replay_trend_summary(rows),
    }


def _detect_agent_guidance_regressions(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regressions: list[dict[str, Any]] = []
    if len(points) < 2:
        return regressions

    latest = points[-1]
    previous = points[:-1]
    prev_invalid_avg = sum(int(p.get("invalid_search_suggestion_count", 0) or 0) for p in previous) / len(previous)
    prev_step_avg = sum(int(p.get("agent_next_step_count", 0) or 0) for p in previous) / len(previous)
    latest_invalid = int(latest.get("invalid_search_suggestion_count", 0) or 0)
    latest_steps = int(latest.get("agent_next_step_count", 0) or 0)
    latest_score = int(latest.get("score", 0) or 0)

    if latest_invalid > prev_invalid_avg:
        regressions.append({
            "type": "agent_guidance",
            "code": "invalid_search_suggestions_increased",
            "severity": "critical" if latest_invalid >= 2 else "warning",
            "latest_invalid_search_suggestion_count": latest_invalid,
            "historical_avg_invalid_search_suggestion_count": round(prev_invalid_avg, 2),
            "message": "agent guidance invalid search suggestions increased",
            "recommendation": "检查 agent_next_steps 是否重新鼓励 find/grep/rg --files/sed 等无界搜索。",
        })
    if prev_step_avg > 0 and latest_steps < prev_step_avg * 0.5:
        regressions.append({
            "type": "agent_guidance",
            "code": "agent_next_steps_coverage_dropped",
            "severity": "warning",
            "latest_agent_next_step_count": latest_steps,
            "historical_avg_agent_next_step_count": round(prev_step_avg, 2),
            "message": "agent_next_steps coverage dropped",
            "recommendation": "检查 query/walkthrough 输出是否仍返回结构化下一步建议。",
        })
    if latest_score < 60 or latest.get("passed") is False:
        regressions.append({
            "type": "agent_guidance",
            "code": "agent_guidance_gate_failed",
            "severity": "critical" if latest_score < 50 else "warning",
            "latest_score": latest_score,
            "message": "agent guidance quality gate failed",
            "recommendation": "运行 eval-agent-guidance 并检查 findings 与 invalid_search_suggestions。",
        })
    return regressions


def _detect_agent_guidance_adoption_regressions(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regressions: list[dict[str, Any]] = []
    if len(points) < 2:
        return regressions

    latest = points[-1]
    previous = points[:-1]
    previous_rates = [float(p.get("adoption_rate", 0.0) or 0.0) for p in previous]
    prev_rate_avg = sum(previous_rates) / len(previous_rates)
    latest_rate = float(latest.get("adoption_rate", 0.0) or 0.0)
    latest_missed = int(latest.get("missed_count", 0) or 0)
    latest_total = int(latest.get("total_guidance_events", 0) or 0)
    latest_score = int(latest.get("score", 0) or 0)

    if latest_total > 0 and latest_rate < 0.6:
        regressions.append({
            "type": "agent_guidance_adoption",
            "code": "low_agent_guidance_adoption_rate",
            "severity": "critical" if latest_rate < 0.3 else "warning",
            "latest_adoption_rate": round(latest_rate, 4),
            "historical_avg_adoption_rate": round(prev_rate_avg, 4),
            "latest_missed_count": latest_missed,
            "message": "agent guidance adoption rate is low",
            "recommendation": "检查 lookup 后续是否按 agent_next_steps 调用了对应 Memory Center 工具。",
        })
    if prev_rate_avg > 0 and latest_rate < prev_rate_avg * 0.7:
        regressions.append({
            "type": "agent_guidance_adoption",
            "code": "agent_guidance_adoption_rate_dropped",
            "severity": "warning",
            "latest_adoption_rate": round(latest_rate, 4),
            "historical_avg_adoption_rate": round(prev_rate_avg, 4),
            "message": "agent guidance adoption rate dropped",
            "recommendation": "对比最近 agent_guidance event 和 tool_call，确认建议动作是否太难执行或入口没有自动串联。",
        })
    if latest_score < 60:
        regressions.append({
            "type": "agent_guidance_adoption",
            "code": "agent_guidance_adoption_gate_failed",
            "severity": "critical" if latest_score < 50 else "warning",
            "latest_score": latest_score,
            "message": "agent guidance adoption quality gate failed",
            "recommendation": "运行 eval-agent-guidance-adoption 并检查 missed adoption_records。",
        })
    return regressions


def _detect_agent_guidance_replay_regressions(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regressions: list[dict[str, Any]] = []
    if len(points) < 2:
        return regressions

    latest = points[-1]
    previous = points[:-1]
    previous_rates = [float(p.get("adoption_rate", 0.0) or 0.0) for p in previous]
    prev_rate_avg = sum(previous_rates) / len(previous_rates)
    latest_rate = float(latest.get("adoption_rate", 0.0) or 0.0)
    latest_bypass_rate = float(latest.get("bypass_rate", 0.0) or 0.0)
    latest_unobservable_rate = float(latest.get("unobservable_rate", 0.0) or 0.0)
    latest_total = int(latest.get("total_guidance_events", 0) or 0)
    latest_score = int(latest.get("score", 0) or 0)

    if latest_total > 0 and latest_rate < 0.6:
        regressions.append({
            "type": "agent_guidance_replay",
            "code": "low_agent_guidance_replay_adoption_rate",
            "severity": "critical" if latest_rate < 0.3 else "warning",
            "latest_adoption_rate": round(latest_rate, 4),
            "historical_avg_adoption_rate": round(prev_rate_avg, 4),
            "message": "agent guidance replay adoption rate is low",
            "recommendation": "运行 eval-agent-guidance-replay，检查 replay_records 的 reason 与 diagnostics。",
        })
    if latest_bypass_rate > 0.2:
        regressions.append({
            "type": "agent_guidance_replay",
            "code": "agent_guidance_bypass_rate_high",
            "severity": "critical" if latest_bypass_rate > 0.5 else "warning",
            "latest_bypass_rate": round(latest_bypass_rate, 4),
            "message": "agent guidance bypass rate is high",
            "recommendation": "检查建议 command 是否足够可执行，以及宿主是否仍优先使用 rg/grep/find 等本地搜索。",
        })
    if latest_unobservable_rate > 0.3:
        regressions.append({
            "type": "agent_guidance_replay",
            "code": "agent_guidance_unobservable_rate_high",
            "severity": "warning",
            "latest_unobservable_rate": round(latest_unobservable_rate, 4),
            "message": "agent guidance unobservable rate is high",
            "recommendation": "确认 lookup 入口是否传入 session_id，后续工具调用是否写入 session event。",
        })
    if prev_rate_avg > 0 and latest_rate < prev_rate_avg * 0.7:
        regressions.append({
            "type": "agent_guidance_replay",
            "code": "agent_guidance_replay_adoption_rate_dropped",
            "severity": "warning",
            "latest_adoption_rate": round(latest_rate, 4),
            "historical_avg_adoption_rate": round(prev_rate_avg, 4),
            "message": "agent guidance replay adoption rate dropped",
            "recommendation": "对比最近 replay trend 的 reason_counts，确认是绕过、不可观测还是动作不匹配。",
        })
    if latest_score < 60:
        regressions.append({
            "type": "agent_guidance_replay",
            "code": "agent_guidance_replay_gate_failed",
            "severity": "critical" if latest_score < 50 else "warning",
            "latest_score": latest_score,
            "message": "agent guidance replay quality gate failed",
            "recommendation": "运行 eval-agent-guidance-replay 并优先处理最高频 reason。",
        })
    return regressions


def _build_agent_guidance_trend_summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    if not points:
        return {
            "total_trend_points": 0,
            "latest_agent_next_step_count": 0,
            "latest_invalid_search_suggestion_count": 0,
            "avg_agent_next_step_count": 0.0,
            "avg_invalid_search_suggestion_count": 0.0,
            "pass_rate": 0.0,
        }
    latest = points[-1]
    avg_steps = sum(int(p.get("agent_next_step_count", 0) or 0) for p in points) / len(points)
    avg_invalid = sum(int(p.get("invalid_search_suggestion_count", 0) or 0) for p in points) / len(points)
    pass_rate = sum(1 for p in points if p.get("passed") is True) / len(points)
    return {
        "total_trend_points": len(points),
        "latest_agent_next_step_count": int(latest.get("agent_next_step_count", 0) or 0),
        "latest_invalid_search_suggestion_count": int(latest.get("invalid_search_suggestion_count", 0) or 0),
        "avg_agent_next_step_count": round(avg_steps, 2),
        "avg_invalid_search_suggestion_count": round(avg_invalid, 2),
        "pass_rate": round(pass_rate, 4),
    }


def _build_agent_guidance_adoption_trend_summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    if not points:
        return {
            "total_trend_points": 0,
            "latest_adoption_rate": 0.0,
            "avg_adoption_rate": 0.0,
            "latest_missed_count": 0,
            "total_guidance_events": 0,
            "total_missed_count": 0,
            "latest_missed_action_counts": {},
            "missed_action_counts": {},
        }
    latest = points[-1]
    avg_rate = sum(float(p.get("adoption_rate", 0.0) or 0.0) for p in points) / len(points)
    total_events = sum(int(p.get("total_guidance_events", 0) or 0) for p in points)
    total_missed = sum(int(p.get("missed_count", 0) or 0) for p in points)
    missed_action_counts: dict[str, int] = {}
    for point in points:
        raw_counts = point.get("missed_action_counts", {})
        if not isinstance(raw_counts, dict):
            continue
        for action, count in raw_counts.items():
            action_key = str(action)
            if not action_key:
                continue
            missed_action_counts[action_key] = missed_action_counts.get(action_key, 0) + int(count or 0)
    latest_action_counts = latest.get("missed_action_counts", {})
    if not isinstance(latest_action_counts, dict):
        latest_action_counts = {}
    return {
        "total_trend_points": len(points),
        "latest_adoption_rate": round(float(latest.get("adoption_rate", 0.0) or 0.0), 4),
        "avg_adoption_rate": round(avg_rate, 4),
        "latest_missed_count": int(latest.get("missed_count", 0) or 0),
        "total_guidance_events": total_events,
        "total_missed_count": total_missed,
        "latest_missed_action_counts": {
            str(action): int(count or 0)
            for action, count in latest_action_counts.items()
            if str(action) and int(count or 0) > 0
        },
        "missed_action_counts": dict(sorted(missed_action_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def _build_agent_guidance_replay_trend_summary(points: list[dict[str, Any]]) -> dict[str, Any]:
    if not points:
        return {
            "total_trend_points": 0,
            "latest_adoption_rate": 0.0,
            "avg_adoption_rate": 0.0,
            "latest_bypass_rate": 0.0,
            "latest_unobservable_rate": 0.0,
            "total_guidance_events": 0,
            "reason_counts": {},
        }
    latest = points[-1]
    avg_rate = sum(float(p.get("adoption_rate", 0.0) or 0.0) for p in points) / len(points)
    reason_counts: dict[str, int] = {}
    for point in points:
        raw_counts = point.get("reason_counts", {})
        if not isinstance(raw_counts, dict):
            continue
        for reason, count in raw_counts.items():
            reason_key = str(reason)
            if not reason_key:
                continue
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + int(count or 0)
    return {
        "total_trend_points": len(points),
        "latest_adoption_rate": round(float(latest.get("adoption_rate", 0.0) or 0.0), 4),
        "avg_adoption_rate": round(avg_rate, 4),
        "latest_bypass_rate": round(float(latest.get("bypass_rate", 0.0) or 0.0), 4),
        "latest_unobservable_rate": round(float(latest.get("unobservable_rate", 0.0) or 0.0), 4),
        "total_guidance_events": sum(int(p.get("total_guidance_events", 0) or 0) for p in points),
        "reason_counts": dict(sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def _detect_regressions(
    function_trends: dict[str, list[dict[str, Any]]],
    threshold_pct: float = 10.0,
) -> list[dict[str, Any]]:
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
    function_trends: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
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


def check_regression_alerts(workspace_file: str | Path, threshold_pct: float = 10.0) -> dict[str, Any]:
    """Check for benchmark regressions and generate alerts.

    Returns alert summary suitable for mc_admin / workbench display.
    """
    trends = get_benchmark_trends(workspace_file)
    regressions = trends.get("regressions", [])
    agent_guidance = get_agent_guidance_trends(workspace_file)
    agent_regressions = agent_guidance.get("regressions", [])
    agent_adoption = get_agent_guidance_adoption_trends(workspace_file)
    agent_adoption_regressions = agent_adoption.get("regressions", [])
    agent_replay = get_agent_guidance_replay_trends(workspace_file)
    agent_replay_regressions = agent_replay.get("regressions", [])

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
    for reg in agent_regressions:
        severity = str(reg.get("severity", "warning") or "warning")
        alerts.append({
            "type": "agent_guidance",
            "function": "agent_guidance",
            "change_pct": 0,
            "severity": severity,
            "recent_avg": reg.get("latest_agent_next_step_count", reg.get("latest_invalid_search_suggestion_count", 0)),
            "historical_avg": reg.get("historical_avg_agent_next_step_count", reg.get("historical_avg_invalid_search_suggestion_count", 0)),
            "message": reg.get("message", ""),
            "recommendation": reg.get("recommendation", ""),
            "code": reg.get("code", ""),
        })
    for reg in agent_adoption_regressions:
        severity = str(reg.get("severity", "warning") or "warning")
        alerts.append({
            "type": "agent_guidance_adoption",
            "function": "agent_guidance_adoption",
            "change_pct": 0,
            "severity": severity,
            "recent_avg": reg.get("latest_adoption_rate", 0),
            "historical_avg": reg.get("historical_avg_adoption_rate", 0),
            "message": reg.get("message", ""),
            "recommendation": reg.get("recommendation", ""),
            "code": reg.get("code", ""),
        })
    for reg in agent_replay_regressions:
        severity = str(reg.get("severity", "warning") or "warning")
        alerts.append({
            "type": "agent_guidance_replay",
            "function": "agent_guidance_replay",
            "change_pct": 0,
            "severity": severity,
            "recent_avg": reg.get("latest_adoption_rate", reg.get("latest_bypass_rate", reg.get("latest_unobservable_rate", 0))),
            "historical_avg": reg.get("historical_avg_adoption_rate", 0),
            "message": reg.get("message", ""),
            "recommendation": reg.get("recommendation", ""),
            "code": reg.get("code", ""),
        })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_regressions": len(alerts),
        "critical_count": sum(1 for a in alerts if a["severity"] == "critical"),
        "warning_count": sum(1 for a in alerts if a["severity"] == "warning"),
        "alerts": alerts,
        "agent_guidance": {
            "total_regressions": len(agent_regressions),
            "summary": agent_guidance.get("summary", {}),
            "regressions": agent_regressions,
        },
        "agent_guidance_adoption": {
            "total_regressions": len(agent_adoption_regressions),
            "summary": agent_adoption.get("summary", {}),
            "regressions": agent_adoption_regressions,
        },
        "agent_guidance_replay": {
            "total_regressions": len(agent_replay_regressions),
            "summary": agent_replay.get("summary", {}),
            "regressions": agent_replay_regressions,
        },
        "health": "critical" if any(a["severity"] == "critical" for a in alerts) else "warning" if alerts else "healthy",
    }

def generate_benchmark_report(
    workspace_file: str | Path,
    function_name: str = "",
) -> dict[str, Any]:
    """Generate comprehensive benchmark report for workbench/admin views."""
    baselines = get_benchmark_baselines(workspace_file, function_name=function_name)
    trends = get_benchmark_trends(workspace_file, function_name=function_name)

    return {
        "baselines": baselines,
        "trends": trends,
        "agent_guidance_trends": get_agent_guidance_trends(workspace_file),
        "agent_guidance_adoption_trends": get_agent_guidance_adoption_trends(workspace_file),
        "agent_guidance_replay_trends": get_agent_guidance_replay_trends(workspace_file),
        "health_score": _calculate_health_score(baselines, trends),
        "recommendations": _generate_recommendations(baselines, trends),
    }


def _calculate_health_score(
    baselines: dict[str, Any],
    trends: dict[str, Any],
) -> dict[str, Any]:
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
    baselines: dict[str, Any],
    trends: dict[str, Any],
) -> list[str]:
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
    per_function_thresholds: dict[str, float] = field(default_factory=dict)

    def threshold_for(self, function_name: str) -> float:
        """Return threshold for a specific function, falling back to default."""
        return self.per_function_thresholds.get(function_name, self.default_threshold_pct)


def check_regression_alerts_configurable(
    workspace_file: str | Path,
    config: RegressionThresholdConfig | None = None,
) -> dict[str, Any]:
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
