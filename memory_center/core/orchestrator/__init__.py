"""Orchestrator subpackage — re-exports all public functions.

All callers that previously did::

    from memory_center.core.orchestrator import memory_query, workspace_sniff, ...

continue to work unchanged through this ``__init__.py``.
"""

from __future__ import annotations

# --- common utilities (re-exported for convenience) ---
from .common import (
    SESSION_EVENTS_FILE,
    SESSION_SUMMARIES_FILE,
    EVENT_PAYLOAD_INLINE_LIMIT,
    LAYER_L0,
    LAYER_L1,
    LAYER_L2,
    LAYER_L3,
    MEMORY_LAYER_ORDER,
    TOOL_WORKSPACE_LOG_SESSION_EVENT,
    TOOL_WORKSPACE_START_SESSION,
    TOOL_WORKSPACE_RECORD_CASE,
    TOOL_WORKSPACE_SUGGEST_CASE,
    TOOL_WORKSPACE_SYNC_SNIFF_ARTIFACTS,
    TOOL_WORKSPACE_SYNC_CASE_ARTIFACTS,
    TOOL_WORKSPACE_ARTIFACT_UPDATE,
    load_context,
    tokenize,
    rank_files,
)

# --- session lifecycle ---
from .session import (
    workspace_start_session,
    workspace_log_session_event,
    workspace_end_session,
    workspace_recent_sessions,
    workspace_session_summary,
    workspace_suggest_case,
    workspace_recent_evidence,
)

# --- graph-native query tools ---
from .query import (
    memory_query,
    memory_context,
    memory_symbol,
    memory_callers,
    memory_callees,
    memory_search_code,
    memory_contracts,
    memory_ref_get,
    memory_ref_batch,
    memory_backend_query,
    memory_tool_usage_report,
)

# --- impact analysis ---
from .impact import (
    memory_impact,
    memory_plan_change,
    memory_verify_checklist,
    memory_detect_changes,
)

# --- memory write pipeline ---
from .write import (
    memory_write_judge,
    memory_plan_write,
    memory_execute_write,
    workspace_record_case,
    workspace_write_receipts,
    workspace_replay_write_chain,
)

# --- workspace operations ---
from .workspace import (
    workspace_check_contract,
    workspace_check_rules,
    workspace_status,
    workspace_sniff,
    workspace_trace,
    workspace_lookup_hint,
    workspace_dashboard,
    workspace_continuity_dashboard,
)

# --- resume and handoff ---
from .resume import (
    workspace_resume_packet,
    workspace_resume_context,
    workspace_unresolved_items,
    workspace_next_actions,
    workspace_handoff_packet,
    workspace_handoff_history,
    workspace_model_profile,
)

# --- evaluation functions ---
from .eval import (
    memory_eval_write_quality,
    memory_eval_resume,
    memory_eval_handoff,
    memory_eval_regression_suite,
    memory_eval_index_freshness,
    memory_eval_tool_adoption,
    memory_eval_context_weight,
)

# --- artifact sync ---
from .sync import (
    workspace_sync_sniff_to_artifacts,
    workspace_sync_case_to_artifacts,
)

# --- private helpers needed by tests ---
from .common import (
    _build_sniff_auto_sync_recommendation,
    _case_risk_level,
    _sniff_risk_level,
    _score_threshold_for_sync_mode,
)

# --- group operations ---
from .group import (
    group_status,
    group_query,
    group_impact,
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
    "load_context", "tokenize", "rank_files",
    # session
    "workspace_start_session", "workspace_log_session_event", "workspace_end_session",
    "workspace_recent_sessions", "workspace_session_summary", "workspace_suggest_case",
    "workspace_recent_evidence",
    # query
    "memory_query", "memory_context", "memory_symbol", "memory_callers", "memory_callees",
    "memory_search_code", "memory_contracts", "memory_ref_get", "memory_ref_batch",
    "memory_backend_query", "memory_tool_usage_report",
    # impact
    "memory_impact", "memory_plan_change", "memory_verify_checklist", "memory_detect_changes",
    # write
    "memory_write_judge", "memory_plan_write", "memory_execute_write",
    "workspace_record_case", "workspace_write_receipts", "workspace_replay_write_chain",
    # workspace
    "workspace_status", "workspace_sniff", "workspace_trace", "workspace_lookup_hint",
    "workspace_dashboard", "workspace_continuity_dashboard",
    # resume
    "workspace_resume_packet", "workspace_resume_context",
    "workspace_unresolved_items", "workspace_next_actions",
    "workspace_handoff_packet", "workspace_handoff_history", "workspace_model_profile",
    # eval
    "memory_eval_write_quality", "memory_eval_resume", "memory_eval_handoff",
    "memory_eval_regression_suite", "memory_eval_index_freshness",
    "memory_eval_tool_adoption", "memory_eval_context_weight",
    # sync
    "workspace_sync_sniff_to_artifacts", "workspace_sync_case_to_artifacts",
    # group
    "group_status", "group_query", "group_impact",
]