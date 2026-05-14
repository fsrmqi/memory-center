# MCP Tools / MCP 工具说明

Memory Center exposes graph-first project memory to AI coding agents through MCP.

记忆中心通过 MCP 把图优先项目记忆暴露给 AI 编程助手。

## Tools / 工具

| Tool | Description / 说明 |
|---|---|
| `workspace_sniff_tool(intent, limit)` | Retrieve task context: services, files, rules, topology hints, historical cases, plus `symbolic_context` for low-token planning. `symbolic_context` now includes both `entities_mermaid` and `flow_mermaid`. / 任务开始前召回服务、文件、规则、拓扑、历史经验，并返回低 Token 规划用的 `symbolic_context`；其中同时包含 `entities_mermaid` 和 `flow_mermaid`。 |
| `workspace_artifact_list_tool()` | List shared workspace artifacts such as context, requirement, design, plan, test plan and change log. / 列出共享工件，如 context、requirement、design、plan、test plan、change log。 |
| `workspace_artifact_get_tool(name)` | Read one shared artifact. / 读取一个共享工件。 |
| `workspace_artifact_outline_tool(name)` | Read only the section outline of one artifact. / 只读取共享工件的章节提纲。 |
| `workspace_artifact_context_tool(intent, limit)` | Retrieve only relevant snippets from artifacts for one intent, instead of loading full documents. / 针对当前意图只召回相关片段，而不是整篇读取工件。 |
| `workspace_artifact_update_tool(name, content)` | Replace one shared artifact content. / 覆盖更新一个共享工件。 |
| `workspace_append_change_log_tool(entry)` | Append one timestamped change-log entry. / 追加一条带时间戳的 change-log 记录。 |
| `workspace_compact_change_log_tool(keep_recent)` | Archive older change-log entries to keep shared context compact. / 归档较早的 change-log 记录，保持共享上下文精简。 |
| `workspace_sync_sniff_artifacts_tool(intent, limit)` | Sync one sniff result into shared `context.md` and `plan.md`. / 把一次 sniff 结果同步进共享 `context.md` 和 `plan.md`。 |
| `workspace_sync_case_artifacts_tool(session_id)` | Sync one suggested case into shared `design.md` and `change-log.md`. / 把一次建议 case 同步进共享 `design.md` 和 `change-log.md`。 |
| `memory_query_tool(query, limit)` | Graph-aware hybrid search across files, symbols, endpoints, Feign clients, topics and fields, with exact/semantic retrieval metadata and `progressive` summary/evidence/detail views. / 基于图谱的混合检索，查询文件、符号、接口、Feign、Topic、字段，并返回精确/语义召回来源信息，以及 `progressive` 的摘要/证据/细节分层视图。 |
| `memory_search_code_tool(query, scope, limit)` | Keyword search over indexed files and symbol hints, useful for quick entrypoint discovery. / 在索引文件与符号提示上做关键词搜索，适合快速找入口。 |
| `memory_symbol_tool(name, limit)` | Resolve one symbol and return best match with candidates. / 解析一个符号并返回最佳命中及候选。 |
| `memory_callers_tool(symbol, depth, limit)` | Find upstream callers for a symbol. / 查询某符号的上游调用方。 |
| `memory_callees_tool(symbol, depth, limit)` | Find downstream callees for a symbol. / 查询某符号的下游被调方。 |
| `memory_context_tool(name, max_depth)` | 360-degree context for a graph node, with retrieval entrypoints, evidence summary and `progressive` layered view. / 返回某个节点的上下游上下文，并附带召回入口、证据摘要和 `progressive` 分层视图。 |
| `memory_impact_tool(target, direction, max_depth)` | Impact analysis for DTO, Feign, MQ topic, endpoint, service or file, with lookup provenance, evidence summary and `progressive` layered view. / 对 DTO、Feign、消息主题、接口、服务、文件做影响面分析，并附带命中来源、证据摘要和 `progressive` 分层视图。 |
| `memory_plan_change_tool(target, direction, max_depth)` | Build an actionable change plan from impact and rule evidence. / 基于影响面与规则证据生成可执行改动计划。 |
| `memory_verify_checklist_tool(target)` | Build verification checklist before merge/release. / 生成合并/发布前验证清单。 |
| `memory_detect_changes_tool(scope)` | Map local git diff to affected files, projects, rules and risk level. / 把本地 Git diff 映射为影响项目、规则和风险等级。 |
| `memory_contracts_tool()` | List API/Feign/MQ contracts and contract rules. / 列出接口、Feign、MQ 契约及相关规则。 |
| `workspace_trace_tool(entry)` | Trace candidates by class, endpoint, Feign client or topic. / 按类名、接口、Feign、Topic 追踪候选链路。 |
| `workspace_check_contract_tool(contract_file, change_type)` | Check safety before modifying shared DTO/Feign/MQ contracts. / 修改公共 DTO、Feign、MQ Message 前检查。 |
| `workspace_check_rules_tool(projects, change_type, files)` | Match architecture rules before editing. / 编辑前匹配架构规则。 |
| `workspace_record_case_tool(task, projects, files, flow, risk_points, verified_by)` | Record validated task memory. / 完成验证后沉淀任务经验。 |
| `workspace_start_session_tool(intent, session_id)` | Start a lightweight long-memory session. / 开始一个轻量长期记忆会话。 |
| `workspace_log_session_event_tool(session_id, event_type, payload)` | Append one session event like prompt/tool/result/note. / 追加一次会话事件，例如提问、工具调用、工具结果、备注。 |
| `workspace_end_session_tool(session_id, outcome, verified_by)` | End a session and generate a summary. / 结束会话并生成摘要。 |
| `workspace_recent_sessions_tool(limit)` | Read recent summarized sessions. / 查看最近会话摘要。 |
| `workspace_session_summary_tool(session_id)` | Read one session summary and raw events. / 查看单次会话摘要和原始事件。 |
| `workspace_resume_context_tool(intent, limit)` | Resume a new task from related sessions, cases and entrypoints. / 基于相关会话、经验和入口点恢复新任务上下文。 |
| `workspace_suggest_case_tool(session_id)` | Suggest one record-case draft from a finished session, including `evidence_refs` back to raw events. / 从已结束会话自动生成一条经验沉淀草稿，并附带可回溯原始事件的 `evidence_refs`。 |
| `memory_generate_wiki_tool(output_dir)` | Generate bilingual architecture wiki. / 生成双语架构 Wiki。 |
| `memory_generate_skills_tool(output_dir)` | Generate Agent skill files from task memory. / 根据历史任务生成 Agent Skill。 |
| `workspace_status_tool()` | Return index and memory status, including semantic backend readiness. / 返回索引和记忆状态，包含语义 backend 就绪情况。 |
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
2. Call `memory_context_tool` or `memory_impact_tool` before modifying contracts.
3. Call `workspace_check_rules_tool` before editing.
4. Call `workspace_record_case_tool` after validation.

1. 大范围搜索代码前，先调用 `workspace_sniff_tool`。
2. 修改契约前，调用 `memory_context_tool` 或 `memory_impact_tool`。
3. 编辑前，调用 `workspace_check_rules_tool`。
4. 验证完成后，调用 `workspace_record_case_tool` 沉淀经验。
