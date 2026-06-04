"""Workflow Protocol Profiles — map task types to recommended tool sequences.

Implements ECC-1 from NEXT_PHASE_MASTER_PLAN.md.
Provides structured workflow protocols for common coding tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WorkflowProfile:
    """A workflow protocol profile for a specific task type."""
    name: str
    description: str
    steps: List[Dict[str, str]] = field(default_factory=list)
    applicable_when: List[str] = field(default_factory=list)
    tools_sequence: List[str] = field(default_factory=list)


# Built-in workflow profiles
BUILTIN_PROFILES: Dict[str, WorkflowProfile] = {
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


def get_workflow_profile(task_type: str) -> Optional[WorkflowProfile]:
    """Get a workflow profile by task type."""
    return BUILTIN_PROFILES.get(task_type)


def recommend_workflow(task_description: str, available_tools: List[str] | None = None) -> WorkflowProfile:
    """Recommend a workflow profile based on task description."""
    desc_lower = task_description.lower()
    # Simple heuristic matching
    if any(k in desc_lower for k in ["bug", "fix", "修复", "hotfix", "配置"]):
        return BUILTIN_PROFILES["quick-fix"]
    if any(k in desc_lower for k in ["feign", "dto", "契约", "api", "contract"]):
        return BUILTIN_PROFILES["contract-change"]
    if any(k in desc_lower for k in ["架构", "重构", "migration", "新模块", "architecture"]):
        return BUILTIN_PROFILES["architecture"]
    return BUILTIN_PROFILES["long-task"]
