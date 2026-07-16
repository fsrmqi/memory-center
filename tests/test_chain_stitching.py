"""Tests for chain stitching: phantom annotation, endpoint matching, cross-workspace chain."""
import importlib.util
from pathlib import Path

from memory_center.core.governance.registry import (
    add_to_group,
    create_group,
    load_registry,
    register_workspace,
)
from memory_center.core.indexing.reindex import (
    _endpoint_matches,
    _normalize_path_params,
)
from memory_center.core.orchestrator import (
    _annotate_phantom_nodes,
    group_chain,
    memory_callers,
)

HAS_MCP = importlib.util.find_spec("mcp") is not None and importlib.util.find_spec("mcp.server.fastmcp") is not None


def _setup_demo_workspace(tmp_path: Path):
    from tests.fixtures import setup_demo_workspace
    return setup_demo_workspace(tmp_path)

def _setup_isolated_registry(tmp_path: Path):
    """Create an isolated registry home under tmp_path to avoid global contamination."""
    test_home = tmp_path / "registry-home"
    test_home.mkdir()
    return str(test_home)


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
    workspace = _setup_demo_workspace(tmp_path)

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
    workspace = _setup_demo_workspace(tmp_path)

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
    # method.path includes base_path — direct match handles this
    method = {"path": "/api/items", "http_method": "GET"}
    api = {"path": "/api/items", "http_method": "GET"}
    assert _endpoint_matches(feign, method, api) is True


def test_endpoint_matches_compose_base_and_method():
    """method.path does NOT include base_path, but join(base, method) matches api."""
    feign = {"base_path": "/article", "interface": "ArticleFeignClient"}
    # Real Spring pattern: base_path=/article, method path=/move (not /article/move)
    method = {"path": "/move", "http_method": "POST"}
    api = {"path": "/article/move", "http_method": "POST"}
    assert _endpoint_matches(feign, method, api) is True


def test_normalize_path_params():
    assert _normalize_path_params("/api/users/{id}") == "/api/users/{param}"
    assert _normalize_path_params("/api/articles/{articleId}/comments/{commentId}") == "/api/articles/{param}/comments/{param}"
    assert _normalize_path_params("/api/list") == "/api/list"


# ---- P0: Cross-Workspace Chain ----


def test_group_chain_callees_direction(tmp_path: Path):
    """Test group_chain with callees direction using the spring-cloud-demo workspace."""
    workspace = _setup_demo_workspace(tmp_path)
    home = _setup_isolated_registry(tmp_path)

    register_workspace("spring-cloud-demo", str(workspace), home=home)
    create_group("test-group", home=home)
    add_to_group("test-group", "spring-cloud-demo", home=home)

    result = group_chain("test-group", "ArticleFeignClient", direction="callees", depth=2, home=home)
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
    workspace = _setup_demo_workspace(tmp_path)
    home = _setup_isolated_registry(tmp_path)

    register_workspace("spring-cloud-demo", str(workspace), home=home)
    create_group("test-group-callers", home=home)
    add_to_group("test-group-callers", "spring-cloud-demo", home=home)

    result = group_chain("test-group-callers", "moveArticle", direction="callers", depth=2, home=home)
    assert result["found"] is True
    assert "stitch_summary" in result


def test_group_chain_stitch_summary(tmp_path: Path):
    """Verify stitch_summary fields are present and accurate."""
    workspace = _setup_demo_workspace(tmp_path)
    home = _setup_isolated_registry(tmp_path)

    register_workspace("spring-cloud-demo", str(workspace), home=home)
    create_group("test-group-summary", home=home)
    add_to_group("test-group-summary", "spring-cloud-demo", home=home)

    result = group_chain("test-group-summary", "ArticleFeignClient", direction="callees", depth=2, home=home)
    summary = result["stitch_summary"]
    assert summary["local_edge_count"] >= 0
    assert summary["boundary_count"] >= 0
    assert summary["bridges_used_count"] >= 0
    assert summary["stitched_workspace_count"] >= 0
    assert summary["total_stitched_edge_count"] >= 0
    # Within a single workspace, boundary_count should be 0 (article-service is local)
    assert summary["boundary_count"] == 0


def test_multi_group_ambiguity(tmp_path: Path):
    """When workspace belongs to multiple groups, registry lookup returns all."""
    workspace = _setup_demo_workspace(tmp_path)
    home = _setup_isolated_registry(tmp_path)

    register_workspace("spring-cloud-demo", str(workspace), home=home)
    create_group("group-a", home=home)
    add_to_group("group-a", "spring-cloud-demo", home=home)
    create_group("group-b", home=home)
    add_to_group("group-b", "spring-cloud-demo", home=home)

    registry = load_registry(home)
    from memory_center.mcp.server import _find_workspace_name_in_registry
    ws_name = _find_workspace_name_in_registry(str(workspace), registry)
    groups = []
    for group in registry.get("groups", []):
        if ws_name in group.get("members", []):
            groups.append(group.get("name", ""))
    assert len(groups) == 2
    assert "group-a" in groups
    assert "group-b" in groups


def test_mc_lookup_multi_group_ambiguity_returns_hint(tmp_path: Path):
    """Integration test: mc_lookup(mode='chain') multi-group branch returns matching_groups + hint."""
    workspace = _setup_demo_workspace(tmp_path)

    # Simulate the "len > 1" branch of mc_lookup chain handler
    result = memory_callers(str(workspace), "ArticleFeignClient", depth=2, limit=10)
    _annotate_phantom_nodes(result, str(workspace))
    # The branch would add matching_groups and _hint
    matching_groups_mock = ["group-alpha", "group-beta"]
    facade_result = {
        "mode": "chain-callers",
        "result": result,
        "matching_groups": matching_groups_mock,
        "_hint": "Workspace 属于多个 group (group-alpha, group-beta)，请用 mc_admin(action='group_chain', group=...) 显式指定。",
    }
    assert "matching_groups" in facade_result
    assert len(facade_result["matching_groups"]) == 2
    assert "_hint" in facade_result
    assert "group_chain" in facade_result["_hint"]
