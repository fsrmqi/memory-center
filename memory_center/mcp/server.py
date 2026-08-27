"""Memory Center MCP server — 8 facade tools (task-level interface).

Previously exposed 82 atomic tools; now consolidated into 8 task-level facades:
  mc_start   — begin a task workflow (sniff + sync + session)
  mc_lookup  — unified knowledge lookup (auto/symbol/code/query/trace/chain/walkthrough/context/contracts/ref)
  mc_analyze — change impact analysis (quick/standard/full depth)
  mc_sync    — sync context to workspace artifacts (sniff or case)
  mc_resume  — resume a task with consolidated context
  mc_handoff — build a handoff package for another model
  mc_close   — close a task workflow (end + sync + record)
  mc_admin   — admin/router for status, artifacts, evals, sessions, groups, etc.

All underlying orchestrator/artifacts functions remain callable from Python.
CLI and HTTP server keep their fine-grained interfaces unchanged.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from memory_center.core.foundation.errors import InvalidInputError
from memory_center.core.orchestrator import (
    _annotate_phantom_nodes,
    bootstrap_workspace_context,
    execute_mcp_bridge_action,
    execute_provider_action,
    fuse_provider_evidence,
    group_chain,
    mcp_bridge_status,
    memory_backend_query,
    memory_callees,
    memory_callers,
    memory_context,
    memory_contracts,
    memory_detect_changes,
    memory_impact,
    memory_method_walkthrough,
    memory_plan_change,
    memory_query_hybrid,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_tool_usage_report,
    memory_verify_checklist,
    workspace_check_contract,
    workspace_check_rules,
    workspace_end_session,
    workspace_handoff_packet,
    workspace_lookup_hint,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_record_agent_guidance,
    workspace_record_case,
    workspace_record_close_feedback,
    workspace_resume_packet,
    workspace_suggest_case,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_trace,
    workspace_unresolved_items,
)
from memory_center.mcp.runtime import WorkspaceContext, find_groups_for_workspace, safe_mcp_tool
from memory_center.mcp.tool_support import (
    degraded_analysis_step,
    extract_symbol_like_token,
    flatten_walkthrough_payload,
    validate_analyze_request,
    wants_deep_chain,
)

# Behavior-matrix tests assert that MCP keeps parity with shared backends even
# for capabilities routed through facades/admin actions instead of direct imports.
_SHARED_BACKEND_CONTRACTS = (
    "get_workflow_profile",
    "audit_agent_runtime",
    "check_regression_alerts",
    "memory_eval_parser_benchmark",
    "VerificationLoop",
    "extract_business_flows_for_workspace",
    "business_flow_impact_for_workspace",
)

def _lookup_payload_with_agent_steps(mode_key: str, mode_value: str, result: dict[str, Any], **extra: Any) -> dict[str, Any]:
    payload = {mode_key: mode_value, "result": result, **extra}
    agent_next_steps = result.get("agent_next_steps") if isinstance(result, dict) else None
    if agent_next_steps:
        payload["agent_next_steps"] = agent_next_steps
    return payload


def _agent_next_steps_for_lookup_route(mode: str, result: dict[str, Any], query: str = "") -> list[dict[str, Any]]:
    found = bool(result.get("found", True)) if isinstance(result, dict) else False
    if not found:
        return [
            {
                "action": "refine_query",
                "priority": "medium",
                "reason": f"{mode} lookup did not find bounded evidence",
                "command": "retry mc_lookup with a concrete class, method, endpoint, Feign client, or config key",
                "uses_existing_evidence": False,
            }
        ]
    if mode == "symbol":
        return [
            {
                "action": "inspect_symbol_anchor",
                "priority": "high",
                "reason": "symbol lookup selected a bounded anchor",
                "command": "read result.best_match / result.summary_lines before switching tools",
                "uses_existing_evidence": True,
            }
        ]
    if mode == "code":
        return [
            {
                "action": "inspect_code_hits",
                "priority": "medium",
                "reason": "code search returned indexed hits",
                "command": "read the top hit path/snippet, then rerun mc_lookup with a concrete symbol if needed",
                "uses_existing_evidence": True,
            }
        ]
    if mode.startswith("chain"):
        return [
            {
                "action": "inspect_chain_summary",
                "priority": "high",
                "reason": "call-chain route returned graph evidence",
                "command": "read result.summary_lines / result.chain_summary, then call mc_analyze before editing shared contracts",
                "uses_existing_evidence": True,
            }
        ]
    if mode == "context":
        return [
            {
                "action": "inspect_context_summary",
                "priority": "high",
                "reason": "context route returned incoming/outgoing/risk summaries",
                "command": "read result.summary_lines and risk/context sections before broadening search",
                "uses_existing_evidence": True,
            }
        ]
    if mode == "trace":
        return [
            {
                "action": "inspect_trace_overview",
                "priority": "high",
                "reason": "trace route returned cross-service overview evidence",
                "command": "use matched Feign/API/MQ entries to choose walkthrough or impact analysis",
                "uses_existing_evidence": True,
            }
        ]
    return [
        {
            "action": "inspect_route_result",
            "priority": "medium",
            "reason": f"{mode or 'lookup'} route returned bounded evidence",
            "command": "read result summaries before using broader search",
            "uses_existing_evidence": True,
        }
    ]


def _build_context_pack_recommendation(wf: str, intent: str, sniff_result: dict) -> dict:
    """D-02: Recommend context pack based on intent and risk level."""
    risk = sniff_result.get("risk_level", "low")
    intent_lower = intent.lower()
    arch_keywords = {"architecture", "design", "refactor", "migrate", "module", "service", "struct", "设计", "架构", "重构", "迁移"}
    change_keywords = {"change", "modify", "fix", "update", "impact", "affect", "break", "修改", "变更", "影响"}
    is_arch = any(k in intent_lower for k in arch_keywords)
    is_change = any(k in intent_lower for k in change_keywords) or risk in ("medium", "high")
    recommended = is_arch or is_change
    if not recommended:
        return {"recommended": False, "reason": "Intent does not suggest architecture or change-impact questions."}
    reason = "Architecture understanding intent" if is_arch else "Change-impact or elevated risk detected"
    return {
        "recommended": True,
        "reason": reason,
        "tool": "mc_context_pack",
        "suggested_query": intent,
        "suggested_budget": "medium" if risk == "low" else "large",
    }


def create_server(workspace_file: str):
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Please install MCP dependency: pip install -e .[mcp]") from exc

    ctx = WorkspaceContext(workspace_file)
    mcp = FastMCP("Memory Center")

    # Import workflow templates for guidance

    # ===================== FACADE 1: mc_start =====================
    @safe_mcp_tool(mcp, ctx)
    def mc_bootstrap_context(
        path: str = "",
        intent: str = "",
        query: str = "",
        target: str = "",
        limit: int = 8,
    ):
        """Build context without initializing a workspace. Uses an existing Memory Center workspace when available; otherwise invokes the optional GitNexus provider through fixed read-only commands. External evidence is session-ephemeral and never written into the graph."""
        return bootstrap_workspace_context(path or ctx.workspace_input, intent=intent, query=query, target=target, limit=limit)

    @safe_mcp_tool(mcp, ctx)
    def mc_provider_action(
        action: str,
        provider: str = "gitnexus",
        query: str = "",
        target: str = "",
        confirm: bool = False,
        force: bool = False,
        limit: int = 8,
        depth: int = 3,
    ):
        """Run a registered external-provider action. Read actions run directly; index or clean actions require confirm=true and use fixed arguments only."""
        return execute_provider_action(
            ctx.workspace_input,
            provider=provider,
            action=action,
            query=query,
            target=target,
            confirm=confirm,
            force=force,
            limit=limit,
            depth=depth,
        )

    @safe_mcp_tool(mcp, ctx)
    def mc_mcp_bridge(
        action: str = "",
        provider: str = "",
        query: str = "",
        target: str = "",
        confirm: bool = False,
        evidence_refs_json: str = "",
    ):
        """Inspect or invoke a policy-whitelisted external HTTP MCP tool, or fuse redacted EvidenceRef claims. Leave action empty to inspect allowed providers; pass evidence_refs_json as a JSON EvidenceRef array to fuse claims. Only registered tools and fixed argument templates are callable. Controlled-write or destructive actions require confirm=true."""
        if evidence_refs_json.strip():
            try:
                evidence_refs = json.loads(evidence_refs_json)
            except json.JSONDecodeError as exc:
                raise InvalidInputError("evidence_refs_json must be a JSON array") from exc
            if not isinstance(evidence_refs, list) or not all(isinstance(item, dict) for item in evidence_refs):
                raise InvalidInputError("evidence_refs_json must be a JSON array of objects")
            return fuse_provider_evidence(ctx.workspace_input, evidence_refs)
        if not action.strip():
            return mcp_bridge_status(ctx.workspace_input)
        if not provider.strip():
            return {
                "status": "invalid_input",
                "reason": "provider_required_for_mcp_bridge_action",
                "next_action": "先调用 mc_mcp_bridge() 查看已登记 provider，再指定 provider 与 action。",
            }
        return execute_mcp_bridge_action(
            ctx.workspace_input,
            provider=provider,
            action=action,
            query=query,
            target=target,
            confirm=confirm,
        )

    @safe_mcp_tool(mcp, ctx)
    def mc_start(
        intent: str,
        limit: int = 12,
        auto_sync_mode: str = "balanced",
        sync_task_space: bool = True,
        budget: str = "medium",
        deadline_ms: int = 5_000,
        request_tier: str = "standard",
    ):
        """Start a new task workflow. Sniffs workspace context, optionally syncs to task space, and starts a session. Returns consolidated context with services, files, rules, risk level, session_id, and task_id."""
        from memory_center.application.task_start import start_task

        result = start_task(ctx.workspace_file, intent, limit=limit, auto_sync_mode=auto_sync_mode, sync_task_space=sync_task_space, budget=budget, deadline_ms=deadline_ms, request_tier=request_tier)
        result["context_pack_recommendation"] = _build_context_pack_recommendation(ctx.workspace_file, intent, result["sniff"])
        return result

    # ===================== FACADE 2: mc_lookup =====================
    @safe_mcp_tool(mcp, ctx)
    def mc_lookup(
        query: str,
        mode: str = "auto",
        intent: str = "",
        name: str = "",
        scope: str = "",
        symbol: str = "",
        chain_direction: str = "callers",
        depth: int = 2,
        entry: str = "",
        ref_id: str = "",
        ref_ids: list[str] | None = None,
        limit: int = 20,
        project: str = "",
        report_level: str = "standard",
        enable_vector: bool = False,
        vector_weight: float = 0.15,
        session_id: str = "",
        request_tier: str = "standard",
    ):
        """Unified knowledge lookup. Mode selects strategy: auto (system decides via lookup_hint), symbol (resolve name), code (keyword search), query (graph-aware multi-source), trace (cross-service by class/Feign/endpoint/MQ), chain (caller/callee analysis, use chain_direction), walkthrough (method-level indexed walkthrough), context (360-degree context for a service/symbol), contracts (list all Feign/API/MQ contracts), ref (resolve short memory reference IDs). For Class#method requests that say full chain/全链路/到底层, prefer mode='walkthrough' or auto; walkthrough returns summary_lines, local_service_continuations, feign_continuations.server_walkthroughs, service_impl_continuations, and absolute_file_path. If absolute_file_path is present, read that path directly and do not run find/grep/IDEA search to locate the same controller or impl. Use project to disambiguate when multiple modules contain the same symbol name."""
        wf = ctx.workspace_file
        from memory_center.application.lookup import finalize_lookup, prepare_lookup

        lookup_target = query or symbol or name or entry
        prepared = prepare_lookup(
            wf,
            lookup_target,
            request_tier=request_tier,
            limit=limit,
            depth=depth,
            enable_vector=enable_vector,
            project=project,
        )
        plan = prepared["plan"]
        limit, depth, enable_vector = plan.limit, plan.depth, plan.enable_vector
        if plan.tier == "fast":
            report_level = "compact"

        def emit(payload: dict[str, Any], emitted_mode: str) -> dict[str, Any]:
            payload = finalize_lookup(wf, lookup_target, payload, prepared, "mc_lookup")
            if session_id.strip():
                workspace_record_agent_guidance(
                    wf,
                    session_id,
                    query=query,
                    mode=emitted_mode,
                    source="mcp.mc_lookup",
                    payload=payload,
                )
            return payload

        resolved_symbol = extract_symbol_like_token(symbol, name, entry, query)
        resolved_depth = max(depth, 4) if wants_deep_chain(query, intent, symbol, name, entry) else depth
        if mode == "auto":
            # A full-chain request with an explicit method already has a
            # precise indexed entrypoint. Do not run the broad sniff/hint
            # preflight first: on a large workspace it needlessly loads and
            # scans the full symbol index before the walkthrough begins.
            if wants_deep_chain(query, intent, symbol, name, entry) and "#" in resolved_symbol:
                result = memory_method_walkthrough(
                    wf,
                    resolved_symbol,
                    depth=resolved_depth,
                    limit=min(max(1, limit), 20),
                    project=project,
                    view="compact",
                    budget="small",
                    report_level=report_level,
                )
                payload = flatten_walkthrough_payload(result, mode_key="mode_used")
                payload["routing_note"] = "auto selected direct walkthrough for Class#method full-chain query; broad workspace sniff was skipped."
                return emit(payload, "walkthrough")
            hint = workspace_lookup_hint(wf, query=query, intent=intent, limit=limit)
            preferred = hint.get("preferred_tools", [])
            decision_fields = {
                "lookup_hint": hint,
                "candidate_paths": hint.get("candidate_paths", []),
                "recommended_path": hint.get("recommended_candidate_path", {}),
            }
            # preferred_tools returns names with "_tool" suffix (e.g. "memory_symbol_tool")
            # Strip suffix for cleaner matching
            preferred_bare = [t.replace("_tool", "") for t in preferred]
            if "memory_callers" in preferred_bare and resolved_symbol:
                matching_groups = find_groups_for_workspace(wf)
                if len(matching_groups) == 1:
                    result = group_chain(matching_groups[0], resolved_symbol, direction="callers", depth=resolved_depth, limit=limit)
                    result["agent_next_steps"] = _agent_next_steps_for_lookup_route("chain-group", result, query)
                    return emit(_lookup_payload_with_agent_steps("mode_used", "chain-group", result, **decision_fields), "chain-group")
                result = memory_callers(wf, resolved_symbol, resolved_depth, limit, project=project, view="compact", budget="small")
                _annotate_phantom_nodes(result, wf)
                result["agent_next_steps"] = _agent_next_steps_for_lookup_route("chain-callers", result, query)
                if len(matching_groups) > 1:
                    return emit(_lookup_payload_with_agent_steps("mode_used", "chain-callers", result, matching_groups=matching_groups, _hint=f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。", **decision_fields), "chain-callers")
                return emit(_lookup_payload_with_agent_steps("mode_used", "chain-callers", result, **decision_fields), "chain-callers")
            if "memory_callees" in preferred_bare and resolved_symbol:
                matching_groups = find_groups_for_workspace(wf)
                if len(matching_groups) == 1:
                    result = group_chain(matching_groups[0], resolved_symbol, direction="callees", depth=resolved_depth, limit=limit)
                    result["agent_next_steps"] = _agent_next_steps_for_lookup_route("chain-group", result, query)
                    return emit(_lookup_payload_with_agent_steps("mode_used", "chain-group", result, **decision_fields), "chain-group")
                result = memory_callees(wf, resolved_symbol, resolved_depth, limit, project=project, view="compact", budget="small")
                _annotate_phantom_nodes(result, wf)
                result["agent_next_steps"] = _agent_next_steps_for_lookup_route("chain-callees", result, query)
                if len(matching_groups) > 1:
                    return emit(_lookup_payload_with_agent_steps("mode_used", "chain-callees", result, matching_groups=matching_groups, _hint=f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。", **decision_fields), "chain-callees")
                return emit(_lookup_payload_with_agent_steps("mode_used", "chain-callees", result, **decision_fields), "chain-callees")
            if "memory_symbol" in preferred_bare and (name or resolved_symbol or query):
                from memory_center.core.retrieval.templates import find_symbols

                result = find_symbols(wf, name or resolved_symbol or query, tier=plan.tier, limit=limit, project=project)
                result["agent_next_steps"] = _agent_next_steps_for_lookup_route("symbol", result, query)
                return emit(_lookup_payload_with_agent_steps("mode_used", "symbol", result, **decision_fields), "symbol")
            if "memory_search_code" in preferred_bare:
                result = memory_search_code(wf, query, scope, limit, project=project)
                result["agent_next_steps"] = _agent_next_steps_for_lookup_route("code", result, query)
                return emit(_lookup_payload_with_agent_steps("mode_used", "code", result, **decision_fields), "code")
            if "memory_context" in preferred_bare and (name or resolved_symbol or query):
                result = memory_context(wf, name or resolved_symbol or query, resolved_depth, project=project, view="compact", budget="small")
                result["agent_next_steps"] = _agent_next_steps_for_lookup_route("context", result, query)
                return emit(_lookup_payload_with_agent_steps("mode_used", "context", result, **decision_fields), "context")
            if "workspace_trace" in preferred_bare and (entry or resolved_symbol or query):
                result = workspace_trace(wf, entry or resolved_symbol or query)
                result["agent_next_steps"] = _agent_next_steps_for_lookup_route("trace", result, query)
                return emit(_lookup_payload_with_agent_steps("mode_used", "trace", result, **decision_fields), "trace")
            query_result = memory_query_hybrid(
                    wf,
                    query,
                    limit,
                    project=project,
                    enable_vector=enable_vector,
                    vector_weight=vector_weight,
                )
            return emit(_lookup_payload_with_agent_steps("mode_used", "query", query_result, **decision_fields), "query")
        if mode == "symbol":
            from memory_center.core.retrieval.templates import find_symbols

            result = find_symbols(wf, name or query, tier=plan.tier, limit=limit, project=project)
            result["agent_next_steps"] = _agent_next_steps_for_lookup_route("symbol", result, query)
            return emit(_lookup_payload_with_agent_steps("mode", "symbol", result), "symbol")
        if mode == "code":
            result = memory_search_code(wf, query, scope, limit, project=project)
            result["agent_next_steps"] = _agent_next_steps_for_lookup_route("code", result, query)
            return emit(_lookup_payload_with_agent_steps("mode", "code", result), "code")
        if mode == "query":
            query_result = memory_query_hybrid(
                    wf,
                    query,
                    limit,
                    project=project,
                    enable_vector=enable_vector,
                    vector_weight=vector_weight,
                )
            return emit(_lookup_payload_with_agent_steps("mode", "query", query_result), "query")
        if mode == "trace":
            result = workspace_trace(wf, entry or query)
            result["agent_next_steps"] = _agent_next_steps_for_lookup_route("trace", result, query)
            return emit(_lookup_payload_with_agent_steps("mode", "trace", result), "trace")
        if mode == "chain":
            from memory_center.core.retrieval.templates import trace_call_paths

            cross_types = ["CALLS_SERVICE", "IMPLEMENTS_FEIGN"] if scope == "cross-service" else None
            matching_groups = find_groups_for_workspace(wf)
            if len(matching_groups) == 1:
                result = group_chain(matching_groups[0], symbol or query,
                                      direction=chain_direction, depth=depth, limit=limit)
                result["agent_next_steps"] = _agent_next_steps_for_lookup_route("chain-group", result, query)
                return emit(_lookup_payload_with_agent_steps("mode", "chain-group", result), "chain-group")
            if len(matching_groups) > 1:
                result = trace_call_paths(wf, symbol or query, direction=chain_direction, tier=plan.tier, depth=depth, limit=limit, project=project)
                if cross_types:
                    if chain_direction == "callees":
                        result = memory_callees(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project, view="compact", budget="small")
                    else:
                        result = memory_callers(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project, view="compact", budget="small")
                _annotate_phantom_nodes(result, wf)
                result["agent_next_steps"] = _agent_next_steps_for_lookup_route(f"chain-{chain_direction}", result, query)
                return emit(_lookup_payload_with_agent_steps("mode", f"chain-{chain_direction}", result, matching_groups=matching_groups, _hint=f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。"), f"chain-{chain_direction}")
            result = trace_call_paths(wf, symbol or query, direction=chain_direction, tier=plan.tier, depth=depth, limit=limit, project=project)
            if cross_types:
                if chain_direction == "callees":
                    result = memory_callees(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project, view="compact", budget="small")
                else:
                    result = memory_callers(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project, view="compact", budget="small")
            _annotate_phantom_nodes(result, wf)
            result["agent_next_steps"] = _agent_next_steps_for_lookup_route(f"chain-{chain_direction}", result, query)
            return emit(_lookup_payload_with_agent_steps("mode", f"chain-{chain_direction}", result), f"chain-{chain_direction}")
        if mode == "walkthrough":
            result = memory_method_walkthrough(wf, symbol or resolved_symbol or query, depth=depth, limit=limit, project=project, view="compact", budget="small", report_level=report_level)
            return emit(flatten_walkthrough_payload(result, mode_key="mode"), "walkthrough")
        if mode == "context":
            result = memory_context(wf, name or query, depth, project=project, view="compact", budget="small")
            result["agent_next_steps"] = _agent_next_steps_for_lookup_route("context", result, query)
            return emit(_lookup_payload_with_agent_steps("mode", "context", result), "context")
        if mode == "contracts":
            return {"mode": "contracts", "result": memory_contracts(wf)}
        if mode == "ref":
            if ref_ids:
                return {"mode": "ref-batch", "result": memory_ref_batch(wf, ref_ids)}
            return {"mode": "ref-get", "result": memory_ref_get(wf, ref_id=ref_id)}
        if mode == "backend":
            return {"mode": "backend", "result": memory_backend_query(wf, collection="", record_id="", created_after="", ref_path="", project=scope, payload_type="", limit=limit)}
        raise ValueError(f"Unknown mc_lookup mode: {mode}. Valid: auto, symbol, code, query, trace, chain, walkthrough, context, contracts, ref, backend")

    # ===================== FACADE 3: mc_analyze =====================
    @safe_mcp_tool(mcp, ctx)
    def mc_analyze(
        target: str,
        depth: str = "standard",
        direction: str = "upstream",
        max_depth: int = 3,
        project: str = "",
        contract_file: str = "",
        change_type: str = "modify",
        projects: list[str] | None = None,
        files: list[str] | None = None,
        scope: str = "staged",
        task_id: str = "",
        execution_mode: str = "sync",
        job_action: str = "",
        job_id: str = "",
    ):
        """Analyze change impact and generate action plans. Depth quick: impact only. Depth standard: impact + change plan + rules check. Depth full: standard + contract check + verification checklist. If target is empty, runs detect-changes instead of impact."""
        wf = ctx.workspace_file
        validate_analyze_request(depth, direction, max_depth, execution_mode)
        if job_action == "status":
            from memory_center.application.jobs import analysis_job_status
            return {"workflow": "mc-analyze", "job": analysis_job_status(wf, job_id)}
        if job_action == "cancel":
            from memory_center.application.jobs import cancel_analysis_job
            return {"workflow": "mc-analyze", "job": cancel_analysis_job(wf, job_id)}

        def run_analysis() -> dict[str, Any]:
            return _run_analysis()

        def _run_analysis() -> dict[str, Any]:
            project_filter = project or ((projects or [None])[0] or "")
            if target:
                impact_result = memory_impact(wf, target, direction, max_depth, project=project_filter, view="compact", budget="small")
            else:
                impact_result = memory_detect_changes(wf, scope)
            result = {"workflow": "mc-analyze", "depth": depth, "impact": impact_result, "analysis_status": "complete", "diagnostics": {}}
            from memory_center.core.freshness.contract import attach_contract

            result_count = len(impact_result.get("candidate_paths", []) or []) if isinstance(impact_result, dict) else 0
            try:
                attach_contract(result, wf, request_tier="standard", result_count=result_count)
            except Exception:
                pass
            if target:
                result["candidate_paths"] = impact_result.get("candidate_paths", [])
                result["recommended_path"] = impact_result.get("recommended_path", {})
            if depth in ("standard", "full") and target:
                from memory_center.core.retrieval.templates import find_contract_consumers

                plan, plan_diagnostic = degraded_analysis_step("plan", lambda: memory_plan_change(wf, target, direction, max_depth))
                rules, rules_diagnostic = degraded_analysis_step("rules", lambda: workspace_check_rules(wf, projects, change_type, files))
                consumers, consumers_diagnostic = degraded_analysis_step("contract_consumers", lambda: find_contract_consumers(wf, target, tier="standard", project=project_filter))
                if plan is not None:
                    result["plan"] = plan
                if rules is not None:
                    result["rules"] = rules
                if consumers is not None:
                    result["contract_consumers"] = {
                        "found": consumers.get("found", False),
                        "consumers": consumers.get("consumers", []),
                        "query_budget": consumers.get("query_budget", {}),
                    }
                if plan_diagnostic:
                    result["diagnostics"]["plan"] = plan_diagnostic
                if rules_diagnostic:
                    result["diagnostics"]["rules"] = rules_diagnostic
                if consumers_diagnostic:
                    result["diagnostics"]["contract_consumers"] = consumers_diagnostic
            if depth == "full" and target:
                contract, contract_diagnostic = degraded_analysis_step("contract", lambda: workspace_check_contract(wf, contract_file or target, change_type))
                checklist, checklist_diagnostic = degraded_analysis_step("checklist", lambda: memory_verify_checklist(wf, target))
                if contract is not None:
                    result["contract"] = contract
                if checklist is not None:
                    result["checklist"] = checklist
                if contract_diagnostic:
                    result["diagnostics"]["contract"] = contract_diagnostic
                if checklist_diagnostic:
                    result["diagnostics"]["checklist"] = checklist_diagnostic
                if task_id.strip() and contract is not None:
                    from memory_center.application.jobs import write_contract_evidence
                    evidence, evidence_diagnostic = degraded_analysis_step("contract_evidence", lambda: write_contract_evidence(wf, task_id, contract))
                    if evidence is not None:
                        result["contract_evidence"] = evidence
                    if evidence_diagnostic:
                        result["diagnostics"]["contract_evidence"] = evidence_diagnostic
            if result["diagnostics"]:
                result["analysis_status"] = "partial"
                result["next_action"] = "影响图已返回；修复 diagnostics 中不可用阶段后重试，或先沿 candidate_paths 验证高置信影响。"
            return result

        if execution_mode == "background":
            from memory_center.application.jobs import submit_analysis_job
            return {"workflow": "mc-analyze", "job": submit_analysis_job(wf, run_analysis), "execution_mode": "background"}
        return run_analysis()

    # ===================== FACADE 4: mc_sync =====================
    @safe_mcp_tool(mcp, ctx)
    def mc_sync(
        intent: str = "",
        session_id: str = "",
        task_id: str = "",
        title: str = "",
        limit: int = 12,
        auto_sync_mode: str = "balanced",
    ):
        """Sync task context to workspace artifacts. Provide intent for sniff-sync, or session_id for case-sync. session_id takes precedence if both provided."""
        wf = ctx.workspace_file
        if session_id.strip():
            return {"workflow": "mc-sync", "mode": "case", "result": workspace_sync_case_to_artifacts(wf, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)}
        if intent.strip():
            return {"workflow": "mc-sync", "mode": "sniff", "result": workspace_sync_sniff_to_artifacts(wf, intent, limit=limit, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)}
        raise ValueError("mc_sync requires intent or session_id")

    # ===================== FACADE 5: mc_resume =====================
    @safe_mcp_tool(mcp, ctx)
    def mc_resume(
        intent: str = "",
        task_id: str = "",
        session_id: str = "",
        limit: int = 8,
        budget: str = "medium",
    ):
        """Resume a task with consolidated context. Returns resume packet, next actions, unresolved items, and recent evidence. Provide intent, task_id, or session_id to focus the resume."""
        wf = ctx.workspace_file
        return {
            "workflow": "mc-resume",
            "resume_packet": workspace_resume_packet(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "next_actions": workspace_next_actions(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "unresolved_items": workspace_unresolved_items(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "recent_evidence": workspace_recent_evidence(wf, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
        }

    # ===================== FACADE 6: mc_handoff =====================
    @safe_mcp_tool(mcp, ctx)
    def mc_handoff(
        target_model: str,
        task_id: str = "",
        session_id: str = "",
        intent: str = "",
        limit: int = 8,
        budget: str = "medium",
    ):
        """Build a handoff package for another model or session. Returns handoff packet, recent evidence, and tool usage report. Essential for multi-model workflows and context transfer."""
        wf = ctx.workspace_file
        return {
            "workflow": "mc-handoff",
            "handoff_packet": workspace_handoff_packet(wf, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "recent_evidence": workspace_recent_evidence(wf, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
            "tool_usage_report": memory_tool_usage_report(wf, limit=50),
        }

    # ===================== FACADE 7: mc_close =====================
    @safe_mcp_tool(mcp, ctx)
    def mc_close(
        session_id: str,
        outcome: str = "",
        task_id: str = "",
        title: str = "",
        auto_sync_mode: str = "balanced",
        record_case: bool = True,
        verified_by: list[str] | None = None,
        validation_command: str = "",
        validation_exit_code: int | None = None,
        validation_summary: str = "",
        validation_status: str = "",
    ):
        """Close a task workflow. Optionally record a completed validation command and result; the command is never executed by this tool."""
        wf = ctx.workspace_file
        ended = workspace_end_session(
            wf,
            session_id,
            outcome,
            verified_by,
            validation_command=validation_command,
            validation_exit_code=validation_exit_code,
            validation_summary=validation_summary,
            validation_status=validation_status,
        )
        synced = workspace_sync_case_to_artifacts(wf, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)
        draft = workspace_suggest_case(wf, session_id)
        recorded = None
        candidate_feedback = None
        case = draft.get("draft_case", {}) if draft.get("found") else {}
        if record_case and case.get("projects") and case.get("files"):
            recorded = workspace_record_case(
                wf, case.get("task", outcome or "mc-close"),
                case.get("projects", []), case.get("files", []),
                case.get("flow", ""), case.get("risk_points", []),
                verified_by=case.get("verified_by", []) or verified_by,
                source_session_id=session_id, source_task_id=task_id,
            )
        candidate_feedback = workspace_record_close_feedback(
            wf,
            session_id,
            task_id=task_id,
            source="mc_close_auto",
        )
        return {
            "workflow": "mc-close",
            "ended": ended,
            "sync_case": synced,
            "suggested_case": draft,
            "record_case": recorded,
            "candidate_feedback": candidate_feedback,
        }

    # ===================== FACADE 8: mc_admin =====================
    @safe_mcp_tool(mcp, ctx)
    def mc_admin(
        action: str,
        view: str = "compact",
        budget: str = "medium",
        limit: int = 10,
        name: str = "",
        content: str = "",
        task_id: str = "",
        title: str = "",
        intent: str = "",
        owner: str = "",
        tags: list[str] | None = None,
        priority: str = "medium",
        status: str = "",
        source: str = "",
        reason: str = "",
        include_archived: bool = False,
        create_if_missing: bool = True,
        score_threshold: int = 3,
        limit_candidates: int = 3,
        entry: str = "",
        keep_recent: int = 30,
        session_id: str = "",
        event_type: str = "",
        payload: str = "",
        outcome: str = "",
        verified_by: list[str] | None = None,
        target_model: str = "codex",
        scope: str = "all",
        tool_name: str = "",
        model: str = "",
        text: str = "",
        prefer_layer: str = "",
        projects: list[str] | None = None,
        files: list[str] | None = None,
        group: str = "",
        direction: str = "upstream",
        max_depth: int = 3,
        output_dir: str = "",
        collection: str = "",
        record_id: str = "",
        created_after: str = "",
        ref_path: str = "",
        project: str = "",
        payload_type: str = "",
        layer: str = "",
        action_filter: str = "",
        force: bool = False,
        strict: bool = False,
    ):
        """管理与维护操作：高级检索、ANN、重排器预热、模型档案和回放评测。"""
        wf = ctx.workspace_file
        from memory_center.application.admin import build_admin_registry
        registry = build_admin_registry(
            workspace_file=wf,
            action=action,
            view=view,
            budget=budget,
            limit=limit,
            name=name,
            content=content,
            task_id=task_id,
            title=title,
            intent=intent,
            owner=owner,
            tags=tags,
            priority=priority,
            status=status,
            source=source,
            reason=reason,
            include_archived=include_archived,
            create_if_missing=create_if_missing,
            score_threshold=score_threshold,
            limit_candidates=limit_candidates,
            entry=entry,
            keep_recent=keep_recent,
            session_id=session_id,
            event_type=event_type,
            payload=payload,
            outcome=outcome,
            verified_by=verified_by,
            target_model=target_model,
            scope=scope,
            tool_name=tool_name,
            model=model,
            text=text,
            prefer_layer=prefer_layer,
            projects=projects,
            files=files,
            group=group,
            direction=direction,
            max_depth=max_depth,
            output_dir=output_dir,
            collection=collection,
            record_id=record_id,
            created_after=created_after,
            ref_path=ref_path,
            project=project,
            payload_type=payload_type,
            layer=layer,
            action_filter=action_filter,
            force=force,
            strict=strict,
        )
        return {"action": action, "result": registry.dispatch(action)}

    from memory_center.mcp.insights import register_insight_surface

    register_insight_surface(mcp, ctx)
    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=".", help="Path to workspace.yaml or a project directory")
    args = parser.parse_args()
    server = create_server(args.workspace)
    server.run()


if __name__ == "__main__":
    main()
