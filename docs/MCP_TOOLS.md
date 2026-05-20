# MCP Tools / MCP 工具说明

Memory Center exposes graph-first project memory to AI coding agents through MCP.

记忆中心通过 MCP 把图优先项目记忆暴露给 AI 编程助手。

## Tools / 工具

| Tool | Description / 说明 |
|---|---|
| `workspace_sniff_tool(intent, limit, auto_sync_mode)` | Retrieve task context: services, files, rules, topology hints, historical cases, plus `symbolic_context` for low-token planning. `symbolic_context` includes both `entities_mermaid` and `flow_mermaid`; response also includes `resolved_task`, `task_candidates`, and `auto_sync_recommendation` for explainable task-space routing. `auto_sync_mode` supports `strict|balanced|aggressive`. / 任务开始前召回服务、文件、规则、拓扑、历史经验，并返回低 Token 规划用的 `symbolic_context`（含 `entities_mermaid` 与 `flow_mermaid`）；同时返回 `resolved_task`、`task_candidates` 和 `auto_sync_recommendation`，便于可解释地路由到任务空间。`auto_sync_mode` 支持 `strict|balanced|aggressive`。 |
| `workspace_artifact_list_tool()` | List shared workspace artifacts such as context, requirement, design, plan, test plan and change log. / 列出共享工件，如 context、requirement、design、plan、test plan、change log。 |
| `workspace_artifact_get_tool(name)` | Read one shared artifact. / 读取一个共享工件。 |
| `workspace_artifact_outline_tool(name)` | Read only the section outline of one artifact. / 只读取共享工件的章节提纲。 |
| `workspace_artifact_context_tool(intent, limit)` | Retrieve only relevant snippets from artifacts for one intent, instead of loading full documents. / 针对当前意图只召回相关片段，而不是整篇读取工件。 |
| `workspace_artifact_update_tool(name, content)` | Replace one shared artifact content. / 覆盖更新一个共享工件。 |
| `workspace_append_change_log_tool(entry)` | Append one timestamped change-log entry. / 追加一条带时间戳的 change-log 记录。 |
| `workspace_compact_change_log_tool(keep_recent)` | Archive older change-log entries to keep shared context compact. / 归档较早的 change-log 记录，保持共享上下文精简。 |
| `workspace_sync_sniff_artifacts_tool(intent, limit, task_id, title, auto_sync_mode)` | Sync one sniff result into shared `context.md` and `plan.md`, with the same `auto_sync_mode` strategy (`strict|balanced|aggressive`) used by sniff recommendation. / 把一次 sniff 结果同步进共享 `context.md` 和 `plan.md`，并支持与 sniff 建议一致的 `auto_sync_mode` 策略（`strict|balanced|aggressive`）。 |
| `workspace_sync_case_artifacts_tool(session_id, task_id, title, auto_sync_mode)` | Sync one suggested case into shared `design.md` and `change-log.md`, with the same `auto_sync_mode` strategy (`strict|balanced|aggressive`) used by task routing recommendation. The response includes `risk_evidence` to explain risk scoring from `risk_points + evidence_refs`. / 把一次建议 case 同步进共享 `design.md` 和 `change-log.md`，并支持与任务路由建议一致的 `auto_sync_mode` 策略（`strict|balanced|aggressive`）。返回会包含 `risk_evidence`，用于解释基于 `risk_points + evidence_refs` 的风险评分。 |
| `workspace_task_space_create_tool(title, intent)` | Create one task-specific artifact space from a custom title or intent. / 通过自定义标题或任务意图创建任务工件空间。 |
| `workspace_task_space_list_tool(include_archived)` | List active or archived task-specific artifact spaces. / 列出活跃或已归档的任务工件空间。 |
| `workspace_task_space_resolve_tool(intent, title, create_if_missing, include_archived)` | Resolve the most relevant task space from natural language, and create one only if needed. / 根据自然语言解析最相关的任务工件空间，只有在必要时才新建。 |
| `workspace_task_artifact_get_tool(task_id, name)` | Read one artifact inside a task-specific space. / 读取任务工件空间中的单个文档。 |
| `workspace_task_artifact_update_tool(task_id, name, content)` | Replace one artifact inside a task-specific space. / 更新任务工件空间中的单个文档。 |
| `workspace_task_append_change_log_tool(task_id, entry, keep_recent)` | Append one timestamped entry into a task-specific change log. / 追加一条带时间戳的任务变更记录。 |
| `workspace_task_status_tool(task_id, status)` | Update one task-specific space status: `draft / active / blocked / done / archived`. / 更新任务工件空间状态：`draft / active / blocked / done / archived`。 |
| `workspace_task_archive_tool(task_id, reason)` | Archive one task-specific artifact space manually. / 手动归档一个任务工件空间。 |
| `workspace_task_auto_archive_tool(retention_days)` | Auto-archive task-specific artifact spaces older than retention_days. / 按保留天数自动归档过期任务工件空间。 |
| `memory_query_tool(query, limit)` | Graph-aware hybrid search across files, symbols, endpoints, Feign clients, topics and fields, with exact/semantic retrieval metadata and `progressive` summary/evidence/detail views. / 基于图谱的混合检索，查询文件、符号、接口、Feign、Topic、字段，并返回精确/语义召回来源信息，以及 `progressive` 的摘要/证据/细节分层视图。 |
| `memory_search_code_tool(query, scope, limit)` | Keyword search over indexed files and symbol hints, useful for quick entrypoint discovery. / 在索引文件与符号提示上做关键词搜索，适合快速找入口。 |
| `memory_symbol_tool(name, limit)` | Resolve one symbol and return best match with candidates. / 解析一个符号并返回最佳命中及候选。 |
| `memory_callers_tool(symbol, depth, limit)` | Find upstream callers for a symbol. / 查询某符号的上游调用方。 |
| `memory_callees_tool(symbol, depth, limit)` | Find downstream callees for a symbol. / 查询某符号的下游被调方。 |
| `memory_context_tool(name, max_depth)` | 360-degree context for a graph node, with retrieval entrypoints, evidence summary and `progressive` layered view. / 返回某个节点的上下游上下文，并附带召回入口、证据摘要和 `progressive` 分层视图。 |
| `memory_impact_tool(target, direction, max_depth)` | Impact analysis for DTO, Feign, MQ topic, endpoint, service or file, with lookup provenance, evidence summary and `progressive` layered view. / 对 DTO、Feign、消息主题、接口、服务、文件做影响面分析，并附带命中来源、证据摘要和 `progressive` 分层视图。 |
| `memory_plan_change_tool(target, direction, max_depth)` | Build an actionable change plan from impact and rule evidence. / 基于影响面与规则证据生成可执行改动计划。 |
| `memory_verify_checklist_tool(target)` | Build verification checklist before merge/release. / 生成合并/发布前验证清单。 |
| `memory_write_judge_tool(text, source, intent, prefer_layer, projects, files)` | Judge which layer should receive this information: `L0_session_events / L1_case_atoms / L2_task_spaces / L3_workspace_profile`, with confidence, score and suggested tool. / 判断输入信息应写入哪个记忆层：`L0_session_events / L1_case_atoms / L2_task_spaces / L3_workspace_profile`，并返回置信度、评分和建议工具。 |
| `memory_plan_write_tool(text, source, intent, session_id, task_id, title, prefer_layer, projects, files)` | Build one executable write plan from judge result, including readiness and example args for each step. / 基于裁决结果生成可执行写入计划，包含每步是否可执行与示例参数。 |
| `memory_execute_write_tool(text, source, intent, session_id, task_id, title, prefer_layer, projects, files)` | Execute the ready steps from `memory_plan_write_tool`, returning executed tool results and the resolved `session_id` when applicable. / 执行 `memory_plan_write_tool` 中已就绪的步骤，并返回实际执行结果以及可解析出的 `session_id`。 |
| `workspace_write_receipts_tool(layer, action, scope, task_id, session_id, limit)` | Query persisted write receipts by layer/action/scope/task/session. / 按 layer、action、scope、task、session 查询已持久化的写入回执。 |
| `workspace_replay_write_chain_tool(task_id, session_id, limit)` | Replay one write chain in time order. / 按时间顺序回放一条写入链路。 |
| `memory_eval_write_quality_tool(task_id, session_id, intent, limit)` | Evaluate whether the observed receipts cover the expected memory layers. / 评估当前写入回执是否覆盖了预期的记忆层。 |
| `workspace_recent_evidence_tool(task_id, session_id, limit)` | Return recent evidence from session events and write receipts. / 返回来自 session 事件和写入回执的近期证据。 |
| `workspace_unresolved_items_tool(task_id, session_id, intent, limit)` | Return unresolved items for one task/session. / 返回一个任务或会话的未解决事项。 |
| `workspace_next_actions_tool(task_id, session_id, intent, limit)` | Suggest next actions for one task/session. / 为一个任务或会话推荐下一步动作。 |
| `workspace_resume_packet_tool(task_id, session_id, intent, limit)` | Build a compact resume packet for the next model/session. / 为下一个模型或下一次会话生成紧凑的恢复包。 |

`workspace_resume_packet_tool` is now rule-driven and returns `resume_rule_profile` so you can see which resume profile shaped the packet. / `workspace_resume_packet_tool` 现在由规则驱动，并会返回 `resume_rule_profile`，用于说明本次恢复包命中了哪条规则画像。
| `workspace_model_profile_tool(model_name)` | Normalize one target model name and return its handoff preference profile. / 规范化目标模型名称，并返回其交接偏好画像。 |
| `workspace_handoff_packet_tool(target_model, task_id, session_id, intent, limit)` | Build one handoff packet tailored to the target model. / 按目标模型生成一份专用交接包。 |
| `workspace_handoff_history_tool(target_model, task_id, session_id, limit)` | Query persisted handoff history. / 查询已持久化的交接历史。 |

Write tools now try to return a normalized `write_receipt` when they actually persist memory or artifacts. / 写入类工具在真正落盘时会尽量返回统一的 `write_receipt` 回执结构。
| `memory_detect_changes_tool(scope)` | Map local git diff to affected files, projects, rules and risk level. / 把本地 Git diff 映射为影响项目、规则和风险等级。 |
| `memory_contracts_tool()` | List API/Feign/MQ contracts and contract rules. / 列出接口、Feign、MQ 契约及相关规则。 |
| `workspace_trace_tool(entry)` | Trace candidates by class, endpoint, Feign client or topic. / 按类名、接口、Feign、Topic 追踪候选链路。 |
| `workspace_check_contract_tool(contract_file, change_type)` | Check safety before modifying shared DTO/Feign/MQ contracts. / 修改公共 DTO、Feign、MQ Message 前检查。 |
| `workspace_check_rules_tool(projects, change_type, files)` | Match architecture rules before editing. / 编辑前匹配架构规则。 |
| `workspace_record_case_tool(task, projects, files, flow, risk_points, verified_by, source_session_id, source_task_id)` | Record validated task memory, optionally linking it back to one session/task space. / 完成验证后沉淀任务经验，并可选回链到 session/task space。 |
| `workspace_start_session_tool(intent, session_id)` | Start a lightweight long-memory session. / 开始一个轻量长期记忆会话。 |
| `workspace_log_session_event_tool(session_id, event_type, payload)` | Append one session event like prompt/tool/result/note. Large payloads may be offloaded into `memory/refs/` with `payload_ref`. / 追加一次会话事件，例如提问、工具调用、工具结果、备注。体积过大的 payload 会自动外置到 `memory/refs/` 并返回 `payload_ref`。 |
| `workspace_end_session_tool(session_id, outcome, verified_by)` | End a session and generate a summary. / 结束会话并生成摘要。 |
| `workspace_recent_sessions_tool(limit)` | Read recent summarized sessions. / 查看最近会话摘要。 |
| `workspace_session_summary_tool(session_id)` | Read one session summary and raw events. / 查看单次会话摘要和原始事件。 |
| `workspace_resume_context_tool(intent, limit)` | Resume a new task from related sessions, cases and entrypoints. / 基于相关会话、经验和入口点恢复新任务上下文。 |
| `workspace_suggest_case_tool(session_id)` | Suggest one record-case draft from a finished session, including `evidence_refs` back to raw events. / 从已结束会话自动生成一条经验沉淀草稿，并附带可回溯原始事件的 `evidence_refs`。 |
| `memory_generate_wiki_tool(output_dir)` | Generate bilingual architecture wiki. / 生成双语架构 Wiki。 |
| `memory_generate_skills_tool(output_dir)` | Generate Agent skill files from task memory. / 根据历史任务生成 Agent Skill。 |
| `workspace_status_tool()` | Return index and memory status, including semantic backend readiness, layered memory counts (`L0/L1/L2/L3`), active task spaces, and `current_focus_task` with `focus_reason`. / 返回索引和记忆状态，包含语义 backend 就绪情况、分层记忆统计（`L0/L1/L2/L3`）、活跃任务空间，以及带 `focus_reason` 的 `current_focus_task`。 |
| `group_query_tool(group, query, limit)` | Run a merged query across registered workspaces in one logical group, with exact/semantic retrieval metadata and `progressive` summary/evidence/detail views. / 对逻辑分组中的多个工作区做聚合查询，并返回精确/语义召回来源信息，以及 `progressive` 的摘要/证据/细节分层视图。 |
| `group_status_tool(group)` | Return aggregated group status, including semantic index readiness, document counts and backend distribution. / 返回逻辑分组聚合状态，包含语义索引就绪度、文档数和 backend 分布。 |
| `group_impact_tool(group, target, direction, max_depth)` | Run cross-workspace impact analysis with lookup provenance, graph evidence, bridge evidence and `progressive` layered views. / 结合命中来源、图谱证据、bridge 证据和 `progressive` 分层视图做跨工作区影响面分析。 |

## Resources / 资源

- `memory-center://status`
- `memory-center://contracts`
- `memory-center://topology`

## Prompts / 提示词

- `detect_impact(target)`
- `spring_cloud_safe_change(task)`

## Recommended agent behavior / 推荐 Agent 行为

1. Call `workspace_sniff_tool` before broad code exploration.
2. Call `memory_write_judge_tool` or `memory_plan_write_tool` before writing memory, so the agent knows whether to write L0/L1/L2/L3.
3. For long-running or collaborative tasks, call `workspace_sync_sniff_artifacts_tool` to write context/plan into task space.
4. Call `memory_context_tool` or `memory_impact_tool` before modifying contracts.
5. Call `workspace_check_rules_tool` before editing.
6. For long tasks, use `workspace_start_session_tool` / `workspace_log_session_event_tool` during the process.
7. After validation, call `workspace_end_session_tool`, then `workspace_sync_case_artifacts_tool`.
8. Finally call `workspace_record_case_tool`.

1. 大范围搜索代码前，先调用 `workspace_sniff_tool`。
2. 写入记忆前，先调用 `memory_write_judge_tool` 或 `memory_plan_write_tool`，明确应写到 L0 / L1 / L2 / L3 哪一层。
3. 对于长任务或多人协作任务，先调用 `workspace_sync_sniff_artifacts_tool` 把上下文和计划写入任务空间。
4. 修改契约前，调用 `memory_context_tool` 或 `memory_impact_tool`。
5. 编辑前，调用 `workspace_check_rules_tool`。
6. 长任务过程中，使用 `workspace_start_session_tool` / `workspace_log_session_event_tool` 持续记录关键过程。
7. 验证完成后，先调用 `workspace_end_session_tool`，再调用 `workspace_sync_case_artifacts_tool` 回写任务空间。
8. 最后调用 `workspace_record_case_tool` 沉淀长期经验。
