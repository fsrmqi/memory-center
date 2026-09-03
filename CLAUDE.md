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
