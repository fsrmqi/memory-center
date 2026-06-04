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
- `eval-token-gain`
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
- `eval_*`
- `group_*`

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
