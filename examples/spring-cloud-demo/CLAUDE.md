<!-- memory-center:start -->
# Memory Center Agent Protocol

本 workspace 使用 Memory Center 作为 AI 编程助手的项目记忆 MCP 服务。

## 必须遵守

1. 任何代码分析、Bug 修复、新功能开发、重构、架构评审任务前，先调用 `workspace_sniff(intent)`。
2. 如果用户要“找类 / 找方法 / 找 Feign / 找 Topic / 找配置项 / 找调用链”，优先调用 `memory_symbol(name)`、`memory_search_code(query)`、`workspace_trace(entry)`、`memory_callers(symbol)`、`memory_callees(symbol)`，不要先直接做全仓库文本搜索。
3. 在写入任何记忆前，先调用 `memory_write_judge(text, source, intent)`；需要可执行步骤时，再调用 `memory_plan_write(...)`，明确该写 L0 / L1 / L2 / L3 哪一层。
4. 如果任务会持续一段时间，或者需要多人/多 Agent 共享上下文，在 `workspace_sniff(intent)` 之后优先调用 `workspace_sync_sniff_artifacts(intent, ...)`，把上下文和计划写入任务空间，而不只是停留在查询结果里。
5. 对于长任务，开始时调用 `workspace_start_session(intent)`；关键步骤、关键结论、关键工具结果要持续调用 `workspace_log_session_event(...)` 记录到 session memory。
6. 修改 Feign、DTO、MQ Message、公共 API 前，调用 `workspace_check_contract(contract_file, change_type)`。
7. 修改任何核心文件前，调用 `workspace_check_rules(projects, change_type, files)`。
8. 任务结束后，先调用 `workspace_end_session(session_id, ...)`，再调用 `workspace_sync_case_artifacts(session_id, ...)`，把本次任务结论、设计和变更摘要同步回任务空间。
9. 完成验证后，再调用 `workspace_record_case(task, projects, files, flow, risk_points, verified_by)` 沉淀长期经验。
10. `context.md`、`requirement.md`、`design.md`、`plan.md`、`test-plan.md`、`change-log.md`、`current-summary.md` 属于追加保护工件，只允许尾部追加或去重，不允许整篇覆盖。
11. 首轮工具列表没有 Memory Center 工具不等于服务不可用。先做延迟工具发现并轻量调用；配置已启用但工具仍不可见时说明“宿主工具快照尚未刷新”，提示刷新或新建会话。只有绑定、命令或 MCP 调用明确失败时，才说明不可用并降级为本地搜索。

## 推荐任务链路

1. `workspace_sniff(intent)`
2. 若是找类/方法/调用链：`memory_symbol(name)` / `memory_search_code(query)` / `workspace_trace(entry)`
3. `memory_write_judge(text=intent, source="sniff_intent", intent=intent)`
4. `memory_plan_write(text=intent, source="sniff_intent", intent=intent)`
5. `workspace_sync_sniff_artifacts(intent, auto_sync_mode=balanced)`
6. `workspace_start_session(intent)`
7. `workspace_log_session_event(...)` 记录关键分析、影响面、验证结果
8. `workspace_check_contract(...)` / `workspace_check_rules(...)`
9. 完成后：`workspace_end_session(session_id, ...)`
10. `workspace_sync_case_artifacts(session_id, auto_sync_mode=balanced)`
11. `workspace_record_case(...)`

## 重要说明

- `workspace_sniff` 默认只读，只负责查上下文与给出同步建议，不会自动写任务空间。
- “找类 / 找方法 / 找 Feign / 找 Topic / 找配置项 / 找调用链” 属于 Memory Center 的强项，优先走 `memory_symbol` / `memory_search_code` / `workspace_trace` / `memory_callers` / `memory_callees`，不要一上来就全仓库 grep。
- `memory_write_judge` 负责决定信息应进入 L0 session、L1 case、L2 task space 还是 L3 workspace profile。
- `memory_plan_write` 不直接写入，而是返回“下一步应该调哪个 tool、缺什么参数、是否 ready”的执行计划。
- `workspace_record_case` 默认只写 `memory/cross-service-task-memory.jsonl`，不会自动更新 `artifacts/tasks/...` 下的 `context.md`、`plan.md`、`design.md`、`change-log.md`。
- 真正把内容写回任务空间的是 `workspace_sync_sniff_artifacts` 和 `workspace_sync_case_artifacts`。
- L3 级别信息优先进入 `workspace_profile`、`team_rules`、`architecture_invariants`、`active_migration_policy` 等核心记忆块。
- 如果希望“当前任务上下文”能沉淀到公共空间，必须显式走 sync 链路，而不是只调用 sniff / record-case。

## Spring Cloud 重点风险

- Feign 契约变更必须做调用方影响分析。
- MQ 消费必须保证幂等、重试、死信或补偿。
- 公共 DTO 不允许破坏性删除字段或改变字段语义。
- ES 写入必须确认 write index，并处理 bulk item 级失败。
- 核心链路日志必须包含 chainId、siteCode、uid、业务主键和阶段码。
- 跨时间分表/索引迁移必须支持重复执行和失败补偿。
<!-- memory-center:end -->

