"""MCP 资源、提示词与上下文洞察工具注册。"""
from __future__ import annotations

from typing import Any

from memory_center.application.analysis import build_context_pack, freshness_banner, onboarding_tour
from memory_center.application.analysis import domain_overview as build_domain_overview
from memory_center.core.orchestrator import memory_contracts, workspace_status
from memory_center.mcp.runtime import safe_mcp_tool


def register_insight_surface(mcp: Any, workspace_context: Any) -> None:
    """注册不依赖任务会话状态的资源、提示词与洞察工具。"""

    @mcp.resource("memory-center://status")
    def status_resource():
        return workspace_status(workspace_context.workspace_file)

    @mcp.resource("memory-center://startup-diagnostics")
    def startup_diagnostics_resource():
        return workspace_context.startup_diagnostics

    @mcp.resource("memory-center://contracts")
    def contracts_resource():
        return memory_contracts(workspace_context.workspace_file)

    @mcp.resource("memory-center://topology")
    def topology_resource():
        return workspace_status(workspace_context.workspace_file).get("topology", {})

    @mcp.prompt()
    def detect_impact(target: str) -> str:
        return "Use Memory Center before editing. Call mc_analyze for the target to get impact analysis, change plan, and rules check. " f"Target: {target}"

    @mcp.prompt()
    def spring_cloud_safe_change(task: str) -> str:
        return "For this Spring Cloud task, call mc_start first. Then use mc_lookup or mc_analyze for important contracts. Use mc_sync to save progress, and mc_close when done. " f"Task: {task}"

    @mcp.prompt()
    def onboard_new_dev(scope: str = "workspace") -> str:
        return "You are onboarding a new developer to this project. Call mc_onboard with persona='developer' to get a guided architecture tour. Then call mc_domain to understand business domains and flows. Finally call mc_freshness to check if the index is up to date."

    @mcp.prompt()
    def check_mq_safety(topic: str = "") -> str:
        base = "Check MQ consumer safety for this project. Call mc_lookup to find MQ consumers and topics. Verify each consumer has idempotent handling. Check message format compatibility. "
        return base + (f"Focus topic: {topic}" if topic else "Check all MQ consumers in the workspace.")

    @mcp.prompt()
    def analyze_dto_impact(dto_class: str = "") -> str:
        base = "Analyze the impact of changing a DTO class. Call mc_analyze to get the full impact analysis. Check serialization compatibility, MQ message bodies, and Feign client contracts. "
        return base + (f"Target DTO: {dto_class}" if dto_class else "Analyze all DTOs in the workspace.")

    @mcp.prompt()
    def cross_service_trace(service: str = "") -> str:
        base = "Trace cross-service call chains. If the input contains Class#method or asks for full chain/全链路/到底层, call mc_lookup with mode='walkthrough' first. Use mode='chain' only for generic caller/callee graph exploration. For walkthrough results, follow summary_lines, local_service_continuations, feign_continuations.server_walkthroughs, and service_impl_continuations. When absolute_file_path is present, read that path directly; do not run find/grep/IDEA search to locate the same controller or impl. Then map Feign clients, MQ producers/consumers, and shared configs as needed. "
        return base + (f"Starting from: {service}" if service else "Trace all cross-service interactions.")

    @mcp.prompt()
    def config_propagation_check(key: str = "") -> str:
        base = "Check configuration key propagation across services. Call mc_lookup to find ConfigKey nodes. Identify which services read the same config keys. Flag potential configuration drift. "
        return base + (f"Focus key: {key}" if key else "Check all shared configuration keys.")

    @mcp.prompt()
    def freshness_check() -> str:
        return "Check index freshness before making code changes. Call mc_freshness to see if the graph index is up to date. If status is 'pending' or 'stale', read live files before editing. Never edit based on stale index data."

    @mcp.prompt()
    def domain_overview() -> str:
        return "Get a business domain overview of this project. Call mc_domain to extract business domains and flows. Understand how code maps to business concepts. Use this for product/business stakeholder discussions."

    @mcp.prompt()
    def diff_impact_analysis(diff_summary: str = "") -> str:
        base = "Analyze the impact of a git diff. Call mc_context_pack to get a compact context package. Then call mc_analyze for detailed impact analysis. Generate a change checklist with risk assessment. "
        return base + (f"Diff summary: {diff_summary}" if diff_summary else "Analyze the current working tree changes.")

    @safe_mcp_tool(mcp)
    def mc_context_pack(query: str, intent: str = "auto", budget_tokens: int = 8000, limit: int = 10):
        """返回面向编码 Agent 的紧凑、带证据上下文包。"""
        pack = build_context_pack(workspace_context.workspace_file, query, intent, budget_tokens, limit)
        return {"workflow": "mc-context-pack", **pack, "relationships": pack["relationships"][:20]}

    @safe_mcp_tool(mcp)
    def mc_onboard(scope: str = "workspace", persona: str = "developer", target: str = ""):
        """按角色生成项目架构导览。"""
        return {"workflow": "mc-onboard", **onboarding_tour(workspace_context.workspace_file, persona, scope, target)}

    @safe_mcp_tool(mcp)
    def mc_domain(scope: str = "workspace", include_flows: bool = True):
        """从知识图谱提取业务领域和业务流。"""
        return {"workflow": "mc-domain", **build_domain_overview(workspace_context.workspace_file, include_flows)}

    @safe_mcp_tool(mcp)
    def mc_freshness(scope: str = "workspace"):
        """返回索引新鲜度状态。"""
        return {"workflow": "mc-freshness", **freshness_banner(workspace_context.workspace_file)}
