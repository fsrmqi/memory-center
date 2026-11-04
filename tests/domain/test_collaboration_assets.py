from __future__ import annotations

import pytest

from memory_center.application.admin import build_admin_registry
from memory_center.application.analysis import build_context_pack
from memory_center.core.knowledge.assets import (
    ASSET_REGISTRY_FILE,
    SYSTEM_ASSET_OWNER,
    approve_collaboration_asset,
    bind_collaboration_asset,
    collaboration_asset_loadout,
    collaboration_asset_status,
    ingest_wiki_document_asset,
    register_collaboration_asset,
    register_external_published_skill,
    submit_asset_for_sharing,
    sync_workspace_collaboration_assets,
)
from memory_center.core.storage.workspace import WorkspaceStore


def test_collaboration_asset_sharing_is_approved_before_role_loadout(demo_workspace) -> None:
    registered = register_collaboration_asset(
        demo_workspace,
        kind="skill",
        title="发布检查",
        owner="alice",
        source_ref="skill:release-check",
        context_excerpt="先检查契约兼容性。",
        actor="alice",
    )
    asset_id = registered["asset"]["asset_id"]
    assert collaboration_asset_loadout(demo_workspace, agent_id="alice")["count"] == 1
    submitted = submit_asset_for_sharing(demo_workspace, asset_id, visibility="restricted", actor="alice", allowed_roles=["reviewer"])
    assert submitted["submitted"] is True
    assert not collaboration_asset_loadout(demo_workspace, role="reviewer")["assets"]
    assert approve_collaboration_asset(demo_workspace, asset_id, approved=True, actor="maintainer")["approved"] is True
    assert bind_collaboration_asset(demo_workspace, asset_id, actor="alice", roles=["reviewer"])["bound"] is True
    assert collaboration_asset_loadout(demo_workspace, role="reviewer")["assets"][0]["asset_id"] == asset_id
    assert not collaboration_asset_loadout(demo_workspace, role="developer")["assets"]


def test_asset_owner_cannot_be_overwritten_or_self_approve(demo_workspace) -> None:
    try:
        register_collaboration_asset(demo_workspace, kind="wiki", title="伪造身份", owner="alice", source_ref="wiki:forged", actor="mallory")
    except PermissionError:
        pass
    else:
        raise AssertionError("asset actor must match the declared owner")
    asset = register_collaboration_asset(demo_workspace, kind="wiki", title="设计", owner="alice", source_ref="wiki:design", actor="alice")["asset"]
    try:
        register_collaboration_asset(demo_workspace, kind="wiki", title="夺取", owner="mallory", source_ref="wiki:design", asset_id=asset["asset_id"], actor="mallory")
    except PermissionError:
        pass
    else:
        raise AssertionError("non-owner must not overwrite an existing asset")
    assert submit_asset_for_sharing(demo_workspace, asset["asset_id"], visibility="team", actor="alice")["submitted"] is True
    try:
        approve_collaboration_asset(demo_workspace, asset["asset_id"], approved=True, actor="alice")
    except PermissionError:
        pass
    else:
        raise AssertionError("owner must not approve its own sharing request")


def test_private_binding_and_asset_budget_are_honored(demo_workspace) -> None:
    asset = register_collaboration_asset(demo_workspace, kind="skill", title="私有 Skill", owner="alice", source_ref="skill:private", context_excerpt="x" * 800, metadata={"details": "y" * 800}, actor="alice")["asset"]
    assert bind_collaboration_asset(demo_workspace, asset["asset_id"], actor="alice", agents=["codex"])["bound"] is True
    loadout = collaboration_asset_loadout(demo_workspace, agent_id="codex", max_chars=500)
    assert loadout["count"] == 1
    assert len(str(loadout["assets"])) <= 700
    assert approve_collaboration_asset(demo_workspace, asset["asset_id"], approved=False, actor="maintainer")["reason"] == "asset_not_pending_review"


def test_asset_sync_preserves_approved_team_asset(demo_workspace) -> None:
    synced = sync_workspace_collaboration_assets(demo_workspace, owner="alice")
    graph_asset = next(asset_id for asset_id in synced["asset_ids"] if asset_id == "asset-code-graph-active")
    assert approve_collaboration_asset(demo_workspace, graph_asset, approved=True, actor="maintainer")["approved"] is True
    assert collaboration_asset_loadout(demo_workspace, agent_id="codex")["count"] == 1
    sync_workspace_collaboration_assets(demo_workspace, owner="alice")
    assert collaboration_asset_loadout(demo_workspace, agent_id="codex")["count"] == 1


def test_asset_sync_is_idempotent_across_agents(demo_workspace) -> None:
    sync_workspace_collaboration_assets(demo_workspace, owner="alice")
    synced = sync_workspace_collaboration_assets(demo_workspace, owner="bob")
    graph_asset = next(item for item in collaboration_asset_status(demo_workspace)["assets"] if item["asset_id"] == "asset-code-graph-active")
    assert synced["synced"] is True
    assert graph_asset["owner"] == SYSTEM_ASSET_OWNER


def test_registry_recovers_from_last_valid_backup_without_dropping_assets(demo_workspace) -> None:
    register_collaboration_asset(demo_workspace, kind="wiki", title="一", owner="alice", source_ref="wiki:one", actor="alice")
    register_collaboration_asset(demo_workspace, kind="wiki", title="二", owner="alice", source_ref="wiki:two", actor="alice")
    store = WorkspaceStore(demo_workspace)
    (store.artifacts_dir / ASSET_REGISTRY_FILE).write_text("{invalid", encoding="utf-8")
    recovered = collaboration_asset_status(demo_workspace)
    assert [asset["title"] for asset in recovered["assets"]] == ["一"]
    register_collaboration_asset(demo_workspace, kind="wiki", title="三", owner="alice", source_ref="wiki:three", actor="alice")
    assert {asset["title"] for asset in collaboration_asset_status(demo_workspace)["assets"]} == {"一", "三"}


def test_asset_metadata_and_loadout_have_total_size_budgets(demo_workspace) -> None:
    try:
        register_collaboration_asset(
            demo_workspace, kind="wiki", title="过大", owner="alice", source_ref="wiki:large",
            metadata={f"field-{index}": "x" * 800 for index in range(40)}, actor="alice",
        )
    except ValueError as exc:
        assert "metadata exceeds" in str(exc)
    else:
        raise AssertionError("oversized metadata must be rejected")
    asset = register_collaboration_asset(demo_workspace, kind="wiki", title="有界", owner="alice", source_ref="wiki:bounded", metadata={f"field-{index}": "x" * 350 for index in range(40)}, actor="alice")["asset"]
    assert asset["metadata"]
    loadout = collaboration_asset_loadout(demo_workspace, agent_id="alice")
    assert loadout["max_chars"] == 12 * 1024
    assert len(str(loadout["assets"])) <= loadout["max_chars"] + 2_000


def test_wiki_document_asset_links_code_evidence_and_context_pack(demo_workspace) -> None:
    workspace_root = demo_workspace.parent.parent
    document = workspace_root / "architecture-note.md"
    document.write_text("# 发布架构\n\n使用 `ArticleFeignClient`。详见 [流程](docs/flow.md)。\n", encoding="utf-8")
    ingested = ingest_wiki_document_asset(demo_workspace, document, owner="alice")
    assert ingested["ingested"] is True
    asset_id = ingested["asset"]["asset_id"]
    assert submit_asset_for_sharing(demo_workspace, asset_id, visibility="team", actor="alice")["submitted"] is True
    assert approve_collaboration_asset(demo_workspace, asset_id, approved=True, actor="maintainer")["approved"] is True
    pack = build_context_pack(str(demo_workspace), "发布", "auto", 1000, 4, agent_id="reviewer")
    assert any(item["asset_id"] == asset_id for item in pack["collaboration_assets"]["assets"])
    assert ingested["document_graph"]["links"] == ["docs/flow.md"]


def test_context_pack_enforces_effective_token_budget(demo_workspace) -> None:
    pack = build_context_pack(str(demo_workspace), "发布链路", "auto", 128, 12, agent_id="reviewer")
    assert pack["budget_tokens"] == 128
    assert pack["token_estimate"] <= pack["budget_tokens"]


def test_storage_budget_report_is_bounded_and_actionable(demo_workspace) -> None:
    report = WorkspaceStore(demo_workspace).storage_budget_report(warning_bytes=1)
    assert set(report["categories"]) == {"graph", "index", "artifacts", "memory"}
    assert report["status"] == "warning"
    assert report["next_action"]


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_asset_sync_and_admin_actions_share_the_same_domain_service(demo_workspace) -> None:
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_personal_wiki_promotion_can_be_registered_as_traceable_reverse_link(demo_workspace) -> None:
    admin = build_admin_registry(
        workspace_file=str(demo_workspace),
        source="local-agent",
        payload=(
            '{"kind":"wiki","title":"稳定发布规则","owner":"local-agent",'
            '"source_ref":"pawiki:知识沉淀/长期知识/稳定发布规则.md",'
            '"metadata":{"knowledge_id":"pawiki-0123456789abcdef",'
            '"content_sha256":"0123456789abcdef",'
            '"source_task_id":"task-demo",'
            '"evidence_refs":["delivery-evidence:receipt-demo"]}}'
        ),
    )
    registered = admin.dispatch("asset_register")
    asset = registered["asset"]
    assert registered["registered"] is True
    assert asset["kind"] == "wiki"
    assert asset["source_ref"].startswith("pawiki:")
    assert asset["metadata"]["knowledge_id"] == "pawiki-0123456789abcdef"
    assert asset["metadata"]["source_task_id"] == "task-demo"
    loaded = collaboration_asset_loadout(demo_workspace, agent_id="local-agent")
    assert any(item["asset_id"] == asset["asset_id"] for item in loaded["assets"])


def test_external_published_skill_keeps_only_manifest_evidence_and_requires_validation_for_loadout(demo_workspace) -> None:
    content_hash = "a" * 64
    snapshot_only = register_external_published_skill(
        demo_workspace,
        owner="alice",
        actor="alice",
        source_tag="personal-assistant-wiki",
        publication={
            "schema_version": 2,
            "asset": {"kind": "agent_skill", "name": "release-check", "version": "1.0.0", "content_sha256": content_hash},
            "release": {"status": "published", "verification_status": "snapshot_exported", "snapshot_refs": ["dsh-research-kit:run:demo:passport:abc"]},
            "skill_body": "must never be persisted",
            "candidate_path": "/private/external/SKILL.md",
        },
    )
    assert snapshot_only["recommendable"] is False
    asset = snapshot_only["asset"]
    publication = asset["metadata"]["external_publication"]
    assert publication["snapshot_refs"] == ["dsh-research-kit:run:demo:passport:abc"]
    assert publication["validation_refs"] == []
    assert "skill_body" not in str(asset)
    assert "candidate_path" not in str(asset)
    assert not collaboration_asset_loadout(demo_workspace, agent_id="alice")["assets"]

    registered = register_external_published_skill(
        demo_workspace,
        owner="alice",
        actor="alice",
        source_tag="personal-assistant-wiki",
        publication={
            "schema_version": 2,
            "asset": {"kind": "agent_skill", "name": "release-check", "version": "1.0.0", "content_sha256": content_hash},
            "release": {
                "status": "published",
                "verification_status": "validation_referenced",
                "validation_refs": ["memory-center:delivery-validation:receipt-01"],
                "snapshot_refs": ["dsh-research-kit:run:demo:passport:abc"],
            },
        },
    )
    assert registered["recommendable"] is True
    loaded = collaboration_asset_loadout(demo_workspace, agent_id="alice")
    loaded_asset = next(item for item in loaded["assets"] if item["asset_id"] == registered["asset"]["asset_id"])
    assert loaded_asset["metadata"]["external_publication"]["content_sha256"] == content_hash
    assert loaded_asset["metadata"]["external_publication"]["recommendation_status"] == "eligible"


def test_external_skill_register_admin_action_uses_the_same_evidence_gate(demo_workspace) -> None:
    admin = build_admin_registry(
        workspace_file=str(demo_workspace),
        source="alice",
        payload=(
            '{"owner":"alice","source_tag":"personal-assistant-wiki","publication":{"schema_version":2,'
            '"asset":{"kind":"agent_skill","name":"contract-review","version":"1.0.0","content_sha256":"'
            + "b" * 64
            + '"},"release":{"status":"published","validation_refs":["memory-center:delivery-validation:receipt-02"]}}}'
        ),
    )
    result = admin.dispatch("external_skill_register")
    assert result["recommendable"] is True
    assert result["asset"]["source_ref"].startswith("external-skill:personal-assistant-wiki:")
