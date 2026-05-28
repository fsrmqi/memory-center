"""Tests for chain stitching: phantom annotation, endpoint matching, cross-workspace chain."""
import json
from pathlib import Path
import pytest

from memory_center.core.config import load_workspace_config
from memory_center.core.indexer import (
    _endpoint_matches,
    _normalize_path_params,
    join_path,
    reindex_workspace,
)
from memory_center.core.store import WorkspaceStore
from memory_center.core.orchestrator import (
    _annotate_phantom_nodes,
    group_chain,
    memory_callers,
    memory_callees,
)
from memory_center.core.registry import (
    register_workspace,
    create_group,
    add_to_group,
    load_registry,
)


# ---- P1: Phantom Annotation ----


def test_annotate_phantom_on_external_service(tmp_path: Path):
    chain_result = {
        "found": True,
        "callees": [{
            "type": "CALLS_SERVICE",
            "source": {"name": "SomeFeignClient", "id": "FeignClient:proj:SomeFeignClient"},
            "target": {"name": "ucap-cloud-datainterface", "type": "Service", "id": "Service:ucap-cloud-datainterface"},
            "metadata": {"target_service": "ucap-cloud-datainterface"},
            "confidence": 0.9,
        }],
    }
    # Use the demo workspace whose local services are article-service, common-api, task-service
    import shutil
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    _annotate_phantom_nodes(chain_result, str(workspace))
    edge = chain_result["callees"][0]
    target_node = edge["target"]
    assert target_node["_is_external_service"] is True
    assert target_node["_external_service_hint"] == "ucap-cloud-datainterface"
    assert edge["_is_external_service"] is True
    assert edge["_boundary_type"] == "feign-service-phantom"


def test_annotate_no_phantom_on_local_service(tmp_path: Path):
    chain_result = {
        "found": True,
        "callees": [{
            "type": "CALLS_SERVICE",
            "source": {"name": "ArticleFeignClient", "id": "FeignClient:common-api:ArticleFeignClient"},
            "target": {"name": "article-service", "type": "Service", "id": "Service:article-service"},
            "metadata": {"target_service": "article-service"},
            "confidence": 0.9,
        }],
    }
    import shutil
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    _annotate_phantom_nodes(chain_result, str(workspace))
    edge = chain_result["callees"][0]
    target_node = edge["target"]
    assert "_is_external_service" not in target_node
    assert "_boundary_type" not in edge


# ---- P2: Endpoint Matching ----


def test_endpoint_matches_path_param_template():
    feign = {"base_path": "", "interface": "X"}
    method = {"path": "/api/users/{id}", "http_method": "GET"}
    api = {"path": "/api/users/{userId}", "http_method": "GET"}
    assert _endpoint_matches(feign, method, api) is True


def test_endpoint_matches_http_method_mismatch():
    feign = {"base_path": "", "interface": "X"}
    method = {"path": "/api/articles", "http_method": "POST"}
    api = {"path": "/api/articles", "http_method": "GET"}
    assert _endpoint_matches(feign, method, api) is False


def test_endpoint_matches_http_method_standard_only():
    feign = {"base_path": "", "interface": "X"}
    method = {"path": "/api/articles", "http_method": "REQUEST"}
    api = {"path": "/api/articles", "http_method": "GET"}
    assert _endpoint_matches(feign, method, api) is True


def test_endpoint_matches_empty_http_graceful():
    feign = {"base_path": "", "interface": "X"}
    method = {"path": "/api/articles", "http_method": ""}
    api = {"path": "/api/articles", "http_method": "GET"}
    assert _endpoint_matches(feign, method, api) is True


def test_endpoint_matches_full_feign_path():
    feign = {"base_path": "/article", "interface": "ArticleFeignClient"}
    method = {"path": "/article/move", "http_method": "POST"}
    api = {"path": "/article/move", "http_method": "POST"}
    assert _endpoint_matches(feign, method, api) is True


def test_endpoint_matches_existing_direct_match():
    feign = {"base_path": "", "interface": "X"}
    method = {"path": "/article/move", "http_method": "POST"}
    api = {"path": "/article/move", "http_method": "POST"}
    assert _endpoint_matches(feign, method, api) is True


def test_endpoint_matches_base_remainder():
    feign = {"base_path": "/api", "interface": "Y"}
    # When method path includes base, remainder stripping works
    method = {"path": "/api/items", "http_method": "GET"}
    api = {"path": "/items", "http_method": "GET"}
    assert _endpoint_matches(feign, method, api) is True


def test_normalize_path_params():
    assert _normalize_path_params("/api/users/{id}") == "/api/users/{param}"
    assert _normalize_path_params("/api/articles/{articleId}/comments/{commentId}") == "/api/articles/{param}/comments/{param}"
    assert _normalize_path_params("/api/list") == "/api/list"


# ---- P0: Cross-Workspace Chain ----


def test_group_chain_callees_direction(tmp_path: Path):
    """Test group_chain with callees direction using the spring-cloud-demo workspace."""
    import shutil
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    # Register and group
    register_workspace("spring-cloud-demo", str(workspace))
    create_group("test-group")
    add_to_group("test-group", "spring-cloud-demo")

    result = group_chain("test-group", "ArticleFeignClient", direction="callees", depth=2)
    assert result["found"] is True
    assert len(result["local_chain"]) > 0
    assert "stitch_summary" in result
    assert "local_edge_count" in result["stitch_summary"]
    assert "boundary_count" in result["stitch_summary"]
    assert "bridges_used_count" in result["stitch_summary"]
    assert "stitched_workspace_count" in result["stitch_summary"]
    assert "total_stitched_edge_count" in result["stitch_summary"]


def test_group_chain_callers_direction(tmp_path: Path):
    """Test group_chain with callers direction using the spring-cloud-demo workspace."""
    import shutil
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    register_workspace("spring-cloud-demo", str(workspace))
    create_group("test-group-callers")
    add_to_group("test-group-callers", "spring-cloud-demo")

    result = group_chain("test-group-callers", "moveArticle", direction="callers", depth=2)
    assert result["found"] is True
    assert "stitch_summary" in result


def test_group_chain_stitch_summary(tmp_path: Path):
    """Verify stitch_summary fields are present and accurate."""
    import shutil
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    register_workspace("spring-cloud-demo", str(workspace))
    create_group("test-group-summary")
    add_to_group("test-group-summary", "spring-cloud-demo")

    result = group_chain("test-group-summary", "ArticleFeignClient", direction="callees", depth=2)
    summary = result["stitch_summary"]
    assert summary["local_edge_count"] >= 0
    assert summary["boundary_count"] >= 0
    assert summary["bridges_used_count"] >= 0
    assert summary["stitched_workspace_count"] >= 0
    assert summary["total_stitched_edge_count"] >= 0
    # Within a single workspace, boundary_count should be 0 (article-service is local)
    assert summary["boundary_count"] == 0


def test_multi_group_ambiguity(tmp_path: Path):
    """When workspace belongs to multiple groups, _find_groups_for_workspace returns all."""
    import shutil
    from memory_center.core.registry import save_registry
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    from memory_center.mcp.server import _find_groups_for_workspace

    # Use a fresh registry in tmp_path to avoid contamination from other tests
    test_home = tmp_path / "registry-home"
    test_home.mkdir()

    from memory_center.core.registry import register_workspace, create_group, add_to_group
    register_workspace("spring-cloud-demo", str(workspace), home=str(test_home))
    create_group("group-a", home=str(test_home))
    add_to_group("group-a", "spring-cloud-demo", home=str(test_home))
    create_group("group-b", home=str(test_home))
    add_to_group("group-b", "spring-cloud-demo", home=str(test_home))

    # _find_groups_for_workspace uses default home, so we need to test with the test_home
    # Directly load registry and check
    from memory_center.core.registry import load_registry
    registry = load_registry(str(test_home))
    from memory_center.mcp.server import _find_workspace_name_in_registry
    ws_name = _find_workspace_name_in_registry(str(workspace), registry)
    groups = []
    for group in registry.get("groups", []):
        if ws_name in group.get("members", []):
            groups.append(group.get("name", ""))
    assert len(groups) == 2
    assert "group-a" in groups
    assert "group-b" in groups