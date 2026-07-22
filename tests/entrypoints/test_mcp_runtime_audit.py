from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory_center.core.orchestrator import workspace_start_session
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.mcp.runtime import (
    MCP_AUDIT_MAX_RECORDS,
    MCP_AUDIT_RETENTION_DAYS,
    MCP_INVOCATIONS_FILE,
    WorkspaceContext,
    safe_mcp_tool,
)


class _FakeMcp:
    def tool(self):
        return lambda fn: fn


def test_mcp_calls_are_recorded_and_linked_to_started_session(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    context = WorkspaceContext(str(workspace))

    @safe_mcp_tool(_FakeMcp(), context)
    def mc_start(intent: str):
        return {"session": workspace_start_session(workspace, intent, session_id="session-mcp-audit")}

    @safe_mcp_tool(_FakeMcp(), context)
    def mc_lookup(query: str, mode: str = "auto"):
        return {"workflow": "mc-lookup", "mode": mode, "results": [{"name": "ArticleService"}]}

    mc_start("验证 MCP 调用记录")
    mc_lookup("ArticleService", mode="query")

    store = WorkspaceStore(workspace)
    invocations = store.read_jsonl(MCP_INVOCATIONS_FILE, limit=10)
    assert [item["tool_name"] for item in invocations[-2:]] == ["mc_start", "mc_lookup"]
    assert invocations[-1]["session_id"] == "session-mcp-audit"
    assert invocations[-1]["inputs"] == {"mode": "query", "query": "ArticleService"}
    assert invocations[-1]["result"]["results_count"] == 1

    events = store.read_jsonl("session-events.jsonl", limit=20)
    tool_calls = [item for item in events if item.get("event_type") == "tool_call"]
    assert [item["payload"]["tool_name"] for item in tool_calls[-2:]] == ["mc_start", "mc_lookup"]


def test_mcp_call_audit_redacts_unapproved_inputs_and_records_errors(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    context = WorkspaceContext(str(workspace))

    @safe_mcp_tool(_FakeMcp(), context)
    def mc_admin(action: str, content: str = "", payload: str = ""):
        raise ValueError("invalid admin request")

    result = mc_admin("session_log", content="private markdown", payload='{"secret":"value"}')

    assert result["error"] is True
    assert result["error_type"] == "invalid_input"
    invocation = WorkspaceStore(workspace).read_jsonl(MCP_INVOCATIONS_FILE, limit=1)[0]
    assert invocation["status"] == "error"
    assert invocation["inputs"] == {"action": "session_log"}
    assert "content" not in invocation["inputs"]
    assert "payload" not in invocation["inputs"]


def test_mcp_audit_retention_prunes_file_and_backend(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    now = datetime.now(timezone.utc)
    store.append_jsonl(MCP_INVOCATIONS_FILE, {"tool_name": "expired", "created_at": (now - timedelta(days=31)).isoformat()})
    for index in range(3):
        store.append_jsonl(
            MCP_INVOCATIONS_FILE,
            {"tool_name": f"recent-{index}", "created_at": (now - timedelta(minutes=3 - index)).isoformat()},
        )

    summary = store.prune_jsonl(
        MCP_INVOCATIONS_FILE,
        created_before=now - timedelta(days=MCP_AUDIT_RETENTION_DAYS),
        max_records=2,
    )

    assert (MCP_AUDIT_RETENTION_DAYS, MCP_AUDIT_MAX_RECORDS) == (30, 100_000)
    assert summary["expired"] == 1
    assert summary["overflow"] == 1
    assert [row["tool_name"] for row in store.read_jsonl(MCP_INVOCATIONS_FILE, limit=10)] == ["recent-1", "recent-2"]
    assert store.memory_backend_query_records(collection=MCP_INVOCATIONS_FILE, limit=10)["total_count"] == 2


def test_first_mcp_call_applies_audit_retention(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    store.append_jsonl(
        MCP_INVOCATIONS_FILE,
        {"tool_name": "expired", "created_at": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()},
    )
    context = WorkspaceContext(str(workspace))

    @safe_mcp_tool(_FakeMcp(), context)
    def mc_lookup(query: str):
        return {"workflow": "mc-lookup", "results": []}

    mc_lookup("ArticleService")

    assert [row["tool_name"] for row in store.read_jsonl(MCP_INVOCATIONS_FILE, limit=10)] == ["mc_lookup"]


def test_large_mcp_audit_keeps_reads_bounded_while_compaction_runs(tmp_path: Path, monkeypatch) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    now = datetime.now(timezone.utc)
    # Create a file large enough to force the asynchronous physical-compaction
    # branch, while retaining an expired SQLite mirror row for logical filtering.
    store.append_jsonl(
        MCP_INVOCATIONS_FILE,
        {"tool_name": "expired", "created_at": (now - timedelta(days=31)).isoformat()},
    )
    audit_path = store.memory_dir / MCP_INVOCATIONS_FILE
    audit_path.write_text(audit_path.read_text(encoding="utf-8") + (" " * 70_000) + "\n", encoding="utf-8")
    started = threading.Event()
    original_prune = WorkspaceStore.prune_jsonl

    def slow_prune(self, *args, **kwargs):
        started.set()
        time.sleep(0.2)
        return original_prune(self, *args, **kwargs)

    monkeypatch.setattr(WorkspaceStore, "prune_jsonl", slow_prune)
    samples: list[float] = []
    for _ in range(8):
        context = WorkspaceContext(str(workspace))

        @safe_mcp_tool(_FakeMcp(), context)
        def mc_lookup(query: str):
            return {"workflow": "mc-lookup", "results": []}

        began = time.perf_counter()
        mc_lookup("ArticleService")
        samples.append((time.perf_counter() - began) * 1000)

    ordered = sorted(samples)
    p95_ms = ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.95))]
    p99_ms = ordered[min(len(ordered) - 1, int((len(ordered) - 1) * 0.99))]
    assert p95_ms < 100
    assert p99_ms < 100
    assert started.wait(1)
    assert WorkspaceStore(workspace).memory_backend_query_records(collection=MCP_INVOCATIONS_FILE, limit=10)["total_count"] == 8
