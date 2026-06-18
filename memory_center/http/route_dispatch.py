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
    "RouteParams",
]


class RouteParams:
    """Thin adapter around the parsed query string ``params`` dict.

    Routes share many optional fields (``view``, ``budget``, ``task_id``,
    ``session_id``, ``intent``, ``project``, ``auto_sync_mode``,
    ``report_level``, ``limit``).  ``RouteParams`` keeps the public path/param
    contract identical while letting handlers say ``rp.view()`` instead of
    ``rp.view()``.  This collapses the most common
    duplication without inventing a heavyweight schema layer.
    """

    __slots__ = ("params", "default_workspace")

    def __init__(self, params: dict, default_workspace: str | None) -> None:
        self.params = params
        self.default_workspace = default_workspace

    # --- required -----------------------------------------------------------
    def workspace(self) -> str:
        return _require_workspace(self.params, self.default_workspace)

    def require(self, key: str) -> str:
        return _require_one(self.params, key)

    # --- optional strings ---------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        return self.params.get(key, [default])[0]

    def task_id(self) -> str:
        return self.get("task_id", "")

    def session_id(self) -> str:
        return self.get("session_id", "")

    def intent(self) -> str:
        return self.get("intent", "")

    def project(self) -> str:
        return self.get("project", "")

    def title(self) -> str:
        return self.get("title", "")

    def view(self, default: str = "compact") -> str:
        return self.get("view", default)

    def budget(self, default: str = "medium") -> str:
        return self.get("budget", default)

    def auto_sync_mode(self, default: str = "balanced") -> str:
        return self.get("auto_sync_mode", default)

    def report_level(self, default: str = "standard") -> str:
        return self.get("report_level", default)

    def target_model(self, default: str = "codex") -> str:
        return self.get("target_model", default)

    # --- optional ints / lists ---------------------------------------------
    def limit(self, default: int = 20, *, max_val: int = 10000) -> int:
        return _parse_int(self.params, "limit", default, max_val=max_val)

    def int_param(self, key: str, default: int, *, min_val: int = 1, max_val: int = 10000) -> int:
        return _parse_int(self.params, key, default, min_val=min_val, max_val=max_val)

    def list_param(self, key: str) -> list[str]:
        return [item for item in self.params.get(key, []) if item]

    def bool_param(self, key: str, default: bool = False) -> bool:
        raw = self.params.get(key, [str(default).lower()])[0]
        return str(raw).strip().lower() == "true"

    # --- composites ---------------------------------------------------------
    def view_budget(self) -> dict:
        return {"view": self.view(), "budget": self.budget()}

    def task_session(self) -> dict:
        return {"task_id": self.task_id(), "session_id": self.session_id()}

    def task_session_intent(self) -> dict:
        out = self.task_session()
        out["intent"] = self.intent()
        return out


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
    rp = RouteParams(params, default_workspace)

    # --- workspace status / sniff / artifacts ---------------------------------
    registry.register("/workspace/status", lambda: workspace_status(
        rp.workspace(),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/sniff", lambda: workspace_sniff(
        rp.workspace(),
        rp.require('intent'),
        limit=_parse_int(params, "limit", 12),
        auto_sync_mode=rp.auto_sync_mode(),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/artifacts", lambda: list_artifacts(
        rp.workspace(),
    ))
    registry.register("/workspace/artifact", lambda: get_artifact(
        rp.workspace(),
        rp.require('name'),
    ))
    registry.register("/workspace/artifact/outline", lambda: artifact_outline(
        rp.workspace(),
        rp.require('name'),
    ))
    registry.register("/workspace/artifact/context", lambda: artifact_context(
        rp.workspace(),
        rp.require('intent'),
        limit=_parse_int(params, "limit", 6),
    ))
    registry.register("/workspace/artifact/update", lambda: update_artifact(
        rp.workspace(),
        rp.require('name'),
        rp.require('content'),
    ))
    registry.register("/workspace/change-log/append", lambda: append_change_log(
        rp.workspace(),
        rp.require('entry'),
    ))
    registry.register("/workspace/change-log/compact", lambda: compact_change_log(
        rp.workspace(),
        keep_recent=_parse_int(params, "keep_recent", 30),
    ))

    # --- task spaces ----------------------------------------------------------
    registry.register("/workspace/task-spaces", lambda: list_task_spaces(
        rp.workspace(),
        include_archived=rp.bool_param("include_archived"),
    ))
    registry.register("/workspace/task-space/resolve", lambda: resolve_task_space(
        rp.workspace(),
        intent=rp.require('intent'),
        title=rp.title(),
        create_if_missing=rp.bool_param("create_if_missing", True),
        include_archived=rp.bool_param("include_archived"),
        limit_candidates=_parse_int(params, "limit_candidates", 3),
        score_threshold=_parse_int(params, "score_threshold", 3),
    ))
    registry.register("/workspace/task-space/create", lambda: create_task_space(
        rp.workspace(),
        title=rp.title(),
        intent=rp.intent(),
        owner=rp.get("owner", ""),
        tags=rp.list_param("tag"),
        priority=rp.get("priority", "medium"),
    ))
    registry.register("/workspace/task-artifact", lambda: get_task_artifact(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('name'),
    ))
    registry.register("/workspace/task-artifact/update", lambda: update_task_artifact(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('name'),
        rp.require('content'),
    ))
    registry.register("/workspace/task-change-log/append", lambda: append_task_change_log(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('entry'),
        keep_recent=_parse_int(params, "keep_recent", 30),
    ))
    registry.register("/workspace/task-space/archive", lambda: archive_task_space(
        rp.workspace(),
        rp.require('task_id'),
        reason=rp.get("reason", ""),
    ))
    registry.register("/workspace/task-space/status", lambda: update_task_status(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('status'),
    ))
    registry.register("/workspace/task-space/touch-activity", lambda: touch_task_activity(
        rp.workspace(),
        rp.require('task_id'),
        rp.require('source'),
    ))
    registry.register("/workspace/task-spaces/auto-archive", lambda: auto_archive_task_spaces(
        rp.workspace(),
        retention_days=_parse_int(params, "retention_days", 30),
    ))
    registry.register("/workspace/artifacts/sync-sniff", lambda: workspace_sync_sniff_to_artifacts(
        rp.workspace(),
        rp.require('intent'),
        limit=_parse_int(params, "limit", 12),
        task_id=rp.task_id(),
        title=rp.title(),
        auto_sync_mode=rp.auto_sync_mode(),
    ))
    registry.register("/workspace/artifacts/sync-case", lambda: workspace_sync_case_to_artifacts(
        rp.workspace(),
        rp.require('session_id'),
        task_id=rp.task_id(),
        title=rp.title(),
        auto_sync_mode=rp.auto_sync_mode(),
    ))

    # --- query / search / symbols / call graph --------------------------------
    registry.register("/workspace/query", lambda: memory_query_hybrid(
        rp.workspace(),
        rp.require('text'),
        limit=_parse_int(params, "limit", 20),
        project=rp.project(),
    ))
    registry.register("/workspace/search-code", lambda: memory_search_code(
        rp.workspace(),
        rp.require('text'),
        scope=rp.get("scope", ""),
        limit=_parse_int(params, "limit", 20),
        project=rp.project(),
    ))
    registry.register("/workspace/lookup-hint", lambda: workspace_lookup_hint(
        rp.workspace(),
        query=rp.require('query'),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 8),
    ))
    registry.register("/workspace/symbol", lambda: memory_symbol(
        rp.workspace(),
        rp.require('name'),
        limit=_parse_int(params, "limit", 10),
        project=rp.project(),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/callers", lambda: memory_callers(
        rp.workspace(),
        rp.require('symbol'),
        depth=_parse_int(params, "depth", 2),
        limit=_parse_int(params, "limit", 80, max_val=500),
        project=rp.project(),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/callees", lambda: memory_callees(
        rp.workspace(),
        rp.require('symbol'),
        depth=_parse_int(params, "depth", 2),
        limit=_parse_int(params, "limit", 80, max_val=500),
        project=rp.project(),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/plan-change", lambda: memory_plan_change(
        rp.workspace(),
        rp.require('target'),
        direction=rp.get("direction", "upstream"),
        max_depth=_parse_int(params, "max_depth", 3),
    ))

    # --- method walkthrough ---------------------------------------------------
    registry.register("/workspace/method-walkthrough", lambda: memory_method_walkthrough(
        rp.workspace(),
        rp.require('symbol'),
        depth=_parse_int(params, "depth", 4),
        limit=_parse_int(params, "limit", 80),
        project=rp.project(),
        view=rp.view(),
        budget=rp.budget(),
        report_level=rp.report_level(),
    ))
    registry.register("/workspace/walkthrough-health", lambda: memory_walkthrough_health(
        rp.workspace(),
        symbol=rp.get("symbol", ""),
        project=rp.project(),
        report_level=rp.report_level(),
    ))
    registry.register("/workspace/walkthrough-export", lambda: memory_export_walkthrough_artifact(
        rp.workspace(),
        symbol=rp.require('symbol'),
        project=rp.project(),
        report_level=rp.report_level("deep"),
        title=rp.title(),
    ))
    registry.register("/workspace/walkthrough-eval", lambda: memory_eval_walkthrough_quality(
        rp.workspace(),
        symbol=rp.require('symbol'),
        project=rp.project(),
        report_level=rp.report_level(),
    ))

    # --- write pipeline / receipts / replay -----------------------------------
    registry.register("/workspace/memory-write-judge", lambda: memory_write_judge(
        rp.workspace(),
        text=rp.require('text'),
        source=rp.get("source", "note"),
        intent=rp.intent(),
        prefer_layer=rp.get("prefer_layer", ""),
        projects=rp.list_param("project") or None,
        files=rp.list_param("file") or None,
    ))
    registry.register("/workspace/memory-plan-write", lambda: memory_plan_write(
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
    registry.register("/workspace/memory-execute-write", lambda: memory_execute_write(
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
    registry.register("/workspace/write-receipts", lambda: workspace_write_receipts(
        rp.workspace(),
        layer=rp.get("layer", ""),
        action=rp.get("action", ""),
        scope=rp.get("scope", ""),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(params, "limit", 50),
    ))
    registry.register("/workspace/replay-write-chain", lambda: workspace_replay_write_chain(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(params, "limit", 100),
    ))

    # --- evaluations ----------------------------------------------------------
    registry.register("/workspace/eval-write-quality", lambda: memory_eval_write_quality(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 100),
    ))
    registry.register("/workspace/eval-resume", lambda: memory_eval_resume(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 20),
    ))
    registry.register("/workspace/eval-handoff", lambda: memory_eval_handoff(
        rp.workspace(),
        target_model=rp.require('target_model'),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 20),
    ))
    registry.register("/workspace/eval-regression-suite", lambda: memory_eval_regression_suite(
        rp.workspace(),
        target_model=rp.target_model(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 20),
    ))
    registry.register("/workspace/eval-index-freshness", lambda: memory_eval_index_freshness(
        rp.workspace(),
        scope=rp.get("scope", "all"),
    ))
    registry.register("/workspace/eval-tool-adoption", lambda: memory_eval_tool_adoption(
        rp.workspace(),
        limit=_parse_int(params, "limit", 200),
    ))
    registry.register("/workspace/eval-context-weight", lambda: memory_eval_context_weight(
        rp.workspace(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 8),
    ))
    registry.register("/workspace/eval-parser-benchmark", lambda: memory_eval_parser_benchmark(
        rp.workspace(),
        limit=_parse_int(params, "limit", 200),
        max_findings=_parse_int(params, "max_findings", 20),
    ))

    # --- tooling / refs / backend / verify ------------------------------------
    registry.register("/workspace/tool-usage-report", lambda: memory_tool_usage_report(
        rp.workspace(),
        limit=_parse_int(params, "limit", 200),
    ))
    registry.register("/workspace/ref-get", lambda: memory_ref_get(
        rp.workspace(),
        ref_id=rp.require('ref_id'),
    ))
    registry.register("/workspace/ref-batch", lambda: memory_ref_batch(
        rp.workspace(),
        ref_ids=rp.list_param("ref_id"),
    ))
    registry.register("/workspace/memory-backend-query", lambda: memory_backend_query(
        rp.workspace(),
        collection=rp.get("collection", ""),
        record_id=rp.get("record_id", ""),
        created_after=rp.get("created_after", ""),
        ref_path=rp.get("ref_path", ""),
        project=rp.project(),
        payload_type=rp.get("payload_type", ""),
        limit=_parse_int(params, "limit", 50),
    ))
    registry.register("/workspace/verify-checklist", lambda: memory_verify_checklist(
        rp.workspace(),
        rp.require('target'),
    ))

    # --- sessions / recent / evidence -----------------------------------------
    registry.register("/workspace/sessions/recent", lambda: workspace_recent_sessions(
        rp.workspace(),
        limit=_parse_int(params, "limit", 10),
    ))
    registry.register("/workspace/session/summary", lambda: workspace_session_summary(
        rp.workspace(),
        rp.require('session_id'),
    ))
    registry.register("/workspace/recent-evidence", lambda: workspace_recent_evidence(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(params, "limit", 10),
        budget=rp.budget(),
        view=rp.view(),
    ))

    # --- workflow facades (compound work-* routes) ----------------------------
    def _work_start() -> Dict[str, Any]:
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

    def _work_sync() -> Dict[str, Any]:
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
            "result": workspace_sync_sniff_to_artifacts(ws, intent, limit=_parse_int(params, "limit", 8), task_id=task_id, title=title, auto_sync_mode=auto_sync_mode),
        }

    def _work_resume() -> Dict[str, Any]:
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

    def _work_handoff() -> Dict[str, Any]:
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

    def _work_close() -> Dict[str, Any]:
        ws = rp.workspace()
        session_id = rp.require('session_id')
        outcome = rp.get("outcome", "")
        task_id = rp.task_id()
        title = rp.title()
        auto_sync_mode = rp.auto_sync_mode()
        record_case = rp.bool_param("record_case", True)
        ended = workspace_end_session(ws, session_id, outcome=outcome, verified_by=rp.list_param("verified_by") or None)
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
    registry.register("/workspace/work-handoff", _work_handoff)
    registry.register("/workspace/work-close", _work_close)
    registry.register("/workspace/work-health", _work_health)

    registry.register("/workspace/unresolved-items", lambda: workspace_unresolved_items(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 10),
    ))
    registry.register("/workspace/next-actions", lambda: workspace_next_actions(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 8),
    ))
    registry.register("/workspace/resume-packet", lambda: workspace_resume_packet(
        rp.workspace(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 10),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/model-profile", lambda: workspace_model_profile(
        rp.require('model_name'),
    ))
    registry.register("/workspace/handoff-packet", lambda: workspace_handoff_packet(
        rp.workspace(),
        target_model=rp.require('target_model'),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 10),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/handoff-history", lambda: workspace_handoff_history(
        rp.workspace(),
        target_model=rp.get("target_model", ""),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(params, "limit", 50),
    ))
    registry.register("/workspace/continuity-dashboard", lambda: workspace_continuity_dashboard(
        rp.workspace(),
        intent=rp.intent(),
        task_id=rp.task_id(),
        session_id=rp.session_id(),
        limit=_parse_int(params, "limit", 10),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/dashboard", lambda: workspace_dashboard(
        rp.workspace(),
        intent=rp.intent(),
        limit=_parse_int(params, "limit", 10),
        view=rp.view(),
        budget=rp.budget(),
    ))
    registry.register("/workspace/resume-context", lambda: workspace_resume_context(
        rp.workspace(),
        rp.require('text'),
        limit=_parse_int(params, "limit", 5),
    ))
    registry.register("/workspace/suggest-case", lambda: workspace_suggest_case(
        rp.workspace(),
        rp.require('session_id'),
    ))

    # --- group-level (registry-name based) ------------------------------------
    registry.register("/group/status", lambda: group_status(rp.require('group')))
    registry.register("/group/query", lambda: group_query(
        rp.require('group'),
        rp.require('text'),
        limit=_parse_int(params, "limit", 20),
    ))
    registry.register("/group/impact", lambda: group_impact(
        rp.require('group'),
        rp.require('target'),
        direction=rp.get("direction", "upstream"),
        max_depth=_parse_int(params, "max_depth", 3),
    ))

    # --- discover / constraint / audit / drill / consistency / benchmark ------
    registry.register("/workspace/discover", lambda: memory_discover(
        rp.workspace(),
        limit=_parse_int(params, "limit", 50),
    ))

    def _constraint() -> Dict[str, Any]:
        from memory_center.core.templates import get_constraint_template, auto_select_action
        template = rp.get("template", "coding_agent")
        context = rp.get("context", "")
        if context:
            return {"context": context, "template": template, "recommended_action": auto_select_action(context, template)}
        tmpl = get_constraint_template(template)
        return tmpl or {"error": f"Unknown template: {template}"}

    registry.register("/workspace/constraint", _constraint)

    def _audit() -> Dict[str, Any]:
        from memory_center.core.audit.completion import run_completion_audit
        return run_completion_audit(
            rp.workspace(),
            work_package=rp.get("work_package", ""),
        )

    registry.register("/workspace/audit", _audit)

    def _drill_ref() -> Dict[str, Any]:
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        ws = rp.workspace()
        ref_id = rp.require('ref_id')
        with DrillDownNavigator(ws) as nav:
            return nav.expand_ref(ref_id)

    registry.register("/workspace/drill-ref", _drill_ref)

    def _drill_timeline() -> Dict[str, Any]:
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        ws = rp.workspace()
        with DrillDownNavigator(ws) as nav:
            return nav.drill_timeline(
                session_id=rp.session_id(),
                task_id=rp.task_id(),
                limit=_parse_int(params, "limit", 50),
            )

    registry.register("/workspace/drill-timeline", _drill_timeline)

    def _drill_task() -> Dict[str, Any]:
        from memory_center.core.navigation.drilldown import DrillDownNavigator
        ws = rp.workspace()
        task_id = rp.require('task_id')
        with DrillDownNavigator(ws) as nav:
            return nav.drill_task(task_id)

    registry.register("/workspace/drill-task", _drill_task)

    def _backend_consistency() -> Dict[str, Any]:
        from memory_center.core.store import WorkspaceStore
        from memory_center.core.backend.query import UnifiedBackendQuery
        ws = rp.workspace()
        store = WorkspaceStore(ws)
        with UnifiedBackendQuery(store.memory_db_path) as backend:
            return backend.check_consistency(store.base_dir)

    registry.register("/workspace/backend-consistency", _backend_consistency)

    def _benchmark_trend() -> Dict[str, Any]:
        from memory_center.core.benchmark.trending import generate_benchmark_report
        return generate_benchmark_report(
            rp.workspace(),
            function_name=rp.get("function_name", ""),
        )

    registry.register("/workspace/eval-token-benchmark-trend", _benchmark_trend)

    def _regression_alerts() -> Dict[str, Any]:
        from memory_center.core.benchmark.trending import check_regression_alerts
        return check_regression_alerts(
            rp.workspace(),
            threshold_pct=float(rp.get("threshold_pct", "10.0")),
        )

    registry.register("/workspace/regression-alerts", _regression_alerts)

    # --- next-phase verification / explanation / business flow ----------------
    def _verification_loop() -> Dict[str, Any]:
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

    def _pattern_promotion() -> Dict[str, Any]:
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

    def _heuristics() -> Dict[str, Any]:
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

    def _workflow_profile() -> Dict[str, Any]:
        from memory_center.core.verification.workflow_profiles import get_workflow_profile
        return get_workflow_profile(rp.get("profile", "quick-fix"))

    registry.register("/workspace/workflow-profile", _workflow_profile)

    def _workflow_recommend() -> Dict[str, Any]:
        from memory_center.core.verification.workflow_profiles import recommend_workflow_with_learning
        ws = rp.workspace()
        return recommend_workflow_with_learning(ws, rp.require('description'))

    registry.register("/workspace/workflow-recommend", _workflow_recommend)

    def _bundle_export() -> Dict[str, Any]:
        from memory_center.core.verification.bundle_export import generate_agent_bundle
        ws = rp.workspace()
        return generate_agent_bundle(ws, agent=rp.get("agent", "codex"))

    registry.register("/workspace/bundle-export", _bundle_export)

    def _runtime_audit() -> Dict[str, Any]:
        from memory_center.core.audit.runtime import audit_agent_runtime
        return audit_agent_runtime(rp.workspace())

    registry.register("/workspace/runtime-audit", _runtime_audit)

    def _explanation() -> Dict[str, Any]:
        from memory_center.core.explanation.schema import Explanation
        text = rp.require('text')
        persona = rp.get("persona", "developer")
        exp = Explanation(subject="explanation", summary=text, persona=persona)
        return exp.adapt_for_persona(persona).to_full()

    registry.register("/workspace/explanation", _explanation)

    def _business_flow() -> Dict[str, Any]:
        from memory_center.core.domain.flow import extract_business_flows_for_workspace
        ws = rp.workspace()
        return extract_business_flows_for_workspace(
            ws,
            rp.require('seed'),
            max_depth=_parse_int(params, "max_depth", 4),
        )

    registry.register("/workspace/business-flow", _business_flow)

    def _business_flow_impact() -> Dict[str, Any]:
        from memory_center.core.domain.flow import business_flow_impact_for_workspace
        ws = rp.workspace()
        return business_flow_impact_for_workspace(
            ws,
            rp.require('node_id'),
            max_depth=_parse_int(params, "max_depth", 3),
        )

    registry.register("/workspace/business-flow-impact", _business_flow_impact)

    def _metrics_summary() -> Dict[str, Any]:
        from memory_center.core.metrics import MetricsCollector
        ws = params.get("workspace", [default_workspace])[0]
        if not ws:
            return {"summary": {}, "note": "no_workspace_in_context"}
        metric_name = rp.get("metric_name", "")
        if not metric_name:
            return {"summary": {}, "note": "metric_name_required"}
        return {"summary": MetricsCollector(ws).summary(metric_name)}

    registry.register("/workspace/metrics-summary", _metrics_summary)

    def _onboard() -> Dict[str, Any]:
        from memory_center.core.onboarding.tour import ArchitectureTourGenerator
        from memory_center.core.storage.unified import UnifiedStore
        from memory_center.core.store import WorkspaceStore
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

    def _context_pack() -> Dict[str, Any]:
        from memory_center.core.context.pack import ContextPackBuilder
        ws = rp.workspace()
        builder = ContextPackBuilder(ws)
        query = rp.require('query')
        intent = rp.intent()
        budget_tokens = _parse_int(params, "budget_tokens", 8000)
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

    def _freshness() -> Dict[str, Any]:
        from memory_center.core.freshness.status import IndexFreshnessService
        ws = rp.workspace()
        return IndexFreshnessService(ws).banner()

    registry.register("/workspace/freshness", _freshness)

    # --- workspace-anchored group helpers (load_registry from workspace) ------
    def _workspace_group_status() -> Dict[str, Any]:
        from memory_center.core.registry import load_registry
        ws = rp.workspace()
        return group_status(load_registry(ws))

    registry.register("/workspace/group-status", _workspace_group_status)

    def _workspace_group_query() -> Dict[str, Any]:
        from memory_center.core.registry import load_registry
        ws = rp.workspace()
        return group_query(
            load_registry(ws),
            query=rp.require('query'),
            limit=_parse_int(params, "limit", 20),
        )

    registry.register("/workspace/group-query", _workspace_group_query)

    def _workspace_group_impact() -> Dict[str, Any]:
        from memory_center.core.registry import load_registry
        ws = rp.workspace()
        return group_impact(load_registry(ws), target=rp.require('target'))

    registry.register("/workspace/group-impact", _workspace_group_impact)

    def _workspace_group_chain() -> Dict[str, Any]:
        from memory_center.core.registry import load_registry
        ws = rp.workspace()
        return group_chain(load_registry(ws), symbol=rp.require('symbol'))

    registry.register("/workspace/group-chain", _workspace_group_chain)

    return registry
