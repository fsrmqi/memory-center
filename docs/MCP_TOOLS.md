# MCP Tools / MCP 工具说明

Memory Center exposes graph-first project memory to AI coding agents through MCP.

记忆中心通过 MCP 把图优先项目记忆暴露给 AI 编程助手。

## Tools / 工具

| Tool | Description / 说明 |
|---|---|
| `workspace_sniff_tool(intent, limit)` | Retrieve task context: services, files, rules, topology hints, historical cases. / 任务开始前召回服务、文件、规则、拓扑、历史经验。 |
| `memory_query_tool(query, limit)` | Graph-aware hybrid search across files, symbols, endpoints, Feign clients, topics and fields, with exact/semantic retrieval metadata. / 基于图谱的混合检索，查询文件、符号、接口、Feign、Topic、字段，并返回精确/语义召回来源信息。 |
| `memory_context_tool(name, max_depth)` | 360-degree context for a graph node. / 返回某个节点的上下游上下文。 |
| `memory_impact_tool(target, direction, max_depth)` | Impact analysis for DTO, Feign, MQ topic, endpoint, service or file. / 对 DTO、Feign、消息主题、接口、服务、文件做影响面分析。 |
| `memory_detect_changes_tool(scope)` | Map local git diff to affected files, projects, rules and risk level. / 把本地 Git diff 映射为影响项目、规则和风险等级。 |
| `memory_contracts_tool()` | List API/Feign/MQ contracts and contract rules. / 列出接口、Feign、MQ 契约及相关规则。 |
| `workspace_trace_tool(entry)` | Trace candidates by class, endpoint, Feign client or topic. / 按类名、接口、Feign、Topic 追踪候选链路。 |
| `workspace_check_contract_tool(contract_file, change_type)` | Check safety before modifying shared DTO/Feign/MQ contracts. / 修改公共 DTO、Feign、MQ Message 前检查。 |
| `workspace_check_rules_tool(projects, change_type, files)` | Match architecture rules before editing. / 编辑前匹配架构规则。 |
| `workspace_record_case_tool(task, projects, files, flow, risk_points, verified_by)` | Record validated task memory. / 完成验证后沉淀任务经验。 |
| `memory_generate_wiki_tool(output_dir)` | Generate bilingual architecture wiki. / 生成双语架构 Wiki。 |
| `memory_generate_skills_tool(output_dir)` | Generate Agent skill files from task memory. / 根据历史任务生成 Agent Skill。 |
| `workspace_status_tool()` | Return index and memory status. / 返回索引和记忆状态。 |
| `group_query_tool(group, query, limit)` | Run a merged query across registered workspaces in one logical group, with exact/semantic retrieval metadata. / 对逻辑分组中的多个工作区做聚合查询，并返回精确/语义召回来源信息。 |
| `group_status_tool(group)` | Return aggregated group status, including semantic index readiness and document counts. / 返回逻辑分组聚合状态，包含语义索引就绪度与文档数。 |
| `group_impact_tool(group, target, direction, max_depth)` | Run cross-workspace impact analysis with bridge evidence. / 结合 bridge 证据做跨工作区影响面分析。 |

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
