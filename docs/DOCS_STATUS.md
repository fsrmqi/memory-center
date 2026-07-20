# Documentation Status / 文档状态说明

本文档用于说明当前哪些文档是**主入口 / 当前维护**，哪些只是**历史记录 / 参考资料**。

This document explains which documents are the **current maintained entrypoints** and which ones are **historical records or reference material**.

---

## Active Docs / 当前主文档

这些文档应优先保持和当前实现一致：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/README.md)
  - `docs/` 目录导航首页，按用途分组。
- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
  - 项目总览、安装、快速开始、主入口说明。
- [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
  - 当前系统架构、分层边界、运行模型。
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
  - MCP facade、宿主接入、推荐调用顺序。
- [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
  - 用户操作路径、CLI/HTTP/MCP 常见工作流。
- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
  - 命令、接口、参数、返回结构参考。
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
  - 公开 schema、workspace 结构、关键约束。
- [CHANGELOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/CHANGELOG.md)
  - 已发布和未发布变更记录。
- [RELEASE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/RELEASE.md)
  - 发布时的最小检查清单。
- [NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md)
  - 当前唯一活跃的开发路线。
- [DOCUMENT_CONSTITUTION.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCUMENT_CONSTITUTION.md)
  - 文档类型、权威来源、生命周期与更新门禁。
- [ONTOLOGY_EVOLUTION_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ONTOLOGY_EVOLUTION_PLAN.md)
  - 需要单独评审的本体演进决策与实施计划。

---

## Historical Docs / 历史文档

这些文档保留是为了追溯背景、设计演进或执行痕迹，不应再被当成“当前主路线”：

- [archive/ROADMAP.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/archive/ROADMAP.md)
  - 早期路线图摘要，存在旧版本号和旧阶段表述。
- [archive/DELEGATED_EXECUTION_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/archive/DELEGATED_EXECUTION_PLAN.md)
  - 阶段性外部协作执行手册，保留背景，不作为当前主计划。
- [archive/DELEGATED_EXECUTION_LOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/archive/DELEGATED_EXECUTION_LOG.md)
  - 大体量执行日志，仅供追溯。
- [archive/CBM_INSPIRED_EVOLUTION_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/archive/CBM_INSPIRED_EVOLUTION_PLAN.md)
  - 基于外部项目参考形成的演进草案，保留为历史设计输入。

---

## Update Rule / 更新规则

当实现发生变化时，默认更新顺序应为：

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/MCP_GUIDE.md`
4. `docs/REFERENCE.md` 或 `docs/SPECS.md`
5. `docs/CHANGELOG.md`
6. `docs/DOCUMENT_CONSTITUTION.md` 规定的公开入口可发现性检查

只有在该变更确实影响开发路线或发布流程时，再更新：

- `docs/NEXT_PHASE_MASTER_PLAN.md`
- `docs/RELEASE.md`

历史文档默认不做同步改写；如果引用它们，应明确说明它们是 historical / archived context。

---

## Current Recommendation / 当前建议

如果你只想快速判断“现在该信哪份文档”，按下面顺序读：

1. [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
2. [docs/README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/README.md)
3. [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
4. [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
5. [CHANGELOG.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/CHANGELOG.md)
