"""Entrypoint tests for evidence-index view + Session Notes admin actions."""
from __future__ import annotations

import json

import pytest

from memory_center.application.admin import build_admin_registry
from memory_center.core.orchestrator.evidence_index import build_evidence_index


@pytest.fixture()
def workspace(tmp_path):
    base = tmp_path / ".memory-center"
    base.mkdir()
    (base / "workspace.yaml").write_text("workspace: ep-notes\nroot: .\nservices: []\n", encoding="utf8")
    return str(base / "workspace.yaml")


def test_admin_note_actions_roundtrip(workspace):
    rec = build_admin_registry(workspace_file=workspace, action="note_record", text="决定: 用令牌桶限流", session_id="s1", event_type="decision").dispatch("note_record")
    assert rec["recorded"] is True
    listed = build_admin_registry(workspace_file=workspace, action="note_list", session_id="s1").dispatch("note_list")
    assert [row["text"] for row in listed["notes"]] == ["决定: 用令牌桶限流"]
    searched = build_admin_registry(workspace_file=workspace, action="note_search", text="令牌桶").dispatch("note_search")
    assert len(searched["hits"]) == 1
    sup = build_admin_registry(workspace_file=workspace, action="note_supersede", name=rec["note_id"], text="决定: 用令牌桶限流 (v2)").dispatch("note_supersede")
    assert sup["superseded"] is True
    fgt = build_admin_registry(workspace_file=workspace, action="note_forget", name=sup["new_note_id"]).dispatch("note_forget")
    assert fgt["forgotten"] is True
    assert build_admin_registry(workspace_file=workspace, action="note_list").dispatch("note_list")["notes"] == []


def test_admin_note_rejects_bad_kind(workspace):
    result = build_admin_registry(workspace_file=workspace, action="note_record", text="无效 kind", event_type="nonsense").dispatch("note_record")
    assert result["kind"] == "fact"


def test_admin_note_search_empty_query_returns_no_hits(workspace):
    record_note = build_admin_registry(workspace_file=workspace, action="note_record", text="事实 X").dispatch("note_record")
    assert record_note["recorded"] is True
    result = build_admin_registry(workspace_file=workspace, action="note_search", text="").dispatch("note_search")
    assert result["hits"] == []


def test_evidence_index_includes_note_hits(workspace):
    from memory_center.core.orchestrator.session import workspace_start_session

    workspace_start_session(workspace, "网关限流方案已确认", session_id="sess-note")
    build_admin_registry(workspace_file=workspace, action="note_record", text="网关限流方案已确认", session_id="sess-note").dispatch("note_record")

    from memory_center.core.tasks.session_notes import search_notes

    hits = search_notes(workspace, "限流", limit=5)
    assert hits and hits[0]["text"] == "网关限流方案已确认"
    merged_result = {
        "workspace": "ep-notes",
        "results": [
            {
                "node_id": hits[0]["note_id"],
                "node": {"type": "Note", "name": hits[0]["text"], "project": "", "file_path": ""},
                "score": hits[0]["score"],
                "sources": ["note"],
                "semantic_strength": "fact",
                "evidence_level": "EXTRACTED",
                "created_at": hits[0]["created_at"],
                "source_layer": "L0.5_session_notes",
                "source_kind": "note",
            }
        ],
        "total_found": 1,
        "claim_boundary": {"negative_claim_allowed": True, "evidence_level": "VERIFIED_NEGATIVE"},
        "knowledge_state": {"state": "NOT_INDEXED"},
        "freshness": {"freshness": {"status": "fresh"}},
    }
    index = build_evidence_index(merged_result, store=None, query="限流")
    assert index["selected"][0]["ref_id"].startswith("note:")
    assert index["selected"][0]["source_layer"] == "L0.5_session_notes"
    assert index["selected"][0]["text"] == "网关限流方案已确认"


def test_close_case_records_surfaces_note_drafts_without_recording(tmp_path):
    from memory_center.application.task_shadow_flow import close_case_records

    base = tmp_path / ".memory-center"
    base.mkdir()
    (base / "workspace.yaml").write_text("workspace: close-notes\nroot: .\nservices: []\n", encoding="utf8")
    wf = str(base / "workspace.yaml")

    from memory_center.core.orchestrator.session import workspace_start_session

    workspace_start_session(wf, "修复登录超时", session_id="sess-close")
    result = close_case_records(
        wf,
        "sess-close",
        close_task_id="",
        title="t",
        auto_sync_mode="shadow_only",
        outcome="done",
        record_case=False,
        verified_by=[],
    )
    assert isinstance(result.get("note_drafts"), list)
    # intent draft should be among the suggestions (not persisted)
    texts = json.dumps(result["note_drafts"], ensure_ascii=False)
    assert "修复登录超时" in texts
    from memory_center.core.tasks.session_notes import list_notes

    assert list_notes(wf)["notes"] == []
