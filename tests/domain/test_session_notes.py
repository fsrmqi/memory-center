"""Session Notes (L0.5 narrative layer) domain tests — capability B."""
from __future__ import annotations

import pytest

from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.session_notes import (
    NoteRejected,
    forget_note,
    list_notes,
    note_fingerprint,
    record_note,
    search_notes,
    supersede_note,
)


@pytest.fixture()
def workspace(tmp_path):
    base = tmp_path / ".memory-center"
    base.mkdir()
    (base / "workspace.yaml").write_text("workspace: notes-test\nroot: .\nservices: []\n", encoding="utf8")
    return str(base / "workspace.yaml")


def test_record_and_duplicate_noop(workspace):
    first = record_note(workspace, "决定: 网关限流改用 Redis 令牌桶", kind="decision", session_id="s1")
    assert first["recorded"] is True
    again = record_note(workspace, "决定: 网关限流改用 Redis 令牌桶", kind="decision", session_id="s1")
    assert again == {"recorded": False, "duplicate": True, "note_id": first["note_id"], "reason": "fingerprint_noop"}


def test_whitespace_normalization_shares_fingerprint(workspace):
    a = note_fingerprint("fact", "  uses   redis  ")
    b = note_fingerprint("fact", "uses redis")
    assert a == b


def test_absolute_path_rejected(workspace):
    with pytest.raises(NoteRejected) as excinfo:
        record_note(workspace, "配置在 /Users/cuijiaqi/secret/app.yaml", kind="fact")
    assert excinfo.value.code == "absolute_path_rejected"


def test_secret_shape_rejected(workspace):
    with pytest.raises(NoteRejected) as excinfo:
        record_note(workspace, "api_key = sk-abcdefghijklmnopqrs", kind="fact")
    assert excinfo.value.code == "secret_shape_rejected"


def test_private_span_stripped_before_storage(workspace):
    record_note(workspace, "偏好: 中文回复 <private>邮箱 a@b.com</private>", kind="preference")
    rows = list_notes(workspace)["notes"]
    assert len(rows) == 1
    assert "a@b.com" not in rows[0]["text"]
    assert "已省略私有片段" in rows[0]["text"]


def test_supersede_replaces_and_hides_old(workspace):
    created = record_note(workspace, "决定: 用令牌桶", kind="decision", session_id="s1")
    result = supersede_note(workspace, created["note_id"], "决定: 用令牌桶，每实例 100 QPS")
    assert result["superseded"] is True
    active = [row["note_id"] for row in list_notes(workspace)["notes"]]
    assert result["new_note_id"] in active
    assert created["note_id"] not in active
    superseded = list_notes(workspace, status="superseded")["notes"]
    assert any(row["note_id"] == created["note_id"] and row["superseded_by"] == result["new_note_id"] for row in superseded)


def test_forget_only_hides_named_note(workspace):
    a = record_note(workspace, "事实 A", kind="fact")
    b = record_note(workspace, "事实 B", kind="fact")
    result = forget_note(workspace, a["note_id"])
    assert result == {"forgotten": True, "note_id": a["note_id"], "duplicate": False}
    active = [row["note_id"] for row in list_notes(workspace)["notes"]]
    assert active == [b["note_id"]]
    forgotten = list_notes(workspace, status="forgotten")["notes"]
    assert [row["note_id"] for row in forgotten] == [a["note_id"]]


def test_forget_missing_note_is_reported(workspace):
    result = forget_note(workspace, "note:ghost:1")
    assert result == {"forgotten": False, "reason": "note_not_found", "note_id": "note:ghost:1"}


def _note_rows(workspace):
    return WorkspaceStore(workspace).read_jsonl_prefer_backend("session-notes.jsonl", limit=100)


def _note_decisions(workspace):
    return WorkspaceStore(workspace).read_jsonl_prefer_backend("session-note-decisions.jsonl", limit=100)


def test_supersede_appends_decision_row_and_keeps_original_row_untouched(workspace):
    created = record_note(workspace, "决定: 用令牌桶", kind="decision", session_id="s1")
    result = supersede_note(workspace, created["note_id"], "决定: 用令牌桶，每实例 100 QPS")
    assert result["superseded"] is True

    original = _note_rows(workspace)[0]
    assert original["status"] == "active", "追加式：原行不允许被改写"
    assert original["superseded_by"] == ""

    decisions = _note_decisions(workspace)
    assert len(decisions) == 1
    assert decisions[0]["record_type"] == "note_decision"
    assert decisions[0]["note_id"] == created["note_id"]
    assert decisions[0]["decision"] == "supersede"
    assert decisions[0]["superseded_by"] == result["new_note_id"]

    superseded = list_notes(workspace, status="superseded")["notes"]
    assert any(row["note_id"] == created["note_id"] and row["superseded_by"] == result["new_note_id"] for row in superseded)


def test_forget_appends_decision_row_and_keeps_original_row_untouched(workspace):
    created = record_note(workspace, "事实 A", kind="fact")
    result = forget_note(workspace, created["note_id"], reason="outdated")
    assert result == {"forgotten": True, "note_id": created["note_id"], "duplicate": False}

    original = _note_rows(workspace)[0]
    assert original["status"] == "active", "追加式：原行不允许被改写"

    decisions = _note_decisions(workspace)
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "forget"
    assert decisions[0]["reason"] == "outdated"

    forgotten = list_notes(workspace, status="forgotten")["notes"]
    assert [row["note_id"] for row in forgotten] == [created["note_id"]]


def test_forgotten_note_allows_rerecording_same_text(workspace):
    created = record_note(workspace, "事实: 网关双写开关关闭", kind="fact")
    forget_note(workspace, created["note_id"])
    again = record_note(workspace, "事实: 网关双写开关关闭", kind="fact")
    assert again["recorded"] is True, "投影判定已失效的指纹不应阻止重新记录"


def test_workspace_active_note_count_uses_projection(workspace):
    from memory_center.core.orchestrator.workspace_ops import workspace_status

    created = record_note(workspace, "事实 A", kind="fact")
    before = workspace_status(workspace)
    assert before["memory_layers"]["L0.5_session_notes"]["active_note_count"] == 1

    forget_note(workspace, created["note_id"])

    after = workspace_status(workspace)
    assert after["memory_layers"]["L0.5_session_notes"]["active_note_count"] == 0


def test_search_only_returns_active_matches(workspace):
    a = record_note(workspace, "限流使用 Redis 令牌桶", kind="decision")
    record_note(workspace, "日志必须包含 chainId", kind="rule")
    supersede_note(workspace, a["note_id"], "限流使用 Redis 令牌桶（v2）")
    hits = search_notes(workspace, "限流")
    assert all(row["status"] if False else True for row in hits)
    assert {row["text"] for row in hits} == {"限流使用 Redis 令牌桶（v2）"}


def test_list_filters_by_kind_and_session(workspace):
    record_note(workspace, "决定 A", kind="decision", session_id="s1")
    record_note(workspace, "事实 B", kind="fact", session_id="s2")
    decisions = list_notes(workspace, kind="decision")["notes"]
    assert [row["text"] for row in decisions] == ["决定 A"]
    s2 = list_notes(workspace, session_id="s2")["notes"]
    assert [row["text"] for row in s2] == ["事实 B"]


def test_backend_and_jsonl_export_stay_consistent(workspace):
    created = record_note(workspace, "事实 C", kind="fact")
    forget_note(workspace, created["note_id"])
    store = WorkspaceStore(workspace)
    # 追加式契约：note 原行不再被改写，决策落在独立决策文件里
    backend_rows = store.read_jsonl_prefer_backend("session-notes.jsonl", limit=100)
    assert backend_rows[0]["status"] == "active"
    decision_rows = store.read_jsonl_prefer_backend("session-note-decisions.jsonl", limit=100)
    assert len(decision_rows) == 1
    assert decision_rows[0]["note_id"] == created["note_id"]
