# Context Engineering Baseline Review / 上下文工程基线评审

> **Status / 状态**：2026-09-14 基线。依据当前源码、公开文档与接口契约进行静态评审；不是运行时性能或模型质量基准。
>
> **Scope / 范围**：Memory Center 的检索、记忆连续性、宿主边界、隐私和可运维性。原始 Context Engineering 文章仅作理念来源，不作为实现事实来源。

## Executive Decision / 结论

Memory Center 已具备 Context Engineering 的主要工程能力：JIT 混合检索、证据边界、渐进披露、分层记忆、Task Shadow、恢复与 handoff、审计和有界输出。当前不应新增“自动会话压缩”或“宿主 token 预算治理”。

优先工作不是扩张能力，而是持续验证现有能力是否真正降低了无效上下文、是否在不同宿主下保持边界一致。

## Baseline Matrix / 基线矩阵

| 评审主题 | 现状 | 证据 | 结论 |
|---|---|---|---|
| 精准而非全量供给 | 图谱、BM25、稀疏/可选向量检索；`mc_context_pack` 与 evidence-index 提供有界结果 | ARCHITECTURE 7.1–7.4；MCP 查询协议 | 已满足 |
| 结论可信与新鲜度 | `evidence_level`、freshness、coverage、`claim_boundary` 与 chain anchor gate | ARCHITECTURE 7.5；MCP_GUIDE 6 | 已满足 |
| 长任务连续性 | L0/L0.5/L1/L2/L3、Task Shadow、`mc_resume`、`mc_handoff` | ARCHITECTURE 10；MCP_GUIDE 5 | 已满足 |
| 宿主会话所有权 | 仅接收 durable、脱敏快照；不保存完整对话 | ARCHITECTURE 11；SESSION_FIRST proposal 11 | 已满足，已澄清 |
| 输出与存储容量控制 | context-pack 预算、渐进展开、工件/事件/审计归档 | context budget、artifact/session archive | 已满足；术语已澄清为 MC 自身数据控制 |
| 自动压缩宿主会话 | 不实现、不计划为默认候选 | MEMORY_ENRICHMENT_DESIGN 3.4、7 | 明确不做 |
| 效果度量 | 已有 retrieval replay、Golden、质量/运行观测 | ARCHITECTURE 13 | 基础已具备，需持续积累真实样本 |

## Clarifications Applied / 已完成的表述治理

- “compact output / 紧凑输出”只指 Memory Center 的响应形状，不指会话摘要。
- “archive / 归档”只指 Memory Center 的工件、事件或审计保留，不指宿主历史压缩。
- `budget_tokens` 是调用方请求的响应体积预算；不是宿主实际剩余 token，也不能用作自动压缩阈值。
- 宿主仍拥有完整会话、token 统计、压缩策略和最近文件状态；MC 只接收可持久化的结构化快照。

## Evidence-backed Roadmap / 有证据的后续路线

### P1 — Measure retrieval usefulness / 度量检索有效性

为已有 `eval_retrieval_replay`、Golden 和 interaction effects 建立真实工作区样本：按任务类型记录命中是否改变了下一步、是否减少重复搜索、是否带来可验证的交付结果。只观测，不从“建议被执行”自动推断检索质量。

**Exit criteria / 退出条件**：有足够人工验证样本时，再评估融合权重或默认输出大小；样本不足时保持现状。

### P2 — Cross-host Shadow contract verification / 跨宿主 Shadow 契约验证

使用 DSH/Codex/其他 adapter 的真实 durable snapshot 做兼容回放，验证 watermark、source identity、隐私拒收、stale state 和 handoff 行为；不传输完整对话。

**Exit criteria / 退出条件**：每种接入宿主均能证明快照幂等、异常恢复和隐私字段拒收。

### P2 — Review checklist adoption / 清单进入设计流程

将 [Context Engineering Narrative and Review Checklist](CONTEXT_ENGINEERING_NARRATIVE_AND_REVIEW.md) 链接到新的设计提案或 ADR 模板；只要求在新增检索源、记忆层、adapter 或自动化行为时填写，不将其改造成所有普通修复的阻断门禁。

## Explicit Non-goals / 明确非目标

- 自动压缩宿主对话或管理宿主 token 预算。
- 自动注入记忆、阻塞用户输入或默认扩大检索范围。
- 把未验证的模型摘要直接升级为长期经验。
- 以单一 token 节省数字替代检索正确性、证据质量和交付验证。
