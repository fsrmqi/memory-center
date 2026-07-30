# Reference / 参考手册

## 1. CLI Command Groups / CLI 命令分组

### Workspace / Index

- `init`
- `reindex`
- `status`
- `inspect`
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
- `export-evidence-subgraph`：显式导出 JSON / Markdown / HTML 证据子图；`--max-depth<=3`、`--max-edges<=120`，不扫描全图。
- `architecture-communities`：显式聚合项目社区、跨项目关系与高中心性节点；只传输 SQL 聚合结果。

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
- `eval-agent-guidance-adoption-trend`
- `eval-agent-guidance-replay`
- `eval-agent-guidance-replay-trend`
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

### Public Discovery Contract / 公开入口发现约定

每个公开能力必须在 CLI、HTTP 或 MCP 中至少有一个入口，并在 USER_GUIDE、MCP_GUIDE 与本参考手册中可发现。代码、`memory-center <command> --help`、HTTP route registry 与 MCP schema 是参数和返回字段的最终事实来源。

### Evidence Subgraph / 证据子图

- CLI：`export-evidence-subgraph --workspace <workspace.yaml> --target <node-id-or-symbol> --format json|markdown|html`
- HTTP：`GET /workspace/evidence-subgraph?target=...&direction=both&max_depth=2&max_edges=60&format=json`
- MCP：`mc_admin(action="evidence_subgraph_export", text="<node-id-or-symbol>")`
- 边界：最多 3 跳、120 条边、80 个节点；不读取源码、原始工具载荷或全图。

### Architecture Communities / 架构社区

- CLI：`architecture-communities --workspace <workspace.yaml> --limit 20`
- HTTP：`GET /workspace/architecture-communities?limit=20`
- MCP：`mc_admin(action="architecture_communities")`
- 边界：仅显式执行 SQL 聚合，最多返回 50 个关键节点；普通查询和 status 只读取已有摘要。

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

参数约束：

- `depth`：`quick|standard|full`。
- `direction`：`upstream|downstream|both`。
- `max_depth`：`1..6`；更深的分析应分阶段执行，避免无界图遍历。
- `execution_mode`：`sync|background`；后台模式返回 job，使用同一工具的 `job_action=status|cancel` 和 `job_id` 查询或取消。

稳定的 additive 返回字段：

- `analysis_status`：`complete|partial`。`partial` 表示影响图已返回，但计划、规则、契约、检查清单或工件写入中存在不可用阶段。
- `diagnostics`：按阶段返回安全状态、原因类别和下一步动作；入口错误还包含 `operation`、`exception_class`、`trace_id`。
- `candidate_paths`、`recommended_path`：优先验证的有界影响路径。

`analysis_status=partial` 不是空结果，也不是“无需影响”。调用方应保留 `impact` 作为当前证据，并按诊断补充或重试辅助阶段。

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

### 需求交付工作流 / Delivery workflow

- `workflow-profile` / `workflow-recommend`：按任务意图推荐 `quick-fix`、`contract-change`、`long-task`、`architecture` 或 `maintenance`。画像返回稳定工作区规则、架构证据、变更契约与当前子任务范围的分层加载建议；`maintenance` 面向健康检查、技术债治理和架构增量演进，不会替代既有交付状态机。
- `artifact delivery-init --workspace <workspace.yaml> --task-id <task>`：初始化 `feature_delivery_v2`。
- `artifact delivery-breakdown --source-refs '["req:..." ]' --summary '...'`：生成不写入的需求候选；候选必须确认后再写入契约。
- `artifact delivery-contract --kind requirements|subtasks|acceptance --items '<JSON数组>'`：写入结构化需求、代码定位子任务或验收标准。需求项应提供 `source_refs`、`scope`、`out_of_scope`、`search_terms`、`candidate_modules`、`ambiguities` 和 `acceptance_ids`。
- `artifact delivery-policy --policy '<JSON对象>'`：维护预注册验证 profile，例如 `{"validation_profiles":[{"id":"unit","argv":["mvn","test"],"timeout_sec":900}]}`；profile 使用 argv，禁止 shell 文本。
- `artifact delivery-execute-validation --profile-id unit --acceptance-ids '["AC-1"]'`：执行已注册 profile，保存受限输出摘要、hash 与证据文件。
- `artifact delivery-matrix --task-id <task>`：派生交付矩阵和只读 `TECH_SPEC.md`。
- `artifact delivery-transition --stage breakdown|locate|implement|verify|close`：按门禁推进；验收未被执行器或人工验证证据覆盖时不能关闭。
- `artifact delivery-record-validation`：仅记录外部验证摘要；默认 `recorded_external` 不可用于关闭门禁。
- `artifact delivery-skill-candidate|delivery-skill-canary|delivery-skill-observe|delivery-skill-evaluate|delivery-skill-publish|delivery-skill-rollback|delivery-skill-recommend`：Skill 必须先进入隔离灰度；仅三条以上带证据的成功观测、且无失败观测时可发布。默认检索仅返回 `published` 状态；回滚不删除证据。
- `artifact delivery-failure-candidates|delivery-skill-synthesize`：显式、离线地聚类跨任务失败和多个已验证交付的共同结构；只保存脱敏元数据和证据引用，不在查询热路径运行。

交付 `subtasks` 除 `code_targets` 外可附加 `read_targets`、`write_targets`、`stop_conditions`：分别表示实现前必须核实的目标、允许修改的范围，以及触发重新分析或请求决策的停止条件。`delivery-matrix` 与派生 `TECH_SPEC.md` 会展示范围契约覆盖率。工作区 `delivery-policy.json` 设置 `enforce_scope_contract: true` 后，进入 `implement` 前每个子任务必须同时具备上述范围字段；默认关闭，既有任务不受影响。
- `artifact compact-task --task-id <task>`：对超大任务工件进行流式 gzip 归档，保留有界恢复摘要；先执行 `artifact health-task` 识别异常空间。
- `artifact generation-gc --workspace <workspace.yaml> --dry-run`：预览可回收的旧索引代际；确认后追加 `--apply`。该命令始终保留当前和上一代，Agent 在发现 `index/generations` 占用异常时应先执行预览。
- `artifact storage-legacy-cleanup --workspace <workspace.yaml> --dry-run`：检查已废弃的 `memory/memory.db` 副本；仅在运行时事实库已是 `graph/graph.db` 时允许 `--apply` 删除。
- `artifact assertion-sparsify --workspace <workspace.yaml> --dry-run`：预览可由图边派生的旧 `EXTRACTED` 断言和 JSONL 导出；确认后追加 `--apply`。此操作保留人工验证、拒绝和治理覆盖。
- `artifact assertion-vacuum --workspace <workspace.yaml> --dry-run`：预览 `graph.db` 重整；仅在确认没有 reindex 或写入任务时追加 `--apply` 回收稀疏化后的 SQLite 页。

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
- `/workspace/eval-agent-guidance-adoption-trend`
- `/workspace/eval-agent-guidance-replay`
- `/workspace/eval-agent-guidance-replay-trend`
- `/workspace/eval-agent-guidance-trend`
- `/workspace/eval-parser-benchmark`
- `/workspace/onboard`
- `/workspace/context-pack`
- `/workspace/freshness`
- `/workspace/business-flow`
- `/workspace/business-flow-impact`
- `/workspace/delivery`
- `/workspace/delivery/init`
- `/workspace/delivery/contract`
- `/workspace/delivery/skill/canary`
- `/workspace/delivery/skill/observe`
- `/workspace/delivery/skill/evaluate`
- `/workspace/delivery/skill/recommend`
- `/workspace/delivery/skill/rollback`
- `/workspace/delivery/failure-candidates`
- `/workspace/delivery/skill/synthesize`

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

### Java 调用解析真实精度 / Java Call Resolution Precision

先执行只读诊断，再建立私有逻辑锚点案例；诊断不会读取或输出源码正文、文件路径或实际项目名：

```bash
memory-center eval-java-call-resolution-unresolved --workspace <workspace.yaml> --limit 30
```

输出中的 `receiver_shape_counts` 用于区分 `static_class_receiver`、`typed_receiver`、`untyped_instance_receiver` 与无接收者调用。静态类或缺失依赖源码的调用属于 `external_or_missing_source`，不能为了降低未解析率而合成为项目内调用边。只对 `receiver_type_missing`、`missing_method_or_polymorphism` 等可复现类别建立 3-5 个私有 case，并运行：

```bash
memory-center eval-java-call-resolution --workspace <workspace.yaml> --cases <private-logical-cases.yaml>
memory-center release-gate --workspace <workspace.yaml> --java-call-cases <private-logical-cases.yaml>
memory-center eval-java-call-resolution-metrics --workspace <workspace.yaml>
```

`private-logical-cases.yaml` 仅保存 `Class#method` 逻辑锚点和预期关系，不得保存路径、源码片段、请求正文或密钥。

当 case 指定 `expected_resolution_levels` 时，该解析等级也是门禁条件。例如链式调用应填写 `chain_return_type`；即使目标方法仍能命中，解析等级退化也会失败。`eval-java-call-resolution-metrics` 只输出解析等级分布、`chain_return_type` 边/源数量、平均置信度和未解析率，适合在真实工作空间记录边增量，但不代替含 `forbidden_targets` 的私有精度 case。

Run the read-only diagnostic before creating private logical-anchor cases. `receiver_shape_counts` separates static/dependency calls from missing local receiver types. Never synthesize workspace call edges just to lower the unresolved rate; only promote reproducible local categories into a 3-5 case private suite and release gate.

When a case declares `expected_resolution_levels`, that level is gated too. For example, a chain case should declare `chain_return_type`; a generic fallback fails even if the target still matches. `eval-java-call-resolution-metrics` reports only aggregate resolution-level distribution, chain edge/source counts, mean confidence, and unresolved rate. Use it to observe real-workspace edge changes, not as a replacement for private cases with `forbidden_targets`.

### 检索热路径性能 / Retrieval Hot Path Performance

定向 `reindex --path ...` 会返回 `bm25_sync_mode` 与 `bm25_changed_docs`。正常局部刷新为 `partial`，只替换受影响节点的 BM25 posting；旧格式索引首次升级可能返回 `full-legacy-fallback`，用于一次性迁移持久化词频，之后恢复局部更新。BM25 查询使用持久化词频和全局统计动态计分，局部刷新结果与完整重建一致。

升级到该格式但尚未执行 reindex 时，查询会继续使用旧索引中已保存的 BM25 分值；不会返回空结果。下一次显式重建才执行迁移。

Path-scoped `reindex --path ...` returns `bm25_sync_mode` and `bm25_changed_docs`. A normal scoped refresh reports `partial` and replaces postings only for affected nodes. A legacy index can report `full-legacy-fallback` once while persistent term frequencies are migrated, after which scoped updates resume. BM25 queries score from persisted term frequencies and global statistics, so partial results remain equivalent to a full rebuild.

After an application upgrade but before reindex, queries continue to use the legacy persisted BM25 scores rather than returning empty results. Migration occurs only on the next explicit reindex.

批量治理记录、语义编码向量和 ANN 标签/距离都会先校验数量一致再配对；这避免异常响应被静默截断，也使 macOS 默认 Python 的本地开发与生产解释器保持相同行为。

Governance batches, semantic vectors, and ANN label/distance pairs validate their counts before pairing. This prevents silent truncation and keeps macOS default-Python development behavior aligned with production interpreters.

普通 query 会在 `retrieval_diagnostics.timing_ms` 返回阶段耗时和缓存状态。缓存只在同一已发布图 generation、相同 query、配置、策略和新鲜度下生效，TTL 为 20 秒；命中缓存不会跳过新鲜度检查、治理动作或响应包装。

新鲜度优先读取已发布的 `graph-summary.json` 时间。运行时审计、治理与记忆记录共享 `graph.db`，它们的写入不会伪装为索引刷新，也不会使同一 generation 的检索缓存失效；缺少图摘要的旧工作空间才回退到图数据库时间。

`performance.timing_ms` 还会记录 query 外层阶段耗时；同样的聚合数值会写入操作审计，便于比较缓存命中前后的核心检索、断言摘要和 Action 开销。

同一 query 派生的 `agent_actions` 使用稳定 ID 去重：首次出现才写入治理 JSONL 与读模型，后续相同建议直接复用 ID，避免把普通读取变成重复写入负载。

`release-gate --query-samples 5` 会记录首查冷查询 P95、其余样本的热查询 P95 和 `stage_p95_ms`。热查询 P95 默认预算为 `2000ms`；超出时 `retrieval.reason=hot_query_p95_budget_exceeded`。仅在明确维护窗口可使用 `--max-hot-query-p95-ms 0` 关闭绝对预算。

Regular query responses expose stage timings and cache status under `retrieval_diagnostics.timing_ms`. The cache applies only to the same published graph generation, query, configuration, policy, and freshness for 20 seconds; cache hits do not bypass freshness, governance, or response wrapping.

Freshness prefers the published `graph-summary.json` timestamp. Runtime audit, governance, and memory records share `graph.db`; their writes neither masquerade as reindexing nor invalidate retrieval cache entries for the same generation. Legacy workspaces without a graph summary fall back to the graph database timestamp.

`performance.timing_ms` also covers outer query stages. The same aggregate values are stored in operation audit to compare core retrieval, assertion-summary, and action costs before and after a cache hit.

`agent_actions` derived from the same query are stable-ID deduplicated: only the first observation writes governance JSONL and the read model, and later identical recommendations reuse the ID instead of turning reads into write load.

`release-gate --query-samples 5` reports cold-query P95, hot-query P95, and `stage_p95_ms`. The default hot-query budget is `2000ms`; excess latency yields `retrieval.reason=hot_query_p95_budget_exceeded`. Only an explicit maintenance window should use `--max-hot-query-p95-ms 0` to disable the absolute budget.

日常运营视图也会暴露相同方向的轻量检查：

- `memory_eval_agent_guidance` / `eval-agent-guidance` / `/workspace/eval-agent-guidance`
- `memory_eval_agent_guidance_adoption` / `eval-agent-guidance-adoption` / `/workspace/eval-agent-guidance-adoption`
- `memory_eval_agent_guidance_adoption_trend` / `eval-agent-guidance-adoption-trend` / `/workspace/eval-agent-guidance-adoption-trend`
- `memory_eval_agent_guidance_replay` / `eval-agent-guidance-replay` / `/workspace/eval-agent-guidance-replay`
- `memory_eval_agent_guidance_replay_trend` / `eval-agent-guidance-replay-trend` / `/workspace/eval-agent-guidance-replay-trend`
- `memory_eval_agent_guidance_trend` / `eval-agent-guidance-trend` / `/workspace/eval-agent-guidance-trend`
- `mc_admin(action="eval_agent_guidance")`
- `mc_admin(action="eval_agent_guidance_adoption")`
- `mc_admin(action="eval_agent_guidance_adoption_trend")`
- `mc_admin(action="eval_agent_guidance_replay")`
- `mc_admin(action="eval_agent_guidance_replay_trend")`
- `mc_admin(action="eval_agent_guidance_trend")`
- `workspace_dashboard.agent_guidance`

这些字段用于快速查看 `agent_next_step_count`、`agent_next_step_actions`、`invalid_search_suggestion_count` 和相关 findings。
Adoption 检查依赖 session event：先记录 `event_type="agent_guidance"` 或 `event_type="agent_next_steps"`，payload 中包含 `agent_next_steps`；再用后续 `tool_call` 判断建议动作是否被执行。
CLI `memory-center query --session-id ...`、HTTP `/workspace/query?session_id=...` 与 MCP `mc_lookup(session_id=...)` 会自动记录该 `agent_guidance` event。
MCP 服务器会自动记录所有工具调用到 `mcp-invocations.jsonl`；当调用带 `session_id`，或同一 MCP 进程此前执行过 `mc_start`，还会自动写入对应 session 的 `tool_call` event。因此 replay 和 adoption 验证无需再手工补记 Memory Center 工具调用。
`mcp-invocations.jsonl` 采用固定保留窗口：最近 30 天且最多 100,000 条。读取会立即应用该窗口；64 KiB 以内的日志同步裁剪，更大的日志由后台执行物理压缩，避免占用 MCP 请求线程。SQLite 运行记录与 JSONL 导出使用同一裁剪操作收口。
MCP 审计事件会带 `trace_id`、可选 `thread_id` / `turn_id`、Memory Center 版本和 active index generation，便于在索引或工具版本变化后区分历史效果。宿主 Hook 的非 MCP 工具事件写入 `host-interactions.jsonl`，字段经过白名单和路径/secret 脱敏；原始对话正文、源码和 payload 不会写入该账本。`mcp-effect-summary.json` 仅保存聚合指标，用于 Workbench 和回归观察。
生命周期按数据层级区分：MCP/宿主原始交互 30 天、session event 90 天、session summary 365 天，单类最多 100,000 条；case、任务工件和汇总指标作为可复用知识不会被此清理任务删除。
Replay 检查会进一步把每条建议分类为 `adopted`、`missed`、`bypassed` 或 `unobservable`，并给出 `reason_counts`，用于定位是本地搜索绕过、后续工具不可观测、建议缺少可执行命令，还是 Memory Center 工具调用与建议动作不匹配。它按同一 session 中后续工具事件的出现顺序判定：若本地搜索先于匹配的 Memory Center 工具出现，该建议仍为 `bypassed`。本地搜索只依据结构化工具名或 shell 的 `cmd` / `command` / `script` 字段识别，不扫描 payload 任意文本，避免普通内容误报。
趋势入口会追加 `.memory-center/memory/agent-guidance-trends.jsonl`、`.memory-center/memory/agent-guidance-adoption-trends.jsonl` 与 `.memory-center/memory/agent-guidance-replay-trends.jsonl`，`generate_benchmark_report` 与 `check_regression_alerts` 会读取这些文件并暴露 `agent_guidance_trends`、`agent_guidance_adoption_trends`、`agent_guidance_replay_trends` 以及对应告警摘要。
`agent-guidance-adoption-trends.jsonl` 会保存 `missed_action_counts`；当最新退化趋势中某个 action 反复 missed 时，query 返回的 `agent_next_steps` 会附加 `adoption_feedback` 并强化 command。
`agent-guidance-replay-trends.jsonl` 会保存 `reason_counts`；当最新退化趋势显示绕过、不可观测、缺 target 或动作不匹配时，query 返回的 `agent_next_steps` 会附加 `replay_feedback`，并把 command 强化成对应的第一步工具、`session_id`、`target_ref/read_targets` 或 Memory Center mode。方法级 `switch_to_walkthrough` 在有已解析路径时也会返回 `target_ref` 与 `read_targets`。

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
