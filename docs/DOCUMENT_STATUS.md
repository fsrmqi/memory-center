# Documentation Status / 文档状态目录

> **基准版本**：5.0.0b33；原引擎文档以 4.x 保留版本为来源
> **更新日期**：2026-11-18
> **规则 / Rule**：当前行为以代码、CLI `--help`、路由、MCP schema 和标记为 `current` 的文档为准。历史文档保留当时的样本与结论，不重写为当前事实。

## Current / 当前文档

| 文档 | 权威范围 |
|---|---|
| `docs/V5_CATALOG_GUIDE.md` | 项目身份、受控登记接口、预览范围与错误合同 |
| `docs/V5_SERVICE_GUIDE.md` | 5.0 服务入口、接口合同与 wheel/Compose 操作 |
| `README.md` | 产品定位、安装、快速开始与当前版本概览 |
| `docs/ARCHITECTURE.md` | 当前分层、运行模型、质量/检索/存储架构 |
| `docs/MCP_GUIDE.md` | 5.0 统一 MCP 合同：接入方式、17 个工具参考、证据边界与 4.x 迁移对照 |
| `docs/USER_GUIDE.md` | 用户工作流、维护、质量门禁与故障处理 |
| `docs/REFERENCE.md` | CLI、HTTP、MCP 的事实参考与维护命令 |
| `docs/ONTOLOGY.md` | 实体、关系、证据强度和治理语义 |
| `docs/TECHNICAL_DESIGN_AGENT_PROPOSAL.md` | 技术方案设计 Agent 的决策提案：以证据约束的渐进式方案工作流；`TECH_SPEC.md` 的部分基础字段已落地，完整编排与门禁尚未实现 |
| `docs/LOOKUP_ARCHITECTURE_HANDOFF_PLAN.md` | 查询架构的契约、门禁与验收矩阵 |
| `docs/MEMORY_ENRICHMENT_DESIGN.md` | 记忆增强设计提案：四项能力设计与证据边界；A（evidence-index 渐进式披露）与 B（Session Notes 叙事层）已实现（见 CHANGELOG），C（Memory Cube）为草案，D（四类记忆用户模型）已落 USER_GUIDE |
| `docs/HTTP_DISPLAY_MIGRATION.md` | 内置工作台下线后的 HTTP JSON 读模型与管理页迁移说明 |
| `docs/DSH_LOCAL_TELEMETRY.md` | 可选的宿主执行元数据接入与本地观测边界 |
| `docs/DOCUMENT_CONSTITUTION.md` | 文档治理、生命周期与发布清单 |
| `docs/THREE_SYSTEM_KNOWLEDGE_LOOP.md` | Memory Center 与外部长期知识库、宿主插件的协作边界 |

## Current decisions and references / 当前决策与参考

- `docs/adr/0004-service-platform-and-admin.md`：方向已接受；调整未来展示的产品边界，保留核心依赖方向，按全新安装重建，不保留历史数据与接口兼容层。

| 文档 | 状态 |
|---|---|
| `docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md` | Phase A–D 已实施；Phase E 仅在真实非 Java 需求出现后评估 |
| `docs/adr/0001-core-dependency-direction.md` | 有效 |
| `docs/adr/0002-module-boundaries-and-completion.md` | 有效 |
| `docs/adr/0003-remove-graph-view-builder.md` | 有效 |
| `docs/adr/0005-v5-workspace-catalog.md` | 有效 |

## Historical evidence / 历史证据

公开仓库只保留用户可感知的历史记录：`docs/CHANGELOG.md` 的已发布条目与 `docs/adr/`、`docs/decisions/` 中的决策记录。实验样本、内部实施回执与性能取证属内部证据，不进公开仓库；它们可能包含旧版本号、旧基线或已替代的设计，也不得据此判断当前接口或待办。

| 分类 | 文档 |
|---|---|
| 历史记录 | `docs/CHANGELOG.md` 的已发布条目 |
| 决策记录 | `docs/adr/`、`docs/decisions/` |

## 4.6.13 capability summary / 4.6.13 能力摘要

- `quality-gate`：只读发布质量决策，汇总 generation、coverage、replay、IR、刷新与存储；不执行维护动作。
- `change_review.validation_plan`：按风险类别给出最小可证伪验证设计；不执行用户命令。
- `primary_chain`：非 fast 的 Method lookup 可返回有界 Feign/HTTP 主链；MQ 无 destination 证据时返回 `insufficient_evidence`。
- retrieval replay：仓库外脱敏 case 驱动质量评测；同类失败少于三例不触发检索改动。
- scoped refresh budgets：按 category + scope 分桶；少于五条真实样本不产生超预算门禁。
- SQLite-first indexes：`RUNTIME_ONLY_INDEXES` 无 JSON 查询回退；清理、GC、compact 和 VACUUM 必须显式 apply。
- Workbench quality overview：只读展示 quality-gate、generation、刷新、IR 与存储摘要，不展示私有正文或源码。
- Retrieval context governance：related case 按已有命中热度稳定重排；会话级已服务文件仅以无歧义路径降权；purpose 会以兼容字段解释候选和证据预算。
- Session-state boundary：已服务账本由 SQLite `session_state` 权威存储；新 case 带稳定 ID，resume 的 `case_recalled` 事件用于精确热度统计。
