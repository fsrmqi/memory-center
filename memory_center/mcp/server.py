from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from memory_center.core.orchestrator import (
    group_impact,
    group_query,
    group_status,
    memory_callers,
    memory_callees,
    memory_context,
    memory_contracts,
    memory_detect_changes,
    memory_impact,
    memory_plan_change,
    memory_query,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    workspace_end_session,
    workspace_log_session_event,
    workspace_recent_sessions,
    workspace_resume_context,
    workspace_suggest_case,
    workspace_check_contract,
    workspace_check_rules,
    workspace_record_case,
    workspace_session_summary,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_trace,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
)
from memory_center.core.artifacts import append_change_log, artifact_context, artifact_outline, compact_change_log, get_artifact, list_artifacts, update_artifact
from memory_center.core.wiki import generate_skills, generate_wiki

_WORKSPACE_FILE: Optional[str] = None


def create_server(workspace_file: str):
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Please install MCP dependency: pip install -e .[mcp]") from exc

    global _WORKSPACE_FILE
    _WORKSPACE_FILE = workspace_file
    mcp = FastMCP("Memory Center")

    @mcp.tool()
    def workspace_sniff_tool(intent: str, limit: int = 12):
        """Before any code task, retrieve services, files, rules, topology hints and historical cases."""
        return workspace_sniff(_WORKSPACE_FILE, intent, limit)

    @mcp.tool()
    def workspace_sync_sniff_artifacts_tool(intent: str, limit: int = 12):
        """Sync sniff result into shared context and plan artifacts."""
        return workspace_sync_sniff_to_artifacts(_WORKSPACE_FILE, intent, limit)

    @mcp.tool()
    def workspace_artifact_list_tool():
        """List shared workspace artifacts such as context, requirement, design, plan and change log."""
        return list_artifacts(_WORKSPACE_FILE)

    @mcp.tool()
    def workspace_artifact_get_tool(name: str):
        """Read one shared workspace artifact."""
        return get_artifact(_WORKSPACE_FILE, name)

    @mcp.tool()
    def workspace_artifact_outline_tool(name: str):
        """Read one shared workspace artifact outline without loading full content."""
        return artifact_outline(_WORKSPACE_FILE, name)

    @mcp.tool()
    def workspace_artifact_context_tool(intent: str, limit: int = 6):
        """Retrieve only relevant artifact snippets for the current intent."""
        return artifact_context(_WORKSPACE_FILE, intent, limit)

    @mcp.tool()
    def workspace_artifact_update_tool(name: str, content: str):
        """Replace one shared workspace artifact content."""
        return update_artifact(_WORKSPACE_FILE, name, content)

    @mcp.tool()
    def workspace_append_change_log_tool(entry: str):
        """Append one timestamped entry to the shared change log."""
        return append_change_log(_WORKSPACE_FILE, entry)

    @mcp.tool()
    def workspace_compact_change_log_tool(keep_recent: int = 30):
        """Archive older change-log entries to keep shared context compact."""
        return compact_change_log(_WORKSPACE_FILE, keep_recent)

    @mcp.tool()
    def memory_query_tool(query: str, limit: int = 20):
        """Graph-aware query across files, symbols, services, contracts, rules and memory."""
        return memory_query(_WORKSPACE_FILE, query, limit)

    @mcp.tool()
    def memory_search_code_tool(query: str, scope: str = "", limit: int = 20):
        """Keyword code search for project/path/symbol hints before deep graph traversal."""
        return memory_search_code(_WORKSPACE_FILE, query, scope, limit)

    @mcp.tool()
    def memory_symbol_tool(name: str, limit: int = 10):
        """Resolve one symbol and provide best match plus nearby candidates."""
        return memory_symbol(_WORKSPACE_FILE, name, limit)

    @mcp.tool()
    def memory_callers_tool(symbol: str, depth: int = 2, limit: int = 80):
        """Find upstream callers for a symbol (method/class/feign/topic/config)."""
        return memory_callers(_WORKSPACE_FILE, symbol, depth, limit)

    @mcp.tool()
    def memory_callees_tool(symbol: str, depth: int = 2, limit: int = 80):
        """Find downstream callees for a symbol (method/class/feign/topic/config)."""
        return memory_callees(_WORKSPACE_FILE, symbol, depth, limit)

    @mcp.tool()
    def memory_context_tool(name: str, max_depth: int = 2):
        """Return 360-degree context for a service, endpoint, Feign method, topic, file or symbol."""
        return memory_context(_WORKSPACE_FILE, name, max_depth)

    @mcp.tool()
    def memory_impact_tool(target: str, direction: str = "upstream", max_depth: int = 3):
        """Analyze upstream/downstream impact for a changed symbol, DTO, Feign contract, endpoint or topic."""
        return memory_impact(_WORKSPACE_FILE, target, direction, max_depth)

    @mcp.tool()
    def memory_detect_changes_tool(scope: str = "staged"):
        """Map local git changes to affected projects, graph nodes, rules and risk level."""
        return memory_detect_changes(_WORKSPACE_FILE, scope)

    @mcp.tool()
    def memory_contracts_tool():
        """List discovered Feign/API/MQ contracts and contract-related rules."""
        return memory_contracts(_WORKSPACE_FILE)

    @mcp.tool()
    def memory_plan_change_tool(target: str, direction: str = "upstream", max_depth: int = 3):
        """Create one actionable change plan from impact and rule evidence."""
        return memory_plan_change(_WORKSPACE_FILE, target, direction, max_depth)

    @mcp.tool()
    def memory_verify_checklist_tool(target: str):
        """Generate one verification checklist before merge/release."""
        return memory_verify_checklist(_WORKSPACE_FILE, target)

    @mcp.tool()
    def workspace_trace_tool(entry: str):
        """Trace cross-service candidates by class name, Feign client, Controller endpoint, or MQ topic."""
        return workspace_trace(_WORKSPACE_FILE, entry)

    @mcp.tool()
    def workspace_check_contract_tool(contract_file: str, change_type: str):
        """Check impact before changing DTO, Feign client, MQ message or shared contract files."""
        return workspace_check_contract(_WORKSPACE_FILE, contract_file, change_type)

    @mcp.tool()
    def workspace_check_rules_tool(projects: List[str] | None = None, change_type: str = "general", files: List[str] | None = None):
        """Check architecture rules before editing files."""
        return workspace_check_rules(_WORKSPACE_FILE, projects, change_type, files)

    @mcp.tool()
    def workspace_record_case_tool(task: str, projects: List[str], files: List[str], flow: str = "", risk_points: List[str] | None = None, verified_by: List[str] | None = None):
        """Record a solved task into cross-service memory after validation."""
        return workspace_record_case(_WORKSPACE_FILE, task, projects, files, flow, risk_points, verified_by)

    @mcp.tool()
    def workspace_start_session_tool(intent: str, session_id: str = ""):
        """Start one lightweight task session for later resume/review."""
        return workspace_start_session(_WORKSPACE_FILE, intent, session_id=session_id or None)

    @mcp.tool()
    def workspace_log_session_event_tool(session_id: str, event_type: str, payload: dict | None = None):
        """Append one session event such as prompt, tool_call, tool_result or note."""
        return workspace_log_session_event(_WORKSPACE_FILE, session_id, event_type, payload)

    @mcp.tool()
    def workspace_end_session_tool(session_id: str, outcome: str = "", verified_by: List[str] | None = None):
        """End one session and generate a reusable summary."""
        return workspace_end_session(_WORKSPACE_FILE, session_id, outcome, verified_by)

    @mcp.tool()
    def workspace_recent_sessions_tool(limit: int = 10):
        """List recent summarized sessions for this workspace."""
        return workspace_recent_sessions(_WORKSPACE_FILE, limit)

    @mcp.tool()
    def workspace_session_summary_tool(session_id: str):
        """Read one session summary together with recorded raw events."""
        return workspace_session_summary(_WORKSPACE_FILE, session_id)

    @mcp.tool()
    def workspace_resume_context_tool(intent: str, limit: int = 5):
        """Resume a new task by mixing related sessions, cases and query entrypoints."""
        return workspace_resume_context(_WORKSPACE_FILE, intent, limit)

    @mcp.tool()
    def workspace_suggest_case_tool(session_id: str):
        """Suggest one record-case draft from a finished session."""
        return workspace_suggest_case(_WORKSPACE_FILE, session_id)

    @mcp.tool()
    def workspace_sync_case_artifacts_tool(session_id: str):
        """Sync one suggested case into shared design and change-log artifacts."""
        return workspace_sync_case_to_artifacts(_WORKSPACE_FILE, session_id)

    @mcp.tool()
    def memory_generate_wiki_tool(output_dir: str | None = None):
        """Generate bilingual Markdown wiki from the current workspace graph and task memory."""
        return generate_wiki(_WORKSPACE_FILE, output_dir)

    @mcp.tool()
    def memory_generate_skills_tool(output_dir: str | None = None):
        """Generate agent skill files from historical task memory."""
        return generate_skills(_WORKSPACE_FILE, output_dir)

    @mcp.tool()
    def workspace_status_tool():
        """Return workspace index and memory status."""
        return workspace_status(_WORKSPACE_FILE)

    @mcp.tool()
    def group_query_tool(group: str, query: str, limit: int = 20):
        """Run a merged query across all workspaces registered in a logical group."""
        return group_query(group, query, limit)

    @mcp.tool()
    def group_status_tool(group: str):
        """Return aggregated index status for all workspaces in a logical group."""
        return group_status(group)

    @mcp.tool()
    def group_impact_tool(group: str, target: str, direction: str = "upstream", max_depth: int = 3):
        """Run cross-workspace impact analysis across a logical group."""
        return group_impact(group, target, direction, max_depth)

    @mcp.resource("memory-center://status")
    def status_resource():
        return workspace_status(_WORKSPACE_FILE)

    @mcp.resource("memory-center://contracts")
    def contracts_resource():
        return memory_contracts(_WORKSPACE_FILE)

    @mcp.resource("memory-center://topology")
    def topology_resource():
        return workspace_status(_WORKSPACE_FILE).get("topology", {})

    @mcp.prompt()
    def detect_impact(target: str) -> str:
        return (
            "Use Memory Center before editing. Call memory_impact_tool for the target, "
            "then inspect required_rules and review_checklist before proposing changes. "
            f"Target: {target}"
        )

    @mcp.prompt()
    def spring_cloud_safe_change(task: str) -> str:
        return (
            "For this Spring Cloud task, call workspace_sniff_tool first, then memory_context_tool or "
            "memory_impact_tool for important contracts. Before editing, call workspace_check_rules_tool. "
            "After validation, call workspace_record_case_tool. Task: " + task
        )

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="Path to .memory-center/workspace.yaml")
    args = parser.parse_args()
    server = create_server(str(Path(args.workspace).expanduser().resolve()))
    server.run()


if __name__ == "__main__":
    main()
