"""Orchestrator subpackage — re-exports all public functions.

Public task operations are re-exported here for MCP, CLI, HTTP and hooks.
"""

from __future__ import annotations

# --- external provider actions ---
from .bootstrap import (
    bootstrap_workspace_context,
    execute_mcp_bridge_action,
    execute_provider_action,
    fuse_provider_evidence,
    mcp_bridge_status,
)

# --- evaluation functions ---
from .evaluations import (
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
    memory_eval_token_benchmark_compare,
    memory_eval_token_benchmark_save,
    memory_eval_token_gain,
    memory_eval_tool_adoption,
    memory_eval_workflow_orchestration,
    memory_eval_write_quality,
)

# --- group operations ---
from .group import (
    group_chain,
    group_impact,
    group_query,
    group_status,
)

# --- impact analysis ---
from .impact import (
    memory_detect_changes,
    memory_impact,
    memory_plan_change,
    memory_verify_checklist,
)

# --- graph-native query tools ---
from .query import (
    _annotate_phantom_nodes,
    memory_backend_query,
    memory_callees,
    memory_callers,
    memory_context,
    memory_contracts,
    memory_discover,
    memory_eval_walkthrough_quality,
    memory_export_walkthrough_artifact,
    memory_method_walkthrough,
    memory_query_hybrid,
    memory_ref_batch,
    memory_ref_get,
    memory_search_code,
    memory_symbol,
    memory_tool_usage_report,
    memory_walkthrough_health,
)

# --- common utilities (re-exported for convenience) ---
# --- private helpers needed by tests ---
from .ranking import (
    rank_files,
    tokenize,
)

# --- resume and handoff ---
from .resume import (
    workspace_handoff_history,
    workspace_handoff_packet,
    workspace_model_profile,
    workspace_next_actions,
    workspace_resume_context,
    workspace_resume_packet,
    workspace_unresolved_items,
)
from .resume_check import workspace_task_resume_check
from .rules import _score_threshold_for_sync_mode

# --- session lifecycle ---
from .session import (
    workspace_end_session,
    workspace_capture_dsh_delivery_summary,
    workspace_log_session_event,
    workspace_recent_evidence,
    workspace_recent_sessions,
    workspace_record_agent_guidance,
    workspace_record_close_feedback,
    workspace_session_summary,
    workspace_start_session,
    workspace_suggest_case,
)
from .session_payloads import EVENT_PAYLOAD_INLINE_LIMIT
from .shared import (
    LAYER_L0,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    MEMORY_LAYER_ORDER,
    SESSION_EVENTS_FILE,
    SESSION_SUMMARIES_FILE,
    TOOL_WORKSPACE_ARTIFACT_UPDATE,
    TOOL_WORKSPACE_LOG_SESSION_EVENT,
    TOOL_WORKSPACE_RECORD_CASE,
    TOOL_WORKSPACE_START_SESSION,
    TOOL_WORKSPACE_SUGGEST_CASE,
    TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
    TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
    _build_sniff_auto_sync_recommendation,
    _case_risk_level,
    _sniff_risk_level,
    load_context,
    preferred_edge_types,
)

# --- artifact sync ---
from .sync import (
    workspace_sync_case_to_artifacts,
    workspace_sync_sniff_to_artifacts,
)

# --- workspace operations ---
from .workspace_ops import (
    workspace_check_contract,
    workspace_check_rules,
    workspace_continuity_dashboard,
    workspace_dashboard,
    workspace_lookup_hint,
    workspace_sniff,
    workspace_status,
    workspace_workbench_summary,
    workspace_trace,
)

# --- memory write pipeline ---
from .write import (
    memory_execute_write,
    memory_plan_write,
    memory_write_judge,
    workspace_record_case,
    workspace_replay_write_chain,
    workspace_write_receipts,
)

# --- multi-session consolidation (offline, dry-run by default) ---
from .consolidate import (
    workspace_consolidate_sessions,
    workspace_decide_consolidation_candidate,
    workspace_list_consolidation_candidates,
)

__all__ = [
    # constants
    "SESSION_EVENTS_FILE", "SESSION_SUMMARIES_FILE", "EVENT_PAYLOAD_INLINE_LIMIT",
    "LAYER_L0", "LAYER_L1", "LAYER_L2", "LAYER_L3", "MEMORY_LAYER_ORDER",
    "TOOL_WORKSPACE_LOG_SESSION_EVENT", "TOOL_WORKSPACE_START_SESSION",
    "TOOL_WORKSPACE_RECORD_CASE", "TOOL_WORKSPACE_SUGGEST_CASE",
    "TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS", "TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS",
    "TOOL_WORKSPACE_ARTIFACT_UPDATE",
    # utilities
    "load_context", "tokenize", "rank_files", "preferred_edge_types",
    # session
    "workspace_start_session", "workspace_log_session_event", "workspace_end_session",
    "workspace_record_agent_guidance", "workspace_record_close_feedback",
    "workspace_recent_sessions", "workspace_session_summary", "workspace_suggest_case", "workspace_capture_dsh_delivery_summary",
    "workspace_recent_evidence",
    # query
    "memory_query_hybrid", "memory_context", "memory_symbol", "memory_callers", "memory_callees", "memory_method_walkthrough",
    "memory_walkthrough_health", "memory_eval_walkthrough_quality", "memory_export_walkthrough_artifact",
    "memory_search_code", "memory_contracts", "memory_ref_get", "memory_ref_batch",
    "memory_backend_query", "memory_tool_usage_report", "memory_discover", "_annotate_phantom_nodes",
    # impact
    "memory_impact", "memory_plan_change", "memory_verify_checklist", "memory_detect_changes",
    # write
    "memory_write_judge", "memory_plan_write", "memory_execute_write",
    "workspace_record_case", "workspace_write_receipts", "workspace_replay_write_chain",
    "workspace_consolidate_sessions", "workspace_decide_consolidation_candidate",
    "workspace_list_consolidation_candidates",
    # workspace
    "workspace_check_contract", "workspace_check_rules",
    "workspace_status", "workspace_workbench_summary", "workspace_sniff", "workspace_trace", "workspace_lookup_hint", "bootstrap_workspace_context", "execute_provider_action", "mcp_bridge_status", "execute_mcp_bridge_action", "fuse_provider_evidence",
    "workspace_dashboard", "workspace_continuity_dashboard", "workspace_task_resume_check",
    # resume
    "workspace_resume_packet", "workspace_resume_context",
    "workspace_unresolved_items", "workspace_next_actions",
    "workspace_handoff_packet", "workspace_handoff_history", "workspace_model_profile",
    # eval
    "memory_eval_write_quality", "memory_eval_resume", "memory_eval_handoff",
    "memory_eval_agent_guidance", "memory_eval_agent_guidance_adoption", "memory_eval_agent_guidance_adoption_trend", "memory_eval_agent_guidance_replay", "memory_eval_agent_guidance_replay_campaign", "memory_eval_agent_guidance_replay_trend", "memory_eval_agent_guidance_trend",
    "memory_eval_regression_suite", "memory_eval_index_freshness",
    "memory_eval_tool_adoption", "memory_eval_context_weight", "memory_eval_workflow_orchestration", "memory_eval_token_gain", "memory_eval_parser_benchmark", "memory_eval_java_call_resolution", "memory_eval_java_call_resolution_metrics", "memory_eval_java_call_resolution_review", "memory_eval_java_call_resolution_unresolved", "memory_eval_token_benchmark",
    "memory_eval_token_benchmark_save", "memory_eval_token_benchmark_compare",
    # sync
    "workspace_sync_sniff_to_artifacts", "workspace_sync_case_to_artifacts",
    # group
    "group_status", "group_query", "group_impact", "group_chain",
    # private helpers used by legacy tests
    "_build_sniff_auto_sync_recommendation", "_case_risk_level",
    "_sniff_risk_level", "_score_threshold_for_sync_mode",
]
