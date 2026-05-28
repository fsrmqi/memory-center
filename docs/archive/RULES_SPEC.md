# Rules Spec / 规则规范

## 中文

规则是 Memory Center 的核心价值之一。它让团队经验变成 AI Agent 可以读取的结构化上下文。

```yaml
- id: MQ-001
  title: MQ 消费必须保证幂等
  scope: [mq, consumer, kafka, rocketmq]
  severity: must
  file_patterns:
    - "**/*Consumer.java"
    - "**/*Listener.java"
  trigger_keywords:
    - kafka
    - rocketmq
    - 消费
    - topic
  rule: >
    Kafka/RocketMQ 消费逻辑必须使用业务唯一键做幂等，不能只依赖 offset。
  reason: >
    重平衡、重试、网络抖动、业务异常都会导致重复消费。
  checklist:
    - 是否有业务唯一键
    - 是否处理重复消费
    - 是否记录 topic/group/msgKey
    - 是否有失败重试或补偿
```

### 字段说明

| 字段 | 说明 |
|---|---|
| `id` | 规则唯一编号。 |
| `title` | 规则标题。 |
| `scope` | 规则作用域。 |
| `severity` | `must`、`should`、`suggestion`。 |
| `file_patterns` | 匹配文件路径。 |
| `trigger_keywords` | 匹配任务意图。 |
| `rule` | 规则正文。 |
| `reason` | 为什么这么做。 |
| `checklist` | Agent 修改前后的自检清单。 |

### 推荐规则分类

- `MQ-*`: Kafka / RocketMQ 消费、生产、幂等、重试。
- `CONTRACT-*`: Feign、DTO、MQ Message、公共 API。
- `ES-*`: Elasticsearch 写入、查询、别名、bulk。
- `LOG-*`: 链路日志、业务字段、异常阶段码。
- `DATA-*`: 跨表、跨月、跨索引迁移。
- `SEC-*`: 安全、脱敏、权限。

## English

Rules are structured architecture guardrails. They allow coding agents to retrieve team constraints before editing code.

A rule contains an id, scope, severity, file patterns, trigger keywords, rationale and checklist.
