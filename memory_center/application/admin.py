"""Action handlers for the MCP ``mc_admin`` facade.

``server.mc_admin`` keeps its FastMCP signature and short docstring; the
actual mapping of action names to orchestrator/artifact calls lives here so
that:

- ``server.py`` stops carrying ~150 lines of admin lambdas.
- The action table can be unit-tested directly (no FastMCP, no transport).

Public surface:

- ``build_admin_registry(workspace_file, **kwargs)`` returns a
  ``CommandRegistry`` whose handlers close over the supplied workspace and
parameters. The action table is centralized so CLI, HTTP and MCP share one
deterministic dispatch implementation.
"""

from __future__ import annotations

import json
from typing import Any

from memory_center.application.external_capabilities import audit_external_capabilities, snapshot_external_capabilities
from memory_center.application.performance import record_workspace_performance_snapshot
from memory_center.application.runtime_governance import workspace_runtime_governance
from memory_center.application.tasks import execute_task_repair
from memory_center.core.audit.inspect import inspect_runtime
from memory_center.core.audit.interactions import build_effect_summary, record_host_interaction, refresh_effect_summary
from memory_center.core.audit.runtime import audit_agent_runtime
from memory_center.core.benchmark.cochange import evaluate_git_cochange
from memory_center.core.benchmark.trending import check_regression_alerts
from memory_center.core.contracting.runtime import (
    ingest_runtime_contract_samples,
    runtime_contract_compatibility,
    set_contract_migration,
)
from memory_center.core.domain.flow import (
    business_flow_impact_for_workspace,
    extract_business_flows_for_workspace,
)
from memory_center.core.explanation.schema import Explanation
from memory_center.core.foundation.dispatch import CommandRegistry
from memory_center.core.freshness.change_reports import (
    pending_change_impact_reports,
    recent_change_impact_reports,
    record_change_impact_feedback,
)
from memory_center.core.freshness.daemon import start_watcher_daemon, stop_watcher_daemon, watcher_daemon_status
from memory_center.core.indexing.control_plane import index_control_status, rollback_generation
from memory_center.core.indexing.shards import cleanup_generations
from memory_center.core.knowledge.assets import (
    approve_collaboration_asset,
    bind_collaboration_asset,
    collaboration_asset_loadout,
    collaboration_asset_status,
    ingest_wiki_document_asset,
    register_collaboration_asset,
    submit_asset_for_sharing,
    sync_workspace_collaboration_assets,
)
from memory_center.core.knowledge.communities import analyze_architecture_communities
from memory_center.core.knowledge.skill_generation import generate_skills
from memory_center.core.observability.metrics import MetricsCollector
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
    memory_eval_java_call_resolution_metrics,
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
    memory_query_hybrid,
    memory_tool_usage_report,
    memory_walkthrough_health,
    memory_write_judge,
    workspace_check_contract,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_end_session,
    workspace_handoff_history,
    workspace_log_session_event,
    workspace_model_profile,
    workspace_recent_sessions,
    workspace_record_agent_guidance,
    workspace_replay_write_chain,
    workspace_session_summary,
    workspace_start_session,
    workspace_status,
    workspace_task_resume_check,
    workspace_write_receipts,
)
from memory_center.core.retrieval.templates import plan_change_risk
from memory_center.core.presentation.evidence_subgraph import export_evidence_subgraph
from memory_center.core.retrieval.calibration import evaluate_retrieval_replay_calibration
from memory_center.core.retrieval.cross_service import evaluate_cross_shard_replay
from memory_center.core.retrieval.cross_service_fusion import evaluate_cross_shard_fusion
from memory_center.core.tasks.shadow import (
    bind_shadow_to_task,
    build_merged_shadow,
    discard_shadow,
    promote_shadow_to_task,
    shadow_retention_cleanup,
    suggest_shadow_binding,
)
from memory_center.core.tasks.shadow_observations import (
    list_observations,
    record_observation,
    set_shadow_authority,
)
from memory_center.core.tasks.shadow_handoff import (
    claim_handoff,
    close_handoff,
    create_handoff,
    get_handoff,
    list_handoffs,
    mark_handed_off,
)
from memory_center.core.tasks.session_notes import (
    NOTE_KINDS,
    NOTE_STATUSES,
    forget_note,
    list_notes,
    record_note,
    search_notes,
    supersede_note,
)
from memory_center.core.retrieval.model_profiles import retrieval_model_profile
from memory_center.core.retrieval.planner import (
    scoped_refresh_performance_status,
    workspace_performance_snapshot_status,
    workspace_performance_summary,
)
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.vector_index import VectorIndex
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.tasks.artifacts import (
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
    list_task_decisions,
    list_task_spaces,
    record_task_decision,
    resolve_task_space,
    task_evidence_gc,
    task_space_health,
    task_space_repair_plan,
    task_spaces_health,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
    update_task_status,
    write_task_evidence_chunk,
)
from memory_center.core.tasks.delivery import (
    delivery_matrix,
    delivery_policy_status,
    delivery_skill_candidate,
    delivery_skill_replay_set,
    delivery_skill_status,
    delivery_workflow_status,
    derive_delivery_failure_candidates,
    evaluate_delivery_skill,
    execute_delivery_validation,
    initialize_delivery_workflow,
    propose_delivery_breakdown,
    publish_delivery_skill,
    recommend_delivery_skills,
    record_delivery_skill_observation,
    record_delivery_validation,
    rollback_delivery_skill,
    start_delivery_skill_canary,
    synthesize_delivery_skill_trajectories,
    transition_delivery_stage,
    update_delivery_contract,
    update_delivery_policy,
    update_delivery_skill_contract,
    update_delivery_subtask_status,
)
from memory_center.core.verification.bundle_export import generate_agent_bundle
from memory_center.core.verification.heuristics import HeuristicsRegister
from memory_center.core.verification.loop import VerificationLoop
from memory_center.core.verification.pattern_promotion import PatternPromotion
from memory_center.core.verification.workflow_profiles import (
    get_workflow_profile,
    recommend_workflow_with_learning,
)
from memory_center.core.workspace.jobs import cancel_workspace_job, submit_reindex_workspace_job, workspace_job_status


def _vector_ann_action(workspace_file: str, operation: str, limit: int) -> dict[str, Any]:
    """MCP/HTTP/CLI 共用的受限 ANN 维护入口。"""
    store = WorkspaceStore(workspace_file)
    with RuntimeStore(store.graph_db_path) as runtime:
        index = VectorIndex(runtime)
        if operation == "rebuild":
            return index.rebuild_ann()
        if operation == "tune":
            return index.tune_ann(sample_size=max(8, min(limit, 128)))
        return index.stats()


def _advanced_query_action(
    workspace_file: str,
    text: str,
    *,
    limit: int,
    project: str,
    session_id: str,
) -> dict[str, Any]:
    """高级查询与普通查询共享 session guidance 闭环。"""
    result = memory_query_hybrid(
        workspace_file,
        text,
        limit=limit,
        project=project,
        enable_vector=True,
        enable_reranker=True,
    )
    if session_id.strip():
        workspace_record_agent_guidance(
            workspace_file,
            session_id,
            query=text,
            mode="advanced_query",
            source="mcp_admin.advanced_query",
            payload=result,
        )
    return result


def _reranker_action(operation: str, model_name: str = "") -> dict[str, Any]:
    from memory_center.core.retrieval.hybrid import prewarm_reranker, reranker_status

    return prewarm_reranker(model_name or None) if operation == "prewarm" else reranker_status(model_name or None)


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


def _update_assertion_status_action(
    workspace_file: str, assertion_id: str, status: str, payload: str, actor: str
) -> dict[str, Any]:
    from memory_center.core.knowledge.assertions import update_assertion_status

    data = parse_payload(payload) or {}
    return update_assertion_status(
        WorkspaceStore(workspace_file),
        assertion_id,
        status=status,
        verification_ref=str(data.get("verification_ref", "") or ""),
        actor=actor,
    )


def _inspect_assertion_action(workspace_file: str, assertion_id: str) -> dict[str, Any]:
    from memory_center.core.knowledge.assertions import inspect_assertion

    return inspect_assertion(WorkspaceStore(workspace_file), assertion_id)


def runtime_contract_gate_action(workspace_file: str, *, contract_file: str = "", task_id: str = "") -> dict[str, Any]:
    result = runtime_contract_compatibility(workspace_file, contract_file)
    if task_id.strip():
        result["evidence"] = write_task_evidence_chunk(
            workspace_file,
            task_id,
            json.dumps(result, ensure_ascii=False, indent=2),
            source="runtime_contract_gate",
        )
    return result


def benchmark_trend_report(workspace_file: str, function_name: str = "") -> dict[str, Any]:
    from memory_center.core.benchmark.trending import generate_benchmark_report

    return generate_benchmark_report(workspace_file, function_name=function_name)


def run_audit(workspace_file: str, work_package: str = "") -> dict[str, Any]:
    from memory_center.core.audit.reports import run_completion_audit

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


def backend_consistency(workspace_file: str, *, repair_exports: bool = False, apply: bool = False) -> dict[str, Any]:
    from memory_center.core.backend.query import UnifiedBackendQuery
    from memory_center.core.storage.workspace import WorkspaceStore

    store = WorkspaceStore(workspace_file)
    with UnifiedBackendQuery(store.runtime_db_path) as backend:
        result = backend.check_consistency(store.base_dir)
    health = store.jsonl_export_health()
    repaired: list[dict[str, Any]] = []
    if repair_exports and apply:
        for entry in health["collections"]:
            if entry["needs_sync"]:
                repaired.append(store.sync_jsonl_export(str(entry["collection"])))
        health = store.jsonl_export_health()
    result["jsonl_projection"] = {
        **health,
        "repair_requested": repair_exports,
        "applied": bool(repair_exports and apply),
        "repaired": repaired,
    }
    return result


def constraint_action(context: str = "", template: str = "coding_agent") -> dict[str, Any]:
    from memory_center.core.governance.templates import auto_select_action, get_constraint_template

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
    return exp.adapt_for_persona(persona).to_full()


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
    return check_regression_alerts(workspace_file)


def eval_golden_action(workspace_file: str, cases_file: str) -> dict[str, Any]:
    from memory_center.application.golden import run_golden_suite

    return run_golden_suite(workspace_file, cases_file)


def eval_java_call_resolution_action(workspace_file: str, cases_file: str, *, strict: bool = False) -> dict[str, Any]:
    return memory_eval_java_call_resolution(
        workspace_file,
        cases_file,
        fail_on_forbidden_high_confidence=strict,
    )


def eval_java_call_resolution_metrics_action(workspace_file: str) -> dict[str, Any]:
    return memory_eval_java_call_resolution_metrics(workspace_file)


def eval_java_call_resolution_review_action(
    workspace_file: str, cases_file: str, *, limit: int = 200
) -> dict[str, Any]:
    return memory_eval_java_call_resolution_review(workspace_file, cases_file, limit=limit)


def eval_java_call_resolution_unresolved_action(workspace_file: str, *, limit: int = 30) -> dict[str, Any]:
    return memory_eval_java_call_resolution_unresolved(workspace_file, limit=limit)


def _record_observation_structured(workspace_file: str, observation: dict[str, Any], *, fold_into_shadow: bool = True) -> dict[str, Any]:
    """Observation 入口的结构化失败包装：schema 拒收时返回 {recorded: False, reason}，
    不让 ObservationRejected 直接穿透为异常。"""
    from memory_center.core.tasks.shadow_observations import ObservationRejected, record_observation

    try:
        return record_observation(workspace_file, observation, fold_into_shadow=fold_into_shadow)
    except ObservationRejected as exc:
        return {"recorded": False, "reason": exc.code, "detail": str(exc)[:200]}


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

    registry.register_many(
        {
            "status": lambda: workspace_status(wf, view=view, budget=budget),
            "dashboard": lambda: workspace_dashboard(wf, intent=intent, limit=limit, view=view, budget=budget),
            "continuity": lambda: workspace_continuity_dashboard(
                wf, intent=intent, task_id=task_id, session_id=session_id, limit=limit, view=view, budget=budget
            ),
            "health": lambda: {
                "workflow": "mc-admin-health",
                "status": workspace_status(wf, view="compact", budget="medium"),
                "tool_usage_report": memory_tool_usage_report(wf, limit=50),
                "regression_suite": memory_eval_regression_suite(
                    wf, intent=intent, target_model=target_model, limit=limit
                ),
            },
            "artifact_list": lambda: list_artifacts(wf),
            "artifact_get": lambda: get_artifact(wf, name),
            "artifact_outline": lambda: artifact_outline(wf, name),
            "artifact_context": lambda: artifact_context(wf, intent, limit=limit),
            "asset_status": lambda: collaboration_asset_status(
                wf, limit=limit, max_chars=int((parse_payload(payload) or {}).get("max_chars", 0) or 0)
            ),
            "asset_register": lambda: register_collaboration_asset(
                wf,
                **{
                    **(parse_payload(payload) or {}),
                    "actor": source or str((parse_payload(payload) or {}).get("owner", "")) or "local-agent",
                },
            ),
            "asset_sync": lambda: sync_workspace_collaboration_assets(wf, owner=owner or source),
            "asset_share": lambda: submit_asset_for_sharing(
                wf,
                str((parse_payload(payload) or {}).get("asset_id", "")),
                visibility=str((parse_payload(payload) or {}).get("visibility", "team")),
                actor=source,
                allowed_agents=list((parse_payload(payload) or {}).get("allowed_agents", [])),
                allowed_roles=list((parse_payload(payload) or {}).get("allowed_roles", [])),
            ),
            "asset_approve": lambda: approve_collaboration_asset(
                wf,
                str((parse_payload(payload) or {}).get("asset_id", "")),
                approved=bool((parse_payload(payload) or {}).get("approved", False)),
                actor=source,
                note=str((parse_payload(payload) or {}).get("note", "")),
            ),
            "asset_bind": lambda: bind_collaboration_asset(
                wf,
                str((parse_payload(payload) or {}).get("asset_id", "")),
                actor=source,
                agents=list((parse_payload(payload) or {}).get("agents", [])),
                roles=list((parse_payload(payload) or {}).get("roles", [])),
            ),
            "asset_loadout": lambda: collaboration_asset_loadout(
                wf,
                agent_id=str((parse_payload(payload) or {}).get("agent_id", "")),
                role=str((parse_payload(payload) or {}).get("role", "")),
                limit=limit,
                max_chars=int((parse_payload(payload) or {}).get("max_chars", 0) or 0),
            ),
            "wiki_document_ingest": lambda: ingest_wiki_document_asset(
                wf,
                str((parse_payload(payload) or {}).get("document_path", "")),
                owner=owner or source,
                visibility=str((parse_payload(payload) or {}).get("visibility", "private")),
                tags=list((parse_payload(payload) or {}).get("tags", [])),
            ),
            "artifact_update": lambda: update_artifact(wf, name, content),
            "change_log_append": lambda: append_change_log(wf, entry),
            "change_log_compact": lambda: compact_change_log(wf, keep_recent),
            "task_create": lambda: create_task_space(
                wf, title=title, intent=intent, owner=owner, tags=tags, priority=priority
            ),
            "task_list": lambda: list_task_spaces(wf, include_archived=include_archived),
            "task_health": lambda: task_space_health(wf, task_id),
            "task_health_all": lambda: task_spaces_health(wf, include_archived=include_archived, limit=limit),
            "task_repair_plan": lambda: task_space_repair_plan(wf, task_id),
            "task_repair_apply": lambda: execute_task_repair(wf, task_id, apply=force, intent=intent or text),
            "task_resume_check": lambda: workspace_task_resume_check(
                wf, intent=intent, task_id=task_id, session_id=session_id, limit=limit, budget=budget
            ),
            "task_resolve": lambda: resolve_task_space(
                wf,
                intent=intent,
                title=title,
                create_if_missing=create_if_missing,
                include_archived=include_archived,
                limit_candidates=limit_candidates,
                score_threshold=score_threshold,
            ),
            "task_get": lambda: get_task_artifact(wf, task_id, name),
            "task_update": lambda: update_task_artifact(wf, task_id, name, content),
            "task_decision_record": lambda: record_task_decision(
                wf,
                task_id,
                title or name,
                content,
                reason or intent,
                evidence_refs=[item.strip() for item in payload.split(",") if item.strip()],
            ),
            "task_decision_list": lambda: list_task_decisions(wf, task_id, limit=limit),
            "task_evidence_gc": lambda: task_evidence_gc(wf, task_id, apply=force),
            "task_change_log_append": lambda: append_task_change_log(wf, task_id, entry, keep_recent=keep_recent),
            "task_archive": lambda: archive_task_space(wf, task_id, reason=reason),
            "task_auto_archive": lambda: auto_archive_task_spaces(wf, retention_days=keep_recent),
            "task_status": lambda: update_task_status(wf, task_id, status),
            "task_activity_touch": lambda: touch_task_activity(wf, task_id, source),
            # --- Task Shadow (Session-first continuity, L1) -------------------
            "task_shadow_status": lambda: (
                build_merged_shadow(wf, name)
                or {"found": False, "shadow_id": name, "reason": "shadow_not_found"}
            ),
            "task_shadow_bind": lambda: bind_shadow_to_task(
                wf,
                name,
                task_id,
                expected_revision=int((parse_payload(payload) or {}).get("expected_revision"))
                if (parse_payload(payload) or {}).get("expected_revision") is not None
                else None,
                source=source or "mc_admin",
            ),
            "task_shadow_discard": lambda: discard_shadow(wf, name, reason=reason or "user_requested"),
            "task_shadow_promote": lambda: promote_shadow_to_task(wf, name, task_id=task_id, title=title),
            "task_shadow_suggest": lambda: suggest_shadow_binding(
                wf, name, candidate_tasks=list((parse_payload(payload) or {}).get("candidate_tasks", []))
            ),
            "task_shadow_retention": lambda: shadow_retention_cleanup(wf, apply=force),
            "task_shadow_observation_record": lambda: _record_observation_structured(wf, parse_payload(payload) or {}, fold_into_shadow=not force),
            "task_shadow_observation_list": lambda: list_observations(
                wf, source_kind=scope if scope in ("dsh", "codex", "claude", "other") else "", source_session_id=session_id, kind=event_type, limit=limit
            ),
            "task_shadow_authority": lambda: set_shadow_authority(
                wf, name, str((parse_payload(payload) or {}).get("authority", "snapshot"))
            ),
            "task_shadow_handoff_create": lambda: create_handoff(
                wf,
                from_session_id=session_id,
                shadow_id=name,
                to_agent_hint=str((parse_payload(payload) or {}).get("to_agent_hint", "")),
            ),
            "task_shadow_handoff_handed_off": lambda: mark_handed_off(
                wf, name, expected_revision=int((parse_payload(payload) or {}).get("expected_revision", 0))
            ),
            "task_shadow_handoff_claim": lambda: claim_handoff(
                wf,
                name,
                claimed_by_session_id=session_id,
                expected_revision=int((parse_payload(payload) or {}).get("expected_revision", 0)),
            ),
            "task_shadow_handoff_close": lambda: close_handoff(
                wf, name, expected_revision=int((parse_payload(payload) or {}).get("expected_revision", 0)), outcome=outcome
            ),
            "task_shadow_handoff_get": lambda: get_handoff(wf, name),
            "task_shadow_handoff_list": lambda: list_handoffs(wf, status=status, limit=limit),
            # --- Session Notes (L0.5 narrative layer) -------------------------
            "note_record": lambda: record_note(
                wf,
                text or title,
                kind=event_type if event_type in NOTE_KINDS else "fact",
                session_id=session_id,
                origin="user_explicit" if source == "user" else "agent_summary",
                source_refs=list((parse_payload(payload) or {}).get("source_refs", [])),
            ),
            "note_list": lambda: list_notes(
                wf,
                kind=event_type if event_type in NOTE_KINDS else "",
                status=status if status in NOTE_STATUSES else "active",
                session_id=session_id,
                limit=limit,
            ),
            "note_search": lambda: {"query": text, "hits": search_notes(wf, text, limit=limit)},
            "note_supersede": lambda: supersede_note(
                wf,
                name,
                text,
                kind=event_type if event_type in NOTE_KINDS else "",
            ),
            "note_forget": lambda: forget_note(wf, name, reason=reason or "user_requested"),
            "delivery_init": lambda: initialize_delivery_workflow(wf, task_id, actor=source),
            "delivery_status": lambda: delivery_workflow_status(wf, task_id),
            "delivery_breakdown": lambda: propose_delivery_breakdown(
                wf,
                task_id,
                source_refs=list((parse_payload(payload) or {}).get("source_refs", [])),
                summary=str((parse_payload(payload) or {}).get("summary", "")),
            ),
            "delivery_policy": lambda: (
                update_delivery_policy(wf, parse_payload(payload) or {}, actor=source)
                if payload
                else delivery_policy_status(wf)
            ),
            "delivery_contract_update": lambda: update_delivery_contract(
                wf,
                task_id,
                kind=str((parse_payload(payload) or {}).get("kind", "")),
                items=list((parse_payload(payload) or {}).get("items", [])),
                actor=source,
            ),
            "delivery_subtask_status": lambda: update_delivery_subtask_status(
                wf,
                task_id,
                str((parse_payload(payload) or {}).get("subtask_id", "")),
                str((parse_payload(payload) or {}).get("status", "")),
                actor=source,
            ),
            "delivery_validation_record": lambda: record_delivery_validation(
                wf,
                task_id,
                status=str((parse_payload(payload) or {}).get("status", "recorded")),
                summary=str((parse_payload(payload) or {}).get("summary", "")),
                command=str((parse_payload(payload) or {}).get("command", "")),
                exit_code=(parse_payload(payload) or {}).get("exit_code"),
                acceptance_ids=(parse_payload(payload) or {}).get("acceptance_ids", []),
                evidence_refs=(parse_payload(payload) or {}).get("evidence_refs", []),
                evidence_types=(parse_payload(payload) or {}).get("evidence_types", []),
                evidence_kind=str((parse_payload(payload) or {}).get("evidence_kind", "recorded_external")),
                actor=str((parse_payload(payload) or {}).get("actor", "")),
                actor_source=source or "mcp",
            ),
            "delivery_validation_execute": lambda: execute_delivery_validation(
                wf,
                task_id,
                profile_id=str((parse_payload(payload) or {}).get("profile_id", "")),
                acceptance_ids=(parse_payload(payload) or {}).get("acceptance_ids", []),
                actor=source,
            ),
            "delivery_matrix": lambda: delivery_matrix(wf, task_id, write=not force),
            "delivery_transition": lambda: transition_delivery_stage(
                wf,
                task_id,
                str((parse_payload(payload) or {}).get("stage", "")),
                actor=source,
                force=force,
            ),
            "delivery_skill_candidate": lambda: delivery_skill_candidate(wf, task_id),
            "delivery_skill_publish": lambda: publish_delivery_skill(wf, task_id),
            "delivery_skill_status": lambda: delivery_skill_status(wf, task_id),
            "delivery_skill_contract_update": lambda: update_delivery_skill_contract(
                wf, task_id, contract=parse_payload(payload) or {}, actor=source
            ),
            "delivery_skill_canary": lambda: start_delivery_skill_canary(wf, task_id, actor=source),
            "delivery_skill_observe": lambda: record_delivery_skill_observation(
                wf,
                str((parse_payload(payload) or {}).get("skill_id", "")),
                outcome=str((parse_payload(payload) or {}).get("outcome", "")),
                evidence_refs=list((parse_payload(payload) or {}).get("evidence_refs", [])),
                latency_ms=(parse_payload(payload) or {}).get("latency_ms"),
                token_count=(parse_payload(payload) or {}).get("token_count"),
                actor=source,
            ),
            "delivery_skill_evaluate": lambda: evaluate_delivery_skill(
                wf, skill_id=str((parse_payload(payload) or {}).get("skill_id", ""))
            ),
            "delivery_skill_rollback": lambda: rollback_delivery_skill(
                wf,
                str((parse_payload(payload) or {}).get("skill_id", "")),
                reason=str((parse_payload(payload) or {}).get("reason", "")),
                actor=source,
            ),
            "delivery_skill_recommend": lambda: recommend_delivery_skills(
                wf,
                str((parse_payload(payload) or {}).get("intent", intent)),
                language=str((parse_payload(payload) or {}).get("language", "")),
                limit=limit,
            ),
            "delivery_skill_replay": lambda: delivery_skill_replay_set(
                wf, skill_id=str((parse_payload(payload) or {}).get("skill_id", "")), limit=limit
            ),
            "delivery_failure_candidates": lambda: derive_delivery_failure_candidates(wf, limit_tasks=limit),
            "delivery_skill_synthesize": lambda: synthesize_delivery_skill_trajectories(
                wf, min_support=max(2, min(limit, 20))
            ),
            "session_start": lambda: workspace_start_session(wf, intent, session_id=session_id or None),
            "session_log": lambda: workspace_log_session_event(wf, session_id, event_type, parse_payload(payload)),
            "session_end": lambda: workspace_end_session(wf, session_id, outcome, verified_by),
            "session_recent": lambda: workspace_recent_sessions(wf, limit),
            "session_summary": lambda: workspace_session_summary(wf, session_id),
            "model_profile": lambda: workspace_model_profile(target_model),
            "handoff_history": lambda: workspace_handoff_history(
                wf, target_model=target_model, task_id=task_id, session_id=session_id, limit=limit
            ),
            "write_judge": lambda: memory_write_judge(
                wf, text=text, source=source, intent=intent, prefer_layer=prefer_layer, projects=projects, files=files
            ),
            "write_plan": lambda: memory_plan_write(
                wf,
                text=text,
                source=source,
                intent=intent,
                session_id=session_id,
                task_id=task_id,
                title=title,
                prefer_layer=prefer_layer,
                projects=projects,
                files=files,
            ),
            "write_execute": lambda: memory_execute_write(
                wf,
                text=text,
                source=source,
                intent=intent,
                session_id=session_id,
                task_id=task_id,
                title=title,
                prefer_layer=prefer_layer,
                projects=projects,
                files=files,
            ),
            "receipts": lambda: workspace_write_receipts(
                wf, layer=layer, action=action_filter, scope=scope, task_id=task_id, session_id=session_id, limit=limit
            ),
            "replay": lambda: workspace_replay_write_chain(wf, task_id=task_id, session_id=session_id, limit=limit),
            "backend_query": lambda: memory_backend_query(
                wf,
                collection=collection,
                record_id=record_id,
                created_after=created_after,
                ref_path=ref_path,
                project=project,
                payload_type=payload_type,
                limit=limit,
            ),
            "interaction_record": lambda: record_host_interaction(
                wf, parse_payload(payload) or {}, session_id=session_id, task_id=task_id
            ),
            "interaction_effects": lambda: build_effect_summary(wf, limit=max(limit, 100)),
            "interaction_effects_refresh": lambda: refresh_effect_summary(wf),
            "active_session_bindings": lambda: WorkspaceStore(wf).read_json_prefer_backend(
                "active-session-bindings.json", {}
            ),
            "index_control": lambda: index_control_status(WorkspaceStore(wf)),
            "contract_gate": lambda: workspace_check_contract(wf, name or ref_path or text, action_filter or "modify"),
            "runtime_contract_ingest": lambda: ingest_runtime_contract_samples(
                wf, list((parse_payload(payload) or {}).get("samples", [])), source=source or "mcp_admin"
            ),
            "runtime_contract_migration": lambda: set_contract_migration(wf, parse_payload(payload) or {}),
            "runtime_contract_gate": lambda: runtime_contract_gate_action(
                wf, contract_file=name or ref_path or text, task_id=task_id
            ),
            "index_rollback": lambda: rollback_generation(WorkspaceStore(wf), record_id),
            "index_generation_gc": lambda: cleanup_generations(
                WorkspaceStore(wf),
                active_generation=str(index_control_status(WorkspaceStore(wf)).get("active_generation", "") or ""),
                previous_generation=str(index_control_status(WorkspaceStore(wf)).get("previous_generation", "") or ""),
                keep=max(2, keep_recent),
                apply=force,
            ),
            "query_performance": lambda: workspace_performance_summary(wf, limit=max(limit, 20)),
            "performance_snapshot": lambda: record_workspace_performance_snapshot(
                wf, samples=max(1, min(limit, 20)), tier=budget if budget in {"fast", "standard", "deep"} else "fast"
            ),
            "performance_snapshot_status": lambda: workspace_performance_snapshot_status(wf, limit=max(limit, 20)),
            "scoped_refresh_performance": lambda: scoped_refresh_performance_status(wf, limit=max(limit, 20)),
            "runtime_governance": lambda: workspace_runtime_governance(wf),
            "external_capability_audit": lambda: audit_external_capabilities(wf),
            "external_capability_snapshot": lambda: snapshot_external_capabilities(wf),
            "http_route_contract_audit": lambda: __import__(
                "memory_center.http.route_dispatch", fromlist=["audit_http_route_contract"]
            ).audit_http_route_contract(),
            "advanced_query": lambda: _advanced_query_action(
                wf, text, limit=limit, project=project, session_id=session_id
            ),
            "vector_ann_status": lambda: _vector_ann_action(wf, "status", limit),
            "vector_ann_rebuild": lambda: _vector_ann_action(wf, "rebuild", limit),
            "vector_ann_tune": lambda: _vector_ann_action(wf, "tune", limit),
            "retrieval_reranker_status": lambda: _reranker_action("status", model),
            "retrieval_reranker_prewarm": lambda: _reranker_action("prewarm", model),
            "retrieval_model_profile": lambda: retrieval_model_profile(wf, text, apply=force),
            "eval_retrieval_replay": lambda: evaluate_retrieval_replay_calibration(
                wf, min_samples=max(1, limit), apply=force
            ),
            "eval_cross_shard_replay": lambda: evaluate_cross_shard_replay(
                wf,
                [line.strip() for line in text.splitlines() if line.strip()],
                tier=budget if budget in {"fast", "standard", "deep"} else "standard",
            ),
            "eval_cross_shard_fusion": lambda: evaluate_cross_shard_fusion(
                wf,
                list((parse_payload(payload) or {}).get("cases", [])),
                tier=budget if budget in {"fast", "standard", "deep"} else "standard",
            ),
            "job_status": lambda: workspace_job_status(wf, record_id, limit=limit),
            "job_cancel": lambda: cancel_workspace_job(wf, record_id),
            "job_reindex": lambda: submit_reindex_workspace_job(wf, projects=projects, paths=files),
            "watcher_start": lambda: start_watcher_daemon(wf),
            "watcher_status": lambda: watcher_daemon_status(wf),
            "watcher_stop": lambda: stop_watcher_daemon(wf),
            "change_impact_recent": lambda: recent_change_impact_reports(wf, limit=limit),
            "change_impact_pending": lambda: pending_change_impact_reports(wf, limit=limit),
            "change_impact_confirm": lambda: record_change_impact_feedback(
                wf,
                record_id,
                decision=action_filter or status,
                task_id=task_id,
                session_id=session_id,
                validation_status=str((parse_payload(payload) or {}).get("validation_status", "not_run")),
                validation_summary=str((parse_payload(payload) or {}).get("validation_summary", "")),
                verified_by=verified_by,
                note=str((parse_payload(payload) or {}).get("note", "")),
            ),
            "assertion_status": lambda: _update_assertion_status_action(wf, record_id, status, payload, source),
            "assertion_inspect": lambda: _inspect_assertion_action(wf, record_id),
            "assertion_query": lambda: __import__(
                "memory_center.core.knowledge.assertions", fromlist=["query_assertions"]
            ).query_assertions(
                WorkspaceStore(wf),
                as_of_generation=str((parse_payload(payload) or {}).get("as_of_generation", "")),
                as_of_time=str((parse_payload(payload) or {}).get("as_of_time", "")),
                time_axis=str((parse_payload(payload) or {}).get("time_axis", "valid")),
                limit=min(max(1, limit), 500),
            ),
            "evidence_subgraph_export": lambda: export_evidence_subgraph(
                wf,
                text or name or record_id,
                direction=direction if direction in {"both", "upstream", "downstream"} else "both",
                max_depth=min(max(1, max_depth), 3),
                max_edges=min(max(1, limit), 120),
                output_format=action_filter or "json",
            ),
            "architecture_communities": lambda: analyze_architecture_communities(wf, limit=min(max(1, limit), 50)),
            "change_review": lambda: plan_change_risk(
                wf,
                scope=scope,
                files=files,
                detail_level=view if view in {"minimal", "standard", "deep"} else "minimal",
                refresh=not strict,
                max_depth=max_depth,
            ),
            "eval_cochange": lambda: evaluate_git_cochange(
                wf,
                max_commits=min(max(1, limit), 100),
                warmup_commits=max(1, min(50, int((parse_payload(payload) or {}).get("warmup_commits", 5) or 5))),
                apply=force,
            ),
            "eval_write_quality": lambda: memory_eval_write_quality(
                wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit
            ),
            "eval_resume": lambda: memory_eval_resume(
                wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit
            ),
            "eval_handoff": lambda: memory_eval_handoff(
                wf, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit
            ),
            "eval_regression_suite": lambda: memory_eval_regression_suite(
                wf, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit
            ),
            "eval_index_freshness": lambda: memory_eval_index_freshness(wf, scope=scope),
            "eval_tool_adoption": lambda: memory_eval_tool_adoption(wf, limit=limit),
            "eval_context_weight": lambda: memory_eval_context_weight(wf, intent=intent, limit=limit),
            "eval_agent_guidance": lambda: memory_eval_agent_guidance(wf, intent=intent, limit=limit),
            "eval_agent_guidance_adoption": lambda: memory_eval_agent_guidance_adoption(
                wf, session_id=session_id, limit=limit
            ),
            "eval_agent_guidance_adoption_trend": lambda: memory_eval_agent_guidance_adoption_trend(
                wf, session_id=session_id, limit=limit
            ),
            "eval_agent_guidance_replay": lambda: memory_eval_agent_guidance_replay(
                wf, session_id=session_id, limit=limit
            ),
            "eval_agent_guidance_replay_campaign": lambda: memory_eval_agent_guidance_replay_campaign(
                wf, min_events=20, limit=max(limit, 500)
            ),
            "eval_agent_guidance_replay_trend": lambda: memory_eval_agent_guidance_replay_trend(
                wf, session_id=session_id, limit=limit
            ),
            "eval_agent_guidance_trend": lambda: memory_eval_agent_guidance_trend(wf, intent=intent, limit=limit),
            "eval_workflow_orchestration": lambda: memory_eval_workflow_orchestration(
                wf, task_id=task_id, session_id=session_id, intent=intent, limit=limit
            ),
            "eval_token_gain": lambda: memory_eval_token_gain(
                wf, tool_name=tool_name, budget=budget, model=model, limit=limit
            ),
            "eval_parser_benchmark": lambda: memory_eval_parser_benchmark(wf, limit=limit),
            "eval_java_call_resolution": lambda: eval_java_call_resolution_action(wf, name, strict=strict),
            "eval_java_call_resolution_metrics": lambda: eval_java_call_resolution_metrics_action(wf),
            "eval_java_call_resolution_review": lambda: eval_java_call_resolution_review_action(wf, name, limit=limit),
            "eval_java_call_resolution_unresolved": lambda: eval_java_call_resolution_unresolved_action(
                wf, limit=limit
            ),
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
            "generate_skills": lambda: generate_skills(wf, output_dir or None),
            "group_status": lambda: group_status(group),
            "group_query": lambda: group_query(group, query=text, limit=limit),
            "group_impact": lambda: group_impact(
                group, target=intent or text, direction=direction, max_depth=max_depth
            ),
            "group_chain": lambda: group_chain(
                group, symbol=name or text, direction=direction, depth=max_depth, limit=limit
            ),
            "method_walkthrough": lambda: memory_method_walkthrough(
                wf,
                name or text or intent,
                depth=max_depth,
                limit=limit,
                project=project,
                view=view,
                budget=budget,
                report_level=model or "standard",
            ),
            "walkthrough_health": lambda: memory_walkthrough_health(
                wf, symbol=name or text or intent, project=project, report_level=model or "standard"
            ),
            "walkthrough_export": lambda: memory_export_walkthrough_artifact(
                wf, symbol=name or text or intent, project=project, report_level=model or "deep", title=title
            ),
            "eval_walkthrough_quality": lambda: memory_eval_walkthrough_quality(
                wf, symbol=name or text or intent, project=project, report_level=model or "standard"
            ),
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
            "runtime_inspect": lambda: inspect_runtime(wf, thread_id=payload or session_id),
            "explanation": lambda: explanation_action(text, persona=intent or "developer"),
            "business_flow": lambda: business_flow_action(wf, name, max_depth),
            "business_flow_impact": lambda: business_flow_impact_action(wf, intent or text, max_depth),
            "metrics_summary": lambda: metrics_summary_action(wf, name),
            "regression_alerts": lambda: regression_alerts_action(wf, name),
        }
    )
    return registry
