# Codex Prompt / Codex 使用提示词

## 中文

```text
你正在维护 Memory Center，这是一个面向 AI 编程助手的 MCP 项目记忆服务。

工作前必须：
1. 阅读 README.md、docs/ARCHITECTURE.md、docs/MCP_TOOLS.md。
2. 如果当前仓库已配置 Memory Center MCP，先调用 workspace_sniff(intent)。
3. 修改 MCP tool、规则、索引器前，说明影响范围。
4. 修改完成后补充测试，并更新中文/英文文档。
5. 不要破坏 CLI 命令：memory-center、memory-center-mcp。

输出要求：
- 说明修改点。
- 说明测试方式。
- 说明兼容性影响。
```

## English

```text
You are working on Memory Center, an MCP-native project memory service for AI coding agents.

Before changes:
1. Read README.md, docs/ARCHITECTURE.md and docs/MCP_TOOLS.md.
2. If Memory Center MCP is configured, call workspace_sniff(intent) first.
3. Explain the impact before changing MCP tools, rules or indexers.
4. Add tests and update bilingual docs.
5. Keep the CLI commands memory-center and memory-center-mcp compatible.
```
