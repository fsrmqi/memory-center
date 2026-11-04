"""Tests for MCP workflow facades and focused insight tools."""
import asyncio
import importlib.util
import inspect
from pathlib import Path

import pytest

pass  # 4.x 入口已退役
from memory_center.core.indexing.reindex import reindex_workspace
from memory_center.core.orchestrator import (
    memory_callers,
    memory_context,
    memory_detect_changes,
    memory_eval_walkthrough_quality,
    memory_export_walkthrough_artifact,
    memory_impact,
    memory_method_walkthrough,
    memory_plan_change,
    memory_query_hybrid,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    memory_walkthrough_health,
    workspace_check_rules,
    workspace_end_session,
    workspace_handoff_packet,
    workspace_lookup_hint,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_resume_packet,
    workspace_sniff,
    workspace_start_session,
    workspace_suggest_case,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_trace,
    workspace_unresolved_items,
)
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

pass  # 4.x 入口已退役

HAS_MCP = importlib.util.find_spec("mcp") is not None and importlib.util.find_spec("mcp.server.fastmcp") is not None

if HAS_MCP:
    pass  # 4.x 入口已退役


@pytest.fixture(autouse=True)
def _main_thread_event_loop():
    """Keep legacy synchronous FastMCP tests compatible with Python 3.11+."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _resolve_mcp_result(payload):
    """Resolve either sync or async FastMCP tool wrappers in direct tests."""
    return asyncio.get_event_loop().run_until_complete(payload) if inspect.isawaitable(payload) else payload


def _setup_workspace(tmp_path: Path) -> str:
    from tests.fixtures import setup_demo_workspace
    return str(setup_demo_workspace(tmp_path))


def _setup_duplicate_symbol_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "dupe-demo"
    for service in ("alpha-service", "beta-service", "gamma-service"):
        (root / service / "src" / "main" / "java" / "com" / "example").mkdir(parents=True, exist_ok=True)

    shared_class = (
        "package com.example;\n\n"
        "public class RedisDelayedQueue {\n"
        "    public String source() {\n"
        "        return \"%s\";\n"
        "    }\n"
        "}\n"
    )
    (root / "alpha-service" / "src" / "main" / "java" / "com" / "example" / "RedisDelayedQueue.java").write_text(
        shared_class % "alpha",
        encoding="utf-8",
    )
    (root / "beta-service" / "src" / "main" / "java" / "com" / "example" / "RedisDelayedQueue.java").write_text(
        shared_class % "beta",
        encoding="utf-8",
    )
    (root / "gamma-service" / "src" / "main" / "java" / "com" / "example" / "GammaWorker.java").write_text(
        "package com.example;\n\npublic class GammaWorker {}\n",
        encoding="utf-8",
    )

    workspace_dir = root / ".memory-center"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    workspace = workspace_dir / "workspace.yaml"
    workspace.write_text(
        "\n".join(
            [
                "workspace: duplicate-symbol-demo",
                f"root: {root.as_posix()}",
                "services:",
                "  - name: alpha-service",
                "    path: alpha-service",
                "    type: spring-boot-service",
                "  - name: beta-service",
                "    path: beta-service",
                "    type: spring-boot-service",
                "  - name: gamma-service",
                "    path: gamma-service",
                "    type: spring-boot-service",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)
    return workspace

@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_server_exposes_workflow_facades_and_insight_tools(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_exposes_zero_initialization_context_bootstrap(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_bootstrap_does_not_create_workspace_state(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


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
    q = memory_query_hybrid(wf, "ArticleFeignClient", limit=5)
    assert q


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_lookup_extracts_symbol_from_natural_language_query():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_extract_symbol_keeps_class_dot_method():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_lookup_hint_symbol_wins_over_api_token(tmp_path):
    """A `Controller.method` query carrying an `api` token must stay on
    symbol_lookup, not be downgraded to cross_service/context.

    Regression from replay: `VersionController.apiGetVersion` was routed to
    context because the `api` substring triggered the cross-service rule.
    """
    from tests.fixtures import copy_demo_workspace

    demo_ws = str(copy_demo_workspace(tmp_path / "hint-fixture-api"))
    from memory_center.core.orchestrator.workspace_ops import workspace_lookup_hint

    hint = workspace_lookup_hint(demo_ws, "VersionController.apiGetVersion", limit=4)
    assert hint.get("recommended_path") == "symbol_lookup", (
        f"Controller.method with api token must route to symbol_lookup, got {hint.get('recommended_path')}"
    )
    assert "memory_symbol_tool" in hint.get("preferred_tools", [])


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_extract_symbol_keeps_camel_method_names():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_extract_symbol_still_keeps_class_and_chain():
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


def test_camel_method_query_hint_prefers_symbol(tmp_path):
    """A pure camelCase method query must route to symbol_lookup (memory
    symbol) instead of local_search/code, so the Method node surfaces.

    Uses a small fixture workspace so the hint decision is deterministic.
    直连真实 demo 会打开其 graph.db（WAL checkpoint 污染后续副本），改用副本。
    """
    from pathlib import Path as _Path

    from tests.fixtures import copy_demo_workspace

    demo_ws = str(copy_demo_workspace(_Path(tmp_path) / "hint-fixture"))
    from memory_center.core.orchestrator.workspace_ops import workspace_lookup_hint

    hint = workspace_lookup_hint(demo_ws, "getArticleList", limit=4)
    assert hint.get("recommended_path") == "symbol_lookup", (
        f"camel method query should route to symbol_lookup, got {hint.get('recommended_path')}"
    )
    assert "memory_symbol_tool" in hint.get("preferred_tools", [])


def test_plain_local_search_phrase_not_rerouted_to_symbol(tmp_path):
    """Over-filtering guard: a query that is clearly a local keyword phrase
    (no camel symbol shape) must not be hijacked into symbol_lookup."""
    from tests.fixtures import copy_demo_workspace

    demo_ws = str(copy_demo_workspace(tmp_path / "hint-fixture-plain"))
    from memory_center.core.orchestrator.workspace_ops import workspace_lookup_hint

    hint = workspace_lookup_hint(demo_ws, "where is the file path", limit=4)
    # multi-word lowercase phrase with no symbol shape -> not symbol_lookup
    assert hint.get("recommended_path") != "symbol_lookup"


def test_mc_lookup_modes_direct(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # symbol
    r = memory_symbol(wf, "ArticleFeignClient", limit=5)
    assert r
    # code
    r = memory_search_code(wf, "ArticleFeignClient", "", limit=5)
    assert r
    # query
    r = memory_query_hybrid(wf, "ArticleFeignClient", limit=5)
    assert r
    # trace
    r = workspace_trace(wf, "ArticleFeignClient")
    assert r
    assert r["trace_mode"] == "index_overview"
    assert "mc_lookup(mode='chain')" in r["trace_note"]
    # chain (callers)
    r = memory_callers(wf, "ArticleFeignClient", depth=2, limit=10)
    assert r


def test_code_search_keeps_method_call_names_searchable(tmp_path: Path):
    wf = _setup_workspace(tmp_path)

    result = memory_search_code(wf, "moveArticle", limit=5)

    assert result["total_hits"] >= 1


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
    assert result["read_targets"]
    assert result["read_targets"][0]["role"] == "target"
    assert result["read_targets"][0]["absolute_file_path"] == result["target"]["absolute_file_path"]
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
    assert result["completion_status"]["state"] == "complete"
    assert result["completion_status"]["recommended_action"] == "use_current_evidence"
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
    from memory_center.core.walkthrough.risks import build_data_scope_guards, build_walkthrough_performance_risks

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
    risks = build_walkthrough_performance_risks(result)
    guards = build_data_scope_guards(result)
    assert {item["code"] for item in risks} >= {"es_script_query", "es_wildcard_query", "track_total_hits"}
    assert {item["code"]: item["status"] for item in guards}["custom_info_enrichment"] == "present"
    assert {item["code"]: item["status"] for item in guards}["cust_code_cleared"] == "present"
    assert {item["code"]: item["status"] for item in guards}["internal_feign_header"] == "present"
    assert {item["code"]: item["status"] for item in guards}["downstream_data_protection_filters"] == "present"


def test_walkthrough_answer_v2_is_detailed_but_readable(tmp_path: Path):
    from memory_center.core.walkthrough.answer import render_method_walkthrough_answer
    from memory_center.core.walkthrough.risks import build_method_walkthrough_mermaid

    wf = tmp_path / ".memory-center" / "workspace.yaml"
    wf.parent.mkdir(parents=True)
    wf.write_text(f"workspace: demo\nroot: {tmp_path.as_posix()}\nservices: []\n", encoding="utf-8")

    result = {
        "workspace": "demo",
        "symbol": "com.example.EntryService#listByDto",
        "target": {
            "project": "entry-service",
            "class": "EntryService",
            "method": "listByDto",
            "absolute_file_path": "/repo/entry/EntryService.java",
            "line": 22,
        },
        "summary_lines": [
            "Target entry-service:EntryService#listByDto (/repo/entry/EntryService.java:22)",
            "Step line 24: 调用 commonService.getCustomInfo",
            "Feign EntryFeignClient.listByDtoObject -> POST /entry/listByDto endpoints=1",
            "Server data-service:EntryController#listByDto (/repo/data/EntryController.java:35)",
            "Impl data-service:EntryServiceImpl#listByDto (/repo/data/EntryServiceImpl.java:110)",
            "ImplSameClass EntryServiceImpl#query2query (/repo/data/EntryServiceImpl.java:224) fields=58",
        ],
        "local_steps": [
            {"kind": "method_call", "line": 24, "receiver": "commonService", "receiver_type": "CommonService", "method": "getCustomInfo", "summary": "调用 commonService.getCustomInfo"},
            {"kind": "feign_call", "line": 30, "receiver": "entryFeignClient", "receiver_type": "EntryFeignClient", "method": "listByDtoObject", "summary": "调用 Feign EntryFeignClient.listByDtoObject"},
        ],
        "local_service_continuations": [
            {"target": {"project": "entry-service", "class": "CommonServiceImpl", "method": "getCustomInfo", "absolute_file_path": "/repo/entry/CommonServiceImpl.java", "line": 25}}
        ],
        "feign_continuations": [
            {
                "interface": "EntryFeignClient",
                "method": "listByDtoObject",
                "http_method": "POST",
                "path": "/entry/listByDto",
                "server_walkthroughs": [
                    {
                        "project": "data-service",
                        "controller": "EntryController",
                        "method": "listByDto",
                        "absolute_file_path": "/repo/data/EntryController.java",
                        "line": 35,
                        "service_impl_continuations": [
                            {
                                "target": {"project": "data-service", "class": "EntryServiceImpl", "method": "listByDto", "absolute_file_path": "/repo/data/EntryServiceImpl.java", "line": 110},
                                "same_class_method_continuations": [
                                    {
                                        "target": {"class": "EntryServiceImpl", "method": "query2query", "absolute_file_path": "/repo/data/EntryServiceImpl.java", "line": 224},
                                        "field_filter_summary": {"unique_dto_field_count": 58, "unique_dto_fields": ["protectCode", "unitLevel"]},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "performance_risks": [
            {"severity": "high", "code": "es_script_query", "message": "检测到 Elasticsearch scriptQuery。", "evidence": {"line": 10}},
            {"severity": "high", "code": "es_script_query", "message": "检测到 Elasticsearch scriptQuery。", "evidence": {"line": 20}},
            {"severity": "low", "code": "track_total_hits", "message": "检测到 trackTotalHits(true)。", "evidence": {"line": 30}},
        ],
        "data_scope_guards": [{"status": "present", "code": "custom_info_enrichment", "message": "入口保护单位信息。"}],
        "index_freshness": {"index_stale": False},
        "branch_outline": [],
        "next_actions": ["优先阅读 read_targets 中的文件。"],
    }
    result["mermaid_flow"] = build_method_walkthrough_mermaid(result)

    markdown = render_method_walkthrough_answer(result, wf, report_level="standard")

    assert "### 0. 快速结论" in markdown
    assert "### 1. 主链路" in markdown
    assert "### 2. 分层详情" in markdown
    assert "### 3. 证据文件" in markdown
    assert "### 4. 风险与数据范围" in markdown
    assert "入口层" in markdown
    assert "本地辅助服务" in markdown
    assert "远程 Feign" in markdown
    assert "下游服务端" in markdown
    assert "底层查询构造" in markdown
    assert "es_script_query" in markdown
    assert "出现 2 次" in markdown
    assert "[F1]" in markdown
    assert "/repo/entry/EntryService.java" in markdown
    assert "风险 " not in result["mermaid_flow"]
    assert "数据范围保护" not in result["mermaid_flow"]


def test_method_walkthrough_report_levels_preserve_chain_with_different_detail(tmp_path: Path):
    wf = Path(_setup_workspace(tmp_path))
    symbol = "com.example.task.ArticleMoveService#move"

    summary = memory_method_walkthrough(wf, symbol, view="compact", budget="small", report_level="summary")
    standard = memory_method_walkthrough(wf, symbol, view="compact", budget="small", report_level="standard")
    deep = memory_method_walkthrough(wf, symbol, view="compact", budget="small", report_level="deep")

    assert summary["summary_lines"] == standard["summary_lines"] == deep["summary_lines"]
    assert "### 快速结论" in summary["answer_markdown"]
    assert "### 主链路" in summary["answer_markdown"]
    assert "### 证据文件" in summary["answer_markdown"]
    assert "### 2. 分层详情" not in summary["answer_markdown"]
    assert "### 2. 分层详情" in standard["answer_markdown"]
    assert "### 业务词汇" in deep["answer_markdown"]
    assert len(summary["answer_markdown"]) < len(standard["answer_markdown"]) < len(deep["answer_markdown"])
    assert summary["answer_markdown"].count("ArticleController#moveArticle") >= 1
    assert deep["answer_markdown"].count("ArticleController#moveArticle") >= 1


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


def test_walkthrough_health_eval_and_export(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    symbol = "com.example.task.ArticleMoveService#move"

    health = memory_walkthrough_health(wf, symbol=symbol)
    assert health["status"] in {"pass", "warn"}
    assert any(item["name"] == "sample_contract" and item["status"] == "pass" for item in health["checks"])
    assert "recent_agent_bypass_feedback" in health

    quality = memory_eval_walkthrough_quality(wf, symbol=symbol)
    assert quality["grade"] == "pass"
    assert quality["score"] >= 80
    assert any(item["name"] == "does_not_recommend_low_signal_tools" and item["passed"] for item in quality["checks"])

    exported = memory_export_walkthrough_artifact(wf, symbol=symbol, title="Article move walkthrough")
    artifact_path = Path(exported["path"])
    assert exported["exported"] is True
    assert exported["artifact"].startswith("walkthroughs/")
    assert artifact_path.exists()
    content = artifact_path.read_text(encoding="utf-8")
    assert "# Article move walkthrough" in content
    assert "```mermaid" in content
    assert "## Read Targets" in content


def test_walkthrough_support_modules_keep_query_contracts():
    from memory_center.core.walkthrough import (
        WalkthroughCache,
        evaluate_walkthrough_result,
        render_walkthrough_markdown,
        slugify_walkthrough_symbol,
    )

    result = {
        "found": True,
        "schema_version": 2,
        "fields_contract": {"stable_top_level": ["answer_markdown"]},
        "target": {"absolute_file_path": "/tmp/Demo.java"},
        "summary_lines": ["入口方法已命中"],
        "answer_markdown": "### 调用链",
        "feign_continuations": [{"server_walkthroughs": []}],
        "agent_usage_policy": {"do_not_search_when_absolute_path_present": True},
        "mermaid_flow": "flowchart TD\nA-->B",
        "branch_outline": [{"label": "main"}],
        "performance_risks": [{"risk": "N+1"}],
        "cache": {"hit": False},
    }

    cache = WalkthroughCache(ttl_seconds=60, max_items=2)
    cache.put("k", result)
    cached = cache.get("k")
    assert cached is not result
    assert cached["cache"]["hit"] is True

    quality = evaluate_walkthrough_result(result)
    assert quality["grade"] == "pass"
    assert slugify_walkthrough_symbol("com.example.Service#run") == "com.example.Service__run"
    markdown = render_walkthrough_markdown("demo", "com.example.Service#run", result, read_targets="- target: /tmp/Demo.java:1")
    assert "## Read Targets" in markdown
    assert "flowchart TD" in markdown


def test_command_registry_shared_seam():
    from memory_center.core.foundation.dispatch import CommandRegistry

    registry = CommandRegistry(label="demo action").register_many({
        "ping": lambda: {"ok": True},
    })
    assert registry.dispatch("ping") == {"ok": True}
    assert registry.names() == ["ping"]
    with pytest.raises(ValueError, match="Unknown demo action"):
        registry.dispatch("missing")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_walkthrough_routes_use_registered_dispatch(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_method_walkthrough_surfaces_completion_status(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_walkthrough_cli_commands(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_lookup_auto_returns_decision_fields(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_lookup_with_session_id_records_agent_guidance(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_lookup_query_mode_forwards_vector_options(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_lookup_auto_query_lifts_agent_next_steps(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_lookup_auto_lifts_agent_next_steps_for_non_query_routes(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_lookup_direct_modes_lift_agent_next_steps(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_lookup_auto_prefers_chain_for_deep_method_trace_queries(monkeypatch, tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_admin_walkthrough_actions(tmp_path: Path):

    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_create_server_resolves_directory_workspace(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_lookup_and_analyze_default_to_compact_views(tmp_path: Path):

    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_analyze_keeps_impact_when_optional_plan_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_analyze_rejects_invalid_direction_without_internal_error(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


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


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_business_flow_cli_uses_workspace_yaml_not_sqlite_path(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_http_next_phase_entrypoint_matrix_uses_workspace_yaml(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mcp_next_phase_entrypoint_matrix_uses_workspace_yaml(tmp_path: Path):

    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


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


def test_memory_symbol_prefers_active_service_for_duplicate_symbols(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wf = _setup_duplicate_symbol_workspace(tmp_path)
    monkeypatch.chdir(wf.parent.parent / "beta-service")

    result = memory_symbol(wf, "RedisDelayedQueue", limit=5)

    assert result["found"] is True
    assert result["best_match"]["project"] == "beta-service"
    assert result["matches"]
    assert result["matches"][0]["node"]["project"] == "beta-service"


def test_memory_search_code_prefers_active_service_for_duplicate_symbols(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wf = _setup_duplicate_symbol_workspace(tmp_path)
    monkeypatch.chdir(wf.parent.parent / "beta-service")

    result = memory_search_code(wf, "RedisDelayedQueue", limit=5)

    assert result["project_scope"]["effective"] == "beta-service"
    assert result["hits"]
    assert {hit["project"] for hit in result["hits"]} == {"beta-service"}


def test_memory_search_code_keeps_active_service_scope_when_no_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wf = _setup_duplicate_symbol_workspace(tmp_path)
    monkeypatch.chdir(wf.parent.parent / "gamma-service")

    result = memory_search_code(wf, "RedisDelayedQueue", limit=5)

    assert result["project_scope"]["effective"] == "gamma-service"
    assert result["hits"] == []
    assert result["knowledge_state"]["state"] == "NOT_FOUND"


def test_memory_impact_keeps_active_service_scope_when_no_duplicate_symbol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wf = _setup_duplicate_symbol_workspace(tmp_path)
    monkeypatch.chdir(wf.parent.parent / "gamma-service")

    impact = memory_impact(wf, "RedisDelayedQueue", direction="upstream", max_depth=2)

    assert impact["found"] is False


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
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_close_auto_records_candidate_feedback(tmp_path: Path):

    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_admin_dispatch_table_coverage(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skipif(not HAS_MCP, reason="mcp package not installed")
@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_admin_task_health_actions(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_lookup_invalid_mode_returns_structured_mcp_error(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_admin_invalid_action_returns_structured_mcp_error(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")


@pytest.mark.skip(reason="4.x CLI/HTTP/Hook/MCP 合同已退役；5.0 接入由 tests/service 验证")
def test_mc_sync_missing_input_returns_structured_mcp_error(tmp_path: Path):
    pytest.skip("4.x 入口合同已退役；5.0 常驻服务合同由 tests/service 验证")
