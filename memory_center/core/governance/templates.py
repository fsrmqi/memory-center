"""Workflow instruction templates for guiding LLM behavior.

Provides structured guidance for each work-* command that MCP facade returns
can include to help models follow the expected protocol.
"""
from __future__ import annotations

from typing import Any

WORKFLOW_TEMPLATES: dict[str, dict[str, Any]] = {
    "work-start": {
        "expected_input": "intent: string describing the coding task",
        "decision_tree": {
            "new_task": "If no matching task space found, create one via mc_start with sync_task_space=True",
            "resumed_task": "If task space found, read current_summary and next_actions before proceeding",
            "high_risk": "If risk_level=high, review related_rules before any code changes",
        },
        "output_format": "sniff + session + optional sync result",
        "anti_patterns": [
            "Do not skip sniff and go directly to code search",
            "Do not create duplicate task spaces for the same intent",
            "Do not ignore risk_level warnings",
        ],
    },
    "work-log": {
        "expected_input": "session_id: string, event_type: string, payload: dict",
        "decision_tree": {
            "tool_call": "Log tool_name, query/target, and result summary",
            "error_event": "Include full error message and stack trace in payload",
            "decision": "Log the decision rationale, not just the outcome",
        },
        "output_format": "session_event with ref_id",
        "anti_patterns": [
            "Do not log redundant events (same tool, same target, consecutive)",
            "Do not omit error details from failure events",
        ],
    },
    "work-sync": {
        "expected_input": "session_id or intent, optional task_id",
        "decision_tree": {
            "case_sync": "If session_id provided, sync case artifacts to task space",
            "sniff_sync": "If intent provided, sync sniff results to artifacts",
            "no_task": "If no task_id, suggest creating one first",
        },
        "output_format": "sync result with artifact references",
        "anti_patterns": [
            "Do not sync without a valid session or intent",
            "Do not overwrite existing artifacts without checking",
        ],
    },
    "work-resume": {
        "expected_input": "intent or task_id or session_id",
        "decision_tree": {
            "has_task": "Resume from task context, show next_actions and unresolved_items",
            "has_session": "Resume from session context, show recent_evidence",
            "intent_only": "Search for matching task spaces, suggest best match",
        },
        "output_format": "resume_packet + next_actions + unresolved_items + recent_evidence",
        "anti_patterns": [
            "Do not resume without showing next_actions",
            "Do not ignore unresolved_items from previous session",
        ],
    },
    "work-handoff": {
        "expected_input": "target_model: string, optional task_id/session_id",
        "decision_tree": {
            "different_model": "Build handoff packet with target model's budget profile",
            "same_model": "Still useful for context refresh, use compact view",
            "no_context": "If no task/session, create minimal handoff from workspace status",
        },
        "output_format": "handoff_packet + recent_evidence + tool_usage_report",
        "anti_patterns": [
            "Do not handoff without including recent evidence",
            "Do not use wrong budget profile for target model",
        ],
    },
    "work-close": {
        "expected_input": "session_id, optional outcome string",
        "decision_tree": {
            "has_session": "End session, sync case, suggest case record",
            "no_session": "Skip session end, still run health check",
            "error_outcome": "Include error details in outcome for future reference",
        },
        "output_format": "session_end + sync_case + optional case_record",
        "anti_patterns": [
            "Do not close without syncing case artifacts",
            "Do not lose error context in outcome summary",
        ],
    },
    "work-health": {
        "expected_input": "optional workspace path",
        "decision_tree": {
            "healthy": "Run status + tool_usage_report + regression_suite",
            "degraded": "Focus on failing checks, skip redundant reports",
            "no_workspace": "Auto-detect workspace from current directory",
        },
        "output_format": "status + tool_usage_report + regression_results",
        "anti_patterns": [
            "Do not skip regression suite even if status looks healthy",
            "Do not ignore tool_usage_report warnings",
        ],
    },
}


def get_workflow_template(workflow_name: str) -> dict[str, Any] | None:
    """Get the template for a workflow command."""
    return WORKFLOW_TEMPLATES.get(workflow_name)


def get_workflow_guidance(workflow_name: str, context: dict[str, Any] | None = None) -> str:
    """Get condensed guidance string for a workflow, suitable for MCP response metadata."""
    template = WORKFLOW_TEMPLATES.get(workflow_name)
    if not template:
        return ""

    parts = [f"Workflow: {workflow_name}"]
    parts.append(f"Input: {template['expected_input']}")

    # Add relevant decision based on context
    decision_tree = template.get("decision_tree", {})
    if context and decision_tree:
        for key, guidance in decision_tree.items():
            if key in str(context):
                parts.append(f"Decision ({key}): {guidance}")
                break
        else:
            # Default to first decision
            first_key = next(iter(decision_tree))
            parts.append(f"Default: {decision_tree[first_key]}")

    # Add top anti-pattern
    anti_patterns = template.get("anti_patterns", [])
    if anti_patterns:
        parts.append(f"Avoid: {anti_patterns[0]}")

    return " | ".join(parts)


# ---- Constraint Templates (mattpocock/skills inspired) ----

CONSTRAINT_TEMPLATES: dict[str, dict[str, Any]] = {
    "coding_agent": {
        "description": "Standard coding agent protocol",
        "work_protocol": {
            "start": {
                "required": ["mc_start"],
                "optional": ["mc_lookup(mode=auto)"],
                "when": "Beginning any coding task",
            },
            "during": {
                "required": ["mc_analyze(before edits)"],
                "optional": ["mc_sync(periodic)"],
                "when": "Active coding phase",
            },
            "end": {
                "required": ["mc_close"],
                "optional": ["mc_admin(action=health)"],
                "when": "Task complete or session ending",
            },
        },
        "auto_select_strategy": {
            "new_intent": "mc_start",
            "code_lookup": "mc_lookup(mode=auto)",
            "before_edit": "mc_analyze",
            "resume_work": "mc_resume",
            "switch_model": "mc_handoff",
            "check_health": "mc_admin(action=health)",
        },
        "constraints": [
            "Always sniff before coding to understand context",
            "Always analyze before editing to check impact",
            "Always close session to preserve memory",
        ],
    },
    "review_agent": {
        "description": "Code review agent protocol",
        "work_protocol": {
            "start": {
                "required": ["mc_start"],
                "optional": ["mc_lookup(mode=chain, scope=cross-service)"],
                "when": "Beginning code review",
            },
            "during": {
                "required": ["mc_analyze(depth=full)"],
                "optional": ["mc_lookup(mode=context)"],
                "when": "Reviewing code changes",
            },
            "end": {
                "required": ["mc_close"],
                "optional": ["mc_admin(action=audit)"],
                "when": "Review complete",
            },
        },
        "auto_select_strategy": {
            "new_review": "mc_start",
            "check_impact": "mc_analyze(depth=full)",
            "trace_chain": "mc_lookup(mode=chain)",
            "check_contracts": "mc_lookup(mode=contracts)",
        },
        "constraints": [
            "Use full-depth analysis for review",
            "Check cross-service impact for any API changes",
            "Verify contract compatibility",
        ],
    },
    "quick_lookup": {
        "description": "Quick lookup protocol for fast queries",
        "work_protocol": {
            "lookup": {
                "required": ["mc_lookup(mode=auto)"],
                "optional": [],
                "when": "Need to find code, symbols, or relationships",
            },
        },
        "auto_select_strategy": {
            "find_class": "mc_lookup(mode=symbol)",
            "find_code": "mc_lookup(mode=code)",
            "find_caller": "mc_lookup(mode=chain)",
            "find_contract": "mc_lookup(mode=contracts)",
        },
        "constraints": [
            "Use auto mode for best routing",
            "Use compact view for faster responses",
        ],
    },
}


def get_constraint_template(template_name: str) -> dict[str, Any] | None:
    """Get a constraint template by name."""
    return CONSTRAINT_TEMPLATES.get(template_name)


def auto_select_action(context: str, template_name: str = "coding_agent") -> str | None:
    """Auto-select the best action based on context and template strategy.

    Args:
        context: Description of what the user wants to do
        template_name: Which constraint template to use

    Returns:
        Recommended action string, or None if no match
    """
    template = CONSTRAINT_TEMPLATES.get(template_name)
    if not template:
        return None

    strategy = template.get("auto_select_strategy", {})
    context_lower = context.lower()

    # Match context to strategy keywords
    keyword_map = {
        "new_intent": ["start", "begin", "new task", "开始"],
        "code_lookup": ["find", "search", "look", "查", "找"],
        "before_edit": ["edit", "change", "modify", "改", "修改"],
        "resume_work": ["resume", "continue", "继续", "恢复"],
        "switch_model": ["handoff", "switch", "切换"],
        "check_health": ["health", "status", "健康"],
        "check_impact": ["impact", "affect", "影响"],
        "trace_chain": ["chain", "caller", "callee", "调用链"],
        "check_contracts": ["contract", "feign", "api", "契约"],
    }

    for key, keywords in keyword_map.items():
        if any(kw in context_lower for kw in keywords):
            action = strategy.get(key)
            if action:
                return action

    # Default: return the first strategy entry
    if strategy:
        return next(iter(strategy.values()))
    return None
