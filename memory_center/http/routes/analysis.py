from __future__ import annotations

from memory_center.application.admin import (
    business_flow_action,
    business_flow_impact_action,
    explanation_action,
    heuristics_action,
    metrics_summary_action,
    pattern_promote_action,
    verification_loop_action,
)
from memory_center.application.analysis import (
    build_context_pack,
    export_agent_bundle,
    freshness_banner,
    onboarding_tour,
    recommend_workflow,
    runtime_audit,
    runtime_inspect,
    workflow_profile,
)
from memory_center.application.groups import (
    workspace_group_chain,
    workspace_group_impact,
    workspace_group_query,
    workspace_group_status,
)
from memory_center.application.http_facades import Any
from memory_center.core.foundation.dispatch import CommandRegistry
from memory_center.core.orchestrator import memory_impact

from .params import RouteParams, _parse_int


def register_analysis_routes(registry: CommandRegistry) -> None:
    # --- next-phase verification / explanation / business flow ----------------
    def _verification_loop(rp: RouteParams) -> dict[str, Any]:
        return verification_loop_action(rp.workspace(), rp.get("task_type", "general"), rp.get("task_id", "default"))

    registry.register("/workspace/verification-loop", _verification_loop)

    def _pattern_promotion(rp: RouteParams) -> dict[str, Any]:
        return pattern_promote_action(rp.workspace(), rp.get("action", "list"), rp.get("text", ""))

    registry.register("/workspace/pattern-promotion", _pattern_promotion)

    def _heuristics(rp: RouteParams) -> dict[str, Any]:
        return heuristics_action(rp.workspace(), rp.get("action", "query"), rp.get("text", ""))

    registry.register("/workspace/heuristics", _heuristics)

    def _workflow_profile(rp: RouteParams) -> dict[str, Any]:
        return workflow_profile(rp.get("profile", "quick-fix"))

    registry.register("/workspace/workflow-profile", _workflow_profile)

    def _workflow_recommend(rp: RouteParams) -> dict[str, Any]:
        return recommend_workflow(rp.workspace(), rp.require('description'))

    registry.register("/workspace/workflow-recommend", _workflow_recommend)

    def _bundle_export(rp: RouteParams) -> dict[str, Any]:
        return export_agent_bundle(rp.workspace(), rp.get("agent", "codex"))

    registry.register("/workspace/bundle-export", _bundle_export)

    def _runtime_audit(rp: RouteParams) -> dict[str, Any]:
        return runtime_audit(rp.workspace())

    registry.register("/workspace/runtime-audit", _runtime_audit)

    def _runtime_inspect(rp: RouteParams) -> dict[str, Any]:
        return runtime_inspect(rp.workspace(), rp.get("thread_id", ""))

    registry.register("/workspace/inspect", _runtime_inspect)

    def _eval_golden(rp: RouteParams) -> dict[str, Any]:
        from memory_center.application.golden import run_golden_suite

        baseline = rp.get("baseline", "")
        return run_golden_suite(rp.workspace(), rp.require('cases'), performance_baseline=baseline or None)

    registry.register("/workspace/eval-golden", _eval_golden)

    def _explanation(rp: RouteParams) -> dict[str, Any]:
        return explanation_action(rp.require('text'), rp.get("persona", "developer"))

    registry.register("/workspace/explanation", _explanation)

    def _business_flow(rp: RouteParams) -> dict[str, Any]:
        return business_flow_action(rp.workspace(), rp.require('seed'), _parse_int(rp.params, "max_depth", 4))

    registry.register("/workspace/business-flow", _business_flow)

    def _business_flow_impact(rp: RouteParams) -> dict[str, Any]:
        return business_flow_impact_action(rp.workspace(), rp.require('node_id'), _parse_int(rp.params, "max_depth", 3))

    registry.register("/workspace/business-flow-impact", _business_flow_impact)

    registry.register("/workspace/impact", lambda rp: memory_impact(
        rp.workspace(),
        rp.require('target'),
        direction=rp.get('direction', 'upstream'),
        max_depth=_parse_int(rp.params, 'max_depth', 3),
        view=rp.view(),
        budget=rp.budget(),
    ))

    def _metrics_summary(rp: RouteParams) -> dict[str, Any]:
        ws = rp.params.get("workspace", [rp.default_workspace])[0]
        return metrics_summary_action(ws, rp.get("metric_name", ""))

    registry.register("/workspace/metrics-summary", _metrics_summary)

    def _onboard(rp: RouteParams) -> dict[str, Any]:
        return onboarding_tour(rp.workspace(), rp.get("persona", "developer"))

    registry.register("/workspace/onboard", _onboard)

    def _context_pack(rp: RouteParams) -> dict[str, Any]:
        return build_context_pack(rp.workspace(), rp.require('query'), rp.intent(), _parse_int(rp.params, "budget_tokens", 8000), rp.limit(10), agent_id=rp.get("agent_id", ""), role=rp.get("role", ""))

    registry.register("/workspace/context-pack", _context_pack)

    def _freshness(rp: RouteParams) -> dict[str, Any]:
        return freshness_banner(rp.workspace())

    registry.register("/workspace/freshness", _freshness)

    # --- workspace-anchored group helpers (load_registry from workspace) ------
    def _workspace_group_status(rp: RouteParams) -> dict[str, Any]:
        return workspace_group_status(rp.workspace())

    registry.register("/workspace/group-status", _workspace_group_status)

    def _workspace_group_query(rp: RouteParams) -> dict[str, Any]:
        return workspace_group_query(rp.workspace(), rp.require('query'), _parse_int(rp.params, "limit", 20))

    registry.register("/workspace/group-query", _workspace_group_query)

    def _workspace_group_impact(rp: RouteParams) -> dict[str, Any]:
        return workspace_group_impact(rp.workspace(), rp.require('target'))

    registry.register("/workspace/group-impact", _workspace_group_impact)

    def _workspace_group_chain(rp: RouteParams) -> dict[str, Any]:
        return workspace_group_chain(rp.workspace(), rp.require('symbol'))

    registry.register("/workspace/group-chain", _workspace_group_chain)
