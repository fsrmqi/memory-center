# Hook Specification / Hook 规范

## Overview / 概述

Memory Center's Hook layer is a **host integration solution**, not a core capability. It defines which lifecycle events trigger which Memory Center facade calls, with configurable enforcement modes.

Memory Center 的 Hook 层是**宿主集成方案**，不是核心能力。它定义宿主在什么生命周期点自动触发哪些 facade 调用，以及可配置的执行模式。

The architecture separates three concerns:
架构分离三个关注点：

1. **Specification** (`hooks.yaml`): What to trigger and how
   **规范** (`hooks.yaml`)：触发什么、怎么触发
2. **Runner** (`memory-center run-hook`): When to trigger (lifecycle events)
   **Runner** (`memory-center run-hook`)：何时触发（生命周期事件）
3. **Adapters** (`memory-center generate-hooks --host ...`): How to connect to a specific host
   **适配器** (`memory-center generate-hooks --host ...`)：如何连接到特定宿主

## hooks.yaml Schema / hooks.yaml 格式

```yaml
version: "1.0"

hooks:
  <event_name>:                  # session_start, pre_edit, session_stop, user_prompt_submit
    enabled: true|false          # Optional. false disables the hook entirely.
    facade: <facade_name>         # mc_start, mc_lookup, mc_analyze, mc_sync, mc_resume, mc_handoff, mc_close, mc_admin
    mode: <mode>                  # soft, guard, suggest, off
    params:
      <param>_from: <source>      # event, tool_input_file, file, static
      <param>: <static_value>     # Static parameter values
    filter:                       # Optional, for pre_edit
      tool_matcher: "Edit|Write"  # Host tool name filter
      file_patterns: [...]        # Glob patterns for file filtering
    prompt_template: |            # Only for suggest mode
      ... $ARGUMENTS ...
    cleanup: [...]                # Post-hook actions: delete_session_id_file
    timeout: <seconds>
    async: true|false
```

### Modes / 模式

| Mode | Behavior | Use case |
|------|----------|----------|
| `soft` | Execute hook, always return exit 0 (never block host action) | Context injection (sniff, close) |
| `guard` | Execute hook, return exit 2 if high-risk rules match (blocks host action) | Rule-checking before edits |
| `suggest` | Inject prompt text into LLM, no shell command executed | Optional UserPromptSubmit nudges |
| `off` | Skip entirely, return disabled message | Per-workspace override |

| 模式 | 行为 | 用途 |
|------|------|------|
| `soft` | 执行 hook，始终返回 exit 0（不阻塞主流程） | 上下文注入（sniff, close） |
| `guard` | 执行 hook，高风险规则匹配时返回 exit 2（阻塞主流程） | 编辑前规则检查 |
| `suggest` | 注入提示文本到 LLM，不执行 shell 命令 | 可选的 UserPromptSubmit 提醒 |
| `off` | 跳过，返回禁用消息 | 按 workspace 覆盖 |

### Parameter Resolution / 参数解析

`*_from` fields declare where parameter values come from:

| Source | Resolution |
|--------|------------|
| `event` | Parse from stdin JSON (e.g. `stdin_json["prompt"]` for intent) |
| `tool_input_file` | Extract `tool_input.file_path` from PreToolUse stdin |
| `file` | Read from known file path (`/tmp/memory-center-session-id`) |
| `static` | Use literal string value from `params` section |

`*_from` 字段声明参数值来源：

| 来源 | 解析方式 |
|------|----------|
| `event` | 从 stdin JSON 解析（如 `stdin_json["prompt"]` 作为 intent） |
| `tool_input_file` | 从 PreToolUse stdin 提取 `tool_input.file_path` |
| `file` | 从已知文件路径读取（`/tmp/memory-center-session-id`） |
| `static` | 使用 params 中的固定字符串值 |

### Standard Hook Mapping / 标准 Hook 映射

| Event | Facade | Mode | Description |
|-------|--------|------|-------------|
| `session_start` | `mc_start` | soft | Auto-sniff + start session on session begin |
| `pre_edit` | `mc_analyze` | guard | Auto-check rules before Edit/Write; block if must-severity matches |
| `session_stop` | `mc_close` | soft | Auto-close session + sync + record on session end |
| `user_prompt_submit` | `mc_start` | suggest | Disabled by default. Only for hosts where advisory prompt injection will not interrupt ordinary natural-language requests. |

| 事件 | Facade | 模式 | 说明 |
|------|--------|------|------|
| `session_start` | `mc_start` | soft | 会话开始时自动 sniff + 启动 session |
| `pre_edit` | `mc_analyze` | guard | 编辑前自动检查规则；must-severity 匹配时阻塞 |
| `session_stop` | `mc_close` | soft | 会话结束时自动关闭 + 同步 + 记录 |
| `user_prompt_submit` | `mc_start` | suggest | 默认禁用。仅适用于“建议型 prompt 不会打断普通自然语言请求”的宿主。 |

### Recommended Auto-Invocation Matrix / 推荐自动调用矩阵

The key decision rule is: **auto-run only on lifecycle events with stable semantics and clear parameters**. Do not treat ordinary natural-language user prompts as strong hook points.

核心判断原则是：**只在语义稳定、参数明确的生命周期事件上做自动执行**。不要把普通自然语言用户输入当成强 Hook 点。

| Event / 场景 | Recommended level / 推荐级别 | Suggested facade / 建议 facade | Why / 原因 |
|---|---|---|---|
| `SessionStart` | Auto-execute / 自动执行 | `mc_start` | New task/session begin is stable, and loading context does not interrupt normal conversation. / 新任务开始语义稳定，先取上下文不会误伤对话。 |
| `PreToolUse(Edit\|Write)` | Auto-execute / 自动执行 | `mc_analyze` | Target file is known, so rule-check and impact analysis are precise. / 已知目标文件，规则检查与影响分析最精确。 |
| `Stop` / `SessionEnd` | Auto-execute / 自动执行 | `mc_close` | Session-end sync and case recording are deterministic cleanup actions. / 会话结束的同步与经验沉淀属于确定性收尾动作。 |
| `UserPromptSubmit` | Disabled by default / 默认禁用 | None by default / 默认不挂 | Ordinary NL requests like `继续` / `下一步` / `同步下文档` are too context-dependent and are easily turned into host-side interruptions. / `继续`、`下一步`、`同步下文档` 这类输入上下文依赖太强，容易被宿主误处理成拦截。 |

### When to auto-execute vs. when to let the model decide / 什么时候自动执行，什么时候交给模型决定

Recommended split:

推荐拆分方式：

1. **Lifecycle events → auto-execute**
   - `SessionStart -> mc_start`
   - `PreToolUse(Edit|Write) -> mc_analyze`
   - `Stop -> mc_close`

2. **Short follow-up prompts → model decides**
   - `继续`
   - `下一步`
   - `接着`
   - `同步下文档`

   These should be handled by agent protocol / system prompt / workflow rules.
   If current task/session context already exists, the model should prefer `mc_resume`;
   only fall back to `mc_start` when no active context exists.

   这类输入应由 agent protocol / system prompt / workflow 规则处理。
   若当前已有 task/session，上层模型应优先走 `mc_resume`；只有没有活跃上下文时才回退到 `mc_start`。

### Session ID Lifecycle / session_id 生命周期

- `session_start`: Runner writes session_id to `/tmp/memory-center-session-id`
- `session_stop`: Runner reads session_id from that file, then deletes it (cleanup)

- `session_start`: Runner 将 session_id 写入 `/tmp/memory-center-session-id`
- `session_stop`: Runner 从该文件读取 session_id，然后删除（cleanup）

## CLI Commands / CLI 命令

### run-hook

```bash
memory-center run-hook --workspace <workspace.yaml> --hook <event_name>
```

Reads stdin JSON from host, resolves parameters, dispatches to orchestrator, outputs JSON result.

Process exit codes:
- 0: Allow (soft/suggest/off modes)
- 2: Block (guard mode when must-severity rules match)
- 1: Error

从宿主 stdin 读 JSON，解析参数，调度到 orchestrator，输出 JSON 结果。

进程 exit code：
- 0: 允许（soft/suggest/off 模式）
- 2: 阻塞（guard 模式且 must-severity 规则匹配）
- 1: 错误

### generate-hooks

```bash
memory-center generate-hooks --workspace <workspace.yaml> --host claude-code [--output <path>]
memory-center generate-hooks --workspace <workspace.yaml> --host codex [--output <path>]
memory-center generate-hooks --workspace <workspace.yaml> --host cursor [--output <path>]
```

Reads hooks.yaml from workspace, generates host-specific configuration.

从 workspace hooks.yaml 读取，生成宿主特定配置。

### init / reindex

`init` and `reindex` commands automatically write `hooks.yaml` to `.memory-center/hooks.yaml` if it does not already exist (following the same pattern as `rules.yaml`).

`init` 和 `reindex` 命令会在 `.memory-center/hooks.yaml` 不存在时自动写入默认 hooks.yaml（与 rules.yaml 相同模式）。

## Per-Workspace Customization / 按 Workspace 定制

Each workspace can have its own `hooks.yaml` in `.memory-center/hooks.yaml` alongside `workspace.yaml`. This allows:

每个 workspace 可以有自己的 `hooks.yaml`，放在 `.memory-center/hooks.yaml` 与 `workspace.yaml` 同级目录。这允许：

- Different hook strategies per workspace (e.g. guard mode in one, soft in another)
- Setting `mode: off` or `enabled: false` on specific hooks
- Narrowing `pre_edit` filter to only high-risk file patterns
- Changing `budget`, `auto_sync_mode`, etc. per hook

- 不同 workspace 不同 hook 策略（如一个用 guard，一个用 soft）
- 对特定 hook 设置 `mode: off` 或 `enabled: false`
- 缩窄 `pre_edit` 过滤到只高风险文件模式
- 按 hook 修改 `budget`、`auto_sync_mode` 等

## File Location / 文件位置

```
.memory-center/
  workspace.yaml           # Core workspace config
  rules/                   # Architecture rules
    global-rules.yaml
    auto-sync-rules.yaml
    ...
  hooks.yaml               # NEW: Hook integration spec
  artifacts/               # Shared workspace artifacts
  index/                   # Built indexes
  graph/                   # Service topology
  memory/                  # Cross-service memory
```

## Package Structure / 包结构

```
memory_center/hooks/
  __init__.py               # exports load_hooks_config, run_hook
  spec.py                   # hooks.yaml schema, validation, DEFAULT_HOOKS
  runner.py                 # Host-agnostic runner
  adapters/
    __init__.py
    claude_code.py           # Generate settings.json from hooks.yaml
    codex.py                 # Placeholder: shell wrapper scripts
    cursor.py                # Placeholder: .cursorrules additions
  default_hooks.yaml         # Shipped default (written to workspace on init/reindex)
```

The runner calls orchestrator functions **directly** (no subprocess), matching the MCP facade pattern. Adapters only translate format (hooks.yaml → host config). Mode enforcement happens in the runner.

Runner 直接调用 orchestrator 函数（非 subprocess），与 MCP facade 模式一致。适配器只翻译格式（hooks.yaml → 宿主配置）。模式执行在 runner 中。
