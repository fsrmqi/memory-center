# MCP Guide / MCP 接入指南

## 1. Public Surface / 对外公开面

MCP 当前公开的是 12 个 task-level tools：

- `mc_start`
- `mc_lookup`
- `mc_analyze`
- `mc_sync`
- `mc_resume`
- `mc_handoff`
- `mc_close`
- `mc_admin`
- `mc_context_pack`
- `mc_onboard`
- `mc_domain`
- `mc_freshness`

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
| `mc_close` | 会话收尾、同步 case、记录经验，并自动回写可推断的候选路径反馈 |
| `mc_admin` | 状态、面板、评测、工件、group 等管理入口 |
| `mc_context_pack` | 生成紧凑、证据驱动的上下文包 |
| `mc_onboard` | 生成面向不同 persona 的架构导览 |
| `mc_domain` | 提取业务域和业务流 |
| `mc_freshness` | 检查索引新鲜度与 stale/pending 风险 |

`mc_start` / `mc_lookup` 可传 `request_tier="fast"|"standard"|"deep"`，其中 `fast` 会收紧候选数量和深度。`mc_analyze(execution_mode="background")` 会立即返回 `job_id`；使用同一工具并传入 `job_action="status"|"cancel"` 与 `job_id` 即可读取或取消后台分析。默认仍是同步执行，保持既有调用兼容。

管理类异步重建使用 `mc_admin(action="job_reindex", projects=[...], files=[...])`。返回值中的 `job_id` 传给 `mc_admin(action="job_status", record_id="...")` 或 `mc_admin(action="job_cancel", record_id="...")`。可使用 `index_control` 查看 active/staging generation，使用 `query_performance` 查看 P50/P95/P99 查询耗时。任务级架构决策使用 `task_decision_record` / `task_decision_list`；`task_evidence_gc` 仅在 `force=true` 时删除候选证据。

传入 `mc_lookup(..., project="service-name")` 时，服务范围内的 code/hybrid 查询会优先读取 active generation 的物理服务分片。回滚使用 `mc_admin(action="index_rollback", record_id="<generation>")`；generation 清理使用 `mc_admin(action="index_generation_gc", keep_recent=2, force=false)`，默认仅返回候选项。

不传 `project` 的 `mc_lookup` 也会返回 `shard_route`（generation、起始服务、扩展深度、契约/拓扑依据）和 `shard_evidence`（并行查询的服务分片及命中）。跨服务性能门禁使用 `mc_admin(action="eval_cross_shard_replay", text="每行一个查询", budget="fast|standard|deep")`；结果只记录耗时、选片数量和证据覆盖率。

## 3. Recommended Agent Behavior / 推荐 Agent 行为

推荐顺序：

1. 开始任务：`mc_start`
2. 查信息：`mc_lookup(mode="auto")`
3. 改前检查：`mc_analyze`
4. 长任务同步：`mc_sync`
5. 中断后恢复：`mc_resume`
6. 切换模型：`mc_handoff`
7. 架构/变更问题先看：`mc_context_pack`
8. 新人或跨角色理解：`mc_onboard` / `mc_domain`
9. 改动前确认索引状态：`mc_freshness`
10. 收尾：`mc_close`

补充说明：
- 回到已知任务空间时，优先调用 `mc_admin(action="task_resume_check", task_id="...")`。它会合并 resume packet、task health、repair plan、next actions、unresolved items 和 recent evidence，返回 `ready`、`needs_repair` 或 `blocked`。
- 当 `task_resume_check.status="needs_repair"` 时，先看 `mc_admin(action="task_repair_plan", task_id="...")`。需要执行修复时再调用 `mc_admin(action="task_repair_apply", task_id="...", force=false)` 做 dry-run；确认后用 `force=true` 应用。刷新 `current-summary` 这类修复应传入 `intent`，例如 `intent="继续 Feign DTO 兼容改造"`。
- `task_repair_apply` 只执行保守低风险修复：补齐缺失 context/plan 模板、在有 intent 时刷新 current-summary。它不会伪造 write receipt、自动归档相似任务空间或覆盖已有人工内容。
- `mode="trace"` 适合先看跨服务索引概览，快速知道 Feign / API / MQ 命中了什么。
- 如果需求是“某个方法一路追到最底层”，优先用 `mode="walkthrough"`；当查询里已经包含 `Class#method` 且明确提到“全链路/到底层”时，`mode="auto"` 现在也会优先转到 walkthrough。
- `mode="chain"` 适合看图谱 callers / callees；`mode="walkthrough"` 适合看一个方法体内的已索引步骤、下游调用和 Feign 服务端候选。
- `mode="walkthrough"` 的 Feign 续链会在 `feign_continuations[].server_walkthroughs` 中优先展开目标服务的 Controller 方法；如果 Controller 调用同项目 Service interface，会在 `service_impl_continuations` 中继续给出 Impl 方法落点和已索引本地步骤。
- `mode="walkthrough"` 还会在 `local_service_continuations` 中展开当前方法内的普通 Service interface → Impl 调用；compact 输出会优先保留关键方法调用和 Feign 调用，`downstream_summary` 只作为补充图谱线索。
- walkthrough 的关键落点均返回 `absolute_file_path`；agent 应直接读取该路径，不需要再用 `find` / `grep -l` 定位文件。
- walkthrough 返回 `agent_usage_policy.do_not_search_when_absolute_path_present=true` 时，宿主模型应把 `find`、`grep -l`、`rg --files`、IDE 全局搜索视为不必要的重复定位；只有怀疑索引过期或文件不存在时才做 live search。
- walkthrough 返回 `same_class_method_continuations` 时，宿主模型应优先阅读该续链的 `field_filter_summary` 和 `local_steps`，不要先用 `sed -n` 切同一文件片段；只有需要逐行核对业务分支时才读取 `absolute_file_path`。
- `mc_lookup(auto|walkthrough)` 的 walkthrough 响应会把 `answer`、`answer_markdown`、`summary_lines`、`read_targets`、`mermaid_flow`、`performance_risks`、`data_scope_guards`、`diff_context`、`glossary_hits`、`index_freshness`、`branch_outline`、`anti_patterns`、`cache`、`schema_version`、`fields_contract` 提升到顶层；宿主模型应直接使用这些顶层字段，不需要读取或解析本地 `tool-results/*.json`。
- Hybrid query responses include additive `retrieval_policy` and `retrieval_diagnostics.policy` fields. They explain selected sources and bounded budgets without changing existing MCP tool parameters.
- Hybrid query 响应新增兼容型 `retrieval_policy` 与 `retrieval_diagnostics.policy` 字段，用于解释来源选择和有界预算，不改变现有 MCP tool 参数。
- Lookup responses also include additive `agent_next_steps`; `mc_lookup` lifts it to the top level for auto-routed and direct query/symbol/code/context/chain/trace routes, so the host agent can follow a bounded next step instead of inventing a new search path.
- Lookup 响应还会返回兼容型 `agent_next_steps`；`mc_lookup` 在自动路由和直接 query/symbol/code/context/chain/trace 路由下会把它提升到顶层，让宿主 Agent 按证据边界执行下一步，而不是重新发散搜索路径。
- When `session_id` is provided, `mc_lookup` records returned `agent_next_steps` as an `agent_guidance` session event for adoption evaluation.
- 传入 `session_id` 时，`mc_lookup` 会把返回的 `agent_next_steps` 自动记录为 `agent_guidance` session event，用于后续 adoption 评估。
- If adoption trends show a returned action is repeatedly missed, future query `agent_next_steps` may include `adoption_feedback` and a more explicit command while preserving the action.
- 如果 adoption 趋势显示某个返回 action 反复未被执行，后续 query 的 `agent_next_steps` 可能会附加 `adoption_feedback` 并给出更明确的 command，但保留原 action。
- If replay trends explain why guidance failed, future query `agent_next_steps` may include `replay_feedback`: bypass reasons suppress broad local search, unobservable reasons remind callers to pass `session_id`, missing-target reasons force `target_ref` / `read_targets`, and action-mismatch reasons point to the matching Memory Center mode. Replay preserves follow-up order, so a local-search bypass before a later matching Memory Center call is still `bypassed`; it detects bypasses from structured tool names or shell command fields only.
- 如果 replay 趋势解释了建议失败原因，后续 query 的 `agent_next_steps` 可能会附加 `replay_feedback`：绕过原因会压制泛本地搜索，不可观测原因会提示传入 `session_id`，缺少目标原因会强制使用 `target_ref` / `read_targets`，动作不匹配原因会提示切到对应的 Memory Center mode。Replay 会保留后续事件顺序，因此先本地搜索绕过、之后才调用匹配的 Memory Center 工具仍会归类为 `bypassed`；绕过检测只使用结构化工具名或 shell 命令字段。
- Method-level `switch_to_walkthrough` guidance preserves `target_ref` and `read_targets` when the indexed hit has a resolved path.
- 当方法级 `switch_to_walkthrough` 建议对应的索引命中已解析路径时，会保留 `target_ref` 与 `read_targets`。
- The same field is visible from CLI `memory-center query` and HTTP `/workspace/query`; MCP only adds the top-level lift for non-query route wrappers.
- CLI `memory-center query` 和 HTTP `/workspace/query` 也会返回同一字段；MCP 只是额外在非 query 路由包装层把它提升到顶层。
- 如果当前 MCP workspace 是子项目，method walkthrough 会尝试自动升级到父级或 registry 中覆盖当前项目的聚合 workspace。查看 `workspace_escalation.status` 判断是否已切换；`not_needed_or_not_found` 不是错误。
- `memory-center init` / `memory-center reindex` 写入的受管说明块和 MCP 绑定现在会镜像到各个已配置 service root，明确提示并实际绑定上层 `.memory-center/workspace.yaml`；这能减少 Agent 在子项目里“没连上父级 workspace 就不调用 MCP”的情况。
- `memory-center setup-agent --workspace <workspace.yaml>` 是推荐的一键接入口，会刷新说明、Hooks、MCP 绑定并返回是否需要重启宿主会话。
- `memory-center runtime-audit --workspace <workspace.yaml> --fix` 会检查并刷新根目录和子项目目录下的 `.codex/mcp.json`、`.cursor/mcp.json`、`.mcp.json`，用于自动修复看不到 `mc_*` 工具的宿主接入问题。
- MCP server 暴露 `memory-center://startup-diagnostics` resource，用于查看启动时解析到的 workspace、MCP 绑定状态和下一步修复建议。
- 可在 `.memory-center/templates/method_walkthrough.md` 配置报告模板，支持占位符 `{target_label}`、`{summary_lines}`、`{read_targets}`、`{rule_groups}`、`{mermaid_flow}`、`{performance_risks}`、`{data_scope_guards}`、`{diff_context}`、`{glossary}`、`{next_actions}`。未配置时返回内置 `answer_markdown`，可用 `report_level=brief|standard|deep|risk-focused` 控制默认报告形态。
- MCP server 的 `--workspace` 可以传 `workspace.yaml` 或项目目录；传目录时会向上寻找 `.memory-center/workspace.yaml`，找不到时保持原入参并由后续工具返回正常错误信息。
- 可在 `.memory-center/glossary.yaml`、`.memory-center/glossary.yml` 或 `.memory-center/business-glossary.yaml` 配置业务词汇，命中结果会出现在 `glossary_hits`。
- endpoint 候选会包含 `confidence` / `confidence_reasons`，多候选时优先使用置信度最高的 Controller。
- `index_freshness.index_stale=true` 表示主链路文件比索引更新，应先 live read 或 reindex；`cache.hit=true` 表示命中短期进程内缓存。
- `branch_outline` 会把大方法规则分组、DTO 字段或方法调用整理成可读轮廓；`anti_patterns` 明确列出宿主模型应避免的低效动作。
- `mc_admin(action="walkthrough_health")` 会检查模板、glossary、索引文件、缓存、字段契约与近期绕过行为；`mc_admin(action="eval_walkthrough_quality")` 会对 walkthrough 输出做 agent-ready 评分；`mc_admin(action="walkthrough_export")` 会导出 `.memory-center/artifacts/walkthroughs/*.md`。

`mc_close` 在 session 内存在可推断的 lookup / impact / sync 路径且有验证结果时，会自动写回一轮 `candidate_feedback`，让后续推荐权重逐步学习。

`mc_lookup(mode="auto")`、`workspace_lookup_hint`、`workspace_sniff`、`mc_analyze`、`runtime_audit`、discover 类推荐，以及 `session_start` / `workflow_recommend` 的 workflow profile 推荐，现在都会吸收这些学习结果：主链路保留规则生成的解释与下一步动作，同时用学习后的 `recommended_weight` 轻量修正默认优先级。

## 4. mc_admin Actions / mc_admin 操作列表

`mc_admin` 通过 `action` 参数路由到不同子操作：

### 状态与健康

- `status` — 工作区状态
- `dashboard` — 工作区面板
- `continuity` — 连续性面板
- `health` — 健康检查（状态 + 工具使用 + 回归套件）
- `eval_agent_guidance` — 检查 lookup 输出是否包含有界 `agent_next_steps`，并标记低效搜索建议
- `eval_agent_guidance_adoption` — 检查已记录的 agent guidance 是否被后续 tool call 执行
- `eval_agent_guidance_adoption_trend` — 执行 adoption 检查并追加一条 adoption rate 趋势记录
- `eval_agent_guidance_replay` — 回放真实 session event，并把建议执行结果分类为 adopted / missed / bypassed / unobservable
- `eval_agent_guidance_replay_campaign` — 检查真实 replay 的最小事件量和意图覆盖；只读，不会自动调整检索权重
- `eval_agent_guidance_replay_trend` — 执行 replay 检查并追加一条 replay 趋势记录
- `eval_java_call_resolution_unresolved` — 按可行动原因汇总未解析 Java `CALLS_METHOD`，只返回逻辑锚点样本，不返回文件路径或源码
- `eval_agent_guidance_trend` — 执行同一检查并追加一条 agent guidance 趋势记录
- `audit` — 完成审计（文档/测试/实现/设计一致性）
- `discover` — 热点命令发现与下一步推荐
- `constraint` — 约束模板与自动策略选择
- `backend_consistency` — JSONL 与 SQLite 后端一致性检查

### 经验与权重回写

- `heuristics_query` — 查询已学习启发式与当前聚合权重
- `heuristics_record` — 记录启发式模式
- `heuristics_feedback` — 对候选路径写回验证结果，更新推荐权重
- `heuristics_explain` — 解释某条候选路径 / workflow profile 当前为何被提升、保护、回滚或衰减，并返回最近事件时间线

### 钻取导航

- `drill_ref` — 展开 ref，渐进式披露（通过 `ref_path` 参数指定 ref ID）
- `drill_timeline` — 时间线钻取（通过 `session_id` 或 `task_id` 过滤）
- `drill_task` — 任务上下文钻取（通过 `task_id` 参数）

### 评测

- `eval_parser_benchmark` — 真实 workspace 下的 regex / tree-sitter parser 对比评测；reindex 同时返回 parser、fallback 原因与 disagreement diagnostics
- `eval_java_call_resolution` — 对 Java `CALLS_METHOD` 解析结果运行真实精度门禁；`name` 参数传 cases YAML 路径，cases 只允许逻辑锚点，不允许私有文件路径；传 `strict=true` 时会对 `forbidden_targets` 启用严格失败门禁
- `eval_java_call_resolution_review` — 汇总未分类高置信 Java 调用边，按逻辑锚点去重后供人工回写为 `allowed_targets` 或 `forbidden_targets`
- `eval_golden` — 对指定 workspace + cases 文件运行 Golden Benchmark；hybrid case 可用 `enable_vector: true` 显式启用 ANN 向量检索，用于概念查询回归
- `eval_token_benchmark` — Token 基准测试
- `eval_token_benchmark_trend` — Token 基准趋势报告（回归检测、健康评分）
- `eval_token_gain` — Token 节省评估
- `eval_regression_suite` — 回归套件
- `eval_write_quality` / `eval_resume` / `eval_handoff` — 各维度评测
- `regression_alerts` — Token 回归告警，使用默认阈值；HTTP / CLI 对应入口使用 `threshold_pct`

### 工件与任务

- `artifact_*` — 工件操作
- `task_*` — 任务空间操作
- `task_health` — 检查单个任务空间的恢复健康度和风险
- `task_health_all` — 汇总所有任务空间健康度
- `task_repair_plan` — 生成任务空间修复计划，不写入
- `task_repair_apply` — 默认 dry-run，`force=true` 时执行保守修复；可带 `intent`
- `task_resume_check` — 一键恢复门禁，合并恢复包、健康度、修复建议和证据
- `session_*` — 会话操作
- `group_*` — 跨工作区组操作
- `walkthrough_health` / `eval_walkthrough_quality` / `walkthrough_export` — method walkthrough 自检、质量评测与 Markdown artifact 导出

## 5. V3 Tools / V3 工具

### `mc_context_pack`

- 用途：给模型一个紧凑的、证据驱动的上下文包
- 适合场景：
  - 架构理解
  - 变更影响预热
  - 希望减少多次 grep / read / lookup

### `mc_onboard`

- 用途：按 persona 生成架构导览
- 支持的 persona：
  - `developer`
  - `architect`
  - `product`
  - `tester`

### `mc_domain`

- 用途：从代码图谱中提取业务域与业务流
- 适合场景：
  - 业务边界梳理
  - 跨模块业务链路说明

### `mc_freshness`

- 用途：检查索引是否 stale / pending
- 适合场景：
  - 改动前确认图谱是否可信
  - 提醒是否应先读 live file 或触发增量索引

### Next Phase 入口一致性 / Entry Consistency

以下能力必须保持 CLI / MCP / HTTP 对 `workspace.yaml` 的解析语义一致：

- `context-pack`
- `freshness`
- `onboard`
- `domain`
- `business-flow`
- `business-flow-impact`
- `runtime-audit`
- `regression-alerts`

维护时不要把 `workspace.yaml` 直接传给 `GraphStore` 或 `UnifiedStore`。入口应先通过 `WorkspaceStore(workspace).graph_db_path` 解析实际 SQLite 路径，或复用 core 层提供的 workspace helper。

For maintenance, public entrypoints accept `workspace.yaml`; resolve the graph database path through `WorkspaceStore` or shared core helpers before opening SQLite stores.

## 6. Hooks / Hook 接入

### 推荐自动执行

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

### 默认不要挂

- `UserPromptSubmit`

原因：普通自然语言请求过于依赖上下文，容易被宿主误处理成拦截步骤。

## 7. Host Strategy / 宿主策略

### Claude Code / Codex

默认建议：

- 生成 `SessionStart / PreToolUse / Stop`
- 不生成 `UserPromptSubmit`

### Cursor

更适合作为规则与工作流提示层，而不是强阻断执行层。

## 8. Security Model / 安全模型

Memory Center 默认是：

- 本地优先
- 读优先
- 不改业务源码

写入范围主要限于：

- `.memory-center/memory`
- `.memory-center/artifacts`
- 生成的 wiki / skills / dashboard

## 9. Unified Error Model / 统一错误模型

CLI、MCP、HTTP 的真实入口统一使用以下错误类型：

| Error Type | HTTP | Meaning |
|---|---:|---|
| `invalid_input` | 400 | 参数缺失、格式错误或不支持的操作 |
| `not_found` | 404 | workspace、route 或资源不存在 |
| `unavailable` | 503 | backend、连接或能力暂时不可用 |
| `conflict` | 409 | 与当前状态冲突 |
| `internal_error` | 500 | 未预期内部错误 |

入口行为：

- HTTP 保留 `ok=false` 和 `error`，并增加 `error_type`、可选 `suggested_action` 与 `diagnostics`。
- MCP tool 捕获入口异常并返回结构化错误 dict，便于 Agent 决定下一步。
- 安装后的 CLI 输出 `[error_type] message` 和可选建议，退出码为 1，不输出 traceback。
- 成功返回和现有 MCP tool schema 不变。

## 10. HTTP Bridge / HTTP 桥接

MCP 之外，还可通过 HTTP bridge 复用同一套能力：

```bash
memory-center serve-http --workspace /abs/path/.memory-center/workspace.yaml --host 127.0.0.1 --port 8765
```

## 11. Related Docs / 相关文档

- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
- [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [SPECIAL_NOTES.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECIAL_NOTES.md)
