# Memory Center Agent Instructions / 记忆中心 Agent 指令

## 中文

本仓库实现 **Memory Center（记忆中心）**：面向 AI 编程助手的 MCP 项目记忆服务，用于多 Agent 公共空间、项目上下文、跨服务影响分析和经验沉淀。

修改代码前必须遵守：

1. 优先阅读 `README.md`、`docs/ARCHITECTURE.md`、`docs/MCP_GUIDE.md`。
2. 变更 MCP tool schema 时必须保持兼容，若不兼容必须在 README、CHANGELOG、docs 中明确说明。
3. 修改 Spring Cloud 索引器、规则匹配、CLI、MCP Server 时必须补充或更新测试。
4. 所有面向用户的说明尽量保持中英文双语。
5. 不要提交真实私有项目生成的 `.memory-center/index` 或 `.memory-center/memory` 内容。
6. 不要把私有路径、公司内部服务名、真实密钥写进示例。

## English

This repository implements **Memory Center**, an MCP-native project memory service and shared context center for AI coding agents.

Before making broad changes:

1. Read `README.md`, `docs/ARCHITECTURE.md`, and `docs/MCP_GUIDE.md`.
2. Keep MCP tool schemas backward-compatible unless a breaking change is explicitly documented.
3. Add or update tests when changing the Spring Cloud indexer, rule matching, CLI, or MCP server.
4. Keep public-facing documentation bilingual when possible.
5. Do not commit generated `.memory-center/index` or `.memory-center/memory` content from private workspaces.
6. Do not include private paths, internal service names, or secrets in examples.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **memory-center** (11099 symbols, 26098 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/memory-center/context` | Codebase overview, check index freshness |
| `gitnexus://repo/memory-center/clusters` | All functional areas |
| `gitnexus://repo/memory-center/processes` | All execution flows |
| `gitnexus://repo/memory-center/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

<!-- memory-center:start -->
# Memory Center Agent Protocol

本 workspace 使用 Memory Center 作为 AI 编程助手的项目记忆 MCP 服务。

- 当前宿主绑定的 Memory Center workspace：`/Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml`
- 本仓库（memory-center）没有自己的 `.memory-center/workspace.yaml`；在这里执行任务时，记忆读写命中上面这个 workspace，不要假设存在仓库级 workspace。
- Bound Memory Center workspace for this host: `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml`
- This repository has no `.memory-center/workspace.yaml` of its own. Tasks performed here read and write the bound workspace above; do not assume a repo-local workspace exists.

## MCP 工具速查

| 工具 | 用途 |
|------|------|
| `mc_start` | 开始任务：sniff 上下文 + 同步任务空间 + 启动 session |
| `mc_lookup` | 统一查询（mode 控制策略：auto/symbol/code/query/trace/chain/context/contracts/ref） |
| `mc_analyze` | 变更影响分析（depth: quick/standard/full） |
| `mc_sync` | 同步上下文到任务空间（intent=sniff-sync, session_id=case-sync） |
| `mc_resume` | 恢复任务：汇总上下文、下一步动作、未解决问题 |
| `mc_handoff` | 构建跨模型/session 的交接包 |
| `mc_close` | 关闭任务：结束 session + 同步 + 记录案例 |
| `mc_admin` | 管理操作（action 子命令：status, session_log, write_judge, write_plan 等） |

## 必须遵守

1. 任何编码/架构/调试任务开始时，先调用 `mc_start(intent=...)` 获取 session_id。
2. 如果用户要"找类 / 找方法 / 找 Feign / 找 Topic / 找配置项 / 找调用链"，用 `mc_lookup`：
   - 找符号：`mc_lookup(query="类名或方法名", mode="symbol")`
   - 搜代码：`mc_lookup(query="关键词", mode="code")`
   - 跨服务追踪：`mc_lookup(query="入口类", mode="trace", entry="类名或Feign名")`
   - 查调用方：`mc_lookup(mode="chain", query="符号名", symbol="符号名", chain_direction="callers")`
   - 查被调用方：`mc_lookup(mode="chain", query="符号名", symbol="符号名", chain_direction="callees")`
   - 中文意图可放 `query` 或说明文本，但 `symbol` 必须是待验证的类/方法标识（硬锚），否则查询可能锚定到不相关符号。
   - chain/trace 返回的锚点与请求符号不符（`chain_anchor_validation.status != "matched"`）、`chain_summary` 为空、或 `claim_boundary.negative_claim_allowed=false` 时，视为查询失败或范围不足。立即回退到 `mc_lookup(mode="symbol")`、`mc_lookup(mode="code")` 或有界文件搜索；禁止把空结果当作"确认不存在调用方"。
   - 不确定用哪个：`mc_lookup(query="...", mode="auto")` 让系统自动路由
3. 在写入任何记忆前，先调用 `mc_admin(action="write_judge", text=..., source=..., intent=...)`；需要可执行步骤时，再调用 `mc_admin(action="write_plan", ...)`。
4. 如果任务会持续一段时间，在 `mc_start` 之后用 `mc_sync(intent=..., auto_sync_mode="balanced")` 同步上下文到任务空间。
5. 对于长任务，`mc_start` 已自动启动 session；关键步骤用 `mc_admin(action="session_log", session_id=..., event_type=..., payload=...)` 记录。
6. 修改 Feign、DTO、MQ Message、公共 API 前，调用 `mc_analyze(target=..., depth="full", contract_file=..., change_type=...)`。
7. 修改任何核心文件前，调用 `mc_analyze(target=..., depth="standard", projects=[...], files=[...])` 检查规则。
8. 任务结束后，调用 `mc_close(session_id=..., outcome=..., record_case=True)` 结束并沉淀案例。
9. 完成验证后，`mc_close` 已自动包含 record_case，无需额外操作。
10. `context.md`、`requirement.md`、`design.md`、`plan.md`、`test-plan.md`、`change-log.md`、`current-summary.md` 属于追加保护工件，只允许尾部追加或去重，不允许整篇覆盖。
11. 首轮工具列表没有 `mc_*` 不等于 Memory Center 不可用。先执行延迟工具发现并查找 `mcp__memory_center__mc_freshness`；发现后调用一次 `mc_freshness(scope="workspace")` 完成端到端验证。
12. 延迟发现后仍缺少工具时，先检查宿主绑定：Codex 使用 `codex mcp get memory-center`，其他宿主检查对应 MCP 配置。若配置存在且 enabled，状态应表达为“Memory Center 已配置，当前宿主工具快照尚未刷新”，提示刷新或新建会话，禁止表述为“未加载”或“不可用”。
13. 只有绑定不存在、命令不存在，或 MCP initialize / 轻量调用明确失败时，才说明：`Memory Center MCP 当前不可用，以下基于本地代码搜索完成。` 若当前目录是子项目，先运行 `memory-center runtime-audit --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml --fix` 修复绑定。
14. 当 `mc_lookup` 的 `agent_next_steps` 返回 `rebuild_vector_ann` 时，必须依次调用 `mc_admin(action="vector_ann_rebuild")` 和 `mc_admin(action="vector_ann_tune")`，再重试原查询；不得对大型向量库使用 Python 全量扫描。
15. 对概念型、中文需求与代码混合查询，优先调用 `mc_admin(action="advanced_query", text="原查询")`，它会启用 ANN 和有界 Cross-Encoder 重排；重排器只使用当前 MCP 进程已预热模型，返回 `reranker_not_prewarmed` 时保留基础排序，不得在请求链路加载或下载模型。只有用户明确同意时，管理员才可在当前 MCP 进程调用 `mc_admin(action="retrieval_reranker_prewarm")`；普通符号查找仍使用 `mc_lookup`。
16. `mc_admin(action="retrieval_model_profile", text="multilingual", force=true)` 会选择 BGE-M3 档案，但随后必须显式完整 reindex；Agent 不得自行切换模型档案或触发全量 reindex，除非用户明确要求。
17. 定期调用 `mc_admin(action="eval_retrieval_replay")` 检查带 evidence 的人工验证样本；只有返回 `ready` 才可使用 `force=true` 应用融合权重提案。
18. 代码审查、提交前检查或用户要求“看下变更影响”时，优先调用 `mc_admin(action="change_review", scope="all", view="minimal")`。它会定向刷新相关文件并一次返回加权影响链、契约风险、测试缺口和验证 Action；不要手工重复串联全局搜索。
19. 遵守 `invocation_budget`：默认按 `minimal -> standard -> deep` 渐进展开；只有 `knowledge_state` 证据不足、结果被截断或用户明确要求时才升级。达到 `stop_condition`、预算耗尽或出现 `user_confirmation_required` 后必须停止工具调用。
20. 相同 `fingerprint` 和 generation 的审查结果视为等价证据；短时间内不得重复调用 `lookup/analyze/change_review/provider` 获取同一范围。需要重试时必须先有 generation 变化、范围变化或新的验证证据。

## 推荐任务链路

1. `mc_start(intent="任务描述")` — 获取 session_id、上下文、风险等级
2. 查找代码：`mc_lookup(query="...", mode="symbol/code/trace/chain")` 按需选 mode
3. `mc_admin(action="write_judge", text="意图", source="sniff_intent", intent="意图")`
4. `mc_admin(action="write_plan", text="意图", source="sniff_intent", intent="意图")`
5. `mc_sync(intent="任务描述", auto_sync_mode="balanced")` — 同步上下文
6. 开发过程中：`mc_admin(action="session_log", session_id="...", event_type="分析", payload="{...}")`
7. 变更前：`mc_analyze(target="文件或符号", depth="standard/full")`
8. 提交或审查前：`mc_admin(action="change_review", scope="all", view="minimal")`
9. 任务完成：`mc_close(session_id="...", outcome="完成描述", record_case=True)`

## 重要说明

- `mc_start` 默认只读 sniff + 自动同步建议 + 启动 session，返回 session_id 供后续使用。
- "找类 / 找方法 / 找 Feign / 找 Topic / 找配置项 / 找调用链" 属于 Memory Center 的强项，优先用 `mc_lookup`，不要一上来就全仓库 grep。
- `mc_admin(action="write_judge")` 负责决定信息应进入 L0 session、L1 case、L2 task space 还是 L3 workspace profile。
- `mc_admin(action="write_plan")` 不直接写入，而是返回执行计划。
- `mc_close` 包含：结束 session + 同步案例到任务空间 + 记录到 cross-service memory，一步到位。
- L3 级别信息优先进入 `workspace_profile`、`team_rules`、`architecture_invariants`、`active_migration_policy` 等核心记忆块。
- 若首轮看不到 `mc_*` 工具，先做延迟工具发现；配置已启用但工具仍不可见时刷新宿主会话。只有绑定缺失时才运行 `memory-center runtime-audit --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml --fix`，避免把工具快照延迟误诊为服务不可用。
- `vector_ann_status`、`vector_ann_rebuild`、`vector_ann_tune`、`advanced_query`、`retrieval_reranker_status`、`retrieval_reranker_prewarm`、`retrieval_model_profile` 和 `eval_retrieval_replay` 都通过 `mc_admin(action=...)` 调用；先遵守返回的 stop_condition 和 next_action，再进入宽泛搜索。
- `change_review` 是变更审查默认入口；同一 fingerprint 命中缓存时直接复用，不再追加等价搜索。`eval_cochange` 是显式离线 walk-forward 评测，不得放入普通查询链路；只有 `calibration.eligible=true` 时才允许用户通过 CLI `--apply` 或 MCP `force=true` 写入哈希先验。

## Spring Cloud 重点风险

- Feign 契约变更必须做调用方影响分析。
- MQ 消费必须保证幂等、重试、死信或补偿。
- 公共 DTO 不允许破坏性删除字段或改变字段语义。
- ES 写入必须确认 write index，并处理 bulk item 级失败。
- 核心链路日志必须包含 chainId、siteCode、uid、业务主键和阶段码。
- 跨时间分表/索引迁移必须支持重复执行和失败补偿。
<!-- memory-center:end -->
