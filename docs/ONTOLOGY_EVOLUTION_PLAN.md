# Ontology Evolution Plan / 本体演进实施计划

## 1. 定位与目标

本计划将 Memory Center 从“索引、检索、任务记忆的组合”升级为**可版本化、可证伪、可追溯的工程知识系统**。它不追求学术化的全量语义网，而是解决真实工程问题：同一条结论从何而来、何时有效、是否验证、被谁否定、会影响哪些任务。

### 成功标准

1. 一个查询结论能定位到实体、关系断言、来源、generation、验证状态和失效原因。
2. `confidence` 不再承担“事实性”“来源”“人工确认”的混合职责。
3. 代码图、变更报告、任务、验证和证据子图可通过同一关系语言关联。
4. 默认 `mc_lookup`、`workspace_status` 不增加全图扫描或明显延迟。
5. 既有 CLI、HTTP、MCP 字段保持 additive 兼容；迁移失败可以回退到旧读模型。

## 2. 设计原则

| 原则 | 实施约束 |
|---|---|
| 实体稳定 | `Method`、`Endpoint`、`Task` 等身份不因一次索引或验证而改变。 |
| 断言可变 | “A 调用 B”“任务影响 C”都是带来源和有效期的 Assertion。 |
| 来源先于置信度 | 先说明 AST、规则、运行时还是人工；`confidence` 仅用于排序。 |
| 验证可证伪 | 人工确认可以 `VERIFY`，也可以 `REJECT`，不能只追加正向记录。 |
| 时间是一级事实 | 所有可变结论必须关联 generation 或观测时间。 |
| 默认有界 | 任何查询仅读取目标断言与有界邻接；历史和全局聚合必须显式执行。 |
| 隐私优先 | Assertion 只存稳定标识、脱敏摘要、hash/ref，不保存源码正文、原始对话和工具 payload。 |

## 3. 目标本体模型

### 3.0 认识论与否定性结论

Memory Center 采用开放世界假设：图中没有关系不等于关系不存在。所有否定性或不完整结论必须使用下列状态，而不得以空数组暗示“没有影响”：

| 状态 | 含义 | 用户体验 |
|---|---|---|
| `NOT_FOUND` | 在当前查询范围内未发现目标 | 显示检索范围与细化入口。 |
| `UNKNOWN` | 证据不足，无法判断 | 显示缺失证据和推荐验证动作。 |
| `NOT_INDEXED` | 文件、项目或语言尚未索引 | 显示局部 reindex 命令。 |
| `STALE` | 结论可能被源码或 generation 变化影响 | 显示受影响文件与刷新入口。 |
| `REJECTED` | 有人工或运行时反证 | 显示否定决策和原因摘要。 |

所有负向结果新增兼容字段 `absence_reason`、`scope_checked`、`next_action`。任何 API 都不得把 `NOT_FOUND` 自动转换为“没有调用/没有影响”的事实性语言。

### 3.1 实体层 Entity

实体代表可稳定识别的对象，至少包括：

- 代码：`Workspace`、`Service`、`File`、`Class`、`Method`、`Field`、`Endpoint`、`FeignClient`、`MQTopic`、`ConfigKey`。
- 工程活动：`ChangeSet`、`Analysis`、`EvidenceSubgraph`、`ArchitectureCommunity`。
- 协作与治理：`Task`、`Session`、`Validation`、`Decision`、`ChangeImpactReport`、`Artifact`。

实体统一字段：

```json
{
  "entity_id": "Method:order-service:com.example.OrderService:create",
  "entity_type": "Method",
  "workspace_id": "ucap",
  "project": "order-service",
  "display_name": "OrderService#create",
  "identity_version": 1,
  "created_at": "ISO-8601"
}
```

`entity_id` 是身份，不携带一次分析的置信度、generation 或人工结论。

### 3.2 关系类型 RelationType

RelationType 描述允许的谓词，例如 `DECLARES`、`CALLS_METHOD`、`AFFECTS`、`VERIFIES`、`REJECTS`、`SUMMARIZES`、`EXPLAINS`。每个类型必须在 registry 中声明：

- 允许的 source / target entity type。
- 是否可跨 workspace。
- 默认 provenance_kind。
- 是否允许人工验证、是否支持失效。
- 默认查询方向和最大安全深度。

禁止在入口层凭字符串临时创造关系类型。

### 3.3 断言层 Assertion

Assertion 是“某主体与客体存在某种关系”的可变、可审计表述。

```json
{
  "assertion_id": "asr:sha256:...",
  "subject_id": "Method:...",
  "predicate": "CALLS_METHOD",
  "object_id": "Method:...",
  "provenance_kind": "STATIC",
  "assertion_status": "EXTRACTED",
  "confidence": 0.82,
  "evidence_refs": ["ev:graph-edge:..."],
  "generation_id": "gen-...",
  "observed_at": "ISO-8601",
  "valid_from": "ISO-8601",
  "valid_to": null,
  "supersedes": "",
  "metadata": {"resolution_level": "receiver_resolved"}
}
```

### 3.4 两个正交维度

`provenance_kind`：`STATIC`、`RUNTIME`、`HUMAN`、`DERIVED`。

`assertion_status`：`EXTRACTED`、`INFERRED`、`VERIFIED`、`REJECTED`、`STALE`、`SUPERSEDED`。

规则：

- `VERIFIED` 必须有 `Validation`、`Decision` 或可追溯 runtime evidence。
- `REJECTED` 不能删除原 Assertion，只能关闭其有效区间并写明 decision ref。
- `STALE` 表示索引或源文件已变化，不能被当作不存在。
- `confidence` 不能把 `INFERRED` 提升为 `VERIFIED`。

### 3.5 跨域关系

新增但保持轻量的治理关系：

| 谓词 | 含义 |
|---|---|
| `Task AFFECTS Entity` | 任务修改或风险覆盖某代码实体。 |
| `Analysis EXPLAINS Assertion` | 分析结果解释某个断言。 |
| `Validation VERIFIES Assertion` | 验证为断言提供证据。 |
| `Decision ACCEPTS/REJECTS Assertion` | 人工确认或否定结论。 |
| `ChangeImpactReport SUMMARIZES ChangeSet` | watcher 报告归纳一次变化。 |
| `EvidenceSubgraph EXPLAINS Analysis` | 导出物是一次分析的受限证据视图。 |

### 3.6 身份、别名与等价性

每个实体拥有稳定 `canonical_id`，外部名称通过 Alias 表达，避免把 Maven artifact、Feign name、Nacos 服务名、网关 route、旧模块名误当成独立实体。

| 关系 | 含义 |
|---|---|
| `ALIAS_OF` | 当前名称指向 canonical entity。 |
| `SAME_AS` | 两个外部身份经过证据确认等价。 |
| `RENAMED_FROM` | 当前实体由旧身份重命名而来。 |
| `REPLACES` | 当前实体替代历史实体，但不等价。 |

Alias 必须记录 `identity_confidence`、来源、有效期；低置信别名不能参与默认跨服务自动合并。

### 3.7 双时间模型

断言同时记录事件时间与知识时间：

- `event_at`：代码提交、运行事件或人工决策实际发生的时间。
- `observed_at`：Memory Center 获取并写入知识的时间。
- `valid_from / valid_to`：断言在指定 generation/事实版本中的有效范围。

这使系统能解释“代码昨天已经修改、今天才被索引”的延迟，并支持按当时知识或按当时代码两种历史回放。

### 3.8 因果、结构与相关性

关系必须标注 `relation_mode`：

- `STRUCTURAL`：AST、配置或显式声明提取的结构关系。
- `CAUSAL_CANDIDATE`：可能形成影响传播的可验证链路。
- `CORRELATIONAL`：共变更、语义相似、中心性、风险相关等统计关联。

社区、高中心性、`HISTORICALLY_RELATED`、`RISK_CORRELATED` 只能显示“关联/候选影响”，不得生成“因为 A 所以 B”的因果表述，除非有 runtime 或人工验证 Assertion。

### 3.9 规范与行动本体

治理对象升级为一等实体：`Policy`、`Constraint`、`Decision`、`Exception`、`Waiver`、`GateResult`。它们通过 `GOVERNS`、`VIOLATES`、`WAIVES`、`APPROVES` 关联到 Entity、Task 和 Assertion。

`Action` 也是一等对象，而非提示文案：

```json
{
  "action_type": "verify_contract",
  "preconditions": ["assertion_status=INFERRED", "risk=high"],
  "expected_evidence": "Validation ref",
  "cost": "lightweight",
  "stop_condition": "validation recorded",
  "fallback": "request_deep_analysis"
}
```

每个 `agent_next_steps` 必须能映射到 Action；它明确说明为什么做、成本、停止条件和失败回退，避免 Agent 或用户无界重试。

## 4. 存储与迁移设计

### Phase A：Registry 对齐（已完成）

1. 以 `core/knowledge/ontology.py` 为唯一 registry。
2. 补齐 `File`、`Bean`、`DataResource` 等已使用节点，删除或标记未实现关系。
3. 由 registry 生成/校验 `ONTOLOGY.md` 表格，禁止手工漂移。
4. 新增 `RelationTypeSpec`，在单元测试中校验 source/target 类型约束。

验收：文档、registry、indexer 实际输出三者无未知类型；CI 给出明确差异。当前已完成第一版，后续新增类型继续受同一门禁约束。

### Phase B：Assertion Sidecar（已完成第一版）

1. 新建 `.memory-center/memory/assertions.jsonl` 与 SQLite mirror，不改写既有 `edges` 表。
2. 每次 reindex/局部 refresh 为新边写 Assertion；旧边读取仍可工作。
3. `assertion_id` 以 subject、predicate、object、generation、来源的稳定 hash 生成。
4. 增加 `assertion-index.json`，只保存活跃 Assertion 的有界读模型。

验收：旧查询结果不变；新查询可选返回 `assertion_ref`；写入失败不阻断索引发布。

当前实现以 `assertions.jsonl` 保留审计流，以 `memory.db.assertions` 提供活跃断言索引；证据子图仅在有已发布 sidecar generation 时附加 `assertion_ref`，不在普通图查询中引入额外扫描。

### Phase C：时间与失效（已完成第一版）

1. generation 发布后关闭被替代 Assertion 的 `valid_to`。
2. watcher dirty path 只标记相关 Assertion 为 `STALE`，不触发全局回写。
3. 支持 `as_of_generation` 与 `as_of_time` 的显式历史查询，默认只读取 active Assertion。
4. 每日裁剪 30 天的运行/审计断言；静态断言按 generation 保留策略裁剪。
5. 增加 Alias sidecar，支持 canonical identity、重命名与替代关系；历史查询可选择事件时间或知识时间。

验收：历史任务可解释“当时为什么成立”；默认查询不读取过期历史。

当前已提供按 generation 或时间点的有界读取，默认仅读取 active Assertion；文件级 `STALE` 标记已接入 watcher dirty journal，只更新关联文件的断言。Alias sidecar 支持 canonical identity、重命名链和循环歧义，不会改写历史实体 ID。

### Phase D：治理闭环

1. 将 change-impact confirm 映射为 `Decision` 与 `VERIFIES/REJECTS` Assertion。
2. `mc_close` 的验证摘要创建 `Validation`，只关联脱敏 evidence ref。
3. evidence subgraph 增加 Assertion 状态、generation、验证摘要引用。
4. 社区分析明确标为 `DERIVED + INFERRED`，不作为代码事实传播。
5. 将 Policy、GateResult、Decision 和 Action 写入跨域关系读模型；默认结论只返回最小证据集。

验收：从 Task 可回溯到变更、断言、验证和最终结论。

当前已完成 change-impact confirmation、任务关闭验证到治理断言的投影；证据子图会按目标节点精确呈现关联治理关系。跨域读模型保持为有界 index，不进入普通图查询。

## 5. API 与体验设计

### 5.1 默认查询体验

`mc_lookup`、CLI query、HTTP query 保持原字段；新增兼容字段：

```json
{
  "assertion_summary": {
    "active": 12,
    "verified": 3,
    "inferred": 6,
    "stale": 1,
    "next_action": "验证 1 条高风险推断"
  }
}
```

默认只展示与答案直接相关的最多 20 个 Assertion，详细证据通过 `assertion_ref` 按需展开。

当前默认查询已返回兼容的聚合 `assertion_summary`；evidence subgraph 提供有界 assertion ref，CLI、HTTP 和 MCP 均可按 ref 展开断言详情。

### 5.1.1 可信结论卡

CLI、HTTP 和 Workbench 默认使用同一结论卡，而不是直接抛出图边：

```text
结论：订单创建可能影响库存服务
状态：INFERRED，等待验证
证据：Feign 映射 + 2 条调用断言
新鲜度：当前 generation
风险：高
下一步：运行契约检查，预计轻量
```

展开后才显示节点、关系、confidence、generation、规则、验证和历史。所有状态徽标必须可行动：`VERIFIED` 展示来源，`INFERRED` 展示验证入口，`STALE` 展示刷新入口，`UNKNOWN` 展示缺失证据，`REJECTED` 展示否定决策。

### 5.2 人工确认体验

确认 UI/CLI 只要求三项：结论、验证状态、短摘要；task/session/验证人自动带入已有上下文。用户可选择：

- `验证成立`
- `发现误报`
- `需要深度分析`
- `已处理`

系统必须明确显示“此操作改变的是断言状态，不会修改源码或删除历史证据”。

### 5.3 排障体验

`inspect` 增加本体诊断：未知类型、缺少来源、VERIFIED 无验证引用、活跃 Assertion 指向旧 generation、registry/doc drift。每个问题给出一条命令级修复建议。

## 6. 性能预算

| 路径 | 预算 | 实现要求 |
|---|---|---|
| 默认查询 | 额外 < 10ms / 有界读取 | active Assertion index，最多 20 条。 |
| 局部 refresh | 额外 < 5% | 仅写受影响文件节点的 Assertion。 |
| 完整 reindex | 额外 < 10% | 批量写入与单事务，禁止逐条 SQLite commit。 |
| 历史查询 | 显式调用 | 限定 generation/time window 与 500 条上限。 |
| 社区/全局审计 | 显式后台或命令 | 仅 SQL 聚合，禁止进入 status/query。 |

体验约束：默认结论必须遵守最小解释原则，只展示支撑结论的最小证据集；遵守最小惊讶原则，缓存、推断、刷新或 generation 造成结论变化时必须说明何时变化、为何变化、影响什么。

所有预算以真实 workspace P50/P95 为发布门禁，不以示例项目替代。

当前提供 `memory-center eval-ontology-gate --workspace <workspace.yaml>`，用于验证默认查询新增 assertion summary 的真实 workspace P50/P95 门禁。

当前还提供 `memory-center eval-assertion-scope-gate --workspace <workspace.yaml> --path <logical-path>`，默认只读地校验局部刷新选中的断言边数必须小于全图边数且不超过范围上限。只有在需要验证真实局部发布时，才显式追加 `--apply`；该选项会产生一个新的局部索引 generation。

## 7. 测试与发布门禁

每个阶段必须增加：

1. registry 与 `ONTOLOGY.md` 一致性测试。
2. 实体/关系类型约束测试。
3. Assertion 生命周期：创建、验证、拒绝、失效、替代、裁剪。

当前已覆盖创建、验证、拒绝、文件级失效与 generation 替代；运行/审计 JSONL 的 30 天、10 万条裁剪复用 WorkspaceStore 既有保留策略。
4. 负向结论、别名归并、双时间查询、因果/相关性语言和 Action 停止条件测试。
5. CLI/HTTP/MCP 三入口一致性测试。
6. 旧 schema 回归与旧索引读取测试。
7. 真实 workspace 的 anchor recall、edge recall、forbidden hit、P50/P95、token 指标对比。

发布阻断条件：未知关系类型、`VERIFIED` 无证据、将 UNKNOWN 表述为不存在、相关性表述为因果、默认查询全图扫描、无停止条件的 Action、性能超过预算、私有正文写入 Assertion。

## 8. 交付顺序与里程碑

| 版本 | 交付 | 完成定义 |
|---|---|---|
| O1 | Registry 对齐 | 文档/代码/索引类型一致。 |
| O2 | Assertion Sidecar | 新旧读模型并存，查询可返回 ref。 |
| O3 | 时间与失效 | generation、stale、历史读取可解释。 |
| O4 | 验证与决策闭环 | confirmation、validation、task 跨域关联。 |
| O5 | 体验与门禁 | 结论卡、Action、inspect、真实 benchmark 全部可用。 |

任何阶段若真实指标退化，停止推进下一阶段，保留 sidecar 并回滚默认读取。

## 9. 非目标

- 不引入远程图数据库或 RDF/OWL 运行时。
- 不把所有 JSONL/Markdown 迁移为图节点。
- 不因本体重构破坏 MCP facade 或既有 dict schema。
- 不在普通查询中推理全量跨域关系。
- 不将 LLM 输出自动升级为 VERIFIED。

## 10. 收尾实现状态（4.1.34）

- 查询与状态入口已提供兼容的 `knowledge_state`，避免以空结果表达不存在；断言支持有效期、事件时间与观测时间查询。
- 治理实体、关系、Action 读模型、验证别名和全入口断言确认已接入；旧 sidecar 可通过 `ontology-migrate` 预检或显式回填。
- `eval-ontology-gate`、`eval-assertion-scope-gate` 与 `eval-assertion-reindex-gate` 覆盖默认查询、局部范围和隔离 reindex 开销门禁。
