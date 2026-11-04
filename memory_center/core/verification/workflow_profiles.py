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
    context_layers: list[dict[str, str]] = field(default_factory=list)
    delivery_guardrails: list[str] = field(default_factory=list)


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
        context_layers=[
            {"layer": "workspace_rules", "when": "开始前", "purpose": "读取稳定规则和禁动边界。"},
            {"layer": "change_scope", "when": "修改前", "purpose": "只加载当前目标和直接影响证据。"},
        ],
        delivery_guardrails=["先确认影响范围，再进行最小修改。", "验证失败时停止扩大修改范围。"],
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
        context_layers=[
            {"layer": "workspace_rules", "when": "开始前", "purpose": "读取跨服务规则和兼容策略。"},
            {"layer": "architecture", "when": "分析时", "purpose": "加载调用链、契约关系和上下游证据。"},
            {"layer": "change_scope", "when": "实现前", "purpose": "加载任务读写边界和验收条件。"},
        ],
        delivery_guardrails=["必须记录上下游代码目标。", "未完成契约验证不得关闭任务。"],
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
        context_layers=[
            {"layer": "workspace_rules", "when": "启动时", "purpose": "加载稳定规则、团队约束和现行决策。"},
            {"layer": "architecture", "when": "定位时", "purpose": "按需加载图谱关系、模块边界和影响证据。"},
            {"layer": "change_contract", "when": "设计时", "purpose": "加载需求、范围、验收和未决事项。"},
            {"layer": "task_scope", "when": "实施时", "purpose": "加载当前子任务的读写目标、停止条件与验证要求。"},
        ],
        delivery_guardrails=["每个子任务先定位读写目标，再进入实现。", "跨会话只读取当前阶段所需的上下文包。", "验证失败时记录证据并回到受影响子任务。"],
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
        context_layers=[
            {"layer": "workspace_rules", "when": "开始前", "purpose": "读取稳定约束和迁移策略。"},
            {"layer": "architecture", "when": "调研时", "purpose": "加载服务拓扑、模块边界、依赖与容量证据。"},
            {"layer": "change_contract", "when": "设计时", "purpose": "加载 ADR、范围、风险和验收标准。"},
            {"layer": "task_scope", "when": "实施时", "purpose": "逐子任务限定读写范围和停止条件。"},
        ],
        delivery_guardrails=["设计结论必须关联证据或明确标为推断。", "破坏性变更必须声明停止条件和回退路径。"],
    ),
    "maintenance": WorkflowProfile(
        name="maintenance",
        description="项目健康检查、技术债治理或架构增量演进",
        steps=[
            {"step": "启动", "tool": "mc_start", "description": "创建可追溯任务空间"},
            {"step": "体检", "tool": "runtime_inspect", "description": "检查运行配置、索引、审计和任务健康"},
            {"step": "调研", "tool": "mc_lookup", "description": "定位模块、重复问题和现有约束"},
            {"step": "分析", "tool": "mc_analyze", "description": "确认候选改动的影响与风险"},
            {"step": "治理", "tool": "mc_sync", "description": "记录架构决策、任务边界和验证计划"},
            {"step": "验证", "tool": "验证循环", "description": "执行已注册验证并记录证据"},
            {"step": "关闭", "tool": "mc_close", "description": "沉淀可复用结论或后续行动"},
        ],
        applicable_when=["health_check", "maintenance", "technical_debt", "architecture_evolution", "audit"],
        tools_sequence=["mc_start", "runtime_inspect", "mc_lookup", "mc_analyze", "mc_sync", "verify", "mc_close"],
        context_layers=[
            {"layer": "workspace_rules", "when": "启动时", "purpose": "加载稳定规则、运行策略和历史决策。"},
            {"layer": "architecture", "when": "体检时", "purpose": "加载拓扑、质量指标、架构证据和已知风险。"},
            {"layer": "change_contract", "when": "立项时", "purpose": "记录治理范围、优先级、风险和验收。"},
            {"layer": "task_scope", "when": "执行时", "purpose": "对每项治理动作限定读写范围、停止条件和验证。"},
        ],
        delivery_guardrails=["体检结论与实际修改分为独立子任务。", "未确认影响前不执行大范围重构或删除。", "架构决策必须保留证据、有效期和后续验证。"],
    ),
}

_BUGFIX_KEYWORDS = ("bug", "fix", "修复", "hotfix", "配置")
_CONTRACT_KEYWORDS = ("feign", "dto", "契约", "api", "contract")
_ARCHITECTURE_KEYWORDS = ("架构", "重构", "migration", "新模块", "architecture")
_MAINTENANCE_KEYWORDS = ("健康", "巡检", "技术债", "治理", "审计", "health", "maintenance", "debt", "audit")
_WORKFLOW_PRIORITY = {
    "maintenance": 0,
    "contract-change": 1,
    "architecture": 2,
    "long-task": 3,
    "quick-fix": 4,
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
    has_maintenance = _has_any_keyword(desc_lower, _MAINTENANCE_KEYWORDS)

    # 契约变更优先于泛化 bugfix；架构类问题优先于普通长期任务。
    if has_contract:
        return BUILTIN_PROFILES["contract-change"]
    if has_architecture:
        return BUILTIN_PROFILES["architecture"]
    if has_maintenance:
        return BUILTIN_PROFILES["maintenance"]
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
            item.get("learning_state") == "rolled-back",
            -float(item.get("weight", 0.0)),
            _WORKFLOW_PRIORITY.get(str(item.get("name", "") or ""), 99),
            item.get("name", ""),
        )
    )
    top = next((item for item in adjusted_candidates if item.get("learning_state") != "rolled-back"), None)
    for item in adjusted_candidates:
        item["status"] = "probable" if top is not None and item["name"] == top["name"] else "possible"
        if item.get("learning_state") == "rolled-back":
            item["status"] = "possible"
    if top is None:
        return {
            "recommended_profile": "",
            "description": "所有工作流画像均已回滚，暂不自动推荐。",
            "tools_sequence": [],
            "steps": [],
            "learning_applied": True,
            "learning_state": "withheld_all_rolled_back",
            "learning_guard_reason": "all_workflow_profiles_rolled_back",
            "learned_recommended_weight": None,
            "candidate_profiles": adjusted_candidates,
        }
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
        "maintenance": 0.56,
    }

    has_bugfix = _has_any_keyword(desc_lower, _BUGFIX_KEYWORDS)
    has_contract = _has_any_keyword(desc_lower, _CONTRACT_KEYWORDS)
    has_architecture = _has_any_keyword(desc_lower, _ARCHITECTURE_KEYWORDS)
    has_maintenance = _has_any_keyword(desc_lower, _MAINTENANCE_KEYWORDS)

    if has_bugfix:
        scores["quick-fix"] = 0.92
        scores["long-task"] = max(scores["long-task"], 0.54)
    if has_contract:
        scores["contract-change"] = 0.96 if has_bugfix else 0.92
        scores["quick-fix"] = max(scores["quick-fix"], 0.6)
    if has_architecture:
        scores["architecture"] = 0.92
        scores["long-task"] = max(scores["long-task"], 0.7)
    if has_maintenance:
        scores["maintenance"] = 0.92
        scores["architecture"] = max(scores["architecture"], 0.68)
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
