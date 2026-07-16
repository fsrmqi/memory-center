from pathlib import Path

from memory_center.core.config import load_workspace_config
from memory_center.core.contracts import CONTRACT_DIFF_FILE
from memory_center.core.indexer import reindex_workspace
from memory_center.core.orchestrator.workspace import workspace_check_contract
from memory_center.core.store import WorkspaceStore


def test_dto_field_removal_is_breaking_contract_change(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    config = load_workspace_config(workspace)
    reindex_workspace(config, store, parallel=False)
    source = Path(config.root_path) / "common-api/src/main/java/com/example/api/MoveArticleRequest.java"
    source.write_text(source.read_text(encoding="utf-8").replace("    private String oldPubTime;\n", ""), encoding="utf-8")

    reindex_workspace(config, store, projects=["common-api"], parallel=False)
    report = workspace_check_contract(workspace, "MoveArticleRequest.java", "modify")
    diff = store.read_json_prefer_backend(CONTRACT_DIFF_FILE, {})

    assert diff["breaking_count"] >= 1
    assert report["semantic_compatibility"]["status"] == "block"
    assert any(change["change_type"] == "field_removed" for change in report["semantic_compatibility"]["breaking_changes"])


def test_first_contract_snapshot_is_non_blocking_baseline(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)
    reindex_workspace(load_workspace_config(workspace), store, parallel=False)

    report = workspace_check_contract(workspace, "ArticleFeignClient.java", "modify")

    assert report["semantic_compatibility"]["baseline_available"] is False
    assert report["semantic_compatibility"]["status"] != "block"
