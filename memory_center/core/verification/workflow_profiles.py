"""Workflow Protocol Profiles — map task types to recommended tool sequences.

Implements ECC-1 from NEXT_PHASE_MASTER_PLAN.md.
Provides structured workflow protocols for common coding tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .heuristics import _merge_weight, candidate_path_learning_index, load_learning_policy


@dataclass
class WorkflowProfile:
    """A workflow protocol profile for a specific task type."""
    name: str
    description: str
    steps: list[dict[str, str]] = field(default_factory=list)
    applicable_when: list[str] = field(default_factory=list)
    tools_sequence: list[str] = field(default_factory=list)


# Built-in workflow profiles
BUILTIN_PROFILES: dict[str, WorkflowProfile] = {
    "quick-fix": WorkflowProfile(
        name="quick-fix",
        description="小范围 bug 修复或配置变更",
        steps=[
            {"step": "定位", "tool": "mc_lookup", "description": "定位问题代码"},
            {"step": "分析", "tool": "mc_analyze", "description": "检查影响面"},
            {"step": "修改", "tool": "直接编辑", "description": "最小化变更"},
            {"step": "验证", "tool": "测试", "description": "运行相关测试"},
            {"step": "关闭", "tool": "mc_close", "description": "记录变更"},
        ],
        applicable_when=["bugfix", "config_change", "hotfix"],
        tools_sequence=["mc_lookup", "mc_analyze", "edit", "test", "mc_close"],
    ),
    "contract-change": WorkflowProfile(
        name="contract-change",
        description="涉及 Feign/DTO/API 契约的变更",
        steps=[
            {"step": "定位", "tool": "mc_lookup", "description": "定位契约实体"},
            {"step": "分析", "tool": "mc_analyze", "description": "检查跨服务影响"},
            {"step": "查看链路", "tool": "group_chain", "description": "追踪跨项目链路"},
            {"step": "修改", "tool": "编辑", "description": "修改契约 + 上下游"},
            {"step": "回归", "tool": "测试", "description": "全量回归测试"},
            {"step": "关闭", "tool": "mc_close", "description": "记录变更"},
        ],
        applicable_when=["feign_change", "dto_change", "api_change", "contract_change"],
        tools_sequence=["mc_lookup", "mc_analyze", "group_chain", "edit", "test", "mc_close"],
    ),
    "long-task": WorkflowProfile(
        name="long-task",
        description="跨多文件、多会话的长期任务",
        steps=[
            {"step": "启动", "tool": "mc_start", "description": "创建任务空间"},
            {"step": "调研", "tool": "mc_lookup", "description": "收集上下文"},
            {"step": "方案", "tool": "mc_analyze", "description": "影响分析 + 方案设计"},
            {"step": "实现", "tool": "mc_sync", "description": "分步实现 + 同步"},
            {"step": "验证", "tool": "验证循环", "description": "结构化验证"},
            {"step": "交接", "tool": "mc_handoff", "description": "跨模型交接"},
            {"step": "关闭", "tool": "mc_close", "description": "任务收尾"},
        ],
        applicable_when=["feature", "refactor", "migration", "architecture_change"],
        tools_sequence=["mc_start", "mc_lookup", "mc_analyze", "mc_sync", "verify", "mc_handoff", "mc_close"],
    ),
    "architecture": WorkflowProfile(
        name="architecture",
        description="架构级变更或新模块引入",
        steps=[
            {"step": "调研", "tool": "mc_lookup + group_status", "description": "了解全貌"},
            {"step": "影响", "tool": "mc_analyze + group_impact", "description": "跨项目影响分析"},
            {"step": "设计", "tool": "文档", "description": "写 ADR / 设计文档"},
            {"step": "实现", "tool": "mc_sync", "description": "分步实现"},
            {"step": "审计", "tool": "run_completion_audit", "description": "架构审计"},
            {"step": "关闭", "tool": "mc_close", "description": "记录决策"},
        ],
        applicable_when=["new_module", "architectural_decision", "major_refactor"],
        tools_sequence=["mc_lookup", "group_status", "mc_analyze", "group_impact", "doc", "mc_sync", "audit", "mc_close"],
    ),
}

_BUGFIX_KEYWORDS = ("bug", "fix", "修复", "hotfix", "配置")
_CONTRACT_KEYWORDS = ("feign", "dto", "契约", "api", "contract")
_ARCHITECTURE_KEYWORDS = ("架构", "重构", "migration", "新模块", "architecture")
_WORKFLOW_PRIORITY = {
    "contract-change": 0,
    "architecture": 1,
    "long-task": 2,
    "quick-fix": 3,
}


def get_workflow_profile(task_type: str) -> WorkflowProfile | None:
    """Get a workflow profile by task type."""
    return BUILTIN_PROFILES.get(task_type)


def _has_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def recommend_workflow(task_description: str, available_tools: list[str] | None = None) -> WorkflowProfile:
    """Recommend a workflow profile based on task description."""
    desc_lower = task_description.lower()
    has_contract = _has_any_keyword(desc_lower, _CONTRACT_KEYWORDS)
    has_architecture = _has_any_keyword(desc_lower, _ARCHITECTURE_KEYWORDS)
    has_bugfix = _has_any_keyword(desc_lower, _BUGFIX_KEYWORDS)

    # 契约变更优先于泛化 bugfix；架构类问题优先于普通长期任务。
    if has_contract:
        return BUILTIN_PROFILES["contract-change"]
    if has_architecture:
        return BUILTIN_PROFILES["architecture"]
    if has_bugfix:
        return BUILTIN_PROFILES["quick-fix"]
    return BUILTIN_PROFILES["long-task"]


def recommend_workflow_with_learning(
    workspace_file: str | Path,
    task_description: str,
    available_tools: list[str] | None = None,
) -> dict[str, Any]:
    """Recommend a workflow profile using static heuristics plus learned profile preference."""
    base_profile = recommend_workflow(task_description, available_tools=available_tools)
    candidates = _build_workflow_profile_candidates(task_description, base_profile.name)
    learning_index = candidate_path_learning_index(workspace_file)
    policy = load_learning_policy(workspace_file)

    adjusted_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        learning = learning_index.get(("workflow_profile", item["name"]))
        item["learning_applied"] = learning is not None
        if learning is not None:
            learned_weight = float(learning.get("recommended_weight", learning.get("confidence", item["weight"])) or item["weight"])
            item["learned_recommended_weight"] = learned_weight
            item["learning_state"] = str(learning.get("recommendation_state", "") or "")
            item["learning_guard_reason"] = str(learning.get("guard_reason", "") or "")
            item["weight"] = round(
                _merge_weight(policy, kind="workflow_profile", base_weight=float(item["weight"]), learned_weight=learned_weight),
                2,
            )
            if item["learning_state"] == "rolled-back":
                item["status"] = "possible"
        adjusted_candidates.append(item)

    adjusted_candidates.sort(
        key=lambda item: (
            -float(item.get("weight", 0.0)),
            _WORKFLOW_PRIORITY.get(str(item.get("name", "") or ""), 99),
            item.get("name", ""),
        )
    )
    top = adjusted_candidates[0]
    for item in adjusted_candidates:
        item["status"] = "probable" if item["name"] == top["name"] else "possible"
        if item.get("learning_state") == "rolled-back":
            item["status"] = "possible"
    profile = BUILTIN_PROFILES[top["name"]]
    return {
        "recommended_profile": profile.name,
        "description": profile.description,
        "tools_sequence": profile.tools_sequence,
        "steps": [s.get("step", "") for s in profile.steps],
        "learning_applied": top.get("learning_applied", False),
        "learning_state": top.get("learning_state", ""),
        "learning_guard_reason": top.get("learning_guard_reason", ""),
        "learned_recommended_weight": top.get("learned_recommended_weight"),
        "candidate_profiles": adjusted_candidates,
    }


def _build_workflow_profile_candidates(task_description: str, recommended_name: str) -> list[dict[str, Any]]:
    desc_lower = task_description.lower()
    scores = {
        "quick-fix": 0.58,
        "contract-change": 0.58,
        "long-task": 0.62,
        "architecture": 0.56,
    }

    has_bugfix = _has_any_keyword(desc_lower, _BUGFIX_KEYWORDS)
    has_contract = _has_any_keyword(desc_lower, _CONTRACT_KEYWORDS)
    has_architecture = _has_any_keyword(desc_lower, _ARCHITECTURE_KEYWORDS)

    if has_bugfix:
        scores["quick-fix"] = 0.92
        scores["long-task"] = max(scores["long-task"], 0.54)
    if has_contract:
        scores["contract-change"] = 0.96 if has_bugfix else 0.92
        scores["quick-fix"] = max(scores["quick-fix"], 0.6)
    if has_architecture:
        scores["architecture"] = 0.92
        scores["long-task"] = max(scores["long-task"], 0.7)
    if recommended_name == "long-task":
        scores["long-task"] = max(scores["long-task"], 0.86)

    candidates: list[dict[str, Any]] = []
    for name, profile in BUILTIN_PROFILES.items():
        candidates.append(
            {
                "name": name,
                "description": profile.description,
                "status": "probable" if name == recommended_name else "possible",
                "weight": round(scores.get(name, 0.58), 2),
                "why": "静态规则认为该 workflow 与当前任务描述最匹配。" if name == recommended_name else "作为备选 workflow 保留，用于学习修正优先级。",
            }
        )
    return candidates
