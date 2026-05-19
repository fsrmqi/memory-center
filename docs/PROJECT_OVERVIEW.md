# Memory Center 项目全景文档

> 版本：1.3.0  |  语言：Python 3.10+  |  状态：Beta

---

## 一、项目定位

Memory Center（记忆中心）是一个 **面向 AI 编程助手的 MCP 原生项目记忆与知识图谱服务**。

**要解决的核心问题：** 传统 AI 编程助手（Claude Code、Cursor、Copilot、Codex 等）在大型 Spring Cloud 系统中进行跨服务开发时，依赖临时 grep 和文件遍历，无法感知服务间 Feign 调用、MQ 消息契约、配置依赖和历史经验，导致生成的代码缺乏全局正确性保障。

**解决思路：** 预先扫描项目结构，构建本地知识图谱（Graph-first），将项目的关系、契约、规则和历史经验统一存储，通过 MCP 协议暴露给 AI Agent，使 Agent 在编码前就能获取完整上下文。

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────┐
│                  AI Coding Agents                        │
│       Claude Code / Cursor / Copilot / Codex / Gemini    │
└────────────────────────┬────────────────────────────────┘
                         │  MCP stdio / HTTP
                         ▼
┌─────────────────────────────────────────────────────────┐
│               Agent Protocol Layer                       │
│   MCP Server (42 tools, 3 resources, 2 prompts)         │
│   HTTP Bridge Server (REST API)                         │
│   Agent Instruction Files (CLAUDE.md / AGENTS.md etc.)  │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│             Context Orchestrator                         │
│   intent 解析 → 规则匹配 → 图谱检索 → 案例召回 → 风险评估  │
└────────────────────────┬────────────────────────────────┘
                         │
            ┌────────────┼─────────────┐
            ▼            ▼             ▼
   ┌──────────────┐ ┌─────────┐ ┌──────────┐
   │  Rule Center │ │ Memory  │ │  Graph   │
   │  YAML 规则   │ │  JSONL  │ │  SQLite  │
   └──────────────┘ └─────────┘ └──────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│                Workspace Index Layer                      │
│   file-index / java-symbol / api / feign / mq / config  │
│   service-topology / semantic-index                      │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│             Spring Cloud Workspace                       │
│   gateway / services / common-api / common-core / ...    │
└─────────────────────────────────────────────────────────┘
```

五层架构各司其职：

| 层 | 职责 | 核心产物 |
|---|---|---|
| **Workspace** | 定义多服务工作区 | `workspace.yaml` |
| **Indexer** | 扫描服务，提取文件/符号/API/Feign/MQ/配置/拓扑 | 7 个 JSON 索引 + SQLite 图谱 |
| **Rule Center** | 存储团队约束与架构守则 | YAML 规则文件 |
| **Memory** | 记录已完成任务的工程经验 | JSONL 案例 + Session 日志 |
| **Agent Protocol** | 将以上能力通过 MCP/HTTP 暴露给 Agent | MCP tools / resources / prompts |

---

## 三、项目结构

```
memory-center/
├── memory_center/                  # Python 源码包
│   ├── cli/                        # CLI 入口 (memory-center 命令)
│   │   └── main.py                 #   Typer 应用，全部子命令定义
│   ├── core/                       # 核心业务逻辑
│   │   ├── orchestrator.py         #   主编排层：sniff/query/context/impact 等
│   │   ├── indexer.py              #   索引器：扫描 workspace 生成索引
│   │   ├── graph.py                #   SQLite 知识图谱存储与查询
│   │   ├── semantic.py             #   语义检索 (sparse TF-IDF / sentence-transformers)
│   │   ├── artifacts.py            #   共享工件管理 (context/design/plan/changelog)
│   │   ├── config.py               #   workspace.yaml 加载与维护
│   │   ├── store.py                #   WorkspaceStore 磁盘抽象
│   │   ├── rules.py                #   规则加载与匹配
│   │   ├── registry.py             #   全局 workspace 注册与分组
│   │   ├── models.py               #   数据模型定义
│   │   ├── wiki.py                 #   Wiki / Skills 文档生成
│   │   ├── instructions.py         #   Agent 指令文件生成
│   │   ├── exporters.py            #   Mermaid 拓扑图导出
│   │   ├── validators.py           #   workspace 校验 (doctor)
│   │   ├── text_utils.py           #   文本分词工具
│   │   └── indexing/               #   语言解析器
│   │       ├── base.py             #     解析器协议定义
│   │       └── java_regex_parser.py#     正则 Java/Spring 解析器
│   ├── mcp/                        # MCP Server
│   │   └── server.py               #   42 tools + 3 resources + 2 prompts
│   ├── http/                       # HTTP Bridge Server
│   │   └── server.py               #   REST API for Web UI / IDE
│   └── templates/                  # 生成模板 (CLAUDE.md 等)
│
├── tests/                          # 测试套件
│   └── test_public_mvp.py          #   核心功能测试
│
├── docs/                           # 文档 (15+ 篇)
│   ├── ARCHITECTURE.md             #   架构说明
│   ├── PROJECT_OVERVIEW.md         #   ← 本文档
│   ├── MCP_TOOLS.md                #   MCP 工具完整规格
│   ├── WORKSPACE_SPEC.md           #   Workspace 配置规格
│   ├── RULES_SPEC.md               #   规则规格
│   ├── SPRING_CLOUD_INDEXING.md    #   Spring Cloud 索引细节
│   ├── GRAPH_FIRST_DESIGN.md       #   Graph-first 设计哲学
│   ├── DESIGN.md                   #   设计理念
│   ├── MCP_SECURITY.md             #   安全模型
│   ├── LOCAL_USAGE_GUIDE.md        #   本地使用指南
│   └── ...
│
├── examples/                       # 示例项目
│   └── spring-cloud-demo/          #   带 .memory-center 配置的示例
│
├── pyproject.toml                  # Python 项目元数据与依赖
├── install.sh                      # 一键安装脚本
└── README.md                       # 项目 README
```

---

## 四、三大接入入口

Memory Center 提供三种独立的服务入口，面向不同使用场景：

### 4.1 CLI 命令行（`memory-center`）

```bash
memory-center <command> [options]
```

**核心命令一览：**

| 分类 | 命令 | 说明 |
|------|------|------|
| **初始化** | `init` | 创建 workspace 目录和默认 workspace.yaml |
| **索引** | `reindex` | 全量重建所有索引（文件/符号/API/Feign/MQ/配置/拓扑/图谱） |
| **查询** | `query` | 图感知关键词搜索 |
| | `search-code` | 纯关键词代码搜索 |
| | `symbol` | 符号解析（类名/方法名 → 所在文件/行号） |
| | `callers` / `callees` | 上游调用链 / 下游调用链遍历 |
| | `context` | 符号 360° 全面上下文 |
| **变更分析** | `impact` | 影响面分析（upstream / downstream） |
| | `plan-change` | 变更计划生成 |
| | `verify-checklist` | 合并前检查清单 |
| | `detect-changes` | Git 变更 → 受影响项目/规则映射 |
| **契约** | `contracts` | 列出 Feign / API / MQ 契约 |
| | `check-contract` | 修改契约文件前的安全检查 |
| **规则** | `check-rules` | 根据 intent/文件/范围匹配架构规则 |
| **经验** | `record-case` | 记录已验证的任务经验 |
| | `sniff` | 编码前获取任务上下文（核心入口） |
| **Session** | `start-session` / `log-session-event` / `end-session` | 轻量 Session 追踪 |
| **生成** | `generate-wiki` / `generate-skills` | 从记忆生成文档/技能文件 |
| **管理** | `status` | 查看索引状态 |
| | `serve-http` | 启动 HTTP Bridge 服务 |
| | `registry add/remove/list` | 全局 workspace 注册 |
| | `group create/add/remove` | workspace 分组 |

### 4.2 MCP Server（`memory-center-mcp`）

通过 stdio 或 Streamable HTTP 协议接入 AI Agent，提供 **42 个 tools**、**3 个 resources**、**2 个 prompts**。

**Tools 按功能域分类：**

| 功能域 | Tools | 说明 |
|--------|-------|------|
| **任务嗅探** | `workspace_sniff_tool` | 编码前自动收集上下文（核心入口） |
| **图谱查询** | `memory_query_tool`, `memory_search_code_tool`, `memory_symbol_tool` | 搜索、符号解析 |
| **调用链** | `memory_callers_tool`, `memory_callees_tool` | 上游/下游调用链 |
| **上下文** | `memory_context_tool` | 360° 上下文 |
| **变更分析** | `memory_impact_tool`, `memory_plan_change_tool`, `memory_verify_checklist_tool`, `memory_detect_changes_tool` | 影响面、计划、检查清单、变更映射 |
| **契约管理** | `memory_contracts_tool`, `workspace_check_contract_tool`, `workspace_trace_tool` | 契约列表、安全检查、跨服务追踪 |
| **规则检查** | `workspace_check_rules_tool` | 架构规则匹配 |
| **经验记忆** | `workspace_record_case_tool`, `workspace_resume_context_tool`, `workspace_suggest_case_tool` | 案例记录、上下文恢复、案例建议 |
| **Session** | `workspace_start_session_tool`, `workspace_log_session_event_tool`, `workspace_end_session_tool`, `workspace_session_summary_tool` | Session 生命周期 |
| **工件管理** | `workspace_artifact_*_tool`, `workspace_task_space_*_tool` | 共享工件与任务空间 CRUD |
| **Task Space** | `workspace_task_space_create_tool`, `workspace_task_space_list_tool`, `workspace_task_space_resolve_tool`, `workspace_task_status_tool`, `workspace_task_archive_tool` 等 | 任务空间生命周期管理 |
| **生成** | `memory_generate_wiki_tool`, `memory_generate_skills_tool` | Wiki / Skills 生成 |
| **状态** | `workspace_status_tool`, `workspace_sniff_tool` | 工作区状态查询 |
| **多 Workspace** | `group_query_tool`, `group_status_tool`, `group_impact_tool` | 跨 Workspace 联合查询 |

**Resources：**
- `memory-center://status` — 工作区索引状态
- `memory-center://contracts` — 已发现的 Feign/API/MQ 契约
- `memory-center://topology` — 服务拓扑图

**Prompts：**
- `detect_impact(target)` — 影响面检测工作流模板
- `spring_cloud_safe_change(task)` — Spring Cloud 安全变更工作流模板

### 4.3 HTTP Bridge Server（`memory-center-http`）

为 Web UI、IDE 插件和轻量自动化提供 REST API，所有 MCP 核心能力均可通过 HTTP 调用：

```
GET  /health
GET  /workspace/status
POST /workspace/query
POST /workspace/search-code
GET  /workspace/symbol
GET  /workspace/callers | /callees
POST /workspace/plan-change
POST /workspace/verify-checklist
GET  /workspace/artifacts
POST /workspace/task-spaces
GET  /group/status | /group/query | /group/impact
```

---

## 五、核心模块详解

### 5.1 知识图谱（`core/graph.py`）

采用 SQLite 实现轻量图存储，零外部依赖。

**数据模型：**
```
GraphNode:
  id: str           # 唯一 ID，格式 "kind:project:path:name"
  type: str         # 节点类型（见下表）
  name: str
  project: str
  file_path: str
  line: int
  metadata: dict

GraphEdge:
  id: str           # 唯一 ID，格式 "edge_type:source->target"
  source_id: str
  target_id: str
  type: str         # 边类型（见下表）
  confidence: float  # 置信度
  metadata: dict
```

**节点类型（16+ 种）：**

| 节点类型 | 说明 |
|----------|------|
| `service` | 微服务 |
| `file` | 源码文件 |
| `class` | Java 类 |
| `interface` | Java 接口 |
| `method` | 方法 |
| `api_endpoint` | REST API 端点 |
| `feign_client` | Feign 客户端 |
| `feign_method` | Feign 方法 |
| `mq_topic` | MQ Topic |
| `mq_producer` | MQ 生产者 |
| `mq_consumer` | MQ 消费者 |
| `config_property` | 配置属性 |
| `dto` | 数据传输对象 |
| `bean` | Spring Bean |
| `data_resource` | 数据资源（ES Index / Mongo Collection） |
| `annotation` | 注解 |

**边类型（14+ 种）：**

| 边类型 | 说明 |
|--------|------|
| `calls` | 方法调用 |
| `injects` | Bean 注入 |
| `produces_to` | MQ 生产 |
| `consumes_from` | MQ 消费 |
| `feign_calls` | Feign 远程调用 |
| `uses_dto` | 使用 DTO |
| `uses_config` | 使用配置 |
| `belongs_to` | 属于（方法→类，类→文件等） |
| `contains` | 包含（服务→文件等） |
| `exposes_api` | 暴露 API |
| `implements` | 实现接口 |
| `extends` | 继承 |
| `uses_resource` | 使用数据资源 |
| `endpoint_for` | 端点对应方法 |

**查询能力：**
- `find_nodes(query, types)` — FTS5 全文检索，回退 LIKE 模糊匹配
- `neighbors(node_id, direction, max_depth)` — BFS 多跳邻居遍历（支持 upstream/downstream/both）
- `rebuild_search_index()` — 重建 FTS5 索引

### 5.2 Java 解析器（`core/indexing/java_regex_parser.py`）

基于正则表达式的 Java/Spring 轻量解析器，零外部依赖。

**提取能力：**
- 包名、类名、接口名、方法名、字段名
- 注解（`@RestController`、`@FeignClient`、`@KafkaListener` 等）
- Bean 注入关系（`@Autowired`、`@Resource`、`@RequiredArgsConstructor`、构造器注入）
- 方法调用关系（含接收者类型推断）
- DTO 字段使用（getter/setter 调用）
- 配置属性使用（`@Value`、`@ConfigurationProperties`）
- 数据资源声明（`@Document`、MongoDB/ES 相关注解）

**设计原则：** 保守提取——只提取高置信度的证据，不猜测。未来可通过实现同一接口替换为 tree-sitter-java 解析器。

### 5.3 语义检索（`core/semantic.py`）

提供两种语义后端：

| 后端 | 算法 | 适用场景 |
|------|------|---------|
| `sparse`（默认） | TF-IDF 稀疏向量 + 余弦相似度 | 零依赖，开箱即用 |
| `sentence-transformers` | Dense embedding + 余弦相似度 | 高精度语义匹配 |

**配置：**
```bash
# 切换后端
export MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers

# 指定嵌入模型
export MEMORY_CENTER_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

**工作流程：**
1. `reindex` 时自动构建语义索引（`semantic-node-index.json`）
2. 每个图节点 → 分词 → TF-IDF 向量化 → 持久化
3. 查询时计算 query 向量与所有文档向量的余弦相似度
4. 返回按相关性排序的结果

### 5.4 编排器（`core/orchestrator.py`）

编排器是 Memory Center 的大脑，协调索引、图谱、规则、语义、工件等所有子系统。

**核心流程 `sniff`（任务嗅探）：**

```
输入: intent（任务描述）
  │
  ├─ 分词 → 关键词提取
  │
  ├─ 并行检索：
  │   ├─ file-index   → 匹配文件
  │   ├─ java-symbol  → 匹配符号
  │   ├─ api-index    → 匹配 API
  │   ├─ feign-index  → 匹配 Feign
  │   ├─ mq-index     → 匹配 MQ
  │   ├─ cases        → 匹配历史经验
  │   └─ sessions     → 匹配历史 Session
  │
  ├─ 规则匹配 → 相关架构规则
  │
  ├─ 风险评估 → low / medium / high / critical
  │
  ├─ Task Space 解析 → 匹配或创建任务空间
  │
  └─ 自动同步推荐 → 基于风险等级决定是否同步工件
```

**风险评估因素：**
- 涉及多个服务 → 升级
- 涉及 Feign 调用 → 升级
- 涉及 MQ 消息 → 升级
- 匹配到 `must` 级别规则 → 升级
- 历史案例有风险点记录 → 升级

### 5.5 规则中心（`core/rules.py`）

规则是可配置的 YAML 文件，存储团队的架构约束和工程守则。

**默认内置 5 条规则：**

| ID | 标题 | 严重级别 |
|----|------|---------|
| `MQ-001` | MQ 消费必须保证幂等 | must |
| `CONTRACT-001` | 公共契约禁止破坏性变更 | must |
| `ES-001` | ES 写入必须确认别名和批量失败处理 | must |
| `LOG-001` | 核心链路日志必须包含上下文标识 | must |
| `DATA-001` | 跨时间分表迁移必须保证一致性 | must |

**每条规则包含：**
- `scope` — 适用范围关键词
- `trigger_keywords` — 触发关键词
- `file_patterns` — 文件 glob 模式
- `rule` — 规则描述
- `reason` — 原因说明
- `checklist` — 检查清单

**匹配算法：**
- scope 匹配 +3 分
- trigger_keyword 匹配 +2 分
- file_pattern 匹配 +3 分
- 按总分降序排列

### 5.6 工件管理（`core/artifacts.py`）

**共享工件（Shared Artifacts）：**
- `context` — 项目上下文概览
- `requirement` — 需求文档
- `design` — 设计文档
- `plan` — 实施计划
- `test-plan` — 测试计划
- `change-log` — 变更日志

**任务空间（Task Spaces）：**
- 每个任务有独立的工件空间
- 生命周期：`draft → active → done → archived`
- 支持自动归档（基于保留天数）
- 包含独立的 change-log

### 5.7 Session 记忆

轻量级任务 Session 追踪：

```
workspace_start_session → workspace_log_session_event (×N) → workspace_end_session
```

Session 事件类型：`prompt`、`tool_call`、`tool_result`、`note`

Session 总结存储在 `session-summaries.jsonl`，支持后续上下文恢复。

### 5.8 多 Workspace 支持

```
全局注册表 (~/.memory-center/registry.json)
  ├─ workspace A (spring-cloud-project-a)
  ├─ workspace B (spring-cloud-project-b)
  └─ group "my-team"
       ├─ workspace A
       └─ workspace B
```

- `group_query_tool` — 跨 workspace 联合搜索
- `group_status_tool` — 聚合状态查看
- `group_impact_tool` — 跨 workspace 影响分析

---

## 六、Workspace 配置规格

### 6.1 workspace.yaml 结构

```yaml
workspace: my-spring-cloud          # 工作区名称
root: ..                            # 项目根目录（相对于 workspace.yaml 所在目录）
language: [zh-CN, en-US]            # 偏好语言

services:
  - name: gateway                   # 服务标识名
    path: gateway                   # 相对于 root 的路径
    type: spring-cloud-gateway      # 服务类型
    service_name: gateway           # Spring 服务名
    port: 8080                      # 端口（可选）
    tags: [入口]                     # 标签

  - name: common-api
    path: common-api
    type: shared-library            # 共享库类型
    tags: [contract]

  - name: article-service
    path: article-service
    type: spring-boot-service
    service_name: article-service
```

### 6.2 支持的服务类型

| 类型 | 说明 |
|------|------|
| `spring-boot-service` | 标准 Spring Boot 微服务 |
| `spring-cloud-gateway` | Spring Cloud Gateway |
| `spring-boot-task` | 定时任务 / 批处理服务 |
| `shared-library` | 共享库（common-api / common-core） |

### 6.3 数据目录结构

索引后的 `.memory-center/` 目录：

```
.memory-center/
├── workspace.yaml                   # 工作区配置
├── index/                           # JSON 索引
│   ├── file-index.json              #   文件索引
│   ├── java-symbol-index.json       #   Java 符号索引
│   ├── api-index.json               #   REST API 索引
│   ├── feign-index.json             #   Feign 客户端索引
│   ├── mq-index.json                #   MQ 端点索引
│   ├── config-index.json            #   配置属性索引
│   └── service-topology.json        #   服务拓扑
├── graph/                           # SQLite 图谱
│   └── graph.db
├── memory/                          # 经验记忆
│   ├── cross-service-task-memory.jsonl
│   ├── session-events.jsonl
│   └── session-summaries.jsonl
├── rules/                           # 架构规则
│   └── global-rules.yaml
├── artifacts/                       # 共享工件
│   ├── context.md
│   ├── design.md
│   ├── plan.md
│   └── change-log.md
└── task-spaces/                     # 任务空间
    └── <task-id>/
        ├── context.md
        ├── plan.md
        └── change-log.md
```

---

## 七、典型工作流

### 7.1 初始化流程

```bash
# 1. 创建 workspace
memory-center init --workspace-root /path/to/spring-cloud --name my-project

# 2. 编辑 workspace.yaml，声明服务
vim .memory-center/workspace.yaml

# 3. 全量索引
memory-center reindex --workspace .memory-center/workspace.yaml

# 4. 查看状态
memory-center status --workspace .memory-center/workspace.yaml
```

### 7.2 AI Agent 辅助开发流程

```bash
# 1. Agent 接收任务："修改 article-service 的发布时间字段迁移逻辑"

# 2. 调用 sniff 获取上下文
memory-center sniff --workspace .memory-center/workspace.yaml \
  --intent "oldPubTime newPubTime Kafka 迁移分表"

#   返回：
#   ├── risk_level: high（跨服务 + MQ + 匹配 DATA-001 规则）
#   ├── matched_services: [article-service, task-service, common-api]
#   ├── candidate_files: [ArticleTimeMigrator.java, ...]
#   ├── related_feigns: [ArticleFeignClient.updatePubTime]
#   ├── related_mq: [topic: article-migration, consumer: task-service]
#   ├── related_rules: [DATA-001, MQ-001]
#   └── historical_cases: [previous similar migration]

# 3. 影响面分析
memory-center impact --workspace ... --target "ArticleTimeMigrator"

# 4. 变更计划
memory-center plan-change --workspace ... --target "ArticleTimeMigrator"

# 5. 编码完成后记录经验
memory-center record-case --workspace ... \
  --task "oldPubTime→newPubTime 迁移" \
  --projects article-service,task-service \
  --files ArticleTimeMigrator.java,ArticleMigrationConsumer.java
```

### 7.3 MCP Server 使用（Claude Code 配置）

```json
// .claude/settings.json
{
  "mcpServers": {
    "memory-center": {
      "command": "memory-center-mcp",
      "args": ["--workspace", "/path/to/.memory-center/workspace.yaml"]
    }
  }
}
```

Agent 可直接调用 42 个 MCP tools，实现完整的上下文感知开发。

---

## 八、依赖与安装

### 8.1 核心依赖

| 包 | 用途 |
|---|---|
| `pyyaml` | YAML 配置解析 |
| `filelock` | 文件锁（防止并发索引冲突） |
| `typer` | CLI 框架 |
| `rich` | 终端格式化输出 |

### 8.2 可选依赖

| 包 | 用途 | 安装方式 |
|---|---|---|
| `mcp >= 1.2.0` | MCP Server 运行时 | `pip install memory-center[mcp]` |
| `litellm` | LLM 调用（用于 wiki/skills 生成） | `pip install memory-center[mcp]` |
| `sentence-transformers` | Dense 语义嵌入 | 手动安装 |
| `tree-sitter` | 更精确的代码解析（未来） | 手动安装 |

### 8.3 安装

```bash
# 一键安装（推荐）
cd memory-center && bash install.sh

# 开发安装
python -m venv .venv
source .venv/bin/activate
pip install -e ".[mcp]"

# 验证
memory-center --help
```

---

## 九、安全模型

Memory Center 遵循 **本地优先、只读默认** 原则：

| 方面 | 策略 |
|------|------|
| 数据存储 | 全部本地 SQLite + JSON 文件，无云同步 |
| 写入范围 | MCP write tools 仅限 Memory Center 自有工件（artifacts / task-spaces / session），**不修改业务源码** |
| 索引模式 | 索引器只读扫描，不修改任何项目文件 |
| 敏感数据 | workspace.yaml 不含密码/Token；索引数据不含源码全文 |
| 网络 | 默认离线运行；HTTP Bridge 仅绑定 localhost |

---

## 十、技术特点总结

| 特点 | 说明 |
|------|------|
| **Graph-first** | 关系预计算，查询 O(1) 查找 + O(k) 遍历，非实时 grep |
| **MCP-native** | 原生 42 个 MCP tools，Agent 无需自行拼装 |
| **Local-first** | SQLite + 文件系统，零外部服务依赖 |
| **Spring Cloud 深度索引** | Feign / MQ / Config / Endpoint / DTO / Bean 全链路提取 |
| **Hybrid Retrieval** | Graph 拓扑 + FTS 全文 + 可选语义嵌入，三层检索融合 |
| **经验可沉淀** | 任务完成后 record-case，跨 Session 可复用 |
| **规则可配置** | YAML 规则 + 自动匹配 + 检查清单 |
| **多 Workspace** | 全局注册 + 分组 + 跨 workspace 查询 |
| **零侵入** | 不修改业务代码，不改变现有工作流 |

---

## 十一、后续演进方向

| 方向 | 说明 |
|------|------|
| **更精确解析器** | 替换正则为 tree-sitter-java，提升提取准确率 |
| **增量索引** | 基于 git diff 的增量更新，避免全量重建 |
| **更多语言** | 扩展到 Kotlin / Go / TypeScript |
| **团队共享** | 图谱数据支持远程同步，多 Agent 协作 |
| **IDE 深度集成** | VS Code / JetBrains 插件，利用 HTTP API |
| **LLM 辅助** | 利用 LLM 增强意图理解和规则生成 |

---

## 附录 A：pyproject.toml 摘要

```toml
[project]
name = "memory-center"
version = "1.3.0"
requires-python = ">=3.10"
dependencies = ["pyyaml", "filelock", "typer", "rich"]

[project.optional-dependencies]
mcp = ["mcp>=1.2.0", "litellm"]

[project.scripts]
memory-center = "memory_center.cli.main:app"
memory-center-mcp = "memory_center.mcp.server:main"
memory-center-http = "memory_center.http.server:main"
```

## 附录 B：环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_CENTER_SEMANTIC_BACKEND` | `sparse` | 语义后端 (`sparse` / `sentence-transformers`) |
| `MEMORY_CENTER_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | 嵌入模型名称 |
| `MEMORY_CENTER_WORKSPACE` | - | 默认 workspace.yaml 路径 |
