# Memory Center 当前系统架构 / Current System Architecture

> 本文基于当前全量代码实现整理，作为一份独立的系统架构说明。它面向外部评审者、集成方和维护者，说明 Memory Center 的设计目标、核心能力、运行模型、模块边界和数据安全边界。
>
> This is a standalone architecture document for the current implementation. It is written for external reviewers, integrators, and maintainers, and describes Memory Center's goals, core capabilities, runtime model, module boundaries, and data-safety boundaries.

---

## 目录 / Table of Contents

1. [系统定位 / System Role](#1-系统定位--system-role)
2. [整体架构 / Overall Architecture](#2-整体架构--overall-architecture)
3. [顶层数据流 / Top-Level Flow](#3-顶层数据流--top-level-flow)
4. [Workspace Model / 工作区模型](#4-workspace-model--工作区模型)
5. [Indexing Layer / 索引层](#5-indexing-layer--索引层)
6. [Storage Layer / 存储层](#6-storage-layer--存储层)
7. [Retrieval and Query Layer / 检索与查询层](#7-retrieval-and-query-layer--检索与查询层)
8. [Orchestrator Layer / 编排层](#8-orchestrator-layer--编排层)
9. [MCP, CLI, HTTP Adapters / 入口适配层](#9-mcp-cli-http-adapters--入口适配层)
10. [Task Memory and Artifacts / 任务记忆与工件](#10-task-memory-and-artifacts--任务记忆与工件)
11. [Freshness, Hooks, and Host Integration / 新鲜度、Hook 与宿主集成](#11-freshness-hooks-and-host-integration--新鲜度hook-与宿主集成)
12. [Error Model and Dispatch Seams / 错误模型与分发边界](#12-error-model-and-dispatch-seams--错误模型与分发边界)
13. [Evaluation and Observability / 评测与可观测性](#13-evaluation-and-observability--评测与可观测性)
14. [Security and Privacy Boundaries / 安全与隐私边界](#14-security-and-privacy-boundaries--安全与隐私边界)

---

## 1. 系统定位 / System Role

Memory Center 是一个面向 AI 编程助手的本地优先项目记忆与知识图谱系统。它把多仓、多服务、多语言工程里的代码结构、服务关系、配置契约、消息链路、历史任务和团队规则统一沉淀到 `.memory-center/` 工作区，并通过 CLI、MCP、HTTP 和本地 Workbench 暴露给 Codex、Claude Code、Cursor、Copilot、Gemini 等宿主。

Memory Center is a local-first project memory and knowledge graph system for AI coding agents. It turns a multi-repository, multi-service, multi-language workspace into a queryable and traceable local context center.

### 1.1 为什么需要它 / Why It Exists

大型后端系统里的 AI Agent 通常会遇到四类问题：

- **上下文不可持续**：每个会话重新读代码，无法稳定继承历史任务、规则和验证结论。
- **跨服务影响不可见**：Controller、Feign、MQ、配置、DTO、数据资源之间的影响链依赖人工搜索。
- **检索不可解释**：纯关键词或语义检索能召回片段，但很难解释“为什么这些文件有关”。
- **协作不可追溯**：多个模型或多个会话之间缺少统一的任务空间、交接包和证据链。

Memory Center 的核心设计是把这些上下文前置为本地可重建的工程资产：索引层提取事实，图谱层表达关系，检索层组合证据，编排层把复杂能力收敛为少量 agent 可调用的任务级接口。

### 1.2 面向读者 / Intended Readers

本文面向三类读者：

| 读者 | 关注点 | 本文回答的问题 |
|---|---|---|
| 外部评审者 / Reviewer | 系统边界、隐私、安全、可解释性 | Memory Center 处理什么数据、写到哪里、如何避免黑盒检索 |
| 集成方 / Integrator | CLI、MCP、HTTP、Hook 接入 | 如何把它接到不同 AI 编程宿主和本地工作流 |
| 维护者 / Maintainer | 模块边界、索引链路、存储职责 | 新能力应该放在哪一层，哪些路径是事实源 |

### 1.3 核心能力域 / Capability Domains

| 能力域 | 说明 | 关键模块 |
|---|---|---|
| Workspace Intelligence | 自动识别服务、语言、项目结构和 workspace shape 风险 | `core/workspace/config.py`, `core/workspace/doctor.py`, `core/workspace/shape.py`, `core/workspace/kinds.py` |
| Code and Service Indexing | 提取文件、Java/Spring、Feign、MQ、配置、多语言结构化符号 | `core/indexing/reindex.py`, `core/indexing/*` |
| Knowledge Graph | 将服务、文件、类、方法、Endpoint、Topic、Config、DataResource 转为节点和边 | `core/storage/runtime.py`, `core/knowledge/ontology.py` |
| Hybrid Retrieval | 融合 exact graph、neighbors、FTS、BM25、semantic、可选 vector | `core/retrieval/*` |
| Method Walkthrough | 对 `Class#method` 做本地调用、Feign 续链、服务端 Controller/Impl 展开 | `core/walkthrough/*` |
| Task Memory | 保存 session、case、task space、handoff、write receipt 和 L3 记忆块 | `core/orchestrator/session.py`, `write.py`, `sync.py` |
| Interaction History | 记录脱敏的 MCP/宿主交互、thread-session 绑定和效果聚合 | `core/audit/interactions.py`, `mcp/runtime.py`, `hooks/runner.py` |
| Agent Facade | 将复杂能力收敛为 `mc_start`、`mc_lookup`、`mc_analyze` 等任务级接口 | `mcp/server.py`, `core/orchestrator/*` |
| Quality and Governance | freshness、audit、benchmark、parser precision、runtime diagnostics | `core/freshness/*`, `core/benchmark/*`, `core/audit/*` |

### 1.4 部署与运行形态 / Runtime Shape

Memory Center 不要求中心化服务。默认形态是每个 workspace 自带一个 `.memory-center/` 本地目录：

- **Local CLI**：开发者或脚本直接运行 `memory-center`。
- **MCP Server**：AI 编程助手通过 `memory-center-mcp` 调用任务级 tools。
- **HTTP Bridge**：本地 `memory-center-http` 提供 JSON API 和 Workbench。
- **Host Hooks**：在 SessionStart、PreToolUse、Stop 等生命周期节点自动触发上下文、影响分析和收尾。

这种部署形态的关键收益是：工程事实不需要上传到远程平台，索引和记忆可以随 workspace 一起复制、清理、重建，也可以被人类直接审查。

核心原则：

- **Local-first / 本地优先**：业务源码、索引、图谱、记忆和工件都落在本地 workspace。
- **Graph-first / 图谱优先**：跨服务影响、调用链、契约、配置和消息关系先进入 SQLite graph，再由检索和推理层消费。
- **Facade-first / 面向 Agent 暴露任务级接口**：MCP 只暴露少量 task-level tools，复杂实现留在 core。
- **Evidence-first / 证据优先**：回答、handoff、case、ref、audit 都尽量保留来源和可追溯证据。
- **Stable-entry / 稳定入口**：MCP tool schema、CLI 命令和 HTTP 路径保持稳定；内部读模型只保留当前架构，不保留历史数据回退。

- **Ontology state / 本体状态**：查询通过 `knowledge_state` 明确当前索引范围、未发现、过期和未知状态；Assertion sidecar 保存来源、有效期、事件时间与观测时间，治理 Action 采用有界读模型而不进入图查询热路径。
- **Delivery workflow / 需求交付工作流**：`core/tasks/delivery.py` 在任务空间内维护需求来源/范围、子任务、验收、GateResult、验证回执和派生交付矩阵。执行器只消费 workspace policy 的预注册 argv profile，记录受限输出与 hash；任意模型或需求文本都不能转化为可执行 shell。已验证交付的 Skill 使用 `candidate -> canary -> published|rolled_back` 生命周期，并在同一 registry 中维护语言、前置/停止条件、输入输出契约和 replay 策略；每条观测和自动脱敏 replay 绑定 `contract_sha256`，发布只统计当前契约且达到其 `minimum_verified_passed` 门槛、没有失败。已发布契约不可原地修改。registry、观测事件、replay、失败聚类和多轨迹归纳均为有界本地工件，其中后两者只在显式离线维护中运行。
- **Collaboration assets / 协作资产**：`core/knowledge/assets.py` 将任务、已发布 Skill、Wiki 文档和 CodeGraph 统一为本地资产。资产带 owner、版本、状态、可见性与 Agent/角色绑定；既有资产只允许 owner 更新，团队共享须由 owner 提交、另一维护者审批。registry 用原子替换与有效备份恢复，双副本损坏时拒绝写入；活跃 CodeGraph 使用稳定系统主体，避免多 Agent 同步冲突。metadata 限制 16 KiB，status/loadout 与 context pack 都有总预算和截断标记，避免把资产正文和全局记忆压入热路径。
- **Resilient analysis / 可降级分析**：`mc_analyze` 把图谱影响、计划、规则、契约和验证清单分成可诊断阶段。影响图已成功时，后续辅助阶段故障只会产生 `partial` 结果和安全诊断，不会覆盖已获得的图谱证据；入口错误通过 trace ID 与本地 MCP 审计关联。

### 1.4.1 架构不可变量 / Architectural Invariants

以下规则是未来重构的判定标准，而不是可选建议：

- 默认查询不得扫描全图，也不得隐式触发全量重建；高成本分析必须显式请求或进入后台 job。
- 节点邻居查询采用有界分层 BFS：每层仅访问当前 frontier，并在扩展前去重；关系边遍历与节点查询分别通过 `traverse_edges`、`neighbors` 表达，避免递归路径物化和语义混淆。
- `VERIFIED` 结论必须关联验证命令结果、人工确认或可追溯运行结果；置信度不能替代验证。
- 运行时事实统一写入 SQLite；大体积、可重建的结构化索引不再写出 JSON 副本，JSON/JSONL 仅保留小型控制面和人工工件，且不能成为查询回退或覆盖 SQLite 的新事实。
- CLI、MCP、HTTP 的异常必须收敛为结构化诊断和可行动建议，禁止无界重试。
- 文档、审计和导出默认不包含私有源码、原始对话正文或工具载荷。

当前版本的系统入口：

| 入口 | 命令 / 路径 | 代码位置 | 职责 |
|---|---|---|---|
| CLI | `memory-center` | `memory_center/cli/main.py` | 初始化、索引、查询、影响分析、任务工作流、评测、hook 生成 |
| MCP | `memory-center-mcp` | `memory_center/mcp/server.py` | 12 个 task-level tools、resources、prompts、`mc_admin` |
| HTTP | `memory-center-http` | `memory_center/http/server.py` | JSON API、本地 HTML UI、Vue Workbench `/app` |
| Hooks | generated host hooks | `memory_center/hooks/` | SessionStart、PreToolUse、Stop 等宿主生命周期集成 |

### 1.5 Core 领域布局 / Core Domain Layout

`core/` 根目录只保留 `__init__.py`，不承载实现或兼容转发。共享模型、错误、schema、分发和纯工具位于 `foundation/`；workspace 配置、健康检查、工作区形态、服务类型和后台 job 位于 `workspace/`；workspace、图和 memory SQLite 存储位于 `storage/`；规则和宿主协议位于 `governance/`；诊断、指标和操作事件位于 `observability/`；质量/完成度位于 `assessment/`；本体与 Wiki 位于 `knowledge/`。索引、检索、契约、任务、编排和展示各自只使用自己的领域包。

The `core/` root contains only `__init__.py`; it has no implementation or compatibility shims. Shared models, errors, schemas, dispatch, and pure utilities live in `foundation/`; workspace configuration, health checks, shape, service kinds, and jobs live in `workspace/`; workspace, graph, and memory SQLite storage live in `storage/`; rules and host protocol live in `governance/`; diagnostics, metrics, and operation events live in `observability/`; quality/completion live in `assessment/`; ontology and wiki generation live in `knowledge/`. Each domain has one canonical import path.

核心依赖方向由 `docs/adr/0001-core-dependency-direction.md` 约束：底层事实与存储不依赖编排或入口；`application/` 负责组合跨领域任务用例；编排层只负责核心任务组合；CLI、MCP、HTTP、hooks 均为入口适配层。

---

## 2. 整体架构 / Overall Architecture

Memory Center 当前是一个本地文件系统 + SQLite 派生索引驱动的多入口服务。核心代码分为六层：

```text
┌─────────────────────────────────────────────────────────────┐
│ Host Agents / 用户入口                                      │
│ CLI: memory-center   MCP: memory-center-mcp   HTTP: /app    │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Adapter Layer / 入口适配层                                   │
│ cli/main.py + commands/*   mcp/server.py + runtime/insights   │
│ 只负责参数绑定、展示、错误边界和公开 schema 兼容              │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Application Layer / 应用层                                   │
│ task_start, lookup, analysis, tasks, admin, presentation     │
│ 跨领域用例、局部刷新、结果装配与入口共享编排                  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Core Orchestrator / 核心任务编排                             │
│ start, lookup, analyze, sync, resume, handoff, close, eval   │
│ 聚合索引、图谱、规则、记忆、freshness 和上下文包              │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Core Engines / 核心引擎层                                    │
│ indexer, graph, retrieval, walkthrough, reasoning, audit     │
│ 负责确定性索引、知识图谱、检索融合、链路展开和质量评测        │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Local Stores / 本地存储层                                    │
│ workspace.yaml, index/*.json, graph.db, artifacts             │
│ graph.db 是运行时事实库；源码 / YAML / Markdown 是外部输入与工件 │
└─────────────────────────────────────────────────────────────┘
```

这五层的职责边界是：

- Adapter 不复制 core 决策；MCP、CLI、HTTP 对同一能力应优先复用 `application/` 用例。
- Application 负责入口间共享的跨领域用例、局部刷新和返回装配；它可依赖 core，但 core 不得反向依赖 application。
- Orchestrator 负责核心任务语义与稳定的核心调用和返回结构。
- Core engines 负责可验证的工程事实提取、图谱查询、检索融合和推理降级。
- Stores 分清运行时事实与导出物：`graph.db` 是唯一运行时事实库；源码、`workspace.yaml`、rules 和 artifacts 是外部输入或人工工件；`index/*.json`、JSONL 是可重建导出物。
- Hooks 属于宿主集成层，只在生命周期节点触发已有 facade，不拥有业务状态。

### 2.1 代码目录视图 / Codebase Layout

当前仓库围绕 `memory_center/` Python package 展开，前端 Workbench 和测试分别独立放置：

```text
memory_center/
├── application/            # 入口共享用例、局部刷新和输出装配
├── cli/                    # memory-center 命令行入口
│   └── commands/           # registry/group/workspace/artifact 等子命令注册
├── core/                   # 索引、图谱、检索、记忆、评测、编排等核心逻辑
│   ├── indexing/           # tree-sitter / regex / 多语言结构化解析
│   ├── retrieval/          # hybrid retrieval, BM25, policy
│   ├── walkthrough/        # method walkthrough 全链路展开
│   ├── orchestrator/       # task-level 业务编排 facade
│   ├── storage/            # RuntimeStore、SQLite 连接、PRAGMA 与 vector
│   ├── freshness/          # 索引新鲜度与 workspace shape 状态
│   ├── benchmark/          # golden、token、parser、Java call resolution 评测
│   ├── audit/              # completion/runtime audit
│   ├── context/            # context pack
│   ├── domain/             # 业务域与业务流抽取
│   ├── onboarding/         # persona-based onboarding
│   └── reasoning/          # evidence-bounded reasoning pipeline
├── mcp/                    # memory-center-mcp facade tools/resources/prompts
│   ├── runtime.py           # workspace 解析、启动诊断、统一 MCP 错误边界
│   └── insights.py          # resources、prompts、context/onboard/domain/freshness tools
├── http/                   # HTTP bridge, route registry, local UI serving
├── hooks/                  # Codex / Claude Code / Cursor 等宿主 hook 生成
└── templates/              # 内置模板与生成内容骨架

web/
└── src/                    # Vue Workbench 页面、路由、API client 和共享组件

tests/                      # 单元、集成、回归、性能和 public surface 测试
examples/                   # 可提交的脱敏示例 workspace / cases
docs/                       # 面向用户和维护者的说明文档
```

从目录职责看，`core/` 是系统内核，`application/` 是入口共享的用例层，`mcp/`、`cli/`、`http/` 是三种入口适配器，`web/` 是本地可视化工作台。测试覆盖按 public surface 和核心引擎组织，避免把私有 workspace 产物提交进仓库。

### 2.2 架构分层契约 / Layer Contracts

| 层 | 输入 | 输出 | 稳定性要求 |
|---|---|---|---|
| Adapter | CLI args、MCP tool params、HTTP query/body | 面向用户或模型的结构化响应 | 公开参数和返回字段默认兼容 |
| Application | 已标准化的入口请求、workspace 路径、任务参数 | 跨领域用例结果、刷新/路由诊断 | 可依赖 core，不得被 core 反向依赖 |
| Orchestrator | workspace path、intent、target、budget、view | task-level response、diagnostics、refs | 统一语义，不按入口复制逻辑 |
| Core Engines | workspace config、index、graph、memory records | facts、relations、ranked evidence、reports | 失败可降级，但必须暴露原因 |
| Store | YAML、JSON、JSONL、Markdown、SQLite | SQLite 运行时事实库与可审查导出 | 路径职责清晰，写入可追溯 |
| Host Integration | hook event、model/session context | start/analyze/close/handoff actions | 不拥有业务状态，不绕过 facade |

---

## 3. 顶层数据流 / Top-Level Flow

Memory Center 的数据流分为四个阶段：索引期建立工程事实，任务期提供上下文和影响分析，写入期沉淀任务证据，恢复/交接期把历史上下文重新组织给模型。

### 图感知变更审查 / Graph-Aware Change Review

统一 Change Review Plan 将变更检测、新鲜度、定向刷新、影响传播、测试与契约风险、验证 Action 收敛在同一个应用服务。刷新范围硬限制为最多 12 个可证明相关文件；失败时保留旧 generation 并显式报告，不允许回退为全量 reindex。

多仓库变更检测按仓库执行一次 `git diff --name-status -z`，最多 8 路并发，并在内存中同时解析修改、删除和重命名；不再为“变更”和“删除”重复启动 Git 进程。随后用 `nodes.file_path` 索引批量定位图节点，禁止逐文件模糊搜索大图。

影响传播在 SQLite 中按 frontier 分层读取，只为每个端点保留当前最佳路径。路径分数为：

```text
impact = relation_weight * edge_confidence * evidence_factor * freshness * depth_decay
```

固定关系权重和确定性排序保证同一 generation 可复现；节点、边、深度和耗时预算阻止环路枚举和全图 Python 物化。结果返回最佳路径与分数构成，供结论卡解释，而非只返回无法审计的邻居集合。

交互层默认 `minimal`，证据不足时才升级 `standard` / `deep`。源码签名、请求参数和 generation 构成调用指纹；短期缓存抑制 Agent 重复调用，调用次数、输出和总耗时预算提供明确停止条件。

架构健康分析与 Git co-change 评测属于显式离线路径。前者读取有界项目投影，使用固定种子 Leiden 或确定性加权标签传播，并以有界 Brandes 估算桥接点；后者使用同一提交中除种子外的文件作为独立真值。两者都不进入 lookup/impact 热路径，也不复制源码正文或私有路径到长期报告。

```text
workspace.yaml
  + source repositories
  + rules / glossary / templates
       │
       ▼
  reindex_workspace()
       │
       ├─> index/*.json
       ├─> graph/graph.db
       ├─> semantic-node-index.json
       ├─> SQLite BM25 inverted index
       └─> optional VectorIndex

Agent task
       │
       ├─> mc_start / workspace_sniff
       ├─> mc_lookup / mc_context_pack / mc_analyze
       ├─> mc_sync / artifacts / task space
       ├─> mc_resume / mc_handoff
       └─> mc_close / case / feedback learning
```

### 3.1 索引期 / Index-Time Flow

索引期的目标是把源码和配置转换成可解释、可重建的工程事实：

| 输入 | 处理 | 输出 |
|---|---|---|
| `workspace.yaml` | 解析 workspace root、services、service kind、language override | 标准化 `WorkspaceConfig` |
| 服务源码 | 文件扫描、Java/Spring 解析、多语言结构化解析 | `file-index.json`, `java-symbol-index.json` |
| Spring annotations | Controller、Feign、MQ、配置、数据资源提取 | `api-index.json`, `feign-index.json`, `mq-index.json`, `config-index.json` |
| 符号与关系 | graph node/edge 构建、call resolution、partial rebuild | `graph/graph.db`, `graph-summary.json` |
| 文本与节点摘要 | sparse semantic、BM25、可选 dense vector | `semantic-node-index.json`, inverted index, vector index |

索引产物由源码、规则和 workspace 配置重建；运行时查询统一从 SQLite 事实库读取，文件产物用于原子发布、审查和导出，不参与读取兜底。

### 3.1.1 索引控制面与分片路由 / Index Control Plane and Shard Routing

每次 reindex 会生成 staging generation，并在图、关键词/语义检索和索引摘要写入完成后原子发布为 active generation。SQLite 是唯一查询读模型；JSON/JSONL 仅作导出。控制面维护 active/previous generation、构建状态和回滚证据。`shard-manifest.json` 不复制完整索引，而是按服务统计 Service Shard，并汇总 Contract Shard（API/Feign/MQ/config）与 Topology Shard 的路由元数据。

Every reindex builds a staging generation and publishes it as the active generation only after graph, retrieval/semantic, and summary artifacts complete. Existing JSON/SQLite artifacts remain compatible read models. The control plane owns consistency boundaries, previous generation, lifecycle state, and recovery evidence. `shard-manifest.json` is routing metadata rather than a duplicated index payload.

当前 generation 目录还保存真实的 `services/<project>.json`、`services/<project>.graph.db`、`contracts.json` 与 `topology.json`。服务分片是完整索引的不可变快照；带明确 project 范围的 code/hybrid 查询优先使用服务分片，跨服务路由仍从 topology/contract 分片出发并可回退到全局读模型。watcher 将失效计划提交为可合并的后台 partial reindex；每次成功发布后控制面自动保留当前与上一代并回收更早代际，既支持一次回滚，也避免历史快照无限累积。

局部 reindex 使用 copy-on-write：它从前一 generation 继承未受影响的服务分片，只重建失效计划命中的服务分片，再发布新的 generation。这样增量更新不需要复制或解析全部服务，同时保持 generation 级一致性。

4.3.84 将该语义落实为按 manifest 的物理发布：继承阶段只硬链接未受影响服务的两个产物，不遍历复制完整 generation；受影响项目通过 SQLite `ATTACH + INSERT SELECT` 从全局读模型流式导出。临时分片关闭可恢复写入所不需要的 journal，先装载节点和内部边，再统一创建二级索引与 FTS。局部多项目最多 3 个 worker 并行，全量构建保持串行。整个过程不在 Python 中保存项目级节点/边列表，峰值内存由 SQLite 页缓存约束。

The generation directory also contains physical `services/<project>.json`, `services/<project>.graph.db`, `contracts.json`, and `topology.json` artifacts. Service shards are immutable snapshots; project-scoped code/hybrid queries prefer them, while cross-service routing starts from topology/contracts and can fall back to the compatible global read model. Watcher invalidation plans submit coalesced background partial reindex work, and the control plane supports rollback plus explicit generation GC.

Partial reindex uses copy-on-write: unchanged service shards are inherited from the preceding generation, only invalidated services are rebuilt, and the new generation is then published atomically.

Since 4.3.84, physical publication follows the manifest directly: unchanged service artifacts are hard-linked, while affected graphs stream from the global read model through SQLite `ATTACH + INSERT SELECT`. Secondary indexes and FTS are built after data loading. Partial multi-project builds use at most three workers; full builds remain sequential, and no project-sized Python node/edge list is created.

### 3.1.2 跨服务分片编排 / Cross-Service Shard Orchestration

未指定 project 的请求由路由层决定全局或服务范围。已解析 service 的请求只在对应 SQLite 图分片取证；分片未发布时明确返回 `NOT_INDEXED` 并要求局部 refresh/reindex，不回退全局索引。响应携带 generation、路由依据、查询分片和证据来源。

Requests without an explicit project are routed by the query planner. Scoped requests read only the selected SQLite graph shards; unavailable shards return `NOT_INDEXED` and schedule/require a bounded refresh rather than silently expanding to a global search.

### 3.1.3 跨分片融合与可信结论 / Cross-Shard Fusion and Trusted Conclusions

融合层在不改变既有查询字段的前提下，统一主检索与服务分片命中，按 `project/type/name/file` 去重并合并来源。它校验 routed generation 是否等于 active generation；不一致时把结论降为派生证据并要求重试。对于选中的服务，融合层基于 Contract/Topology Shard 生成 Feign 目标解析、MQ producer/consumer 覆盖和 DTO 审核提示。输出使用事实/推断/派生强度、置信度、契约状态和下一步动作，避免把“未命中”误作“没有影响”。

The fusion layer preserves existing query fields while deduplicating primary and service-shard hits by `project/type/name/file` and merging sources. It verifies the routed generation equals the active generation; mismatches downgrade conclusions to derived evidence and request a retry. Contract/Topology shards produce Feign target resolution, MQ producer/consumer coverage, and DTO review hints. Output includes fact/inferred/derived strength, confidence, contract status, and next actions.

### 3.1.4 契约语义快照与变更门禁 / Contract Snapshots and Change Gates

每次 reindex 会标准化 API、Feign 方法、MQ endpoint 和 DTO 字段类型，并与前一快照生成差异。删除 API/Feign/MQ 契约、删除 DTO 字段或修改字段类型被判定为 high severity breaking change；新增 DTO 字段为中等风险，要求检查默认值和消费者兼容性。静态校验同时验证 Feign 的 target service、HTTP 方法和路径是否存在服务端 API，以及 MQ topic 是否同时具有 producer/consumer。full 分析、任务证据、pre-edit guard、显式 contract gate 和 release gate 使用同一报告，避免不同入口给出相互矛盾的结论。

Every reindex normalizes APIs, Feign methods, MQ endpoints, and DTO field types, then diffs them against the previous snapshot. Removed API/Feign/MQ contracts, removed DTO fields, and DTO type changes are high-severity breaking changes; new DTO fields are medium risk and require default/consumer review. Static validation also checks Feign target service plus HTTP method/path and MQ producer/consumer coverage. Full analysis, task evidence, pre-edit guard, explicit contract gate, and release gate consume the same report.

### 3.1.5 脱敏运行时契约闭环 / Redacted Runtime Contract Loop

运行时层只接受元数据样本，不保存 payload、请求体、消息内容或 header。API 样本包含服务、HTTP 方法/路径、DTO 名称、字段名集合和成功/失败计数；MQ 样本包含服务、topic、producer/consumer 方向和计数。校验器将样本与当前 endpoint/topic、静态 breaking diff 对照，识别已影响流量的风险。迁移记录采用 `planned`、`dual_read`、`dual_write`、`consumer_migrated`、`completed` 状态；处于批准双读/双写阶段的活跃风险会降级为 attention，但仍会进入发布报告和任务证据。

The runtime layer accepts metadata samples only and never stores payloads, request bodies, message content, or headers. API samples include service, HTTP method/path, DTO name, field names, and counters; MQ samples include service, topic, direction, and counters. The verifier compares samples with active endpoints/topics and static breaking diffs to distinguish active traffic impact. Approved migration states can downgrade controlled dual-read/dual-write risk to attention while retaining it in release reports and task evidence.

### 3.2 任务期 / Task-Time Flow

任务期面向 AI Agent 暴露少量稳定动作：

| Agent 需求 | 推荐入口 | 系统行为 |
|---|---|---|
| 开始理解任务 | `mc_start` | 嗅探 workspace、当前 intent、freshness、规则和推荐工作流 |
| 查询符号或背景 | `mc_lookup(mode="auto")` | 根据 intent 自动选择 graph、BM25、semantic、walkthrough 等检索路径 |
| 修改前看影响面 | `mc_analyze` | 汇总 contracts、跨服务关系、规则风险、验证建议 |
| 需要紧凑上下文 | `mc_context_pack` | 生成带证据、风险和 checklist 的上下文包 |
| 理解业务域 | `mc_domain` | 从图谱提取业务域、业务流和影响关系 |
| 新人导览 | `mc_onboard` | 按 developer / architect / product / tester persona 生成导览 |

查询期的热刷新不是一次全量重建：`RefreshCoordinator` 以 workspace 锁协调并发 Agent，先对命中/dirty 文件做内容哈希和 generation 校验，再以单 SQLite 事务替换子图及 generation 记录。它只扩展一跳既有依赖边，避免正常链路分析变成全库扫描。深度分析可提交为本地后台 job，并通过任务状态读取或取消；任务空间的大证据则以 SHA-256 内容块保存，摘要仅持有引用。

Freshness refresh is not a full rebuild: `RefreshCoordinator` coordinates concurrent local Agents, validates content hash and generation for matched/dirty files, and replaces the subgraph plus generation record in one SQLite transaction. Lookup only schedules this work and reads the current published generation; it never hashes files, traverses graphs, or reindexes in the request thread. It expands only one existing dependency hop. Deep analysis can run as a local background job with PID/heartbeat state and cooperative cancellation; large task evidence is stored as SHA-256 addressed chunks while summaries retain only references.

公共入口会先经 `QueryPlanner` 生成 fast/standard/deep 的有限预算计划，并记录 generation、分片范围、耗时和超时结果。需要更完整的失效传播时，变更文件会按 DTO、Feign、MQ、HTTP、配置或普通代码分类，产出有界依赖计划；长耗时 reindex 可进入持久状态的本地 job。任务空间还保存任务级 ADR（decision、rationale、evidence refs），证据回收默认为 dry-run。

Public facades first use `QueryPlanner` to apply fast/standard/deep budgets and record generation, shard scope, latency, and timeout outcomes. Changed files are classified as DTO, Feign, MQ, HTTP, configuration, or code to produce a bounded invalidation plan; long reindex work can run as a local persistent-status job. Task spaces also retain task-scoped ADRs, while evidence GC is dry-run by default.

### 3.3 写入与沉淀 / Write and Memory Flow

Memory Center 不把模型临时输出直接当成长期知识。写入链路会区分 session event、task artifact、case atom 和 workspace profile：

- Session event 记录原始过程证据，较大 payload 通过 refs offload。
- Task artifact 保存当前任务的 context、requirement、design、plan、test-plan、change-log、current-summary。
- Case atom 只记录经过验证、可复用的经验。
- L3 memory block 保存跨任务稳定规则和工作区画像。

核心任务工件默认 append-only 或 guarded append，避免模型覆盖已有协作上下文。

### 3.4 恢复与交接 / Resume and Handoff Flow

当任务跨会话、跨模型或跨 Agent 继续执行时，系统通过 `mc_resume` 和 `mc_handoff` 重新组织上下文：

- 从 recent sessions、task space、case、refs、graph facts 中抽取证据。
- 根据目标模型和 token budget 生成 compact 或 full 输出。
- 保留 next actions、risks、read targets、validation status 和已知约束。
- 对无法内联的大对象返回 ref，按需 drill-down。

任务空间恢复现在包含一条显式门禁链路：`task_space_health -> task_space_repair_plan -> task_space_repair_execute -> workspace_task_resume_check`。健康检查负责发现缺失/过期 `current-summary`、空 next actions、未解决 write receipts、相似任务空间和过大工件；修复计划只描述可修复项；执行修复默认 dry-run，只有显式 apply/force 后才做保守写入；恢复门禁把 resume packet、健康度、修复建议、下一步动作、未解决事项和证据合并为 `ready`、`needs_repair` 或 `blocked`。

这条链路的写入边界必须保守：可以补齐缺失 context/plan 模板，也可以在有明确 intent 时刷新 `current-summary`；不能伪造 write receipt、自动归档歧义任务空间、覆盖已有工件或把高风险修复当成自动操作。

几个关键边界：

- `workspace.yaml`、rules YAML、业务源码和 Markdown artifacts 是可读事实源。
- `.memory-center/index/*.json` 是 SQLite 索引状态的可审查导出。
- `.memory-center/graph/graph.db` 是派生知识图谱、FTS、BM25、向量元数据与 HNSW 映射等图向能力的主读后端；相邻的 `.hnsw` 文件仅保存可重建的 ANN 图。
- `.memory-center/graph/graph.db` 同时保存图、索引状态、记忆记录、断言和检索结构，是唯一运行时事实库。
- `.memory-center/artifacts/**/*.md` 是任务空间、计划、设计、变更记录和 L3 记忆块的人类可读事实源。

---

## 4. Workspace Model / 工作区模型

每个 Memory Center workspace 以 `.memory-center/workspace.yaml` 为根配置。当前 `WorkspaceConfig` 和 `ServiceConfig` 支持：

- `root`：workspace 根目录；相对路径按 `workspace.yaml` 所在目录解析。
- `services[]`：服务列表。
- `services[].path`：支持相对路径和绝对路径。
- `services[].type`：通过 `service_kinds.py` 映射到语言、构建标记和 Spring-aware 行为。
- `services[].language`：可覆盖 service kind 推断语言。
- `services[].service_name`、`port`、`tags`：用于 Spring Cloud、契约和规则匹配。

初始化路径：

- `memory-center init` 默认扫描 immediate child directories，识别 Spring、generic JVM、Python、Node/TypeScript、Go、Rust 等项目。
- 已存在的 `workspace.yaml` 不会被自动覆盖。

工作区结构：

```text
.memory-center/
├── workspace.yaml
├── index/                  # deterministic JSON indexes
├── graph/graph.db          # graph, FTS, BM25, vector metadata and ANN labels
├── graph/graph.hnsw        # optional, rebuildable persistent HNSW index
├── memory/                 # JSONL exports and refs
├── artifacts/              # shared/task Markdown artifacts and L3 blocks
├── rules/                  # matching/eval/handoff/write-policy rules
├── instructions/           # generated agent instructions
├── hooks.yaml              # host hook config
├── store.lock              # file-level write lock
└── reindex.lock            # full reindex writer lock
```

Workspace shape analysis lives in `memory_center/core/workspace/shape.py`。它会检测 duplicate roots、nested roots，并给出收窄 service path 的建议；`IndexFreshnessService.banner()` 会把 workspace shape warnings 合并进 freshness banner。

---

## 5. Indexing Layer / 索引层

索引主入口是 `memory_center/core/indexing/reindex.py::reindex_workspace()`。它支持全量和按 project/path 的部分重建，默认并行解析 Java 文件。

局部刷新使用精确 scope walker：文件直接读取，目录只遍历该子树，无法映射到服务根的 scope 保守返回空匹配而不扫描其他服务；Java 与多语言结构 pass 共享该边界。大型 runtime index 在单次 Store 生命周期内按 SQLite `updated_at` 缓存，跨 Store 更新会立即失效。刷新性能记录只保存 generation、scope 数量、分阶段耗时和预算状态，不保存文件路径或源码。

完整 reindex 生命周期由 `reindex.lock` 串行化；`index/reindex-state.json` 仅记录运行状态、时间、范围计数和脱敏失败原因，供 CLI、HTTP status 与 Workbench Health 判断是否等待或重试。它不记录源码路径或 payload。

### 5.1 确定性索引产物

`reindex_workspace()` 生成并写入：

- `file-index.json`：服务、逻辑路径、绝对路径、后缀。
- `java-symbol-index.json`：Java package、class/interface/method/field/import、方法签名、注解、常量、调用证据、配置使用、数据资源。
- `api-index.json`：Spring MVC Controller endpoint。
- `feign-index.json`：OpenFeign client、target service、method mapping。
- `mq-index.json`：Kafka / RocketMQ consumer 和 producer。
- `config-index.json`：`application.yml` / `bootstrap.yml` 等配置键。
- `service-topology.json`：服务、Feign、MQ、配置拓扑摘要。
- `graph-summary.json`：graph 计数、parser diagnostics、parser precision。
- `semantic-node-index.json`：稀疏语义索引和可选 dense vectors。

写入通过 `WorkspaceStore.write_json()` 完成：在 SQLite 中提交运行时状态，并同步生成 `index/*.json` 审查导出。

### 5.2 Java / Spring 深度解析

Java 解析是 Spring-aware 主路径：

- 优先使用 `TreeSitterJavaParser`，保留 regex fallback，并返回 fallback reason / disagreement diagnostics。
- `RegexJavaParser` 仍是稳定兼容路径，提取 Spring 注解、方法、字段、imports、bean injection、method calls、DTO field usage、config usage、Mongo / Elasticsearch resource hints。
- `JavaCallResolver` 构建全工程 `JavaClassIndex`，把 `method_calls` 解析为带置信度的 `CALLS_METHOD` 边。
- Feign 与 API 匹配使用索引 lookup，避免大仓内线性扫描。

当前 Java call resolution levels：

| level | confidence | 含义 |
|---|---:|---|
| `same_class` | 1.0 | `this.foo()`、`super.foo()`、裸调用或 owner class 内方法 |
| `same_package` | 0.9 | receiver type 在同 package 内匹配 |
| `import` / `static_import` | 0.85 | 显式 import 或 static import 匹配 |
| `wildcard_import` / `static_wildcard_import` | 0.6 | wildcard import 匹配 |
| `unresolved` | 0.3 | 保留调用证据，但不绑定到随机同名方法 |

默认 caller/callee 查询优先使用高置信边；高置信为空但低置信存在时会标注 fallback。

4.3.78 起，Java 类型事实同时保存 `type_kind`（class、interface、enum、record、annotation）和父类型。未解析调用不再使用一个笼统原因：编译器生成的 enum 方法标记为 `generated_enum_method_out_of_scope`，链式调用返回外部类型标记为 `chain_return_type_not_indexed`，本地接口间接继承外部框架接口时标记为 `inherited_method_out_of_scope`。这些类别会从本地 resolver 修复 campaign 中排除，避免为了降低未解析率而伪造调用边。

Git co-change v2 不再对文件邻居执行无序 `DISTINCT LIMIT`。它最多读取 1,600 条相邻边，使用关系权重与边置信度聚合，再按最强证据、证据数量、总分和路径确定性排序；默认只返回 8 个候选。该路径保持有界，不在 17GB 级图数据库上执行全图 SQL 聚合。

4.3.80 的 co-change v3 将评测与应用拆开：评测按每个 Git 仓库从旧到新推进，提交事实只有在该提交完成预测后才进入历史；当前图快照仅用于诊断。通过 past-only popularity 基线后，可显式写入 `cochange_priors` 稀疏表，表中只有路径哈希、支持度和分数。查询时先完成原有有界图候选，再对命中的哈希先验增加有上限的排序增益，因此不会用历史共变绕过代码证据。

4.3.81 将 Java 变量类型证据分为两层：调用与 DTO 字段访问保存所在重载方法体的词法作用域类型，`method_variable_types` 仅作为兼容聚合视图。不同重载中同名变量类型冲突时，聚合视图删除该项而不是采用最后写入值；resolver 优先读取调用自身的确定证据。该设计不增加图查询热路径开销，也不引入编译器级全仓分析。

4.3.82 在方法体作用域内增加第二层 Lambda 词法区间。显式参数类型直接形成证据；标准 `java.util.function` 目标类型只映射其输入泛型位置。解析器通过括号深度确定块 Lambda 和表达式 Lambda 的结束位置，并选择包含调用的最内层作用域。该过程仅在索引时扫描当前方法体，不进入查询热路径；无法证明契约的第三方回调不会形成目标边。

4.3.83 在同一索引期作用域模型上增加 JDK 集合泛型输入层。参数、局部变量和显式可见字段中的 `List/Set/Collection/Iterable/Stream<T>` 只向紧邻的直接集合或 Stream 操作提供单个输入类型，`Map<K,V>.forEach` 提供键值双输入。嵌套调用采用零宽重叠扫描，外层高阶调用不会吞掉回调内方法调用。通配符、裸类型、类型变量和经过 `map/flatMap` 类型变换的后续链不传播类型，从而保持索引复杂度与方法体长度线性相关，查询热路径开销为零。

### 5.3 多语言结构化索引

多语言路径位于 `memory_center/core/indexing/`：

- `language_registry.py`：注册 Java、Kotlin、Python、TypeScript、TSX、JavaScript、Go 等语言与 tree-sitter binding。
- `structural_parser.py`：按语言 AST walker 输出 `StructuralParseResult`。
- `parse_result.py`：跨语言通用实体：module、import、class、function、call、constant。
- `multilang_indexer.py`：把非 Java 文件转换成 `Module` / `Class` / `Function` 节点和 `DEFINES` / `IMPORTS` / `CALLS` 边。

Java 仍保留 Spring-aware 专用解析；多语言 structural pass 避免重复索引 `.java`。

### 5.4 Graph 构建

`build_graph_store()` 把索引结果转换成 `GraphNode` / `GraphEdge` 写入 `graph.db`。核心节点包括：

- `Service`
- `File`
- `Class`
- `Method`
- `Field`
- `Endpoint`
- `FeignClient`
- `FeignMethod`
- `MQTopic`
- `MQConsumer` / `MQProducer`
- `ConfigKey`
- `DataResource`
- `Module`
- `Function`

核心边包括：

- `CONTAINS`
- `DECLARES`
- `EXPOSES_ENDPOINT`
- `HANDLES_ENDPOINT`
- `CALLS_SERVICE`
- `IMPLEMENTS_FEIGN`
- `CONSUMES_TOPIC`
- `PRODUCES_TOPIC`
- `INJECTS_BEAN`
- `CALLS_METHOD`
- `READS_FIELD`
- `READS_CONFIG`
- `USES_DATA_RESOURCE`
- `DEFINES`
- `IMPORTS`
- `CALLS`

`GraphStore` 提供节点/边写入、FTS5 搜索、LIKE fallback、BFS neighbors、partial rebuild。全量 rebuild 使用 `executemany` 和 `fast_write_mode()`；FTS 使用 SQLite 内部 `INSERT ... SELECT` 构建，不向 Python 物化全量节点。部分 rebuild 按 project/path 删除并 upsert scope 内节点边，只批量替换变更节点的 FTS 行，并输出同步模式、节点数与耗时。

---

## 6. Storage Layer / 存储层

Memory Center 当前有三类存储角色。

### 6.1 File-backed WorkspaceStore

`WorkspaceStore` 负责 `.memory-center` 目录下的文件读写：

- JSON index：`index/*.json`
- JSONL memory：`memory/*.jsonl`
- refs：`memory/refs/**/*.json`
- artifacts：`artifacts/**/*.md`
- graph path / memory path 解析
- 文件锁：`store.lock`

`read_json_prefer_backend()` 与 `read_jsonl_prefer_backend()` 只读取 SQLite 事实库。文件读取 API 仅用于导出检查和显式恢复流程，不是运行时降级路径。

### 6.2 MemoryBackendStore

`memory_center/core/storage/memory_backend.py` 管理 `.memory-center/graph/graph.db` 中的记忆表、refs、断言和索引状态。它服务于：

- recent sessions / session summary
- timeline / drill-down
- write receipts
- backend query
- 聚合 dashboard / eval

它不替代 Markdown artifacts、workspace YAML、rules YAML 或业务源码。

### 6.3 GraphStore / UnifiedStore

`RuntimeStore` 是 graph-native 查询、运行记录、vector 与 inverted-index 共用的唯一 SQLite 访问层。实际维护时必须区分：

- `WorkspaceStore.graph_db_path`（等同于 `runtime_db_path`）：传给 `GraphStore`、`UnifiedStore`、VectorIndex、InvertedIndex、`MemoryBackendStore` 与 `UnifiedBackendQuery`。

不要把 `workspace.yaml` 直接传给 SQLite store；所有运行时存储访问都应从 `WorkspaceStore.runtime_db_path` 获取数据库路径，统一落在 `.memory-center/graph/graph.db`。

所有 SQLite 连接通过 `storage/pragmas.py` 应用统一 PRAGMA：WAL、`synchronous=NORMAL`、大 cache、`temp_store=MEMORY`、mmap、foreign keys。全量重建可临时进入 `synchronous=OFF` 的 fast write mode。

---

## 7. Retrieval and Query Layer / 检索与查询层

公共查询入口在 `memory_center/core/orchestrator/query.py`，MCP/CLI/HTTP 都通过它或其 wrapper 调用。

### 7.1 Hybrid Retrieval

`memory_center/core/retrieval/hybrid.py` 负责融合：

- exact graph lookup
- graph neighbors
- FTS / sparse keyword
- SQLite BM25 inverted index
- sparse semantic index
- optional dense vector ANN

`retrieval/policy.py` 根据 query intent、freshness、learned weights 生成确定性 `RetrievalPolicy`：

- full-chain / walkthrough：exact + graph 是硬约束，深度更大，候选更窄。
- chain：exact + graph + 可选 BM25 / sparse / semantic。
- structured entity：class / method / Feign / MQ / endpoint / config 使用类型加权。
- general：多源融合，vector 仍默认关闭。

禁用或不可用的 source 会进入 `retrieval_diagnostics`，不静默伪装成功。

### 7.2 Semantic / BM25 / Vector

`semantic.py` 只保存 `semantic-node-index.json` 的轻量状态，不再持久化全量节点、词频或 embedding 副本：

- 默认 backend 是 `sparse`。
- 设置 `MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers` 后，可对 selective candidate 生成 dense vectors。
- `MEMORY_CENTER_VECTOR_SCOPE=off|selective|all` 控制 dense candidate 范围。
- 稀疏检索直接查询 SQLite `InvertedIndex`，dense 检索直接查询 `VectorIndex`，随后按命中 ID 有界回填图节点；查询热路径不会扫描或反序列化全量语义文档。
- `semantic_index_stats()` 返回 `vector_status`、candidate count、dense count 和 disabled reason。

`retrieval/inverted.py` 将 graph nodes 写入 SQLite 代码感知 BM25F posting lists，名称、契约、路径和元数据采用不同字段权重。`storage/vector_index.py` 优先支持 sqlite-vec，否则使用持久化 hnswlib HNSW；sqlite-vec 的维度作为显式元数据校验，模型维度不一致时拒绝使用旧表并要求完整 reindex。大索引未安装 ANN 时返回可诊断不可用状态，禁止 Python 全量余弦回退。少于 64 条向量仅用于开发/测试的有界精确校验。HNSW 的向量事实写入、rebuild、增量同步、删除、调优、读取和 label 映射通过同一索引锁串行化，文件保存采用临时路径原子替换；查询锁最多等待 300ms，维护占用时返回可重试诊断而不是阻塞。HNSW 的查询 `ef` 可由有界 self-recall 探针调优。

融合阶段在固定候选预算内执行 relation-weighted personalized graph ranking；可选 Cross-Encoder 只重排前 12 个候选，并且仅使用当前 MCP 进程已显式预热的模型。磁盘缓存不触发查询期加载；预热中并发查询立即保留基础排序，不等待模型锁。模型档案可选择 MiniLM 平衡档或 BGE-M3 多语言档，档案切换必须通过显式完整 reindex 创建新 generation。LTR 只接受候选级人工验证标签，不能从 agent guidance 采纳率推断。

交付 Skill 使用稳定 `skill_id` 和逐次 canary `activation_id`：回滚后复用同一 registry 记录但开启新 activation，旧观测不进入新发布门禁。验证回执使用任务标识哈希与随机 receipt ID，不把任务标题写入 replay；人工验证要求明确 actor，但以 `self_asserted` 标记身份可信等级。回执 JSONL 是审计源，统一 `graph.db` 的 `delivery_receipts` 是查询投影，验收项和证据引用另存为稀疏关系索引。旧日志在工作区锁内按 500 条分批惰性回填，`projection_version` 负责 schema 演进；同步水位登记读取前的尺寸和 mtime，因此锁外追加最多触发下一次补读，不会被永久越过。状态和关闭门禁直接查询验收覆盖，只有最近回执展示读取最多 100 条 payload。新增回执以 JSONL 先落盘、SQLite 后提交的顺序写入，中断后由尺寸和 mtime 差异自动补齐。成功观测在工作区事务内完成证据去重，并把 replay 作为 observation 内的派生投影一次落盘；旧 replay 只在按当前契约和 activation 过滤后参与数量限制。Skill registry 与协作资产 registry 一样采用临时文件原子替换、有效备份恢复和双损坏拒写，并按 Skill 合并独立陈旧快照；canary、契约更新、发布和回滚使用完整读改写事务。外部评测采用可选 `skill-up` 适配器：Memory Center 仍是 Skill ID、发布状态、证据和回滚的唯一事实源；外部失败不能自动改变 Skill 发布状态。

检索融合权重不从“是否执行建议”推断。`retrieval/calibration.py` 只读取带 evidence 的人工验证 `retrieval-source` 回放，使用平滑后验与样本收缩生成提案，并仅由显式 `--apply` 写入当前工作区的校准快照。

### 7.3 Method Walkthrough

全链路方法报告由 `memory_center/core/walkthrough/` 承载，公共入口仍在 `orchestrator/query.py`：

- `runner.py`：端到端组装。
- `symbols.py`：符号解析、Impl 查找、绝对路径、Java 方法体提取。
- `continuations.py`：本地调用、Feign 续链、服务端 Controller / Impl 续链、同类方法续链。
- `risks.py`：性能风险、数据范围保护、diff context、freshness、Mermaid。
- `answer.py`：summary lines、read targets、agent policy、anti-patterns、Markdown 报告。
- `cache.py`：短期进程内缓存。
- `operations.py`：health、quality eval、artifact export。

`mc_lookup(mode="auto")` 遇到 `Class#method` 且用户表达“全链路/到底层/full chain”时，会优先路由到 walkthrough。walkthrough 顶层返回 `answer`、`summary_lines`、`read_targets`、`completion_status`、`index_freshness`、`agent_usage_policy` 等字段，宿主不需要解析本地 tool-result 文件。

### 7.4 Context Pack / Onboarding / Domain

V3 task tools 直接面向 agent 减少 grep/read：

- `ContextPackBuilder`：聚合 entrypoints、relationships、snippets、risks、checklist、freshness。
- `onboarding/*`：按 persona 生成架构导览、glossary、tour。
- `domain/*`：从图谱抽取业务域、业务流和业务影响。

### 7.5 Reasoning Pipeline

`ReasoningPipeline` 是 evidence-bounded 推理编排层。它不会替代图谱事实，而是把三类结果整理到稳定字段：

- `facts`：目标节点和直接关系。
- `inferences`：风险模式、结构模式。
- `derived`：有界传递推理。
- `quality`：证据数、截断状态、是否需要验证。

每个证据项可额外返回 `evidence_level`，用于统一展示结论可信边界：`EXTRACTED` 表示直接从索引或源码结构抽取，`INFERRED` 表示规则、模式或多跳推理，`AMBIGUOUS` 表示回退或证据不足，`VERIFIED` 仅表示存在显式验证结果。它是对既有 `semantic_strength` 的兼容扩展，不会由高置信度自动升级为 `VERIFIED`。

Each evidence item may additionally expose `evidence_level`: `EXTRACTED`, `INFERRED`, `AMBIGUOUS`, or explicitly validated `VERIFIED`. This is additive to `semantic_strength`; confidence alone never upgrades evidence to `VERIFIED`.

底层引擎：

- `GraphPatternEngine`
- `RiskPatternEngine`
- `TransitiveInferenceEngine`

单个引擎失败会以 diagnostics 形式降级，不丢弃其他健康证据。

---

## 8. Orchestrator Layer / 编排层

`memory_center/core/orchestrator/` 是核心业务编排层。入口层不应重复业务逻辑，而应调用这里的函数。

| 模块 | 主要职责 |
|---|---|
| `shared.py` | 上下文加载、token/budget、ref offload、排序、共享常量 |
| `compact.py` | compact/full 输出裁剪 |
| `workspace_ops.py` | status、sniff、trace、lookup hint、dashboard、规则/契约检查 |
| `query.py` | query、symbol、code search、callers/callees、context、contracts、walkthrough |
| `impact.py` | detect changes、impact、plan change、verification checklist |
| `session.py` | session start/log/end、recent sessions/evidence、case suggestion、close feedback |
| `resume.py` | resume packet、handoff packet/history、model profile、next actions |
| `sync.py` | sniff/case 同步到 artifacts/task space |
| `write.py` | memory write judge/plan/execute、case record、write receipts、replay |
| `group.py` | registry/group 跨 workspace 查询、影响、链路 |
| `evaluations.py` | write/resume/handoff/agent-guidance/regression/token/parser/java-call/golden 等评测 |

`orchestrator/__init__.py` 导出编排层公共函数；其他领域模块不经由根目录转发。

Benchmark/observability 趋势数据写在 `.memory-center/memory/*-trends.jsonl`，例如 token benchmark 的 `benchmark-trends.jsonl`、agent guidance quality 的 `agent-guidance-trends.jsonl` 和 agent guidance adoption 的 `agent-guidance-adoption-trends.jsonl`。这些文件用于本地运营与回归告警，不应把真实私有项目生成内容提交到公开仓库。

真实工作区 P95 采用显式快照而不是请求内测量：`workspace-performance-snapshots.jsonl` 仅保存 generation、采样次数、P50/P95/P99、最大值和成功/失败计数。它不保存查询、文件路径或正文，且不会在 lookup 热路径运行。快照状态只读取最近有界记录，比较上一条 P95 后给出局部刷新或重新采样建议。HTTP route dispatch 在进程初始化后为每条已注册路由生成读写契约；审计会阻断未分类、无效方法、孤立声明和名称表现为写入却被声明为 GET 的路由。

后台任务仍以 `workspace-jobs.json` 为唯一持久化模型。读取适配层按运行状态派生 `progress_percent`、`elapsed_ms`、`estimated_remaining_ms`、`can_cancel` 和 `recovery_action`，不回写或篡改历史结果；`/ui/jobs` 只轮询该紧凑状态，不读 graph、index 或源码。

---

## 9. MCP, CLI, HTTP Adapters / 入口适配层

### 9.1 MCP Facade

MCP 当前公开 15 个 task-level tools：

- `mc_bootstrap_context`
- `mc_provider_action`
- `mc_mcp_bridge`
- `mc_start`
- `mc_lookup`
- `mc_analyze`
- `mc_sync`
- `mc_resume`
- `mc_handoff`
- `mc_close`
- `mc_admin`
- `mc_context_pack`
- `mc_onboard`
- `mc_domain`
- `mc_freshness`

设计意图：模型看到的是任务级接口，不是几十个内部原子工具。`mc_admin` 的 action table 位于 `memory_center/application/admin.py`，通过 `CommandRegistry` 分发。

`mc_bootstrap_context` 是联邦读取入口：它先向上发现已有 `.memory-center/workspace.yaml`；找不到时通过 Provider Registry 选择 GitNexus 的固定 `status/query/context` 能力，结果包装为带 provider、范围、观测时间、持久化边界、`provider_selection` 和 `evidence_ref` 的临时证据。`EvidenceRef` 仅保存元数据和正文哈希，不复制外部正文。它不创建 workspace，也不将外部读取结果写入 SQLite 图谱。Provider 不可用时仅返回有界本地搜索计划。

`mc_provider_action` / `provider-action` 是独立的受控动作面。GitNexus 的 `impact/trace/detect-changes/check` 为读取动作；`analyze` 是受控索引动作、`clean` 是破坏性清理动作，均使用固定参数模板并要求 `confirm=true`。Provider Registry 可以声明混合能力，但每个动作仍单独标记 `read_only`、`controlled_write` 或 `destructive`，不会把外部命令变成 Agent 可自由拼接的 shell。

`mc_mcp_bridge` / `mcp-bridge-action` 是独立的受限 MCP Client 面，不通过宿主 Agent 转发。它只读取 `<root>/.memory-center/provider-mcp-policy.json` 中维护者明确登记的 HTTP URL、`sse|streamable_http` transport、工具名和参数模板，并在建立会话后以 `list_tools` 二次校验。策略不接受 stdio、认证字段、任意工具或参数；写入和破坏性动作总是需要 `confirm=true`。调用的原始结果不写入图谱、SQLite、断言或审计存储，只作为响应正文与不含正文的会话级 `EvidenceRef` 返回。该层以 60 秒超时、12,000 字符输出上限和同步线程隔离避免外部 MCP 卡住主查询链路。

Provider Registry 的路由健康数据只在进程内保存最近调用的耗时和状态，计算 P95、错误率和成本惩罚后与静态 priority 合并排序。它不在热路径外启动探测扫描。外部索引状态仅在 Provider 明确报告 `gitnexus_index_not_found` 或 `gitnexus_index_stale` 时生成确认型行动卡；行动卡指向固定 `analyze --index-only`，绝不自动执行。

Bridge 策略中声明 `capabilities: [code_navigation]` 的 `read_only` tool 会动态注册到同一 Provider Registry。因此零初始化联邦上下文会在 GitNexus 与健康的 IDEA/GitNexus MCP 等 Provider 间按 `priority + health penalty` 选择，而不是永远阻塞在一个外部工具上。跨 Provider 融合只消费临时 EvidenceRef 的来源、范围、哈希和显式结构化 Claim：同一 `subject/predicate` 的不同值返回 `CONFLICT` 与 `verify_conflict` Action；缺少 Claim 或来源不足只返回 `INSUFFICIENT_EVIDENCE`。融合器不解释、不拼接外部正文，也不写入长期层。

MCP 还暴露 resources：

- `memory-center://status`
- `memory-center://contracts`
- `memory-center://topology`

以及 prompts：impact、Spring Cloud safe change、onboarding、MQ safety、DTO impact、cross-service trace、freshness、domain overview、diff impact 等。

### 9.2 CLI

CLI 命令集中在 `memory_center/cli/main.py`，覆盖：

- workspace init / service maintenance
- reindex / status / sniff / trace
- query / search-code / symbol / callers / callees / walkthrough
- impact / contracts / plan / checklist
- memory write pipeline
- eval / benchmark / parser / golden / java call resolution
- session / work-* / handoff / dashboard
- HTTP serving / hook generation / runtime audit / business flow / metrics

CLI 是维护者和本地脚本最完整的操作面，但核心语义应复用 orchestrator。

任务空间健康检查和修复类 CLI（例如 `artifact health-task`、`artifact repair-plan-task`、`artifact repair-task`、`work-resume-check`）也必须复用 core 中的 artifacts/resume 语义。CLI 只负责参数适配和输出，不应自行复制匹配、健康评分或修复判断。

### 9.3 HTTP Bridge and Workbench

HTTP server 使用标准库 `ThreadingHTTPServer`，不是 FastAPI。它提供：

- `/health`
- `/workspace/*` JSON routes
- `/group/*` JSON routes
- `/ui/*` HTML exporters
- `/app` Vue SPA 静态托管

路由表在 `memory_center/http/routes/`，由 `route_dispatch.py` 组合：

- `workspace_ops.py`
- `workflow.py`
- `analysis.py`

每个 route family 注册到共享 `CommandRegistry`。请求参数由 `RouteParams` 适配，避免在 server 中堆 if-chain。

HTTP 的方法语义由 `route_dispatch.is_mutating_http_route` 统一约束：GET 严格只读，所有写入和可能执行外部动作的 route 必须 POST。服务默认绑定 loopback；非回环绑定必须使用访问令牌，并通过 `Authorization: Bearer` 验证。`actor` 是审计归因字段，不是远程身份认证机制。

Context Pack 将 top-K 节点聚合为一次有界的一跳边读取，再进行预算裁剪；不为每个节点重复建立 SQLite 读取。`WorkspaceStore` 将 index、artifact、audit 写锁拆分，generation 仍由独立 reindex lock 串行化。空间治理只扫描 `.memory-center` 的 graph/index/artifacts/memory 四类目录，并只返回显式 dry-run 维护建议。

Vue Workbench 位于 `web/src/`，主要页面包括 dashboard、query、impact、group、timeline、receipts、freshness、audit、health、onboard、flow、metrics、verification 等。

---

## 10. Task Memory and Artifacts / 任务记忆与工件

### 10.1 Workflow Profiles and Scoped Delivery / 工作流画像与受控交付

工作流画像是推荐层，不是第二套编排器。`quick-fix`、`contract-change`、`long-task`、`architecture` 与 `maintenance` 只描述任务应加载的上下文层和推荐工具顺序；真正的状态、门禁、验证回执与审计仍归属 `feature_delivery_v2`。

交付子任务可附带 `read_targets`、`write_targets`、`stop_conditions`。它们作为任务级范围契约写入现有 delivery 工件，并在 `delivery-matrix`、`TECH_SPEC.md` 中派生展示。默认只提供透明度；工作区策略启用 `enforce_scope_contract` 后，范围不完整的子任务不能进入 `implement`，从而避免高风险任务在上下文不足时扩大修改面。

Memory Center 的记忆模型分为四层：

| 层 | 位置 | 内容 |
|---|---|---|
| L0 session events | `memory/session-events.jsonl`、refs | 原始 prompt/tool/result/note、较大 payload 引用 |
| L1 case atoms | `memory/cases.jsonl` | 已验证可复用经验 |
| L2 task spaces | `artifacts/tasks/<task_id>/` | context、plan、design、change-log、current-summary 等任务协作工件 |
| L3 workspace profile | `artifacts/memory-blocks/` | workspace-profile、team-rules、architecture-invariants、active-migration-policy |

核心工件默认 append-only 或 guarded append，避免模型整篇覆盖上下文。写入链路包括：

- `memory_write_judge`
- `memory_plan_write`
- `memory_execute_write`
- `workspace_write_receipts`
- `workspace_replay_write_chain`

L2 task spaces 还提供恢复体验相关操作：健康检查、修复计划、保守修复执行和恢复门禁。MCP (`mc_admin`)、CLI (`artifact ...` / `work-resume-check`) 与 HTTP (`/workspace/work-resume-check`) 必须复用同一套核心函数，保证本地脚本、Agent 和 Web/IDE 集成看到一致结果。

`mc_close` 会结束 session、同步 case 到 artifacts、生成 suggested case，并在可推断时写回 candidate path feedback，用于后续推荐权重学习。

---

## 11. Freshness, Hooks, and Host Integration / 新鲜度、Hook 与宿主集成

`IndexFreshnessService` 通过 graph/index 时间和 workspace shape 生成 freshness banner。`mc_start`、hybrid retrieval、context pack、walkthrough 等主链路会暴露 freshness 相关信息，提醒 agent 在 stale/pending 时读取 live file 或 reindex。`freshness/daemon.py` 以独立本地进程持有每个 workspace 的 watcher lock，轮询并去抖源码和配置变更，再通过既有失效计划提交有界 partial reindex job；状态持久化在 `watcher-daemon.json`，CLI、MCP 与 Workbench 读取同一状态，不在查询热路径执行全量扫描。job 到达终态后 `change_reports.py` 仅使用失效计划、任务结果、服务路径前缀和 generation 元数据生成有界影响摘要；它不会加载全量图或自动调用深度 impact，契约类高风险变更只返回显式复核建议。报告确认采用追加式审计事件与紧凑索引读模型：`confirmed`、`false_positive`、`resolved` 关闭报告，`deep_analysis_required` 保持待确认。Workbench 仅读取最多 5 条未确认高风险项；报告和确认审计均按 30 天、10 万条做日常裁剪。MCP 审计采用分层维护：所有读取先应用保留窗口，64 KiB 以下的日志同步收口，超过阈值的日志由后台完成物理压缩，避免把十万级 JSONL 扫描置于工具响应链路。

`presentation/evidence_subgraph.py` 是显式导出路径：先以 node id 或受限 symbol 查询定位一个根节点，再执行最多 3 跳、120 条边、80 个节点的邻接遍历。输出只包含节点标识、项目、文件路径、边类型、置信度和证据等级，可渲染为 JSON、Markdown 或 HTML；不读取源码、原始工具载荷或全图，因此不会增加普通查询的延迟与数据暴露面。

Hook 层在 `memory_center/hooks/`，属于宿主集成，不是核心业务层。默认建议：

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

`UserPromptSubmit` 默认不启用；它容易打断普通自然语言输入。Claude Code、Codex、Cursor adapter 分别生成适配各宿主的 hook/规则文件。

---

## 12. Error Model and Dispatch Seams / 错误模型与分发边界

统一错误模型在 `core/foundation/errors.py`。CLI、MCP、HTTP 入口应捕获核心异常并返回结构化错误：

| Error Type | HTTP | 含义 |
|---|---:|---|
| `invalid_input` | 400 | 参数缺失、格式错误或不支持的操作 |
| `not_found` | 404 | workspace、route 或资源不存在 |
| `unavailable` | 503 | backend、连接或能力暂时不可用 |
| `conflict` | 409 | 与当前状态冲突 |
| `internal_error` | 500 | 未预期内部错误 |

`core/foundation/dispatch.py::CommandRegistry` 是小而深的分发 seam：

- MCP `mc_admin` action table 使用它。
- HTTP route registry 使用它。
- CLI walkthrough 命令组使用它。

它只负责注册、列出和分发 handler；参数绑定仍由 adapter 自己负责，以保持 public schema / path / command 兼容。

`mc_analyze` 还定义了阶段性成功语义：图谱 impact 是主结果，plan、rules、contract、checklist 和 contract evidence 是可独立诊断的补充阶段。主结果已成功时，补充阶段故障返回 `analysis_status=partial` 与阶段级 diagnostics；只有主结果或入口本身无法完成时才走统一错误模型。这样 Agent 能继续验证已有高置信影响，不会因一个可恢复依赖错误丢失工程证据。

---

## 13. Evaluation and Observability / 评测与可观测性

评测与质量模块用于防止“看起来有结果但不可用”：

- `benchmark/golden.py`：Golden Benchmark，case 使用逻辑锚点，禁止私有路径。
- `benchmark/java_call_resolution.py`：Java `CALLS_METHOD` 解析精度门禁。
- `benchmark/trending.py`：token benchmark trend 和回归告警。
- `parser_precision.py` 与 parser diagnostics：tree-sitter / regex fallback、critical disagreement。
- `audit/reports.py`：完成审计、设计决策、健康评分。
- `audit/runtime.py`：Agent runtime audit。
- `verification/*`：verification loop、pattern promotion、heuristics、workflow profile、agent bundle。
- `metrics.py`：workspace metrics summary。
- `observability.py`：操作观测装饰器。

公开 examples 适合 CI、smoke 和文档模板；真实大仓验收必须使用用户提供的本地 workspace/cases，并且不得提交私有 index/memory 产物。

---

## 14. Security and Privacy Boundaries / 安全与隐私边界

Memory Center 默认不改业务源码。写入范围主要限于：

- `.memory-center/index`
- `.memory-center/graph`
- `.memory-center/memory`
- `.memory-center/artifacts`
- `.memory-center/rules`
- `.memory-center/instructions`
- host hook / rule 配置文件

维护时必须遵守：

- 不提交真实私有项目生成的 `.memory-center/index` 或 `.memory-center/memory`。
- 示例、docs、tests 不写私有路径、内部服务名或真实密钥。
- 新增测试如果会写 graph / memory / index / benchmark，必须复制 demo workspace 到 `tmp_path` 后操作。
- `tests/conftest.py` 会在每个测试前后校验受跟踪 demo workspace 的摘要；测试不得绕过该门禁直接写入 `examples/spring-cloud-demo/.memory-center`。
- MCP tool schema 变化默认 additive；破坏兼容时必须同步 README、CHANGELOG、docs 和测试。
