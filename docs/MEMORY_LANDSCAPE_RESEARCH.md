# AI 记忆项目全景：对 Memory Center 的最终吸收结论 / AI Memory Landscape: Final Adoption Decision for Memory Center

日期 / Date：2026-08-22
状态 / Status：已完成调研与项目内核对；会话候选生命周期已落地为 P1 的人工审批实现，其余结论仍是决策边界，不构成自动化开发排期。

## 1. 结论摘要 / Executive Decision

Memory Center 不应演变为通用的“聊天记忆平台”。它的核心定位仍是：面向编程 Agent 的、本地优先、证据可追溯、可做跨服务影响分析并受治理约束的项目记忆中心。

外部项目最有价值的不是其存储、模型或产品形态，而是三条工程纪律：

1. **记忆写入应有生命周期，而非无条件追加。** 会话沉淀应先生成可审计候选，再由明确门禁决定新增、合并、替代或放弃。
2. **时序结论必须同时有来源和历史证据。** “某关系曾经成立”不能由一次重新索引时写入的时间戳推断。
3. **记忆是否有价值，要看它是否改善下一个 Agent 的工作。** 资产装载、会话恢复和检索质量都应以真实 replay 或验证回执衡量。

因此，当前**不新增外部依赖、不改变既有 MCP tool schema、不新开 P0 实现项**。会话候选的“暂存 → 逐条审批 → L1 写入”已作为人工门禁的 P1 切片实现；自动合并、自动 L3 晋升、默认 Skill 装载仍须满足下列触发和验证条件。

## 2. 项目现状与约束 / Current Evidence and Constraints

| 已有能力 | 已核对证据 | 对外部机制的含义 |
|---|---|---|
| Assertion sidecar 已保存 `valid_from`、`valid_to`、`event_at`、`observed_at`，并支持按时间轴读取。 | `memory_center/core/storage/memory_backend.py` | 先复用断言的时间与证据模型；不能将其误等同于历史图。 |
| 主图的 `edges` 只有关系、置信度和 metadata；局部刷新会删除来源节点的出边并重写。 | `memory_center/core/storage/graph.py` | 图边时间字段本身无法保存历史，除非同时保存来源版本或历史 generation。 |
| `workspace_suggest_case` 从会话生成 L1 case 草稿，`workspace_record_case` 经确认后追加写入。 | `core/orchestrator/session.py`、`core/orchestrator/write.py` | 已有“候选 → 人工确认”的正确起点，但缺少 case 身份、合并和替代策略。 |
| 协作资产具备 owner、审批、绑定与有界 loadout；Context Pack 按预算装载。 | `core/knowledge/assets.py`、`core/context/pack.py` | 资产治理与定向注入已具备，缺的是收益归因而不是更多资产类型。 |
| `eval_retrieval_replay` 按时间切分训练/验证；样本不足不会调权。 | `core/retrieval/calibration.py` | 所有自动化建议应延续“样本不足只观测、不改变默认行为”的原则。 |

所有后续设计必须保持下列不变量：additive 扩展、evidence-first、显式离线维护不进入查询热路径、查询使用有界已发布 generation、破坏性写入需确认。详见 [ARCHITECTURE.md](./ARCHITECTURE.md) 与 [NEXT_PHASE_MASTER_PLAN.md](./NEXT_PHASE_MASTER_PLAN.md)。

## 3. 外部机制：哪些值得借鉴 / What the Landscape Actually Teaches

### 3.1 Graphiti / Zep：时间、来源与历史查询必须是一个整体

Graphiti 将关系表示为带有效窗口的事实，并让派生事实回溯到输入 episode；其价值在于可回答“现在为真还是过去曾为真”，而不是为图边增加几个日期字段。Graphiti 同时需要专门的图数据库和 ingestion 管线，这与 Memory Center 的 local-first SQLite 选择不同。

对本项目的启发：当真实任务需要按历史版本判断 Feign、MQ 或 API 契约时，应设计“**历史来源（Git commit / 已发布 generation / 人工验证）→ 关系断言 → as-of 查询**”的完整链路。没有可回放来源时，不得返回历史事实结论。

### 3.2 LangMem：把会话整合放在后台，但不把模型判断当作真相

LangMem 区分热路径即时形成与后台形成；后者可在不增加交互延迟的前提下，提取、更新、删除、合并和泛化记忆。这个分层适合 Memory Center，但其模型输出只能用作候选。

对本项目的启发：保留现有 `workspace_suggest_case` 的人工门禁，后续若要整合多个 session，应采用显式、默认 dry-run 的离线命令；每一条候选都必须包含来源 event/evidence ref、冲突理由和预期写操作。

### 3.3 Mem0：反例同样有价值

截至本次核验，Mem0 的 README 将其一条路径描述为 “[ADD-only extraction](https://github.com/mem0ai/mem0)”，即记忆累积而不做 UPDATE/DELETE。它证明追加写入实现简单，但不能解决经验过期、重复或相互矛盾的问题。

对本项目的启发：不要把 `ADD/UPDATE/DELETE/NOOP` 错称为 Mem0 的现成能力；Memory Center 若引入操作语义，应以自身的证据、审批和可逆性要求独立设计。

### 3.4 TencentDB Agent Memory：资产装载应服务角色，而非堆叠上下文

其资产、审批、版本与按 Agent 装载的思路，与 Memory Center 现有协作资产模型高度同构。可借鉴的是“不同角色有不同 loadout”，不可照搬的是云端产品形态或其完整平台。

对本项目的启发：先统计已发布 Skill / Wiki / CodeGraph 在指定 Agent、角色与任务意图下是否被采纳、是否帮助通过验证，再调整默认装载。没有可比较的基线时，不能声称某个 Skill 带来收益。

### 3.5 其他记忆 OS、策展产品与公开 benchmark

自动策展 UI、分层记忆和长期对话召回基准提示了未来方向，但当前不是缺口的直接证据。Memory Center 已有有界 Context Pack、任务恢复、retrieval replay 与交付 Skill 生命周期；在缺少真实 session 召回失败或候选积压数据前，不应先建 UI、引入新存储或构造通用协议层。

## 4. 最终吸收决策 / Final Adoption Matrix

| 候选机制 | 决策 | 进入设计的触发条件 | 最小验证与停止条件 |
|---|---|---|---|
| 会话 → L1/L3 候选整合 | **P1 已实现：人工审批切片** | 已结束会话具有可脱敏 event/evidence refs。自动化升级仍要求真实积压或人工记录成本证据。 | `--stage` 只持久化候选；逐条 approve 前重查 current-truth 冲突。L3 仍只产出草稿。来源不足、冲突或 REVIEW 均不得写入。 |
| Case memory operation candidates（ADD / UPDATE / SUPERSEDE / NOOP） | **P1 部分实现** | `workspace_suggest_case` 的草稿出现重复、过期或需批量筛选的真实证据。 | 当前仅有 `ADD / REVIEW`：无冲突 ADD 可审批，current-truth 或批内重复必须 REVIEW。`UPDATE / SUPERSEDE / NOOP` 必须先定义 stable case ID、比较维度、旧 case 状态回写与审批回执，不能由文本相似度推断。 |
| 历史图 / as-of impact analysis | **P2 观察项** | 同一影响链在不同历史时间窗结论不同，且至少有 3 个可复放的 Git 或 generation case。 | 先以 Git commit/generation 构建只读实验；仅当历史 precision、来源覆盖和查询预算均通过，才考虑持久化边时间。不能用 observed time 伪造 valid time。 |
| Skill / asset loadout 收益量化 | **P2 观察项** | `eval_retrieval_replay` 与交付 Skill replay 有足够的、带证据的验证样本。 | 对同意图、同角色样本比较采纳、验证通过和 token/延迟；不可比较或 Brier score 退化则不调默认 loadout。 |
| 跨会话召回评测 | **P2 观察项** | `mc_resume` 或 `mc_handoff` 出现可复现的关键事实遗漏。 | 建立脱敏、时间切分的 session-recall case；区分“索引缺失、检索遗漏、证据不足”，不把模型猜测当作召回成功。 |
| 记忆策展 UI | **明确延后** | 上述候选至少一项已发布且稳定产生待审批数据。 | UI 只消费已有候选与审批回执；不新增第二套真源。 |

### 4.1 已实现的会话候选生命周期 / Implemented Session-Candidate Lifecycle

当前实现是一个明确的离线维护路径，且不进入 MCP 查询热路径：

```text
已结束 session
  → consolidate-session --stage
  → session-consolidation-candidates.jsonl（append-only candidate）
  → consolidation-candidates（查看 pending）
  → decide-consolidation-candidate --decision approve|reject
  → L1 case + write receipt，或 append-only decision
```

- `consolidate-session` 默认 dry-run；`--stage` 将候选持久化到待审核池；`--apply` 是直接显式 ADD 模式，不能与 `--stage` 同用。日常维护应优先使用 `--stage → approve|reject`，以保留逐条审核轨迹。
- 候选必须来自已结束会话。命中 existing current-truth case 或同批主题重复时返回 `REVIEW`，审批接口拒绝写入；暂存后再次 approve 时还会重查 current-truth，避免状态变化造成重复 L1。
- `--include-l3` 仅在候选中附带 L3 memory-block 草稿。approve 目前**只写 L1**；L3 必须由维护者通过既有 artifact 更新路径单独审阅和写入。
- 审批传入的 `actor` 当前只是可审计的记录字段，不等于认证身份。进入团队共享场景前，应复用协作资产的 owner/非 owner 审批规则，不能仅信任 CLI 文本。

### 4.2 运营指标与下一步门槛 / Operating Metrics and Next Gate

会话候选功能已具备正确性测试，但尚无真实工作区收益结论。首次真实使用应记录下列聚合指标，不保存原始会话正文：

| 指标 | 目的 | 触发决策 |
|---|---|---|
| 来源完整率 | candidate 是否同时带 source refs 和 evidence refs | 低于预设门槛时只保留 dry-run，修复提取链路。 |
| REVIEW / reject 比例 | 判断相似度规则是否过宽或候选质量不足 | 偏高时先优化 case identity 与比较维度，不自动合并。 |
| 审批后重复率 | 检查 current-truth 防重是否有效 | 非零时停止扩大默认批量范围。 |
| stage 到决策耗时 | 验证候选池是否真正降低人工沉淀成本 | 没有改善时不建设策展 UI。 |
| 后续使用证据 | 已写 L1 是否被 `mc_resume`、`mc_context_pack` 或受控 Skill replay 消费 | 无消费方时不推进自动 L3 晋升或默认 loadout。 |

至少收集 3–5 个脱敏真实 case 并完成上述复盘后，才可决定是否设计 `UPDATE / SUPERSEDE`、L3 审批或会话召回评测。

## 5. 明确不吸收 / Explicit Non-Goals

- 不引入 Graphiti、Neo4j、Qdrant 或其他外部图/向量数据库；现有 SQLite + 可选 HNSW 的扩展先由真实容量与质量数据决定。
- 不引入“自然遗忘”或无证据衰退模型；过期、拒绝与替代必须保留可追溯记录。
- 不将聊天记忆、云端托管平台或通用互操作协议作为当前产品目标。
- 不让 LLM 直接自动写入、删除或认证 L1/L3 记忆；模型只能提出带证据的候选。
- 不因本调研调整现有 P1 Java 解析精度、P2 检索质量与 P3 交付闭环的优先级。

## 6. 实施门槛 / Implementation Gate

除已实现的人工候选切片外，任一候选实施前都必须完成：

1. 写出真实需求证据与 3–5 个脱敏逻辑锚点 case。
2. 说明现有 schema、CLI、MCP、HTTP 与 Workbench 的兼容策略；默认保持 MCP schema 不变。
3. 以 dry-run 或只读实验先验证，并补充单元、系统和回归测试。
4. 证明不在 MCP/HTTP 查询热路径引入全表扫描、模型调用或全量重建；默认读取 P95 不得超过同类真实基线 10%。
5. 只有验收数据不退化、证据可审计且存在明确消费方时，才进入默认行为或发布门禁。

## 7. 来源与核验范围 / Sources and Verification Scope

本结论以当前仓库源码与架构文档为最高优先级。外部资料仅用于理解机制，产品自述、融资或 benchmark 宣称均不视为本项目的性能证据。外部链接于 2026-08-22 访问：

- [Graphiti README](https://github.com/getzep/graphiti) — temporal context graph、有效窗口、episode provenance 与增量构图。
- [LangMem Core Concepts](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/) — 热路径/后台形成，以及提取、更新、删除、合并记忆的分层模型。
- [Mem0 README](https://github.com/mem0ai/mem0) — ADD-only extraction 的当前表述，用作追加模式的反例。
- [TencentDB Agent Memory README](https://github.com/TencentCloud/TencentDB-Agent-Memory) — 团队资产治理、角色化装载与 CodeGraph 影响分析的产品模型。
- [LoCoMo 参考入口](https://github.com/NirDiamant/Agent_Memory_Techniques/blob/main/all_techniques/29_memory_benchmarks_LoCoMo/README.md) — 长期记忆评测方向；本项目尚未将其作为发布门禁。

本文件应在以下任一情形重新核验：外部项目的机制/协议发生重大变化、Memory Center 首次出现相关真实需求证据、或任一候选准备进入实现设计。
