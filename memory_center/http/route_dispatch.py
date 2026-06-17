"""HTTP route dispatch for the local Memory Center bridge.

This module owns the full CommandRegistry that turns ``GET/POST`` paths into
calls on the orchestrator/artifact/audit/etc. layer.  Keeping it separate from
``server.py`` keeps the HTTP handler small and lets us unit-test the routing
table without spinning up an HTTP server.

Public surface:

- ``build_http_route_registry(params, default_workspace)`` returns a
  ``CommandRegistry`` whose handlers close over ``params`` and the default
  workspace.  The handler lambdas intentionally stay 1:1 with the legacy
  if-chain so that public path / parameter contracts in ``server.py`` and the
  Vue web client do not change.
- ``_require_workspace`` / ``_require_one`` / ``_parse_int`` are the parameter
  helpers re-used by ``server.py`` itself for things like the HTML exporters.
"""

from __future__ import annotations

import json as _json
from typing import Any, Dict

from memory_center.core.dispatch import CommandRegistry


def _require_workspace(params: dict, default_workspace: str | None) -> str:
    value = params.get("workspace", [default_workspace])[0]
    if not value:
        raise ValueError("workspace query param is required when no default workspace is configured")
    return value


def _require_one(params: dict, key: str) -> str:
    value = params.get(key, [""])[0].strip()
    if not value:
        raise ValueError(f"{key} query param is required")
    return value


def _parse_int(params: dict, key: str, default: int, min_val: int = 1, max_val: int = 10000) -> int:
    raw = params.get(key, [str(default)])[0]
    try:
        value = int(raw)
    except (ValueError, TypeError):
        raise ValueError(f"{key} must be an integer, got: {raw!r}")
    return max(min_val, min(value, max_val))


__all__ = [
    "build_http_route_registry",
    "_require_workspace",
    "_require_one",
    "_parse_int",
]


def build_http_route_registry(params: dict, default_workspace: str | None) -> CommandRegistry:
    """Return a CommandRegistry mapping HTTP path -> zero-arg handler closure.

    The handlers close over ``params`` and ``default_workspace`` so the registry
    is rebuilt per request.  This keeps each closure tiny while still giving us
    a single ``registry.dispatch(path)`` line in ``_route_request``.
    """
    # Lazy imports to keep startup time low and to mirror the legacy structure
    # where many specialized routes only loaded their dependencies on demand.
    from memory_center.core.exporters import (
        export_continuity_dashboard_html,
        export_focus_task_html,
        export_index_freshness_html,
        export_receipts_html,
        export_ref_html,
        export_memory_backend_html,
        export_timeline_html,
        export_usage_report_html,
        export_workbench_index_html,
        export_workspace_dashboard_html,
    )
    from memory_center.core.orchestrator import (
        group_chain,
        group_impact,
        group_query,
        group_status,
        memory_callers,
        memory_callees,
        memory_execute_write,
        memory_eval_write_quality,
        memory_eval_regression_suite,
        memory_eval_index_freshness,
        memory_eval_tool_adoption,
        memory_eval_context_weight,
        memory_eval_parser_benchmark,
        memory_eval_walkthrough_quality,
        memory_eval_resume,
        memory_eval_handoff,
        memory_export_walkthrough_artifact,
        memory_method_walkthrough,
        memory_backend_query,
        memory_ref_batch,
        memory_ref_get,
        memory_tool_usage_report,
        memory_walkthrough_health,
        memory_plan_change,
        memory_plan_write,
        memory_query_hybrid,
        memory_search_code,
        memory_symbol,
        memory_verify_checklist,
        memory_write_judge,
        workspace_end_session,
        workspace_handoff_packet,
        workspace_handoff_history,
        workspace_lookup_hint,
        workspace_model_profile,
        workspace_continuity_dashboard,
        workspace_dashboard,
        workspace_next_actions,
        workspace_recent_evidence,
        workspace_recent_sessions,
        workspace_record_case,
        workspace_record_close_feedback,
        workspace_resume_packet,
        workspace_resume_context,
        workspace_session_summary,
        workspace_sniff,
        workspace_start_session,
        workspace_suggest_case,
        workspace_status,
        workspace_sync_case_to_artifacts,
        workspace_sync_sniff_to_artifacts,
        workspace_unresolved_items,
        workspace_replay_write_chain,
        workspace_write_receipts,
        memory_discover,
    )
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

    registry = CommandRegistry(label="HTTP route")

    # --- workspace status / sniff / artifacts ---------------------------------
    registry.register("/workspace/status", lambda: workspace_status(
        _require_workspace(params, default_workspace),
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/sniff", lambda: workspace_sniff(
        _require_workspace(params, default_workspace),
        _require_one(params, "intent"),
        limit=_parse_int(params, "limit", 12),
        auto_sync_mode=params.get("auto_sync_mode", ["balanced"])[0],
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/artifacts", lambda: list_artifacts(
        _require_workspace(params, default_workspace),
    ))
    registry.register("/workspace/artifact", lambda: get_artifact(
        _require_workspace(params, default_workspace),
        _require_one(params, "name"),
    ))
    registry.register("/workspace/artifact/outline", lambda: artifact_outline(
        _require_workspace(params, default_workspace),
        _require_one(params, "name"),
    ))
    registry.register("/workspace/artifact/context", lambda: artifact_context(
        _require_workspace(params, default_workspace),
        _require_one(params, "intent"),
        limit=_parse_int(params, "limit", 6),
    ))
    registry.register("/workspace/artifact/update", lambda: update_artifact(
        _require_workspace(params, default_workspace),
        _require_one(params, "name"),
        _require_one(params, "content"),
    ))
    registry.register("/workspace/change-log/append", lambda: append_change_log(
        _require_workspace(params, default_workspace),
        _require_one(params, "entry"),
    ))
    registry.register("/workspace/change-log/compact", lambda: compact_change_log(
        _require_workspace(params, default_workspace),
        keep_recent=_parse_int(params, "keep_recent", 30),
    ))

    # --- task spaces ----------------------------------------------------------
    registry.register("/workspace/task-spaces", lambda: list_task_spaces(
        _require_workspace(params, default_workspace),
        include_archived=params.get("include_archived", ["false"])[0].lower() == "true",
    ))
    registry.register("/workspace/task-space/resolve", lambda: resolve_task_space(
        _require_workspace(params, default_workspace),
        intent=_require_one(params, "intent"),
        title=params.get("title", [""])[0],
        create_if_missing=params.get("create_if_missing", ["true"])[0].lower() == "true",
        include_archived=params.get("include_archived", ["false"])[0].lower() == "true",
        limit_candidates=_parse_int(params, "limit_candidates", 3),
        score_threshold=_parse_int(params, "score_threshold", 3),
    ))
    registry.register("/workspace/task-space/create", lambda: create_task_space(
        _require_workspace(params, default_workspace),
        title=params.get("title", [""])[0],
        intent=params.get("intent", [""])[0],
        owner=params.get("owner", [""])[0],
        tags=[item for item in params.get("tag", []) if item],
        priority=params.get("priority", ["medium"])[0],
    ))
    registry.register("/workspace/task-artifact", lambda: get_task_artifact(
        _require_workspace(params, default_workspace),
        _require_one(params, "task_id"),
        _require_one(params, "name"),
    ))
    registry.register("/workspace/task-artifact/update", lambda: update_task_artifact(
        _require_workspace(params, default_workspace),
        _require_one(params, "task_id"),
        _require_one(params, "name"),
        _require_one(params, "content"),
    ))
    registry.register("/workspace/task-change-log/append", lambda: append_task_change_log(
        _require_workspace(params, default_workspace),
        _require_one(params, "task_id"),
        _require_one(params, "entry"),
        keep_recent=_parse_int(params, "keep_recent", 30),
    ))
    registry.register("/workspace/task-space/archive", lambda: archive_task_space(
        _require_workspace(params, default_workspace),
        _require_one(params, "task_id"),
        reason=params.get("reason", [""])[0],
    ))
    registry.register("/workspace/task-space/status", lambda: update_task_status(
        _require_workspace(params, default_workspace),
        _require_one(params, "task_id"),
        _require_one(params, "status"),
    ))
    registry.register("/workspace/task-space/touch-activity", lambda: touch_task_activity(
        _require_workspace(params, default_workspace),
        _require_one(params, "task_id"),
        _require_one(params, "source"),
    ))
    registry.register("/workspace/task-spaces/auto-archive", lambda: auto_archive_task_spaces(
        _require_workspace(params, default_workspace),
        retention_days=_parse_int(params, "retention_days", 30),
    ))
    registry.register("/workspace/artifacts/sync-sniff", lambda: workspace_sync_sniff_to_artifacts(
        _require_workspace(params, default_workspace),
        _require_one(params, "intent"),
        limit=_parse_int(params, "limit", 12),
        task_id=params.get("task_id", [""])[0],
        title=params.get("title", [""])[0],
        auto_sync_mode=params.get("auto_sync_mode", ["balanced"])[0],
    ))
    registry.register("/workspace/artifacts/sync-case", lambda: workspace_sync_case_to_artifacts(
        _require_workspace(params, default_workspace),
        _require_one(params, "session_id"),
        task_id=params.get("task_id", [""])[0],
        title=params.get("title", [""])[0],
        auto_sync_mode=params.get("auto_sync_mode", ["balanced"])[0],
    ))

    # --- query / search / symbols / call graph --------------------------------
    registry.register("/workspace/query", lambda: memory_query_hybrid(
        _require_workspace(params, default_workspace),
        _require_one(params, "text"),
        limit=_parse_int(params, "limit", 20),
        project=params.get("project", [""])[0],
    ))
    registry.register("/workspace/search-code", lambda: memory_search_code(
        _require_workspace(params, default_workspace),
        _require_one(params, "text"),
        scope=params.get("scope", [""])[0],
        limit=_parse_int(params, "limit", 20),
        project=params.get("project", [""])[0],
    ))
    registry.register("/workspace/lookup-hint", lambda: workspace_lookup_hint(
        _require_workspace(params, default_workspace),
        query=_require_one(params, "query"),
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 8),
    ))
    registry.register("/workspace/symbol", lambda: memory_symbol(
        _require_workspace(params, default_workspace),
        _require_one(params, "name"),
        limit=_parse_int(params, "limit", 10),
        project=params.get("project", [""])[0],
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/callers", lambda: memory_callers(
        _require_workspace(params, default_workspace),
        _require_one(params, "symbol"),
        depth=_parse_int(params, "depth", 2),
        limit=_parse_int(params, "limit", 80, max_val=500),
        project=params.get("project", [""])[0],
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/callees", lambda: memory_callees(
        _require_workspace(params, default_workspace),
        _require_one(params, "symbol"),
        depth=_parse_int(params, "depth", 2),
        limit=_parse_int(params, "limit", 80, max_val=500),
        project=params.get("project", [""])[0],
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/plan-change", lambda: memory_plan_change(
        _require_workspace(params, default_workspace),
        _require_one(params, "target"),
        direction=params.get("direction", ["upstream"])[0],
        max_depth=_parse_int(params, "max_depth", 3),
    ))

    # --- method walkthrough ---------------------------------------------------
    registry.register("/workspace/method-walkthrough", lambda: memory_method_walkthrough(
        _require_workspace(params, default_workspace),
        _require_one(params, "symbol"),
        depth=_parse_int(params, "depth", 4),
        limit=_parse_int(params, "limit", 80),
        project=params.get("project", [""])[0],
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
        report_level=params.get("report_level", ["standard"])[0],
    ))
    registry.register("/workspace/walkthrough-health", lambda: memory_walkthrough_health(
        _require_workspace(params, default_workspace),
        symbol=params.get("symbol", [""])[0],
        project=params.get("project", [""])[0],
        report_level=params.get("report_level", ["standard"])[0],
    ))
    registry.register("/workspace/walkthrough-export", lambda: memory_export_walkthrough_artifact(
        _require_workspace(params, default_workspace),
        symbol=_require_one(params, "symbol"),
        project=params.get("project", [""])[0],
        report_level=params.get("report_level", ["deep"])[0],
        title=params.get("title", [""])[0],
    ))
    registry.register("/workspace/walkthrough-eval", lambda: memory_eval_walkthrough_quality(
        _require_workspace(params, default_workspace),
        symbol=_require_one(params, "symbol"),
        project=params.get("project", [""])[0],
        report_level=params.get("report_level", ["standard"])[0],
    ))

    # --- write pipeline / receipts / replay -----------------------------------
    registry.register("/workspace/memory-write-judge", lambda: memory_write_judge(
        _require_workspace(params, default_workspace),
        text=_require_one(params, "text"),
        source=params.get("source", ["note"])[0],
        intent=params.get("intent", [""])[0],
        prefer_layer=params.get("prefer_layer", [""])[0],
        projects=params.get("project", []) or None,
        files=params.get("file", []) or None,
    ))
    registry.register("/workspace/memory-plan-write", lambda: memory_plan_write(
        _require_workspace(params, default_workspace),
        text=_require_one(params, "text"),
        source=params.get("source", ["note"])[0],
        intent=params.get("intent", [""])[0],
        session_id=params.get("session_id", [""])[0],
        task_id=params.get("task_id", [""])[0],
        title=params.get("title", [""])[0],
        prefer_layer=params.get("prefer_layer", [""])[0],
        projects=params.get("project", []) or None,
        files=params.get("file", []) or None,
    ))
    registry.register("/workspace/memory-execute-write", lambda: memory_execute_write(
        _require_workspace(params, default_workspace),
        text=_require_one(params, "text"),
        source=params.get("source", ["note"])[0],
        intent=params.get("intent", [""])[0],
        session_id=params.get("session_id", [""])[0],
        task_id=params.get("task_id", [""])[0],
        title=params.get("title", [""])[0],
        prefer_layer=params.get("prefer_layer", [""])[0],
        projects=params.get("project", []) or None,
        files=params.get("file", []) or None,
    ))
    registry.register("/workspace/write-receipts", lambda: workspace_write_receipts(
        _require_workspace(params, default_workspace),
        layer=params.get("layer", [""])[0],
        action=params.get("action", [""])[0],
        scope=params.get("scope", [""])[0],
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        limit=_parse_int(params, "limit", 50),
    ))
    registry.register("/workspace/replay-write-chain", lambda: workspace_replay_write_chain(
        _require_workspace(params, default_workspace),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        limit=_parse_int(params, "limit", 100),
    ))

    # --- evaluations ----------------------------------------------------------
    registry.register("/workspace/eval-write-quality", lambda: memory_eval_write_quality(
        _require_workspace(params, default_workspace),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 100),
    ))
    registry.register("/workspace/eval-resume", lambda: memory_eval_resume(
        _require_workspace(params, default_workspace),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 20),
    ))
    registry.register("/workspace/eval-handoff", lambda: memory_eval_handoff(
        _require_workspace(params, default_workspace),
        target_model=_require_one(params, "target_model"),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 20),
    ))
    registry.register("/workspace/eval-regression-suite", lambda: memory_eval_regression_suite(
        _require_workspace(params, default_workspace),
        target_model=params.get("target_model", ["codex"])[0],
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 20),
    ))
    registry.register("/workspace/eval-index-freshness", lambda: memory_eval_index_freshness(
        _require_workspace(params, default_workspace),
        scope=params.get("scope", ["all"])[0],
    ))
    registry.register("/workspace/eval-tool-adoption", lambda: memory_eval_tool_adoption(
        _require_workspace(params, default_workspace),
        limit=_parse_int(params, "limit", 200),
    ))
    registry.register("/workspace/eval-context-weight", lambda: memory_eval_context_weight(
        _require_workspace(params, default_workspace),
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 8),
    ))
    registry.register("/workspace/eval-parser-benchmark", lambda: memory_eval_parser_benchmark(
        _require_workspace(params, default_workspace),
        limit=_parse_int(params, "limit", 200),
        max_findings=_parse_int(params, "max_findings", 20),
    ))

    # --- tooling / refs / backend / verify ------------------------------------
    registry.register("/workspace/tool-usage-report", lambda: memory_tool_usage_report(
        _require_workspace(params, default_workspace),
        limit=_parse_int(params, "limit", 200),
    ))
    registry.register("/workspace/ref-get", lambda: memory_ref_get(
        _require_workspace(params, default_workspace),
        ref_id=_require_one(params, "ref_id"),
    ))
    registry.register("/workspace/ref-batch", lambda: memory_ref_batch(
        _require_workspace(params, default_workspace),
        ref_ids=[item for item in params.get("ref_id", []) if item],
    ))
    registry.register("/workspace/memory-backend-query", lambda: memory_backend_query(
        _require_workspace(params, default_workspace),
        collection=params.get("collection", [""])[0],
        record_id=params.get("record_id", [""])[0],
        created_after=params.get("created_after", [""])[0],
        ref_path=params.get("ref_path", [""])[0],
        project=params.get("project", [""])[0],
        payload_type=params.get("payload_type", [""])[0],
        limit=_parse_int(params, "limit", 50),
    ))
    registry.register("/workspace/verify-checklist", lambda: memory_verify_checklist(
        _require_workspace(params, default_workspace),
        _require_one(params, "target"),
    ))

    # --- sessions / recent / evidence -----------------------------------------
    registry.register("/workspace/sessions/recent", lambda: workspace_recent_sessions(
        _require_workspace(params, default_workspace),
        limit=_parse_int(params, "limit", 10),
    ))
    registry.register("/workspace/session/summary", lambda: workspace_session_summary(
        _require_workspace(params, default_workspace),
        _require_one(params, "session_id"),
    ))
    registry.register("/workspace/recent-evidence", lambda: workspace_recent_evidence(
        _require_workspace(params, default_workspace),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        limit=_parse_int(params, "limit", 10),
        budget=params.get("budget", ["medium"])[0],
        view=params.get("view", ["compact"])[0],
    ))

    # --- workflow facades (compound work-* routes) ----------------------------
    def _work_start() -> Dict[str, Any]:
        ws = _require_workspace(params, default_workspace)
        intent = _require_one(params, "intent")
        limit = _parse_int(params, "limit", 8)
        auto_sync_mode = params.get("auto_sync_mode", ["balanced"])[0]
        budget = params.get("budget", ["medium"])[0]
        sniff_result = workspace_sniff(ws, intent, limit=limit, auto_sync_mode=auto_sync_mode, view="compact", budget=budget)
        synced = None
        resolved_task = sniff_result.get("resolved_task", {}) or {}
        auto_sync = sniff_result.get("auto_sync_recommendation", {}) or {}
        if params.get("sync_task_space", ["true"])[0].lower() == "true" and (auto_sync.get("recommended") or resolved_task.get("task_id")):
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

    def _work_sync() -> Dict[str, Any]:
        ws = _require_workspace(params, default_workspace)
        session_id = params.get("session_id", [""])[0]
        task_id = params.get("task_id", [""])[0]
        title = params.get("title", [""])[0]
        auto_sync_mode = params.get("auto_sync_mode", ["balanced"])[0]
        if session_id:
            return {
                "workflow": "work-sync",
                "mode": "case",
                "result": workspace_sync_case_to_artifacts(ws, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode),
            }
        intent = _require_one(params, "intent")
        return {
            "workflow": "work-sync",
            "mode": "sniff",
            "result": workspace_sync_sniff_to_artifacts(ws, intent, limit=_parse_int(params, "limit", 8), task_id=task_id, title=title, auto_sync_mode=auto_sync_mode),
        }

    def _work_resume() -> Dict[str, Any]:
        ws = _require_workspace(params, default_workspace)
        task_id = params.get("task_id", [""])[0]
        session_id = params.get("session_id", [""])[0]
        intent = params.get("intent", [""])[0]
        limit = _parse_int(params, "limit", 8)
        budget = params.get("budget", ["medium"])[0]
        return {
            "workflow": "work-resume",
            "resume_packet": workspace_resume_packet(ws, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "next_actions": workspace_next_actions(ws, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "unresolved_items": workspace_unresolved_items(ws, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "recent_evidence": workspace_recent_evidence(ws, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
        }

    def _work_handoff() -> Dict[str, Any]:
        ws = _require_workspace(params, default_workspace)
        target_model = _require_one(params, "target_model")
        task_id = params.get("task_id", [""])[0]
        session_id = params.get("session_id", [""])[0]
        intent = params.get("intent", [""])[0]
        limit = _parse_int(params, "limit", 8)
        budget = params.get("budget", ["medium"])[0]
        return {
            "workflow": "work-handoff",
            "handoff_packet": workspace_handoff_packet(ws, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "recent_evidence": workspace_recent_evidence(ws, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget, view="compact"),
            "tool_usage_report": memory_tool_usage_report(ws, limit=50),
        }

    def _work_close() -> Dict[str, Any]:
        ws = _require_workspace(params, default_workspace)
        session_id = _require_one(params, "session_id")
        outcome = params.get("outcome", [""])[0]
        task_id = params.get("task_id", [""])[0]
        title = params.get("title", [""])[0]
        auto_sync_mode = params.get("auto_sync_mode", ["balanced"])[0]
        record_case = params.get("record_case", ["true"])[0].lower() == "true"
        ended = workspace_end_session(ws, session_id, outcome=outcome, verified_by=params.get("verified_by", []) or None)
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
                verified_by=case.get("verified_by", []) or params.get("verified_by", []) or None,
                source_session_id=session_id,
                source_task_id=task_id,
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

    def _work_health() -> Dict[str, Any]:
        ws = _require_workspace(params, default_workspace)
        intent = params.get("intent", ["Memory Center work health"])[0]
        target_model = params.get("target_model", ["codex"])[0]
        limit = _parse_int(params, "limit", 5)
        return {
            "workflow": "work-health",
            "status": workspace_status(ws, view="compact", budget="medium"),
            "tool_usage_report": memory_tool_usage_report(ws, limit=50),
            "regression_suite": memory_eval_regression_suite(ws, intent=intent, target_model=target_model, limit=limit),
        }

    registry.register("/workspace/work-start", _work_start)
    registry.register("/workspace/work-sync", _work_sync)
    registry.register("/workspace/work-resume", _work_resume)
    registry.register("/workspace/work-handoff", _work_handoff)
    registry.register("/workspace/work-close", _work_close)
    registry.register("/workspace/work-health", _work_health)

    registry.register("/workspace/unresolved-items", lambda: workspace_unresolved_items(
        _require_workspace(params, default_workspace),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 10),
    ))
    registry.register("/workspace/next-actions", lambda: workspace_next_actions(
        _require_workspace(params, default_workspace),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 8),
    ))
    registry.register("/workspace/resume-packet", lambda: workspace_resume_packet(
        _require_workspace(params, default_workspace),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 10),
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/model-profile", lambda: workspace_model_profile(
        _require_one(params, "model_name"),
    ))
    registry.register("/workspace/handoff-packet", lambda: workspace_handoff_packet(
        _require_workspace(params, default_workspace),
        target_model=_require_one(params, "target_model"),
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 10),
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/handoff-history", lambda: workspace_handoff_history(
        _require_workspace(params, default_workspace),
        target_model=params.get("target_model", [""])[0],
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        limit=_parse_int(params, "limit", 50),
    ))
    registry.register("/workspace/continuity-dashboard", lambda: workspace_continuity_dashboard(
        _require_workspace(params, default_workspace),
        intent=params.get("intent", [""])[0],
        task_id=params.get("task_id", [""])[0],
        session_id=params.get("session_id", [""])[0],
        limit=_parse_int(params, "limit", 10),
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/dashboard", lambda: workspace_dashboard(
        _require_workspace(params, default_workspace),
        intent=params.get("intent", [""])[0],
        limit=_parse_int(params, "limit", 10),
        view=params.get("view", ["compact"])[0],
        budget=params.get("budget", ["medium"])[0],
    ))
    registry.register("/workspace/resume-context", lambda: workspace_resume_context(
        _require_workspace(params, default_workspace),
        _require_one(params, "text"),
        limit=_parse_int(params, "limit", 5),
    ))
    registry.register("/workspace/suggest-case", lambda: workspace_suggest_case(
        _require_workspace(params, default_workspace),
        _require_one(params, "session_id"),
    ))

    # --- group-level (registry-name based) ------------------------------------
    registry.register("/group/status", lambda: group_status(_require_one(params, "group")))
    registry.register("/group/query", lambda: group_query(
        _require_one(params, "group"),
        _require_one(params, "text"),
        limit=_parse_int(params, "limit", 20),
    ))
    registry.register("/group/impact", lambda: group_impact(
        _require_one(params, "group"),
        _require_one(params, "target"),
        direction=params.get("direction", ["upstream"])[0],
        max_depth=_parse_int(params, "max_depth", 3),
    ))

    # --- discover / constraint / audit / drill / consistency / benchmark ------
    registry.register("/workspace/discover", lambda: memory_discover(
        _require_workspace(params, default_workspace),
        limit=_parse_int(params, "limit", 50),
    ))

    def _constraint() -> Dict[str, Any]:
        from memory_center.core.templates import get_constraint_template, auto_select_action
        template = params.get("template", ["coding_agent"])[0]
        context = params.get("context", [""])[0]
        if context:
            return {"context": context, "template": template, "recommended_action": auto_select_action(context, template)}
        tmpl = get_constraint_template(template)
        return tmpl or {"error": f"Unknown template: {template}"}

    registry.register("/workspace/constraint", _constraint)

    def _audit() -> Dict[str, Any]:
        from memory_center.core.audit.completion import run_completion_audit
        return run_completion_audit(
            _require_workspace(params, default_workspace),
            work_package=params.get("work_package", [""])[0],
        )

    registry.register("/workspace/audit", _audit)

    def _drill_ref() -> Dict[str, Any]:
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        ws = _require_workspace(params, default_workspace)
        ref_id = _require_one(params, "ref_id")
        with DrillDownNavigator(ws) as nav:
            return nav.expand_ref(ref_id)

    registry.register("/workspace/drill-ref", _drill_ref)

    def _drill_timeline() -> Dict[str, Any]:
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        ws = _require_workspace(params, default_workspace)
        with DrillDownNavigator(ws) as nav:
            return nav.drill_timeline(
                session_id=params.get("session_id", [""])[0],
                task_id=params.get("task_id", [""])[0],
                limit=_parse_int(params, "limit", 50),
            )

    registry.register("/workspace/drill-timeline", _drill_timeline)

    def _drill_task() -> Dict[str, Any]:
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        ws = _require_workspace(params, default_workspace)
        task_id = _require_one(params, "task_id")
        with DrillDownNavigator(ws) as nav:
            return nav.drill_task(task_id)

    registry.register("/workspace/drill-task", _drill_task)

    def _backend_consistency() -> Dict[str, Any]:
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.backend.query import UnifiedBackendQuery
        ws = _require_workspace(params, default_workspace)
        store = WorkspaceStore(ws)
        with UnifiedBackendQuery(store.memory_db_path) as backend:
            return backend.check_consistency(store.base_dir)

    registry.register("/workspace/backend-consistency", _backend_consistency)

    def _benchmark_trend() -> Dict[str, Any]:
        from memory_center.core.benchmark.trending import generate_benchmark_report
        return generate_benchmark_report(
            _require_workspace(params, default_workspace),
            function_name=params.get("function_name", [""])[0],
        )

    registry.register("/workspace/eval-token-benchmark-trend", _benchmark_trend)

    def _regression_alerts() -> Dict[str, Any]:
        from memory_center.core.benchmark.trending import check_regression_alerts
        return check_regression_alerts(
            _require_workspace(params, default_workspace),
            threshold_pct=float(params.get("threshold_pct", ["10.0"])[0]),
        )

    registry.register("/workspace/regression-alerts", _regression_alerts)

    # --- next-phase verification / explanation / business flow ----------------
    def _verification_loop() -> Dict[str, Any]:
        from memory_center.core.verification.loop import VerificationLoop
        ws = _require_workspace(params, default_workspace)
        vl = VerificationLoop(ws)
        task_type = params.get("task_type", ["general"])[0]
        task_id = params.get("task_id", ["default"])[0]
        analysis = {"task_type": task_type, "workspace": ws}
        return {
            "checklist": vl.generate_checklist(analysis),
            "status": vl.get_status(task_id),
        }

    registry.register("/workspace/verification-loop", _verification_loop)

    def _pattern_promotion() -> Dict[str, Any]:
        from memory_center.core.verification.pattern_promotion import PatternPromotion
        ws = _require_workspace(params, default_workspace)
        pp = PatternPromotion(ws)
        action_type = params.get("action", ["list"])[0]
        if action_type == "list":
            return {"proposals": pp.list_proposals()}
        if action_type == "propose":
            return pp.propose({"rule_text": _require_one(params, "text"), "source": "http"})
        if action_type == "promote":
            return pp.promote(_require_one(params, "text"))
        return {"error": f"Unknown action: {action_type}"}

    registry.register("/workspace/pattern-promotion", _pattern_promotion)

    def _heuristics() -> Dict[str, Any]:
        from memory_center.core.verification.heuristics import HeuristicsRegister
        ws = _require_workspace(params, default_workspace)
        hr = HeuristicsRegister(ws)
        action_type = params.get("action", ["query"])[0]
        if action_type == "query":
            return {"heuristics": hr.query(params.get("text", [""])[0])}
        if action_type in {"record", "feedback", "explain"}:
            try:
                data = _json.loads(_require_one(params, "text"))
            except Exception:
                data = {"pattern": _require_one(params, "text")}
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

    def _workflow_profile() -> Dict[str, Any]:
        from memory_center.core.verification.workflow_profiles import get_workflow_profile
        return get_workflow_profile(params.get("profile", ["quick-fix"])[0])

    registry.register("/workspace/workflow-profile", _workflow_profile)

    def _workflow_recommend() -> Dict[str, Any]:
        from memory_center.core.verification.workflow_profiles import recommend_workflow_with_learning
        ws = _require_workspace(params, default_workspace)
        return recommend_workflow_with_learning(ws, _require_one(params, "description"))

    registry.register("/workspace/workflow-recommend", _workflow_recommend)

    def _bundle_export() -> Dict[str, Any]:
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        ws = _require_workspace(params, default_workspace)
        return generate_agent_bundle(ws, agent=params.get("agent", ["codex"])[0])

    registry.register("/workspace/bundle-export", _bundle_export)

    def _runtime_audit() -> Dict[str, Any]:
        from memory_center.core.audit.runtime import audit_agent_runtime
        return audit_agent_runtime(_require_workspace(params, default_workspace))

    registry.register("/workspace/runtime-audit", _runtime_audit)

    def _explanation() -> Dict[str, Any]:
        from memory_center.core.explanation.schema import Explanation
        text = _require_one(params, "text")
        persona = params.get("persona", ["developer"])[0]
        exp = Explanation(subject="explanation", summary=text, persona=persona)
        return exp.adapt_for_persona(persona).to_full()

    registry.register("/workspace/explanation", _explanation)

    def _business_flow() -> Dict[str, Any]:
        from memory_center.core.domain.flow import extract_business_flows_for_workspace
        ws = _require_workspace(params, default_workspace)
        return extract_business_flows_for_workspace(
            ws,
            _require_one(params, "seed"),
            max_depth=_parse_int(params, "max_depth", 4),
        )

    registry.register("/workspace/business-flow", _business_flow)

    def _business_flow_impact() -> Dict[str, Any]:
        from memory_center.core.domain.flow import business_flow_impact_for_workspace
        ws = _require_workspace(params, default_workspace)
        return business_flow_impact_for_workspace(
            ws,
            _require_one(params, "node_id"),
            max_depth=_parse_int(params, "max_depth", 3),
        )

    registry.register("/workspace/business-flow-impact", _business_flow_impact)

    def _metrics_summary() -> Dict[str, Any]:
        from memory_center.core.metrics import MetricsCollector
        return MetricsCollector().summary()

    registry.register("/workspace/metrics-summary", _metrics_summary)

    def _onboard() -> Dict[str, Any]:
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
        ws = _require_workspace(params, default_workspace)
        persona = params.get("persona", ["developer"])[0]
        workspace_store = WorkspaceStore(ws)
        unified = UnifiedStore(workspace_store.graph_db_path)
        try:
            gen = ArchitectureTourGenerator(unified)
            tour = gen.generate_tour(persona=persona)
            return {"tour": tour.to_dict()}
        finally:
            unified.close()

    registry.register("/workspace/onboard", _onboard)

    def _context_pack() -> Dict[str, Any]:
        from memory_center.core.context.pack import ContextPackBuilder
        ws = _require_workspace(params, default_workspace)
        builder = ContextPackBuilder(ws)
        query = _require_one(params, "query")
        intent = params.get("intent", [""])[0]
        budget_tokens = _parse_int(params, "budget_tokens", 8000)
        limit = _parse_int(params, "limit", 10)
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

    def _freshness() -> Dict[str, Any]:
        from memory_center.core.freshness.status import IndexFreshnessService
        ws = _require_workspace(params, default_workspace)
        return IndexFreshnessService(ws).banner()

    registry.register("/workspace/freshness", _freshness)

    # --- workspace-anchored group helpers (load_registry from workspace) ------
    def _workspace_group_status() -> Dict[str, Any]:
        from memory_center.core.registry import load_registry
        ws = _require_workspace(params, default_workspace)
        return group_status(load_registry(ws))

    registry.register("/workspace/group-status", _workspace_group_status)

    def _workspace_group_query() -> Dict[str, Any]:
        from memory_center.core.registry import load_registry
        ws = _require_workspace(params, default_workspace)
        return group_query(
            load_registry(ws),
            query=_require_one(params, "query"),
            limit=_parse_int(params, "limit", 20),
        )

    registry.register("/workspace/group-query", _workspace_group_query)

    def _workspace_group_impact() -> Dict[str, Any]:
        from memory_center.core.registry import load_registry
        ws = _require_workspace(params, default_workspace)
        return group_impact(load_registry(ws), target=_require_one(params, "target"))

    registry.register("/workspace/group-impact", _workspace_group_impact)

    def _workspace_group_chain() -> Dict[str, Any]:
        from memory_center.core.registry import load_registry
        ws = _require_workspace(params, default_workspace)
        return group_chain(load_registry(ws), symbol=_require_one(params, "symbol"))

    registry.register("/workspace/group-chain", _workspace_group_chain)

    return registry
