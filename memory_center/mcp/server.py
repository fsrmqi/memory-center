from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from memory_center.core.orchestrator import (
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
    memory_backend_query,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_verify_checklist,
    memory_plan_write,
    memory_execute_write,
    memory_tool_usage_report,
    memory_eval_write_quality,
    memory_eval_regression_suite,
    memory_eval_index_freshness,
    memory_eval_tool_adoption,
    memory_eval_context_weight,
    memory_eval_workflow_orchestration,
    memory_eval_resume,
    memory_eval_handoff,
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
from memory_center.core.wiki import generate_skills, generate_wiki

_WORKSPACE_FILE: Optional[str] = None


def create_server(workspace_file: str):
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Please install MCP dependency: pip install -e .[mcp]") from exc

    global _WORKSPACE_FILE
    _WORKSPACE_FILE = workspace_file
    mcp = FastMCP("Memory Center")

    @mcp.tool()
    def workspace_sniff_tool(intent: str, limit: int = 12, auto_sync_mode: str = "balanced", view: str = "compact", budget: str = "medium"):
        """Before any code task, retrieve services, files, rules, topology hints and historical cases."""
        return workspace_sniff(_WORKSPACE_FILE, intent, limit, auto_sync_mode=auto_sync_mode, view=view, budget=budget)

    @mcp.tool()
    def workspace_sync_sniff_artifacts_tool(
        intent: str,
        limit: int = 12,
        task_id: str = "",
        title: str = "",
        auto_sync_mode: str = "balanced",
    ):
        """Sync sniff result into shared context and plan artifacts."""
        return workspace_sync_sniff_to_artifacts(
            _WORKSPACE_FILE,
            intent,
            limit,
            task_id=task_id,
            title=title,
            auto_sync_mode=auto_sync_mode,
        )

    @mcp.tool()
    def workspace_artifact_list_tool():
        """List shared workspace artifacts such as context, requirement, design, plan and change log."""
        return list_artifacts(_WORKSPACE_FILE)

    @mcp.tool()
    def workspace_artifact_get_tool(name: str):
        """Read one shared workspace artifact."""
        return get_artifact(_WORKSPACE_FILE, name)

    @mcp.tool()
    def workspace_artifact_outline_tool(name: str):
        """Read one shared workspace artifact outline without loading full content."""
        return artifact_outline(_WORKSPACE_FILE, name)

    @mcp.tool()
    def workspace_artifact_context_tool(intent: str, limit: int = 6):
        """Retrieve only relevant artifact snippets for the current intent."""
        return artifact_context(_WORKSPACE_FILE, intent, limit)

    @mcp.tool()
    def workspace_artifact_update_tool(name: str, content: str):
        """Replace one shared workspace artifact content."""
        return update_artifact(_WORKSPACE_FILE, name, content)

    @mcp.tool()
    def workspace_append_change_log_tool(entry: str):
        """Append one timestamped entry to the shared change log."""
        return append_change_log(_WORKSPACE_FILE, entry)

    @mcp.tool()
    def workspace_compact_change_log_tool(keep_recent: int = 30):
        """Archive older change-log entries to keep shared context compact."""
        return compact_change_log(_WORKSPACE_FILE, keep_recent)

    @mcp.tool()
    def workspace_task_space_create_tool(title: str = "", intent: str = "", owner: str = "", tags: List[str] | None = None, priority: str = "medium"):
        """Create one task-specific artifact space from a custom title or intent."""
        return create_task_space(_WORKSPACE_FILE, title=title, intent=intent, owner=owner, tags=tags, priority=priority)

    @mcp.tool()
    def workspace_task_space_list_tool(include_archived: bool = False):
        """List active or archived task-specific artifact spaces."""
        return list_task_spaces(_WORKSPACE_FILE, include_archived=include_archived)

    @mcp.tool()
    def workspace_task_space_resolve_tool(intent: str, title: str = "", create_if_missing: bool = True, include_archived: bool = False, limit_candidates: int = 3, score_threshold: int = 3):
        """Resolve one task space from natural language; create one if needed. Score below threshold will not auto-match."""
        return resolve_task_space(_WORKSPACE_FILE, intent=intent, title=title, create_if_missing=create_if_missing, include_archived=include_archived, limit_candidates=limit_candidates, score_threshold=score_threshold)

    @mcp.tool()
    def workspace_task_artifact_get_tool(task_id: str, name: str):
        """Read one artifact inside a task-specific space."""
        return get_task_artifact(_WORKSPACE_FILE, task_id, name)

    @mcp.tool()
    def workspace_task_artifact_update_tool(task_id: str, name: str, content: str):
        """Replace one artifact inside a task-specific space."""
        return update_task_artifact(_WORKSPACE_FILE, task_id, name, content)

    @mcp.tool()
    def workspace_task_append_change_log_tool(task_id: str, entry: str, keep_recent: int = 30):
        """Append one timestamped entry into a task-specific change log."""
        return append_task_change_log(_WORKSPACE_FILE, task_id, entry, keep_recent=keep_recent)

    @mcp.tool()
    def workspace_task_archive_tool(task_id: str, reason: str = ""):
        """Archive one task-specific artifact space manually."""
        return archive_task_space(_WORKSPACE_FILE, task_id, reason=reason)

    @mcp.tool()
    def workspace_task_auto_archive_tool(retention_days: int = 30):
        """Auto-archive task-specific artifact spaces older than retention_days."""
        return auto_archive_task_spaces(_WORKSPACE_FILE, retention_days=retention_days)

    @mcp.tool()
    def workspace_task_status_tool(task_id: str, status: str):
        """Update one task-specific space status: draft/active/blocked/done/archived."""
        return update_task_status(_WORKSPACE_FILE, task_id, status)

    @mcp.tool()
    def workspace_task_activity_touch_tool(task_id: str, source: str):
        """Record last activity source for a task space (e.g. sync-sniff, sync-case, mcp)."""
        return touch_task_activity(_WORKSPACE_FILE, task_id, source)

    @mcp.tool()
    def memory_query_tool(query: str, limit: int = 20):
        """Graph-aware query across files, symbols, services, contracts, rules and memory."""
        return memory_query(_WORKSPACE_FILE, query, limit)

    @mcp.tool()
    def memory_search_code_tool(query: str, scope: str = "", limit: int = 20):
        """Keyword code search for project/path/symbol hints before deep graph traversal."""
        return memory_search_code(_WORKSPACE_FILE, query, scope, limit)

    @mcp.tool()
    def memory_symbol_tool(name: str, limit: int = 10):
        """Resolve one symbol and provide best match plus nearby candidates."""
        return memory_symbol(_WORKSPACE_FILE, name, limit)

    @mcp.tool()
    def memory_callers_tool(symbol: str, depth: int = 2, limit: int = 80):
        """Find upstream callers for a symbol (method/class/feign/topic/config)."""
        return memory_callers(_WORKSPACE_FILE, symbol, depth, limit)

    @mcp.tool()
    def memory_callees_tool(symbol: str, depth: int = 2, limit: int = 80):
        """Find downstream callees for a symbol (method/class/feign/topic/config)."""
        return memory_callees(_WORKSPACE_FILE, symbol, depth, limit)

    @mcp.tool()
    def memory_context_tool(name: str, max_depth: int = 2):
        """Return 360-degree context for a service, endpoint, Feign method, topic, file or symbol."""
        return memory_context(_WORKSPACE_FILE, name, max_depth)

    @mcp.tool()
    def memory_impact_tool(target: str, direction: str = "upstream", max_depth: int = 3):
        """Analyze upstream/downstream impact for a changed symbol, DTO, Feign contract, endpoint or topic."""
        return memory_impact(_WORKSPACE_FILE, target, direction, max_depth)

    @mcp.tool()
    def memory_detect_changes_tool(scope: str = "staged"):
        """Map local git changes to affected projects, graph nodes, rules and risk level."""
        return memory_detect_changes(_WORKSPACE_FILE, scope)

    @mcp.tool()
    def memory_contracts_tool():
        """List discovered Feign/API/MQ contracts and contract-related rules."""
        return memory_contracts(_WORKSPACE_FILE)

    @mcp.tool()
    def memory_plan_change_tool(target: str, direction: str = "upstream", max_depth: int = 3):
        """Create one actionable change plan from impact and rule evidence."""
        return memory_plan_change(_WORKSPACE_FILE, target, direction, max_depth)

    @mcp.tool()
    def memory_verify_checklist_tool(target: str):
        """Generate one verification checklist before merge/release."""
        return memory_verify_checklist(_WORKSPACE_FILE, target)

    @mcp.tool()
    def workspace_lookup_hint_tool(query: str, intent: str = "", limit: int = 8):
        """Suggest whether to use Memory Center lookup tools or local search first."""
        return workspace_lookup_hint(_WORKSPACE_FILE, query=query, intent=intent, limit=limit)

    @mcp.tool()
    def memory_write_judge_tool(
        text: str,
        source: str = "note",
        intent: str = "",
        prefer_layer: str = "",
        projects: List[str] | None = None,
        files: List[str] | None = None,
    ):
        """Judge whether input should be written to L0/L1/L2/L3 memory layer."""
        return memory_write_judge(
            _WORKSPACE_FILE,
            text=text,
            source=source,
            intent=intent,
            prefer_layer=prefer_layer,
            projects=projects,
            files=files,
        )

    @mcp.tool()
    def memory_plan_write_tool(
        text: str,
        source: str = "note",
        intent: str = "",
        session_id: str = "",
        task_id: str = "",
        title: str = "",
        prefer_layer: str = "",
        projects: List[str] | None = None,
        files: List[str] | None = None,
    ):
        """Build one executable write plan from memory_write_judge decision."""
        return memory_plan_write(
            _WORKSPACE_FILE,
            text=text,
            source=source,
            intent=intent,
            session_id=session_id,
            task_id=task_id,
            title=title,
            prefer_layer=prefer_layer,
            projects=projects,
            files=files,
        )

    @mcp.tool()
    def memory_execute_write_tool(
        text: str,
        source: str = "note",
        intent: str = "",
        session_id: str = "",
        task_id: str = "",
        title: str = "",
        prefer_layer: str = "",
        projects: List[str] | None = None,
        files: List[str] | None = None,
    ):
        """Execute the ready write steps derived from memory_plan_write."""
        return memory_execute_write(
            _WORKSPACE_FILE,
            text=text,
            source=source,
            intent=intent,
            session_id=session_id,
            task_id=task_id,
            title=title,
            prefer_layer=prefer_layer,
            projects=projects,
            files=files,
        )

    @mcp.tool()
    def workspace_write_receipts_tool(
        layer: str = "",
        action: str = "",
        scope: str = "",
        task_id: str = "",
        session_id: str = "",
        limit: int = 50,
    ):
        """Query persisted write receipts by layer/action/scope/task/session."""
        return workspace_write_receipts(
            _WORKSPACE_FILE,
            layer=layer,
            action=action,
            scope=scope,
            task_id=task_id,
            session_id=session_id,
            limit=limit,
        )

    @mcp.tool()
    def workspace_replay_write_chain_tool(task_id: str = "", session_id: str = "", limit: int = 100):
        """Replay one write chain by task_id or session_id."""
        return workspace_replay_write_chain(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, limit=limit)

    @mcp.tool()
    def memory_eval_write_quality_tool(task_id: str = "", session_id: str = "", intent: str = "", limit: int = 100):
        """Evaluate whether receipts cover the expected write layers."""
        return memory_eval_write_quality(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit)

    @mcp.tool()
    def memory_eval_resume_tool(task_id: str = "", session_id: str = "", intent: str = "", limit: int = 20):
        """Evaluate resume packet quality."""
        return memory_eval_resume(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit)

    @mcp.tool()
    def memory_eval_handoff_tool(target_model: str, task_id: str = "", session_id: str = "", intent: str = "", limit: int = 20):
        """Evaluate handoff packet quality."""
        return memory_eval_handoff(_WORKSPACE_FILE, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit)

    @mcp.tool()
    def memory_eval_regression_suite_tool(target_model: str = "codex", task_id: str = "", session_id: str = "", intent: str = "", limit: int = 20):
        """Run one aggregated write/resume/handoff regression suite."""
        return memory_eval_regression_suite(
            _WORKSPACE_FILE,
            target_model=target_model,
            task_id=task_id,
            session_id=session_id,
            intent=intent,
            limit=limit,
        )

    @mcp.tool()
    def memory_eval_index_freshness_tool(scope: str = "all"):
        """Evaluate whether current indexes look stale relative to git changes."""
        return memory_eval_index_freshness(_WORKSPACE_FILE, scope=scope)

    @mcp.tool()
    def memory_eval_tool_adoption_tool(limit: int = 200):
        """Evaluate recent Memory Center tool adoption quality."""
        return memory_eval_tool_adoption(_WORKSPACE_FILE, limit=limit)

    @mcp.tool()
    def memory_eval_context_weight_tool(intent: str = "", limit: int = 8):
        """Evaluate whether compact budgeted payloads are still too heavy."""
        return memory_eval_context_weight(_WORKSPACE_FILE, intent=intent, limit=limit)

    @mcp.tool()
    def memory_eval_workflow_orchestration_tool(task_id: str = "", session_id: str = "", intent: str = "", limit: int = 20):
        """Evaluate whether a workflow follows the recommended start→log→sync→close pattern."""
        return memory_eval_workflow_orchestration(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit)

    @mcp.tool()
    def memory_tool_usage_report_tool(limit: int = 200):
        """Summarize recent Memory Center vs external tool usage and lookup adoption."""
        return memory_tool_usage_report(_WORKSPACE_FILE, limit=limit)

    @mcp.tool()
    def memory_ref_get_tool(ref_id: str):
        """Resolve one short memory reference id into the underlying raw content."""
        return memory_ref_get(_WORKSPACE_FILE, ref_id=ref_id)

    @mcp.tool()
    def memory_ref_batch_tool(ref_ids: List[str]):
        """Resolve multiple short memory reference ids."""
        return memory_ref_batch(_WORKSPACE_FILE, ref_ids=ref_ids)

    @mcp.tool()
    def memory_backend_query_tool(collection: str = "", record_id: str = "", created_after: str = "", ref_path: str = "", project: str = "", payload_type: str = "", limit: int = 50):
        """Query the mirrored SQLite memory backend."""
        return memory_backend_query(_WORKSPACE_FILE, collection=collection, record_id=record_id, created_after=created_after, ref_path=ref_path, project=project, payload_type=payload_type, limit=limit)

    @mcp.tool()
    def workspace_trace_tool(entry: str):
        """Trace cross-service candidates by class name, Feign client, Controller endpoint, or MQ topic."""
        return workspace_trace(_WORKSPACE_FILE, entry)

    @mcp.tool()
    def workspace_check_contract_tool(contract_file: str, change_type: str):
        """Check impact before changing DTO, Feign client, MQ message or shared contract files."""
        return workspace_check_contract(_WORKSPACE_FILE, contract_file, change_type)

    @mcp.tool()
    def workspace_check_rules_tool(projects: List[str] | None = None, change_type: str = "general", files: List[str] | None = None):
        """Check architecture rules before editing files."""
        return workspace_check_rules(_WORKSPACE_FILE, projects, change_type, files)

    @mcp.tool()
    def workspace_record_case_tool(
        task: str,
        projects: List[str],
        files: List[str],
        flow: str = "",
        risk_points: List[str] | None = None,
        verified_by: List[str] | None = None,
        source_session_id: str = "",
        source_task_id: str = "",
        valid_from: str = "",
        valid_to: str = "",
        superseded_by: str = "",
        current_truth: bool = True,
    ):
        """Record a solved task into cross-service memory after validation."""
        return workspace_record_case(
            _WORKSPACE_FILE,
            task,
            projects,
            files,
            flow,
            risk_points,
            verified_by,
            source_session_id=source_session_id,
            source_task_id=source_task_id,
            valid_from=valid_from,
            valid_to=valid_to,
            superseded_by=superseded_by,
            current_truth=current_truth,
        )

    @mcp.tool()
    def workspace_start_session_tool(intent: str, session_id: str = ""):
        """Start one lightweight task session for later resume/review."""
        return workspace_start_session(_WORKSPACE_FILE, intent, session_id=session_id or None)

    @mcp.tool()
    def workspace_log_session_event_tool(session_id: str, event_type: str, payload: dict | None = None):
        """Append one session event such as prompt, tool_call, tool_result or note."""
        return workspace_log_session_event(_WORKSPACE_FILE, session_id, event_type, payload)

    @mcp.tool()
    def workspace_work_start_tool(intent: str, limit: int = 8, auto_sync_mode: str = "balanced", sync_task_space: bool = True, budget: str = "medium"):
        """Start one task workflow: sniff, optional sync, then start session."""
        sniff_result = workspace_sniff(_WORKSPACE_FILE, intent, limit=limit, auto_sync_mode=auto_sync_mode, view="compact", budget=budget)
        synced = None
        resolved_task = sniff_result.get("resolved_task", {}) or {}
        auto_sync = sniff_result.get("auto_sync_recommendation", {}) or {}
        if sync_task_space and (auto_sync.get("recommended") or resolved_task.get("task_id")):
            synced = workspace_sync_sniff_to_artifacts(
                _WORKSPACE_FILE,
                intent,
                limit=limit,
                task_id=str(resolved_task.get("task_id", "") or ""),
                title=str(resolved_task.get("title", "") or ""),
                auto_sync_mode=auto_sync_mode,
            )
        session = workspace_start_session(_WORKSPACE_FILE, intent)
        return {"workflow": "work-start", "sniff": sniff_result, "sync_sniff": synced, "session": session}

    @mcp.tool()
    def workspace_work_sync_tool(intent: str = "", session_id: str = "", task_id: str = "", title: str = "", limit: int = 8, auto_sync_mode: str = "balanced"):
        """Sync current task context or case back into task space."""
        if session_id.strip():
            return {
                "workflow": "work-sync",
                "mode": "case",
                "result": workspace_sync_case_to_artifacts(_WORKSPACE_FILE, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode),
            }
        if intent.strip():
            return {
                "workflow": "work-sync",
                "mode": "sniff",
                "result": workspace_sync_sniff_to_artifacts(_WORKSPACE_FILE, intent, limit=limit, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode),
            }
        raise ValueError("workspace_work_sync_tool requires intent or session_id")

    @mcp.tool()
    def workspace_end_session_tool(session_id: str, outcome: str = "", verified_by: List[str] | None = None):
        """End one session and generate a reusable summary."""
        return workspace_end_session(_WORKSPACE_FILE, session_id, outcome, verified_by)

    @mcp.tool()
    def workspace_recent_sessions_tool(limit: int = 10):
        """List recent summarized sessions for this workspace."""
        return workspace_recent_sessions(_WORKSPACE_FILE, limit)

    @mcp.tool()
    def workspace_session_summary_tool(session_id: str):
        """Read one session summary together with recorded raw events."""
        return workspace_session_summary(_WORKSPACE_FILE, session_id)

    @mcp.tool()
    def workspace_resume_context_tool(intent: str, limit: int = 5):
        """Resume a new task by mixing related sessions, cases and query entrypoints."""
        return workspace_resume_context(_WORKSPACE_FILE, intent, limit)

    @mcp.tool()
    def workspace_recent_evidence_tool(task_id: str = "", session_id: str = "", limit: int = 10, budget: str = "medium"):
        """Return recent evidence from receipts and session events."""
        return workspace_recent_evidence(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, limit=limit, budget=budget)

    @mcp.tool()
    def workspace_unresolved_items_tool(task_id: str = "", session_id: str = "", intent: str = "", limit: int = 10):
        """Return unresolved items for one task/session."""
        return workspace_unresolved_items(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit)

    @mcp.tool()
    def workspace_next_actions_tool(task_id: str = "", session_id: str = "", intent: str = "", limit: int = 8):
        """Suggest next actions for one task/session."""
        return workspace_next_actions(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit)

    @mcp.tool()
    def workspace_resume_packet_tool(task_id: str = "", session_id: str = "", intent: str = "", limit: int = 10, view: str = "compact", budget: str = "medium"):
        """Build one resume packet for the next model/session."""
        return workspace_resume_packet(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view=view, budget=budget)

    @mcp.tool()
    def workspace_work_resume_tool(task_id: str = "", session_id: str = "", intent: str = "", limit: int = 8, budget: str = "medium"):
        """Resume one task with compact packet, next actions, unresolved items, and recent evidence."""
        return {
            "workflow": "work-resume",
            "resume_packet": workspace_resume_packet(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "next_actions": workspace_next_actions(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "unresolved_items": workspace_unresolved_items(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, intent=intent, limit=limit),
            "recent_evidence": workspace_recent_evidence(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget),
        }

    @mcp.tool()
    def workspace_model_profile_tool(model_name: str):
        """Return one normalized model profile for handoff."""
        return workspace_model_profile(model_name)

    @mcp.tool()
    def workspace_handoff_packet_tool(target_model: str, task_id: str = "", session_id: str = "", intent: str = "", limit: int = 10, view: str = "compact", budget: str = "medium"):
        """Build one handoff packet for the target model."""
        return workspace_handoff_packet(_WORKSPACE_FILE, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view=view, budget=budget)

    @mcp.tool()
    def workspace_work_handoff_tool(target_model: str, task_id: str = "", session_id: str = "", intent: str = "", limit: int = 8, budget: str = "medium"):
        """Build one compact handoff workflow package."""
        return {
            "workflow": "work-handoff",
            "handoff_packet": workspace_handoff_packet(_WORKSPACE_FILE, target_model=target_model, task_id=task_id, session_id=session_id, intent=intent, limit=limit, view="compact", budget=budget),
            "recent_evidence": workspace_recent_evidence(_WORKSPACE_FILE, task_id=task_id, session_id=session_id, limit=min(limit, 5), budget=budget),
            "tool_usage_report": memory_tool_usage_report(_WORKSPACE_FILE, limit=50),
        }

    @mcp.tool()
    def workspace_handoff_history_tool(target_model: str = "", task_id: str = "", session_id: str = "", limit: int = 50):
        """Query persisted handoff history."""
        return workspace_handoff_history(_WORKSPACE_FILE, target_model=target_model, task_id=task_id, session_id=session_id, limit=limit)

    @mcp.tool()
    def workspace_continuity_dashboard_tool(intent: str = "", task_id: str = "", session_id: str = "", limit: int = 10, view: str = "compact", budget: str = "medium"):
        """Build one daily continuity dashboard."""
        return workspace_continuity_dashboard(_WORKSPACE_FILE, intent=intent, task_id=task_id, session_id=session_id, limit=limit, view=view, budget=budget)

    @mcp.tool()
    def workspace_dashboard_tool(intent: str = "", limit: int = 10, view: str = "compact", budget: str = "medium"):
        """Build one workspace-level dashboard."""
        return workspace_dashboard(_WORKSPACE_FILE, intent=intent, limit=limit, view=view, budget=budget)

    @mcp.tool()
    def workspace_work_close_tool(session_id: str, outcome: str = "", task_id: str = "", title: str = "", auto_sync_mode: str = "balanced", record_case: bool = True, verified_by: List[str] | None = None):
        """Close one task workflow: end session, sync case, optionally record case."""
        ended = workspace_end_session(_WORKSPACE_FILE, session_id, outcome, verified_by)
        synced = workspace_sync_case_to_artifacts(_WORKSPACE_FILE, session_id, task_id=task_id, title=title, auto_sync_mode=auto_sync_mode)
        draft = workspace_suggest_case(_WORKSPACE_FILE, session_id)
        recorded = None
        case = draft.get("draft_case", {}) if draft.get("found") else {}
        if record_case and case.get("projects") and case.get("files"):
            recorded = workspace_record_case(
                _WORKSPACE_FILE,
                case.get("task", outcome or "work-close"),
                case.get("projects", []),
                case.get("files", []),
                case.get("flow", ""),
                case.get("risk_points", []),
                verified_by=case.get("verified_by", []) or verified_by,
                source_session_id=session_id,
                source_task_id=task_id,
            )
        return {"workflow": "work-close", "ended": ended, "sync_case": synced, "suggested_case": draft, "record_case": recorded}

    @mcp.tool()
    def workspace_work_health_tool(intent: str = "Memory Center work health", target_model: str = "codex", limit: int = 5):
        """Run one compact workflow health check."""
        return {
            "workflow": "work-health",
            "status": workspace_status(_WORKSPACE_FILE, view="compact", budget="medium"),
            "tool_usage_report": memory_tool_usage_report(_WORKSPACE_FILE, limit=50),
            "regression_suite": memory_eval_regression_suite(_WORKSPACE_FILE, intent=intent, target_model=target_model, limit=limit),
        }

    @mcp.tool()
    def workspace_suggest_case_tool(session_id: str):
        """Suggest one record-case draft from a finished session."""
        return workspace_suggest_case(_WORKSPACE_FILE, session_id)

    @mcp.tool()
    def workspace_sync_case_artifacts_tool(
        session_id: str,
        task_id: str = "",
        title: str = "",
        auto_sync_mode: str = "balanced",
    ):
        """Sync one suggested case into shared design and change-log artifacts."""
        return workspace_sync_case_to_artifacts(
            _WORKSPACE_FILE,
            session_id,
            task_id=task_id,
            title=title,
            auto_sync_mode=auto_sync_mode,
        )

    @mcp.tool()
    def memory_generate_wiki_tool(output_dir: str | None = None):
        """Generate bilingual Markdown wiki from the current workspace graph and task memory."""
        return generate_wiki(_WORKSPACE_FILE, output_dir)

    @mcp.tool()
    def memory_generate_skills_tool(output_dir: str | None = None):
        """Generate agent skill files from historical task memory."""
        return generate_skills(_WORKSPACE_FILE, output_dir)

    @mcp.tool()
    def workspace_status_tool(view: str = "compact", budget: str = "medium"):
        """Return workspace index and memory status."""
        return workspace_status(_WORKSPACE_FILE, view=view, budget=budget)

    @mcp.tool()
    def group_query_tool(group: str, query: str, limit: int = 20):
        """Run a merged query across all workspaces registered in a logical group."""
        return group_query(group, query, limit)

    @mcp.tool()
    def group_status_tool(group: str):
        """Return aggregated index status for all workspaces in a logical group."""
        return group_status(group)

    @mcp.tool()
    def group_impact_tool(group: str, target: str, direction: str = "upstream", max_depth: int = 3):
        """Run cross-workspace impact analysis across a logical group."""
        return group_impact(group, target, direction, max_depth)

    @mcp.resource("memory-center://status")
    def status_resource():
        return workspace_status(_WORKSPACE_FILE)

    @mcp.resource("memory-center://contracts")
    def contracts_resource():
        return memory_contracts(_WORKSPACE_FILE)

    @mcp.resource("memory-center://topology")
    def topology_resource():
        return workspace_status(_WORKSPACE_FILE).get("topology", {})

    @mcp.prompt()
    def detect_impact(target: str) -> str:
        return (
            "Use Memory Center before editing. Call memory_impact_tool for the target, "
            "then inspect required_rules and review_checklist before proposing changes. "
            f"Target: {target}"
        )

    @mcp.prompt()
    def spring_cloud_safe_change(task: str) -> str:
        return (
            "For this Spring Cloud task, call workspace_sniff_tool first. If this is a multi-step or "
            "collaborative task, sync the sniff result with workspace_sync_sniff_artifacts_tool, then use "
            "memory_context_tool or memory_impact_tool for important contracts. Before editing, call "
            "workspace_check_rules_tool. For long tasks, record key steps with workspace_start_session_tool / "
            "workspace_log_session_event_tool, then end the session, sync conclusions with "
            "workspace_sync_case_artifacts_tool, and finally call workspace_record_case_tool. Task: " + task
        )

    return mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="Path to .memory-center/workspace.yaml")
    args = parser.parse_args()
    server = create_server(str(Path(args.workspace).expanduser().resolve()))
    server.run()


if __name__ == "__main__":
    main()
