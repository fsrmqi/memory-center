0# Memory Center / 记忆中心

> **MCP-native project memory and knowledge graph service for AI coding agents.**
>
> **面向 AI 编程助手的 MCP 项目记忆服务：多 Agent 公共空间、项目上下文、知识图谱、影响分析、经验沉淀。**

Memory Center is designed for teams that use Codex, Claude Code, Cursor, GitHub Copilot, Gemini or other coding agents on large Spring Cloud workspaces. It turns a multi-repository backend system into a local, queryable, graph-first memory center.

记忆中心用于解决大型 Spring Cloud 多项目场景下 AI 编程助手“每次从零理解项目、跨服务影响面不清、历史经验无法沉淀、规则容易忘记”的问题。它会把多个项目索引成一个本地知识图谱，并通过 MCP tools/resources/prompts 提供给 AI Agent 使用。

`services[].path` now supports both relative paths and absolute paths, so one workspace can index projects spread across different parent directories.

`services[].path` 现在同时支持相对路径和绝对路径，因此一个 workspace 可以索引分散在不同父目录下的多个项目。

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

查询结果同时提供可追溯的 `knowledge_state`：它区分当前范围内找到、未索引、未发现、索引过期和证据不足，避免把“未找到”误读为“工程中不存在”。断言详情可按有效期、事件时间或观测时间读取，并通过 CLI、MCP、HTTP 或 Workbench 完成验证与拒绝。

记忆中心的核心思想是：**不要让 AI 每次临时理解项目，而是在索引阶段提前构建服务图、调用图、契约图、消息图、规则图、经验图。**

当前主文档请优先看：

- [docs/README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/README.md)
- [docs/PRODUCT_TECHNICAL_OVERVIEW.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/PRODUCT_TECHNICAL_OVERVIEW.md)
- [docs/TECHNICAL_ARCHITECTURE_AND_EVOLUTION.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_ARCHITECTURE_AND_EVOLUTION.md)
- [docs/DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [docs/SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
- [docs/CHANGELOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/CHANGELOG.md)
- [docs/RELEASE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/RELEASE.md)
- [docs/NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md)

历史规划、执行日志和外部参考演进文档仍保留在 `docs/archive/` 下，但不再作为默认阅读入口；具体见 [docs/README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/README.md) 和 [docs/DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md)。

---

## Core ideas / 核心思想

### 1. Graph-first project memory / 图优先的项目记忆

Memory Center stores code and service relationships as graph nodes and edges in a local SQLite graph store:

记忆中心把项目关系沉淀为本地 SQLite 图存储：

- Nodes / 节点：Workspace, Service, File, Class, Method, Field, Endpoint, FeignClient, FeignMethod, MQTopic, MQConsumer, ConfigKey, MongoCollection, EsIndex, Rule, TaskMemory
- Edges / 边：CONTAINS, DECLARES, EXPOSES_ENDPOINT, HANDLES_ENDPOINT, CALLS_SERVICE, IMPLEMENTS_FEIGN, CONSUMES_TOPIC, IMPORTS, INJECTS_BEAN, CALLS_METHOD, READS_FIELD, READS_CONFIG, USES_DATA_RESOURCE, RELATED_TO_MEMORY

This makes impact analysis and context retrieval deterministic and explainable.

这样 AI 查询上下文时不是靠猜，而是沿着真实的工程关系返回影响面。

### 1.1 Zero-initialization federation / 零初始化联邦上下文

即使当前项目尚未创建 `.memory-center/workspace.yaml`，也可以调用 `mc_bootstrap_context` 或 `memory-center bootstrap-context --path <project-dir>`。它会先探测已有 Memory Center workspace；没有 workspace 时调用 GitNexus 的固定读取能力并返回会话级外部证据；Provider 不可用时才建议有界本地搜索。该流程不初始化目录，也不把外部读取结果写进图谱。

Even without `.memory-center/workspace.yaml`, `mc_bootstrap_context` or `memory-center bootstrap-context --path <project-dir>` first detects an existing workspace, then optionally uses fixed GitNexus read capabilities, and finally suggests bounded local search. It never initializes or persists external read results into the graph.

外部能力通过 Provider Registry 统一选择；联邦结果包含 `provider_selection` 与临时 `evidence_ref`，后者只保存来源、范围和内容哈希，不保存外部正文。通过 `provider-action` 可执行注册的固定动作：读取动作直接运行，索引或清理动作必须显式确认。后续可接入更多 Provider，而不改变 Agent 的上下文入口。

External capabilities are selected through the Provider Registry. Federated responses include `provider_selection` and an ephemeral `evidence_ref`, which retains provenance, scope, and a content hash rather than external body content. `provider-action` runs registered fixed actions: reads run directly while indexing or cleanup requires explicit confirmation. More providers can be added without changing the Agent context entrypoint.

Provider Registry 还会在进程内记录调用 P95、错误率和成本分，用于在同类读取 Provider 间避开持续失败或过慢的能力。若 GitNexus 明确报告未索引或陈旧，`bootstrap-context` 返回确认型 `action_cards`，建议使用固定的 `provider-action --action analyze --confirm`；系统不会自动建立外部索引。

The Provider Registry also records in-process P95, error rate, and cost score to avoid persistently failing or slow read providers. If GitNexus explicitly reports a missing or stale index, `bootstrap-context` returns confirmation-gated `action_cards` suggesting fixed `provider-action --action analyze --confirm`; the system never builds an external index automatically.

Memory Center 也可作为受限 MCP Client 直接调用外部 IDEA MCP、GitNexus MCP 等 HTTP Server。工作区维护者必须在 `.memory-center/provider-mcp-policy.json` 显式登记 URL、传输、工具和参数模板；调用 `memory-center mcp-bridge-status --path <project-dir>` 查看白名单，再用 `mcp-bridge-action --provider <id> --action <action>` 调用。只支持 `sse` 与 `streamable_http`，参数模板只允许 `{query}`、`{target}`；所有 `controlled_write` / `destructive` 动作必须 `--confirm`。外部正文只停留在响应中，长期层仅保留临时 `evidence_ref` 的元数据与哈希。

Memory Center can also act as a restricted MCP Client for external HTTP servers such as IDEA MCP and GitNexus MCP. A workspace maintainer must explicitly whitelist the URL, transport, tools, and argument templates in `.memory-center/provider-mcp-policy.json`; use `memory-center mcp-bridge-status --path <project-dir>` to inspect the policy, then `mcp-bridge-action --provider <id> --action <action>` to invoke it. Only `sse` and `streamable_http` are supported, templates may only use `{query}` and `{target}`, and every `controlled_write` / `destructive` action requires `--confirm`. External bodies stay in the response; the long-term layer retains only ephemeral `evidence_ref` metadata and hashes.

Bridge 的只读工具可声明 `capabilities: [code_navigation]`，自动进入联邦初始化的健康路由，与 GitNexus 按优先级、P95 和错误率共同选择；失败或超时会被降权。不同 Provider 的 `evidence_ref` 可经 `provider-evidence-fuse` 或 `mc_mcp_bridge(evidence_refs_json="...")` 融合。只有外部工具显式返回，或策略显式声明的 `{subject,predicate,value}` 结构化 Claim 才会判定一致或冲突；无 Claim 的不同正文哈希只表示证据不足，不会被误判为冲突。

Read-only bridge tools can declare `capabilities: [code_navigation]` to join federated bootstrap health routing alongside GitNexus, selected by priority, P95, and error rate; failures and timeouts are penalized. `evidence_ref` values from different providers can be fused with `provider-evidence-fuse` or `mc_mcp_bridge(evidence_refs_json="...")`. Only explicit structured `{subject,predicate,value}` claims returned by a tool or declared in policy can be judged consistent or conflicting. Different body hashes without a claim mean insufficient evidence, never an inferred conflict.

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

1. `mc_start(intent)` before code search / 任务开始先取上下文
2. `mc_lookup(mode="auto", query=intent)` for any knowledge lookup — it routes to the best search strategy automatically / 任何知识检索用统一入口，自动路由到最佳策略
3. `mc_analyze(target, depth="standard")` before editing important contracts — returns impact, plan, and rules in one call / 改重要契约前做影响面和规则分析，一次返回影响面、改动计划和规则检查
4. `mc_sync(intent)` for long-running or collaborative tasks / 长任务或多人协作任务先把上下文写入任务空间
5. `mc_close(session_id)` after validation to end session, sync case, and optionally record experience / 验证后结束会话、同步 case 并可选沉淀经验
6. `mc_resume(intent)` when returning to a previous task / 回到之前的任务时用恢复包
7. `mc_handoff(target_model)` when switching models or sessions / 切换模型或会话时生成交接包

### 4. Experience memory / 经验沉淀

Solved tasks can be recorded as JSONL task memory and later used for search, wiki generation and agent skills.

已解决任务会沉淀为任务记忆，可用于后续召回、Wiki 生成和 Agent Skill 生成。

### 5. Layered memory model / 分层记忆模型

Memory Center separates evidence and reusable structure through four layers:

记忆中心通过四层模型把“原始证据”和“可复用结构”分开管理：

- `L0_session_events` / `L0 会话事件`：raw prompt/tool/result/note events, plus offloaded large payload refs in `memory/refs/`
- `L1_case_atoms` / `L1 经验原子`：validated reusable cases written by `workspace_record_case`
- `L2_task_spaces` / `L2 任务空间`：task-scoped `context/plan/design/change-log/current-summary`
- `L3_workspace_profile` / `L3 工作区画像`：rules, instructions, topology and team operating protocol

This makes one task traceable from task-space summaries down to raw session evidence.

这样一个任务就可以从任务空间摘要一路追溯到原始 session 证据。

The workspace now also ships with L3 core memory blocks under `artifacts/memory-blocks/`:

现在 workspace 还会默认生成一组 L3 核心记忆块，位于 `artifacts/memory-blocks/`：

- `workspace-profile.md`
- `team-rules.md`
- `architecture-invariants.md`
- `active-migration-policy.md`

They are meant for stable cross-task knowledge that should not be buried inside one session or one case.

这些块适合沉淀跨任务稳定有效的信息，而不是把它们埋进单次 session 或单条 case。

For core task-memory artifacts such as `context.md`, `requirement.md`, `design.md`, `plan.md`, `test-plan.md`, `change-log.md`, and task-space `current-summary.md`, Memory Center now enforces append-only writes by default.

对于 `context.md`、`requirement.md`、`design.md`、`plan.md`、`test-plan.md`、`change-log.md` 以及任务空间里的 `current-summary.md` 这类核心记忆工件，记忆中心现在默认强制“只能尾部追加，不能整篇覆盖”。

对于可持续的需求开发任务，可在任务空间初始化 `feature_delivery_v2`：它将需求来源、范围边界、代码定位、验收、策略门禁和验证证据关联为 `intake -> breakdown -> locate -> implement -> verify -> close` 的有界状态机。普通回执仅标为外部记录；关闭任务需要执行器证据或带引用的人工验证。执行器只运行 workspace policy 中预注册的 argv profile，绝不执行模型或需求正文传入的 shell 字符串；CLI、MCP、HTTP 的具体用法见 [docs/REFERENCE.md](./docs/REFERENCE.md) 与 [docs/MCP_GUIDE.md](./docs/MCP_GUIDE.md)。

已关闭且验证完整的交付可以生成 Skill 候选，但候选不会直接进入默认检索。它必须先声明适用语言、前置条件、停止条件、输入输出契约和脱敏 replay 策略，再进入 `canary`。每条观测会绑定当时的契约哈希；契约修订后必须重新积累当前契约的灰度证据，已发布 Skill 的契约不可原地修改。累计达到契约 `minimum_verified_passed`（默认 3）条带验证证据引用的成功观测与脱敏 replay、且没有失败观测后，才可显式发布为 `published`；出现回归可立即 `rolled_back`，历史证据不会删除。replay 只记录契约哈希、语言、结果、证据引用、时延和 Token 指标，不读取或落盘原始源码、需求正文、日志、工具正文或操作人。

任务、已发布 Skill、Wiki 文档和活跃 CodeGraph 可登记为统一协作资产。资产默认 `private`；既有资产只能由 owner 更新，`team` 或 `restricted` 共享必须由 owner 提交并由另一维护者审批，随后才可绑定给指定 Agent 或角色。`mc_context_pack(agent_id=..., role=...)` 只装载授权资产的有界摘要、来源引用和代码证据，并为资产预留独立 Token 预算，不复制文档正文、源码或对话内容。

Tasks, published Skills, Wiki documents, and the active CodeGraph can be registered as unified collaboration assets. Registration requires an `actor` matching the declared owner; existing assets can only be updated or bound by that owner. Team or restricted sharing must be submitted by the owner and approved by a different maintainer while pending review. `mc_context_pack(agent_id=..., role=...)` loads only bounded, authorized summaries, provenance references, and code evidence within a dedicated asset budget, never document bodies, source, or conversations.

Closed, fully verified deliveries can produce Skill candidates, but candidates never enter default retrieval directly. A candidate must declare applicable languages, preconditions, stop conditions, I/O contracts, and a redacted replay policy before entering `canary`. Every observation is bound to its contract hash; a contract revision must accumulate fresh canary evidence, and a published Skill contract is immutable. It then needs at least three successful observations with verification evidence and redacted replays, with no failures, before explicit publication. Regressions can be rolled back immediately without deleting evidence. Replays retain only contract hashes, languages, outcomes, evidence references, latency, and token metrics, never source text, request bodies, logs, tool bodies, or actors.

影响分析中的图谱证据与辅助检查也采用分阶段降级：`mc_analyze` 成功获取影响图后，计划、规则、契约或检查清单阶段暂时不可用只会返回 `analysis_status="partial"`、安全诊断和后续动作，不会把已获得的影响证据替换为笼统内部异常。MCP 错误中的 `diagnostics.trace_id` 可与本地审计记录关联。

Impact analysis also degrades by phase: after `mc_analyze` obtains graph evidence, an unavailable plan, rule, contract, or checklist phase returns `analysis_status="partial"`, safe diagnostics, and a next action instead of replacing the evidence with a generic internal error. `diagnostics.trace_id` in MCP errors correlates with the local audit record.

For long-running feature work, `feature_delivery_v2` links requirement sources and scope, located subtasks, acceptance criteria, policy gates, and verification evidence through a bounded delivery state machine. It never executes a supplied command or edits source code; its executor only runs reviewed argv profiles registered by the workspace owner.

Each protected write also records `write_mode` and an `audit_ref` into `memory/artifact-write-audit.jsonl`, so you can later inspect whether a model attempted a full overwrite or was downgraded to guarded append.

每次受保护的工件写入还会把 `write_mode` 和 `audit_ref` 记录到 `memory/artifact-write-audit.jsonl`，这样后续可以追查模型到底是正常追加，还是曾经试图整篇覆盖后被降级成受保护追加。

Detailed local setup and multi-project workflow / 详细本地初始化与多项目使用流程：

- [docs/USER_GUIDE.md](./docs/USER_GUIDE.md)
- [docs/MCP_GUIDE.md](./docs/MCP_GUIDE.md)
- [docs/SPECS.md](./docs/SPECS.md)
- [docs/TECHNICAL_GUIDE.md](./docs/TECHNICAL_GUIDE.md)
- [docs/NEXT_PHASE_MASTER_PLAN.md](./docs/NEXT_PHASE_MASTER_PLAN.md)
- [docs/archive/ROADMAP.md](./docs/archive/ROADMAP.md)（historical / 历史）

---

## Installation / 安装

### One-command install / 一条命令安装

If you have the repository locally, the installer now installs the current checkout by default:

如果仓库已经在本地，安装脚本现在默认安装当前 checkout：

```bash
cd memory-center
bash install.sh
```

If you want to install directly from GitHub, you can still use the hosted script:

如果你想直接从 GitHub 安装，仍然可以使用托管脚本：

```bash
curl -fsSL https://raw.githubusercontent.com/fsrmqi/memory-center/main/install.sh | bash
```

The installer uses `pipx` by default and exposes:

安装脚本默认使用 `pipx`，安装后会暴露：

- `memory-center`
- `memory-center-mcp`
- `memory-center-http`

The install script selects an available Python 3.10+ interpreter automatically. For a manual `pipx` refresh, explicitly select a Python 3.10+ interpreter as well:

安装脚本会自动选择可用的 Python 3.10+ 解释器。手工用 `pipx` 刷新时也应显式指定 Python 3.10+：

```bash
pipx install --python python3.11 --force /path/to/memory-center
```

Verify installation:

安装后验证：

```bash
memory-center --version
```

If `pipx` was installed but the current shell still says `command not found: pipx`, add the user bin directory to `PATH` first.

如果 `pipx` 已经安装，但当前 shell 仍然提示 `command not found: pipx`，先把用户 bin 目录加到 `PATH`。

Common macOS fix / macOS 常见修复：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then rerun:

然后重新执行：

```bash
bash install.sh
```

### Verify MCP / 验证 MCP

The default install includes the MCP runtime dependencies. Verify `memory-center-mcp` directly:

默认安装已包含 MCP 运行时依赖，可直接验证 `memory-center-mcp`：

```bash
memory-center-mcp --help
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

### Vue Frontend / Vue 前端

The project includes a modern Vue 3 + Node.js frontend workbench. To set up:

项目包含 Vue 3 + Node.js 前端工作台。安装步骤：

```bash
cd web
pnpm install
pnpm build    # Build production assets to web/dist/
```

The built frontend is automatically served by the HTTP server at `/app`:

构建后的前端由 HTTP 服务器在 `/app` 路径自动托管：

```bash
memory-center serve-http --workspace /path/to/workspace.yaml
# Then open http://127.0.0.1:8765/app in your browser
```

For frontend development with hot reload:

前端开发模式（热更新）：

```bash
cd web
pnpm dev      # Starts Vite dev server on port 5173 with API proxy
```

---

## Quick start / 快速开始

Workspace maintenance helpers / 工作区配置维护命令：

- `memory-center workspace list-services`
- `memory-center workspace add-service`
- `memory-center workspace remove-service`

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
learning_policy:
  version: 1
  candidate_path_learning:
    provisional_promotion_cap: 0.54
    rollback_recommendation_cap: 0.35
    merge_weights:
      rule_weight: 0.4
      learned_weight: 0.6
  workflow_profile_learning:
    merge_weights:
      base_weight: 0.5
      learned_weight: 0.5
```

`learning_policy` is optional. You only need it when tuning how candidate-path and workflow recommendations learn from real verification outcomes.

`learning_policy` 是可选项。只有当你要调优“候选路径/工作流推荐如何根据真实验证结果学习”时，才需要显式配置。

`learning_policy.version` can be used as a lightweight compatibility marker when the team tunes or migrates learning behavior across versions.

`learning_policy.version` 可作为轻量兼容标记，在团队调整学习策略或做版本迁移时帮助区分不同策略代次。

### 2. Reindex / 重建索引

```bash
memory-center reindex \
  --workspace /path/to/spring-cloud-root/.memory-center/workspace.yaml
```

For large workspaces, partial rebuilds are now supported:

```bash
memory-center reindex \
  --workspace /path/to/.memory-center/workspace.yaml \
  --project task-service

memory-center reindex \
  --workspace /path/to/.memory-center/workspace.yaml \
  --path task-service/src/main/java/com/example/task/ArticleMoveService.java

memory-center reindex \
  --workspace /path/to/.memory-center/workspace.yaml \
  --changed-only \
  --scope all
```

Reindex uses a workspace-level `reindex.lock` so only one index writer can run at a time. A concurrent request returns a conflict instead of a SQLite lock traceback; wait explicitly when that is intentional:

```bash
memory-center reindex \
  --workspace /path/to/.memory-center/workspace.yaml \
  --lock-timeout 30
```

`workspace status` and Workbench Health expose the latest reindex state (`running`, `succeeded`, `failed`, or `interrupted`) without exposing local paths.

对于大 workspace，现在也支持局部重建：

```bash
memory-center reindex \
  --workspace /path/to/.memory-center/workspace.yaml \
  --project task-service

memory-center reindex \
  --workspace /path/to/.memory-center/workspace.yaml \
  --path task-service/src/main/java/com/example/task/ArticleMoveService.java

memory-center reindex \
  --workspace /path/to/.memory-center/workspace.yaml \
  --changed-only \
  --scope all
```

重建会使用 workspace 级 `reindex.lock`，同一时间只允许一个索引写入者运行。并发请求会返回 conflict，而不是 SQLite 锁栈追踪；确实需要等待时可显式设置：

```bash
memory-center reindex \
  --workspace /path/to/.memory-center/workspace.yaml \
  --lock-timeout 30
```

`workspace status` 与 Workbench Health 会显示最近一次重建状态（`running`、`succeeded`、`failed` 或 `interrupted`），且不暴露本地路径。

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

Reindex also rebuilds the local semantic node index and SQLite BM25 inverted index used by hybrid retrieval. Full rebuilds recreate BM25; later path-scoped rebuilds replace only changed BM25 documents and preserve untouched postings. When the semantic backend produces dense vectors, they are synchronized into `VectorIndex`.

重建索引时也会同步构建本地语义节点索引和 SQLite BM25 倒排索引，供混合检索使用。完整重建会重建 BM25；之后的指定路径重建只替换变更节点的 BM25 文档，并保留未变更 posting。当语义 backend 生成 dense vectors 时，还会同步写入 `VectorIndex`。

For incremental / path-scoped reindex, BM25 and dense vector sync are incremental: changed vector-eligible nodes are deleted and upserted in `VectorIndex`, while unrelated embeddings and BM25 postings are preserved. A sparse-only reindex no longer clears dense embeddings from a previous local embedding run. A legacy BM25 index is rebuilt once to migrate its persisted term frequencies, then later scoped refreshes stay incremental.

对于增量 / 指定路径 reindex，BM25 和 dense vector 同步都是增量的：只有变更且可向量化的节点会在 `VectorIndex` 中 delete + upsert，未变化的 embedding 与 BM25 posting 会保留。一次 sparse-only reindex 不会再清空之前本地 embedding backend 生成的 dense embeddings。旧格式 BM25 索引会为迁移持久化词频完整重建一次，之后的局部刷新保持增量。

Reindex output also includes parser diagnostics: selected parser, parse count, fallback count/reasons, native disagreement count, and final critical disagreement count. Public parser parity is gated by `examples/parser-corpus/` and `tests/test_parser_differential.py`.

reindex 输出还会包含 parser diagnostics：实际 parser、解析次数、fallback 次数/原因、原生差异数和最终 critical disagreement 数。公开 parser 一致性由 `examples/parser-corpus/` 与 `tests/test_parser_differential.py` 守护。

Reindex output also exposes semantic/vector observability fields: `semantic_backend`, `requested_semantic_backend`, `vector_scope`, `vector_candidate_count`, `dense_doc_count`, `vector_status`, and `vector_disabled_reason`. When `vector_embeddings=0`, these fields explain whether vectors are disabled by the sparse backend, blocked by a missing local embedding model, filtered by scope, or ready but empty.

reindex 输出还会暴露语义/向量可观测字段：`semantic_backend`、`requested_semantic_backend`、`vector_scope`、`vector_candidate_count`、`dense_doc_count`、`vector_status` 和 `vector_disabled_reason`。当 `vector_embeddings=0` 时，可以直接判断是 sparse backend 未开启向量、本地 embedding 模型不可用、scope 过滤为空，还是已就绪但无结果。

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
  --intent "oldPubTime newPubTime ArticleFeignClient 文章发布时间迁移" \
  --auto-sync-mode balanced
```

### 4. Graph query / 图谱查询

```bash
memory-center query \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --text "oldPubTime ArticleFeignClient"
```

Local query now uses hybrid retrieval across graph, FTS, SQLite BM25, semantic, and optional vector sources.

当前查询已支持本地混合召回：图谱、FTS、SQLite BM25、语义检索，以及可选的原生向量检索。

Before executing sources, an adaptive policy now selects the source set, graph depth, candidate limit, and evidence budget from query intent, index freshness, and bounded verified feedback. Full-chain queries keep exact + graph as non-removable constraints and use a deep-but-narrow evidence path.

检索源执行前，自适应策略会根据查询意图、索引新鲜度和有界验证反馈选择来源、图深度、候选上限与证据预算。全链路查询始终保留 exact + graph 硬约束，并采用“深但窄”的证据路径。

When a local embedding backend is enabled, reindex synchronizes dense embeddings into `VectorIndex`. Vector ANN remains disabled by default and can be enabled through `HybridRetrievalConfig(enable_vector=True)`; sparse and BM25 retrieval remain safe fallbacks. For large dense indexes, install the `semantic-ann` extra (or `pipx inject memory-center hnswlib numpy`) and use the persistent HNSW index. Memory Center never falls back to a Python full scan for a large vector corpus.

启用本地 embedding backend 后，reindex 会把 dense embeddings 同步到 `VectorIndex`。原生向量 ANN 默认关闭，可通过 `HybridRetrievalConfig(enable_vector=True)` 启用；稀疏语义和 BM25 继续作为安全 fallback。大型 dense 索引请安装 `semantic-ann` extra（或执行 `pipx inject memory-center hnswlib numpy`）并使用持久化 HNSW；Memory Center 不会再对大型向量库执行 Python 全量扫描。

```bash
# Inspect / rebuild the persistent ANN index without a full reindex.
memory-center vector-ann-status --workspace .memory-center/workspace.yaml
memory-center vector-ann-rebuild --workspace .memory-center/workspace.yaml

# Preview calibrated weights from human-verified retrieval replay; apply is explicit.
memory-center eval-retrieval-replay --workspace .memory-center/workspace.yaml
memory-center eval-retrieval-replay --workspace .memory-center/workspace.yaml --apply
```

`eval-retrieval-replay` only consumes evidence-backed, human-verified `retrieval-source` outcomes. Agent guidance adoption is operational telemetry, not relevance evidence, so it never changes fusion weights. The command uses a 30-day window by default, bounded source weights, and sample shrinkage; it reports `insufficient_replay` without writing anything until the threshold is met.

`eval-retrieval-replay` 只使用带 evidence 的人工验证 `retrieval-source` 结果。Agent 是否采纳建议属于运行遥测，不等于召回正确性，因此不会改变融合权重。命令默认统计近 30 天，使用有界权重和样本收缩；样本不足时返回 `insufficient_replay` 且不写入任何内容。

### Advanced Retrieval / 高级检索

The default sparse path uses code-aware BM25F: entity names and contracts outweigh paths and metadata. Hybrid results also receive bounded personalized graph ranking. For difficult conceptual queries, opt into a bounded cross-encoder stage; it reranks at most 12 candidates. Query requests only use an already cached local model and never download weights, so a cold model cannot block an MCP request.

默认稀疏检索使用代码感知 BM25F：实体名称和契约的权重高于路径和元数据。混合结果还会做有界个性化图排序。概念型复杂查询可显式启用 Cross-Encoder；它最多重排 12 条候选，查询只使用本地已缓存模型，绝不会下载权重，因此冷模型不会阻塞 MCP 请求。

```bash
memory-center query --workspace .memory-center/workspace.yaml --text '用户登录调用链' --vector --rerank
memory-center vector-ann-tune --workspace .memory-center/workspace.yaml

# Check local cache, or explicitly prewarm inside the active MCP process.
memory-center retrieval-reranker-status
memory-center retrieval-reranker-prewarm

# Preview or select a multilingual BGE-M3 profile. A full reindex remains explicit.
memory-center retrieval-model-profile --workspace .memory-center/workspace.yaml --profile multilingual
memory-center retrieval-model-profile --workspace .memory-center/workspace.yaml --profile multilingual --apply
MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers memory-center reindex --workspace .memory-center/workspace.yaml
```

Agents do not need to parse shell examples to use these capabilities. Generated `AGENTS.md` routes retrieval maintenance through MCP: `mc_admin(action="vector_ann_status")`, `vector_ann_rebuild`, `vector_ann_tune`, `advanced_query`, `retrieval_reranker_status`, `retrieval_reranker_prewarm`, `retrieval_model_profile`, and `eval_retrieval_replay`. A query waits for an ANN maintenance lock for at most 300ms and then returns a retry diagnostic. When lookup returns `agent_next_steps.action="rebuild_vector_ann"`, the Agent must rebuild then tune ANN before retrying. Model-profile application, full reindex, and reranker prewarm remain explicit user-approved operations.

Agent 不需要依赖 shell 示例才能使用这些能力。生成的 `AGENTS.md` 会通过 MCP 路由检索维护：`mc_admin(action="vector_ann_status")`、`vector_ann_rebuild`、`vector_ann_tune`、`advanced_query`、`retrieval_reranker_status`、`retrieval_reranker_prewarm`、`retrieval_model_profile` 与 `eval_retrieval_replay`。查询最多等待 ANN 维护锁 300ms，超时会返回重试诊断而不是卡住。当 lookup 返回 `agent_next_steps.action="rebuild_vector_ann"` 时，Agent 必须先重建并调优 ANN，再重试查询；模型档案应用、完整 reindex 和重排器预热仍是需要用户明确确认的操作。CLI 预热只保证模型已下载；要让高级查询使用重排器，必须在当前 MCP 进程调用 `mc_admin(action="retrieval_reranker_prewarm")`。

Golden Benchmark hybrid cases can opt in to ANN with `enable_vector: true`, which keeps vector-backed concept-query behavior under regression coverage without changing existing cases.

Golden Benchmark 的 hybrid case 可通过 `enable_vector: true` 显式启用 ANN，把向量支持的概念查询纳入长期回归门禁，同时不改变既有 case 行为。

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

### 6.5 Session memory / 会话长期记忆

You can now keep lightweight task-session memory inside the same workspace:

现在也可以在同一个 workspace 里记录轻量的任务会话记忆：

`workspace_sniff` 现在会返回 `symbolic_context`，适合在长任务开始前先做低 Token 的符号化规划；其中同时包含 `entities_mermaid`（实体聚焦图）和 `flow_mermaid`（任务流程图），并且 `flow_mermaid` 会根据本次命中的 Feign/API、MQ、Config、历史 Case 动态切换流程分支，同时按 `risk_level` 决定是否强制插入 `memory_impact -> memory_plan_change -> memory_verify_checklist` 这条更严格主链路。`workspace_sniff` 还会返回 `auto_sync_recommendation`（含 `recommended/confidence/reason/score_threshold/mode`）帮助判断是否自动同步到任务空间，并支持 `auto_sync_mode=strict|balanced|aggressive` 三档策略。`workspace_suggest_case` 会返回 `evidence_refs`，用于把 case 草稿回溯到原始事件；workspace 级 `query/context/impact` 会返回 `progressive` 的 `summary / evidence / detail` 三层视图，便于按需展开。`workspace_sniff` 还会返回 `source_refs`，把 file/Feign/API/MQ/case 命中结果暴露为结构化来源引用；`workspace_suggest_case` / `workspace_record_case` 则支持 `source_session_id`、`source_task_id`、`source_refs`，便于把 L1 经验原子追溯回 L0 会话与 L2 任务空间。对于体积过大的 session event payload，系统会自动把完整内容外置到 `memory/refs/sessions/...`，事件本体只保留关键摘要与 `payload_ref`。
`sync-case-artifacts` 的风险等级也已升级为 `risk_points + evidence_refs` 联合评分，并在返回中提供 `risk_evidence`（含 score、signals、evidence_type_counts），用于解释自动同步策略的风险判断依据。

`workspace_sniff` now returns `symbolic_context` for low-token planning, including both `entities_mermaid` and `flow_mermaid`. It also returns `auto_sync_recommendation` (`recommended/confidence/reason/score_threshold/mode`) so agents can decide whether to auto-sync into task spaces, with `auto_sync_mode=strict|balanced|aggressive`. `workspace_suggest_case` returns `evidence_refs` back to raw events, and workspace `query/context/impact` responses now include a `progressive` view with `summary / evidence / detail` layers. `workspace_sniff` also returns `source_refs` so file/Feign/API/MQ/case hits can be reused as structured provenance; `workspace_suggest_case` / `workspace_record_case` support `source_session_id`, `source_task_id`, and `source_refs` so one L1 case atom can trace back to both L0 session evidence and L2 task-space artifacts. Large session payloads are automatically offloaded into `memory/refs/sessions/...`, while the event keeps a compact summary plus `payload_ref`.
`sync-case-artifacts` now computes risk from both `risk_points` and typed `evidence_refs`, and returns `risk_evidence` (score/signals/evidence_type_counts) to explain why a sync recommendation is conservative or aggressive.

Group-level `query` and `impact` now expose the same `progressive` structure, so agents can use one consistent disclosure pattern across single-workspace and multi-workspace workflows.

group 级 `query` 和 `impact` 现在也会返回同样的 `progressive` 结构，这样单 workspace 与多 workspace 场景可以使用同一套渐进式披露模式。

The workspace now also includes a shared `artifacts/` layer for multi-agent collaboration, with default artifacts such as `context.md`, `requirement.md`, `design.md`, `plan.md`, `test-plan.md`, and `change-log.md`.

现在 workspace 还包含一个面向多智能体协作的共享 `artifacts/` 层，默认提供 `context.md`、`requirement.md`、`design.md`、`plan.md`、`test-plan.md`、`change-log.md` 等共享工件。

You can also sync task outputs back into shared artifacts:

你现在还可以把任务结果反向同步回共享工件：

```bash
memory-center sync-sniff-artifacts \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --intent "修改 Feign DTO 并评估 MQ 影响" \
  --auto-sync-mode balanced

memory-center sync-case-artifacts \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --session-id session-xxxx \
  --auto-sync-mode balanced
```

For longer-running work, prefer task-specific spaces under `artifacts/tasks/<task-title-slug>/`, so the same requirement keeps its own `context/design/plan/change-log`, and stale task spaces can be archived automatically after N days.

对于周期更长的任务，建议使用 `artifacts/tasks/<任务标题-slug>/` 这种按需求分空间的方式，让同一需求拥有自己的 `context/design/plan/change-log`；过期任务空间还可以按保留天数自动归档。

### 索引存储与空间维护 / Index Storage and Space Maintenance

语义检索的倒排 posting 与 ANN 向量分别保存在 SQLite 运行时索引中；`semantic-node-index` 只保留轻量状态，不复制全量节点和 embedding。旧工作区可先运行 `artifact semantic-index-compact --workspace <workspace.yaml> --dry-run`，确认后追加 `--apply`，再在没有 reindex 或写入任务时运行 `artifact storage-vacuum --workspace <workspace.yaml> --apply` 回收 SQLite 页。该维护不会重建源码索引。

Sparse postings and ANN vectors are stored in dedicated SQLite runtime indexes; `semantic-node-index` retains only lightweight state and no longer duplicates all nodes or embeddings. Existing workspaces can run `artifact semantic-index-compact --workspace <workspace.yaml> --dry-run`, then `--apply`, followed by `artifact storage-vacuum --workspace <workspace.yaml> --apply` while no reindex or write task is running. This maintenance does not rebuild source indexes.

已发布的交付 Skill 可选接入外部 `skill-up` 评测器：Agent 先运行 `artifact delivery-skill-eval-status`；仅当二进制可用且 Skill 已发布时，执行 `delivery-skill-eval-init` 生成脱敏用例骨架。Agent 必须先运行 `delivery-skill-eval-run --dry-run`，只有维护者明确要求后才可追加 `--apply`；外部评测结果不能自动发布或提升 Skill 状态。

Published delivery Skills can optionally use the external `skill-up` evaluator. Agents first run `artifact delivery-skill-eval-status`; only when the binary is available and the Skill is published may they initialize a sanitized evaluation skeleton. Agents must use `delivery-skill-eval-run --dry-run` before an explicitly requested `--apply`; external results never auto-publish or promote a Skill.

```bash
memory-center artifact create-task \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --title "Feign DTO 兼容改造"

memory-center artifact list-tasks \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml

memory-center artifact health-task \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --task-id feign-dto-compat

memory-center artifact repair-plan-task \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --task-id feign-dto-compat

memory-center artifact repair-task \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --task-id feign-dto-compat

memory-center artifact repair-task \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --task-id feign-dto-compat \
  --apply \
  --intent "继续 Feign DTO 兼容改造"

memory-center artifact auto-archive-tasks \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --retention-days 30
```

Task health checks diagnose whether a task space is resumable: missing or stale `current-summary`, empty next actions, unresolved write receipts, similar task spaces, and oversized artifacts. `repair-task` defaults to dry-run. Applying repairs only performs conservative low-risk writes: it can append templates for missing context/plan and refresh `current-summary` when an explicit `--intent` is provided. It does not fake write receipts, auto-archive ambiguous task spaces, or overwrite existing artifacts.

任务健康检查会判断任务空间是否适合恢复：例如缺失或过期的 `current-summary`、下一步为空、未解决写入回执、相似任务空间和过大的工件。`repair-task` 默认只做 dry-run。真正应用修复时只执行保守低风险写入：可以为缺失的 context/plan 追加模板，也可以在提供明确 `--intent` 后刷新 `current-summary`；不会伪造写入回执、不会自动归档歧义任务空间，也不会覆盖已有工件。

When a new conversation starts, you do not have to pass `task_id` every time. The system can resolve the most relevant existing task space from your natural-language intent, and only create a new one when nothing matches well enough.

当你开启一个新对话时，不需要每次都手填 `task_id`。系统可以根据自然语言意图自动匹配最相关的已有任务空间，只有在匹配不到时才会新建。

Task spaces now also support `owner`, `tags`, and `priority`, and `resolve-task` returns top candidates so the match is explainable instead of fully black-box.

任务空间现在还支持 `owner`、`tags`、`priority`，并且 `resolve-task` 会返回前几个候选结果，让匹配过程可解释，而不是完全黑盒。

For long-running projects, do not feed the full artifact documents every time. Use artifact outline/context retrieval and compact old change logs:

对于长期运行项目，不要每次都整篇读取共享工件。优先使用提纲/相关片段检索，并定期压缩归档旧的 change-log：

```bash
memory-center artifact outline \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --name context

memory-center artifact context \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --intent "Feign DTO 兼容改动" \
  --limit 6

memory-center artifact compact-change-log \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --keep-recent 30
```

```bash
memory-center start-session \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --intent "修复 Feign 调用链"

memory-center log-session-event \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --session-id session-xxxx \
  --event-type tool_call \
  --payload '{"tool_name":"mc_lookup","query":"ArticleFeignClient"}'

memory-center end-session \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --session-id session-xxxx \
  --outcome "完成 Feign 调用链定位"

memory-center resume-context \
  --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml \
  --intent "继续处理 Feign 调用链"
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

### 8.1 Workflow shortcuts / 一键工作流命令

```bash
memory-center work-start \
  --workspace /path/to/.memory-center/workspace.yaml \
  --intent "ArticleFeignClient 调用链"

memory-center work-log \
  --workspace /path/to/.memory-center/workspace.yaml \
  --session-id session-xxx \
  --event-type note \
  --payload '{"note":"补充风险点"}'

memory-center work-sync \
  --workspace /path/to/.memory-center/workspace.yaml \
  --intent "ArticleFeignClient 调用链"

memory-center work-resume \
  --workspace /path/to/.memory-center/workspace.yaml \
  --task-id some-task

memory-center work-resume-check \
  --workspace /path/to/.memory-center/workspace.yaml \
  --task-id some-task

memory-center work-handoff \
  --workspace /path/to/.memory-center/workspace.yaml \
  --target-model glm-4 \
  --task-id some-task

memory-center work-close \
  --workspace /path/to/.memory-center/workspace.yaml \
  --session-id session-xxx \
  --outcome "done"

memory-center work-health \
  --workspace /path/to/.memory-center/workspace.yaml
```

`work-resume-check` is the one-call resume gate: it combines the resume packet, task health, repair plan, next actions, unresolved items and evidence into `ready`, `needs_repair`, or `blocked`.

`work-resume-check` 是恢复前的一键门禁：它会把恢复包、任务健康、修复计划、下一步动作、未解决事项和证据合并成 `ready`、`needs_repair` 或 `blocked`。

### 9. Real-world `ucap-all` examples / `ucap-all` 真实路径示例

If you are using the shared UCAP workspace discussed in the docs, you can copy these commands directly:

如果你正在使用文档中那套 `ucap-all` 公共空间，下面这些命令可以直接复制：

```bash
memory-center status \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml

memory-center query \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --text "ucap-cloud-back"

memory-center context \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --name ucap-cloud-back

memory-center impact \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --target ucap-cloud-back \
  --direction upstream

memory-center start-session \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --intent "继续处理 ucap-cloud-back Feign 调用链"

memory-center resume-context \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --intent "继续处理 ucap-cloud-back Feign 调用链"
```

---

## MCP server / MCP 服务

```bash
memory-center-mcp \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

Available MCP tools (8 facade tools) / MCP 工具（8 个任务级 facade）：

| Tool | Purpose / 用途 |
|---|---|
| `mc_start` | Start task workflow: sniff → sync → start session / 开始任务：上下文召回 → 同步 → 启动会话 |
| `mc_lookup` | Unified knowledge lookup (auto/symbol/code/query/trace/chain/walkthrough/context/contracts/ref/backend) / 统一知识检索，mode 自动路由到最佳策略 |
| `mc_analyze` | Change impact analysis (quick/standard/full depth) / 变更影响面分析，按 depth 逐层深入 |
| `mc_sync` | Sync context to workspace artifacts (sniff or case) / 同步上下文到工件 |
| `mc_resume` | Resume task with consolidated context / 恢复任务上下文 |
| `mc_handoff` | Build handoff package for another model / 为目标模型生成交接包 |
| `mc_close` | Close task workflow: end session → sync case → record experience / 关闭任务工作流 |
| `mc_admin` | Admin router (status/dashboard/eval/artifact/session/group etc.) / 管理路由，action 选择子操作 |

Task-space resume experience is available through `mc_admin` actions: `task_health`, `task_health_all`, `task_repair_plan`, `task_repair_apply`, and `task_resume_check`. `task_resume_check` should be the default first call when an agent returns to a known `task_id`; `task_repair_apply` runs as dry-run unless `force=true` is passed, and current-summary refreshes should include an `intent`.

任务空间恢复体验通过 `mc_admin` action 暴露：`task_health`、`task_health_all`、`task_repair_plan`、`task_repair_apply`、`task_resume_check`。Agent 回到已知 `task_id` 时，默认应先调用 `task_resume_check`；`task_repair_apply` 在未传 `force=true` 时只做 dry-run，刷新 current-summary 时建议同时传入 `intent`。

`mc_lookup(mode="walkthrough")` targets `Class#method` traces. For local service calls, `local_service_continuations` resolves Service interface calls to Impl methods. For Feign calls, `feign_continuations[].server_walkthroughs` expands matching server-side Controller methods, and `service_impl_continuations` resolves same-project Service interface calls to Impl methods when indexed.

`mc_lookup(mode="walkthrough")` 面向 `Class#method` 链路梳理。遇到本地 Service 调用时，`local_service_continuations` 会解析 Service interface 到 Impl 方法。遇到 Feign 调用时，`feign_continuations[].server_walkthroughs` 会展开匹配到的服务端 Controller 方法；如果 Controller 调用同项目 Service interface，`service_impl_continuations` 会继续解析到 Impl 方法。

For a request containing both `Class#method` and a full-chain intent, `mc_lookup(mode="auto")` now enters the indexed walkthrough directly. It skips broad workspace sniffing, keeps the chain depth bounded, and returns compact evidence first. Large-workspace task startup also uses graph FTS for candidate files instead of loading the full Java symbol payload.

当请求同时包含 `Class#method` 和“全链路”语义时，`mc_lookup(mode="auto")` 会直接进入索引化 walkthrough，跳过宽泛的 workspace sniff，保持链路深度有界并优先返回紧凑证据。大型 workspace 的任务启动也会用 graph FTS 定位候选文件，不再加载完整 Java 符号 payload。

Task-space matching, health checks, resume summaries, and automatic sync read task artifacts with bounded excerpts. Oversized artifacts are reported by task health and preserved unchanged during automatic sync, so generated Markdown cannot turn a normal analysis request into an unbounded memory read.

任务空间匹配、健康检查、恢复摘要和自动同步都会对任务工件采用有界摘要读取。超大工件会在任务健康检查中提示，并在自动同步时保持原样跳过，避免生成型 Markdown 让普通分析请求退化为无界内存读取。

`mc_start` reuses its first sniff result during optional task sync. Sniff responses include `performance` with stage timings, cache state, retrieval mode, and the soft request deadline. Reindex also writes `index-summary.json`; status and Workbench read that small summary instead of loading full Java or semantic indexes.

`mc_start` 在可选任务同步时会复用首次 sniff 结果。sniff 响应包含 `performance`，提供阶段耗时、缓存状态、检索模式和软请求时限。reindex 还会写入 `index-summary.json`，状态页和 Workbench 只读取这一轻量摘要，不再加载完整 Java 或语义索引。

Before `mc_start` and `mc_lookup` return indexed evidence, Memory Center schedules a bounded set of graph/path candidates for background freshness checking. When a source file changed since indexing, the File/Class/Method overlay refresh is queued and returned as `auto_refresh.scheduled`; the request always reads the current published generation and never performs index work on the request path.

`mc_start` 和 `mc_lookup` 返回索引证据前，会把有界数量的图谱/路径候选提交给后台 freshness 检查。发现源码在索引后已变更时，文件的 File/Class/Method 子图及其声明、注入、方法调用出边会以 `auto_refresh.scheduled` 排队刷新；请求始终读取当前已发布 generation，不执行哈希、图遍历或索引重建。文件 watcher 只写入去抖后的 dirty journal，由后台定向刷新消费。

需要在不查询时也保持索引更新，可启动每个工作区唯一的本地守护：`memory-center watcher-start --workspace <workspace.yaml>`。它使用轮询和去抖合并源码、配置变更，提交有界局部 reindex job；`watcher-status` 展示 PID、最近变更与 job，`watcher-stop` 优雅停止。守护状态也会出现在 Workbench 的 `hot_refresh.watcher`，不会在 Agent 查询热路径扫描全量工作区。

每个 watcher 局部 reindex 到达终态后都会写入轻量变更影响摘要。摘要只使用变更路径、已有失效计划、任务统计和 index generation，记录受影响服务、风险等级与证据边界；通过 `memory-center change-impact-reports` 查看。DTO、Feign、MQ、HTTP、配置等高风险变更只会提示显式执行深度分析，不会由后台自动触发昂贵的全图检索。

摘要可通过 `memory-center change-impact-confirm --report-id <id> --decision confirmed|false_positive|deep_analysis_required|resolved` 追加人工结论；可关联任务、会话、验证状态和验证人。`deep_analysis_required` 会继续保留为待确认项，Workbench 的 `hot_refresh.pending_change_reports.high_risk_reports` 只展示最多 5 条未确认高风险报告。审计事件与紧凑反馈索引都自动保留 30 天且最多 10 万条：读取会立即按窗口过滤，64 KiB 以内的 MCP 审计日志同步收口，大日志在后台物理压缩，避免请求线程扫描和重写十万级 JSONL。

需要为一次链路分析生成可交接的证据视图时，使用 `memory-center export-evidence-subgraph --workspace <workspace.yaml> --target <node-id-or-symbol> --format markdown`。也可通过 `GET /workspace/evidence-subgraph` 或 `mc_admin(action="evidence_subgraph_export")` 获取 JSON、Markdown、HTML。导出严格限制为最多 3 跳、120 条边、80 个节点，不读取源码、不扫描全图，也不会进入普通查询热路径。

需要理解模块边界和共享核心节点时，显式运行 `memory-center architecture-communities --workspace <workspace.yaml>`。它仅在 SQLite 中聚合跨项目边与节点度数，输出项目社区、跨项目关系和高中心性节点；结果缓存到轻量摘要供 Workbench/status 读取，不会在查询热路径计算。

Hot refresh is coordinated per workspace across local Agents. Each replacement commits a content hash and file generation in the same SQLite transaction, then expands at most one graph hop to related API/Feign/DTO/MQ/config files. `mc_start` and `mc_lookup` support `request_tier="fast"|"standard"|"deep"`; `fast` has bounded retrieval. For costly impact analysis, use `mc_analyze(execution_mode="background")`, then poll or cancel with `job_action="status"|"cancel"` and `job_id`.

热刷新会在同一 workspace 的本地 Agent 之间协调执行。每次替换会在同一个 SQLite 事务中提交内容哈希与文件 generation，并最多扩展一跳已有图关联的 API/Feign/DTO/MQ/config 文件。`mc_start` 与 `mc_lookup` 支持 `request_tier="fast"|"standard"|"deep"`；`fast` 强制有界检索。代价较高的影响分析可调用 `mc_analyze(execution_mode="background")`，再通过 `job_action="status"|"cancel"` 和 `job_id` 查询或取消。

Task artifacts keep `current_summary` concise. Large writes are stored as immutable content-addressed evidence chunks and leave a lightweight evidence reference in the artifact, so resume/handoff never needs to load the entire original payload.

任务工件保持 `current_summary` 紧凑。超大写入会保存为不可变、内容寻址的证据块，并在工件中只留下轻量引用，因此恢复和交接不需要加载完整原始 payload。

### Versioned Index Control / 版本化索引控制

Reindex now builds under a staging generation and activates it only after graph, retrieval, semantic, and shard-routing metadata are complete. Existing index files remain compatible read models; `index-control.json` records the active generation and `shard-manifest.json` provides service, contract, and topology routing summaries. Status exposes both generation state and recent query latency percentiles.

reindex 会先构建 staging generation，只有图、检索、语义和分片路由元数据全部完成后才激活。运行时查询只读取 `graph.db` 中的 SQLite 事实库；`index/*.json` 与 JSONL 仅作为可审查导出，不参与查询回退。`index-control.json` 记录 active generation，`shard-manifest.json` 提供服务、契约和拓扑路由摘要。状态接口同时提供 generation 状态与近期查询延迟分位数。

For large asynchronous work, use `mc_admin(action="job_reindex")`, then `job_status` or `job_cancel` with `record_id=<job_id>`. Task decisions can be recorded with `task_decision_record`; `task_evidence_gc` is dry-run by default and needs `force=true` to remove unreferenced evidence.

对于较大的异步工作，可使用 `mc_admin(action="job_reindex")`，再通过 `job_status` 或 `job_cancel` 并传入 `record_id=<job_id>` 查询或取消。任务决策可通过 `task_decision_record` 记录；`task_evidence_gc` 默认只预览，必须传 `force=true` 才会删除未引用证据。

### Physical Index Shards / 物理索引分片

Each active generation now contains immutable service JSON shards, service-local SQLite graph shards, a shared contract shard, and a topology shard. Explicit project-scoped code and hybrid graph queries read the service shard first, then fall back to legacy global indexes only when the shard is absent or scope expansion is required. File watcher changes create a bounded invalidation plan and coalesce an asynchronous partial reindex job. `mc_admin(action="index_rollback", record_id="<generation>")` restores a retained generation; `index_generation_gc` previews cleanup unless `force=true` is supplied.

每个 active generation 包含不可变的服务 JSON 分片、服务本地 SQLite 图分片、共享契约分片和拓扑分片。已解析 `project` 的代码搜索与混合图查询只读取对应服务分片；分片未发布时返回 `NOT_INDEXED`，不会悄悄退回全局扫描。file watcher 的变更会生成有界失效计划并合并异步局部 reindex job。`mc_admin(action="index_rollback", record_id="<generation>")` 可恢复保留的 generation；`index_generation_gc` 默认只预览清理，传 `force=true` 才会执行。

When `mc_lookup` has no explicit `project`, it now routes through the active topology and contract shards, selects a bounded set of service shards by request tier, and queries them in parallel. Responses include `shard_route` and `shard_evidence`, each tied to the active generation. Use `mc_admin(action="eval_cross_shard_replay", text="one intent per line")` to verify cross-service shard P95 and evidence coverage without persisting the raw replay text.

当 `mc_lookup` 未传 `project` 时，现在会先通过 active topology 与 contract 分片路由，按请求档位选择有界服务分片集合，再并行查询。响应包含与 active generation 绑定的 `shard_route` 和 `shard_evidence`。可使用 `mc_admin(action="eval_cross_shard_replay", text="每行一个意图")` 验证跨服务分片 P95 与证据覆盖率，原始 replay 文本不会被持久化。

`mc_lookup` also returns `cross_shard_fusion`: deduplicated matches from primary and shard retrieval, active/routed generation consistency, Feign/MQ/DTO contract checks, confidence, semantic strength, and explicit next actions. Use `mc_admin(action="eval_cross_shard_fusion", payload='{"cases":[{"query":"...","expected_projects":["..."]}]}')` for a Golden-like gate covering service selection, generation consistency, and explainability.

`mc_lookup` 还会返回 `cross_shard_fusion`：它融合主检索和分片取证结果，执行去重、active/routed generation 一致性检查、Feign/MQ/DTO 契约检查，并给出置信度、证据强度和明确的下一步动作。可使用 `mc_admin(action="eval_cross_shard_fusion", payload='{"cases":[{"query":"...","expected_projects":["..."]}]}')` 运行类似 Golden 的门禁，验证服务选片、generation 一致性和可解释性。

### Contract Semantic Gate / 契约语义门禁

Reindex writes a normalized API/Feign/MQ/DTO contract snapshot and compares it with the prior snapshot. Removed APIs, removed DTO fields, DTO field type changes, and removed Feign/MQ contracts are marked breaking. `mc_analyze(depth="full")` always includes `contract.semantic_compatibility`; optionally pass `task_id` to store the report as immutable task evidence. `mc_admin(action="contract_gate", name="...")` and CLI `check-contract` expose the same check. Guard-mode pre-edit hooks block on breaking contract changes, while release-gate includes the check when a real contract snapshot exists.

reindex 会写入标准化的 API/Feign/MQ/DTO 契约快照，并与前一快照比较。删除 API、删除 DTO 字段、DTO 字段类型变更、删除 Feign/MQ 契约会标记为破坏性变更。`mc_analyze(depth="full")` 始终包含 `contract.semantic_compatibility`；可传 `task_id` 将报告存为不可变任务证据。`mc_admin(action="contract_gate", name="...")` 与 CLI `check-contract` 暴露相同校验。guard 模式的 pre-edit hook 会阻断破坏性契约变更；release-gate 在存在真实契约快照时也会纳入该检查。

### Runtime Contract Verification / 运行时契约验证

通过 `mc_admin(action="runtime_contract_ingest")` 只导入脱敏元数据：服务、API 方法/路径或 MQ topic/方向、DTO 名称、字段名集合和成功/失败计数。payload/body/header/message 内容会被拒绝，绝不会存储。`runtime_contract_gate` 会将活跃样本与静态 breaking change、endpoint/topic 可用性比较。活跃破坏性变更会阻断发布；已有记录的 `dual_read` / `dual_write` 迁移可降级为 `attention`。存在样本时，full 契约分析与 release-gate 都会纳入运行时结果。

Walkthrough key locations include `absolute_file_path`; agents should read that path directly instead of running `find` first.

walkthrough 的关键落点包含 `absolute_file_path`；Agent 应直接读取该路径，不需要先执行 `find` 定位文件。

Walkthrough also returns `same_class_method_continuations` for unqualified helper/private method calls and nested Feign continuations inside Service Impl nodes. When these continuations are present, agents should use the returned summaries before falling back to `sed -n`.

walkthrough 还会为同类未限定辅助/私有方法调用返回 `same_class_method_continuations`，并展开 Service Impl 内部的嵌套 Feign 调用。存在这些续链时，Agent 应先使用返回摘要，不要直接退回 `sed -n`。

For MCP `mc_lookup(auto|walkthrough)`, walkthrough responses expose `answer`, `answer_markdown`, `summary_lines`, `primary_flow`, `read_targets`, `mermaid_flow`, `performance_risks`, `data_scope_guards`, `diff_context`, `glossary_hits`, `index_freshness`, `branch_outline`, `anti_patterns`, `cache`, `schema_version`, `fields_contract`, and `agent_usage_policy` at the top level. Agents should use these top-level fields directly instead of parsing local `tool-results/*.json` files.

MCP `mc_lookup(auto|walkthrough)` 的 walkthrough 响应会把 `answer`、`answer_markdown`、`summary_lines`、`primary_flow`、`read_targets`、`mermaid_flow`、`performance_risks`、`data_scope_guards`、`diff_context`、`glossary_hits`、`index_freshness`、`branch_outline`、`anti_patterns`、`cache`、`schema_version`、`fields_contract` 和 `agent_usage_policy` 提升到顶层。Agent 应直接使用这些顶层字段，不需要解析本地 `tool-results/*.json`。

Lookup results also include additive `agent_next_steps`, a structured next-step list derived from retrieval policy, freshness, completion status and available evidence. CLI `memory-center query`, HTTP `/workspace/query`, and MCP `mc_lookup` expose this field. In MCP `mc_lookup`, it is lifted to the top level for auto-routed and direct query/symbol/code/context/chain/trace routes, so agents do not need to inspect nested `result` just to decide the next action. It tells agents whether to read existing `read_targets`, inspect a bounded symbol/code/chain/context result, switch to walkthrough, validate semantic hits, refine the query, or refresh stale evidence.

Lookup 结果还会返回兼容新增字段 `agent_next_steps`，它会根据 retrieval policy、新鲜度、completion status 和现有证据生成结构化下一步。CLI `memory-center query`、HTTP `/workspace/query` 和 MCP `mc_lookup` 都会暴露该字段。MCP `mc_lookup` 在自动路由和直接 query/symbol/code/context/chain/trace 路由下还会把该字段提升到顶层，Agent 不需要为了判断下一步再深入读取嵌套 `result`；字段会明确提示应读取现有 `read_targets`、检查有界的 symbol/code/chain/context 结果、切到 walkthrough、验证语义命中、细化查询，还是先刷新过期证据。

When CLI `memory-center query`, HTTP `/workspace/query`, or MCP `mc_lookup` receives `session_id`, Memory Center automatically records the returned `agent_next_steps` as an `agent_guidance` session event. This feeds `eval-agent-guidance-adoption` without requiring a separate manual log call.

当 CLI `memory-center query`、HTTP `/workspace/query` 或 MCP `mc_lookup` 传入 `session_id` 时，Memory Center 会自动把返回的 `agent_next_steps` 记录为 `agent_guidance` session event。这样 `eval-agent-guidance-adoption` 可以直接评估后续执行情况，不再需要额外手工写日志。

When adoption trend data shows a specific action is repeatedly missed, future query results keep the same action but add `adoption_feedback`, raise its priority, and rewrite `command` with a more explicit first tool/file step.

当 adoption 趋势显示某个 action 连续未被执行时，后续 query 结果会保留同一 action，但会附加 `adoption_feedback`、提升 priority，并把 `command` 改写成更明确的第一步工具或文件动作。

When replay trend data shows why guidance failed, future query results may also add `replay_feedback`. Bypass-heavy trends tell the agent to execute the Memory Center command before `rg` / `grep` / `find`; unobservable trends remind the caller to pass `session_id`; missing-target trends force `target_ref` / `read_targets` usage; action-mismatch trends point the agent to the Memory Center mode that matches the suggested action. Replay preserves event order: a local-search bypass before a later matching Memory Center call remains `bypassed`. Bypass detection uses structured tool names or shell command fields, not arbitrary text inside a tool payload. Method-level walkthrough suggestions preserve the resolved `target_ref` and `read_targets` when available.

当 replay 趋势说明建议为什么失败时，后续 query 结果还可能附加 `replay_feedback`。如果高频原因是绕过本地搜索，会提示先执行 Memory Center 命令再用 `rg` / `grep` / `find`；如果是不可观测，会提示调用方传入 `session_id`；如果缺少目标，会强制使用 `target_ref` / `read_targets`；如果是动作不匹配，会提示使用与建议 action 对应的 Memory Center mode。Replay 会保留事件顺序：先发生本地搜索绕过、之后才调用匹配的 Memory Center 工具，仍会归类为 `bypassed`。绕过检测只检查结构化工具名或 shell 命令字段，不会从 payload 任意文本中猜测；方法级 walkthrough 建议在可用时会保留解析到的 `target_ref` 与 `read_targets`。

When a method walkthrough starts from a sub-project workspace, Memory Center can automatically escalate to a parent or registry-covered aggregate workspace if that workspace produces a more complete cross-service flow. The `workspace_escalation` field records whether this happened; missing parents are safe fallbacks, not errors.

当 method walkthrough 从子项目 workspace 启动时，Memory Center 会尝试自动升级到父级或 registry 中覆盖当前项目的聚合 workspace，只在聚合结果更完整时切换。`workspace_escalation` 会记录是否切换；找不到父级不是错误。

Report formatting is configurable via `.memory-center/templates/method_walkthrough.md` or `.memory-center/method_walkthrough_template.md`. If no template exists, Memory Center returns a built-in `answer_markdown` plus top-level `summary_lines`, so agents can still organize the final response themselves.

报告格式可通过 `.memory-center/templates/method_walkthrough.md` 或 `.memory-center/method_walkthrough_template.md` 配置。未配置时会返回内置 `answer_markdown` 和顶层 `summary_lines`，保证 agent 仍可自行组织最终回答。

`mc_lookup(mode="walkthrough", report_level="brief|standard|deep|risk-focused")` controls the built-in report shape when no configured template exists. Workspace inputs may be a `workspace.yaml` file or a project directory; directory inputs are resolved upward to `.memory-center/workspace.yaml` when possible.

`mc_lookup(mode="walkthrough", report_level="brief|standard|deep|risk-focused")` 可控制未配置模板时的内置报告形态。workspace 入参既可以是 `workspace.yaml` 文件，也可以是项目目录；目录会尽量向上解析到 `.memory-center/workspace.yaml`。

Golden Benchmark can also run directly against an existing real workspace:

```bash
memory-center reindex --workspace examples/golden-benchmark/workspace.yaml
memory-center eval-golden \
  --workspace examples/golden-benchmark/workspace.yaml \
  --cases examples/golden-benchmark/cases.yaml
```

It also supports an existing real workspace:

```bash
memory-center eval-golden \
  --workspace /path/to/.memory-center/workspace.yaml \
  --cases /path/to/private-cases.yaml
```

Golden Benchmark 也可以直接对已有真实 workspace 运行：

```bash
memory-center reindex --workspace examples/golden-benchmark/workspace.yaml
memory-center eval-golden \
  --workspace examples/golden-benchmark/workspace.yaml \
  --cases examples/golden-benchmark/cases.yaml
```

也支持直接对已有真实 workspace 运行：

```bash
memory-center eval-golden \
  --workspace /path/to/.memory-center/workspace.yaml \
  --cases /path/to/private-cases.yaml
```

Use [examples/golden-benchmark/cases.template.yaml](/Users/cuijiaqi/Ai-common-skills/memory-center/examples/golden-benchmark/cases.template.yaml) as the public template, then keep real cases in a private local file.

可先用 [examples/golden-benchmark/cases.template.yaml](/Users/cuijiaqi/Ai-common-skills/memory-center/examples/golden-benchmark/cases.template.yaml) 作为公开模板，再把真实 case 维护在你本地私有文件里。

### Release Gate / 发布门禁

`release-gate` runs a full reindex, repeatable retrieval smoke checks, and optional Golden, Java call-resolution, and parser-precision checks as one release decision. Its output and saved baseline contain metrics and statuses only: no query text, filesystem paths, case IDs, or result payloads.

`release-gate` 会将全量重建、可重复的检索冒烟检查，以及可选的 Golden、Java 调用解析、解析器精度检查收敛为一次发布结论。输出和保存的 baseline 只包含指标与状态，不包含查询文本、文件路径、case ID 或结果 payload。

```bash
memory-center release-gate \
  --workspace /path/to/.memory-center/workspace.yaml \
  --query "logical symbol or business term" \
  --query "another stable query" \
  --golden-cases /path/to/.memory-center/golden/cases.yaml \
  --java-call-cases /path/to/.memory-center/golden/java-call-resolution.yaml \
  --parser-limit 200 \
  --save-baseline /path/to/.memory-center/golden/release-gate-baseline.json \
  --label vNext
```

`--query-samples N`（默认 `1`）可让同一查询执行 N 次：首轮记录冷查询，后续样本计算热查询 P95。发布 baseline 优先比较热查询 P95；N=1 时保持现有的单次查询开销。

Use `--query-samples N` (default `1`) to execute each query N times: the first sample records cold-query latency and the remaining samples produce hot-query P95. Release baselines prefer hot P95; N=1 preserves the existing single-query cost.

`release-gate` 默认要求热查询 P95 不超过 `2000ms`，并返回 `stage_p95_ms` 帮助定位精确检索、BM25、语义、图排序或邻居扩展的瓶颈。维护窗口可通过 `--max-hot-query-p95-ms 0` 显式关闭绝对预算，但仍会保留基线退化检查。

`release-gate` enforces a default `2000ms` hot-query P95 and returns `stage_p95_ms` to locate exact, BM25, semantic, graph-rank, or enrichment bottlenecks. A maintenance window can explicitly disable the absolute budget with `--max-hot-query-p95-ms 0`; baseline-regression checks remain active.

Use the saved portable baseline in later releases. A baseline is written only after the gate passes. The gate fails when a configured quality check fails, or when a shared component exceeds the latency or quality-drop threshold. Missing optional checks are reported as `skipped`, not treated as a pass.

后续版本可带上保存的 portable baseline。只有门禁通过时才会写入 baseline；已配置的质量检查失败，或共有组件超过延迟退化/质量下降阈值时，门禁会失败；未配置的可选检查会标记为 `skipped`，不会被伪装为通过。

```bash
memory-center release-gate \
  --workspace /path/to/.memory-center/workspace.yaml \
  --query "logical symbol or business term" \
  --baseline /path/to/.memory-center/golden/release-gate-baseline.json
```

Optional business glossary files `.memory-center/glossary.yaml`, `.memory-center/glossary.yml`, or `.memory-center/business-glossary.yaml` can enrich walkthrough output through `glossary_hits`.

可选的业务词汇文件 `.memory-center/glossary.yaml`、`.memory-center/glossary.yml` 或 `.memory-center/business-glossary.yaml` 会通过 `glossary_hits` 补充链路解释。

Walkthrough endpoint candidates include `confidence` and `confidence_reasons`. `index_freshness.index_stale=true` means at least one returned read target is newer than the current index and should be live-read or reindexed. Repeated walkthrough calls use a short in-process cache keyed by workspace, symbol, report shape, and index signature.

walkthrough 的 endpoint 候选会包含 `confidence` 和 `confidence_reasons`。当 `index_freshness.index_stale=true` 时，说明至少一个主链路文件比当前索引更新，应先读实时文件或重新 reindex。重复 walkthrough 会使用短期进程内缓存，缓存键包含 workspace、symbol、报告形态和索引签名。

Context lookup, impact analysis, and method walkthrough now share one evidence-bounded reasoning pipeline. `_reasoning` separates indexed `facts`, explainable `inferences`, and transitive `derived` results; every non-factual item includes its source, relations, confidence, and `why`. Existing `patterns`, `transitive`, and `risk` groups remain compatible.

Context lookup、影响分析和 method walkthrough 现在共用一条证据预算化 reasoning pipeline。`_reasoning` 会区分索引事实 `facts`、可解释推断 `inferences` 和传递派生 `derived`；每条非事实结果都包含来源、关系、置信度与 `why`。原有 `patterns`、`transitive`、`risk` 分组继续兼容。

Operational walkthrough helpers are available for upgrade checks and team handoff:

链路梳理还提供面向验收与协作的辅助能力：

```bash
memory-center walkthrough-health --workspace /path/to/project --symbol com.example.Service#method
memory-center walkthrough-eval --workspace /path/to/project --symbol com.example.Service#method
memory-center walkthrough-export --workspace /path/to/project --symbol com.example.Service#method
```

The equivalent MCP admin actions are `mc_admin(action="walkthrough_health")`, `mc_admin(action="eval_walkthrough_quality")`, and `mc_admin(action="walkthrough_export")`. Exported Markdown is written under `.memory-center/artifacts/walkthroughs/*.md`.

对应的 MCP admin action 是 `mc_admin(action="walkthrough_health")`、`mc_admin(action="eval_walkthrough_quality")` 和 `mc_admin(action="walkthrough_export")`。导出的 Markdown 会写入 `.memory-center/artifacts/walkthroughs/*.md`。

> **Note**: CLI and HTTP still expose all fine-grained atomic commands. Only the MCP surface uses facade tools. See [docs/MCP_GUIDE.md](./docs/MCP_GUIDE.md) and [docs/REFERENCE.md](./docs/REFERENCE.md) for facade routing and command reference.
>
> **注意**：CLI 和 HTTP 仍保留所有细粒度原子命令。只有 MCP 工具面使用 facade 工具。路由与命令参考见 [docs/MCP_GUIDE.md](./docs/MCP_GUIDE.md) 和 [docs/REFERENCE.md](./docs/REFERENCE.md)。

**Hook host integration** / **宿主集成层**（`memory_center/hooks/`）：

Hook 是宿主集成方案，不是 Memory Center 核心能力。它定义宿主（Claude Code / Codex / Cursor）在什么生命周期点自动触发哪些 facade 调用。

| Hook 事件 | Facade | 模式 | 说明 |
|-----------|--------|------|------|
| `session_start` | `mc_start` | soft | 不阻塞，注入上下文 |
| `pre_edit` | `mc_analyze` | guard | must-severity 规则匹配时阻塞编辑 |
| `session_stop` | `mc_close` | soft | 不阻塞，关闭并同步 |
| `user_prompt_submit` | `mc_start` | suggest | 注入提示，不执行命令 |

模式说明：soft（不阻塞），guard（风险规则匹配时阻塞，exit 2），suggest（只注入提示），off（禁用）。

配置文件：每 workspace 的 `.memory-center/hooks.yaml`（声明式，不同 workspace 可有不同策略）。

CLI 命令：
```bash
memory-center run-hook --workspace <workspace.yaml> --hook session_start  # 执行 hook
memory-center generate-hooks --workspace <workspace.yaml> --host claude-code  # 生成宿主配置
```

从当前版本开始，`init` / `reindex` 写入的受管说明块和 MCP 绑定不只落在聚合 workspace 根目录，也会镜像到各个已配置的 service 子项目根目录（如 `service-a/AGENTS.md`、`service-a/.codex/mcp.json`、`service-a/.cursor/mcp.json`、`service-a/.mcp.json`）。这样当你直接在子项目目录里打开 Codex / Claude / Cursor 时，Agent 能复用上层 `.memory-center/workspace.yaml` 并拿到 `mc_*` 工具。

Starting from this version, the managed instruction block and MCP bindings written by `init` / `reindex` are mirrored not only to the aggregate workspace root but also to each configured service root (for example `service-a/AGENTS.md`, `service-a/.codex/mcp.json`, `service-a/.cursor/mcp.json`, and `service-a/.mcp.json`). This helps agents launched inside a subproject reuse the parent `.memory-center/workspace.yaml` and receive the `mc_*` tools.

如果子项目里仍看不到 `mc_*` 工具，优先运行一键接入命令：

```bash
memory-center setup-agent --workspace <workspace.yaml>
```

If a subproject still does not expose `mc_*` tools, prefer the one-step setup command:

```bash
memory-center setup-agent --workspace <workspace.yaml>
```

该命令会刷新说明、Hooks、MCP 绑定并返回是否需要重启宿主会话；`runtime-audit --fix` 仍可作为底层诊断修复入口。

This command refreshes instructions, hooks, MCP bindings, and reports whether the host session should be restarted; `runtime-audit --fix` remains available as the lower-level diagnostic repair entrypoint.

详见 [docs/MCP_GUIDE.md](./docs/MCP_GUIDE.md)。

Supported model targets for handoff now include `codex`, `claude-code`, `cursor-agent`, `gemini`, `deepseek`, `glm`, `qwen`, `minimax`, `mimo`, and generic MCP agents.

目前交接能力已支持 `codex`、`claude-code`、`cursor-agent`、`gemini`、`deepseek`、`glm`、`qwen`、`minimax`、`mimo` 以及通用 MCP Agent。

`mc_resume` is now rule-driven by `rules/resume-rules.yaml`, and model handoff preferences are driven by `rules/handoff-profiles.yaml`.

`mc_resume` 现在由 `rules/resume-rules.yaml` 驱动，模型交接偏好由 `rules/handoff-profiles.yaml` 驱动。

Write placement, auto-sync strategy, and eval penalties can now also be tuned through:

- `rules/write-policy-rules.yaml`
- `rules/auto-sync-rules.yaml`
- `rules/eval-rules.yaml`

现在写入层级判定、自动同步策略和评估扣分项也都可以通过下面这些规则文件调整：

- `rules/write-policy-rules.yaml`
- `rules/auto-sync-rules.yaml`
- `rules/eval-rules.yaml`

Daily continuity view is now available through `mc_admin(action="continuity")`, which aggregates focus task, resume packet, next actions, unresolved items, receipts, handoffs and evidence.

现在还提供了日常连续性视图 `mc_admin(action="continuity")`，会汇总当前焦点任务、恢复包、下一步动作、未解决事项、回执、交接历史和近期证据。

At the workspace level, `mc_admin(action="dashboard")` provides a broader operational view: active tasks, resumable tasks, blocked tasks, low-quality tasks, recent handoffs and recent write receipts.

在 workspace 级别，`mc_admin(action="dashboard")` 会进一步提供更宽的运营视图：活跃任务、可恢复任务、阻塞任务、低质量任务、最近交接和最近写入回执。

The dashboard also includes `focus_resume_eval` and `agent_guidance`, so the current focus task has directly visible resume-quality and next-step guidance signals.

总面板现在还会包含 `focus_resume_eval` 和 `agent_guidance`，让当前焦点任务的恢复包质量与下一步建议质量直接可见。

You can now export the workspace dashboard as HTML or Markdown with `memory-center export-workspace-dashboard --format html|markdown`.

现在还可以通过 `memory-center export-workspace-dashboard --format html|markdown` 导出 workspace 总面板的 HTML 或 Markdown 版本。

Resume and handoff packets can now be evaluated through `mc_admin(action=”eval_resume”)` and `mc_admin(action=”eval_handoff”)`, so continuity quality is no longer implicit.

现在还可以通过 `mc_admin(action=”eval_resume”)` 和 `mc_admin(action=”eval_handoff”)` 评估恢复包与交接包的质量，让连续性能力从”有接口”变成”可量化”。

`mc_lookup(mode=”auto”)` can now route lookup-style questions toward the best search strategy, or suggest local search when the query is too small and local.

Learning-backed candidate-path and workflow recommendations can now be inspected directly through `memory-center heuristics --action explain ...` or `mc_admin(action="heuristics_explain")`, so recommendation changes are explainable instead of opaque.

现在候选路径与 workflow 推荐背后的学习结果，也可以直接通过 `memory-center heuristics --action explain ...` 或 `mc_admin(action="heuristics_explain")` 查看，不再只是黑盒升降权。

现在还可以通过 `mc_lookup(mode=”auto”)` 给”找类 / 找方法 / 找调用链”这类问题做检索路由建议，告诉 Agent 该优先走哪个检索策略，还是先本地搜索更划算。

`mc_admin(action=”tool_usage_report”)` summarizes recent Memory Center tool adoption and flags suspected bypasses where lookup-like tool calls did not use Memory Center.

`mc_admin(action=”tool_usage_report”)` 会汇总近期 Memory Center 工具使用率，并标记那些”看起来在找类/符号/调用链，但没有走 Memory Center”的疑似绕过场景。

The evaluation layer now also includes:

- `mc_admin(action="eval_index_freshness")`
- `mc_admin(action="eval_tool_adoption")`
- `mc_admin(action="eval_context_weight")`
- `mc_admin(action="eval_agent_guidance")`
- `mc_admin(action="eval_agent_guidance_adoption")`
- `mc_admin(action="eval_agent_guidance_adoption_trend")`
- `mc_admin(action="eval_agent_guidance_replay")`
- `mc_admin(action="eval_agent_guidance_replay_trend")`
- `mc_admin(action="eval_agent_guidance_trend")`

These help answer whether indexes are stale, whether models are actually using Memory Center, whether compact payloads are still too heavy, whether lookup output includes bounded `agent_next_steps` without invalid broad-search suggestions, and whether recorded guidance was actually followed by later tool calls. Use `eval_agent_guidance_replay` when adoption is low and you need the reason: it classifies guidance as `adopted`, `missed`, `bypassed`, or `unobservable` and reports reason counts. Use `eval_agent_guidance_trend` to append a quality trend point into `.memory-center/memory/agent-guidance-trends.jsonl`; use `eval_agent_guidance_adoption_trend` to append an adoption-rate trend point into `.memory-center/memory/agent-guidance-adoption-trends.jsonl`; use `eval_agent_guidance_replay_trend` to append a replay-quality trend point into `.memory-center/memory/agent-guidance-replay-trends.jsonl`. `eval_agent_guidance`, `eval_agent_guidance_adoption`, and `eval_agent_guidance_replay` are read-only.

评测层现在还额外包含：

- `mc_admin(action="eval_index_freshness")`
- `mc_admin(action="eval_tool_adoption")`
- `mc_admin(action="eval_context_weight")`
- `mc_admin(action="eval_agent_guidance")`
- `mc_admin(action="eval_agent_guidance_adoption")`
- `mc_admin(action="eval_agent_guidance_adoption_trend")`
- `mc_admin(action="eval_agent_guidance_replay")`
- `mc_admin(action="eval_agent_guidance_replay_trend")`
- `mc_admin(action="eval_agent_guidance_trend")`

它们分别用于判断索引是否过期、模型是否真的在使用 Memory Center、compact payload 是否仍然偏重、lookup 输出是否包含有界的 `agent_next_steps` 且没有无效的泛搜索建议，以及已记录的建议是否真的被后续 tool call 执行。adoption 偏低时使用 `eval_agent_guidance_replay` 定位原因：它会把建议分类为 `adopted`、`missed`、`bypassed` 或 `unobservable`，并输出原因计数。需要写入建议质量历史曲线时使用 `eval_agent_guidance_trend`，它会追加到 `.memory-center/memory/agent-guidance-trends.jsonl`；需要写入 adoption rate 历史曲线时使用 `eval_agent_guidance_adoption_trend`，它会追加到 `.memory-center/memory/agent-guidance-adoption-trends.jsonl`；需要写入 replay 质量曲线时使用 `eval_agent_guidance_replay_trend`，它会追加到 `.memory-center/memory/agent-guidance-replay-trends.jsonl`。`eval_agent_guidance`、`eval_agent_guidance_adoption` 与 `eval_agent_guidance_replay` 本身保持只读。

To reduce model-side token usage, `workspace_sniff`, `workspace_status`, `workspace_resume_packet`, `workspace_recent_evidence` (now with `view=compact|full`), `workspace_continuity_dashboard`, `workspace_dashboard`, and `workspace_handoff_packet` all support `view=compact|full` plus `budget=small|medium|large`. MCP defaults to `compact + medium`; use `full` for local debugging or manual inspection.

为了降低模型侧 token 消耗，`workspace_sniff`、`workspace_status`、`workspace_resume_packet`、`workspace_recent_evidence`（现已补齐 `view=compact|full`）、`workspace_continuity_dashboard`、`workspace_dashboard`、`workspace_handoff_packet` 现在都支持 `view=compact|full`，并新增 `budget=small|medium|large`。MCP 默认使用 `compact + medium`；本地调试或人工排查时再切 `full`。

`workspace_handoff_packet` now follows the same `view=compact|full` and `budget=small|medium|large` contract, so the context-light protocol is aligned across sniff/resume/handoff/dashboard.

`workspace_handoff_packet` 现在也已经补齐 `view=compact|full` 和 `budget=small|medium|large`，因此轻量上下文协议在 sniff / resume / handoff / dashboard 这几条主链路上已经对齐。

For fixed regressions, `memory_eval_regression_suite` now aggregates write/resume/handoff/agent-guidance evals into one suite-level score.

为了做固定回归，`memory_eval_regression_suite` 现在会把 write/resume/handoff/agent-guidance 四类评估聚合成一份 suite 级结果。

It is now exposed through CLI, MCP, and HTTP as `eval-regression-suite`, `memory_eval_regression_suite_tool`, and `/workspace/eval-regression-suite`.

它现在已经通过 CLI、MCP、HTTP 三条入口暴露出来：`eval-regression-suite`、`memory_eval_regression_suite_tool`、`/workspace/eval-regression-suite`。

Agent guidance adoption is exposed as `eval-agent-guidance-adoption`, `/workspace/eval-agent-guidance-adoption`, and `mc_admin(action="eval_agent_guidance_adoption")`. It reads `agent_guidance` / `agent_next_steps` session events and checks whether following `tool_call` events match the suggested action.

Agent guidance adoption 入口为 `eval-agent-guidance-adoption`、`/workspace/eval-agent-guidance-adoption` 和 `mc_admin(action="eval_agent_guidance_adoption")`。它会读取 `agent_guidance` / `agent_next_steps` session event，并检查后续 `tool_call` 是否匹配建议动作。

Agent guidance adoption trend recording is exposed as `eval-agent-guidance-adoption-trend`, `/workspace/eval-agent-guidance-adoption-trend`, and `mc_admin(action="eval_agent_guidance_adoption_trend")`. Benchmark trend reports and regression alerts include `agent_guidance_adoption_trends`, so daily checks can catch falling adoption rate.

Agent guidance adoption 趋势记录入口为 `eval-agent-guidance-adoption-trend`、`/workspace/eval-agent-guidance-adoption-trend` 和 `mc_admin(action="eval_agent_guidance_adoption_trend")`。Benchmark trend report 与 regression alerts 现在会包含 `agent_guidance_adoption_trends`，日常检查可以发现 adoption rate 下降。

Agent guidance replay is exposed as `eval-agent-guidance-replay`, `/workspace/eval-agent-guidance-replay`, and `mc_admin(action="eval_agent_guidance_replay")`. Replay trend recording is exposed as `eval-agent-guidance-replay-trend`, `/workspace/eval-agent-guidance-replay-trend`, and `mc_admin(action="eval_agent_guidance_replay_trend")`; benchmark reports and regression alerts include `agent_guidance_replay_trends` to surface bypass and unobservable rates.

Agent guidance replay 入口为 `eval-agent-guidance-replay`、`/workspace/eval-agent-guidance-replay` 和 `mc_admin(action="eval_agent_guidance_replay")`。Replay 趋势记录入口为 `eval-agent-guidance-replay-trend`、`/workspace/eval-agent-guidance-replay-trend` 和 `mc_admin(action="eval_agent_guidance_replay_trend")`；benchmark report 与 regression alerts 会包含 `agent_guidance_replay_trends`，用于暴露绕过率和不可观测率。

Adoption trend points also store `missed_action_counts`. Query-time `agent_next_steps` uses those counts as bounded feedback: only actions missed in the latest regressed trend are reinforced, and normal query behavior is unchanged when adoption is healthy.

Adoption 趋势点还会记录 `missed_action_counts`。Query 阶段的 `agent_next_steps` 会把这些计数作为有界反馈：只强化最近退化趋势里确实 missed 的 action；adoption 健康时保持原有查询行为不变。

Replay trend points store `reason_counts`. Query-time `agent_next_steps` uses the latest regressed replay reason as bounded feedback and leaves healthy workspaces unchanged.

Replay 趋势点会记录 `reason_counts`。Query 阶段的 `agent_next_steps` 会把最近退化 replay 原因作为有界反馈；replay 健康时保持原有查询行为不变。

Agent guidance trend recording is exposed as `eval-agent-guidance-trend`, `/workspace/eval-agent-guidance-trend`, and `mc_admin(action="eval_agent_guidance_trend")`. Benchmark trend reports and regression alerts include `agent_guidance_trends`, so daily checks can catch falling `agent_next_steps` coverage or renewed invalid broad-search suggestions.

Agent guidance 趋势记录入口为 `eval-agent-guidance-trend`、`/workspace/eval-agent-guidance-trend` 和 `mc_admin(action="eval_agent_guidance_trend")`。Benchmark trend report 与 regression alerts 现在会包含 `agent_guidance_trends`，日常检查可以发现 `agent_next_steps` 覆盖率下降或无效泛搜索建议回潮。

Short references can now be expanded through `memory_ref_get` / `memory_ref_batch`, so compact evidence can stay tiny until the model explicitly needs the raw payload.

现在短引用也可以通过 `memory_ref_get` / `memory_ref_batch` 再展开回原始内容，因此默认上下文可以保持很轻，只有模型明确需要时才取细节。

For one-command health checks, `memory-center regression-smoke --workspace ...` now runs write, session, sync, ref expansion, compact views, and regression suite checks together.

为了做一键健康检查，现在可以直接运行 `memory-center regression-smoke --workspace ...`，它会一起检查写入、session、sync、短引用展开、compact 视图和 regression suite。

Runtime state is stored in the single local SQLite database `.memory-center/graph/graph.db`: graph, index metadata, session records, assertions and retrieval structures share one transactional fact store. JSON/JSONL files remain inspectable exports; Markdown artifacts remain human-authored source material.

运行时状态统一保存在 `.memory-center/graph/graph.db`：图、索引元数据、会话记录、断言和检索结构共享同一个事务事实库。JSON/JSONL 文件仅供审查和导出；Markdown 工件仍是人工维护的内容来源。

You can also query the mirrored backend directly through `memory-backend-query` / `memory_backend_query_tool` / `/workspace/memory-backend-query`.

现在也可以直接查询这层镜像后端：`memory-backend-query` / `memory_backend_query_tool` / `/workspace/memory-backend-query`。

`timeline_query` and the higher-level evidence/replay views can now read from the mirrored SQLite backend in `auto/sqlite` mode, so the backend is already starting to participate in real read paths instead of being write-only.

`timeline_query` 以及上层的 evidence/replay 视图直接读取 SQLite 运行时事实库；JSONL 只作为可审查导出，不再作为查询兜底。

`workspace_recent_sessions`、`workspace_session_summary`、`workspace_write_receipts` 现在也会优先复用镜像后的 SQLite backend，并在需要时回退到原始 JSONL。

`workspace_recent_sessions`、`workspace_session_summary`、`workspace_write_receipts` 现在也已经优先复用镜像后的 SQLite backend，并在必要时回退到原始 JSONL。

`workspace_sniff` 的历史 case/session 召回、`workspace_resume_context`、`memory_tool_usage_report`、`write_receipts_overview` 现在也已经优先复用镜像后的 SQLite backend。

Under the hood, session events, write receipts and handoff history are now converging toward one shared timeline substrate, so replay, dashboard, evidence lookup and eval can reuse the same chronological model.

在底层，session events、write receipts 和 handoff history 现在开始收敛到同一套 timeline substrate，这样 replay、dashboard、evidence lookup 和 eval 可以复用同一个时间线模型。

For agentmemory-style regression checks, `memory_eval_token_benchmark` now compares 7 high-frequency compact responses (`sniff / status / resume / recent_evidence / continuity / dashboard / handoff`) across `small / medium / large` budgets and returns both per-function tables and total token counts.

为了做 agentmemory 风格的回归检查，`memory_eval_token_benchmark` 现在会对 7 个高频 compact 返回（`sniff / status / resume / recent_evidence / continuity / dashboard / handoff`）在 `small / medium / large` 三档预算下做 token 对比，并同时返回按函数分组的表格和总 token 统计。

`workspace_recent_evidence` also now uses an explicit top-K evidence strategy in compact mode: `small=3`、`medium=5`、`large=10`。排序优先级为 `ref_id + summary + payload_ref/receipt_ref` 的信号丰富度，再按时间倒序，避免 evidence 数量跟通用 event 限额一起漂移。

## Stable Schemas / 稳定协议

The following response families now carry explicit schema metadata through `schema.name` and `schema.version`, so external CLI wrappers, MCP clients, HTTP consumers, exporters and future UI layers can bind to stable contracts instead of loose dictionaries.

以下核心返回现在都会带 `schema.name` 和 `schema.version`，方便 CLI 包装层、MCP 客户端、HTTP 消费方、导出器和后续 UI 直接绑定稳定协议，而不是依赖松散的字典结构。

| Schema | Purpose / 用途 | Stable payload highlights / 稳定字段重点 |
|---|---|---|
| `write_receipt` | One persisted write action / 单次持久化写入动作 | `receipt_id`, `summary`, `layer`, `action`, `scope`, `target`, `target_file`, `task_id`, `session_id`, `receipt_ref` |
| `timeline_item` | One chronological event / 单个时间线事件 | `kind`, `created_at`, `task_id`, `session_id`, `layer`, `action`, `scope`, `target`, `receipt_ref` |
| `timeline_result` | Timeline query result / 时间线查询结果 | `timeline`, `limit`, `filters` |
| `eval_result` | Unified eval output / 统一评估结果 | `score`, `quality`, `findings` |
| `memory_ref` | One expanded short reference / 单个短引用展开结果 | `ref_id`, `kind`, `summary`, `raw`, `timeline_ref`, `found` |
| `memory_ref_batch` | Batch expanded short references / 批量短引用展开结果 | `requested`, `found_count`, `refs` |
| `resume_packet` | Cross-session resume contract / 跨会话恢复协议 | `task_id`, `current_summary`, `next_recommended_actions`, `unresolved_items`, `resume_rule_profile` |
| `handoff_packet` | Cross-model handoff contract / 跨模型交接协议 | `target_model`, `model_profile`, `handoff_rule_profile`, `minimal_required_context`, `what_to_check_next` |
| `workspace_continuity_dashboard` | Task continuity view / 单任务连续性视图 | `focus_task`, `resume_packet`, `next_actions`, `unresolved_items`, `recent_evidence` |
| `workspace_dashboard` | Workspace operational dashboard / 工作区总面板 | `focus_task`, `continuity_overview`, `write_receipts_overview`, `active_tasks`, `recent_handoffs`, `focus_resume_eval` |

Timeline consumers should treat `session_event`, `write_receipt`, and `handoff` as the three current canonical `timeline_item.kind` values.

使用 timeline 的外部系统目前应把 `session_event`、`write_receipt`、`handoff` 视为三种正式的 `timeline_item.kind` 枚举值。
| `memory_detect_changes_tool` | Git diff risk mapping / Git 变更风险映射 |
| `memory_contracts_tool` | API/Feign/MQ contract list / 契约列表 |
| `workspace_trace_tool` | Cross-service trace hints / 跨服务追踪 |
| `workspace_check_contract_tool` | Contract safety check / 契约变更检查 |
| `workspace_check_rules_tool` | Rule matching / 规则匹配 |
| `workspace_record_case_tool` | Record solved task memory / 任务经验沉淀 |
| `workspace_start_session_tool` | Start session memory / 开始会话记忆 |
| `workspace_log_session_event_tool` | Append session event / 追加会话事件 |
| `workspace_end_session_tool` | End session and summarize / 结束会话并生成摘要 |
| `workspace_recent_sessions_tool` | Read recent sessions / 查看最近会话 |
| `workspace_session_summary_tool` | Read one session summary / 查看单次会话摘要 |
| `workspace_resume_context_tool` | Resume context by intent / 按意图恢复会话上下文 |
| `workspace_suggest_case_tool` | Suggest case draft from session / 从会话生成经验草稿 |
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

AI 编程助手改代码前推荐按 facade 协议执行：

```text
1. Call mc_start(intent)
2. For any class/method/Feign/topic/config/call-chain lookup, call mc_lookup(mode="auto", query=...)
   - If the user asks for Class#method 全链路 / 到底层 / full chain, prefer mc_lookup(mode="walkthrough") or auto-routed walkthrough.
   - If walkthrough returns absolute_file_path, read that path directly; do not run find / grep -l / rg --files / IDE search to locate the same Controller or ServiceImpl.
3. Before implementation, call mc_analyze(target, depth="standard"|"full")
4. If the task is long-running or collaborative, call mc_sync(...)
5. During long tasks, use mc_resume(...) or session workflow commands to keep continuity
6. After validation, call mc_close(...)
7. If another model will continue, call mc_handoff(...)
```

Atomic tools are still available through CLI / HTTP / internal orchestrator paths when finer control is needed, but MCP users should treat the 8 facade tools as the default public surface.

当需要更细粒度控制时，CLI / HTTP / 内部 orchestrator 仍可使用原子能力；但对 MCP 调用方来说，默认公开接口应视为这 8 个 facade 工具。

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

You can also open the built-in local workbench pages:

- `/ui`
- `/ui/dashboard`
- `/ui/continuity`
- `/ui/task`
- `/ui/task?task_id=...`
- `/ui/timeline`
- `/ui/receipts`
- `/ui/usage`
- `/ui/backend`
- `/ui/index-freshness`
- `/ui/ref?ref_id=...`

现在也可以直接打开内置本地工作台页面：

- `/ui`
- `/ui/dashboard`
- `/ui/continuity`
- `/ui/task`
- `/ui/task?task_id=...`
- `/ui/timeline`
- `/ui/receipts`
- `/ui/usage`
- `/ui/backend`
- `/ui/index-freshness`
- `/ui/ref?ref_id=...`

Or:

```bash
memory-center-http --workspace /path/to/.memory-center/workspace.yaml
```

`GET` 只用于无副作用读取；所有会修改 workspace 的 HTTP 路由必须使用 `POST`。默认仅允许回环地址；如需绑定局域网或其他非回环地址，必须显式设置强随机令牌：

`GET` is only for side-effect-free reads; every workspace mutation requires `POST`. The bridge defaults to loopback-only use. Binding to a LAN or any other non-loopback address requires an explicit strong token:

```bash
MEMORY_CENTER_HTTP_TOKEN="replace-with-a-strong-random-token" \
memory-center serve-http --workspace /path/to/.memory-center/workspace.yaml --host 0.0.0.0 --port 8765
```

远程调用通过 `Authorization: Bearer <token>` 传递令牌。协作资产的 metadata 最大 16 KiB；`asset-status`、`asset-loadout` 和 Context Pack 都会返回预算与 `truncated`/`truncated_sections`，调用方应按来源引用继续按需读取，而不是请求无界正文。

Remote callers send `Authorization: Bearer <token>`. Collaboration-asset metadata is capped at 16 KiB; `asset-status`, `asset-loadout`, and Context Pack report their budgets plus `truncated`/`truncated_sections`, so callers can continue from provenance references instead of requesting unbounded content.

Example routes:

- `GET /health`
- `GET /workspace/status?workspace=/path/to/.memory-center/workspace.yaml`
- `GET /workspace/query?workspace=/path/to/.memory-center/workspace.yaml&text=ArticleFeignClient`
- `GET /workspace/search-code?workspace=/path/to/.memory-center/workspace.yaml&text=ArticleFeignClient&scope=task-service`
- `GET /workspace/symbol?workspace=/path/to/.memory-center/workspace.yaml&name=ArticleMoveService`
- `GET /workspace/callers?workspace=/path/to/.memory-center/workspace.yaml&symbol=ArticleMoveService&depth=2`
- `GET /workspace/callees?workspace=/path/to/.memory-center/workspace.yaml&symbol=ArticleMoveService&depth=2`
- `GET /workspace/plan-change?workspace=/path/to/.memory-center/workspace.yaml&target=MoveArticleRequest`
- `GET /workspace/verify-checklist?workspace=/path/to/.memory-center/workspace.yaml&target=MoveArticleRequest`
- `GET /workspace/suggest-case?workspace=/path/to/.memory-center/workspace.yaml&session_id=session-xxxx`
- `GET /workspace/work-resume-check?workspace=/path/to/.memory-center/workspace.yaml&task_id=some-task`
- `GET /group/status?group=backend-platform`
- `GET /group/query?group=backend-platform&text=ArticleFeignClient`
- `GET /group/impact?group=backend-platform&target=ArticleFeignClient`

写入示例：`POST /workspace/asset/register`、`POST /workspace/artifact/update`、`POST /workspace/work-start`。`/workspace/query` 不带 `session_id` 可用 GET；带 `session_id` 会记录指导事件，因此必须 POST。

Mutation examples: `POST /workspace/asset/register`, `POST /workspace/artifact/update`, and `POST /workspace/work-start`. `/workspace/query` may use GET without `session_id`; a query with `session_id` records a guidance event and therefore requires POST.

---

## Documentation Status / 文档状态

- `docs/` 的目录导航首页是 [docs/README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/README.md)。
- 当前对外说明以 [docs/DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md) 为准。
- 当前实现状态、最近改动和版本变化以 [docs/CHANGELOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/CHANGELOG.md) 为准。
- 当前唯一活跃开发路线以 [docs/NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md) 为准。
- `docs/archive/ROADMAP.md`、`docs/archive/DELEGATED_EXECUTION_PLAN.md`、`docs/archive/DELEGATED_EXECUTION_LOG.md`、`docs/archive/CBM_INSPIRED_EVOLUTION_PLAN.md` 仅保留为历史背景，不再作为当前版本状态说明。

---

## Security model / 安全模型

Memory Center is local-first and read-only by default. Query/context/impact/contract tools do not modify business source code. Write tools are limited to Memory Center artifacts such as task memory, wiki, and generated skills. See `docs/MCP_GUIDE.md`.

记忆中心默认本地优先、只读优先。查询、上下文、影响分析、契约查看不会修改业务源码；写入类工具只写记忆、Wiki、Skill 等 Memory Center 产物。详见 `docs/MCP_GUIDE.md`。

## License / 许可证

Apache-2.0
