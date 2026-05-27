from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from .schemas import with_schema

def build_finding(severity: str, code: str, message: str) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
    }


def score_to_quality(score: int) -> str:
    if score >= 85:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


@dataclass
class EvalResultBuilder:
    initial_score: int = 100
    findings: List[Dict[str, Any]] = field(default_factory=list)
    score: int = field(init=False)

    def __post_init__(self) -> None:
        self.score = self.initial_score

    def add(self, severity: str, code: str, message: str, penalty: int) -> None:
        self.findings.append(build_finding(severity, code, message))
        self.score -= penalty

    def finalize(self, **payload: Any) -> Dict[str, Any]:
        final_score = max(0, self.score)
        return with_schema(
            "eval_result",
            {
            **payload,
            "score": final_score,
            "quality": score_to_quality(final_score),
            "findings": self.findings,
            },
        )


def eval_workflow_orchestration(tool_events: List[Dict[str, Any]], intent: str = "") -> Dict[str, Any]:
    """Evaluate whether a workflow follows the recommended start→log→sync→close pattern."""
    builder = EvalResultBuilder()
    event_types = [str(e.get("event_type", "") or e.get("type", "")) for e in tool_events]
    tool_names = [str(e.get("tool_name", "") or e.get("payload", {}).get("tool_name", "")) for e in tool_events]

    has_start = any("work-start" in t or "workspace_sniff" in t or "workspace_start_session" in t for t in tool_names)
    has_log = any("work-log" in t or "workspace_log_session_event" in t or "session_event" in et for t, et in __import__("itertools").zip_longest(tool_names, event_types, fillvalue=""))
    has_sync = any("work-sync" in t or "sync_sniff" in t or "sync_case" in t for t in tool_names)
    has_close = any("work-close" in t or "workspace_end_session" in t or "workspace_suggest_case" in t for t in tool_names)
    has_lookup = any(t in {"memory_symbol_tool", "memory_query_tool", "workspace_trace_tool", "memory_callers_tool", "memory_callees_tool"} for t in tool_names)

    if not has_start:
        builder.add("medium", "no_work_start", "Workflow lacks a work-start/sniff step.", 20)
    if not has_log:
        builder.add("low", "no_work_log", "No session events logged during workflow.", 10)
    if not has_sync:
        builder.add("low", "no_work_sync", "No sync step to persist context into task space.", 15)
    if not has_close:
        builder.add("medium", "no_work_close", "Workflow does not have a close/end step.", 20)
    if not has_lookup:
        builder.add("low", "no_lookup_in_workflow", "No Memory Center lookup tools used during the workflow.", 10)

    return builder.finalize(
        intent=intent,
        has_start=has_start,
        has_log=has_log,
        has_sync=has_sync,
        has_close=has_close,
        has_lookup=has_lookup,
        event_count=len(tool_events),
    )
