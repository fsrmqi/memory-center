"""Agent Runtime Audit — audit hooks, MCP config, and agent configuration.

Implements ECC-5 from NEXT_PHASE_MASTER_PLAN.md.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_center.core.governance.instructions import inspect_agent_mcp_bindings, repair_agent_mcp_bindings
from memory_center.core.governance.rules import ensure_default_rules
from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config
from memory_center.core.workspace.doctor import doctor

from ..tasks.artifacts import ensure_default_artifacts
from ..verification.heuristics import apply_candidate_path_learning
from .hook_config import ensure_default_hooks

AUDIT_LOG_FILE = "agent-runtime-audit.jsonl"


def setup_agent_runtime(workspace_file: str | Path) -> dict[str, Any]:
    """Prepare host-agent integration for a workspace in one explicit step."""
    config = load_workspace_config(workspace_file)
    store = WorkspaceStore(workspace_file)
    ensure_default_rules(store)
    ensure_default_hooks(store)
    ensure_default_artifacts(workspace_file)
    audit = audit_agent_runtime(workspace_file, fix=True)
    mcp_bindings = audit.get("mcp_bindings", {}) or {}
    next_steps = [
        "如果当前 Codex / Cursor / Claude Code / DSH 会话已经启动，请重启或刷新宿主会话，让新的 MCP 配置生效。",
        "5.0 的 MCP 入口是常驻服务的统一端点，不再按子项目绑定 workspace 文件；项目匹配在 mc_workspaces() 的返回结果里选择。",
    ]
    if not mcp_bindings.get("ok", False):
        next_steps.insert(0, f"请确认 Memory Center 服务在 {mcp_bindings.get('mcp_url', '')} 可达，再重启宿主会话。")
    return {
        "workflow": "setup-agent",
        "workspace": config.workspace,
        "workspace_file": str(Path(workspace_file).expanduser().resolve()),
        "workspace_root": str(Path(config.root_path).expanduser().resolve()),
        "mcp_bindings": mcp_bindings,
        "audit": audit,
        "requires_host_reload": True,
        "next_steps": next_steps,
    }


def audit_agent_runtime(
    workspace_file: str | Path,
    fix: bool = False,
    *,
    record: bool = True,
) -> dict[str, Any]:
    """Audit the agent runtime configuration for a workspace.

    Checks: hooks config, MCP settings, agent profile, tool access.
    """
    store = WorkspaceStore(workspace_file)
    findings: list[dict[str, Any]] = []
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

    config = load_workspace_config(workspace_file)
    if fix:
        mcp_bindings = repair_agent_mcp_bindings(store, config.root_path)
    else:
        mcp_bindings = inspect_agent_mcp_bindings(store, config.root_path)

    # Check MCP configuration at the files real hosts read.
    if not mcp_bindings.get("ok", False):
        missing_count = len(mcp_bindings.get("missing_or_stale", []) or [])
        findings.append({
            "category": "mcp",
            "severity": "high",
            "code": "mcp_binding_missing_or_stale",
            "message": f"发现 {missing_count} 个 agent MCP 绑定缺失或未指向当前服务端点 {mcp_bindings.get('mcp_url', '')}。",
        })
        score -= 20

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

    workspace_doctor = doctor(workspace_file, self_test=False)
    workspace_shape = workspace_doctor.get("workspace_shape", {}) or {}
    suggested_fixes = workspace_doctor.get("suggested_fixes", []) or []
    advisories = workspace_doctor.get("advisories", []) or []
    failed_checks = [item for item in workspace_doctor.get("checks", []) if not item.get("ok")]

    for advisory in advisories:
        findings.append(
            {
                "category": advisory.get("category", "workspace"),
                "severity": advisory.get("severity", "medium"),
                "code": advisory.get("code", ""),
                "message": advisory.get("message", ""),
            }
        )

    risk_level = workspace_shape.get("risk_level", "low")
    if risk_level == "high":
        score -= 15
    elif risk_level == "medium":
        score -= 8

    if failed_checks and not workspace_doctor.get("ok", True):
        findings.append(
            {
                "category": "workspace",
                "severity": "medium" if risk_level != "high" else "high",
                "code": "workspace_doctor_failed",
                "message": f"workspace 健康检查存在 {len(failed_checks)} 个未通过项，建议优先处理 service root 与索引健康问题。",
            }
        )
    candidate_paths = _build_runtime_audit_candidate_paths(
        findings=findings,
        workspace_shape=workspace_shape,
        suggested_fixes=suggested_fixes,
        doctor_hint=workspace_doctor.get("hint", ""),
    )
    candidate_paths = apply_candidate_path_learning(workspace_file, candidate_paths)
    recommended_path = dict(candidate_paths[0]) if candidate_paths else {}

    # Record audit
    audit_record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": max(0, score),
        "findings_count": len(findings),
        "findings": findings,
        "workspace_shape_risk_level": workspace_shape.get("risk_level", "low"),
        "suggested_fix_count": len(suggested_fixes),
    }
    if record:
        store.append_jsonl(AUDIT_LOG_FILE, audit_record)

    return {
        "score": max(0, score),
        "quality": "high" if score >= 85 else "medium" if score >= 60 else "low",
        "findings": findings,
        "workspace_shape": workspace_shape,
        "mcp_bindings": mcp_bindings,
        "auto_fixed": bool(fix),
        "suggested_fixes": suggested_fixes,
        "candidate_paths": candidate_paths,
        "recommended_path": recommended_path,
        "doctor_hint": workspace_doctor.get("hint", ""),
        "audit_record": audit_record,
    }


def _build_runtime_audit_candidate_paths(
    *,
    findings: list[dict[str, Any]],
    workspace_shape: dict[str, Any],
    suggested_fixes: list[dict[str, Any]],
    doctor_hint: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    risk_level = str(workspace_shape.get("risk_level", "low") or "low")
    if suggested_fixes:
        first_fix = suggested_fixes[0]
        candidates.append(
            {
                "candidate_type": "workspace_fix",
                "target": first_fix.get("parent_service") or first_fix.get("root") or first_fix.get("keep_service") or "",
                "status": "confirmed" if risk_level in {"high", "medium"} else "probable",
                "weight": 0.95 if risk_level == "high" else 0.88 if risk_level == "medium" else 0.76,
                "why": doctor_hint or "当前最应该先处理的是 workspace 配置冲突或结构风险。",
                "next_action": "先按 suggested_fixes 收敛 workspace 配置，再运行 reindex",
                "verification_cost": "medium",
                "fix_code": first_fix.get("code", ""),
                "_learning_aliases": [
                    {
                        "candidate_type": "workspace_fix",
                        "target": first_fix.get("parent_service") or first_fix.get("root") or first_fix.get("keep_service") or "",
                    }
                ],
            }
        )

    if risk_level != "low":
        candidates.append(
            {
                "candidate_type": "doctor_followup",
                "target": risk_level,
                "status": "probable",
                "weight": 0.8 if risk_level == "medium" else 0.9,
                "why": f"workspace_shape 风险等级为 {risk_level}，在修复结构问题前其余治理动作收益较低。",
                "next_action": "优先处理 runtime-audit / doctor 返回的结构化治理建议",
                "verification_cost": "low",
                "_learning_aliases": [
                    {"candidate_type": "workspace_fix", "target": risk_level},
                ],
            }
        )

    if not suggested_fixes:
        candidates.append(
            {
                "candidate_type": "runtime_governance",
                "target": "hooks-mcp-agent-profile",
                "status": "possible",
                "weight": 0.66,
                "why": "workspace 结构已基本健康，后续治理重点转向 hooks、MCP 和 agent profile 配置。",
                "next_action": "按 findings 补 hooks / MCP / agent profile",
                "verification_cost": "low",
                "_learning_aliases": [
                    {"candidate_type": "runtime_governance", "target": "hooks-mcp-agent-profile"},
                ],
            }
        )

    if any(item.get("code") == "mcp_binding_missing_or_stale" for item in findings):
        candidates.append(
            {
                "candidate_type": "agent_mcp_repair",
                "target": "memory-center",
                "status": "confirmed",
                "weight": 0.92,
                "why": "当前 agent 实际读取的 MCP 配置缺失或未指向本 workspace，子项目里会看不到 mc_* 工具。",
                "next_action": "运行 `memory-center runtime-audit --workspace <workspace.yaml> --fix` 自动补齐根目录和子项目 MCP 绑定",
                "verification_cost": "low",
                "_learning_aliases": [
                    {"candidate_type": "runtime_governance", "target": "hooks-mcp-agent-profile"},
                ],
            }
        )

    if any(item.get("code") == "low_health_score" for item in findings):
        candidates.append(
            {
                "candidate_type": "reindex_or_health_repair",
                "target": "workspace-health",
                "status": "possible",
                "weight": 0.72,
                "why": "当前已有 workspace health 低分信号，先恢复索引和健康状态可以减少后续噪声。",
                "next_action": "运行 reindex 或补齐 workspace-health 所需数据",
                "verification_cost": "medium",
            }
        )

    return sorted(
        candidates,
        key=lambda item: (
            0 if item.get("status") == "confirmed" else 1 if item.get("status") == "probable" else 2,
            -float(item.get("weight", 0.0)),
            item.get("candidate_type", ""),
        ),
    )
