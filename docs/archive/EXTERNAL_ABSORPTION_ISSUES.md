# External Absorption Archive / 外部能力吸收归档

本文档不再维护外部项目 issue 草案。已吸收的外部项目思想已经进入当前代码、测试或主文档体系，后续无需继续参考这些外部项目推进开发路线。

例外：`codebase-memory-mcp` 的关键工程设计已单独固化到
[docs/references/codebase-memory-mcp.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/references/codebase-memory-mcp.md)。
后续只引用这份本地参考文档，不继续跟踪外部项目变化。

This document is now an archive. External project ideas that were useful have already been absorbed into Memory Center. Future roadmap decisions should be driven by real user scenarios, benchmarks, gates, and current architecture gaps instead of tracking upstream external projects. The only exception is CBM's fixed local reference document at `docs/references/codebase-memory-mcp.md`.

---

## 已完成吸收 / Completed Absorption

### CodeGraph 类项目

状态：已完成，后续无需继续参考。

已吸收能力：

- Tree-sitter Java parser
- SQLite BM25 / inverted retrieval
- Freshness banner in main query paths
- Watcher-to-incremental-reindex bridge
- Context pack first workflow
- Context pack benchmark
- Workspace daemon feasibility record

### Understand-Anything 类项目

状态：已完成，后续无需继续参考。

已吸收能力：

- Guided tour / onboarding
- Unified explanation schema
- Business domain / business flow
- Flow-aware impact
- Persona-adaptive explanation
- Incremental refresh for understanding assets

### ECC 类项目

状态：已完成，后续无需继续参考。

已吸收能力：

- Workflow protocol profiles
- Verification loop
- Pattern promotion pipeline
- Learned heuristics register
- Agent runtime audit
- Agent usage bundle export

### rtk

状态：已完成，后续无需继续参考。

已吸收能力：

- Token estimate heuristic
- Compact operation gain evaluation
- Discover / command compression style output

### agentmemory

状态：已完成，后续无需继续参考。

已吸收能力：

- Top-K memory ranking
- Token benchmark pattern
- Benchmark baseline / trend thinking

### mattpocock/skills

状态：已完成，后续无需继续参考。

已吸收能力：

- Constraint templates
- Model-side workflow protocol
- Recommended next action shaping

### Candidate Path / 概率树视角

状态：已完成，后续无需继续参考。

已吸收能力：

- Candidate paths
- Recommended path
- Confidence / risk / verification cost
- Low-cost validation first
- Verification feedback into bounded learning weights

---

## 不再继续追踪 / No Longer Tracked

`alibaba/open-code-review` 和 `github/spec-kit` 曾作为治理思想参考，但未作为当前路线的活跃依赖或持续参考源。后续如果出现真实问题需要 deterministic diff scope、constitution、human gates 或 spec traceability，应按 Memory Center 自己的需求、数据模型和 gate 重新立项，而不是继续跟踪外部项目。

---

## 后续原则 / Future Rule

- 不再新增“外部项目吸收 issue 草案”。
- 不复制外部项目命令体系、目录结构或运行时依赖。
- 不把外部项目变化作为 Memory Center 路线输入。
- CBM 后续只通过 `docs/references/codebase-memory-mcp.md` 作为固定参考，不直接跟踪外部项目变化。
- 新功能必须绑定真实场景、benchmark、回归门禁或当前架构缺口。
