"""分析类任务级用例，供 MCP、HTTP、CLI 共享。"""
from __future__ import annotations

from typing import Any

from memory_center.core.audit.inspect import inspect_runtime
from memory_center.core.audit.runtime import audit_agent_runtime
from memory_center.core.context.pack import ContextPackBuilder
from memory_center.core.domain.extractor import BusinessDomainExtractor
from memory_center.core.freshness.status import IndexFreshnessService
from memory_center.core.onboarding.tour import ArchitectureTourGenerator
from memory_center.core.storage.unified import UnifiedStore
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.verification.bundle_export import generate_agent_bundle
from memory_center.core.verification.workflow_profiles import get_workflow_profile, recommend_workflow_with_learning


def workflow_profile(profile: str) -> dict[str, Any]:
    return get_workflow_profile(profile)


def recommend_workflow(workspace_file: str, description: str) -> dict[str, Any]:
    return recommend_workflow_with_learning(workspace_file, description)


def export_agent_bundle(workspace_file: str, agent: str = "codex") -> dict[str, Any]:
    return generate_agent_bundle(workspace_file, agent=agent)


def runtime_audit(workspace_file: str) -> dict[str, Any]:
    return audit_agent_runtime(workspace_file)


def runtime_inspect(workspace_file: str, thread_id: str = "") -> dict[str, Any]:
    return inspect_runtime(workspace_file, thread_id=thread_id)


def onboarding_tour(
    workspace_file: str,
    persona: str = "developer",
    scope: str = "workspace",
    target: str = "",
) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    unified = UnifiedStore(store.graph_db_path)
    try:
        tour = ArchitectureTourGenerator(unified).generate_tour(persona=persona, scope=scope, target=target or None)
        return {"tour": tour.to_dict()}
    finally:
        unified.close()


def build_context_pack(workspace_file: str, query: str, intent: str, budget_tokens: int, limit: int) -> dict[str, Any]:
    pack = ContextPackBuilder(workspace_file).build(query=query, intent=intent or "auto", budget_tokens=budget_tokens, limit=limit)
    return {key: getattr(pack, key) for key in ("query", "intent", "entrypoints", "relationships", "snippets", "risks", "checklist", "freshness", "token_estimate", "progressive")}


def freshness_banner(workspace_file: str) -> dict[str, Any]:
    return IndexFreshnessService(workspace_file).banner()


def domain_overview(workspace_file: str, include_flows: bool = True) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    unified = UnifiedStore(store.graph_db_path)
    try:
        extractor = BusinessDomainExtractor(unified)
        domains = extractor.extract_domains()
        result = {"domains": [domain.to_dict() for domain in domains], "domain_count": len(domains)}
        if include_flows:
            flows = extractor.extract_flows()
            result["flows"] = [flow.to_dict() for flow in flows]
            result["flow_count"] = len(flows)
        return result
    finally:
        unified.close()
