"""Token gain tracking — records compact vs raw token counts per tool invocation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore

TOKEN_GAIN_LOG_FILE = "token-gain-log.jsonl"


def log_token_gain(
    workspace_file: str | Path,
    tool_name: str,
    budget: str,
    raw_tokens: int,
    compact_tokens: int,
    *,
    model: str = "",
    view: str = "",
) -> None:
    """Append one token gain record to the workspace gain log."""
    if raw_tokens <= 0:
        return
    store = WorkspaceStore(workspace_file)
    saved = raw_tokens - compact_tokens
    pct = (saved / raw_tokens * 100) if raw_tokens > 0 else 0.0
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_name": tool_name,
        "budget": budget,
        "model": model,
        "view": view,
        "raw_tokens": raw_tokens,
        "compact_tokens": compact_tokens,
        "saved_tokens": saved,
        "savings_pct": round(pct, 1),
    }
    store.append_jsonl(TOKEN_GAIN_LOG_FILE, entry)


def query_token_gain(
    workspace_file: str | Path,
    *,
    tool_name: str = "",
    budget: str = "",
    model: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """Read and aggregate token gain records."""
    store = WorkspaceStore(workspace_file)
    rows = store.read_jsonl_prefer_backend(TOKEN_GAIN_LOG_FILE, limit=max(limit, 5000))
    if tool_name:
        rows = [r for r in rows if r.get("tool_name") == tool_name]
    if budget:
        rows = [r for r in rows if r.get("budget") == budget]
    if model:
        rows = [r for r in rows if r.get("model") == model]

    recent = rows[-limit:]

    # Aggregate per-tool
    tool_stats: dict[str, dict[str, Any]] = {}
    for row in recent:
        tn = row.get("tool_name", "")
        stats = tool_stats.setdefault(tn, {"count": 0, "raw_tokens": 0, "compact_tokens": 0, "saved_tokens": 0})
        stats["count"] += 1
        stats["raw_tokens"] += row.get("raw_tokens", 0)
        stats["compact_tokens"] += row.get("compact_tokens", 0)
        stats["saved_tokens"] += row.get("saved_tokens", 0)
    for stats in tool_stats.values():
        raw = stats["raw_tokens"] or 1
        stats["avg_savings_pct"] = round(stats["saved_tokens"] / raw * 100, 1)

    total_raw = sum(r.get("raw_tokens", 0) for r in recent)
    total_compact = sum(r.get("compact_tokens", 0) for r in recent)
    total_saved = total_raw - total_compact

    # Top 5 most savings, bottom 5 least savings
    sorted_tools = sorted(tool_stats.items(), key=lambda kv: kv[1].get("avg_savings_pct", 0), reverse=True)
    top_5 = [{"tool": tn, **stats} for tn, stats in sorted_tools[:5]]
    bottom_5 = [{"tool": tn, **stats} for tn, stats in sorted_tools[-5:] if len(sorted_tools) >= 5]

    return {
        "total_records": len(recent),
        "total_raw_tokens": total_raw,
        "total_compact_tokens": total_compact,
        "total_saved_tokens": total_saved,
        "overall_savings_pct": round(total_saved / (total_raw or 1) * 100, 1),
        "per_tool_stats": tool_stats,
        "top_5_savings": top_5,
        "bottom_5_savings": bottom_5,
        "recent": recent[:50],
    }
