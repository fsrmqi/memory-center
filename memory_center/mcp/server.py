"""Memory Center MCP server — 8 facade tools (task-level interface).

Previously exposed 82 atomic tools; now consolidated into 8 task-level facades:
  mc_start   — begin a task workflow (sniff + sync + session)
  mc_lookup  — unified knowledge lookup (auto/symbol/code/query/trace/chain/context/contracts/ref)
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
import inspect
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_center.core.orchestrator import (
    group_chain,
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
    memory_query_hybrid,
    memory_backend_query,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    memory_plan_write,
    memory_execute_write,
    memory_tool_usage_report,
    memory_discover,
    memory_eval_write_quality,
    memory_eval_regression_suite,
    memory_eval_index_freshness,
    memory_eval_tool_adoption,
    memory_eval_context_weight,
    memory_eval_workflow_orchestration,
    memory_eval_resume,
    memory_eval_handoff,
    memory_eval_token_gain,
    memory_eval_parser_benchmark,
    memory_eval_token_benchmark,
    memory_write_judge,
    workspace_end_session,
    workspace_log_session_event,
    workspace_recent_sessions,
    workspace_recent_evidence,
    workspace_handoff_packet,
    workspace_handoff_history,
    workspace_model_profile,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_lookup_hint,
    workspace_resume_packet,
    workspace_resume_context,
    workspace_suggest_case,
    workspace_check_contract,
    workspace_check_rules,
    workspace_record_case,
    workspace_record_close_feedback,
    workspace_session_summary,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_trace,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_unresolved_items,
    workspace_write_receipts,
    workspace_replay_write_chain,
    workspace_next_actions,
    _annotate_phantom_nodes,
)
from memory_center.core.registry import load_registry
from memory_center.core.verification.loop import VerificationLoop
from memory_center.core.verification.pattern_promotion import PatternPromotion
from memory_center.core.verification.heuristics import HeuristicsRegister
from memory_center.core.verification.workflow_profiles import get_workflow_profile, recommend_workflow, recommend_workflow_with_learning
from memory_center.core.verification.bundle_export import generate_agent_bundle
from memory_center.core.audit.runtime import audit_agent_runtime
from memory_center.core.explanation.schema import Explanation
from memory_center.core.errors import normalize_exception
from memory_center.core.domain.flow import business_flow_impact_for_workspace, extract_business_flows_for_workspace
from memory_center.core.metrics import MetricsCollector
from memory_center.core.store import WorkspaceStore
from memory_center.core.benchmark.trending import check_regression_alerts
from memory_center.core.artifacts import (
    append_change_log,
    append_task_change_log,
    archive_task_space,
    artifact_context,
    artifact_outline,
    auto_archive_task_spaces,
    compact_change_log,
    create_task_space,
    get_artifact,
    get_task_artifact,
    list_artifacts,
    list_task_spaces,
    resolve_task_space,
    touch_task_activity,
    update_task_status,
    update_artifact,
    update_task_artifact,
)
from memory_center.core.wiki import generate_skills, generate_wiki

def _find_workspace_name_in_registry(workspace_file: str, registry: Dict[str, Any]) -> str | None:
    wf_resolved = str(Path(workspace_file).expanduser().resolve())
    for repo in registry.get("repos", []):
        if str(Path(repo.get("workspace_file", "")).expanduser().resolve()) == wf_resolved:
            return repo.get("name")
    return None

def _find_groups_for_workspace(workspace_file: str) -> List[str]:
    registry = load_registry()
    ws_name = _find_workspace_name_in_registry(workspace_file, registry)
    if not ws_name:
        return []
    groups: List[str] = []
    for group in registry.get("groups", []):
        if ws_name in group.get("members", []):
            groups.append(group.get("name", ""))
    return groups

class _WorkspaceContext:
    """Holds workspace file path per server instance, avoiding module-level global."""
    def __init__(self, workspace_file: str):
        self.workspace_file = workspace_file


def _parse_payload(payload_str: str) -> Dict[str, Any] | None:
    """Parse a JSON string payload for MCP tool compatibility."""
    if not payload_str:
        return None
    try:
        import json
        result = json.loads(payload_str)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _benchmark_trend_report(workspace_file: str, function_name: str = "") -> Dict[str, Any]:
    """Generate benchmark trend report for mc_admin."""
    from ..core.benchmark.trending import generate_benchmark_report
    return generate_benchmark_report(workspace_file, function_name=function_name)


def _run_audit(workspace_file: str, work_package: str = "") -> Dict[str, Any]:
    """Run completion audit for mc_admin."""
    from ..core.audit.completion import run_completion_audit
    return run_completion_audit(workspace_file, work_package=work_package)


def _drill_ref(workspace_file: str, ref_id: str = "") -> Dict[str, Any]:
    """Expand a ref with progressive disclosure for mc_admin."""
    from ..core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.expand_ref(ref_id)


def _drill_timeline(workspace_file: str, session_id: str = "", task_id: str = "", limit: int = 50) -> Dict[str, Any]:
    """Drill into timeline for mc_admin."""
    from ..core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.drill_timeline(session_id=session_id, task_id=task_id, limit=limit)


def _drill_task(workspace_file: str, task_id: str = "") -> Dict[str, Any]:
    """Drill into task context for mc_admin."""
    from ..core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.drill_task(task_id)


def _backend_consistency(workspace_file: str) -> Dict[str, Any]:
    """Check backend consistency for mc_admin."""
    from ..core.store import WorkspaceStore
    from ..core.backend.query import UnifiedBackendQuery
    store = WorkspaceStore(workspace_file)
    with UnifiedBackendQuery(store.memory_db_path) as backend:
        return backend.check_consistency(store.base_dir)


def _constraint_action(context: str = "", template: str = "coding_agent") -> Dict[str, Any]:
    """Show constraint template or auto-select action for mc_admin."""
    from ..core.templates import get_constraint_template, auto_select_action
    if context:
        action = auto_select_action(context, template)
        return {"context": context, "template": template, "recommended_action": action}
    tmpl = get_constraint_template(template)
    return tmpl or {"error": f"Unknown template: {template}"}

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


def _mcp_error_boundary(fn):
    """Wrap an MCP tool without changing its registered schema."""
    if inspect.iscoroutinefunction(fn):
        @wraps(fn)
        async def async_wrapped(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                return normalize_exception(exc).to_mcp_dict()

        return async_wrapped

    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            return normalize_exception(exc).to_mcp_dict()

    return wrapped


def _safe_mcp_tool(mcp):
    """Register an MCP tool with the unified error boundary."""
    def decorator(fn):
        return mcp.tool()(_mcp_error_boundary(fn))

    return decorator


def create_server(workspace_file: str):
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Please install MCP dependency: pip install -e .[mcp]") from exc

    ctx = _WorkspaceContext(workspace_file)
    mcp = FastMCP("Memory Center")

    # Import workflow templates for guidance
    from memory_center.core.templates import get_workflow_guidance

    # ===================== FACADE 1: mc_start =====================
    @_safe_mcp_tool(mcp)
    def mc_start(
        intent: str,
        limit: int = 12,
        auto_sync_mode: str = "balanced",
        sync_task_space: bool = True,
        budget: str = "medium",
    ):
        """Start a new task workflow. Sniffs workspace context, optionally syncs to task space, and starts a session. Returns consolidated context with services, files, rules, risk level, session_id, and task_id."""
        wf = ctx.workspace_file
        sniff_result = workspace_sniff(wf, intent, limit=limit, auto_sync_mode=auto_sync_mode, view="compact", budget=budget)
        synced = None
        resolved_task = sniff_result.get("resolved_task", {}) or {}
        auto_sync = sniff_result.get("auto_sync_recommendation", {}) or {}
        if sync_task_space and (auto_sync.get("recommended") or resolved_task.get("task_id")):
            synced = workspace_sync_sniff_to_artifacts(
                wf, intent, limit=limit,
                task_id=str(resolved_task.get("task_id", "") or ""),
                title=str(resolved_task.get("title", "") or ""),
                auto_sync_mode=auto_sync_mode,
            )
        session = workspace_start_session(wf, intent)
        guidance = get_workflow_guidance("work-start", {"risk_level": sniff_result.get("risk_level", ""), "task_id": resolved_task.get("task_id", "")})
        # D-01: Freshness enters mc_start main chain
        try:
            from memory_center.core.freshness.integration import get_freshness_with_actions
            _freshness = get_freshness_with_actions(wf)
        except Exception:
            _freshness = {"status": "unknown", "recommended_actions": [], "semantics": ""}
        # D-02: Context Pack recommendation for architecture/change intents
        _cp_rec = _build_context_pack_recommendation(wf, intent, sniff_result)
        return {"workflow": "mc-start", "sniff": sniff_result, "sync_sniff": synced, "session": session, "_workflow_guidance": guidance, "freshness": _freshness, "context_pack_recommendation": _cp_rec}

    # ===================== FACADE 2: mc_lookup =====================
    @_safe_mcp_tool(mcp)
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
        ref_ids: List[str] | None = None,
        limit: int = 20,
        project: str = "",
    ):
        """Unified knowledge lookup. Mode selects strategy: auto (system decides via lookup_hint), symbol (resolve name), code (keyword search), query (graph-aware multi-source), trace (cross-service by class/Feign/endpoint/MQ), chain (caller/callee analysis, use chain_direction), context (360-degree context for a service/symbol), contracts (list all Feign/API/MQ contracts), ref (resolve short memory reference IDs). Use project to disambiguate when multiple modules contain the same symbol name."""
        wf = ctx.workspace_file
        if mode == "auto":
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
            if "memory_symbol" in preferred_bare and (name or query):
                return {"mode_used": "symbol", "result": memory_symbol(wf, name or query, limit, project=project), **decision_fields}
            if "memory_search_code" in preferred_bare:
                return {"mode_used": "code", "result": memory_search_code(wf, query, scope, limit, project=project), **decision_fields}
            if "memory_context" in preferred_bare and (name or query):
                return {"mode_used": "context", "result": memory_context(wf, name or query, depth, project=project), **decision_fields}
            if "workspace_trace" in preferred_bare and (entry or query):
                return {"mode_used": "trace", "result": workspace_trace(wf, entry or query), **decision_fields}
            if "memory_callers" in preferred_bare and (symbol or query):
                matching_groups = _find_groups_for_workspace(wf)
                if len(matching_groups) == 1:
                    result = group_chain(matching_groups[0], symbol or query, direction="callers", depth=depth, limit=limit)
                    return {"mode_used": "chain-group", "result": result, **decision_fields}
                result = memory_callers(wf, symbol or query, depth, limit, project=project)
                _annotate_phantom_nodes(result, wf)
                if len(matching_groups) > 1:
                    return {"mode_used": "chain-callers", "result": result, "matching_groups": matching_groups, "_hint": f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。", **decision_fields}
                return {"mode_used": "chain-callers", "result": result, **decision_fields}
            if "memory_callees" in preferred_bare and (symbol or query):
                matching_groups = _find_groups_for_workspace(wf)
                if len(matching_groups) == 1:
                    result = group_chain(matching_groups[0], symbol or query, direction="callees", depth=depth, limit=limit)
                    return {"mode_used": "chain-group", "result": result, **decision_fields}
                result = memory_callees(wf, symbol or query, depth, limit, project=project)
                _annotate_phantom_nodes(result, wf)
                if len(matching_groups) > 1:
                    return {"mode_used": "chain-callees", "result": result, "matching_groups": matching_groups, "_hint": f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。", **decision_fields}
                return {"mode_used": "chain-callees", "result": result, **decision_fields}
            return {"mode_used": "query", "result": memory_query_hybrid(wf, query, limit, project=project), **decision_fields}
        if mode == "symbol":
            return {"mode": "symbol", "result": memory_symbol(wf, name or query, limit, project=project)}
        if mode == "code":
            return {"mode": "code", "result": memory_search_code(wf, query, scope, limit, project=project)}
        if mode == "query":
            return {"mode": "query", "result": memory_query_hybrid(wf, query, limit, project=project)}
        if mode == "trace":
            return {"mode": "trace", "result": workspace_trace(wf, entry or query)}
        if mode == "chain":
            cross_types = ["CALLS_SERVICE", "IMPLEMENTS_FEIGN"] if scope == "cross-service" else None
            matching_groups = _find_groups_for_workspace(wf)
            if len(matching_groups) == 1:
                result = group_chain(matching_groups[0], symbol or query,
                                      direction=chain_direction, depth=depth, limit=limit)
                return {"mode": "chain-group", "result": result}
            if len(matching_groups) > 1:
                if chain_direction == "callees":
                    result = memory_callees(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project)
                else:
                    result = memory_callers(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project)
                _annotate_phantom_nodes(result, wf)
                return {
                    "mode": f"chain-{chain_direction}",
                    "result": result,
                    "matching_groups": matching_groups,
                    "_hint": f"Workspace 属于多个 group ({', '.join(matching_groups)})，请用 mc_admin(action='group_chain', group=...) 显式指定。",
                }
            if chain_direction == "callees":
                result = memory_callees(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project)
            else:
                result = memory_callers(wf, symbol or query, depth, limit, edge_type_filter=cross_types, project=project)
            _annotate_phantom_nodes(result, wf)
            return {"mode": f"chain-{chain_direction}", "result": result}
        if mode == "context":
            return {"mode": "context", "result": memory_context(wf, name or query, depth, project=project)}
        if mode == "contracts":
            return {"mode": "contracts", "result": memory_contracts(wf)}
        if mode == "ref":
            if ref_ids:
                return {"mode": "ref-batch", "result": memory_ref_batch(wf, ref_ids)}
            return {"mode": "ref-get", "result": memory_ref_get(wf, ref_id=ref_id)}
        if mode == "backend":
            return {"mode": "backend", "result": memory_backend_query(wf, collection="", record_id="", created_after="", ref_path="", project=scope, payload_type="", limit=limit)}
        raise ValueError(f"Unknown mc_lookup mode: {mode}. Valid: auto, symbol, code, query, trace, chain, context, contracts, ref, backend")

    # ===================== FACADE 3: mc_analyze =====================
    @_safe_mcp_tool(mcp)
    def mc_analyze(
        target: str,
        depth: str = "standard",
        direction: str = "upstream",
        max_depth: int = 3,
        contract_file: str = "",
        change_type: str = "modify",
        projects: List[str] | None = None,
        files: List[str] | None = None,
        scope: str = "staged",
    ):
        """Analyze change impact and generate action plans. Depth quick: impact only. Depth standard: impact + change plan + rules check. Depth full: standard + contract check + verification checklist. If target is empty, runs detect-changes instead of impact."""
        wf = ctx.workspace_file
        if target:
            impact_result = memory_impact(wf, target, direction, max_depth)
        else:
            impact_result = memory_detect_changes(wf, scope)
        result = {"workflow": "mc-analyze", "depth": depth, "impact": impact_result}
        if target:
            result["candidate_paths"] = impact_result.get("candidate_paths", [])
            result["recommended_path"] = impact_result.get("recommended_path", {})
        if depth in ("standard", "full") and target:
            result["plan"] = memory_plan_change(wf, target, direction, max_depth)
            result["rules"] = workspace_check_rules(wf, projects, change_type, files)
        if depth == "full" and target:
            if contract_file:
                result["contract"] = workspace_check_contract(wf, contract_file, change_type)
            result["checklist"] = memory_verify_checklist(wf, target)
        return result

    # ===================== FACADE 4: mc_sync =====================
    @_safe_mcp_tool(mcp)
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
    @_safe_mcp_tool(mcp)
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
    @_safe_mcp_tool(mcp)
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
    @_safe_mcp_tool(mcp)
    def mc_close(
        session_id: str,
        outcome: str = "",
        task_id: str = "",
        title: str = "",
        auto_sync_mode: str = "balanced",
        record_case: bool = True,
        verified_by: List[str] | None = None,
    ):
        """Close a task workflow. Ends session, syncs case to artifacts, suggests case record, and optionally records it to cross-service memory."""
        wf = ctx.workspace_file
        ended = workspace_end_session(wf, session_id, outcome, verified_by)
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
    @_safe_mcp_tool(mcp)
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
        tags: List[str] | None = None,
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
        verified_by: List[str] | None = None,
        target_model: str = "codex",
        scope: str = "all",
        tool_name: str = "",
        model: str = "",
        text: str = "",
        prefer_layer: str = "",
        projects: List[str] | None = None,
        files: List[str] | None = None,
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
    ):
        """Admin and utility operations. Action selects sub-operation: status, dashboard, continuity, health, audit, discover, constraint, drill_ref, drill_timeline, drill_task, backend_consistency, artifact_list, artifact_get, artifact_outline, artifact_context, artifact_update, change_log_append, change_log_compact, task_create, task_list, task_resolve, task_get, task_update, task_change_log_append, task_archive, task_auto_archive, task_status, task_activity_touch, session_start, session_log, session_end, session_recent, session_summary, model_profile, handoff_history, write_judge, write_plan, write_execute, receipts, replay, backend_query, eval_write_quality, eval_resume, eval_handoff, eval_regression_suite, eval_index_freshness, eval_tool_adoption, eval_context_weight, eval_workflow_orchestration, eval_token_gain, eval_parser_benchmark, eval_token_benchmark, eval_token_benchmark_trend, tool_usage_report, generate_wiki, generate_skills, group_status, group_query, group_impact, group_chain."""
        wf = ctx.workspace_file
        _DISPATCH = {
            "status": lambda: workspace_status(wf, view=view, budget=budget),
            "dashboard": lambda: workspace_dashboard(wf, intent=intent, limit=limit, view=view, budget=budget),
            "continuity": lambda: workspace_continuity_dashboard(wf, intent=intent, task_id=task_id, session_id=session_id, limit=limit, view=view, budget=budget),
            "health": lambda: {
                "workflow": "mc-admin-health",
                "status": workspace_status(wf, view="compact", budget="medium"),
                "tool_usage_report": memory_tool_usage_report(wf, limit=50),
                "regression_suite": memory_eval_regression_suite(wf, intent=intent, target_model=target_model, limit=limit),
            },
            "artifact_list": lambda: list_artifacts(wf),
            "artifact_get": lambda: get_artifact(wf, name),
            "artifact_outline": lambda: artifact_outline(wf, name),
            "artifact_context": lambda: artifact_context(wf, intent, limit=limit),
            "artifact_update": lambda: update_artifact(wf, name, content),
            "change_log_append": lambda: append_change_log(wf, entry),
            "change_log_compact": lambda: compact_change_log(wf, keep_recent),
            "task_create": lambda: create_task_space(wf, title=title, intent=intent, owner=owner, tags=tags, priority=priority),
            "task_list": lambda: list_task_spaces(wf, include_archived=include_archived),
            "task_resolve": lambda: resolve_task_space(wf, intent=intent, title=title, create_if_missing=create_if_missing, include_archived=include_archived, limit_candidates=limit_candidates, score_threshold=score_threshold),
            "task_get": lambda: get_task_artifact(wf, task_id, name),
            "task_update": lambda: update_task_artifact(wf, task_id, name, content),
            "task_change_log_append": lambda: append_task_change_log(wf, task_id, entry, keep_recent=keep_recent),
            "task_archive": lambda: archive_task_space(wf, task_id, reason=reason),
            "task_auto_archive": lambda: auto_archive_task_spaces(wf, retention_days=keep_recent),
            "task_status": lambda: update_task_status(wf, task_id, status),
            "task_activity_touch": lambda: touch_task_activity(wf, task_id, source),
            "session_start": lambda: workspace_start_session(wf, intent, session_id=session_id or None),
            "session_log": lambda: workspace_log_session_event(wf, session_id, event_type, _parse_payload(payload)),
            "session_end": lambda: workspace_end_session(wf, session_id, outcome, verified_by),
            "session_recent": lambda: workspace_recent_sessions(wf, limit),
            "session_summary": lambda: workspace_session_summary(wf, session_id),
            "model_profile": lambda: workspace_model_profile(target_model),
            "handoff_history": lambda: workspace_handoff_history(wf, target_model=target_model, task_id=task_id, session_id=session_id, limit=limit),
            "write_judge": lambda: memory_write_judge(wf, text=text, source=source, intent=intent, prefer_layer=prefer_layer, projects=projects, files=files),
            "write_plan": lambda: memory_plan_write(wf, text=text, source=source, intent=intent, session_id=session_id, task_id=task_id, title=title, prefer_layer=prefer_layer, projects=projects, files=files),
            "write_execute": lambda: memory_execute_write(wf, text=text, source=source, intent=intent, session_id=session_id, task_id=task_id, title=title, prefer_layer=prefer_layer, projects=projects, files=files),
            "receipts": lambda: workspace_write_receipts(wf, layer=layer, action=action_filter, scope=scope, task_id=task_id, session_id=session_id, limit=limit),
            "replay": lambda: workspace_replay_write_chain(wf, task_id=task_id, session_id=session_id, limit=limit),
            "backend_query": lambda: memory_backend_query(wf, collection=collection, record_id=record_id, created_after=created_after, ref_path=ref_path, project=project, payload_type=payload_type, limit=limit),
            "eval_write_quality": lambda: memory_eval_write_quality(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "eval_resume": lambda: memory_eval_resume(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "eval_handoff": lambda: memory_eval_handoff(wf, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "eval_regression_suite": lambda: memory_eval_regression_suite(wf, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "eval_index_freshness": lambda: memory_eval_index_freshness(wf, scope=scope),
            "eval_tool_adoption": lambda: memory_eval_tool_adoption(wf, limit=limit),
            "eval_context_weight": lambda: memory_eval_context_weight(wf, intent=intent, limit=limit),
            "eval_workflow_orchestration": lambda: memory_eval_workflow_orchestration(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "eval_token_gain": lambda: memory_eval_token_gain(wf, tool_name=tool_name, budget=budget, model=model, limit=limit),
            "eval_parser_benchmark": lambda: memory_eval_parser_benchmark(wf, limit=limit),
            "eval_token_benchmark": lambda: memory_eval_token_benchmark(wf, intent=intent, limit=limit),
            "eval_token_benchmark_trend": lambda: _benchmark_trend_report(wf, name),
            "audit": lambda: _run_audit(wf, intent),
            "drill_ref": lambda: _drill_ref(wf, ref_path),
            "drill_timeline": lambda: _drill_timeline(wf, session_id, task_id, limit),
            "drill_task": lambda: _drill_task(wf, task_id),
            "backend_consistency": lambda: _backend_consistency(wf),
            "discover": lambda: memory_discover(wf, limit=limit),
            "constraint": lambda: _constraint_action(text, name),
            "tool_usage_report": lambda: memory_tool_usage_report(wf, limit=limit),
            "generate_wiki": lambda: generate_wiki(wf, output_dir or None),
            "generate_skills": lambda: generate_skills(wf, output_dir or None),
            "group_status": lambda: group_status(group),
            "group_query": lambda: group_query(group, query=text, limit=limit),
            "group_impact": lambda: group_impact(group, target=intent or text, direction=direction, max_depth=max_depth),
            "group_chain": lambda: group_chain(group, symbol=name or text, direction=direction, depth=max_depth, limit=limit),
            # ECC — verification loop
            "verification_loop": lambda: _verification_loop_action(wf, intent, task_id),
            # ECC — pattern promotion
            "pattern_promotion_propose": lambda: _pattern_promote_action(wf, "propose", text),
            "pattern_promotion_list": lambda: _pattern_promote_action(wf, "list", ""),
            "pattern_promotion_promote": lambda: _pattern_promote_action(wf, "promote", text),
            # ECC — heuristics
            "heuristics_query": lambda: _heuristics_action(wf, "query", text),
            "heuristics_record": lambda: _heuristics_action(wf, "record", text),
            "heuristics_feedback": lambda: _heuristics_action(wf, "feedback", text),
            "heuristics_explain": lambda: _heuristics_action(wf, "explain", text),
            # ECC — workflow profiles
            "workflow_profile": lambda: get_workflow_profile(intent or "quick-fix"),
            "workflow_recommend": lambda: recommend_workflow_with_learning(wf, text or intent or ""),
            # ECC — bundle export
            "bundle_export": lambda: generate_agent_bundle(wf, agent=name or "codex"),
            # ECC — runtime audit
            "runtime_audit": lambda: audit_agent_runtime(wf),
            # UA — explanation schema
            "explanation": lambda: _explanation_action(text, persona=intent or "developer"),
            # UA — business flow
            "business_flow": lambda: _business_flow_action(wf, name, max_depth),
            "business_flow_impact": lambda: _business_flow_impact_action(wf, intent or text, max_depth),
            # Metrics
            "metrics_summary": lambda: _metrics_summary_action(),
            # Benchmark regression alerts
            "regression_alerts": lambda: _regression_alerts_action(wf, name),
        }
        handler = _DISPATCH.get(action)
        if handler is None:
            valid = ", ".join(sorted(_DISPATCH.keys()))
            raise ValueError(f"Unknown mc_admin action: {action}. Valid actions: {valid}")
        return {"action": action, "result": handler()}


    # ===================== Next-phase helper actions =====================
    @staticmethod
    def _verification_loop_action(wf: str, intent: str, task_id: str) -> dict:
        vl = VerificationLoop(wf)
        if not task_id:
            task_id = "default"
        analysis = {"task_type": intent or "general", "workspace": wf}
        checklist = vl.generate_checklist(analysis)
        status = vl.get_status(task_id)
        return {"checklist": checklist, "status": status, "workflow": "mc-verification-loop"}

    @staticmethod
    def _pattern_promote_action(wf: str, action_type: str, text: str) -> dict:
        pp = PatternPromotion(wf)
        if action_type == "propose":
            proposal = {"rule_text": text, "source": "manual"}
            return pp.propose(proposal)
        elif action_type == "list":
            return {"proposals": pp.list_proposals()}
        elif action_type == "promote":
            return pp.promote(text)
        return {"error": "unknown action"}

    @staticmethod
    def _heuristics_action(wf: str, action_type: str, text: str) -> dict:
        hr = HeuristicsRegister(wf)
        import json
        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {"pattern": text}
        if action_type == "query":
            return {"heuristics": hr.query(text)}
        elif action_type == "record":
            entry = hr.record(data)
            return {"status": "recorded", "entry": entry}
        elif action_type == "feedback":
            feedback = hr.record_candidate_path_feedback(
                candidate_type=str(data.get("candidate_type", "") or ""),
                target=str(data.get("target", "") or ""),
                outcome=str(data.get("outcome", "") or ""),
                evidence=data.get("evidence") or [],
                source=str(data.get("source", "") or "mc_admin"),
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
        elif action_type == "explain":
            return hr.explain(
                candidate_type=str(data.get("candidate_type", "") or ""),
                target=str(data.get("target", "") or ""),
                category=str(data.get("category", "") or "candidate-path"),
                heuristic_id=str(data.get("heuristic_id", "") or ""),
                pattern=str(data.get("pattern", "") or ""),
                limit=int(data.get("limit", 10) or 10),
            )
        return {"error": "unknown action"}

    @staticmethod
    def _explanation_action(text: str, persona: str = "developer") -> dict:
        exp = Explanation(
            subject="explanation",
            summary=text or "",
            persona=persona,
        )
        return {"explanation": exp.adapt_for_persona(persona).to_full()}

    @staticmethod
    def _business_flow_action(wf: str, name: str, max_depth: int) -> dict:
        if not name:
            return {"error": "name (seed node) required"}
        result = extract_business_flows_for_workspace(wf, name, max_depth=max_depth or 4)
        result["workflow"] = "mc-business-flow"
        return result

    @staticmethod
    def _business_flow_impact_action(wf: str, node_id: str, max_depth: int) -> dict:
        result = business_flow_impact_for_workspace(wf, node_id or "", max_depth=max_depth or 3)
        result["workflow"] = "mc-business-flow-impact"
        return result

    @staticmethod
    def _metrics_summary_action() -> dict:
        mc = MetricsCollector()
        return {"summary": mc.summary(), "workflow": "mc-metrics"}

    @staticmethod
    def _regression_alerts_action(wf: str, name: str) -> dict:
        alerts = check_regression_alerts(wf)
        return {"alerts": alerts, "workflow": "mc-regression-alerts"}

    # ===================== Resources (unchanged) =====================
    @mcp.resource("memory-center://status")
    def status_resource():
        return workspace_status(ctx.workspace_file)

    @mcp.resource("memory-center://contracts")
    def contracts_resource():
        return memory_contracts(ctx.workspace_file)

    @mcp.resource("memory-center://topology")
    def topology_resource():
        return workspace_status(ctx.workspace_file).get("topology", {})

    # ===================== Prompts (updated tool names) =====================
    @mcp.prompt()
    def detect_impact(target: str) -> str:
        return (
            "Use Memory Center before editing. Call mc_analyze for the target "
            "to get impact analysis, change plan, and rules check. "
            f"Target: {target}"
        )

    @mcp.prompt()
    def spring_cloud_safe_change(task: str) -> str:
        return (
            "For this Spring Cloud task, call mc_start first. "
            "Then use mc_lookup or mc_analyze for important contracts. "
            "Use mc_sync to save progress, and mc_close when done. "
            f"Task: {task}"
        )

    @mcp.prompt()
    def onboard_new_dev(scope: str = "workspace") -> str:
        return (
            "You are onboarding a new developer to this project. "
            "Call mc_onboard with persona='developer' to get a guided "
            "architecture tour. Then call mc_domain to understand business "
            "domains and flows. Finally call mc_freshness to check if "
            "the index is up to date."
        )

    @mcp.prompt()
    def check_mq_safety(topic: str = "") -> str:
        base = (
            "Check MQ consumer safety for this project. "
            "Call mc_lookup to find MQ consumers and topics. "
            "Verify each consumer has idempotent handling. "
            "Check message format compatibility. "
        )
        return base + (f"Focus topic: {topic}" if topic else "Check all MQ consumers in the workspace.")

    @mcp.prompt()
    def analyze_dto_impact(dto_class: str = "") -> str:
        base = (
            "Analyze the impact of changing a DTO class. "
            "Call mc_analyze to get the full impact analysis. "
            "Check serialization compatibility, MQ message bodies, "
            "and Feign client contracts. "
        )
        return base + (f"Target DTO: {dto_class}" if dto_class else "Analyze all DTOs in the workspace.")

    @mcp.prompt()
    def cross_service_trace(service: str = "") -> str:
        base = (
            "Trace cross-service call chains. "
            "Call mc_lookup with mode='chain' to find Feign clients, "
            "MQ producers/consumers, and shared configs. "
            "Map the complete call graph across services. "
        )
        return base + (f"Starting from: {service}" if service else "Trace all cross-service interactions.")

    @mcp.prompt()
    def config_propagation_check(key: str = "") -> str:
        base = (
            "Check configuration key propagation across services. "
            "Call mc_lookup to find ConfigKey nodes. "
            "Identify which services read the same config keys. "
            "Flag potential configuration drift. "
        )
        return base + (f"Focus key: {key}" if key else "Check all shared configuration keys.")

    @mcp.prompt()
    def freshness_check() -> str:
        return (
            "Check index freshness before making code changes. "
            "Call mc_freshness to see if the graph index is up to date. "
            "If status is 'pending' or 'stale', read live files before editing. "
            "Never edit based on stale index data."
        )

    @mcp.prompt()
    def domain_overview() -> str:
        return (
            "Get a business domain overview of this project. "
            "Call mc_domain to extract business domains and flows. "
            "Understand how code maps to business concepts. "
            "Use this for product/business stakeholder discussions."
        )

    @mcp.prompt()
    def diff_impact_analysis(diff_summary: str = "") -> str:
        base = (
            "Analyze the impact of a git diff. "
            "Call mc_context_pack to get a compact context package. "
            "Then call mc_analyze for detailed impact analysis. "
            "Generate a change checklist with risk assessment. "
        )
        return base + (f"Diff summary: {diff_summary}" if diff_summary else "Analyze the current working tree changes.")

    # ===================== FACADE 9-12: V3 MCP Tools (§20.6) =====================

    @_safe_mcp_tool(mcp)
    def mc_context_pack(
        query: str,
        intent: str = "auto",
        budget_tokens: int = 8000,
        limit: int = 10,
    ):
        """Return a compact, evidence-backed context package for coding agents. Assembles entrypoints, relationships, risk patterns, and checklist into a single response to reduce agent grep/read cycles. Use this before mc_lookup for architecture or change-impact questions."""
        from memory_center.core.context.pack import ContextPackBuilder
        wf = ctx.workspace_file
        builder = ContextPackBuilder(wf)
        pack = builder.build(query=query, intent=intent, budget_tokens=budget_tokens, limit=limit)
        return {
            "workflow": "mc-context-pack",
            "query": pack.query,
            "intent": pack.intent,
            "entrypoints": pack.entrypoints,
            "relationships": pack.relationships[:20],
            "snippets": pack.snippets,
            "risks": pack.risks,
            "checklist": pack.checklist,
            "freshness": pack.freshness,
            "token_estimate": pack.token_estimate,
            "progressive": pack.progressive,
        }

    @_safe_mcp_tool(mcp)
    def mc_onboard(
        scope: str = "workspace",
        persona: str = "developer",
        target: str = "",
    ):
        """Generate a guided architecture tour for onboarding. persona: developer | architect | product | tester. Returns step-by-step walkthrough of the project structure."""
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.unified import UnifiedStore
        wf = ctx.workspace_file
        store = WorkspaceStore(wf)
        db_path = store.graph_db_path
        unified = UnifiedStore(db_path)
        try:
            gen = ArchitectureTourGenerator(unified)
            tour = gen.generate_tour(persona=persona, scope=scope, target=target or None)
            return {"workflow": "mc-onboard", "tour": tour.to_dict()}
        finally:
            unified.close()

    @_safe_mcp_tool(mcp)
    def mc_domain(
        scope: str = "workspace",
        include_flows: bool = True,
    ):
        """Extract business domains and business flows from the code knowledge graph. Shows how code entities map to business concepts like user management, order processing, payment, etc."""
        from memory_center.core.domain.extractor import BusinessDomainExtractor
        from memory_center.core.storage.unified import UnifiedStore
        wf = ctx.workspace_file
        store = WorkspaceStore(wf)
        db_path = store.graph_db_path
        unified = UnifiedStore(db_path)
        try:
            extractor = BusinessDomainExtractor(unified)
            domains = extractor.extract_domains()
            result = {
                "workflow": "mc-domain",
                "domains": [d.to_dict() for d in domains],
                "domain_count": len(domains),
            }
            if include_flows:
                flows = extractor.extract_flows()
                result["flows"] = [f.to_dict() for f in flows]
                result["flow_count"] = len(flows)
            return result
        finally:
            unified.close()

    @_safe_mcp_tool(mcp)
    def mc_freshness(
        scope: str = "workspace",
    ):
        """Return index freshness status. If pending files affect the query target, instruct the agent to read the live file before editing."""
        from memory_center.core.freshness.status import IndexFreshnessService
        wf = ctx.workspace_file
        svc = IndexFreshnessService(wf)
        banner = svc.banner()
        return {"workflow": "mc-freshness", **banner}

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="Path to .memory-center/workspace.yaml")
    args = parser.parse_args()
    server = create_server(str(Path(args.workspace).expanduser().resolve()))
    server.run()


if __name__ == "__main__":
    main()
