# MCP Tools / MCP 工具说明

Memory Center exposes graph-first project memory to AI coding agents through MCP, using 8 task-level facade tools instead of 82 atomic tools.

记忆中心通过 MCP 把图优先项目记忆暴露给 AI 编程助手，使用 8 个任务级 facade 工具替代原先的 82 个原子工具。

## Facade Tools / 任务级工具

| Tool | Description / 说明 |
|---|---|
| `mc_start(intent, limit, auto_sync_mode, sync_task_space, budget)` | Start a new task workflow: sniff workspace context → sync to task space → start session. Returns consolidated context with services, files, rules, risk level, session_id, and task_id. / 开始任务工作流：sniff 工作区上下文 → 同步到任务空间 → 启动会话。返回整合的上下文，含服务、文件、规则、风险等级、session_id、task_id。 |
| `mc_lookup(query, mode, intent, name, scope, symbol, chain_direction, depth, entry, ref_id, ref_ids, limit)` | Unified knowledge lookup. Mode selects strategy: auto (system decides), symbol (resolve name), code (keyword search), query (graph-aware), trace (cross-service), chain (caller/callee), context (360-degree), contracts (list all), ref (resolve IDs), backend (query SQLite). / 统一知识检索。mode 选择策略：auto（系统决策）、symbol（解析名称）、code（关键词）、query（图检索）、trace（跨服务）、chain（调用链）、context（全景）、contracts（列出契约）、ref（展开引用）、backend（查 SQLite）。 |
| `mc_analyze(target, depth, direction, max_depth, contract_file, change_type, projects, files, scope)` | Analyze change impact. Depth quick: impact only. Depth standard: impact + change plan + rules check. Depth full: standard + contract check + verification checklist. If target is empty, runs detect-changes instead. / 变更影响面分析。depth quick：仅影响面。depth standard：影响面+改动计划+规则检查。depth full：standard+契约检查+验证清单。target 为空时运行 detect-changes。 |
| `mc_sync(intent, session_id, task_id, title, limit, auto_sync_mode)` | Sync task context to workspace artifacts. Provide intent for sniff-sync, or session_id for case-sync. session_id takes precedence. / 同步任务上下文到工件。intent → sniff-sync，session_id → case-sync，session_id 优先。 |
| `mc_resume(intent, task_id, session_id, limit, budget)` | Resume a task with consolidated context. Returns resume packet, next actions, unresolved items, and recent evidence. / 恢复任务上下文。返回恢复包、下一步、未解决项和近期证据。 |
| `mc_handoff(target_model, task_id, session_id, intent, limit, budget)` | Build a handoff package for another model or session. Returns handoff packet, recent evidence, and tool usage report. / 为目标模型生成交接包。返回交接包、近期证据和工具使用报告。 |
| `mc_close(session_id, outcome, task_id, title, auto_sync_mode, record_case, verified_by)` | Close a task workflow: end session → sync case → suggest case → optionally record case to cross-service memory. / 关闭任务工作流：结束会话→同步 case→建议 case→可选沉淀长期记忆。 |
| `mc_admin(action, ...)` | Admin and utility router. Action selects sub-operation: status, dashboard, continuity, health, artifact_list/get/outline/context/update, change_log_append/compact, task_create/list/resolve/get/update/change_log_append/archive/auto_archive/status/activity_touch, session_start/log/end/recent/summary, model_profile, handoff_history, write_judge/plan/execute, receipts, replay, backend_query, eval_write_quality/resume/handoff/regression_suite/index_freshness/tool_adoption/context_weight/workflow_orchestration/token_gain, tool_usage_report, generate_wiki/skills, group_status/query/impact. / 管理和工具路由。action 选择子操作。 |

## Why 8 facade tools? / 为什么是 8 个 facade 工具？

The previous 82 atomic tools caused "choice paralysis" for AI models — too many similar options with unclear trigger semantics, consuming ~28k+ tokens of context but rarely being called. The 8 facade tools consolidate atomic operations into task-level workflows, reducing token cost by ~85% and making the tool surface "task-oriented" instead of "implementation-oriented".

原先的 82 个原子工具导致 AI 模型"选择瘫痪"——太多相似选项，触发语义不清，消耗 ~28k+ token 上下文但几乎不被调用。8 个 facade 工具将原子操作合并为任务级工作流，token 开销减少约 85%，工具面从"实现层接口"变成"任务层接口"。

## Internal routing / 内部路由

Each facade internally dispatches to the same orchestrator functions that the old 82 tools called. The underlying Python functions remain accessible to CLI, HTTP server, and internal callers. Only the MCP tool surface changed.

每个 facade 内部路由到与旧 82 个工具相同的 orchestrator 函数。底层 Python 函数仍可被 CLI、HTTP 服务器和内部调用者访问。只有 MCP 工具面变了。

### mc_lookup mode routing / mc_lookup mode 路由

| mode | Internal function / 内部函数 |
|---|---|
| auto | workspace_lookup_hint → dispatch to best tool / workspace_lookup_hint → 路由到最佳工具 |
| symbol | memory_symbol / 符号解析 |
| code | memory_search_code / 关键词搜索 |
| query | memory_query / 图检索 |
| trace | workspace_trace / 跨服务追踪 |
| chain | memory_callers / memory_callees (chain_direction selects) / 调用链分析 |
| context | memory_context / 全景上下文 |
| contracts | memory_contracts / 列出契约 |
| ref | memory_ref_get / memory_ref_batch / 引用展开 |
| backend | memory_backend_query / SQLite 查询 |

### mc_analyze depth routing / mc_analyze depth 路由

| depth | Steps / 执行步骤 |
|---|---|
| quick | memory_impact OR memory_detect_changes / 仅影响面 |
| standard | quick + memory_plan_change + workspace_check_rules / quick + 改动计划 + 规则检查 |
| full | standard + workspace_check_contract + memory_verify_checklist / standard + 契约检查 + 验证清单 |

### mc_admin action list / mc_admin action 列表

status, dashboard, continuity, health, artifact_list, artifact_get, artifact_outline, artifact_context, artifact_update, change_log_append, change_log_compact, task_create, task_list, task_resolve, task_get, task_update, task_change_log_append, task_archive, task_auto_archive, task_status, task_activity_touch, session_start, session_log, session_end, session_recent, session_summary, model_profile, handoff_history, write_judge, write_plan, write_execute, receipts, replay, backend_query, eval_write_quality, eval_resume, eval_handoff, eval_regression_suite, eval_index_freshness, eval_tool_adoption, eval_context_weight, eval_workflow_orchestration, eval_token_gain, tool_usage_report, generate_wiki, generate_skills, group_status, group_query, group_impact

## Resources / 资源

- `memory-center://status`
- `memory-center://contracts`
- `memory-center://topology`

## Prompts / 提示词

- `detect_impact(target)` — calls mc_analyze
- `spring_cloud_safe_change(task)` — calls mc_start → mc_lookup/mc_analyze → mc_sync → mc_close

## Recommended agent behavior / 推荐 Agent 行为

1. Call `mc_start` before starting any coding task.
2. Call `mc_lookup` with mode="auto" for any knowledge lookup — it routes to the best search strategy automatically.
3. Call `mc_analyze` before modifying code — it returns impact, plan, and rules in one call.
4. Call `mc_sync` to save progress mid-task, or `mc_close` when done.
5. Call `mc_resume` when returning to a previous task.
6. Call `mc_handoff` when switching models or sessions.

1. 任何编程任务开始前，调用 `mc_start`。
2. 调用 `mc_lookup` mode="auto" 做知识检索——自动路由到最佳策略。
3. 修改代码前调用 `mc_analyze`——一次返回影响面、改动计划和规则检查。
4. 中途保存进度用 `mc_sync`，结束时用 `mc_close`。
5. 回到之前的任务时用 `mc_resume`。
6. 切换模型或会话时用 `mc_handoff`。

## Stable response schemas / 稳定返回协议

The following response families expose explicit `schema.name` and `schema.version` metadata so downstream tools can bind to stable contracts.

以下返回族会显式暴露 `schema.name` 和 `schema.version`，方便下游工具绑定稳定协议。

| Schema | Produced by / 产出入口 | Contract highlights / 协议重点 |
|---|---|---|
| `write_receipt` | mc_admin write_judge/plan/execute | `receipt_id`, `summary`, `layer`, `action`, `scope`, `target`, `task_id`, `session_id`, `receipt_ref` |
| `timeline_item` | timeline query internals / 时间线项 | `kind`, `created_at`, `task_id`, `session_id`, `layer`, `action`, `scope`, `target` |
| `timeline_result` | mc_admin replay / 时间线结果 | `timeline`, `limit`, `filters` |
| `eval_result` | mc_admin eval_* | `score`, `quality`, `findings` |
| `memory_ref` | mc_lookup mode=ref / 引用展开 | `ref_id`, `kind`, `summary`, `raw` |
| `resume_packet` | mc_resume | `current_summary`, `next_recommended_actions`, `unresolved_items`, `resume_rule_profile` |
| `handoff_packet` | mc_handoff | `target_model`, `model_profile`, `handoff_rule_profile`, `minimal_required_context`, `what_to_check_next` |
| `workspace_continuity_dashboard` | mc_admin continuity | `focus_task`, `resume_packet`, `next_actions`, `recent_evidence` |
| `workspace_dashboard` | mc_admin dashboard | `focus_task`, `continuity_overview`, `write_receipts_overview`, `active_tasks`, `focus_resume_eval` |