from __future__ import annotations

import json as _json

from memory_center.core.foundation.dispatch import CommandRegistry

from .dependencies import Any, group_chain, group_impact, group_query, group_status
from .params import RouteParams, _parse_int


def register_analysis_routes(registry: CommandRegistry) -> None:
    # --- next-phase verification / explanation / business flow ----------------
    def _verification_loop(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.verification.loop import VerificationLoop
        ws = rp.workspace()
        vl = VerificationLoop(ws)
        task_type = rp.get("task_type", "general")
        task_id = rp.get("task_id", "default")
        analysis = {"task_type": task_type, "workspace": ws}
        return {
            "checklist": vl.generate_checklist(analysis),
            "status": vl.get_status(task_id),
        }

    registry.register("/workspace/verification-loop", _verification_loop)

    def _pattern_promotion(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        ws = rp.workspace()
        pp = PatternPromotion(ws)
        action_type = rp.get("action", "list")
        if action_type == "list":
            return {"proposals": pp.list_proposals()}
        if action_type == "propose":
            return pp.propose({"rule_text": rp.require('text'), "source": "http"})
        if action_type == "promote":
            return pp.promote(rp.require('text'))
        return {"error": f"Unknown action: {action_type}"}

    registry.register("/workspace/pattern-promotion", _pattern_promotion)

    def _heuristics(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.verification.heuristics import HeuristicsRegister
        ws = rp.workspace()
        hr = HeuristicsRegister(ws)
        action_type = rp.get("action", "query")
        if action_type == "query":
            return {"heuristics": hr.query(rp.get("text", ""))}
        if action_type in {"record", "feedback", "explain"}:
            try:
                data = _json.loads(rp.require('text'))
            except Exception:
                data = {"pattern": rp.require('text')}
            if action_type == "record":
                entry = hr.record(data)
                return {"status": "recorded", "entry": entry}
            if action_type == "explain":
                return hr.explain(
                    candidate_type=str(data.get("candidate_type", "") or ""),
                    target=str(data.get("target", "") or ""),
                    category=str(data.get("category", "") or "candidate-path"),
                    heuristic_id=str(data.get("heuristic_id", "") or ""),
                    pattern=str(data.get("pattern", "") or ""),
                    limit=int(data.get("limit", 10) or 10),
                )
            feedback = hr.record_candidate_path_feedback(
                candidate_type=str(data.get("candidate_type", "") or ""),
                target=str(data.get("target", "") or ""),
                outcome=str(data.get("outcome", "") or ""),
                evidence=data.get("evidence") or [],
                source=str(data.get("source", "") or "http"),
                task_id=str(data.get("task_id", "") or ""),
                session_id=str(data.get("session_id", "") or ""),
                weight_before=data.get("weight_before"),
                weight_delta=data.get("weight_delta"),
                why=str(data.get("why", "") or ""),
                next_action=str(data.get("next_action", "") or ""),
                verification_cost=str(data.get("verification_cost", "") or ""),
                category=str(data.get("category", "") or "candidate-path"),
                pattern=str(data.get("pattern", "") or ""),
                trigger=str(data.get("trigger", "") or ""),
            )
            return {"status": "recorded", "feedback": feedback}
        return {"error": f"Unknown action: {action_type}"}

    registry.register("/workspace/heuristics", _heuristics)

    def _workflow_profile(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.verification.workflow_profiles import get_workflow_profile
        return get_workflow_profile(rp.get("profile", "quick-fix"))

    registry.register("/workspace/workflow-profile", _workflow_profile)

    def _workflow_recommend(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.verification.workflow_profiles import recommend_workflow_with_learning
        ws = rp.workspace()
        return recommend_workflow_with_learning(ws, rp.require('description'))

    registry.register("/workspace/workflow-recommend", _workflow_recommend)

    def _bundle_export(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        ws = rp.workspace()
        return generate_agent_bundle(ws, agent=rp.get("agent", "codex"))

    registry.register("/workspace/bundle-export", _bundle_export)

    def _runtime_audit(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.audit.runtime import audit_agent_runtime
        return audit_agent_runtime(rp.workspace())

    registry.register("/workspace/runtime-audit", _runtime_audit)

    def _eval_golden(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core import benchmark as benchmark_module

        baseline = rp.get("baseline", "")
        return benchmark_module.run_golden_suite(rp.workspace(), rp.require('cases'), performance_baseline=baseline or None)

    registry.register("/workspace/eval-golden", _eval_golden)

    def _explanation(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.explanation.schema import Explanation
        text = rp.require('text')
        persona = rp.get("persona", "developer")
        exp = Explanation(subject="explanation", summary=text, persona=persona)
        return exp.adapt_for_persona(persona).to_full()

    registry.register("/workspace/explanation", _explanation)

    def _business_flow(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.domain.flow import extract_business_flows_for_workspace
        ws = rp.workspace()
        return extract_business_flows_for_workspace(
            ws,
            rp.require('seed'),
            max_depth=_parse_int(rp.params, "max_depth", 4),
        )

    registry.register("/workspace/business-flow", _business_flow)

    def _business_flow_impact(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.domain.flow import business_flow_impact_for_workspace
        ws = rp.workspace()
        return business_flow_impact_for_workspace(
            ws,
            rp.require('node_id'),
            max_depth=_parse_int(rp.params, "max_depth", 3),
        )

    registry.register("/workspace/business-flow-impact", _business_flow_impact)

    def _metrics_summary(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.observability.metrics import MetricsCollector
        ws = rp.params.get("workspace", [rp.default_workspace])[0]
        if not ws:
            return {"summary": {}, "note": "no_workspace_in_context"}
        metric_name = rp.get("metric_name", "")
        if not metric_name:
            return {"summary": {}, "note": "metric_name_required"}
        return {"summary": MetricsCollector(ws).summary(metric_name)}

    registry.register("/workspace/metrics-summary", _metrics_summary)

    def _onboard(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = rp.workspace()
        persona = rp.get("persona", "developer")
        workspace_store = WorkspaceStore(ws)
        unified = UnifiedStore(workspace_store.graph_db_path)
        try:
            gen = ArchitectureTourGenerator(unified)
            tour = gen.generate_tour(persona=persona)
            return {"tour": tour.to_dict()}
        finally:
            unified.close()

    registry.register("/workspace/onboard", _onboard)

    def _context_pack(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.context.pack import ContextPackBuilder
        ws = rp.workspace()
        builder = ContextPackBuilder(ws)
        query = rp.require('query')
        intent = rp.intent()
        budget_tokens = _parse_int(rp.params, "budget_tokens", 8000)
        limit = rp.limit(10)
        pack = builder.build(query=query, intent=intent or "auto", budget_tokens=budget_tokens, limit=limit)
        return {
            "query": pack.query,
            "intent": pack.intent,
            "entrypoints": pack.entrypoints,
            "relationships": pack.relationships,
            "snippets": pack.snippets,
            "risks": pack.risks,
            "checklist": pack.checklist,
            "freshness": pack.freshness,
            "token_estimate": pack.token_estimate,
            "progressive": pack.progressive,
        }

    registry.register("/workspace/context-pack", _context_pack)

    def _freshness(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.freshness.status import IndexFreshnessService
        ws = rp.workspace()
        return IndexFreshnessService(ws).banner()

    registry.register("/workspace/freshness", _freshness)

    # --- workspace-anchored group helpers (load_registry from workspace) ------
    def _workspace_group_status(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.governance.registry import load_registry
        ws = rp.workspace()
        return group_status(load_registry(ws))

    registry.register("/workspace/group-status", _workspace_group_status)

    def _workspace_group_query(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.governance.registry import load_registry
        ws = rp.workspace()
        return group_query(
            load_registry(ws),
            query=rp.require('query'),
            limit=_parse_int(rp.params, "limit", 20),
        )

    registry.register("/workspace/group-query", _workspace_group_query)

    def _workspace_group_impact(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.governance.registry import load_registry
        ws = rp.workspace()
        return group_impact(load_registry(ws), target=rp.require('target'))

    registry.register("/workspace/group-impact", _workspace_group_impact)

    def _workspace_group_chain(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.governance.registry import load_registry
        ws = rp.workspace()
        return group_chain(load_registry(ws), symbol=rp.require('symbol'))

    registry.register("/workspace/group-chain", _workspace_group_chain)
