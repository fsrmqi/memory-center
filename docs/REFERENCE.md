# Reference / 参考手册

## 1. CLI Command Groups / CLI 命令分组

### Workspace / Index

- `init`
- `reindex`
- `status`
- `serve-http`

### Query / Analysis

- `sniff`
- `query`
- `search-code`
- `symbol`
- `callers`
- `callees`
- `context`
- `impact`
- `plan-change`
- `verify-checklist`
- `detect-changes`
- `trace`

### Workflow / Session

- `work-start`
- `work-log`
- `work-sync`
- `work-resume`
- `work-resume-check`
- `work-handoff`
- `work-close`
- `work-health`
- `start-session`
- `log-session-event`
- `end-session`

### Memory / Eval

- `record-case`
- `suggest-case`
- `sync-sniff-artifacts`
- `sync-case-artifacts`
- `ref-get`
- `ref-batch`
- `memory-backend-query`
- `eval-write-quality`
- `eval-resume`
- `eval-handoff`
- `eval-regression-suite`
- `eval-index-freshness`
- `eval-tool-adoption`
- `eval-context-weight`
- `eval-agent-guidance`
- `eval-agent-guidance-adoption`
- `eval-agent-guidance-trend`
- `eval-token-gain`
- `eval-parser-benchmark`
- `eval-token-benchmark`
- `eval-token-benchmark-save`
- `eval-token-benchmark-compare`
- `eval-token-benchmark-trend`
- `discover`
- `constraint`
- `audit`
- `drill-ref`
- `drill-timeline`
- `drill-task`
- `backend-consistency`
- `onboard`
- `domain`
- `freshness`
- `context-pack`

### Artifact / Task Space

- `artifact create-task`
- `artifact list-tasks`
- `artifact resolve-task`
- `artifact health-task`
- `artifact health-tasks`
- `artifact repair-plan-task`
- `artifact repair-task`
- `artifact auto-archive-tasks`

`artifact repair-task` 默认 dry-run；传 `--apply` 才写入。刷新 `current-summary` 时建议同时传 `--intent`，修复器不会伪造 write receipt、自动归档相似任务空间或覆盖已有人工内容。

## 2. MCP Facade Parameters / MCP Facade 参数

### `mc_lookup`

常见 `mode`：

- `auto`
- `symbol`
- `code`
- `query`
- `trace`
- `chain`
- `context`
- `contracts`
- `ref`
- `backend`

`project` 参数：当同名符号存在于多个模块时，用 `project` 消歧。支持 FQN 自动推断（如 `cn.kaipuyun.cloud.openapi...ServiceImpl` → `ucap-cloud-open-api`）。

### `mc_analyze`

常见 `depth`：

- `quick`
- `standard`
- `full`

### `mc_admin`

常见 `action`：

- `status`
- `dashboard`
- `continuity`
- `health`
- `audit`
- `discover`
- `constraint`
- `drill_ref`
- `drill_timeline`
- `drill_task`
- `backend_consistency`
- `backend_query`
- `tool_usage_report`
- `task_health`
- `task_health_all`
- `task_repair_plan`
- `task_repair_apply`
- `task_resume_check`
- `eval_*`
- `group_*`

任务空间恢复相关 action：

- `task_health(task_id=...)`：检查单个任务空间健康度。
- `task_health_all()`：汇总任务空间健康度。
- `task_repair_plan(task_id=...)`：返回修复计划，不写入。
- `task_repair_apply(task_id=..., force=false, intent=...)`：默认 dry-run，`force=true` 时执行保守修复。
- `task_resume_check(task_id=...)`：返回恢复门禁，合并恢复包、健康度、修复建议、下一步动作、未解决事项和证据。

### `mc_context_pack`

常见参数：

- `query`
- `intent`
- `budget_tokens`
- `limit`

### `mc_onboard`

常见参数：

- `scope`
- `persona`
- `target`

### `mc_domain`

常见参数：

- `scope`
- `include_flows`

### `mc_freshness`

常见参数：

- `scope`

## 3. HTTP Endpoints / HTTP 端点

高频端点：

- `/workspace/status`
- `/workspace/sniff`
- `/workspace/query`
- `/workspace/search-code`
- `/workspace/symbol`
- `/workspace/callers`
- `/workspace/callees`
- `/workspace/trace`
- `/workspace/resume-packet`
- `/workspace/continuity-dashboard`
- `/workspace/dashboard`
- `/workspace/ref-get`
- `/workspace/ref-batch`
- `/workspace/memory-backend-query`
- `/workspace/work-start`
- `/workspace/work-sync`
- `/workspace/work-resume`
- `/workspace/work-resume-check`
- `/workspace/work-handoff`
- `/workspace/work-close`
- `/workspace/work-health`
- `/workspace/discover`
- `/workspace/constraint`
- `/workspace/audit`
- `/workspace/drill-ref`
- `/workspace/drill-timeline`
- `/workspace/drill-task`
- `/workspace/backend-consistency`
- `/workspace/eval-token-benchmark-trend`
- `/workspace/eval-agent-guidance-adoption`
- `/workspace/eval-agent-guidance-trend`
- `/workspace/eval-parser-benchmark`
- `/workspace/onboard`
- `/workspace/context-pack`
- `/workspace/freshness`
- `/workspace/business-flow`
- `/workspace/business-flow-impact`

## 4. Stable Schemas / 稳定协议

高频稳定返回：

- `resume_packet`
- `handoff_packet`
- `timeline_item`
- `workspace_dashboard`
- `workspace_continuity_dashboard`
- `eval_result`

Hybrid query / walkthrough 可附加：

- `retrieval_policy`
- `retrieval_diagnostics`
- `agent_next_steps`

Golden Benchmark summary 会聚合：

- `agent_next_step_count`
- `agent_next_step_action_counts`
- `agent_invalid_search_suggestion_count`
- `agent_invalid_search_reduction_rate`

Golden performance baseline / compare 会继续保存并比较这些字段；当 `agent_next_steps` 覆盖率下降、低效搜索建议增加或 reduction rate 下降时，`performance_gate.agent_guidance.passed=false`，整体 gate 也会失败。

日常运营视图也会暴露相同方向的轻量检查：

- `memory_eval_agent_guidance` / `eval-agent-guidance` / `/workspace/eval-agent-guidance`
- `memory_eval_agent_guidance_adoption` / `eval-agent-guidance-adoption` / `/workspace/eval-agent-guidance-adoption`
- `memory_eval_agent_guidance_trend` / `eval-agent-guidance-trend` / `/workspace/eval-agent-guidance-trend`
- `mc_admin(action="eval_agent_guidance")`
- `mc_admin(action="eval_agent_guidance_adoption")`
- `mc_admin(action="eval_agent_guidance_trend")`
- `workspace_dashboard.agent_guidance`

这些字段用于快速查看 `agent_next_step_count`、`agent_next_step_actions`、`invalid_search_suggestion_count` 和相关 findings。
Adoption 检查依赖 session event：先记录 `event_type="agent_guidance"` 或 `event_type="agent_next_steps"`，payload 中包含 `agent_next_steps`；再用后续 `tool_call` 判断建议动作是否被执行。
CLI `memory-center query --session-id ...`、HTTP `/workspace/query?session_id=...` 与 MCP `mc_lookup(session_id=...)` 会自动记录该 `agent_guidance` event。
趋势入口会追加 `.memory-center/memory/agent-guidance-trends.jsonl`，`generate_benchmark_report` 与 `check_regression_alerts` 会读取该文件并暴露 `agent_guidance_trends` / `agent_guidance` 告警摘要。

`resume_packet` 兼容保留既有字段，并可附加：

- `resume_readiness`
- `missing_context`
- `stale_artifacts`
- `must_read_refs`
- `confidence`
- `task_health`
- `repair_plan_hint`

## 5. Token Controls / Token 控制

高频大返回支持：

- `view=compact|full`
- `budget=small|medium|large`

其中：

- token benchmark：7 个高频函数
- evidence top-K：`small=3` / `medium=5` / `large=10`

## 6. Main Reading Order / 主阅读顺序

主线使用请优先看：

- [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [SPECIAL_NOTES.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECIAL_NOTES.md)
