# MCP Security Model / MCP 安全模型

## 中文

Memory Center 是本地优先的 MCP 服务。默认行为：

1. **只读工具**：`memory_query`、`memory_context`、`memory_impact`、`memory_contracts`、`workspace_sniff` 不修改业务代码。
2. **受限写入**：`workspace_record_case` 写入 `.memory-center/memory/`；`generate-wiki`、`generate-skills` 写入 `.memory-center/wiki` 或用户指定目录。
3. **不执行任意命令**：索引阶段不执行 Maven、Gradle、Shell、npm 等命令。
4. **Git 变更检测只读**：`detect-changes` 只执行 `git diff --name-only`。
5. **默认不联网**：不会把源码发送到外部模型或服务；语义检索需要用户显式安装并配置 provider。

## English

Memory Center is a local-first MCP server. Default behavior:

1. **Read-only tools**: `memory_query`, `memory_context`, `memory_impact`, `memory_contracts`, and `workspace_sniff` do not modify business source code.
2. **Constrained writes**: `workspace_record_case` writes to `.memory-center/memory/`; `generate-wiki` and `generate-skills` write to `.memory-center/wiki` or an explicit user-provided output directory.
3. **No arbitrary command execution**: Indexing does not execute Maven, Gradle, shell scripts, npm, or project code.
4. **Read-only Git detection**: `detect-changes` only runs `git diff --name-only`.
5. **Offline by default**: Source code is not sent to external models or services unless optional semantic providers are explicitly configured.
