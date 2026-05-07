from pathlib import Path
import json
import socket
import threading
from urllib.request import urlopen

from memory_center.core.config import load_workspace_config
from memory_center.core.exporters import export_mermaid
from memory_center.core.indexer import reindex_workspace
from memory_center.core.orchestrator import workspace_sniff, workspace_trace
from memory_center.core.registry import add_to_group, create_group, register_workspace
from memory_center.core.rules import ensure_default_rules
from memory_center.core.store import WorkspaceStore
from memory_center.core.validators import doctor
from memory_center.http.server import create_handler


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
    assert counts["semantic_docs"] > 0

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
    from memory_center.core.orchestrator import memory_context, memory_impact, memory_query, workspace_status
    from memory_center.core.rules import ensure_default_rules
    from memory_center.core.store import WorkspaceStore

    workspace = "examples/spring-cloud-demo/.memory-center/workspace.yaml"
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    counts = reindex_workspace(config, store)

    assert counts["graph_nodes"] > 0
    assert counts["graph_edges"] > 0
    assert counts["semantic_docs"] > 0
    query_result = memory_query(workspace, "oldPubTime ArticleFeignClient", 5)
    assert query_result["matches"]
    assert query_result["semantic_hits"]
    status = workspace_status(workspace)
    assert status["semantic_index"]["ready"] is True
    assert status["index_counts"]["semantic_docs"] > 0
    assert memory_context(workspace, "ArticleFeignClient")["found"] is True
    assert memory_impact(workspace, "MoveArticleRequest")["found"] is True


def test_trusted_graph_edges_and_evidence_based_impact(tmp_path: Path):
    import shutil
    from memory_center.core.config import load_workspace_config
    from memory_center.core.graph import GraphStore
    from memory_center.core.indexer import reindex_workspace
    from memory_center.core.orchestrator import memory_impact
    from memory_center.core.store import WorkspaceStore

    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "trusted-demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)
    graph = GraphStore(store.graph_db_path)

    field = graph.find_nodes("newPubTime", types=["Field"], limit=5)[0]
    upstream = graph.neighbors(field["id"], direction="upstream", max_depth=3, limit=100)
    assert any(edge["type"] == "READS_FIELD" for edge in upstream)
    assert any(edge["evidence"] for edge in upstream)
    assert any(edge["source"]["name"] == "ArticleMoveConsumer.consume" for edge in upstream)

    urlmd5 = graph.find_nodes("urlmd5", types=["Field"], limit=5)[0]
    urlmd5_upstream = graph.neighbors(urlmd5["id"], direction="upstream", max_depth=3, limit=100)
    assert any(edge["type"] == "READS_FIELD" and edge["source"]["name"] == "ArticleMoveService.move" for edge in urlmd5_upstream)

    consumer = graph.find_nodes("ArticleMoveConsumer", types=["Class"], limit=5)[0]
    consumer_outgoing = graph.neighbors(consumer["id"], direction="downstream", max_depth=1, limit=50)
    assert any(edge["type"] == "INJECTS_BEAN" and edge["target"]["name"] == "ArticleMoveService" for edge in consumer_outgoing)

    move_service = graph.find_nodes("ArticleMoveService", types=["Class"], limit=5)[0]
    service_outgoing = graph.neighbors(move_service["id"], direction="downstream", max_depth=1, limit=50)
    assert any(edge["type"] == "INJECTS_BEAN" and edge["target"]["name"] == "ArticleFeignClient" for edge in service_outgoing)

    impact = memory_impact(workspace, "newPubTime", direction="upstream")
    assert impact["found"] is True
    assert "confirmed_impacts" in impact
    assert "probable_impacts" in impact
    assert "possible_impacts" in impact
    assert "unknown_risks" in impact

    report = doctor(workspace, self_test=True)
    assert report["ok"] is True
    assert report["self_test"]["query_matches"] > 0
    assert any(item["name"] == "semantic:docs" and item["ok"] for item in report["checks"])


def test_group_query_and_status(tmp_path: Path):
    from memory_center.core.orchestrator import group_impact, group_query, group_status

    workspace_a = _copy_demo_workspace(tmp_path, "group-demo-a")
    workspace_b = _copy_demo_workspace(tmp_path, "group-demo-b")
    for workspace in [workspace_a, workspace_b]:
        config = load_workspace_config(workspace)
        store = WorkspaceStore(workspace)
        ensure_default_rules(store)
        reindex_workspace(config, store)

    home = tmp_path / "home" / ".memory-center"
    register_workspace("demo-a", workspace_a, home=home)
    register_workspace("demo-b", workspace_b, home=home)
    create_group("backend-platform", home=home)
    add_to_group("backend-platform", "demo-a", home=home)
    add_to_group("backend-platform", "demo-b", home=home)

    status = group_status("backend-platform", home=home)
    assert status["workspace_count"] == 2
    assert status["index_totals"]["files"] >= 10
    assert status["bridge_counts"]["FEIGN_SERVICE"] >= 2
    assert status["bridge_counts"]["FEIGN_ENDPOINT"] >= 2
    assert status["bridge_counts"]["MQ_TOPIC_CONFIG"] >= 2

    result = group_query("backend-platform", "ArticleFeignClient", limit=5, home=home)
    assert result["workspace_count"] == 2
    assert result["merged_matches"]
    assert any(item["node"]["name"] == "ArticleFeignClient" for item in result["merged_matches"])
    assert result["target_types"][0] == "FeignClient"
    assert result["merged_matches"][0]["node"]["type"] == "FeignClient"
    assert any(bridge["type"] in {"FEIGN_SERVICE", "FEIGN_ENDPOINT"} for bridge in result["related_bridges"])

    mq_result = group_query("backend-platform", "article-pubtime-change", limit=10, home=home)
    assert any(bridge["type"] == "MQ_TOPIC_CONFIG" for bridge in mq_result["related_bridges"])

    impact = group_impact("backend-platform", "ArticleFeignClient", home=home)
    assert impact["found"] is True
    assert impact["risk_level"] in {"high", "medium"}
    assert impact["impacted_workspaces"] == ["demo-a", "demo-b"]
    assert "FeignClient" in impact["target_types"]
    assert impact["confirmed_impacts"] or impact["probable_impacts"]
    assert all(bridge["type"] in {"FEIGN_SERVICE", "FEIGN_ENDPOINT"} for bridge in impact["related_bridges"])
    assert impact["related_bridges"][0]["type"] == "FEIGN_ENDPOINT"
    assert all(
        item["impact"]["type"] not in {"CONTAINS", "DECLARES"}
        for item in impact["confirmed_impacts"] + impact["probable_impacts"] + impact["possible_impacts"]
        if item.get("kind") == "graph"
    )
    graph_types = [item["impact"]["type"] for item in impact["confirmed_impacts"] + impact["probable_impacts"] if item.get("kind") == "graph"]
    assert "INJECTS_BEAN" in graph_types
    assert "IMPORTS" in graph_types
    assert graph_types.index("INJECTS_BEAN") < graph_types.index("IMPORTS")

    topic_impact = group_impact("backend-platform", "article-pubtime-change", home=home)
    assert topic_impact["found"] is True
    assert all(bridge["type"] in {"MQ_TOPIC_CONFIG", "MQ_TOPIC_SHARED"} for bridge in topic_impact["related_bridges"])
    assert topic_impact["related_bridges"][0]["type"] == "MQ_TOPIC_CONFIG"


def test_http_bridge_routes(tmp_path: Path):
    from http.server import ThreadingHTTPServer

    workspace = _copy_demo_workspace(tmp_path, "http-demo")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    ensure_default_rules(store)
    reindex_workspace(config, store)

    home = tmp_path / "home" / ".memory-center"
    register_workspace("http-demo", workspace, home=home)
    create_group("http-group", home=home)
    add_to_group("http-group", "http-demo", home=home)

    # Route closures use the default registry home, so point HOME at the temp registry.
    import os
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home.parent)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", _free_port()), create_handler(workspace))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"

        health = json.loads(urlopen(f"{base}/health").read().decode("utf-8"))
        assert health["ok"] is True

        status = json.loads(urlopen(f"{base}/group/status?group=http-group").read().decode("utf-8"))
        assert status["workspace_count"] == 1
        assert "bridge_counts" in status

        query = json.loads(urlopen(f"{base}/workspace/query?text=ArticleFeignClient").read().decode("utf-8"))
        assert query["matches"]

        group_query_payload = json.loads(urlopen(f"{base}/group/query?group=http-group&text=article-pubtime-change").read().decode("utf-8"))
        assert group_query_payload["related_bridges"]

        group_impact_payload = json.loads(urlopen(f"{base}/group/impact?group=http-group&target=ArticleFeignClient").read().decode("utf-8"))
        assert group_impact_payload["found"] is True
        assert "FeignClient" in group_impact_payload["target_types"]
    finally:
        server.shutdown()
        server.server_close()
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


def _copy_demo_workspace(tmp_path: Path, name: str) -> Path:
    import shutil

    source = Path("examples/spring-cloud-demo")
    target = tmp_path / name
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return workspace


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
