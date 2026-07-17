from __future__ import annotations

from memory_center.core.audit.interactions import (
    MCP_INVOCATIONS_FILE,
    bind_active_session,
    build_effect_summary,
    maintain_history_retention,
    record_host_interaction,
    resolve_active_session,
)
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.mcp.runtime import WorkspaceContext, safe_mcp_tool


class _FakeMcp:
    def tool(self):
        return lambda fn: fn


def test_host_interaction_redacts_sensitive_values_and_paths(tmp_path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    result = record_host_interaction(
        str(workspace),
        {
            "event_type": "tool_call",
            "query": "authorization=Bearer top-secret inspect /Users/example/private/Service.java",
            "tool_name": "Read",
            "content": "must not persist",
        },
        session_id="session-history",
    )

    interaction = result["event"]["interaction"]
    assert "top-secret" not in interaction["query"]
    assert "/Users/example" not in interaction["query"]
    assert "<PATH:" in interaction["query"]
    assert "content" not in interaction


def test_active_session_binding_survives_new_runtime_context(tmp_path, monkeypatch) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    monkeypatch.setenv("MEMORY_CENTER_THREAD_ID", "thread-history")
    bind_active_session(str(workspace), "thread-history", "session-history", "trace-history")

    context = WorkspaceContext(str(workspace))

    @safe_mcp_tool(_FakeMcp(), context)
    def mc_lookup(query: str):
        return {"workflow": "mc-lookup", "results": []}

    mc_lookup("ArticleService")

    calls = WorkspaceStore(workspace).read_jsonl(MCP_INVOCATIONS_FILE, limit=1)
    assert context.active_session_id == "session-history"
    assert resolve_active_session(str(workspace), "thread-history") == "session-history"
    assert calls[0]["session_id"] == "session-history"
    assert calls[0]["trace_id"]
    assert "memory_center_version" in calls[0]["runtime"]


def test_effect_summary_combines_calls_host_events_and_session_outcomes(tmp_path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    store.append_jsonl(MCP_INVOCATIONS_FILE, {"tool_name": "mc_lookup", "status": "success", "duration_ms": 20, "session_id": "s1"})
    store.append_jsonl(MCP_INVOCATIONS_FILE, {"tool_name": "mc_analyze", "status": "error", "duration_ms": 80})
    record_host_interaction(str(workspace), {"event_type": "pre_edit", "tool_name": "Edit"}, session_id="s1")
    store.append_jsonl("session-summaries.jsonl", {"session_id": "s1", "outcome": "resolved"})

    summary = build_effect_summary(str(workspace))

    assert summary["calls"]["total"] == 2
    assert summary["calls"]["status_counts"] == {"error": 1, "success": 1}
    assert summary["calls"]["session_link_rate"] == 0.5
    assert summary["calls"]["latency_ms"]["p95"] == 20.0
    assert summary["host_interactions"]["session_link_rate"] == 1.0
    assert summary["outcomes"]["verified_success_rate"] == 1.0


def test_history_retention_keeps_derived_summaries_longer_than_raw_events(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    store.append_jsonl("host-interactions.jsonl", {"created_at": old})
    store.append_jsonl("session-events.jsonl", {"created_at": old})
    store.append_jsonl("session-summaries.jsonl", {"created_at": old})

    result = maintain_history_retention(str(workspace), force=True)

    assert result["pruned"] is True
    assert store.read_jsonl("host-interactions.jsonl", limit=10) == []
    assert store.read_jsonl("session-events.jsonl", limit=10) == []
    assert len(store.read_jsonl("session-summaries.jsonl", limit=10)) == 1
