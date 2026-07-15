# Next Phase Master Plan / 下一阶段唯一开发路线

> 本文件是 Memory Center 当前唯一活跃开发路线。
>
> This is the single active development roadmap for Memory Center.

> 文档入口与 active/historical 状态请同时参考 [DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md)。
>
> Also see [DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md) for the current documentation entrypoints and active-vs-historical status.

---

## 1. 文档定位 / Scope

本文件整合并替代旧版执行计划、superpowers 演进计划和旧版 master plan；这些历史来源已归档到 `docs/archive/`，不再作为独立活跃文档维护。

This file consolidates and replaces the older execution plan, superpowers evolution plans, and the previous master plan. Those historical sources have been folded into this document and are no longer maintained as separate files.

旧计划中的已完成任务不再作为待办重复跟踪；未完成方向按当前代码和 benchmark 重新排序。

如果要看当前系统怎么用，优先读：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [docs/TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_GUIDE.md)
- [docs/references/codebase-memory-mcp.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/references/codebase-memory-mcp.md)

---

## 2. 当前判断 / Current Assessment

当前重点不再是“补一个新工具”，而是把已有能力收敛成更快、更准、更少误导 Agent 的主链路。

### 已完成，不再作为待办 / Completed

以下能力已经进入当前代码或主文档体系：

- MCP facade：`mc_start`、`mc_lookup`、`mc_analyze`、`mc_sync`、`mc_resume`、`mc_handoff`、`mc_close`、`mc_admin`、`mc_context_pack`、`mc_onboard`、`mc_domain`、`mc_freshness`
- V3 基础模块：context pack、domain / business flow、freshness、onboarding、presentation、ontology、reasoning、storage
- Hybrid retrieval：intent detection、policy selection、BM25 / graph / semantic / optional vector fusion
- 自适应检索策略：`RetrievalPolicy` 已接入 source 执行前，学习权重受边界约束
- Golden Benchmark：公开 fixture + 私有真实场景 case 支持，含 recall、forbidden hit、latency、token、agent guidance 门禁
- Java parser differential：regex / tree-sitter 差异评测、fallback diagnostics、critical disagreement 统计
- Java call resolution benchmark：基于逻辑锚点的 `CALLS_METHOD` 精度门禁，CLI / MCP / HTTP 入口已接入
- Reasoning pipeline：`_reasoning` additive 字段，区分 fact / inferred / derived 并保留 explanation
- Completion status：method walkthrough 返回 complete / partial / blocked / stale，指导 Agent 停止或继续补证据
- Walkthrough 输出分级：`summary / standard / deep`，结构化字段保持不变
- Candidate paths：`workspace_sniff`、`lookup_hint`、`memory_impact`、`runtime_audit`、`discover` 已有候选路径、推荐路径和学习回流
- Context Pack / Freshness 推荐：`mc_start` 已返回 context pack / freshness 相关提示
- Observable dual-read：JSON / JSONL 与 SQLite mirror 的读取来源、fallback 和一致性状态可观测
- 删除/移动感知增量索引：scoped reconciliation 会清理确定性索引和 graph stale 数据
- Typed facade metadata：`_meta`、`_quality` 等 additive 元数据保持 dict 兼容
- Unified observability：reindex / hybrid lookup 结构化记录 duration、outcome、result count，路径类标签脱敏
- Portable benchmark baseline：支持 median / p95 latency 与 quality regression 比较
- Vue Workbench：HTTP `/app` 托管，覆盖 dashboard、query、impact、freshness、audit、health 等页面

### 仍未完成 / Still Open

当前真正值得继续做的是：

1. **Java Parser / Call Resolver 真实精度深化**：已有严格门禁和未解析分类报告；持续用真实跨项目 controller / service / feign case 扩充样本并修复明确误判。
2. **Retrieval / Reasoning 质量运营闭环**：策略、解释、replay、趋势与有界反馈已经落地；下一步是积累真实任务回放并只根据人工验证结果调整权重，减少“看似命中、实际偏题”。
3. **真实性能基线长期治理**：已有 portable Golden 基线和回归比较；后续版本必须在真实 workspace 的冷/热查询、全量/增量索引上证明不低于基线。
4. **Workbench 与报告体验产品化**：Health 已展示 benchmark/gate 摘要并可直达 walkthrough；walkthrough 导出时会同时呈现当时的 gate 摘要，形成面向人工复盘的阅读路径。

### 最近完成 / Recently Completed

以下事项已在最近一轮代码和真实场景验收中完成，不再作为待办：

1. **CBM 参考设计对齐**：已形成固定参考文档 [docs/references/codebase-memory-mcp.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/references/codebase-memory-mcp.md) 和配套设计收口文档 [docs/benchmarks/P0_INDEX_HOT_PATH_DESIGN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/benchmarks/P0_INDEX_HOT_PATH_DESIGN.md)。
2. **Java reindex 性能热点修复**：P1-0 profile 定位的 parser 双轨、`dataclasses.asdict`、graph metadata `json.dumps` 三个热点已在代码中修复，并已在私有 UCAP workspace 上通过 call resolution / golden / performance / doctor / walkthrough gate 验收。

---

## 3. 开发优先级 / Development Priorities

### P0-0：CBM 参考设计对齐（已完成）

目标：在动 P0 性能代码前，先把 CBM 的关键工程设计转成 Memory Center 的索引热路径方案。

依据：

- [docs/references/codebase-memory-mcp.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/references/codebase-memory-mcp.md)

任务：

1. 明确本阶段吸收哪些 CBM 思路：RAM-first staging、批量写入、tree-sitter + resolver 分层、FTS/BM25 候选、watcher 增量、graph artifact。
2. 明确本阶段不做哪些：C 重写、158 语言覆盖、CBM backend provider、复制源码、必选压缩依赖。
3. 输出一个短设计或直接更新 P0 实施说明，保证 `asdict`、metadata JSON、parser 双轨三个修复能落在同一热路径策略里。
4. **产出**：[docs/benchmarks/P0_INDEX_HOT_PATH_DESIGN.md](./benchmarks/P0_INDEX_HOT_PATH_DESIGN.md)，已锁定三个修复的共享契约、实施顺序、验收门禁、非目标，并明确 CBM 的 watcher / incremental / FTS / BM25 / resolver 分层在当前代码里已经落地，本阶段只补 Python 热路径与 graph metadata 收口。

验收：

- 文档明确 P0 热点修复顺序和不做事项。**已完成**。
- 不超过一个工作日，不能变成长期调研。**已完成**。
- 完成后直接进入 P0 Java reindex 性能热点修复。**已完成,见下**。

### P0：Java reindex 性能热点修复（已完成,真实 UCAP gate 全过）

目标：降低真实 Java workspace 的全量 reindex 时间，同时不牺牲 parser / call resolver 精度。

依据：

- [P0_UCAP_REAL_BENCHMARK.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/benchmarks/P0_UCAP_REAL_BENCHMARK.md)
- [P1_0_JAVA_PARSING_PROFILE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/benchmarks/P1_0_JAVA_PARSING_PROFILE.md)

任务：

1. `TreeSitterJavaParser.parse` 去掉默认全量 regex 双轨。**已完成**：tree-sitter 成功路径改为只调用 `RegexJavaParser.parse_supplements` 做按需补抽取；`MEMORY_CENTER_PARSER_FULL_DUAL=1` 可一键回退到旧的双轨全量行为。
2. tree-sitter 成功时只执行必要的轻量补抽取，或在 differential gate 通过后完全跳过 regex。**已完成**：supplements 只抽 `constants` / `method_variable_types` / `bean_injections` / `method_calls` / `dto_field_usages` / `config_usages` / `data_resources`，结构性字段全部由 tree-sitter 提供；regex `parse_supplements` 仍会跑 `_parse_fields` 自愈兜底。
3. 为 `JavaSymbol` 增加手写浅拷贝 `to_dict()`，避免通用 `dataclasses.asdict` 深递归。**已完成**：键集合、键序、值与 `asdict` 完全一致；`core.models.to_dict` 优先调用对象自带的 `to_dict()`。
4. 为 graph metadata 序列化增加安全快路径：空 metadata 直接写 `'{}'`，非空再 `json.dumps`。**已完成**：新增 `memory_center/core/storage/metadata.py:metadata_json`，`GraphStore.rebuild` / `bulk_write` / `partial_rebuild` / `_upsert_search_rows`、`retrieval/inverted.py`、`semantic.py` 全部统一调用。
5. 为三项优化分别补 focused benchmark，不用主观体感判断是否变快。**已完成**：`tests/test_p0_index_hot_path.py` 锁住等价性契约;本地微基准 `to_dict ~97x` / `metadata_json({}) ~19x`;真实 UCAP reindex 一次冷启动从 140.6s → 139.0s(IO 抖动主导,wall-clock 持平),graph 反而多出 ~1.7K 节点(tree-sitter 现在覆盖 `@interface`、interface 常量、wildcard imports);Java call resolution gate / Golden gate / performance gate / doctor / walkthrough 状态全部不退步。

验收：

- parser differential critical disagreement `= 0`
- Java call resolution gate 不下降
- Golden anchor recall / edge recall 不下降
- forbidden hit rate `= 0`
- 真实场景 reindex 性能不低于当前基线
- 不提交真实 workspace 生成的 `.memory-center/index`、`.memory-center/memory` 或源码片段

### P1：Java Parser / Call Resolver 真实精度深化（已完成第一轮,持续扩充）

目标：让 method walkthrough 和跨项目链路在真实 Spring Cloud 场景下更稳。

任务：

1. 从真实 workspace 中选取 10-15 个跨项目 controller 入口，转成只含逻辑锚点的私有 cases。**已完成**：`golden/java-call-resolution-openapi.yaml` 从 15 个 case 扩到 26 个。
2. 扩展 Java call resolution case schema：覆盖 entry method、same-class private method、Service interface -> Impl、Feign -> Controller、Controller -> Service Impl、mapper / repository 边界。**已完成**：新增 5 类 case（Controller -> ServiceImpl 直接 DI；Controller -> Service interface 多态 dispatch 3 个；ServiceImpl -> Mapper 3 个；ServiceImpl same-class private helper 2 个；static_import 2 个）。
3. 对每类失败只修一个明确 parser / resolver gap，避免靠宽泛搜索掩盖问题。**已完成第一轮**：发现并修复 `RegexJavaParser` 把 interface 方法声明当 body 导致的 ~13K self-loop 假边（self-loop 12,812 -> 795，-94%）；CALLS_METHOD 总量从 294,230 -> 279,542 抹掉 14,688 条假边。
4. 将误判样例沉淀为可复跑 case，而不是只修当前文件。**已完成**：`tests/test_p1_call_resolution_and_vector_gate.py` 锁住 interface declaration 自环不重现 + default 方法体仍正常抽取调用 + `enable_vector` schema round-trip + `_sync_retrieval_indexes` 不破坏现有 VectorIndex。
5. 在 `mc_admin(action="eval_java_call_resolution")`、CLI、HTTP 输出里持续保留失败原因和缺失锚点。**保持现状**：26/26 cases edge_recall=1.0 / high_confidence=1.0 / unresolved=0.0。
6. 未解析 CALLS_METHOD 已可通过 `eval-java-call-resolution-unresolved`、`/workspace/eval-java-call-resolution-unresolved`、`mc_admin(action="eval_java_call_resolution_unresolved")` 按原因分类，只返回逻辑锚点样本，不返回路径或源码。后续从最大分类开始补真实 case（external API、缺失模块、receiver type、polymorphism dispatch），不得以宽泛 fallback 提高召回率。

验收：

- 真实私有 cases anchor recall `>= 0.90` **ok**（26/26 = 1.0）
- edge recall `>= 0.85` **ok**（1.0）
- forbidden hit rate `= 0` **ok**
- 每个失败 case 都能定位到 parser、resolver、graph 或 retrieval 中的具体一层 **ok**（interface self-loop -> parser 层 `_parse_method_calls` bare-call 误匹配 declaration span）

### P1.5：Vector Gate / 向量召回长期门禁（已完成）

目标：把 [P0_5_VECTOR_VALIDATION.md](./benchmarks/P0_5_VECTOR_VALIDATION.md) 在真实 UCAP 上验证过的 vector 收益锁进 long-term golden gate。

任务：

1. `GoldenCase` schema 新增可选 `enable_vector` 字段（默认 False），让 hybrid case 可以显式声明走 ANN 路径。**已完成**。
2. `golden/cases.yaml` 增加 vector-aware concept query case（Feign 鉴权拦截器、Kafka 消费者解析消息），expected_anchors 指向 method 级真实命中。**已完成**：anchor_recall 0.6444 -> 0.8667。
3. 修复 `_sync_retrieval_indexes` 在 sparse-only reindex 时悄悄清空 VectorIndex 的 silent regression。**已完成**：`dense_items` 为空时保留现有 vector embeddings。

### P2：Retrieval / Reasoning 质量闭环

目标：让 `mc_lookup(auto)`、walkthrough、impact、context pack 在真实任务中更少误判、更少重复搜索。

任务：

1. **实现完成，进入真实运营验证**：用真实 session replay 验证 adaptive retrieval policy，不再用 examples 作为主要验收；每个版本至少比较 adoption、bypass、unobservable 和 Golden 指标。
2. **已完成**：retrieval diagnostics、reasoning explanation、completion status 已收敛为稳定的 `agent_next_steps`。
3. **已完成**：存在 `absolute_file_path` / `read_targets` 时抑制 `find`、`grep -l` 等重复定位建议，并由 guidance gate 覆盖。
4. **已完成**：Golden case 支持 full-chain、impact、context（architecture understanding）模式和禁止锚点。
5. **已完成但必须人工验证**：retrieval source feedback 仅接受显式 verified outcome，并限制权重区间；replay 只影响下一步建议表达，不会把“执行过工具”误当成“检索正确”。

验收：

- 完整链路 case 不再建议重复全局搜索
- partial / stale case 明确指出缺失层或 stale 文件
- same input 产生确定性 retrieval policy
- token 和 latency 不低于真实基线

### P2 下一轮执行计划 / Next Executable Plan

1. 使用 `eval-agent-guidance-replay-campaign --min-events 20` 在私有真实 workspace 连续采集至少 20 个带 `session_id` 的任务回放，覆盖 full-chain、impact、MQ、config 与概念检索；该 gate 只评估覆盖与采纳，不会自动调整权重。
2. 对每个 replay 记录人工确认的命中/偏题结果；只将确认结果写入 retrieval-source feedback。
3. 每次权重变更后运行 Golden、replay trend、cold/hot query baseline；任一质量门禁退化即回滚。
4. 对 Java 未解析报告中最高频分类补 3-5 个逻辑锚点 case；只有 case 证明精度时才改 resolver。
5. Workbench Health 已展示 benchmark/gate 摘要，且仅输出指标、状态和建议，不暴露私有源码内容；已可直达 walkthrough，导出动作同时呈现当前 gate 快照。

### P3：Workbench 与报告体验产品化

目标：详细输出继续保留，但阅读顺序和视觉组织更适合人和 Agent。

任务：

1. Query / Walkthrough 页面突出 quick conclusion、main chain、completion status、read targets、risks。**已完成**：Workbench walkthrough 使用顶层结构化字段，原始响应退到可展开 evidence 区。
2. `summary / standard / deep` 三档在 CLI / MCP / HTTP / Workbench 中展示语义一致。**已完成**：Workbench walkthrough 可选择三档，并直接透传 `report_level`。
3. 报告里的长路径继续使用证据编号，完整路径集中在 evidence files 区。**已完成**：Workbench 主阅读区仅展示角色和逻辑锚点，完整响应仅在折叠 evidence 区呈现。
4. Workbench 增加 benchmark / gate 结果摘要，不展示私有源码内容。**已完成**：Health 页面通过 `/workspace/quality-gates-summary` 展示 benchmark、regression alerts、replay campaign 和 Java unresolved-call 指标。
5. 将 walkthrough export 与真实 gate 结果关联，便于人工复盘。**已完成**：导出完成反馈显示对应的实时 gate snapshot；Health 摘要也可直接进入 walkthrough review。

验收：

- 人类阅读不需要解析原始 JSON 才能知道主链路
- Agent 可直接使用顶层字段，不需要读 `tool-results/*.json`
- Workbench 不泄漏私有路径、源码片段或服务名

### 已完成：外部吸收归档

目标：已吸收的外部项目思想全部标记完成，后续无需继续参考这些外部项目推进主路线。

已完成吸收：

- `codegraph` 类项目：tree-sitter Java parser、SQLite BM25 / inverted retrieval、freshness banner、watcher-to-incremental-reindex、context pack first、context pack benchmark、daemon feasibility 均已落地或归档。
- `Understand-Anything` 类项目：guided tour / onboarding、统一 explanation schema、business flow、flow-aware impact、persona-adaptive explanation、理解资产增量刷新均已落地。
- `ECC` 类项目：workflow profiles、verification loop、pattern promotion、learned heuristics、agent runtime audit、agent bundle export 均已落地。
- `rtk`：token estimate、compact operation gain、discover / command compression 思路已吸收到 token benchmark、payload compression 和 discover 输出。
- `agentmemory`：top-K memory ranking、token benchmark / trend 思路已吸收到 session memory、benchmark baseline 和 trend。
- `mattpocock/skills`：constraint templates 和模型内工作协议思路已吸收到 templates / workflow profile / recommended next action。
- candidate path / 概率树视角：candidate paths、recommended path、confidence / risk / verification cost、低成本验证优先和 learning feedback 已进入主链路。

归档判断：

- 上述项目后续不再作为路线输入，不再继续追踪原项目变化；CBM 例外，仅保留为固定本地参考文档 [docs/references/codebase-memory-mcp.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/references/codebase-memory-mcp.md)，后续引用该文档而不是继续跟踪外部项目。
- 未进入当前实现的 `open-code-review`、`spec-kit` 相关想法不再单列路线；如未来真实问题需要，再按本项目自己的 gate 重新立项。
- 不引入外部项目作为必选 runtime dependency，不复制外部 CLI / 配置目录 / slash command 体系。
- 不把自然语言 spec 置于真实代码和运行证据之上，不把权重伪装成客观真值，不引入非工程化叙事。

---

## 4. 执行原则 / Execution Rules

这些原则从旧版执行计划合并而来，后续不再单独维护执行计划文档。

1. 功能真实可用、用户实际好用优先于遵守旧模块边界和旧任务顺序。
2. 可以重排阶段、合并任务、替换旧实现和重构核心模块。
3. 每项完成的能力应有测试、入口验证和文档同步。
4. CLI / MCP / HTTP 可以针对入口场景优化，但核心语义、结果结构和错误语义必须可解释。
5. 任何主链路 `except Exception` 都不能静默吞掉真实失败，必须返回 diagnostics、fallback reason 或明确降级说明。
6. 新入口必须优先复用 core 层能力，不在 CLI / MCP / HTTP 三处复制决策逻辑。
7. 输入 workspace 时，公共入口默认接收 `workspace.yaml` 或目录，再通过 `WorkspaceStore` 解析 graph / memory / artifact 路径。
8. 测试不得直接写入仓库内 `examples/*/.memory-center` 的运行态 graph / memory 生成物；需要写入时复制到 `tmp_path`。
9. 公开 examples 只做 smoke / fixture，真实完成判断必须优先使用用户提供的真实场景。
10. 不提交私有 workspace 的 `.memory-center/index`、`.memory-center/memory`、私有 cases、私有 baseline、完整 payload、真实路径、内部服务名或密钥。

### 三入口一致性 / CLI MCP HTTP Consistency

下列能力继续保持三入口一致性测试和文档同步：

- `context-pack`
- `freshness`
- `onboard`
- `domain`
- `business-flow`
- `business-flow-impact`
- `runtime-audit`
- `regression-alerts`
- `eval-golden`
- `eval-java-call-resolution`

验收要求：

- 同一 workspace / query / seed 在 CLI、MCP、HTTP 中返回核心字段一致。
- 错误使用统一错误模型：`invalid_input`、`not_found`、`unavailable`、`conflict`、`internal_error`。
- MCP schema 只能 additive 兼容扩展，不能破坏既有 tool 参数。

### Ruff 与代码治理 / Ruff and Code Governance

当前 Ruff 方向不再作为主路线最高优先级，但保留为持续治理要求：

- 基础门禁 `F/E9/I001/B006/B008/B904` 必须持续通过。
- `UP035 / UP006 / UP045 / UP007` 等现代化项按目录小批量处理，避免大 churn。
- `B007`、`B905` 这类语义项必须手工判断，不能机械改 `_` 或盲目加 `strict=True`。
- Ruff 清理不能替代真实场景 gate；它只证明代码卫生，不证明用户体验完成。

### 开放方向 / Open Directions

以下方向不再视为禁区。只要能明显改善真实用户问题，可以直接调研、原型验证并实施：

1. 重写 indexer，提高索引精度、增量性能和语言扩展能力。
2. 引入可选图数据库、向量数据库或搜索后端。
3. 重新设计 JSONL、SQLite、graph 和 memory 存储结构，并提供迁移工具。
4. 增加 daemon、后台任务、自动监听和持续索引能力。
5. 重做前端、可视化、配置流程和排障体验。
6. 合并或删除重复入口，重新设计 MCP、CLI、HTTP 的产品交互。
7. 引入新的语言支持、框架适配器、评测系统和 Agent 工作流。

实施前至少回答：

- 解决了哪个真实用户问题。
- 相比当前实现，体验、准确率、性能或维护性提升在哪里。
- 最小可用版本如何验证。
- 数据迁移、兼容和回滚如何处理。
- 后续维护成本是否可接受。

注意：开放方向不再依赖外部项目清单驱动。外部吸收项已经归档，后续立项必须来自真实使用问题、benchmark、gate 或当前架构缺口。

---

## 5. 统一验收门禁 / Unified Gates

后续任何“完成”判断必须优先使用真实场景：

- 默认真实 workspace 使用本地私有 `workspace.yaml`，文档只写 `<private-real-workspace>` 占位。
- 公开 examples 只作为 CI smoke test、单元测试 fixture、公开复现模板。
- 若真实 cases 缺失，结果必须标记为 `real_case_missing`，不能用 examples 指标替代真实验收。
- 若性能 baseline 缺失，可以用当前已验收版本生成新基线；后续版本只能更好，不能比基线差。

最低检查：

```bash
python3 -m compileall -q memory_center tests
git diff --check
pytest -q
scripts/verify_real_ucap.sh
```

真实场景 gate 最少包含：

- Golden anchor recall
- Golden edge recall
- forbidden hit rate
- Java call resolution recall
- walkthrough invalid search suggestion count
- median / p95 latency
- token estimate
- parser diagnostics
- completion status

---

## 6. 非目标 / Non-Goals

- 不删除 regex parser；它仍作为 fallback 和 differential oracle。
- 不默认开启 vector retrieval；真实质量和性能基准稳定后再讨论默认策略。
- 不一次性把 JSON / JSONL / Markdown 事实源迁移到 SQLite。
- 不新增平行 MCP facade tool；优先扩展现有 `mc_lookup`、`mc_analyze`、`mc_admin`。
- 不为了类型化破坏现有 dict 返回和 MCP tool schema。
- 不把私有 workspace 生成物、源码片段、真实路径或密钥写进仓库文档。

---

## 7. 下一步建议 / Recommended Next Step

下一步进入 **P1 Java Parser / Call Resolver 真实精度深化**:扩充真实跨项目 controller / service / Feign cases,把误判样例逐个转成可复跑门禁,并继续给 method walkthrough 在更多真实场景下增加稳定性。

P0 三步修复推荐顺序已经按以下风险序落地:

1. `JavaSymbol.to_dict()` 手写浅拷贝(最稳)。
2. graph metadata 空 dict 快路径(schema 不变)。
3. parser 双轨改为补抽取(最敏感,有 differential / call resolution / golden gate 兜底,并保留 `MEMORY_CENTER_PARSER_FULL_DUAL` 环境变量回滚开关)。

完成 P0 后,真实 UCAP 复测通过即进入 P1 扩充真实 Java call resolution cases,并把失败样例逐个转成可复跑门禁。
