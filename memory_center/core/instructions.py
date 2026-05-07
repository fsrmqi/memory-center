from __future__ import annotations

from pathlib import Path

from .store import WorkspaceStore

AGENT_PROTOCOL = """# Memory Center Agent Protocol

本 workspace 使用 Memory Center 作为 AI 编程助手的项目记忆 MCP 服务。

## 必须遵守

1. 任何代码分析、Bug 修复、新功能开发、重构、架构评审任务前，先调用 `workspace_sniff(intent)`。
2. 修改 Feign、DTO、MQ Message、公共 API 前，调用 `workspace_check_contract(contract_file, change_type)`。
3. 修改任何核心文件前，调用 `workspace_check_rules(projects, change_type, files)`。
4. 任务完成后，调用 `workspace_record_case(task, projects, files, flow, risk_points, verified_by)` 沉淀经验。
5. 如果 MCP 不可用，必须明确说明：Memory Center MCP 当前不可用，以下基于本地代码搜索完成。

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
