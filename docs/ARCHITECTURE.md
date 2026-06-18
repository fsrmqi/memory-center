# Architecture / 架构说明

## Overview / 总览

Memory Center 是一个面向 AI 编程助手的本地优先项目记忆系统，核心目标是把“代码索引、跨服务关系、任务上下文、经验沉淀、模型交接”收敛到同一个工作区里。

Memory Center is a local-first project memory system for coding agents. It unifies indexing, cross-service relationships, task context, experience memory, and model handoff into one workspace.

系统入口统一为三类：

- `memory-center`：CLI
- `memory-center-mcp`：MCP facade tools
- `memory-center-http`：本地 HTTP bridge / workbench

## Core Model / 核心模型

### 1. Workspace / 工作区

每个 workspace 对应一个 `.memory-center/workspace.yaml`，定义：

- root 路径
- 服务列表
- 索引输出目录
- graph / memory / artifacts 存储位置
- 可选的嵌入与 registry 配置

### 2. Indexing / 索引层

索引层负责从代码仓库中提取：

- 文件索引
- Java symbol 索引
- API / Controller 索引
- OpenFeign 索引
- MQ / Topic 索引
- 配置索引
- 语义索引

针对 Spring Cloud / Spring Boot 多模块项目，系统会额外识别：

- Feign 客户端与下游 endpoint 的关系
- DTO / 公共契约位置
- MQ producer / consumer
- 配置与跨服务调用线索

### 3. Graph / 图谱层

索引结果会转换为节点与边，落到本地 SQLite graph store 中，用于：

- 图感知查询
- 调用链追踪
- 影响面分析
- 上下文拼装

图谱是 Memory Center 的结构化骨架；语义检索与规则系统都围绕它补强，而不是替代它。

### 4. Memory / 记忆层

记忆按层组织：

- `L0_session_events`：会话事件与过程证据
- `L1_case_atoms`：经验原子 / case
- `L2_task_spaces`：任务空间与协作工件
- `L3_workspace_profile`：工作区长期规则与画像

会话事件、写入回执、handoff、refs 元数据会镜像进入 SQLite `memory.db`，同时继续保留 JSONL / Markdown 作为可读、可追踪的落盘形式。

### 5. Workflow / 工作流层

对模型暴露的是任务级 facade，而不是大量原子工具：

- `mc_start`
- `mc_lookup`
- `mc_analyze`
- `mc_sync`
- `mc_resume`
- `mc_handoff`
- `mc_close`
- `mc_admin`

CLI / HTTP 仍保留细粒度原子操作，但 MCP 默认以 facade 为公开面，降低模型选择成本与 token 开销。

## Data Flow / 数据流

典型链路如下：

1. `reindex` 构建索引、graph、semantic 数据
2. `mc_start` 或 `workspace_sniff` 获取当前任务上下文
3. `mc_lookup` / `mc_analyze` 做检索、影响分析、规则检查
4. `work-*` 或 `mc_sync` 将过程同步到 task space / memory
5. `mc_resume` / `mc_handoff` 为恢复或跨模型交接提供轻量上下文
6. `mc_close` 做会话收尾、case 同步与经验沉淀

## Token Strategy / Token 策略

系统默认按“轻量优先、细节按需展开”设计：

- `view=compact|full`
- `budget=small|medium|large`
- short refs：`ref_id + summary`
- `memory_ref_get / memory_ref_batch` 按需展开
- top-K evidence 策略
- token gain / token benchmark 评测

## Unified Backend / 统一后端

`memory.db` 当前承担的是“镜像 + 高频读路径优先查询”的角色，而不是唯一事实源。

当前已经优先走 SQLite / backend 的典型高频路径包括：

- timeline
- recent sessions / session summary
- write receipts
- 部分 query / resume / dashboard / eval 相关读取

其余路径仍允许 fallback 到 JSONL / Markdown，这样可以兼顾稳定性和渐进演进。

完整读取路径、事实源、已知分叉和迁移顺序见：

- [UNIFIED_BACKEND_READ_PATHS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/UNIFIED_BACKEND_READ_PATHS.md)

需要特别区分：

- `memory.db`：memory、index、ref 镜像与聚合查询。
- `graph.db`：派生知识图谱和 graph-oriented retrieval/reasoning 主读后端。

当前 `read_json*_prefer_backend` 仍缺少来源和 fallback reason，并可能在镜像部分失败后优先读到旧 backend 数据。后续迁移必须先建立双读一致性保护。

## Hooks / 宿主 Hook

Hook 层属于宿主集成，不是核心业务层。推荐自动执行的只有三类生命周期事件：

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

`UserPromptSubmit` 默认不建议作为宿主 Hook 开启，因为它容易打断普通自然语言操作。

## Recommended Reading / 推荐阅读

- [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [ROADMAP.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ROADMAP.md)
- [TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_GUIDE.md)

## Implemented Capabilities (3.x / V3 Foundation) / 已实现能力（3.x / V3 基础版）

以下模块是当前系统里已经存在的能力，用于说明“已经落地了什么”，而不是表示这些仍然是待做事项：

### Hybrid Retrieval Engine / 混合检索引擎

**位置**: `memory_center/core/retrieval/hybrid.py`

**职责**: 智能路由 graph、FTS、SQLite BM25、semantic 和可选 vector 检索源，提供更稳定的召回效果。

**核心组件**:
- `HybridRetrievalConfig`: 检索配置（权重、阈值、特性开关）
- `RetrievalResult`: 统一检索结果（带来源追踪）
- `detect_query_intent()`: 查询意图自动检测
- `hybrid_retrieve()`: 主检索入口

**检索策略**:
- Graph 检索: 结构化关系（callers, callees, chains）
- Sparse/FTS 检索: 精确匹配和关键词查找
- SQLite BM25: reindex 后自动重建的倒排候选检索
- Semantic 检索: 模糊/概念匹配
- Vector ANN: 当 semantic index 存在 dense vectors 时同步到 `VectorIndex`，默认关闭、按需启用
- 基于意图的类型加权（feign/mq/endpoint/config/chain/class/method）

`HybridRetrievalConfig.enable_sparse_bm25` 默认开启；`enable_vector` 默认关闭。禁用或不可用的检索源会在 `retrieval_diagnostics` 中返回明确状态，不静默伪装成功。

### Benchmark Trending / 基准趋势

**位置**: `memory_center/core/benchmark/trending.py`

**职责**: 长期监控 token 使用，检测回归问题。

**核心组件**:
- `record_benchmark_baseline()`: 记录基准线
- `record_benchmark_trend()`: 记录趋势点
- `get_benchmark_trends()`: 获取趋势分析
- `generate_benchmark_report()`: 生成综合报告

**特性**:
- 自动回归检测（近期 vs 历史对比）
- 健康评分和建议
- 按函数/budget 维度分析

### Unified Backend Query / 统一后端查询

**位置**: `memory_center/core/backend/query.py`

**职责**: 统一 SQLite 读取路径，减少分叉读取。

**核心组件**:
- `UnifiedBackendQuery`: 统一查询类

**查询能力**:
- 索引查询: `read_index()`, `read_index_list()`, `read_index_dict()`
- 记录查询: `query_records()`, `query_session_events()`, `query_write_receipts()`
- 聚合查询: `aggregate_by_session()`, `aggregate_by_project()`
- 健康检查: `check_health()`

### Drill-Down Navigation / 钻取导航

**位置**: `memory_center/core/navigation/drilldown.py`

**职责**: 增强 timeline/ref/task 的导航和钻取体验。

**核心组件**:
- `DrillDownNavigator`: 钻取导航器

**功能**:
- 渐进式 ref 展开（Level 1 摘要 → Level 2 详情 → Level 3 相关项）
- 时间线钻取: `drill_timeline()`
- 任务钻取: `drill_task()`
- 切换上下文: `build_handoff_context()`
- Facade 摘要: `build_facade_summary()`

### Completion Audit / 完成审计

**位置**: `memory_center/core/audit/completion.py`

**职责**: 文档对齐检查、设计决策记录、健康评估。

**核心组件**:
- `run_completion_audit()`: 运行完成审计
- `record_design_decision()`: 记录设计决策
- `get_design_decisions()`: 查询设计决策
- `generate_audit_report()`: 生成综合报告

**审计维度**:
- 文档检查: 关键文档存在性（自适应，不硬编码特定文件名）、SPECIAL_NOTES 完整性
- 测试检查: 多语言测试文件检测（Python/Java/JS/TS/Go/Rust）、多框架配置（pytest/Maven Surefire/Gradle JUnit/package.json/Cargo.toml）
- 实现检查: 模块完整性
- 设计一致性: 冲突决策检测
- 评分一致性: 审计分数与健康分数使用统一权重

## Module Architecture / 模块架构

### Python 后端 / Python Backend

```
memory_center/core/
├── retrieval/           # 混合检索（Phase A）
│   ├── __init__.py
│   └── hybrid.py
├── walkthrough/         # 方法全链路报告支持模块
│   ├── __init__.py
│   ├── artifact.py      # Markdown artifact 渲染
│   ├── cache.py         # 短期进程内缓存适配器
│   ├── quality.py       # agent-ready 质量评分
│   ├── symbols.py       # 符号 / Impl / abs path / Java 方法体提取
│   ├── continuations.py # local steps、Feign / 服务端 Impl / 同类续链
│   ├── risks.py         # 性能风险、scope guard、freshness、diff、Mermaid
│   ├── answer.py        # 模板、summary lines、compact view、agent policy
│   ├── escalation.py    # workspace 输入解析 / 父级覆盖 / quality score
│   ├── operations.py    # health / quality / export 编排
│   └── runner.py        # build_walkthrough_result 端到端组装入口
├── benchmark/           # 基准趋势（Phase B）
│   ├── __init__.py
│   └── trending.py
├── backend/             # 统一后端（Phase C）
│   ├── __init__.py
│   └── query.py
├── navigation/          # 钻取导航（Phase D）
│   ├── __init__.py
│   └── drilldown.py
├── audit/               # 完成审计（Phase E）
│   ├── __init__.py
│   └── completion.py
├── graph.py             # 图存储
├── dispatch.py          # MCP / HTTP / CLI 共享命令分发 seam
├── semantic.py          # 语义索引
├── store.py             # 工作区存储
├── memory_backend.py    # SQLite 后端
└── orchestrator/        # 编排层
    ├── query.py         # 查询编排（已集成 hybrid retrieval；walkthrough 通过子模块承载渲染/缓存/评分）
    └── ...
```

### Walkthrough Refactoring / Walkthrough 拆分

`memory_center.core.orchestrator.query` remains the compatibility facade for MCP, CLI, and HTTP callers. Method walkthrough support code is split across `memory_center.core.walkthrough`:

- `cache.py`: short-lived process cache with defensive copies.
- `artifact.py`: Markdown artifact rendering and slug generation.
- `quality.py`: agent-ready quality scoring.
- `symbols.py`: symbol parsing, owner/Impl resolution, file-abs path map, and Java method/body/case extraction.
- `continuations.py`: local steps, Feign continuations, server impl continuations, same-class continuations, DTO field summary/rule groups, and next-action assembly.
- `risks.py`: performance risk detection, data-scope guards, diff context, index freshness, branch outline, and Mermaid flow rendering.
- `answer.py`: schema/contract, agent policy, anti-patterns, summary lines, compact view, template loading, and answer Markdown rendering.
- `escalation.py`: workspace input resolution, parent/covering/sibling discovery, quality-score comparison, and bypass feedback.
- `operations.py`: walkthrough health, quality evaluation, and artifact export orchestration.

`orchestrator/query.py` keeps the public ``memory_method_walkthrough`` /
``memory_walkthrough_health`` / ``memory_eval_walkthrough_quality`` /
``memory_export_walkthrough_artifact`` entry points and a thin layer of
underscore-prefixed delegators that re-export the new helpers; this keeps
existing MCP / HTTP / CLI imports and tests stable.

`memory_center.core.orchestrator.query` 仍然是 MCP、CLI 和 HTTP 调用方的兼容 facade。method walkthrough 的支撑逻辑已经按下面的子模块拆分到 `memory_center.core.walkthrough`：

- `cache.py`：短期进程内缓存，防御性拷贝。
- `artifact.py`：Markdown artifact 渲染和 slug 生成。
- `quality.py`：agent-ready 评分。
- `symbols.py`：符号解析、owner/Impl 查找、file-abs path map、Java 方法体与 case 提取。
- `continuations.py`：本地 step、Feign 续链、服务端 Impl 续链、同类方法续链、DTO 字段摘要/规则分组、next actions。
- `risks.py`：性能风险、数据范围保护、diff 上下文、索引新鲜度、分支轮廓、Mermaid。
- `answer.py`：schema/contract、agent policy、反模式、summary lines、compact view、模板加载与 answer Markdown 渲染。
- `escalation.py`：workspace 输入解析、父级/覆盖/兄弟 workspace 查找、质量分对比、绕过反馈。
- `operations.py`：walkthrough 健康检查、质量评估和 artifact 导出编排。

`orchestrator/query.py` 只保留公共入口（``memory_method_walkthrough`` /
``memory_walkthrough_health`` / ``memory_eval_walkthrough_quality`` /
``memory_export_walkthrough_artifact``）以及一层下划线前缀的轻量委托
helper，把调用转给新模块；这样 MCP / HTTP / CLI 调用方和测试都不需要改动。

### Command Dispatch Seam / 命令分发 Seam

`memory_center.core.dispatch.CommandRegistry` is the shared dispatch module for MCP actions, HTTP routes, and CLI command groups that would otherwise repeat large dictionaries or if-chains. Its interface is intentionally small: register handlers, check available names, and dispatch one name. The adapter still owns parameter binding, so public MCP action names, HTTP paths, and CLI command names remain backward-compatible.

`memory_center.core.dispatch.CommandRegistry` 是 MCP action、HTTP route 与 CLI command group 共享的分发 Module，用于减少大字典和 if-chain 的重复。它的 interface 保持很小：注册 handler、检查可用名称、按名称分发。参数绑定仍由各 adapter 自己负责，因此公开的 MCP action 名称、HTTP 路径和 CLI 命令名保持兼容。

Current adapters using this seam:

- MCP: `mc_admin` dispatches through `CommandRegistry(label="mc_admin action")`; `memory_center.mcp.action_registry` remains as a compatibility import.
- CLI: method walkthrough commands dispatch through a walkthrough command registry.
- HTTP: ``build_http_route_registry`` returns one process-wide registry composed from the ``workspace``, ``workflow``, and ``analysis`` route-family Modules under ``memory_center.http.routes``. Request-specific ``RouteParams`` are supplied at dispatch time, so the adapter does not rebuild every handler per request. ``server._route_request`` only handles ``/health`` and unknown-route errors.

当前已接入的 adapter：

- MCP：`mc_admin` 通过 `CommandRegistry(label="mc_admin action")` 分发；`memory_center.mcp.action_registry` 保留为兼容导入路径。
- CLI：method walkthrough 相关命令通过 walkthrough command registry 分发。
- HTTP：``build_http_route_registry`` 返回进程级单例 registry，由 ``memory_center.http.routes`` 下的 ``workspace``、``workflow``、``analysis`` 三个 route-family Module 组合。请求级 ``RouteParams`` 在 dispatch 时传入，不再为每个请求重建全部 handler。``server._route_request`` 只处理 ``/health`` 与未知路径错误。

The seam is intentionally not a framework. It is a small deep Module: deleting it would push unknown-action errors, valid-name listing, and handler maps back into every adapter.

该 seam 刻意不做成框架，而是一个小而深的 Module：如果删除它，unknown-action 错误、有效名称列表、handler map 会重新散落回每个 adapter。

### Architecture Backlog / 后续架构优化队列

The following work is intentionally documented as follow-up scope so it can be implemented in smaller, verifiable changes:

- `P2` Migrate the remaining handful of low-frequency walkthrough helpers to ``core/walkthrough/`` if they grow new responsibilities; today the orchestrator only keeps the public facade and a thin ``lookup_provider`` / ``escalation_runner`` plumbing.
- `P2` Watch ``memory_center/http/routes/`` for repeated optional flags. ``RouteParams`` already collapses ``view`` / ``budget`` / ``task_id`` / ``session_id`` / ``intent`` / ``project`` / ``auto_sync_mode`` / ``report_level`` etc.; extend it instead of bringing back repeated ``params.get`` literals.
- `P2` Keep ``mc_admin`` action coverage in lockstep with the registry: ``tests/test_mcp_admin_actions.py`` is the canonical seam test; new actions should be added there rather than relying on the FastMCP shape test.
- `P2` Keep retrieval fusion regression coverage in ``tests/test_hybrid_fusion_purity.py``. ``_merge_retrieval_results`` and ``_apply_type_boosting`` default to deep copies; if a future optimisation reintroduces in-place mutation, gate it behind an explicit flag and add a parallel purity test.
- `P2` Maintain the indexed Feign↔API and field-by-class lookups in ``indexer.py``. ``tests/test_indexer_perf.py`` asserts indexed lookup remains at least 5x faster than a linear scan; if a refactor regresses that ratio, restore the index before merging.
- `P2` Grow the synthetic Spring Cloud benchmark in ``tests/test_benchmark_workspace_perf.py`` rather than introducing private fixtures. Adjust ``SERVICES`` / ``CONTROLLERS_PER_SERVICE`` / ``ENDPOINTS_PER_CONTROLLER`` knobs when the topology under test changes; keep the wall-clock budgets generous so CI variance does not cause flakes.
- `P2` Unify CLI / HTTP / MCP parameter models where the same operation exists in multiple adapters. Introduce light argument objects only when they reduce duplicated defaults and validation rules.
- `P2` Keep architecture documentation and migration notes current. When public entrypoints remain compatible, document internal seams in `ARCHITECTURE.md`; only document breaking changes in README / CHANGELOG when legacy fallbacks are removed.

以下工作作为后续范围记录，便于小步实现和验证：

- `P2` 当 walkthrough 子模块再出现新的轻量 helper 时，优先放到 ``core/walkthrough/``；目前 orchestrator 只保留公共 facade 与 ``lookup_provider`` / ``escalation_runner`` 的粘合。
- `P2` 关注 ``memory_center/http/routes/`` 的可选参数重复。``RouteParams`` 已经把 ``view`` / ``budget`` / ``task_id`` / ``session_id`` / ``intent`` / ``project`` / ``auto_sync_mode`` / ``report_level`` 等收口；应扩 ``RouteParams``，不要重新复制 ``params.get`` 字面量。
- `P2` ``mc_admin`` action 覆盖度与 registry 同步：``tests/test_mcp_admin_actions.py`` 是规范化的 seam 测试，新 action 应在这里加测试，而不是依赖 FastMCP 形状检测。
- `P2` 保留 ``tests/test_hybrid_fusion_purity.py``：``_merge_retrieval_results`` 与 ``_apply_type_boosting`` 默认是纯函数（deep copy）。如果未来出于性能重新引入原地修改，必须挂在显式开关后并补一组对应的纯函数测试。
- `P2` 维护 ``indexer.py`` 中的 Feign↔API 与 field-by-class 索引 lookup。``tests/test_indexer_perf.py`` 要求索引 lookup 至少比线性扫描快 5 倍；任何回归这个比例的改动都应在合入前恢复索引。
- `P2` 在 ``tests/test_benchmark_workspace_perf.py`` 中扩展合成 Spring Cloud benchmark，不要引入私有 fixture。需要调拓扑时调整 ``SERVICES`` / ``CONTROLLERS_PER_SERVICE`` / ``ENDPOINTS_PER_CONTROLLER`` 等旋钮；wall-clock 上限保持宽松，避免 CI 抖动 flake。
- `P2` 统一 CLI / HTTP / MCP 的参数模型。只有当同一个操作跨多个 adapter 重复默认值和校验规则时，才引入轻量参数对象。
- `P2` 持续维护架构文档和迁移说明。公开入口保持兼容时，只在 `ARCHITECTURE.md` 记录内部 seam；只有移除 legacy fallback 或产生不兼容变化时，才写入 README / CHANGELOG。

### Vue 前端 / Vue Frontend

```
web/
├── src/
│   ├── api/client.js      # API 客户端（axios，代理到 Python 后端）
│   ├── router/index.js    # Vue Router 配置
│   ├── layouts/AppLayout.vue  # 主布局（侧边栏 + 工作区输入）
│   ├── components/        # 共享组件
│   │   ├── DataCard.vue   # 数据卡片（loading/error/content）
│   │   ├── JsonTree.vue   # JSON 树形查看器
│   │   └── KeyValueTable.vue  # 键值对表格
│   └── views/             # 页面视图
│       ├── WorkbenchView.vue   # 工作台首页
│       ├── DashboardView.vue   # 工作区总面板
│       ├── ContinuityView.vue  # 连续性面板
│       ├── TaskView.vue        # 焦点任务
│       ├── QueryView.vue       # 查询/检索
│       ├── ImpactView.vue      # 影响分析
│       ├── GroupView.vue       # 跨项目查询/影响/链路
│       ├── TimelineView.vue    # 时间线
│       ├── ReceiptsView.vue    # 写入回执
│       ├── UsageView.vue       # 使用报告
│       ├── BackendView.vue     # 后端数据
│       ├── FreshnessView.vue   # 索引新鲜度
│       ├── AuditView.vue       # 审计
│       └── HealthView.vue      # 健康检查
├── vite.config.js         # Vite 配置（含 API 代理）
└── package.json           # 依赖：vue@3, vue-router@4, axios
```

前端通过 HTTP 服务器的 `/app` 路径托管，支持 SPA 客户端路由。

## Integration Guide / 集成指南

### 使用 Hybrid Retrieval

```python
from memory_center.core.retrieval import hybrid_retrieve, HybridRetrievalConfig

# 默认配置
result = hybrid_retrieve(graph, workspace_file, "asyncBusinessOperationExport")

# 自定义配置
config = HybridRetrievalConfig(
    graph_weight=0.5,
    sparse_weight=0.3,
    semantic_weight=0.2,
    vector_weight=0.15,
    enable_sparse_bm25=True,
    enable_vector=False,
)
result = hybrid_retrieve(graph, workspace_file, query, config=config)
```

### 使用 Benchmark Trending

```python
from memory_center.core.benchmark import record_benchmark_trend, get_benchmark_trends

# 记录趋势
record_benchmark_trend(workspace_file, "mc_lookup", raw_tokens=1000, compact_tokens=300)

# 获取趋势分析
trends = get_benchmark_trends(workspace_file, function_name="mc_lookup", days=30)
```

### 使用 Unified Backend

```python
from memory_center.core.backend import UnifiedBackendQuery

with UnifiedBackendQuery(db_path) as backend:
    records = backend.query_records(collection="session-events.jsonl")
    stats = backend.aggregate_by_session()
    health = backend.check_health()
```

### 使用 Drill-Down Navigation

```python
from memory_center.core.navigation import DrillDownNavigator

with DrillDownNavigator(workspace_file) as nav:
    ref = nav.expand_ref("session-event:abc123")
    timeline = nav.drill_timeline(session_id="xyz")
    task = nav.drill_task(task_id="task-001")
    handoff = nav.build_handoff_context(session_id="xyz")
```

### 使用 Completion Audit

```python
from memory_center.core.audit import run_completion_audit, record_design_decision

# 运行审计
audit = run_completion_audit(workspace_file, work_package="Phase A")

# 记录设计决策
record_design_decision(
    workspace_file,
    topic="hybrid_retrieval",
    decision="使用 RRF 合并三种检索源",
    rationale="平衡精确性和召回率",
)
```
