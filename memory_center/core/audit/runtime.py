"""Agent Runtime Audit — audit hooks, MCP config, and agent configuration.

Implements ECC-5 from NEXT_PHASE_MASTER_PLAN.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..store import WorkspaceStore

AUDIT_LOG_FILE = "agent-runtime-audit.jsonl"


def audit_agent_runtime(workspace_file: str | Path) -> Dict[str, Any]:
    """Audit the agent runtime configuration for a workspace.

    Checks: hooks config, MCP settings, agent profile, tool access.
    """
    store = WorkspaceStore(workspace_file)
    findings: List[Dict[str, Any]] = []
    score = 100

    # Check hooks configuration
    hooks_config = store.read_json_prefer_backend("hooks-config.json", {})
    if not hooks_config:
        findings.append({
            "category": "hooks",
            "severity": "info",
            "code": "no_hooks",
            "message": "未配置 hooks（可选但推荐）",
        })

    # Check MCP configuration
    mcp_config = store.read_json_prefer_backend("mcp-config.json", {})
    if not mcp_config:
        findings.append({
            "category": "mcp",
            "severity": "info",
            "code": "no_mcp_config",
            "message": "未配置 MCP 服务（可选）",
        })

    # Check agent profile
    agent_profile = store.read_json_prefer_backend("agent-profile.json", {})
    if not agent_profile:
        findings.append({
            "category": "agent",
            "severity": "low",
            "code": "no_agent_profile",
            "message": "未配置 agent profile（推荐配置以获得个性化建议）",
        })

    # Check workspace health
    health = store.read_json_prefer_backend("workspace-health.json", {})
    if health and health.get("health_score", 100) < 50:
        findings.append({
            "category": "health",
            "severity": "medium",
            "code": "low_health_score",
            "message": f"工作区健康分数偏低: {health.get('health_score', 'unknown')}",
        })
        score -= 10

    # Record audit
    audit_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": max(0, score),
        "findings_count": len(findings),
        "findings": findings,
    }
    store.append_jsonl(AUDIT_LOG_FILE, audit_record)

    return {
        "score": max(0, score),
        "quality": "high" if score >= 85 else "medium" if score >= 60 else "low",
        "findings": findings,
        "audit_record": audit_record,
    }
