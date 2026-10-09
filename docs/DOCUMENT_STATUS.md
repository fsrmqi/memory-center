# Documentation Status / 文档状态目录

> **基准版本 / Baseline**：4.6.13
> **更新日期 / Updated**：2026-09-03  
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
| `docs/TECHNICAL_DESIGN_AGENT_PROPOSAL.md` | 技术方案设计 Agent 的决策提案：以证据约束的渐进式方案工作流；`TECH_SPEC.md` 的部分基础字段已落地，完整编排与门禁尚未实现 |
| `docs/LOOKUP_ARCHITECTURE_HANDOFF_PLAN.md` | 查询架构收口的专项交接计划、契约与验收矩阵 |
| `docs/SESSION_FIRST_TASK_CONTINUITY_PROPOSAL.md` | Session-first / Task Shadow 产品与架构提案；L1 Shadow 核心已实现（shadow/observations/handoff 三模块 + facade/admin/CLI/HTTP 接入），DSH 侧适配见 `memory-center-dsh-plugin`（Task Shadow L1 投影） |
| `docs/MEMORY_ENRICHMENT_DESIGN.md` | 记忆增强设计提案：借鉴 MemOS / claude-mem / MemoraX 的四项能力；A（evidence-index 渐进式披露）与 B（Session Notes 叙事层）已实现（见 CHANGELOG Unreleased），C（Memory Cube）为 P2 草案待评审，D（四类记忆用户模型）已落 USER_GUIDE |
| `docs/WRITE_GOVERNANCE_ABSORPTION_PLAN.md` | 写入治理吸收方案：借鉴 Utopia（deeplethe/utopia）写入判定的七项工作项 G1–G7（P0：案例替代闭环 / L0.5 追加式替代 / 决策事件化）；含已核实现状基线、写入入口矩阵与前置验证清单 V1–V4 |
| `docs/DSH_WORKBENCH_PRODUCTIZATION_ROADMAP.md` | DSH/Workbench 产品路线与只读质量视图 |
| `docs/HTTP_DISPLAY_MIGRATION.md` | 内置 Workbench 下线后的 DSH 与 HTTP JSON 读模型迁移说明 |
| `docs/DOCUMENT_CONSTITUTION.md` | 文档治理、生命周期与发布清单 |
| `docs/THREE_SYSTEM_KNOWLEDGE_LOOP.md` | Memory Center、DSH 与 Personal Wiki 的协作边界 |

## Current decisions and references / 当前决策与参考

2026-10-09 服务化分支新增决策文档：

- `docs/V5_IMPLEMENTATION_PLAN.md`：decision；5.0.0 全新安装改造流程、WeKnora 固定版本参考、项目重建与发布验收；5.x 文档/Wiki/长期记忆为后续专题。
- `docs/SERVICE_PLATFORM_TECHNICAL_PLAN.md`：decision；4.6.30 基线上的独立服务、多空间和管理页面技术方案，包含现状证据、新协议与存储边界、开发切片与验收；描述的新增能力尚未实现。
- `docs/adr/0004-service-platform-and-admin.md`：方向已接受，实施待完成；调整未来展示的产品边界，保留核心依赖方向，按全新安装重建，不保留历史数据与接口兼容层。
- 唯一开发路线入口仍为 `docs/NEXT_PHASE_MASTER_PLAN.md`；其服务化分支说明优先于旧 DSH P0 展示路线。

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
