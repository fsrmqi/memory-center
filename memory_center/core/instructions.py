from __future__ import annotations

from pathlib import Path

from .store import WorkspaceStore

AGENT_PROTOCOL = """# Memory Center Agent Protocol

本 workspace 使用 Memory Center 作为 AI 编程助手的项目记忆 MCP 服务。

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
   - 查调用方：`mc_lookup(query="符号名", mode="chain", symbol="符号名", chain_direction="callers")`
   - 查被调用方：`mc_lookup(query="符号名", mode="chain", symbol="符号名", chain_direction="callees")`
   - 不确定用哪个：`mc_lookup(query="...", mode="auto")` 让系统自动路由
3. 在写入任何记忆前，先调用 `mc_admin(action="write_judge", text=..., source=..., intent=...)`；需要可执行步骤时，再调用 `mc_admin(action="write_plan", ...)`。
4. 如果任务会持续一段时间，在 `mc_start` 之后用 `mc_sync(intent=..., auto_sync_mode="balanced")` 同步上下文到任务空间。
5. 对于长任务，`mc_start` 已自动启动 session；关键步骤用 `mc_admin(action="session_log", session_id=..., event_type=..., payload=...)` 记录。
6. 修改 Feign、DTO、MQ Message、公共 API 前，调用 `mc_analyze(target=..., depth="full", contract_file=..., change_type=...)`。
7. 修改任何核心文件前，调用 `mc_analyze(target=..., depth="standard", projects=[...], files=[...])` 检查规则。
8. 任务结束后，调用 `mc_close(session_id=..., outcome=..., record_case=True)` 结束并沉淀案例。
9. 完成验证后，`mc_close` 已自动包含 record_case，无需额外操作。
10. `context.md`、`requirement.md`、`design.md`、`plan.md`、`test-plan.md`、`change-log.md`、`current-summary.md` 属于追加保护工件，只允许尾部追加或去重，不允许整篇覆盖。
11. 如果 MCP 不可用，必须明确说明：Memory Center MCP 当前不可用，以下基于本地代码搜索完成。

## 推荐任务链路

1. `mc_start(intent="任务描述")` — 获取 session_id、上下文、风险等级
2. 查找代码：`mc_lookup(query="...", mode="symbol/code/trace/chain")` 按需选 mode
3. `mc_admin(action="write_judge", text="意图", source="sniff_intent", intent="意图")`
4. `mc_admin(action="write_plan", text="意图", source="sniff_intent", intent="意图")`
5. `mc_sync(intent="任务描述", auto_sync_mode="balanced")` — 同步上下文
6. 开发过程中：`mc_admin(action="session_log", session_id="...", event_type="分析", payload="{...}")`
7. 变更前：`mc_analyze(target="文件或符号", depth="standard/full")`
8. 任务完成：`mc_close(session_id="...", outcome="完成描述", record_case=True)`

## 重要说明

- `mc_start` 默认只读 sniff + 自动同步建议 + 启动 session，返回 session_id 供后续使用。
- "找类 / 找方法 / 找 Feign / 找 Topic / 找配置项 / 找调用链" 属于 Memory Center 的强项，优先用 `mc_lookup`，不要一上来就全仓库 grep。
- `mc_admin(action="write_judge")` 负责决定信息应进入 L0 session、L1 case、L2 task space 还是 L3 workspace profile。
- `mc_admin(action="write_plan")` 不直接写入，而是返回执行计划。
- `mc_close` 包含：结束 session + 同步案例到任务空间 + 记录到 cross-service memory，一步到位。
- L3 级别信息优先进入 `workspace_profile`、`team_rules`、`architecture_invariants`、`active_migration_policy` 等核心记忆块。

## Spring Cloud 重点风险

- Feign 契约变更必须做调用方影响分析。
- MQ 消费必须保证幂等、重试、死信或补偿。
- 公共 DTO 不允许破坏性删除字段或改变字段语义。
- ES 写入必须确认 write index，并处理 bulk item 级失败。
- 核心链路日志必须包含 chainId、siteCode、uid、业务主键和阶段码。
- 跨时间分表/索引迁移必须支持重复执行和失败补偿。
"""


def write_agent_instructions(store: WorkspaceStore, workspace_root: str | Path) -> None:
    root = Path(workspace_root).expanduser().resolve()
    targets = [
        root / "AGENTS.md",
        root / "CLAUDE.md",
        root / "GEMINI.md",
        root / ".github" / "copilot-instructions.md",
        root / ".cursor" / "rules" / "memory-center.mdc",
    ]
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        block = managed_block(AGENT_PROTOCOL)
        if "<!-- memory-center:start -->" in current and "<!-- memory-center:end -->" in current:
            start = current.index("<!-- memory-center:start -->")
            end = current.index("<!-- memory-center:end -->") + len("<!-- memory-center:end -->")
            next_text = current[:start] + block + current[end:]
        else:
            next_text = (current.rstrip() + "\n\n" if current.strip() else "") + block
        target.write_text(next_text, encoding="utf-8")


def managed_block(content: str) -> str:
    return f"<!-- memory-center:start -->\n{content.rstrip()}\n<!-- memory-center:end -->\n"
