# Memory Center Repository Instructions / 记忆中心仓库指令

Memory Center is an MCP-native project memory service for AI coding agents. It provides a shared context space, Spring Cloud workspace indexing, rule checking, and experience memory.

When modifying this repository:

1. Preserve the public CLI commands: `memory-center` and `memory-center-mcp`.
2. Preserve MCP tool compatibility unless the change is intentionally breaking and documented.
3. Update tests for scanner, orchestrator, rule matching, CLI, or MCP behavior changes.
4. Update both Chinese and English documentation for public behavior changes.
5. Keep examples generic and safe. Do not add private company data or secrets.
6. Do not commit generated private `.memory-center/index` or `.memory-center/memory` data.

The project prioritizes:

- MCP-first integration.
- File-based transparent local memory.
- Spring Cloud multi-repository workspaces.
- Cross-service impact analysis.
- Architecture rules and validated experience accumulation.
