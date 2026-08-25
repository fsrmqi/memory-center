from __future__ import annotations

from pathlib import Path

from memory_center.core.knowledge.assets import collaboration_asset_status
from memory_center.core.knowledge.wiki_bridge import sync_personal_wiki_assets


def test_sync_personal_wiki_assets_registers_only_reverse_links(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)
    wiki_root = tmp_path / "wiki"
    document = wiki_root / "工作" / "开普云" / "项目" / "众包平台.md"
    document.parent.mkdir(parents=True)
    document.write_text("# 众包平台\n\n这段正文不应复制进资产摘要。", encoding="utf-8")

    result = sync_personal_wiki_assets(
        workspace,
        wiki_root=wiki_root,
        owner="tester",
        documents=["工作/开普云/项目/众包平台.md"],
    )

    assert result["synced"] is True
    asset = result["assets"][0]
    assert asset["kind"] == "wiki"
    assert asset["source_ref"] == "pawiki:工作/开普云/项目/众包平台.md"
    assert "这段正文" not in asset["context_excerpt"]
    assert asset["metadata"]["scope"] == "kaipuyun"
    status = collaboration_asset_status(workspace)
    assert status["counts"]["wiki"] == 1
