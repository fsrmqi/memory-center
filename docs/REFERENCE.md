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
- `bootstrap-context`：`--path <project-dir>` 在不初始化 workspace 的前提下，优先复用已有 Memory Center，否则尝试只读 GitNexus，再返回有界本地搜索计划。

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

### Federated Bootstrap / 联邦初始化

- CLI：`memory-center bootstrap-context --path <project-dir> --intent "..." --query "..." --target "..."`
- HTTP：`GET /workspace/bootstrap-context?path=<project-dir>&intent=...&query=...&target=...`
- MCP：`mc_bootstrap_context(path="<project-dir>", intent="...", query="...", target="...")`
- 返回：`context_state=READY|FEDERATED|LIVE_SEARCH`、`provider`、`freshness`、`evidence`、`provider_selection`、`tool_plan`、`persistence`、`next_action`；`FEDERATED` 和 `LIVE_SEARCH` 额外返回 `evidence_ref`。
- `provider_selection`：能力路由的选中 Provider、尝试序列和 Provider Registry 描述；`evidence_ref`：只保留来源、范围、观测时间、耗时、内容哈希和验证状态的临时证据引用。
- `provider_selection.health`：进程内滑动窗口的 Provider P95、错误率和成本分；仅由实际调用更新，不触发后台探测或仓库扫描。GitNexus 明确未索引或陈旧时，`LIVE_SEARCH.action_cards` 提供确认型 `analyze --index-only` 建议。
- 边界：`bootstrap-context` 只使用 GitNexus 的 `status/query/context` 读取能力；读取结果最多保留在进程内 30 秒，绝不写入图谱或工作区。写入类操作只能经下方的 Provider Action 契约执行。

### Provider Actions / 外部 Provider 动作

- CLI：`memory-center provider-action --path <project-dir> --action impact --target <symbol>`。
- HTTP：`POST /workspace/provider-action?path=<project-dir>&provider=gitnexus&action=impact&target=<symbol>`。
- MCP：`mc_provider_action(action="impact", target="<symbol>")`。
- GitNexus 固定读取动作：`status`、`query`、`context`、`impact`、`trace`、`detect-changes`、`check`；`analyze` 是受控索引动作，`clean` 是破坏性清理动作，二者必须 `confirm=true`。
- 参数只能使用动作契约中的 `query`、`target`、`limit`、`depth`、`force`；系统不会转发任意 argv、shell 或外部正文。

### Restricted MCP Client Bridge / 受限 MCP Client Bridge

- CLI：`memory-center mcp-bridge-status --path <project-dir>` 查看策略；`memory-center mcp-bridge-action --path <project-dir> --provider <provider-id> --action <action> --query "..." --target "..."` 调用一个白名单动作。
- HTTP：`GET /workspace/mcp-bridge-status?path=<project-dir>`；`POST /workspace/mcp-bridge-action?path=<project-dir>&provider=<provider-id>&action=<action>&query=...&target=...&confirm=false`。
- MCP：`mc_mcp_bridge()` 查看策略；`mc_mcp_bridge(provider="<provider-id>", action="<action>", query="...", target="...", confirm=false)` 调用。
- 策略路径：`<project-dir>/.memory-center/provider-mcp-policy.json`。缺失或不合法策略只返回 `provider_not_configured`，不会初始化 workspace。

```json
{
  "schema_version": 1,
  "providers": [
    {
      "id": "idea_mcp",
      "server": "idea",
      "url": "http://127.0.0.1:64342/sse",
      "transport": "sse",
      "timeout_seconds": 10,
      "tools": [
        {
          "action": "symbol_context",
          "tool": "get_symbol_info",
          "mode": "read_only",
          "capabilities": ["code_navigation"],
          "arguments": {"symbol": "{target}", "query": "{query}"},
          "evidence_claim": {"subject": "{target}", "predicate": "symbol_context", "value": "available"}
        }
      ]
    }
  ]
}
```

- `url` 只能是 `http(s)`，传输只能是 `sse` 或 `streamable_http`；工具会在调用前由 `list_tools` 校验。参数模板只允许常量、`{query}` 与 `{target}`，单个值最长 2,000 字符；每次调用最长 60 秒，响应正文最多 12,000 字符。
- `read_only` 可以直接调用；`controlled_write` 与 `destructive` 必须 `confirm=true`。Bridge 不支持 stdio、token/认证字段、自由工具名、自由参数或任意 shell；外部正文仅在当前响应中返回，`evidence_ref` 不包含正文。
- MCP Server 运行时依赖固定为 `mcp>=1.2.0,<2.0.0`；SDK 2.x 不兼容当前 FastMCP Server 入口。

### Cross-Provider Evidence Fusion / 跨 Provider 证据融合

- CLI：`memory-center provider-evidence-fuse --path <project-dir> --evidence-json '<EvidenceRef JSON 数组>'`。
- HTTP：`POST /workspace/provider-evidence-fuse?path=<project-dir>&evidence_json=<JSON 数组>`。
- MCP：`mc_mcp_bridge(evidence_refs_json="<EvidenceRef JSON 数组>")`。
- Fusion 最多接收 20 条不含 `output/content/text/payload/body` 的 `evidence:*` 引用。只有至少两个独立 Provider 对相同 `claim.subject + claim.predicate` 提供值时，才会返回 `CONSISTENT` 或 `CONFLICT`；其它情况是 `INSUFFICIENT_EVIDENCE`。
- `CONFLICT` 返回 `verify_conflict` Action 和关联引用，要求补充测试、运行时或人工验证。没有 Claim 的引用不会因正文哈希不同而冲突。融合过程不写入 workspace、图谱、SQLite 或审计。

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
- `artifact delivery-record-validation`：默认只记录 `recorded_external` 摘要；显式传 `--evidence-kind manual_verified --actor <reviewer>` 会生成脱敏 `delivery-validation` 回执引用，可用于关闭和 Skill 门禁。人工验证缺少 actor、数组参数不是 JSON 数组时会明确拒绝。
- `artifact delivery-skill-candidate|delivery-skill-contract-update|delivery-skill-canary|delivery-skill-observe|delivery-skill-evaluate|delivery-skill-publish|delivery-skill-rollback|delivery-skill-recommend|delivery-skill-replay`：候选必须声明完整边界契约，并匹配真实验证回执后才可进入隔离灰度。成功观测只接受可解析的 `delivery-validation` 或执行器证据，同一回执不能重复计数。每次 canary 都有独立 `activation_id`；契约修订或回滚重启后仅统计当前 activation 与 `contract_sha256` 的观测和 replay。`minimum_verified_passed`（默认 3）由评估与发布共同使用；失败会阻断发布。默认推荐仅返回契约完整的 `published` Skill，并返回禁用、停止和回滚语义；registry 损坏时从有效备份恢复，双副本损坏则拒绝覆盖。
- `artifact asset-status|asset-sync|asset-register|asset-share|asset-approve|asset-bind|asset-loadout|wiki-document-ingest`：管理本地任务、Skill、Wiki、CodeGraph 协作资产。`asset-register` 必须提供与 `owner` 一致的 `actor`；既有资产的更新和绑定也只允许 owner。metadata 最大 16 KiB；`asset-status` / `asset-loadout` 采用默认总输出预算，可用 `max_chars` 收紧并查看 `truncated`。团队/受限共享必须先由 owner 提交、再由另一维护者审批，只有 active 且绑定匹配的资产会进入 Agent/角色 loadout。HTTP 读取使用 `GET /workspace/assets|/workspace/asset/loadout`，写入使用 `POST /workspace/asset/*` 和 `POST /workspace/wiki/document-ingest`；MCP 使用同名 `mc_admin` action。
- HTTP：`POST /workspace/delivery/skill/contract?task_id=<id>&payload=<JSON>` 更新契约；`GET /workspace/delivery/skill/replay?skill_id=<id>&limit=100` 读取 replay。MCP 使用 `mc_admin(action="delivery_skill_contract_update"|"delivery_skill_replay", ...)`。
- `artifact delivery-failure-candidates|delivery-skill-synthesize`：显式、离线地聚类跨任务失败和多个已验证交付的共同结构；只保存脱敏元数据和证据引用，不在查询热路径运行。

交付 `subtasks` 除 `code_targets` 外可附加 `read_targets`、`write_targets`、`stop_conditions`：分别表示实现前必须核实的目标、允许修改的范围，以及触发重新分析或请求决策的停止条件。`delivery-matrix` 与派生 `TECH_SPEC.md` 会展示范围契约覆盖率。工作区 `delivery-policy.json` 设置 `enforce_scope_contract: true` 后，进入 `implement` 前每个子任务必须同时具备上述范围字段；默认关闭，既有任务不受影响。
- `artifact compact-task --task-id <task>`：对超大任务工件进行流式 gzip 归档，保留有界恢复摘要；先执行 `artifact health-task` 识别异常空间。
- 成功 reindex 后会自动回收旧索引代际，只保留当前和上一代；`artifact generation-gc --workspace <workspace.yaml> --dry-run` 可在异常空间占用排查时预览同一回收策略，确认后追加 `--apply`。Agent 不得手工删除 generation 目录。
- `artifact index-export-cleanup --workspace <workspace.yaml> --dry-run`：预览由 SQLite `index_mirror` 覆盖的大型结构化索引 JSON 副本；确认后追加 `--apply`。运行时不从这些文件回退读取，未存在 SQLite canonical payload 的文件不会被删除。
- `artifact storage-legacy-cleanup --workspace <workspace.yaml> --dry-run`：检查已废弃的 `memory/memory.db` 副本；仅在运行时事实库已是 `graph/graph.db` 时允许 `--apply` 删除。
- `artifact assertion-sparsify --workspace <workspace.yaml> --dry-run`：预览可由图边派生的旧静态断言镜像，包括早期 `EXTRACTED`、已 superseded 的静态 SQLite 行及 `json_records` 镜像；确认后追加 `--apply`。此操作保留人工验证、拒绝和治理覆盖。
- `artifact assertion-vacuum --workspace <workspace.yaml> --dry-run`：预览 `graph.db` 重整；仅在确认没有 reindex 或写入任务时追加 `--apply` 回收稀疏化后的 SQLite 页。
- `artifact semantic-index-compact --workspace <workspace.yaml> --dry-run`：预览并在 `--apply` 后删除旧版 `semantic-node-index` 中与 SQLite 倒排、ANN 向量索引重复的全量文档镜像，不触发 reindex。
- `artifact storage-vacuum --workspace <workspace.yaml> --dry-run`：在大型存储清理后显式重整 `graph.db` 并回收 SQLite 空闲页；执行期间需要独占数据库。
- `artifact delivery-skill-eval-status`：检查可选外部 `skill-up` 评测器；未安装不会影响检索或交付流程。
- `artifact delivery-skill-eval-init --workspace <workspace.yaml> --skill-id <id>`：仅为已发布 Skill 创建脱敏 `eval.yaml` 与 `cases/` 骨架。
- `artifact delivery-skill-eval-run --workspace <workspace.yaml> --skill-id <id> --dry-run|--apply`：预览或显式执行固定的 `skill-up validate/run`，产出 JSON、JUnit、HTML；结果只能作为外部评测证据，不能自动发布 Skill。

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

HTTP 方法规则：GET 只读；会修改 workspace、记录会话、执行受控外部动作或导出工件的端点必须 POST。默认仅绑定 loopback；非回环 host 必须使用 `MEMORY_CENTER_HTTP_TOKEN`，通过 `Authorization: Bearer <token>` 校验。

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

输出中的 `receiver_shape_counts` 用于区分 `static_class_receiver`、`typed_receiver`、`untyped_instance_receiver` 与无接收者调用。`campaign` 会自动跳过 `external_or_missing_source` 和 `out_of_scope_target`，只在 `receiver_type_missing`、`missing_method_or_polymorphism`、`dynamic_or_unqualified` 中选择最大可证明类别，并在 `candidate_samples` 中给出脱敏逻辑锚点。静态类或缺失依赖源码的调用属于 `external_or_missing_source`，不能为了降低未解析率而合成为项目内调用边。仅对 campaign 选中的可复现类别建立 3-5 个私有 case，并运行：

```bash
memory-center eval-java-call-resolution --workspace <workspace.yaml> --cases <private-logical-cases.yaml>
memory-center release-gate --workspace <workspace.yaml> --java-call-cases <private-logical-cases.yaml>
memory-center eval-java-call-resolution-metrics --workspace <workspace.yaml>
```

`private-logical-cases.yaml` 仅保存 `Class#method` 逻辑锚点和预期关系，不得保存路径、源码片段、请求正文或密钥。

当 Tree-sitter Java 可用时，索引器会从 AST 补充 `receiver.first(...).second(...)` 的一段嵌套调用链，并且只在第一个调用的返回类型在当前工作区唯一、第二个方法显式存在或可由 Lombok 确定时创建边。正则解析无法平衡嵌套实参，因此不会猜测这类链路；Tree-sitter 不可用时仍保持保守未解析。

当 case 指定 `expected_resolution_levels` 时，该解析等级也是门禁条件。例如链式调用应填写 `chain_return_type`；即使目标方法仍能命中，解析等级退化也会失败。`eval-java-call-resolution-metrics` 只输出解析等级分布、`chain_return_type` 边/源数量、平均置信度和未解析率，适合在真实工作空间记录边增量，但不代替含 `forbidden_targets` 的私有精度 case。

Run the read-only diagnostic before creating private logical-anchor cases. `receiver_shape_counts` separates static/dependency calls from missing local receiver types. Never synthesize workspace call edges just to lower the unresolved rate; only promote reproducible local categories into a 3-5 case private suite and release gate.

When a case declares `expected_resolution_levels`, that level is gated too. For example, a chain case should declare `chain_return_type`; a generic fallback fails even if the target still matches. `eval-java-call-resolution-metrics` reports only aggregate resolution-level distribution, chain edge/source counts, mean confidence, and unresolved rate. Use it to observe real-workspace edge changes, not as a replacement for private cases with `forbidden_targets`.

The `campaign` skips `external_or_missing_source` and `out_of_scope_target`, selecting the largest locally provable category from `receiver_type_missing`, `missing_method_or_polymorphism`, and `dynamic_or_unqualified`. Its `candidate_samples` are redacted logical anchors for the 3-5 private cases; they are not evidence to synthesize a target edge. If no actionable category exists, review dependency or workspace-scope coverage instead of changing the resolver.

When Tree-sitter Java is available, the indexer supplements AST-proven one-hop nested chains such as `receiver.first(...).second(...)`. It creates a graph edge only when the first return type is unique in the workspace and the second method is explicit or a deterministic Lombok accessor. The regex fallback never guesses a nested-argument chain and remains conservatively unresolved when Tree-sitter is unavailable.

### 检索热路径性能 / Retrieval Hot Path Performance

定向 `reindex --path ...` 会返回 `bm25_sync_mode` 与 `bm25_changed_docs`。正常局部刷新为 `partial`，只替换受影响节点的 BM25 posting；旧格式索引首次升级可能返回 `full-legacy-fallback`，用于一次性迁移持久化词频，之后恢复局部更新。BM25 查询使用持久化词频和全局统计动态计分，局部刷新结果与完整重建一致。

升级到该格式但尚未执行 reindex 时，查询会继续使用旧索引中已保存的 BM25 分值；不会返回空结果。下一次显式重建才执行迁移。

Path-scoped `reindex --path ...` returns `bm25_sync_mode` and `bm25_changed_docs`. A normal scoped refresh reports `partial` and replaces postings only for affected nodes. A legacy index can report `full-legacy-fallback` once while persistent term frequencies are migrated, after which scoped updates resume. BM25 queries score from persisted term frequencies and global statistics, so partial results remain equivalent to a full rebuild.

定向 `reindex --path ...` 还会返回 `fts_sync_mode`、`fts_changed_nodes` 与 `fts_elapsed_ms`。局部刷新仅替换变更节点的 FTS 行；完整重建由 SQLite 内部 `INSERT ... SELECT` 写入 FTS，不会把全量节点先加载到 Python 内存。`fts_elapsed_ms` 是真实 workspace 重建性能门禁与排障的优先指标。

Path-scoped `reindex --path ...` also returns `fts_sync_mode`, `fts_changed_nodes`, and `fts_elapsed_ms`. Scoped refresh replaces only FTS rows for changed nodes; full rebuild uses SQLite-internal `INSERT ... SELECT` and never materializes all graph nodes in Python first. `fts_elapsed_ms` is a primary metric for real-workspace rebuild gates and diagnosis.

After an application upgrade but before reindex, queries continue to use the legacy persisted BM25 scores rather than returning empty results. Migration occurs only on the next explicit reindex.

Java 调用链中，`receiver.getField().target()` 只有在 `getField` 可由 Lombok 注解和字段事实验证、字段类型在工作区唯一且 `target` 在该类型源码中声明时，才会返回 `chain_lombok_accessor_return_type`。外部库、同名歧义或缺失字段类型不会建立调用边。

For Java chains, `receiver.getField().target()` returns `chain_lombok_accessor_return_type` only when Lombok annotations and field facts verify `getField`, the field type is unique in the workspace, and `target` is declared in that type's source. External libraries, ambiguous names, and missing field types never create a call edge.

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
