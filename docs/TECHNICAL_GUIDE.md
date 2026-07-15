# Technical Guide / 技术说明

## 1. 文档定位

这份文档面向：

- 维护 Memory Center 本身的人
- 需要理解核心实现结构的人
- 想知道“功能落在哪个模块、数据怎么流动、哪些地方该改”的开发者

如果你只是想安装和使用，优先看：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)

如果你想理解当前系统的统一实体、关系和语义边界，补充看：

- [docs/ONTOLOGY.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ONTOLOGY.md)

## 2. 代码总览

核心包在：

- `memory_center/cli/`
- `memory_center/core/`
- `memory_center/mcp/`
- `memory_center/http/`
- `memory_center/hooks/`

### 2.1 入口层

#### CLI

- 文件：`memory_center/cli/main.py`
- 对外命令：`memory-center`
- 负责：
  - init / reindex / query / impact
  - work-* 工作流
  - hook 生成与执行
  - eval / benchmark / backend query

#### MCP

- 文件：`memory_center/mcp/server.py`
- 对外命令：`memory-center-mcp`
- 负责：
  - 12 个 task-level tools
  - resources / prompts
  - `mc_admin` 路由管理
  - V3 `context_pack / onboard / domain / freshness`

#### HTTP

- 文件：`memory_center/http/server.py`
- 对外命令：`memory-center-http`
- 负责：
  - `/workspace/*` 端点
  - `/ui/*` 本地 workbench

## 3. Core 层模块职责

### 3.1 索引与图谱

- `core/indexer.py`
  - workspace 全量 / 增量索引
  - 文件、symbol、API、Feign、MQ、config、semantic 入口
- `core/indexing/java_regex_parser.py`
  - Java / Spring Cloud 规则解析
- `core/indexing/java_call_resolver.py`
  - Java 方法调用解析
  - 将 `method_calls` 从文本证据提升为带置信度的 `CALLS_METHOD` 边
- `core/graph.py`
  - graph.db 节点边写入与查询

### 3.2 配置与存储

- `core/config.py`
  - 读取 `workspace.yaml`
- `core/store.py`
  - workspace 目录读写
  - JSON / JSONL / refs
  - `read_json_prefer_backend` / `read_jsonl_prefer_backend`
- `core/memory_backend.py`
  - SQLite `memory.db`
  - 镜像写入与统一后端查询

### 3.3 规则与协议

- `core/rules.py`
  - 默认规则
  - YAML 规则读取
  - 匹配逻辑
- `core/schemas.py`
  - 稳定返回 schema
- `core/write_receipts.py`
  - 写入回执

### 3.4 编排器

现在编排器已经拆分到：

- `core/orchestrator/common.py`
- `core/orchestrator/compact.py`
- `core/orchestrator/query.py`
- `core/orchestrator/impact.py`
- `core/orchestrator/session.py`
- `core/orchestrator/resume.py`
- `core/orchestrator/sync.py`
- `core/orchestrator/workspace.py`
- `core/orchestrator/write.py`
- `core/orchestrator/group.py`
- `core/orchestrator/eval.py`

这是当前系统最核心的一层。

#### 主要职责拆分

- `common.py`
  - load/store 上下文
  - budget/profile
  - ref 解析
  - payload compact / offload
- `compact.py`
  - compact/full 输出裁剪
  - dashboard / sniff / handoff / resume 压缩层
- `query.py`
  - `memory_query`
  - `memory_ref_get / batch`
- `impact.py`
  - `memory_impact`
  - `memory_plan_change`
  - `memory_verify_checklist`
- `session.py`
  - session 开始 / 记录 / 结束
  - recent evidence
  - top-K evidence compact
- `resume.py`
  - `workspace_resume_packet`
  - `workspace_handoff_packet`
- `sync.py`
  - sync sniff / sync case
- `workspace.py`
  - `workspace_status`
  - `workspace_sniff`
  - `workspace_dashboard`
- `write.py`
  - write judge / plan / execute
- `group.py`
  - registry/group 聚合
- `eval.py`
  - quality eval
  - token gain / token benchmark

### 3.5 辅助层

- `core/benchmark/golden.py`
  - Golden Benchmark case loading
  - logical anchor / edge extraction
  - suite scoring and latency summary
- `core/benchmark/models.py`
  - portable `GoldenCase` schema
  - private-path / unsupported-field guardrails
- `core/timeline.py`
  - session_event / write_receipt / handoff 统一时间线
- `core/tracking.py`
  - token gain 日志
- `core/token_utils.py`
  - token 估算与节省统计
- `core/exporters.py`
  - HTML / Markdown / UI 片段渲染
- `core/wiki.py`
  - wiki / skills 生成
- `core/instructions.py`
  - AGENT / CLAUDE / GEMINI 指令文件生成

### 3.6 V3 层

- `core/context/*`
  - context pack、budget、evidence
- `core/domain/*`
  - business domain / business flow 抽取与查询
- `core/freshness/*`
  - 索引新鲜度检测、watcher、reconcile
- `core/ontology.py`
  - Code KG ontology node / edge typing
- `core/reasoning/*`
  - `models.py`: immutable `ReasoningRequest`
  - `pipeline.py`: fact / inferred / derived orchestration, global evidence budget, deduplication and partial degradation
  - `patterns.py`: workspace-level structural scans
  - `transitive.py`: bounded breadth traversal for target call chains
  - `risk.py`: target-level change risk
  - `integration.py`: canonical/legacy compatibility views
- `core/indexing/differential.py`
  - entity-level regex/tree-sitter comparison
  - method overload identity and line-delta checks
  - Controller/Feign mapping parity
  - corpus-level recall and critical-disagreement summary
- `examples/parser-corpus/`
  - sanitized Java syntax and Spring mapping fixtures
  - public parser regression gate; never replace with private source files
- `core/storage/*`
  - unified store / SQLite pool / vector index
- `core/onboarding/*`
  - guided tour / glossary / onboarding
- `core/presentation/*`
  - progressive explanation helpers

## 4. 当前系统的几条主链路

### 4.1 索引链路

1. `workspace.yaml`
2. `reindex_workspace(...)`
3. index JSON 产物
4. `graph.db`
5. semantic index
6. SQLite BM25 inverted index
7. optional dense vectors → `VectorIndex`
8. instructions / hooks / default rules

### 4.1.1 Java call resolution levels / Java 调用解析层级

`reindex_workspace` 在 Java symbol 扫描完成后会构建一次全工程
`JavaClassIndex`，再由 `JavaCallResolver` 解析每条 `method_calls` 证据。
解析结果写入 `CALLS_METHOD` 边的 `confidence` 与 `metadata_json`，不会改变
MCP tool schema。

解析层级：

| resolution_level | confidence | 规则 |
|---|---:|---|
| `same_class` | `1.0` | `this.foo()`、`super.foo()`、裸 `foo()` 或 owner class 内方法 |
| `same_package` | `0.9` | receiver type 在当前 package 内能唯一匹配 class |
| `import` | `0.85` | receiver type 通过显式 `import com.foo.Bar` 匹配 |
| `static_import` | `0.85` | 裸调用通过 `import static com.foo.Bar.baz` 匹配 |
| `wildcard_import` | `0.6` | receiver type 通过 `import com.foo.*` 匹配 |
| `static_wildcard_import` | `0.6` | 裸调用通过 `import static com.foo.Bar.*` 匹配 |
| `unresolved` | `0.3` | 保留调用证据,但不绑定到随机同名真实方法 |

边元数据包含：

- `resolution_level`
- `receiver` / `receiver_type`
- `target_fqcn` / `target_file`
- `arg_count` / `matched_signature`
- `inferred_target`
- 原始 `evidence`

`memory_callers` / `memory_callees` 默认优先返回 `confidence >= 0.85`
的边；如果高置信结果为空但存在低置信边，会自动降级返回并在
`confidence_filter.fallback_to_low_confidence=true` 中标注。CLI 和 HTTP 可通过
`min_confidence=0` 主动查看 unresolved / wildcard 等低置信边。

Known limitation: 目前 resolver 仍是轻量静态解析，不处理继承分派、泛型实参
推断、Spring conditional bean、AOP/反射和 MyBatis XML 间接调用。这些应进入
后续真实场景 golden case，而不是在公开 fixture 里伪造。

### 4.2 任务上下文链路

1. `workspace_sniff(...)`
2. `lookup_hint`
3. `resolved_task`
4. `auto_sync_recommendation`
5. `mc_start`

### 4.3 连续性链路

1. session events
2. write receipts
3. recent evidence
4. resume packet
5. handoff packet
6. continuity / dashboard

### 4.4 写入治理链路

1. `memory_write_judge`
2. `memory_plan_write`
3. `memory_execute_write`
4. write receipt

### 4.5 Golden Benchmark 链路

1. 私有或公开 `cases.yaml`
2. `run_golden_suite(workspace.yaml, cases.yaml)`
3. `memory_method_walkthrough` / `memory_query_hybrid`
4. logical anchor / edge extraction
5. recall / forbidden-hit / latency 聚合
6. CLI / MCP / HTTP 统一适配输出

当前适配入口：

- CLI: `memory-center eval-golden --workspace <workspace.yaml> --cases <cases.yaml>`
- MCP: `mc_admin(action="eval_golden", workspace_file=..., name=<cases.yaml>)`
- HTTP: `/workspace/eval-golden?workspace=...&cases=...`

说明：

- `cases.yaml` 只保存逻辑 symbol、edge type 和阈值，不保存绝对路径、源码片段或私有业务数据。
- 如果没有配置 repo 内模板，可以直接传入你本地维护的私有 cases 文件；workspace 可以直接指向真实项目的 `.memory-center/workspace.yaml`。
5. artifact write audit

### 4.5 统一后端链路

1. JSONL / Markdown 继续落盘
2. 关键记录镜像到 `memory.db`
3. 高频读路径优先走 backend
4. fallback 到 JSON/JSONL

## 5. 当前最重要的设计取舍

### 5.1 MCP 面收敛为 facade

现在默认不把实现层几十个工具直接暴露给模型，而是暴露 12 个任务级工具：

- 基础 8 个 facade：
  - `mc_start / mc_lookup / mc_analyze / mc_sync / mc_resume / mc_handoff / mc_close / mc_admin`
- V3 4 个理解与治理工具：
  - `mc_context_pack / mc_onboard / mc_domain / mc_freshness`

原因：

- 降低 token
- 降低工具选择成本
- 保持任务级语义稳定

### 5.2 轻量上下文优先

不是所有返回都直接把完整结构喂给模型，而是：

- `view=compact|full`
- `budget=small|medium|large`
- short refs
- top-K evidence

### 5.3 SQLite 不是唯一真相源

当前仍然保留：

- JSON
- JSONL
- Markdown

SQLite `memory.db` 负责：

- 镜像
- 高频查询优先
- 观察与聚合

这是渐进统一，而不是一步替换。

### 5.4 Hook 是宿主集成，不是核心业务

Hook 的价值在于自动触发关键生命周期动作，但不应该过度侵入自然语言入口。

当前推荐：

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

默认不推荐：

- `UserPromptSubmit`

## 6. 当前最值得关注的实现热点

如果后面继续优化，最容易碰到的热点是：

- `core/indexer.py`
- `core/orchestrator/*`
- `core/store.py`
- `core/memory_backend.py`
- `mcp/server.py`
- `http/server.py`
- `hooks/*`

## 7. 推荐阅读顺序

如果你是第一次接手这个项目，建议顺序：

1. [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
2. [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
3. 本文档
4. [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
5. [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
6. [docs/NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md)

## 8. 已实现能力细节 (v2.2.0)

这一节记录的是 v2.2.0 阶段已经落地的实现细节，便于维护者理解当前代码；它不是新的待办计划列表。

### 8.1 Hybrid Retrieval 实现细节

**问题**: 之前 `memory_query()` 只使用 graph + semantic 两种检索源，对于某些查询（如 Feign、MQ、endpoint）召回不稳定。

**解决方案**: 实现 graph / FTS / BM25 / semantic / optional vector 多源混合检索 + 智能路由。

**核心算法**:

```python
# 1. 在执行前生成确定性策略
policy = select_retrieval_policy(intent, freshness, learned_weights)

# 2. 只执行策略选中的来源
graph_hits = _graph_retrieval(...) if "graph" in policy.sources else []
sparse_hits = _sparse_retrieval(...) if "sparse" in policy.sources else []
semantic_hits = _semantic_retrieval(...) if policy.semantic_enabled else []
bm25_hits = _bm25_sparse_retrieval(...) if "bm25" in policy.sources else []
vector_hits = _vector_retrieval(...) if config.enable_vector and policy.vector_enabled else []

# 3. RRF 合并
merged = _merge_retrieval_results(
    graph_hits,
    sparse_hits,
    semantic_hits,
    config,
    vector_hits=vector_hits,
    bm25_hits=bm25_hits,
)

# 4. 类型加权
merged = _apply_type_boosting(merged, intent)

# 5. 按 policy.graph_depth 和 policy.evidence_budget 有界丰富邻居
for item in merged[:limit]:
    item.neighbors = graph.neighbors(item.node_id, ...)

# 5. 跨 workspace 解析
_resolve_cross_workspace_refs(merged[:limit], graph, workspace_file)
```

**意图检测**:
- 正则匹配: `feign|client|远程调用|rpc` → feign 意图
- 结构推断: `/` 开头 → endpoint 意图
- 关键词: `kafka|topic|consumer` → mq 意图

**权重配置**:
- Graph: 0.4（结构关系优先）
- Sparse: 0.35（精确匹配）
- Semantic: 0.25（模糊匹配）
- Vector: 0.15（可选 ANN；默认关闭）

reindex 会自动重建 SQLite BM25。只有 semantic index 中存在 `dense_vector` 时才会同步 VectorIndex；full reindex 会重建完整 VectorIndex，partial / path-scoped reindex 会只 delete/upsert changed node 的 embedding。若当前 reindex 是 sparse-only 且没有 dense vectors，系统会保留已有 VectorIndex，避免一次默认 sparse reindex 悄悄清空本地 embedding backend 生成的向量。

reindex 汇总会透出 `semantic_backend`、`requested_semantic_backend`、`vector_scope`、`vector_candidate_count`、`dense_doc_count`、`vector_status`、`vector_disabled_reason`。其中 `vector_candidate_count` 表示按当前 scope 可向量化的核心节点数，`dense_doc_count` 表示实际生成 dense vector 的节点数；当 `vector_status=disabled|unavailable|no_candidates` 时，`vector_disabled_reason` 给出可操作原因。

真实 UCAP 验证中，`selective` scope 生成 47,633 个 dense docs。partial semantic rebuild 对单个 changed dense candidate 只重 encode 1 个 doc，VectorIndex sync 使用 `vector_sync_mode=partial`，只 delete/upsert 该 changed node，embedding 总数保持不变。当前 partial sync 的剩余主要成本来自 BM25 仍全量 rebuild，这是后续 P2 性能优化项。

### 8.2 Benchmark Trending 实现细节

**问题**: 无法知道哪条链路的 token 使用又变胖了。

**解决方案**: 时间序列记录 + 回归检测。

**回归检测算法**:
```python
# 将趋势点分为 recent（最近 5 个）和 historical（之前）
recent = points[-5:]
historical = points[:-5]

# 计算平均值
recent_avg_raw = sum(p.raw_tokens for p in recent) / len(recent)
historical_avg_raw = sum(p.raw_tokens for p in historical) / len(historical)

# 检测增长
change_pct = ((recent_avg - historical_avg) / historical_avg) * 100

# 超过阈值（默认 10%）则标记为回归
if change_pct > threshold:
    regressions.append(...)
```

**健康评分**:
- 基础分: 100
- 高严重度回归: -15 分/个
- 中严重度回归: -8 分/个
- 低节省率函数: -5 分/个

### 8.3 Unified Backend Query 实现细节

**问题**: 高频读取分散在多处，使用 `read_json*_prefer_backend` 不一致。

**解决方案**: 统一查询层 `UnifiedBackendQuery`。

**设计原则**:
- 所有高频读取通过统一 API
- 自动选择最优路径（SQLite 优先，JSONL fallback）
- 提供聚合能力（按 session/project/collection）

**典型用法**:
```python
# 之前（分散）
events = store.read_jsonl_prefer_backend("session-events.jsonl")
receipts = store.read_jsonl_prefer_backend("write-receipts.jsonl")

# 现在（统一）
with UnifiedBackendQuery(db_path) as backend:
    events = backend.query_session_events(session_id="xyz")
    receipts = backend.query_write_receipts(project="test")
    stats = backend.aggregate_by_session()
```

### 8.4 Drill-Down Navigation 实现细节

**问题**: ref/timeline/task 的导航需要大量手动切换。

**解决方案**: 渐进式钻取 + 上下文保留。

**渐进式披露**:
- Level 1: 摘要（始终显示，token 最少）
- Level 2: 详情（按需展开）
- Level 3: 相关项（进一步探索）

**钻取流程**:
```
expand_ref(ref_id)
  → Level 1 摘要
  → Level 2 详情
  → Level 3 相关项
  → reverse_links（反向导航）

drill_timeline(session_id, start_event_id)
  → 上下文窗口
  → 导航提示（has_more_before/after）

drill_task(task_id)
  → 任务摘要
  → timeline
  → write_receipts

build_handoff_context(session_id)
  → session_summary
  → key_points
  → open_questions
  → next_steps
```

### 8.5 Completion Audit 实现细节

**问题**: 文档容易与实现漂移。

**解决方案**: 自动化审计 + 设计决策记录。

**审计维度**:
1. **文档检查**: 关键文档存在性、SPECIAL_NOTES 完整性
2. **测试检查**: 测试文件存在性、pytest 配置
3. **实现检查**: 模块完整性
4. **设计一致性**: 冲突决策检测

**设计决策记录**:
```python
record_design_decision(
    workspace_file,
    topic="hybrid_retrieval",
    decision="使用 RRF 合并三种检索源",
    rationale="平衡精确性和召回率",
    alternatives=["简单加权", "学习排序"],
    impact="high"
)
```

**冲突检测**:
- 同一主题的多个决策会触发警告
- 最新决策优先，但保留历史

### 8.6 避免循环依赖

**问题**: `retrieval.hybrid` 需要导入 `orchestrator.common`，而 `orchestrator.query` 需要导入 `retrieval.hybrid`。

**解决方案**: 懒导入（lazy import）。

```python
# retrieval/hybrid.py
def _get_common_functions():
    """Lazy import to avoid circular dependency."""
    from ..orchestrator.common import tokenize, _rrf, _best_match
    return tokenize, _rrf, _best_match

# orchestrator/query.py
def memory_query_hybrid(...):
    # Lazy import
    from ..retrieval.hybrid import HybridRetrievalConfig, hybrid_retrieve, detect_query_intent
    ...
```

### 8.7 测试策略

**单元测试**: 每个模块的核心算法
- 意图检测
- 回归检测
- 评分计算
- 分类逻辑

**集成测试**: 所有模块可同时导入
- 无循环依赖
- 与现有模块兼容

**语法检查**: AST 解析 + 编译检查

## 9. 性能考虑

### 9.1 Hybrid Retrieval 性能

- Graph 检索: O(log n) 索引查找
- Sparse 检索: FTS5 全文索引
- BM25 检索: 倒排 posting-list 候选查询
- Semantic 检索: 离线稀疏语义或本地 dense semantic
- Vector 检索: sqlite-vec 或 brute-force fallback（可选，默认关闭）
- 合并排序: O(n log n)

**优化**: 
- 限制结果数量（limit 参数）
- 类型过滤减少候选集
- 懒加载 semantic 检索

### 9.2 Benchmark Trending 性能

- 写入: O(1) 追加
- 读取: O(n) 扫描 + 过滤
- 回归检测: O(n) 遍历

**优化**:
- 限制时间窗口（days 参数）
- 限制结果数量（limit 参数）

### 9.3 Unified Backend 性能

- SQLite 索引查询: O(log n)
- 聚合查询: O(n) 扫描
- JSONL fallback: O(n) 读取 + 解析

**优化**:
- 使用 SQLite 索引
- 限制扫描范围
- 缓存常用查询

## 10. Java CALLS_METHOD Precision Gate / Java 调用解析精度门禁

Java call resolver 的回归验证分两层：

- 公开仓库提交 evaluator、单元测试和脱敏说明。
- 真实 UCAP cases 与性能/精度基线保存在真实 workspace 的 `.memory-center/golden/`，不提交到本仓库。

CLI 用法：

```bash
memory-center eval-java-call-resolution \
  --workspace /path/to/.memory-center/workspace.yaml \
  --cases /path/to/.memory-center/golden/java-call-resolution.yaml
```

cases 文件只允许逻辑锚点：

```yaml
schema_version: 1
cases:
  - case_id: controller-to-service
    source: ExampleController#list
    expected_target: ExampleService#list
    min_confidence: 0.85
    expected_resolution_levels: [import, same_package]
    # 该入口中的其他高置信调用是合法旁路，不应当作误绑定。
    allowed_targets: [AuditService#record]
    # 明确禁止出现的同名误绑定；严格模式下命中即失败。
    forbidden_targets: [LegacyOrderService#list]
```

P1 真实 UCAP case 已覆盖 Controller -> Service interface、Controller -> ServiceImpl、ServiceImpl -> Mapper、same-class helper、static import 等路径。新增 case 时仍只写 `Class#method` 逻辑锚点，不写文件路径或私有源码片段。

Golden Benchmark 的 hybrid case 可选 `enable_vector: true`，用于验证 ANN 路径：

```yaml
schema_version: 1
cases:
  - case_id: vector-concept-query
    query: Feign 调用的鉴权拦截器
    mode: hybrid
    enable_vector: true
    expected_anchors:
      - FeignConfig#feignDecoder
    expected_edges: []
    max_latency_ms: 8000
```

Golden case 还支持 `mode: impact` 与 `mode: context`，分别验证影响分析和架构上下文；`project` 可用于同名类跨模块场景。三类常用回归分别是 `walkthrough`（全链路）、`impact`（改动影响）和 `context`（架构理解）。所有 case 仍只允许逻辑锚点，`forbidden_anchors` 用于阻止相似模块误命中。

可将当前结果保存为 portable baseline（只保存质量和性能指标，不保存 case、路径或 payload），后续 `eval-golden --baseline <file>` 会自动比较：

```bash
memory-center eval-golden-baseline-save --workspace /path/to/workspace.yaml --cases /path/to/cases.yaml --output /path/to/golden-baseline.json --label current
```

门禁指标：

- `edge_recall`：预期调用边是否在 graph 的 `CALLS_METHOD` 中出现。
- `high_confidence_expected_rate`：命中的预期边是否达到 case 的 `min_confidence`。
- `resolution_level_rate`：如配置 `expected_resolution_levels`，解析层级是否符合预期。
- `unresolved_rate`：预期链路没有命中或命中 unresolved 的比例。
- `allowed_high_confidence_edge_count`：已声明为合法旁路的高置信调用数量。
- `forbidden_high_confidence_edge_count`：命中 `forbidden_targets` 的高置信调用数量；传入 `--fail-on-forbidden-high-confidence` 时会让 CLI 门禁失败。

HTTP / MCP：

- HTTP: `/workspace/eval-java-call-resolution?workspace=...&cases=...&fail_on_forbidden_high_confidence=true`
- MCP: `mc_admin(action="eval_java_call_resolution", name="<cases.yaml>", strict=true)`

审阅未分类高置信边时，使用下列入口。它只返回 `Class#method` 逻辑锚点、解析层级、置信度和关联 case ID，不返回文件路径或源码片段：

```bash
memory-center eval-java-call-resolution-review \
  --workspace /path/to/.memory-center/workspace.yaml \
  --cases /path/to/.memory-center/golden/java-call-resolution.yaml \
  --limit 200
```

- HTTP: `/workspace/eval-java-call-resolution-review?workspace=...&cases=...&limit=200`
- MCP: `mc_admin(action="eval_java_call_resolution_review", name="<cases.yaml>", limit=200)`

审阅后仅把逻辑锚点写回对应 case 的 `allowed_targets` 或 `forbidden_targets`；不要把私有路径、源码片段或完整运行 payload 写入公开仓库。

This gate intentionally validates resolver output at the graph edge layer,
before walkthrough/report formatting, so parser/retrieval/reasoning changes
cannot hide a broken Java call edge.

该门禁故意在 graph edge 层做验证，而不是只看最终报告文本，避免
walkthrough / retrieval / reasoning 的展示层优化掩盖 Java 调用边解析退化。

## 11. 未来优化方向

### 11.1 Hybrid Retrieval

- 学习排序（Learning to Rank）
- 查询扩展（Query Expansion）
- 反馈循环（用户点击 → 权重调整）

### 11.2 Benchmark Trending

- 更细粒度的回归归因
- 自动修复建议
- 与 CI/CD 集成
- 使用 `record_baseline_sample()` 记录脱敏 portable sample；只允许 operation、topology size、duration、result count、quality score、parser 和 timestamp
- 使用 `compare_baseline_samples()` 比较 median / p95 延迟与质量下降，样本中禁止写入路径或任意 payload

### 11.3 Unified Backend

- 更多聚合维度
- 查询缓存
- 增量更新

### 11.4 Drill-Down Navigation

- 图形化导航
- 智能推荐下一步
- 跨 workspace 钻取

### 11.5 Completion Audit

- 实时审计（文件变更触发）
- 自动修复建议
- 与 PR 流程集成
