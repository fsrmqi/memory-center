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

- `Service`
- `Class`
- `Method`
- `Field`
- `Endpoint`
- `FeignClient`
- `FeignMethod`
- `MQTopic`
- `MQConsumer`
- `ConfigKey`
- `File`

### 2.2 记忆实体

- `SessionEvent`
- `WriteReceipt`
- `Ref`
- `Task`
- `Handoff`
- `ResumePacket`

### 2.3 运行/治理实体

- `Lookup`
- `Analyze`
- `Sync`
- `Resume`
- `Close`
- `Audit`

## 3. 关系类型

### 3.1 代码关系

- `CALLS`
- `CALLS_SERVICE`
- `IMPLEMENTS_FEIGN`
- `EXPOSES_ENDPOINT`
- `HANDLES_ENDPOINT`
- `PUBLISHES`
- `CONSUMES`
- `USES_CONFIG`
- `IMPORTS`
- `INJECTS_BEAN`

### 3.2 记忆关系

- `REFERENCES`
- `BELONGS_TO_TASK`
- `DERIVED_FROM`
- `SUMMARIZES`
- `HANDOFF_OF`
- `RESUME_OF`

## 4. 语义强度

所有关系和结果，原则上分成三类：

### `fact`

由索引器、显式结构或确定记录直接得到。

例子：

- `FeignMethod` 明确实现某个 `Endpoint`
- `WriteReceipt` 属于某个 `Task`
- `SessionEvent` 属于某个 `Session`

### `inferred`

由规则、命名、邻接、上下文推断得到，但不是直接事实。

例子：

- 某个查询更像 Feign 还是本地 Service
- 某个对象可能属于跨服务边界
- 某条链路更可能关联哪个 task

### `derived`

由多个事实或推断组合加工后的产物。

例子：

- `ResumePacket`
- `HandoffPacket`
- `CompletionAudit`
- `RetrievalSummary`

## 5. 当前最重要的约束

### 5.1 `Service` 不等于 `FeignClient`

- `ArticleService` 更偏本地代码实体
- `ArticleFeignClient` / `FeginAutomaticReviewTaskService` 更偏远程调用实体

不能因为名字里有 `Service` 就默认走 Feign 路线。

### 5.2 `Endpoint` 不等于 `Controller`

- `Controller` 是实现载体
- `Endpoint` 是接口暴露点

两者相关，但不是同一层对象。

### 5.3 `Ref` 不是原始数据本身

- `Ref` 是可追溯入口
- 真正详情要通过 ref 展开

所以 facade 输出里优先给 `summary + ref_id`，不是直接塞大 payload。

### 5.4 `Task`、`Session`、`Receipt` 是不同层对象

- `Task`：工作目标和上下文
- `Session`：一次工作过程
- `WriteReceipt`：一次具体写入记录

它们之间要通过关系关联，而不是混成一个大对象。

## 6. 本体论先作用到哪里

第一批最应该被 ontology 约束的是：

1. `detect_query_intent`
2. `memory_query_hybrid`
3. `contracts / chain / group_chain`
4. `timeline / ref / receipt / task`

## 7. 落地原则

这份 ontology 的目标不是把系统做重，而是：

- 先统一领域语言
- 再统一关系表达
- 再统一事实/推断边界

后续如果某个行为“看起来像 bug，但其实是语义边界不清”，优先回来看这份文档，而不是先继续堆特殊规则。
