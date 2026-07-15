"""Action handlers for the MCP ``mc_admin`` facade.

``server.mc_admin`` keeps its FastMCP signature and short docstring; the
actual mapping of action names to orchestrator/artifact calls lives here so
that:

- ``server.py`` stops carrying ~150 lines of admin lambdas.
- The action table can be unit-tested directly (no FastMCP, no transport).

Public surface:

- ``build_admin_registry(workspace_file, **kwargs)`` returns a
  ``CommandRegistry`` whose handlers close over the supplied workspace and
  parameters.  The handler shape mirrors the legacy in-line table so existing
  ``mc_admin(action=...)`` callers do not see any behavioural change.
"""

from __future__ import annotations

import json
from typing import Any

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
    task_space_health,
    task_space_repair_execute,
    task_space_repair_plan,
    task_spaces_health,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
    update_task_status,
)
from memory_center.core.audit.runtime import audit_agent_runtime
from memory_center.core.benchmark.trending import check_regression_alerts
from memory_center.core.dispatch import CommandRegistry
from memory_center.core.domain.flow import (
    business_flow_impact_for_workspace,
    extract_business_flows_for_workspace,
)
from memory_center.core.explanation.schema import Explanation
from memory_center.core.metrics import MetricsCollector
from memory_center.core.orchestrator import (
    group_chain,
    group_impact,
    group_query,
    group_status,
    memory_backend_query,
    memory_discover,
    memory_eval_agent_guidance,
    memory_eval_agent_guidance_adoption,
    memory_eval_agent_guidance_adoption_trend,
    memory_eval_agent_guidance_replay,
    memory_eval_agent_guidance_replay_campaign,
    memory_eval_agent_guidance_replay_trend,
    memory_eval_agent_guidance_trend,
    memory_eval_context_weight,
    memory_eval_handoff,
    memory_eval_index_freshness,
    memory_eval_java_call_resolution,
    memory_eval_java_call_resolution_review,
    memory_eval_java_call_resolution_unresolved,
    memory_eval_parser_benchmark,
    memory_eval_regression_suite,
    memory_eval_resume,
    memory_eval_token_benchmark,
    memory_eval_token_gain,
    memory_eval_tool_adoption,
    memory_eval_walkthrough_quality,
    memory_eval_workflow_orchestration,
    memory_eval_write_quality,
    memory_execute_write,
    memory_export_walkthrough_artifact,
    memory_method_walkthrough,
    memory_plan_write,
    memory_tool_usage_report,
    memory_walkthrough_health,
    memory_write_judge,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_end_session,
    workspace_handoff_history,
    workspace_log_session_event,
    workspace_model_profile,
    workspace_recent_sessions,
    workspace_replay_write_chain,
    workspace_session_summary,
    workspace_start_session,
    workspace_status,
    workspace_task_resume_check,
    workspace_write_receipts,
)
from memory_center.core.verification.bundle_export import generate_agent_bundle
from memory_center.core.verification.heuristics import HeuristicsRegister
from memory_center.core.verification.loop import VerificationLoop
from memory_center.core.verification.pattern_promotion import PatternPromotion
from memory_center.core.verification.workflow_profiles import (
    get_workflow_profile,
    recommend_workflow_with_learning,
)
from memory_center.core.wiki import generate_skills, generate_wiki

__all__ = [
    "build_admin_registry",
    "parse_payload",
    "benchmark_trend_report",
    "run_audit",
    "drill_ref",
    "drill_timeline",
    "drill_task",
    "backend_consistency",
    "constraint_action",
    "verification_loop_action",
    "pattern_promote_action",
    "heuristics_action",
    "explanation_action",
    "business_flow_action",
    "business_flow_impact_action",
    "metrics_summary_action",
    "regression_alerts_action",
]


# ---------------------------------------------------------------------------
# Helper actions (previously inline / static methods inside create_server)
# ---------------------------------------------------------------------------

def parse_payload(payload_str: str) -> dict[str, Any] | None:
    if not payload_str:
        return None
    try:
        data = json.loads(payload_str)
    except json.JSONDecodeError:
        return {"raw": payload_str}
    return data if isinstance(data, dict) else {"value": data}


def benchmark_trend_report(workspace_file: str, function_name: str = "") -> dict[str, Any]:
    from memory_center.core.benchmark.trending import generate_benchmark_report
    return generate_benchmark_report(workspace_file, function_name=function_name)


def run_audit(workspace_file: str, work_package: str = "") -> dict[str, Any]:
    from memory_center.core.audit.completion import run_completion_audit
    return run_completion_audit(workspace_file, work_package=work_package)


def drill_ref(workspace_file: str, ref_id: str = "") -> dict[str, Any]:
    from memory_center.core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.expand_ref(ref_id)


def drill_timeline(workspace_file: str, session_id: str = "", task_id: str = "", limit: int = 50) -> dict[str, Any]:
    from memory_center.core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.drill_timeline(session_id=session_id, task_id=task_id, limit=limit)


def drill_task(workspace_file: str, task_id: str = "") -> dict[str, Any]:
    from memory_center.core.navigation.drilldown import DrillDownNavigator
    with DrillDownNavigator(workspace_file) as nav:
        return nav.drill_task(task_id)


def backend_consistency(workspace_file: str) -> dict[str, Any]:
    from memory_center.core.backend.query import UnifiedBackendQuery
    from memory_center.core.store import WorkspaceStore
    store = WorkspaceStore(workspace_file)
    with UnifiedBackendQuery(store.memory_db_path) as backend:
        return backend.check_consistency(store.base_dir)


def constraint_action(context: str = "", template: str = "coding_agent") -> dict[str, Any]:
    from memory_center.core.templates import auto_select_action, get_constraint_template
    if context:
        return {"context": context, "template": template, "recommended_action": auto_select_action(context, template)}
    tmpl = get_constraint_template(template)
    return tmpl or {"error": f"Unknown template: {template}"}


def verification_loop_action(workspace_file: str, intent: str, task_id: str) -> dict[str, Any]:
    vl = VerificationLoop(workspace_file)
    if not task_id:
        task_id = "default"
    analysis = {"task_type": intent or "general", "workspace": workspace_file}
    checklist = vl.generate_checklist(analysis)
    status = vl.get_status(task_id)
    return {"checklist": checklist, "status": status, "workflow": "mc-verification-loop"}


def pattern_promote_action(workspace_file: str, action_type: str, text: str) -> dict[str, Any]:
    pp = PatternPromotion(workspace_file)
    if action_type == "propose":
        return pp.propose({"rule_text": text, "source": "manual"})
    if action_type == "list":
        return {"proposals": pp.list_proposals()}
    if action_type == "promote":
        return pp.promote(text)
    return {"error": "unknown action"}


def heuristics_action(workspace_file: str, action_type: str, text: str) -> dict[str, Any]:
    hr = HeuristicsRegister(workspace_file)
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        data = {"pattern": text}
    if action_type == "query":
        return {"heuristics": hr.query(text)}
    if action_type == "record":
        entry = hr.record(data)
        return {"status": "recorded", "entry": entry}
    if action_type == "feedback":
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
    if action_type == "explain":
        return hr.explain(
            candidate_type=str(data.get("candidate_type", "") or ""),
            target=str(data.get("target", "") or ""),
            category=str(data.get("category", "") or "candidate-path"),
            heuristic_id=str(data.get("heuristic_id", "") or ""),
            pattern=str(data.get("pattern", "") or ""),
            limit=int(data.get("limit", 10) or 10),
        )
    return {"error": "unknown action"}


def explanation_action(text: str, persona: str = "developer") -> dict[str, Any]:
    exp = Explanation(subject="explanation", summary=text or "", persona=persona)
    return {"explanation": exp.adapt_for_persona(persona).to_full()}


def business_flow_action(workspace_file: str, name: str, max_depth: int) -> dict[str, Any]:
    if not name:
        return {"error": "name (seed node) required"}
    result = extract_business_flows_for_workspace(workspace_file, name, max_depth=max_depth or 4)
    result["workflow"] = "mc-business-flow"
    return result


def business_flow_impact_action(workspace_file: str, node_id: str, max_depth: int) -> dict[str, Any]:
    result = business_flow_impact_for_workspace(workspace_file, node_id or "", max_depth=max_depth or 3)
    result["workflow"] = "mc-business-flow-impact"
    return result


def metrics_summary_action(workspace_file: str = "", metric_name: str = "") -> dict[str, Any]:
    """Return aggregated metrics for the workspace.

    ``workspace_file`` is required by ``MetricsCollector``; an empty string is
    treated as "the registry was constructed without a workspace context", in
    which case we still return a structurally-valid payload so callers that
    only need ``workflow`` (smoke tests, CommandRegistry introspection) do not
    crash.

    ``metric_name`` is optional; when omitted we return an empty structurally
    valid payload instead of raising, which preserves backward compatibility
    with callers that only need to confirm the registry is wired up.
    """
    if not workspace_file:
        return {"summary": {}, "workflow": "mc-metrics", "note": "no_workspace_in_context"}
    if not metric_name:
        return {"summary": {}, "workflow": "mc-metrics", "note": "metric_name_required"}
    return {"summary": MetricsCollector(workspace_file).summary(metric_name), "workflow": "mc-metrics"}


def regression_alerts_action(workspace_file: str, _name_unused: str = "") -> dict[str, Any]:
    alerts = check_regression_alerts(workspace_file)
    return {"alerts": alerts, "workflow": "mc-regression-alerts"}


def eval_golden_action(workspace_file: str, cases_file: str) -> dict[str, Any]:
    from memory_center.core import benchmark as benchmark_module

    return benchmark_module.run_golden_suite(workspace_file, cases_file)


def eval_java_call_resolution_action(workspace_file: str, cases_file: str, *, strict: bool = False) -> dict[str, Any]:
    return memory_eval_java_call_resolution(
        workspace_file,
        cases_file,
        fail_on_forbidden_high_confidence=strict,
    )


def eval_java_call_resolution_review_action(workspace_file: str, cases_file: str, *, limit: int = 200) -> dict[str, Any]:
    return memory_eval_java_call_resolution_review(workspace_file, cases_file, limit=limit)


def eval_java_call_resolution_unresolved_action(workspace_file: str, *, limit: int = 30) -> dict[str, Any]:
    return memory_eval_java_call_resolution_unresolved(workspace_file, limit=limit)


def build_admin_registry(
    *,
    workspace_file: str,
    action: str = "",
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
) -> CommandRegistry:
    """Return a CommandRegistry mapping action name -> zero-arg handler.

    The signature mirrors ``server.mc_admin``; ``server.mc_admin`` simply
    forwards its kwargs here, dispatches one action, and returns the wrapper
    payload.  This keeps the FastMCP tool schema in ``server.py`` while moving
    the actual action table here so it can be tested without FastMCP.
    """
    wf = workspace_file
    registry = CommandRegistry(label="mc_admin action")

    registry.register_many({
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
        "task_health": lambda: task_space_health(wf, task_id),
        "task_health_all": lambda: task_spaces_health(wf, include_archived=include_archived, limit=limit),
        "task_repair_plan": lambda: task_space_repair_plan(wf, task_id),
        "task_repair_apply": lambda: task_space_repair_execute(wf, task_id, apply=force, intent=intent or text),
        "task_resume_check": lambda: workspace_task_resume_check(wf, intent=intent, task_id=task_id, session_id=session_id, limit=limit, budget=budget),
        "task_resolve": lambda: resolve_task_space(wf, intent=intent, title=title, create_if_missing=create_if_missing, include_archived=include_archived, limit_candidates=limit_candidates, score_threshold=score_threshold),
        "task_get": lambda: get_task_artifact(wf, task_id, name),
        "task_update": lambda: update_task_artifact(wf, task_id, name, content),
        "task_change_log_append": lambda: append_task_change_log(wf, task_id, entry, keep_recent=keep_recent),
        "task_archive": lambda: archive_task_space(wf, task_id, reason=reason),
        "task_auto_archive": lambda: auto_archive_task_spaces(wf, retention_days=keep_recent),
        "task_status": lambda: update_task_status(wf, task_id, status),
        "task_activity_touch": lambda: touch_task_activity(wf, task_id, source),
        "session_start": lambda: workspace_start_session(wf, intent, session_id=session_id or None),
        "session_log": lambda: workspace_log_session_event(wf, session_id, event_type, parse_payload(payload)),
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
        "eval_agent_guidance": lambda: memory_eval_agent_guidance(wf, intent=intent, limit=limit),
        "eval_agent_guidance_adoption": lambda: memory_eval_agent_guidance_adoption(wf, session_id=session_id, limit=limit),
        "eval_agent_guidance_adoption_trend": lambda: memory_eval_agent_guidance_adoption_trend(wf, session_id=session_id, limit=limit),
        "eval_agent_guidance_replay": lambda: memory_eval_agent_guidance_replay(wf, session_id=session_id, limit=limit),
        "eval_agent_guidance_replay_campaign": lambda: memory_eval_agent_guidance_replay_campaign(wf, min_events=20, limit=max(limit, 500)),
        "eval_agent_guidance_replay_trend": lambda: memory_eval_agent_guidance_replay_trend(wf, session_id=session_id, limit=limit),
        "eval_agent_guidance_trend": lambda: memory_eval_agent_guidance_trend(wf, intent=intent, limit=limit),
        "eval_workflow_orchestration": lambda: memory_eval_workflow_orchestration(wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
        "eval_token_gain": lambda: memory_eval_token_gain(wf, tool_name=tool_name, budget=budget, model=model, limit=limit),
        "eval_parser_benchmark": lambda: memory_eval_parser_benchmark(wf, limit=limit),
        "eval_java_call_resolution": lambda: eval_java_call_resolution_action(wf, name, strict=strict),
        "eval_java_call_resolution_review": lambda: eval_java_call_resolution_review_action(wf, name, limit=limit),
        "eval_java_call_resolution_unresolved": lambda: eval_java_call_resolution_unresolved_action(wf, limit=limit),
        "eval_golden": lambda: eval_golden_action(wf, name),
        "eval_token_benchmark": lambda: memory_eval_token_benchmark(wf, intent=intent, limit=limit),
        "eval_token_benchmark_trend": lambda: benchmark_trend_report(wf, name),
        "audit": lambda: run_audit(wf, intent),
        "drill_ref": lambda: drill_ref(wf, ref_path),
        "drill_timeline": lambda: drill_timeline(wf, session_id, task_id, limit),
        "drill_task": lambda: drill_task(wf, task_id),
        "backend_consistency": lambda: backend_consistency(wf),
        "discover": lambda: memory_discover(wf, limit=limit),
        "constraint": lambda: constraint_action(text, name),
        "tool_usage_report": lambda: memory_tool_usage_report(wf, limit=limit),
        "generate_wiki": lambda: generate_wiki(wf, output_dir or None),
        "generate_skills": lambda: generate_skills(wf, output_dir or None),
        "group_status": lambda: group_status(group),
        "group_query": lambda: group_query(group, query=text, limit=limit),
        "group_impact": lambda: group_impact(group, target=intent or text, direction=direction, max_depth=max_depth),
        "group_chain": lambda: group_chain(group, symbol=name or text, direction=direction, depth=max_depth, limit=limit),
        "method_walkthrough": lambda: memory_method_walkthrough(wf, name or text or intent, depth=max_depth, limit=limit, project=project, view=view, budget=budget, report_level=model or "standard"),
        "walkthrough_health": lambda: memory_walkthrough_health(wf, symbol=name or text or intent, project=project, report_level=model or "standard"),
        "walkthrough_export": lambda: memory_export_walkthrough_artifact(wf, symbol=name or text or intent, project=project, report_level=model or "deep", title=title),
        "eval_walkthrough_quality": lambda: memory_eval_walkthrough_quality(wf, symbol=name or text or intent, project=project, report_level=model or "standard"),
        "verification_loop": lambda: verification_loop_action(wf, intent, task_id),
        "pattern_promotion_propose": lambda: pattern_promote_action(wf, "propose", text),
        "pattern_promotion_list": lambda: pattern_promote_action(wf, "list", ""),
        "pattern_promotion_promote": lambda: pattern_promote_action(wf, "promote", text),
        "heuristics_query": lambda: heuristics_action(wf, "query", text),
        "heuristics_record": lambda: heuristics_action(wf, "record", text),
        "heuristics_feedback": lambda: heuristics_action(wf, "feedback", text),
        "heuristics_explain": lambda: heuristics_action(wf, "explain", text),
        "workflow_profile": lambda: get_workflow_profile(intent or "quick-fix"),
        "workflow_recommend": lambda: recommend_workflow_with_learning(wf, text or intent or ""),
        "bundle_export": lambda: generate_agent_bundle(wf, agent=name or "codex"),
        "runtime_audit": lambda: audit_agent_runtime(wf, fix=bool(force)),
        "explanation": lambda: explanation_action(text, persona=intent or "developer"),
        "business_flow": lambda: business_flow_action(wf, name, max_depth),
        "business_flow_impact": lambda: business_flow_impact_action(wf, intent or text, max_depth),
        "metrics_summary": lambda: metrics_summary_action(wf, name),
        "regression_alerts": lambda: regression_alerts_action(wf, name),
    })
    return registry
