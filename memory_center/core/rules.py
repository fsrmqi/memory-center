from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .models import Rule
from .store import WorkspaceStore

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
        if files and any(any(fnmatch.fnmatch(f, pattern) for pattern in rule.file_patterns) for f in files):
            score += 3
        if not files and not intent and not scopes:
            score = 1
        if score > 0:
            item = rule.__dict__.copy()
            item["score"] = score
            matched.append(item)
    matched.sort(key=lambda x: x["score"], reverse=True)
    return matched
