from __future__ import annotations

from pathlib import Path

import pytest

from memory_center.core.knowledge.assets import collaboration_asset_status
from memory_center.core.knowledge.wiki_bridge import sync_personal_wiki_assets


@pytest.fixture(autouse=True)
def _neutral_profile_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认使用中性（空）profile；需要 profile 的用例显式声明或 setenv。"""
    monkeypatch.delenv("MEMORY_CENTER_PROFILE", raising=False)
    monkeypatch.delenv("MEMORY_CENTER_PROFILE_DIR", raising=False)


def test_sync_personal_wiki_assets_registers_only_reverse_links(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    wiki_root = tmp_path / "wiki"
    relative = "工作/acme/项目/demo.md"
    document = wiki_root / relative
    document.parent.mkdir(parents=True)
    document.write_text("# 示例条目\n\n这段正文不应复制进资产摘要。", encoding="utf-8")

    result = sync_personal_wiki_assets(
        workspace,
        wiki_root=wiki_root,
        owner="tester",
        scope="acme",
        documents=[relative],
    )

    assert result["synced"] is True
    asset = result["assets"][0]
    assert asset["kind"] == "wiki"
    assert asset["source_ref"] == f"pawiki:{relative}"
    assert "这段正文" not in asset["context_excerpt"]
    assert asset["metadata"]["scope"] == "acme"
    status = collaboration_asset_status(workspace)
    assert status["counts"]["wiki"] == 1


def test_sync_personal_wiki_assets_is_neutral_without_profile(tmp_path: Path) -> None:
    """空 profile + 未显式传 documents：不选中任何文档、不预设 scope、不抛错。"""
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir()

    result = sync_personal_wiki_assets(workspace, wiki_root=wiki_root, owner="tester")

    assert result["synced"] is True
    assert result["assets"] == []
    assert result["scope"] is None
    assert result["scope_state"] == "not_configured"
    assert result["documents_state"] == "not_configured"
