from __future__ import annotations

from typing import Any, Dict, List

from ..schemas import with_schema
from .common import _budget_limits, _trim_summary


def _compact_task_rows(rows: List[Dict[str, Any]], limit: int = 5) -> List[Dict[str, Any]]:
    return [
        {
            "task_id": row.get("task_id", ""),
            "title": row.get("title", ""),
            "status": row.get("status", ""),
            "priority": row.get("priority", ""),
            "updated_at": row.get("updated_at", ""),
            "summary_preview": row.get("summary_preview", ""),
        }
        for row in rows[:limit]
    ]


def _compact_sniff_result(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    limits = _budget_limits(budget)
    symbolic = result.get("symbolic_context", {}) or {}
    focus_entities = symbolic.get("focus_entities", {}) or {}
    return {
        "workspace": result.get("workspace", ""),
        "intent": result.get("intent", ""),
        "risk_level": result.get("risk_level", ""),
        "matched_services": result.get("matched_services", [])[: limits["services"]],
        "candidate_files": [
            {"project": item.get("project", ""), "path": item.get("path", ""), "score": item.get("score", 0)}
            for item in result.get("candidate_files", [])[: limits["files"]]
        ],
        "related_summary": {
            "api_count": len(result.get("related_apis", []) or []),
            "feign_count": len(result.get("related_feigns", []) or []),
            "mq_count": len(result.get("related_mq", []) or []),
            "rule_count": len(result.get("related_rules", []) or []),
            "case_count": len(result.get("historical_cases", []) or []),
        },
        "task_candidates": [
            {
                "task_id": item.get("task_id", ""),
                "title": item.get("title", ""),
                "status": item.get("status", ""),
                "score": item.get("score", 0),
            }
            for item in result.get("task_candidates", [])[: max(1, limits["tasks"] // 2)]
        ],
        "source_refs": [
            {
                "ref_id": item.get("ref_id", ""),
                "type": item.get("type", ""),
                "summary": item.get("summary", ""),
            }
            for item in result.get("source_refs", [])[: limits["refs"]]
        ],
        "resolved_task": result.get("resolved_task", {}),
        "auto_sync_recommendation": result.get("auto_sync_recommendation", {}),
        "write_judge_recommendation": result.get("write_judge_recommendation", {}),
        "lookup_hint": result.get("lookup_hint", {}),
        "symbolic_context": {
            "flow_flags": symbolic.get("flow_flags", {}),
            "flow_mermaid": symbolic.get("flow_mermaid", ""),
            "focus_entities": {
                "services": focus_entities.get("services", [])[:3],
                "files": focus_entities.get("files", [])[: limits["files"]],
                "apis": focus_entities.get("apis", [])[: limits["events"]],
                "feigns": focus_entities.get("feigns", [])[: limits["events"]],
            },
        },
        "next_steps": result.get("next_steps", [])[: limits["steps"]],
    }


def _compact_workspace_status(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    limits = _budget_limits(budget)
    return {
        "workspace": result.get("workspace", ""),
        "root": result.get("root", ""),
        "index_counts": result.get("index_counts", {}),
        "semantic_index": result.get("semantic_index", {}),
        "memory_layers": result.get("memory_layers", {}),
        "memory_overview": result.get("memory_overview", {}),
        "write_receipts_overview": {
            "total": (result.get("write_receipts_overview", {}) or {}).get("total", 0),
            "layer_counts": (result.get("write_receipts_overview", {}) or {}).get("layer_counts", {}),
            "action_counts": (result.get("write_receipts_overview", {}) or {}).get("action_counts", {}),
        },
        "continuity_overview": result.get("continuity_overview", {}),
        "core_memory_blocks": {
            "block_count": (result.get("core_memory_blocks", {}) or {}).get("block_count", 0),
            "filled_count": (result.get("core_memory_blocks", {}) or {}).get("filled_count", 0),
        },
        "active_task_spaces": _compact_task_rows(result.get("active_task_spaces", []), limit=limits["tasks"]),
        "current_focus_task": result.get("current_focus_task", {}),
    }


def _compact_resume_packet(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    limits = _budget_limits(budget)
    return with_schema(
        "resume_packet",
        {
            "workspace": result.get("workspace", ""),
            "task_id": result.get("task_id", ""),
            "task_title": result.get("task_title", ""),
            "task_status": result.get("task_status", ""),
            "current_phase": result.get("current_phase", ""),
            "current_summary": _trim_summary(str(result.get("current_summary", "") or "")),
            "next_recommended_actions": result.get("next_recommended_actions", [])[: limits["steps"]],
            "unresolved_items": result.get("unresolved_items", [])[: limits["findings"]],
            "verification_pending": result.get("verification_pending", False),
            "resume_rule_profile": result.get("resume_rule_profile", ""),
        },
    )


def _compact_continuity_dashboard(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    limits = _budget_limits(budget)
    resume_packet = result.get("resume_packet", {}) or {}
    return with_schema(
        "workspace_continuity_dashboard",
        {
            "workspace": result.get("workspace", ""),
            "focus_task": result.get("focus_task", {}),
            "continuity_overview": result.get("continuity_overview", {}),
            "resume_packet": {
                "task_id": resume_packet.get("task_id", ""),
                "task_title": resume_packet.get("task_title", ""),
                "current_phase": resume_packet.get("current_phase", ""),
                "resume_rule_profile": resume_packet.get("resume_rule_profile", ""),
                "next_recommended_actions": resume_packet.get("next_recommended_actions", [])[: limits["steps"]],
                "unresolved_items": resume_packet.get("unresolved_items", [])[: limits["findings"]],
            },
            "next_actions": result.get("next_actions", [])[: limits["steps"]],
            "unresolved_items": result.get("unresolved_items", [])[: limits["findings"]],
            "recent_receipts": result.get("recent_receipts", [])[: limits["events"]],
            "recent_handoffs": result.get("recent_handoffs", [])[: limits["events"]],
            "recent_evidence": result.get("recent_evidence", [])[: limits["events"]],
        },
    )


def _compact_workspace_dashboard(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    limits = _budget_limits(budget)
    focus_dashboard = result.get("focus_dashboard", {}) or {}
    focus_resume_eval = result.get("focus_resume_eval", {}) or {}
    tool_usage_report = result.get("tool_usage_report", {}) or {}
    write_receipts_overview = result.get("write_receipts_overview", {}) or {}
    return with_schema(
        "workspace_dashboard",
        {
            "workspace": result.get("workspace", ""),
            "focus_task": result.get("focus_task", {}),
            "continuity_overview": result.get("continuity_overview", {}),
            "write_receipts_overview": {
                "total": write_receipts_overview.get("total", 0),
                "layer_counts": write_receipts_overview.get("layer_counts", {}),
                "action_counts": write_receipts_overview.get("action_counts", {}),
            },
            "active_tasks": _compact_task_rows(result.get("active_tasks", []), limit=limits["tasks"]),
            "resumable_tasks": _compact_task_rows(result.get("resumable_tasks", []), limit=limits["tasks"]),
            "blocked_tasks": _compact_task_rows(result.get("blocked_tasks", []), limit=limits["tasks"]),
            "low_quality_tasks": _compact_task_rows(result.get("low_quality_tasks", []), limit=limits["tasks"]),
            "recent_receipts": result.get("recent_receipts", [])[: limits["events"]],
            "recent_handoffs": result.get("recent_handoffs", [])[: limits["events"]],
            "focus_dashboard": {
                "focus_task": focus_dashboard.get("focus_task", {}),
                "next_actions": focus_dashboard.get("next_actions", [])[: limits["steps"]],
                "unresolved_items": focus_dashboard.get("unresolved_items", [])[: limits["findings"]],
            },
            "focus_resume_eval": {
                "quality": focus_resume_eval.get("quality", ""),
                "score": focus_resume_eval.get("score", 0),
                "findings": focus_resume_eval.get("findings", [])[: limits["findings"]],
            },
            "tool_usage_report": {
                "summary": tool_usage_report.get("summary", {}),
                "lookup_tool_counts": tool_usage_report.get("lookup_tool_counts", {}),
                "suspected_bypass": tool_usage_report.get("suspected_bypass", [])[: limits["events"]],
                "adoption_hints": tool_usage_report.get("adoption_hints", [])[:2],
            },
        },
    )


def _compact_handoff_packet(result: Dict[str, Any], budget: str = "medium") -> Dict[str, Any]:
    limits = _budget_limits(budget)
    packet = result.get("handoff_packet", {}) or {}
    model_profile = result.get("model_profile", {}) or {}
    return with_schema(
        "handoff_packet",
        {
            "workspace": result.get("workspace", ""),
            "target_model": result.get("target_model", ""),
            "task_id": result.get("task_id", ""),
            "session_id": result.get("session_id", ""),
            "model_profile": {
                "normalized_model": model_profile.get("normalized_model", ""),
                "handoff_style": model_profile.get("handoff_style", ""),
            },
            "handoff_rule_profile": result.get("handoff_rule_profile", ""),
            "handoff_packet": {
                "what_has_been_done": packet.get("what_has_been_done", [])[: limits["events"]],
                "what_not_to_repeat": packet.get("what_not_to_repeat", [])[: limits["findings"]],
                "what_is_risky": packet.get("what_is_risky", [])[: limits["findings"]],
                "what_to_check_next": packet.get("what_to_check_next", [])[: limits["steps"]],
                "minimal_required_context": packet.get("minimal_required_context", {}),
                "recent_evidence": packet.get("recent_evidence", [])[: limits["events"]],
                "notes": packet.get("notes", [])[:2],
            },
            "handoff_ref": result.get("handoff_ref", ""),
        },
    )
