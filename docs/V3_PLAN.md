# Memory Center 3.0 Plan / 记忆中心 3.0 方案

> **核心命题：让 AI 真正读懂代码。**
>
> **Core thesis: Make AI agents genuinely understand codebases, not just search them.**

## 1. 文档定位 / Document Purpose

这份文档是 Memory Center 3.0 的总体方案。它回答三个问题：

This document is the master plan for Memory Center 3.0. It answers three questions:

1. 3.0 要解决什么根本问题？/ What fundamental problem does 3.0 solve?
2. 怎么从"代码搜索引擎"进化到"代码知识图谱"？/ How do we evolve from a code search engine to a code knowledge graph?
3. 具体分几阶段做，每阶段的交付物是什么？/ What are the phases and their deliverables?

### 3.0 的一句话定义

**Memory Center 3.0 = 代码知识图谱 + 向量语义检索 + 图感知推理**

当前 2.x 版本已经做到了"索引代码关系 → 图存储 → MCP 查询"的基本链路。但 AI Agent 对代码的理解仍然停留在"关键词匹配 + 邻居展开"的层面。

3.0 的目标是让 Agent 能像一个读过全部代码的高级工程师一样思考：不仅知道"谁调用了谁"，还能理解"为什么这样调用"、"改了会影响什么"、"历史上踩过什么坑"。

The current 2.x release has built the basic pipeline: index code relationships → graph store → MCP queries. But AI agents still reason about code at the "keyword match + neighbor expansion" level.

3.0 aims to make the agent think like a senior engineer who has read the entire codebase: not just "who calls whom," but "why it's called this way," "what breaks if changed," and "what pitfalls exist in history."

---

## 2. 核心问题 / Core Problems

### 2.1 当前瓶颈 / Current Bottlenecks

| 问题 | 现状 | 3.0 目标 |
|------|------|----------|
| **AI 只能搜索，不能推理** | `mc_lookup` 返回节点列表，Agent 自己拼上下文 | 图感知推理引擎，自动组装影响链路和上下文 |
| **语义检索是暴力扫描** | `_sparse_semantic_query` 遍历全部 doc 做 BM25 打分 | 倒排索引 + 向量 ANN，查询延迟从 O(N) 降到 O(log N) |
| **不支持原生向量搜索** | 仅有 BM25 sparse 和可选 sentence-transformers，无 ANN 索引 | 原生向量检索支持（sqlite-vec + 可选 faiss） |
| **代码理解深度不够** | 正则解析 Java 注解，无法理解控制流、数据流、泛型 | Tree-sitter AST 解析 + 轻量数据流分析 |
| **跨服务推理靠人工拼接** | group_chain 需要显式指定 group | 自动跨工作区推理，基于 bridge 图自动追踪 |
| **索引完全串行** | 单线程 os.walk + 逐文件解析 | 并行索引 + 增量 diff |
| **存储层碎片化** | graph.db + memory.db 双 SQLite，无连接池 | 统一存储层 + WAL 模式 + 连接池 |
| **返回类型全是 Dict** | 全库 Dict[str, Any]，无类型安全 | Pydantic v2 强类型返回 |
| **测试覆盖 ~21%** | 3,550 行测试 / 16,600 行源码 | 目标 50%+，重点覆盖 orchestrator 和 graph |

### 2.2 "让 AI 真正读懂代码"的三层含义

**Layer 1: 结构感知 / Structural Awareness**
- AI 知道这个项目有哪些服务、类、方法、接口、消息队列
- 当前状态：✅ 已实现（indexer + graph store）

**Layer 2: 关系推理 / Relationship Reasoning**
- AI 能沿着调用链、Feign 契约、MQ 消息流、配置传播自动追踪影响面
- 当前状态：🟡 部分实现（graph neighbors + group chain，但缺少推理引擎）

**Layer 3: 语义理解 / Semantic Understanding**
- AI 能理解"这段代码在做什么业务"、"这个改动的风险模式是什么"、"历史上类似改动踩过什么坑"
- 当前状态：🔴 未实现（语义检索仅做节点匹配，不做代码语义理解）

**3.0 要把 Layer 2 做透，把 Layer 3 从 0 推到可用。**

---

## 3. 代码知识图谱 / Code Knowledge Graph

### 3.1 定义

代码知识图谱（Code KG）不是传统意义上的 RDF/OWL 知识图谱。它是一个**以代码实体为节点、以工程关系为边、以置信度为权重、以语义向量为辅助**的可查询图结构。

Code Knowledge Graph (Code KG) is not a traditional RDF/OWL knowledge graph. It is a queryable graph structure where **code entities are nodes, engineering relationships are edges, confidence scores are weights, and semantic vectors provide auxiliary retrieval.**

### 3.2 与当前 Graph 的区别

| 维度 | 2.x Graph | 3.0 Code KG |
|------|-----------|-------------|
| 节点 | 代码实体（Class/Method/Field...） | 代码实体 + 语义摘要节点 + 业务意图节点 |
| 边 | 静态关系（CALLS/INJECTS/IMPORTS...） | 静态关系 + 推断关系 + 时序关系 + 跨工作区桥接 |
| 查询 | 图遍历（BFS neighbors） | 图遍历 + 图模式匹配 + 路径查询 + 子图提取 |
| 索引 | FTS5 全文 + BM25 sparse | FTS5 + BM25 + 向量 ANN + 倒排索引 |
| 推理 | 无 | 轻量规则推理引擎（传递性、约束检查、模式识别） |

### 3.3 新增节点类型

| 节点类型 | 说明 | 来源 |
|----------|------|------|
| **CodeSummary** | 文件/类/方法的语义摘要（由 LLM 生成或规则提取） | 语义索引层 |
| **BusinessIntent** | 业务意图标签（如"订单创建"、"支付回调"） | LLM 标注或规则推断 |
| **RiskPattern** | 风险模式（如"无幂等消费"、"破坏性契约变更"） | 规则引擎 + 历史 case |
| **ArchitecturalLayer** | 架构层（controller / service / dao / infra） | 包名推断 |
| **DataFlowNode** | 数据流节点（DTO 字段、配置值、MQ 消息体字段） | AST 深度分析 |

### 3.4 新增边类型

| 边类型 | 说明 | 语义强度 |
|--------|------|----------|
| **TRANSITIVELY_CALLS** | 传递调用（A→B→C 推断 A 调用 C） | derived (0.4-0.6) |
| **DATA_FLOWS_TO** | 数据流（DTO 字段从 Controller 流到 MQ 消息体） | inferred (0.5-0.7) |
| **CONFIG_PROPAGATES** | 配置传播（配置项被多个服务读取） | inferred (0.7) |
| **HISTORICALLY_RELATED** | 历史关联（两个文件在同一 case 中被修改） | derived (0.3-0.5) |
| **SEMANTIC_SIMILAR** | 语义相似（向量余弦相似度 > 阈值） | derived (0.3-0.8) |
| **RISK_CORRELATED** | 风险关联（修改 A 大概率需要检查 B） | derived (0.4-0.7) |

### 3.5 图模式查询（Graph Pattern Matching）

3.0 将支持声明式图模式查询，让 Agent 可以用自然语言描述的模式在图上做匹配：

3.0 will support declarative graph pattern matching, allowing agents to match patterns described in natural language:

```
# 示例：找到所有"没有幂等保护的 MQ 消费者"
Pattern: MQConsumer -[CONSUMES_TOPIC]-> MQTopic
Filter: MQConsumer.method NOT CONTAINS "idempotent" OR "幂等"
Risk: high

# 示例：找到所有"跨 3 个以上服务的 Feign 调用链"
Pattern: FeignClient -[CALLS_SERVICE]-> Service -> FeignClient -[CALLS_SERVICE]-> Service -> ...
Filter: chain_length >= 3
Risk: medium

# 示例：找到"修改 DTO 但没检查下游"的场景
Pattern: Class(has_annotation="DTO") -[DECLARES]-> Field
Filter: Field NOT IN any mc_analyze(checklist) in last 7 days
Risk: high
```

实现方式：基于 SQLite 递归 CTE + Python 规则引擎，不需要引入外部图数据库。

Implementation: SQLite recursive CTE + Python rule engine. No external graph database required.

---

## 4. 向量搜索支持 / Vector Search Support

### 4.1 当前状态

**当前 Memory Center 部分支持向量搜索，但不是原生能力：**

- 语义索引（`semantic.py`）默认后端是 **sparse BM25**，纯 Python 实现
- 可选后端是 `sentence-transformers`，启用后会生成 dense vector 并做**暴力全量扫描**（`_dense_semantic_query` 遍历所有 doc 计算余弦相似度）
- 没有 ANN（Approximate Nearest Neighbor）索引，5000+ 节点时查询会明显变慢
- dense vector 存在 JSON 文件里，不在 SQLite 中

**Current Memory Center partially supports vector search, but it's not a native capability:**

- The semantic index (`semantic.py`) defaults to **sparse BM25**, implemented in pure Python
- The optional `sentence-transformers` backend generates dense vectors but uses **brute-force full scan** (`_dense_semantic_query` iterates all docs to compute cosine similarity)
- No ANN (Approximate Nearest Neighbor) index exists; queries slow down noticeably at 5000+ nodes
- Dense vectors are stored in JSON files, not in SQLite

### 4.2 3.0 向量搜索方案

#### 方案选型

| 方案 | 优势 | 劣势 | 推荐度 |
|------|------|------|--------|
| **sqlite-vec**（SQLite 扩展） | 零外部依赖，与现有 SQLite 无缝集成，WAL 兼容 | 需要编译 C 扩展，macOS/Linux 有预编译包 | ⭐⭐⭐⭐⭐ |
| **faiss**（Facebook ANN） | 性能极好，支持 IVF/HNSW/PQ | 重量级依赖，需要额外索引文件 | ⭐⭐⭐ |
| **usearch** | 轻量、单文件、支持多语言 | 生态较小 | ⭐⭐⭐⭐ |
| **numpy 暴力扫描** | 零依赖 | O(N) 不可扩展 | ⭐⭐（当前状态） |

**推荐方案：sqlite-vec 作为默认，faiss 作为可选高性能后端。**

**Recommended: sqlite-vec as default, faiss as optional high-performance backend.**

理由：
- sqlite-vec 让向量和代码图谱共存在同一个 SQLite 数据库里，不需要额外的索引文件管理
- 已有的 `GraphStore` 和 `MemoryBackendStore` 只需要加一列 vector 就能支持向量查询
- 用户不需要额外安装任何东西（sqlite-vec 有 pip 包 `sqlite-vec`）

#### 架构设计

```
┌─────────────────────────────────────────────────┐
│                 mc_lookup(mode="auto")            │
│                     ↓ intent detect               │
│    ┌────────────┬────────────┬────────────┐      │
│    │ Graph      │ Sparse     │ Vector     │      │
│    │ Traversal  │ BM25/FTS5  │ ANN Search │      │
│    │ (BFS)      │ (inverted) │ (sqlite-vec)│     │
│    └─────┬──────┴─────┬──────┴─────┬──────┘     │
│          └────────────┼────────────┘             │
│                       ↓                           │
│              Hybrid Merge & Rank                  │
│              (RRF + intent boost)                 │
│                       ↓                           │
│              Neighbor Enrichment                  │
│                       ↓                           │
│              Progressive Disclosure               │
└─────────────────────────────────────────────────┘
```

#### 实现步骤

**Phase 1：倒排索引替换暴力 BM25**（优先级最高）

当前 `_sparse_semantic_query` 每次查询都遍历全部 doc。改为：

```python
# 构建阶段：为每个 token 建 posting list
# inverted_index[token] = [(doc_id, tf_idf_weight), ...]

# 查询阶段：只遍历命中 token 的 doc
candidate_docs = set()
for token in query_tokens:
    candidate_docs.update(inverted_index.get(token, []))
# 只对 candidate_docs 做 BM25 打分
```

预期收益：查询延迟从 O(N) 降到 O(K)，K = 命中文档数，通常 K << N。

**Phase 2：sqlite-vec 向量索引**

```sql
-- 新增 vec 列
ALTER TABLE nodes ADD COLUMN embedding BLOB;

-- 创建向量索引
CREATE VIRTUAL TABLE node_vec USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[384]   -- all-MiniLM-L6-v2 维度
);

-- 向量查询
SELECT id, distance
FROM node_vec
WHERE embedding MATCH @query_vector
ORDER BY distance
LIMIT 20;
```

**Phase 3：Hybrid 三路融合优化**

统一到一个 `HybridRetrievalEngine` 类：

```python
class HybridRetrievalEngine:
    def __init__(self, graph_db_path, semantic_config):
        self.graph = GraphStore(graph_db_path)
        self.inverted_index = InvertedIndex(graph_db_path)
        self.vector_index = VectorIndex(graph_db_path)  # sqlite-vec

    def retrieve(self, query, intent, limit=20):
        # 1. Graph traversal (结构关系)
        graph_hits = self._graph_retrieve(query, intent, limit * 2)
        # 2. Sparse BM25 (精确匹配)
        sparse_hits = self._sparse_retrieve(query, limit * 2)
        # 3. Vector ANN (语义相似)
        vector_hits = self._vector_retrieve(query, limit * 2)
        # 4. Merge + rank
        return self._merge_and_rank(graph_hits, sparse_hits, vector_hits, intent, limit)
```

### 4.3 向量搜索的适用场景

| 场景 | 适合用向量搜索吗 | 原因 |
|------|------------------|------|
| 找类/方法的精确名称 | ❌ 不适合 | FTS5 精确匹配更好 |
| 找"和订单创建相关的代码" | ✅ 非常适合 | 语义理解，不需要精确关键词 |
| 找"历史上类似的 bug" | ✅ 非常适合 | case 描述的语义匹配 |
| 找 Feign 调用链 | ❌ 不适合 | 图遍历更精确 |
| 找"改了这个 DTO 影响谁" | ❌ 不适合 | 图遍历 + 影响分析 |
| 找"类似的配置项" | ✅ 适合 | 配置值的语义相似性 |
| 跨项目找"类似功能的代码" | ✅ 非常适合 | 向量空间中的跨项目聚类 |

**结论：向量搜索是图遍历的补充，不是替代。两者结合才是完整的代码理解能力。**

**Conclusion: Vector search complements graph traversal, not replaces it. The combination of both is the complete code understanding capability.**

---

## 5. 存储层重构 / Storage Layer Refactoring

### 5.1 统一数据库

**当前问题：**
- `graph.db`（GraphStore）和 `memory.db`（MemoryBackendStore）是两个独立 SQLite 文件
- 每次 `mc_lookup` 调用链里，`memory_query` 打开 GraphStore 3 次（query.py:68, query.py:84, query.py:98）
- 没有 WAL 模式，没有连接池

**3.0 方案：**

```python
class UnifiedStore:
    """Single SQLite database for graph + memory + vectors."""

    def __init__(self, db_path: Path):
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        # ... init all tables (nodes, edges, json_records, refs, node_vec, ...)
```

收益：
- 去掉双 DB 管理的复杂度
- 连接复用，减少 TCP/文件句柄开销
- WAL 模式允许并发读
- 向量索引和图索引在同一事务中保持一致

### 5.2 GraphStore 性能优化

**`neighbors()` 改为递归 CTE：**

```sql
-- 当前：每层 BFS 一次查询，depth=2 就是 2 次
-- 3.0：一条递归 CTE 搞定
WITH RECURSIVE chain(source_id, target_id, type, depth) AS (
    SELECT e.source_id, e.target_id, e.type, 1
    FROM edges e
    WHERE e.source_id = ? OR e.target_id = ?
    UNION ALL
    SELECT e.source_id, e.target_id, e.type, c.depth + 1
    FROM edges e
    JOIN chain c ON (e.source_id = c.target_id OR e.target_id = c.source_id)
    WHERE c.depth < ?
)
SELECT DISTINCT * FROM chain LIMIT ?;
```

### 5.3 连接池

```python
import sqlite3
from contextlib import contextmanager

class SQLitePool:
    """Simple connection pool for SQLite with WAL mode."""

    def __init__(self, db_path: Path, pool_size: int = 4):
        self._db_path = db_path
        self._pool = queue.SimpleQueue()
        for _ in range(pool_size):
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._pool.put(conn)

    @contextmanager
    def connection(self):
        conn = self._pool.get()
        try:
            yield conn
        finally:
            self._pool.put(conn)
```

---

## 6. 索引引擎升级 / Indexer Upgrades

### 6.1 并行索引

**当前问题：** `indexer.py` 单线程遍历 + 解析。

**3.0 方案：**

```python
from concurrent.futures import ThreadPoolExecutor

def reindex_workspace_parallel(config, store, *, max_workers=8):
    # Phase 1: 并行扫描 + 解析
    java_files = []
    config_files = []
    for svc in config.services:
        for path in walk_project(config.resolve_service_path(svc)):
            if path.suffix == ".java":
                java_files.append((svc, path))
            elif path.name in CONFIG_NAMES:
                config_files.append((svc, path))

    # 并行解析 Java 文件（I/O 密集型，线程池足够）
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_parse_java_file, svc, path): (svc, path)
            for svc, path in java_files
        }
        results = [f.result() for f in as_completed(futures)]

    # Phase 2: 串行构建图（需要全局状态）
    # ... build graph from results ...
```

预期收益：索引速度提升 3-5x（取决于 CPU 核数和磁盘 I/O）。

### 6.2 Tree-sitter AST 解析器

**当前问题：** `RegexJavaParser` 对复杂嵌套场景有漏报。

**3.0 方案：** 实现 `TreeSitterJavaParser`，共享 `JavaParser` 协议。

```python
class TreeSitterJavaParser:
    """Tree-sitter based Java parser for higher accuracy."""

    name = "tree-sitter"

    def parse(self, text: str, file_path: str) -> JavaParseResult:
        import tree_sitter_java as tsjava
        from tree_sitter import Language, Parser

        parser = Parser(Language(tsjava.language()))
        tree = parser.parse(bytes(text, "utf8"))

        # 用 AST query 提取：类、方法、字段、注解、import、调用关系
        # 比正则更准确，尤其对匿名内部类、泛型、注解参数内换行
        ...
```

策略：默认 regex（零依赖），opt-in tree-sitter（更准确）。索引结果带 `parser` 字段标记来源。

### 6.3 增量 diff 索引

当前 partial 模式已经做了 `_merge_index_rows`，但还是要读全量旧索引。3.0 改为：

1. 用 `git diff --name-status` 检测变更文件
2. 只 re-parse 变更文件
3. 用图节点 ID 做精确的 upsert/delete，而不是全量 merge

```python
def incremental_reindex(config, store):
    changed = git_changed_files(store.base_dir)
    if not changed:
        return {"mode": "no-change"}

    added_modified = [f for f in changed if f.status in ("A", "M")]
    deleted = [f for f in changed if f.status == "D"]

    # 只解析变更文件
    new_symbols = [parse_java_file(f) for f in added_modified]
    # 精确删除旧节点
    for f in deleted:
        graph.remove_by_file(f.path)
    # Upsert 新节点
    graph.bulk_write(new_nodes, new_edges)
```

---

## 7. 编排层瘦身 / Orchestrator Refactoring

### 7.1 模块拆分

**当前问题：**
- `orchestrator/query.py` 1,072 行，承担检索 + 合并 + 排序 + 渐进视图 + evidence summary + project 匹配 + FQN 推断
- `orchestrator/group.py` 1,134 行，承担 bridge 构建 + 跨工作区查询 + 影响分析 + 链路拼接

**3.0 拆分方案：**

```
memory_center/core/
├── orchestrator/
│   ├── query.py          # 精简到 ~400 行，只保留编排逻辑
│   ├── impact.py         # 影响分析编排
│   ├── session.py        # 会话管理
│   ├── sync.py           # 同步逻辑
│   ├── resume.py         # 恢复逻辑
│   ├── compact.py        # 压缩逻辑
│   ├── eval.py           # 评测逻辑
│   ├── group.py          # 精简到 ~500 行，只保留编排
│   ├── workspace.py      # 工作区管理
│   ├── write.py          # 写入逻辑
│   └── common.py         # 精简到 ~300 行
├── presentation/          # 新增：渐进式视图构建
│   ├── __init__.py
│   ├── progressive.py    # _build_*_progressive_view 系列
│   ├── evidence.py       # evidence summary 构建
│   └── compact.py        # compact 视图逻辑
├── matching/              # 新增：匹配与推断
│   ├── __init__.py
│   ├── project.py        # _project_matches, _infer_project_from_fqn
│   ├── symbol.py         # _best_match, symbol resolution
│   └── intent.py         # intent detection（从 hybrid.py 移入）
├── bridges/               # 新增：跨工作区桥接
│   ├── __init__.py
│   ├── builder.py        # _build_group_bridges
│   ├── matcher.py        # bridge 匹配逻辑
│   └── stitcher.py       # chain stitching
└── reasoning/             # 新增：图推理引擎
    ├── __init__.py
    ├── patterns.py        # 图模式匹配
    ├── transitive.py      # 传递性推理
    └── risk.py            # 风险模式识别
```

### 7.2 mc_admin 参数简化

**当前问题：** `server.py` 的 `mc_admin` 有 50+ 个参数。

**3.0 方案：** 参数改为 JSON payload。

```python
@mcp.tool()
def mc_admin(action: str, payload: str = "{}"):
    """Admin and utility operations. payload is a JSON string whose schema depends on action."""
    params = json.loads(payload)
    handler = _DISPATCH.get(action)
    if handler is None:
        raise ValueError(f"Unknown action: {action}")
    return {"action": action, "result": handler(**params)}
```

### 7.3 类型安全

**当前问题：** 全库 Dict[str, Any]，无类型检查。

**3.0 方案：** 核心返回类型用 Pydantic v2。

```python
from pydantic import BaseModel

class LookupResult(BaseModel):
    query: str
    mode_used: str
    results: list[RetrievalItem]
    retrieval_summary: RetrievalSummary
    progressive: ProgressiveView

class ImpactResult(BaseModel):
    target: str
    found: bool
    risk_level: str
    confirmed_impacts: list[ImpactItem]
    probable_impacts: list[ImpactItem]
    possible_impacts: list[ImpactItem]

class RetrievalItem(BaseModel):
    node_id: str
    node: NodeInfo
    score: float
    sources: list[str]
    evidence: dict[str, Any]
```

---

## 8. 测试与可观测性 / Testing & Observability

### 8.1 测试覆盖目标

| 模块 | 当前行数 | 当前测试 | 目标覆盖率 |
|------|----------|----------|------------|
| core/graph.py | 429 | 间接 | 80% |
| core/semantic.py | 368 | 间接 | 70% |
| core/indexer.py | 765 | 间接 | 60% |
| core/orchestrator/query.py | 1,072 | 间接 | 60% |
| core/orchestrator/group.py | 1,134 | 间接 | 60% |
| core/orchestrator/common.py | 843 | 间接 | 60% |
| mcp/server.py | 612 | 254 行 | 70% |
| hooks/runner.py | 549 | 203 行 | 70% |

**核心策略：** 引入 fixture 工厂，预构建小型 graph + memory，避免每次测试都从头索引。

```python
@pytest.fixture
def mini_workspace(tmp_path):
    """Pre-built mini workspace with 3 services, 10 classes, 5 Feign clients."""
    store = create_mini_workspace(tmp_path, services=3, classes=10, feigns=5)
    return store
```

### 8.2 结构化日志

```python
import structlog

logger = structlog.get_logger("memory_center")

def mc_lookup(query, mode, ...):
    log = logger.bind(query=query, mode=mode)
    log.info("lookup.start")
    result = ...
    log.info("lookup.complete", result_count=len(result["results"]), elapsed_ms=elapsed)
```

### 8.3 关键指标

| 指标 | 说明 |
|------|------|
| `mc_lookup.latency_ms` | 查询延迟 |
| `mc_analyze.latency_ms` | 分析延迟 |
| `reindex.duration_s` | 索引耗时 |
| `graph.node_count` | 图节点数 |
| `graph.edge_count` | 图边数 |
| `semantic.doc_count` | 语义索引文档数 |
| `tool.adoption_rate` | Memory Center 工具使用率 |
| `cache.hit_rate` | 缓存命中率 |

---

## 9. 实施路线 / Implementation Roadmap

### Phase 1：存储与检索基础重构（4-6 周）

> 目标：把地基打牢，为后续所有优化铺路。

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| 统一 SQLite 数据库（graph + memory + vec） | P0 | 1 周 |
| 开启 WAL 模式 + 连接池 | P0 | 2 天 |
| `neighbors()` 改为递归 CTE | P0 | 3 天 |
| 倒排索引替换暴力 BM25 | P0 | 1 周 |
| GraphStore 单例注入 | P1 | 2 天 |
| 编排层模块拆分（presentation/matching/bridges） | P1 | 1 周 |

**交付物：**
- 统一存储层 `UnifiedStore`
- 倒排索引 `InvertedIndex`
- 拆分后的 orchestrator 子模块
- 查询延迟 benchmark（before/after）

### Phase 2：向量搜索与代码知识图谱（4-6 周）

> 目标：让 AI 能用语义理解代码，而不只是关键词匹配。

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| sqlite-vec 集成 | P0 | 1 周 |
| 向量索引构建 + 增量更新 | P0 | 1 周 |
| HybridRetrievalEngine 统一检索类 | P0 | 1 周 |
| 三路融合优化（graph + sparse + vector） | P1 | 1 周 |
| 新增节点类型（CodeSummary, RiskPattern, ArchitecturalLayer） | P1 | 1 周 |
| 新增边类型（TRANSITIVELY_CALLS, DATA_FLOWS_TO, SEMANTIC_SIMILAR） | P1 | 1 周 |

**交付物：**
- `HybridRetrievalEngine` 类
- sqlite-vec 向量索引
- 向量搜索 benchmark
- 代码知识图谱 schema 升级

### Phase 3：推理引擎与索引升级（4-6 周）

> 目标：从"搜索"进化到"推理"。

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| 图模式匹配引擎 | P0 | 2 周 |
| 传递性推理（A→B→C 推断 A→C） | P1 | 1 周 |
| 风险模式识别 | P1 | 1 周 |
| Tree-sitter Java 解析器 | P1 | 1 周 |
| 并行索引 | P1 | 1 周 |
| 增量 diff 索引 | P2 | 1 周 |

**交付物：**
- `reasoning/` 模块（patterns, transitive, risk）
- `TreeSitterJavaParser`
- 并行索引 benchmark（before/after）
- 风险模式规则库

### Phase 4：类型安全、测试与可观测性（3-4 周）

> 目标：让系统可维护、可信赖。

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| 核心返回类型 Pydantic v2 化 | P0 | 1 周 |
| mc_admin 参数简化（JSON payload） | P1 | 2 天 |
| structlog 结构化日志 | P1 | 3 天 |
| orchestrator 单元测试 | P0 | 2 周 |
| GraphStore 图操作测试 | P0 | 1 周 |
| Fixture 工厂 | P1 | 3 天 |
| 关键指标埋点 | P2 | 3 天 |

**交付物：**
- Pydantic 模型定义（`models/v3/`）
- 测试覆盖率报告（目标 50%+）
- 结构化日志配置
- 指标 dashboard

---

## 10. 向后兼容 / Backward Compatibility

### 10.1 MCP 工具兼容

- 8 个 facade 工具（`mc_start` / `mc_lookup` / `mc_analyze` / `mc_sync` / `mc_resume` / `mc_handoff` / `mc_close` / `mc_admin`）**接口不变**
- 新增能力通过新参数暴露（如 `mc_lookup(mode="vector")`, `mc_admin(action="graph_pattern")`）
- 旧参数继续支持，新参数可选

### 10.2 存储兼容

- 3.0 首次运行时自动迁移：`graph.db` + `memory.db` → 统一 `memory-center.db`
- 迁移脚本保留旧文件作为备份
- semantic-node-index.json 自动迁移到 SQLite

### 10.3 配置兼容

- `workspace.yaml` schema 向后兼容
- 新增 `vector_backend` 配置项（默认 `sqlite-vec`，可选 `faiss`）
- 新增 `indexer.parser` 配置项（默认 `regex`，可选 `tree-sitter`）

---

## 11. 成功指标 / Success Metrics

| 指标 | 2.x 基线 | 3.0 目标 |
|------|----------|----------|
| `mc_lookup` 平均延迟（5000 节点） | ~200ms | <50ms |
| `reindex` 耗时（500 个 Java 文件） | ~30s | <10s |
| 语义查询延迟（5000 doc） | ~100ms（暴力扫描） | <10ms（倒排 + ANN） |
| 测试覆盖率 | ~21% | >50% |
| 向量搜索召回率（top-20） | N/A | >85% |
| 图模式匹配支持 | 无 | 支持 5+ 内置模式 |
| Agent 代码理解准确率（人工评估） | 基线 | +30% |

---

## 12. 风险与缓解 / Risks & Mitigations

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| sqlite-vec 编译问题（Windows） | 向量搜索不可用 | fallback 到 numpy 暴力扫描 + 倒排索引 |
| 统一 DB 迁移失败 | 数据丢失 | 迁移前备份旧文件，支持回滚 |
| Tree-sitter 解析结果与 regex 不一致 | 索引结果差异 | 双 parser 对比测试，渐进切换 |
| Pydantic v2 性能开销 | 大结果集序列化慢 | 只在 facade 层用 Pydantic，内部仍用 dict |
| 并行索引的线程安全 | 数据竞争 | SQLite WAL + 写入串行化（只并行读/解析） |

---

## 13. 与外部项目的对比 / Competitive Landscape

### 13.1 Understand-Anything

[Understand-Anything](https://github.com/Lum1104/Understand-Anything) 侧重**交互式代码理解 workbench**，提供可视化的代码导航和 drill-down。

**可借鉴：** 交互式 onboarding 体验、workbench UI 模式。

**Memory Center 的优势：** MCP 原生接入、图谱深度索引、跨工作区推理、经验沉淀。

### 13.2 CodeGraph

[CodeGraph](https://github.com/colbymchenry/codegraph) 侧重**代码图谱的可视化和查询**，提供 VS Code 插件级别的代码关系浏览。

**可借鉴：** 图可视化交互、VS Code 集成模式。

**Memory Center 的优势：** MCP facade 设计、混合检索引擎、分层记忆模型、多 Agent 协作。

### 13.3 Memory Center 3.0 的差异化

| 维度 | Understand-Anything | CodeGraph | Memory Center 3.0 |
|------|---------------------|-----------|-------------------|
| 核心定位 | 代码理解 workbench | 代码图谱可视化 | AI Agent 项目记忆服务 |
| 接入方式 | Web UI | VS Code 插件 | MCP 原生 |
| 检索能力 | 全文搜索 | 图查询 | 混合三路检索（graph + sparse + vector） |
| 推理能力 | 无 | 无 | 图模式匹配 + 传递推理 + 风险识别 |
| 记忆能力 | 无 | 无 | L0-L3 分层记忆 + 经验沉淀 |
| 跨项目 | 不支持 | 不支持 | 跨工作区 bridge + group chain |
| 多 Agent | 不支持 | 不支持 | 多模型 handoff + budget 适配 |

---

## 附录 A：技术选型清单 / Technology Choices

| 组件 | 选型 | 理由 |
|------|------|------|
| 向量索引 | sqlite-vec（默认） + faiss（可选） | 零外部依赖，与 SQLite 无缝集成 |
| AST 解析 | tree-sitter-java | 成熟、支持增量解析、多语言 |
| 类型系统 | Pydantic v2 | 性能好、生态好、v2 比 v1 快 5-50x |
| 日志 | structlog | 结构化、可配置、性能好 |
| 测试 | pytest + hypothesis | 已有基础，hypothesis 做属性测试 |
| 序列化 | orjson（可选） | 比 json 快 2-10x，大结果集场景有用 |

## 附录 B：代码知识图谱本体扩展 / Code KG Ontology Extension

在 [ONTOLOGY.md](./ONTOLOGY.md) 基础上，3.0 新增以下本体定义：

### B.1 新增实体

```yaml
CodeSummary:
  description: "代码实体的语义摘要"
  source: "LLM 生成 或 规则提取"
  fields: [entity_id, summary_text, generated_by, confidence]

BusinessIntent:
  description: "业务意图标签"
  source: "LLM 标注 或 规则推断"
  fields: [intent_id, label, description, related_entities]

RiskPattern:
  description: "风险模式"
  source: "规则引擎 + 历史 case"
  fields: [pattern_id, pattern_type, severity, description, affected_entity_types]

ArchitecturalLayer:
  description: "架构层"
  source: "包名推断"
  fields: [layer_id, layer_type, package_pattern]
  layer_types: [controller, service, repository, infrastructure, common, gateway]

DataFlowNode:
  description: "数据流节点"
  source: "AST 深度分析"
  fields: [flow_id, source_entity, target_entity, field_path, data_type]
```

### B.2 新增关系

```yaml
TRANSITIVELY_CALLS:
  source: "图推理引擎"
  confidence_range: [0.4, 0.6]
  semantic_strength: "derived"
  description: "通过传递性推断的调用关系"

DATA_FLOWS_TO:
  source: "数据流分析"
  confidence_range: [0.5, 0.7]
  semantic_strength: "inferred"
  description: "数据从一个实体流向另一个实体"

CONFIG_PROPAGATES:
  source: "配置分析"
  confidence_range: [0.7, 0.7]
  semantic_strength: "inferred"
  description: "配置项被多个服务读取"

HISTORICALLY_RELATED:
  source: "历史 case 分析"
  confidence_range: [0.3, 0.5]
  semantic_strength: "derived"
  description: "两个实体在历史 case 中被关联修改"

SEMANTIC_SIMILAR:
  source: "向量检索"
  confidence_range: [0.3, 0.8]
  semantic_strength: "derived"
  description: "两个实体在语义向量空间中相似"

RISK_CORRELATED:
  source: "风险模式引擎"
  confidence_range: [0.4, 0.7]
  semantic_strength: "derived"
  description: "修改一个实体时，另一个实体有风险"
```

---

**Document version:** 3.0-draft-3
**Last updated:** 2026-06-02
**Author:** Memory Center Contributors

---

## 14. UI 与可观测性 / UI & Observability

### 14.1 当前 UI 现状

当前 Memory Center 的 UI 能力分布在三个层面：

| 层面 | 实现 | 现状 |
|------|------|------|
| **HTTP Workbench** | `http/server.py` + `exporters.py` | 有 10 个 HTML 页面（dashboard、timeline、receipts、usage 等），但样式原始、无交互 |
| **CLI** | `cli/main.py`（Typer + Rich） | 命令行输出有颜色和表格，但无可视化 |
| **MCP Prompts** | `server.py` 里的 `detect_impact` / `spring_cloud_safe_change` | 只有 2 个 prompt，引导能力弱 |

**核心问题：没有真正的可观测性仪表盘，开发者无法一眼看到"我的工作区现在什么状态"。**

### 14.2 3.0 Dashboard 方案

#### 14.2.1 交互式 Web Dashboard

把当前 `exporters.py` 的静态 HTML 升级为 **单页应用（SPA）**，用 `memory-center serve-http` 启动时自动提供。

**核心页面：**

| 页面 | 功能 | 优先级 |
|------|------|--------|
| **Overview / 总览** | 工作区健康度、索引新鲜度、活跃任务、最近会话 | P0 |
| **Graph Explorer / 图谱浏览** | 交互式代码知识图谱可视化（节点可点击、可缩放、可过滤） | P0 |
| **Impact Viewer / 影响面查看** | 输入目标 → 展示影响链路图 + 风险等级 | P1 |
| **Timeline / 时间线** | 会话事件 + 写入回执的时间轴，支持按 task/session 过滤 | P1 |
| **Task Board / 任务看板** | 所有 task space 的状态（draft/active/blocked/done/archived） | P1 |
| **Benchmark Trends / 基准趋势** | Token 使用趋势图、回归检测、健康评分 | P2 |
| **Audit Report / 审计报告** | 文档/测试/实现/设计一致性的可视化报告 | P2 |

**技术选型：**

```
前端：轻量 SPA（Preact + htm，零构建工具）
      或者用 Pyodide 在浏览器里跑 Python（适合快速原型）
图可视化：D3.js force-directed graph 或 vis.js
数据源：HTTP API（复用 memory-center serve-http 的端点）
部署：serve-http 时静态文件和 API 共用同一端口
```

#### 14.2.2 Graph Explorer 设计

这是 3.0 最有差异化价值的 UI 组件。

**交互模式：**

```
┌─────────────────────────────────────────────────────────┐
│  🔍 Search: [UserService                           ]    │
│  ─────────────────────────────────────────────────────── │
│  Filter: [✓] Class  [✓] Method  [✓] Endpoint           │
│          [✓] Feign  [✓] MQ      [ ] Config              │
│  ─────────────────────────────────────────────────────── │
│                                                          │
│         ┌──────────┐                                     │
│         │ UserSvc  │ ← 点击展开详情                      │
│         └────┬─────┘                                     │
│              │ CALLS_SERVICE                              │
│         ┌────▼─────┐      ┌──────────┐                   │
│         │ OrderSvc │─────→│ OrderDAO │                   │
│         └────┬─────┘      └──────────┘                   │
│              │ IMPLEMENTS_FEIGN                           │
│         ┌────▼──────────┐                                │
│         │ GET /orders   │                                │
│         └───────────────┘                                │
│                                                          │
│  ─────────────────────────────────────────────────────── │
│  Detail Panel:                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Type: Service | Project: ucap-cloud-user            │ │
│  │ Files: 23 | Classes: 15 | Endpoints: 8              │ │
│  │ Feign Clients: 3 | MQ Consumers: 2                  │ │
│  │ Risk Level: medium                                   │ │
│  │ [View Impact] [View Chain] [View Context]            │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**关键交互：**
- 节点点击：展开详情面板（类型、项目、文件数、关联数）
- 边点击：显示关系详情（置信度、证据来源）
- 右键菜单：View Impact / View Chain / View Context / Mark as Risk
- 拖拽：重新布局
- 缩放：滚轮缩放 + 拖拽平移
- 过滤：按节点类型、项目、置信度范围过滤
- 搜索：实时搜索节点名称，高亮匹配节点

#### 14.2.3 实时健康度指示器

在 dashboard 顶部始终显示：

```
┌─────────────────────────────────────────────────────────┐
│  🟢 Index: fresh (2h ago)  │  🟢 Graph: 12,345 nodes    │
│  🟡 Semantic: stale (2d)   │  🟢 Memory: 892 events     │
│  🔴 Tests: 3 failing       │  🟢 MCP: connected         │
└─────────────────────────────────────────────────────────┘
```

颜色规则：
- 🟢 正常：索引 < 1h，测试全过，MCP 连接正常
- 🟡 警告：索引 > 4h，语义索引 > 1d，测试有 skip
- 🔴 异常：索引 > 1d，测试有 fail，MCP 断连

### 14.3 MCP Prompt 增强

**当前只有 2 个 prompt。3.0 增加到 8+ 个，覆盖完整工作流：**

```python
@mcp.prompt()
def code_review_checklist(target: str) -> str:
    """Generate a code review checklist based on the target's impact analysis."""
    return f"""Before reviewing {target}, call mc_analyze(target="{target}", depth="full").
    Use the returned checklist, rules, and impact to guide your review.
    Focus on: contract compatibility, cross-service impact, risk patterns."""

@mcp.prompt()
def debug_session(symptom: str) -> str:
    """Start a structured debugging session."""
    return f"""For the symptom: {symptom}
    1. Call mc_start(intent="{symptom}") to load context
    2. Use mc_lookup(mode="trace") to find related call chains
    3. Check historical cases for similar issues
    4. Document findings in the task space"""

@mcp.prompt()
def migration_planning(from_service: str, to_service: str) -> str:
    """Plan a service migration with impact analysis."""
    return f"""Planning migration from {from_service} to {to_service}:
    1. Call mc_lookup(mode="contracts") to list all contracts
    2. Call mc_analyze(target="{from_service}", depth="full") for full impact
    3. Check cross-workspace bridges for external dependencies
    4. Generate migration checklist from impact results"""
```

---

## 15. 缓存与性能 / Caching & Performance

### 15.1 查询结果缓存

**当前问题：** 相同查询每次都要重新计算（graph traversal + BM25 + merge）。

**3.0 方案：** LRU 缓存 + 失效策略。

```python
from functools import lru_cache
from hashlib import sha256

class QueryCache:
    """Workspace-scoped query result cache."""

    def __init__(self, max_size: int = 256, ttl_seconds: int = 300):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and (time.time() - entry[0]) < self._ttl:
            return entry[1]
        return None

    def put(self, key: str, value: Any):
        if len(self._cache) >= self._max_size:
            # Evict oldest
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        self._cache[key] = (time.time(), value)

    def invalidate_on_reindex(self):
        """Clear cache after reindex."""
        self._cache.clear()
```

**缓存粒度：**
- `mc_lookup(mode="auto")` 结果缓存 5 分钟
- `mc_analyze` 结果缓存到下次 reindex
- `workspace_status` 缓存 1 分钟
- reindex 后清除所有缓存

### 15.2 大结果集流式返回

**当前问题：** `group_impact` 可能返回几百条影响记录，全部序列化后一次性返回，token 消耗巨大。

**3.0 方案：** 支持 streaming response。

```python
@mcp.tool()
def mc_lookup_stream(query: str, mode: str = "auto", limit: int = 20):
    """Streaming version of mc_lookup. Returns results progressively."""
    yield {"type": "header", "query": query, "mode": mode}
    for item in retrieval_results:
        yield {"type": "result", "data": item}
    yield {"type": "summary", "total": len(all_results)}
```

### 15.3 增量式 Graph 更新

**当前问题：** partial rebuild 仍然要读全量索引文件做 merge。

**3.0 方案：** 基于 file watcher 的增量更新。

```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class IndexWatcher(FileSystemEventHandler):
    """Watch for file changes and trigger incremental reindex."""

    def on_modified(self, event):
        if event.src_path.endswith(".java"):
            self._queue.put(("modified", event.src_path))

    def on_created(self, event):
        if event.src_path.endswith(".java"):
            self._queue.put(("created", event.src_path))

    def on_deleted(self, event):
        if event.src_path.endswith(".java"):
            self._queue.put(("deleted", event.src_path))
```

---

## 16. 多语言支持 / Multi-Language Support

### 16.1 当前限制

当前 Memory Center **只支持 Java / Spring Cloud**。indexer 硬编码了 Java 注解解析、Spring MVC mapping、FeignClient 等。

### 16.2 3.0 扩展方案

**不改变核心架构，而是通过插件化 indexer 支持多语言：**

```python
# core/indexing/base.py
class LanguageParser(Protocol):
    """Protocol for language-specific parsers."""
    name: str
    extensions: set[str]

    def parse(self, text: str, file_path: str) -> ParseResult: ...

# core/indexing/registry.py
PARSER_REGISTRY: Dict[str, LanguageParser] = {}

def register_parser(parser: LanguageParser):
    PARSER_REGISTRY[parser.name] = parser

# 注册内置 parser
register_parser(RegexJavaParser())
register_parser(TreeSitterJavaParser())  # 3.0 新增

# 用户可以注册自定义 parser
# memory-center register-parser my-lang /path/to/parser.py
```

**优先支持的语言：**

| 语言 | 优先级 | 原因 |
|------|--------|------|
| **TypeScript / JavaScript** | P0 | 前后端分离项目的前端部分 |
| **Go** | P1 | 微服务常用语言 |
| **Python** | P1 | AI/数据服务常用 |
| **Kotlin** | P2 | Spring Boot 生态 |

---

## 17. 工作区模板与快速启动 / Workspace Templates

### 17.1 当前问题

新项目接入 Memory Center 需要手动编写 `workspace.yaml`，配置服务列表、路径等。

### 17.2 3.0 方案

提供预置模板 + 自动检测：

```bash
# 自动检测项目结构并生成 workspace.yaml
memory-center init --auto-detect

# 使用预置模板
memory-center init --template spring-cloud-microservice
memory-center init --template spring-boot-monolith
memory-center init --template nextjs-spring-backend

# 从已有 workspace 复制配置
memory-center init --from /path/to/existing/workspace.yaml
```

**自动检测逻辑：**
1. 扫描目录下的 `pom.xml` / `build.gradle` → 识别为 Java/Maven/Gradle 项目
2. 扫描 `@FeignClient` / `@RestController` 注解 → 确认为 Spring Cloud
3. 检测 `application.yml` 中的 `spring.application.name` → 提取服务名
4. 自动填充 `workspace.yaml` 的 services 列表

---

## 18. 导出与分享 / Export & Share

### 18.1 当前能力

`exporters.py` 已经支持导出：
- HTML dashboard
- Markdown dashboard
- Mermaid 图
- Wiki 生成（`generate_wiki`）
- Skills 生成（`generate_skills`）

### 18.2 3.0 增强

| 导出格式 | 说明 | 优先级 |
|----------|------|--------|
| **SVG 图谱** | 代码知识图谱的矢量图，可嵌入文档 | P1 |
| **JSON Schema** | 导出图谱的 JSON Schema，供其他工具消费 | P1 |
| **OpenAPI Spec** | 从 Endpoint 索引自动生成 OpenAPI 3.0 spec | P2 |
| **PlantUML** | 从调用链自动生成时序图 | P2 |
| **Markdown Impact Report** | 影响分析报告，可直接贴到 PR 描述 | P0 |
| **CHANGELOG.md** | 从历史 case 自动生成变更日志 | P2 |

**Impact Report 示例：**

```markdown
## Impact Analysis: UserService.updateUser()

### Risk Level: HIGH

### Affected Services (4)
- order-service: via FeignClient(UserServiceClient.updateUser)
- payment-service: via Kafka(user-updated-topic)
- notification-service: via Kafka(user-updated-topic)
- gateway: via route(/api/users/**)

### Affected Contracts
- UserServiceClient.updateUser (Feign)
- UserUpdatedEvent (MQ Message)
- UserDTO.email, UserDTO.phone (DTO fields)

### Rules Triggered
- CONTRACT-001: 公共契约禁止破坏性变更
- MQ-001: MQ 消费必须保证幂等

### Checklist
- [ ] 搜索所有 UserServiceClient 使用点
- [ ] 检查 UserUpdatedEvent 的消费方幂等
- [ ] 验证 UserDTO 字段兼容性
```

---

## 19. 更新后的实施路线 / Updated Roadmap

### Phase 1：存储与检索基础重构（4-6 周）

*（不变，见 §9）*

### Phase 2：向量搜索与代码知识图谱（4-6 周）

*（不变，见 §9）*

### Phase 3：推理引擎 + UI + 索引升级（6-8 周）

> 目标：从"搜索"进化到"推理"，同时提供可视化能力。

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| 图模式匹配引擎 | P0 | 2 周 |
| 传递性推理 | P1 | 1 周 |
| 风险模式识别 | P1 | 1 周 |
| **Graph Explorer 交互式图谱浏览** | **P0** | **2 周** |
| **Web Dashboard（Overview + Health）** | **P0** | **1 周** |
| **Impact Viewer** | **P1** | **1 周** |
| Tree-sitter Java 解析器 | P1 | 1 周 |
| 并行索引 | P1 | 1 周 |
| 增量 diff 索引 | P2 | 1 周 |
| 查询结果缓存 | P1 | 3 天 |
| 多语言 parser 协议 | P2 | 3 天 |

**交付物：**
- `reasoning/` 模块
- Graph Explorer（D3.js / vis.js）
- Web Dashboard（10 个页面升级为 SPA）
- Impact Viewer
- `TreeSitterJavaParser`
- 查询缓存层
- parser 插件协议

### Phase 4：类型安全、测试、导出与可观测性（3-4 周）

> 目标：让系统可维护、可信赖、可分享。

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| 核心返回类型 Pydantic v2 化 | P0 | 1 周 |
| mc_admin 参数简化 | P1 | 2 天 |
| structlog 结构化日志 | P1 | 3 天 |
| orchestrator 单元测试 | P0 | 2 周 |
| GraphStore 图操作测试 | P0 | 1 周 |
| **MCP Prompt 增强（8+ prompt）** | **P1** | **3 天** |
| **Impact Report 导出** | **P0** | **2 天** |
| **workspace init 自动检测** | **P1** | **3 天** |
| **实时健康度指示器** | **P1** | **2 天** |
| 关键指标埋点 | P2 | 3 天 |

**交付物：**
- Pydantic 模型定义
- 测试覆盖率报告（目标 50%+）
- 8+ MCP prompt
- Impact Report 导出功能
- `memory-center init --auto-detect`
- 健康度指示器
- 指标 dashboard

---

---

## 20. 外部标杆深度吸收：CodeGraph + Understand-Anything / External Benchmark Integration

> 本节用于把 2026-W23 GitHub AI 编程趋势中的两个代码知识图谱标杆项目，转化为 Memory Center 3.0 的可执行增强项。
>
> 核心结论：**3.0 不应只做“更强的 MCP 检索工具”，还要做“能让 Agent 少读文件、少调用工具、能向人解释系统结构的代码理解底座”。**

### 20.1 背景判断：代码知识图谱已经成为 AI 编程基础设施

本周 AI/ML 趋势中，Understand-Anything 与 CodeGraph 同时位居前列，说明社区关注点正在从“让 AI 写代码”转向“让 AI 在写代码前真正理解项目”。这与 Memory Center 3.0 的核心命题完全一致：**让 AI 真正读懂代码，而不是反复 grep / read / 猜测上下文。**

对 Memory Center 3.0 的直接启发是：

1. **代码图谱不只是检索索引，而是 Agent 的上下文调度层。**
2. **UI 不只是锦上添花，而是 onboarding、审计、影响面解释的必要入口。**
3. **索引新鲜度必须显式可见，否则 Agent 会基于旧图谱做错误判断。**
4. **衡量成功不能只看查询延迟，还要看 token、工具调用次数、文件读取次数、影响分析准确率。**

---

### 20.2 CodeGraph 可借鉴能力拆解

CodeGraph 的核心定位是：**预索引代码知识图谱，为 Claude Code、Codex、Gemini、Cursor 等 AI 编程助手提供本地语义代码上下文。**

#### 20.2.1 值得吸收的能力

| 能力 | CodeGraph 做法 | Memory Center 3.0 吸收方式 |
|------|----------------|-----------------------------|
| **预索引图谱上下文** | Agent 查询图谱，而不是反复 grep/read | 强化 `mc_lookup` 的“先图谱、后读文件”策略 |
| **少工具调用/少 token** | 通过 `context + explore` 一次返回入口点、相关符号、代码片段 | 新增 `mc_context_pack`，面向 Agent 一次性组装可执行上下文 |
| **本地优先** | 100% local，SQLite 存储，不依赖外部服务 | 保持 Memory Center 的本地 SQLite + 可选向量后端策略 |
| **索引自动保鲜** | 文件 watcher + debounce auto-sync + connect-time catch-up | 新增 `IndexFreshnessService` 和“索引新鲜度横幅” |
| **框架路由识别** | 识别 Django/Flask/FastAPI/Express/Spring 等路由并链接 handler | 对 Java/Spring Cloud 场景优先实现 `RouteNode` 与 `ROUTES_TO` |
| **影响面分析** | trace callers/callees/impact radius | 升级 `mc_analyze` 为“图谱影响面 + 风险规则 + checklist” |
| **多语言解析** | 20+ languages + framework-aware | 3.0 不追求一次覆盖 20+，先做 parser 插件协议，Java/Spring 为默认主线 |

#### 20.2.2 对 Memory Center 的关键修正

当前 V3_PLAN 中已有 Code KG、Hybrid Retrieval、Graph Explorer，但还缺少一个非常关键的 Agent 执行闭环：

```text
Agent 提问
  ↓
Memory Center 判断意图
  ↓
返回“足够回答问题”的上下文包
  ↓
Agent 尽量不再 grep/read
  ↓
必要时才读取真实文件进行验证
```

因此 3.0 需要新增一个上下文打包层：

```python
class ContextPackBuilder:
    """Build compact, evidence-backed context package for coding agents."""

    def build(self, query: str, intent: str, budget_tokens: int = 8000) -> ContextPack:
        # 1. 定位入口节点
        entrypoints = self.retrieve_entrypoints(query, intent)

        # 2. 沿图谱扩展关键邻居
        neighbors = self.expand_important_neighbors(entrypoints)

        # 3. 提取最小必要代码片段
        snippets = self.select_snippets(entrypoints, neighbors, budget_tokens)

        # 4. 附带证据、风险、下一步建议
        risks = self.match_risk_patterns(entrypoints, neighbors)
        checklist = self.generate_checklist(intent, risks)

        return ContextPack(
            entrypoints=entrypoints,
            relationships=neighbors,
            snippets=snippets,
            risks=risks,
            checklist=checklist,
            freshness=self.index_freshness.status(),
        )
```

对应 MCP 工具：

```python
@mcp.tool()
def mc_context_pack(query: str, intent: str = "auto", budget_tokens: int = 8000):
    """
    Return a compact, evidence-backed context package for coding agents.
    Prefer this before grep/read when answering architecture or change-impact questions.
    """
```

---

### 20.3 Understand-Anything 可借鉴能力拆解

Understand-Anything 的核心定位是：**把代码库、知识库、文档转成可探索、可搜索、可问答的交互式知识图谱。**

#### 20.3.1 值得吸收的能力

| 能力 | Understand-Anything 做法 | Memory Center 3.0 吸收方式 |
|------|---------------------------|-----------------------------|
| **教学型图谱** | 不是炫酷复杂图，而是帮助用户理解系统如何组织 | Graph Explorer 默认提供“简化视图”，而不是一上来展示全量节点 |
| **业务域视图** | 将代码映射到 domain / flow / step | 新增 `BusinessDomainView`，把 Controller/Service/MQ/DB 串成业务流程 |
| **Guided Tours** | 自动生成按依赖顺序的架构 walkthrough | 新增 `mc_onboard` / `ArchitectureTourGenerator` |
| **Persona-Adaptive UI** | 按 junior dev / PM / power user 调整细节层级 | Dashboard 增加 persona 参数：developer / architect / product |
| **Fuzzy & Semantic Search** | 支持“哪个部分处理 auth”这类语义问题 | Hybrid Retrieval 中强化自然语言意图识别与结果解释 |
| **Diff Impact Analysis** | 提交前查看变更影响 | `mc_analyze(diff=True)` 支持 git diff 输入，输出影响链路和检查清单 |
| **知识库图谱** | 支持将 docs/wiki 转为知识图谱 | 3.0 后续支持 `DocNode` / `DecisionRecord`，把 ADR、README、设计文档纳入同一图谱 |

#### 20.3.2 对 Memory Center 的关键修正

V3_PLAN 当前偏“工程底座”，但对“新人如何快速理解项目”和“非技术人员如何看懂业务流程”的考虑还不够。需要把 Graph Explorer 从“技术图谱浏览器”升级为“分层理解入口”。

新增三种 UI 模式：

| UI 模式 | 面向对象 | 主要内容 |
|---------|----------|----------|
| **Architecture Mode** | 架构师/高级开发 | 服务、模块、接口、MQ、配置、依赖链路 |
| **Business Mode** | 产品/业务/测试 | 业务域、业务流程、入口接口、关键状态流转 |
| **Change Mode** | 正在改代码的 Agent/开发者 | 当前 diff、影响面、风险规则、验证 checklist |

实现建议：

```python
class GraphViewBuilder:
    def build(self, mode: str, target: str | None = None, persona: str = "developer"):
        if mode == "architecture":
            return self.build_architecture_view(target, persona)
        if mode == "business":
            return self.build_business_flow_view(target, persona)
        if mode == "change":
            return self.build_change_impact_view(target, persona)
        raise ValueError(f"Unknown graph view mode: {mode}")
```

---

### 20.4 需要新增到 3.0 的核心模块

基于两个项目的启发，Memory Center 3.0 建议新增以下模块：

```text
memory_center/core/
├── context/
│   ├── __init__.py
│   ├── pack.py              # ContextPackBuilder：面向 Agent 的最小上下文包
│   ├── budget.py            # TokenBudgetAllocator：按模型/任务预算裁剪上下文
│   └── evidence.py          # EvidenceSelector：选择最可靠证据
├── freshness/
│   ├── __init__.py
│   ├── watcher.py           # 文件 watcher + debounce auto-sync
│   ├── status.py            # 索引新鲜度状态
│   └── reconcile.py         # connect-time catch-up / hash reconcile
├── onboarding/
│   ├── __init__.py
│   ├── tour.py              # ArchitectureTourGenerator
│   ├── glossary.py          # 项目术语表
│   └── guide.py             # 新人 onboarding guide
├── domain/
│   ├── __init__.py
│   ├── extractor.py         # 业务域/业务流程抽取
│   ├── flow.py              # BusinessFlowGraph
│   └── mapper.py            # code entity → business domain 映射
└── views/
    ├── __init__.py
    ├── architecture.py      # Architecture Mode
    ├── business.py          # Business Mode
    └── change.py            # Change Mode
```

---

### 20.5 本体扩展：吸收 Route、Flow、Tour、Freshness

在附录 B 的 Code KG Ontology 基础上，补充以下实体与关系。

#### 20.5.1 新增实体

```yaml
RouteNode:
  description: "HTTP/RPC/MQ 入口路由或消息入口"
  source: "框架解析器 / 注解解析 / 配置解析"
  fields: [route_id, route_type, method, path, topic, handler_entity, service]

BusinessFlow:
  description: "业务流程，如用户登录、订单创建、支付回调"
  source: "规则推断 + LLM 摘要"
  fields: [flow_id, name, domain, steps, confidence]

FlowStep:
  description: "业务流程中的一个步骤"
  source: "代码图谱路径 + 语义摘要"
  fields: [step_id, flow_id, order, entity_id, action, input, output]

ArchitectureTour:
  description: "面向新人或特定角色的架构导览"
  source: "依赖图拓扑排序 + LLM 摘要"
  fields: [tour_id, persona, scope, steps, generated_at]

IndexFreshness:
  description: "索引新鲜度状态"
  source: "文件 watcher / git diff / hash reconcile"
  fields: [workspace, changed_files, pending_files, last_indexed_at, staleness_level]
```

#### 20.5.2 新增关系

```yaml
ROUTES_TO:
  source: "框架解析器"
  confidence_range: [0.7, 0.95]
  semantic_strength: "confirmed"
  description: "入口路由指向具体 handler"

IMPLEMENTS_FLOW_STEP:
  source: "业务流程抽取器"
  confidence_range: [0.4, 0.8]
  semantic_strength: "inferred"
  description: "代码实体实现某个业务流程步骤"

NEXT_STEP:
  source: "业务流程图构建器"
  confidence_range: [0.4, 0.8]
  semantic_strength: "inferred"
  description: "业务流程中的步骤顺序"

EXPLAINS:
  source: "ArchitectureTourGenerator"
  confidence_range: [0.6, 0.9]
  semantic_strength: "derived"
  description: "导览步骤解释某个代码实体或子图"

STALE_FOR:
  source: "IndexFreshnessService"
  confidence_range: [1.0, 1.0]
  semantic_strength: "runtime"
  description: "某个图谱节点对应的源文件已变更但尚未完成索引"
```

---

### 20.6 MCP 工具增强

当前 8 个 facade 工具保持不变，但新增 4 个更贴合 Agent 编程场景的工具。

| 工具 | 作用 | 优先级 |
|------|------|--------|
| `mc_context_pack` | 一次性返回入口点、关系、代码片段、风险、checklist，减少 Agent 自行 grep/read | P0 |
| `mc_onboard` | 生成项目/模块 onboarding guide 与架构导览 | P1 |
| `mc_domain` | 抽取业务域、业务流程、流程步骤 | P1 |
| `mc_freshness` | 查询索引新鲜度、pending files、是否需要读取真实文件 | P0 |

示例：

```python
@mcp.tool()
def mc_freshness(scope: str = "workspace"):
    """
    Return index freshness status.
    If pending files affect the query target, instruct the agent to Read the live file.
    """
```

```python
@mcp.tool()
def mc_onboard(scope: str = "workspace", persona: str = "developer"):
    """
    Generate a guided architecture tour for onboarding.
    persona: developer | architect | product | tester
    """
```

---

### 20.7 UI 增强：从 Dashboard 到 Teaching Workbench

V3_PLAN 已经提出 SPA Dashboard、Graph Explorer、Impact Viewer。这里进一步明确产品形态：

#### 20.7.1 Graph Explorer 默认不展示“全量复杂图”

全量图谱容易炫但不实用。默认策略应是：

1. 首屏只展示服务/模块级拓扑。
2. 点击服务后展开 Controller / Service / Repository / MQ / Config。
3. 点击节点后展示：
    - Plain-English / 中文解释
    - 关键调用链
    - 被谁调用 / 调用了谁
    - 相关业务流程
    - 修改风险
    - 最近变更与索引新鲜度
4. 用户需要时才进入 Raw Graph 模式。

#### 20.7.2 新增 Guided Tour 页面

```text
Guided Tour
├── 1. 项目整体分层
├── 2. 核心服务关系
├── 3. 核心业务流程
├── 4. 数据入口与出口
├── 5. MQ / Feign / 配置传播
├── 6. 高风险修改点
└── 7. 推荐阅读顺序
```

#### 20.7.3 新增 Business Flow 页面

特别适合企业 Spring Cloud 项目：

```text
用户创建流程
  POST /api/users
    → UserController.create
    → UserService.create
    → UserRepository.save
    → publish UserCreatedEvent
    → notification-service consumes UserCreatedEvent
    → audit-service consumes UserCreatedEvent
```

这个视图比“类和方法图谱”更容易给业务、测试、产品理解。

---

### 20.8 索引新鲜度机制：避免 Agent 基于旧图谱误判

这是 CodeGraph 给 3.0 最大的工程启发之一。

#### 20.8.1 新增 Freshness 状态

| 状态 | 含义 | Agent 策略 |
|------|------|------------|
| `fresh` | 图谱与文件一致 | 直接使用图谱结果 |
| `pending` | 有文件变更，正在 debounce 或等待索引 | 图谱可参考，但命中文件必须 Read 实时内容 |
| `stale` | 索引落后较久或 watcher 不可用 | 先提示需要 reindex/sync |
| `unknown` | 无法判断新鲜度 | 保守处理，要求读取真实文件验证 |

#### 20.8.2 MCP 返回中增加新鲜度横幅

```json
{
  "freshness": {
    "status": "pending",
    "pending_files": ["src/user/UserService.java"],
    "message": "Graph may be stale for UserService.java. Read live file before editing."
  }
}
```

#### 20.8.3 实现策略

```text
文件变更事件
  ↓
debounce 2s
  ↓
标记 pending_files
  ↓
增量解析变更文件
  ↓
upsert nodes/edges/snippets/embeddings
  ↓
清除 pending 状态
```

connect-time catch-up：

```text
MCP server 启动
  ↓
扫描 size + mtime
  ↓
对可疑文件计算 hash
  ↓
发现变更则增量 reindex
  ↓
完成后再响应第一个查询
```

---

### 20.9 成功指标补充

原 §11 偏向系统性能，补充 Agent 编程效果指标。

| 指标 | 2.x 基线 | 3.0 目标 | 说明 |
|------|----------|----------|------|
| Agent 文件读取次数 | 无统计 | 降低 50%+ | 架构问答/影响分析场景 |
| Agent 工具调用次数 | 无统计 | 降低 40%+ | 通过 `mc_context_pack` 减少 grep/read |
| Token 消耗 | 无统计 | 降低 25%+ | 以同一问题 A/B 对比 |
| stale 命中提示率 | 无 | 100% | 命中 pending/stale 文件必须提示 |
| Onboarding 首答可用率 | 无 | >80% | 新人问“项目怎么跑/核心流程是什么”可直接回答 |
| Business Flow 抽取准确率 | 无 | >70% | 先人工评估核心流程 |
| Diff Impact 召回率 | 基线 | >85% | 已知变更影响面 benchmark |

---

### 20.10 Roadmap 修正建议

将原 §19 的 Phase 3/4 稍作调整，突出“上下文打包、索引保鲜、教学型图谱”。

#### Phase 2.5：Agent Context Pack + Freshness（新增，2-3 周）

> 目标：先解决 Agent 编程中最直接的痛点——少读文件、少工具调用、不基于旧索引误判。

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| `ContextPackBuilder` | P0 | 1 周 |
| `mc_context_pack` MCP 工具 | P0 | 2 天 |
| `IndexFreshnessService` | P0 | 3 天 |
| 文件 watcher + debounce sync | P0 | 3 天 |
| MCP freshness banner | P0 | 1 天 |
| context pack token budget 裁剪 | P1 | 3 天 |

**交付物：**
- `context/pack.py`
- `freshness/` 模块
- `mc_context_pack`
- `mc_freshness`
- Agent A/B benchmark：with context pack vs without context pack

#### Phase 3：推理引擎 + Teaching Workbench + 索引升级（6-8 周）

在原 Phase 3 基础上新增：

| 任务 | 优先级 | 预估工时 |
|------|--------|----------|
| Guided Tour 生成器 | P1 | 1 周 |
| Business Flow 抽取 | P1 | 1 周 |
| RouteNode / ROUTES_TO 支持（Spring 优先） | P0 | 1 周 |
| Graph Explorer 简化视图 | P0 | 1 周 |
| Business Mode / Change Mode | P1 | 1 周 |

---

### 20.11 最终定位修正

原定义：

> Memory Center 3.0 = 代码知识图谱 + 向量语义检索 + 图感知推理

建议升级为：

> **Memory Center 3.0 = 本地代码知识图谱 + 混合检索 + 图感知推理 + Agent 上下文打包 + 教学型可视化工作台**

一句话说明：

> Memory Center 3.0 不只是让 AI “搜到代码”，而是让 AI 和人都能快速理解一个项目：Agent 获得最小必要上下文，人获得可解释的架构、业务流程和变更影响视图。

---

### 20.12 对当前 V3_PLAN 的具体落地修改清单

| 原章节 | 建议修改 |
|--------|----------|
| §1 一句话定义 | 改为“代码知识图谱 + 混合检索 + 图感知推理 + Agent 上下文打包 + Teaching Workbench” |
| §3 Code KG | 增加 `RouteNode`、`BusinessFlow`、`FlowStep`、`IndexFreshness` |
| §4 Vector Search | 保持，但强调向量服务于 context pack，而不是单独搜索能力 |
| §6 Indexer | 增加 watcher、debounce、connect-time catch-up |
| §7 Orchestrator | 增加 `context/`、`freshness/`、`domain/`、`onboarding/` |
| §8 Observability | 增加 Agent 工具调用次数、文件读取次数、token 消耗指标 |
| §13 外部对比 | 将 CodeGraph/Understand-Anything 从“竞品对比”升级为“能力吸收矩阵” |
| §14 UI | 从 Dashboard 升级为 Teaching Workbench：Architecture / Business / Change 三模式 |
| §19 Roadmap | 增加 Phase 2.5：Context Pack + Freshness |

---

**Document version:** 3.0-draft-3  
**Last updated:** 2026-06-02  
**Update note:** Added deep integration analysis for CodeGraph and Understand-Anything, including Context Pack, Freshness, Teaching Workbench, Business Flow, RouteNode, and updated roadmap.

**Author:** Memory Center Contributors
