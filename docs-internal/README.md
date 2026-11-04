# 内部过程资料 / Internal Process Material

> 本目录**不进入公开发布**。它保存项目开发过程中的路线计划、实施回执、真实工程基准与第三方调研，仅用于项目历史追溯、决策复现和内部参考。
>
> This directory is **not part of the public release**. It keeps process material — roadmaps, implementation receipts, real-workspace benchmarks and third-party research — for project history, decision traceability and internal reference only.

## 1. 边界 / Boundary

- 公开面只保留 `docs/`：`ARCHITECTURE.md`、`MCP_GUIDE.md`、`USER_GUIDE.md`、`REFERENCE.md`、`ONTOLOGY.md`、各 `V5_*` 指南、`adr/`、`decisions/`，以及根 `README.md` 与 `docs/CHANGELOG.md`。
- 本目录内容不随源码包 / wheel / sdist / 文档站发布；打包与发布清单不应包含 `docs-internal/`。
- 两处内容冲突时，**以 `docs/` 与 `docs/CHANGELOG.md` 为准**；本目录不重复维护公开文档正文。
- 本目录文件可能包含真实工程规模、内部系统名、第三方项目评估等内部信息：**禁止整段复制进公开文档、示例、提交信息或对客材料**。
- The public surface is `docs/` only (plus root `README.md` and `docs/CHANGELOG.md`). This directory is excluded from packaging and releases. If the two disagree, `docs/` and `docs/CHANGELOG.md` win.

## 2. 索引 / Index

### 2.1 开发路线与未发布方案 / Roadmaps and unreleased plans

| 文件 | 说明 |
|---|---|
| [NEXT_PHASE_MASTER_PLAN.md](NEXT_PHASE_MASTER_PLAN.md) | 阶段性主开发计划：优先级、执行原则、统一验收门禁与路线图 |
| [DSH_WORKBENCH_PRODUCTIZATION_ROADMAP.md](DSH_WORKBENCH_PRODUCTIZATION_ROADMAP.md) | 工作台产品化路线与迭代划分 |
| [V5_IMPLEMENTATION_PLAN.md](V5_IMPLEMENTATION_PLAN.md) | 5.0 服务化改造流程与全新安装验收方案 |
| [SERVICE_PLATFORM_TECHNICAL_PLAN.md](SERVICE_PLATFORM_TECHNICAL_PLAN.md) | 服务化技术合同、存储边界与开发切片 |
| [FOCUS_TASK_SESSION_FIRST_PROPOSAL.md](FOCUS_TASK_SESSION_FIRST_PROPOSAL.md) | 焦点任务与会话优先的产品提案 |
| [SESSION_FIRST_TASK_CONTINUITY_PROPOSAL.md](SESSION_FIRST_TASK_CONTINUITY_PROPOSAL.md) | Session-first / Task Shadow 架构提案与适配器契约 |

已进入公开面的对应结论：`docs/adr/0004-service-platform-and-admin.md`、`docs/adr/0005-v5-workspace-catalog.md`、`docs/V5_PLATFORM_GUIDE.md`。

### 2.2 第三方调研与吸收方案 / Third-party research and absorption

| 文件 | 说明 |
|---|---|
| [ARCHIFY_ABSORPTION_RESEARCH.md](ARCHIFY_ABSORPTION_RESEARCH.md) | 对 Archify 生成式 Wiki 机制的调研与取舍结论 |
| [WRITE_GOVERNANCE_ABSORPTION_PLAN.md](WRITE_GOVERNANCE_ABSORPTION_PLAN.md) | 写入治理机制对比与吸收工作项 G1–G7 |
| [references/codebase-memory-mcp.md](references/codebase-memory-mcp.md) | 代码索引类参考项目的机制摘录 |

> 这些文件涉及对第三方项目的评估与源码级摘录：**只作内部参考，不对外引用**；若需公开引用，必须补充上游链接、版本与许可证说明，并只保留中性机制描述。
> These notes evaluate and excerpt third-party projects. Keep them internal; any public citation needs upstream URL, version and license, with neutral wording only.

### 2.3 真实工程基准 / Real-workspace benchmarks

| 文件 | 说明 |
|---|---|
| [benchmarks/P0_UCAP_REAL_BENCHMARK.md](benchmarks/P0_UCAP_REAL_BENCHMARK.md) | 索引/检索链路在真实工程上的基线测量 |
| [benchmarks/P1_0_JAVA_PARSING_PROFILE.md](benchmarks/P1_0_JAVA_PARSING_PROFILE.md) | Java 解析热点 profile 与分桶 |
| [benchmarks/P0_5_VECTOR_VALIDATION.md](benchmarks/P0_5_VECTOR_VALIDATION.md) | 向量检索链路验证与召回核对 |
| [benchmarks/P0_INDEX_HOT_PATH_DESIGN.md](benchmarks/P0_INDEX_HOT_PATH_DESIGN.md) | 索引热路径设计与吸收项对照 |
| [benchmarks/V5_PARSE_CACHE_BENCHMARK.md](benchmarks/V5_PARSE_CACHE_BENCHMARK.md) | 解析缓存命中与耗时 |
| [benchmarks/V5_SERVICE_INDEX_STAGE_BASELINE.md](benchmarks/V5_SERVICE_INDEX_STAGE_BASELINE.md) | 服务级索引阶段耗时基线 |
| [benchmarks/V5_EMBEDDING_STAGE_BASELINE.md](benchmarks/V5_EMBEDDING_STAGE_BASELINE.md) | 嵌入阶段耗时与吞吐基线 |

> 基准中的规模与耗时来自真实私有工程，**只有方法论可复用**；要写公开性能说明，请用 `examples/` 或开源工程重测。

### 2.4 交付回执 / Implementation receipts

| 文件 | 说明 |
|---|---|
| [implementation-receipts/V5_S0_SERVICE.md](implementation-receipts/V5_S0_SERVICE.md) | S0 服务骨架与打包验证 |
| [implementation-receipts/V5_S1_CATALOG.md](implementation-receipts/V5_S1_CATALOG.md) | S1 项目目录与管理员边界 |
| [implementation-receipts/V5_LOCAL_ACCESS.md](implementation-receipts/V5_LOCAL_ACCESS.md) | 本机默认访问模式与认证边界 |
| [implementation-receipts/V5_MULTILANGUAGE.md](implementation-receipts/V5_MULTILANGUAGE.md) | 多语言代码图与引用解析范围 |
| [implementation-receipts/V5_PLATFORM.md](implementation-receipts/V5_PLATFORM.md) | 平台切片整体验收记录 |
| [implementation-receipts/V5_PROJECT_STORAGE.md](implementation-receipts/V5_PROJECT_STORAGE.md) | 项目空间统计口径 |
| [implementation-receipts/V5_PROJECT_EMBEDDING.md](implementation-receipts/V5_PROJECT_EMBEDDING.md) | 项目级向量范围与发布校验 |
| [implementation-receipts/V5_STORAGE_GOVERNANCE.md](implementation-receipts/V5_STORAGE_GOVERNANCE.md) | 代际保留、清理预览与真实索引验收 |
| [implementation-receipts/V5_WIKI_DIRECTORIES.md](implementation-receipts/V5_WIKI_DIRECTORIES.md) | 多 Wiki 目录接入 |
| [implementation-receipts/V5_GOVERNANCE_SKILLS.md](implementation-receipts/V5_GOVERNANCE_SKILLS.md) | 知识治理与 Skill 迁移 |
| [implementation-receipts/V5_REFERENCE_ADOPTION.md](implementation-receipts/V5_REFERENCE_ADOPTION.md) | 参考能力吸收与本轮边界 |
| [implementation-receipts/code-graph-foundation.md](implementation-receipts/code-graph-foundation.md) | 代码图谱基础设施验证 |
| [implementation-receipts/graph-db-space-diagnostic.md](implementation-receipts/graph-db-space-diagnostic.md) | 图谱库空间占用诊断 |
| [implementation-receipts/primary-chain-replay.md](implementation-receipts/primary-chain-replay.md) | 主链路 replay 回归 |
| [implementation-receipts/retrieval-replay-calibration.md](implementation-receipts/retrieval-replay-calibration.md) | 检索 replay 校准与失败分类 |
| [implementation-receipts/scoped-refresh-performance.md](implementation-receipts/scoped-refresh-performance.md) | 定向刷新性能与门禁 |

回执体的公开替代物：`docs/CHANGELOG.md`（只记录用户可感知的变化）与 `docs/adr/`（只记录稳定决策）。

### 2.5 真实运行记录 / Real-run records

| 文件 | 说明 |
|---|---|
| [DATA_REAL_LOOP_RUN1.md](DATA_REAL_LOOP_RUN1.md) | 内容闭环在真实工程上的首轮运行记录 |

## 3. 维护约定 / Maintenance

1. 新文档先进 `docs/`；确认属于内部过程资料（路线、回执、真实基准、第三方调研）后再迁入本目录，并在此登记。
2. 迁入时保持相对链接可用：指向公开文档用 `../docs/...`，本目录内部保持同构相对路径（`benchmarks/`、`implementation-receipts/`、`references/`）。
3. 本目录不对**外**承诺路径/文件名稳定；文件可随时归档或删除。
4. 不要把本目录内容复制回公开面；对外表述请引用 `docs/` 中的公开文档。

1. New material lands in `docs/` first; move it here only after it is confirmed to be process material, and register it in this index.
2. Keep relative links working: point at public docs via `../docs/...`, and keep the internal layout (`benchmarks/`, `implementation-receipts/`, `references/`) for links among internal files.
3. No stability promise for external consumers; files may be archived or removed.
4. Never copy this material back to the public surface; cite the public docs in `docs/` instead.

---

*2026-11：本目录建立，33 个内部文档由 `docs/` 迁入（顶层 9、`references/` 1、`benchmarks/` 7、`implementation-receipts/` 16），迁移保留 git 历史。*
*2026-11: this directory was created by moving 33 internal documents out of `docs/` (9 top-level, 1 `references/`, 7 `benchmarks/`, 16 `implementation-receipts/`), preserving git history.*
