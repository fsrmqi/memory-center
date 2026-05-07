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


def ensure_default_rules(store: WorkspaceStore) -> Path:
    path = store.rules_dir / "global-rules.yaml"
    if not path.exists():
        path.write_text(yaml.safe_dump({"rules": DEFAULT_RULES}, allow_unicode=True, sort_keys=False), encoding="utf-8")
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
