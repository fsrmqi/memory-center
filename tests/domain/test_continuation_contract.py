"""会话接续契约与资料边界：接不上原会话时的降级路径必须可判定。"""
from __future__ import annotations

import pytest

from memory_center.core.foundation.continuation import (
    CONTINUE_SESSION,
    REBUILD_FROM_PACKET,
    content_boundary,
    continuation_contract,
    session_handle,
)
from memory_center.core.orchestrator import (
    workspace_end_session,
    workspace_resume_packet,
    workspace_start_session,
)


def test_continuation_contract_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError):
        continuation_contract(strategy="resume_magic", reason="x")


def test_continuation_contract_is_bounded_and_complete() -> None:
    contract = continuation_contract(
        strategy=REBUILD_FROM_PACKET,
        reason="session_closed",
        workspace_id="demo",
        session_handle=session_handle("memory-center", "s1", "closed"),
        packet_self_sufficient=True,
        next_action={"tool": "mc_start"},
        must_read=[f"ref-{index}" for index in range(20)],
    )
    assert contract["strategy"] == REBUILD_FROM_PACKET
    assert contract["session_handle"]["state"] == "closed"
    assert len(contract["must_read"]) == 8


def test_content_boundary_keeps_data_and_instruction_disjoint() -> None:
    boundary = content_boundary(data=["recent_evidence"], instruction=["next_recommended_actions"])
    assert boundary["data"] == ["recent_evidence"]
    assert boundary["instruction"] == ["next_recommended_actions"]
    assert set(boundary["data"]).isdisjoint(boundary["instruction"])
    assert boundary["policy"]


def test_resume_packet_continuation_follows_session_state(demo_workspace) -> None:
    session = workspace_start_session(demo_workspace, "接续契约")
    packet = workspace_resume_packet(demo_workspace, session_id=session["session_id"], view="full", limit=5)
    continuation = packet["continuation"]
    assert continuation["strategy"] == CONTINUE_SESSION
    assert continuation["reason"] == "session_open"
    assert continuation["session_handle"] == {
        "provider": "memory-center",
        "session_id": session["session_id"],
        "state": "open",
    }
    assert continuation["next_action"]["tool"] == "workspace_log_session_event"
    assert continuation["pending_decisions"]["count"] == 0

    workspace_end_session(demo_workspace, session["session_id"], outcome="done")
    closed = workspace_resume_packet(demo_workspace, session_id=session["session_id"], view="full", limit=5)
    assert closed["continuation"]["strategy"] == REBUILD_FROM_PACKET
    assert closed["continuation"]["reason"] == "session_closed"
    assert closed["continuation"]["session_handle"]["state"] == "closed"


def test_resume_packet_without_session_rebuilds_from_packet(demo_workspace) -> None:
    packet = workspace_resume_packet(demo_workspace, view="full", limit=5)
    assert packet["continuation"]["strategy"] == REBUILD_FROM_PACKET
    assert packet["continuation"]["reason"] == "no_session_id"
    assert packet["continuation"]["session_handle"]["state"] == "missing"


def test_resume_packet_boundary_survives_compact_view(demo_workspace) -> None:
    session = workspace_start_session(demo_workspace, "压缩视图")
    compact = workspace_resume_packet(demo_workspace, session_id=session["session_id"], view="compact", limit=5)
    assert compact["continuation"]["strategy"] == CONTINUE_SESSION
    boundary = compact["content_boundary"]
    assert "recent_evidence" in boundary["data"]
    assert "next_recommended_actions" in boundary["instruction"]
    assert set(boundary["data"]).isdisjoint(boundary["instruction"])
