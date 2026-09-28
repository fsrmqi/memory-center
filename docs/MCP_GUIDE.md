# MCP Guide / MCP 接入指南

## Ontology / 本体状态与断言

`mc_lookup` 会附加 `knowledge_state`，其中 `state`、`absence_reason`、`scope_checked` 与 `next_action` 说明当前范围内的知识状态。不要将 `NOT_FOUND` 当作不存在的事实结论。

`mc_admin(action="assertion_inspect")` 可读取断言详情和 Action；`mc_admin(action="assertion_status")` 用于验证或拒绝，`VERIFIED` 必须带脱敏 `verification_ref`。本体只使用 V2 读模型；升级后的旧 sidecar 必须运行完整 `reindex` 重建，不提供迁移或旧格式回退。

## Delivery Workflow / 需求交付工作流

`feature_delivery_v2` 将需求交付收敛为 `intake -> breakdown -> locate -> implement -> verify -> close`。需求项必须包含来源、范围和验收关联；模型只能提出候选，范围决策必须有引用证据。`mc_start` 的 workflow 推荐会根据任务意图选择修复、契约、长期、架构或 `maintenance` 画像，并返回稳定规则、架构证据、变更契约和任务范围的分层上下文建议。

- `mc_admin(action="delivery_init", task_id="...")` 初始化任务工作流。
- `mc_admin(action="delivery_contract_update", task_id="...", payload='{"kind":"requirements|subtasks|acceptance","items":[...]}')` 更新需求、子任务或验收标准。子任务可附加 `read_targets`、`write_targets` 与 `stop_conditions`；acceptance 可附加 `critical_hypothesis`、`continue_if`、`stop_if`、`rollback`、`evidence_required`，形成可证伪验证设计。
- `mc_admin(action="delivery_breakdown"|"delivery_matrix" ...)` 生成不写入的需求候选，以及 `Requirement -> Subtask -> CodeTarget -> Acceptance -> Evidence` 派生矩阵与 `TECH_SPEC.md`。
- `mc_admin(action="delivery_policy"|"delivery_validation_execute" ...)` 分别读取/更新预注册验证 profile，或执行其中一个 profile。只接受 policy 中的 argv，不能传入 shell 命令。profile 可声明 `evidence_types`，执行回执还会自动带上 `executor-receipt`；`delivery_validation_record` 也可接收人工确认的 `evidence_types`。工作区可设置 `enforce_scope_contract=true`、`enforce_validation_design_contract=true` 或 `enforce_evidence_contract=true`，分别约束实现范围、定位前的验证设计和关闭前的证据闭环。三者默认关闭以保持既有任务可用。
- `mc_admin(action="delivery_subtask_status"|"delivery_validation_record"|"delivery_transition" ...)` 分别更新子任务、记录外部/人工验证、推进阶段。人工验证 payload 必须显式传 `evidence_kind="manual_verified"` 与声明的 `actor`，系统返回 `reported_actor`、`actor_source`、`identity_assurance=self_asserted` 以及不含任务标题的 `delivery-validation` 引用；`acceptance_ids`、`evidence_refs` 必须是只含字符串的 JSON 数组。所有动作返回门禁、缺失项与确定的下一步。
- 关闭阶段要求每项 `required=true` 的验收标准都关联 `executor` 或 `manual_verified` 的 `passed` 证据。普通外部回执标记为 `recorded_external`，不能伪装成执行器验证。
- `mc_admin(action="delivery_skill_candidate"|"delivery_skill_contract_update"|"delivery_skill_canary"|"delivery_skill_observe"|"delivery_skill_evaluate"|"delivery_skill_publish"|"delivery_skill_rollback"|"delivery_skill_recommend"|"delivery_skill_replay", task_id="...", payload="...")` 管理可验证 Skill 生命周期。候选必须声明完整边界契约并匹配真实回执。成功观测只能引用工作区中可解析的已通过验证，重复引用会返回 `evidence_already_used`；并发观测在同一事务中去重并同步生成 replay。观测和 replay 同时按 `activation_id` 与 `contract_sha256` 隔离，并在数量截断前完成过滤；评估和发布共同使用 `minimum_verified_passed`。回执审计按任务锁内分批同步到 SQLite，状态与关闭门禁读取稀疏验收覆盖，不全量解码历史。回滚重启创建新 activation；残缺旧契约不进入默认推荐。发布后的协作资产同步失败会返回 `asset_registered=false` 和 `artifact asset-sync` 修复动作，不会把已经完成的发布误报为失败。
- `mc_admin(action="delivery_failure_candidates"|"delivery_skill_synthesize")` 仅显式执行离线失败归纳和多轨迹归纳，不会读取原始代码、需求正文或验证日志，也不会影响普通查询延迟。
- `mc_admin(action="asset_status|asset_register|asset_sync|asset_share|asset_approve|asset_bind|asset_loadout|wiki_document_ingest", source="...", payload="...")` 管理本地协作资产。`asset_register` 的 `source` 必须与 payload 的 owner 相同；既有资产更新与绑定只接受 owner 身份。共享资产默认 `pending_review`，仅该状态的 team/restricted 资产可由非 owner 审批，owner 不能自审，审批前不会进入任何 Agent 装载。metadata 最大 16 KiB，`asset_status` / `asset_loadout` 可通过 payload `max_chars` 控制有界输出并返回 `truncated`；`mc_context_pack(agent_id="...", role="...")` 还返回 `budget_tokens` 与 `truncated_sections`。
- 与外部 Personal Assistant Wiki 协作时，推荐由宿主加载 `wiki` Skill：当前工程事实和任务证据保留在 Memory Center，长期知识由 Wiki 的两阶段确认流程治理。Wiki 晋升成功后，用 `asset_register` 登记 `kind=wiki`、`source_ref=pawiki:<path>` 的反向链接，并在 metadata 中保存 `knowledge_id`、`content_sha256`、`source_task_id` 和有界 `evidence_refs`；不要复制外部 Wiki 正文。The host Agent should orchestrate both MCP servers and retain only a governed reverse link in Memory Center.
- 跨宿主部署可使用 Personal Assistant Wiki MCP 2.4+ 提供的 `personal-assistant-wiki-integrations`：它把同一份 `wiki` Skill 安装到共享 `~/.agents` 目录，并为需要独立目录的 Codex、Claude、WorkBuddy 补充兼容副本，同时生成通用 stdio MCP 清单与 DeepSeek Harness patch。各宿主仍应通过自己的配置入口显式启用 MCP，不假设存在全局统一配置文件。Cross-host setup installs one shared Skill source with only the compatibility copies required by each host, then renders host-specific MCP configuration without weakening approval gates.
- `mc_analyze` 的 `depth` 仅支持 `quick|standard|full`，`direction` 仅支持 `upstream|downstream|both`，`max_depth` 为 `1..6`。标准和完整分析若计划、规则、契约等辅助阶段不可用，会保留已成功的影响图并返回 `analysis_status="partial"`、`diagnostics` 与下一步动作；MCP 错误响应的 `diagnostics.trace_id` 可对应本地调用审计。
- 当任务工件或索引代际空间异常时，Agent 先建议 `artifact compact-task`、`artifact generation-gc --dry-run`、`artifact index-export-cleanup --dry-run` 或 `artifact semantic-index-compact --dry-run`；涉及删除必须由显式 `--apply` 或 `mc_admin(action="index_generation_gc", force=true)` 确认。语义镜像清理后，Agent 应在无写入任务时建议 `artifact storage-vacuum --apply` 回收 SQLite 页。
- Skill 外部评测不属于 MCP 查询热路径。Agent 只有在用户要求评测已发布 Skill 时，才可建议 CLI 依次执行 `artifact delivery-skill-eval-status`、`delivery-skill-eval-init`、`delivery-skill-eval-run --dry-run`；运行外部引擎必须获得明确 `--apply` 授权，结果只能作为待审核的外部证据。

## 1. Public Surface / 对外公开面

MCP 当前公开的是 15 个 task-level tools：

- `mc_bootstrap_context`
- `mc_provider_action`
- `mc_mcp_bridge`
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
| `mc_bootstrap_context` | 零初始化上下文入口：已有 workspace 用 Memory Center；否则只读调用可选 GitNexus，再降级为有界本地搜索；外部结果不持久化 |
| `mc_provider_action` | 运行注册的外部 Provider 固定动作；读取动作直接执行，索引或清理必须 `confirm=true`，不接受自由命令 |
| `mc_mcp_bridge` | 受限外部 MCP Client：无 `action` 时查看 Provider 白名单；有 `provider/action` 时只调用策略登记的 HTTP MCP 工具、固定模板参数，写入必须 `confirm=true` |
| `mc_start` | 嗅探任务上下文、可选同步、启动 session；自动创建/续接 Task Shadow（L1）。仅在自动同步已获推荐且任务标题或标签直接命中时才自动绑定/写 L2；其余情况保持 Shadow-only，并通过 additive `task_binding` 说明决策。 |
| `mc_lookup` | 统一检索入口：symbol / code / query / trace / chain / context / ref / backend；`mode="query"` 支持 `view="evidence-index"` 紧凑有序证据索引（渐进式披露第一跳，第二跳用 `mode="ref"` 展开），缺省视图不变 |
| `mc_analyze` | 统一影响分析入口：quick / standard / full |
| `mc_sync` | 将 sniff / case / task 过程同步到工件与记忆；低置信任务解析会停写并要求显式 task_id。新增 `sync_target=auto\|task\|shadow`：低置信解析 fallback 更新 Task Shadow 而不放弃连续性 |
| `mc_resume` | 恢复任务上下文 |
| `mc_handoff` | 为其他模型构建交接包 |
| `mc_close` | 会话收尾、同步 case、记录经验，并自动回写可推断的候选路径反馈；优先复用 `mc_start` 绑定的 task_id；输出 `binding_recommendation` 与 `promotion_options`（默认保留为临时工作影子） |
| `mc_admin` | 状态、面板、评测、工件、group 等管理入口 |
| `mc_context_pack` | 生成紧凑、证据驱动的上下文包 |
| `mc_onboard` | 生成面向不同 persona 的架构导览 |
| `mc_domain` | 提取业务域和业务流 |
| `mc_freshness` | 检查索引新鲜度与 stale/pending 风险 |

`mc_start` / `mc_lookup` 可传 `request_tier="fast"|"standard"|"deep"`，其中 `fast` 会收紧候选数量和深度。`mc_analyze(execution_mode="background")` 会立即返回 `job_id`；使用同一工具并传入 `job_action="status"|"cancel"` 与 `job_id` 即可读取或取消后台分析。默认仍是同步执行，保持既有调用兼容。

`mc_mcp_bridge(evidence_refs_json="...")` 可融合多个 Provider 返回的脱敏 `EvidenceRef`。只有显式 `claim={subject,predicate,value}` 才会参与一致性判断：多个独立 Provider 同值为 `CONSISTENT`，异值为 `CONFLICT` 并返回 `verify_conflict`；没有 Claim 时是 `INSUFFICIENT_EVIDENCE`，不得根据正文差异编造冲突。策略中有 `capabilities: ["code_navigation"]` 的只读 Bridge tool 会进入联邦初始化的健康路由，使用现有 P95、错误率和成本分避开慢或失败 Provider。

当 `mc_lookup` 已解析出 `project` 时，系统只查询该服务的 active generation 分片；分片未发布会返回 `knowledge_state.state=NOT_INDEXED`，不会静默退回全局索引。运行时索引、会话和断言统一读取 SQLite 事实库，JSON/JSONL 仅用于审查与导出。

管理类异步重建使用 `mc_admin(action="job_reindex", projects=[...], files=[...])`。返回值中的 `job_id` 传给 `mc_admin(action="job_status", record_id="...")` 或 `mc_admin(action="job_cancel", record_id="...")`。可使用 `index_control` 查看 active/staging generation，使用 `query_performance` 查看 P50/P95/P99 查询耗时。任务级架构决策使用 `task_decision_record` / `task_decision_list`；`task_evidence_gc` 仅在 `force=true` 时删除候选证据。

传入 `mc_lookup(..., project="service-name")` 时，服务范围内的 code/hybrid 查询会优先读取 active generation 的物理服务分片。回滚使用 `mc_admin(action="index_rollback", record_id="<generation>")`；generation 清理使用 `mc_admin(action="index_generation_gc", keep_recent=2, force=false)`，默认仅返回候选项。

不传 `project` 的 `mc_lookup` 也会返回 `shard_route`（generation、起始服务、扩展深度、契约/拓扑依据）和 `shard_evidence`（并行查询的服务分片及命中）。跨服务性能门禁使用 `mc_admin(action="eval_cross_shard_replay", text="每行一个查询", budget="fast|standard|deep")`；结果只记录耗时、选片数量和证据覆盖率。

`mc_lookup` 的 `cross_shard_fusion` 是可直接用于决策的融合结果：`generation.consistent` 必须为 `true` 才应将索引结论当作事实；`contract_consistency.overall="attention"` 时，应继续调用 `mc_analyze(depth="full")`。融合质量门禁使用 `mc_admin(action="eval_cross_shard_fusion", payload='{"cases":[{"query":"...","expected_projects":["..."]}]}')`，检查服务选择、generation 一致性和结论可解释性。

查询结果、推理项、图边和质量摘要会追加四级 `evidence_level`：`EXTRACTED`、`INFERRED`、`AMBIGUOUS`、`VERIFIED`。其中 `VERIFIED` 只接受显式验证状态；`_meta.evidence_level` 仍是旧的来源/处理阶段标识，调用方不得将其当作结论验证等级。

运行 `memory-center inspect --workspace <workspace.yaml>` 可在不暴露私有路径、原始提示词或会话 ID 的前提下，集中查看实际生效的 MCP 版本、AGENTS、Hook、线程会话绑定、交互保留策略、索引代际和修复建议。HTTP 可调用 `/workspace/inspect`；MCP 可调用 `mc_admin(action="runtime_inspect")`，并通过 `payload` 传入可选的宿主 thread ID。

`mc_start` 会追加 Git 分支、HEAD 和脏文件数量快照；`mc_close` 可追加已经执行过的 `validation_command`、`validation_exit_code`、`validation_summary` 和 `validation_status`。Memory Center 只记录脱敏摘要，绝不执行传入的验证命令；会话 summary 的 `evidence_chain` 会关联起始/结束代码版本、验证结果与 outcome。非 Git 工作空间或未提供验证结果时自动降级，不阻断关闭流程。

后台 reindex 的 `mc_admin(action="job_reindex")` 会返回 `job_id`；用 `mc_admin(action="job_status", record_id="...")` 读取同一份持久化进度。`progress.stage` 依次使用 `queued`、`scanning`、`parsing`、`graph`、`semantic`、`retrieval`、`finalizing`，并在完成、失败、取消或中断时返回对应终态和有界事件历史。

`job_status` 还会派生 `progress_percent`、`elapsed_ms`、`estimated_remaining_ms`、`can_cancel` 与 `recovery_action`，供 Agent、DSH 和 `GET /workspace/job-status` 使用；这些字段不会改写任务历史或索引。内置 `/ui/jobs` 页面已随 `/ui/*` 下线。真实工作区性能通过显式 `mc_admin(action="performance_snapshot", limit=5, budget="fast")` 采样，随后用 `performance_snapshot_status` 查看 P95 趋势。快照只保存聚合指标和 generation，不保存查询、文件路径或正文。`mc_admin(action="http_route_contract_audit")` 可在发布前审计 HTTP 路由读写契约。

`job_status` also derives `progress_percent`, `elapsed_ms`, `estimated_remaining_ms`, `can_cancel`, and `recovery_action` for Agents, DSH, and `GET /workspace/job-status`; it never rewrites job history or indexes. The bundled `/ui/jobs` page was removed with `/ui/*`. Real-workspace performance is sampled only by explicit `mc_admin(action="performance_snapshot", limit=5, budget="fast")`, then read through `performance_snapshot_status`. Snapshots retain aggregate metrics and generation only, never queries, paths, or source text. `mc_admin(action="http_route_contract_audit")` audits HTTP read/write contracts before release.

真实工作区运行治理使用 `mc_admin(action="runtime_governance")`、`GET /workspace/runtime-governance` 或 `memory-center runtime-governance`。它只汇总性能快照、空间预算、generation、ANN 和活跃任务；未初始化 workspace 不创建 SQLite，任何维护动作仍需 Agent 根据 `next_action` 显式发起。

局部刷新性能通过 `mc_admin(action="scoped_refresh_performance", limit=20)`、`GET /workspace/scoped-refresh-performance` 或 `memory-center scoped-refresh-performance` 读取。Agent 应先查看 `status`、P95 和 `latest.dominant_stage`；预算内不重复刷新，超预算时只 profile 建议阶段，禁止自动升级为全量 reindex。

4.3.84 的局部刷新结果会额外返回 `generation_inherit`、`generation_service_payloads`、`generation_graph_shards`、`generation_shared_shards`。Agent 应按最大子阶段行动：图分片高时检查受影响项目数量和分片规模，payload 高时检查服务 JSON 体积；不得因某个子阶段超预算自动触发全量 reindex。局部多项目导出已内置最多 3 个 worker，无需 Agent 自行并发调用 reindex。

外部 `skill-up` 评测必须使用 3 到 5 个脱敏、可观察的 case；隔离运行环境未建立前，`without_skill` 基线固定为不可比较。执行结果会返回 `pass`、`skill_failure`、`evaluation_failure` 或 `environment_error`，其中认证、网络、MCP、进程和超时问题绝不计入 Skill 失败率。Java 调用解析的 `eval_java_call_resolution_unresolved` 返回 `campaign`，要求先增加 3 到 5 个 `expected_target`、`allowed_targets`、`forbidden_targets` 逻辑锚点 case，再允许变更 resolver/parser。enum 生成方法、外部返回类型链和最终继承外部框架接口的方法会作为索引边界单独分类，不参与本地修复 campaign。

Java 同名重载从 4.3.81 起按各自方法体绑定接收者类型。由于公开逻辑锚点仍采用 `Class#method` 并汇总该方法的所有重载，私有 case 的 `allowed_targets` 必须列出其他重载产生的合法高置信边；`forbidden_targets` 只填写对所有重载都不合法的目标。

4.3.82 的 Lambda 类型推导只接受显式参数类型和标准 `java.util.function` 泛型目标。MCP 返回的第三方无类型回调仍应解释为“证据不足”，Agent 不应据此请求宽泛 fallback；应先补私有逻辑锚点或外部 Provider 证据，再决定是否扩展契约。

4.3.83 进一步接受可证明的 JDK 集合泛型：参数、局部变量或显式可见字段上的 `List/Set/Collection/Iterable/Stream<T>` 仅用于直接 Lambda，`Map<K,V>.forEach` 映射两个输入。Agent 看到通配符、裸类型、第三方容器或类型变换后的链时，仍应保留 `UNKNOWN/receiver_type_missing`，不得要求全局猜测或自动全量重建；先用 3-5 个私有逻辑锚点和定向刷新验证。

常驻索引更新通过 `memory-center watcher-start --workspace <workspace.yaml>` 启动；它对去抖后的源码、配置变更创建有界局部重建任务，不在查询链路执行全量重建。使用 `watcher-status` / `watcher-stop` 查看或停止。MCP 对应 `mc_admin(action="watcher_start|watcher_status|watcher_stop")`；Workbench 的 `hot_refresh.watcher` 同步显示相同状态。

局部重建完成后，watcher 自动写入轻量变更影响摘要，只复用失效计划、任务结果和 index generation，不会自动执行深度影响分析。通过 `memory-center change-impact-reports`、`GET /workspace/change-impact-reports` 或 `mc_admin(action="change_impact_recent")` 查询；DTO、Feign、MQ、HTTP、配置变更会标为高风险并建议显式调用 `mc_analyze(depth="full")`。

确认闭环使用 `memory-center change-impact-confirm`、`POST /workspace/change-impact-confirm` 或 `mc_admin(action="change_impact_confirm")`。决策为 `confirmed`、`false_positive`、`deep_analysis_required`、`resolved`；可附带 `task_id`、`session_id`、`validation_status`、结构化验证摘要和 `verified_by`。其中 `deep_analysis_required` 保持待确认，其他决策关闭报告；`GET /workspace/change-impact-reports?pending_only=true` 与 `mc_admin(action="change_impact_pending")` 返回有界待处理清单。

证据子图导出使用 `mc_admin(action="evidence_subgraph_export", text="<node-id-or-symbol>")`；可选 `direction`、`max_depth`、`limit` 与 `action_filter="json|markdown|html"`。HTTP 为 `GET /workspace/evidence-subgraph?target=...`，CLI 为 `export-evidence-subgraph`。该能力仅做显式、有界邻接读取，限制为最多 3 跳、120 条边、80 个节点，不读取源码、不扫描全图。

统一变更审查使用 `mc_admin(action="change_review", scope="all", view="minimal")`，HTTP 为 `GET /workspace/change-review?scope=all&detail_level=minimal`，CLI 为 `change-review`。它最多定向刷新 12 个相关文件，禁止退化为全量 reindex；返回加权最佳影响路径、测试缺口、契约风险、验证 Action、停止条件和调用预算。同一源码签名与 index generation 的等价请求直接复用结果；只有证据不足或用户显式请求时才升级 `standard` / `deep`。

Git co-change 独立评测使用 `mc_admin(action="eval_cochange", limit=20, payload='{"warmup_commits":5}')`、`GET /workspace/eval-cochange?max_commits=20&warmup_commits=5` 或 CLI `eval-cochange`。4.3.80 默认执行 walk-forward，当前图只作诊断；只有 `calibration.eligible=true` 时才允许 CLI `--apply` 或 MCP `force=true` 写入哈希先验。HTTP 保持只读预检。该能力不进入查询热路径，提交、路径和消息不会写入报告。

`eval_retrieval_replay` 使用按时间切分的训练/留出集，并按 task/evidence 指纹去重。`status=ready` 仍不等于自动应用；必须同时确认具体 source 的 `validated=true`、Brier score 不退化，再通过 CLI `--apply` 或 MCP `force=true` 显式写入。样本不足时保持现有权重。

架构社区分析使用 `mc_admin(action="architecture_communities")`，HTTP 为 `GET /workspace/architecture-communities`，CLI 为 `architecture-communities`。它读取有界 SQL 投影，优先使用固定种子的 Leiden，缺少可选依赖时使用确定性加权标签传播，并返回社区、桥接点、异常跨社区连接与未测试高中心性节点；仅在显式调用时执行，Workbench/status 仅读取已缓存摘要，异常结论始终标记为 `INFERRED`。

契约语义校验使用 `mc_admin(action="contract_gate", name="SomeRequestDto.java")`，返回 `semantic_compatibility.status`：`pass`、`attention` 或 `block`。`mc_analyze(depth="full", target="...", task_id="...")` 自动执行同一校验并可将完整报告写为任务 evidence。guard 模式 pre-edit hook 遇到 `block` 会拒绝编辑；release gate 在索引存在契约快照时失败。

运行时样本通过 `mc_admin(action="runtime_contract_ingest", payload="...")` 导入，payload 应只包含 `samples` 元数据数组，禁止业务 payload/body/header/message。用 `runtime_contract_migration` 登记双读/双写迁移，用 `runtime_contract_gate` 获取活跃流量兼容结论；传 `task_id` 会将该报告保存为任务 evidence。release gate 仅在存在样本时增加运行时契约组件。

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

### Evidence-bounded reasoning prompts / 证据约束推理 Prompt

以下 Prompt 是对现有 facade 的只读编排，不增加新的 tool schema：

| Prompt | 使用场景 | 停止或升级条件 |
|---|---|---|
| `clarify_change_request(request)` | 需求仍有范围、兼容性、目标或验收歧义 | 每次只问一个会改变结论的问题；信息足够立即停止，确认后才实现 |
| `audit_project_claim(claim, scope="workspace")` | 核查“某调用一定存在”“所有消费者都兼容”等工程断言 | 明确 facts / inferences / judgments；证据 stale 或不足时保持 `AMBIGUOUS` / `UNKNOWN` |
| `design_minimal_validation(change, task_id="")` | 为变更设计最低成本的可证伪验证 | 必须给出可观察的 `continue_if` / `stop_if`；只有真实回执才能标为 `VERIFIED` |
| `compare_change_options(problem, option_a, option_b, constraints="", task_id="")` | 架构、兼容或迁移方案二选一 | 用相同维度钢人化双方；只在用户接受后记录 task decision |

`clarify_change_request` 应先使用 `mc_start` / `mc_lookup` 回答可从工作区发现的问题，不能把已有新鲜证据重新问给用户。`audit_project_claim` 必须保留 `NOT_FOUND` 的开放世界边界。`design_minimal_validation` 不执行来自需求正文的 shell 字符串，只能建议动作或使用 workspace policy 中预注册的 argv profile。`compare_change_options` 使用专业视角但不虚构专家人物或真实人物观点。

These prompts reuse existing facades and evidence semantics. They do not persist a second reasoning state, execute arbitrary commands, or promote confidence to verification.

回归 Prompt 合同时运行：

```bash
memory-center eval-reasoning-prompts
```

该命令默认只返回 `static_contract=pass|fail`，真实行为仍为 `real_case_missing`。需要真实验收时，从 `examples/reasoning-prompt-eval/` 复制模板到本地私有评测目录，再传入 `--cases` 和 `--observations`。四类 Prompt 均有真实 case、脱敏 evidence refs 和四项人工检查后，`real_behavior.status=pass`、`release_ready=true`。人工 reviewer 仅标为 `identity_assurance=self_asserted`，报告不会返回姓名、输入正文或 evidence ref 内容。

补充说明：
- 回到已知任务空间时，优先调用 `mc_admin(action="task_resume_check", task_id="...")`。它会合并 resume packet、task health、repair plan、next actions、unresolved items 和 recent evidence，返回 `ready`、`needs_repair` 或 `blocked`。
- 当 `task_resume_check.status="needs_repair"` 时，先看 `mc_admin(action="task_repair_plan", task_id="...")`。需要执行修复时再调用 `mc_admin(action="task_repair_apply", task_id="...", force=false)` 做 dry-run；确认后用 `force=true` 应用。刷新 `current-summary` 这类修复应传入 `intent`，例如 `intent="继续 Feign DTO 兼容改造"`。
- `task_repair_apply` 只执行保守低风险修复：补齐缺失 context/plan 模板、在有 intent 时刷新 current-summary。它不会伪造 write receipt、自动归档相似任务空间或覆盖已有人工内容。
- `mode="trace"` 适合先看跨服务索引概览，快速知道 Feign / API / MQ 命中了什么。
- 如果需求是“某个方法一路追到最底层”，优先用 `mode="walkthrough"`；当查询里已经包含 `Class#method` 且明确提到“全链路/到底层”时，`mode="auto"` 现在也会优先转到 walkthrough。
- `mode="chain"` 适合看图谱 callers / callees；`mode="walkthrough"` 适合看一个方法体内的已索引步骤、下游调用和 Feign 服务端候选。
- `mode="walkthrough"` 的 Feign 续链会在 `feign_continuations[].server_walkthroughs` 中优先展开目标服务的 Controller 方法；如果 Controller 调用同一 service 的 Service interface，会在 `service_impl_continuations` 中继续给出 Impl 方法落点和已索引本地步骤。
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
- 如果当前 MCP workspace 是 service 子目录，method walkthrough 会尝试自动升级到父级或 registry 中覆盖当前 workspace 的聚合 workspace。查看 `workspace_escalation.status` 判断是否已切换；`not_needed_or_not_found` 不是错误。
- `memory-center init` / `memory-center reindex` 写入的受管说明块和 MCP 绑定现在会镜像到各个已配置 service root，明确提示并实际绑定上层 `.memory-center/workspace.yaml`；这能减少 Agent 在 service 子目录里“没连上父级 workspace 就不调用 MCP”的情况。
- `memory-center setup-agent --workspace <workspace.yaml>` 是推荐的一键接入口，会刷新说明、Hooks、MCP 绑定并返回是否需要重启宿主会话。
- `memory-center runtime-audit --workspace <workspace.yaml> --fix` 会检查并刷新根目录和 service 子目录下的 `.codex/mcp.json`、`.cursor/mcp.json`、`.mcp.json`，以及每个 DSH profile 的 `cordis.patch.yml`（`$DSH_HOME/profiles/*`，默认 `~/.dsh`，可用 `DSH_HOME` 覆盖），用于自动修复看不到 `mc_*` 工具的宿主接入问题。DSH 绑定校验四件事：`mcp-memory-center` 条目是否存在、`command` 是否真实可执行、`--workspace` 是否指向当前 workspace、整份 patch 层是否仍是合法 YAML（不合法时在 `parse_error` 中给出原因）；任一不满足即计入 `missing_or_stale`。修复只就地替换或追加该条目，以文本级拼接完成，不重排 YAML，也不会破坏 `!!js` 表达式与注释。MCP 可执行文件按 PATH → `~/.local/bin` → `/opt/homebrew/bin` → `/usr/local/bin` 解析（可用 `MEMORY_CENTER_BIN` 覆盖），避免 GUI 宿主最小 PATH 下写入裸命令名或已失效的绝对路径。
- `memory-center runtime-audit --workspace <workspace.yaml> --fix` checks and refreshes `.codex/mcp.json`, `.cursor/mcp.json`, and `.mcp.json` under the workspace root and each service sub-directory, plus every DSH profile's `cordis.patch.yml` (`$DSH_HOME/profiles/*`, default `~/.dsh`, overridable with `DSH_HOME`). A DSH binding is validated on four facts: the `mcp-memory-center` entry exists, its `command` is actually executable, `--workspace` targets the current workspace, and the whole patch layer is still valid YAML (otherwise `parse_error` explains why); any failure lands in `missing_or_stale`. Repair only replaces or appends that entry through text splicing, so the YAML is never re-serialised and `!!js` expressions and comments survive. The MCP executable is resolved through PATH → `~/.local/bin` → `/opt/homebrew/bin` → `/usr/local/bin` (overridable with `MEMORY_CENTER_BIN`), which prevents bare command names or dead absolute paths from being written under a GUI host's minimal PATH.
- 首轮工具快照没有 `mc_*` 只表示“未知或装载中”，不能直接判定 MCP 不可用。Agent 应先执行延迟工具发现并调用 `mc_freshness`；Codex 可用 `codex mcp get memory-center` 检查全局绑定。配置为 enabled 但当前会话仍无工具时，应提示刷新或新建会话；只有绑定、命令或实际 MCP 调用失败时才降级。
- MCP server 暴露 `memory-center://startup-diagnostics` resource，用于查看启动时解析到的 workspace、MCP 绑定状态和下一步修复建议。
- 每次 MCP 工具调用都会自动记录到 `.memory-center/memory/mcp-invocations.jsonl`，仅保留工具名、脱敏参数摘要、耗时、状态、结果规模与可选 session/task 关联，不保存完整请求或响应。`mc_start` 创建的 session 会自动关联同一 MCP 进程后的调用，并同步为 `tool_call` session event，供 replay、采纳分析和后续验证使用。
- Every MCP tool call is automatically recorded in `.memory-center/memory/mcp-invocations.jsonl`. The audit log keeps only tool name, redacted input summary, duration, status, result size, and optional session/task linkage. Calls following `mc_start` reuse its session in the same MCP process and are mirrored as `tool_call` session events for replay and verification.
- 审计记录默认只保留最近 30 天且最多 100,000 条；首次调用、每 5 分钟或达到条数上限时触发维护。所有读取会立即按保留窗口过滤；64 KiB 以内的小日志同步裁剪，大日志由后台线程物理压缩，避免 MCP 请求线程扫描和重写十万级 JSONL。SQLite 运行记录与 JSONL 导出由同一裁剪操作同步收口。
- Audit records retain the latest 30 days and at most 100,000 entries. Maintenance runs on the first call, every five minutes, or when the entry limit is reached. Every read enforces the retention window immediately; logs up to 64 KiB are pruned synchronously, while larger logs are physically compacted in the background to keep MCP requests off the large JSONL scan/rewrite path. SQLite runtime records and JSONL exports are pruned by the same operation.
- 历史生命周期分层执行：MCP 与宿主原始交互保留 30 天，session event 保留 90 天，session summary 保留 365 天，均最多 100,000 条；case、任务工件和聚合效果摘要不按此规则删除。
- History lifecycle is tiered: raw MCP and host interactions retain 30 days, session events retain 90 days, and session summaries retain 365 days, each capped at 100,000 entries. Cases, task artifacts, and aggregate effect summaries are not removed by this policy.
- 可通过 `mc_admin(action="backend_query", collection="mcp-invocations.jsonl", limit=20)` 查看最近审计记录。
- Use `mc_admin(action="backend_query", collection="mcp-invocations.jsonl", limit=20)` to inspect recent audit records.
- 宿主 Hook 会自动记录 session_start、pre_edit、session_stop 等交互元数据到 `host-interactions.jsonl`；只保存白名单字段和脱敏预览，不保存对话正文、文件内容或 payload。宿主可通过 `mc_admin(action="interaction_record", session_id="...", payload="{...}")` 补记其他工具事件。
- Host hooks automatically record metadata for session_start, pre_edit, and session_stop in `host-interactions.jsonl`. Only allowlisted metadata and redacted previews are retained; dialogue bodies, file contents, and payloads are excluded. Hosts can record additional tool events with `mc_admin(action="interaction_record", session_id="...", payload="{...}")`.
- 默认 `user_prompt_submit` Hook 是 `record_only`：只记录脱敏的用户提示预览，不向宿主注入额外提示、不阻塞请求，也不会触发 `mc_start`。
- The default `user_prompt_submit` hook is `record_only`: it stores a redacted user-prompt preview without injecting guidance, blocking the request, or invoking `mc_start`.
- 设置 `MEMORY_CENTER_THREAD_ID`（可选 `MEMORY_CENTER_TRACE_ID`、`MEMORY_CENTER_TURN_ID`）后，MCP 会持久化 thread 到 session 的绑定；重启 MCP 进程后同一 thread 仍会自动续接。`mc_admin(action="active_session_bindings")` 可查看当前绑定。
- With `MEMORY_CENTER_THREAD_ID` (and optional `MEMORY_CENTER_TRACE_ID` / `MEMORY_CENTER_TURN_ID`), MCP persists thread-to-session bindings so the same thread resumes after an MCP restart. Use `mc_admin(action="active_session_bindings")` to inspect bindings.
- `mc_admin(action="interaction_effects")` 汇总调用量、状态、P50/P95、session 关联率、宿主交互覆盖和已关闭会话的验证成功率；`interaction_effects_refresh` 会刷新本地快照。
- `mc_admin(action="interaction_effects")` summarizes call volume, status, P50/P95, session-link rate, host interaction coverage, and verified success for closed sessions; `interaction_effects_refresh` refreshes the local snapshot.
- 可在 `.memory-center/templates/method_walkthrough.md` 配置报告模板，支持占位符 `{target_label}`、`{summary_lines}`、`{read_targets}`、`{rule_groups}`、`{mermaid_flow}`、`{performance_risks}`、`{data_scope_guards}`、`{diff_context}`、`{glossary}`、`{next_actions}`。未配置时返回内置 `answer_markdown`，可用 `report_level=brief|standard|deep|risk-focused` 控制默认报告形态。
- MCP server 的 `--workspace` 可以传 `workspace.yaml` 或 workspace 目录；传目录时会向上寻找 `.memory-center/workspace.yaml`，找不到时保持原入参并由后续工具返回正常错误信息。
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
- `advanced_query` — 面向概念型或中英文混合查询，启用 ANN 与最多 12 条候选的 Cross-Encoder 重排；只使用当前 MCP 进程已预热的模型，不会在请求中下载或加载权重
- `vector_ann_status` — 检查 dense vector 的 ANN 可用性和当前查询 `ef`
- `vector_ann_rebuild` — 从已有 dense embeddings 显式重建 HNSW；仅在 `rebuild_vector_ann` 下一步动作或维护任务中调用
- `vector_ann_tune` — 使用有界 self-recall 探针调优 HNSW 查询 `ef`；重建或大规模 reindex 后调用一次
- `retrieval_reranker_status` — 区分模型是否仅磁盘缓存，还是已经在当前 MCP 进程可立即使用
- `retrieval_reranker_prewarm` — 在显式维护窗口下载并加载 Cross-Encoder 到当前 MCP 进程；不得由普通查询自动触发
- `retrieval_model_profile` — 查看或选择 embedding 档案；`text="multilingual"` 且 `force=true` 仅写档案，完整 reindex 必须单独确认
- `eval_retrieval_replay` — 读取带 evidence 的人工验证检索反馈；只有结果 `ready` 时才允许 `force=true` 应用权重提案

### Agent 自动维护 / Agent-directed maintenance

`mc_lookup` / `/workspace/query` 返回的 `agent_next_steps` 是 Agent 的可执行控制面。若出现 `rebuild_vector_ann`，Agent 必须顺序调用：

1. `mc_admin(action="vector_ann_rebuild")`
2. `mc_admin(action="vector_ann_tune")`
3. 以原 query 重试 `mc_lookup`

该规则只在已有大规模 dense embeddings 且 ANN 不可用时触发；不会在普通查询中隐式全量重建。ANN 正在维护时，查询最多等待 300ms 并返回 `vector_ann_maintenance_in_progress` 与 `retry_after_ms`，向量后端读取失败会返回 `vector_backend_query_failed` 和 `vector-ann-rebuild`，两者都不阻塞 MCP。定向 freshness refresh 只会后台排队，`auto_refresh.scheduled=true` 表示当前响应使用已发布 generation。对复杂概念查询，Agent 应调用 `mc_admin(action="advanced_query", text="原查询")`，而非自行执行无界本地搜索。若结果诊断为 `reranker_not_prewarmed` 或 `reranker_timeout`，基础排序仍可直接使用；只有用户明确同意时才调用当前 MCP 进程中的 `mc_admin(action="retrieval_reranker_prewarm")`。模型档案和全量 reindex 也不会由 Agent 自动发起。
- `eval_java_call_resolution_unresolved` — 按可行动原因汇总未解析 Java `CALLS_METHOD`，只返回逻辑锚点样本，不返回文件路径或源码；静态类/外部依赖、实例类型缺失、接口多态和范围遗漏会分别计数。Agent 应先用该动作选定一个类别，再要求人工提供 3-5 个私有逻辑锚点 case；不得根据样本臆造 service 内目标边
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
- `eval_java_call_resolution_metrics` — 返回解析等级分布、链式调用数量、平均置信度和未解析率；仅返回聚合指标，不暴露路径、源码或私有 case
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
- `task_shadow_*` — Task Shadow（Session-first 会话影子，L1）操作：`task_shadow_status`（合并投影）、`task_shadow_bind`（CAS 绑定到正式 task）、`task_shadow_suggest`（写入候选）、`task_shadow_promote`（bound 后升格合并进 L2）、`task_shadow_discard`（丢弃，L0/L2 不受影响）、`task_shadow_retention`（未绑定过期清理，默认 dry-run）、`task_shadow_authority`（observation|snapshot 切换）、`task_shadow_observation_record` / `task_shadow_observation_list`（Observation Inbox，allowlist fail-closed）、`task_shadow_handoff_create` / `hand_off` / `claim` / `close` / `get` / `list`（Handoff Claim，claim-once CAS）
- `note_record` / `note_list` / `note_search` / `note_supersede` / `note_forget` — Session Notes（L0.5 叙事记忆层）：显式记录跨任务叙事事实；同 fingerprint 幂等、supersede/forget 均为 append-only 决策行（`memory/session-note-decisions.jsonl`，原 note 行永不改写，生效状态由投影计算，决策行携带 `actor`=`source` 透传）、forget 只隐藏具名条；隐私门 fail-closed（绝对路径/密钥拒收，`<private>` 片段剥除）。`mc_close` 返回 `note_drafts`（确定性草稿，未确认不落盘）
- `case_supersede` / `case_reinstate` / `case_decision_list` — L1 case 治理：以 append-only 决策行（`memory/case-decisions.jsonl`）替代/恢复 case，原 case 行永不改写，current truth 由 `project_case_truth` 投影计算（读取经 SQLite 权威）；替代前校验 successor 存在且仍为 current truth，自替代被拒（`successor_is_self` / `successor_not_current_truth`），重复操作为结构化 no-op
- `group_*` — 跨工作区组操作
- `walkthrough_health` / `eval_walkthrough_quality` / `walkthrough_export` — method walkthrough 自检、质量评测与 Markdown artifact 导出

## 5. Task Shadow / 会话影子（Session-first Continuity）

Task Shadow 是 L0（会话证据）之上的临时、可丢弃连续性状态层（提案见 `docs/SESSION_FIRST_TASK_CONTINUITY_PROPOSAL.md`）。默认工作流无需手动创建 task：

```text
mc_start → 自动创建/续接 Shadow（不写 L2）
mc_sync  → bound 同步 task；否则只更新 Shadow
mc_close → 输出 binding/promotion 建议，默认"保留为临时工作影子"
```

核心约束：

- **多源 contribution**：Shadow 按 `(source_provider_id, source_session_id)` 保存独立 contribution，各源独立 durable 水位；对外是确定性 merge（union 去重，与到达顺序无关）。
- **幂等水位**：快照幂等键 `(shadow_id, source_provider_id, source_session_id, durable_as_of_seq)`；相同/较旧水位是 no-op；`observed_as_of_seq` 必须等于 `durable_as_of_seq`；`delivery_mode=volatile` 直接拒收。
- **不确定不写**：未绑定 Shadow 不写任何 L2 artifact；`task_shadow_promote` 仅在 `binding_status=bound` 后生效。
- **CAS 并发**：绑定与 handoff claim 携带 `expected_revision`，stale revision 返回冲突。
- **Observation Inbox**：跨 harness 最小事实契约，payload 字段 allowlist fail-closed（拒绝完整 prompt、工具正文、绝对路径），`(source_kind, source_session_id, event_seq)` 幂等去重；`shadow_authority=snapshot` 时 Observation 仅保留 L0 审计。
- **审计**：所有 Shadow 状态变更写 L0 write receipt；retention 清理只影响未绑定 Shadow，L0 receipt / L2 artifact / L3 case 不受影响。

入站快照 schema（adapter 提交，state_version 需与 MC 兼容，版本更新会标记 stale 并要求 resync）：

```json
{
  "shadow_id": "shadow:dsh:session-1",
  "source_provider_id": "dsh-task-shadow@1",
  "source_session_id": "session-1",
  "observed_as_of_seq": 5,
  "durable_as_of_seq": 5,
  "durable_event_count": 10,
  "delivery_mode": "durable",
  "state_version": 1,
  "intent_summary": "bounded summary",
  "candidate_tasks": [],
  "candidate_files": [],
  "evidence_refs": [],
  "unresolved_items": [],
  "next_actions": [],
  "binding_status": "unbound"
}
```

## 6. V3 Tools / V3 工具

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
- Phase A 合同：响应额外携带 `index_context`（active generation、freshness FRESH/STALE/PARTIAL/NOT_INDEXED、coverage 计数与原因、query_budget）与 `claim_boundary`。

### Index Claim Contract / 索引结论边界合同

`mc_lookup`、`mc_analyze`（impact 路径）与 change review 响应均附带 additive 字段 `index_context` 与 `claim_boundary`；不会删除或改变既有字段，也未新增 MCP tool。

- `index_context.coverage` 按 workspace、已指定 project 或 logical path 给出 requested/indexed/partial/skipped/failed/unknown 文件计数、脱敏原因码和 `truncated` 标记。
- `claim_boundary.negative_claim_allowed=true` 仅当：存在 active generation、freshness=FRESH、覆盖完整、查询未截断/未超时，且 chain 结果的锚点校验匹配（`chain_anchor_validation.status="matched"`）、shard 路由覆盖锚点项目（`chain_scope_validation.scope_incomplete=false`）。此时空结果可表述为"已覆盖范围内不存在"。
- 其余情况下 Agent 必须使用"在已覆盖范围内未发现"，不得声称"工程中不存在"；`evidence_level` 会相应降级为 `AMBIGUOUS` 或 `NOT_INDEXED`。

The claim boundary is a logical gate, not prompt wording: responses carry machine-readable reason codes (`index_not_published`, `generation_stale`, `coverage_partial`, `query_truncated`, `query_timed_out`, `anchor_mismatch`, `scope_incomplete`) and agents must phrase empty results accordingly.

#### Chain Anchor Gate / 调用链锚点门禁

`memory_callers` / `memory_callees`（`mc_lookup(mode="chain")` 底层）响应新增 additive 字段：

- `chain_anchor_validation`：`{"requested_symbol", "resolved_anchor", "status": "matched|mismatch|missing", "reason"}`。中文意图词混入 query 不影响判定；显式 `symbol` 参数优先作为校验目标（硬锚）。
- `chain_scope_validation`：`{"anchor_project", "routed_projects", "anchor_project_covered", "scope_incomplete", "reason"}`。用原始查询词模拟 shard 路由，检查锚点项目是否被路由覆盖。
- `fallback_action`（仅空 chain 时）：给出 `mc_lookup(mode='symbol')`、`mc_lookup(mode='code')` 等有界回退动作，不生成"确认不存在调用方"文案。
- 锚点不匹配时响应携带 `anchor_candidate_only=true`，该候选仅作参考、不作为精确锚定。

The chain anchor gate prevents a real failure mode: a misspelled or ambiguous query resolves to an unrelated class, the chain returns empty, and the old gate wrongly certified "no callers". Empty chains under anchor mismatch or incomplete shard coverage are now forced to `AMBIGUOUS`.

### Bounded Query Templates / 有界图查询模板（Phase B）

内部模板 `find_symbols` / `trace_call_paths` / `find_contract_consumers` / `plan_change_risk` 通过既有 facade 提供服务，不新增 MCP tool：

- fast/standard/deep 三档硬预算：fast=depth 1/nodes 20/edges 30，standard=depth 3/nodes 80/edges 120，deep=depth 5/nodes 300/edges 500；显式传入的 depth/limit 会钳制到档位上限，deep 同样有硬预算和 deadline。
- 同一 generation 与参数下结果排序确定；任何截断都通过 `query_budget.truncated` 可见。
- 模板结果缓存键包含 active generation：generation 变化立即失效。
- `mc_analyze(depth="standard"|"full")` 追加有界 `contract_consumers`（DTO/Feign/MQ 消费者），命中失败不影响其他分析阶段。

### Primary Cross-Service Chain / 跨服务主链路

`mc_lookup(auto)` 对已解析出 **Method 锚点**的 symbol 查询（非 fast tier）附加 additive 字段 `primary_chain`：

```json
{"primary_chain": {"status": "found|not_found|insufficient_evidence|truncated",
  "anchor": {}, "steps": [], "score": 0.0,
  "evidence_level": "EXTRACTED|INFERRED|AMBIGUOUS",
  "generation": "gen-...", "reason_codes": []}}
```

- `status=found`：含至少一个跨服务/契约关系边（CALLS_SERVICE / IMPLEMENTS_FEIGN / HANDLES_ENDPOINT / PRODUCES_TOPIC / CONSUMES_TOPIC），且证据不是 AMBIGUOUS。
- `Class.method` 形式的查询（如 `Service.getUserName`）会完整提取为方法符号，`mc_lookup(auto)` 直接命中 Method 锚点并触发主链路；含 `Controller`/`Service` 的方法名查询优先走 symbol，不会被 `api` 等 token 降级到 context。
- `not_found` / `insufficient_evidence`：无跨服务图证据或索引不完整。**不得把这种状态表述为"调用了下游服务"**。
- 结构边（CONTAINS / DECLARES / IMPORTS）永不作链路主体；Feign 接口方法经 retrieval 层桥接到 FeignClient/FeignMethod（桥接步骤标 INFERRED）。
- fast tier 跳过 primary_chain 以保持 P95；`best_match` / `candidate_paths` 等原有字段不受影响。
- **MQ Producer 锚点**：当 Topic 的消费者无法从本地索引证明（binding→destination 映射在配置中心）时返回 `insufficient_evidence` + `mq_topic_consumer_unprovable` 等 reason，不返回 `not_found`（避免暗示"无消费者"），也不编造消费者。

### Resolution Diagnostics / 解析诊断边界（Phase D）

- Java 调用解析诊断通过显式 IR 记录通信；`stable_id` 由工作区事实确定性派生，不依赖 SQLite rowid。通用 parser adapter 的完整 IR 投影仍按真实需求分阶段推进。
- 无法证明的调用目标保持 AMBIGUOUS（`target_ref=None`），按 reason code 和文件聚合到索引目录 `index-resolution.json`；摘要附在 `graph-summary.json` 的 `resolution_summary`。诊断只含计数、短 reason code 和已持久化的逻辑路径，不含源码片段或 prompt。
- 差分报告携带 `symbol_category_counts`，regex 与 AST 分歧可定位到文件与符号类别。

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

## 7. Hooks / Hook 接入

### 推荐自动执行

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

### `UserPromptSubmit` 默认只记录不注入

`user_prompt_submit` 默认配置为 `enabled: true` + `record_only: true`：只把脱敏 prompt 交互写入交互历史，不注入提示、不阻塞输入；宿主 adapter 也不会为它生成注入/阻断型配置。

原因：普通自然语言请求过于依赖上下文，容易被宿主误处理成拦截步骤。如需 suggest 注入必须由维护者显式修改 `hooks.yaml`。

## 8. Host Strategy / 宿主策略

### Claude Code / Codex

默认建议：

- 生成 `SessionStart / PreToolUse / Stop`
- `UserPromptSubmit` 只生成 record_only 版本（仅记录，不注入、不阻断）

### Cursor

更适合作为规则与工作流提示层，而不是强阻断执行层。

## 9. Security Model / 安全模型

Memory Center 默认是：

- 本地优先
- 读优先
- 不改业务源码

写入范围主要限于：

- `.memory-center/memory`
- `.memory-center/artifacts`
- 生成的 skills / dashboard

## 10. Unified Error Model / 统一错误模型

CLI、MCP、HTTP 的真实入口统一使用以下错误类型：

| Error Type | HTTP | Meaning |
|---|---:|---|
| `invalid_input` | 400 | 参数缺失、格式错误或不支持的操作 |
| `not_found` | 404 | workspace、route 或资源不存在 |
| `unavailable` | 503 | backend、连接或能力暂时不可用 |
| `conflict` | 409 | 与当前状态冲突（含 `reindex_conflict`：scope 重叠的不同刷新请求被拒绝） |
| `internal_error` | 500 | 未预期内部错误 |

### Reindex Runtime Governance / Reindex 运行治理（Phase C）

reindex job 的权威状态位于 SQLite `workspace_jobs` 账本：

- 相同请求指纹的重复提交返回 `coalesced=true` 并指向执行中的 job；scope 重叠且请求不同返回 `reindex_conflict` 与 owner job id；非重叠 service 允许并行。
- generation 发布是原子的：manifest + active 指针 + 审计行单事务提交，发布后执行只读 smoke；smoke 失败自动回滚到 previous generation 并记录 `publish_smoke_failed`。
- 取消是协作式的：CLI `memory-center job-cancel` 或 registry cancel 在阶段边界生效，publish 事务内只能完成或回滚。
- lease 过期且 owner PID 消失的 job 被标记 `interrupted`（`failure_code=lease_interrupted`）；PID 仍存活时上报 `suspected_stalled` 等待显式处理，不会误杀。

入口行为：

- HTTP 保留 `ok=false` 和 `error`，并增加 `error_type`、可选 `suggested_action` 与 `diagnostics`。
- MCP tool 捕获入口异常并返回结构化错误 dict，便于 Agent 决定下一步。
- 安装后的 CLI 输出 `[error_type] message` 和可选建议，退出码为 1，不输出 traceback。
- 成功返回和现有 MCP tool schema 不变。

## 11. HTTP Bridge / HTTP 桥接

MCP 之外，还可通过 HTTP bridge 复用同一套能力：

```bash
memory-center serve-http --workspace /abs/path/.memory-center/workspace.yaml --host 127.0.0.1 --port 8765
```

HTTP GET 只允许无副作用读取；所有写入 route 必须 POST。非回环 `--host` 必须设置 `MEMORY_CENTER_HTTP_TOKEN`，调用方使用 `Authorization: Bearer <token>`；`actor` 仅表示审计归因，不是网络认证。

## 12. Related Docs / 相关文档

- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)

### Release Quality System / 发布质量体系

- CLI `quality-gate --workspace ...`：只读发布质量门禁，汇总 generation 健康 / coverage / retrieval replay+perf / IR diff gate / 存储 dry-run，输出 `pass|attention|block|real_case_missing`；不执行 reindex/GC/VACUUM/用户命令。
- `change_review` 响应附带 additive `validation_plan`：最小可证伪验证方案（DTO/Feign/HTTP/MQ/Config/私有方法/删除）；MQ 缺 destination 为 `insufficient_evidence`，contract block 为 `blocked`。

### Current quality behavior / 当前质量行为（4.6.12）

- `mc_lookup(auto)` 在已定位 Method 且 `request_tier != "fast"` 时可返回 additive `primary_chain`；`found` 必须有可解释的图证据，Feign 名称桥接标记为 `INFERRED`，MQ destination 无本地证据时为 `insufficient_evidence`，不得根据 binding 名猜测消费者。
- `index_context.coverage` 会区分 `irrelevant_excluded` 与 `relevant_unsupported`。明确无关的非源码资源仅审计、不阻断；相关未覆盖、解析失败、范围未知、查询超时或截断仍会阻断否定性结论。
- 质量与性能读取统一使用 `mc_admin(action="scoped_refresh_performance"|"runtime_governance")` 或 CLI `quality-gate`。质量门禁只读；`attention` 可能表示真实样本不足或分桶 P95 问题，不等于可以自动维护索引。
- HTTP `/workspace/quality-overview`：脱敏、有界的质量 + 空间 + generation 健康视图，供 DSH/Workbench 只读展示；不暴露查询正文/源码/绝对路径。

- **coverage 语义校准**：`index_context.coverage` 新增 `irrelevant_excluded`（unsupported_syntax 的非源码资源，如 xml/png/json/md）与 `relevant_unsupported`（相关但解析器不支持）。`claim_boundary` 只在 `relevant_unsupported`/`parse_failed`/`scope_unknown` 时拒绝否定性结论；明确无关的排除资源仅审计、不阻断。

- **调用链锚点门禁**（4.6.21）：chain 响应新增 `chain_anchor_validation` 与 `chain_scope_validation`；锚定失败或分片路由未覆盖锚点项目时，空 chain 结果强制 `AMBIGUOUS`（reason codes `anchor_mismatch`/`scope_incomplete`），并给出 `fallback_action` 回退建议，不再把空结果当作"确认不存在调用方"。

- **任务解析写入门禁**（4.6.21）：`resolve_task_space` 输出 `resolution_confidence`（high/medium/low）、`auto_write_allowed` 与 `required_action`；低置信/歧义解析不再自动绑定 task space。`workspace_sync_sniff_to_artifacts` / `workspace_sync_case_to_artifacts`（`mc_sync`）在低置信时停止写入并返回候选，需要显式 `task_id`。`mc_close` 优先复用同会话 `mc_start` 绑定的 task ID。匹配来源分类（`tag_exact`/`title_exact`/`intent_exact`/`signature_overlap`/`fuzzy_token`）在 `match_reasons` 中可见；中文长意图与任务工件正文用连续公共子串判定语义重叠。
- **`mc_start` 最终绑定门禁**：启动入口不会再把自然语言解析出的 `task_id` 伪装成显式选择传给同步层。仅当 auto-sync 已推荐，且 `match_reasons` 含非空 `title_exact` 或 `tag_exact` 时，才允许自动同步和绑定会话；否则不写 L2、也不向 `mc_close` 传递 task 绑定，只保留 Task Shadow。响应新增 additive `task_binding={mode, auto_bindable, task_id, reason}`，用于审计本次选择。
- **匹配源与通名弱化**（误绑定修复）：`current_summary` 不作为匹配源（它每次 close 被当次 intent 覆盖，作为输入会自写自匹配）；workspace 自身名字、框架/中间件通名（feign/kafka/redis 等）计入弱 token，不构成强证据；status/priority 加分仅在已有强证据时生效。workspace overview 的任务列表用 `effective_status` 展示活跃度：active 超 14 天无 task-space 活动展示为 `stale`（排序沉底，`registered_status` 保留原登记值）。

- **freshness generation 快照**（4.6.21）：`mc_start` 的 freshness 标记 `freshness_snapshot=true` 并携带 `observed_generation`/`observed_at`/`refresh_in_flight`；后续 `mc_lookup`（带 session_id）在 generation 变化时返回 `freshness_transition`（如 `stale_to_fresh`），Agent 不应把启动时的 stale banner 当作当前查询事实。

- **刷新预算分层**：`scoped_refresh_performance_status` 按变更类别/范围分桶（plain_java/contract/delete_or_move × single_file/multi_service），每桶独立预算；legacy 无 bucket 样本不参与判定，仅 ≥5 样本且 P95 超本桶预算才标记 `over_budget_buckets`。
