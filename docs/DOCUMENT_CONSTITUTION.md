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
| 对外介绍 | 价值、能力边界和技术路线如何被非维护者理解？ | PRODUCT_TECHNICAL_OVERVIEW、README、ARCHITECTURE |
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
- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md) — 命令、接口、参数、返回结构参考
- [PRODUCT_TECHNICAL_OVERVIEW.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/PRODUCT_TECHNICAL_OVERVIEW.md) — 对外产品技术介绍
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md) — 公开 schema、workspace 结构、关键约束
- [CHANGELOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/CHANGELOG.md) — 已发布和未发布变更记录
- [NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md) — 当前唯一活跃的开发路线
- [RELEASE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/RELEASE.md) — 发布时的最小检查清单
- [ONTOLOGY_EVOLUTION_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ONTOLOGY_EVOLUTION_PLAN.md) — 本体演进决策与实施计划

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

## 更新规则

当实现发生变化时，默认更新顺序：

1. `README.md`
2. `docs/PRODUCT_TECHNICAL_OVERVIEW.md`（影响产品定位、技术边界或对外能力时）
3. `docs/ARCHITECTURE.md`
4. `docs/MCP_GUIDE.md`
5. `docs/REFERENCE.md` 或 `docs/SPECS.md`
6. `docs/CHANGELOG.md`

只有在该变更确实影响开发路线或发布流程时，再更新：

- `docs/NEXT_PHASE_MASTER_PLAN.md`
- `docs/RELEASE.md`

## 推荐阅读顺序

如果你只想快速判断“现在该信哪份文档”，按下面顺序读：

1. [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
2. [PRODUCT_TECHNICAL_OVERVIEW.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/PRODUCT_TECHNICAL_OVERVIEW.md)
3. [docs/README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/README.md)
4. [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
5. [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
6. [CHANGELOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/CHANGELOG.md)
