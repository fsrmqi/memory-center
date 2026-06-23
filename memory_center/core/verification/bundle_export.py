"""Agent Usage Bundle Export — export best practices as installable bundles.

Implements ECC-6 from NEXT_PHASE_MASTER_PLAN.md.
Exports agent usage bundles for Codex / Claude Code / Cursor.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..store import WorkspaceStore
from .workflow_profiles import BUILTIN_PROFILES


def generate_agent_bundle(workspace_file: str | Path, agent: str = "codex") -> dict[str, Any]:
    """Generate an agent usage bundle for the specified agent platform.

    Args:
        workspace_file: Workspace configuration file path
        agent: Target agent platform (codex | claude | cursor)
    """
    store = WorkspaceStore(workspace_file)

    # Collect rules, profiles, and context
    rules = store.read_json_prefer_backend("rules.json", [])
    profiles = {k: v.__dict__ if hasattr(v, '__dict__') else v for k, v in BUILTIN_PROFILES.items()}

    bundle = {
        "bundle_version": "1.0.0",
        "agent": agent,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contents": {
            "workflow_profiles": profiles,
            "rules_count": len(rules),
            "recommended_startup": "mc_start",
            "recommended_lookup": "mc_lookup",
            "recommended_analyze": "mc_analyze",
            "recommended_close": "mc_close",
        },
        "agent_specific": _get_agent_specific_config(agent),
    }

    return bundle


def _get_agent_specific_config(agent: str) -> dict[str, Any]:
    """Get agent-specific configuration recommendations."""
    configs = {
        "codex": {
            "mcp_config_path": ".codex/mcp.json",
            "instructions_path": "AGENTS.md",
            "recommended_skills": ["memory-center"],
            "hooks": ["post-edit: mc_sync", "pre-close: mc_close"],
        },
        "claude": {
            "mcp_config_path": ".mcp.json",
            "instructions_path": "CLAUDE.md",
            "recommended_skills": ["memory-center"],
            "hooks": ["post-tool: mc_sync"],
        },
        "cursor": {
            "mcp_config_path": ".cursor/mcp.json",
            "instructions_path": ".cursorrules",
            "recommended_skills": ["memory-center"],
            "hooks": [],
        },
    }
    return configs.get(agent, configs["codex"])
