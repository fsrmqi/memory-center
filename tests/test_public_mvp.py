from pathlib import Path

from memory_center.core.config import load_workspace_config
from memory_center.core.exporters import export_mermaid
from memory_center.core.indexer import reindex_workspace
from memory_center.core.orchestrator import workspace_sniff, workspace_trace
from memory_center.core.rules import ensure_default_rules
from memory_center.core.store import WorkspaceStore
from memory_center.core.validators import doctor


def test_demo_workspace_indexes_spring_cloud_patterns(tmp_path: Path):
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    import shutil
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"

    # Force an absolute fixture root after copying.
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    counts = reindex_workspace(config, store)
    ensure_default_rules(store)

    assert counts["files"] >= 5
    assert counts["apis"] >= 1
    assert counts["feigns"] >= 1
    assert counts["mq"] >= 1

    sniffed = workspace_sniff(workspace, "oldPubTime newPubTime Kafka ArticleFeignClient move")
    assert sniffed["candidate_files"]
    assert sniffed["related_rules"]

    traced = workspace_trace(workspace, "article-pubtime-change")
    assert traced["matched_mq"]

    diagram = export_mermaid(workspace)
    assert "flowchart LR" in diagram
    assert "article-service" in diagram

    report = doctor(workspace)
    assert report["ok"] is True


def test_graph_query_context_and_impact(tmp_path):
    from memory_center.core.config import load_workspace_config
    from memory_center.core.indexer import reindex_workspace
    from memory_center.core.orchestrator import memory_context, memory_impact, memory_query
    from memory_center.core.rules import ensure_default_rules
    from memory_center.core.store import WorkspaceStore

    workspace = "examples/spring-cloud-demo/.memory-center/workspace.yaml"
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    counts = reindex_workspace(config, store)

    assert counts["graph_nodes"] > 0
    assert counts["graph_edges"] > 0
    assert memory_query(workspace, "oldPubTime ArticleFeignClient", 5)["matches"]
    assert memory_context(workspace, "ArticleFeignClient")["found"] is True
    assert memory_impact(workspace, "MoveArticleRequest")["found"] is True
