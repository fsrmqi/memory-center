from __future__ import annotations

from pathlib import Path

from .store import WorkspaceStore

AGENT_PROTOCOL = """# Memory Center Agent Protocol

本 workspace 使用 Memory Center 作为 AI 编程助手的项目记忆 MCP 服务。

## 必须遵守

1. 任何代码分析、Bug 修复、新功能开发、重构、架构评审任务前，先调用 `workspace_sniff(intent)`。
2. 如果任务会持续一段时间，或者需要多人/多 Agent 共享上下文，在 `workspace_sniff(intent)` 之后立即调用 `workspace_sync_sniff_artifacts(intent, ...)`，把上下文和计划写入任务空间，而不只是停留在查询结果里。
3. 对于长任务，开始时调用 `workspace_start_session(intent)`；关键步骤、关键结论、关键工具结果要持续调用 `workspace_log_session_event(...)` 记录到 session memory。
4. 修改 Feign、DTO、MQ Message、公共 API 前，调用 `workspace_check_contract(contract_file, change_type)`。
5. 修改任何核心文件前，调用 `workspace_check_rules(projects, change_type, files)`。
6. 任务结束后，先调用 `workspace_end_session(session_id, ...)`，再调用 `workspace_sync_case_artifacts(session_id, ...)`，把本次任务结论、设计和变更摘要同步回任务空间。
7. 完成验证后，再调用 `workspace_record_case(task, projects, files, flow, risk_points, verified_by)` 沉淀长期经验。
8. 如果 MCP 不可用，必须明确说明：Memory Center MCP 当前不可用，以下基于本地代码搜索完成。

## 推荐任务链路

1. `workspace_sniff(intent)`
2. `workspace_sync_sniff_artifacts(intent, auto_sync_mode=balanced)`
3. `workspace_start_session(intent)`
4. `workspace_log_session_event(...)` 记录关键分析、影响面、验证结果
5. `workspace_check_contract(...)` / `workspace_check_rules(...)`
6. 完成后：`workspace_end_session(session_id, ...)`
7. `workspace_sync_case_artifacts(session_id, auto_sync_mode=balanced)`
8. `workspace_record_case(...)`

## 重要说明

- `workspace_sniff` 默认只读，只负责查上下文与给出同步建议，不会自动写任务空间。
- `workspace_record_case` 默认只写 `memory/cross-service-task-memory.jsonl`，不会自动更新 `artifacts/tasks/...` 下的 `context.md`、`plan.md`、`design.md`、`change-log.md`。
- 真正把内容写回任务空间的是 `workspace_sync_sniff_artifacts` 和 `workspace_sync_case_artifacts`。
- 如果希望“当前任务上下文”能沉淀到公共空间，必须显式走 sync 链路，而不是只调用 sniff / record-case。

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
