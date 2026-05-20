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
}


def schema_meta(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "version": SCHEMA_VERSIONS.get(name, 1),
    }


def with_schema(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": schema_meta(name),
        **payload,
    }
