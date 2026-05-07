# Memory Center / 记忆中心

> **MCP-native project memory and knowledge graph service for AI coding agents.**
>
> **面向 AI 编程助手的 MCP 项目记忆服务：多 Agent 公共空间、项目上下文、知识图谱、影响分析、经验沉淀。**

Memory Center is designed for teams that use Codex, Claude Code, Cursor, GitHub Copilot, Gemini or other coding agents on large Spring Cloud workspaces. It turns a multi-repository backend system into a local, queryable, graph-first memory center.

记忆中心用于解决大型 Spring Cloud 多项目场景下 AI 编程助手“每次从零理解项目、跨服务影响面不清、历史经验无法沉淀、规则容易忘记”的问题。它会把多个项目索引成一个本地知识图谱，并通过 MCP tools/resources/prompts 提供给 AI Agent 使用。

---

## Why / 为什么需要 Memory Center

Traditional coding agents often rely on ad-hoc file reads and grep. That works for small repositories, but it is fragile for Spring Cloud systems where one change may cross:

传统 AI 编程助手一般靠临时读文件、grep、搜索关键词。小项目可以，大型 Spring Cloud 项目很容易失效，因为一个改动往往横跨：

- Gateway routes / 网关路由
- Feign clients / Feign 契约
- Controllers / HTTP API
- Kafka or RocketMQ consumers / 消息消费
- DTOs and MQ messages / 公共 DTO 与消息体
- Elasticsearch, MongoDB, Redis, MySQL / 多种数据资源
- Nacos or application.yml configuration / 配置中心与本地配置
- Historical fixes and team rules / 历史经验与团队规范

Memory Center precomputes these relationships before the agent starts editing.

记忆中心的核心思想是：**不要让 AI 每次临时理解项目，而是在索引阶段提前构建服务图、调用图、契约图、消息图、规则图、经验图。**

---

## Core ideas / 核心思想

### 1. Graph-first project memory / 图优先的项目记忆

Memory Center stores code and service relationships as graph nodes and edges in a local SQLite graph store:

记忆中心把项目关系沉淀为本地 SQLite 图存储：

- Nodes / 节点：Workspace, Service, File, Class, Method, Field, Endpoint, FeignClient, FeignMethod, MQTopic, MQConsumer, ConfigKey, MongoCollection, EsIndex, Rule, TaskMemory
- Edges / 边：CONTAINS, DECLARES, EXPOSES_ENDPOINT, HANDLES_ENDPOINT, CALLS_SERVICE, IMPLEMENTS_FEIGN, CONSUMES_TOPIC, IMPORTS, INJECTS_BEAN, CALLS_METHOD, READS_FIELD, READS_CONFIG, USES_DATA_RESOURCE, RELATED_TO_MEMORY

This makes impact analysis and context retrieval deterministic and explainable.

这样 AI 查询上下文时不是靠猜，而是沿着真实的工程关系返回影响面。

### 2. Spring Cloud deep indexing / Spring Cloud 深度索引

Current scanner supports:

当前支持扫描：

- `@RestController`, `@Controller`, `@RequestMapping`, `@GetMapping`, `@PostMapping`, `@PutMapping`, `@DeleteMapping`
- `@FeignClient`
- `@KafkaListener`
- `@RocketMQMessageListener`
- Java class/interface/method/field/import
- Bean injection hints: `@Autowired`, `@Resource`, `@Inject`, constructor/Lombok-style final fields
- Method-call hints, DTO getter/setter field usage, `@Value` / `@ConfigurationProperties` config usage
- MongoDB / Elasticsearch resource hints
- `application.yml`, `application.yaml`, `bootstrap.yml`, `bootstrap.yaml`
- service topology and Feign/MQ contract indexes

### 3. MCP-native agent access / MCP 原生接入

Memory Center exposes tools, resources and prompts through MCP so coding agents can follow the same workflow:

记忆中心通过 MCP 暴露工具、资源和提示词，让不同 Agent 使用同一套流程：

1. `workspace_sniff_tool(intent)` before code search / 任务开始先取上下文
2. `memory_context_tool(name)` or `memory_impact_tool(target)` before editing important contracts / 改重要契约前做上下文和影响分析
3. `workspace_check_rules_tool(...)` before file changes / 编辑前检查规则
4. `workspace_record_case_tool(...)` after validation / 完成后沉淀经验

### 4. Experience memory / 经验沉淀

Solved tasks can be recorded as JSONL task memory and later used for search, wiki generation and agent skills.

已解决任务会沉淀为任务记忆，可用于后续召回、Wiki 生成和 Agent Skill 生成。

Detailed local setup and multi-project workflow / 详细本地初始化与多项目使用流程：

- [docs/LOCAL_USAGE_GUIDE.md](./docs/LOCAL_USAGE_GUIDE.md)
- [docs/UCAP_ALL_SETUP.md](./docs/UCAP_ALL_SETUP.md)

---

## Installation / 安装

### One-command install / 一条命令安装

If you have the repository locally:

如果仓库已经在本地：

```bash
cd memory-center
bash install.sh
```

After you publish the repository URL, you can also install like GitNexus:

仓库地址发布后，也可以像 GitNexus 一样直接安装：

```bash
curl -fsSL https://raw.githubusercontent.com/fsrmqi/memory-center/main/install.sh | bash
```

The installer uses `pipx` by default and exposes:

安装脚本默认使用 `pipx`，安装后会暴露：

- `memory-center`
- `memory-center-mcp`
- `memory-center-http`

Verify installation:

安装后验证：

```bash
memory-center --version
```

If `pipx` was installed but the current shell still says `command not found: pipx`, add the user bin directory to `PATH` first.

如果 `pipx` 已经安装，但当前 shell 仍然提示 `command not found: pipx`，先把用户 bin 目录加到 `PATH`。

Common macOS fix / macOS 常见修复：

```bash
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
```

Then rerun:

然后重新执行：

```bash
bash install.sh
```

### Enable MCP / 启用 MCP

The base install does not bundle MCP dependencies by default. To enable `memory-center-mcp`:

基础安装默认不附带 MCP 依赖。如果你要启用 `memory-center-mcp`：

```bash
pipx inject memory-center "mcp>=1.2.0"
```

Then verify:

然后验证：

```bash
memory-center-mcp --workspace /path/to/.memory-center/workspace.yaml
```

### Development install / 开发环境安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[mcp]
```

For development:

```bash
pip install -e .[dev,mcp]
pytest -q
```

---

## Quick start / 快速开始

### 1. Create a workspace / 初始化工作区

```bash
memory-center init \
  --workspace-root /path/to/spring-cloud-root \
  --name content-risk-platform
```

Edit:

```text
/path/to/spring-cloud-root/.memory-center/workspace.yaml
```

Example:

```yaml
workspace: content-risk-platform
root: ..
services:
  - name: common-api
    path: common-api
    type: shared-library
    tags: [contract]
  - name: article-service
    path: article-service
    type: spring-boot-service
    service_name: article-service
  - name: task-service
    path: task-service
    type: spring-boot-task
    service_name: task-service
```

### 2. Reindex / 重建索引

```bash
memory-center reindex \
  --workspace /path/to/spring-cloud-root/.memory-center/workspace.yaml
```

This generates:

```text
.memory-center/
  index/
    file-index.json
    java-symbol-index.json
    api-index.json
    feign-index.json
    mq-index.json
    config-index.json
    service-topology.json
    semantic-node-index.json
  graph/
    graph.db
  memory/
    cross-service-task-memory.jsonl
  rules/
    default-rules.yaml
```

Reindex also builds the local semantic node index used by hybrid retrieval.

重建索引时也会同步构建本地语义节点索引，供混合检索使用。

By default the semantic index uses the built-in sparse backend. If `sentence-transformers` is installed, you can switch to a local embedding backend with:

默认情况下语义索引使用内置稀疏后端。如果安装了 `sentence-transformers`，可以通过下面的环境变量切换到本地 embedding backend：

```bash
pip install -e .[semantic-local]
```

```bash
export MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers
export MEMORY_CENTER_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

### 3. Query task context / 查询任务上下文

```bash
memory-center sniff \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --intent "oldPubTime newPubTime ArticleFeignClient 文章发布时间迁移"
```

### 4. Graph query / 图谱查询

```bash
memory-center query \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --text "oldPubTime ArticleFeignClient"
```

Local query now uses hybrid retrieval: graph/FTS exact hits plus an offline sparse semantic index built from graph nodes.

当前查询已支持本地混合召回：图谱/FTS 精确命中 + 基于图节点构建的离线稀疏语义索引。

When a local embedding backend is enabled, the same query path upgrades to dense semantic retrieval automatically, while keeping the sparse backend as a safe fallback.

启用本地 embedding backend 后，同一套查询路径会自动升级为 dense semantic retrieval，同时保留稀疏后端作为安全 fallback。

Workspace query now also exposes `retrieval_summary` and per-match `retrieval_sources`, so agents can tell whether a hit came from exact graph lookup, semantic recall, or both.

工作区查询现在也会返回 `retrieval_summary` 和每条结果的 `retrieval_sources`，便于 Agent 判断命中来自图谱精确检索、语义召回，还是二者混合。

Workspace status and group status also expose semantic backend information, so you can verify whether the active index is using `sparse` or `sentence-transformers`.

工作区状态和分组状态现在也会暴露语义 backend 信息，便于确认当前索引实际使用的是 `sparse` 还是 `sentence-transformers`。

Group query keeps the same hybrid model and now exposes `retrieval_summary` plus per-match `retrieval_sources` so agents can distinguish exact hits from semantic-only recalls.

分组查询也沿用同样的混合召回模型，并额外返回 `retrieval_summary` 与每条结果的 `retrieval_sources`，便于 Agent 区分精确命中和纯语义召回。

### 5. 360-degree context / 符号上下文

```bash
memory-center context \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --name ArticleFeignClient
```

Context output now includes `lookup` and `evidence_summary`, so agents can see both the retrieval entrypoints and the graph evidence density behind the selected node.

上下文输出现在会包含 `lookup` 和 `evidence_summary`，便于 Agent 同时看到命中的召回入口，以及该节点背后的图谱证据密度。

### 6. Impact analysis / 影响面分析

Impact results are evidence-based and split into `confirmed_impacts`, `probable_impacts`, `possible_impacts`, and `unknown_risks`.

影响分析会按证据强弱拆分为 `confirmed_impacts`、`probable_impacts`、`possible_impacts` 和 `unknown_risks`，避免 AI 把弱推断当成精确结论。

Impact output also includes `lookup` and `evidence_summary`, making it explicit whether analysis started from exact graph hits, semantic recall, bridge evidence, or a mix of them.

影响分析输出也会包含 `lookup` 和 `evidence_summary`，明确标识分析入口来自图谱精确命中、语义召回、bridge 证据，还是它们的组合。


```bash
memory-center impact \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --target MoveArticleRequest \
  --direction upstream
```

### 7. Detect git changes / 变更影响分析

```bash
memory-center detect-changes \
  --workspace /path/to/.memory-center/workspace.yaml \
  --scope staged
```

### 8. Generate wiki and skills / 生成 Wiki 和 Agent Skills

```bash
memory-center generate-wiki --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml
memory-center generate-skills --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml
```

---

## MCP server / MCP 服务

```bash
memory-center-mcp \
  --workspace /path/to/.memory-center/workspace.yaml
```

Available MCP tools / MCP 工具：

| Tool | Purpose / 用途 |
|---|---|
| `workspace_sniff_tool` | Task-level context retrieval / 任务上下文召回 |
| `memory_query_tool` | Graph-aware search / 图谱检索 |
| `memory_context_tool` | 360-degree node context / 符号、服务、契约上下文 |
| `memory_impact_tool` | Impact analysis / 影响面分析 |
| `memory_detect_changes_tool` | Git diff risk mapping / Git 变更风险映射 |
| `memory_contracts_tool` | API/Feign/MQ contract list / 契约列表 |
| `workspace_trace_tool` | Cross-service trace hints / 跨服务追踪 |
| `workspace_check_contract_tool` | Contract safety check / 契约变更检查 |
| `workspace_check_rules_tool` | Rule matching / 规则匹配 |
| `workspace_record_case_tool` | Record solved task memory / 任务经验沉淀 |
| `memory_generate_wiki_tool` | Generate bilingual wiki / 生成双语 Wiki |
| `memory_generate_skills_tool` | Generate Agent skills / 生成 Agent Skills |
| `workspace_status_tool` | Index status / 索引状态 |
| `group_query_tool` | Merged query across a registered group / 逻辑分组聚合查询 |
| `group_status_tool` | Aggregated group status, including semantic index readiness / 逻辑分组聚合状态，包含语义索引就绪度 |
| `group_impact_tool` | Cross-workspace impact analysis / 跨工作区影响面分析 |

Available MCP resources / MCP 资源：

- `memory-center://status`
- `memory-center://contracts`
- `memory-center://topology`

Available MCP prompts / MCP 提示词：

- `detect_impact(target)`
- `spring_cloud_safe_change(task)`

---

## Recommended AI agent protocol / 推荐 Agent 协议

Before a coding agent changes code:

AI 编程助手改代码前必须执行：

```text
1. Call workspace_sniff_tool(intent)
2. For important contract/topic/service symbols, call memory_context_tool or memory_impact_tool
3. Before editing files, call workspace_check_rules_tool
4. If changing DTO/Feign/MQ Message, call workspace_check_contract_tool
5. After validation, call workspace_record_case_tool
```

---

## Example: Spring Cloud data migration / 示例：文章发布时间迁移

User task:

```text
新增一个消费任务，消费 accountCode/accountType/url/urlmd5/pageType/oldPubTime/newPubTime，
根据 oldPubTime 找旧数据，再按 newPubTime 挪到对应表。
```

Memory Center should return:

记忆中心应返回：

- Entry service: `task-service` consumer / 入口服务：消费任务
- Contract service: `common-api` DTO or Feign client / 契约服务：公共 DTO 或 Feign 接口
- Business service: `article-service` controller/service/repository / 业务服务
- Related topic: Kafka/RocketMQ topic / 相关 Topic
- Required rules: idempotency, contract compatibility, data migration, ES bulk safety / 必检规则
- Historical cases: similar task records / 历史案例
- Impact path: Consumer → Service → Feign → Controller → ArchiveService → ES/Mongo/DB / 影响链路

---

## Global registry / 全局 Registry

You can register many workspaces globally:

可以把多个工作区注册到全局：

```bash
memory-center registry add \
  --name content-risk-platform \
  --workspace /path/to/.memory-center/workspace.yaml

memory-center registry list
```

Create logical groups:

```bash
memory-center group create --name backend-platform
memory-center group add --name backend-platform --repo content-risk-platform
memory-center group status --name backend-platform
memory-center group query --name backend-platform --text ArticleFeignClient
memory-center group impact --name backend-platform --target ArticleFeignClient
```

This enables group-level querying and organization-level memory.

现在已经可以做 group 级聚合查询和状态汇总。

`group status` returns aggregated index counts and `bridge_counts`.

`group status` 会返回聚合索引统计和 `bridge_counts`。

`group query` returns merged search results plus `related_bridges`, such as Feign → service, Feign → endpoint, MQ topic ↔ config, and shared config-key hints.

`group query` 除了聚合搜索结果，还会返回 `related_bridges`，例如 Feign → 服务、Feign → 接口、MQ Topic ↔ 配置、共享配置键等跨工作区线索。

## HTTP bridge / HTTP 桥接

Use the local HTTP bridge when you want Web UI, IDE integrations, or lightweight automation to reuse the same query backend:

当你希望 Web UI、IDE 集成或轻量自动化复用同一套查询后端时，可以使用本地 HTTP bridge：

```bash
memory-center serve-http \
  --workspace /path/to/.memory-center/workspace.yaml \
  --host 127.0.0.1 \
  --port 8765
```

Or:

```bash
memory-center-http --workspace /path/to/.memory-center/workspace.yaml
```

Example routes:

- `GET /health`
- `GET /workspace/status?workspace=/path/to/.memory-center/workspace.yaml`
- `GET /workspace/query?workspace=/path/to/.memory-center/workspace.yaml&text=ArticleFeignClient`
- `GET /group/status?group=backend-platform`
- `GET /group/query?group=backend-platform&text=ArticleFeignClient`
- `GET /group/impact?group=backend-platform&target=ArticleFeignClient`

---

## Roadmap / 路线图

- v1.2: trusted graph release, parser plug-in architecture, evidence-based impact, FTS5 fallback search, MCP security docs
- v1.3: Maven multi-module dependency graph and group-level aggregated graph
- v1.4: optional tree-sitter-java AST parser and JavaParser sidecar
- v1.5: Nacos config snapshot indexing and configuration-key lineage
- v1.6: optional embeddings + RRF ranking + process-flow extraction
- v1.7: web graph API and Mermaid architecture maps
- v2.0: stable public component for Spring Cloud AI coding workflows

---

## Security model / 安全模型

Memory Center is local-first and read-only by default. Query/context/impact/contract tools do not modify business source code. Write tools are limited to Memory Center artifacts such as task memory, wiki, and generated skills. See `docs/MCP_SECURITY.md`.

记忆中心默认本地优先、只读优先。查询、上下文、影响分析、契约查看不会修改业务源码；写入类工具只写记忆、Wiki、Skill 等 Memory Center 产物。详见 `docs/MCP_SECURITY.md`。

## License / 许可证

Apache-2.0
