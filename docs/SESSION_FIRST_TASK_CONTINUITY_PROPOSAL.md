# Session-first Task Continuity / 会话优先的任务连续性提案

> 状态 / Status：proposal
>
> 目标 / Goal：让 Agent 在默认工作流中无需手动创建、解析和维护 task space，同时避免错误自动写入长期工件。

## 1. 问题定义 / Problem

当前 task space 模型偏向维护者工作流：创建任务、解析任务、同步工件、结束任务。真实编码会话中，用户通常只想开始工作、查代码、改代码、验证、结束；要求频繁操作 task space 会造成摩擦。

自动解析也不是充分替代：错配后，`context.md`、`plan.md`、`design.md`、`current-summary.md` 等追加保护工件会获得长期脏数据。

The current model asks users to manage task spaces too early. Automatic binding is unsafe when confidence is low because append-only artifacts retain incorrect context.

## 2. 产品原则 / Product Principles

1. **Session-first**：每次工作天然有 session，不要求先有 task。
2. **自动收集，延迟绑定，显式升格**：低风险事实自动保存；长期结构只在可信绑定后写入。
3. **绑定优先级高于文本猜测**：同一 thread/session 的既有绑定永远优先于新一轮相似度解析。
4. **正式 task 是协作承诺，不是草稿容器**：仅在跨轮、跨人、验证、交接或长期决策需要时物化。
5. **不确定不写**：候选可以展示，长期工件不能污染。

## 3. 分层模型 / Layered Model

```text
L0  Session Evidence
    原始提示、工具事实、候选文件、验证摘要、receipt

L1  Task Shadow
    临时、轻量、可丢弃的工作连续性状态；默认不创建 task 目录

L2  Formal Task Space
    已绑定的协作工件：context / plan / design / change-log / summary

L3  Verified Case / Workspace Memory
    经验证、可复用的经验和稳定规则
```

### Task Shadow 数据契约

```json
{
  "shadow_id": "thread-or-session-derived",
  "session_ids": ["..."],
  "intent_summary": "...",
  "candidate_tasks": [],
  "candidate_files": [],
  "recent_evidence_refs": [],
  "unresolved_items": [],
  "next_actions": [],
  "binding_status": "unbound|suggested|bound",
  "confidence": "low|medium|high",
  "updated_at": "..."
}
```

Task Shadow 不保存完整 prompt、源码、完整 tool payload 或绝对路径；这些仍按现有 L0 ref/evidence 规则保存。

> 与 11.3 的关系：本节是 Memory Center 内部存储的 Shadow 形态；11.3 是 DSH Adapter 提交的脱敏 Shadow Snapshot 形态。两者的映射：`source_session_id` + `lineage` 折叠后归入 `session_ids`；`evidence_refs` 对应 `recent_evidence_refs`；`as_of_seq`/`state_version` 是同步水位元数据，不进入内部存储；`confidence` 由 Adapter 侧 `binding_status` 与候选分数在 MC 内部推导。

> 多 source 规则：内部 Shadow 不能把多个 session 的 whole-value snapshot 直接做全局 last-write-wins。每个 `source_session_id` 保存独立 contribution 与独立 watermark；对外 Task Shadow 是所有活跃 contribution 的确定性 merge projection。

## 4. 任务绑定状态机 / Binding State Machine

```text
session_start
  → unbound shadow
  → suggested shadow      (有候选，但不写 L2)
  → bound task            (显式或强证据)
  → promoted case draft   (close 且验证通过时可选)
```

### 绑定优先级 / Binding Priority

```text
explicit task_id
> persisted thread/session binding
> user confirmation in current turn
> high-confidence automatic binding
> suggested only
```

`mc_close` 必须优先复用 `mc_start` 或同 thread 已绑定的 task ID；只有绑定不存在、失效或用户显式取消时才重新解析。

## 5. 写入分级 / Write Policy

| 内容 | 默认行为 | 写入位置 |
|---|---|---|
| tool 事实、候选文件、索引状态 | 自动 | L0 / Shadow |
| 风险、下一步、未决项 | 自动生成草稿 | Shadow |
| task 候选及分数 | 自动 | Shadow |
| `context.md`、`plan.md`、`design.md` | 仅 bound 后 | L2 |
| `current-summary.md` | 仅 bound 后 | L2 |
| case / skill 候选 | close + 验证后 | L1 / candidate |
| L3 规则 | 显式确认或严格门禁 | L3 |

`auto_write_allowed=false` 时，sync 返回候选和 `required_action=explicit_task_id`，但 session/Shadow 继续正常更新。

## 6. 默认用户体验 / Default UX

正常工作流无需手动 task 操作：

```text
mc_start
→ mc_lookup / mc_analyze / mc_sync
→ mc_close
```

`mc_sync` 在未绑定时更新 Shadow，而非创建或写入 task artifact。`mc_close` 只提供一次短建议：

```text
本会话可：
1. 绑定到候选任务 X
2. 保留为临时工作影子
3. 在验证通过后生成 case draft
```

默认选项是“保留为临时工作影子”。

## 7. 物化正式任务的条件 / Materialization Conditions

满足任一条件才创建或写入 L2：

- 用户显式提供 `task_id`；
- 用户确认候选任务；
- 同一 thread/session 已可靠绑定；
- 跨多轮持续工作且高置信绑定；
- 有明确验收、交接、多人协作、发布证据或长期设计决策需求。

短会话、探索性查询、一次性诊断、无验证失败尝试默认不创建 task space。

## 8. 生命周期 / Lifecycle

| 状态 | 行为 |
|---|---|
| 短会话、未验证、未续接 | 按 session retention 清理 Shadow |
| 多轮同 thread | 续接同一 Shadow |
| bound | 合并 Shadow 摘要和 evidence 到 L2 |
| close + 验证通过 | 可提出 case draft |
| close + 无绑定 | 保留 session summary，延迟清理 Shadow |

不允许 Shadow 自动变成 L2；必须满足物化条件。

## 9. 接口演进 / API Evolution

所有字段 additive，保持 CLI/HTTP/MCP 兼容。

### `mc_start`

新增：`task_shadow`、`binding_status`、`task_candidates`。不再默认自动同步 L2。

### `mc_sync`

新增 `sync_target=shadow|task|auto`：

- `auto` 默认；bound 时同步 task，否则同步 Shadow；
- `task` 需要显式 task ID 或可信绑定；
- `shadow` 永不写 L2。

### `mc_close`

新增 `promotion_options`、`binding_recommendation`；默认不创建 task space。

### 管理接口

建议增加：

```text
task_shadow_status
task_shadow_bind
task_shadow_discard
task_shadow_promote
```

所有状态变更写 receipt，绑定和升格可审计。

## 10. 多项目与多 Agent 简化原则 / Multi-project and Multi-agent Simplification

### 10.1 三个范围不能混用

```text
Project / Service scope  = 代码、契约、索引和影响分析范围
Agent / Session scope    = 谁在执行、哪次会话产生了事实
Task scope               = 一个逻辑工作目标与协作承诺
```

项目边界不应驱动 task 生命周期。一个 task 可以跨多个 service；同一个 service 中的多个 Agent session 也不必自动生成多个 task。

### 10.2 保留什么 / What Remains

保留 workspace 内的多项目/多 service 索引，因为它是跨 Feign、MQ、DTO、配置和调用链分析的基础能力：

- service/project 作为 query、impact、coverage、contract 的过滤范围；
- task 可声明 `projects: []`，用于 evidence 和影响范围；
- 跨项目 evidence、candidate files、primary chain 和显式 handoff；
- 同一正式 task 可绑定多个 session/thread/Agent。

### 10.3 默认不做什么 / What Is Not Automatic

默认不应：

- 按 project 自动创建 task space；
- 因多个 Agent 调用而自动创建多个 task；
- 因 group/multi-workspace 发现而自动切换或绑定 task；
- 给 project 名在 task 自动归属中赋过高权重；
- 将“一个项目”隐含解释为“一个任务”。

group / multi-workspace chain 仅保留为显式高级能力；默认 `mc_lookup` 不自动跨 group。用户或调用方必须明确指定 group/workspace，结果必须保留范围说明。

### 10.4 推荐默认拓扑 / Recommended Default Topology

```text
Workspace
  └── Services / Projects          # 代码检索与影响分析范围
      └── Sessions / Threads       # Agent 执行事实
          └── Task Shadow          # 默认连续性状态
              └── Formal Task      # 显式或高置信升格
```

多个 Agent 的正常协作方式是多个 session 绑定到同一个 Shadow 或正式 task。只有显式 handoff、明确 task ID 或强证据确认时，才建立共享绑定。

### 10.5 实施影响 / Implementation Impact

1. `resolve_task_space` 的 project 名仅作为弱辅助证据，不能单独触发 auto-bind。
2. Task Shadow 主键优先 thread/session，而不是 project/service。
3. `projects` 是 task 的关联集合，不是 task 的分区键。
4. `mc_start` 在多项目 workspace 中仅创建 session/Shadow；不因候选 service 自动创建 L2 task。
5. `mc_close` 仅复用已有绑定或给出候选；不基于 group 自动落到其他 workspace task。
6. 多 Agent 统计以 session binding 聚合，不能用 task 数量推断 Agent 数量或项目数量。

## 11. DSH-backed Task Shadow Adapter / 基于 DSH 会话投影的 Task Shadow 适配器

### 11.1 结论 / Conclusion

DeepSeek Harness（DSH）的 Session Persistence 与 Session Projection 模型是 Session-first 方案的优先实现参考。DSH 已将权威事件日志、纯投影、检查点缓存、单会话写入所有权、生命周期边界和崩溃恢复分开建模；Memory Center 不应复制一套完整对话日志或并行 Shadow 日志。

推荐边界：DSH 作为会话事实层和 Shadow 投影来源；Memory Center 作为脱敏 Shadow snapshot、跨项目 evidence、task binding、正式 task/case 升格和治理层。

采纳判据（取其精华、去其糟粕）：DSH 的机制大多以"同进程、持有完整日志、模型侧"为前提。凡是依赖该前提的实现细节，Memory Center 只借不变式思想、不搬实现；凡是能以脱敏 whole-value 快照跨进程复用的，才进入本节方案。Memory Center 侧应定义通用 `TaskShadowSource` 接入契约（push/pull、watermark 语义、schema 版本协商），DSH Adapter 只是该契约的第一个 provider——MC 核心不硬编码 DSH 概念，其他 Agent 框架未来可实现同一契约接入。

```text
DSH Session Event Log              权威完整会话
        ↓ pure fold
DSH Task Shadow Projection         会话内派生状态
        ↓ checkpoint / asOfSeq
Memory Center Shadow Adapter       脱敏同步与去重
        ↓ explicit bind / promote
Formal Task Space / Verified Case  长期协作工件
```

### 11.2 可复用的 DSH 原则 / DSH Principles to Reuse

| DSH 能力 | Memory Center 应用 |
|---|---|
| append-only Session Event Log | Shadow 只能由事实折叠，不允许任意覆盖 |
| SessionHandle 的 create/open/append/flush/close | Shadow 生命周期与可靠 checkpoint 边界 |
| 单写者所有权 | 单个源 session 同一时刻只允许一个 Shadow 投影写入方 |
| `flush` durability barrier | `turn/end`、handoff、close、dispose 时持久化 Shadow 快照 |
| 崩溃恢复的 interrupted turn closer | 未闭合会话恢复后仍可生成连续 Shadow |
| SessionHeader 与日志分离 | cwd、lineage、thread、seed 边界不混入正文事件 |
| ProjectionDefinition 纯 fold | Shadow 是派生投影，不是第二套任务状态机 |
| `asOfSeq` watermark | 拒绝旧快照覆盖新快照 |
| Projection Cache：日志领先、缓存跟随 | Shadow snapshot 可以陈旧，但绝不能领先或错误 |
| turn outline | 不加载完整日志也可展示当前轮、未决项、下一步 |
| state version | Shadow schema 变化时安全丢弃/重建旧缓存 |

核心原则：

```text
Session log leads.
Shadow projection follows.
Cache may be stale, but must never be wrong.
```

### 11.2.1 取其精华 / What to Adopt

以下不变式与模式值得直接采纳，且不依赖 DSH 进程内前提：

1. **Whole-value + source-local last-wins**：投影状态事件携带完整变更后状态，从不携带裸 delta。MC 快照同样遵循：每个 snapshot 自包含、可独立解释。幂等键为 `(shadow_id, source_session_id, as_of_seq)` 三元组；一个 Shadow 有多个 source session 时，每个 source 只对自己的 contribution 使用 last-write-wins，MC 再将所有 contribution 做确定性 merge，绝不让后到 session 擦除另一 session 的候选文件或未决项。
2. **Watermark 只读已持久化前缀**：watermark 永远不得超过源日志的 durable 边界（"stale but never wrong"）。
3. **stateVersion 驱动缓存失效**：schema 或 fold 语义变化时 bump 版本，旧缓存整批丢弃，绝不清 forward-apply。
4. **Fail-closed schema 校验**：所有跨边界数据先过 schema + 字段允许列表 + 有界长度，不合法即拒收并写 receipt。
5. **封闭枚举 + 机器可路由 reason code**：状态机字段（`binding_status`、`required_action`）用封闭枚举，附 stable-kebab-case code + human message 双轨解释。
6. **CAS 乐观并发**：绑定状态变更带 `id + revision`，stale revision 拒绝，防止多 Agent 并发写同一绑定记录。
7. **整表替换的轻量列表**：`candidate_files` / `unresolved_items` / `next_actions` 无条目 id、在单个 source contribution 内整表替换（source-local last-write-wins），不引入条目级身份管理；跨 source merge 采用稳定 union/优先级规则。
8. **不透明 revision token 轮询**：pull 模式下用源端 `stat` 类变更令牌做廉价探测，变化才拉取，避免常驻订阅。该 token 只能在同一 source provider/session 实例内判断“是否变化”，不得持久化比较大小，也不得用作 MC 的 CAS revision。
9. **生命周期边界即 checkpoint 候选边界**：turn/end、handoff、close、dispose 是自然的快照点；普通 turn checkpoint 可以是 best-effort，bind/handoff/close/promote 必须先经过 durability barrier。崩溃恢复只闭合不截断（保留已 durable 的事实，追加合成 closer）。

### 11.2.2 去其糟粕 / What NOT to Adopt (Details)

DSH 的以下实现细节以"同进程、持有完整 JSONL 日志、模型侧"为前提，Memory Center 不照搬：

1. **不搬运会话日志本身**（11.8 已明确）：MC 不实现 `SessionHandle`/JSONL 后端一类日志存储，MC 侧的"重折叠"不存在——见 11.3 约束 3 的修正。
2. **不照搬进程内单写者锁**：`SessionAlreadyOwnedError` 一类互斥对跨进程协作无效，改用 11.4 的 `revision/lease` + CAS。
3. **不做 surface/compaction 投影**：DSH 的 replace-遮蔽 surface 是模型上下文管理机制，MC 的 Shadow 只需折叠结果，无需复刻 surface 代数。仅在接入契约中要求：折叠输入使用 compaction 之后的等效视图，使 `as_of_seq` 在源侧 compaction 后仍保持单调、水位规则不受影响。
4. **不复制 token 计量、流式 chunk、provider 路由等模型侧事件词汇**：`SessionEventMap` 是 DSH 的领域词汇，MC 只定义 Shadow snapshot 的目标 schema，不镜像其事件源。
5. **不依赖事件驱动 live 订阅作为唯一通路**：DSH registry 的 eager drive 建立在同进程订阅上；跨进程默认 pull + watermark 轮询，push 作为可选优化，且必须可从 pull 重建。
6. **不把 UI 级 projection cache 行为照搬为治理状态**：DSH cache 是零 I/O 展示层读路径（"as stale as the last durable checkpoint"），MC 的 Shadow 是治理与升格依据，必须逐条 receipt 审计，代价上接受比 UI 缓存更重的一致性要求。

### 11.3 Shadow Snapshot 契约 / Shadow Snapshot Contract

Memory Center 接收的不是完整 prompt、模型回复、工具参数/结果或源码，而是受限的脱敏投影：

```json
{
  "shadow_id": "derived-session-id",
  "source_provider_id": "provider-kind-and-schema",
  "source_instance_id": "optional-stable-installation-id",
  "source_session_id": "opaque-session-id",
  "lineage": {
    "parent_session_id": "",
    "fork_seq": 0
  },
  "observed_as_of_seq": 0,
  "durable_as_of_seq": 0,
  "durable_event_count": 0,
  "source_revision_hint": "opaque-change-token",
  "delivery_mode": "durable",
  "state_version": 1,
  "intent_summary": "bounded summary",
  "candidate_tasks": [],
  "candidate_files": [],
  "evidence_refs": [],
  "unresolved_items": [],
  "next_actions": [],
  "binding_status": "unbound|suggested|bound"
}
```

约束：

1. 幂等键是 `(shadow_id, source_provider_id, source_session_id, durable_as_of_seq)`；每个 source contribution 只接受严格递增的 durable 水位；
2. 相同或较旧 durable 水位返回幂等 no-op；
3. `source_revision_hint` 仅用于 source-local pull 轮询，不能参与跨进程 CAS、顺序比较或 durability 判断；
4. 正式投递给 MC 的 snapshot 必须满足 `observed_as_of_seq == durable_as_of_seq` 且 `delivery_mode="durable"`。否则 state 内容可能领先 durable 日志，即使 watermark 较旧也会违反 "never wrong" 原则；
5. `turn/end` 的 volatile/best-effort snapshot 只允许 DSH 内存或 UI 预览使用，MC 不得用它 bind task、写 L2、promote case 或作为长期 evidence；
6. bind/handoff/close/promote 前，adapter 必须先通过源侧 durability barrier（DSH 中为 `ctx.sessions.flush(session)`）并投递 durable snapshot；
7. `durable_event_count` 与 `durable_as_of_seq` 是 MC 可验证的 durable 前缀边界；revision token 不等于日志长度。发现 durable 序列不连续、来源重建或 identity 变化时，丢弃 contribution 并请求源侧全量重同步；
8. `state_version` 高于 MC 已知版本时，MC 不做本地重折叠（MC没有源日志，也不应有），而是标记 Shadow `stale/unusable`、写 receipt、并向 adapter 请求新版完整快照；
9. 快照不包含完整对话、工具正文、绝对路径或私密 payload；
10. Memory Center 保存 snapshot receipt、source identity、durable watermark 与 binding 审计，但不保存 DSH 原始日志副本。

### 11.3.1 Source Contribution Merge / 多源贡献合并

MC 内部应保存 source-local contribution，而不是直接覆盖完整 Shadow：

```text
ShadowSourceContribution[source_provider_id, source_session_id]
  ├── durable_as_of_seq
  ├── source_revision_hint       # 仅 pull 轮询提示，不参与 CAS
  ├── candidate_files
  ├── unresolved_items
  ├── next_actions
  └── evidence_refs

TaskShadow
  └── deterministic merge(active contributions)
```

合并规则：

- `candidate_files`：按稳定路径/逻辑 ID 去重 union；
- `evidence_refs`：按 receipt/ref ID 去重 union；
- `unresolved_items`：保留 source 归属，状态关闭只影响同 source 或显式关联项；
- `next_actions`：按 action key 去重，保留最高风险/最高置信版本；
- 任一 contribution 过期或被 dispose 后从 active merge 移除，但 receipt 保留审计。

### 11.3.2 Structured Facts versus Compacted Surface / 结构化事实与压缩 Surface

Task Shadow 不应完全以 compaction 后的模型 surface 为折叠输入。规则如下：

| 信息类型 | 来源 |
|---|---|
| candidate files、tool receipt、验证、handoff、binding、watermark | 完整 durable 结构化事件或 log-only 领域事件 |
| intent summary、自然语言当前摘要 | 可使用 compaction 后的 surface 等效视图 |
| source lineage、state version、durability status | SessionHeader / persistence metadata |

compaction 可以替换模型上下文中的自然语言消息，但不得遮蔽已存在的结构化 evidence。Adapter 的 `ProjectionDefinition.apply()` 必须先折叠 durable 结构化事件；surface 等效视图仅作为 `intent_summary` / `prose_summary` 的可选输入，再选择性叠加到 snapshot。

### 11.4 所有权与多 Agent / Ownership and Multi-agent

DSH 的单写者模型主要是进程内保证。Memory Center 面向跨 Agent/跨进程协作时，应改用：

```text
source_session_id + as_of_seq + revision/lease
```

- DSH 负责一个 session 内事件顺序和本地单写者；
- Memory Center Adapter 以 `source_session_id` 和 watermark 幂等接收；DSH `stat().revision` 只作“是否重新拉取”的 source-local hint，MC binding CAS 使用自己持久化的 revision；
- 多个 Agent 各自拥有独立 Shadow；
- 只有显式 task bind、handoff 或高置信确认时，多个 Shadow 才关联到同一正式 task；
- 不允许多个 Agent 直接写同一个 Shadow 文档。

### 11.5 检查点与生命周期 / Checkpoints and Lifecycle

建议 DSH Adapter 在以下边界发送脱敏快照：

| 生命周期事件 | Adapter 行为 |
|---|---|
| session create | 初始化 Shadow identity/header |
| `turn/end` | 可生成 volatile/best-effort UI checkpoint；若不 flush，不得向 MC 投递正式 durable snapshot |
| handoff/fork | 先 flush，再保存 lineage 与当前 durable watermark |
| flush | 显式持久性屏障 |
| bind / promote | 先 flush，再允许改变正式 task/case 归属 |
| session dispose/close | 先 flush，写最终快照、生成可升格摘要 |
| interrupted recovery | 在 closer 后继续折叠，避免残缺 turn 误导 Shadow |

失败采用 fail-soft：DSH 日志继续权威保存；Adapter 下次 checkpoint 重试。若同步长期失败，只报告 Shadow stale，不阻断 DSH 主会话。

### 11.6 Shadow 在 DSH 侧的落地形态 / Shadow as a DSH Projection Unit

在 DSH 侧，Task Shadow 不需要新通道：它就是一个 `ProjectionDefinition`——`key: 'task-shadow'`、`stateVersion`、纯 `init/apply` fold、`wire` 输出脱敏 snapshot。消费路径复用现有 `session/projection` 推送帧或 `snapshot()` 读取；持久化 checkpoint 复用 session-projection-cache 的三个强制点（session creation、`turn/end`、session disposal）。折叠输入使用 surface 等效视图（compaction 之后的 current surface），使 Shadow 天然吸收 compaction 的 replace 遮蔽，且 `as_of_seq` 单调性不受影响。

接入契约（`TaskShadowSource`）要求的源侧能力，对应 DSH 现成机制如下：

| 契约要求 | DSH 现成机制 |
|---|---|
| 脱敏 whole-value snapshot | `ProjectionDefinition.wire.view` + `viewSchema` |
| schema 版本协商 | `stateVersion` bump + 旧缓存丢弃 |
| durable 前缀水位 | `ctx.sessions.flush(session)` 后的 `asOfSeq` |
| 变更探测（pull 模式） | `stat(id).revision` 不透明变更令牌 |
| fork/lineage | `inheritedEventCount`（精确继承前缀长度）；子 Shadow 以父 Shadow 在 fork 边界的状态为种子，而非空开始 |
| 崩溃恢复 | resume 路径追加 `interrupted` closer；adapter 只在已闭合 turn 边界 checkpoint |

fork 场景子 Shadow 继承 lineage（`parent_session_id` + `fork_seq` 对齐 `inheritedEventCount`），但不自动继承正式 task 绑定——这使 11.4 的"继承 lineage、不自动继承 task"有了具体机制。

### 11.7 实施阶段 / Implementation Plan

#### Phase DSH-1 — Read-only Adapter Prototype

- 定义 `TaskShadowSource` 接入契约（push/pull、watermark 语义、schema 版本协商）与 `TaskShadowSnapshot` schema；
- DSH 侧实现 `task-shadow` ProjectionDefinition（surface 折叠 + 脱敏 wire view），MC 只保存 receipt/watermark/status，不写正式 task；
- pull 模式基于 `stat.revision` 变更探测；验证无完整会话正文泄露（schema 允许列表 + 有界长度 fail-closed）。

#### Phase DSH-2 — Idempotent Shadow Sync

- 实现 `(shadow_id, source_session_id, as_of_seq)` 幂等去重；
- 落实 durable 前缀水位（flush 后 checkpoint）、截断检测与全量重同步路径；
- 加入 state version 方向性拒绝、stale status 和 retry receipt；
- 定义跨进程 revision/lease 与绑定记录 CAS 规则；
- 提供只读 status API。

#### Phase DSH-3 — Explicit Task Binding

- Shadow 只提出 task 候选；
- 用户/Agent 显式 bind 后才允许写 L2；
- handoff/fork 继承 lineage，不自动继承正式 task；
- close 输出 promotion options，不自动发布 case。

#### Phase DSH-4 — Checkpoint and Replay Validation

- create/turn-end/dispose/checkpoint coverage；
- stale cache 不领先日志；
- crash/interrupted turn 后 watermark 连续；
- 多 Agent Shadow 不互相覆盖；
- session 到 task 的误绑定率、恢复成功率和人工操作数可观测。

### 11.8 不应照搬的部分 / What Not to Copy Directly

- 不直接把 DSH 的进程内单写者所有权当作跨 Agent 锁；
- 不把每个 DSH session 的完整 JSONL/压缩日志复制到 Memory Center；
- 不把 Projection Cache 当作权威 task 状态；
- 不让 DSH 浏览器端直接读取 Memory Center SQLite/JSONL；
- 不因为 DSH session 存在就自动创建正式 task。

### 11.9 Cross-agent Memory Lifecycle Reference / 跨 Agent 记忆生命周期参考

跨 Agent memory 系统的成熟模式可总结为：

```text
capture → consolidate → recall → handoff
```

这与本提案的 Session-first 方向一致，但 Memory Center 应借鉴模式而不复制完整实现。核心结论：用户不应执行“记住这个”或“创建 task”的仪式；系统先捕获低风险事实，延迟整合，只有可信边界才升格为 task/case。

#### 应采纳的模式 / What to Adopt

| 模式 | Memory Center 对应设计 |
|---|---|
| 生命周期 hooks 静默捕获 | 多 Agent adapter 写入统一脱敏 Observation |
| session-end consolidate | close/handoff 时生成 Shadow summary 或 promotion draft |
| 受限 handoff | owner/revision/claim-once 的 Handoff Claim |
| 人类可读长期页面 | bound task/case 使用 Markdown 工件 |
| 机器可重建索引 | SQLite 保存事实、绑定、水位、receipt、审计 |
| 默认零 LLM | Shadow 先由规则折叠；LLM 只生成可选 draft |

#### Observation Inbox / 观察事实收件箱

新增跨 harness 的最小事实契约：

```json
{
  "observation_id": "opaque-id",
  "source_kind": "dsh|codex|claude|other",
  "source_session_id": "opaque-session-id",
  "event_seq": 0,
  "kind": "session_boundary|tool_fact|candidate_file|validation|handoff|task_hint",
  "payload": {},
  "observed_at": "..."
}
```

允许列表只包含：session/thread 标识、工具名称、脱敏 query 摘要、candidate files、receipt/validation 状态、generation/freshness、结构化风险和下一步。默认拒绝完整 prompt、完整工具 payload、源码正文、完整模型回复、绝对私有路径。

`Observation` 是 L0/Shadow 的输入，不直接写 L2。Adapter 必须用 `(source_kind, source_session_id, event_seq)` 幂等去重，并对 schema/大小/字段 allowlist fail-closed。

#### Handoff Claim / 交接认领

handoff 不是提示词约定，而是有状态协议：

```text
suggested → bound → handed_off → claimed → closed
```

建议记录：

```json
{
  "handoff_id": "...",
  "shadow_id": "...",
  "from_session_id": "...",
  "to_agent_hint": "",
  "revision": 1,
  "status": "handed_off|claimed|expired|closed",
  "claimed_by_session_id": "",
  "expires_at": ""
}
```

- claim 必须携带 `handoff_id + expected_revision`；
- 同一 handoff 只允许一个成功 claim；
- stale revision 返回冲突，不覆盖先到接手者；
- handoff 可以关联 Task Shadow，但不自动创建正式 task；
- close 时仅已 claim/bound 的会话可以升格同一 task。

#### SQLite 与 Markdown 的双层职责 / SQLite and Markdown Responsibilities

```text
SQLite authoritative:
  observations, source watermarks, shadow contributions,
  task bindings, handoff claims, receipts, audits, code graph

Markdown human-facing:
  bound task context/plan/design/change-log,
  handoff brief, verified case, human-readable summary
```

不把 Markdown 作为代码图、watermark、lease 或 CAS 的事实源；也不把 SQLite 行直接暴露为用户协作页面。

#### LLM 使用边界 / LLM Boundary

```text
默认：规则/结构化 Observation → Task Shadow
可选：close/handoff/promotion → LLM-readable draft
人工或强门禁：draft → Formal Task / Case
```

LLM 输出不得修改 binding、watermark、receipt、验证状态或结构化事实；只能建议摘要、候选任务或下一步。

#### 明确不采纳 / Explicit Non-adoption

- 不复制完整 prompt、模型回复或工具正文；
- 不将 git-backed Markdown wiki 设为所有运行时事实的唯一来源；
- 不在当前阶段引入完整多用户 server、认证、跨机器同步体系；
- 不让 hooks 直接写 L2 task artifact；
- 不让 session end 自动发布 case/skill；
- 不把 managed workstream 等同于正式 task。

#### 推荐交付顺序 / Recommended Sequence

1. Observation schema、allowlist、adapter receipt；
2. Observation → source-local Shadow contribution 折叠；
3. Task Shadow merge 与现有 session/task binding 对接；
4. Handoff Claim CAS；
5. close-time promotion draft；
6. 真实 replay 观测后才评估跨机器/多用户能力。

## 12. 实施阶段 / Delivery Phases

### Phase A — Shadow Storage and Thread Binding

- 定义 Task Shadow schema 和 SQLite/JSONL 投影；
- 复用既有 thread-session binding；
- `mc_start` 自动创建或续接 Shadow；
- 不改变现有 task space 默认写入行为，先以 feature flag 观察。

### Phase B — Shadow-aware Sync

- `mc_sync(auto)` 未绑定时写 Shadow；
- L2 sync 必须校验 `auto_write_allowed`；
- 输出明确 `write_target`、`binding_status`、`required_action`。

### Phase C — Close-time Promotion

- `mc_close` 复用既有绑定；
- 输出 binding/promotion suggestion；
- 验证通过时生成 case draft，不自动发布。

### Phase D — Migration and Default Switch

- 用真实 replay 验证误绑定率、手动 task 创建率、恢复成功率；
- 达到门槛后将 Session-first 设为默认；
- 保留旧显式 task 命令与 workspace policy 开关。

## 13. 测试与验收 / Acceptance

必须覆盖：

1. 未显式 task 的短会话不创建 L2；
2. 同 thread 多轮续接同一 Shadow；
3. 低置信候选不会修改任何 task artifact；
4. 显式 task ID 立即 bound；
5. start/close 不会重新猜到不同 task；
6. Shadow 绑定后摘要/evidence 正确进入 L2；
7. 验证通过前不自动产生正式 case；
8. retention 清理 Shadow 不影响 L0 receipt、L2 artifact 或 L3 case；
9. CLI/HTTP/MCP 语义一致；
10. 不输出 prompt、源码、完整 payload、绝对路径或私有 task 标题到公共评测报告。
11. 跨项目 task 可绑定多个 project，但不会因 project 名自动创建或错绑 L2 task。
12. 多 Agent session 默认创建/续接 Shadow，不会各自自动创建正式 task。

建议观测指标：

```text
task_auto_bind_rate
task_bind_conflict_rate
task_write_blocked_rate
shadow_to_task_promotion_rate
resume_success_rate
manual_task_create_rate
```

### Phase D 门槛 / Phase D Gate

基于真实 replay 的建议阈值（首次切换默认前需全部满足）：

```text
task_auto_bind_rate            ≥ 0.80   # 有候选时自动绑定被接受的比例
task_bind_conflict_rate        ≤ 0.02   # start/close归属不一致或用户纠正的比例
task_write_blocked_rate        ≤ 0.05   # 合法 L2 写入被误拦截的比例
resume_success_rate            ≥ 0.90   # 同 thread 续接同一 Shadow 的成功率
manual_task_create_rate        ≤ 0.10   # 默认流程下仍需手动创建 task 的比例
shadow_to_task_promotion_rate  不设下限  # 仅观测，升格应保持低频
```

阈值为初始值，运行两批 replay 后允许按实测分布校准一次，校准需记录在 receipt 中。

## 14. 非目标 / Non-Goals

- 不把每个 session 自动创建为正式 task；
- 不以文本相似度强制覆盖用户 task 选择；
- 不把 Shadow 变成第二套 task state machine；
- 不自动发布 case、skill 或 L3 记忆；
- 不向浏览器或公共 baseline 泄露会话正文。
- 不删除 workspace 内跨项目索引、Feign/MQ/DTO 关系或显式 group 查询能力。

## 15. Definition of Done

- [ ] 用户可完成默认工作流而无需手动创建 task；
- [ ] 不确定解析只生成 Shadow/candidate，绝不污染 L2；
- [ ] 同 thread 的 start/close 任务归属一致；
- [ ] 正式 task 仅在可信绑定或显式升格后物化；
- [ ] Shadow 生命周期、receipt、retention 和恢复路径可审计；
- [ ] 真实 replay 显示误绑定和人工管理成本下降。
- [ ] 多项目和多 Agent 不再自动导致 task 分裂或误绑定。

## 16. Implementation Handoff Checklist / 实现交接清单

实现者开始前应确认：

- [ ] 先实现 `TaskShadowSource` 与 `TaskShadowSnapshot` schema，不直接修改 L2 自动写入行为；
- [ ] source contribution 的主键包含 provider、session 与 durable watermark；
- [ ] durable snapshot 与 volatile UI checkpoint 是两个明确 delivery mode；
- [ ] source revision hint 不进入 MC 的 CAS 或顺序逻辑；
- [ ] Task Shadow 结构化事实来自 durable event fold，不来自 surface-only fold；
- [ ] 多 source merge 有确定性 union/优先级规则和测试；
- [ ] bind/handoff/close/promote 前先 source flush，再写 MC receipt；
- [ ] 所有 adapter 输入均经过 allowlist、schema、大小限制和隐私测试；
- [ ] 未绑定或低置信 Shadow 不得写 L2 task artifact；
- [ ] 先交付 DSH read-only adapter prototype，再交付 bind/promotion；
- [ ] 每阶段提供 CLI/HTTP/MCP 状态读取、receipt 和不污染原 session 的回归测试；
- [ ] 私有 session、query、路径、baseline 不提交到仓库。
