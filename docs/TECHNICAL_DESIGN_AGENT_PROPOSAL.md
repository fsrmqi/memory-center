# Technical Design Agent Proposal / 技术方案设计 Agent 提案

> **状态 / Status**：提案；`TECH_SPEC.md` 已可派生部分方案基础信息，但本文定义的完整编排与门禁尚未实现，也不是当前默认工作流。
>
> **范围 / Scope**：定义如何基于 Memory Center 现有的工程事实、任务工件和验证证据，逐步形成可追溯的技术方案设计能力。

---

## 1. 目标与边界 / Goal and Boundaries

本提案中的“技术方案设计 Agent”不是一个替代架构师的自动决策器，也不是把需求、代码和历史文档一次性塞进上下文的长提示词。它是一条受证据约束的工作流：把需求范围、业务含义、服务链路、代码与配置事实、影响面和验证设计组织成一份可审查的方案。

The proposed Technical Design Agent is not an autonomous architect and not a long prompt containing every document. It is an evidence-bounded workflow that turns scope, domain meaning, service paths, code and configuration facts, impacts, and validation design into a reviewable technical plan.

它必须遵守以下边界：

- **证据优先**：影响实现范围的结论必须带来源引用、索引 generation 和证据等级；没有足够证据时只能标记为 `AMBIGUOUS`、`UNKNOWN` 或“待确认”。
- **渐进加载**：按任务推进加载最小必要上下文，禁止为生成方案而默认扫描全 workspace、重建索引或读取原始大附件。
- **人类保留决策权**：跨团队接口承诺、数据口径、合规、安全、资源预算和优先级冲突必须形成问题并停止等待确认，不能由 Agent 擅自补全。
- **不改变事实源**：代码、配置、图谱、运行时证据和既有任务工件仍是各自权威来源；方案只是可回溯的派生工件。
- **兼容优先**：首版不引入破坏性 MCP schema 变更、不新增平行 facade，也不自动执行写入、发布或验证命令。

## 2. 为什么值得做 / Why This Matters

复杂系统中，代码只能说明部分实现事实。一个可执行方案还要回答业务对象与边界、跨服务调用和异步链路、历史兼容约束、灰度与回滚、以及如何证明改动安全。若这些信息只是散落在少数人的经验、历史任务和文档中，Agent 即使局部代码解释正确，也可能在系统层面做出错误判断。

Memory Center 已具备这条能力链的基础：图谱与精确检索提供工程事实，`mc_analyze` 提供影响与验证清单，任务会话和工件保留过程上下文，freshness、evidence 与 claim boundary 约束结论强度。缺少的是把这些能力收敛为“产出技术方案前必须经过哪些证据门”的显式工作流。

## 3. 最小可行闭环 / Minimum Viable Loop

```text
需求材料
  -> 范围与验收澄清
  -> 业务术语和目标服务定位
  -> 调用链、契约和配置影响分析
  -> 代码事实与索引新鲜度核验
  -> Gap / 待确认项
  -> 技术方案 + 验证矩阵
  -> 人工评审后进入实现
```

| 阶段 | 目标 | 优先复用的当前能力 | 必须产物 |
|---|---|---|---|
| 1. Intake | 将原始需求变成可讨论的范围 | `mc_start`、任务工件、`feature_delivery_v2` | 目标、非目标、验收项、歧义项与来源 |
| 2. Discover | 先回答“改的是什么” | `mc_lookup`、`mc_domain`、`mc_context_pack` | 业务术语映射、候选服务/模块、证据引用 |
| 3. Trace | 定位“影响谁、经由哪里” | `mc_lookup(mode="trace"/"chain")`、`mc_analyze` | 主链路、旁路、契约/配置/MQ 风险 |
| 4. Verify | 用工程事实限制推断 | freshness、`mc_analyze(depth="standard"/"full")`、代码阅读 | 已核验事实、范围边界、未证实断言 |
| 5. Design | 输出可评审的变更方案 | 只读投影和任务工件 | 变更点、复用/改造/新建判断、风险与验证矩阵 |
| 6. Gate | 把不确定性留在台面上 | 人工评审、既有 policy/validation | 决策问题、停止条件、批准记录 |

这里的关键不是要求 Agent 知道所有信息，而是让它能沿着可靠路径获取完成**当前判断**所需的最小上下文与证据。

## 4. 方案输出契约 / Proposed Plan Contract

首版应以任务空间中的只读派生 `TECH_SPEC.md` 或等价 JSON 投影承载，不创建第二套事实库。当前 `TECH_SPEC.md` 已从既有工件展示需求范围、非目标、来源、代码目标、子任务读/写范围与停止条件，以及验收和验证设计；下列其余字段仍是建议结构，不代表已发布的 MCP 参数或存储 schema：

```text
technical_design
  source_refs             # 需求、图谱、代码、人工确认的引用
  scope / out_of_scope    # 做什么、不做什么
  assumptions             # 前提；每项都标记已确认或待确认
  terminology_map         # 业务语义 -> 服务/API/数据对象
  affected_targets        # 服务、仓库、模块、接口、配置、消息
  primary_flow            # 主链路及边界
  change_strategy         # reuse | modify | create，并说明原因
  compatibility_risks     # API、DTO、MQ、数据、配置、灰度与回滚
  validation_matrix       # 单测、契约、集成、回归、观测、发布/回滚
  open_questions          # 不能由代码或既有证据回答的问题
  evidence_boundary       # generation、freshness、证据等级、覆盖缺口
```

任何方案至少要回答五个问题：**改哪里、为什么改、影响谁、如何验证、还有什么没有确认**。最后一项不是缺陷，而是防止模型把信息缺口伪装成确定结论的安全阀。

## 5. 与当前架构的对应关系 / Mapping to the Current Architecture

| 设计 Agent 所需能力 | Memory Center 现有基础 | 尚需的编排或约束 |
|---|---|---|
| 需求范围、验收和阶段状态 | `feature_delivery_v2`、任务工件、resume/handoff | 形成统一的方案输入投影与歧义门禁 |
| 业务/架构/服务上下文 | 图谱、`mc_domain`、`mc_lookup`、`mc_context_pack` | 明确按任务类型选择和逐步加载的顺序 |
| 跨服务影响与契约风险 | `mc_analyze`、trace/chain、contract checks | 将结果收敛为方案的“影响与风险”章节 |
| 工程事实核验 | generation、freshness、evidence level、claim boundary | 禁止把 stale 或低证据结果升级为设计事实 |
| 长任务连续性与复用 | session、Task Shadow、task artifacts、case/Skill governance | 把确认后的设计决策与验证结果可控回写 |
| 展示与人工决策 | DSH Workbench、CLI/MCP/HTTP 的只读投影 | 展示 Gap、待确认项和批准状态，而非只展示漂亮摘要 |

## 6. 分阶段落地建议 / Incremental Delivery Plan

### Phase 0: 方案模板与人工试运行

先不新增工具。复用现有 `TECH_SPEC.md` 的基础字段，为少量真实、可脱敏的跨服务任务人工补充并审阅方案，记录：证据是否够用、漏掉了哪些参与方、哪些问题必须人工确认、验证矩阵是否真正覆盖风险。

Success criterion: at least several reviewed tasks show that the template improves completeness without causing unbounded retrieval or unsupported claims.

### Phase 1: 只读方案投影

在既有任务工件之上派生只读方案视图，复用 `mc_lookup`、`mc_analyze` 和 delivery matrix 已有证据；只展示来源、范围、影响、缺口与下一步，不自动写回业务知识或触发实现。

验收：同一任务在 CLI、MCP、HTTP 和 DSH 的核心字段一致；索引过期、调用链锚定失败或证据不足时，方案明确降级为待确认，而不是给出确定结论。

### Phase 2: 受控编排

仅在真实 replay 证明手工串联成本和遗漏率均值得优化后，再评估对既有入口作 additive 扩展。优先扩展 `mc_lookup`、`mc_analyze` 或 `mc_admin` 的兼容模式，避免新增第二个平行的 MCP facade。

验收：每一步都有有界输入、停止条件和可追溯输出；未决歧义、跨服务契约或高风险影响不能绕过人工 Gate。

### Phase 3: 基于验证的经验提炼

只有方案已实施、验证证据完备且经过人工确认后，才将可复用的结构、规则或验证路径提炼为 Skill 候选或 case。原始需求、私有源码和模型过程不得自动提升为长期事实。

## 7. 质量门禁与度量 / Quality Gates and Metrics

建议把“方案写得通顺”与“方案可执行”分开评估。可执行性至少包含六个维度：

1. **需求覆盖**：每条需求是否明确属于“做 / 不做 / 待确认”。
2. **系统覆盖**：涉及的服务、仓库、接口、配置、消息和外部参与方是否有来源。
3. **证据覆盖**：关键结论能否回溯至代码、配置、图谱、已确认文档或人工决定。
4. **风险覆盖**：兼容、异常、幂等、灰度、缓存、数据与安全约束是否被检查或显式排除。
5. **验证覆盖**：每个主要改动是否对应可证伪的测试、契约、观测、回滚或发布验证。
6. **不确定性治理**：未知和冲突是否作为问题暴露，而没有被模型自行补齐。

不应以“方案完整度 95%”这类脱离证据的单一数字作为发布条件。更可信的度量是：有多少关键结论具备来源、多少风险有验证动作、多少未决项在实施前得到人工关闭，以及真实回放中方案是否漏掉了参与方或验证项。

## 8. 非目标与风险 / Non-goals and Risks

- 不承诺自动替代架构评审、产品取舍或跨团队协调。
- 不把 RAG 结果、模型置信度或空搜索结果当作工程事实。
- 不让需求文本驱动任意 shell、写操作、发布、索引重建或知识提升。
- 不为方案生成引入全量代码上下文、全图遍历或默认模型下载。
- 不将真实私有路径、源代码片段、原始对话或机密配置写进公共模板、案例或评测数据。

## 9. 维护说明 / Maintenance Note

本文件属于**决策提案**。在相应能力实施并通过测试与真实任务验证前，当前行为仍以代码、CLI `--help`、MCP schema、HTTP 路由和标记为 `current` 的主文档为准。实现发生后，应将已完成事项迁入 `CHANGELOG.md` 和当前架构文档，并从本提案与主计划中移除已完成待办。
