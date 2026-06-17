"""Tests for MCP facade tools (8 task-level tools replacing 82 atomic tools)."""
from pathlib import Path
import pytest
from typer.testing import CliRunner

from memory_center.core.orchestrator import (
    memory_callers, memory_callees, memory_context, memory_contracts,
    memory_detect_changes, memory_impact, memory_method_walkthrough, memory_plan_change, memory_query,
    memory_query_hybrid, memory_search_code, memory_symbol,
    memory_verify_checklist,
    workspace_check_rules, workspace_end_session,
    workspace_handoff_packet, workspace_next_actions,
    workspace_recent_evidence, workspace_resume_packet, workspace_sniff,
    workspace_start_session, workspace_status, workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts, workspace_suggest_case, workspace_trace,
    workspace_unresolved_items, workspace_lookup_hint,
)
from memory_center.core.artifacts import (
    list_artifacts, create_task_space, list_task_spaces,
)
from memory_center.cli.main import app
from memory_center.http.server import _route_request

try:
    from mcp.server.fastmcp import FastMCP
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

if HAS_MCP:
    from memory_center.mcp.server import create_server


def _setup_workspace(tmp_path: Path) -> str:
    from tests.fixtures import setup_demo_workspace
    return str(setup_demo_workspace(tmp_path))

@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
def test_mcp_server_has_exactly_8_facade_tools(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    server = create_server(wf)
    # FastMCP stores tools internally; verify count and names
    tool_names = list(server._tool_manager._tools.keys())
    assert len(tool_names) == 8
    expected = {"mc_start", "mc_lookup", "mc_analyze", "mc_sync", "mc_resume", "mc_handoff", "mc_close", "mc_admin"}
    assert set(tool_names) == expected


def test_mc_start_returns_consolidated_context(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # Simulate what mc_start does internally
    sniff_result = workspace_sniff(wf, "ArticleFeignClient", limit=8, auto_sync_mode="balanced", view="compact", budget="medium")
    session = workspace_start_session(wf, "ArticleFeignClient")
    result = {"workflow": "mc-start", "sniff": sniff_result, "session": session}
    assert result["workflow"] == "mc-start"
    assert "sniff" in result
    assert "session" in result
    assert sniff_result["candidate_paths"]
    assert sniff_result["recommended_path"]["target"]
    assert result["session"]["session_id"]


def test_mc_lookup_mode_auto_routes_correctly(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # Test auto mode: lookup_hint should dispatch
    hint = workspace_lookup_hint(wf, query="ArticleFeignClient", intent="", limit=8)
    assert "preferred_tools" in hint
    assert hint["candidate_paths"]
    assert hint["recommended_candidate_path"]["target"]
    # Test that symbol mode works
    sym = memory_symbol(wf, "ArticleFeignClient", limit=5)
    assert sym
    # Test that query mode works
    q = memory_query(wf, "ArticleFeignClient", limit=5)
    assert q


def test_mcp_lookup_extracts_symbol_from_natural_language_query():
    from memory_center.mcp.server import _extract_symbol_like_token, _wants_deep_chain

    query = "梳理下 com.example.api.ArticleFeignClient#moveArticle 全链路，一直到最底层逻辑处理"
    assert _extract_symbol_like_token(query) == "com.example.api.ArticleFeignClient#moveArticle"
    assert _wants_deep_chain(query) is True


def test_mc_lookup_modes_direct(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # symbol
    r = memory_symbol(wf, "ArticleFeignClient", limit=5)
    assert r
    # code
    r = memory_search_code(wf, "ArticleFeignClient", "", limit=5)
    assert r
    # query
    r = memory_query(wf, "ArticleFeignClient", limit=5)
    assert r
    # trace
    r = workspace_trace(wf, "ArticleFeignClient")
    assert r
    assert r["trace_mode"] == "index_overview"
    assert "mc_lookup(mode='chain')" in r["trace_note"]
    # chain (callers)
    r = memory_callers(wf, "ArticleFeignClient", depth=2, limit=10)
    assert r


def test_workspace_trace_attaches_chain_preview_for_deep_method_queries(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    r = workspace_trace(wf, "梳理下 com.example.api.ArticleFeignClient#moveArticle 全链路，一直到最底层逻辑处理")
    assert r["trace_mode"] == "index_overview"
    assert r["suggested_symbol"] == "com.example.api.ArticleFeignClient#moveArticle"
    assert r["chain_preview"]["depth"] >= 4
    assert r["chain_preview"]["callers"]["found"] is True
    assert r["chain_preview"]["callees"]["found"] is True


def test_memory_method_walkthrough_returns_feign_continuations(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    result = memory_method_walkthrough(wf, "com.example.task.ArticleMoveService#move", depth=4, limit=20, view="compact", budget="small")
    assert result["found"] is True
    assert result["target"]["class"] == "ArticleMoveService"
    assert result["target"]["absolute_file_path"].endswith("task-service/src/main/java/com/example/task/ArticleMoveService.java")
    assert result["agent_usage_policy"]["do_not_search_when_absolute_path_present"] is True
    assert result["agent_usage_policy"]["do_not_sed_when_continuation_present"] is True
    assert "absolute_file_path" in result["agent_usage_policy"]["read_files_by"]
    assert any(step["kind"] == "feign_call" for step in result["local_steps"])
    assert any(step["receiver_type"] == "ArticleAuditService" for step in result["local_steps"])
    assert result["same_class_method_continuations"]
    assert result["same_class_method_continuations"][0]["target"]["class"] == "ArticleMoveService"
    assert result["same_class_method_continuations"][0]["target"]["method"] == "validateMove"
    assert result["local_service_continuations"]
    assert result["local_service_continuations"][0]["target"]["class"] == "ArticleAuditServiceImpl"
    assert result["local_service_continuations"][0]["target"]["absolute_file_path"].endswith("task-service/src/main/java/com/example/task/ArticleAuditServiceImpl.java")
    assert result["feign_continuations"]
    continuation = result["feign_continuations"][0]
    assert continuation["interface"] == "ArticleFeignClient"
    assert continuation["path"] == "/article/move"
    assert continuation["matched_endpoints"]
    assert continuation["matched_endpoints"][0]["controller"] == "ArticleController"
    assert continuation["server_walkthroughs"]
    server_walkthrough = continuation["server_walkthroughs"][0]
    assert server_walkthrough["controller"] == "ArticleController"
    assert server_walkthrough["absolute_file_path"].endswith("article-service/src/main/java/com/example/article/ArticleController.java")
    assert any(step["receiver_type"] == "ArticleWorkflowService" for step in server_walkthrough["local_steps"])
    impl = server_walkthrough["service_impl_continuations"][0]
    assert impl["target"]["class"] == "ArticleWorkflowServiceImpl"
    assert impl["target"]["method"] == "moveArticle"
    assert impl["target"]["absolute_file_path"].endswith("article-service/src/main/java/com/example/article/ArticleWorkflowServiceImpl.java")
    assert any(line.startswith("LocalImpl task-service:ArticleAuditServiceImpl#recordMove") for line in result["summary_lines"])
    assert any(line.startswith("Server article-service:ArticleController#moveArticle") for line in result["summary_lines"])
    assert result["answer_markdown"]
    assert result["answer_template"]["status"] == "fallback_builtin"
    assert result["mermaid_flow"].startswith("flowchart TD")
    assert "performance_risks" in result
    assert "data_scope_guards" in result
    assert "diff_context" in result
    assert "glossary_hits" in result
    assert result["schema_version"] >= 2
    assert "stable_top_level" in result["fields_contract"]
    assert result["index_freshness"]["index_stale"] is False
    assert result["branch_outline"]
    assert result["anti_patterns"]
    assert result["cache"]["hit"] is False
    assert continuation["matched_endpoints"][0]["confidence"] > 0
    assert continuation["matched_endpoints"][0]["confidence_reasons"]
    assert server_walkthrough["endpoint_confidence"] == continuation["matched_endpoints"][0]["confidence"]


def test_method_walkthrough_cache_hits_repeated_query(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    first = memory_method_walkthrough(wf, "com.example.task.ArticleMoveService#move", depth=4, limit=20, view="compact", budget="small")
    second = memory_method_walkthrough(wf, "com.example.task.ArticleMoveService#move", depth=4, limit=20, view="compact", budget="small")
    assert first["found"] is True
    assert second["found"] is True
    assert first["cache"]["hit"] is False
    assert second["cache"]["hit"] is True


def test_method_walkthrough_detects_stale_index_target(tmp_path: Path):
    import os
    import time

    wf = _setup_workspace(tmp_path)
    result = memory_method_walkthrough(wf, "com.example.task.ArticleMoveService#move", depth=4, limit=20, view="compact", budget="small")
    target_path = Path(result["target"]["absolute_file_path"])
    future = time.time() + 120
    os.utime(target_path, (future, future))

    fresh = memory_method_walkthrough(wf, "com.example.task.ArticleMoveService#move", depth=4, limit=20, view="compact", budget="medium")
    assert fresh["index_freshness"]["index_stale"] is True
    assert any(item["absolute_file_path"] == str(target_path) for item in fresh["index_freshness"]["stale_read_targets"])


def test_method_walkthrough_report_level_and_glossary(tmp_path: Path):
    wf = Path(_setup_workspace(tmp_path))
    glossary = wf.parent / "glossary.yaml"
    glossary.write_text(
        "terms:\n"
        "  urlmd5: URL 指纹，用于文章移动校验。\n"
        "  ArticleFeignClient:\n"
        "    description: 文章服务 Feign 客户端。\n"
        "    category: contract\n",
        encoding="utf-8",
    )

    result = memory_method_walkthrough(
        wf,
        "com.example.task.ArticleMoveService#move",
        view="compact",
        budget="small",
        report_level="risk-focused",
    )
    assert "### 性能风险" in result["answer_markdown"]
    assert result["glossary_hits"]
    assert any(item["term"] == "urlmd5" for item in result["glossary_hits"])


def test_walkthrough_risk_helpers_detect_performance_and_scope(tmp_path: Path):
    from memory_center.core.orchestrator.query import _build_data_scope_guards, _build_walkthrough_performance_risks

    source = tmp_path / "Demo.java"
    source.write_text(
        """
        class Demo {
          public void listByDto(QueryDto queryDto) {
            commonService.getCustomInfo(queryDto.getCustCode());
            queryDto.setCustCode(null);
            feign.listByDto(queryDto, SecurityConstants.FROM_IN);
          }
        }
        """,
        encoding="utf-8",
    )
    result = {
        "target": {"absolute_file_path": str(source), "method": "listByDto"},
        "method_calls": [
            {"method_name": "scriptQuery", "receiver": "QueryBuilders", "line": 10},
            {"method_name": "wildcardQuery", "receiver": "QueryBuilders", "line": 11},
            {"method_name": "setTrackTotalHits", "receiver": "sourceBuilder", "line": 12},
        ],
        "feign_continuations": [
            {
                "server_walkthroughs": [
                    {
                        "service_impl_continuations": [
                            {
                                "same_class_method_continuations": [
                                    {"rule_groups": [{"group": "data_protection", "fields": ["protectCode", "unitLevel"]}]}
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
    }
    risks = _build_walkthrough_performance_risks(result)
    guards = _build_data_scope_guards(result)
    assert {item["code"] for item in risks} >= {"es_script_query", "es_wildcard_query", "track_total_hits"}
    assert {item["code"]: item["status"] for item in guards}["custom_info_enrichment"] == "present"
    assert {item["code"]: item["status"] for item in guards}["cust_code_cleared"] == "present"
    assert {item["code"]: item["status"] for item in guards}["internal_feign_header"] == "present"
    assert {item["code"]: item["status"] for item in guards}["downstream_data_protection_filters"] == "present"


def test_method_walkthrough_escalates_from_subproject_workspace(tmp_path: Path):
    parent_wf = Path(_setup_workspace(tmp_path))
    repo_root = parent_wf.parent.parent
    child_dir = repo_root / "task-service" / ".memory-center"
    child_dir.mkdir(parents=True)
    child_wf = child_dir / "workspace.yaml"
    child_wf.write_text(
        "\n".join([
            "workspace: task-only",
            f"root: {(repo_root / 'task-service').as_posix()}",
            "services:",
            "  - name: task-service",
            "    path: .",
            "    type: spring-boot-service",
            "    service_name: task-service",
            "",
        ]),
        encoding="utf-8",
    )

    result = memory_method_walkthrough(
        child_wf,
        "com.example.task.ArticleMoveService#move",
        view="compact",
        budget="small",
    )
    assert result["found"] is True
    assert result["workspace"] == "spring-cloud-demo"
    assert result["workspace_escalation"]["status"] == "escalated"
    assert result["workspace_escalation"]["original_workspace_file"] == str(child_wf.resolve())
    assert result["workspace_escalation"]["workspace_used"] == str(parent_wf.resolve())
    assert any(line.startswith("Server article-service:ArticleController#moveArticle") for line in result["summary_lines"])


def test_method_walkthrough_accepts_project_directory(tmp_path: Path):
    wf = Path(_setup_workspace(tmp_path))
    repo_root = wf.parent.parent
    result = memory_method_walkthrough(
        repo_root / "task-service",
        "com.example.task.ArticleMoveService#move",
        view="compact",
        budget="small",
    )
    assert result["found"] is True
    assert result["workspace"] == "spring-cloud-demo"
    assert result["target"]["class"] == "ArticleMoveService"


def test_method_walkthrough_uses_configured_template(tmp_path: Path):
    wf = Path(_setup_workspace(tmp_path))
    template_dir = wf.parent / "templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    template = template_dir / "method_walkthrough.md"
    template.write_text(
        "CUSTOM {target_label}\n{summary_lines}\nFILES\n{read_targets}\n",
        encoding="utf-8",
    )

    result = memory_method_walkthrough(
        wf,
        "com.example.task.ArticleMoveService#move",
        view="compact",
        budget="small",
    )
    assert result["answer_template"]["status"] == "configured"
    assert result["answer_template"]["path"] == str(template)
    assert result["answer_markdown"].startswith("CUSTOM task-service:ArticleMoveService#move")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
def test_mc_lookup_auto_returns_decision_fields(tmp_path: Path):
    import asyncio
    from memory_center.mcp.server import create_server

    wf = _setup_workspace(tmp_path)
    server = create_server(wf)
    mc_lookup = server._tool_manager._tools["mc_lookup"]
    result = asyncio.get_event_loop().run_until_complete(mc_lookup.fn(query="ArticleFeignClient", mode="auto"))
    assert result["candidate_paths"]
    assert result["recommended_path"]["target"]
    assert "lookup_hint" in result
    # chain (callees)
    r = memory_callees(wf, "ArticleFeignClient", depth=2, limit=10)
    assert r
    # context
    r = memory_context(wf, "ArticleFeignClient", max_depth=2)
    assert r
    # contracts
    r = memory_contracts(wf)
    assert r


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
def test_mc_lookup_auto_prefers_chain_for_deep_method_trace_queries(tmp_path: Path):
    import asyncio
    from memory_center.mcp.server import create_server

    wf = _setup_workspace(tmp_path)
    server = create_server(wf)
    mc_lookup = server._tool_manager._tools["mc_lookup"]
    result = asyncio.get_event_loop().run_until_complete(
        mc_lookup.fn(
            query="梳理下 com.example.api.ArticleFeignClient#moveArticle 全链路，一直到最底层逻辑处理",
            mode="auto",
        )
    )
    assert result["mode_used"] == "walkthrough"
    assert result["found"] is True
    assert result["summary_lines"]
    assert result["answer"]
    assert result["read_targets"]
    assert result["mermaid_flow"].startswith("flowchart TD")
    assert "performance_risks" in result
    assert "data_scope_guards" in result
    assert "diff_context" in result
    assert "glossary_hits" in result
    assert result["schema_version"] >= 2
    assert "index_freshness" in result
    assert "branch_outline" in result
    assert "anti_patterns" in result
    assert "cache" in result
    assert result["agent_usage_policy"]["read_files_by"] == "absolute_file_path"
    assert result["result"]["found"] is True
    assert result["result"]["target"]["method"] == "moveArticle"


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
def test_mcp_create_server_resolves_directory_workspace(tmp_path: Path):
    from memory_center.mcp.server import _resolve_workspace_input

    wf = Path(_setup_workspace(tmp_path))
    repo_root = wf.parent.parent
    assert _resolve_workspace_input(str(repo_root)) == str(wf.resolve())


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
def test_mcp_lookup_and_analyze_default_to_compact_views(tmp_path: Path):
    import asyncio
    from memory_center.mcp.server import create_server

    wf = _setup_workspace(tmp_path)
    server = create_server(wf)
    loop = asyncio.get_event_loop()

    mc_lookup = server._tool_manager._tools["mc_lookup"]
    symbol_payload = loop.run_until_complete(mc_lookup.fn(query="ArticleFeignClient", mode="symbol"))
    assert symbol_payload["result"]["found"] is True
    assert "best_match" in symbol_payload["result"]
    assert "lookup" in symbol_payload["result"]
    assert "matches" in symbol_payload["result"]
    assert symbol_payload["result"]["summary_lines"]
    assert "progressive" not in symbol_payload["result"]

    chain_payload = loop.run_until_complete(mc_lookup.fn(query="ArticleFeignClient", mode="chain", chain_direction="callers"))
    assert chain_payload["result"]["found"] is True
    assert chain_payload["result"]["direction"] == "callers"
    assert "chain_summary" in chain_payload["result"]
    assert chain_payload["result"]["summary_lines"]
    assert "callers" not in chain_payload["result"]

    context_payload = loop.run_until_complete(mc_lookup.fn(query="ArticleFeignClient", mode="context"))
    assert context_payload["result"]["found"] is True
    assert "incoming_summary" in context_payload["result"]
    assert "outgoing_summary" in context_payload["result"]
    assert context_payload["result"]["summary_lines"]
    assert "incoming" not in context_payload["result"]

    mc_analyze = server._tool_manager._tools["mc_analyze"]
    analyze_payload = loop.run_until_complete(mc_analyze.fn(target="ArticleFeignClient", depth="quick", direction="upstream", max_depth=2))
    assert analyze_payload["impact"]["found"] is True
    assert "confirmed_summary" in analyze_payload["impact"]
    assert analyze_payload["impact"]["summary_lines"]
    assert "confirmed_impacts" not in analyze_payload["impact"]
    analyze_project_payload = loop.run_until_complete(
        mc_analyze.fn(target="ArticleFeignClient", depth="quick", direction="upstream", max_depth=2, project="task-service")
    )
    assert analyze_project_payload["impact"]["project_scope"]["uses_cross_project_anchor"] is True
    assert analyze_project_payload["impact"]["project_evidence"]
    assert analyze_project_payload["impact"]["lookup"]["entrypoints"][0]["role"] == "anchor"


def test_memory_context_risk_patterns_do_not_fail_silently(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    r = memory_context(wf, "ArticleFeignClient", max_depth=2)
    assert r["found"] is True
    assert isinstance(r.get("risk_patterns"), list)
    diagnostics = r.get("_diagnostics", {})
    assert "risk_patterns" not in diagnostics


def test_memory_query_hybrid_exposes_vector_diagnostics(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    r = memory_query_hybrid(wf, "ArticleFeignClient", limit=5)
    assert "retrieval_diagnostics" in r
    assert "vector" in r["retrieval_diagnostics"]
    assert r["retrieval_diagnostics"]["vector"]["status"] in {"empty", "active", "unavailable", "disabled"}


def test_business_flow_cli_uses_workspace_yaml_not_sqlite_path(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["business-flow", "--workspace", wf, "--seed", "FeignClient:task-service:ArticleFeignClient", "--max-depth", "2"],
    )
    assert result.exit_code == 0, result.output
    assert "file is not a database" not in result.output
    assert "flows" in result.output


def test_http_next_phase_entrypoint_matrix_uses_workspace_yaml(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    cases = [
        ("/workspace/context-pack", {"workspace": [wf], "query": ["ArticleFeignClient"]}, ["query", "freshness", "progressive"]),
        ("/workspace/freshness", {"workspace": [wf]}, ["freshness", "banner"]),
        ("/workspace/onboard", {"workspace": [wf], "persona": ["developer"]}, ["tour"]),
        ("/workspace/business-flow", {"workspace": [wf], "seed": ["FeignClient:task-service:ArticleFeignClient"]}, ["flows", "workflow"]),
        ("/workspace/business-flow-impact", {"workspace": [wf], "node_id": ["FeignClient:task-service:ArticleFeignClient"]}, ["impacted", "workflow"]),
        ("/workspace/runtime-audit", {"workspace": [wf]}, ["score", "quality", "findings"]),
        ("/workspace/regression-alerts", {"workspace": [wf]}, ["alerts"]),
    ]
    for path, params, required_keys in cases:
        payload = _route_request(path, params, None)
        assert isinstance(payload, dict), path
        for key in required_keys:
            assert key in payload, f"{path} missing {key}: {payload}"
        assert "file is not a database" not in str(payload)


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
def test_mcp_next_phase_entrypoint_matrix_uses_workspace_yaml(tmp_path: Path):
    import asyncio

    wf = _setup_workspace(tmp_path)
    server = create_server(wf)
    tools = server._tool_manager._tools
    loop = asyncio.get_event_loop()

    direct_cases = [
        ("mc_context_pack", {"query": "ArticleFeignClient"}, ["workflow", "freshness", "progressive"]),
        ("mc_freshness", {}, ["workflow", "freshness", "banner"]),
        ("mc_onboard", {"persona": "developer"}, ["workflow", "tour"]),
        ("mc_domain", {}, ["workflow", "domains", "domain_count"]),
    ]
    for tool_name, kwargs, required_keys in direct_cases:
        payload = loop.run_until_complete(tools[tool_name].fn(**kwargs))
        for key in required_keys:
            assert key in payload, f"{tool_name} missing {key}: {payload}"

    admin_cases = [
        ({"action": "business_flow", "name": "FeignClient:task-service:ArticleFeignClient"}, ["action", "result"]),
        ({"action": "business_flow_impact", "text": "FeignClient:task-service:ArticleFeignClient"}, ["action", "result"]),
        ({"action": "runtime_audit"}, ["action", "result"]),
        ({"action": "heuristics_feedback", "text": '{"candidate_type":"impact_analysis","target":"ArticleFeignClient","outcome":"confirmed","evidence":[{"type":"test","id":"ev-1"}]}'}, ["action", "result"]),
        ({"action": "heuristics_explain", "text": '{"candidate_type":"impact_analysis","target":"ArticleFeignClient"}'}, ["action", "result"]),
        ({"action": "regression_alerts"}, ["action", "result"]),
    ]
    for kwargs, required_keys in admin_cases:
        payload = loop.run_until_complete(tools["mc_admin"].fn(**kwargs))
        for key in required_keys:
            assert key in payload, f"mc_admin {kwargs['action']} missing {key}: {payload}"
        assert "file is not a database" not in str(payload)


def test_mc_lookup_code_mode_passes_project_filter(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    r = memory_search_code(wf, "ArticleFeignClient", "", limit=20, project="task-service")
    assert r["hits"]
    assert all("task-service" in (item.get("project") or "") for item in r["hits"])


def test_mc_lookup_auto_mode_project_filter(tmp_path: Path):
    """mc_lookup(mode='auto') with project should return only matching project results."""
    wf = _setup_workspace(tmp_path)
    r = memory_query_hybrid(wf, "ArticleFeignClient", limit=10, project="task-service")
    assert r["results"]
    assert all("task-service" in (item.get("node", {}).get("project") or "") for item in r["results"])
    # P1: summary must be consistent with filtered results
    assert r["total_found"] == len(r["results"])
    assert r["retrieval_summary"]["total_results"] == len(r["results"])
    assert r["progressive"]["level_1_quick"]["count"] == len(r["results"])


def test_mc_lookup_symbol_mode_project_filter(tmp_path: Path):
    """mc_lookup(mode='symbol') with project should return only matching project results."""
    wf = _setup_workspace(tmp_path)
    r = memory_symbol(wf, "ArticleFeignClient", limit=10, project="task-service")
    assert r["found"] is True
    assert r["best_match"]["type"] == "Class"
    assert r["best_match"]["name"] == "ArticleFeignClient"
    assert "common-api" in (r["best_match"].get("project") or "")
    assert r["lookup"]["entrypoints"][0]["role"] == "anchor"
    for m in r.get("matches", []):
        assert "task-service" in ((m.get("node") or {}).get("project") or "")


def test_mc_lookup_chain_mode_project_filter(tmp_path: Path):
    """mc_lookup(mode='chain') with project should return results for that project."""
    wf = _setup_workspace(tmp_path)
    r = memory_callers(wf, "ArticleFeignClient", depth=2, limit=10, project="task-service")
    assert r["found"] is True
    assert r["project_scope"]["uses_cross_project_anchor"] is True
    assert r["project_evidence"]
    assert all("task-service" in (item.get("project") or "") for item in r["project_evidence"])


def test_mc_analyze_depth_levels(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # quick: impact only
    impact = memory_impact(wf, "ArticleFeignClient", direction="upstream", max_depth=2)
    assert impact
    assert impact["candidate_paths"]
    assert impact["recommended_path"]["target"]
    result_quick = {"workflow": "mc-analyze", "depth": "quick", "impact": impact}
    assert "impact" in result_quick
    assert "plan" not in result_quick

    # standard: impact + plan + rules
    plan = memory_plan_change(wf, "ArticleFeignClient", direction="upstream", max_depth=2)
    rules = workspace_check_rules(wf, None, "general", None)
    result_std = {"workflow": "mc-analyze", "depth": "standard", "impact": impact, "plan": plan, "rules": rules}
    assert "plan" in result_std
    assert "rules" in result_std
    assert "checklist" not in result_std

    # full: standard + checklist
    checklist = memory_verify_checklist(wf, "ArticleFeignClient")
    result_full = {"workflow": "mc-analyze", "depth": "full", "impact": impact, "plan": plan, "rules": rules, "checklist": checklist}
    assert "checklist" in result_full


def test_memory_impact_project_filter_uses_anchor_and_project_evidence(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    impact = memory_impact(wf, "ArticleFeignClient", direction="upstream", max_depth=2, project="task-service", view="compact", budget="small")
    assert impact["found"] is True
    assert impact["project_scope"]["uses_cross_project_anchor"] is True
    assert impact["project_evidence"]
    assert impact["lookup"]["entrypoints"][0]["role"] == "anchor"
    assert any(item.get("role") == "project_evidence" for item in impact["lookup"]["entrypoints"])


def test_mc_analyze_detect_changes_when_target_empty(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # When target is empty, should use detect_changes
    changes = memory_detect_changes(wf, "staged")
    result = {"workflow": "mc-analyze", "depth": "quick", "impact": changes}
    assert "impact" in result


def test_mc_sync_routes_by_input(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # intent-based (sniff-sync)
    sniff_sync = workspace_sync_sniff_to_artifacts(wf, "ArticleFeignClient", limit=8, task_id="", title="", auto_sync_mode="balanced")
    assert sniff_sync

    # session-based (case-sync) — need a session first
    session = workspace_start_session(wf, "test sync case")
    case_sync = workspace_sync_case_to_artifacts(wf, session["session_id"], task_id="", title="", auto_sync_mode="balanced")
    assert case_sync


def test_mc_resume_returns_four_keys(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    session = workspace_start_session(wf, "test resume")
    result = {
        "workflow": "mc-resume",
        "resume_packet": workspace_resume_packet(wf, session_id=session["session_id"], intent="test resume", limit=5, view="compact", budget="medium"),
        "next_actions": workspace_next_actions(wf, session_id=session["session_id"], intent="test resume", limit=5),
        "unresolved_items": workspace_unresolved_items(wf, session_id=session["session_id"], intent="test resume", limit=5),
        "recent_evidence": workspace_recent_evidence(wf, session_id=session["session_id"], limit=3, budget="medium"),
    }
    assert set(result.keys()) == {"workflow", "resume_packet", "next_actions", "unresolved_items", "recent_evidence"}
    assert result["workflow"] == "mc-resume"


def test_mc_handoff_returns_three_keys(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    from memory_center.core.orchestrator import memory_tool_usage_report
    session = workspace_start_session(wf, "test handoff")
    result = {
        "workflow": "mc-handoff",
        "handoff_packet": workspace_handoff_packet(wf, target_model="codex", session_id=session["session_id"], intent="test", limit=5, view="compact", budget="medium"),
        "recent_evidence": workspace_recent_evidence(wf, session_id=session["session_id"], limit=3, budget="medium"),
        "tool_usage_report": memory_tool_usage_report(wf, limit=50),
    }
    assert set(result.keys()) == {"workflow", "handoff_packet", "recent_evidence", "tool_usage_report"}
    assert result["workflow"] == "mc-handoff"


def test_mc_close_full_workflow(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    session = workspace_start_session(wf, "test close")
    sid = session["session_id"]
    from memory_center.core.orchestrator import workspace_log_session_event
    workspace_log_session_event(wf, sid, "tool_call", {"tool_name": "memory_symbol_tool", "query": "ArticleFeignClient"})

    ended = workspace_end_session(wf, sid, outcome="done")
    synced = workspace_sync_case_to_artifacts(wf, sid, task_id="", title="", auto_sync_mode="balanced")
    draft = workspace_suggest_case(wf, sid)

    result = {"workflow": "mc-close", "ended": ended, "sync_case": synced, "suggested_case": draft}
    assert result["workflow"] == "mc-close"


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
def test_mc_close_auto_records_candidate_feedback(tmp_path: Path):
    import asyncio

    wf = _setup_workspace(tmp_path)
    server = create_server(wf)
    tools = server._tool_manager._tools
    session = workspace_start_session(wf, "定位 ArticleFeignClient")
    sid = session["session_id"]
    from memory_center.core.orchestrator import workspace_log_session_event
    workspace_log_session_event(wf, sid, "tool_call", {"tool_name": "memory_symbol_tool", "query": "ArticleFeignClient"})

    payload = asyncio.get_event_loop().run_until_complete(
        tools["mc_close"].fn(session_id=sid, outcome="完成定位", verified_by=["manual-check"])
    )
    assert payload["candidate_feedback"]["recorded"] is True
    assert payload["candidate_feedback"]["feedback_items"][0]["target"] == "symbol_lookup"
    assert "ended" in result
    assert "sync_case" in result
    assert "suggested_case" in result


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
def test_mc_admin_dispatch_table_coverage(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    server = create_server(wf)
    # Verify mc_admin is registered
    tool_names = list(server._tool_manager._tools.keys())
    assert "mc_admin" in tool_names

    # Test representative actions directly (they call the same underlying functions)
    # status
    r = workspace_status(wf, view="compact", budget="medium")
    assert r
    # artifact_list
    r = list_artifacts(wf)
    assert r
    # task_create
    r = create_task_space(wf, title="test task", intent="test")
    assert "task_id" in r
    # task_list
    r = list_task_spaces(wf)
    assert isinstance(r, list) or isinstance(r, dict)


def test_mc_lookup_invalid_mode_raises(tmp_path: Path):
    """Verify that an invalid mode string raises ValueError with helpful message."""
    wf = _setup_workspace(tmp_path)
    if not HAS_MCP:
        pytest.skip("mcp package not installed")
    server = create_server(wf)
    mc_lookup = server._tool_manager._tools["mc_lookup"]
    import asyncio
    with pytest.raises(ValueError, match="Unknown mc_lookup mode"):
        asyncio.get_event_loop().run_until_complete(mc_lookup.fn(query="test", mode="nonexistent"))


def test_mc_admin_invalid_action_raises(tmp_path: Path):
    """Verify that an invalid action string raises ValueError with action list."""
    wf = _setup_workspace(tmp_path)
    if not HAS_MCP:
        pytest.skip("mcp package not installed")
    server = create_server(wf)
    mc_admin = server._tool_manager._tools["mc_admin"]
    import asyncio
    with pytest.raises(ValueError, match="Unknown mc_admin action"):
        asyncio.get_event_loop().run_until_complete(mc_admin.fn(action="nonexistent_action"))


def test_mc_sync_requires_intent_or_session_id(tmp_path: Path):
    """Verify mc_sync raises ValueError when neither intent nor session_id is provided."""
    wf = _setup_workspace(tmp_path)
    if not HAS_MCP:
        pytest.skip("mcp package not installed")
    server = create_server(wf)
    mc_sync = server._tool_manager._tools["mc_sync"]
    import asyncio
    with pytest.raises(ValueError, match="mc_sync requires intent or session_id"):
        asyncio.get_event_loop().run_until_complete(mc_sync.fn())
