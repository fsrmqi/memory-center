# Memory Center Agent Instructions / 记忆中心 Agent 指令

## 中文

本仓库实现 **Memory Center（记忆中心）**：面向 AI 编程助手的 MCP 项目记忆服务，用于多 Agent 公共空间、项目上下文、跨服务影响分析和经验沉淀。

修改代码前必须遵守：

1. 优先阅读 `README.md`、`docs/ARCHITECTURE.md`、`docs/MCP_TOOLS.md`。
2. 变更 MCP tool schema 时必须保持兼容，若不兼容必须在 README、CHANGELOG、docs 中明确说明。
3. 修改 Spring Cloud 索引器、规则匹配、CLI、MCP Server 时必须补充或更新测试。
4. 所有面向用户的说明尽量保持中英文双语。
5. 不要提交真实私有项目生成的 `.memory-center/index` 或 `.memory-center/memory` 内容。
6. 不要把私有路径、公司内部服务名、真实密钥写进示例。

## English

This repository implements **Memory Center**, an MCP-native project memory service and shared context center for AI coding agents.

Before making broad changes:

1. Read `README.md`, `docs/ARCHITECTURE.md`, and `docs/MCP_TOOLS.md`.
2. Keep MCP tool schemas backward-compatible unless a breaking change is explicitly documented.
3. Add or update tests when changing the Spring Cloud indexer, rule matching, CLI, or MCP server.
4. Keep public-facing documentation bilingual when possible.
5. Do not commit generated `.memory-center/index` or `.memory-center/memory` content from private workspaces.
6. Do not include private paths, internal service names, or secrets in examples.
