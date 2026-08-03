from __future__ import annotations

import json

from memory_center.application.http_facades import (
    append_change_log,
    append_task_change_log,
    archive_task_space,
    artifact_context,
    artifact_outline,
    auto_archive_task_spaces,
    bootstrap_workspace_context,
    compact_change_log,
    create_task_space,
    get_artifact,
    get_task_artifact,
    list_artifacts,
    list_task_spaces,
    memory_backend_query,
    memory_callees,
    memory_callers,
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
    resolve_task_space,
    touch_task_activity,
    update_artifact,
    update_task_artifact,
    update_task_status,
    workspace_architecture_communities,
    workspace_assertion_inspect,
    workspace_assertion_query,
    workspace_assertion_status,
    workspace_background_job_status,
    workspace_change_impact_confirm,
    workspace_change_impact_reports,
    workspace_delivery_breakdown,
    workspace_delivery_contract,
    workspace_delivery_execute_validation,
    workspace_delivery_failure_candidates,
    workspace_delivery_init,
    workspace_delivery_matrix,
    workspace_delivery_policy,
    workspace_delivery_skill_canary,
    workspace_delivery_skill_evaluate,
    workspace_delivery_skill_observe,
    workspace_delivery_skill_recommend,
    workspace_delivery_skill_rollback,
    workspace_delivery_skill_synthesize,
    workspace_delivery_status,
    workspace_delivery_subtask_status,
    workspace_delivery_transition,
    workspace_delivery_validation,
    workspace_evidence_subgraph,
    workspace_lookup_hint,
    workspace_recent_evidence,
    workspace_recent_sessions,
    workspace_record_agent_guidance,
    workspace_replay_write_chain,
    workspace_session_summary,
    workspace_sniff,
    workspace_status,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_write_receipts,
)
from memory_center.core.foundation.dispatch import CommandRegistry

from .params import _parse_float, _parse_int


def _workspace_query_with_guidance(rp):
    result = memory_query_hybrid(
        rp.workspace(),
        rp.require('text'),
        limit=_parse_int(rp.params, "limit", 20),
        project=rp.project(),
        enable_vector=rp.bool_param("enable_vector"),
        vector_weight=_parse_float(rp.params, "vector_weight", 0.15, min_val=0.0, max_val=1.0),
    )
    session_id = rp.session_id()
    if session_id:
        workspace_record_agent_guidance(
            rp.workspace(),
            session_id,
            query=rp.require('text'),
            mode="query",
            source="http.workspace.query",
            payload=result,
        )
    return result


def _delivery_payload(rp) -> dict:
    try:
        payload = json.loads(rp.require("payload"))
    except json.JSONDecodeError as exc:
        raise ValueError("payload must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    return payload


def _delivery_items(payload: dict) -> list[dict]:
    items = payload.get("items", [])
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError("payload.items must be an array of objects")
    return items


def _workspace_delivery_contract(rp):
    payload = _delivery_payload(rp)
    return workspace_delivery_contract(
        rp.workspace(),
        rp.require("task_id"),
        kind=str(payload.get("kind", "")),
        items=_delivery_items(payload),
        actor=rp.get("actor", ""),
    )


def _workspace_delivery_subtask_status(rp):
    payload = _delivery_payload(rp)
    return workspace_delivery_subtask_status(
        rp.workspace(), rp.require("task_id"),
        subtask_id=str(payload.get("subtask_id", "")), status=str(payload.get("status", "")), actor=rp.get("actor", ""),
    )


def _workspace_delivery_validation(rp):
    payload = _delivery_payload(rp)
    return workspace_delivery_validation(
        rp.workspace(), rp.require("task_id"), status=str(payload.get("status", "recorded")),
        summary=str(payload.get("summary", "")), command=str(payload.get("command", "")), exit_code=payload.get("exit_code"),
        acceptance_ids=[str(item) for item in payload.get("acceptance_ids", []) if str(item).strip()],
        evidence_refs=[str(item) for item in payload.get("evidence_refs", []) if str(item).strip()], actor=rp.get("actor", ""),
    )


def _workspace_delivery_transition(rp):
    payload = _delivery_payload(rp)
    return workspace_delivery_transition(
        rp.workspace(), rp.require("task_id"), stage=str(payload.get("stage", "")), actor=rp.get("actor", ""), force=rp.bool_param("force")
    )


def _workspace_delivery_breakdown(rp):
    payload = _delivery_payload(rp)
    return workspace_delivery_breakdown(rp.workspace(), rp.require("task_id"), source_refs=[str(item) for item in payload.get("source_refs", []) if str(item).strip()], summary=str(payload.get("summary", "")))


def _workspace_delivery_policy(rp):
    payload = _delivery_payload(rp) if rp.get("payload") else None
    return workspace_delivery_policy(rp.workspace(), policy=payload, actor=rp.get("actor", ""))


def _workspace_delivery_execute_validation(rp):
    payload = _delivery_payload(rp)
    return workspace_delivery_execute_validation(rp.workspace(), rp.require("task_id"), profile_id=str(payload.get("profile_id", "")), acceptance_ids=[str(item) for item in payload.get("acceptance_ids", []) if str(item).strip()], actor=rp.get("actor", ""))


def _workspace_delivery_matrix(rp):
    return workspace_delivery_matrix(rp.workspace(), rp.require("task_id"), write=not rp.bool_param("dry_run"))


def _workspace_delivery_skill_observe(rp):
    payload = _delivery_payload(rp)
    return workspace_delivery_skill_observe(
        rp.workspace(), skill_id=str(payload.get("skill_id", "")), outcome=str(payload.get("outcome", "")),
        evidence_refs=[str(item) for item in payload.get("evidence_refs", []) if str(item).strip()],
        latency_ms=payload.get("latency_ms"), token_count=payload.get("token_count"), actor=rp.get("actor", ""),
    )


def _workspace_delivery_skill_rollback(rp):
    payload = _delivery_payload(rp)
    return workspace_delivery_skill_rollback(rp.workspace(), skill_id=str(payload.get("skill_id", "")), reason=str(payload.get("reason", "")), actor=rp.get("actor", ""))


def register_workspace_routes(registry: CommandRegistry) -> None:
    # --- workspace status / sniff / artifacts ---------------------------------
    registry.register("/workspace/status", lambda rp: workspace_status(
        rp.workspace(),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/bootstrap-context", lambda rp: bootstrap_workspace_context(
        rp.require("path"),
        intent=rp.intent(),
        query=rp.get("query", ""),
        target=rp.get("target", ""),
        limit=rp.int_param("limit", 8, max_val=12),
    ))
    registry.register("/workspace/job-status", lambda rp: workspace_background_job_status(
        rp.workspace(),
        rp.params.get("job_id", [""])[0],
        limit=_parse_int(rp.params, "limit", 20, max_val=100),
    ))
    registry.register("/workspace/change-impact-reports", lambda rp: workspace_change_impact_reports(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 20, max_val=100),
        pending_only=rp.bool_param("pending_only"),
    ))
    registry.register("/workspace/change-impact-confirm", lambda rp: workspace_change_impact_confirm(
        rp.workspace(),
        rp.require("report_id"),
        decision=rp.require("decision"),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        validation_status=rp.get("validation_status", "not_run"),
        validation_summary=rp.get("validation_summary", ""),
        verified_by=rp.list_param("verified_by") or None,
        note=rp.get("note", ""),
    ))
    registry.register("/workspace/evidence-subgraph", lambda rp: workspace_evidence_subgraph(
        rp.workspace(),
        rp.require("target"),
        direction=rp.get("direction", "both"),
        max_depth=rp.int_param("max_depth", 2, max_val=3),
        max_edges=rp.int_param("max_edges", 60, max_val=120),
        output_format=rp.get("format", "json"),
    ))
    registry.register("/workspace/architecture-communities", lambda rp: workspace_architecture_communities(
        rp.workspace(), limit=rp.int_param("limit", 20, max_val=50)
    ))
    registry.register("/workspace/assertion-status", lambda rp: workspace_assertion_status(
        rp.workspace(),
        rp.require("assertion_id"),
        status=rp.require("status"),
        verification_ref=rp.get("verification_ref", ""),
        actor=rp.get("actor", ""),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
    ))
    registry.register("/workspace/assertion", lambda rp: workspace_assertion_inspect(
        rp.workspace(), rp.require("assertion_id")
    ))
    registry.register("/workspace/assertions", lambda rp: workspace_assertion_query(
        rp.workspace(),
        as_of_generation=rp.get("as_of_generation", ""),
        as_of_time=rp.get("as_of_time", ""),
        time_axis=rp.get("time_axis", "valid"),
        limit=rp.int_param("limit", 20, max_val=500),
    ))
    registry.register("/workspace/sniff", lambda rp: workspace_sniff(
        rp.workspace(),
        rp.require('intent'),
        limit=_parse_int(rp.params, "limit", 12),
        auto_sync_mode=rp.auto_sync_mode(),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/artifacts", lambda rp: list_artifacts(
        rp.workspace(),
    ))
    registry.register("/workspace/artifact", lambda rp: get_artifact(
        rp.workspace(),
        rp.require('name'),
    ))
    registry.register("/workspace/artifact/outline", lambda rp: artifact_outline(
        rp.workspace(),
        rp.require('name'),
    ))
    registry.register("/workspace/artifact/context", lambda rp: artifact_context(
        rp.workspace(),
        rp.require('intent'),
        limit=_parse_int(rp.params, "limit", 6),
    ))
    registry.register("/workspace/artifact/update", lambda rp: update_artifact(
        rp.workspace(),
        rp.require('name'),
        rp.require('content'),
    ))
    registry.register("/workspace/change-log/append", lambda rp: append_change_log(
        rp.workspace(),
        rp.require('entry'),
    ))
    registry.register("/workspace/change-log/compact", lambda rp: compact_change_log(
        rp.workspace(),
        keep_recent=_parse_int(rp.params, "keep_recent", 30),
    ))

    # --- task spaces ----------------------------------------------------------
    registry.register("/workspace/task-spaces", lambda rp: list_task_spaces(
        rp.workspace(),
        include_archived=rp.bool_param("include_archived"),
    ))
    registry.register("/workspace/task-space/resolve", lambda rp: resolve_task_space(
        rp.workspace(),
        intent=rp.require('intent'),
        title=rp.title(),
        create_if_missing=rp.bool_param("create_if_missing", True),
        include_archived=rp.bool_param("include_archived"),
        limit_candidates=_parse_int(rp.params, "limit_candidates", 3),
        score_threshold=_parse_int(rp.params, "score_threshold", 3),
    ))
    registry.register("/workspace/task-space/create", lambda rp: create_task_space(
        rp.workspace(),
        title=rp.title(),
        intent=rp.intent(),
        owner=rp.get("owner", ""),
        tags=rp.list_param("tag"),
        priority=rp.get("priority", "medium"),
    ))
    registry.register("/workspace/delivery", lambda rp: workspace_delivery_status(
        rp.workspace(), rp.require("task_id")
    ))
    registry.register("/workspace/delivery/init", lambda rp: workspace_delivery_init(
        rp.workspace(), rp.require("task_id"), actor=rp.get("actor", "")
    ))
    registry.register("/workspace/delivery/contract", _workspace_delivery_contract)
    registry.register("/workspace/delivery/breakdown", _workspace_delivery_breakdown)
    registry.register("/workspace/delivery/policy", _workspace_delivery_policy)
    registry.register("/workspace/delivery/execute-validation", _workspace_delivery_execute_validation)
    registry.register("/workspace/delivery/matrix", _workspace_delivery_matrix)
    registry.register("/workspace/delivery/subtask-status", _workspace_delivery_subtask_status)
    registry.register("/workspace/delivery/validation", _workspace_delivery_validation)
    registry.register("/workspace/delivery/transition", _workspace_delivery_transition)
    registry.register("/workspace/delivery/skill/canary", lambda rp: workspace_delivery_skill_canary(rp.workspace(), rp.require("task_id"), actor=rp.get("actor", "")))
    registry.register("/workspace/delivery/skill/observe", _workspace_delivery_skill_observe)
    registry.register("/workspace/delivery/skill/evaluate", lambda rp: workspace_delivery_skill_evaluate(rp.workspace(), skill_id=rp.get("skill_id", "")))
    registry.register("/workspace/delivery/skill/rollback", _workspace_delivery_skill_rollback)
    registry.register("/workspace/delivery/skill/recommend", lambda rp: workspace_delivery_skill_recommend(rp.workspace(), intent=rp.require("intent"), limit=rp.int_param("limit", 5, max_val=20)))
    registry.register("/workspace/delivery/failure-candidates", lambda rp: workspace_delivery_failure_candidates(rp.workspace(), limit_tasks=rp.int_param("limit_tasks", 200, max_val=500)))
    registry.register("/workspace/delivery/skill/synthesize", lambda rp: workspace_delivery_skill_synthesize(rp.workspace(), min_support=rp.int_param("min_support", 3, max_val=20)))
    registry.register("/workspace/task-artifact", lambda rp: get_task_artifact(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('name'),
    ))
    registry.register("/workspace/task-artifact/update", lambda rp: update_task_artifact(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('name'),
        rp.require('content'),
    ))
    registry.register("/workspace/task-change-log/append", lambda rp: append_task_change_log(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('entry'),
        keep_recent=_parse_int(rp.params, "keep_recent", 30),
    ))
    registry.register("/workspace/task-space/archive", lambda rp: archive_task_space(
        rp.workspace(),
        rp.require('task_id'),
        reason=rp.get("reason", ""),
    ))
    registry.register("/workspace/task-space/status", lambda rp: update_task_status(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('status'),
    ))
    registry.register("/workspace/task-space/touch-activity", lambda rp: touch_task_activity(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('source'),
    ))
    registry.register("/workspace/task-spaces/auto-archive", lambda rp: auto_archive_task_spaces(
        rp.workspace(),
        retention_days=_parse_int(rp.params, "retention_days", 30),
    ))
    registry.register("/workspace/artifacts/sync-sniff", lambda rp: workspace_sync_sniff_to_artifacts(
        rp.workspace(),
        rp.require('intent'),
        limit=_parse_int(rp.params, "limit", 12),
        task_id=rp.task_id(),
        title=rp.title(),
        auto_sync_mode=rp.auto_sync_mode(),
    ))
    registry.register("/workspace/artifacts/sync-case", lambda rp: workspace_sync_case_to_artifacts(
        rp.workspace(),
        rp.require('session_id'),
        task_id=rp.task_id(),
        title=rp.title(),
        auto_sync_mode=rp.auto_sync_mode(),
    ))

    # --- query / search / symbols / call graph --------------------------------
    registry.register("/workspace/query", _workspace_query_with_guidance)
    registry.register("/workspace/search-code", lambda rp: memory_search_code(
        rp.workspace(),
        rp.require('text'),
        scope=rp.get("scope", ""),
        limit=_parse_int(rp.params, "limit", 20),
        project=rp.project(),
    ))
    registry.register("/workspace/lookup-hint", lambda rp: workspace_lookup_hint(
        rp.workspace(),
        query=rp.require('query'),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 8),
    ))
    registry.register("/workspace/symbol", lambda rp: memory_symbol(
        rp.workspace(),
        rp.require('name'),
        limit=_parse_int(rp.params, "limit", 10),
        project=rp.project(),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/callers", lambda rp: memory_callers(
        rp.workspace(),
        rp.require('symbol'),
        depth=_parse_int(rp.params, "depth", 2),
        limit=_parse_int(rp.params, "limit", 80, max_val=500),
        project=rp.project(),
        view=rp.view(),
        budget=rp.budget(),
        min_confidence=_parse_float(rp.params, "min_confidence", 0.85),
    ))
    registry.register("/workspace/callees", lambda rp: memory_callees(
        rp.workspace(),
        rp.require('symbol'),
        depth=_parse_int(rp.params, "depth", 2),
        limit=_parse_int(rp.params, "limit", 80, max_val=500),
        project=rp.project(),
        view=rp.view(),
        budget=rp.budget(),
        min_confidence=_parse_float(rp.params, "min_confidence", 0.85),
    ))
    registry.register("/workspace/plan-change", lambda rp: memory_plan_change(
        rp.workspace(),
        rp.require('target'),
        direction=rp.get("direction", "upstream"),
        max_depth=_parse_int(rp.params, "max_depth", 3),
    ))

    # --- method walkthrough ---------------------------------------------------
    registry.register("/workspace/method-walkthrough", lambda rp: memory_method_walkthrough(
        rp.workspace(),
        rp.require('symbol'),
        depth=_parse_int(rp.params, "depth", 4),
        limit=_parse_int(rp.params, "limit", 80),
        project=rp.project(),
        view=rp.view(),
        budget=rp.budget(),
        report_level=rp.report_level(),
    ))
    registry.register("/workspace/walkthrough-health", lambda rp: memory_walkthrough_health(
        rp.workspace(),
        symbol=rp.get("symbol", ""),
        project=rp.project(),
        report_level=rp.report_level(),
    ))
    registry.register("/workspace/walkthrough-export", lambda rp: memory_export_walkthrough_artifact(
        rp.workspace(),
        symbol=rp.require('symbol'),
        project=rp.project(),
        report_level=rp.report_level("deep"),
        title=rp.title(),
    ))
    registry.register("/workspace/walkthrough-eval", lambda rp: memory_eval_walkthrough_quality(
        rp.workspace(),
        symbol=rp.require('symbol'),
        project=rp.project(),
        report_level=rp.report_level(),
    ))

    # --- write pipeline / receipts / replay -----------------------------------
    registry.register("/workspace/memory-write-judge", lambda rp: memory_write_judge(
        rp.workspace(),
        text=rp.require('text'),
        source=rp.get("source", "note"),
        intent=rp.intent(),
        prefer_layer=rp.get("prefer_layer", ""),
        projects=rp.list_param("project") or None,
        files=rp.list_param("file") or None,
    ))
    registry.register("/workspace/memory-plan-write", lambda rp: memory_plan_write(
        rp.workspace(),
        text=rp.require('text'),
        source=rp.get("source", "note"),
        intent=rp.intent(),
        session_id=rp.session_id(),
        task_id=rp.task_id(),
        title=rp.title(),
        prefer_layer=rp.get("prefer_layer", ""),
        projects=rp.list_param("project") or None,
        files=rp.list_param("file") or None,
    ))
    registry.register("/workspace/memory-execute-write", lambda rp: memory_execute_write(
        rp.workspace(),
        text=rp.require('text'),
        source=rp.get("source", "note"),
        intent=rp.intent(),
        session_id=rp.session_id(),
        task_id=rp.task_id(),
        title=rp.title(),
        prefer_layer=rp.get("prefer_layer", ""),
        projects=rp.list_param("project") or None,
        files=rp.list_param("file") or None,
    ))
    registry.register("/workspace/write-receipts", lambda rp: workspace_write_receipts(
        rp.workspace(),
        layer=rp.get("layer", ""),
        action=rp.get("action", ""),
        scope=rp.get("scope", ""),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 50),
    ))
    registry.register("/workspace/replay-write-chain", lambda rp: workspace_replay_write_chain(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 100),
    ))

    # --- evaluations ----------------------------------------------------------
    registry.register("/workspace/eval-write-quality", lambda rp: memory_eval_write_quality(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 100),
    ))
    registry.register("/workspace/eval-resume", lambda rp: memory_eval_resume(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 20),
    ))
    registry.register("/workspace/eval-handoff", lambda rp: memory_eval_handoff(
        rp.workspace(),
        target_model=rp.require('target_model'),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 20),
    ))
    registry.register("/workspace/eval-regression-suite", lambda rp: memory_eval_regression_suite(
        rp.workspace(),
        target_model=rp.target_model(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 20),
    ))
    registry.register("/workspace/eval-index-freshness", lambda rp: memory_eval_index_freshness(
        rp.workspace(),
        scope=rp.get("scope", "all"),
    ))
    registry.register("/workspace/eval-tool-adoption", lambda rp: memory_eval_tool_adoption(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 200),
    ))
    registry.register("/workspace/eval-context-weight", lambda rp: memory_eval_context_weight(
        rp.workspace(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 8),
    ))
    registry.register("/workspace/eval-agent-guidance", lambda rp: memory_eval_agent_guidance(
        rp.workspace(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 20),
    ))
    registry.register("/workspace/eval-agent-guidance-trend", lambda rp: memory_eval_agent_guidance_trend(
        rp.workspace(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 20),
    ))
    registry.register("/workspace/eval-agent-guidance-adoption", lambda rp: memory_eval_agent_guidance_adoption(
        rp.workspace(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 200),
    ))
    registry.register("/workspace/eval-agent-guidance-adoption-trend", lambda rp: memory_eval_agent_guidance_adoption_trend(
        rp.workspace(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 200),
    ))
    registry.register("/workspace/eval-agent-guidance-replay", lambda rp: memory_eval_agent_guidance_replay(
        rp.workspace(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 200),
    ))
    registry.register("/workspace/eval-agent-guidance-replay-campaign", lambda rp: memory_eval_agent_guidance_replay_campaign(
        rp.workspace(),
        min_events=_parse_int(rp.params, "min_events", 20),
        limit=_parse_int(rp.params, "limit", 500),
    ))
    registry.register("/workspace/eval-agent-guidance-replay-trend", lambda rp: memory_eval_agent_guidance_replay_trend(
        rp.workspace(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 200),
    ))
    registry.register("/workspace/eval-parser-benchmark", lambda rp: memory_eval_parser_benchmark(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 200),
        max_findings=_parse_int(rp.params, "max_findings", 20),
    ))
    registry.register("/workspace/eval-java-call-resolution", lambda rp: memory_eval_java_call_resolution(
        rp.workspace(),
        rp.require("cases"),
        min_recall=_parse_float(rp.params, "min_recall", 0.90),
        min_confidence_rate=_parse_float(rp.params, "min_confidence_rate", 0.85),
        min_resolution_level_rate=_parse_float(rp.params, "min_resolution_level_rate", 1.0),
        max_unresolved_rate=_parse_float(rp.params, "max_unresolved_rate", 0.10),
        fail_on_unexpected_high_confidence=rp.get("fail_on_unexpected_high_confidence", "").lower() in {"1", "true", "yes"},
        fail_on_forbidden_high_confidence=rp.get("fail_on_forbidden_high_confidence", "").lower() in {"1", "true", "yes"},
    ))
    registry.register("/workspace/eval-java-call-resolution-metrics", lambda rp: memory_eval_java_call_resolution_metrics(
        rp.workspace(),
    ))
    registry.register("/workspace/eval-java-call-resolution-review", lambda rp: memory_eval_java_call_resolution_review(
        rp.workspace(),
        rp.require("cases"),
        limit=_parse_int(rp.params, "limit", 200),
    ))
    registry.register("/workspace/eval-java-call-resolution-unresolved", lambda rp: memory_eval_java_call_resolution_unresolved(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 30),
    ))

    # --- tooling / refs / backend / verify ------------------------------------
    registry.register("/workspace/tool-usage-report", lambda rp: memory_tool_usage_report(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 200),
    ))
    registry.register("/workspace/ref-get", lambda rp: memory_ref_get(
        rp.workspace(),
        ref_id=rp.require('ref_id'),
    ))
    registry.register("/workspace/ref-batch", lambda rp: memory_ref_batch(
        rp.workspace(),
        ref_ids=rp.list_param("ref_id"),
    ))
    registry.register("/workspace/memory-backend-query", lambda rp: memory_backend_query(
        rp.workspace(),
        collection=rp.get("collection", ""),
        record_id=rp.get("record_id", ""),
        created_after=rp.get("created_after", ""),
        ref_path=rp.get("ref_path", ""),
        project=rp.project(),
        payload_type=rp.get("payload_type", ""),
        limit=_parse_int(rp.params, "limit", 50),
    ))
    registry.register("/workspace/verify-checklist", lambda rp: memory_verify_checklist(
        rp.workspace(),
        rp.require('target'),
    ))

    # --- sessions / recent / evidence -----------------------------------------
    registry.register("/workspace/sessions/recent", lambda rp: workspace_recent_sessions(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 10),
    ))
    registry.register("/workspace/session/summary", lambda rp: workspace_session_summary(
        rp.workspace(),
        rp.require('session_id'),
    ))
    registry.register("/workspace/recent-evidence", lambda rp: workspace_recent_evidence(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 10),
        budget=rp.budget(),
        view=rp.view(),
    ))
