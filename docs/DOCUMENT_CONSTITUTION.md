# Documentation Constitution / 文档宪章

## 目的

文档不是代码的重复叙述，而是帮助人和 Agent 在信息不完整时做出可验证、可回滚决策的约束系统。

## 文档类型

每份当前文档必须明确自己属于以下一种类型：

| 类型 | 回答的问题 | 权威来源 |
|---|---|---|
| 规范 | 什么不能被违反？ | ADR、SPECS、公开 schema 与测试 |
| 操作 | 当前任务怎样完成？ | USER_GUIDE、MCP_GUIDE |
| 事实 | 现在有哪些入口和字段？ | 代码、`--help`、路由注册、REFERENCE |
| 对外介绍 | 价值、能力边界和技术路线如何被非维护者理解？ | README、ARCHITECTURE |
| 决策 | 为什么这样设计，何时推翻？ | ADR、decisions、主计划 |
| 历史 | 过去发生过什么？ | archive、CHANGELOG |

同一事实只能有一个权威来源；其他文档必须链接或概述，不能复制出独立版本。

## 生命周期与状态

- `current`：必须与当前发行版一致。
- `decision`：记录仍有效的设计取舍及失效条件。
- `historical`：只可追溯，不可作为当前实现或计划依据。
- `generated`：由代码或测试生成/校验，不允许手工猜测接口。

主计划只记录未完成承诺。完成项迁入 CHANGELOG、ADR 或 decision；过期步骤必须删除，而不是留在“下一步”中。

## 更新与验证

新增或变更公开 CLI、HTTP、MCP 能力时，必须同步更新：

1. 操作文档：用户在什么场景使用它、何时停止或升级。
2. 参考文档：入口、关键参数、输出边界与错误语义。
3. MCP 文档：Agent 应如何调用、性能与证据边界。
4. CHANGELOG：用户可感知的变化。

测试必须校验公开能力在上述文档中可发现；代码、`--help`、路由与 MCP schema 是接口事实的最终来源。

## 架构不可变量

- 默认查询不得扫描全图或隐式触发全量重建。
- `VERIFIED` 必须拥有验证命令、人工确认或可追溯运行结果。
- SQLite `graph.db` 必须单一承载运行时事实；JSON、JSONL、Markdown 导出或人工工件不得静默覆盖运行时状态。
- Adapter 错误必须返回结构化、可行动的诊断，不得诱导无界重试。
- 文档、导出物和审计不得泄露私有源码、原始对话正文或工具载荷。

## Active Docs / 当前主文档

这些文档应优先保持和当前实现一致：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md) — 项目总览、安装、快速开始
- [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md) — 当前系统架构、分层边界、运行模型（含设计决策附录）
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md) — MCP facade、宿主接入、推荐调用顺序
- [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md) — 用户操作路径、CLI/HTTP/MCP 常见工作流
- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md) — 命令、接口、参数、schema 与约束参考
- [CHANGELOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/CHANGELOG.md) — 已发布和未发布变更记录
- [NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md) — 当前唯一活跃的开发路线
- [ONTOLOGY.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ONTOLOGY.md) — 轻量本体：领域实体、关系与演进计划

## Historical Docs / 历史文档

这些文档保留是为了追溯背景、设计演进或执行痕迹，不应再被当成“当前主路线”：

- `docs/archive/ROADMAP.md` — 早期路线图摘要
- `docs/archive/DELEGATED_EXECUTION_PLAN.md` — 阶段性外部协作执行手册
- `docs/archive/DELEGATED_EXECUTION_LOG.md` — 大体量执行日志
- `docs/archive/CBM_INSPIRED_EVOLUTION_PLAN.md` — 基于外部项目参考形成的演进草案
- `docs/archive/TECHNICAL_ARCHITECTURE_AND_EVOLUTION.md` — 已合并入 ARCHITECTURE 附录
- `docs/archive/TECHNICAL_GUIDE.md` — 已合并入 ARCHITECTURE 附录
- `docs/archive/UNIFIED_BACKEND_READ_PATHS.md` — 已合并入 ARCHITECTURE §6
- `docs/archive/DOCS_STATUS.md` — 已合并入本文档
- `docs/archive/PRODUCT_TECHNICAL_OVERVIEW.md` — 已合并入 ARCHITECTURE
- `docs/archive/SPECIAL_NOTES.md` — 设计决策说明，已吸收进 ARCHITECTURE 附录
- `docs/archive/EXTERNAL_ABSORPTION_ISSUES.md` — 外部能力吸收归档
- `docs/archive/RELEASE.md` — 已合并入本文档
- `docs/archive/SPECS.md` — 已合并入 REFERENCE §6
- `docs/archive/ONTOLOGY_EVOLUTION_PLAN.md` — 已合并入 ONTOLOGY Part II
- `docs/archive/DOCS_README.md` — 已合并入根 README

## 更新规则

当实现发生变化时，默认更新顺序：

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/MCP_GUIDE.md`
4. `docs/REFERENCE.md`
5. `docs/CHANGELOG.md`

只有在该变更确实影响开发路线或发布流程时，再更新：

- `docs/NEXT_PHASE_MASTER_PLAN.md`

## Release / 发布清单

### 发布原则

发布时优先保证：MCP facade 兼容性、文档与实现一致、本地安装可用、关键 smoke 可通过。

### 最小发布清单

1. 更新版本号
2. `python3.11 -m compileall memory_center`
3. 关键 smoke：`status`、`work-start`、`mc_analyze` 的 `quick` 与 `full`（确认 `complete` 或可解释的 `partial`）、`mc_admin(action="health")`、Hook 生成
4. README / docs 是否同步
5. 本地安装验证：`pipx reinstall --python "$(command -v python3.11)" memory-center`，再运行 `memory-center --version`

### 对外说明重点

- 这版新增了什么
- 修了哪些真实 bug
- 有哪些行为变更
- 是否需要重新安装 / 重生成 hooks / 重启 MCP

## 推荐阅读顺序

如果你只想快速判断"现在该信哪份文档"，按下面顺序读：

1. [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
2. [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
3. [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
4. [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
5. [CHANGELOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/CHANGELOG.md)
