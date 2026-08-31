# Documentation Status / 文档状态目录

> **基准版本 / Baseline**：4.6.7  
> **更新日期 / Updated**：2026-08-30  
> **规则 / Rule**：当前行为以代码、CLI `--help`、路由、MCP schema 和标记为 `current` 的文档为准。历史文档保留当时的样本与结论，不重写为当前事实。

## Current / 当前文档

| 文档 | 权威范围 |
|---|---|
| `README.md` | 产品定位、安装、快速开始与当前版本概览 |
| `docs/ARCHITECTURE.md` | 当前分层、运行模型、质量/检索/存储架构 |
| `docs/MCP_GUIDE.md` | MCP facade、Agent 行为、质量与证据边界 |
| `docs/USER_GUIDE.md` | 用户工作流、维护、质量门禁与故障处理 |
| `docs/REFERENCE.md` | CLI、HTTP、MCP 的事实参考与维护命令 |
| `docs/ONTOLOGY.md` | 实体、关系、证据强度和治理语义 |
| `docs/NEXT_PHASE_MASTER_PLAN.md` | 唯一活跃开发路线；已完成工作不作为待办 |
| `docs/DSH_WORKBENCH_PRODUCTIZATION_ROADMAP.md` | DSH/Workbench 产品路线与只读质量视图 |
| `docs/DOCUMENT_CONSTITUTION.md` | 文档治理、生命周期与发布清单 |
| `docs/THREE_SYSTEM_KNOWLEDGE_LOOP.md` | Memory Center、DSH 与 Personal Wiki 的协作边界 |

## Current decisions and references / 当前决策与参考

| 文档 | 状态 |
|---|---|
| `docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md` | Phase A–D 已实施；Phase E 仅在真实非 Java 需求出现后评估 |
| `docs/adr/0001-core-dependency-direction.md` | 有效 |
| `docs/adr/0002-module-boundaries-and-completion.md` | 有效 |
| `docs/adr/0003-remove-graph-view-builder.md` | 有效 |
| `docs/references/codebase-memory-mcp.md` | 设计参考，不是运行时依赖或兼容目标 |

## Historical evidence / 历史证据

以下文档用于追溯当时的实验、样本、实现或研究。它们可能包含旧版本号、旧基线、已完成的“下一步”或已替代的设计；不得据此判断当前接口或待办。

| 分类 | 文档 |
|---|---|
| 实施回执 | `docs/implementation-receipts/*.md` |
| 性能/验证基准 | `docs/benchmarks/*.md` |
| 研究与吸收材料 | `docs/ARCHIFY_ABSORPTION_RESEARCH.md`、`docs/MEMORY_LANDSCAPE_RESEARCH.md` |
| 历史数据闭环 | `docs/DATA_REAL_LOOP_RUN1.md` |
| 历史记录 | `docs/CHANGELOG.md` 的已发布条目 |

## 4.6.7 capability summary / 4.6.7 能力摘要

- `quality-gate`：只读发布质量决策，汇总 generation、coverage、replay、IR、刷新与存储；不执行维护动作。
- `change_review.validation_plan`：按风险类别给出最小可证伪验证设计；不执行用户命令。
- `primary_chain`：非 fast 的 Method lookup 可返回有界 Feign/HTTP 主链；MQ 无 destination 证据时返回 `insufficient_evidence`。
- retrieval replay：仓库外脱敏 case 驱动质量评测；同类失败少于三例不触发检索改动。
- scoped refresh budgets：按 category + scope 分桶；少于五条真实样本不产生超预算门禁。
- SQLite-first indexes：`RUNTIME_ONLY_INDEXES` 无 JSON 查询回退；清理、GC、compact 和 VACUUM 必须显式 apply。
- Workbench quality overview：只读展示 quality-gate、generation、刷新、IR 与存储摘要，不展示私有正文或源码。
