"""KnowledgeLink 集成契约测试（Phase 1/2/4）。

锚定 docs/KNOWLEDGE_LINK_INTEGRATION_PLAN.md 的安全门禁：
- 无 evidence_refs 不注册；shadow_only 会话不得创建 task-scoped 链接；
- 相同 (knowledge_id, content_sha256) 幂等；content_sha256 为 raw 字节全量 SHA-256；
- 候选读取 fail closed；stale/revoked 不进候选；
- 漂移检测除 stale 标记外只读；revoked 仅人工产生。
"""
from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path

import pytest

from memory_center.core.knowledge import wiki_promotion as promotion_module
from memory_center.core.knowledge.assets import get_collaboration_asset, ingest_wiki_document_asset, register_collaboration_asset
from memory_center.core.knowledge.candidates import MAX_CANDIDATES, wiki_knowledge_candidates
from memory_center.core.knowledge.knowledge_events import read_knowledge_events
from memory_center.core.knowledge.wiki_bridge import (
    attach_knowledge_link_to_task,
    knowledge_id_for_path,
    knowledge_link_hash,
    list_knowledge_links,
    mark_knowledge_link_status,
    register_knowledge_link,
    sync_personal_wiki_assets,
)
from memory_center.core.knowledge.wiki_drift import knowledge_link_drift, knowledge_link_metrics
from memory_center.core.knowledge.wiki_promotion import confirm_wiki_promotion, wiki_promotion_preview
from tests.fixtures import copy_demo_workspace

_RELATIVE = "工作/开普云/项目/众包平台.md"


def _wiki_entry(tmp_path: Path, relative: str = _RELATIVE, body: str = "# 众包平台\n\n长期知识正文，不应复制。") -> Path:
    wiki_root = tmp_path / "wiki"
    document = wiki_root / relative
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(body, encoding="utf-8")
    return wiki_root


def _register(workspace: Path, tmp_path: Path, *, task_id: str = "", evidence=None, relative: str = _RELATIVE, binding_mode: str = "") -> dict:
    return register_knowledge_link(
        workspace,
        relative_path=relative,
        title="众包平台",
        owner="tester",
        wiki_root=tmp_path / "wiki",
        scope="kaipuyun",
        task_id=task_id,
        binding_mode=binding_mode,
        relation_reason="测试登记。",
        evidence_refs=evidence if evidence is not None else ["session:src-1"],
        actor="tester",
    )


def _hit(path: str, score: float, snippet: str = "摘要片段", title: str = "标题") -> dict:
    return {"path": path, "score": -score, "snippet": snippet, "title": title}


def _transport_of(hits: list[dict]):
    def transport(*, task: str, scope: str, limit: int) -> dict:
        return {"task": task, "scope": scope, "context": {"business": hits}, "source_count": len(hits)}

    return transport


# ---- Phase 1: registration contract ----

def test_registration_requires_evidence_refs(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    _wiki_entry(tmp_path)
    with pytest.raises(ValueError, match="evidence_refs"):
        _register(workspace, tmp_path, evidence=[])


def test_registration_rejects_shadow_only_task_scope(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    _wiki_entry(tmp_path)
    with pytest.raises(ValueError, match="shadow_only"):
        _register(workspace, tmp_path, task_id="task-1", binding_mode="shadow_only")


def test_registration_is_idempotent_on_same_content_hash(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    _wiki_entry(tmp_path)
    first = _register(workspace, tmp_path)
    assert first["registered"] is True
    version_before = first["asset"]["version"]
    second = _register(workspace, tmp_path)
    assert second["idempotent"] is True and second["registered"] is False
    assert get_collaboration_asset(workspace, first["asset"]["asset_id"])["version"] == version_before


def test_reregister_after_content_change_reactivates_with_history(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    _register(workspace, tmp_path)
    kid = knowledge_id_for_path(_RELATIVE)
    mark_knowledge_link_status(workspace, kid, status="stale", reason="手动模拟漂移", actor="tester")
    (wiki_root / _RELATIVE).write_text("# 众包平台 v2\n\n更新后的长期知识。", encoding="utf-8")
    result = _register(workspace, tmp_path)
    assert result["registered"] is True
    metadata = result["asset"]["metadata"]
    assert metadata["link_status"] == "active"
    assert metadata["content_sha256"] == knowledge_link_hash((wiki_root / _RELATIVE).read_bytes())
    transitions = [(item["from"], item["to"]) for item in metadata["status_history"]]
    assert ("active", "stale") in transitions and ("stale", "active") in transitions


def test_mark_status_records_traceable_history(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    _wiki_entry(tmp_path)
    _register(workspace, tmp_path)
    kid = knowledge_id_for_path(_RELATIVE)
    with pytest.raises(ValueError):
        mark_knowledge_link_status(workspace, kid, status="deleted", reason="x", actor="tester")
    with pytest.raises(ValueError):
        mark_knowledge_link_status(workspace, kid, status="revoked", reason="x", actor="")
    missing = mark_knowledge_link_status(workspace, "pawiki-does-not-exist", status="revoked", reason="r", actor="tester")
    assert missing["marked"] is False
    marked = mark_knowledge_link_status(workspace, kid, status="revoked", reason="条目已删除", actor="tester")
    assert marked["marked"] is True
    metadata = marked["asset"]["metadata"]
    assert metadata["link_status"] == "revoked"
    assert metadata["status_history"][-1]["to"] == "revoked"
    events = read_knowledge_events(workspace)
    assert any(event["event_type"] == "link_status_changed" for event in events)


def test_attach_merges_evidence_and_records_event(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    _wiki_entry(tmp_path)
    _register(workspace, tmp_path)
    kid = knowledge_id_for_path(_RELATIVE)
    with pytest.raises(ValueError):
        attach_knowledge_link_to_task(workspace, kid, task_id="task-1", evidence_refs=[], actor="tester")
    from memory_center.core.tasks.artifacts import create_task_space
    task_id = create_task_space(workspace, title="task-1")["task_id"]
    result = attach_knowledge_link_to_task(workspace, kid, task_id=task_id, evidence_refs=["receipt:wr-1"], actor="tester", reason="人工确认")
    assert result["attached"] is True
    metadata = result["asset"]["metadata"]
    assert metadata["task_id"] == task_id
    assert "receipt:wr-1" in metadata["evidence_refs"] and "session:src-1" in metadata["evidence_refs"]
    assert any(event["event_type"] == "manual_attach" for event in read_knowledge_events(workspace))


def test_attach_missing_link_reports_honestly(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    result = attach_knowledge_link_to_task(workspace, "pawiki-none", task_id="t", evidence_refs=["session:s"], actor="tester")
    assert result["attached"] is False and result["reason"] == "knowledge_link_not_found"


def test_sync_uses_knowledge_link_contract(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    _wiki_entry(tmp_path)
    result = sync_personal_wiki_assets(workspace, wiki_root=tmp_path / "wiki", owner="tester", documents=[_RELATIVE])
    asset = result["assets"][0]
    metadata = asset["metadata"]
    assert asset["source_ref"] == f"pawiki:{_RELATIVE}"
    assert metadata["link_status"] == "active"
    assert len(metadata["content_sha256"]) == 64
    assert metadata["workspace_id"]
    assert "这段正文" not in asset["context_excerpt"]
    links = list_knowledge_links(workspace, status="active")
    assert links["count"] == 1 and links["links"][0]["task_id"] == ""


def test_list_filters_by_task_scope_and_status(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    _wiki_entry(tmp_path)
    _register(workspace, tmp_path, task_id="task-1", evidence=["session:s", "task:task-1"])
    assert list_knowledge_links(workspace, task_id="task-1")["count"] == 1
    assert list_knowledge_links(workspace, task_id="other")["count"] == 0
    assert list_knowledge_links(workspace, status="stale")["count"] == 0
    assert list_knowledge_links(workspace, scope="kaipuyun")["count"] == 1
    with pytest.raises(ValueError):
        list_knowledge_links(workspace, status="gone")


def test_ingest_hash_uses_full_raw_bytes(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    from memory_center.core.workspace.config import load_workspace_config

    root = Path(load_workspace_config(workspace).root)
    document = root / "notes" / "doc.md"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes("# 文档\n\n内容".encode("utf-8"))
    result = ingest_wiki_document_asset(workspace, document, owner="tester")
    assert result["ingested"] is True
    assert result["asset"]["metadata"]["content_sha256"] == hashlib.sha256(document.read_bytes()).hexdigest()


# ---- Phase 2: anchored candidates ----

def test_candidates_reject_missing_anchor(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    result = wiki_knowledge_candidates(workspace, task="  ", wiki_root=tmp_path / "wiki")
    assert result["ready"] is False and result["reason"] == "anchor_missing" and result["candidates"] == []


def test_candidates_fail_closed_when_transport_unavailable(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    result = wiki_knowledge_candidates(workspace, task="众包平台", wiki_root=tmp_path / "wiki", transport=lambda **_: None)
    assert result["ready"] is False and result["reason"] == "wiki_transport_unavailable" and result["candidates"] == []


def test_candidates_exclude_low_scores_and_stale_links(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    other = "技术/项目/MemoryCenter.md"
    (wiki_root / other).parent.mkdir(parents=True, exist_ok=True)
    (wiki_root / other).write_text("# MemoryCenter\n", encoding="utf-8")
    register_knowledge_link(
        workspace, relative_path=other, title="MemoryCenter", owner="tester", wiki_root=wiki_root,
        relation_reason="r", evidence_refs=["session:s"], actor="tester",
    )
    kid = knowledge_id_for_path(other)
    mark_knowledge_link_status(workspace, kid, status="stale", reason="内容漂移", actor="tester")
    transport = _transport_of([
        _hit(other, 9.0, title="MemoryCenter"),
        _hit(_RELATIVE, 5.0, title="众包平台"),
        _hit("工作/低分.md", -1.0),
        {"path": "工作/无分.md", "snippet": "没有分数"},
        {"score": 3.0, "snippet": "没有路径"},
    ])
    result = wiki_knowledge_candidates(workspace, task="众包平台", wiki_root=wiki_root, transport=transport)
    assert result["ready"] is True
    assert [candidate["title"] for candidate in result["candidates"]] == ["众包平台"]
    assert result["excluded"]["stale_or_revoked"] == 1
    assert result["excluded"]["low_score_or_unscored"] == 3


def test_candidates_enrich_from_registry_and_file(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    other = "技术/项目/PersonalAssistantWikiMCP.md"
    (wiki_root / other).parent.mkdir(parents=True, exist_ok=True)
    (wiki_root / other).write_text("# PA Wiki MCP\n", encoding="utf-8")
    _register(workspace, tmp_path)
    transport = _transport_of([_hit(_RELATIVE, 4.0, title="众包平台"), _hit(other, 2.0, title="PA Wiki MCP")])
    result = wiki_knowledge_candidates(workspace, task="众包平台", wiki_root=wiki_root, transport=transport)
    by_title = {candidate["title"]: candidate for candidate in result["candidates"]}
    assert by_title["众包平台"]["knowledge_id"] == knowledge_id_for_path(_RELATIVE)
    assert by_title["PA Wiki MCP"]["knowledge_id"] == knowledge_id_for_path(other)
    assert by_title["PA Wiki MCP"]["content_sha256"] == knowledge_link_hash((wiki_root / other).read_bytes())
    assert all(len(candidate["content_sha256"]) == 64 for candidate in result["candidates"])
    assert all(candidate["relevance_reason"] and candidate["freshness"] for candidate in result["candidates"])
    assert any(event["event_type"] == "candidate_exposure" for event in read_knowledge_events(workspace))


def test_candidates_cap_at_three(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    hits = []
    for index in range(5):
        relative = f"工作/条目{index}.md"
        (wiki_root / relative).parent.mkdir(parents=True, exist_ok=True)
        (wiki_root / relative).write_text(f"# 条目{index}\n", encoding="utf-8")
        hits.append(_hit(relative, float(index + 1)))
    result = wiki_knowledge_candidates(workspace, task="条目", wiki_root=wiki_root, transport=_transport_of(hits), limit=5)
    assert len(result["candidates"]) == MAX_CANDIDATES == 3
    assert result["candidates"][0]["knowledge_id"] == knowledge_id_for_path("工作/条目4.md")


# ---- Phase 4: drift and metrics ----

def test_drift_marks_stale_and_reports_readonly_repair(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    _register(workspace, tmp_path)
    (wiki_root / _RELATIVE).write_text("# 众包平台 v2\n\n正文已更新。", encoding="utf-8")
    result = knowledge_link_drift(workspace, wiki_root=str(wiki_root), actor="tester", mark_stale=True)
    kid = knowledge_id_for_path(_RELATIVE)
    assert result["stale_marked"] == [kid]
    assert any(item["kind"] == "content_sha256_drift" for item in result["findings"])
    assert any(item["action"] == "refresh_via_wiki_assets_sync" for item in result["repair_actions"])
    link = list_knowledge_links(workspace, status="stale")["links"][0]
    assert link["knowledge_id"] == kid


def test_drift_reports_missing_entry_without_auto_revoking(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    _register(workspace, tmp_path)
    (wiki_root / _RELATIVE).unlink()
    result = knowledge_link_drift(workspace, wiki_root=str(wiki_root))
    assert any(item["kind"] == "wiki_entry_missing" for item in result["findings"])
    assert any(item["action"] == "confirm_revoke_or_restore" for item in result["repair_actions"])
    assert list_knowledge_links(workspace, status="active")["count"] == 1


def test_drift_flags_task_scoped_links_without_evidence(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    kid = knowledge_id_for_path(_RELATIVE)
    register_collaboration_asset(
        workspace,
        kind="wiki",
        title="legacy",
        owner="tester",
        source_ref=f"pawiki:{_RELATIVE}",
        metadata={
            "knowledge_id": kid,
            "content_sha256": knowledge_link_hash((wiki_root / _RELATIVE).read_bytes()),
            "link_status": "active",
            "task_id": "task-1",
            "evidence_refs": [],
            "wiki_root": str(wiki_root),
            "scope": "kaipuyun",
        },
        asset_id=f"asset-wiki-{kid}",
        actor="tester",
    )
    result = knowledge_link_drift(workspace)
    assert any(item["kind"] == "evidence_refs_missing" for item in result["findings"])


def test_drift_reports_unknown_wiki_root(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    kid = knowledge_id_for_path(_RELATIVE)
    register_collaboration_asset(
        workspace,
        kind="wiki",
        title="no root",
        owner="tester",
        source_ref=f"pawiki:{_RELATIVE}",
        metadata={"knowledge_id": kid, "content_sha256": knowledge_link_hash((wiki_root / _RELATIVE).read_bytes()), "link_status": "active", "task_id": "", "evidence_refs": ["session:s"]},
        asset_id=f"asset-wiki-{kid}",
        actor="tester",
    )
    result = knowledge_link_drift(workspace)
    assert any(item["kind"] == "wiki_root_unknown" for item in result["findings"])


def test_metrics_aggregate_statuses_and_events(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    _register(workspace, tmp_path)
    mark_knowledge_link_status(workspace, knowledge_id_for_path(_RELATIVE), status="stale", reason="漂移", actor="tester")
    metrics = knowledge_link_metrics(workspace)
    assert metrics["total_links"] == 1
    assert metrics["links_by_status"]["stale"] == 1
    assert metrics["stale_rate"] == 1.0
    assert metrics["events_by_type"].get("link_status_changed") == 1


# ---- Write path: preview evidence and confirmed promotion ----

def test_preview_carries_evidence_refs(tmp_path: Path) -> None:
    workspace = copy_demo_workspace(tmp_path)
    from memory_center.core.orchestrator.session import workspace_capture_dsh_delivery_summary
    from memory_center.core.tasks.artifacts import create_task_space
    from memory_center.core.tasks.shadow import bind_shadow_to_task, ensure_shadow_for_session

    # Session-first：delivery capture 需要可信锚点；先建任务并显式绑定 Shadow。
    task_id = create_task_space(workspace, title="knowledge link contract")["task_id"]
    shadow = ensure_shadow_for_session(workspace, "src-session-1", intent="契约")
    bind_shadow_to_task(workspace, shadow["shadow_id"], task_id, source="explicit")
    captured = workspace_capture_dsh_delivery_summary(workspace, "src-session-1", "完成 KnowledgeLink 契约。细节略。")
    assert captured["captured"] is True and captured["task_id"] == task_id
    preview = wiki_promotion_preview(workspace, captured["session_id"], wiki_root=tmp_path / "wiki")
    assert preview["ready"] is True
    assert "session:src-session-1" in preview["evidence_refs"]
    assert f"task:{task_id}" in preview["evidence_refs"]


def test_confirm_registers_knowledge_link_and_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path, body="# 众包平台\n\n人工确认后的晋升正文。")
    from memory_center.core.orchestrator.session import workspace_capture_dsh_delivery_summary
    from memory_center.core.tasks.artifacts import create_task_space
    from memory_center.core.tasks.shadow import bind_shadow_to_task, ensure_shadow_for_session

    task_id = create_task_space(workspace, title="knowledge link promotion")["task_id"]
    shadow = ensure_shadow_for_session(workspace, "src-session-2", intent="晋升")
    bind_shadow_to_task(workspace, shadow["shadow_id"], task_id, source="explicit")
    captured = workspace_capture_dsh_delivery_summary(workspace, "src-session-2", "完成 KnowledgeLink 晋升链路。")
    promoted_payload = {"path": _RELATIVE, "title": "众包平台"}

    def fake_run(command, **_):
        assert "--confirm" in command
        # Session-first：锚点经清洗后作为审计标注传给 Wiki bridge。
        assert "--task-id" in command
        assert task_id in command
        return types.SimpleNamespace(stdout=json.dumps(promoted_payload, ensure_ascii=False))

    monkeypatch.setattr(promotion_module.subprocess, "run", fake_run)
    result = confirm_wiki_promotion(workspace, captured["session_id"], wiki_root=wiki_root, owner="tester")
    assert result["promoted"] is True
    link = result["knowledge_link"]
    assert link["registered"] is True
    assert link["asset"]["metadata"]["link_status"] == "active"
    assert "session:src-session-2" in link["asset"]["metadata"]["evidence_refs"]
    events = read_knowledge_events(workspace)
    assert any(event["event_type"] == "promotion_confirmed" for event in events)


def test_confirm_forces_workspace_scope_for_shadow_only_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = copy_demo_workspace(tmp_path)
    wiki_root = _wiki_entry(tmp_path)
    from memory_center.core.orchestrator.session import workspace_capture_dsh_delivery_summary
    from memory_center.core.tasks.artifacts import create_task_space
    from memory_center.core.tasks.shadow import bind_shadow_to_task, ensure_shadow_for_session

    # delivery capture 本身需要绑定；但 session 决策是 shadow_only 时，
    # KnowledgeLink 仍必须降级为 workspace-scoped（task_id 为空）。
    task_id = create_task_space(workspace, title="shadow scope check")["task_id"]
    shadow = ensure_shadow_for_session(workspace, "src-session-3", intent="shadow")
    bind_shadow_to_task(workspace, shadow["shadow_id"], task_id, source="explicit")
    captured = workspace_capture_dsh_delivery_summary(workspace, "src-session-3", "完成 shadow 会话晋升。")
    monkeypatch.setattr(
        promotion_module.subprocess,
        "run",
        lambda command, **_: types.SimpleNamespace(stdout=json.dumps({"path": _RELATIVE}, ensure_ascii=False)),
    )
    result = confirm_wiki_promotion(workspace, captured["session_id"], wiki_root=wiki_root, owner="tester", binding_mode="shadow_only")
    assert result["promoted"] is True
    assert result["knowledge_link"]["asset"]["metadata"]["task_id"] == ""
