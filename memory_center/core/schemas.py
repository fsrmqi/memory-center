from __future__ import annotations

from typing import Any, Dict


SCHEMA_VERSIONS = {
    "write_receipt": 1,
    "timeline_item": 1,
    "timeline_result": 1,
    "eval_result": 1,
    "resume_packet": 1,
    "handoff_packet": 1,
    "workspace_continuity_dashboard": 1,
    "workspace_dashboard": 1,
    "lookup_hint": 1,
    "tool_usage_report": 1,
    "memory_ref": 1,
    "memory_ref_batch": 1,
    # --- Facade return type schemas (B-02) ---
    "mc_start": 1,
    "mc_lookup": 1,
    "mc_analyze": 1,
    "mc_sync": 1,
    "mc_resume": 1,
    "mc_handoff": 1,
    "mc_close": 1,
    "mc_admin": 1,
    "mc_context_pack": 1,
    "mc_onboard": 1,
    "mc_domain": 1,
    "mc_freshness": 1,
}

SCHEMA_REQUIRED_FIELDS = {
    "write_receipt": {"receipt_id", "summary", "layer", "action", "scope", "target", "target_file"},
    "timeline_item": {"kind", "ref_id", "summary", "created_at", "task_id", "session_id", "layer", "action", "scope", "target"},
    "timeline_result": {"timeline", "summary", "filters"},
    "eval_result": {"score", "quality", "findings"},
    "resume_packet": {"resume_rule_profile"},
    "handoff_packet": {"target_model", "model_profile", "handoff_rule_profile", "handoff_packet"},
    "workspace_continuity_dashboard": {"focus_task", "resume_packet", "next_actions", "unresolved_items", "recent_evidence"},
    "workspace_dashboard": {"focus_task", "continuity_overview", "write_receipts_overview", "active_tasks", "recent_handoffs", "focus_resume_eval"},
    "lookup_hint": {"workspace", "query", "recommended_path", "preferred_tools", "reasons", "should_use_memory_center"},
    "tool_usage_report": {"workspace", "summary", "tool_counts", "lookup_tool_counts", "adoption_hints"},
    "memory_ref": {"ref_id", "kind", "summary", "raw"},
    "memory_ref_batch": {"refs", "requested", "found_count"},
    # --- Facade return type required fields (B-02) ---
    "mc_start": {"workflow", "sniff", "session"},
    "mc_lookup": {"result"},
    "mc_analyze": {"workflow", "depth", "impact"},
    "mc_sync": {"workflow", "mode", "result"},
    "mc_resume": {"workflow", "resume_packet", "next_actions", "unresolved_items", "recent_evidence"},
    "mc_handoff": {"workflow", "handoff_packet", "recent_evidence", "tool_usage_report"},
    "mc_close": {"workflow", "ended", "sync_case", "suggested_case"},
    "mc_admin": set(),  # mc_admin dispatches to sub-actions; no fixed required fields
    "mc_context_pack": {"workflow", "query", "intent", "entrypoints", "relationships", "checklist"},
    "mc_onboard": {"workflow", "tour"},
    "mc_domain": {"workflow", "domains", "domain_count"},
    "mc_freshness": {"workflow"},
}


def schema_meta(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "version": SCHEMA_VERSIONS.get(name, 1),
    }


def validate_schema_payload(name: str, payload: Dict[str, Any]) -> None:
    required = SCHEMA_REQUIRED_FIELDS.get(name, set())
    missing = sorted(field for field in required if field not in payload)
    if missing:
        raise ValueError(f"schema '{name}' missing required fields: {', '.join(missing)}")


def with_schema(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    validate_schema_payload(name, payload)
    return {
        "schema": schema_meta(name),
        **payload,
    }
