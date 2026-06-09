from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from .models import Rule
from .store import WorkspaceStore


def _glob_match(path: str, pattern: str) -> bool:
    """Match a file path against a glob pattern, supporting ** for recursive matching."""
    from fnmatch import fnmatch
    if "**" not in pattern:
        return fnmatch(path, pattern) or fnmatch(Path(path).name, pattern)
    # Replace ** with recursive matching logic
    norm_path = path.replace("\\", "/")
    norm_pattern = pattern.replace("\\", "/")
    # Split pattern into segments around **
    parts = norm_pattern.split("**")
    if len(parts) == 2:
        prefix = parts[0].rstrip("/")
        suffix = parts[1].lstrip("/")
        if prefix and not norm_path.startswith(prefix):
            return False
        remaining = norm_path[len(prefix):].lstrip("/") if prefix else norm_path
        return fnmatch(remaining, suffix) or fnmatch(Path(remaining).name, suffix)
    # Fallback for complex ** patterns
    return fnmatch(norm_path, norm_pattern)

DEFAULT_RULES = [
    {
        "id": "MQ-001",
        "title": "MQ 消费必须保证幂等",
        "scope": ["mq", "consumer", "kafka", "rocketmq"],
        "severity": "must",
        "file_patterns": ["**/*Consumer.java", "**/*Listener.java"],
        "trigger_keywords": ["consumer", "kafka", "rocketmq", "消息", "消费", "topic"],
        "rule": "Kafka/RocketMQ 消费逻辑必须使用业务唯一键做幂等，不能只依赖 offset 或消息投递次数。",
        "reason": "重平衡、重试、网络抖动、业务异常都会导致重复消费。",
        "checklist": ["是否有业务唯一键", "是否处理重复消费", "是否记录 topic/group/msgKey", "是否有失败重试或补偿"]
    },
    {
        "id": "CONTRACT-001",
        "title": "公共契约禁止破坏性变更",
        "scope": ["contract", "common-api", "dto", "feign", "message"],
        "severity": "must",
        "file_patterns": ["**/common-api/**/*.java", "**/*Feign*.java", "**/*Message.java", "**/*DTO.java", "**/*Req.java", "**/*Resp.java"],
        "trigger_keywords": ["DTO", "Feign", "Message", "字段", "契约", "接口"],
        "rule": "Feign DTO、MQ Message、公共 Response/Request 不允许直接删除字段或修改字段语义。新增字段必须兼容历史调用方和历史消息。",
        "reason": "公共契约被多个服务依赖，破坏性修改会导致反序列化失败或运行时兼容问题。",
        "checklist": ["全 workspace 搜索字段使用点", "检查历史 MQ 消息兼容", "检查 Feign 调用方", "保留默认值策略"]
    },
    {
        "id": "ES-001",
        "title": "ES 写入必须确认别名和批量失败处理",
        "scope": ["elasticsearch", "es", "bulk"],
        "severity": "must",
        "file_patterns": ["**/*Es*.java", "**/*Elastic*.java", "**/*Search*.java"],
        "trigger_keywords": ["ES", "Elasticsearch", "索引", "bulk", "alias"],
        "rule": "涉及 ES 写入时必须确认目标索引或别名 write index，并记录 bulk item 级失败明细。",
        "reason": "多索引别名无 write index 会直接写入失败，bulk 局部失败不处理会造成数据不一致。",
        "checklist": ["是否确认 write index", "是否处理 bulk item failure", "是否有重试/降级", "是否避免超大字段 analyzed"]
    },
    {
        "id": "LOG-001",
        "title": "核心链路日志必须包含上下文标识",
        "scope": ["logging", "observability"],
        "severity": "must",
        "file_patterns": ["**/*.java"],
        "trigger_keywords": ["日志", "链路", "trace", "排查", "异常"],
        "rule": "核心业务链路日志必须包含 chainId、siteCode、uid、业务主键、阶段码和异常摘要。",
        "reason": "跨服务问题定位依赖统一上下文字段，否则线上排查成本极高。",
        "checklist": ["是否有 chainId", "是否有业务主键", "是否有阶段码", "异常是否包含上下文"]
    },
    {
        "id": "DATA-001",
        "title": "跨时间分表迁移必须保证一致性",
        "scope": ["data-migration", "sharding", "table-route"],
        "severity": "must",
        "file_patterns": ["**/*Service*.java", "**/*Repository*.java", "**/*Mapper*.java"],
        "trigger_keywords": ["oldPubTime", "newPubTime", "迁移", "分表", "跨月", "发布时间"],
        "rule": "按 oldPubTime 定位旧数据、按 newPubTime 写入新表/新索引时，必须先写新位置成功，再标记或删除旧位置，并保证重复执行安全。",
        "reason": "跨月/跨表迁移容易出现双写、漏删、重复插入、旧新不一致。",
        "checklist": ["同月迁移", "跨月迁移", "旧数据不存在", "新位置写入失败", "重复消费", "回滚/补偿"]
    }
]

DEFAULT_HANDOFF_PROFILES = {
    "profiles": {
        "codex": {
            "strengths": ["代码修改执行力强", "多文件实现推进快", "适合 task-first 交接"],
            "handoff_style": "task-first",
            "preferred_payload": ["task_id", "current_summary", "next_recommended_actions", "latest_receipts"],
            "avoid": ["过长背景铺垫", "缺少可执行动作"],
        },
        "claude-code": {
            "strengths": ["复杂上下文理解强", "风险分析与方案梳理好", "适合 context-first 交接"],
            "handoff_style": "context-first",
            "preferred_payload": ["task_title", "current_summary", "recent_evidence", "unresolved_items", "next_recommended_actions"],
            "avoid": ["只有文件列表没有原因", "缺少任务阶段说明"],
        },
        "cursor-agent": {
            "strengths": ["IDE 内短回路高效", "适合 file-first 接手", "适合跟随 task space 修改"],
            "handoff_style": "file-first",
            "preferred_payload": ["task_id", "current_summary", "recent_evidence", "next_recommended_actions"],
            "avoid": ["大段历史堆叠", "没有文件入口的抽象描述"],
        },
        "gemini": {
            "strengths": ["高层概览与长文阅读好", "适合 overview-first 接棒", "适合大范围交叉核对"],
            "handoff_style": "overview-first",
            "preferred_payload": ["task_title", "current_phase", "current_summary", "recent_evidence"],
            "avoid": ["碎片化细节堆砌", "没有总体目标"],
        },
        "deepseek": {
            "strengths": ["证据驱动推理清晰", "诊断与比较能力强", "适合 evidence-first 接手"],
            "handoff_style": "evidence-first",
            "preferred_payload": ["current_summary", "recent_evidence", "unresolved_items", "next_recommended_actions"],
            "avoid": ["无依据结论", "只给结论不附证据"],
        },
        "glm": {
            "strengths": ["中文工作流友好", "任务摘要接棒顺畅", "适合 summary-first 交接"],
            "handoff_style": "summary-first",
            "preferred_payload": ["task_title", "current_summary", "unresolved_items", "next_recommended_actions"],
            "avoid": ["结构混乱", "大量低价值日志"],
        },
        "qwen": {
            "strengths": ["中文代码协作顺滑", "说明与执行平衡好", "适合 balanced 交接"],
            "handoff_style": "balanced",
            "preferred_payload": ["task_title", "current_summary", "recent_evidence", "next_recommended_actions"],
            "avoid": ["只有抽象目标没有执行入口", "上下文缺少阶段说明"],
        },
        "minimax": {
            "strengths": ["长文摘要友好", "适合 overview + summary 混合交接"],
            "handoff_style": "overview-first",
            "preferred_payload": ["task_title", "current_phase", "current_summary", "unresolved_items"],
            "avoid": ["无重点的证据堆砌", "缺少高层目标"],
        },
        "mimo": {
            "strengths": ["轻量快速切换友好", "适合最小交接包"],
            "handoff_style": "minimal-first",
            "preferred_payload": ["task_id", "current_summary", "next_recommended_actions"],
            "avoid": ["超长上下文", "低价值历史噪声"],
        },
        "generic-mcp-agent": {
            "strengths": ["适配任意 MCP Agent", "通用性最好"],
            "handoff_style": "balanced",
            "preferred_payload": ["task_id", "current_summary", "recent_evidence", "next_recommended_actions", "latest_receipts"],
            "avoid": ["依赖特定 IDE 假设", "依赖特定模型习惯"],
        },
    }
}

DEFAULT_RESUME_RULES = {
    "default": {
        "fields": [
            "task_id",
            "task_title",
            "task_status",
            "current_phase",
            "current_summary",
            "latest_receipts",
            "recent_evidence",
            "next_recommended_actions",
            "unresolved_items",
            "verification_pending",
        ],
        "evidence_limit": 5,
        "receipt_limit": 5,
        "action_limit": 5,
        "unresolved_limit": 5,
    },
    "profiles": {
        "rule_update": {
            "trigger_keywords": ["规则", "规范", "invariant", "migration", "策略"],
            "fields": [
                "task_id",
                "task_title",
                "current_phase",
                "current_summary",
                "recent_evidence",
                "unresolved_items",
                "next_recommended_actions",
                "verification_pending",
            ],
            "evidence_limit": 6,
            "receipt_limit": 4,
            "action_limit": 6,
            "unresolved_limit": 6,
        },
        "implementation": {
            "trigger_keywords": ["修复", "改造", "实现", "开发", "需求"],
            "fields": [
                "task_id",
                "task_title",
                "task_status",
                "current_phase",
                "current_summary",
                "latest_receipts",
                "next_recommended_actions",
                "unresolved_items",
            ],
            "evidence_limit": 4,
            "receipt_limit": 6,
            "action_limit": 6,
            "unresolved_limit": 5,
        },
    },
}

DEFAULT_HANDOFF_RULES = {
    "default": {
        "done_limit": 5,
        "next_limit": 5,
        "evidence_limit": 5,
        "risk_limit": 5,
        "include_sections": [
            "what_has_been_done",
            "what_not_to_repeat",
            "what_is_risky",
            "what_to_check_next",
            "minimal_required_context",
            "recent_evidence",
            "notes",
        ],
    },
    "profiles": {
        "evidence_first": {
            "trigger_models": ["deepseek"],
            "done_limit": 4,
            "next_limit": 4,
            "evidence_limit": 8,
            "risk_limit": 6,
        },
        "task_first": {
            "trigger_models": ["codex", "cursor-agent", "mimo"],
            "done_limit": 6,
            "next_limit": 6,
            "evidence_limit": 4,
            "risk_limit": 4,
        },
        "summary_first": {
            "trigger_models": ["glm", "qwen", "minimax", "gemini", "claude-code"],
            "done_limit": 4,
            "next_limit": 5,
            "evidence_limit": 5,
            "risk_limit": 5,
        },
    },
}

DEFAULT_WRITE_POLICY_RULES = {
    "default": {
        "source_layer_boosts": {
            "tool_call": { "L0_session_events": 3 },
            "tool_result": { "L0_session_events": 3 },
            "user_prompt": { "L0_session_events": 3 },
            "note": { "L0_session_events": 3 },
            "session_event": { "L0_session_events": 3 },
        },
        "keyword_layer_boosts": [
            {
                "keywords": ["经验", "复盘", "教训", "风险", "兼容", "验证", "best practice", "lessons learned"],
                "layer": "L1_case_atoms",
                "score": 4,
                "reason": "文本包含经验/风险/验证特征，适合沉淀 L1 case。",
            },
            {
                "keywords": ["任务", "计划", "方案", "context", "plan", "design", "change log", "当前", "next step", "todo"],
                "layer": "L2_task_spaces",
                "score": 4,
                "reason": "文本包含任务执行上下文特征，适合写入 L2 task space。",
            },
            {
                "keywords": ["团队", "规范", "规则", "约束", "invariant", "workspace", "profile", "迁移策略", "migration", "governance", "guardrail"],
                "layer": "L3_workspace_profile",
                "score": 5,
                "reason": "文本包含团队规则/架构约束特征，适合写入 L3 workspace profile。",
            },
        ],
        "intent_layer_boosts": [
            {
                "keywords": ["修复", "改造", "实现", "任务", "需求"],
                "layer": "L2_task_spaces",
                "score": 2,
                "reason": "当前 intent 偏执行任务，增强 L2 权重。",
            }
        ],
        "projects_present_boosts": {
            "L1_case_atoms": 1,
            "L2_task_spaces": 1,
        },
        "files_present_boosts": {
            "L1_case_atoms": 1,
            "L2_task_spaces": 2,
        },
        "prefer_layer_boost": 3,
    }
}

DEFAULT_AUTO_SYNC_RULES = {
    "default": {
        "mode_aliases": {
            "safe": "strict",
            "strict": "strict",
            "balanced": "balanced",
            "aggressive": "aggressive",
        },
        "modes": {
            "strict": {
                "min_delta": 2,
                "allowed_risk_levels": ["low"],
                "fallback": "strict 模式下建议优先人工确认 task_candidates。",
            },
            "balanced": {
                "min_delta": 0,
                "allowed_risk_levels": ["low", "medium"],
                "fallback": "balanced 模式下可先检查 task_candidates[0] 再决定是否同步。",
            },
            "aggressive": {
                "min_delta": 0,
                "allowed_risk_levels": ["low", "medium", "high"],
                "fallback": "aggressive 模式会优先推进自动同步，但高风险任务仍建议人工复核。",
            },
        },
    }
}

DEFAULT_EVAL_RULES = {
    "write_quality": {
        "penalties": {
            "missing_l0": 20,
            "missing_l1": 15,
            "missing_l2": 30,
            "missing_l3": 20,
            "no_receipts": 100,
        },
        "rule_intent_keywords": ["规则", "规范", "invariant"],
    },
    "resume": {
        "penalties": {
            "missing_current_summary": 30,
            "missing_next_actions": 20,
            "missing_unresolved_items": 15,
            "verification_flag_without_items": 10,
            "missing_resume_rule_profile": 10,
        }
    },
    "handoff": {
        "penalties": {
            "missing_minimal_context": 30,
            "missing_next_checks": 20,
            "missing_do_not_repeat": 15,
            "missing_handoff_rule_profile": 10,
            "missing_model_profile": 10,
        }
    },
}


def ensure_default_rules(store: WorkspaceStore) -> Path:
    path = store.rules_dir / "global-rules.yaml"
    if not path.exists():
        path.write_text(yaml.safe_dump({"rules": DEFAULT_RULES}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    handoff_path = store.rules_dir / "handoff-profiles.yaml"
    if not handoff_path.exists():
        handoff_path.write_text(yaml.safe_dump(DEFAULT_HANDOFF_PROFILES, allow_unicode=True, sort_keys=False), encoding="utf-8")
    resume_path = store.rules_dir / "resume-rules.yaml"
    if not resume_path.exists():
        resume_path.write_text(yaml.safe_dump(DEFAULT_RESUME_RULES, allow_unicode=True, sort_keys=False), encoding="utf-8")
    handoff_rules_path = store.rules_dir / "handoff-rules.yaml"
    if not handoff_rules_path.exists():
        handoff_rules_path.write_text(yaml.safe_dump(DEFAULT_HANDOFF_RULES, allow_unicode=True, sort_keys=False), encoding="utf-8")
    write_policy_path = store.rules_dir / "write-policy-rules.yaml"
    if not write_policy_path.exists():
        write_policy_path.write_text(yaml.safe_dump(DEFAULT_WRITE_POLICY_RULES, allow_unicode=True, sort_keys=False), encoding="utf-8")
    auto_sync_path = store.rules_dir / "auto-sync-rules.yaml"
    if not auto_sync_path.exists():
        auto_sync_path.write_text(yaml.safe_dump(DEFAULT_AUTO_SYNC_RULES, allow_unicode=True, sort_keys=False), encoding="utf-8")
    eval_rules_path = store.rules_dir / "eval-rules.yaml"
    if not eval_rules_path.exists():
        eval_rules_path.write_text(yaml.safe_dump(DEFAULT_EVAL_RULES, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def load_rules(store: WorkspaceStore) -> List[Rule]:
    ensure_default_rules(store)
    rules: List[Rule] = []
    for path in store.rules_dir.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for item in data.get("rules", []):
            rules.append(Rule(**item))
    return rules


def match_rules(store: WorkspaceStore, intent: str = "", files: List[str] | None = None, scopes: List[str] | None = None) -> List[Dict[str, Any]]:
    files = files or []
    scopes = scopes or []
    intent_lower = intent.lower()
    matched: List[Dict[str, Any]] = []
    for rule in load_rules(store):
        score = 0
        if any(scope in rule.scope for scope in scopes):
            score += 3
        if any(k.lower() in intent_lower for k in rule.trigger_keywords):
            score += 2
        if files and any(any(_glob_match(f, pattern) for pattern in rule.file_patterns) for f in files):
            score += 3
        if not files and not intent and not scopes:
            score = 1
        if score > 0:
            item = rule.__dict__.copy()
            item["score"] = score
            matched.append(item)
    matched.sort(key=lambda x: x["score"], reverse=True)
    return matched


def load_yaml_rule_config(store: WorkspaceStore, file_name: str, default_data: Dict[str, Any]) -> Dict[str, Any]:
    ensure_default_rules(store)
    path = store.rules_dir / file_name
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _deep_merge(default_data, data)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base. Dicts are merged recursively; other values are overwritten."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# --- Constitution Governance (H-01) ---
# Project-level invariants that cannot be silently overridden by regular tasks.
# These rules represent the project's "constitution" — the bottom-line principles
# that must be respected regardless of task intent.

CONSTITUTION_RULES = [
    {
        "id": "CONSTITUTION-001",
        "principle": "数据安全",
        "constraint_level": "absolute",
        "scope": ["all"],
        "rule": "不得提交真实密钥、私有路径、内部服务名或私有 workspace 数据。",
        "version": "1.0.0",
        "status": "active",
    },
    {
        "id": "CONSTITUTION-002",
        "principle": "测试隔离",
        "constraint_level": "absolute",
        "scope": ["test"],
        "rule": "写入型测试必须使用临时 workspace，不得直接修改仓库 demo。",
        "version": "1.0.0",
        "status": "active",
    },
    {
        "id": "CONSTITUTION-003",
        "principle": "诊断可见性",
        "constraint_level": "required",
        "scope": ["main_chain"],
        "rule": "主链路可选能力失败时必须返回 diagnostics，不得静默失败。",
        "version": "1.0.0",
        "status": "active",
    },
    {
        "id": "CONSTITUTION-004",
        "principle": "破坏性迁移可恢复",
        "constraint_level": "required",
        "scope": ["migration"],
        "rule": "破坏性数据迁移必须可重复、可验证，并提供迁移或回滚说明。",
        "version": "1.0.0",
        "status": "active",
    },
    {
        "id": "CONSTITUTION-005",
        "principle": "Workspace 隔离",
        "constraint_level": "absolute",
        "scope": ["workspace"],
        "rule": "公开入口接收 workspace.yaml，底层 store 需要先解析实际 db 路径。",
        "version": "1.0.0",
        "status": "active",
    },
]


def load_constitution(store: WorkspaceStore) -> List[Dict[str, Any]]:
    """Load constitution rules. Returns the default constitution."""
    return CONSTITUTION_RULES


def check_constitution_conflicts(
    intent: str = "",
    files: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Check if an intent or file set conflicts with constitution rules."""
    conflicts = []
    files = files or []
    intent_lower = intent.lower()

    for rule in CONSTITUTION_RULES:
        if rule["status"] != "active":
            continue

        if rule["id"] == "CONSTITUTION-001":
            import re
            if re.search(r'(password|secret|token|api.?key)\s*[:=]', intent_lower):
                conflicts.append({
                    "constitution_id": rule["id"],
                    "principle": rule["principle"],
                    "conflict_type": "potential_secret_in_intent",
                    "severity": "critical",
                })
            for f in files:
                if any(p in f.lower() for p in ['/users/', '/home/', '/root/']):
                    conflicts.append({
                        "constitution_id": rule["id"],
                        "principle": rule["principle"],
                        "conflict_type": "private_path_in_files",
                        "severity": "critical",
                    })
                    break

    return conflicts
