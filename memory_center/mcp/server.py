from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from memory_center.core.orchestrator import (
    group_query,
    group_status,
    memory_context,
    memory_contracts,
    memory_detect_changes,
    memory_impact,
    memory_query,
    workspace_check_contract,
    workspace_check_rules,
    workspace_record_case,
    workspace_sniff,
    workspace_status,
    workspace_trace,
)
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
    def memory_query_tool(query: str, limit: int = 20):
        """Graph-aware query across files, symbols, services, contracts, rules and memory."""
        return memory_query(_WORKSPACE_FILE, query, limit)

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
