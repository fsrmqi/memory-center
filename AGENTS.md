# Memory Center Agent Instructions / 记忆中心 Agent 指令

## 中文

本仓库实现 **Memory Center（记忆中心）**：面向 AI 编程助手的 MCP 项目记忆服务，用于多 Agent 公共空间、项目上下文、跨语言影响分析和经验沉淀。5.0 起以独立常驻服务（`memory_center.service`）为唯一入口，管理页与统一 MCP 共用同一应用层。

修改代码前必须遵守：

1. 优先阅读 `README.md`、`docs/ARCHITECTURE.md`、`docs/MCP_GUIDE.md`。
2. 变更 MCP tool schema 时必须保持兼容，若不兼容必须在 `README.md`、`docs/CHANGELOG.md` 或 `docs/` 中明确说明。
3. 修改索引器、规则匹配、服务层、CLI 或 MCP Server 时必须补充或更新测试。
4. 所有面向用户的说明尽量保持中英文双语。
5. 不要提交真实私有项目生成的数据（如 `memory_center/service/static/` 构建产物与私有 workspace 的索引/记忆）。
6. 不要把私有路径、公司内部服务名、真实密钥写进示例。

> `CLAUDE.md` 等其它宿主说明文件只保留宿主自动管理的说明块，正文以本文件为准，避免重复维护。

## English

This repository implements **Memory Center**, an MCP-native project memory service and shared context center for AI coding agents. Since 5.0 a single long-running service (`memory_center.service`) is the only entry point; the admin UI and unified MCP share one application layer.

Before making broad changes:

1. Read `README.md`, `docs/ARCHITECTURE.md`, and `docs/MCP_GUIDE.md`.
2. Keep MCP tool schemas backward-compatible unless a breaking change is explicitly documented in `README.md`, `docs/CHANGELOG.md`, or `docs/`.
3. Add or update tests when changing the indexer, rule matching, service layer, CLI, or MCP server.
4. Keep public-facing documentation bilingual when possible.
5. Do not commit generated data from private workspaces (e.g. `memory_center/service/static/` build output, private workspace index/memory).
6. Do not include private paths, internal service names, or secrets in examples.

> `CLAUDE.md` and other host instruction files keep only the host-managed blocks; the canonical text is maintained here to avoid divergent duplicates.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **memory-center** (12932 symbols, 37318 relationships, 809 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/memory-center/context` | Codebase overview, check index freshness |
| `gitnexus://repo/memory-center/clusters` | All functional areas |
| `gitnexus://repo/memory-center/processes` | All execution flows |
| `gitnexus://repo/memory-center/process/{name}` | Step-by-step execution trace |

<!-- gitnexus:end -->

<!-- memory-center:start -->
# Memory Center 5.0 Agent Protocol

本仓库采用独立常驻 Memory Center 5.0 服务；管理页和统一 MCP 共用同一应用层。不要绑定旧 workspace 文件或启动独立 Wiki MCP。当前参数以服务实际 tool schema 为准，参考 `docs/V5_PLATFORM_GUIDE.md`。

1. 开始工程交付前先 `mc_workspaces()` 查看已登记项目，只选择与当前源码目录明确匹配的 `workspace_id`。尚未登记时使用本地 GitNexus 和源码验证，说明服务已配置但本项目未登记；不得借用其它业务项目的会话或记忆。项目接入通过管理页处理。
2. 已匹配的交付任务调用 `mc_start(workspace_id=..., intent=...)`，保存返回的 `id` 作为 session_id；只读了解不自动创建/关闭会话。
3. 工程查询用 `mc_lookup(workspace_id=..., query=..., mode=...)`，mode 为 hybrid/symbol/callers/callees/context。调用关系结果须核对覆盖、新鲜度与来源，空结果不是不存在的证明。
4. 修改前先做本仓库 GitNexus impact；已登记且需要服务影响证据时调用 `mc_analyze(workspace_id=..., target=...)`。不要调用旧 `mc_admin`、`mc_sync`、旧深度/文件参数或旧 ANN 指令。
5. 长任务用 `mc_resume(session_id=...)` 恢复；完成明确交付后 `mc_close(session_id=..., outcome=...)`。不要认领或关闭其他项目的会话。
6. 长期知识由同一服务的 `assistant_knowledge(action="brief"|"search"|"read"|"analyze", ...)` 查询。事实和验证证据优先；冲突应指出 Wiki 可能过期。
7. 知识晋升/资料归档、Skill 创建/发布均先 `confirm=false` 预览，展示后等待对应写入的明确确认。Skill 来源、工件哈希和验证引用应保留；引用不等于自动证明外部内容真实。
8. 管理页“知识治理”和“Skill 管理”可维护受管 Wiki 与候选/发布目录；原 Wiki 只读来源和受管知识分别维护。`assistant_admin(action="scan")` 只报告垃圾，不删除。
9. 普通项目记忆写入用 `mc_memory_write(workspace_id=..., content=..., confirmed=...)`，区分待确认与已确认记录。不要将会话、源码、日志、私有路径或未验证推断直接晋升为长期 Wiki。
10. 宿主配置变更后刷新会话以重新发现工具；已配置但快照未刷新时不要误称服务不可用。MCP 地址默认 `http://127.0.0.1:8765/mcp`；stdio 代理为 `memory-center-mcp`，不带旧 `--workspace`。

English: Use one Memory Center 5.0 service and select only a registered workspace matching the current repository. Never reuse an unrelated project's session. Wiki and Skill governance use the integrated assistant tools; preview and explicit confirmation precede governed writes. Old workspace-bound MCP contracts are retired.
<!-- memory-center:end -->
