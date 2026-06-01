# MCP Guide / MCP 接入指南

## 1. Public Surface / 对外公开面

MCP 默认公开的是 8 个 facade tools：

- `mc_start`
- `mc_lookup`
- `mc_analyze`
- `mc_sync`
- `mc_resume`
- `mc_handoff`
- `mc_close`
- `mc_admin`

设计目标是让模型看到的是“任务级接口”，而不是几十个实现层原子工具。

## 2. Facade Summary / Facade 概览

| Tool | Purpose |
|---|---|
| `mc_start` | 嗅探任务上下文、可选同步、启动 session |
| `mc_lookup` | 统一检索入口：symbol / code / query / trace / chain / context / ref / backend |
| `mc_analyze` | 统一影响分析入口：quick / standard / full |
| `mc_sync` | 将 sniff / case / task 过程同步到工件与记忆 |
| `mc_resume` | 恢复任务上下文 |
| `mc_handoff` | 为其他模型构建交接包 |
| `mc_close` | 会话收尾、同步 case、记录经验 |
| `mc_admin` | 状态、面板、评测、工件、group 等管理入口 |

## 3. Recommended Agent Behavior / 推荐 Agent 行为

推荐顺序：

1. 开始任务：`mc_start`
2. 查信息：`mc_lookup(mode="auto")`
3. 改前检查：`mc_analyze`
4. 长任务同步：`mc_sync`
5. 中断后恢复：`mc_resume`
6. 切换模型：`mc_handoff`
7. 收尾：`mc_close`

## 4. mc_admin Actions / mc_admin 操作列表

`mc_admin` 通过 `action` 参数路由到不同子操作：

### 状态与健康

- `status` — 工作区状态
- `dashboard` — 工作区面板
- `continuity` — 连续性面板
- `health` — 健康检查（状态 + 工具使用 + 回归套件）
- `audit` — 完成审计（文档/测试/实现/设计一致性）
- `backend_consistency` — JSONL 与 SQLite 后端一致性检查

### 钻取导航

- `drill_ref` — 展开 ref，渐进式披露（通过 `ref_path` 参数指定 ref ID）
- `drill_timeline` — 时间线钻取（通过 `session_id` 或 `task_id` 过滤）
- `drill_task` — 任务上下文钻取（通过 `task_id` 参数）

### 评测

- `eval_token_benchmark` — Token 基准测试
- `eval_token_benchmark_trend` — Token 基准趋势报告（回归检测、健康评分）
- `eval_token_gain` — Token 节省评估
- `eval_regression_suite` — 回归套件
- `eval_write_quality` / `eval_resume` / `eval_handoff` — 各维度评测

### 工件与任务

- `artifact_*` — 工件操作
- `task_*` — 任务空间操作
- `session_*` — 会话操作
- `group_*` — 跨工作区组操作

## 5. Hooks / Hook 接入

### 推荐自动执行

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

### 默认不要挂

- `UserPromptSubmit`

原因：普通自然语言请求过于依赖上下文，容易被宿主误处理成拦截步骤。

## 6. Host Strategy / 宿主策略

### Claude Code / Codex

默认建议：

- 生成 `SessionStart / PreToolUse / Stop`
- 不生成 `UserPromptSubmit`

### Cursor

更适合作为规则与工作流提示层，而不是强阻断执行层。

## 7. Security Model / 安全模型

Memory Center 默认是：

- 本地优先
- 读优先
- 不改业务源码

写入范围主要限于：

- `.memory-center/memory`
- `.memory-center/artifacts`
- 生成的 wiki / skills / dashboard

## 8. HTTP Bridge / HTTP 桥接

MCP 之外，还可通过 HTTP bridge 复用同一套能力：

```bash
memory-center serve-http --workspace /abs/path/.memory-center/workspace.yaml --host 127.0.0.1 --port 8765
```

## 9. Related Docs / 相关文档

- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
- [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [SPECIAL_NOTES.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECIAL_NOTES.md)
