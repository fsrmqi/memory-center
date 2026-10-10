# Claude Code Instructions for Memory Center

Memory Center 是面向 AI 编程助手的 MCP 项目记忆服务。

工作要求：

- 修改前先阅读 README 和 docs。
- 保持 CLI / MCP tool schema 稳定。
- 修改索引器、规则、MCP、CLI 时更新测试。
- 面向用户的文档保持中英文双语。
- 不提交真实私有 workspace 生成数据。

## MCP Task-level Tools (15 个任务级工具)

MCP tool surface: 15 task-level tools (mc_start/lookup/analyze/sync/resume/handoff/close/admin + mc_bootstrap_context/provider_action/mcp_bridge/context_pack/onboard/domain/freshness). Do NOT add atomic tools back to MCP — keep task-level facade surface. CLI and HTTP keep fine-grained interfaces unchanged.

**何时用哪个工具 — 自动路由规则：**

| 场景 | 自动调用 | 说明 |
|------|----------|------|
| 用户输入涉及编码/架构/调试 | `mc_start` | SessionStart hook 已自动 sniff；这里主动调用获取 session_id |
| 需要查代码/符号/调用链/契约 | `mc_lookup` | mode="auto" 自动路由到最佳策略 |
| 要修改代码前 | `mc_analyze` | PreToolUse hook 已自动 check-rules；这里主动调用获取影响面 |
| 修改过程中想保存进度 | `mc_sync` | 提供 intent（sniff-sync）或 session_id（case-sync） |
| 回到之前的任务 | `mc_resume` | 提供 intent/task_id/session_id |
| 切换模型或 session | `mc_handoff` | 提供 target_model |
| 任务完成 | `mc_close` | Stop hook 已自动 close；这里主动调用确认 |
| 查状态/工件/评估/生成 | `mc_admin` | action 参数选择子操作 |
| 未初始化 workspace 的项目 | `mc_bootstrap_context` | 零初始化联邦读取，外部结果不持久化 |

**关键行为：**
- 编码任务开始时，先调用 `mc_start` 获取 session_id，存到 `/tmp/memory-center-session-id` 供 Stop hook 使用
- 修改代码前，调用 `mc_analyze` 获取影响面和规则检查
- 任务结束时 Stop hook 自动调用 `mc_close` 关闭 session
- 其他场景用 `mc_lookup` (mode="auto") 自动路由

## Hook Host Integration Layer (宿主集成层)

Hook 是宿主集成方案，不是 memory-center 核心能力。核心能力是记忆/图谱/上下文/工作流，Hook 是"宿主在什么时机自动调哪些能力"。

**架构：**
- `hooks.yaml` — 声明式配置，定义生命周期事件→facade 映射和模式
- `memory-center run-hook` — host-agnostic runner，从 stdin 读 JSON，解析参数，调度到 orchestrator
- `memory-center generate-hooks --host claude-code` — 生成宿主特定配置（Claude Code settings.json）

**4 个标准 Hook 映射：**

| Hook 事件 | Facade | 模式 | 说明 |
|-----------|--------|------|------|
| session_start | mc_start | soft | 不阻塞，只注入上下文 |
| pre_edit | mc_analyze | guard | must-severity 规则匹配时阻塞（exit 2） |
| session_stop | mc_close | soft | 不阻塞，关闭并同步 |
| user_prompt_submit | mc_start | suggest + record_only | 默认只记录脱敏交互，不注入提示、不阻塞 |

**模式说明：**
- soft: 执行但不阻塞主流程（exit 0）
- guard: 风险规则匹配时阻塞（exit 2，Claude Code PreToolUse 会阻止编辑）
- suggest: 只注入提示文本，不执行 shell 命令
- off: 跳过

**CLI 命令：**
```bash
memory-center run-hook --workspace <workspace.yaml> --hook session_start
memory-center generate-hooks --workspace <workspace.yaml> --host claude-code
```

**注意：** `run-hook` 是 CLI-only 入口，不作为 MCP tool。宿主通过 shell 命令调用。MCP 客户端直接调 facade。

Core commands:

```bash
memory-center reindex --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml
memory-center sniff --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml --intent "oldPubTime newPubTime Kafka"
pytest -q
```

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
