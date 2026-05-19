# Architecture / 架构说明

## 中文

Memory Center 的架构目标是为 AI 编程助手提供一个稳定、可解释、可沉淀的项目记忆中心。它由五个核心层组成：

```text
AI Coding Agents
  Codex / Claude Code / Cursor / Copilot / Gemini
        │ MCP stdio/http
        ▼
Memory Center MCP Server
  tools / resources / prompts
        │
        ▼
Context Orchestrator
  intent matching / rule matching / topology retrieval / case retrieval
        │
        ▼
Workspace Store
  index / rules / memory / instructions
        │
        ▼
Spring Cloud Workspace
  gateway / services / common-api / common-core / task / engine
```

### 1. Workspace 层

一个 workspace 代表一个多项目工作区。它可以包含多个 Spring Cloud 服务和公共库，例如：

- gateway
- article-service
- task-service
- risk-engine
- dictionary-service
- common-api
- common-core

### 2. Indexer 层

Indexer 扫描每个服务，生成：

- file-index
- java-symbol-index
- api-index
- feign-index
- mq-index
- config-index
- service-topology

当前版本使用轻量正则解析，适合作为 MVP。后续可以升级到 tree-sitter-java 或 JavaParser。

### 3. Rule Center 层

规则中心保存团队约束，例如：

- MQ 消费必须幂等。
- 公共 DTO 不允许破坏性修改。
- ES bulk 写入必须处理 item 级失败。
- 核心链路日志必须包含 chainId。
- 跨时间分表迁移必须支持重复执行。

### 4. Memory 层

任务完成后，Agent 可以先调用 `workspace_end_session` 与 `workspace_sync_case_artifacts` 把结论同步回任务空间，再调用 `workspace_record_case` 写入长期经验。

经验不是聊天记录，而是可检索的工程事实：

- 任务是什么。
- 涉及哪些项目。
- 修改哪些文件。
- 数据流是什么。
- 风险点是什么。
- 如何验证。

### 5. Agent Protocol 层

Memory Center 会生成 Agent 指令文件：

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `.github/copilot-instructions.md`
- `.cursor/rules/memory-center.mdc`

这些文件要求 Agent 在工作前先调用 Memory Center MCP。

## English

Memory Center is built as a project memory and context orchestration layer for AI coding agents. Its architecture has five layers:

1. **Workspace**: defines all repositories and services in one multi-project system.
2. **Indexer**: extracts files, symbols, APIs, Feign clients, MQ listeners and configuration.
3. **Rule Center**: stores architecture guardrails and risk checklists.
4. **Memory Store**: records solved tasks and reusable engineering cases.
5. **Agent Protocol**: generates instruction files for coding agents.

The design intentionally separates indexing, rule matching and memory recording so that the component can evolve from a lightweight local tool into a shared team service.
