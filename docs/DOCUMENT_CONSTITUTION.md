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
| 决策 | 为什么这样设计，何时推翻？ | ADR、decisions |
| 历史 | 过去发生过什么？ | archive、CHANGELOG |

同一事实只能有一个权威来源；其他文档必须链接或概述，不能复制出独立版本。

## 生命周期与状态

- `current`：必须与当前发行版一致。
- `decision`：记录仍有效的设计取舍及失效条件。
- `historical`：只可追溯，不可作为当前实现或计划依据。
- `generated`：由代码或测试生成/校验，不允许手工猜测接口。

内部证据不进公开仓库：实施回执、基准取证、研究材料与运行样本保存在维护者内部文档库，公开仓库只保留 CHANGELOG 与 ADR/decisions。公开的历史条目保留当时的版本、样本与结论，不重写成当前状态。当前行为只由 Active Docs、代码、`--help`、路由与 schema 定义。

完成项迁入 CHANGELOG、ADR 或 decision；过期步骤必须删除，而不是留在“下一步”中。

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

- [DOCUMENT_STATUS.md](./DOCUMENT_STATUS.md) — 当前、决策与历史文档的状态目录

- [README.md](../README.md) — 项目总览、安装、快速开始
- [ARCHITECTURE.md](./ARCHITECTURE.md) — 当前系统架构、分层边界、运行模型（含设计决策附录）
- [MCP_GUIDE.md](./MCP_GUIDE.md) — MCP facade、宿主接入、推荐调用顺序
- [USER_GUIDE.md](./USER_GUIDE.md) — 用户操作路径、CLI/HTTP/MCP 常见工作流
- [REFERENCE.md](./REFERENCE.md) — 命令、接口、参数、schema 与约束参考
- [CHANGELOG.md](./CHANGELOG.md) — 已发布和未发布变更记录
- [ADR-0004：服务化平台与管理页](./adr/0004-service-platform-and-admin.md) — 服务化方向与展示面边界的决策入口
- [ONTOLOGY.md](./ONTOLOGY.md) — 轻量本体：领域实体、关系与演进计划

## 更新规则

当实现发生变化时，默认更新顺序：

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/MCP_GUIDE.md`
4. `docs/REFERENCE.md`
5. `docs/CHANGELOG.md`

只有在该变更确实影响决策边界或发布流程时，再更新：

- `docs/adr/`（新增或修订决策）与 `docs/CHANGELOG.md`

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

1. [README.md](../README.md)
2. [ARCHITECTURE.md](./ARCHITECTURE.md)
3. [MCP_GUIDE.md](./MCP_GUIDE.md)
4. [USER_GUIDE.md](./USER_GUIDE.md)
5. [CHANGELOG.md](./CHANGELOG.md)
