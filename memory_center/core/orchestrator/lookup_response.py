"""Response envelope, guidance and telemetry for hybrid lookup."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from memory_center.core.assessment.quality import build_quality_summary
from memory_center.core.foundation.result_types import attach_facade_metadata
from memory_center.core.observability.diagnostics import DIAG, diag_entry
from memory_center.core.storage.workspace import WorkspaceStore


def finalize_hybrid_response(
    result: dict[str, Any], *, store: WorkspaceStore, workspace_file: str | Path,
    query: str, effective_project: str, freshness_banner: dict[str, Any], session_id: str,
    timings: dict[str, float], elapsed: Callable[[float], float], started: float, phase_started: float,
    guidance_builder: Callable[..., list[dict[str, Any]]], record_delivery: Callable[..., None],
) -> dict[str, Any]:
    """Attach backward-compatible quality, guidance, observability and envelope fields."""
    try:
        result["freshness"] = freshness_banner
        status = (freshness_banner.get("freshness", {}) or {}).get("status", "unknown")
        if status in ("stale", "pending"):
            from ..freshness.integration import freshness_action_hint, freshness_risk_escalation

            result["_freshness_warning"] = {
                "status": status, "hint": freshness_action_hint(status),
                "risk_escalation": freshness_risk_escalation(result.get("intent_analysis", {}).get("risk_level", "low"), status),
            }
    except Exception as exc:
        result["freshness"] = diag_entry(DIAG.UNKNOWN, exc=exc)
    try:
        from memory_center.core.observability.metrics import MetricsCollector

        MetricsCollector(workspace_file).record("memory_query_hybrid", len(json.dumps(result, ensure_ascii=False)), unit="chars")
    except Exception:
        pass
    freshness_status = str(((result.get("freshness", {}) or {}).get("freshness", {}) or {}).get("status", "unknown"))
    # L0.5 Session Notes: merge bounded note hits so query/evidence-index see
    # narrative memory alongside graph evidence (fail-soft on any note error).
    try:
        from memory_center.core.tasks.session_notes import search_notes

        note_hits = search_notes(workspace_file, query, limit=5)
        if note_hits:
            result["note_matches"] = note_hits
            merged = [
                *(result.get("results", []) or []),
                *[
                    {
                        "node_id": hit["note_id"],
                        "node": {"type": "Note", "name": hit["text"], "project": "", "file_path": ""},
                        "score": hit["score"],
                        "sources": ["note"],
                        "semantic_strength": "fact",
                        "evidence_level": "EXTRACTED",
                        "created_at": hit.get("created_at", ""),
                        "source_layer": "L0.5_session_notes",
                        "source_kind": "note",
                    }
                    for hit in note_hits
                ],
            ]
            result["results"] = merged
            # matches is a documented alias of results (backward compat).
            if "matches" in result:
                result["matches"] = merged
    except Exception:
        pass
    evidence = []
    for item in result.get("results", []) or []:
        sources = set(item.get("sources", []) or item.get("retrieval_sources", []) or [])
        evidence.append({"confidence": item.get("score", 0.0),
                         "evidence_type": "fact" if sources & {"exact", "graph_exact", "direct_lookup"} else "inferred",
                         "evidence_level": item.get("evidence_level", ""), "_is_fallback": bool(item.get("_is_fallback", False))})
    result["_quality"] = build_quality_summary(evidence, freshness_status=freshness_status)
    result["agent_next_steps"] = guidance_builder(result, query=query, workspace_file=workspace_file)
    try:
        from memory_center.core.knowledge.governance import record_actions

        result["agent_actions"] = record_actions(store, origin=f"memory_query_hybrid:{query}", actions=list(result["agent_next_steps"]))
    except Exception:
        result["agent_actions"] = []
    timings["quality_and_actions"] = elapsed(phase_started)
    result = attach_facade_metadata(result, operation="memory_query_hybrid", result_kind="lookup", evidence_level="hybrid_indexed")
    from memory_center.core.knowledge.state import attach_knowledge_state

    result = attach_knowledge_state(store, result, query=query, project=effective_project, mode="memory_query_hybrid")
    result["performance"] = {"timing_ms": {**timings, "total": elapsed(started)}}
    record_delivery(workspace_file, session_id, result)
    return result


__all__ = ["finalize_hybrid_response"]
