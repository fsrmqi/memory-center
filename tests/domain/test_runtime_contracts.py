from pathlib import Path

from memory_center.core.contracting.runtime import (
    ingest_runtime_contract_samples,
    runtime_contract_compatibility,
    set_contract_migration,
)
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config


def test_active_runtime_dto_usage_blocks_breaking_change_until_migrated(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store, parallel=False)
    source = Path(config.root_path) / "common-api/src/main/java/com/example/api/MoveArticleRequest.java"
    source.write_text(source.read_text(encoding="utf-8").replace("    private String oldPubTime;\n", ""), encoding="utf-8")
    reindex_workspace(config, store, projects=["common-api"], parallel=False)

    ingested = ingest_runtime_contract_samples(
        workspace,
        [{"kind": "api", "service": "article-service", "path": "/article/move", "http_method": "POST", "dto": "MoveArticleRequest", "field_names": ["oldPubTime"], "success_count": 20}],
    )
    blocked = runtime_contract_compatibility(workspace, "MoveArticleRequest.java")
    finding = next(item for item in blocked["breaking_runtime_findings"] if item["status"] == "block")
    set_contract_migration(workspace, {"contract_key": finding["contract_key"], "state": "dual_read", "approved_by": "test"})
    mitigated = runtime_contract_compatibility(workspace, "MoveArticleRequest.java")

    assert ingested["accepted"] == 1
    assert blocked["status"] == "block"
    assert mitigated["status"] == "attention"


def test_runtime_ingest_rejects_payload_content(tmp_path: Path) -> None:
    from tests.fixtures import copy_demo_workspace

    workspace = copy_demo_workspace(tmp_path)
    result = ingest_runtime_contract_samples(
        workspace,
        [{"kind": "api", "service": "demo", "path": "/x", "http_method": "GET", "payload": {"secret": "never-store"}}],
    )

    assert result["accepted"] == 0
    assert result["rejected"]
