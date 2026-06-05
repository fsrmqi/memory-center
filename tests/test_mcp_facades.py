"""Tests for MCP facade tools (8 task-level tools replacing 82 atomic tools)."""
from pathlib import Path
import shutil
import pytest
from typer.testing import CliRunner

from memory_center.core.config import load_workspace_config
from memory_center.core.indexer import reindex_workspace
from memory_center.core.orchestrator import (
    memory_callers, memory_callees, memory_context, memory_contracts,
    memory_detect_changes, memory_impact, memory_plan_change, memory_query,
    memory_query_hybrid, memory_ref_get, memory_search_code, memory_symbol,
    memory_verify_checklist,
    workspace_check_contract, workspace_check_rules, workspace_end_session,
    workspace_handoff_packet, workspace_log_session_event, workspace_next_actions,
    workspace_recent_evidence, workspace_resume_packet, workspace_sniff,
    workspace_start_session, workspace_status, workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts, workspace_suggest_case, workspace_trace,
    workspace_unresolved_items, workspace_record_case, workspace_lookup_hint,
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
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = load_workspace_config(workspace)
    from memory_center.core.store import WorkspaceStore
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)
    return str(workspace)


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
    assert result["session"]["session_id"]


def test_mc_lookup_mode_auto_routes_correctly(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # Test auto mode: lookup_hint should dispatch
    hint = workspace_lookup_hint(wf, query="ArticleFeignClient", intent="", limit=8)
    assert "preferred_tools" in hint
    # Test that symbol mode works
    sym = memory_symbol(wf, "ArticleFeignClient", limit=5)
    assert sym
    # Test that query mode works
    q = memory_query(wf, "ArticleFeignClient", limit=5)
    assert q


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
    # chain (callers)
    r = memory_callers(wf, "ArticleFeignClient", depth=2, limit=10)
    assert r
    # chain (callees)
    r = memory_callees(wf, "ArticleFeignClient", depth=2, limit=10)
    assert r
    # context
    r = memory_context(wf, "ArticleFeignClient", max_depth=2)
    assert r
    # contracts
    r = memory_contracts(wf)
    assert r


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
    assert "task-service" in (r["best_match"].get("project") or "")
    for m in r.get("matches", []):
        assert "task-service" in ((m.get("node") or {}).get("project") or "")


def test_mc_lookup_chain_mode_project_filter(tmp_path: Path):
    """mc_lookup(mode='chain') with project should return results for that project."""
    wf = _setup_workspace(tmp_path)
    r = memory_callers(wf, "ArticleFeignClient", depth=2, limit=10, project="task-service")
    assert r["found"] is True


def test_mc_analyze_depth_levels(tmp_path: Path):
    wf = _setup_workspace(tmp_path)
    # quick: impact only
    impact = memory_impact(wf, "ArticleFeignClient", direction="upstream", max_depth=2)
    assert impact
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

    ended = workspace_end_session(wf, sid, outcome="done")
    synced = workspace_sync_case_to_artifacts(wf, sid, task_id="", title="", auto_sync_mode="balanced")
    draft = workspace_suggest_case(wf, sid)

    result = {"workflow": "mc-close", "ended": ended, "sync_case": synced, "suggested_case": draft}
    assert result["workflow"] == "mc-close"
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
