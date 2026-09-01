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
- `query`：检索预算按任务 purpose（`full_chain` / `contract_change` / `quick_fix` / `general`，由意图确定性归并）倾斜——契约类查询获得更宽的候选与证据预算，快速修复类收窄；`query_plan.purpose` 透出归并结果。传入 `session_id` 时，本会话此前已交付过的文件会被有界降权（`_served_before` 标记，账本失败降级为不去重）。 / retrieval budgets are tilted by deterministic task purpose (contract queries widen, quick fixes narrow) and previously served files are bounded-downweighted when `session_id` is provided; ledger failures degrade to no dedup.
- `resume` 相关链路（`resume-context` / `work-resume`）：related cases 按**热度**（命中次数 × 7 天半衰期时间衰减，命中信号来自既有 `agent_guidance` 事件）重排；零命中 case 保持原序，统计失败降级为原排序。 / related cases are re-ranked by hotness (hit count × exponential decay) using existing guidance events; zero-hit cases keep their original order and failures degrade gracefully.
- `change-review`：统一执行有界定向刷新、加权影响路径、测试/契约风险和验证 Action。
- `trace`
- `export-evidence-subgraph`：显式导出 JSON / Markdown / HTML 证据子图；`--max-depth<=3`、`--max-edges<=120`，不扫描全图。
- `architecture-communities`：显式聚合项目社区、跨项目关系与高中心性节点；只传输 SQL 聚合结果。
- `eval-cochange`：用有界 Git 共变历史独立评测图影响预测，只返回哈希引用和聚合指标。

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
- `session-archive-plan`：仅返回按逻辑轮次计算的归档边界；`session_end` / `session_close` 所在整轮始终保留。 / returns the logical-turn archive boundary only; the complete turn containing `session_end` / `session_close` always stays live.
- `session-archive`：显式执行同一归档计划，将完整旧轮次迁移至 `memory/session-events-archive.jsonl`；按事件完整内容精确迁移，不依赖时间戳裁剪。 / explicitly executes that plan and moves complete old turns by exact event content rather than timestamp cutoffs.

### Memory / Eval

- `record-case`：可传 `--case-type <type>` 选择 `rules/case-schemas.yaml` 中的 schema，并以 `--extra-fields '{"situation":"## Situation\\n..."}'` 写入 schema 扩展字段。未知字段会被忽略，校验结果随响应的 `schema_validation` 返回而不阻断旧记录。 / use `--case-type <type>` to select a schema and `--extra-fields` for its extension fields; unknown fields are ignored and validation remains additive.
- `suggest-case`
- `consolidate-session`：把多个已结束会话整合为 L1 case / L3 记忆块候选。默认 dry-run；`--stage` 将候选写入 append-only 待审核池，随后用 `decide-consolidation-candidate` 逐条审批或拒绝。`--apply` 保留为直接显式写入无冲突 ADD 的模式，不能与 `--stage` 同用。既有 current-truth case 或同批重复会话返回 REVIEW、不会写入；已失效 case 不阻止新的 ADD。`--include-l3` 额外产出 L3 memory-block 追加草稿（不自动写入）。
- `consolidation-candidates`：列出 staged 的 `pending|applied|rejected` 多会话整合候选；空 `--status` 返回全部。
- `decide-consolidation-candidate`：维护者以 `approve|reject` 逐条处理候选。approve 只允许无冲突 ADD，写入前会重新检查 current-truth case，避免暂存期间状态变化导致重复写入。
- `eval-session-recall`：读取工作区外的私有 YAML case，通过实际 resume 链路评测 L1 case 召回；仅输出 case ID 与 query/session 哈希，分类为 `hit`、`case_not_indexed`、`retrieval_miss`、`ranking_miss` 或 `evidence_insufficient`，不修改检索策略或工作区状态。
- `agent-execution-import`：显式、幂等导入 DSH 本地插件写入的脱敏 NDJSON inbox；不读取 prompt、工具参数/结果或 cwd。
- `agent-execution-summary`：按 DSH session 聚合 turn/step/model/tool 耗时、首 Token、Token 数与失败；session ID 仅返回哈希。
- `dsh-delivery-capture`：写入一条 completion-signalled DSH 最终摘要为独立 L0 会话；输入为 `workspace`、`source-session-id`、`summary` 与可选 `turn/step`，最多保存 1400 字符，不写入完整 transcript 或自动发布 Case。
- `wiki-assets-sync`：将指定 Personal Assistant Wiki 根目录中的明确入口登记为私有 Wiki 资产；输入 `workspace`、`wiki-root`、`owner` 与可选 `scope`，只持久化 `pawiki:` 反向引用、内容哈希和范围。
- `wiki-promotion-preview|wiki-promotion-confirm`：前者从已捕获的 DSH 交付摘要生成长期知识预览且不写 Wiki；后者必须显式提供 `owner`，确认后才调用 Personal Wiki 晋升并登记新的反向资产链接。
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
- `eval-reasoning-prompts`
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

### Quality, replay, and maintenance / 质量、回放与维护（4.6.8）

- `quality-gate --workspace <workspace.yaml>`：只读汇总 generation、coverage、retrieval replay、IR diff、分桶刷新预算与存储 dry-run；状态为 `pass|attention|block|real_case_missing`，绝不执行 reindex/GC/VACUUM/用户命令。
- `eval-retrieval-replay-cases --workspace <workspace.yaml> --cases <private-cases.yaml> --queries <private-query-map.json>`：运行显式、脱敏的真实 retrieval replay。私有 case 与查询映射必须在仓库外；结果仅保留 case ID、类别、聚合质量与性能指标。
- `scoped-refresh-performance --workspace <workspace.yaml>`：按 `category + scope` bucket 返回 P50/P95、预算与 dominant stage。少于 5 条真实样本或 legacy 无 bucket 样本不构成超预算门禁。
- `artifact index-export-cleanup|generation-gc|semantic-index-compact|storage-vacuum`：均先 `--dry-run`，只有显式 `--apply` 才写入或删除。运行时事实以 SQLite 为准；`RUNTIME_ONLY_INDEXES` 的 JSON 副本不是查询回退。

`change-review` 返回 additive `validation_plan`，它描述最小可证伪验证、停止条件、回滚和证据要求，不会执行测试命令。MQ destination 在没有本地可证明映射时必须返回 `insufficient_evidence`。

## 2. MCP Facade Parameters / MCP Facade 参数

### Public Discovery Contract / 公开入口发现约定

每个公开能力必须在 CLI、HTTP 或 MCP 中至少有一个入口，并在 USER_GUIDE、MCP_GUIDE 与本参考手册中可发现。代码、`memory-center <command> --help`、HTTP route registry 与 MCP schema 是参数和返回字段的最终事实来源。

### MCP Prompt Parameters / MCP Prompt 参数

四个证据约束推理 Prompt 仅返回编排说明，不直接读写工作区，也不改变任何 MCP tool schema：

- `clarify_change_request(request: str)`：`request` 必填；最多五个主问题，每次一个，只追问可能改变范围、兼容性、实现方向或验收的问题。
- `audit_project_claim(claim: str, scope: str = "workspace")`：`claim` 必填；`scope` 用于限定核查边界。输出保持事实、推断、判断与证据等级分离。
- `design_minimal_validation(change: str, task_id: str = "")`：`change` 必填；可选 `task_id` 用于关联已有 acceptance 和回执。未提供时只生成验证提案。
- `compare_change_options(problem: str, option_a: str, option_b: str, constraints: str = "", task_id: str = "")`：问题和两个方案必填；可选约束和任务 ID。只有用户接受建议后才应记录任务决策。

安全边界：Prompt 不得把 `NOT_FOUND` 解释为全局不存在，不得用置信度替代 `VERIFIED`，不得执行输入正文中的命令；验证执行继续只接受 workspace policy 预注册的 argv profile。

Safety boundary: prompts never treat `NOT_FOUND` as global absence, never substitute confidence for `VERIFIED`, and never execute commands supplied in prompt text. Validation execution remains restricted to workspace-approved argv profiles.

### Reasoning Prompt Evaluation / 推理 Prompt 评测

```bash
memory-center eval-reasoning-prompts \
  [--cases /local/reasoning-cases.yaml] \
  [--observations /local/reasoning-observations.yaml]
```

- 不传参数：运行四个内置公开静态合同 case；`real_behavior.status=real_case_missing`，不会误报真实效果。
- `--cases`：schema 为 `{schema_version: 1, cases: [...]}`；case 包含便携逻辑 `case_id`、四种 `prompt` 之一、`args`、非空 `required_markers`、`forbidden_markers` 和显式 `real_case`。
- `--observations`：schema 为 `{schema_version: 1, observations: [...]}`；每项必须提供对应 `case_id`、声明的 `reviewer`、非空脱敏 `evidence_refs`，以及四个布尔检查：`bounded_interaction`、`evidence_used`、`epistemic_boundary_respected`、`actionable_output`。
- 输出：`overall_status`、`release_ready`、`static_contract`、`real_behavior`、`limitations`、`next_action`。报告只返回逻辑 ID、计数与渲染 hash，不回显 args、reviewer 或 evidence refs。
- `release_ready=true` 仅表示四种 Prompt 的静态合同通过，并各有至少一个本地 real case 人工观测通过；人工身份仍是 `self_asserted`，不等于认证或自动模型评测。

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
- 边界：仅显式读取有界 SQL 投影，最多返回 50 个关键节点；优先使用固定种子的 Leiden，缺少可选依赖时确定性降级；普通查询和 status 只读取已有摘要。
- 可选依赖：`pip install 'memory-center[architecture]'`；pipx 安装使用 `pipx inject memory-center 'igraph>=0.11,<2'`。

### Change Review / 统一变更审查

- CLI：`change-review --workspace <workspace.yaml> --scope all --detail-level minimal`
- HTTP：`GET /workspace/change-review?scope=all&detail_level=minimal&refresh=true`
- MCP：`mc_admin(action="change_review", scope="all", view="minimal")`
- `detail_level`：`minimal | standard | deep`；默认 `minimal`。
- 边界：定向刷新最多 12 个相关文件，绝不隐式全量 reindex；同一源码签名与 generation 的等价调用复用短期缓存。
- 返回：`risk`、`changed_nodes`、`impact_paths`、`test_gaps`、`contract_risks`、`actions`、`invocation_budget`、`stop_conditions`、`cache`。

### Git Co-change Evaluation / Git 共变独立评测

- CLI：`eval-cochange --workspace <workspace.yaml> --max-commits 20`
- HTTP：`GET /workspace/eval-cochange?max_commits=20`
- MCP：`mc_admin(action="eval_cochange", limit=20)`
- 发布门禁：`release-gate --workspace <workspace.yaml> --cochange-commits 20`
- 真值：同一 Git 提交中除种子外的其他变更文件；图邻居只作为预测，不作为自证真值。
- 隐私：只返回哈希引用与聚合指标，不保存路径、提交消息或源码；执行错误使用 `environment_error`，不计入 precision/recall。

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
- `artifact delivery-policy --policy '<JSON对象>'`：维护预注册验证 profile，例如 `{"validation_profiles":[{"id":"unit","argv":["mvn","test"],"timeout_sec":900,"evidence_types":["unit-test"]}]}`；profile 使用 argv，禁止 shell 文本。
- `artifact delivery-execute-validation --profile-id unit --acceptance-ids '["AC-1"]'`：执行已注册 profile，保存受限输出摘要、hash 与证据文件。
- `artifact delivery-matrix --task-id <task>`：派生交付矩阵和只读 `TECH_SPEC.md`。
- `artifact delivery-transition --stage breakdown|locate|implement|verify|close`：按门禁推进；验收未被执行器或人工验证证据覆盖时不能关闭。
- `artifact delivery-record-validation`：默认只记录 `recorded_external` 摘要；显式传 `--evidence-kind manual_verified --actor <reviewer> --evidence-types '["contract-gate"]'` 会生成脱敏 `delivery-validation` 回执引用和结构化证据类型，可用于关闭和 Skill 门禁。返回的 `identity_assurance=self_asserted` 表示 actor 是调用方声明而非认证身份。人工验证缺少 actor、数组参数不是纯字符串 JSON 数组时会明确拒绝。回执 JSONL 是审计源；SQLite 通过版本化、锁内分批投影维护最近回执与稀疏验收覆盖，入口无需全量扫描历史。
- `artifact delivery-skill-candidate|delivery-skill-contract-update|delivery-skill-canary|delivery-skill-observe|delivery-skill-evaluate|delivery-skill-publish|delivery-skill-rollback|delivery-skill-recommend|delivery-skill-replay`：候选必须声明完整边界契约，并匹配真实验证回执后才可进入隔离灰度。成功观测只接受可解析的 `delivery-validation` 或执行器证据，同一回执不能重复计数。每次 canary 都有独立 `activation_id`；契约修订或回滚重启后仅统计当前 activation 与 `contract_sha256` 的观测和 replay。`minimum_verified_passed`（默认 3）由评估与发布共同使用；失败会阻断发布。默认推荐仅返回契约完整的 `published` Skill，并返回禁用、停止和回滚语义；registry 损坏时从有效备份恢复，双副本损坏则拒绝覆盖。
- `artifact asset-status|asset-sync|asset-register|asset-share|asset-approve|asset-bind|asset-loadout|wiki-document-ingest`：管理本地任务、Skill、Wiki、CodeGraph 协作资产。`asset-register` 必须提供与 `owner` 一致的 `actor`；既有资产的更新和绑定也只允许 owner。metadata 最大 16 KiB；`asset-status` / `asset-loadout` 采用默认总输出预算，可用 `max_chars` 收紧并查看 `truncated`。团队/受限共享必须先由 owner 提交、再由另一维护者审批，只有 active 且绑定匹配的资产会进入 Agent/角色 loadout。HTTP 读取使用 `GET /workspace/assets|/workspace/asset/loadout`，写入使用 `POST /workspace/asset/*` 和 `POST /workspace/wiki/document-ingest`；MCP 使用同名 `mc_admin` action。
- HTTP：`POST /workspace/delivery/skill/contract?task_id=<id>&payload=<JSON>` 更新契约；`GET /workspace/delivery/skill/replay?skill_id=<id>&limit=100` 读取 replay。MCP 使用 `mc_admin(action="delivery_skill_contract_update"|"delivery_skill_replay", ...)`。
- `artifact delivery-failure-candidates|delivery-skill-synthesize`：显式、离线地聚类跨任务失败和多个已验证交付的共同结构；只保存脱敏元数据和证据引用，不在查询热路径运行。

交付 `subtasks` 除 `code_targets` 外可附加 `read_targets`、`write_targets`、`stop_conditions`：分别表示实现前必须核实的目标、允许修改的范围，以及触发重新分析或请求决策的停止条件。`delivery-matrix` 与派生 `TECH_SPEC.md` 会展示范围契约覆盖率。工作区 `delivery-policy.json` 设置 `enforce_scope_contract: true` 后，进入 `implement` 前每个子任务必须同时具备上述范围字段；默认关闭，既有任务不受影响。

交付 `acceptance` 可兼容性附加以下字段，CLI、HTTP `/workspace/delivery/contract` 与 MCP `delivery_contract_update` 使用同一 items 结构：

```json
{
  "id": "AC-1",
  "title": "旧客户端兼容",
  "critical_hypothesis": "旧客户端仍能解析新响应",
  "continue_if": "旧版回归和契约门禁均通过",
  "stop_if": "旧版反序列化失败",
  "rollback": "恢复旧契约并撤回新增字段",
  "evidence_required": ["contract-gate", "executor-receipt"]
}
```

五个字段均为 additive：旧 acceptance 缺少字段时以空值读取，默认流程仍可推进。矩阵输出同名字段、`validation_design_complete`，coverage 增加 `designed_acceptance` 与 `validation_design_coverage`；`TECH_SPEC.md` 和 resume hints 同步展示缺口。工作区策略设置 `enforce_validation_design_contract: true` 后，必需 acceptance 缺少任一字段会在进入 `locate` 时返回 `validation_design_required`；默认关闭。

可信通过回执可附加 `evidence_types`。执行器回执自动包含 `executor-receipt` 和 `profile:<id>`，并合并 profile 预声明类型；旧 `manual_verified` 回执可推导 `manual-verification`。矩阵为每项验收派生 `evidence_observed`、`evidence_missing`、`evidence_complete`、`evidence_receipt_ids`，coverage 增加 `evidence_complete_acceptance` 与 `evidence_contract_coverage`。设置 `enforce_evidence_contract: true` 后，关闭任务前必须由可信通过回执覆盖全部 `evidence_required`，否则返回 `evidence_contract_required`；默认关闭。
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
- `/workspace/workbench-summary`
- `/workspace/impact`
- `/workspace/consolidation-candidates`
- `/workspace/agent-execution-summary`
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
memory-center eval-java-call-resolution --workspace <workspace.yaml> --cases <private-logical-cases.yaml> --fail-on-unexpected-high-confidence --fail-on-forbidden-high-confidence
memory-center release-gate --workspace <workspace.yaml> --java-call-cases <private-logical-cases.yaml> --cochange-commits 20
memory-center eval-java-call-resolution-metrics --workspace <workspace.yaml>
```

`private-logical-cases.yaml` 仅保存 `Class#method` 逻辑锚点和预期关系，不得保存路径、源码片段、请求正文或密钥。

当 Tree-sitter Java 可用时，索引器会从 AST 补充 `receiver.first(...).second(...)` 的一段嵌套调用链，并且只在第一个调用的返回类型在当前工作区唯一、第二个方法显式存在或可由 Lombok 确定时创建边。正则解析无法平衡嵌套实参，因此不会猜测这类链路；Tree-sitter 不可用时仍保持保守未解析。

当 case 指定 `expected_resolution_levels` 时，该解析等级也是门禁条件。例如链式调用应填写 `chain_return_type`；即使目标方法仍能命中，解析等级退化也会失败。`eval-java-call-resolution-metrics` 只输出解析等级分布、`chain_return_type` 边/源数量、平均置信度和未解析率，适合在真实工作空间记录边增量，但不代替含 `forbidden_targets` 的私有精度 case。

4.3.81 起，调用接收者类型按具体重载的方法体提取；同名重载的参数和局部变量不会相互覆盖。case 的 `source` 仍是 `Class#method`，因此会聚合同名重载的边：其他重载的合法目标应放入 `allowed_targets`，禁止目标必须对该方法的全部重载都不成立。

4.3.82 支持显式 `(Type value) -> ...` Lambda，以及标准 `Consumer / Function / Predicate / Bi* / *Operator` 变量赋值中的输入泛型映射。作用域严格限制在 Lambda 块或表达式内。第三方方法的无类型 Lambda、仅凭 `Type.class` 的回调和无法唯一映射的泛型保持 `receiver_type_missing`。

4.3.83 支持从方法参数、局部变量和显式可见字段读取 `List<T>`、`Set<T>`、`Collection<T>`、`Iterable<T>`、`Stream<T>`，为紧邻的直接 `map/filter/forEach/...` Lambda 提供输入类型；`Map<K,V>.forEach((k,v) -> ...)` 映射键和值。通配符、裸类型、单字母类型变量、第三方容器，以及类型变换 `map/flatMap` 后的后续 Lambda 不参与推导。该能力只影响索引期调用事实，不改变 CLI、HTTP 或 MCP 查询 schema。

4.3.84 的 partial reindex 在既有 `timing_ms` 中增加四个字段：`generation_inherit`、`generation_service_payloads`、`generation_graph_shards`、`generation_shared_shards`，单位均为毫秒。物理 generation 的 `manifest.json` 还包含 `graph_export_mode=sqlite_attach_select`、`graph_export_workers` 和同一组子阶段耗时。字段只增不删；全量 reindex 的 worker 固定为 1，局部多项目最多为 3。

Run the read-only diagnostic before creating private logical-anchor cases. `receiver_shape_counts` separates static/dependency calls from missing local receiver types. Never synthesize workspace call edges just to lower the unresolved rate; only promote reproducible local categories into a 3-5 case private suite and release gate.

When a case declares `expected_resolution_levels`, that level is gated too. For example, a chain case should declare `chain_return_type`; a generic fallback fails even if the target still matches. `eval-java-call-resolution-metrics` reports only aggregate resolution-level distribution, chain edge/source counts, mean confidence, and unresolved rate. Use it to observe real-workspace edge changes, not as a replacement for private cases with `forbidden_targets`.

Since 4.3.83, direct JDK collection Lambdas may receive deterministic input types from generic method parameters, locals, and explicitly visible fields. Wildcards, raw and third-party containers, type variables, and downstream Lambdas after a type-changing operation remain unresolved by design.

Since 4.3.84, partial reindex reports four additive generation timing fields for inheritance, service payloads, graph shards, and shared shards. Physical manifests expose the SQLite streaming export mode and bounded worker count; full reindex remains single-worker.

The `campaign` skips `external_or_missing_source` and `out_of_scope_target`, selecting the largest locally provable category from `receiver_type_missing`, `missing_method_or_polymorphism`, and `dynamic_or_unqualified`. Its `candidate_samples` are redacted logical anchors for the 3-5 private cases; they are not evidence to synthesize a target edge. If no actionable category exists, review dependency or workspace-scope coverage instead of changing the resolver.

When Tree-sitter Java is available, the indexer supplements AST-proven one-hop nested chains such as `receiver.first(...).second(...)`. It creates a graph edge only when the first return type is unique in the workspace and the second method is explicit or a deterministic Lombok accessor. The regex fallback never guesses a nested-argument chain and remains conservatively unresolved when Tree-sitter is unavailable.

4.3.78 将 enum 编译器方法、外部返回类型链和间接继承外部框架方法拆分为独立未解析原因。它们是可解释的索引边界，不属于本地目标缺失；campaign 不会再把这些样本推荐为 resolver 修复对象。真实 case 应同时声明 allowed/forbidden target，并启用两个严格失败参数。

### 检索热路径性能 / Retrieval Hot Path Performance

定向 `reindex --path ...` 会返回 `bm25_sync_mode` 与 `bm25_changed_docs`。正常局部刷新为 `partial`，只替换受影响节点的 BM25 posting；旧格式索引首次升级可能返回 `full-legacy-fallback`，用于一次性迁移持久化词频，之后恢复局部更新。BM25 查询使用持久化词频和全局统计动态计分，局部刷新结果与完整重建一致。

升级到该格式但尚未执行 reindex 时，查询会继续使用旧索引中已保存的 BM25 分值；不会返回空结果。下一次显式重建才执行迁移。

Path-scoped `reindex --path ...` returns `bm25_sync_mode` and `bm25_changed_docs`. A normal scoped refresh reports `partial` and replaces postings only for affected nodes. A legacy index can report `full-legacy-fallback` once while persistent term frequencies are migrated, after which scoped updates resume. BM25 queries score from persisted term frequencies and global statistics, so partial results remain equivalent to a full rebuild.

定向 `reindex --path ...` 还会返回 `fts_sync_mode`、`fts_changed_nodes` 与 `fts_elapsed_ms`。局部刷新仅替换变更节点的 FTS 行；完整重建由 SQLite 内部 `INSERT ... SELECT` 写入 FTS，不会把全量节点先加载到 Python 内存。`fts_elapsed_ms` 是真实 workspace 重建性能门禁与排障的优先指标。

Path-scoped `reindex --path ...` also returns `fts_sync_mode`, `fts_changed_nodes`, and `fts_elapsed_ms`. Scoped refresh replaces only FTS rows for changed nodes; full rebuild uses SQLite-internal `INSERT ... SELECT` and never materializes all graph nodes in Python first. `fts_elapsed_ms` is a primary metric for real-workspace rebuild gates and diagnosis.

4.3.79 的局部刷新还返回 `timing_ms` 与 `refresh_performance`。查看聚合趋势：

```bash
memory-center scoped-refresh-performance --workspace <workspace.yaml> --limit 20
```

HTTP 使用 `GET /workspace/scoped-refresh-performance`，MCP 使用 `mc_admin(action="scoped_refresh_performance", limit=20)`。记录只包含 scope 数量、generation 和阶段耗时；默认总耗时预算为 `10000ms`，可用 `MEMORY_CENTER_SCOPED_REFRESH_BUDGET_MS` 显式调整。

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

`release-gate --cochange-commits 20` 增加独立 `cochange_impact` 组件。4.3.80 使用 `git_cochange_walk_forward_v3`：默认 5 个预热提交，训练事实严格早于评估提交；当前图指标只作诊断。可执行 case 不足、Git 环境错误、时间约束缺失，或 Precision/Recall 低于过去热门文件基线都会阻断该可选组件；未传参数时保持 `skipped`。

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

## 6. Specs / 规格说明

### 6.1 workspace.yaml

核心字段：`workspace`、`root`、`services`、`registry`、`embedding_backend`。每个 service 典型字段：`path`、`type`、`service_name`、`language`、`stack`。

### 6.2 rules

规则文件位于 `.memory-center/rules/`。高频规则：`global-rules.yaml`、`auto-sync-rules.yaml`、`resume-rules.yaml`、`handoff-rules.yaml`、`write-policy-rules.yaml`、`eval-rules.yaml`。规则应至少包含 `id`、`title`、`severity`、`when`、`message`。

### 6.3 hooks.yaml

支持事件：`session_start`、`pre_edit`、`session_stop`、`user_prompt_submit`。支持 mode：`soft`、`guard`、`suggest`、`off`。默认配置：`session_start: soft`、`pre_edit: guard`、`session_stop: soft`、`user_prompt_submit: suggest + enabled: true + record_only: true`（只记录脱敏交互，不注入提示、不阻塞输入）。

### 6.4 Memory Layout / 记忆目录

```text
.memory-center/
  workspace.yaml
  hooks.yaml
  rules/
  index/
  graph/
  memory/
  artifacts/
  instructions/
```

### 6.5 provider-mcp-policy.json / 外部 MCP Bridge 策略

可选策略文件位于 `.memory-center/provider-mcp-policy.json`，声明 Memory Center 可以作为 Client 直接调用的外部 HTTP MCP Server。顶层 `schema_version: 1`、`providers: []`。Provider 字段：`id`、`server`、`url`（只能为不含用户名/密码/查询串的 `http(s)` URL）、`transport`（`sse|streamable_http`）、`timeout_seconds`（1..60）、`priority`、`tools`。Tool 字段：`action`、`tool`、`mode`（`read_only|controlled_write|destructive`）、`arguments`（仅常量及 `{query}`/`{target}` 占位符）。

### 6.6 Timeline / Ref / Receipt

正式 `timeline_item.kind`：`session_event`、`write_receipt`、`handoff`。短引用体系：`ref_id`、`summary`、`payload_ref`/`receipt_ref`。

### 6.7 兼容性原则

MCP facade schema兼容优先；破坏性变更必须同步 README/docs/changelog；原子 CLI/HTTP 能力可继续保留，默认公开面以 facade 为主。

## 7. Main Reading Order / 主阅读顺序

主线使用请优先看：

- [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
