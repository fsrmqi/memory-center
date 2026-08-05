"""Shared route dependencies kept behind the HTTP adapter seam."""

from __future__ import annotations

from typing import Any

from memory_center.application.jobs import analysis_job_status
from memory_center.application.performance import record_workspace_performance_snapshot
from memory_center.application.presentation import (
    export_continuity_dashboard_html,
    export_focus_task_html,
    export_index_freshness_html,
    export_memory_backend_html,
    export_receipts_html,
    export_ref_html,
    export_timeline_html,
    export_usage_report_html,
    export_workbench_index_html,
    export_workspace_dashboard_html,
)
from memory_center.core.freshness.change_reports import recent_change_impact_reports, record_change_impact_feedback
from memory_center.core.knowledge.assertions import inspect_assertion, query_assertions, update_assertion_status
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
from memory_center.core.orchestrator import (
    bootstrap_workspace_context,  # noqa: F401 - re-exported for HTTP route modules
    execute_mcp_bridge_action,  # noqa: F401 - re-exported for HTTP route modules
    execute_provider_action,  # noqa: F401 - re-exported for HTTP route modules
    fuse_provider_evidence,  # noqa: F401 - re-exported for HTTP route modules
    group_chain,
    group_impact,
    group_query,
    group_status,
    mcp_bridge_status,  # noqa: F401 - re-exported for HTTP route modules
    memory_backend_query,
    memory_callees,
    memory_callers,
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
    memory_eval_tool_adoption,
    memory_eval_walkthrough_quality,
    memory_eval_write_quality,
    memory_execute_write,
    memory_export_walkthrough_artifact,
    memory_method_walkthrough,
    memory_plan_change,
    memory_plan_write,
    memory_query_hybrid,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_tool_usage_report,
    memory_verify_checklist,
    memory_walkthrough_health,
    memory_write_judge,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_end_session,
    workspace_handoff_history,
    workspace_handoff_packet,
    workspace_lookup_hint,
    workspace_model_profile,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_recent_sessions,
    workspace_record_agent_guidance,
    workspace_record_case,
    workspace_record_close_feedback,
    workspace_replay_write_chain,
    workspace_resume_context,
    workspace_resume_packet,
    workspace_session_summary,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_suggest_case,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_task_resume_check,
    workspace_unresolved_items,
    workspace_write_receipts,
)
from memory_center.core.presentation.evidence_subgraph import export_evidence_subgraph
from memory_center.core.retrieval.planner import (
    workspace_performance_snapshot_status,
)
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
    list_task_spaces,
    resolve_task_space,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
    update_task_status,
)
from memory_center.core.tasks.delivery import (
    delivery_matrix,
    delivery_policy_status,
    delivery_skill_replay_set,
    delivery_workflow_status,
    derive_delivery_failure_candidates,
    evaluate_delivery_skill,
    execute_delivery_validation,
    initialize_delivery_workflow,
    propose_delivery_breakdown,
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
from memory_center.core.workspace.jobs import cancel_workspace_job


def workspace_background_job_status(workspace_file: str, job_id: str = "", *, limit: int = 20) -> dict[str, Any]:
    """通过 application 边界读取持久化后台任务状态。"""
    return analysis_job_status(workspace_file, job_id, limit=limit)


def workspace_background_job_cancel(workspace_file: str, job_id: str) -> dict[str, Any]:
    """通过 application 边界取消一个可协作的后台任务。"""
    return cancel_workspace_job(workspace_file, job_id)


def workspace_performance_snapshot(workspace_file: str, *, samples: int = 5, tier: str = "fast") -> dict[str, Any]:
    return record_workspace_performance_snapshot(workspace_file, samples=samples, tier=tier)


def workspace_asset_status(workspace_file: str, *, limit: int = 100, max_chars: int = 0) -> dict[str, Any]:
    return collaboration_asset_status(workspace_file, limit=limit, max_chars=max_chars)


def workspace_asset_register(workspace_file: str, payload: dict[str, Any], *, actor: str = "") -> dict[str, Any]:
    return register_collaboration_asset(workspace_file, **{**payload, "actor": actor})


def workspace_asset_sync(workspace_file: str, *, owner: str = "") -> dict[str, Any]:
    return sync_workspace_collaboration_assets(workspace_file, owner=owner)


def workspace_asset_share(
    workspace_file: str,
    asset_id: str,
    *,
    visibility: str,
    actor: str,
    allowed_agents: list[str] | None = None,
    allowed_roles: list[str] | None = None,
) -> dict[str, Any]:
    return submit_asset_for_sharing(
        workspace_file,
        asset_id,
        visibility=visibility,
        actor=actor,
        allowed_agents=allowed_agents,
        allowed_roles=allowed_roles,
    )


def workspace_asset_approve(
    workspace_file: str, asset_id: str, *, approved: bool, actor: str, note: str = ""
) -> dict[str, Any]:
    return approve_collaboration_asset(workspace_file, asset_id, approved=approved, actor=actor, note=note)


def workspace_asset_bind(
    workspace_file: str, asset_id: str, *, actor: str, agents: list[str] | None = None, roles: list[str] | None = None
) -> dict[str, Any]:
    return bind_collaboration_asset(workspace_file, asset_id, actor=actor, agents=agents, roles=roles)


def workspace_asset_loadout(
    workspace_file: str, *, agent_id: str = "", role: str = "", limit: int = 12, max_chars: int = 0
) -> dict[str, Any]:
    return collaboration_asset_loadout(workspace_file, agent_id=agent_id, role=role, limit=limit, max_chars=max_chars)


def workspace_wiki_document_ingest(
    workspace_file: str, document_path: str, *, owner: str, visibility: str = "private", tags: list[str] | None = None
) -> dict[str, Any]:
    return ingest_wiki_document_asset(workspace_file, document_path, owner=owner, visibility=visibility, tags=tags)


def workspace_change_impact_reports(
    workspace_file: str, *, limit: int = 20, pending_only: bool = False
) -> dict[str, Any]:
    """通过 application 边界读取 watcher 的轻量变更影响报告。"""
    return recent_change_impact_reports(workspace_file, limit=limit, pending_only=pending_only)


def workspace_change_impact_confirm(
    workspace_file: str,
    report_id: str,
    *,
    decision: str,
    task_id: str = "",
    session_id: str = "",
    validation_status: str = "not_run",
    validation_summary: str = "",
    verified_by: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """通过 application 边界追加一条变更影响人工确认。"""
    return record_change_impact_feedback(
        workspace_file,
        report_id,
        decision=decision,
        task_id=task_id,
        session_id=session_id,
        validation_status=validation_status,
        validation_summary=validation_summary,
        verified_by=verified_by,
        note=note,
    )


def workspace_evidence_subgraph(
    workspace_file: str,
    target: str,
    *,
    direction: str = "both",
    max_depth: int = 2,
    max_edges: int = 60,
    output_format: str = "json",
) -> dict[str, Any]:
    """通过 application 边界导出有界证据子图。"""
    return export_evidence_subgraph(
        workspace_file,
        target,
        direction=direction,
        max_depth=max_depth,
        max_edges=max_edges,
        output_format=output_format,
    )


def workspace_architecture_communities(workspace_file: str, *, limit: int = 20) -> dict[str, Any]:
    """通过 application 边界显式计算架构社区。"""
    return analyze_architecture_communities(workspace_file, limit=limit)


def workspace_assertion_status(
    workspace_file: str,
    assertion_id: str,
    *,
    status: str,
    verification_ref: str = "",
    actor: str = "",
    task_id: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    """HTTP facade for an explicit, auditable assertion status transition."""
    return update_assertion_status(
        WorkspaceStore(workspace_file),
        assertion_id,
        status=status,
        verification_ref=verification_ref,
        actor=actor,
        task_id=task_id,
        session_id=session_id,
    )


def workspace_assertion_inspect(workspace_file: str, assertion_id: str) -> dict[str, Any]:
    return inspect_assertion(WorkspaceStore(workspace_file), assertion_id)


def workspace_assertion_query(
    workspace_file: str, *, as_of_generation: str = "", as_of_time: str = "", time_axis: str = "valid", limit: int = 20
) -> dict[str, Any]:
    return {
        "assertions": query_assertions(
            WorkspaceStore(workspace_file),
            as_of_generation=as_of_generation,
            as_of_time=as_of_time,
            time_axis=time_axis,
            limit=limit,
        )
    }


def workspace_delivery_status(workspace_file: str, task_id: str) -> dict[str, Any]:
    return delivery_workflow_status(workspace_file, task_id)


def workspace_delivery_init(workspace_file: str, task_id: str, *, actor: str = "") -> dict[str, Any]:
    return initialize_delivery_workflow(workspace_file, task_id, actor=actor)


def workspace_delivery_contract(
    workspace_file: str, task_id: str, *, kind: str, items: list[dict[str, Any]], actor: str = ""
) -> dict[str, Any]:
    return update_delivery_contract(workspace_file, task_id, kind=kind, items=items, actor=actor)


def workspace_delivery_subtask_status(
    workspace_file: str, task_id: str, *, subtask_id: str, status: str, actor: str = ""
) -> dict[str, Any]:
    return update_delivery_subtask_status(workspace_file, task_id, subtask_id, status, actor=actor)


def workspace_delivery_validation(
    workspace_file: str,
    task_id: str,
    *,
    status: str,
    summary: str = "",
    command: str = "",
    exit_code: int | None = None,
    acceptance_ids: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    actor: str = "",
) -> dict[str, Any]:
    return record_delivery_validation(
        workspace_file,
        task_id,
        status=status,
        summary=summary,
        command=command,
        exit_code=exit_code,
        acceptance_ids=acceptance_ids,
        evidence_refs=evidence_refs,
        actor=actor,
    )


def workspace_delivery_breakdown(
    workspace_file: str, task_id: str, *, source_refs: list[str], summary: str = ""
) -> dict[str, Any]:
    return propose_delivery_breakdown(workspace_file, task_id, source_refs=source_refs, summary=summary)


def workspace_delivery_policy(
    workspace_file: str, *, policy: dict[str, Any] | None = None, actor: str = ""
) -> dict[str, Any]:
    return (
        update_delivery_policy(workspace_file, policy, actor=actor)
        if policy is not None
        else delivery_policy_status(workspace_file)
    )


def workspace_delivery_execute_validation(
    workspace_file: str, task_id: str, *, profile_id: str, acceptance_ids: list[str] | None = None, actor: str = ""
) -> dict[str, Any]:
    return execute_delivery_validation(
        workspace_file, task_id, profile_id=profile_id, acceptance_ids=acceptance_ids, actor=actor
    )


def workspace_delivery_matrix(workspace_file: str, task_id: str, *, write: bool = True) -> dict[str, Any]:
    return delivery_matrix(workspace_file, task_id, write=write)


def workspace_delivery_transition(
    workspace_file: str, task_id: str, *, stage: str, actor: str = "", force: bool = False
) -> dict[str, Any]:
    return transition_delivery_stage(workspace_file, task_id, stage, actor=actor, force=force)


def workspace_delivery_skill_canary(workspace_file: str, task_id: str, *, actor: str = "") -> dict[str, Any]:
    return start_delivery_skill_canary(workspace_file, task_id, actor=actor)


def workspace_delivery_skill_observe(
    workspace_file: str,
    *,
    skill_id: str,
    outcome: str,
    evidence_refs: list[str] | None = None,
    latency_ms: int | None = None,
    token_count: int | None = None,
    actor: str = "",
) -> dict[str, Any]:
    return record_delivery_skill_observation(
        workspace_file,
        skill_id,
        outcome=outcome,
        evidence_refs=evidence_refs,
        latency_ms=latency_ms,
        token_count=token_count,
        actor=actor,
    )


def workspace_delivery_skill_evaluate(workspace_file: str, *, skill_id: str = "") -> dict[str, Any]:
    return evaluate_delivery_skill(workspace_file, skill_id=skill_id)


def workspace_delivery_skill_contract_update(
    workspace_file: str, task_id: str, *, contract: dict[str, Any], actor: str = ""
) -> dict[str, Any]:
    return update_delivery_skill_contract(workspace_file, task_id, contract=contract, actor=actor)


def workspace_delivery_skill_replay(workspace_file: str, *, skill_id: str, limit: int = 100) -> dict[str, Any]:
    return delivery_skill_replay_set(workspace_file, skill_id=skill_id, limit=limit)


def workspace_delivery_skill_rollback(
    workspace_file: str, *, skill_id: str, reason: str, actor: str = ""
) -> dict[str, Any]:
    return rollback_delivery_skill(workspace_file, skill_id, reason=reason, actor=actor)


def workspace_delivery_skill_recommend(
    workspace_file: str, *, intent: str, language: str = "", limit: int = 5
) -> dict[str, Any]:
    return recommend_delivery_skills(workspace_file, intent, language=language, limit=limit)


def workspace_delivery_failure_candidates(workspace_file: str, *, limit_tasks: int = 200) -> dict[str, Any]:
    return derive_delivery_failure_candidates(workspace_file, limit_tasks=limit_tasks)


def workspace_delivery_skill_synthesize(workspace_file: str, *, min_support: int = 3) -> dict[str, Any]:
    return synthesize_delivery_skill_trajectories(workspace_file, min_support=min_support)


__all__ = [
    "Any",
    "export_continuity_dashboard_html",
    "export_focus_task_html",
    "export_index_freshness_html",
    "export_receipts_html",
    "export_ref_html",
    "export_memory_backend_html",
    "export_timeline_html",
    "export_usage_report_html",
    "export_workbench_index_html",
    "export_workspace_dashboard_html",
    "group_chain",
    "group_impact",
    "group_query",
    "group_status",
    "memory_callers",
    "memory_callees",
    "memory_execute_write",
    "memory_eval_agent_guidance",
    "memory_eval_agent_guidance_adoption",
    "memory_eval_agent_guidance_adoption_trend",
    "memory_eval_agent_guidance_replay",
    "memory_eval_agent_guidance_replay_campaign",
    "memory_eval_agent_guidance_replay_trend",
    "memory_eval_agent_guidance_trend",
    "memory_eval_write_quality",
    "memory_eval_regression_suite",
    "memory_eval_index_freshness",
    "memory_eval_tool_adoption",
    "memory_eval_context_weight",
    "memory_eval_java_call_resolution",
    "memory_eval_java_call_resolution_metrics",
    "memory_eval_java_call_resolution_review",
    "memory_eval_java_call_resolution_unresolved",
    "memory_eval_parser_benchmark",
    "memory_eval_walkthrough_quality",
    "memory_eval_resume",
    "memory_eval_handoff",
    "memory_export_walkthrough_artifact",
    "memory_method_walkthrough",
    "memory_backend_query",
    "memory_ref_batch",
    "memory_ref_get",
    "memory_tool_usage_report",
    "memory_walkthrough_health",
    "memory_plan_change",
    "memory_plan_write",
    "memory_query_hybrid",
    "memory_search_code",
    "memory_symbol",
    "memory_verify_checklist",
    "memory_write_judge",
    "workspace_end_session",
    "workspace_background_job_status",
    "workspace_background_job_cancel",
    "workspace_performance_snapshot",
    "workspace_performance_snapshot_status",
    "workspace_asset_approve",
    "workspace_asset_bind",
    "workspace_asset_loadout",
    "workspace_asset_register",
    "workspace_asset_share",
    "workspace_asset_status",
    "workspace_asset_sync",
    "workspace_change_impact_reports",
    "workspace_change_impact_confirm",
    "workspace_evidence_subgraph",
    "workspace_delivery_breakdown",
    "workspace_delivery_contract",
    "workspace_delivery_execute_validation",
    "workspace_delivery_init",
    "workspace_delivery_matrix",
    "workspace_delivery_policy",
    "workspace_delivery_failure_candidates",
    "workspace_delivery_skill_canary",
    "workspace_delivery_skill_contract_update",
    "workspace_delivery_skill_evaluate",
    "workspace_delivery_skill_observe",
    "workspace_delivery_skill_recommend",
    "workspace_delivery_skill_replay",
    "workspace_delivery_skill_rollback",
    "workspace_delivery_skill_synthesize",
    "workspace_delivery_status",
    "workspace_delivery_subtask_status",
    "workspace_delivery_transition",
    "workspace_delivery_validation",
    "workspace_architecture_communities",
    "workspace_assertion_status",
    "workspace_assertion_inspect",
    "workspace_assertion_query",
    "workspace_handoff_packet",
    "workspace_handoff_history",
    "workspace_lookup_hint",
    "workspace_model_profile",
    "workspace_continuity_dashboard",
    "workspace_dashboard",
    "workspace_next_actions",
    "workspace_recent_evidence",
    "workspace_recent_sessions",
    "workspace_record_agent_guidance",
    "workspace_record_case",
    "workspace_record_close_feedback",
    "workspace_resume_packet",
    "workspace_resume_context",
    "workspace_session_summary",
    "workspace_sniff",
    "workspace_start_session",
    "workspace_status",
    "workspace_suggest_case",
    "workspace_task_resume_check",
    "workspace_sync_case_to_artifacts",
    "workspace_sync_sniff_to_artifacts",
    "workspace_unresolved_items",
    "workspace_replay_write_chain",
    "workspace_write_receipts",
    "workspace_wiki_document_ingest",
    "memory_discover",
    "append_change_log",
    "append_task_change_log",
    "archive_task_space",
    "artifact_context",
    "artifact_outline",
    "auto_archive_task_spaces",
    "compact_change_log",
    "create_task_space",
    "get_artifact",
    "get_task_artifact",
    "list_artifacts",
    "list_task_spaces",
    "resolve_task_space",
    "touch_task_activity",
    "update_task_status",
    "update_artifact",
    "update_task_artifact",
]
