# Ontology / 轻量本体论

## 1. 目的

这份文档不是学术本体论说明，而是 `memory-center` 的**轻量领域约束**。

它要解决的问题是：

- 同一个词在不同链路里是不是同一种东西
- 哪些关系是事实，哪些只是推断
- `query / contracts / chain / timeline / ref / task` 应该说同一种语言

如果没有这层约束，系统很容易继续出现：

- 意图误判
- contracts 误关联
- chain 边界不清
- timeline / ref / receipt / task 各自长一套语义

## 2. 核心实体

### 2.1 代码实体

从代码仓库中静态提取，由 indexer 构建，落到 graph store。

| 实体 | ID 模式 | 来源 | 分类 |
|------|---------|------|------|
| **Service** | `Service:{name}` | workspace.yaml | 结构性 |
| **File** | `File:{path}` | 文件系统 | 结构性 |
| **Class** | `Class:{project}:{fqcn}` | Java AST | 声明性 |
| **Method** | `Method:{project}:{class}:{method}` | Java AST | 声明性 |
| **Field** | `Field:{project}:{class}:{field}` | Java AST | 声明性 |
| **ConfigKey** | `ConfigKey:{project}:{key}` | YAML/properties | 声明性 |
| **Endpoint** | `Endpoint:{project}:{http_method}:{path}` | @RequestMapping 等 | 契约性 |
| **FeignClient** | `FeignClient:{project}:{interface}` | @FeignClient | 契约性 |
| **FeignMethod** | `FeignMethod:{project}:{interface}:{method}` | Feign 接口 | 契约性 |
| **MQTopic** | `MQTopic:{topic}` | @KafkaListener 等 | 契约性 |
| **MQConsumer** | `MQConsumer:{project}:{class}:{topic}` | @KafkaListener 等 | 契约性 |
| **MQProducer** | `MQProducer:{project}:{class}:{topic}` | KafkaTemplate 等 | 契约性 |
| **Bean** | `Bean:{project}:{type}` | @Autowired 等 | 推断性 |
| **DataResource** | `{kind}:{name}` | Java symbol 解析 | 推断性 |

**实体分类说明：**
- **结构性**：由文件系统和配置直接决定，不含推断
- **声明性**：由源码 AST 直接提取，不含推断
- **契约性**：由注解和框架约定提取，依赖框架语义
- **推断性**：由类型推断和上下文分析得出

### 2.2 记忆实体

由工作流运行时产生，落到 memory 层（JSONL / SQLite）。

| 实体 | 来源 | 层级 | 说明 |
|------|------|------|------|
| **SessionEvent** | session-events.jsonl | L0 | 会话事件（工具调用、读写、错误） |
| **WriteReceipt** | write-receipts.jsonl | L0 | 写入回执（记忆层写入审计） |
| **ValidationReceipt** | 任务 `verification-receipts.jsonl` + SQLite `delivery_receipts` | L0 | 验证审计事实；人工身份标记为调用方自声明，SQLite 仅作按任务增量查询读模型 |
| **Ref** | refs/ 目录 | L0 | 大 payload 外置引用 |
| **SessionNote** | session-notes.jsonl | L0.5 | 显式记录的跨任务叙事事实（decision/preference/rule/next_step/fact）；fingerprint 幂等，supersede 留 `superseded_by` 审计链，forget 仅隐藏具名条；隐私门 fail-closed |
| **TaskShadow** | SQLite `session_state`（`task_shadow_*` 状态族） | L1（临时影子） | Session-first 会话影子；各源 contribution 确定性 merge，未绑定不写 L2 |
| **Task** | tasks/ 目录 | L2 | 任务空间（含工件） |
| **Handoff** | handoff-history.jsonl | L1 | 模型交接记录 |
| **ResumePacket** | 运行时生成 | L1 | 恢复上下文包 |
| **TokenGain** | token-gain-log.jsonl | L0 | Token 节省记录 |
| **BenchmarkTrend** | benchmark-trends.jsonl | L0 | 基准趋势数据点 |
| **DeliverySkill** | `artifacts/skills/delivery-skill-registry.json` | L2 | 从已验证交付派生的可复用经验，带稳定 ID、activation、适用/禁止边界、验收证据、停止/回滚及 I/O 契约 |
| **SkillObservation** | delivery-skill-observations.jsonl | L0 | 对 canary/published Skill 的有界效果观测，绑定 `activation_id`、`contract_sha256` 和可解析验证回执 |
| **SkillReplay** | SkillObservation 内嵌派生投影 | L0 | 自动派生的脱敏回放，仅含契约哈希、语言、结果、证据引用和性能指标；旧独立 JSONL 仅作历史读取 |
| **FailureCandidate** | delivery-failure-candidates.json | L2 | 仅含哈希任务引用、验证 profile、验收标识和证据引用的离线失败模式候选 |

### 2.3 运行/治理实体

- `Lookup` — 知识查询
- `Analyze` — 变更分析
- `Sync` — 上下文同步
- `Resume` — 任务恢复
- `Close` — 会话收尾
- `Audit` — 完成审计
- `QualityGate` — 只读发布质量决策，汇总 generation、coverage、replay、IR、刷新与存储；状态为 `pass|attention|block|real_case_missing`
- `RefreshBucket` — 局部刷新性能的 `category + scope` 分桶；只有真实样本达到门槛才参与 P95 门禁
- `PrimaryChain` — 从 Method 锚点到跨服务 Feign/HTTP 证据的有界检索投影；它是 retrieval 结果，不是持久化图事实

## 3. 关系类型

### 3.1 代码关系（intra-workspace graph edges）

| 关系 | 源 → 目标 | 置信度 | 语义强度 | 说明 |
|------|-----------|--------|----------|------|
| CONTAINS | Workspace → Service | 1.0 | fact | 工作区包含服务 |
| CONTAINS | Service → File | 1.0 | fact | 服务包含文件 |
| DECLARES | File → Class | 1.0 | fact | 文件声明类 |
| DECLARES | Class → Method | 1.0 | fact | 类声明方法 |
| DECLARES | Class → Field | 1.0 | fact | 类声明字段 |
| DECLARES | Class → FeignClient | 1.0 | fact | 类声明 Feign 客户端 |
| DECLARES | FeignClient → FeignMethod | 1.0 | fact | Feign 接口声明方法 |
| DECLARES_CONFIG | File → ConfigKey | 1.0 | fact | 文件声明配置项 |
| EXPOSES_ENDPOINT | Class → Endpoint | 1.0 | fact | Controller 暴露端点 |
| HANDLES_ENDPOINT | Method → Endpoint | 0.9 | inferred | 方法处理端点 |
| CALLS_SERVICE | FeignClient → Service | 0.9 | inferred | Feign 调用目标服务 |
| IMPLEMENTS_FEIGN | FeignMethod → Endpoint | 0.78 | inferred | Feign 方法映射到端点 |
| PRODUCES_TOPIC | MQProducer → MQTopic | 1.0 | fact | 生产者发布主题 |
| CONSUMES_TOPIC | MQConsumer → MQTopic | 1.0 | fact | 消费者订阅主题 |
| INJECTS_BEAN | Class → Bean/Class | 0.82 | inferred | Bean 注入 |
| CALLS_METHOD | Method → Method | 0.58-0.68 | inferred | 方法调用（有/无 receiver_type） |
| TOPIC_CANONICAL_MATCH | 不持久化 | — | inferred | 禁止作为图边写入；没有可证明 destination 时 MQ 主链只能 `insufficient_evidence` |
| READS_FIELD | Method → Field | 0.62-0.74 | inferred | 字段读取 |
| READS_CONFIG | Class → ConfigKey | 0.84 | inferred | 配置使用 |
| IMPORTS | File → File | 0.55 | derived | 文件导入 |
| USES_DATA_RESOURCE | Class → DataResource | 0.72 | derived | 数据资源使用 |

### 3.2 跨工作区桥接关系（cross-workspace bridges）

| 桥接类型 | 置信度 | 语义强度 | 说明 |
|----------|--------|----------|------|
| FEIGN_SERVICE | 0.95 | inferred | Feign 客户端指向另一工作区的 Service |
| FEIGN_ENDPOINT | 0.88 | inferred | Feign 方法路径匹配另一工作区的 Endpoint |
| MQ_TOPIC_CONFIG | 0.84 | inferred | 配置项映射到另一工作区消费的 Topic |
| MQ_TOPIC_SHARED | 0.72 | derived | 两个工作区共享同一 Topic |
| CONFIG_KEY_SHARED | 0.66 | derived | 两个工作区声明同一配置键 |

### 3.3 记忆关系

- `REFERENCES` — Ref 引用 SessionEvent / WriteReceipt
- `BELONGS_TO_TASK` — SessionEvent / WriteReceipt 属于 Task
- `DERIVED_FROM` — ResumePacket / HandoffPacket 从 SessionEvent 派生
- `SUMMARIZES` — SessionSummary 总结 Session
- `HANDOFF_OF` — Handoff 是某次 Session 的交接
- `RESUME_OF` — ResumePacket 是某次 Session 的恢复
- `CANDIDATE_FROM` — DeliverySkill 候选来源于已关闭、已验证的 Task
- `OBSERVES` — SkillObservation 记录 DeliverySkill 的真实使用结果
- `PROMOTES` — 满足证据阈值后 canary Skill 显式发布
- `ROLLS_BACK` — 回归时将 Skill 撤出默认推荐，保留历史证据

## 4. 语义强度

所有关系和结果，原则上分成三类：

### `fact`（事实）

- 来源：源码 AST、注解解析、配置文件直接声明
- 置信度范围：1.0
- 例子：`Class` 声明 `Method`、`FeignClient` 声明 `FeignMethod`、`MQConsumer` 订阅 `MQTopic`
- 特点：**不会因为上下文变化而改变**，除非源码本身修改

### `inferred`（推断）

- 来源：注解语义推断、路径匹配、类型分析、命名约定
- 置信度范围：0.78 - 0.95
- 例子：`FeignMethod` 映射到 `Endpoint`（路径匹配）、`CALLS_SERVICE`（@FeignClient target 解析）、`INJECTS_BEAN`（@Autowired 推断）
- 特点：**高度可信但依赖推断规则**，规则变化可能影响结果

### `derived`（衍生）

- 来源：间接关联、统计推断、跨工作区共享检测、多源聚合
- 置信度范围：0.55 - 0.74
- 例子：`CALLS_METHOD`（无 receiver_type）、`IMPORTS`（import 语句）、`ResumePacket`、`HandoffPacket`、`CompletionAudit`、`RetrievalSummary`
- 特点：**参考价值为主**，不适合作为强断言

### 强度使用规则

1. **查询结果展示**：fact 关系不需要额外标注，inferred/derived 关系应标注 `confidence` 字段
2. **链路分析**：纯 fact 链路可以高置信展示，inferred 链路应标注推断来源
3. **影响分析**：只对 fact + inferred 关系做变更影响传播，derived 关系仅作参考
4. **审计检查**：fact 关系的变化才算"变更"，derived 关系的变化算"漂移"
5. **推断链路衰减**：多跳链路置信度逐跳衰减 — 2跳 ×0.9，3跳 ×0.8，4+跳 ×0.7

## 5. 当前最重要的约束

### 5.1 `Service` 不等于 `FeignClient`

- `ArticleService` 更偏本地代码实体
- `ArticleFeignClient` / `FeginAutomaticReviewTaskService` 更偏远程调用实体

不能因为名字里有 `Service` 就默认走 Feign 路线。

只有满足以下条件之一的才应被识别为 Feign：
- 类名匹配 `Feign*Service` 或 `*FeignClient`（不含独立 `*Client`）
- 存在 `@FeignClient` 注解
- 在 `feign-index.json` 中注册

### 5.2 `Endpoint` 不等于 `Controller`

- `Controller` 是实现载体
- `Endpoint` 是接口暴露点

两者相关，但不是同一层对象。

### 5.3 `Ref` 不是原始数据本身

- `Ref` 是可追溯入口
- 真正详情要通过 ref 展开

所以 facade 输出里优先给 `summary + ref_id`，不是直接塞大 payload。

### 5.4 `Task`、`Session`、`Receipt` 是不同层对象

- `Task`：工作目标和上下文（L2）
- `Session`：一次工作过程（L0）
- `WriteReceipt`：一次具体写入记录（L0）

它们之间要通过关系关联，而不是混成一个大对象。

### 5.5 Endpoint 路径需要足够具体

只有路径至少包含 2 段（如 `/api/users`）的 Endpoint 才参与 Feign→API 自动关联。
单段路径（如 `/`）关联置信度太低。

### 5.6 Contract 过滤需要分层置信度

`_filter_contracts_by_query` 的结果应标注置信度：

| 匹配方式 | confidence | 说明 |
|----------|-----------|------|
| 接口名精确匹配 | 0.95 | query 是接口名的子串或完全匹配 |
| 方法名精确匹配 | 0.85 | query 是方法名的子串 |
| Token 匹配 | 0.60 | query 的 token 出现在接口名中 |
| JSON 全文扫描 | 0.30 | query 的 token 出现在 contract JSON 任意位置 |
| 无匹配回退 | 0.10 | 标记 `is_fallback: true`，返回 top-N |

### 5.7 跨工作区桥接不等于事实

跨工作区桥接（bridges）的最高置信度是 0.95（FEIGN_SERVICE），仍然是 inferred 强度。
不应将桥接关系当作 fact 处理。

### 5.8 推断链路衰减

多跳推断链路的置信度应逐跳衰减：

- 2 跳：取各跳最小置信度 × 0.9
- 3 跳：取各跳最小置信度 × 0.8
- 4+ 跳：取各跳最小置信度 × 0.7

### 5.9 Skill 不是事实源

- `DeliverySkill` 是从已验证交付派生的可复用操作结构，不是源码或业务事实。
- `candidate` 和 `canary` 只能作为待验证建议，默认查询不可将它们作为正式经验。
- 只有 `published` Skill 才可参与默认推荐；发布依赖外部验证证据，不接受模型自评。
- `rolled_back` 不代表历史任务被删除或结论被篡改，只表示该经验不再被默认建议使用。

## 6. 意图到实体的映射

查询意图（`detect_query_intent`）决定优先检索哪些实体和关系：

| 意图 | 优先实体 | 优先关系 |
|------|----------|----------|
| feign | FeignClient, FeignMethod | CALLS_SERVICE, IMPLEMENTS_FEIGN |
| mq | MQTopic, MQConsumer, MQProducer | PRODUCES_TOPIC, CONSUMES_TOPIC |
| endpoint | Endpoint, Class, Method | EXPOSES_ENDPOINT, HANDLES_ENDPOINT |
| config | ConfigKey, Field | READS_CONFIG, DECLARES_CONFIG |
| chain | Method, Class | CALLS_METHOD, CALLS_SERVICE |
| class | Class, Service | DECLARES, CONTAINS |
| method | Method | CALLS_METHOD, HANDLES_ENDPOINT |
| general | （无优先） | （无优先） |

## 7. 本体论先作用到哪里

第一批最应该被 ontology 约束的是：

1. `detect_query_intent`
2. `memory_query_hybrid`
3. `contracts / chain / group_chain`
4. `timeline / ref / receipt / task`

## 8. 落地原则

这份 ontology 的目标不是把系统做重，而是：

- 先统一领域语言
- 再统一关系表达
- 再统一事实/推断边界

后续如果某个行为“看起来像 bug，但其实是语义边界不清”，优先回来看这份文档，而不是先继续堆特殊规则。

### 3.1b V3 扩展关系（V3 Extended Graph Edges — §3.4 + §20.5.2）

以下关系类型在 V3 中新增，用于支持代码理解、推理和治理能力。

| 关系 | 源 → 目标 | 语义强度 | 说明 |
|------|-----------|----------|------|
| TRANSITIVELY_CALLS | Method → Method (多跳) | derived | 调用链传递闭包 |
| DATA_FLOWS_TO | DataFlowNode → DataFlowNode | inferred | 数据流传递 |
| CONFIG_PROPAGATES | ConfigKey → ConfigKey | inferred | 配置传播 |
| HISTORICALLY_RELATED | Entity → Entity | derived | 历史共变更关联 |
| SEMANTIC_SIMILAR | Entity → Entity | derived | 语义相似度 |
| RISK_CORRELATED | Entity → Entity | derived | 风险相关性 |
| ROUTES_TO | RouteNode → Endpoint | confirmed | HTTP/RPC/MQ 路由映射 |
| IMPLEMENTS_FLOW_STEP | Method → FlowStep | inferred | 方法实现流程步骤 |
| NEXT_STEP | FlowStep → FlowStep | inferred | 顺序流程步骤 |
| EXPLAINS | CodeSummary → Entity | derived | 代码摘要解释 |
| STALE_FOR | IndexFreshness → Entity | runtime | 索引新鲜度标记 |

这里的 `confirmed` 和 `runtime` 是当前代码 registry 已使用的语义强度扩展值：

- `confirmed`：由明确代码结构或声明直接确认的事实关系。
- `runtime`：运行期状态关系，不应与静态代码事实混合推断。
- `fact`、`inferred`、`derived` 仍用于其余静态事实、推断和派生关系。

新增或修改语义强度时，必须同步更新 ontology registry、本文档和覆盖全部 edge type 的测试。

本体 registry 已覆盖索引器实际产出的 `HANDLES_ENDPOINT`、`IMPLEMENTS_FEIGN`、`INJECTS_BEAN`、`READS_FIELD`、`USES_DATA_RESOURCE`、`DECLARES_CONFIG` 等边；CI 会校验索引器字面量边类型均已注册。新增关系必须先在 registry 声明 endpoint、来源和关系模式，再进入索引器。

---

# Part II: 本体演进计划

## 演进目标

将 Memory Center 从"索引、检索、任务记忆的组合"升级为**可版本化、可证伪、可追溯的工程知识系统**。不追求学术化的全量语义网，而是解决真实工程问题：同一条结论从何而来、何时有效、是否验证、被谁否定、会影响哪些任务。

### 成功标准

1. 一个查询结论能定位到实体、关系断言、来源、generation、验证状态和失效原因。
2. `confidence` 不再承担"事实性""来源""人工确认"的混合职责。
3. 代码图、变更报告、任务、验证和证据子图可通过同一关系语言关联。
4. 默认 `mc_lookup`、`workspace_status` 不增加全图扫描或明显延迟。
5. CLI、HTTP、MCP 的公开命令和关键字段保持稳定。

### 设计原则

| 原则 | 实施约束 |
|---|---|
| 实体稳定 | `Method`、`Endpoint`、`Task` 等身份不因一次索引或验证而改变。 |
| 断言可变 | "A 调用 B""任务影响 C"都是带来源和有效期的 Assertion。 |
| 来源先于置信度 | 先说明 AST、规则、运行时还是人工；`confidence` 仅用于排序。 |
| 验证可证伪 | 人工确认可以 `VERIFY`，也可以 `REJECT`，不能只追加正向记录。 |
| 时间是一级事实 | 所有可变结论必须关联 generation 或观测时间。 |
| 默认有界 | 任何查询仅读取目标断言与有界邻接；历史和全局聚合必须显式执行。 |
| 隐私优先 | Assertion 只存稳定标识、脱敏摘要、hash/ref，不保存源码正文、原始对话和工具 payload。 |

## 目标本体模型

### 认识论与否定性结论

采用开放世界假设：图中没有关系不等于关系不存在。所有否定性或不完整结论必须使用下列状态：

| 状态 | 含义 | 用户体验 |
|---|---|---|
| `NOT_FOUND` | 在当前查询范围内未发现目标 | 显示检索范围与细化入口。 |
| `UNKNOWN` | 证据不足，无法判断 | 显示缺失证据和推荐验证动作。 |
| `NOT_INDEXED` | 文件、service 或语言尚未索引 | 显示局部 reindex 命令。 |
| `STALE` | 结论可能被源码或 generation 变化影响 | 显示受影响文件与刷新入口。 |
| `REJECTED` | 有人工或运行时反证 | 显示否定决策和原因摘要。 |

### 目标实体层

实体代表可稳定识别的对象，至少包括：
- 代码：`Workspace`、`Service`、`File`、`Class`、`Method`、`Field`、`Endpoint`、`FeignClient`、`MQTopic`、`ConfigKey`。
- 工程活动：`ChangeSet`、`Analysis`、`EvidenceSubgraph`、`ArchitectureCommunity`。
- 协作与治理：`Task`、`Session`、`Validation`、`Decision`、`ChangeImpactReport`、`Artifact`。

### 交付顺序与里程碑

| 版本 | 交付 | 完成定义 |
|---|---|---|
| O1 | Registry 对齐 | 文档/代码/索引类型一致。 |
| O2 | Assertion Sidecar | V2 读模型统一，查询可返回 ref。 |
| O3 | 时间与失效 | generation、stale、历史读取可解释。 |
| O4 | 验证与决策闭环 | confirmation、validation、task 跨域关联。 |
| O5 | 体验与门禁 | 结论卡、Action、inspect、真实 benchmark 全部可用。 |

任何阶段若真实指标退化，停止推进下一阶段，保留 sidecar 并回滚默认读取。

### 非目标

- 不引入远程图数据库或 RDF/OWL 运行时。
- 不把所有 JSONL/Markdown 迁移为图节点。
- 不因本体重构破坏 MCP facade 或既有 dict schema。
- 不在普通查询中推理全量跨域关系。
- 不将 LLM 输出自动升级为 VERIFIED。

### 当前实现状态（4.2.0+）

- 查询与状态入口已提供兼容的 `knowledge_state`，避免以空结果表达不存在；断言支持有效期、事件时间与观测时间查询。
- 治理实体、关系、Action 读模型、验证别名和全入口断言确认已接入；本体侧只保留 V2，旧 sidecar 必须完整 reindex 重建。
- `eval-ontology-gate`、`eval-assertion-scope-gate` 与 `eval-assertion-reindex-gate` 覆盖默认查询、局部范围和隔离 reindex 开销门禁；真实 workspace 局部基线已验证通过。
