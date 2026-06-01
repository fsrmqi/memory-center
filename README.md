# Memory Center / 记忆中心

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

记忆中心的核心思想是：**不要让 AI 每次临时理解项目，而是在索引阶段提前构建服务图、调用图、契约图、消息图、规则图、经验图。**

实施路线图请见：

- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [docs/SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
- [docs/SPECIAL_NOTES.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECIAL_NOTES.md)
- [docs/ROADMAP.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ROADMAP.md)
- [docs/TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_GUIDE.md)
- [docs/NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md)

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

Each protected write also records `write_mode` and an `audit_ref` into `memory/artifact-write-audit.jsonl`, so you can later inspect whether a model attempted a full overwrite or was downgraded to guarded append.

每次受保护的工件写入还会把 `write_mode` 和 `audit_ref` 记录到 `memory/artifact-write-audit.jsonl`，这样后续可以追查模型到底是正常追加，还是曾经试图整篇覆盖后被降级成受保护追加。

Detailed local setup and multi-project workflow / 详细本地初始化与多项目使用流程：

- [docs/USER_GUIDE.md](./docs/USER_GUIDE.md)
- [docs/MCP_GUIDE.md](./docs/MCP_GUIDE.md)
- [docs/SPECS.md](./docs/SPECS.md)
- [docs/ROADMAP.md](./docs/ROADMAP.md)
- [docs/TECHNICAL_GUIDE.md](./docs/TECHNICAL_GUIDE.md)
- [docs/NEXT_PHASE_MASTER_PLAN.md](./docs/NEXT_PHASE_MASTER_PLAN.md)

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
memory-center-mcp --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
```

If your MCP client requires an absolute command path, use:

如果你的 MCP 客户端要求命令绝对路径，可以使用：

```bash
/Users/cuijiaqi/.local/bin/memory-center-mcp --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml
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
```

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
  --intent "oldPubTime newPubTime ArticleFeignClient 文章发布时间迁移" \
  --auto-sync-mode balanced
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

```bash
memory-center artifact create-task \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --title "Feign DTO 兼容改造"

memory-center artifact list-tasks \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml

memory-center artifact auto-archive-tasks \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --retention-days 30
```

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
  --payload '{"tool_name":"memory_query_tool","query":"ArticleFeignClient"}'

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
| `mc_lookup` | Unified knowledge lookup (auto/symbol/code/query/trace/chain/context/contracts/ref/backend) / 统一知识检索，mode 自动路由到最佳策略 |
| `mc_analyze` | Change impact analysis (quick/standard/full depth) / 变更影响面分析，按 depth 逐层深入 |
| `mc_sync` | Sync context to workspace artifacts (sniff or case) / 同步上下文到工件 |
| `mc_resume` | Resume task with consolidated context / 恢复任务上下文 |
| `mc_handoff` | Build handoff package for another model / 为目标模型生成交接包 |
| `mc_close` | Close task workflow: end session → sync case → record experience / 关闭任务工作流 |
| `mc_admin` | Admin router (status/dashboard/eval/artifact/session/group etc.) / 管理路由，action 选择子操作 |

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

The dashboard also includes `focus_resume_eval`, so the current focus task has a directly visible resume-quality signal.

总面板现在还会包含 `focus_resume_eval`，让当前焦点任务的恢复包质量直接可见。

You can now export the workspace dashboard as HTML or Markdown with `memory-center export-workspace-dashboard --format html|markdown`.

现在还可以通过 `memory-center export-workspace-dashboard --format html|markdown` 导出 workspace 总面板的 HTML 或 Markdown 版本。

Resume and handoff packets can now be evaluated through `mc_admin(action=”eval_resume”)` and `mc_admin(action=”eval_handoff”)`, so continuity quality is no longer implicit.

现在还可以通过 `mc_admin(action=”eval_resume”)` 和 `mc_admin(action=”eval_handoff”)` 评估恢复包与交接包的质量，让连续性能力从”有接口”变成”可量化”。

`mc_lookup(mode=”auto”)` can now route lookup-style questions toward the best search strategy, or suggest local search when the query is too small and local.

现在还可以通过 `mc_lookup(mode=”auto”)` 给”找类 / 找方法 / 找调用链”这类问题做检索路由建议，告诉 Agent 该优先走哪个检索策略，还是先本地搜索更划算。

`mc_admin(action=”tool_usage_report”)` summarizes recent Memory Center tool adoption and flags suspected bypasses where lookup-like tool calls did not use Memory Center.

`mc_admin(action=”tool_usage_report”)` 会汇总近期 Memory Center 工具使用率，并标记那些”看起来在找类/符号/调用链，但没有走 Memory Center”的疑似绕过场景。

The evaluation layer now also includes:

- `mc_admin(action="eval_index_freshness")`
- `mc_admin(action="eval_tool_adoption")`
- `mc_admin(action="eval_context_weight")`

These help answer whether indexes are stale, whether models are actually using Memory Center, and whether compact payloads are still too heavy.

评测层现在还额外包含：

- `mc_admin(action="eval_index_freshness")`
- `mc_admin(action="eval_tool_adoption")`
- `mc_admin(action="eval_context_weight")`

它们分别用于判断索引是否过期、模型是否真的在使用 Memory Center、以及 compact payload 是否仍然偏重。

To reduce model-side token usage, `workspace_sniff`, `workspace_status`, `workspace_resume_packet`, `workspace_recent_evidence` (now with `view=compact|full`), `workspace_continuity_dashboard`, `workspace_dashboard`, and `workspace_handoff_packet` all support `view=compact|full` plus `budget=small|medium|large`. MCP defaults to `compact + medium`; use `full` for local debugging or manual inspection.

为了降低模型侧 token 消耗，`workspace_sniff`、`workspace_status`、`workspace_resume_packet`、`workspace_recent_evidence`（现已补齐 `view=compact|full`）、`workspace_continuity_dashboard`、`workspace_dashboard`、`workspace_handoff_packet` 现在都支持 `view=compact|full`，并新增 `budget=small|medium|large`。MCP 默认使用 `compact + medium`；本地调试或人工排查时再切 `full`。

`workspace_handoff_packet` now follows the same `view=compact|full` and `budget=small|medium|large` contract, so the context-light protocol is aligned across sniff/resume/handoff/dashboard.

`workspace_handoff_packet` 现在也已经补齐 `view=compact|full` 和 `budget=small|medium|large`，因此轻量上下文协议在 sniff / resume / handoff / dashboard 这几条主链路上已经对齐。

For fixed regressions, `memory_eval_regression_suite` now aggregates write/resume/handoff evals into one suite-level score.

为了做固定回归，`memory_eval_regression_suite` 现在会把 write/resume/handoff 三类评估聚合成一份 suite 级结果。

It is now exposed through CLI, MCP, and HTTP as `eval-regression-suite`, `memory_eval_regression_suite_tool`, and `/workspace/eval-regression-suite`.

它现在已经通过 CLI、MCP、HTTP 三条入口暴露出来：`eval-regression-suite`、`memory_eval_regression_suite_tool`、`/workspace/eval-regression-suite`。

Short references can now be expanded through `memory_ref_get` / `memory_ref_batch`, so compact evidence can stay tiny until the model explicitly needs the raw payload.

现在短引用也可以通过 `memory_ref_get` / `memory_ref_batch` 再展开回原始内容，因此默认上下文可以保持很轻，只有模型明确需要时才取细节。

For one-command health checks, `memory-center regression-smoke --workspace ...` now runs write, session, sync, ref expansion, compact views, and regression suite checks together.

为了做一键健康检查，现在可以直接运行 `memory-center regression-smoke --workspace ...`，它会一起检查写入、session、sync、短引用展开、compact 视图和 regression suite。

The first unified backend step is now in place: session events, session summaries, handoff history, case atoms, write receipts, and ref metadata are mirrored into a local SQLite `memory.db`, while JSONL/Markdown files remain the source of truth.

统一后端的第一步也已经落地：session events、session summaries、handoff history、case atoms、write receipts 和 ref metadata 现在会镜像写入本地 SQLite `memory.db`，同时继续保留 JSONL/Markdown 作为主落盘形态。

You can also query the mirrored backend directly through `memory-backend-query` / `memory_backend_query_tool` / `/workspace/memory-backend-query`.

现在也可以直接查询这层镜像后端：`memory-backend-query` / `memory_backend_query_tool` / `/workspace/memory-backend-query`。

`timeline_query` and the higher-level evidence/replay views can now read from the mirrored SQLite backend in `auto/sqlite` mode, so the backend is already starting to participate in real read paths instead of being write-only.

`timeline_query` 以及上层的 evidence/replay 视图现在也已经可以在 `auto/sqlite` 模式下直接读取镜像后的 SQLite backend，这意味着后端已经开始参与真实读路径，而不只是写入镜像。

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
- `GET /group/status?group=backend-platform`
- `GET /group/query?group=backend-platform&text=ArticleFeignClient`
- `GET /group/impact?group=backend-platform&target=ArticleFeignClient`

---

## Roadmap / 路线图

- v2.0.8: MCP facade 重构（82→8），hooks.yaml + runner + adapters
- v2.0.9: 增量索引系统、SQLite 镜像后端、评测体系（7 eval + token_gain）
- v2.0.10: WP2/WP3 收口（recent_evidence view/gain、ref→timeline 反向导航）
- v2.0.10: WP5 交互增强（budget/compact UI 切换、refs `<details>` 内联展开）
- v2.0.11: WP5 深化（guided tour overlay、Next Action hero、跨页 drill-down）
- v2.0.11: WP3 深化（全部高频函数默认 compact、compact 收紧为严格短引用）
- v2.0.11: Hooks 收口（Codex chmod +x、Cursor MCP 命令指令）
- v2.1.0: 外部参考吸收（agentmemory benchmark/top-K/hybrid、skills 强约束模板）
- v2.1.0: SQLite 后端更多真实读路径、长期趋势仪表盘
- **v2.2.0: NEXT_PHASE_MASTER_PLAN 全部实现（2026-06-01）**
  - ✅ **Hybrid Retrieval**: 智能混合检索引擎（graph/sparse/semantic）
  - ✅ **Benchmark Trending**: 基准趋势监控和回归检测
  - ✅ **SQLite Main Read Path**: 统一后端查询层
  - ✅ **Timeline/Ref/Task Drill-down**: 渐进式钻取导航
  - ✅ **Completion Audit**: 自动化完成审计和设计决策记录
- v2.2.0: 稳定 public component for Spring Cloud AI coding workflows

---

## Security model / 安全模型

Memory Center is local-first and read-only by default. Query/context/impact/contract tools do not modify business source code. Write tools are limited to Memory Center artifacts such as task memory, wiki, and generated skills. See `docs/MCP_GUIDE.md`.

记忆中心默认本地优先、只读优先。查询、上下文、影响分析、契约查看不会修改业务源码；写入类工具只写记忆、Wiki、Skill 等 Memory Center 产物。详见 `docs/MCP_GUIDE.md`。

## License / 许可证

Apache-2.0
