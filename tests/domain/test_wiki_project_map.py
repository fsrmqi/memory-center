"""P3-2 项目地图三层上下文与语义桥测试。"""
from __future__ import annotations

import json
from pathlib import Path

from memory_center.core.knowledge.wiki import (
    generate_wiki,
    get_l1_context,
    get_l2_context,
    get_l3_bridge,
    mark_wiki_modules_stale,
    update_wiki_profile,
    wiki_status,
)


def test_generate_wiki_creates_three_level_map(demo_workspace_indexed: Path) -> None:
    result = generate_wiki(demo_workspace_indexed)
    assert result["generated"] is True
    assert result["generation_id"].startswith("gen-")
    assert result["profile"] == "default"
    out = Path(result["output_dir"])
    assert (out / "overview.md").exists()
    assert (out / "memory.md").exists()
    assert (out / "semantic-bridge").exists()
    manifest = json.loads((out / "module-manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert manifest["modules"], "indexed demo should have at least one module"
    for entry in manifest["modules"]:
        assert entry["generation_id"] == result["generation_id"]
        assert entry["stale"] is False


def test_incremental_refresh_only_dirty_modules(demo_workspace_indexed: Path) -> None:
    generate_wiki(demo_workspace_indexed)
    result = generate_wiki(demo_workspace_indexed, dirty_paths=["article-service/src/main/java/Foo.java"])
    stats = result["refresh_stats"]
    assert stats["refreshed"], "dirty module should be refreshed"
    assert "article-service" in stats["refreshed"]
    # modules not touched by dirty paths are skipped and reused
    assert stats["skipped"], "unaffected modules should be skipped"


def test_force_regeneration_refreshes_all_modules(demo_workspace_indexed: Path) -> None:
    generate_wiki(demo_workspace_indexed)
    result = generate_wiki(demo_workspace_indexed, dirty_paths=["article-service/x"], force=True)
    assert result["refresh_stats"]["force"] is True
    assert result["refresh_stats"]["skipped"] == []


def test_mark_stale_and_wiki_status(demo_workspace_indexed: Path) -> None:
    assert wiki_status(demo_workspace_indexed)["generated"] is False
    generate_wiki(demo_workspace_indexed)
    marked = mark_wiki_modules_stale(demo_workspace_indexed, ["task-service/src/main/java/Bar.java"])
    assert marked["marked"] >= 1
    status = wiki_status(demo_workspace_indexed)
    assert status["has_stale"] is True
    assert "task-service" in status["stale_modules"]
    # targeted refresh clears staleness
    generate_wiki(demo_workspace_indexed, dirty_paths=["task-service/src/main/java/Bar.java"])
    assert wiki_status(demo_workspace_indexed)["has_stale"] is False


def test_l1_l2_context_are_bounded(demo_workspace_indexed: Path) -> None:
    l1 = get_l1_context(demo_workspace_indexed, budget="small")
    assert l1["level"] == "L1"
    assert l1["service_count"] >= 1
    generate_wiki(demo_workspace_indexed)
    module = l1["services"][0]["name"]
    l2 = get_l2_context(demo_workspace_indexed, module, budget="medium")
    assert l2["found"] is True
    assert l2["stale"] is False
    missing = get_l2_context(demo_workspace_indexed, "no-such-module")
    assert missing["found"] is False


def test_l3_bridge_query_and_profile_custom_mapping(demo_workspace_indexed: Path) -> None:
    update_wiki_profile(
        demo_workspace_indexed,
        {
            "profile_id": "ucap",
            "custom_mappings": [{"term": "积分发放", "targets": ["PointService.grant"], "bridge_type": "business_term"}],
        },
        actor="tester",
    )
    result = generate_wiki(demo_workspace_indexed)
    assert result["profile"] == "ucap"
    bridge = get_l3_bridge(demo_workspace_indexed, query="积分发放")
    assert bridge["found"] is True
    assert bridge["bridges"][0]["bridge_type"] == "business_term"
    typed = get_l3_bridge(demo_workspace_indexed, bridge_type="business_term")
    assert typed["found"] is True


def test_resume_check_contains_l1_context(demo_workspace_indexed: Path) -> None:
    from memory_center.core.orchestrator.resume_check import workspace_task_resume_check

    result = workspace_task_resume_check(demo_workspace_indexed, budget="small")
    assert "l1_context" in result
    assert result["l1_context"].get("level") == "L1"
