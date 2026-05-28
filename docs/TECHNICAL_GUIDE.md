# Technical Guide / 技术说明

## 1. 文档定位

这份文档面向：

- 维护 Memory Center 本身的人
- 需要理解核心实现结构的人
- 想知道“功能落在哪个模块、数据怎么流动、哪些地方该改”的开发者

如果你只是想安装和使用，优先看：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)

## 2. 代码总览

核心包在：

- `memory_center/cli/`
- `memory_center/core/`
- `memory_center/mcp/`
- `memory_center/http/`
- `memory_center/hooks/`

### 2.1 入口层

#### CLI

- 文件：`memory_center/cli/main.py`
- 对外命令：`memory-center`
- 负责：
  - init / reindex / query / impact
  - work-* 工作流
  - hook 生成与执行
  - eval / benchmark / backend query

#### MCP

- 文件：`memory_center/mcp/server.py`
- 对外命令：`memory-center-mcp`
- 负责：
  - 8 个 facade tools
  - resources / prompts
  - `mc_admin` 路由管理

#### HTTP

- 文件：`memory_center/http/server.py`
- 对外命令：`memory-center-http`
- 负责：
  - `/workspace/*` 端点
  - `/ui/*` 本地 workbench

## 3. Core 层模块职责

### 3.1 索引与图谱

- `core/indexer.py`
  - workspace 全量 / 增量索引
  - 文件、symbol、API、Feign、MQ、config、semantic 入口
- `core/indexing/java_regex_parser.py`
  - Java / Spring Cloud 规则解析
- `core/graph.py`
  - graph.db 节点边写入与查询

### 3.2 配置与存储

- `core/config.py`
  - 读取 `workspace.yaml`
- `core/store.py`
  - workspace 目录读写
  - JSON / JSONL / refs
  - `read_json_prefer_backend` / `read_jsonl_prefer_backend`
- `core/memory_backend.py`
  - SQLite `memory.db`
  - 镜像写入与统一后端查询

### 3.3 规则与协议

- `core/rules.py`
  - 默认规则
  - YAML 规则读取
  - 匹配逻辑
- `core/schemas.py`
  - 稳定返回 schema
- `core/write_receipts.py`
  - 写入回执

### 3.4 编排器

现在编排器已经拆分到：

- `core/orchestrator/common.py`
- `core/orchestrator/compact.py`
- `core/orchestrator/query.py`
- `core/orchestrator/impact.py`
- `core/orchestrator/session.py`
- `core/orchestrator/resume.py`
- `core/orchestrator/sync.py`
- `core/orchestrator/workspace.py`
- `core/orchestrator/write.py`
- `core/orchestrator/group.py`
- `core/orchestrator/eval.py`

这是当前系统最核心的一层。

#### 主要职责拆分

- `common.py`
  - load/store 上下文
  - budget/profile
  - ref 解析
  - payload compact / offload
- `compact.py`
  - compact/full 输出裁剪
  - dashboard / sniff / handoff / resume 压缩层
- `query.py`
  - `memory_query`
  - `memory_ref_get / batch`
- `impact.py`
  - `memory_impact`
  - `memory_plan_change`
  - `memory_verify_checklist`
- `session.py`
  - session 开始 / 记录 / 结束
  - recent evidence
  - top-K evidence compact
- `resume.py`
  - `workspace_resume_packet`
  - `workspace_handoff_packet`
- `sync.py`
  - sync sniff / sync case
- `workspace.py`
  - `workspace_status`
  - `workspace_sniff`
  - `workspace_dashboard`
- `write.py`
  - write judge / plan / execute
- `group.py`
  - registry/group 聚合
- `eval.py`
  - quality eval
  - token gain / token benchmark

### 3.5 辅助层

- `core/timeline.py`
  - session_event / write_receipt / handoff 统一时间线
- `core/tracking.py`
  - token gain 日志
- `core/token_utils.py`
  - token 估算与节省统计
- `core/exporters.py`
  - HTML / Markdown / UI 片段渲染
- `core/wiki.py`
  - wiki / skills 生成
- `core/instructions.py`
  - AGENT / CLAUDE / GEMINI 指令文件生成

## 4. 当前系统的几条主链路

### 4.1 索引链路

1. `workspace.yaml`
2. `reindex_workspace(...)`
3. index JSON 产物
4. `graph.db`
5. semantic index
6. instructions / hooks / default rules

### 4.2 任务上下文链路

1. `workspace_sniff(...)`
2. `lookup_hint`
3. `resolved_task`
4. `auto_sync_recommendation`
5. `mc_start`

### 4.3 连续性链路

1. session events
2. write receipts
3. recent evidence
4. resume packet
5. handoff packet
6. continuity / dashboard

### 4.4 写入治理链路

1. `memory_write_judge`
2. `memory_plan_write`
3. `memory_execute_write`
4. write receipt
5. artifact write audit

### 4.5 统一后端链路

1. JSONL / Markdown 继续落盘
2. 关键记录镜像到 `memory.db`
3. 高频读路径优先走 backend
4. fallback 到 JSON/JSONL

## 5. 当前最重要的设计取舍

### 5.1 MCP 面收敛为 facade

现在默认不把实现层几十个工具直接暴露给模型，而是暴露 8 个任务级 facade。

原因：

- 降低 token
- 降低工具选择成本
- 保持任务级语义稳定

### 5.2 轻量上下文优先

不是所有返回都直接把完整结构喂给模型，而是：

- `view=compact|full`
- `budget=small|medium|large`
- short refs
- top-K evidence

### 5.3 SQLite 不是唯一真相源

当前仍然保留：

- JSON
- JSONL
- Markdown

SQLite `memory.db` 负责：

- 镜像
- 高频查询优先
- 观察与聚合

这是渐进统一，而不是一步替换。

### 5.4 Hook 是宿主集成，不是核心业务

Hook 的价值在于自动触发关键生命周期动作，但不应该过度侵入自然语言入口。

当前推荐：

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

默认不推荐：

- `UserPromptSubmit`

## 6. 当前最值得关注的实现热点

如果后面继续优化，最容易碰到的热点是：

- `core/indexer.py`
- `core/orchestrator/*`
- `core/store.py`
- `core/memory_backend.py`
- `mcp/server.py`
- `http/server.py`
- `hooks/*`

## 7. 推荐阅读顺序

如果你是第一次接手这个项目，建议顺序：

1. [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
2. [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
3. 本文档
4. [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
5. [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
6. [docs/NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md)
