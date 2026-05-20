# Memory Center 详细技术参考手册

> 版本：1.3.0  |  配套文档：[PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)

---

## 目录

1. [索引系统详解](#一索引系统详解)
2. [知识图谱数据模型](#二知识图谱数据模型)
3. [MCP Tools 完整参数规格](#三mcp-tools-完整参数规格)
4. [CLI 命令详细参考](#四cli-命令详细参考)
5. [工件系统（Artifacts）](#五工件系统artifacts)
6. [任务空间（Task Spaces）](#六任务空间task-spaces)
7. [Session 记忆系统](#七session-记忆系统)
8. [规则系统](#八规则系统)
9. [多 Workspace 管理](#九多-workspace-管理)
10. [HTTP API 参考](#十http-api-参考)
11. [Agent 集成模式](#十一agent-集成模式)
12. [配置参考](#十二配置参考)

---

## 一、索引系统详解

### 1.1 索引流水线

`reindex` 命令执行以下完整流水线：

```
workspace.yaml
  │
  ├─ 阶段1: 文件扫描 (walk_project)
  │   遍历所有 services 的文件树，排除 .git / target / build 等目录
  │   输出: file-index.json
  │
  ├─ 阶段2: Java 解析 (RegexJavaParser)
  │   对每个 .java 文件提取：
  │   - 包名、类名、接口名、方法名、字段名
  │   - 注解、import
  │   - Bean 注入关系（@Autowired / @Resource / 构造器注入）
  │   - 方法调用（含接收者类型推断）
  │   - DTO 字段使用（getter/setter）
  │   - 配置使用（@Value / @ConfigurationProperties）
  │   - 数据资源（MongoDB / ES）
  │   输出: java-symbol-index.json
  │
  ├─ 阶段3: API 端点提取
  │   从含 @RestController 的类中提取 REST 端点
  │   输出: api-index.json
  │
  ├─ 阶段4: Feign 客户端提取
  │   从含 @FeignClient 的接口中提取远程调用定义
  │   输出: feign-index.json
  │
  ├─ 阶段5: MQ 端点提取
  │   从含 @KafkaListener / @RocketMQMessageListener 的类中提取消息端点
  │   输出: mq-index.json
  │
  ├─ 阶段6: 配置提取
  │   解析 application.yml / bootstrap.yml 中的配置结构
  │   输出: config-index.json
  │
  ├─ 阶段7: 拓扑构建 (build_topology)
  │   汇总 Feign 调用边、API 端点、MQ 主题，构建服务拓扑
  │   输出: service-topology.json
  │
  ├─ 阶段8: 图谱构建 (build_graph_store)
  │   将所有索引数据转为节点/边，写入 SQLite
  │   输出: graph/graph.db
  │
  └─ 阶段9: 语义索引 (build_workspace_semantic_index)
      对所有图节点做 TF-IDF 向量化（或 sentence-transformers 嵌入）
      输出: index/semantic-node-index.json
```

### 1.2 索引文件格式

**file-index.json**
```json
[
  {
    "project": "article-service",
    "service_name": "article-service",
    "path": "article-service/src/main/java/com/example/ArticleController.java",
    "suffix": ".java"
  }
]
```

**java-symbol-index.json**
```json
[
  {
    "project": "article-service",
    "file": "article-service/src/.../ArticleController.java",
    "package": "com.example.article",
    "classes": ["ArticleController"],
    "interfaces": [],
    "methods": ["getArticle", "updatePubTime"],
    "fields": ["articleService"],
    "annotations": ["RestController", "RequestMapping"],
    "imports": ["com.example.common.ArticleDTO"],
    "field_types": {"articleService": "ArticleService"},
    "method_variable_types": {"updatePubTime": {"req": "UpdateTimeReq"}},
    "bean_injections": [
      {"field_name": "articleService", "type": "ArticleService", "annotation": "@Autowired", "line": 15}
    ],
    "method_calls": [
      {"receiver": "articleService", "receiver_type": "ArticleService", "method_name": "findById", "owner_method": "getArticle", "line": 28}
    ],
    "dto_field_usages": [
      {"receiver": "req", "receiver_type": "UpdateTimeReq", "accessor": "get", "field": "oldPubTime", "owner_method": "updatePubTime", "line": 35}
    ],
    "config_usages": [{"key": "article.max-size", "line": 12, "annotation": "@Value"}],
    "data_resources": []
  }
]
```

**api-index.json**
```json
[
  {
    "project": "article-service",
    "file": "article-service/src/.../ArticleController.java",
    "controller": "ArticleController",
    "http_method": "GET",
    "path": "/api/article/{id}",
    "method_name": "getArticle"
  }
]
```

**feign-index.json**
```json
[
  {
    "project": "task-service",
    "file": "task-service/src/.../ArticleFeignClient.java",
    "interface": "ArticleFeignClient",
    "target_service": "article-service",
    "base_path": "/api/article",
    "methods": [
      {"name": "getArticle", "http_method": "GET", "path": "/{id}"},
      {"name": "updatePubTime", "http_method": "POST", "path": "/update-time"}
    ]
  }
]
```

**mq-index.json**
```json
[
  {
    "project": "task-service",
    "file": "task-service/src/.../MigrationConsumer.java",
    "kind": "consumer",
    "topic": "article-migration",
    "group": "task-service-group",
    "class_name": "MigrationConsumer",
    "method_name": "onMessage"
  }
]
```

**service-topology.json**
```json
{
  "services": [
    {"name": "article-service", "service_name": "article-service", "type": "spring-boot-service", "path": "article-service"},
    {"name": "task-service", "service_name": "task-service", "type": "spring-boot-task", "path": "task-service"}
  ],
  "feign_edges": [
    {"from_project": "task-service", "to_project": "article-service", "interface": "ArticleFeignClient", "base_path": "/api/article"}
  ],
  "mq_topics": [
    {"topic": "article-migration", "kind": "consumer", "project": "task-service"}
  ],
  "api_summary": {
    "article-service": [{"method": "GET", "path": "/api/article/{id}"}]
  }
}
```

### 1.3 忽略目录列表

以下目录在索引时自动跳过：

```python
IGNORED_DIRS = {
    ".git", ".idea", ".vscode", "target", "build", "dist",
    "node_modules", ".memory-center", ".project-ai",
    ".symbio", "__pycache__",
}
```

---

## 二、知识图谱数据模型

### 2.1 节点类型详解

| type | ID 格式 | 示例 | metadata 关键字段 |
|------|---------|------|-------------------|
| `service` | `service:{name}` | `service:article-service` | type, service_name, port |
| `file` | `file:{project}:{path}` | `file:article-service:src/.../ArticleController.java` | suffix |
| `class` | `class:{project}:{fqn}` | `class:article-service:ArticleController` | package, annotations |
| `interface` | `interface:{project}:{fqn}` | `interface:task-service:ArticleFeignClient` | package |
| `method` | `method:{project}:{class}.{name}` | `method:article-service:ArticleController.getArticle` | return_type, params |
| `api_endpoint` | `api:{project}:{method}:{path}` | `api:article-service:GET:/api/article/{id}` | controller, method_name |
| `feign_client` | `feign:{project}:{interface}` | `feign:task-service:ArticleFeignClient` | target_service, base_path |
| `feign_method` | `feign_method:{project}:{interface}.{name}` | `feign_method:task-service:ArticleFeignClient.getArticle` | http_method, path |
| `mq_topic` | `mq_topic:{topic}` | `mq_topic:article-migration` | — |
| `mq_consumer` | `mq_consumer:{project}:{class}` | `mq_consumer:task-service:MigrationConsumer` | topic, group |
| `mq_producer` | `mq_producer:{project}:{class}` | `mq_producer:article-service:MigrationProducer` | topic |
| `config_property` | `config:{project}:{key}` | `config:article-service:article.max-size` | annotation |
| `dto` | `dto:{project}:{class}` | `dto:common-api:ArticleDTO` | fields |
| `bean` | `bean:{project}:{class}` | `bean:article-service:ArticleService` | annotation |
| `data_resource` | `resource:{kind}:{name}` | `resource:MongoCollection:articles` | kind, operation |

### 2.2 边类型详解

| type | 含义 | 示例 source → target | metadata |
|------|------|----------------------|----------|
| `belongs_to` | 方法属于类 | method → class | — |
| `contains` | 服务包含文件 | service → file | — |
| `calls` | 方法调用 | method → method | receiver_type, line |
| `injects` | Bean 注入 | class → bean | annotation, field_name |
| `feign_calls` | Feign 远程调用 | feign_method → api_endpoint | feign_client |
| `produces_to` | MQ 生产 | method → mq_topic | — |
| `consumes_from` | MQ 消费 | mq_consumer → mq_topic | group |
| `exposes_api` | 暴露 REST 端点 | class → api_endpoint | — |
| `uses_dto` | 使用 DTO | method → dto | accessor, field |
| `uses_config` | 使用配置 | class → config_property | annotation |
| `implements` | 实现接口 | class → interface | — |
| `extends` | 继承 | class → class | — |
| `uses_resource` | 使用数据资源 | class → data_resource | operation |
| `endpoint_for` | 端点对应方法 | api_endpoint → method | — |

### 2.3 图谱查询示例

```python
# 查找所有包含 "Article" 的节点
graph.find_nodes("Article")
# 返回: [node_ArticleController, node_ArticleService, node_ArticleDTO, ...]

# 只查找 Feign 客户端
graph.find_nodes("Article", types=["feign_client"])
# 返回: [node_ArticleFeignClient]

# 查找某节点的上下游（BFS 2 跳）
graph.neighbors("method:article-service:ArticleController.getArticle", direction="downstream", max_depth=2)
# 返回: [ArticleService.findById → ArticleRepository → MongoDB articles, ...]

# 图谱统计
graph.counts()
# 返回: {"nodes": 342, "edges": 876}
```

---

## 三、MCP Tools 完整参数规格

### 3.1 任务嗅探

#### `workspace_sniff_tool`

**描述：** 编码前自动收集上下文（核心入口工具），返回相关文件、服务、API、Feign、MQ、规则、历史案例。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `intent` | `string` | **必填** | 任务描述文本 |
| `limit` | `int` | `12` | 候选文件最大数量 |
| `auto_sync_mode` | `string` | `"balanced"` | 自动同步工件模式（`strict` / `balanced` / `aggressive`） |

**返回字段：**

```
workspace          : str          工作区名称
intent             : str          原始任务描述
risk_level         : str          风险等级 (low / medium / high / critical)
matched_services   : list[str]    匹配到的服务名
candidate_files    : list[dict]   候选文件（含 project / path / score）
related_apis       : list[dict]   相关 REST API 端点
related_feigns     : list[dict]   相关 Feign 客户端
related_mq         : list[dict]   相关 MQ 端点
related_rules      : list[dict]   匹配到的架构规则（含 score）
historical_cases   : list[dict]   匹配到的历史经验案例
task_candidates    : list[dict]   匹配到的任务空间候选
source_refs        : list[dict]   结构化来源引用（file / feign / api / mq / case）
resolved_task      : dict         自动解析的任务空间信息
auto_sync_recommendation : dict   工件自动同步建议
write_judge_recommendation : dict 写入裁决建议（selected_layer/confidence/suggested_tool）
symbolic_context   : dict         符号化上下文摘要
next_steps         : list[str]    推荐的下一步操作
```

#### `workspace_sync_sniff_artifacts_tool`

**描述：** 将 sniff 结果同步写入共享 context 和 plan 工件。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `intent` | `string` | **必填** | 任务描述 |
| `limit` | `int` | `12` | 候选文件数量 |
| `task_id` | `string` | `""` | 目标任务空间 ID（空则自动创建/匹配） |
| `title` | `string` | `""` | 任务标题 |
| `auto_sync_mode` | `string` | `"balanced"` | 同步模式 |

### 3.2 图谱查询

#### `memory_query_tool`

**描述：** 图感知混合搜索，同时查询文件索引、符号、服务、契约、规则和记忆。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | `string` | **必填** | 搜索查询文本 |
| `limit` | `int` | `20` | 最大返回条数 |

**返回：** 融合后的排序结果列表，每条包含 `source`（来源索引）和 `score`。

#### `memory_search_code_tool`

**描述：** 轻量关键词代码搜索，用于缩小范围后再做图遍历。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `query` | `string` | **必填** | 关键词 |
| `scope` | `string` | `""` | 限定范围（服务名或路径前缀） |
| `limit` | `int` | `20` | 最大返回条数 |

#### `memory_symbol_tool`

**描述：** 符号解析，返回最佳匹配及附近候选。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `string` | **必填** | 类名 / 方法名 / 接口名 |
| `limit` | `int` | `10` | 候选数量 |

### 3.3 调用链遍历

#### `memory_callers_tool` / `memory_callees_tool`

**描述：** BFS 多跳遍历上游调用方 / 下游被调用方。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `symbol` | `string` | **必填** | 起始符号（method / class / feign / topic / config） |
| `depth` | `int` | `2` | 遍历跳数 |
| `limit` | `int` | `80` | 最大返回边数 |

**返回结构：**
```json
{
  "symbol": "ArticleController.getArticle",
  "direction": "upstream",
  "edges": [
    {
      "depth": 1,
      "type": "calls",
      "source": {"type": "method", "name": "GatewayController.forward", "project": "gateway"},
      "target": {"type": "method", "name": "ArticleController.getArticle", "project": "article-service"}
    }
  ],
  "node_count": 5,
  "edge_count": 3
}
```

### 3.4 上下文与影响分析

#### `memory_context_tool`

**描述：** 对任意符号返回 360° 全面上下文（上游、下游、规则、历史案例）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `string` | **必填** | 服务名 / 端点 / Feign 方法 / Topic / 文件 / 符号 |
| `max_depth` | `int` | `2` | 遍历深度 |

#### `memory_impact_tool`

**描述：** 影响面分析，返回受影响的节点、规则和风险评估。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `target` | `string` | **必填** | 变更目标 |
| `direction` | `string` | `"upstream"` | 分析方向（`upstream` / `downstream`） |
| `max_depth` | `int` | `3` | 遍历深度 |

#### `memory_plan_change_tool`

**描述：** 基于影响分析自动生成变更计划。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `target` | `string` | **必填** | 变更目标 |
| `direction` | `string` | `"upstream"` | 分析方向 |
| `max_depth` | `int` | `3` | 遍历深度 |

#### `memory_verify_checklist_tool`

**描述：** 生成合并前验证检查清单。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `target` | `string` | **必填** | 变更目标 |

#### `memory_write_judge_tool`

**描述：** 对一条输入信息进行写入裁决，判断应写入 `L0/L1/L2/L3` 哪一层记忆。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `text` | `string` | **必填** | 待判断的信息文本 |
| `source` | `string` | `"note"` | 信息来源（如 `tool_result` / `user_prompt` / `note`） |
| `intent` | `string` | `""` | 当前任务意图，用于辅助裁决 |
| `prefer_layer` | `string` | `""` | 偏好层级（`L0`/`L1`/`L2`/`L3`） |
| `projects` | `list[str]` | `null` | 相关项目列表（可选） |
| `files` | `list[str]` | `null` | 相关文件列表（可选） |

**返回：**

```text
decision.selected_layer   = L0_session_events | L1_case_atoms | L2_task_spaces | L3_workspace_profile
decision.confidence       = high | medium | low
decision.layer_scores     = 各层评分
decision.reasons          = 裁决理由列表
decision.suggested_tool   = 建议调用的写入工具
decision.suggested_action = 建议动作说明
```

多个写入型工具现在会附带统一 `write_receipt`：

```text
write_receipt.layer            = L0/L1/L2/L3
write_receipt.action           = 实际写入动作名
write_receipt.scope            = memory | workspace | task_space
write_receipt.target           = 写入目标名
write_receipt.target_file      = 目标文件
write_receipt.task_id          = 相关任务空间 ID（若有）
write_receipt.session_id       = 相关 session ID（若有）
write_receipt.updated_artifacts= 更新的工件列表（若有）
write_receipt.payload_ref      = 外置 payload 引用（若有）
```

所有已持久化的回执会追加写入：

```text
memory/write-receipts.jsonl
```

这让外部系统可以不依赖单次接口返回，直接按时间线扫描所有写入动作。

可通过以下入口查询：

- CLI: `memory-center write-receipts --workspace ... --layer L2_task_spaces`
- MCP: `workspace_write_receipts_tool(layer="L2_task_spaces")`
- HTTP: `/workspace/write-receipts?layer=L2_task_spaces`

进一步的高级入口：

- `workspace_replay_write_chain(...)`
  按 task/session 回放完整写入链，适合排查“这次任务到底写到了哪些层”。
- `memory_eval_write_quality(...)`
  基于回执评估写入质量，输出 `score / quality / findings`，适合做 memory eval 或自动巡检。

`workspace_status()` 现在也会返回：

```text
write_receipts_overview.total
write_receipts_overview.layer_counts
write_receipts_overview.action_counts
write_receipts_overview.scope_counts
write_receipts_overview.recent_receipts
```

#### `memory_plan_write_tool`

**描述：** 基于 `memory_write_judge_tool` 结果生成可执行写入计划（不直接执行写入）。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `text` | `string` | **必填** | 待写入信息文本 |
| `source` | `string` | `"note"` | 来源类型 |
| `intent` | `string` | `""` | 当前意图 |
| `session_id` | `string` | `""` | Session ID（用于 L0/L2 case 同步路径） |
| `task_id` | `string` | `""` | 目标任务空间 ID（用于 L2） |
| `title` | `string` | `""` | 任务标题（用于 L2 解析） |
| `prefer_layer` | `string` | `""` | 偏好层级 |
| `projects` | `list[str]` | `null` | 相关项目 |
| `files` | `list[str]` | `null` | 相关文件 |

**返回：**

```text
memory_layer         = 本次判定层级
confidence           = 裁决置信度
judge                = 与 memory_write_judge 相同的 decision 结构
plan.ready           = 是否可直接执行（缺参数时为 false）
plan.steps[].tool    = 建议调用工具名
plan.steps[].ready   = 该步是否可执行
plan.steps[].required= 缺失参数（若有）
plan.steps[].example_args = 示例参数
```

#### `memory_execute_write_tool`

**描述：** 对 `memory_plan_write_tool` 的 ready 步骤做薄执行封装，适合 Agent 不想自己手工拼接最后一步时直接调用。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| 参数集合 | 与 `memory_plan_write_tool` 相同 | — | 执行前会先生成计划，再执行 ready 步骤 |

**返回：**

```text
memory_layer         = 本次执行对应的记忆层
confidence           = 裁决置信度
judge                = 原裁决结果
executed[].tool      = 实际执行的工具名
executed[].result    = 实际工具返回
session_id           = 若过程中自动创建 session，则返回新 session_id
```

#### `memory_detect_changes_tool`

**描述：** 将本地 Git 变更映射到受影响的项目、图节点和规则。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `scope` | `string` | `"staged"` | Git 范围（`staged` / `unstaged` / `all`） |

### 3.5 契约管理

#### `memory_contracts_tool`

**描述：** 列出所有已发现的 Feign/API/MQ 契约及相关规则。

无参数。返回 `{ feigns, apis, mq_topics, rules }`。

#### `workspace_trace_tool`

**描述：** 按类名、Feign 客户端、Controller 端点或 MQ Topic 追踪跨服务链路。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `entry` | `string` | **必填** | 追踪入口 |

#### `workspace_check_contract_tool`

**描述：** 修改 DTO/Feign/MQ Message 前的安全检查。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `contract_file` | `string` | **必填** | 契约文件路径 |
| `change_type` | `string` | **必填** | 变更类型（`add_field` / `remove_field` / `rename` / ...） |

**返回：**
```json
{
  "contract_file": "common-api/.../ArticleDTO.java",
  "change_type": "remove_field",
  "affected_candidates": [...],
  "related_feigns": [...],
  "related_mq": [...],
  "rules": [{"id": "CONTRACT-001", "score": 8, ...}],
  "required_checks": [
    "全 workspace 搜索字段引用点",
    "确认历史 MQ 消息反序列化兼容",
    "确认 Feign 调用方请求/响应兼容",
    "新增字段提供默认值，删除字段需要灰度和兼容周期"
  ]
}
```

### 3.6 规则检查

#### `workspace_check_rules_tool`

**描述：** 根据项目/变更类型/文件匹配架构规则。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `projects` | `list[str]` | `null` | 涉及的项目 |
| `change_type` | `string` | `"general"` | 变更类型 |
| `files` | `list[str]` | `null` | 涉及的文件 |

### 3.7 经验记忆

#### `workspace_record_case_tool`

**描述：** 任务完成后记录已验证的工程经验。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task` | `string` | **必填** | 任务描述 |
| `projects` | `list[str]` | **必填** | 涉及的项目列表 |
| `files` | `list[str]` | **必填** | 修改的文件列表 |
| `flow` | `string` | `""` | 数据流描述 |
| `risk_points` | `list[str]` | `null` | 风险点 |
| `verified_by` | `list[str]` | `null` | 验证方式（测试名、命令等） |
| `source_session_id` | `string` | `""` | 可选来源 Session ID |
| `source_task_id` | `string` | `""` | 可选来源任务空间 ID |
| `valid_from` | `string` | `当前时间` | 该经验开始生效的时间 |
| `valid_to` | `string` | `""` | 该经验失效时间（空表示未设置） |
| `superseded_by` | `string` | `""` | 被哪条新经验替代 |
| `current_truth` | `bool` | `true` | 当前是否仍视为有效事实 |

**存储位置：** `memory/cross-service-task-memory.jsonl`

**记录格式：**
```json
{
  "task": "oldPubTime→newPubTime 迁移",
  "projects": ["article-service", "task-service"],
  "files": ["ArticleTimeMigrator.java", "MigrationConsumer.java"],
  "flow": "Controller → Service → Repository(新表写入) → 标记旧记录",
  "risk_points": ["跨月分表", "MQ 重复消费"],
  "verified_by": ["test_migration_cross_month()", "手动验证 dev 环境"],
  "memory_layer": "L1_case_atom",
  "source_session_id": "session-abc123",
  "source_task_id": "dto-migration",
  "source_refs": [
    {"type": "session_event", "tool_name": "memory_impact_tool", "target": "MoveArticleRequest"}
  ],
  "created_at": "2025-05-10T10:30:00+00:00"
}
```

### 3.8 Session 管理

#### `workspace_start_session_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `intent` | `string` | **必填** | 任务意图 |
| `session_id` | `string` | `""` | 自定义 ID（空则自动生成 UUID） |

#### `workspace_log_session_event_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | `string` | **必填** | Session ID |
| `event_type` | `string` | **必填** | 事件类型（`prompt` / `tool_call` / `tool_result` / `note`） |
| `payload` | `dict` | `null` | 事件负载；体积过大时会自动外置到 `memory/refs/` 并返回 `payload_ref` |

#### `workspace_end_session_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | `string` | **必填** | Session ID |
| `outcome` | `string` | `""` | 结果摘要 |
| `verified_by` | `list[str]` | `null` | 验证方式 |

#### `workspace_recent_sessions_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | `int` | `10` | 返回最近 N 个 Session |

#### `workspace_session_summary_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | `string` | **必填** | Session ID |

**返回补充字段：**

```text
session_overview.memory_layer              = L0_session_events
session_overview.event_count               = 原始事件数
session_overview.event_type_counts         = 各事件类型计数
session_overview.payload_ref_count         = 外置 payload 数量
session_overview.source_ref_like_event_count = 含 query/target/file/project 等来源线索的事件数
session_overview.payload_refs              = 前若干个外置 payload_ref
```

#### `workspace_resume_context_tool`

**描述：** 根据新任务意图，从历史 Session、案例和查询入口中混合召回相关上下文。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `intent` | `string` | **必填** | 新任务意图 |
| `limit` | `int` | `5` | 返回条数 |

#### `workspace_suggest_case_tool`

**描述：** 从已完成的 Session 自动推荐 case 记录草稿。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | `string` | **必填** | 已结束的 Session ID |

**返回补充字段：**

- `draft_case.memory_layer = L1_case_atom`
- `draft_case.source_session_id`
- `draft_case.source_task_id`
- `draft_case.source_refs`
- `draft_case.evidence_refs`

#### `workspace_sync_case_artifacts_tool`

**描述：** 将推荐的 case 同步到共享 design 和 change-log 工件。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | `string` | **必填** | Session ID |
| `task_id` | `string` | `""` | 目标任务空间 ID |
| `title` | `string` | `""` | 标题 |
| `auto_sync_mode` | `string` | `"balanced"` | 同步模式 |

### 3.9 共享工件管理

除常规共享工件外，系统还会自动生成一组 L3 核心记忆块：

```text
artifacts/memory-blocks/
  workspace-profile.md
  team-rules.md
  architecture-invariants.md
  active-migration-policy.md
```

它们适合沉淀：

- 跨任务稳定有效的团队规则
- 长期成立的架构不变量
- 当前仍在生效的迁移/兼容策略
- 对整个 workspace 的高层画像

#### `workspace_artifact_list_tool`

无参数。列出所有共享工件及其状态。

#### `workspace_artifact_get_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `string` | **必填** | 工件名（`context` / `requirement` / `design` / `plan` / `test_plan` / `change_log`） |

#### `workspace_artifact_outline_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `string` | **必填** | 工件名 |

**返回：** Markdown 章节大纲（标题 + 级别 + 预览 + 字符数）。

#### `workspace_artifact_context_tool`

**描述：** 根据 intent 从所有工件中提取相关片段。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `intent` | `string` | **必填** | 意图描述 |
| `limit` | `int` | `6` | 最大返回片段数 |

#### `workspace_artifact_update_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `string` | **必填** | 工件名 |
| `content` | `string` | **必填** | 新内容（对核心记忆工件默认按尾部追加保护处理，不允许模型整篇覆盖） |

#### `workspace_append_change_log_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `entry` | `string` | **必填** | 变更条目文本 |

自动添加时间戳，写入后触发 compact。

#### `workspace_compact_change_log_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `keep_recent` | `int` | `30` | 保留最近 N 条，超出的归档到 `change-log.archive.md` |

### 3.10 任务空间管理

#### `workspace_task_space_create_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `title` | `string` | `""` | 任务标题 |
| `intent` | `string` | `""` | 任务意图（title 和 intent 至少提供一个） |
| `owner` | `string` | `""` | 负责人 |
| `tags` | `list[str]` | `null` | 标签 |
| `priority` | `string` | `"medium"` | 优先级（`low` / `medium` / `high` / `critical`） |

#### `workspace_task_space_list_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `include_archived` | `bool` | `false` | 是否包含已归档 |

#### `workspace_task_space_resolve_tool`

**描述：** 自然语言匹配任务空间，低于阈值不自动创建。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `intent` | `string` | **必填** | 任务意图 |
| `title` | `string` | `""` | 任务标题 |
| `create_if_missing` | `bool` | `true` | 无匹配时是否新建 |
| `include_archived` | `bool` | `false` | 是否搜索已归档 |
| `limit_candidates` | `int` | `3` | 最大候选数 |
| `score_threshold` | `int` | `3` | 匹配阈值（低于此分数不自动匹配） |

#### `workspace_task_artifact_get_tool` / `workspace_task_artifact_update_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task_id` | `string` | **必填** | 任务空间 ID |
| `name` | `string` | **必填** | 工件名 |

说明：

- 对 `context / requirement / design / plan / test_plan / change_log / current_summary` 这类核心记忆工件，`update` 路径默认启用 append-only 保护。
- 如果新内容不是“在现有内容基础上扩展”的完整文档，系统会自动转成尾部追加，而不是覆盖原文。
- 返回里的 `write_mode` 会标识本次实际采用的是 `initial_write / append_full_document / append_guarded / deduplicated_noop / replace`。
- 同时会返回 `audit_ref`，指向 `memory/artifact-write-audit.jsonl` 中对应的审计记录。

#### `workspace_task_status_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task_id` | `string` | **必填** | 任务空间 ID |
| `status` | `string` | **必填** | 新状态（`draft` / `active` / `blocked` / `done` / `archived`） |

#### `workspace_task_archive_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task_id` | `string` | **必填** | 任务空间 ID |
| `reason` | `string` | `""` | 归档原因 |

#### `workspace_task_auto_archive_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `retention_days` | `int` | `30` | 保留天数，超过的自动归档 |

### 3.11 生成工具

#### `memory_generate_wiki_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `output_dir` | `string` | `null` | 输出目录（默认 `{workspace}/wiki/`） |

**生成内容：**
- `overview.md` — 架构总览
- `services/{name}.md` — 每个服务的详情页（Feign 边、MQ Topic）
- `memory.md` — 历史任务记忆汇总

#### `memory_generate_skills_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `output_dir` | `string` | `null` | 输出目录（默认 `{workspace}/skills/generated/`） |

**生成内容：** 每个历史案例生成一个 `SKILL.md`，包含适用场景、流程、关键文件和风险检查清单。

### 3.12 状态与分组

#### `workspace_status_tool`

无参数。返回工作区完整状态，包含索引统计、语义索引状态、分层记忆统计、活跃任务空间、当前焦点任务、拓扑。

**返回补充字段：**

```text
memory_layers.L0_session_events   = 原始会话事件层
memory_layers.L1_case_atoms       = 经验原子层
memory_layers.L2_task_spaces      = 任务空间层
memory_layers.L3_workspace_profile = 工作区画像层

memory_overview.layer_order       = 固定层顺序
memory_overview.layer_counts      = 各层统计值
memory_overview.highlights        = 面向 CLI/MCP/HTTP 的概览摘要
```

#### `group_query_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `group` | `string` | **必填** | 分组名称 |
| `query` | `string` | **必填** | 搜索查询 |
| `limit` | `int` | `20` | 最大返回条数 |

#### `group_status_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `group` | `string` | **必填** | 分组名称 |

#### `group_impact_tool`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `group` | `string` | **必填** | 分组名称 |
| `target` | `string` | **必填** | 变更目标 |
| `direction` | `string` | `"upstream"` | 分析方向 |
| `max_depth` | `int` | `3` | 遍历深度 |

### 3.13 MCP Resources

| URI | 描述 | 返回 |
|-----|------|------|
| `memory-center://status` | 工作区索引状态 | `workspace_status` 完整结果 |
| `memory-center://contracts` | 已发现的契约 | `memory_contracts` 完整结果 |
| `memory-center://topology` | 服务拓扑 | `service-topology.json` 内容 |

### 3.14 MCP Prompts

| Prompt | 参数 | 返回文本 |
|--------|------|---------|
| `detect_impact(target)` | 目标符号 | 引导 Agent 调用 `memory_impact_tool` 并审查规则 |
| `spring_cloud_safe_change(task)` | 任务描述 | 引导 Agent 走完整的 sniff → context → check → record 流程 |

---

## 四、CLI 命令详细参考

### 4.1 初始化

```bash
memory-center init \
  --workspace-root /path/to/spring-cloud-project \
  --name my-project
```

**行为：**
1. 创建 `{root}/.memory-center/` 目录
2. 写入默认 `workspace.yaml`（含示例 gateway / common-api / common-core 服务）
3. 创建 `index/`、`graph/`、`memory/`、`rules/`、`artifacts/` 子目录

### 4.2 索引

```bash
memory-center reindex --workspace .memory-center/workspace.yaml
```

**输出：**
```
Reindexing workspace: my-project
  files: 1240
  symbols: 428
  apis: 86
  feigns: 23
  mq: 12
  configs: 18
  graph_nodes: 2847
  graph_edges: 4521
  semantic_docs: 2847
```

### 4.3 查询

```bash
# 图感知混合查询
memory-center query --workspace .memory-center/workspace.yaml --query "ArticleDTO"

# 关键词代码搜索（限定范围）
memory-center search-code --workspace .memory-center/workspace.yaml \
  --query "updatePubTime" --scope article-service

# 符号解析
memory-center symbol --workspace .memory-center/workspace.yaml \
  --name "ArticleFeignClient"
```

### 4.4 调用链

```bash
# 查找上游调用方（谁调用了这个方法）
memory-center callers --workspace .memory-center/workspace.yaml \
  --symbol "ArticleController.getArticle" --depth 2

# 查找下游被调用方（这个方法调用了谁）
memory-center callees --workspace .memory-center/workspace.yaml \
  --symbol "ArticleController.getArticle" --depth 2

# 360° 上下文
memory-center context --workspace .memory-center/workspace.yaml \
  --name "ArticleFeignClient"
```

### 4.5 变更分析

```bash
# 影响面分析
memory-center impact --workspace .memory-center/workspace.yaml \
  --target "ArticleDTO" --direction upstream

# 变更计划
memory-center plan-change --workspace .memory-center/workspace.yaml \
  --target "ArticleDTO"

# 验证检查清单
memory-center verify-checklist --workspace .memory-center/workspace.yaml \
  --target "ArticleDTO"

# Git 变更检测
memory-center detect-changes --workspace .memory-center/workspace.yaml --scope staged
```

### 4.6 契约与规则

```bash
# 列出所有契约
memory-center contracts --workspace .memory-center/workspace.yaml

# 契约安全检查
memory-center check-contract --workspace .memory-center/workspace.yaml \
  --contract-file common-api/.../ArticleDTO.java --change-type remove_field

# 规则匹配
memory-center check-rules --workspace .memory-center/workspace.yaml \
  --projects article-service --change-type mq --files "MigrationConsumer.java"

# 跨服务追踪
memory-center trace --workspace .memory-center/workspace.yaml \
  --entry "ArticleFeignClient"
```

### 4.7 Session 与经验

```bash
# 开始 Session
memory-center start-session --workspace .memory-center/workspace.yaml \
  --intent "修复跨月迁移 bug"

# 记录事件
memory-center log-session-event --workspace .memory-center/workspace.yaml \
  --session-id abc-123 --event-type note --payload '{"text": "定位到问题根因"}'

# 结束 Session
memory-center end-session --workspace .memory-center/workspace.yaml \
  --session-id abc-123 --outcome "已修复并验证"

# 记录经验案例
memory-center record-case --workspace .memory-center/workspace.yaml \
  --task "跨月迁移修复" \
  --projects article-service,task-service \
  --files "ArticleTimeMigrator.java" \
  --flow "Controller→Service→新表写入→标记旧记录" \
  --risk-points "MQ重复消费,跨月边界"
```

### 4.8 任务嗅探

```bash
# 编码前获取完整上下文
memory-center sniff --workspace .memory-center/workspace.yaml \
  --intent "oldPubTime newPubTime Kafka 迁移分表"
```

**返回示例：**
```yaml
workspace: my-project
intent: "oldPubTime newPubTime Kafka 迁移分表"
risk_level: high
matched_services:
  - article-service
  - task-service
  - common-api
candidate_files:
  - project: article-service
    path: article-service/src/.../ArticleTimeMigrator.java
    score: 8
  - project: task-service
    path: task-service/src/.../MigrationConsumer.java
    score: 6
related_rules:
  - id: DATA-001
    title: 跨时间分表迁移必须保证一致性
    score: 7
  - id: MQ-001
    title: MQ 消费必须保证幂等
    score: 5
next_steps:
  - 先调用 memory_search_code 缩小入口范围
  - 对关键符号调用 memory_callers / memory_callees 理清调用链
  - 先调用 memory_write_judge / memory_plan_write 判断应写入 L0/L1/L2/L3
  - 长任务优先调用 workspace_sync_sniff_artifacts 把 context/plan 写入任务空间
  - 改动前调用 memory_plan_change 与 memory_verify_checklist
  - 涉及 DTO/Feign/MQ 再调用 workspace_check_contract
  - 完成后调用 workspace_sync_case_artifacts 与 workspace_record_case 沉淀经验
```

### 4.9 生成

```bash
# 生成 Wiki
memory-center generate-wiki --workspace .memory-center/workspace.yaml

# 生成 Skills
memory-center generate-skills --workspace .memory-center/workspace.yaml
```

### 4.10 Workspace 管理

```bash
# 查看状态
memory-center status --workspace .memory-center/workspace.yaml

# 添加服务
memory-center workspace add --workspace .memory-center/workspace.yaml \
  --name risk-engine --path risk-engine --type spring-boot-service

# 移除服务
memory-center workspace remove --workspace .memory-center/workspace.yaml \
  --name risk-engine
```

### 4.11 全局注册与分组

```bash
# 注册 workspace 到全局注册表
memory-center registry add --name my-project \
  --workspace /path/to/.memory-center/workspace.yaml

# 列出已注册 workspace
memory-center registry list

# 创建分组
memory-center group create --name my-team --members my-project,other-project

# 将 workspace 添加到分组
memory-center group add --group my-team --repo my-project

# 启动 HTTP Bridge
memory-center serve-http --workspace .memory-center/workspace.yaml --port 8090
```

---

## 五、工件系统（Artifacts）

### 5.1 共享工件类型

| 名称 | 文件 | 用途 |
|------|------|------|
| `context` | `context.md` | 项目上下文概览（自动生成，也可手动编辑） |
| `requirement` | `requirement.md` | 需求文档 |
| `design` | `design.md` | 设计文档 |
| `plan` | `plan.md` | 实施计划 |
| `test_plan` | `test-plan.md` | 测试计划 |
| `change_log` | `change-log.md` | 变更日志（append-only，自动 compact） |

### 5.2 工件操作流

```
list_artifacts          → 列出所有工件及其状态
get_artifact(name)      → 读取工件完整内容
artifact_outline(name)  → 读取工件大纲（Markdown 章节）
artifact_context(intent) → 按意图从所有工件提取相关片段
update_artifact(name, content) → 完整替换工件内容
append_change_log(entry) → 追加变更日志条目（带时间戳）
compact_change_log(keep_recent=30) → 超出 N 条的归档到 .archive.md
```

### 5.3 变更日志归档机制

`append_change_log` 每次写入后自动调用 `compact_change_log`：

```
change-log.md            ← 保留最近 30 条
change-log.archive.md    ← 更早的条目追加到这里
```

归档格式：`## {timestamp}\n\n{entry}\n`

### 5.4 工件自动同步

`sniff` 结果可通过 `workspace_sync_sniff_artifacts_tool` 同步到 `context.md` 和 `plan.md`，减少 Agent 手动写入。

`auto_sync_mode` 控制同步行为：

| 模式 | 行为 |
|------|------|
| `strict` | 高阈值匹配，建议人工确认后同步 |
| `balanced` | 默认策略，匹配分数与风险等级共同决定建议 |
| `aggressive` | 低阈值匹配，更积极地自动命中任务空间 |

---

## 六、任务空间（Task Spaces）

### 6.1 生命周期

```
创建 ──→ draft ──→ active ──→ done ──→ archived
                  ↗               ↗
              blocked          （auto-archive）
```

状态转换：

| 当前状态 | 可转为 |
|---------|--------|
| `draft` | `active`, `archived` |
| `active` | `blocked`, `done`, `archived` |
| `blocked` | `active`, `archived` |
| `done` | `archived` |
| `archived` | — （终态） |

### 6.2 存储结构

```
.memory-center/artifacts/tasks/
└── {task-id}/
    ├── meta.json            # 任务元数据（title, owner, tags, priority, status）
    ├── context.md           # 任务上下文
    ├── requirement.md       # 任务需求
    ├── design.md            # 任务设计
    ├── plan.md              # 任务计划
    ├── test-plan.md         # 测试计划
    ├── current-summary.md   # 当前进展摘要
    └── change-log.md        # 任务变更日志

.memory-center/artifacts/archive/tasks/
└── {task-id}/               # 归档后的任务空间
```

### 6.3 任务空间元数据（meta.json）

```json
{
  "task_id": "abc-123",
  "title": "oldPubTime→newPubTime 迁移",
  "intent": "修改发布时间字段迁移逻辑",
  "owner": "cuijq",
  "tags": ["migration", "kafka"],
  "priority": "high",
  "status": "active",
  "created_at": "2025-05-10T08:00:00Z",
  "last_activity_at": "2025-05-10T14:30:00Z",
  "last_activity_source": "sync-sniff"
}
```

### 6.4 任务空间解析算法

`resolve_task_space` 使用以下策略匹配已有任务空间：

1. 从 `meta.json` 中提取 title / intent / tags
2. 与输入的 intent 做关键词匹配，计算 score
3. 如果最高 score >= `score_threshold`，返回匹配结果
4. 如果 `create_if_missing=true` 且无匹配，创建新任务空间

---

## 七、Session 记忆系统

### 7.1 数据流

```
workspace_start_session
  ↓ session-events.jsonl  (event_type: session_start)
  ↓
workspace_log_session_event (×N)
  ↓ session-events.jsonl  (event_type: prompt / tool_call / tool_result / note)
  ↓
workspace_end_session
  ↓ session-events.jsonl  (event_type: session_end)
  ↓ session-summaries.jsonl  (自动生成摘要)
```

### 7.2 Session 事件格式

```json
{
  "session_id": "abc-123",
  "workspace": "my-project",
  "event_type": "tool_call",
  "payload": {
    "tool": "memory_callers_tool",
    "args": {"symbol": "ArticleDTO"}
  },
  "created_at": "2025-05-10T10:00:00+00:00"
}
```

### 7.3 Session 摘要格式

```json
{
  "session_id": "abc-123",
  "workspace": "my-project",
  "intent": "修复跨月迁移 bug",
  "outcome": "已修复并验证",
  "event_count": 15,
  "files": ["ArticleTimeMigrator.java"],
  "projects": ["article-service"],
  "verified_by": ["test_migration()"],
  "started_at": "2025-05-10T08:00:00+00:00",
  "ended_at": "2025-05-10T10:30:00+00:00"
}
```

### 7.4 上下文恢复

`workspace_resume_context_tool(intent)` 混合以下来源召回上下文：

1. 历史 Session 摘要（关键词匹配 intent）
2. 历史任务案例（关键词匹配 intent）
3. 查询入口（图谱关键词）

---

## 八、规则系统

### 8.1 规则文件格式

```yaml
# .memory-center/rules/custom-rules.yaml
rules:
  - id: CUSTOM-001
    title: "Redis 缓存必须设置 TTL"
    scope: [cache, redis]
    severity: must
    file_patterns: ["**/*Cache*.java", "**/*Redis*.java"]
    trigger_keywords: ["缓存", "Redis", "cache", "TTL"]
    rule: "所有 Redis 缓存写入必须设置过期时间，不能用永久缓存。"
    reason: "无 TTL 的缓存会导致内存泄漏和数据不一致。"
    checklist:
      - "是否有 TTL 设置"
      - "TTL 是否合理（非硬编码常量）"
      - "是否有缓存穿透保护"
```

### 8.2 severity 级别

| 级别 | 含义 |
|------|------|
| `must` | 必须遵守，违反会导致线上问题 |
| `should` | 应该遵守，违反有风险但不致命 |
| `may` | 建议遵守，非强制 |

### 8.3 匹配算法详解

```
score = 0
for each rule:
  if rule.scope ∩ input.scopes ≠ ∅:    score += 3
  if rule.trigger_keywords ∩ intent:    score += 2
  if files match rule.file_patterns:    score += 3

if no input at all:                     score = 1 (返回全部规则)
```

---

## 九、多 Workspace 管理

### 9.1 全局注册表

位置：`~/.memory-center/registry.json`

```json
{
  "version": "1.0",
  "repos": [
    {
      "name": "project-a",
      "workspace_file": "/Users/dev/project-a/.memory-center/workspace.yaml",
      "path": "/Users/dev/project-a",
      "last_registered_at": "2025-05-01T00:00:00+00:00"
    },
    {
      "name": "project-b",
      "workspace_file": "/Users/dev/project-b/.memory-center/workspace.yaml",
      "path": "/Users/dev/project-b",
      "last_registered_at": "2025-05-01T00:00:00+00:00"
    }
  ],
  "groups": [
    {
      "name": "my-team",
      "members": ["project-a", "project-b"],
      "created_at": "2025-05-01T00:00:00+00:00"
    }
  ]
}
```

### 9.2 分组操作

```bash
# 创建分组
memory-center group create --name my-team --members project-a,project-b

# 添加成员
memory-center group add --group my-team --repo project-c
```

### 9.3 跨 Workspace 查询

```bash
# 跨 workspace 搜索
# (CLI: 无直接命令，通过 MCP tool)
# MCP: group_query_tool(group="my-team", query="ArticleDTO")

# 聚合状态
# MCP: group_status_tool(group="my-team")

# 跨 workspace 影响分析
# MCP: group_impact_tool(group="my-team", target="ArticleDTO", direction="upstream")
```

---

## 十、HTTP API 参考

### 10.1 启动

```bash
memory-center serve-http \
  --workspace .memory-center/workspace.yaml \
  --host 127.0.0.1 \
  --port 8090
```

### 10.2 端点清单

| 方法 | 路径 | 说明 | 对应 MCP Tool |
|------|------|------|--------------|
| `GET` | `/health` | 健康检查 | — |
| `GET` | `/workspace/status` | 工作区状态 | `workspace_status_tool` |
| `POST` | `/workspace/query` | 图感知搜索 | `memory_query_tool` |
| `POST` | `/workspace/search-code` | 关键词搜索 | `memory_search_code_tool` |
| `GET` | `/workspace/symbol` | 符号解析 | `memory_symbol_tool` |
| `GET` | `/workspace/callers` | 上游调用链 | `memory_callers_tool` |
| `GET` | `/workspace/callees` | 下游调用链 | `memory_callees_tool` |
| `POST` | `/workspace/plan-change` | 变更计划 | `memory_plan_change_tool` |
| `POST` | `/workspace/verify-checklist` | 验证检查清单 | `memory_verify_checklist_tool` |
| `POST` | `/workspace/detect-changes` | Git 变更检测 | `memory_detect_changes_tool` |
| `GET` | `/workspace/artifacts` | 工件列表 | `workspace_artifact_list_tool` |
| `GET` | `/workspace/artifacts/{name}` | 读取工件 | `workspace_artifact_get_tool` |
| `PUT` | `/workspace/artifacts/{name}` | 更新工件 | `workspace_artifact_update_tool` |
| `GET` | `/workspace/task-spaces` | 任务空间列表 | `workspace_task_space_list_tool` |
| `POST` | `/workspace/task-spaces` | 创建任务空间 | `workspace_task_space_create_tool` |
| `GET` | `/group/status` | 分组状态 | `group_status_tool` |
| `POST` | `/group/query` | 分组查询 | `group_query_tool` |
| `POST` | `/group/impact` | 分组影响分析 | `group_impact_tool` |

---

## 十一、Agent 集成模式

### 11.1 Claude Code 集成

**方式 A：MCP stdio（推荐）**

```json
// .claude/settings.json
{
  "mcpServers": {
    "memory-center": {
      "command": "memory-center-mcp",
      "args": ["--workspace", "/absolute/path/.memory-center/workspace.yaml"]
    }
  }
}
```

**方式 B：MCP Streamable HTTP**

```json
{
  "mcpServers": {
    "memory-center": {
      "url": "http://127.0.0.1:8090/mcp"
    }
  }
}
```

### 11.2 推荐 Agent 工作流

```
1. [开始任务]
   → workspace_sniff_tool(intent)          # 获取上下文 + 风险评估

2. [深入分析]
   → memory_search_code_tool(query)        # 缩小范围
   → memory_symbol_tool(name)              # 定位符号
   → memory_callers_tool(symbol)           # 上游调用链
   → memory_callees_tool(symbol)           # 下游调用链

3. [安全检查]
   → workspace_check_rules_tool(...)       # 架构规则
   → workspace_check_contract_tool(...)    # 契约安全（如涉及 DTO/Feign/MQ）
   → memory_plan_change_tool(target)       # 变更计划
   → memory_verify_checklist_tool(target)  # 验证清单

4. [编码实施]
   → （Agent 编码）

5. [经验沉淀]
   → workspace_end_session_tool(...)       # 结束 Session
   → workspace_sync_case_artifacts_tool(...) # 同步 design/change-log/current-summary
   → workspace_record_case_tool(...)       # 记录长期经验
```

### 11.3 Agent 指令文件

Memory Center 可生成以下指令文件，要求 Agent 在工作前先调用 MCP：

| 文件 | Agent | 路径 |
|------|-------|------|
| `CLAUDE.md` | Claude Code | 项目根目录 |
| `AGENTS.md` | 通用 | 项目根目录 |
| `GEMINI.md` | Gemini | 项目根目录 |
| `.github/copilot-instructions.md` | GitHub Copilot | `.github/` |
| `.cursor/rules/memory-center.mdc` | Cursor | `.cursor/rules/` |

---

## 十二、配置参考

### 12.1 workspace.yaml 完整字段

```yaml
workspace: string         # 工作区名称（必填）
root: string              # 项目根目录，相对于 workspace.yaml 所在目录（可选，默认上一级）
language: [string]        # 偏好语言（可选，默认 [zh-CN, en-US]）

services:                 # 服务列表（必填）
  - name: string          #   服务标识名（必填）
    path: string          #   相对于 root 的路径（必填）
    type: string          #   服务类型（可选，默认 spring-boot-service）
    service_name: string  #   Spring 服务名（可选，默认同 name）
    port: int             #   端口（可选）
    tags: [string]        #   标签列表（可选）
```

### 12.2 服务类型说明

| type | 扫描行为 |
|------|---------|
| `spring-boot-service` | 扫描 Java 文件 + 配置文件 |
| `spring-cloud-gateway` | 同上 |
| `spring-boot-task` | 同上 |
| `shared-library` | 同上（通常标记 `contract` 或 `common` 标签） |

### 12.3 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_CENTER_SEMANTIC_BACKEND` | `sparse` | 语义后端（`sparse` / `sentence-transformers`） |
| `MEMORY_CENTER_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | sentence-transformers 嵌入模型 |
| `MEMORY_CENTER_WORKSPACE` | — | 默认 workspace.yaml 路径 |

### 12.4 文件锁

所有写操作使用 `filelock` 保证并发安全，锁文件位于 `.memory-center/store.lock`。

### 12.5 路径安全

`WorkspaceStore` 对所有文件操作做路径安全校验，防止目录遍历攻击：

```python
def _safe_path(base: Path, name: str) -> Path:
    candidate = (base / name).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise ValueError(f"invalid path: {name}")
    return candidate
```

---

## 附录 A：数据流全景图

```
输入                    处理层                   存储
───────────────────────────────────────────────────────
workspace.yaml    →  config.py 解析        →  WorkspaceConfig
.java 文件        →  indexer.py 扫描        →  7 个 JSON 索引
                    →  graph.py 构建         →  SQLite graph.db
                    →  semantic.py 向量化    →  semantic-node-index.json

intent 文本       →  orchestrator.sniff     →  （不存储，返回结果）
                    →  orchestrator.query

task 案例         →  orchestrator.record    →  cross-service-task-memory.jsonl
                                              （含 source_session_id / source_task_id / source_refs）
session 事件      →  orchestrator.session   →  session-events.jsonl
                                                    session-summaries.jsonl
                                                    memory/refs/sessions/*

工件内容          →  artifacts.py           →  artifacts/*.md
任务空间          →  artifacts.py           →  artifacts/tasks/{id}/*.md

规则配置          →  rules.py               →  rules/*.yaml

wiki 生成         →  wiki.py                →  wiki/*.md
skills 生成       →  wiki.py                →  skills/generated/*/SKILL.md
```

## 附录 B：快速排错

| 问题 | 排查方向 |
|------|---------|
| `reindex` 后 graph_nodes=0 | 检查 workspace.yaml 中 services 的 path 是否正确 |
| MCP server 启动失败 | `pip install -e .[mcp]` 安装 MCP 依赖 |
| 语义搜索无结果 | 检查 `semantic-node-index.json` 是否存在；sparse 后端默认可用 |
| FTS5 不可用 | 某些嵌入式 SQLite 不含 FTS5，自动回退到 LIKE 搜索 |
| 文件锁超时 | 删除 `.memory-center/store.lock` 后重试 |
| workspace 路径找不到 | `memory-center registry list` 检查注册表 |
