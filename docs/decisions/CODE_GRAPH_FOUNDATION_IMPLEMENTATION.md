# 代码图谱基础设施实施决策 / Code Graph Foundation Implementation Decision

> **状态 / Status**：提议（Proposed）  
> **文档类型 / Type**：决策 + 实施规格（Decision + implementation specification）  
> **适用范围 / Scope**：Memory Center 的索引、图查询、局部刷新和本地运行治理  
> **不替代 / Does not replace**：[NEXT_PHASE_MASTER_PLAN.md](../NEXT_PHASE_MASTER_PLAN.md) 仍是唯一活跃开发路线；本文件给出其中相关工作在获准后应如何实现、验证和回滚。  
> **参考 / Reference**：[codebase-memory-mcp.md](../references/codebase-memory-mcp.md)；该参考只提供设计启发，不构成运行时依赖或兼容目标。

---

## 1. 摘要与决定 / Executive Summary and Decision

Memory Center 不复制外部代码图谱产品，也不重写为单体原生二进制。决定在既有
`SQLite + active/staging generation + task-level MCP facade` 的基础上，逐步建设一层
**可信、可增量、可协调的代码图谱基础设施**。

Memory Center will not copy an external code-graph product or rewrite itself as a native
binary. It will incrementally strengthen its existing `SQLite + active/staging generation
+ task-level MCP facade` into a **trustworthy, incremental, coordinated code-graph
foundation**.

实施顺序固定为：

1. **可信查询合同**：先暴露 generation、freshness、coverage 和否定性结论边界；
2. **有界图查询产品化**：把底层图能力收敛为既有 facade 的内部模板；
3. **工作区级运行治理**：补齐写入互斥、租约、合并、取消、原子发布和恢复；
4. **由真实需求驱动的通用解析适配层**：保留 Java/Spring 深解析，逐语言扩展。

本决定的首要目标不是“支持更多语言”或“获得更快的 micro benchmark”，而是让 Agent
在多仓、多服务、多会话并发时，能够基于同一代、覆盖范围明确的图证据给出可解释结论。

---

## 2. 问题、目标与边界 / Problem, Goals, and Boundaries

### 2.1 当前问题 / Current Problems

当前系统已拥有图存储、混合检索、定向刷新、后台 job 和 watcher；但这些能力需要统一为
更严格的执行合同：

- 图中“未命中”可能来自未索引、已跳过、索引陈旧或查询截断，Agent 不能将其等同于
  “工程中不存在”；
- 多个 MCP/CLI/watcher 请求可能同时刷新一个工作区，需要明确谁拥有写入权、谁可以
  合并、谁可以取消，以及失败后读什么；
- 图查询的能力分散在内部实现中，需要稳定地映射到 `mc_lookup`、`mc_analyze`、
  `mc_freshness` 和 `mc_admin`，而不是新增平行 MCP 工具；
- Java/Spring Cloud 深度语义是产品优势；任何通用 AST 扩展都不能降低其调用解析精度。

### 2.2 目标 / Goals

1. 每个代码图谱结论均可追溯到已发布 generation、覆盖范围和证据等级。
2. 默认查询永不等待重建、永不扫描全图、永不隐式全量 reindex。
3. 同一工作区发生并发刷新时，运行时不会出现部分发布、重复构建或损坏的 active 图。
4. 局部刷新按变更集合收敛，并能在失败时保留上一代可读图。
5. 图查询结果可在 CLI、HTTP、MCP 和 Workbench 间保持相同的事实与边界语义。
6. 通用语言扩展通过可替换 parser adapter 和稳定 IR 进行，不改变任务记忆与治理模型。

### 2.3 非目标 / Non-goals

- 不复制 CBM 源码、CLI、MCP tool schema 或 benchmark 数字。
- 不将任意 Cypher/openCypher 作为默认公开 MCP 功能。
- 不引入远程服务、云端源码上传、必选 LSP daemon 或必选向量服务。
- 不默认提交 `.memory-center` 索引快照；私有工作区生成物不得进入仓库。
- 不删除 regex parser；它仍作为 Java parser 的 fallback 和 differential oracle。
- 不改变现有 MCP tool 名称或破坏已有 dict 返回字段，只做 additive 字段和内部路由改进。

---

## 3. 不变量与架构原则 / Invariants and Principles

下列规则是实现门禁，不是建议：

1. `graph.db` 是唯一运行时事实库；JSON、JSONL 和 Markdown 只能是审查、导出或控制面
   工件，不能反向覆盖运行时事实。
2. 查询只能读取 `active generation`；staging generation 未发布前不可对普通查询可见。
3. `VERIFIED` 只能由可追溯验证回执、运行时事实或人工确认产生；置信度不能替代验证。
4. 对“没有调用方”“没有消费者”“无影响”等否定性结论，必须同时满足 freshness 和
   coverage 门禁；否则只能返回 `AMBIGUOUS` 或 `PARTIAL`。
5. 图遍历必须有节点数、边数、深度、分页、时间和 token 预算；不得把全图物化到 Python。
6. 写入操作必须有 owner、lease、进度和可恢复终态；失败不得破坏上一代 active 图。
7. CLI、HTTP、MCP 和 hook 仅是适配层；决策和数据合同由 core/application 层统一实现。
8. 日志、诊断、导出和测试 fixture 均不得包含私有源码、真实业务路径、服务名、prompt 或密钥。

---

## 4. 目标架构 / Target Architecture

```text
                       Read adapters / 读取适配层
      MCP ─┐              CLI ─┐              HTTP/UI ─┐
           └───────────────┬────┴───────────────────────┘
                           ▼
              Task-level Facade / 任务级门面
     mc_lookup | mc_analyze | mc_freshness | mc_admin(change_review)
                           │
          ┌────────────────┼─────────────────┐
          ▼                ▼                 ▼
  Query Planner       Coverage Gate     Job Coordinator
  查询规划器            覆盖度门禁          任务协调器
          │                │                 │
          ▼                ▼                 ▼
  bounded templates   generation state   lease / lock / merge
  有界查询模板          代际状态            publish / cancel / recover
          │                                  │
          └─────────────┬────────────────────┘
                        ▼
              Index Pipeline / 索引流水线
  discovery -> parser adapters -> semantic enrichment -> graph projection
                        │
                        ▼
      staging generation -> validation -> atomic active publish
                        │
                        ▼
      SQLite graph.db + FTS/BM25 + optional ANN + review exports
```

### 4.1 职责划分 / Responsibility Split

| 部件 | 负责 | 不负责 |
|---|---|---|
| Parser adapter | 提取稳定 IR、诊断解析限制 | 业务级最终推理、写任务记忆 |
| Semantic enrichment | Java/Spring/跨服务关系补全和证据等级 | 猜测不可证明的调用目标 |
| Graph projection | 将 IR 原子地投影为节点、边、FTS 和 generation 元数据 | 面向 Agent 的自然语言说明 |
| Query planner | 选择候选源、模板、预算和排序 | 修改图或启动全量索引 |
| Coverage gate | 判断结论的覆盖边界和否定性结论资格 | 提升证据等级为 VERIFIED |
| Job coordinator | 提交、合并、锁、租约、取消、恢复、发布协调 | 解析源代码或实现查询策略 |
| Facade | 组装任务级返回、诊断、行动建议 | 复制 core 决策逻辑 |

---

## 5. 数据模型与兼容策略 / Data Model and Compatibility

### 5.1 稳定内部 IR / Stable Internal IR

所有 parser adapter 必须输出同一组可序列化中间记录；IR 是 parser 与图投影之间的边界，
不等同于 MCP schema。

```python
@dataclass(frozen=True)
class FileRecord:
    path: str                 # workspace-relative, normalized POSIX path
    content_hash: str
    language: str
    parse_status: Literal["parsed", "partial", "skipped", "failed"]
    skip_reason: str | None

@dataclass(frozen=True)
class SymbolRecord:
    stable_id: str            # deterministic: project + path + kind + qualified name + signature
    kind: str                 # Class, Method, Function, Interface, Route, ...
    qualified_name: str
    range: SourceRange
    evidence_level: str       # EXTRACTED or AMBIGUOUS only at parser stage

@dataclass(frozen=True)
class RelationCandidate:
    source_id: str
    relation: str             # CALLS, IMPORTS, EXPOSES_ENDPOINT, ...
    target_ref: str | None
    confidence: float
    resolution_reason: str
    evidence_level: str       # EXTRACTED | INFERRED | AMBIGUOUS
```

要求：

- `stable_id` 不得依赖临时 SQLite row id；同一 source revision 应稳定。
- `target_ref=None` 的候选不可丢弃，应作为未解析诊断聚合，不能伪造边。
- IR 只保存源代码定位必要的最小 metadata；不保存文件全文或用户 prompt。
- Java adapter 必须同时保留 resolver 的 resolution reason，例如 `same_class`、
  `explicit_import`、`unique_interface_impl`、`receiver_type_missing`。

### 5.2 Generation 元数据 / Generation Metadata

每个 generation 必须记录：

```json
{
  "generation_id": "gen-...",
  "parent_generation_id": "gen-...",
  "state": "staging|validating|active|failed|superseded",
  "scope": {"projects": ["..."], "paths": ["..."]},
  "source_revision": {"git_head": "redacted-or-hash", "dirty_signature": "..."},
  "created_at": "...",
  "published_at": "...",
  "parser_versions": {"java": "..."},
  "coverage_summary": {"parsed": 0, "partial": 0, "skipped": 0, "failed": 0},
  "integrity": {"schema_ok": true, "projection_ok": true, "fts_ok": true}
}
```

现有 generation 与 shard manifest 字段保持可读；新字段以 additive 方式加入。发布指针必须在
同一 SQLite transaction 内更新，读请求始终使用一个已提交的 `active_generation` 快照。

### 5.3 索引覆盖度合同 / Index Coverage Contract

所有面向事实或影响的结果在不破坏旧字段的前提下追加：

```json
{
  "index_context": {
    "generation": "gen-...",
    "freshness": "FRESH|STALE|PARTIAL|NOT_INDEXED",
    "coverage": {
      "scope_kind": "workspace|project|paths|traversal",
      "requested_files": 20,
      "indexed_files": 18,
      "partial_files": 1,
      "skipped_files": 1,
      "unknown_files": 0,
      "reasons": [{"code": "unsupported_syntax", "count": 1}],
      "truncated": false
    },
    "query_budget": {"depth": 3, "nodes": 80, "edges": 120, "timed_out": false}
  },
  "claim_boundary": {
    "negative_claim_allowed": false,
    "reason_codes": ["coverage_partial"],
    "evidence_level": "AMBIGUOUS"
  }
}
```

`negative_claim_allowed=true` 的最小条件：

```text
active generation exists
AND freshness == FRESH
AND requested/traversed scope is fully covered
AND query did not time out or truncate relevant pagination
AND no required relation category is unsupported or ambiguous
```

不满足时，回答必须使用“在已覆盖范围内未发现”而非“没有”。这是逻辑门禁，不能由模型文案
自行绕过。

---

## 6. 索引与增量算法 / Indexing and Incremental Algorithms

### 6.1 构建流程 / Build Pipeline

```text
1. Normalize scope
   - resolve workspace/project/path input
   - normalize paths, reject paths outside workspace policy

2. Discover and classify files
   - apply hard excludes -> .gitignore hierarchy -> workspace policy
   - compute content hash; identify added/modified/deleted/moved files

3. Parse into IR
   - choose adapter by language
   - emit FileRecord even for skipped/failed files
   - keep parser diagnostics bounded and aggregated

4. Enrich relations
   - Java: import/type/inheritance/receiver/bean/Feign/Controller/MQ/config rules
   - resolve only provable targets; otherwise record ambiguity

5. Build staging projection
   - write changed file/symbol/relation projection in bounded batches
   - inherit unchanged project shards from parent generation by reference
   - rebuild only affected FTS/semantic partitions

6. Validate staging
   - schema, referential integrity, shard manifest, FTS health, generation consistency
   - run applicable golden/differential gate in explicit validation path

7. Publish atomically or fail safely
   - transactionally move active pointer only after validation
   - preserve previous active generation on any failure
```

### 6.2 变更集合与影响范围 / Dirty Set and Scope Selection

输入变更集合为 `D0`。按以下规则得到有界重建范围：

```text
D1 = files directly modified, added, deleted, or moved
D2 = owners of D1 (project/module/package)
D3 = direct contract neighbors of D1 only when D1 changes DTO, endpoint,
     Feign, MQ, config, build manifest, or public type signature
R  = dedupe(D1 ∪ D2 ∪ D3), subject to project/path budget
```

约束：

- `D3` 只用于选择需要重新投影的服务/分片，不自动进行深度影响分析；
- 删除和移动必须先删除旧路径投影，再新增/更新新路径投影；
- 当 `R` 超出安全预算时，job 进入 `queued_budget_exceeded`，返回建议的显式 full reindex，
  不能静默扩大范围；
- 无法可靠归类的文件以 `partial` coverage 记录，并阻止相关否定性结论。

### 6.3 Java 调用解析算法 / Java Call Resolution

Java 调用边必须依序尝试并记录第一个可证明命中的层级：

```text
local/parameter type
  -> same class overload set
  -> explicit import / static import
  -> same package
  -> inherited member / unique interface implementation
  -> constructor or injected bean field
  -> Feign client -> route contract -> controller target
  -> otherwise unresolved with reason
```

关键规则：

- 多实现接口、通配符/raw type、反射、外部依赖或第三方无类型回调不得生成唯一 `CALLS` 边；
- 对 Lambda 仅在参数或目标函数式接口可证明时解析；无法证明保留
  `UNKNOWN/receiver_type_missing`；
- 重载的 `Class#method` 聚合视图可保留，但底层边必须绑定到真实方法体和签名；
- parser 与 regex 结果的差异必须进入 differential case；不得以关闭 fallback 的方式掩盖漏边。

### 6.4 图投影与查询复杂度 / Projection and Query Complexity

- 对每一个文件，先删除其旧 generation 内的文件归属节点/边，再批量插入该文件的当前投影；
- 节点和边插入按固定排序，确保同 generation 的输出可复现；
- 为 `file_path`、`stable_id`、`qualified_name`、`relation/source/target`、FTS term 建立或复用索引；
- 调用链与影响传播使用分层 frontier BFS，不递归展开路径；每个端点仅保留当前最佳路径；
- 最佳路径评分沿用固定关系权重，并使用：

```text
score(path) = Π(relation_weight × edge_confidence × evidence_factor × freshness_factor × depth_decay)
```

- 同分时按 stable node id、关系类型和路径长度确定性排序；
- 达到 `max_depth`、`max_nodes`、`max_edges`、`deadline` 或 `max_pages` 任一上限后停止，并将
  截断写入 `index_context.query_budget`。

---

## 7. 有界图查询产品化 / Productized Bounded Graph Queries

### 7.1 内部模板，不新增公开工具 / Internal Templates, No New Public Tools

| 内部模板 | 对外入口 | 用途 | 默认上限 |
|---|---|---|---|
| `find_symbols` | `mc_lookup` | 符号、端点、配置、主题定位 | limit 50 |
| `trace_call_paths` | `mc_lookup` / `mc_analyze` | 上下游调用与服务续链 | depth 3，nodes 80 |
| `find_contract_consumers` | `mc_analyze` | DTO/Feign/MQ/HTTP 消费者 | edges 120 |
| `plan_change_risk` | `mc_admin(change_review)` | Git diff 的风险路径、测试缺口 | 最多 12 个文件刷新 |
| `summarize_architecture` | `mc_onboard` | 服务、边界、热点、社区摘要 | 有界投影 |
| `inspect_coverage` | `mc_freshness` | generation 和覆盖状态 | 只读 |

模板参数只能接受：目标、项目、方向、明确的深度/限制和 request tier。不得接受原始 SQL、
Cypher、shell 字符串或无界正则。

### 7.2 查询规划 / Query Planning

```text
intent + target + request_tier
  -> exact symbol/contract lookup
  -> graph-neighbor candidate retrieval
  -> FTS/BM25/semantic candidates only if exact/graph insufficient
  -> graph/ontology/freshness constraint filtering
  -> bounded traversal and deterministic ranking
  -> coverage gate + task-level response assembly
```

检索来源只产生候选，不能自行形成结构事实；任何跨服务链路、调用链或影响结论必须回到
graph relation、契约规则和 freshness/coverage 门禁。

### 7.3 分级合同 / Tier Contract

| 档位 | 允许操作 | 禁止事项 | 适用场景 |
|---|---|---|---|
| `fast` | 精确定位、小范围图邻居、缓存读取 | 否定性/穷尽性结论、深度影响分析 | “在哪里定义” |
| `standard` | 关键路径、覆盖度、来源诊断、有限分页 | 未覆盖范围的完整性声称 | 常规排查、改前定位 |
| `deep` | 完整相关分页、契约和测试风险、显式完整性检查 | 无上限图扫描、自动 reindex | 高风险契约变更 |

缓存键为 `source_signature + active_generation + normalized_template_arguments + tier`；generation
变化必须使缓存失效。缓存只优化重复查询，不能隐藏 freshness 或 coverage 变化。

---

## 8. 运行治理与高可用性 / Runtime Governance and High Availability

### 8.1 可用性模型 / Availability Model

本地单机系统的“高可用”不是多机复制，而是：写入失败或进程中断时，已发布查询能力仍可用，
并且系统能给出确定恢复动作。

| 故障 | 必须保持的能力 | 恢复动作 |
|---|---|---|
| staging reindex 失败 | 上一 active generation 可查询 | 标记 job failed，保留诊断，允许重试 |
| worker 进程中断 | active generation 可查询 | heartbeat/lease 过期后标记 interrupted |
| watcher 异常退出 | 查询与手动刷新可用 | `watcher-start` 显式重启 |
| 读取索引损坏 | 返回结构化 `PARTIAL/STALE`，不伪造结果 | 使用 previous generation 或显式重建 |
| FTS/ANN 维护或失败 | exact/graph 查询仍可用 | 返回降级原因与 retry action |
| 并发写入请求 | 至少一个请求按策略执行，其他请求合并或冲突 | 返回 owner/job 和可行动状态 |

### 8.2 Job 状态机 / Job State Machine

```text
queued -> admitted -> running -> validating -> publishing -> completed
  |          |            |             |             |
  |          └-> coalesced|             |             └-> cancelled
  └-> rejected_budget     └-> cancel_requested -> cancelled
                            └-> failed | interrupted
```

终态：`completed`、`failed`、`cancelled`、`interrupted`、`rejected_budget`。终态不可改写；
重试必须创建新的 job，并通过 `retry_of` 关联旧 job。

### 8.3 Job 记录、owner 与 lease / Job Record, Owner, and Lease

现有 `workspace-jobs.json` 可在迁移期继续作为审查导出；运行时权威记录迁入 SQLite
控制表（或在现有运行时表中等价实现），至少包含：

```text
job_id, kind, workspace_id, scope_fingerprint, request_fingerprint,
owner_session_id, owner_process_id, owner_actor, status,
lease_expires_at, heartbeat_at, cancel_requested_at,
parent_generation, staging_generation, retry_of,
created_at, started_at, completed_at, failure_code, diagnostics_ref
```

规则：

- `owner_actor` 仅是声明身份，除非宿主提供认证上下文，不得表述为已认证身份；
- worker 每 5 秒刷新 heartbeat；lease 至少为 heartbeat 间隔的 3 倍；
- 状态读取发现 lease 过期且 PID 不存在时，CAS 更新为 `interrupted`；
- PID 存在但 heartbeat 过期时返回 `suspected_stalled`，只允许显式取消或人工恢复，避免误杀；
- cancel 为协作式：解析、分片写入、投影和发布前均检查 cancel token；一旦进入 publish transaction，
  只允许完成或回滚，不能中断一半。

### 8.4 锁层级与并发控制 / Lock Hierarchy and Concurrency

锁必须按固定顺序获取，避免死锁：

```text
workspace admission lock
  -> sorted project write locks
    -> generation publish lock
      -> SQLite write transaction
```

- 同一 `scope_fingerprint` 的活动 reindex：请求指纹相同则返回 `coalesced=true`；
- scope 有重叠但请求不同：较小 scope 可在尚未进入解析前合并进待运行 job；已运行时返回
  `conflict` 或排队，不抢占；
- 不重叠项目可并行解析和 staging，但 publish 必须串行；
- 所有读取使用短生命周期只读 SQLite connection 和已发布 generation，不持有写锁；
- 锁文件只承担跨进程排他；SQLite 状态记录是审计和恢复事实。两者都必须存在，不能只信任其一。

### 8.5 原子发布与回滚 / Atomic Publish and Rollback

发布是最小的不可分区：

```text
BEGIN IMMEDIATE;
  verify staging_generation state == validating and integrity gates pass;
  mark previous active generation as superseded;
  mark staging generation as active;
  update active_generation pointer and publish timestamp;
  attach publishing job id;
COMMIT;
```

要求：

- 所有 staging shard、图关系与检索投影在事务前已完成并带 manifest/hash；
- transaction 失败时 rollback，旧 active 指针不变；
- 发布后做只读 smoke（关键元数据、分片可读、FTS 可查询）；smoke 失败时立即使用已知 previous
  generation 执行显式 rollback，并记录 `publish_smoke_failed`；
- generation GC 只删除非 active/previous 的候选代际，且必须显式 `--apply`/`force=true`。

### 8.6 Watcher 调度 / Watcher Scheduling

watcher 不拥有图写入逻辑，只产生规范化变更批次并提交 Job Coordinator：

1. 收集文件事件，路径规范化和去重；
2. debounce 窗口内合并事件，删除优先于修改；
3. 用 `D0 -> R` 算法生成定向刷新 scope；
4. 为同 fingerprint 的活动任务合并；
5. job 完成后仅生成轻量 change-impact report；
6. DTO、Feign、MQ、HTTP、配置等高风险类别只建议显式 `mc_analyze(depth="full")`，不自动深分析。

应提供配置化上限：事件批大小、debounce、并行项目数、CPU worker 数、内存预算、单 job
deadline。任何上限触发都返回可读诊断和 `next_action`，而不是后台无限重试。

---

## 9. 错误语义、观测与安全 / Errors, Observability, and Security

### 9.1 结构化错误码 / Structured Error Codes

| 代码 | 含义 | Agent/用户动作 |
|---|---|---|
| `index_not_published` | 目标 scope 无 active generation | 显式排队定向或全量 reindex |
| `coverage_partial` | 结果范围存在未覆盖/跳过文件 | 不作否定性结论；查看覆盖原因 |
| `generation_stale` | 源码签名晚于 active generation | 使用现有结果并标 stale，或显式刷新 |
| `query_budget_exceeded` | 查询到达深度/节点/时间预算 | 缩小目标或显式提升 tier |
| `reindex_coalesced` | 相同刷新已由其他 job 执行 | 读取对应 job 状态 |
| `reindex_conflict` | 重叠写入无法安全合并 | 等待、排队或显式取消 owner job |
| `lease_interrupted` | worker 已失去 lease | 重试新 job，旧 active 图继续服务 |
| `publish_validation_failed` | staging 未通过完整性门禁 | 修复诊断；不得读取 staging 结论 |
| `semantic_backend_degraded` | ANN/reranker 不可用 | 使用 exact/graph 结果，按需重试 |

所有错误携带 `trace_id`、generation/job 的脱敏标识、阶段、可行动建议；不得回传源码全文、
完整文件路径或自由异常堆栈。

### 9.2 核心指标 / Core Metrics

至少采集聚合值，不采集源码或查询正文：

- 索引：发现、解析、关系补全、图投影、FTS、ANN、发布各阶段耗时；
- 查询：P50/P95/P99、缓存命中、候选来源、截断率、coverage partial 率；
- 质量：anchor recall、edge recall、forbidden hit、unresolved 原因分布；
- 治理：job 合并率、冲突率、取消率、lease 中断率、发布回滚次数；
- 存储：active/previous/staging 数量、graph.db、FTS、ANN、工件体积。

性能 gate 以当前真实基线为准：新增默认读取路径的 P95 不得比同类现有入口基线恶化超过 10%。
没有真实工作区基线时只记录、不宣称优化。

### 9.3 隐私与输入安全 / Privacy and Input Safety

- 仅索引 workspace policy 允许的根目录；解析前解析真实路径并拒绝越界软链接；
- 所有动态输入均视为数据，不得进入 shell、SQL/Cypher 或路径拼接；
- 查询模板用参数绑定，路径和 symbol 使用 allowlisted 规范化规则；
- 图快照导出默认关闭；若将来开放，必须 opt-in、做私有路径/源码泄露检查，并有完整性 hash；
- 外部 parser/LSP/provider 只能经已存在的 provider policy 和显式确认接入，默认不启动外部进程。

---

## 10. 分阶段实施计划 / Phased Implementation Plan

### Phase A：可信查询合同（P0）

**范围**

- 实现 `index_context`、`claim_boundary` 与 coverage 聚合；
- 在 `mc_lookup`、`mc_analyze`、`mc_freshness` 和 change review 中接入；
- 添加否定性结论门禁；
- 建立基线输出与 golden case。

**主要模块**

- `memory_center/core/storage/`：generation/file coverage 读模型；
- `memory_center/core/freshness/`：freshness 与 coverage 组合；
- `memory_center/core/retrieval/`：查询预算、截断和结果融合；
- `memory_center/core/orchestrator/`：task-level response assembly；
- `tests/index_storage/`、`tests/domain/`、`tests/entrypoints/`：合同回归。

**验收**

- coverage partial/stale/truncated 条件下，所有否定性结论均被降级；
- 已有 MCP schema 和返回字段兼容；
- 真实/fixture golden 的 anchor 与 edge 指标不下降；
- 默认查询 P95 不超过同类基线 +10%。

### Phase B：有界图查询模板（P0）

**范围**

- 抽取 `find_symbols`、`trace_call_paths`、`find_contract_consumers`、
  `plan_change_risk` 的内部 query service；
- 统一 fast/standard/deep 的预算与缓存键；
- 以 facade 路由替换分散的直接 graph 调用，不增加 MCP tool。

**验收**

- 主要图查询不依赖 Python 全图物化；
- 相同 generation 与参数下结果排序确定；
- 任何截断都可见，deep 仍有硬预算；
- CLI、HTTP、MCP 对同请求返回同 generation 和证据边界。

### Phase C：Job Coordinator 与原子发布（P1）

**范围**

- 将运行时 job 权威状态收敛到 SQLite；保留 JSON 导出兼容；
- 添加 request/scope fingerprint、owner、lease、合并和冲突语义；
- 将 reindex、watcher、CLI/MCP 的写入统一接入 coordinator；
- 完成 staging validation、原子 publish、publish smoke 和 rollback。

**验收**

- 两个相同 reindex 仅执行一次，另一个可追踪地 coalesce；
- worker 被 kill、异常、取消、SQLite transaction 失败后，旧 active generation 仍查询可用；
- 异常恢复后不会遗留永久 running job 或悬挂 lock；
- watcher 不重复提交相同批次，也不会自动启动深度分析。

### Phase D：解析 IR 和 Java 差分收口（P1）

**范围**

- 为现有 Java/regex 流程建立显式 IR 边界；
- 输出统一 parser diagnostics、resolution reason、unresolved 分类；
- 按失败 case 驱动补 Java resolver，不以表面解析率驱动。

**验收**

- Java parser 与 regex 差异可定位到文件/符号类别但不泄露私有内容；
- 新规则提升目标失败类别且不降低 forbidden-hit/precision；
- 不可证明的目标维持 UNKNOWN/AMBIGUOUS。

### Phase E：通用语言 adapter 试点（P2，按数据触发）

**前置条件**

- Phase A-D 已有真实性能和质量数据；
- 已存在明确的非 Java workspace 需求和可脱敏评测集；
- 不引入外部 daemon 也无法满足结构化定位需求，或原型证明收益显著。

**范围**

- 先实现一种语言的 AST adapter（建议 TypeScript/JavaScript 或 Python，按真实需求选择）；
- 仅支持文件/模块/符号/import/基础 call candidate；
- 通用结果默认 `EXTRACTED` 或 `AMBIGUOUS`，不声称 Spring 级业务语义。

**验收**

- adapter 不影响 Java/Spring 基准；
- 覆盖度、未解析原因、性能和 token 指标均被记录；
- 仅在真实 case 达标后扩展下一语言。

---

## 11. 测试、故障注入与发布门禁 / Testing, Fault Injection, and Release Gates

### 11.1 必须新增或强化的测试 / Required Test Coverage

| 类别 | 场景 |
|---|---|
| 合同 | fresh/full、stale、partial、not-indexed、truncated 时的 `claim_boundary` |
| 解析 | Java overload、lambda、继承、多实现、Feign、MQ、DTO、删除/移动文件 |
| 增量 | 新增/修改/删除/重命名后，active generation 和 shard inheritance 正确 |
| 并发 | 同 fingerprint 合并、重叠 scope 冲突、不重叠项目并行、锁顺序 |
| 取消 | queued/running/validating 可取消；publishing 阶段只完成或回滚 |
| 故障 | worker kill、heartbeat 超时、SQLite busy/transaction failure、publish smoke failure |
| 查询 | 预算截断、确定排序、缓存 generation 失效、FTS/ANN 降级 |
| 入口 | CLI、HTTP、MCP、Workbench 对同一 core 结果一致 |
| 回归 | golden anchor/edge recall、forbidden hit、Java unresolved campaign、P95/token |

### 11.2 故障注入要求 / Fault Injection Requirements

测试中必须可注入以下失败点：

```text
after staging manifest write
after graph projection, before FTS projection
inside publish transaction, before active pointer update
after active pointer update, before publish smoke
during watcher batch coalescing
during job heartbeat and cancellation check
```

每个失败点必须断言：旧 active generation 仍能读取；job 到达可解释终态；下一次显式重试可以
继续；没有遗留错误 lock 或被当作 active 的 staging generation。

### 11.3 最小发布门禁 / Minimum Release Gate

1. 静态检查与全部相关单测；
2. fixture golden：anchor recall、edge recall、forbidden hit；
3. Java 调用解析 unresolved 分类回归；
4. 并发/kill/cancel/publish rollback 故障注入；
5. 真实 workspace 的冷/热查询、局部刷新、完整 reindex 指标；
6. CLI、MCP、HTTP 合同一致性检查；
7. 文档、REFERENCE、MCP_GUIDE、CHANGELOG 按实际公开变化同步。

未拥有真实 workspace 指标时，只能以“实验/观测中”发布，不得宣称性能或高可用目标已达成。

---

## 12. 迁移与回滚 / Migration and Rollback

### 12.1 迁移原则 / Migration Principles

- 所有新响应字段 additive；旧客户端忽略即可工作；
- SQLite 控制表先双写/镜像 JSON job 导出，再切换状态读取；
- 新 query template 先以 feature flag 在 `mc_lookup` 内启用，保留旧路径作回退和差分比较；
- 新 parser adapter 不直接替换 Java 深解析；以单项目、单语言、显式 enable 试点；
- 索引 schema 变更必须带 migration version、前置备份和 downgrade 说明。

### 12.2 回滚条件 / Rollback Triggers

满足任一条件应停止扩大范围，并回滚 feature flag 或 generation：

- golden anchor/edge recall 降低，或 forbidden hit 上升；
- 默认查询 P95 超过基线 +10%，且 profile 未证明收益；
- active generation 读到不一致 shard 或发布失败无法自动恢复；
- coverage 合同使旧结果含义不兼容却没有明确兼容层；
- parser 将外部/多态/未知类型错误提升为确定调用边。

回滚操作顺序：停止新 job admission -> 取消可安全取消的 staging job -> rollback active generation ->
关闭相关 feature flag -> 保留脱敏诊断与基准结果 -> 创建新的修复 job。不得删除失败证据或覆盖历史
generation 审计。

---

## 13. 交付物与责任划分 / Deliverables and Ownership

每个 phase 的交付必须包含以下四类产物：

1. **代码与迁移**：core/application 实现、migration、feature flag、结构化诊断；
2. **测试与基准**：单测、集成、故障注入、golden/真实指标前后对比；
3. **文档**：架构决策、MCP/REFERENCE 变化、运维和回滚说明；
4. **验证回执**：执行命令、退出结果、脱敏摘要、已知限制与下一步。

建议拆分为独立可审查任务：

| 任务包 | 依赖 | 可独立验收 |
|---|---|---|
| A1 coverage 数据投影 | 无 | 文件/分片覆盖状态准确 |
| A2 facade 合同与否定性门禁 | A1 | 不完整索引不作否定性结论 |
| B1 query template 服务 | A2 | 有界、确定、带截断诊断 |
| B2 tier/cache 统一 | B1 | 跨入口一致且 generation 失效正确 |
| C1 SQLite job 账本与 lease | 无 | job 可恢复、状态可审计 |
| C2 合并/锁/取消协调 | C1 | 并发请求无重复写入 |
| C3 原子发布与故障注入 | C2 | active 图在异常下可用 |
| D1 Java IR 与差分诊断 | A1 | 解析边界和失败类别可观察 |
| E1 单语言试点 adapter | D1 + 数据前置 | 不影响 Java 且有真实收益 |

---

## 14. 替代方案与拒绝理由 / Alternatives Considered

### 14.1 直接集成外部 Code Graph MCP

拒绝作为默认方案。它可作为未来只读、显式配置的 Provider 候选，但会引入外部 schema、
生命周期和证据治理边界，且不能替代 Memory Center 的 Spring Cloud 语义、任务记忆、权限与
验证模型。

### 14.2 先重写为 Tree-sitter 多语言索引器

拒绝。它把最大的实现风险放在价值尚未验证的语言覆盖上，且会延后解决 coverage、generation
一致性和并发刷新这些当前用户可见问题。

### 14.3 默认开放自由 Cypher

拒绝。难以控制成本、分页、权限和证据语义，模型也容易绕过任务级完整性与 coverage 门禁。
可在内部维护/调试路径保留受控只读查询，但不作为默认 Agent 表面。

### 14.4 立即引入账户级全局 daemon

暂缓。工作区级 job coordinator 可先解决实际互斥和恢复问题；只有确证存在多个宿主共享同一
索引、且工作区协调无法满足时，才单独评估全局 daemon 的版本、升级和安全模型。

---

## 15. 复核、失效条件与开放问题 / Review, Invalidation, and Open Questions

### 15.1 复核触发 / Review Triggers

在以下事件后必须复核本决策：

- 真实基准显示当前 SQLite 单副本/服务分片设计存在明确不可接受瓶颈；
- 首个非 Java adapter 试点完成；
- 发生 active generation 不一致、错误回滚或无法恢复的生产级本地事故；
- 需要跨工作区共享索引或跨宿主 daemon；
- MCP schema 需要增加无法通过现有 facade 表达的、经过验证的用户需求。

### 15.2 失效条件 / Invalidation Conditions

若真实数据表明 IR 层产生不可接受的额外开销、query template 无法覆盖关键任务、或单工作区
协调无法处理已验证的跨宿主需求，则应记录新的 ADR，重新评估本设计；不得在实现中静默绕过
本文件的不变量。

### 15.3 开放问题 / Open Questions

1. SQLite job 控制表应放入 `graph.db` 还是独立的 workspace runtime SQLite？决定前需确认
   现有迁移和锁模型的最小风险路径。
2. coverage 的“请求范围”如何按 symbol、contract、service 和 traversal 四种查询统一计算？
   Phase A 必须以 fixture + 真实 case 定义可测试语义。
3. publish smoke 需要哪些固定查询才能既证明可读又不泄露项目事实？建议只检查元数据、
   manifest、SQLite 完整性和匿名计数。
4. 第一种通用语言应由真实 workspace 需求决定；在此前不得预设 TypeScript 或 Python 为默认。

---

## 16. 实施检查表 / Handoff Checklist

开发者开始每个任务前：

- [ ] 阅读本文件、`ARCHITECTURE.md`、`MCP_GUIDE.md`、`NEXT_PHASE_MASTER_PLAN.md`；
- [ ] 说明改动属于哪个 phase 与任务包；
- [ ] 确认不会新增平行 MCP facade 或破坏旧 schema；
- [ ] 写出可证伪的性能/质量假设与 stop condition；
- [ ] 为 parser、索引、watcher、job 或 facade 改动补对应测试。

开发者提交前：

- [ ] 已运行目标测试、合同测试和相关 golden gate；
- [ ] 已检查 freshness、coverage、generation 与取消/失败路径；
- [ ] 已确认 active generation 在故障注入后仍可读；
- [ ] 已记录真实基准或明确标记 `real_case_missing`；
- [ ] 没有提交私有索引、真实路径、服务名、源码片段或密钥；
- [ ] 若公开行为变化，已同步 README、ARCHITECTURE、MCP_GUIDE、REFERENCE、CHANGELOG。

