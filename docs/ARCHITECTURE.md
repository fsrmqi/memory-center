# Architecture / 架构说明

## Overview / 总览

Memory Center 是一个面向 AI 编程助手的本地优先项目记忆系统，核心目标是把“代码索引、跨服务关系、任务上下文、经验沉淀、模型交接”收敛到同一个工作区里。

Memory Center is a local-first project memory system for coding agents. It unifies indexing, cross-service relationships, task context, experience memory, and model handoff into one workspace.

系统入口统一为三类：

- `memory-center`：CLI
- `memory-center-mcp`：MCP facade tools
- `memory-center-http`：本地 HTTP bridge / workbench

## Core Model / 核心模型

### 1. Workspace / 工作区

每个 workspace 对应一个 `.memory-center/workspace.yaml`，定义：

- root 路径
- 服务列表
- 索引输出目录
- graph / memory / artifacts 存储位置
- 可选的嵌入与 registry 配置

### 2. Indexing / 索引层

索引层负责从代码仓库中提取：

- 文件索引
- Java symbol 索引
- API / Controller 索引
- OpenFeign 索引
- MQ / Topic 索引
- 配置索引
- 语义索引

针对 Spring Cloud / Spring Boot 多模块项目，系统会额外识别：

- Feign 客户端与下游 endpoint 的关系
- DTO / 公共契约位置
- MQ producer / consumer
- 配置与跨服务调用线索

### 3. Graph / 图谱层

索引结果会转换为节点与边，落到本地 SQLite graph store 中，用于：

- 图感知查询
- 调用链追踪
- 影响面分析
- 上下文拼装

图谱是 Memory Center 的结构化骨架；语义检索与规则系统都围绕它补强，而不是替代它。

### 4. Memory / 记忆层

记忆按层组织：

- `L0_session_events`：会话事件与过程证据
- `L1_case_atoms`：经验原子 / case
- `L2_task_spaces`：任务空间与协作工件
- `L3_workspace_profile`：工作区长期规则与画像

会话事件、写入回执、handoff、refs 元数据会镜像进入 SQLite `memory.db`，同时继续保留 JSONL / Markdown 作为可读、可追踪的落盘形式。

### 5. Workflow / 工作流层

对模型暴露的是任务级 facade，而不是大量原子工具：

- `mc_start`
- `mc_lookup`
- `mc_analyze`
- `mc_sync`
- `mc_resume`
- `mc_handoff`
- `mc_close`
- `mc_admin`

CLI / HTTP 仍保留细粒度原子操作，但 MCP 默认以 facade 为公开面，降低模型选择成本与 token 开销。

## Data Flow / 数据流

典型链路如下：

1. `reindex` 构建索引、graph、semantic 数据
2. `mc_start` 或 `workspace_sniff` 获取当前任务上下文
3. `mc_lookup` / `mc_analyze` 做检索、影响分析、规则检查
4. `work-*` 或 `mc_sync` 将过程同步到 task space / memory
5. `mc_resume` / `mc_handoff` 为恢复或跨模型交接提供轻量上下文
6. `mc_close` 做会话收尾、case 同步与经验沉淀

## Token Strategy / Token 策略

系统默认按“轻量优先、细节按需展开”设计：

- `view=compact|full`
- `budget=small|medium|large`
- short refs：`ref_id + summary`
- `memory_ref_get / memory_ref_batch` 按需展开
- top-K evidence 策略
- token gain / token benchmark 评测

## Unified Backend / 统一后端

`memory.db` 当前承担的是“镜像 + 高频读路径优先查询”的角色，而不是唯一事实源。

当前已经优先走 SQLite / backend 的典型高频路径包括：

- timeline
- recent sessions / session summary
- write receipts
- 部分 query / resume / dashboard / eval 相关读取

其余路径仍允许 fallback 到 JSONL / Markdown，这样可以兼顾稳定性和渐进演进。

## Hooks / 宿主 Hook

Hook 层属于宿主集成，不是核心业务层。推荐自动执行的只有三类生命周期事件：

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

`UserPromptSubmit` 默认不建议作为宿主 Hook 开启，因为它容易打断普通自然语言操作。

## Recommended Reading / 推荐阅读

- [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [ROADMAP.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ROADMAP.md)
