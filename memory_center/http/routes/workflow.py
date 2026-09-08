from __future__ import annotations

import json

from memory_center.application.admin import (
    backend_consistency,
    benchmark_trend_report,
    constraint_action,
    drill_ref,
    drill_task,
    drill_timeline,
    regression_alerts_action,
    run_audit,
)
from memory_center.application.http_facades import (
    Any,
    group_impact,
    group_query,
    group_status,
    memory_discover,
    memory_eval_regression_suite,
    memory_tool_usage_report,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_end_session,
    workspace_handoff_history,
    workspace_handoff_packet,
    workspace_model_profile,
    workspace_next_actions,
    workspace_recent_evidence,
    workspace_record_case,
    workspace_record_close_feedback,
    workspace_resume_context,
    workspace_resume_packet,
    workspace_sniff,
    workspace_start_session,
    workspace_status,
    workspace_suggest_case,
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
    workspace_task_resume_check,
    workspace_unresolved_items,
)
from memory_center.application.quality_gates import quality_gates_summary
from memory_center.core.observability.agent_execution import summarize_agent_execution
from memory_center.core.orchestrator import (
    reinstate_case,
    supersede_case,
    workspace_case_decisions,
    workspace_list_consolidation_candidates,
    workspace_workbench_summary,
)
from memory_center.core.orchestrator import workspace_quality_overview
from memory_center.core.orchestrator import workspace_task_delivery_overview
from memory_center.core.knowledge.projection import workspace_knowledge_summary
from memory_center.core.foundation.dispatch import CommandRegistry

from .params import RouteParams, _parse_int


def register_workflow_routes(registry: CommandRegistry) -> None:
    # --- workflow facades (compound work-* routes) ----------------------------
    def _work_start(rp: RouteParams) -> dict[str, Any]:
        ws = rp.workspace()
        intent = rp.require('intent')
        limit = rp.limit(8)
        auto_sync_mode = rp.auto_sync_mode()
        budget = rp.budget()
        sniff_result = workspace_sniff(ws, intent, limit=limit, auto_sync_mode=auto_sync_mode, view="compact", budget=budget)
        synced = None
        resolved_task = sniff_result.get("resolved_task", {}) or {}
        auto_sync = sniff_result.get("auto_sync_recommendation", {}) or {}
        if rp.bool_param("sync_task_space", True) and (auto_sync.get("recommended") or resolved_task.get("task_id")):
            synced = workspace_sync_sniff_to_artifacts(
                ws,
                intent,
                limit=limit,
                task_id=str(resolved_task.get("task_id", "") or ""),
                title=str(resolved_task.get("title", "") or ""),
                auto_sync_mode=auto_sync_mode,
            )
        session = workspace_start_session(ws, intent)
        return {"workflow": "work-start", "sniff": sniff_result, "sync_sniff": synced, "session": session}

    def _work_sync(rp: RouteParams) -> dict[str, Any]:
        ws = rp.workspace()
        session_id = rp.session_id()
        task_id = rp.task_id()
        title = rp.title()
        auto_sync_mode = rp.auto_sync_mode()
        if session_id:
            return {
                "workflow": "work-sync",
                "mode": "case",
                "result": workspace_sync_case_to_artifacts(ws, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode),
            }
        intent = rp.require('intent')
        return {
            "workflow": "work-sync",
            "mode": "sniff",
            "result": workspace_sync_sniff_to_artifacts(ws, intent, limit=_parse_int(rp.params, "limit", 8), task_id=task_id, title=title, auto_sync_mode=auto_sync_mode),
        }

    def _work_resume(rp: RouteParams) -> dict[str, Any]:
        ws = rp.workspace()
        task_id = rp.task_id()
        session_id = rp.session_id()
        intent = rp.intent()
        limit = rp.limit(8)
        budget = rp.budget()
        return {
            "workflow": "work-resume",
            "resume_packet": workspace_resume_packet(ws, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "next_actions": workspace_next_actions(ws, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "unresolved_items": workspace_unresolved_items(ws, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "recent_evidence": workspace_recent_evidence(ws, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
        }

    def _work_resume_check(rp: RouteParams) -> dict[str, Any]:
        return workspace_task_resume_check(
            rp.workspace(),
            task_id=rp.task_id(),
            session_id=rp.session_id(),
            intent=rp.intent(),
            limit=rp.limit(8),
            budget=rp.budget(),
        )

    def _work_handoff(rp: RouteParams) -> dict[str, Any]:
        ws = rp.workspace()
        target_model = rp.require('target_model')
        task_id = rp.task_id()
        session_id = rp.session_id()
        intent = rp.intent()
        limit = rp.limit(8)
        budget = rp.budget()
        return {
            "workflow": "work-handoff",
            "handoff_packet": workspace_handoff_packet(ws, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "recent_evidence": workspace_recent_evidence(ws, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
            "tool_usage_report": memory_tool_usage_report(ws, limit=50),
        }

    def _work_close(rp: RouteParams) -> dict[str, Any]:
        ws = rp.workspace()
        session_id = rp.require('session_id')
        outcome = rp.get("outcome", "")
        task_id = rp.task_id()
        title = rp.title()
        auto_sync_mode = rp.auto_sync_mode()
        record_case = rp.bool_param("record_case", True)
        ended = workspace_end_session(
            ws,
            session_id,
            outcome=outcome,
            verified_by=rp.list_param("verified_by") or None,
            validation_command=rp.get("validation_command", ""),
            validation_exit_code=_parse_int(rp.params, "validation_exit_code", 0) if rp.get("validation_exit_code", "") else None,
            validation_summary=rp.get("validation_summary", ""),
            validation_status=rp.get("validation_status", ""),
        )
        synced = workspace_sync_case_to_artifacts(ws, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)
        draft = workspace_suggest_case(ws, session_id)
        recorded = None
        case = draft.get("draft_case", {}) if draft.get("found") else {}
        if record_case and case.get("projects") and case.get("files"):
            recorded = workspace_record_case(
                ws,
                case.get("task", outcome or "work-close"),
                case.get("projects", []),
                case.get("files", []),
                case.get("flow", ""),
                case.get("risk_points", []),
                verified_by=case.get("verified_by", []) or rp.list_param("verified_by") or None,
                source_session_id=session_id,
                source_task_id=task_id,
                actor=rp.get("actor") or "work_close_agent",
                decision_reason="work_close_auto_case",
            )
        candidate_feedback = workspace_record_close_feedback(
            ws,
            session_id,
            task_id=task_id,
            source="work_close_auto",
        )
        return {
            "workflow": "work-close",
            "ended": ended,
            "sync_case": synced,
            "suggested_case": draft,
            "record_case": recorded,
            "candidate_feedback": candidate_feedback,
        }

    def _work_health(rp: RouteParams) -> dict[str, Any]:
        ws = rp.workspace()
        intent = rp.get("intent", "Memory Center work health")
        target_model = rp.target_model()
        limit = rp.limit(5)
        return {
            "workflow": "work-health",
            "status": workspace_status(ws, view="compact", budget="medium"),
            "tool_usage_report": memory_tool_usage_report(ws, limit=50),
            "regression_suite": memory_eval_regression_suite(ws, intent=intent, target_model=target_model, limit=limit),
        }

    registry.register("/workspace/work-start", _work_start)
    registry.register("/workspace/work-sync", _work_sync)
    registry.register("/workspace/work-resume", _work_resume)
    registry.register("/workspace/work-resume-check", _work_resume_check)
    registry.register("/workspace/work-handoff", _work_handoff)
    registry.register("/workspace/work-close", _work_close)
    registry.register("/workspace/work-health", _work_health)

    registry.register("/workspace/unresolved-items", lambda rp: workspace_unresolved_items(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 10),
    ))
    registry.register("/workspace/next-actions", lambda rp: workspace_next_actions(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 8),
    ))
    registry.register("/workspace/resume-packet", lambda rp: workspace_resume_packet(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 10),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/model-profile", lambda rp: workspace_model_profile(
        rp.require('model_name'),
    ))
    registry.register("/workspace/handoff-packet", lambda rp: workspace_handoff_packet(
        rp.workspace(),
        target_model=rp.require('target_model'),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 10),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/handoff-history", lambda rp: workspace_handoff_history(
        rp.workspace(),
        target_model=rp.get("target_model", ""),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 50),
    ))
    registry.register("/workspace/continuity-dashboard", lambda rp: workspace_continuity_dashboard(
        rp.workspace(),
        intent=rp.intent(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(rp.params, "limit", 10),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/dashboard", lambda rp: workspace_dashboard(
        rp.workspace(),
        intent=rp.intent(),
        limit=_parse_int(rp.params, "limit", 10),
        view=rp.view(),
        budget=rp.budget(),
        session_id=rp.session_id(),
        task_id=rp.task_id(),
    ))
    registry.register("/workspace/workbench-summary", lambda rp: workspace_workbench_summary(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 5),
        session_id=rp.session_id(),
        task_id=rp.task_id(),
    ))
    registry.register("/workspace/quality-overview", lambda rp: workspace_quality_overview(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 10),
    ))
    registry.register("/workspace/knowledge-summary", lambda rp: workspace_knowledge_summary(
        rp.workspace(),
        scope=rp.get("scope", "kaipuyun"),
        limit=_parse_int(rp.params, "limit", 5),
    ))
    registry.register("/workspace/task-delivery-overview", lambda rp: workspace_task_delivery_overview(
        rp.workspace(), task_id=rp.task_id(), limit=_parse_int(rp.params, "limit", 20)
    ))

    # --- Task Shadow (Session-first continuity, L1) ---------------------------
    def _shadow_payload(rp: RouteParams) -> dict[str, Any]:
        try:
            parsed = json.loads(rp.get("payload", "{}") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"payload must be a JSON object: {exc}") from exc
        return parsed if isinstance(parsed, dict) else {}

    def _task_shadow_record_snapshot(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.tasks.shadow import record_shadow_snapshot

        return record_shadow_snapshot(
            rp.workspace(),
            _shadow_payload(rp),
            shadow_id=rp.get("shadow_id", ""),
        )

    registry.register("/workspace/task-shadow-record-snapshot", _task_shadow_record_snapshot)

    def _task_shadow_status(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.tasks.shadow import build_merged_shadow

        shadow = build_merged_shadow(rp.workspace(), rp.get("shadow_id", ""))
        return shadow or {"found": False, "shadow_id": rp.get("shadow_id", "")}

    registry.register("/workspace/task-shadow-status", _task_shadow_status)

    def _task_shadow_bind(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.tasks.shadow import bind_shadow_to_task

        payload = _shadow_payload(rp)
        expected = payload.get("expected_revision")
        return bind_shadow_to_task(
            rp.workspace(),
            rp.get("shadow_id", ""),
            rp.task_id(),
            expected_revision=int(expected) if expected is not None else None,
            source="http",
        )

    registry.register("/workspace/task-shadow-bind", _task_shadow_bind)

    def _task_shadow_discard(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.tasks.shadow import discard_shadow

        return discard_shadow(rp.workspace(), rp.get("shadow_id", ""), reason=rp.get("reason", "user_requested"))

    registry.register("/workspace/task-shadow-discard", _task_shadow_discard)

    def _task_shadow_promote(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.tasks.shadow import promote_shadow_to_task

        return promote_shadow_to_task(rp.workspace(), rp.get("shadow_id", ""), task_id=rp.task_id())

    registry.register("/workspace/task-shadow-promote", _task_shadow_promote)

    def _task_shadow_observation(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.tasks.shadow_observations import record_observation

        return record_observation(rp.workspace(), _shadow_payload(rp))

    registry.register("/workspace/task-shadow-observation", _task_shadow_observation)

    def _task_shadow_observation_list(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.tasks.shadow_observations import list_observations

        return list_observations(
            rp.workspace(),
            source_kind=rp.get("source_kind", ""),
            source_session_id=rp.session_id(),
            kind=rp.get("kind", ""),
            limit=_parse_int(rp.params, "limit", 50),
        )

    registry.register("/workspace/task-shadow-observation-list", _task_shadow_observation_list)

    def _task_shadow_handoff(rp: RouteParams) -> dict[str, Any]:
        from memory_center.core.tasks.shadow_handoff import (
            claim_handoff,
            close_handoff,
            create_handoff,
            get_handoff,
            list_handoffs,
            mark_handed_off,
        )

        ws = rp.workspace()
        action = rp.get("action", "get")
        handoff_id = rp.get("handoff_id", "")
        payload = _shadow_payload(rp)
        expected = payload.get("expected_revision")
        if action == "create":
            return create_handoff(
                ws,
                from_session_id=rp.session_id(),
                shadow_id=rp.get("shadow_id", ""),
                to_agent_hint=str(payload.get("to_agent_hint", "")),
            )
        if action == "hand_off":
            return mark_handed_off(ws, handoff_id, expected_revision=int(expected or 0))
        if action == "claim":
            return claim_handoff(ws, handoff_id, claimed_by_session_id=rp.session_id(), expected_revision=int(expected or 0))
        if action == "close":
            return close_handoff(ws, handoff_id, expected_revision=int(expected or 0), outcome=rp.get("outcome", "completed"))
        if action == "list":
            return list_handoffs(ws, status=rp.get("status", ""), limit=_parse_int(rp.params, "limit", 20))
        return get_handoff(ws, handoff_id)

    registry.register("/workspace/task-shadow-handoff", _task_shadow_handoff)

    registry.register("/workspace/resume-context", lambda rp: workspace_resume_context(
        rp.workspace(),
        rp.require('text'),
        limit=_parse_int(rp.params, "limit", 5),
    ))
    registry.register("/workspace/suggest-case", lambda rp: workspace_suggest_case(
        rp.workspace(),
        rp.require('session_id'),
    ))
    registry.register("/workspace/consolidation-candidates", lambda rp: workspace_list_consolidation_candidates(
        rp.workspace(),
        status=rp.get("status", "pending"),
        limit=_parse_int(rp.params, "limit", 20),
    ))
    registry.register("/workspace/case-supersede", lambda rp: supersede_case(
        rp.workspace(),
        rp.require("case_id"),
        superseded_by=rp.get("superseded_by"),
        actor=rp.get("actor"),
        note=rp.get("note"),
    ))
    registry.register("/workspace/case-reinstate", lambda rp: reinstate_case(
        rp.workspace(),
        rp.require("case_id"),
        actor=rp.get("actor"),
        note=rp.get("note"),
    ))
    registry.register("/workspace/case-decisions", lambda rp: workspace_case_decisions(
        rp.workspace(),
        case_id=rp.get("case_id"),
        limit=rp.limit(50),
    ))
    registry.register("/workspace/agent-execution-summary", lambda rp: summarize_agent_execution(
        rp.workspace(),
        limit_events=_parse_int(rp.params, "limit_events", 20_000),
        limit_sessions=_parse_int(rp.params, "limit_sessions", 20),
    ))

    # --- group-level (registry-name based) ------------------------------------
    registry.register("/group/status", lambda rp: group_status(rp.require('group')))
    registry.register("/group/query", lambda rp: group_query(
        rp.require('group'),
        rp.require('text'),
        limit=_parse_int(rp.params, "limit", 20),
    ))
    registry.register("/group/impact", lambda rp: group_impact(
        rp.require('group'),
        rp.require('target'),
        direction=rp.get("direction", "upstream"),
        max_depth=_parse_int(rp.params, "max_depth", 3),
    ))

    # --- discover / constraint / audit / drill / consistency / benchmark ------
    registry.register("/workspace/discover", lambda rp: memory_discover(
        rp.workspace(),
        limit=_parse_int(rp.params, "limit", 50),
    ))

    def _constraint(rp: RouteParams) -> dict[str, Any]:
        return constraint_action(rp.get("context", ""), rp.get("template", "coding_agent"))

    registry.register("/workspace/constraint", _constraint)

    def _audit(rp: RouteParams) -> dict[str, Any]:
        return run_audit(rp.workspace(), rp.get("work_package", ""))

    registry.register("/workspace/audit", _audit)

    def _drill_ref(rp: RouteParams) -> dict[str, Any]:
        return drill_ref(rp.workspace(), rp.require('ref_id'))

    registry.register("/workspace/drill-ref", _drill_ref)

    def _drill_timeline(rp: RouteParams) -> dict[str, Any]:
        return drill_timeline(rp.workspace(), rp.session_id(), rp.task_id(), _parse_int(rp.params, "limit", 50))

    registry.register("/workspace/drill-timeline", _drill_timeline)

    def _drill_task(rp: RouteParams) -> dict[str, Any]:
        return drill_task(rp.workspace(), rp.require('task_id'))

    registry.register("/workspace/drill-task", _drill_task)

    def _backend_consistency(rp: RouteParams) -> dict[str, Any]:
        return backend_consistency(rp.workspace())

    registry.register("/workspace/backend-consistency", _backend_consistency)

    def _benchmark_trend(rp: RouteParams) -> dict[str, Any]:
        return benchmark_trend_report(rp.workspace(), rp.get("function_name", ""))

    registry.register("/workspace/eval-token-benchmark-trend", _benchmark_trend)

    def _regression_alerts(rp: RouteParams) -> dict[str, Any]:
        return regression_alerts_action(rp.workspace())

    registry.register("/workspace/regression-alerts", _regression_alerts)

    def _quality_gates_summary(rp: RouteParams) -> dict[str, Any]:
        return quality_gates_summary(rp.workspace(), _parse_int(rp.params, "min_events", 20))

    registry.register("/workspace/quality-gates-summary", _quality_gates_summary)
