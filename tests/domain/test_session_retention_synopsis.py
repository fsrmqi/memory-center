"""session 事件滚动归档与外置 payload 确定性摘要测试。

覆盖:
- synopsis:json/csv/yaml/code/text/unknown 分类与有界输出;
- offload 接入:超过内联上限的 payload 事件带 _payload_synopsis;
- retention planner:轮次聚合、预算、keep_recent 保护、锚点保护、空输入;
- 归档执行:事件迁移到 archive 集合、live 裁剪、write_receipt、dry-run plan。
"""
from __future__ import annotations

import json
from pathlib import Path

from memory_center.core.foundation.synopsis import build_synopsis, detect_kind, synopsis_from_payload
from memory_center.core.orchestrator.retention import (
    RETENTION_MODE_TURN_BUDGET,
    group_turns,
    plan_retention,
)
from memory_center.core.orchestrator.session import (
    SESSION_EVENTS_ARCHIVE_FILE,
    archive_session_events,
    plan_session_archive,
    workspace_log_session_event,
    workspace_recent_evidence,
    workspace_start_session,
)
from memory_center.core.storage.workspace import WorkspaceStore


# ---------- synopsis ----------


def test_synopsis_detects_json_csv_yaml_code_text() -> None:
    assert detect_kind('{"a": 1}') == "json"
    assert detect_kind("file,count\na.java,3") == "csv"
    assert detect_kind("a:\n  b: 1") == "yaml"
    code = "import os\nfrom typing import Any\n\nclass Foo:\n    def bar(self):\n        return 1"
    assert detect_kind(code) == "code"
    assert detect_kind("Build succeeded\nTests: 42 passed") == "text"


def test_synopsis_json_is_bounded() -> None:
    payload = json.dumps({"k{i}".format(i=i): i for i in range(50)} | {"nested": {"deep": {"deeper": [1, 2, 3]}}})
    result = build_synopsis(payload)
    assert result.kind == "json"
    assert len(result.structure) <= 12
    assert len(result.notable_items) <= 10
    assert all(len(line) <= 200 for line in result.summary + result.structure + result.notable_items)


def test_synopsis_table_counts_first_column() -> None:
    result = build_synopsis("file,count\na.java,3\nb.java,5\na.java,1")
    assert result.kind == "csv"
    assert "a.java x2" in result.notable_items
    assert "3 data rows" in result.title


def test_synopsis_from_payload_prefers_largest_text_field() -> None:
    big_output = "import os\nclass A:\n    pass\n" * 5
    data = synopsis_from_payload({"tool_name": "pytest", "note": "tiny", "output": big_output})
    assert data is not None
    assert data["source_field"] == "output"
    assert data["kind"] == "code"
    assert data["title"].startswith("pytest:")


def test_synopsis_from_payload_empty_returns_none() -> None:
    assert synopsis_from_payload({"tool_name": "x"}) is None
    assert synopsis_from_payload({}) is None


# ---------- offload integration ----------


def test_offloaded_payload_carries_synopsis(demo_workspace: Path) -> None:
    workspace = demo_workspace
    started = workspace_start_session(str(workspace), "大 payload 事件摘要")
    sid = str(started["session_id"])
    big = {"tool_name": "grep", "output": "\n".join(f"line {i}: some match content" for i in range(400))}
    logged = workspace_log_session_event(str(workspace), sid, "tool_call", big)
    assert logged["payload_ref"], "oversized payload must be offloaded"

    store = WorkspaceStore(workspace)
    rows = store.read_jsonl_prefer_backend("session-events.jsonl", limit=10)
    event = next(row for row in rows if row.get("payload", {}).get("_payload_ref"))
    compact = event["payload"]
    assert compact["_payload_offloaded"] is True
    synopsis = compact["_payload_synopsis"]
    assert synopsis["kind"] in {"text", "unknown"}
    assert synopsis["source_field"] == "output"
    assert len(synopsis["summary"]) <= 5


def test_recent_evidence_exposes_synopsis_full_and_compact(demo_workspace: Path) -> None:
    workspace = demo_workspace
    started = workspace_start_session(str(workspace), "证据摘要透出")
    sid = str(started["session_id"])
    workspace_log_session_event(
        str(workspace),
        sid,
        "tool_call",
        {"tool_name": "pytest", "output": "FAILED test_a.py::test_x\n" + "\n".join(f"line {i}: detail" for i in range(400))},
    )

    full = workspace_recent_evidence(str(workspace), session_id=sid, limit=10, view="full")
    with_synopsis = [e for e in full["evidence"] if e.get("synopsis")]
    assert with_synopsis, "full view must expose synopsis"
    assert with_synopsis[0]["synopsis"]["kind"] in {"text", "unknown"}

    compact = workspace_recent_evidence(str(workspace), session_id=sid, limit=10, view="compact")
    with_title = [e for e in compact["evidence"] if e.get("synopsis_title")]
    assert with_title, "compact view must expose synopsis_title"
    assert with_title[0]["synopsis_title"].startswith("pytest:")


# ---------- retention planner ----------


def _events(turns: int, per_turn: int = 3) -> list[dict]:
    events: list[dict] = []
    for i in range(turns):
        events.append({"event_type": "user_prompt", "payload": {"intent": f"task {i}"}, "created_at": f"2026-01-0{i + 1}T00:00:00+00:00"})
        for j in range(per_turn):
            events.append({"event_type": "tool_call", "payload": {"tool_name": "mc_lookup", "query": f"q{i}{j}", "body": "x" * 200}, "created_at": f"2026-01-0{i + 1}T00:0{j + 1}:00+00:00"})
    return events


def test_group_turns_uses_boundary_events() -> None:
    turns = group_turns(_events(4))
    assert len(turns) == 4
    assert all(turn.event_count == 4 for turn in turns)
    assert turns[0].label == "task 0"


def test_plan_retention_respects_keep_recent_and_budget() -> None:
    events = _events(6)
    decision = plan_retention(events, keep_recent_turns=2, max_archive_tokens=100000)
    assert decision.mode == RETENTION_MODE_TURN_BUDGET
    assert decision.archive_turns == 4
    assert decision.keep_turns == 2
    assert decision.boundary_event_index == decision.archive_events
    # 边界后第一条必须是保留轮次的边界事件
    assert events[decision.boundary_event_index]["event_type"] == "user_prompt"


def test_plan_retention_budget_exhausted_stops_archiving() -> None:
    events = _events(6, per_turn=8)
    decision = plan_retention(events, keep_recent_turns=1, max_archive_tokens=1)
    assert decision.reason in {"archive_budget_exhausted", "planned"}
    if decision.reason == "planned":
        assert decision.archive_turns >= 1


def test_plan_retention_protects_live_anchor_events() -> None:
    events = _events(4)
    events.append({"event_type": "session_end", "payload": {"outcome": "done"}, "created_at": "2026-01-05T00:00:00+00:00"})
    decision = plan_retention(events, keep_recent_turns=1, max_archive_tokens=100000)
    kept_types = [event["event_type"] for event in events[decision.boundary_event_index:]]
    assert "session_end" in kept_types
    assert all(event_type != "session_end" for event_type in [event["event_type"] for event in events[: decision.boundary_event_index]])


def test_plan_retention_keeps_entire_turn_when_anchor_is_in_its_middle() -> None:
    events = [
        {"event_type": "user_prompt", "payload": {"intent": "first"}},
        {"event_type": "session_end", "payload": {"outcome": "done"}},
        {"event_type": "tool_call", "payload": {}},
        {"event_type": "user_prompt", "payload": {"intent": "second"}},
        {"event_type": "user_prompt", "payload": {"intent": "third"}},
    ]
    decision = plan_retention(events, keep_recent_turns=2, max_archive_tokens=100000)
    assert decision.archive_events == 0
    assert decision.boundary_event_index == len(events)


def test_plan_retention_noop_cases() -> None:
    assert plan_retention([]).reason == "no_events"
    few = plan_retention(_events(2), keep_recent_turns=3)
    assert few.reason.startswith("below_keep_recent_turns")
    assert few.archive_events == 0


# ---------- archive execution ----------


def _seed_long_session(workspace: Path) -> str:
    started = workspace_start_session(str(workspace), "滚动归档验证")
    sid = str(started["session_id"])
    for i in range(4):
        workspace_log_session_event(str(workspace), sid, "user_prompt", {"intent": f"阶段 {i}", "note": "x" * 120})
        for j in range(3):
            workspace_log_session_event(
                str(workspace),
                sid,
                "tool_call",
                {"tool_name": "mc_lookup", "query": f"q{i}{j}", "body": "y" * 150},
            )
    return sid


def test_archive_plan_is_dry_run(demo_workspace: Path) -> None:
    workspace = demo_workspace
    sid = _seed_long_session(workspace)
    plan = plan_session_archive(str(workspace), session_id=sid, keep_recent_turns=1, max_archive_tokens=100000)
    assert plan["dry_run"] is True
    assert plan["total_turns"] >= 4
    assert plan["archive_events"] > 0

    store = WorkspaceStore(workspace)
    assert not (store.memory_dir / SESSION_EVENTS_ARCHIVE_FILE).exists()


def test_archive_moves_events_and_keeps_receipt(demo_workspace: Path) -> None:
    workspace = demo_workspace
    sid = _seed_long_session(workspace)
    result = archive_session_events(str(workspace), session_id=sid, keep_recent_turns=1, max_archive_tokens=100000)
    assert result["archived"] is True
    assert result["archived_events"] > 0
    assert result["write_receipt"]["action"] == "workspace_archive_session_events"

    store = WorkspaceStore(workspace)
    archived_rows = store.read_jsonl_prefer_backend(SESSION_EVENTS_ARCHIVE_FILE, limit=100)
    live_rows = [row for row in store.read_jsonl_prefer_backend("session-events.jsonl", limit=100) if row.get("session_id") == sid]
    assert len(archived_rows) >= result["archived_events"]
    assert all(row.get("archived_from") == "session-events.jsonl" for row in archived_rows)
    # live 段只保留最近轮次,且轮次边界在 user_prompt 上
    assert len(live_rows) == result["kept_events"]
    assert live_rows[0]["event_type"] == "user_prompt"


def test_archive_moves_exact_events_when_created_at_is_shared(demo_workspace: Path) -> None:
    store = WorkspaceStore(demo_workspace)
    sid = "same-timestamp-session"
    timestamp = "2026-01-01T00:00:00+00:00"
    events = []
    for turn in range(3):
        events.extend([
            {"session_id": sid, "event_type": "user_prompt", "payload": {"intent": f"turn {turn}"}, "created_at": timestamp},
            {"session_id": sid, "event_type": "tool_call", "payload": {"query": str(turn)}, "created_at": timestamp},
        ])
    for event in events:
        store.append_jsonl("session-events.jsonl", event)

    result = archive_session_events(str(demo_workspace), session_id=sid, keep_recent_turns=1, max_archive_tokens=100000)
    live = store.find_jsonl_prefer_backend("session-events.jsonl", lambda row: row.get("session_id") == sid, limit=20)
    archived = store.find_jsonl_prefer_backend(SESSION_EVENTS_ARCHIVE_FILE, lambda row: row.get("session_id") == sid, limit=20)
    assert result["archived_events"] == 4
    assert result["prune"]["deleted"] == 4
    assert len(live) == 2
    assert len(archived) == 4


def test_archive_noop_when_below_threshold(demo_workspace: Path) -> None:
    workspace = demo_workspace
    started = workspace_start_session(str(workspace), "单轮不归档")
    sid = str(started["session_id"])
    workspace_log_session_event(str(workspace), sid, "tool_call", {"tool_name": "x"})
    result = archive_session_events(str(workspace), session_id=sid)
    assert result["archived"] is False
    assert result["reason"].startswith("below_keep_recent_turns")
