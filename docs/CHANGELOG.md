# Changelog / 更新日志

## Unreleased 未发布

## 4.3.94 本地 Agent 执行观测 / Local Agent Execution Observability

- 新增 DSH 脱敏 execution-event inbox 的幂等导入与本地汇总 CLI，关联 turn、step、model、tool、Token、耗时和失败；不复制 prompt、工具参数/结果、cwd 或消息正文。
- Added idempotent local DSH execution-event ingestion and bounded turn/model/tool/token/failure summaries without retaining prompts, tool payloads, cwd, or message bodies.

## 4.3.93 会话召回精度行动提示 / Session Recall Precision Guidance

- 当私有精度标签发现额外返回项时，`eval-session-recall` 现在优先提示人工审核与补充 allowed 集合；只有确认无关候选过多时才建议收紧 CJK fallback。
- When precision labels surface extra candidates, session recall evaluation now prioritizes human review and allowed-set refinement before recommending a stricter CJK fallback.

## 4.3.92 会话召回精度审查 / Session Recall Precision Review

- 私有 session-recall case 可选声明 `allowed_source_session_ids`；报告只统计待人工审核的额外返回项，不将其自动判定为误报，并返回有标签 case 的 precision 聚合。
- Private session-recall cases can optionally declare allowed source sessions; the report surfaces extra returned candidates for human review without auto-labeling false positives.

## 4.3.91 会话召回模式可观测性 / Session Recall Match-Mode Observability

- `eval-session-recall` 新增脱敏 `related_case_match_modes` 聚合与单 case `related_case_match_mode`，区分 existing exact、CJK fallback 与无命中，避免只凭 recall 判断 fallback 质量。
- Added privacy-safe exact/CJK-fallback/none match-mode telemetry to session recall evaluation so fallback quality is not inferred from recall alone.

## 4.3.90 Resume 中文长意图召回 / CJK Resume Recall

- 当 L1 case 的既有 exact token 匹配为空时，`workspace_resume_context` 仅对中文连续片段启用至少两个二元片段的有界 scored fallback；精确匹配路径保持不变，避免单字泛化噪声。
- Added a bounded scored CJK-bigram fallback for L1 resume only when legacy exact-token matching is empty; exact matching remains unchanged and one-character noise is avoided.

## 4.3.89 会话召回评测 / Session Recall Evaluation

### 会话召回评测 / Session recall evaluation

- 新增只读 `eval-session-recall`：使用工作区外的私有 YAML case 复放实际 resume 链路，区分 L1 未索引、token 检索遗漏、结果窗口截断和证据不足；输出不回显 query、任务正文或 session ID。
- Added read-only `eval-session-recall` using private local cases to classify L1 indexing, retrieval, window-selection, and evidence failures without exposing query or session text.

## 4.3.88 会话候选审批闭环 / Session Candidate Approval Loop

- 新增 staged 多会话候选的 append-only 审批闭环：`consolidate-session --stage`、`consolidation-candidates` 与 `decide-consolidation-candidate`。逐条 approve 会在写入 L1 前重新检查 current-truth 冲突；REVIEW 候选只能人工处理或拒绝。
- 当前会话整合只支持无冲突 `ADD` 与人工 `REVIEW`；L3 仍仅产出草稿，`UPDATE / SUPERSEDE / NOOP` 保持为后续经真实数据验证的候选能力。
- Added append-only staging and per-item approval for multi-session consolidation. Approval rechecks current-truth conflicts before L1 writes; REVIEW candidates cannot be written automatically. L3 remains draft-only.

### 多会话记忆整合 / Multi-session memory consolidation

- 新增 `consolidate-session` CLI 命令（core: `workspace_consolidate_sessions`）：把一组已结束会话的 `suggest-case` 草稿整合为 L1 case / L3 记忆块候选。
- 每条候选都带来源 event/evidence ref、冲突理由与预期写操作；既有 current-truth case 或同批重复会话返回 `REVIEW`，不基于文本相似度自动覆盖；已失效 case 不阻止新的 `ADD`。
- 默认 dry-run 只产出草稿；新增 `--stage`、`consolidation-candidates` 与 `decide-consolidation-candidate`，以 append-only 候选/决策记录支持逐条审批或拒绝；approve 只写入重新校验仍无 current-truth 冲突的 ADD。`--apply` 保留为直接显式模式且不能与 `--stage` 同用；`--include-l3` 额外产出 L3 memory-block 追加草稿（即使 apply 也不自动写入）。
- 设计依据 `docs/MEMORY_LANDSCAPE_RESEARCH.md` §3.2/§4：显式离线维护、不改变 MCP tool schema、不进入查询热路径。

- Added `consolidate-session` CLI (core `workspace_consolidate_sessions`) that folds multiple finished sessions into L1 case / L3 memory-block candidates with source refs, conflict reasons, and expected write operations. It is dry-run by default; `--stage` persists append-only candidates for per-item approval or rejection, and approval rechecks current-truth conflicts before writing. `--apply` writes only conflict-free ADD candidates, while current cases and batch duplicates require review. L3 drafts are never auto-written.

## 4.3.87 推理 Prompt 与证据闭环 / Reasoning Prompts and Evidence Closure

- 新增 `clarify_change_request`、`audit_project_claim`、`design_minimal_validation`、`compare_change_options` 四个 additive MCP Prompt，分别覆盖逐问式需求澄清、工程断言核查、最小可证伪验证和双向钢人决策。
- 四个 Prompt 仅编排现有 `mc_*` facade，保持 tool schema 不变；继续遵守 `knowledge_state` / `evidence_level`、预注册 argv profile、真实验证回执和用户接受后再记录决策的边界。
- Added four additive MCP prompts for bounded clarification, project-claim auditing, falsifiable validation design, and evidence-backed option comparison without changing tool schemas or creating a second state store.
- 新增 `eval-reasoning-prompts`：内置四类静态合同 smoke，并支持本地 `real_case` 与脱敏人工 observation 生成统一验收报告；公开示例、缺少证据引用或覆盖不完整时不会返回 `release_ready=true`。
- 推理 Prompt 评测报告不回显参数正文、reviewer 或 evidence refs，只保留逻辑 case ID、聚合检查、渲染长度与 SHA-256；人工身份明确标记为 `self_asserted`。
- Added a privacy-bounded reasoning-prompt acceptance report that separates static contract smoke from local real behavior observations and never treats public examples as real evidence.
- `feature_delivery_v2` acceptance 新增兼容字段 `critical_hypothesis`、`continue_if`、`stop_if`、`rollback`、`evidence_required`；delivery matrix、TECH_SPEC、任务指标和恢复提示展示验证设计及覆盖率。
- 新增默认关闭的 `enforce_validation_design_contract` workspace policy；启用后，必需验收缺少完整可证伪设计会在进入 `locate` 前返回 `validation_design_required`，旧任务和默认流程保持兼容。
- 验证回执与预注册 profile 新增兼容型 `evidence_types`；delivery matrix、TECH_SPEC、任务指标和恢复提示会计算每项验收的已观测、缺失与闭环证据。新增默认关闭的 `enforce_evidence_contract`，启用后只在 `close` 阶段阻止缺少所需证据类型的任务。
- CLI、HTTP、MCP 的既有 delivery contract 入口复用同一 additive items 结构，无需修改 MCP tool schema。
- Added backward-compatible acceptance validation-design fields and an opt-in locate-stage gate without changing the MCP tool schema.

## 4.3.86 图谱正确性与生成式 Wiki 移除 / Graph Correctness and Generated Wiki Removal

- 移除生成式 Wiki 设计及其 L1/L2/L3 项目地图、semantic bridge、profile、manifest、CLI、Hook 和 `mc_admin` 入口；任务恢复不再隐式注入 Wiki L1 上下文。
- `generate-skills` 迁至独立 `knowledge/skill_generation.py`，不再依赖 Wiki 模块；用户提供文档的协作资产登记能力保持不变。
- `DISPATCHES_TO` 现在要求父子方法签名一致，并排除 `private` / `static` 方法；Java parser 以 additive `modifiers` 字段保留分派所需证据。Lombok `@Builder` 不再无依据推断默认不存在的 `toBuilder()`。
- Removed the generated Wiki design and its L1/L2/L3 project maps, semantic bridge, profile, manifest, CLI, Hook, and `mc_admin` entries. Task resume no longer injects Wiki L1 context implicitly.
- Moved `generate-skills` to the standalone `knowledge/skill_generation.py` module. User-provided document collaboration assets remain unchanged.
- `DISPATCHES_TO` now requires matching parent/child signatures and excludes `private` and `static` methods. Java parser signatures retain additive `modifiers` evidence, and Lombok `@Builder` no longer implies `toBuilder()` without proof.

## 4.3.85 累积功能与质量更新 / Cumulative Feature and Quality Update

### Java 调用解析：Lombok @Builder 支持 / Java call resolution: Lombok @Builder support

- resolver 新增 Lombok `@Builder` 解析：`X.builder()` 静态工厂解析为 `*_lombok_builder`（0.85）；`X.builder().field(...)` 链式 setter 解析为 `chain_lombok_builder_setter`（0.78），`X.builder().build()` 解析为 `chain_lombok_builder_build`（0.80），均标记 `inferred_target`。
- 仅当类带 `@Builder` 注解且 setter 名与声明字段一致时推断，无注解类不误报（新增 4 个单元测试覆盖正/负场景）。
- 真实工作空间验证（ucap，36 模块）：未解析率 52.26% → 48.34%；`missing_method_or_polymorphism` 类别 10,671 → 2,768。
- 新增 3 个私有锚点 case（`java-call-resolution-lombok-builder-v4390.yaml`），门禁 3/3 通过（recall 1.0、resolution_level 全命中）。

### Session replay 匹配器校准 / Session replay matcher calibration

- 修复 agent guidance replay 匹配器：补齐 MCP server 已发出的 `inspect_symbol_anchor/inspect_code_hits/inspect_chain_summary/inspect_context_summary/inspect_trace_overview/inspect_route_result` 动作分支，并识别 `mc_*` CLI 工具别名（与 bypass 判定对齐）。
- 修复前真实工作空间 38 条事件全部误判为 missed（adoption 0.0）；修复后 adoption_rate 0.947，剩余 2 条为真实 `guidance_missing_target_hint` 缺口。
- `eval-retrieval-replay` 校准保持仅消费带证据的人工验证记录（当前 `insufficient_replay` 为设计内状态，guidance adoption 不作为权重学习证据）。

### 向量检索默认开启评估（真实基线对比）/ Vector default-on evaluation against real baseline

- 真实 ucap 工作空间完成 dense 向量链路验证：`sentence-transformers`（all-MiniLM-L6-v2）selective scope 构建 49,897 embeddings；安装 `semantic-ann` 可选依赖（hnswlib）后 `vector_ann_rebuild` + `vector_ann_tune` 就绪（self_recall 1.0，ANN 查询 p95 0.12ms）。
- 对比结论（retrieval-quality 私有套件，sparse 基线 5/5 通过）：vector-on 下 config 语义查询保持 recall 1.0（延迟 188→440ms），但 MQ 契约查询 anchor recall 1.0 → 0.0——向量泛化匹配把大量 Consumer 方法推入前排，稀释契约锚点。
- 决策：**维持 `enable_vector=False` 默认**（MCP/CLI 行为不变）。默认开启的前置条件：带证据人工验证样本完成融合权重校准（当前 `insufficient_replay`），使契约类锚点在 vector-on 下不掉出 top-N。

### P3 交付闭环收尾 / Delivery loop wrap-up

- `propose_delivery_breakdown` 增强：检查索引新鲜度，stale 时标记歧义并建议定向刷新。
- Waiver 运行时管理：`create/approve/revoke/list_delivery_waiver`，门禁检查生效 waiver 并区分 `transitioned/waived_transition/forced_transition`。
- 失败四类显式分类：`classify_delivery_failure`（auto_repairable / environment_blocked / requirement_path_error / human_decision_required）。
- 任务级效果度量：`delivery_task_metrics`（需求覆盖率、验收覆盖率、验证成功率、门禁强制率）。
- `task_resume_check` 消费 delivery-matrix，提取未决歧义与失败验证并给出下一步建议。

### 项目地图三层上下文与语义桥 / Three-level project map and semantic bridge

> 历史说明：本节记录 4.3.85 当时引入的能力；整套生成式 Wiki 设计已在 4.3.86 移除。

- `generate-wiki` 升级为三层项目地图：L1 总览（始终重建、有界）、L2 模块地图（按 dirty path 增量）、L3 语义桥（接口契约/消息契约/配置键/自定义术语 → 代码实体）。
- manifest 引入 generation 追踪与 stale 标记；`wiki-status` 报告过期模块。
- 新增 `mark_wiki_modules_stale`（脏路径→受影响模块，支持嵌套路径与绝对路径段匹配）。
- 新增 workspace wiki profile：`update_wiki_profile` 支持自定义语义桥规则与业务术语映射。
- 新增只读上下文入口：`get_l1_context` / `get_l2_context` / `get_l3_bridge`，CLI 命令 `wiki-status`、`wiki-context`，admin action `wiki_status`、`wiki_context`、`wiki_mark_stale`、`wiki_profile_update`。
- `task_resume_check` 集成 L1 作为默认轻量上下文（失败时降级，不影响恢复判断）。
- 真实工作空间验证：36 模块、702 条语义桥；增量刷新只更新受影响模块。

### 文档进一步精简 / Docs further consolidation

- 将 `PRODUCT_TECHNICAL_OVERVIEW.md` 的核心内容整合入 ARCHITECTURE 新增附录：
  - 附录 C：产品定位与核心问题（一句话介绍、五类真实问题、核心思想）
  - 附录 D：技术选型理由（SQLite、混合检索、generation、部分成功、不训练权重）
  - 附录 E：用户可感知能力（日常定位、影响分析、长任务、新鲜度、质量治理）
  - 附录 F：性能设计原则（热路径规则、风险处理策略表）
  - 附录 G：三种讲法与面试结构（客户/面试/内部分享 + 15 分钟面试结构）
  - 附录 I：常见问题（8 个 FAQ）
- 将 `SPECIAL_NOTES.md` 的关键设计决策整合入 ARCHITECTURE 附录 H（10 条常见设计误解）。
- 将 `SPECS.md` 合并入 `REFERENCE.md` §6（schema、workspace、规则、hooks、记忆目录、Bridge 策略、兼容性）。
- 将 `ONTOLOGY_EVOLUTION_PLAN.md` 合并入 `ONTOLOGY.md` Part II（演进目标、设计原则、目标本体、交付里程碑、非目标）。
- 将 `RELEASE.md` 合并入 `DOCUMENT_CONSTITUTION.md`（发布原则、最小清单、对外说明重点）。
- 将 `docs/README.md` 合并入根 `README.md` 文档导航。
- 归档 `PRODUCT_TECHNICAL_OVERVIEW.md`、`SPECIAL_NOTES.md`、`EXTERNAL_ABSORPTION_ISSUES.md`、`SPECS.md`、`ONTOLOGY_EVOLUTION_PLAN.md`、`RELEASE.md`、`docs/README.md`。
- 活跃文档从 12 份降至 8 份；ARCHITECTURE 从 990 行增至 1150 行，内容完整。
- 同步更新所有活跃文档中对已归档文档的引用。

### 文档合并与同步更新 / Docs consolidation and sync update

- 将 `TECHNICAL_ARCHITECTURE_AND_EVOLUTION.md` 和 `TECHNICAL_GUIDE.md` 的独有内容合并入 `ARCHITECTURE.md` 附录 A（设计决策与选型）和附录 B（代码导航与主链路）；原文件归档至 `docs/archive/`。
- 将 `DOCS_STATUS.md` 合并入 `DOCUMENT_CONSTITUTION.md`（新增 active/historical 文档分类、更新规则和推荐阅读顺序）；原文件归档。
- 删除 `UNIFIED_BACKEND_READ_PATHS.md`（已被 ARCHITECTURE §6 完整覆盖）；原文件归档。
- 更新 ARCHITECTURE §8 编排层模块表，反映 ADR-0002 拆分后的新模块（`ranking.py`、`session_payloads.py`、`rules.py`、`symbol_ranking.py`、`guidance.py`、`contract_filter.py`）。
- 更新 ARCHITECTURE §9.2 CLI 章节，反映 155 个命令拆至 16 个 `cli/commands/<family>.py` 家族模块。
- 更新 NEXT_PHASE_MASTER_PLAN 补充 ADR-0002 内部重构为已交付。
- 同步更新 README、USER_GUIDE、SPECIAL_NOTES、PRODUCT_TECHNICAL_OVERVIEW 中对已归档文档的引用。

### 按 ADR-0002 拆分 cli/main.py 命令族 / Split cli/main.py command families per ADR-0002

- 将 155 个根 `app` 命令按业务域拆至 16 个 `cli/commands/<family>.py` 模块（setup/retrieval/ops/watcher/change/lookup/walkthrough/write/eval/gate/session/resume/work/audit/bridge/tooling），每个模块提供 `register_<family>_commands(app)` 保持命令名与路径不变；`main.py` 从 2892 行降至约 220 行，只保留根装配。
- 11 个共享 typer.Option 单例拆至 `cli/commands/_options.py`；`_dispatch_walkthrough_cli` 随 walkthrough 族、`_parse_event_payload` 随 session 族迁移；跨族依赖（work 族用 `_parse_event_payload`）以显式 import 处理。
- 更新 3 个测试文件的 monkeypatch 目标（`cli.main.X` → `cli.commands.setup.X` / `cli.commands.lookup.X`）与后端函数共享断言（改为聚合 `cli.main` + 全部命令族源码）；`python -m memory_center.cli.main` 与 `watcher-run` 子进程入口保持不变。
- 全量测试通过，CLI 行为零变更（155 根命令 + 4 子组的命令名与调用路径与迁移前完全一致；唯一差异：`--help` 中命令的列出顺序按命令族重组）。

### Split cli/main.py command families per ADR-0002

- Moved all 155 root-`app` commands into 16 `cli/commands/<family>.py` modules (setup/retrieval/ops/watcher/change/lookup/walkthrough/write/eval/gate/session/resume/work/audit/bridge/tooling), each exposing `register_<family>_commands(app)` with command names and paths unchanged; `main.py` drops from 2892 to ~220 lines of pure root assembly.
- Moved the 11 shared `typer.Option` singletons to `cli/commands/_options.py`; `_dispatch_walkthrough_cli` travels with the walkthrough family and `_parse_event_payload` with the session family; cross-family use (work uses `_parse_event_payload`) is an explicit import.
- Updated monkeypatch targets in 3 test files (`cli.main.X` → `cli.commands.setup.X` / `cli.commands.lookup.X`) and the backend-function-sharing assertion (now aggregates `cli.main` plus every command-family module); `python -m memory_center.cli.main` and the `watcher-run` subprocess entry point are unchanged.
- Full suite passing; zero CLI behavior change (command names and invocation paths for the 155 root commands + 4 sub-groups are identical to before; the only difference: the order commands are listed in `--help` is regrouped by command family).

### 按 ADR-0002 拆分 shared.py / Split shared.py per ADR-0002

- 将排序/文本原语（7 个函数）拆至 `core/orchestrator/ranking.py`，会话事件载荷压缩与 ref 摘要（12 个符号）拆至 `core/orchestrator/session_payloads.py`，规则加载（7 个函数）拆至 `core/orchestrator/rules.py`；`shared.py` 从 1036 行降至 628 行。
- 删除 phase-A 后已零消费者的 shared 版 `_project_matches`（保留 query 版在 symbol_ranking）。
- 依赖单向化：shared 回导 `_event_payload` / `_classify_case_evidence_ref` / `_load_auto_sync_rules` / `_summarize_ref`，无循环 import；12 个 importer 的 import 语句同步更新。
- 全量测试通过，行为零变更。

### Split shared.py per ADR-0002

- Moved ranking/text primitives (7 functions) to `core/orchestrator/ranking.py`, session-event payload compaction and ref summarization (12 symbols) to `core/orchestrator/session_payloads.py`, and rule loading (7 functions) to `core/orchestrator/rules.py`; `shared.py` drops from 1036 to 628 lines.
- Deleted the shared.py copy of `_project_matches` that had zero consumers after phase A (the query.py copy lives in symbol_ranking).
- Dependencies are one-directional: shared back-imports `_event_payload` / `_classify_case_evidence_ref` / `_load_auto_sync_rules` / `_summarize_ref` with no import cycles; all 12 importers updated.
- Full suite passing, zero behavior change.

### 按 ADR-0002 拆分 query.py 辅助簇 / Split query.py helper clusters per ADR-0002

- 将符号排序簇（11 个函数 + `_normalize_symbol_name`）拆至 `core/orchestrator/symbol_ranking.py`，agent 下一步建议簇（9 个函数）拆至 `core/orchestrator/guidance.py`，契约过滤簇（3 个函数）拆至 `core/orchestrator/contract_filter.py`；`query.py` 从 2715 行降至 2057 行，只保留公共查询编排。
- 发现并记录 `_project_matches` 双实现分叉：query.py 版含连字符查询匹配（'open-api' 匹配 'open_api'），shared.py 旧版没有；本次以 query.py 版为准移入 symbol_ranking，shared.py 版暂不动，待后续统一。
- 5 个测试文件的私有 helper import 改为指向新模块真实位置；行为零变更，全量测试通过。

### Split query.py helper clusters per ADR-0002

- Moved the symbol-ranking cluster (11 functions plus `_normalize_symbol_name`) into `core/orchestrator/symbol_ranking.py`, the agent next-steps cluster (9 functions) into `core/orchestrator/guidance.py`, and the contract-filter cluster (3 functions) into `core/orchestrator/contract_filter.py`; `query.py` drops from 2715 to 2057 lines and keeps only public query orchestration.
- Discovered and documented a `_project_matches` divergence: the query.py copy supports hyphenated query matching ('open-api' matching 'open_api') while the older shared.py copy does not; this change standardizes on the query.py copy in symbol_ranking and leaves the shared.py copy for a later consolidation.
- Five test files now import the private helpers from their new homes; zero behavior change, full suite passing.

### 移除 core/views 图谱视图模块 / Remove core/views graph view module

- 删除无任何生产调用方的 `core/views/builder.py`（`GraphView` / `GraphViewBuilder`）；能力面已被 `mc_onboard` / `mc_domain` / `mc_context_pack` 覆盖，详见 ADR-0003。
- 同步移除 3 个回归测试文件中仅测试该模块的测试类与 pipeline 中的 view building 步骤；其余测试保持不变。

### Remove core/views graph view module

- Removed `core/views/builder.py` (`GraphView` / `GraphViewBuilder`) which had zero production consumers; the capability is already covered by `mc_onboard` / `mc_domain` / `mc_context_pack`. See ADR-0003.
- Removed the test classes that only exercised this module across three regression test files plus the view-building step inside the V3 pipeline test; all other tests are unchanged.

### 清理 query.py 死转发 / Remove dead walkthrough forwarding shims

- 删除 `core/orchestrator/query.py` 中 59 个仅委托 `core/walkthrough/*` 且无任何调用者的私有转发函数，文件从 2944 行降至 2715 行；纯删除、零行为变更。同步移除失效的 `_wt_continuations` / `_wt_risks` / `_wt_symbols` 别名 import。
- `tests/entrypoints/test_mcp_facades.py` 的两个 walkthrough 风险辅助函数改为直接从真实实现 `core/walkthrough/risks.py` 导入，测试语义不变且更贴近真实接缝。
- 保留 3 个仍有内部调用者的薄适配：`_compact_method_walkthrough_result`、`_render_method_walkthrough_answer`、`_walkthrough_index_signature`。

### Remove dead walkthrough forwarding shims in query.py

- Removed 59 private forwarding functions in `core/orchestrator/query.py` that only delegated to `core/walkthrough/*` with zero callers anywhere; the file drops from 2944 to 2715 lines as a pure, behavior-preserving deletion, along with the now-unused `_wt_continuations` / `_wt_risks` / `_wt_symbols` alias imports.
- The two walkthrough risk helpers referenced by `tests/entrypoints/test_mcp_facades.py` now import directly from their real implementation in `core/walkthrough/risks.py`; test semantics are unchanged and sit closer to the real seam.
- Kept the 3 thin adapters that still have internal callers: `_compact_method_walkthrough_result`, `_render_method_walkthrough_answer`, `_walkthrough_index_signature`.

## 4.3.84 局部 Generation 流式发布 / Scoped Generation Streaming Publication

- 局部 generation 不再递归复制上一代完整目录，只按当前 manifest 硬链接未受影响服务的 JSON 与 SQLite 分片；受影响分片保持新 inode，旧 generation 仍不可变且可回滚。
- 项目图导出从 `project_subgraph()` 的 Python 全量物化、JSON 反序列化和二次序列化，改为 SQLite `ATTACH + INSERT SELECT` 流式导出。临时可重建数据库先装载数据，再批量创建二级索引和 FTS，最后原子替换。
- 2-3 个受影响项目使用最多 3 个有界 worker 并行构建独立分片；全量 reindex 继续串行，避免大工作区形成无界 I/O 峰值。
- 新增继承、服务 payload、图分片和共享分片四段耗时；增加禁止 Python 图物化、双项目并行、节点/边无损对比、索引存在性和 inode 隔离测试。
- 同一真实 3 文件负载连续两次完成于 `8.23s` 和 `8.21s`，较 `10.63s` 基线下降约 `22.6%`；generation 发布从 `4.99s` 降至约 `3.5s`，恢复到 `10s` 健康预算。4.3.81-4.3.83 三套严格 Java 门禁保持全部通过。

## 4.3.84 Scoped Generation Streaming Publication

- Partial generations no longer copy the complete parent directory recursively. Only JSON and SQLite artifacts for unchanged services are hard-linked from the current manifest; rebuilt shards receive new inodes while retained generations remain immutable and rollback-safe.
- Project graph export now uses SQLite `ATTACH + INSERT SELECT` instead of materializing the complete project subgraph in Python and decoding/re-encoding every metadata payload. Rebuildable temporary databases load data before secondary indexes and FTS are created, then publish through an atomic replace.
- Two or three affected projects use at most three bounded workers to build independent shards. Full reindex remains sequential to avoid unbounded I/O bursts on large workspaces.
- Added stage timings for inheritance, service payloads, graph shards, and shared shards, plus regression tests for zero Python graph materialization, two-project parallelism, lossless node/edge counts, query indexes, and inode isolation.
- The same real three-file workload completed twice at `8.23s` and `8.21s`, about `22.6%` below the `10.63s` baseline. Generation publication dropped from `4.99s` to about `3.5s`, restoring the `10s` healthy budget; all strict Java suites from 4.3.81 through 4.3.83 remain passing.

## 4.3.83 JDK 集合泛型 Lambda 推导 / JDK Collection Generic Lambda Inference

- Java regex supplement 可从方法参数、局部变量和显式可见字段的 `List<T>`、`Set<T>`、`Collection<T>`、`Iterable<T>`、`Stream<T>` 中推导直接集合/Stream 操作的 Lambda 输入类型，并支持 `Map<K,V>.forEach((k,v) -> ...)`。
- 嵌套调用改为重叠扫描，`items.forEach(item -> item.submit())` 不再因外层调用吞掉内层接收者调用。类型证据仍限制在对应 Lambda 词法区间内。
- 通配符、裸集合、类型变量、第三方回调及经过类型变换 `map/flatMap` 后的后续 Lambda 保持 unresolved；不跨越无法证明的泛型变换传播类型。
- 新增集合字段/参数/局部变量、Map 双参数、类型变换隔离和通配符负例。真实空间 3 个新增私有 case、上一版 Lambda case 和重载 case 均严格 3/3 通过，意外与禁止高置信边均为 `0`。
- 真实空间单文件刷新 `4.96s`，在 `10s` 预算内；3 文件批量刷新 `10.63s`，其中 generation 发布 `4.99s` 并触发 warning。下一性能优先级是批量 generation 的受影响分片 copy-on-write 发布。

## 4.3.83 JDK Collection Generic Lambda Inference

- Java regex supplements now infer direct collection/Stream Lambda inputs from `List<T>`, `Set<T>`, `Collection<T>`, `Iterable<T>`, and `Stream<T>` method parameters, locals, and explicitly visible fields. `Map<K,V>.forEach((k,v) -> ...)` is supported as well.
- Qualified calls are scanned with overlap, so an outer `items.forEach(...)` no longer hides an inner `item.submit()` call. Inferred evidence remains bounded to the matching Lambda scope.
- Wildcards, raw collections, type variables, third-party callbacks, and downstream Lambdas after type-changing `map/flatMap` operations remain unresolved. Types never propagate across an unproven generic transformation.
- Added positive and negative coverage for collection fields/parameters/locals, bi-arity maps, transformation isolation, and wildcards. Three new private real-workspace cases, the previous Lambda suite, and the overload suite all pass strict 3/3 gates with zero unexpected or forbidden high-confidence edges.
- A real single-file refresh completed in `4.96s` within the `10s` budget. A three-file batch took `10.63s`, including `4.99s` in generation publication, and remains a warning; affected-shard copy-on-write publication is the next performance priority.

## 4.3.82 Java Lambda 词法类型推导 / Java Lambda Lexical Type Inference

- Java regex supplement 新增 Lambda 词法作用域：显式 `(Type value) -> ...` 参数类型仅作用于对应块或表达式，不会污染同名字段及 Lambda 外代码。
- 支持标准 `java.util.function` 的 `Consumer`、`Function`、`Predicate`、双参数和 Operator 泛型输入映射；第三方无类型回调和仅凭 `Type.class` 的回调保持 unresolved，不猜测调用契约。
- 新增显式 Lambda、标准函数接口、同名字段隔离和第三方回调负例测试。真实空间 3 个私有 case 严格门禁全部通过，召回、置信率和解析等级均为 `1.0`，意外与禁止高置信边均为 `0`；上一版重载门禁保持 3/3 通过。
- 3 个大文件合并刷新为 `11.42s`，明确标记 warning；其中最重单文件刷新为 `7.77s` 并通过 `10s` 预算。批量大文件 generation 发布继续作为性能观察项，不把合并超预算表述为已解决。

## 4.3.82 Java Lambda Lexical Type Inference

- Added lexical Lambda scopes to Java regex supplements. Explicit `(Type value) -> ...` parameter types apply only to the matching block or expression and cannot leak into same-named fields or code outside the Lambda.
- Added generic input mapping for standard `java.util.function` consumers, functions, predicates, bi-arity interfaces, and operators. Untyped third-party callbacks and callbacks inferred only from a `Type.class` argument remain unresolved because their contracts are not proven.
- Added explicit-Lambda, standard-functional-interface, field-isolation, and third-party negative tests. Three private real-workspace cases pass strict recall, confidence, and resolution-level gates at `1.0`, with zero unexpected or forbidden high-confidence edges; the previous overload suite remains 3/3 passing.
- A combined refresh of three large files took `11.42s` and remains a warning. The largest file alone refreshed in `7.77s`, passing the `10s` budget; large-batch generation publication remains an explicit performance observation rather than a claimed fix.

## 4.3.81 Java 重载作用域隔离 / Java Overload Scope Isolation

- 修复 Java regex supplement 将同名重载方法的参数与局部变量表按方法名相互覆盖的问题。每条调用和 DTO 字段访问现在直接绑定所在重载的变量作用域，不再从其他重载猜测接收者类型。
- 兼容的 `method_variable_types` 聚合视图改为保守合并：同名变量在不同重载中类型冲突时删除该歧义项；解析器仍保留每条调用上的确定类型证据。
- 新增重载调用与 DTO accessor 回归测试，并在真实工作区建立 3 个私有 expected/allowed/forbidden 逻辑锚点。3 文件局部刷新耗时 `6.70s`，严格门禁 3/3 通过，召回率与高置信命中率均为 `1.0`，禁止目标命中为 `0`。

## 4.3.81 Java Overload Scope Isolation

- Fixed Java regex supplements leaking parameter and local-variable types across same-named overloads. Each call and DTO field access now binds directly to the lexical scope of its own overload instead of borrowing a sibling overload's receiver type.
- The compatible `method_variable_types` aggregate is now conservative: a variable with conflicting types across overloads is removed as ambiguous, while deterministic type evidence remains attached to each call.
- Added overload call and DTO-accessor regression coverage plus three private expected/allowed/forbidden anchors on a real workspace. A three-file scoped refresh completed in `6.70s`; all 3 strict cases passed with `1.0` recall and confidence rate and zero forbidden hits.

## 4.3.80 时间前向共变与 Replay 校准 / Walk-Forward Co-change and Replay Calibration

- Git co-change v3 按仓库提交时间从旧到新执行：每个评估提交只能读取更早提交形成的文件对，当前图仅作为诊断对照，不参与校准，消除未来提交与当前图快照泄漏。
- 新增过去热门文件基线和应用门禁；至少 5 个评估提交、20 个 case，且 Precision/Recall 均不低于基线时，才允许 CLI `--apply` 或 MCP `force=true` 写入共变先验。
- 共变先验只保存 24 位路径哈希、支持度和归一化分数；查询只对现有图候选增加最多 0.12 的有界排序增益，不引入无图证据文件。真实工作区应用 546 条先验，100 次候选排序平均增加后的总耗时约 `0.266ms/次`。
- 检索 replay 按任务或证据指纹去重，按时间切分训练集和后 25% 留出集；提案只使用更早样本，只有留出集 Brier score 不退化且训练/验证样本门槛满足时才允许应用。
- 真实共变 66 个 walk-forward case 上 Precision `0.2284`、Recall `0.4539`，高于过去热门文件基线 `0.1742 / 0.4261`；真实检索 replay 当前为 0 条验证样本，因此保持 `insufficient_replay`，未写入权重。

## 4.3.80 Walk-Forward Co-change and Replay Calibration

- Git co-change v3 evaluates commits from oldest to newest. Each evaluation commit can use only older file pairs; the current graph is diagnostic-only and excluded from calibration, preventing future-commit and current-snapshot leakage.
- Added a past-only popularity baseline and an application gate. Hashed priors can be applied only with at least five evaluated commits, twenty cases, and non-regressing precision and recall.
- Persisted priors contain only 24-character path hashes, support, and normalized scores. They add at most a bounded 0.12 ranking boost to existing graph candidates and never introduce files without graph evidence.
- Retrieval replay now deduplicates by task or evidence fingerprint, then uses a chronological training split plus a final 25% holdout. A proposal is applicable only when holdout Brier score does not regress and both training and validation sample requirements pass.
- Across 66 real walk-forward cases, precision reached `0.2284` and recall `0.4539`, above the past-only popularity baseline of `0.1742 / 0.4261`. The real retrieval replay currently has zero verified samples, so no weight was applied.

## 4.3.79 局部刷新性能治理 / Scoped Refresh Performance Governance

- 局部刷新在同一 `WorkspaceStore` 事务内复用大型运行时索引对象，并使用 SQLite `updated_at` 轻量校验跨实例新鲜度；避免重复解码 Java 符号索引，同时不会让长期 Store 读取旧 generation。
- 精确文件/目录 scope 直接定位源码，不再先遍历完整服务目录；多语言结构 pass 复用相同有界 walker，无法解析的 scope 才保持保守回退。
- reindex 新增 `timing_ms`，覆盖索引载入、scope 扫描、解析合并、索引持久化、图更新、语义、检索、generation 发布和断言投影。局部刷新仅持久化 generation、数量和聚合耗时，不记录路径或源码。
- 新增 `scoped-refresh-performance` CLI、`/workspace/scoped-refresh-performance` HTTP、`mc_admin(action="scoped_refresh_performance")` MCP admin，并接入只读 `runtime-governance`。
- 真实单文件刷新由 `12.58s` 降至 `5.81s`，下降约 `53.8%`；scope 扫描由 `1.65s` 降至约 `1.71ms`，默认 `10s` 预算通过。

## 4.3.79 Scoped Refresh Performance Governance

- Reused large runtime-index objects within one `WorkspaceStore` transaction while validating cross-instance freshness through the SQLite `updated_at` token. This removes repeated Java-symbol decoding without serving a stale generation from a long-lived store.
- Exact file and directory scopes now resolve directly instead of walking an entire service tree. The multi-language structural pass shares the same bounded walker and retains conservative fallback semantics for unresolvable scopes.
- Reindex responses now expose stage-level `timing_ms` for index loading, scoped scanning, parsing/merge, index persistence, graph, semantic and retrieval updates, generation publication, and assertion projection. Persisted refresh observations contain only generation, counts, and aggregate timings.
- Added CLI, HTTP, and MCP-admin scoped-refresh performance status and integrated it into read-only runtime governance.
- A real one-file refresh improved from `12.58s` to `5.81s` (about `53.8%`), with scoped scanning reduced from `1.65s` to roughly `1.71ms`, passing the default `10s` budget.

## 4.3.78 Java 调用分类与共变排序 / Java Call Classification and Co-change Ranking

- Java 结构事实新增 `type_kinds`，保留 `class / interface / enum / record / annotation`，并写入 Class 节点；手写 `JavaSymbol.to_dict()` 同步输出该字段，避免高性能序列化路径丢失新事实。
- resolver 新增 `generated_enum_method_out_of_scope`、`chain_return_type_not_indexed`，并递归识别“本地父接口继续继承外部框架接口”的方法。Enum 编译器方法、外部集合链式方法、MyBatis 继承方法不再污染本地多态修复 campaign，也不会生成猜测边。
- UCAP 真实空间建立 3 个私有链式逻辑锚点并定向刷新 14 个相关文件；edge recall、置信率、resolution-level rate 均为 `1.0`，unexpected/forbidden 高置信边均为 `0`。
- co-change 文件候选从无序 `DISTINCT LIMIT` 升级为有界边投影上的确定性加权排序，默认候选从 24 收敛为 8。UCAP 66 个 case 上 Precision 从 `0.0438` 提升到 `0.0706`，Recall 从 `0.2191` 提升到 `0.2229`，评测约 `37ms`。
- 大图原型曾使用全量 SQL 聚合，但真实 17GB 图超过 30 秒，已移除；正式实现最多读取 1600 条邻接边后在内存聚合，不扫描完整文件子图。

## 4.3.78 Java Call Classification and Co-change Ranking

- Added `type_kinds` to Java structural facts and Class-node metadata, preserving class, interface, enum, record, and annotation semantics through the optimized `JavaSymbol.to_dict()` path.
- Added explicit unresolved reasons for generated enum methods and external chain return types, plus cycle-safe recursive detection of local parents that ultimately inherit external framework APIs. These calls no longer pollute local polymorphism campaigns or create guessed edges.
- Added three private UCAP chain anchors and refreshed only 14 related files. Edge recall, confidence rate, and resolution-level rate are all `1.0`, with zero unexpected or forbidden high-confidence edges.
- Replaced unordered co-change file candidates with deterministic weighted ranking over a bounded edge projection and reduced the default candidate set from 24 to 8. Across 66 UCAP cases, precision improved from `0.0438` to `0.0706`, recall from `0.2191` to `0.2229`, with evaluation around `37ms`.
- Removed a full SQL aggregation prototype after it exceeded 30 seconds on the real 17GB graph. The shipped path reads at most 1,600 adjacent edges and aggregates only that bounded slice.

## 4.3.77 图感知变更审查闭环 / Graph-Aware Change Review

- 新增有界加权最佳路径影响传播，按关系权重、边置信度、证据强度、新鲜度和深度衰减计算影响分数；SQLite frontier 逐层查询且每个节点只保留最佳路径，不在查询热路径物化全图。
- 新增统一 `change-review` 应用服务及 CLI、HTTP、MCP admin 入口。它一次完成变更识别、最多 12 个相关文件的定向刷新、影响链、契约风险、测试缺口和验证 Action；禁止自动退化为全量 reindex。
- 新增 `minimal -> standard -> deep` 渐进上下文、调用次数/输出/耗时预算、generation-aware 指纹缓存与重复调用停止条件，Agent 协议默认使用最小结果并复用等价审查。
- `architecture-communities` 升级为显式离线架构健康分析：可选固定种子的 Leiden 社区发现，缺少 `igraph` 时使用确定性加权标签传播；同时返回有界 Brandes 桥接点、异常跨社区连接和未测试高中心性节点。所有异常均标记为 `INFERRED`。
- 新增 Git co-change 独立评测和 `release-gate --cochange-commits`。同一提交中除种子外的文件作为真值，执行错误独立记为 `environment_error`，报告只保存哈希引用和聚合指标，不保存路径、提交消息或源码。
- 真实多仓库变更检测由每仓库最多四次串行 Git 调用改为单次 `name-status` 解析与最多 8 路有界并发；图证据定位从逐文件模糊检索改为 `file_path` 索引批量查询。UCAP 真实工作区只读测量由约 9.6 秒降至约 0.18 秒，完整 minimal Change Review 约 0.22 秒。

## 4.3.77 Graph-Aware Change Review

- Added bounded weighted best-path impact propagation using relation weight, edge confidence, evidence strength, freshness, and depth decay. SQLite frontier expansion keeps one best path per node and never materializes the full graph on the query hot path.
- Added a unified `change-review` application service across CLI, HTTP, and MCP admin. It combines change detection, scoped refresh of at most 12 relevant files, impact paths, contract risks, test gaps, and verification actions without falling back to a full reindex.
- Added progressive `minimal -> standard -> deep` context, invocation/output/time budgets, generation-aware fingerprint caching, and duplicate-call stop conditions. Generated Agent guidance now starts with the minimal review and reuses equivalent results.
- Upgraded `architecture-communities` to explicit offline architecture-health analysis with seeded Leiden when optional `igraph` is installed and deterministic weighted label propagation otherwise, plus bounded Brandes bridges, surprising cross-community links, and untested central hotspots. Findings remain `INFERRED`.
- Added independent Git co-change evaluation and `release-gate --cochange-commits`. Same-commit files excluding the seed form the ground truth; execution failures are isolated as `environment_error`, and only hashed references and aggregate metrics are retained.
- Reworked multi-repository change detection from up to four serial Git calls per repository to one `name-status` parse per scope with at most eight workers. Graph evidence now uses indexed batched `file_path` lookup instead of per-file fuzzy search. A read-only UCAP measurement dropped from about 9.6 seconds to 0.18 seconds, with the complete minimal Change Review around 0.22 seconds.

## 4.3.76 MCP 装载状态防误判 / MCP Loading-State Diagnostics

- Agent 协议将 MCP 状态改为三态：已发现、装载中或未知、已确认不可用。首轮工具快照缺少 `mc_*` 时先延迟发现并调用 `mc_freshness`，配置 enabled 但会话未注入工具时明确提示刷新会话，不再误报“未加载”或“不可用”。
- 生成的 Memory Center MCP 绑定新增 30 秒启动预算；`runtime-audit` 会把该字段纳入一致性检查。示例 Agent 指令、MCP 指南和用户指南同步更新。

## 4.3.76 MCP Loading-State Diagnostics

- Agent instructions now model MCP availability as three states: discovered, loading or unknown, and confirmed unavailable. A missing `mc_*` entry in the initial tool snapshot triggers lazy discovery and an `mc_freshness` probe; an enabled binding without session tools now asks for a session refresh instead of falsely reporting the server as unloaded or unavailable.
- Generated Memory Center MCP bindings now include a 30-second startup budget, and `runtime-audit` validates it. Example agent instructions and MCP/user guides have been updated.

## 4.3.75 交付读模型一致性与有界查询 / Delivery Projection Consistency and Bounded Queries

- 回执惰性同步改为锁内快照，并登记读取前的尺寸与 mtime；并发追加不再被错误标记为已同步，下一次读取会自动补齐。旧读模型通过 `projection_version` 惰性升级，JSONL 回填在单个 SQLite 事务中按 500 条分批消费。
- 新增验收项与证据引用稀疏关系索引。状态和关闭门禁直接查询可信验收覆盖，不再加载、传输和反序列化全部可信回执；早期阶段也不再执行无关回执查询。
- JSONL 尾读会丢弃任意字节起点产生的不完整首行，合法中文 UTF-8 不再误报损坏。新旧 replay 在按 `contract_sha256` 和 `activation_id` 过滤后才应用数量上限，旧数据不会挤掉当前发布证据。
- 内部幂等初始化不再重复更新任务活动时间；新增并发水位、多字节尾读、混合 replay、有界查询、流式回填和旧 schema 升级回归测试。

## 4.3.75 Delivery Projection Consistency and Bounded Queries

- Receipt lazy synchronization now uses a locked snapshot and records the size and mtime observed before reading. Concurrent appends can no longer be marked as already synchronized and are repaired on the next read. Existing projections upgrade lazily through `projection_version`, with JSONL consumed in 500-row batches inside one SQLite transaction.
- Added sparse acceptance and evidence-reference indexes. Status and close gates query trusted acceptance coverage directly instead of loading, transferring, and decoding every trusted receipt; early stages no longer issue unrelated receipt queries.
- JSONL tail reads discard an incomplete first line created by an arbitrary byte offset, preserving valid multibyte UTF-8. Mixed replay sources are filtered by `contract_sha256` and `activation_id` before limits are applied, so legacy rows cannot evict current publication evidence.
- Internal idempotent initialization no longer writes task activity twice. Regression coverage now includes synchronization races, multibyte tails, mixed replays, bounded queries, streaming backfill, and old-schema upgrades.

## 4.3.74 可信回执与增量读模型 / Trusted Receipts and Incremental Read Model

- 修复外部回执伪造成 `manual_verified` 的可信漏洞：解析同时校验状态、证据种类、原始引用归属和执行器证据文件。系统规范引用始终优先保留，不会被 50 条用户引用截断。
- 验证回执 JSONL 继续作为审计源，统一 `graph.db` 新增轻量 `delivery_receipts` 查询读模型。旧 JSONL 首次访问时按任务惰性回填，后续用尺寸和 mtime 增量同步；任务 history 固定保留最近 200 条，千条连续写入不再反复扫描全部历史。
- `manual_verified` 保存 `reported_actor`、`actor_source` 与 `identity_assurance=self_asserted`，明确区分调用方声明和认证身份。字符串数组拒绝对象或嵌套数组；损坏 JSON/JSONL 中断操作并保留原文件。
- replay 改为 observation 内的派生投影，一次原子追加同时保存观测事实和脱敏 replay；旧 replay 文件仍可读取，但新观测不再依赖第二次文件写入。

## 4.3.74 Trusted Receipts and Incremental Read Model

- Fixed a trust bug that allowed external receipts to masquerade as `manual_verified`. Resolution now checks status, evidence kind, original reference ownership, and executor evidence files. The canonical reference is reserved ahead of user references and cannot be truncated at the 50-reference boundary.
- Receipt JSONL remains the audit source while the unified `graph.db` gains a lightweight `delivery_receipts` query model. Existing JSONL is lazily backfilled per task and then synchronized by size and mtime. Task history retains the latest 200 entries, avoiding repeated full-history scans during long write sequences.
- `manual_verified` stores `reported_actor`, `actor_source`, and `identity_assurance=self_asserted`, distinguishing caller claims from authenticated identity. String arrays reject objects and nested arrays; corrupt JSON or JSONL stops the operation without overwriting the source.
- Replay is now a derived projection embedded in each observation, so one atomic append stores both the outcome fact and redacted replay. Legacy replay files remain readable, while new observations no longer depend on a second file write.

## 4.3.73 交付证据并发与长期一致性 / Delivery Evidence Concurrency and Long-Term Consistency

- 验证回执不再只读取最后 100 条；任务级流式读取保证早期通过证据持续可解析，同时避免全工作区扫描。人工验证现在必须提供明确操作人，数组字段在 CLI、HTTP、MCP 统一校验。
- Skill 观测在同一事务中完成活跃状态复核、证据去重、观测与 replay 追加；Registry 对独立陈旧快照做按 Skill 合并，并将 canary、契约更新、发布和回滚收敛到完整读改写事务。
- 子任务状态、阶段门禁、历史和交付矩阵采用锁内原子写入；需求、子任务和验收文件更新后保持 schema v2。验证命令不存在、权限或编码异常返回结构化 `environment_error`，不再暴露内部异常。

## 4.3.73 Delivery Evidence Concurrency and Long-Term Consistency

- Validation receipts are no longer limited to the latest 100 entries. Task-local streaming keeps older passed evidence resolvable without scanning the workspace. Manual verification now requires an explicit actor, and CLI, HTTP, and MCP consistently validate array fields.
- Skill observations atomically recheck lifecycle, deduplicate evidence, and append both observation and replay. The registry merges independent stale snapshots by Skill, while canary, contract update, publication, and rollback use complete read-modify-write transactions.
- Subtask state, stage gates, history, and delivery matrices use locked atomic writes. Requirement, subtask, and acceptance files remain schema v2 after updates. Missing commands, permission failures, and encoding errors now return structured `environment_error` results instead of internal exceptions.

## 4.3.72 Skill 证据与生命周期闭环修复 / Skill Evidence and Lifecycle Closure Fixes

- CLI、HTTP、MCP 现在均可显式记录 `manual_verified`，并自动生成不泄露任务标题的 `delivery-validation:<task-ref>:<receipt-id>` 引用。关闭、候选、观测和发布只接受可解析的已通过回执；伪造引用及同一回执重复计数会被拒绝。
- Skill 每次进入 canary 都生成独立 `activation_id`。回滚后复用稳定 Skill 记录开启新 activation，旧观测与 replay 不进入新评估；状态、契约文件和阈值建议保持一致。
- 残缺旧契约不再进入默认推荐；Skill registry 使用原子替换、有效备份恢复、双损坏拒写和稳定 ID 去重。协作资产注册失败不会把已完成发布误报为失败，而是返回可执行的 `artifact asset-sync` 修复动作。
- 修复真实工作区性能脚本的导入结构，恢复仓库级 Ruff 门禁。

## 4.3.72 Skill Evidence and Lifecycle Closure Fixes

- CLI, HTTP, and MCP can now explicitly record `manual_verified` receipts and automatically emit privacy-safe `delivery-validation:<task-ref>:<receipt-id>` references. Close, candidate, observation, and publication gates accept only resolvable passed receipts; forged references and duplicate receipt counting are rejected.
- Every canary run has an independent `activation_id`. Restarting after rollback reuses the stable Skill record while excluding prior observations and replays; status, generated contract files, and threshold recommendations stay aligned.
- Incomplete legacy contracts no longer enter default recommendation. The Skill registry now uses atomic replacement, valid-backup recovery, double-corruption refusal, and stable-ID deduplication. Collaboration-asset failures return an actionable `artifact asset-sync` repair without misreporting an already completed publication as failed.
- Fixed the real-workspace benchmark import structure and restored the repository-wide Ruff gate.

## 4.3.71 可执行经验边界契约 / Executable Experience-Boundary Contract

- 交付 Skill 契约升级为 v2：新增适用条件、禁止条件、验收证据和回滚方式；候选、灰度、发布、推荐和生成的 `SKILL.md` 共享同一份契约。
- 进入灰度和发布前必须有至少一条与 `acceptance_evidence` 匹配的真实验证回执。默认只接受 `executor` 或 `manual_verified`，并要求 `acceptance_ids` 与 `evidence_refs`，阻止无来源的模型自评沉淀为团队经验。
- 推荐结果现在明确返回禁止条件、停止条件和回滚动作；CLI、README、用户指南、参考文档、规格与 MCP 指南均同步了完整 JSON 契约。

## 4.3.71 Executable Experience-Boundary Contract

- Delivery Skill contracts are now v2 and add applicability conditions, prohibited conditions, acceptance evidence, and rollback behavior. Candidates, canaries, publication, recommendations, and generated `SKILL.md` files share this contract.
- Canary and publication require at least one real validation receipt matching `acceptance_evidence`. The default accepts only `executor` or `manual_verified` with both `acceptance_ids` and `evidence_refs`, preventing unsourced model self-assessments from becoming team experience.
- Recommendations now expose prohibited conditions, stop conditions, and rollback actions. The CLI, README, user guide, reference, specification, and MCP guide document the complete JSON contract.

## 4.3.70 AST 重载返回类型消歧 / AST Overload Return-Type Disambiguation

- 嵌套调用 AST 现在携带内层参数标识与参数数量；resolver 仅在参数的静态类型与重载声明完全一致时选择返回类型。该规则可解析转换器 `convert(req)` 后的 DTO 链式 accessor，同时在变量类型缺失、重载不匹配或仍不唯一时维持 unresolved。

## 4.3.70 AST Overload Return-Type Disambiguation

- Nested-call AST facts now retain inner argument names and arity. The resolver chooses an overload return type only when static argument types exactly match its declared parameters. This resolves DTO accessors after converters such as `convert(req)` while keeping missing, mismatched, or ambiguous overloads unresolved.

## 4.3.69 局部刷新跨文件解析修复 / Scoped Refresh Cross-File Resolution Fix

- 路径或项目定向 reindex 现在使用完整持久化符号表进行只读调用解析，但仅重写变更范围的图切片。修复了局部刷新后跨文件接口、DTO、转换器调用被错误降级为 unresolved 的问题，同时避免向未变更文件写入图数据。

## 4.3.69 Scoped Refresh Cross-File Resolution Fix

- Path- and project-scoped reindex now resolves calls against the full persisted symbol index while rewriting only the changed graph slice. This prevents cross-file interface, DTO, and converter calls from being incorrectly downgraded to unresolved after a local refresh, without rewriting unchanged graph data.

## 4.3.68 AST 嵌套调用解析 / AST Nested Call Resolution

- Tree-sitter Java 现在补充一段可证明的嵌套调用链，并将唯一返回类型上的显式方法或 Lombok accessor 解析为 `chain_return_type` / `chain_return_type_lombok_accessor`。返回类型会在 tree-sitter 与补充解析合并处统一规范化，避免 `public Type` 与 `Type` 被误判为多个类型；Tree-sitter 不可用时仍保守降级。

## 4.3.68 AST Nested Call Resolution

- Tree-sitter Java now supplements a single provable nested call transition and resolves explicit methods or Lombok accessors on a unique return type as `chain_return_type` / `chain_return_type_lombok_accessor`. Return types are normalized across tree-sitter and supplement facts so `public Type` and `Type` do not look ambiguous; the unavailable-parser path remains conservative.

## 4.3.67 Java 嵌套参数伪链路修复 / Java Nested-Argument False Chain Fix

- 正则 Java 解析器不再把 `foo.bar(convert(x).setY(y))` 误判为 `foo.setY(...)` 链式调用。嵌套实参尚不能证明接收者类型时保持未展开，避免向图谱写入错误的低置信调用边；受影响文件可通过局部 reindex 清理旧边。

## 4.3.67 Java Nested-Argument False Chain Fix

- The regex Java parser no longer misclassifies `foo.bar(convert(x).setY(y))` as a `foo.setY(...)` chain. Nested arguments remain unexpanded until their receiver type can be proven, avoiding false low-confidence graph edges; a scoped reindex removes affected legacy edges.

## 4.3.66 Java 调用解析 Campaign 选择修复 / Java Call Resolution Campaign Selection Fix

- 未解析调用报告的 `campaign` 不再按全量最大类别错误地选择外部依赖或范围外调用；它仅在可通过私有逻辑锚点验证的本地类别中选择目标，并返回 `candidate_samples`、排除类别与明确的范围治理动作。这样不会为降低未解析率而诱导不安全的 resolver fallback。

## 4.3.66 Java Call Resolution Campaign Selection Fix

- The unresolved-call report no longer picks external or out-of-scope calls merely because they are the largest category. Its `campaign` selects only locally provable categories, returns `candidate_samples` and excluded categories, and gives an explicit scope-governance action when no safe resolver campaign exists.

## 4.3.65 外部能力目录与漂移审计 / External Capability Registry and Drift Audit

- 新增 `external-capability-audit` 与显式 `external-capability-snapshot`，以及 MCP Admin 对应 action。只采集 Codex/Claude Code Skill、插件和 MCP 配置的元数据、哈希与作用域，不读取正文、不执行安装或宿主配置变更。

## 4.3.64 真实工作区运行治理 / Real Workspace Runtime Governance

- 新增只读 `runtime-governance` CLI、HTTP 与 MCP Admin 入口，统一汇总 P95 趋势、空间预算、索引 generation、ANN 与活跃后台任务。未初始化工作区不会为巡检创建 SQLite，任何 reindex、ANN rebuild、vacuum 或 GC 仍必须显式执行。

## 4.3.64 Real Workspace Runtime Governance

- Added read-only `runtime-governance` through CLI, HTTP, and MCP Admin. It aggregates P95 trends, storage budget, index generation, ANN, and active jobs. Inspection never creates SQLite in an uninitialized workspace; reindex, ANN rebuild, vacuum, and GC remain explicit actions.

## 4.3.63 评测可信化与 Java 精度 Campaign / Evaluation Trust and Java Precision Campaign

- `skill-up` 初始化新增本地评测 policy，默认禁用未隔离的 `without_skill` 对比并要求 3 到 5 个脱敏可观察 case；执行结果区分 `pass`、`skill_failure`、`evaluation_failure` 与 `environment_error`，环境故障不计入 Skill 失败率。
- Java 未解析调用报告新增 `campaign` 与逻辑锚点 case 契约。报告选定最大类别，但在 expected/allowed/forbidden target 门禁通过前明确锁定 resolver/parser 规则修改，避免猜测性 fallback。

## 4.3.63 Evaluation Trust and Java Precision Campaign

- `skill-up` initialization now writes a local evaluation policy that disables non-isolated `without_skill` comparisons and requires 3 to 5 sanitized observable cases. Runs classify `pass`, `skill_failure`, `evaluation_failure`, and `environment_error`, with environment faults excluded from Skill failure rates.
- The unresolved Java-call report now adds a `campaign` and logical-anchor case contract. It identifies the largest category but locks resolver/parser changes until expected/allowed/forbidden target gates pass, preventing speculative fallbacks.

## 4.3.62 真实 P95 闭环、路由契约审计与长任务体验 / Real P95 Loop, Route Contract Audit, and Long-Task UX

- 新增显式 `performance-snapshot` / `performance-status`、HTTP 性能快照接口和 MCP Admin action。快照只保存 generation 与聚合 P50/P95/P99/结果计数，不保存查询、路径或源码，且永不进入普通查询热路径。
- HTTP 注册表现在自动为全部已注册路径建立读写契约，并提供 `http-route-contract-audit`。审计会识别未分类、孤立声明、非法方法和名称表现为写入却被误声明为 GET 的路由。
- 后台任务状态新增进度百分比、已耗时、ETA、可取消性与恢复动作；`/ui/jobs` 只轮询紧凑任务状态，不读取索引正文。

## 4.3.62 Real P95 Loop, Route Contract Audit, and Long-Task UX

- Added explicit `performance-snapshot` / `performance-status`, HTTP snapshot routes, and MCP Admin actions. Snapshots retain generation and aggregate P50/P95/P99/outcome counts only, never queries, paths, or source, and never run on the normal query hot path.
- The HTTP registry now establishes read/write contracts for every registered path and exposes `http-route-contract-audit`. It detects unclassified routes, orphan declarations, invalid methods, and mutation-like paths accidentally declared as GET.
- Background job status now includes progress percentage, elapsed time, ETA, cancel availability, and recovery action; `/ui/jobs` polls only compact job state rather than index content.

## 4.3.61 本地热路径、空间预算与协作体验 / Local Hot Paths, Storage Budget, and Collaboration Experience

- Context Pack 改为批量读取 top-K 节点的一跳关系，减少 SQLite 往返；workspace 的 index、artifact、audit 写入使用分域锁，降低 watcher、任务同步和审计追加的相互阻塞。
- 新增 `artifact storage-budget`，按 graph、index、artifacts、memory 输出空间、预算状态和只读维护建议；增量 generation 持续以文件内容哈希识别未变化输入，不额外落盘冗余 AST 缓存。
- 本地 HTTP/MCP 资产登记在未传 actor 时自动采用声明 owner 或 `local-agent`；协作治理仍只在显式共享时生效。

## 4.3.61 Local Hot Paths, Storage Budget, and Collaboration Experience

- Context Pack now batch-reads one-hop edges for top-K nodes, reducing SQLite round trips. Workspace index, artifact, and audit writes use scoped locks to reduce watcher, task-sync, and audit contention.
- Added `artifact storage-budget`, reporting graph, index, artifacts, and memory usage with read-only maintenance guidance. Incremental generations continue to use file content hashes without persisting a redundant AST cache.
- Local HTTP/MCP asset registration derives a missing actor from the declared owner or `local-agent`; governance remains opt-in through explicit sharing.

## 4.3.60 HTTP 安全、资产可靠性与 Context Pack 硬预算 / HTTP Security, Asset Reliability, and Context-Pack Hard Budgets

- HTTP GET 现在严格只读；所有会改变工作区状态的路由必须 POST。非回环地址绑定必须提供 `--access-token` 或 `MEMORY_CENTER_HTTP_TOKEN`。
- 协作资产 registry 改为临时文件原子替换和有效备份恢复；损坏且无法恢复时拒绝写入，不再以空 registry 覆盖历史数据。活跃 CodeGraph 使用稳定系统主体，多个 Agent 可重复同步。
- 资产 metadata 限制为 16 KiB，status/loadout 使用默认总预算并返回 `truncated`；Context Pack 增加 `budget_tokens`、`truncated_sections`，最终响应执行硬性 Token 裁剪。

## 4.3.60 HTTP Security, Asset Reliability, and Context-Pack Hard Budgets

- HTTP GET is now strictly read-only; every route that can change workspace state requires POST. Non-loopback binding requires `--access-token` or `MEMORY_CENTER_HTTP_TOKEN`.
- Collaboration asset registries now use temporary-file atomic replacement and valid-backup recovery. Writes fail safely when neither copy is valid, while the active CodeGraph has a stable system owner for multi-Agent synchronization.
- Asset metadata is capped at 16 KiB; status/loadout use total response budgets and expose `truncated`. Context packs add `budget_tokens` and `truncated_sections`, with a final hard token-budget guard.

## 4.3.59 协作资产权限与预算修复 / Collaboration Asset Authorization and Budget Fixes

- 既有协作资产只允许 owner 更新或绑定；审批禁止 owner 自审，registry 的读改写在同一文件锁内完成，避免并发丢写。
- 资产同步保留已审批状态；私有资产可装载到 owner 显式绑定的 Agent/角色；协作资产摘要纳入 context pack 的独立预算与 Token 估算。

## 4.3.59 Collaboration Asset Authorization and Budget Fixes

- Existing collaboration assets can only be updated or bound by their owner; owners cannot self-approve, and registry read-modify-write operations share one file lock to prevent concurrent lost updates.
- Asset synchronization preserves approved state; private assets may load for owner-bound Agents/roles; collaboration summaries now consume a dedicated context-pack budget and token estimate.

## 4.3.58 本地协作资产与角色装载 / Local Collaboration Assets and Role Loadouts

- 新增统一协作资产 registry，覆盖 Task、已发布 Delivery Skill、Wiki 文档与活跃 CodeGraph。资产带 owner、版本、状态、可见性、来源与 Agent/角色绑定；私有为默认值，团队/受限共享须提交并审批。
- `mc_context_pack`、HTTP、CLI 与 `mc_admin` 接入有界资产 loadout。上下文只附带授权资产摘要、来源引用和代码证据，不复制源码、文档正文或会话内容。
- 新增工作区内文档 Wiki 资产登记，派生 Markdown 链接和有界代码节点证据；已发布 Delivery Skill 自动登记为私有资产。

## 4.3.58 Local Collaboration Assets and Role Loadouts

- Added a unified local collaboration asset registry for Tasks, published Delivery Skills, Wiki documents, and the active CodeGraph. Assets carry owner, version, state, visibility, provenance, and Agent/role bindings; private is the default and team/restricted sharing requires submission plus approval.
- Added bounded asset loadouts to `mc_context_pack`, HTTP, CLI, and `mc_admin`. Context includes only authorized metadata, excerpts, provenance, and code evidence, never source, document bodies, or conversations.
- Added workspace-document Wiki registration with bounded Markdown links and graph-backed code evidence; published Delivery Skills register automatically as private assets.

## 4.3.57 架构门禁修复 / Architecture Gate Fixes

- 补齐 `core/providers` 模块边界说明，并修正 targeted refresh 测试导入顺序，恢复全量 Ruff 与架构回归门禁。
- 将 MCP 查询工具共享的符号提取、请求校验、可降级分析和响应整形迁移至 `mcp/tool_support.py`，使 `mcp/server.py` 保持为轻量工具注册入口。

## 4.3.57 Architecture Gate Fixes

- Added the `core/providers` module guide and fixed targeted-refresh test import order, restoring Ruff and architecture regression gates.
- Moved shared MCP query helpers for symbol extraction, validation, graceful degradation, and response shaping into `mcp/tool_support.py`, keeping `mcp/server.py` focused on tool registration.

## 4.3.56 可执行 Skill 契约与脱敏 Replay / Executable Skill Contracts and Redacted Replays

- 交付 Skill 候选新增版本化 `contract`：适用语言、前置条件、停止条件、输入字段、输出字段和 replay 策略。`delivery-skill-contract-update`、`/workspace/delivery/skill/contract`、`mc_admin(action="delivery_skill_contract_update")` 复用同一状态转换。
- canary 与发布会校验契约；发布要求达到 `minimum_verified_passed`（默认三条）的带验证引用成功观测和自动生成脱敏 replay，且没有失败。推荐入口可按 `language` 过滤已发布 Skill，并返回适用边界与停止条件。
- 新增 `delivery-skill-replay`、`/workspace/delivery/skill/replay`、`mc_admin(action="delivery_skill_replay")`。replay 仅保存契约哈希、语言、结果、证据引用、时延和 Token 指标；不保存源码、需求正文、日志、外部正文、密钥或操作人。
- 观测与 replay 按 `contract_sha256` 隔离；修订 canary 契约会要求重新积累当前版本证据，已发布 Skill 的契约不可原地修改。

## 4.3.56 Executable Skill Contracts and Redacted Replays

- Delivery Skill candidates now carry a versioned `contract`: applicable languages, preconditions, stop conditions, input fields, output fields, and replay policy. `delivery-skill-contract-update`, `/workspace/delivery/skill/contract`, and `mc_admin(action="delivery_skill_contract_update")` share the same state transition.
- Canary and publication validate the contract. Publication requires the contract's `minimum_verified_passed` threshold (three by default) of successful observations with verification references and automatically generated redacted replays, with no failures. Recommendations can filter published Skills by `language` and return applicability boundaries and stop conditions.
- Added `delivery-skill-replay`, `/workspace/delivery/skill/replay`, and `mc_admin(action="delivery_skill_replay")`. Replays retain only contract hashes, languages, outcomes, evidence references, latency, and token metrics; they never store source, request bodies, logs, external bodies, secrets, or actors.
- Observations and replays are isolated by `contract_sha256`; a revised canary contract requires fresh evidence, while a published Skill contract is immutable.

## 4.3.55 跨 Provider 证据融合与健康路由 / Cross-Provider Evidence Fusion and Health Routing

- Bridge 的只读 `code_navigation` 工具现在作为动态 Provider 进入 `ProviderRegistry`，与 GitNexus 使用同一进程内 P95、错误率和成本分排序；超时或失败会在后续联邦初始化中被降权。
- 新增 `provider-evidence-fuse`、`GET /workspace/provider-evidence-fuse` 与 `mc_mcp_bridge(evidence_refs_json=...)`。融合仅接受脱敏 EvidenceRef，按显式 `claim.subject/predicate/value` 去重并返回 `CONSISTENT`、`CONFLICT` 或 `INSUFFICIENT_EVIDENCE`。
- 冲突生成只读 `verify_conflict` Action；无结构化 Claim 的结果只保留来源线索，绝不根据外部正文、哈希或文本差异制造冲突。融合器不持久化外部正文或 EvidenceRef。

## 4.3.55 Cross-Provider Evidence Fusion and Health Routing

- Read-only Bridge tools with `code_navigation` now join `ProviderRegistry` as dynamic providers and share in-process P95, error-rate, and cost-score routing with GitNexus. Timeouts and failures are penalized for later federated bootstrap calls.
- Added `provider-evidence-fuse`, `GET /workspace/provider-evidence-fuse`, and `mc_mcp_bridge(evidence_refs_json=...)`. Fusion accepts only redacted EvidenceRef values, deduplicates explicit `claim.subject/predicate/value`, and returns `CONSISTENT`, `CONFLICT`, or `INSUFFICIENT_EVIDENCE`.
- Conflicts emit read-only `verify_conflict` Actions. Results without structured claims remain provenance hints and never become conflicts from external body, hash, or text differences. The fuser persists neither external bodies nor EvidenceRef values.

## 4.3.54 MCP SDK 运行时兼容修复 / MCP SDK Runtime Compatibility Fix

- 将 MCP SDK 约束为 `mcp>=1.2.0,<2.0.0`。SDK 2.0 已移除本项目 MCP Server 使用的 `mcp.server.fastmcp` 路径；此前宽泛依赖会使 `memory-center-mcp` 在已安装环境中无法启动。
- 同步更新回归断言并在本地 pipx 环境验证 MCP Server 能创建，确保受限 MCP Client Bridge 的 MCP 入口不是仅源码可达。

## 4.3.54 MCP SDK Runtime Compatibility Fix

- Constrained the MCP SDK to `mcp>=1.2.0,<2.0.0`. SDK 2.0 removed the `mcp.server.fastmcp` path used by this project's MCP Server, so the former broad dependency could prevent `memory-center-mcp` from starting.
- Updated the regression assertion and verify MCP Server creation in the local pipx environment so the restricted MCP Client Bridge is reachable through MCP at runtime, not only in source.

## 4.3.53 受限 MCP Client Bridge / Restricted MCP Client Bridge

- 新增 `mcp-bridge-status`、`mcp-bridge-action`、`GET /workspace/mcp-bridge-status`、`GET /workspace/mcp-bridge-action` 和 MCP `mc_mcp_bridge`。Memory Center 可直接调用工作区策略白名单中的 IDEA MCP、GitNexus MCP 等外部 HTTP MCP Server。
- 策略固定在 `.memory-center/provider-mcp-policy.json`：仅接受 `http(s)` URL、`sse|streamable_http` 传输、允许的工具名以及 `{query}` / `{target}` 参数模板；不支持 stdio、自由工具名、自由参数、令牌字段或任意命令。
- Bridge 在调用前通过 MCP `list_tools` 校验工具真实暴露，单次超时最多 60 秒，输出最多 12,000 字符。外部正文不进入索引、SQLite、断言或审计存储；成功结果只附带会话级 `EvidenceRef`。
- `controlled_write` 和 `destructive` 动作无条件要求显式 `confirm=true`，即使策略错误声明为无需确认也不会放行。

## 4.3.53 Restricted MCP Client Bridge

- Added `mcp-bridge-status`, `mcp-bridge-action`, `GET /workspace/mcp-bridge-status`, `GET /workspace/mcp-bridge-action`, and MCP `mc_mcp_bridge`. Memory Center can directly invoke external HTTP MCP servers such as IDEA MCP and GitNexus MCP that are explicitly whitelisted by workspace policy.
- `.memory-center/provider-mcp-policy.json` accepts only `http(s)` URLs, `sse|streamable_http` transports, allowed tool names, and `{query}` / `{target}` argument templates. Stdio, free-form tools and parameters, token fields, and arbitrary commands are unsupported.
- The bridge verifies the exposed tool with MCP `list_tools`, caps each call at 60 seconds and output at 12,000 characters. External bodies never enter indexes, SQLite, assertions, or audit storage; a successful result only adds a session-level `EvidenceRef`.
- `controlled_write` and `destructive` actions always require explicit `confirm=true`, even if a malformed policy declares otherwise.

## 4.3.52 Provider 健康路由与按需索引行动卡 / Provider Health Routing and On-Demand Index Actions

- Provider Registry 新增进程内滑动窗口健康观测：每次调用记录耗时和结果，返回 P95、错误率和成本分，并以静态优先级加健康惩罚选择读取 Provider；不启动后台扫描，也不写入工作区。
- GitNexus 明确返回未索引或陈旧状态时，`bootstrap-context` 增加 `action_cards`，建议确认后运行固定的 `analyze --index-only`；不会隐式建立或刷新外部索引。

## 4.3.52 Provider Health Routing and On-Demand Index Actions

- Provider Registry adds in-process sliding-window health observations. Each call records latency and status, returning P95, error rate, and cost score; read routing combines static priority with health penalties without background scans or workspace writes.
- When GitNexus explicitly reports a missing or stale index, `bootstrap-context` adds confirmation-gated `action_cards` for fixed `analyze --index-only`; it never creates or refreshes an external index implicitly.

## 4.3.51 受控外部动作 / Controlled External Actions

- 新增 `provider-action`、`GET /workspace/provider-action` 与 MCP `mc_provider_action`。GitNexus 支持固定的 `impact`、`trace`、`detect-changes`、`check`、`analyze` 与 `clean` 动作。
- 读取动作可直接执行；`analyze` 为 `controlled_write`、`clean` 为 `destructive`，均必须显式 `confirm=true`。所有参数由固定动作模板生成，不接受自由 argv 或 shell。

## 4.3.51 Controlled External Actions

- Added `provider-action`, `GET /workspace/provider-action`, and MCP `mc_provider_action`. GitNexus supports fixed `impact`, `trace`, `detect-changes`, `check`, `analyze`, and `clean` actions.
- Read actions execute directly; `analyze` is `controlled_write` and `clean` is `destructive`, both requiring explicit `confirm=true`. All arguments come from fixed action templates; free argv and shell input are rejected.

## 4.3.50 Provider Registry 与临时 EvidenceRef / Provider Registry and Ephemeral EvidenceRef

- 新增只读 `ProviderRegistry`：按能力、优先级、超时、结果上限、写入模式和隐私模式选择外部 Provider，并记录完整降级尝试。
- 联邦上下文结果新增 additive `provider_selection` 与 `evidence_ref`。`EvidenceRef` 仅保留来源、范围、观测时间、耗时、正文哈希和验证状态，不保存外部正文，也不会进入长期图谱。

## 4.3.50 Provider Registry and Ephemeral EvidenceRef

- Added read-only `ProviderRegistry`, selecting external providers by capability, priority, timeout, result cap, mutation mode, and privacy mode while reporting every fallback attempt.
- Federated context now adds `provider_selection` and `evidence_ref`. An `EvidenceRef` retains only provenance, scope, observation time, latency, content hash, and verification state; it never stores external body content or enters the long-term graph.

## 4.3.49 零初始化联邦上下文 / Zero-Initialization Federated Context

- 新增 `bootstrap-context`、`GET /workspace/bootstrap-context` 与 MCP `mc_bootstrap_context`。已有 workspace 时读取 Memory Center；未初始化目录会尝试 GitNexus 的固定只读 `status/query/context` 命令，失败后才建议有界本地搜索。
- GitNexus 结果标记为临时外部证据，不写入 `.memory-center/`、不合并进图谱、不会触发 analyze/reindex/clean 或任意 shell。结果含 provider、范围、观测时间、耗时、持久化边界与下一步动作；会话缓存最长 30 秒。

## 4.3.49 Zero-Initialization Federated Context

- Added `bootstrap-context`, `GET /workspace/bootstrap-context`, and MCP `mc_bootstrap_context`. Existing workspaces use Memory Center; uninitialized directories attempt fixed read-only GitNexus `status/query/context` commands before suggesting bounded local search.
- GitNexus results are ephemeral external evidence: they never write `.memory-center/`, merge into the graph, trigger analyze/reindex/clean, or execute arbitrary shell. Results include provider, scope, observed time, latency, persistence boundary, and next action; the session cache is capped at 30 seconds.

## 4.3.48 可选 skill-up 评测适配器 / Optional skill-up Evaluation Adapter

- 新增 `delivery-skill-eval-status|init|run`：对已发布 Skill 生成脱敏的 `skill-up` 评测骨架，并通过固定 argv 执行 `validate/run`，可输出 JSON、JUnit、HTML 报告。
- `skill-up` 是可选外部组件，未安装时返回明确诊断；执行必须显式 `--apply`，不接受任意 shell、不会进入查询热路径，也不会绕过现有 canary、证据或发布门禁。

## 4.3.48 Optional skill-up Evaluation Adapter

- Added `delivery-skill-eval-status|init|run`: creates a sanitized `skill-up` evaluation skeleton for published Skills and invokes fixed `validate/run` argv with JSON, JUnit, and HTML reports.
- `skill-up` remains optional. Missing installations are diagnosable; execution requires explicit `--apply`, accepts no arbitrary shell, stays out of query paths, and cannot bypass canary, evidence, or publication gates.

## 4.3.47 Lombok 布尔属性调用解析 / Lombok Boolean Property Call Resolution

- Java 调用解析器现识别 Lombok `@Data`、`@Getter`、`@Setter` 或 `@Value` 中 `isSuccess` 形式布尔字段生成的 `isSuccess()` / `setSuccess(...)` 访问器。仅在字段与 Lombok 注解均已索引时补充本地边，外部类型和普通未声明方法仍保持未解析。

## 4.3.47 Lombok Boolean Property Call Resolution

- The Java call resolver now recognizes `isSuccess`-style boolean fields and their Lombok-generated `isSuccess()` / `setSuccess(...)` accessors for indexed `@Data`, `@Getter`, `@Setter`, or `@Value` types. External types and ordinary undeclared methods remain unresolved.

## 4.3.46 语义索引去重与运行时检索 / Semantic Index Deduplication and Runtime Retrieval

- `semantic-node-index` 不再持久化全量节点文档、稀疏向量、词频和 dense embedding；SQLite 倒排索引与 ANN 向量索引成为唯一检索存储，命中后仅按 ID 有界回填图节点，消除大型工作空间的重复镜像与 Python 全量扫描。
- 新增 `artifact semantic-index-compact --dry-run|--apply`，可无 reindex 压缩旧版本语义镜像；随后通过 `artifact storage-vacuum --apply` 显式回收 SQLite 页。

## 4.3.46 Semantic Index Deduplication and Runtime Retrieval

- `semantic-node-index` no longer persists full node documents, sparse vectors, term frequencies, or dense embeddings. SQLite inverted and ANN vector indexes are now the sole retrieval stores; hits are bounded and hydrated by node ID.
- Added `artifact semantic-index-compact --dry-run|--apply` to compact legacy semantic mirrors without reindex, followed by `artifact storage-vacuum --apply` to reclaim SQLite pages.

## 4.3.45 FTS5 批量重建与局部维护 / FTS5 Bulk Rebuild and Scoped Maintenance

- 完整 FTS5 重建改为 SQLite 内部 `INSERT ... SELECT`，不再将全量节点与搜索文本加载进 Python；主图 rebuild 可避免与 FTS rebuild 重复清空搜索表。
- 局部刷新把 FTS 删除与插入收敛为单事务批量操作，并在 reindex 结果中增加 `fts_sync_mode`、`fts_changed_nodes`、`fts_elapsed_ms`。

## 4.3.45 FTS5 Bulk Rebuild and Scoped Maintenance

- Full FTS5 rebuild now uses SQLite-internal `INSERT ... SELECT` without loading all graph nodes and search text into Python; main graph rebuild can avoid clearing the search table twice.
- Scoped refresh batches FTS deletes and inserts in one transaction and adds `fts_sync_mode`, `fts_changed_nodes`, and `fts_elapsed_ms` to reindex output.

## 4.3.44 SQLite 单副本索引导出 / SQLite Single-Copy Index Exports

- 文件、符号、契约、拓扑和语义等大型可重建索引只保留在 SQLite `index_mirror`，不再额外写入同内容 JSON 文件；读取入口统一走 SQLite。
- 新增 `artifact index-export-cleanup --dry-run|--apply`，只删除已存在 SQLite canonical payload 的旧导出，不会删除未迁移的孤立文件。

## 4.3.44 SQLite Single-Copy Index Exports

- Large rebuildable file, symbol, contract, topology, and semantic indexes now remain only in SQLite `index_mirror`; identical JSON files are no longer written, and read paths use SQLite consistently.
- Added `artifact index-export-cleanup --dry-run|--apply`, which removes legacy exports only when a canonical SQLite payload exists and never deletes unmigrated orphan files.

## 4.3.43 索引代际与静态断言空间回收 / Index Generation and Static Assertion Reclamation

- 成功 reindex 后自动执行 generation GC，仅保留当前与上一代；中断（包括 `Ctrl-C`）会将 reindex 生命周期和 index control 明确标记为失败，不再遗留伪 `building` 状态。
- `assertion-sparsify` 现同时删除全部可由图边派生的旧静态断言镜像，包括历史 `SUPERSEDED` SQLite 行与 `json_records` 中的静态 JSON 镜像；人工验证、拒绝和治理覆盖保持不变。

## 4.3.43 Index Generation and Static Assertion Reclamation

- Successful reindex now runs generation GC automatically and retains only the active and previous generations. Interruptions, including `Ctrl-C`, mark both reindex lifecycle and index control as failed instead of leaving a false `building` state.
- `assertion-sparsify` now removes every graph-derived legacy static assertion mirror, including historical `SUPERSEDED` SQLite rows and static JSON mirrors in `json_records`; human verification, rejection, and governance overrides remain intact.

## 4.3.42 Lombok 链式返回类型解析 / Lombok Chained Return-Type Resolution

- Java call resolver 现在可在首段为可验证 Lombok getter、字段类型在工作区唯一且第二段方法真实存在时，解析 `receiver.getField().target()` 为 `chain_lombok_accessor_return_type`；外部或歧义字段类型继续保持未解析。
- 首次 BM25 格式迁移移除了数百万条 posting 的废弃预计算分值，只写入动态查询需要的原始统计，降低完整迁移与完整重建 CPU 成本。

## 4.3.42 Lombok Chained Return-Type Resolution

- The Java call resolver now resolves `receiver.getField().target()` as `chain_lombok_accessor_return_type` only when the first segment is a verifiable Lombok getter, the field type is unique in the workspace, and the second method exists. External or ambiguous field types remain unresolved.
- Initial BM25 migration no longer computes obsolete scores for millions of postings; it writes only raw statistics used by dynamic queries, reducing full-migration and full-rebuild CPU cost.

## 4.3.41 定向刷新增量 BM25 / Incremental BM25 for Scoped Refresh

- SQLite 倒排索引现在持久化原始词频、文档频率和全局长度统计。局部 reindex 只读取、重分词并替换 `changed_node_ids`，未变化 posting 不再删除重写；查询时动态计分，保证与完整重建一致。
- 新格式完整构建不再计算已废弃的逐 posting 预计算分值，首次迁移和完整重建只写入查询所需的原始统计。
- reindex 新增 `bm25_sync_mode` 和 `bm25_changed_docs`。旧 BM25 格式仅在第一次局部刷新时安全完整迁移一次，返回 `full-legacy-fallback`，后续使用 `partial`。

## 4.3.41 Incremental BM25 for Scoped Refresh

- The SQLite inverted index now persists raw term frequencies, document frequencies, and global length statistics. Scoped reindex reads, tokenizes, and replaces only `changed_node_ids`, while untouched postings remain in place. Query-time scoring preserves full-rebuild equivalence.
- Full V2 builds no longer compute obsolete per-posting scores; initial migration and full rebuild retain only raw statistics required at query time.
- Reindex now reports `bm25_sync_mode` and `bm25_changed_docs`. A legacy BM25 index performs one safe full migration on its first scoped refresh as `full-legacy-fallback`; later scoped refreshes report `partial`.

## 4.3.40 发布产物新鲜度与热缓存修复 / Published-Artifact Freshness and Hot-Cache Fix

- 新鲜度优先以已发布 `graph-summary.json` 的时间判断；运行时审计、治理和记忆写入更新共享 `graph.db` 时，不再把索引错误标记为刚刷新。
- 检索缓存键仅使用影响检索策略的新鲜度字段，不再包含展示用的时间与提示文本；同一 generation 的连续查询可以稳定命中缓存。

## 4.3.40 Published-Artifact Freshness and Hot-Cache Fix

- Freshness now prefers the published `graph-summary.json` timestamp. Runtime audit, governance, and memory writes that update shared `graph.db` no longer make the index appear freshly rebuilt.
- Retrieval cache keys retain only freshness fields that affect the retrieval plan, excluding display timestamps and messages so consecutive queries on one generation can reliably hit cache.

## 4.3.39 本地解释器兼容与批量写入修复 / Local Interpreter Compatibility and Batch-Write Fix

- 批量治理写入、向量配对、语义编码结果和工作空间组查询不再依赖 `zip(strict=True)`；改为显式长度校验，因此保留不一致即失败的语义，同时能在 macOS 默认 Python 下正确运行。
- HNSW 返回标签与距离数量不一致时会明确诊断，不再静默截断。

## 4.3.39 Local Interpreter Compatibility and Batch-Write Fix

- Governance batch writes, vector pairing, semantic encoder results, and workspace-group queries no longer depend on `zip(strict=True)`. Explicit length checks preserve fail-fast mismatch semantics while working on the macOS default Python.
- A mismatched HNSW label/distance response now fails with an explicit diagnostic instead of silently truncating.

## 4.3.38 查询外层阶段审计 / Query Outer-Stage Audit

- `memory_query_hybrid` 新增 `performance.timing_ms`，覆盖初始化、新鲜度与策略、核心检索、范围与契约、断言摘要、质量与 Action、响应封装。
- 查询操作审计仅记录上述聚合阶段耗时和核心检索阶段耗时，不记录查询正文、路径或结果载荷，便于在真实工作空间定位缓存外瓶颈。

## 4.3.38 Query Outer-Stage Audit

- `memory_query_hybrid` now exposes `performance.timing_ms` for setup, freshness and policy, core retrieval, scope and contracts, assertion summary, quality and actions, and response wrapping.
- Query operation audit stores only aggregate outer and core-retrieval stage timings, never query text, paths, or result payloads, making real-workspace cache-external bottlenecks observable.

## 4.3.37 已发布 generation 缓存键修复 / Published-Generation Cache-Key Fix

- 检索缓存版本不再依赖共享 SQLite 的文件修改时间；治理 Action、审计和其他运行时写入不会让同一已发布 generation 的核心检索缓存失效。
- 缓存键改为已发布 `active_generation` 与图摘要版本；发布或定向刷新后仍会自动失效。

## 4.3.37 Published-Generation Cache-Key Fix

- Retrieval-cache versioning no longer uses the shared SQLite file mtime, so governance actions, audit events, and other runtime writes do not invalidate the core cache for the same published generation.
- Cache keys now use published `active_generation` and graph-summary versioning; publish and targeted refresh still invalidate automatically.

## 4.3.36 检索热路径性能门禁 / Retrieval Hot-Path Performance Gate

- Hybrid retrieval 新增阶段级 `retrieval_diagnostics.timing_ms`：精确检索、图检索、BM25、语义、向量、图排序、邻居扩展、跨工作空间和结果组装均可定位耗时。
- 相同图 generation、查询、检索配置、策略和新鲜度下启用 20 秒、最多 64 项的进程内核心检索缓存；缓存只复用已索引证据，外层仍执行新鲜度、治理、行动和结果包装逻辑。
- 相同 query 派生的 Action 改用稳定 ID 去重；只在首次出现时写入治理 JSONL 和读模型，重复读取仍返回同一 Action ID。
- `release-gate` 新增默认 `2000ms` 的热查询 P95 绝对预算与 `stage_p95_ms`。超出预算会以 `hot_query_p95_budget_exceeded` 阻断发布；`--max-hot-query-p95-ms 0` 可显式关闭该绝对预算。

## 4.3.36 Retrieval Hot-Path Performance Gate

- Hybrid retrieval now returns per-stage `retrieval_diagnostics.timing_ms` for exact, graph, BM25, semantic, vector, graph rank, enrichment, cross-workspace, and assembly work.
- A bounded 20-second, 64-entry in-process core retrieval cache applies only when graph generation, query, configuration, policy, and freshness match. Freshness, governance, actions, and response wrapping still run outside the cache.
- Actions derived from the same query now use stable-ID deduplication: only the first occurrence writes governance JSONL and its read model, while repeated reads return the same Action ID.
- `release-gate` now enforces a default 2000ms hot-query P95 budget and reports `stage_p95_ms`. Budget overruns fail with `hot_query_p95_budget_exceeded`; `--max-hot-query-p95-ms 0` explicitly disables the absolute budget.

## 4.3.35 Java 基础对象方法范围分类 / Java Object-Method Scope Classification

- 当接收者类型已在工作区可见、但 `equals`、`toString`、`hashCode`、`getClass` 等 Java 基础对象方法未在源码索引中声明时，未解析原因改为 `inherited_method_out_of_scope`。
- 不生成业务调用边、不降低外部依赖边界；该调整仅将基础继承方法从本地多态待修队列中移出，使真实未解析报告更准确。

## 4.3.35 Java Object-Method Scope Classification

- Calls on visible workspace types to source-absent Java object methods such as `equals`, `toString`, `hashCode`, and `getClass` now use `inherited_method_out_of_scope`.
- No business call edge is synthesized and external boundaries remain intact. This only removes base inherited methods from the local polymorphism-fix queue.

## 4.3.34 Java 调用精度门禁与 P95 性能观测 / Java Call Gate and P95 Performance Observability

- Java 调用评测现在将 `expected_resolution_levels` 纳入通过条件；例如链式调用 case 声明 `chain_return_type` 后，退化为普通解析会阻断门禁。
- 新增 `eval-java-call-resolution-metrics`、HTTP `/workspace/eval-java-call-resolution-metrics` 和 MCP `mc_admin(action="eval_java_call_resolution_metrics")`，仅返回解析等级、链式调用数量、置信度和未解析率等聚合指标，不返回路径或源码。
- `release-gate --query-samples N` 可记录冷查询 P95 和热查询 P95；可移植 baseline 优先比较热查询 P95，旧 baseline 继续回退比较 `duration_ms`。

## 4.3.34 Java Call Gate and P95 Performance Observability

- Java call evaluation now gates on `expected_resolution_levels`, so a `chain_return_type` case fails if it regresses to a generic resolution level.
- Added aggregate-only Java call metrics through CLI, HTTP, and MCP; it exposes resolution levels, chain counts, confidence, and unresolved rate without source paths or code.
- `release-gate --query-samples N` records cold and hot-query P95. Portable baselines prefer hot P95 and remain compatible with earlier `duration_ms` baselines.

## 4.3.33 方法返回类型与链式调用 / Method Return Types and Chained Calls

- Java 方法签名和 Method 图节点新增 `return_type`。
- 对 `receiver.first().second()`，仅当首段返回类型和第二段目标均在工作区唯一可见时，生成 `chain_return_type` 调用解析结果。

## 4.3.33 Method Return Types and Chained Calls

- Java method signatures and Method graph nodes now include `return_type`.
- `receiver.first().second()` resolves as `chain_return_type` only when both the first return type and second target are uniquely visible in the workspace.

## 4.3.29 继承 Lombok 访问器解析 / Inherited Lombok Accessor Resolution

- Java 索引新增直接父类型事实；当接收者类型、父类可见性、父类字段和 Lombok 注解均可验证时，调用可定位到父类的推断访问器。
- 只沿工作区内直接可见的继承关系解析；外部 Mapper 基类、多实现接口和不确定泛型分派仍保持未解析，避免伪造业务调用边。

## 4.3.29 Inherited Lombok Accessor Resolution

- Java indexing now carries direct parent-type facts. A call resolves to an inherited Lombok accessor only when receiver type, parent visibility, backing field, and Lombok annotation are all verifiable.
- Resolution follows only directly visible workspace inheritance. External mapper bases, multi-implementation interfaces, and uncertain generic dispatch remain unresolved to avoid false business edges.

## 4.3.28 静态同名类型碰撞隔离 / Static Simple-Name Collision Isolation

- 静态调用的未解析原因现在按当前文件的包与 import 可见性判断，不再因工作区其他位置存在同名类而把第三方工具类误列为“方法缺失/多态”。
- 这项调整只改善分类与优化优先级，不为外部静态 API 合成项目内调用边。

## 4.3.28 Static Simple-Name Collision Isolation

- Static-call unresolved reasons now honor package and import visibility, so a same-named class elsewhere in the workspace cannot misclassify a third-party utility as a missing-method or polymorphism case.
- This change improves diagnostics and prioritization only; it never synthesizes workspace call edges for external static APIs.

## 4.3.27 Catch 参数类型提取 / Catch Parameter Type Extraction

- Java 补充解析器现在会把单类型 `catch (Exception e)` 参数写入所属方法的局部类型表，使 `e.getMessage()` 等调用正确归为已知外部类型，而非本地接收者类型缺失。
- 多异常联合 catch 保持未推断，避免选择其中一个类型后产生错误的项目内调用边。

## 4.3.27 Catch Parameter Type Extraction

- The Java supplement parser now records single-type `catch (Exception e)` parameters in the owning method's local type table, so calls such as `e.getMessage()` are classified as known external types rather than missing local receiver types.
- Multi-catch remains intentionally unresolved, avoiding a false workspace edge from choosing one possible exception type.

## 4.3.26 Java 未解析调用诊断收敛 / Java Unresolved-Call Diagnostics Refinement

- 静态类风格调用且目标类不在工作区时，改标记为 `static_receiver_not_indexed`，不再误归类为本地接收者类型缺失；不会为外部 API 合成项目内调用边。
- 未解析调用报告新增 `receiver_shape_counts`，并可在不全量重建旧索引的前提下，将旧记录中的静态类调用按外部依赖范围重新分类。
- CLI、MCP admin 与 HTTP 继续共享同一只读诊断；文档明确 Agent 应先按类别采样，再用私有逻辑锚点 case 和 release gate 验证单一解析修复。

## 4.3.26 Java Unresolved-Call Diagnostics Refinement

- Static class-style calls whose target is outside the workspace now use `static_receiver_not_indexed` instead of being misclassified as missing local receiver types; no workspace edge is synthesized for external APIs.
- The unresolved-call report now includes `receiver_shape_counts` and refines legacy static-call rows at read time, without requiring a full reindex.
- CLI, MCP admin, and HTTP continue to share the same read-only diagnostic. Documentation now requires category-first sampling followed by private logical-anchor cases and a release-gate check for a single parser fix.

## 4.3.25 工作流回滚保护与刷新队列并发修复 / Workflow Rollback and Refresh Queue Fixes

- 已回滚的 workflow profile 不再参与自动推荐；全部画像都被回滚时明确返回 withheld 状态，而非继续给出不安全默认流程。
- 修复异步定向刷新 worker 在队列为空时的清理竞态，后到请求会启动新 worker 或由现有 worker 消费，不再被注册表清理丢失。

## 4.3.25 Workflow Rollback and Refresh Queue Fixes

- Rolled-back workflow profiles are excluded from automatic recommendations. When every profile is rolled back, the result is explicitly withheld instead of returning an unsafe default.
- Fixed the async targeted-refresh cleanup race. Requests arriving around worker shutdown are now processed by the active worker or a newly registered worker rather than being discarded.

## 4.3.24 受控交付画像与范围契约 / Scoped Delivery Profiles

- 新增 `maintenance` 工作流画像，用于健康检查、技术债治理与架构增量演进；所有画像明确返回分层上下文与交付护栏建议。
- 交付子任务新增 `read_targets`、`write_targets`、`stop_conditions`；交付矩阵和派生 `TECH_SPEC.md` 展示范围覆盖率。
- 工作区可通过 `delivery-policy.json` 的 `enforce_scope_contract` 严格要求范围契约，未满足时阻止进入实现阶段；默认保持关闭。

## 4.3.24 Scoped Delivery Profiles

- Added the `maintenance` workflow profile for health checks, technical-debt governance, and incremental architecture evolution. Workflow profiles now expose layered context and delivery guardrail guidance.
- Delivery subtasks now support `read_targets`, `write_targets`, and `stop_conditions`; the delivery matrix and derived `TECH_SPEC.md` show scope-contract coverage.
- Workspace owners can enable `enforce_scope_contract` in `delivery-policy.json` to block incomplete subtasks from entering implementation. It remains disabled by default.

## 4.3.23 影响分析降级与可诊断错误 / Resilient Impact Analysis

- `mc_analyze` 现在校验 `depth`、`direction`、`max_depth` 和 `execution_mode`。无效参数返回 `invalid_input`，不再误报为内部异常。
- `standard` / `full` 的计划、规则、契约、检查清单和工件写入改为独立可降级阶段：影响图成功后，任一辅助阶段不可用只会返回 `analysis_status=partial`、阶段诊断和下一步动作，不会丢弃已获得的影响证据。
- MCP 错误响应新增安全的 `diagnostics.operation`、`diagnostics.exception_class` 和 `diagnostics.trace_id`，可与本地 MCP 调用审计关联，同时不暴露源码、路径、密钥或异常正文。

## 4.3.23 Resilient Impact Analysis

- `mc_analyze` now validates `depth`, `direction`, `max_depth`, and `execution_mode`. Invalid parameters return `invalid_input` instead of an internal error.
- Plan, rule, contract, checklist, and artifact-write phases in `standard` / `full` analysis are independently degradable. Once graph impact succeeds, an unavailable enrichment returns `analysis_status=partial`, phase diagnostics, and an actionable next step instead of discarding evidence.
- MCP error responses now include safe `diagnostics.operation`, `diagnostics.exception_class`, and `diagnostics.trace_id` fields for correlation with local MCP audit records, without exposing source, paths, secrets, or exception text.

## 4.3.22 可验证 Skill 演进闭环 / Verifiable Skill Evolution Loop

- 交付 Skill 从“候选后直接发布”升级为 `candidate -> canary -> published|rolled_back` 生命周期。canary 不进入默认检索；正式发布至少需要三条带证据引用的成功观测且没有失败观测，禁止模型自评直接晋升。
- 新增 `delivery-skill-canary|observe|evaluate|rollback|recommend`：以有界观测记录成功、失败、绕过、延迟和 Token 指标；回滚会立即撤出默认推荐，但不删除历史证据。
- 新增离线 `delivery-failure-candidates` 与 `delivery-skill-synthesize`：前者按验证 profile 与验收标识聚合跨任务失败，后者从多个已验证候选归纳共同结构。两者均不写入原始源码、需求正文或验证日志，且不在 MCP/HTTP 查询热路径运行。
- Skill registry 保存稳定 ID、版本、结构签名、生命周期、来源证据和工件路径；候选在进入 canary 前先进行结构相似度检查，重复候选要求人工合并审核。

## 4.3.22 Verifiable Skill Evolution Loop

- Delivery Skills now follow `candidate -> canary -> published|rolled_back`. Canary Skills stay out of default retrieval; publishing requires at least three successful observations with evidence references and no failed observations, never an LLM self-rating.
- Added `delivery-skill-canary|observe|evaluate|rollback|recommend` for bounded success, failure, bypass, latency, and token measurements. Rollback removes default recommendation without deleting historical evidence.
- Added offline `delivery-failure-candidates` and `delivery-skill-synthesize`. They aggregate cross-task failure metadata and synthesize common patterns from proven candidates without storing source text, request bodies, or validation logs, and never run on MCP/HTTP query hot paths.
- The Skill registry now persists stable IDs, versions, structural signatures, lifecycle, evidence references, and artifact locations. Candidates are structurally compared before canary entry; likely duplicates require a human merge review.

## 4.3.21 证据优先需求交付闭环 / Evidence-First Delivery Loop

- 交付工作流升级为 `feature_delivery_v2`：需求项新增来源、范围边界、搜索词、候选模块、歧义和决策标记；阶段门禁会写入可追溯 `GateResult`。
- 新增非写入需求拆解候选、`Requirement -> Subtask -> CodeTarget -> Acceptance -> Evidence` 交付矩阵以及派生 `TECH_SPEC.md`，任务恢复可读取有界矩阵。
- 验证回执区分 `recorded_external`、`manual_verified` 与 `executor`。关闭和 Skill 提炼只接受执行器或人工验证证据；执行器仅运行 workspace policy 中预注册的 argv profile，保存超时、退出码、受限输出摘要和 hash。
- Wiki 生成新增每个项目的有界模块地图，供 Agent 在候选模块确定后按需读取。

## 4.3.21 Evidence-First Delivery Loop

- Upgraded delivery workflow to `feature_delivery_v2` with requirement source, scope boundary, search-term, candidate-module, ambiguity, and decision fields; stage checks persist traceable `GateResult` records.
- Added non-writing breakdown candidates, a derived `Requirement -> Subtask -> CodeTarget -> Acceptance -> Evidence` matrix, and a read-only `TECH_SPEC.md` projection consumed by task recovery.
- Validation receipts now distinguish `recorded_external`, `manual_verified`, and `executor`. Closing and Skill extraction require executor or manual evidence; the executor only runs policy-registered argv profiles and records timeout, exit code, bounded output, and hash.
- Wiki generation now emits a bounded per-project module map for on-demand Agent use.

## 4.3.20 静态断言稀疏化 / Derived Static Assertions

- 静态断言改由 `graph.db.edges` 按需派生，reindex 不再全量写入 `EXTRACTED` 断言表或 `assertions.jsonl`；断言存储仅保留人工验证、拒绝与治理状态覆盖。
- 新增 `artifact assertion-sparsify --dry-run|--apply`，显式删除可派生的旧 `EXTRACTED` 副本，并将 JSONL 收敛为轻量迁移标记；SQLite 页回收保持为后续显式维护操作。

## 4.3.20 Derived Static Assertions

- Static assertions are now derived from `graph.db.edges` on demand. Reindex no longer materializes all `EXTRACTED` assertions into SQLite or `assertions.jsonl`; assertion storage keeps only sparse human verification, rejection, and governance overrides.
- Added `artifact assertion-sparsify --dry-run|--apply` to explicitly delete derivable legacy rows and replace the JSONL export with a compact migration marker. SQLite page reclamation remains an explicit maintenance operation.

## 4.3.19 运行时存储去重 / Runtime Storage Deduplication

- 新增 `artifact storage-legacy-cleanup --dry-run|--apply`，仅在当前运行时已经使用 `graph/graph.db` 时识别和清理遗留 `memory/memory.db`，避免旧双存储架构继续占用磁盘。

## 4.3.19 Runtime Storage Deduplication

- Added `artifact storage-legacy-cleanup --dry-run|--apply`, which detects and removes retired `memory/memory.db` only when the active runtime already uses `graph/graph.db`.

## 4.3.18 交付 Skill 演进与空间治理 / Delivery Skill Evolution and Storage Governance

- 新增已验证交付到 Agent Skill 的受控闭环：只有已关闭、验收全部通过且存在定位证据的任务才能生成候选；候选必须显式发布，避免未验证经验自动进入正式 Skill。
- 新增 `artifact delivery-skill-candidate|publish|status` 与 MCP admin 对应动作，并新增 `artifact compact-task`：超大任务工件流式 gzip 归档，仅保留有界恢复上下文。

## 4.3.18 Delivery Skill Evolution and Storage Governance

- Added a governed verified-delivery-to-Agent-Skill loop: only closed tasks with complete passing acceptance evidence and located code targets can create candidates, and candidates require explicit publication.
- Added `artifact delivery-skill-candidate|publish|status`, matching MCP admin actions, and `artifact compact-task` to stream-gzip oversized task artifacts while retaining bounded recovery context.

## 4.3.17 Java 调用边准确性 / Java Call-Edge Accuracy

- 修复 Java 调用提取器扫描整个文件导致的伪调用：注解表达式字符串和字段初始化不再被写入 `CALLS_METHOD`。
- 调用图现在仅从真实方法体提取调用，避免将 `@PreAuthorize("@ss.hasPermission(...)")` 等框架元数据误判为业务调用链，并降低真实工作区中的无接收者类型噪声。
- 修复按绝对文件路径执行局部刷新时的分片路由：命中文件只重建所属服务的物理分片，避免保守回退触发全服务分片重建。
- 局部刷新发布采用硬链接复用未变 SQLite 分片，并将重建分片临时写入后原子替换，避免复制整代大索引或修改上一代数据。
- 图存储新增 `nodes.file_path` 索引；目录范围会先展开为已索引文件，图清理统一走精确匹配，避免大图数据库全表扫描。
- 服务分片导出改为使用项目节点索引连接边表，不再向 SQLite 传入成千上万个双重 `IN` 参数。

## 4.3.17 Java Call-Edge Accuracy

- Fixed false Java calls caused by scanning entire files: annotation-expression strings and field initializers are no longer emitted as `CALLS_METHOD` edges.
- Calls are now extracted only from executable method bodies, preventing framework metadata such as `@PreAuthorize("@ss.hasPermission(...)")` from polluting business call chains.
- Fixed service-shard routing for absolute-path refreshes: a matching file now rebuilds only its owning service shard instead of falling back to all service shards.
- Partial publication now hard-links unchanged SQLite shards and atomically replaces rebuilt shards, avoiding multi-generation index copies or mutation of the prior generation.
- Graph storage now indexes `nodes.file_path`; directory scopes expand to indexed files before graph cleanup, so all graph removal uses exact lookups and avoids full scans of large graph databases.
- Service-shard export now joins edges through indexed project nodes instead of passing SQLite two massive `IN` parameter lists.

## 4.3.16 需求交付工作流 / Delivery Workflow

- 新增可复用的 `feature_delivery_v1` 需求交付状态机：`intake -> breakdown -> locate -> implement -> verify -> close`；每个阶段均通过结构化门禁推进。
- 任务空间新增需求、子任务、验收标准与只追加验证回执契约；完成关闭前必须为每项必需验收标准关联通过的验证回执。
- CLI `artifact delivery-*`、MCP `mc_admin(action="delivery_*")` 和 HTTP `/workspace/delivery*` 共享同一应用服务；记录验证时只保存输入的脱敏摘要，不会执行命令。

## 4.3.16 Delivery Workflow

- Added reusable `feature_delivery_v1`: `intake -> breakdown -> locate -> implement -> verify -> close`, advanced only through structured gates.
- Task spaces now carry requirement, subtask, acceptance, and append-only validation-receipt contracts; closing requires a passing receipt for every required acceptance criterion.
- CLI `artifact delivery-*`, MCP `mc_admin(action="delivery_*")`, and HTTP `/workspace/delivery*` share one application service. Recording validation never executes a supplied command.

本更新日志按**版本号**归纳，优先记录：

- 用户可感知的新能力
- 重要行为变化
- 明确修复的真实 bug

## 4.3.15 测试样例工作区隔离

- 测试框架现在在每个测试前后校验 `examples/spring-cloud-demo/.memory-center` 的完整摘要。任何直接写入受跟踪样例工作区的测试会在当场失败，所有写操作必须使用 `tmp_path` 副本。

## 4.3.15 Test Fixture Workspace Isolation

- The test framework now hashes the demo workspace before and after every test, failing at the exact test that writes to the tracked fixture. Write tests must use a `tmp_path` copy.

## 4.3.14 MCP 大日志保留闭环

- MCP 审计的 JSONL 与 SQLite 查询在后台物理压缩期间立即按 30 天、10 万条窗口过滤；大日志不再短暂暴露过期数据。新增大日志非阻塞回归，确保维护线程不会拉长 MCP 工具响应。

## 4.3.14 MCP Large-log Retention Closure

- MCP audit reads now enforce the 30-day/100k window while background compaction is in progress. Large-log retention has a non-blocking regression guard.

## 4.3.13 MCP 审计保留一致性

- 修复首次 MCP 调用后过期审计记录仍短暂可见的回归。64 KiB 以内的小型审计日志同步收口，保证返回后立即符合 30 天/10 万条策略；大日志继续后台物理压缩，避免请求线程扫描和重写十万级 JSONL。

## 4.3.13 MCP Audit Retention Consistency

- Expired audit records are now removed synchronously for small logs, while large logs keep asynchronous physical compaction to preserve MCP latency.

## 4.3.12 查询热路径与后台任务可靠性修复

- 普通语义查询改为复用进程内本地 embedding 模型缓存；不会重复加载权重、不会联网下载，也不会因索引代际不一致隐式全量重建。大规模 dense 查询统一通过已发布 ANN，只有极小测试索引保留精确计算。
- 默认 lookup 的断言摘要不再读取“最近断言”正文；修复百万级断言表为取一条记录而进行全表排序的 P0 延迟问题，断言详情页才会显式读取该切片。
- `mc_start`、`mc_lookup` 的定向刷新改为后台合并执行；请求立刻使用当前已发布 generation，并通过 `auto_refresh.scheduled` 告知刷新已排队，避免哈希、图遍历和 partial reindex 阻塞 Agent。
- 修复向量后端故障被误报为正常空结果的问题；现在返回 `vector_backend_query_failed` 和 `vector-ann-rebuild` 下一步动作。ANN rebuild/tune 管理操作最多等待 1 秒，不再被长维护锁卡住。
- 后台任务增加进程 PID 与心跳，只在宿主 PID 已失效时标记 `interrupted`；取消请求持久化并在每个重建阶段协作生效，不再把正常长任务误判为中断。
- 重排模型在单一执行器中最多等待 3 秒，超时保留原排序并返回诊断；同一 MCP 进程只保留一个活跃重排模型。MCP 审计清理移出工具请求线程，HTTP POST 请求体限制为 1 MiB。

## 4.3.12 Query Hot-path and Background Job Reliability

- Normal semantic queries reuse local process-cached embedding models, never download or rebuild a full semantic index implicitly, and use published ANN for large dense indexes.
- Targeted refresh is scheduled in the background so lookup returns the current published generation immediately.
- Vector backend failures, job heartbeat/cancellation, reranker deadlines, asynchronous audit retention, and HTTP request-size limits now have explicit bounded behavior.

## 4.3.11 ANN 并发一致性与请求时延收口

- 向量事实写入、HNSW 生成和 label 映射改为同一维护锁的原子推进；查询映射 label 前保持锁，消除 rebuild 与局部 refresh 交错造成的错位与部分索引。
- ANN 查询锁等待上限为 300ms；维护占用时返回 `vector_ann_maintenance_in_progress` 和 `retry_after_ms`，不再无限等待造成 MCP 卡住。
- Cross-Encoder 仅由当前 MCP 进程的显式预热激活；高级查询不会因磁盘缓存模型而同步加载权重。状态区分 `cached_not_prewarmed` 与 `ready`。

## 4.3.10 检索稳定性与冷启动修复

- 修复 embedding 档案切换后的向量维度漂移：sqlite-vec 现在显式保存表维度，维度不一致时不会误查询旧表，状态会要求完整 reindex 重建当前维度。
- HNSW 的 rebuild、增量同步、删除、调优和读取使用同一文件锁，索引文件经临时路径原子替换；并发 reindex 与 ANN 维护不会再写出半个 ANN 文件或错配标签。
- Cross-Encoder 重排器只加载本地缓存，普通 CLI/MCP 查询不会下载模型；新增 `retrieval-reranker-status`、`retrieval-reranker-prewarm` 和对应 `mc_admin` action，将下载移到显式维护窗口。
- `advanced_query` 与普通 query 一样记录 `session_id` 的 `agent_guidance`，使 replay、采纳分析与后续检索调优获得完整输入。

## 4.3.9 Agent 检索维护闭环

- 高级检索和 ANN 维护能力通过 `mc_admin` 统一暴露：`advanced_query`、`vector_ann_status`、`vector_ann_rebuild`、`vector_ann_tune`、`retrieval_model_profile` 与 `eval_retrieval_replay`。
- lookup 在大规模 dense embeddings 缺失 ANN 时返回可执行 `rebuild_vector_ann` Action，Agent 协议要求先重建、再调优、再重试原查询；普通查询不会隐式全量重建。
- 生成到 Codex、Claude、Gemini、Copilot、Cursor 的 Agent 指令和 MCP 指南同步了触发条件、停止条件与模型切换边界。

## 4.3.8 代码检索与自适应排序

- SQLite 倒排检索升级为代码感知 BM25F：类/方法/契约名称权重高于路径和元数据，并复用驼峰拆分后的标识符 token。
- hybrid 融合结果增加有界个性化图排序，只从 Top-3 查询种子沿关系传播最多两层，不扫描全图。
- 新增可选 Cross-Encoder 级联重排：`query --rerank` 最多重排 12 条候选，模型不可用时保持原排序并返回诊断。
- 新增 `vector-ann-tune`，以有界 self-recall 与 P95 探针选择 HNSW 查询 `ef`；新增工作区 `retrieval-model-profile`，可显式选择 BGE-M3 多语言 embedding 档案，仍须完整 reindex 后才生效。

## 4.3.7 持久化 ANN 与真实回放校准

- dense vector 检索不再在大型索引上回退到 Python 全量余弦扫描：优先使用 `sqlite-vec`，否则使用可持久化的 `hnswlib` HNSW；未就绪时返回明确诊断和 `vector-ann-rebuild` 下一步动作。
- 小于 64 条向量的开发/测试索引保留有界精确校验；超过阈值没有 ANN 时不会静默扫描全部 embedding，避免阻塞 MCP 查询。
- 新增 `memory-center vector-ann-status` 与 `memory-center vector-ann-rebuild`，旧 dense 向量可显式重建 HNSW，不在查询或局部 refresh 热路径隐式全量重建。
- 新增 `memory-center eval-retrieval-replay [--apply]`：仅根据有 evidence 的人工验证 `retrieval-source` 反馈，以 Beta 平滑和样本收缩生成融合权重提案；agent guidance 采纳率不会被误当成召回正确性。样本不足时不写入任何权重。

## 4.3.6 检索与图遍历算法优化

- `RuntimeStore.neighbors` 由递归 CTE 改为有界分层 BFS，环状或高分支调用图不会重复物化路径；每层 SQL 查询受结果预算约束。
- FTS 候选按 SQLite FTS5 `bm25` 相关度及稳定字段排序，改善多关键词检索的首屏结果稳定性。
- SQLite 倒排索引的 BM25 查询改在数据库内完成 posting 聚合、排序和 Top-K 截断，避免高频词查询把全部候选回传 Python。
- 默认稀疏语义检索在 SQLite BM25 索引就绪时不再重复扫描完整语义 JSON；BM25 缺失或显式启用 dense backend 时仍保留语义路径。

## 4.3.5 运行时存储与测试职责收敛

- 移除 `UnifiedStore`，以唯一 `RuntimeStore` 承载图索引、运行记录、断言和 refs，统一落在 `graph.db`。
- 明确 `neighbors` 返回节点、`traverse_edges` 返回关系边；写事务回滚后继续抛出，FTS 和向量等可选能力保留可诊断降级。
- 测试重组为 `entrypoints`、`index_storage`、`domain` 和 `regression` 四类，测试资源通过统一根映射访问，不再依赖平铺文件位置。

## 4.3.4 Ref 事实源与死 shim 清理

- payload ref 读写统一以 `graph.db.refs` 为准；删除 JSON 导出后仍可解析 ref，不再发生文件回退。
- 删除无生产调用的 `mcp.action_registry` 转发模块及其兼容测试。
- 读取矩阵明确区分 SQLite refs 与人工 Markdown 工件，消除文档与实现冲突。

## 4.3.3 新架构收尾与历史冲突清理

- 删除固定 Spring Cloud 初始化模板、旧 explanation 字段包装器、Python 3.9 `zip_strict` 兼容层和相应无效测试；`init` 只生成自动识别出的工作区模型。
- 查询契约不再把无匹配契约伪装成低置信候选；当前范围没有证据时返回空结果并由 `knowledge_state` 表达范围与下一步动作。
- 修复 session 事件在 SQLite 为空时回退 JSONL 的旧读路径，避免过期导出重新影响运行时结论。
- 架构、MCP、用户和技术文档统一为 `graph.db` 单运行时事实库，JSON/JSONL/Markdown 仅作为导出或人工工件。

## 4.3.2 运行时事实源收口

- 会话、MCP/宿主交互、验证循环、回执、任务与刷新状态全部只从 SQLite 运行时事实库读取；JSON/JSONL 不再作为任意运行时查询的兜底。
- `memory_query_hybrid` 仅在 freshness 为 `stale` 或 `pending` 且已解析服务范围时，执行最多 4 个候选文件的局部刷新；正常查询不增加刷新成本。
- 清理遗留的文件/SQLite 双读诊断与旧 `memory_db_path` 命名，统一使用 `runtime_db_path`。

## 4.3.1 存储与检索收敛

- 运行时图、索引镜像、会话记录和断言统一收敛到 `.memory-center/graph/graph.db`；JSON/JSONL 保留为可审查导出，不再参与查询回退。
- 删除无范围的 `memory_query` 内部门面，hooks、group 和 resume 统一使用 `memory_query_hybrid`。
- 已解析服务范围的 hybrid/code 查询不再静默退回全局索引；服务分片缺失明确返回 `NOT_INDEXED`，避免扩大延迟和越过查询边界。
- 移除无 schema 启发式记录的热路径兼容；当前稀疏余弦与 BM25 均作为受支持的检索算法。旧工作空间需显式 `reindex` 后使用。

## 4.3.0 本体旧格式移除

- 删除 `ontology-migrate`、旧 sidecar 自动转换和旧读模型回退逻辑；本体数据只接受 V2 格式。
- 升级后的已有工作空间必须运行完整 `reindex` 重建 Assertion、Alias 与治理读模型；CLI、MCP、HTTP 的公开查询和管理入口保持不变。

## 4.2.0 本体 V2 强制切换

- 本体内部停止旧 sidecar 双读和回退：首次 Assertion 查询会强制把 SQLite 列与 JSON payload 迁移到 V2；迁移异常需重新 reindex，不再返回旧读模型。
- release gate 的隐私字段检测改为全量 SQL 扫描，不再抽样最近断言；CLI、MCP 与 HTTP 的公开命令和字段保持稳定。

## 4.1.36 本体演进完整收尾

- 所有 hybrid 查询与 MCP lookup 的 `agent_next_steps` 都会投影为有界、稳定 ID 的 Action；Workbench 可从路由继承 task/session/actor 并写入断言状态审计。
- 已在真实大型 workspace 跑通隔离局部 reindex 基线：断言侧车开销满足 5% 发布预算；本体演进计划的剩余功能、性能和入口一致性项完成收尾。

## 4.1.35 本体闭环修复

- 静态断言优先记录索引中的源码修改时间；已验证别名会扩展默认检索词并返回解析依据，未验证或替代关系不会自动合并。
- MCP lookup 的结构化下一步动作会写入有界 Action 读模型；发布门禁在存在断言侧车时阻断无来源 VERIFIED、旧 generation 活跃断言和可疑私有正文键。

## 4.1.34 本体发布性能门禁

- 新增隔离临时存储中的 graph-only 与 assertion-sidecar reindex 对比门禁，并可接入 `release-gate`；局部范围预算为 5%，完整范围预算为 10%。

## 4.1.33 身份与断言确认体验

- 别名新增验证状态、置信度、有效期与 `ALIAS_OF`、`SAME_AS`、`RENAMED_FROM`、`REPLACES` 语义；默认仅合并有验证证据的等价关系。
- CLI、MCP admin、HTTP、旧 Workbench 和 Vue Workbench 新增断言详情、验证、拒绝与深度分析入口；状态操作不会修改源码或删除历史。

## 4.1.32 治理本体与双时间断言

- registry 新增治理实体与关系端点约束；断言增加 provenance、relation mode、evidence refs、event/observed/valid 时间字段。
- 新增 `ontology-migrate` 只读预检和显式回填，旧断言读模型保持兼容。

## 4.1.31 统一知识状态

- 查询与工作区状态新增 additive `knowledge_state`，明确 `FOUND`、`NOT_FOUND`、`NOT_INDEXED`、`STALE`、`UNKNOWN` 的范围、原因和下一步动作。

## 4.1.30 局部刷新范围门禁

- 新增 `eval-assertion-scope-gate`：先以只读方式统计指定逻辑路径实际选中的断言边，并与全图边数和范围上限比较；只有显式传入 `--apply` 才会发布一次局部 reindex。
- 门禁输出范围比例、选中边数与可选实刷耗时，便于在真实工作空间验证局部索引没有退化为全量物化。

## 4.1.29 静态断言历史保留

- 已关闭静态断言新增低频保留策略：活跃事实永不裁剪；历史按 90 天与 200 万条上限同步清理 SQLite 镜像和 JSONL 审计流，避免长期全量 reindex 导致无限增长。

## 4.1.28 局部断言物化修复

- 局部 reindex 仅关闭并重建受影响路径/项目的断言，不再全图遍历、全量追加或替代无关 `VERIFIED/REJECTED` 断言。
- `assertion_summary.recent` 以 SQLite 当前状态覆盖 payload 历史状态；证据等级与断言状态保持正交，`STALE`、`REJECTED` 不再污染 `evidence_level`。

## 4.1.27 断言引用按需展开

- 新增 `assertion-inspect`、`mc_admin(action="assertion_inspect")` 和 `/workspace/assertion`，可通过稳定 `assertion_ref` 按主键读取单条断言，不扫描审计 JSONL。

## 4.1.26 断言状态三入口

- 断言状态变更新增 `POST` 风格的 HTTP 路由 `/workspace/assertion-status`；CLI、MCP admin、HTTP 均复用同一校验和审计模型。

## 4.1.25 断言验证与拒绝生命周期

- 新增 `assertion-status` 与 `mc_admin(action="assertion_status")`；支持显式 `VERIFIED`、`REJECTED` 等状态更新，并追加审计事件。`VERIFIED` 必须提供脱敏验证引用，不能由置信度自动升级。

## 4.1.24 本体热路径性能门禁

- 新增 `eval-ontology-gate`，测量默认查询新增 assertion summary 的 SQLite 聚合开销，输出 P50/P95、10ms 预算和 pass/fail；不会扫描图、源码或历史审计流。

## 4.1.23 治理证据关联

- evidence subgraph 仅在当前目标直接关联时附加最多 20 条治理断言，实现从变更、决策、验证到任务节点的按需追溯，不进行全局关系推理。

## 4.1.22 结构化行动对象

- 可信结论卡新增 `Action` 对象，包含 action_type、前置条件、停止条件和失败回退，避免 Agent 或用户执行无界重试。

## 4.1.21 本体诊断门禁

- `runtime-inspect` 新增 SQL 聚合诊断：未知节点/关系类型、无来源 VERIFIED 和旧 generation 活跃断言，逐项给出命令级修复建议；不进入普通查询热路径。

## 4.1.20 查询断言摘要

- 旧 `memory_query` 与 hybrid 查询在保留原 schema 的前提下新增常量大小的 `assertion_summary`，包含 active、verified、inferred、stale 及下一步建议，不读取断言明细。

## 4.1.19 本体运行检视

- `runtime-inspect` 新增有界本体摘要：断言代际与状态、近期治理关系、身份别名数量及可执行修复建议，不扫描 JSONL 审计历史。

## 4.1.18 可信结论卡

- evidence subgraph 新增统一、最多 20 条的可信结论卡，展示状态、证据引用、新鲜度、风险和下一步动作；不读取源码或历史审计流。

## 4.1.17 治理断言投影

- watcher 变更确认会投影为 `Decision`、`Validation` 与 `VERIFIES` / `REJECTS` / `REQUESTS_ANALYSIS` 治理断言；复用现有确认输入，不改变已有 MCP、HTTP 或 CLI 契约。

## 4.1.16 断言失效与身份别名

- Assertion mirror 保存关系两端的文件归属；watcher/targeted refresh 写入 dirty journal 时，仅将匹配文件的活跃断言标为 `STALE`，不扫描或回写全图。
- 新增独立身份别名 sidecar，支持可追溯的 canonical identity、重命名链解析及循环歧义提示，历史实体 ID 保持不变。

## 4.1.15 断言历史读取

- Assertion sidecar 增加受限的当前、指定 generation 与指定时间点读取接口；默认只返回 active 断言，避免普通使用场景扫描历史审计流。

## 4.1.13 本体 registry 对齐

- 本体 registry 补齐索引器实际使用的 Workspace/File/Bean/DataResource 节点与关系 endpoint 约束；新增 CI 校验，防止索引器边类型与 registry、文档漂移。

## 4.1.14 本体断言侧车

- 图关系会在代际发布后批量物化为 `assertions.jsonl` 和 SQLite 活跃断言镜像；图发布不再被侧车失败阻断，旧 `reindex` 返回 schema 保持不变。
- 证据子图可按需附加 `assertion_ref`，用于追溯断言代际与来源，不增加普通查询的图扫描。

## 4.1.12 本体认识论与体验扩展

- 本体演进计划补充开放世界否定性结论、身份/别名、双时间、因果与相关性、规范/行动对象、信念修订约束，以及默认可信结论卡与可行动状态体验。

## 4.1.11 本体演进实施计划

- 新增独立本体演进计划，定义实体/断言分离、来源与状态正交、时间有效性、跨域治理关系、sidecar 迁移、性能预算、兼容策略和发布门禁。

## 4.1.10 离线架构社区分析

- 新增 `architecture-communities`、`GET /workspace/architecture-communities` 与 `mc_admin(action="architecture_communities")`，显式聚合项目社区、跨项目关系和高中心性节点。
- 计算只在 SQLite 内聚合，结果缓存为轻量摘要；普通查询与 status 不触发计算，不加载完整图或源码。

## 4.1.9 文档宪章与任务旅程

- 新增 `DOCUMENT_CONSTITUTION.md`，定义文档真相层级、生命周期、公开入口更新门禁与架构不可变量；测试确保新能力在操作、参考、MCP 文档中可发现。
- `USER_GUIDE` 新增按任务组织的操作地图；主计划移除已完成能力的旧执行顺序，架构文档新增可审计的不可变量。

## 4.1.8 有界证据子图导出

- 新增 `export-evidence-subgraph`、`GET /workspace/evidence-subgraph` 与 `mc_admin(action="evidence_subgraph_export")`，围绕一个节点或符号导出 JSON、Markdown、HTML 证据子图。
- 导出严格限制为最多 3 跳、120 条边、80 个节点；不读取源码、不扫描全图、不进入普通查询热路径，输出携带节点/边证据等级。

## 4.1.7 变更影响确认闭环

- watcher 变更影响报告新增人工确认闭环：`confirmed`、`false_positive`、`deep_analysis_required`、`resolved` 可关联 task/session、结构化验证结论和验证人；CLI、HTTP 与 MCP admin 复用同一读写模型。
- Workbench 的 `hot_refresh.pending_change_reports.high_risk_reports` 仅返回最多 5 条未确认高风险项。报告、确认审计和紧凑索引均按 30 天、10 万条维护，查询不加载代码或全量图。

## 4.1.6 可信任务进度与运行证据

### 证据等级

- 查询结果、推理项、图边和质量摘要新增兼容的四级 `evidence_level`：`EXTRACTED`、`INFERRED`、`AMBIGUOUS`、`VERIFIED`；`VERIFIED` 仅由显式验证状态产生，不会因高置信度自动升级。
- 质量摘要新增 `evidence_level_counts`，保留原有 `evidence_counts` 与 facade `_meta.evidence_level` 的来源语义不变。

### 运行时检查

- 新增 `memory-center inspect`、`/workspace/inspect` 和 `mc_admin(action="runtime_inspect")`，统一输出脱敏的 MCP、AGENTS、Hook、会话绑定、交互历史和索引运行状态，以及可执行的修复建议。

### 会话证据链

- `mc_start` 自动记录 Git 分支、HEAD 和脏文件数量；`mc_close`、`work-close` 和 HTTP close 接口可记录已执行验证命令的脱敏摘要、退出码与状态。
- session summary 新增 `evidence_chain`，关联起始/结束代码版本、验证结论和 outcome；不会执行外部传入命令，非 Git 工作空间保持兼容降级。

### 后台任务进度

- workspace job 升级为版本化阶段进度，持久化 `progress` 和有界 `progress_events`；reindex 会上报扫描、解析、图谱、语义、检索和发布阶段，失败状态返回脱敏诊断。

### 常驻定向索引

- 新增每工作区单实例 watcher daemon：`watcher-start|status|stop` 与 `mc_admin(action="watcher_start|watcher_status|watcher_stop")` 支持后台监听、去抖、局部重建、PID 存活检查与优雅停止；Workbench 的 `hot_refresh.watcher` 显示相同持久化状态。
- watcher 的局部 reindex 到达终态后会生成有界变更影响摘要，记录变更类别、受影响服务、generation、任务结果与证据等级；高风险契约变更只建议显式深度分析，避免后台自动消耗索引资源。

### 4.1.4 交互历史与效果闭环

- 新增脱敏交互历史：MCP 调用记录 trace/thread/turn、工具版本和索引 generation；Host Hook 可记录用户提示、编辑前检查和会话收尾等事件，不保存原始正文、源码或 payload。
- 新增 `MEMORY_CENTER_THREAD_ID` 驱动的 thread-session 持久绑定，MCP 进程重启后可自动续接同一宿主线程的 session。
- 新增 `mc_admin(action="interaction_record|interaction_effects|interaction_effects_refresh|active_session_bindings")`，用于补记宿主事件、查看调用 P50/P95、关联率和已关闭会话的验证成功率。
- 历史数据按层治理：MCP/宿主原始交互 30 天、session event 90 天、session summary 365 天，均最多 100,000 条；JSONL 与 SQLite 镜像同步裁剪。
- Workbench Usage 页面展示 MCP 调用效果，Backend 页面可筛选 MCP 与宿主交互账本。

### 4.1.3 MCP 审计保留策略

- `mcp-invocations.jsonl` 自动只保留最近 30 天且最多 100,000 条；首次 MCP 调用、每 5 分钟或达到上限时触发维护。
- 清理会同步裁剪 JSONL 文件和本地 SQLite 镜像，避免已过期调用继续出现在验证查询中。

### 4.1.2 MCP 调用审计

- 所有公开 MCP 工具自动写入 `mcp-invocations.jsonl`，记录脱敏参数摘要、状态、耗时、结果规模和 session/task 关联，默认不保存请求或响应正文。
- `mc_start` 后同一 MCP 进程的调用自动关联 session，并同步为 `tool_call` session event，供 replay、采纳分析和后续验证使用。
- 修复 MCP schema 兼容测试仅扫描单个注册模块、且受函数排版影响的问题，改为跨公开模块的 AST 解析。

### 4.1.1 定向刷新一致性修复

- 定向刷新统一委托正式的按路径局部重建，避免刷新后丢失 API、Feign、MQ、配置与图谱关系。
- dirty journal 现在可处理新增与删除源码文件；首次查询刷新继续以全量索引元数据为基线，避免无变更邻居被重复重建。
- 保持热刷新 file generation 诊断，并新增 Controller Endpoint 保留、新增文件和删除文件的回归测试。

### Core Domain Layout and Query Reliability / Core 领域规整与查询可靠性

- 修复 `memory_query` 在普通查询路径引用未定义项目作用域、导致 `mc_lookup(mode="query")` 崩溃的问题。
- 重整 Core 领域模块：契约治理迁入 `contracting/`，索引控制与分片迁入 `indexing/`，跨服务分片检索迁入 `retrieval/`，任务工件/回执/时间线迁入 `tasks/`，导出迁入 `presentation/`。
- 移除 `core/*.py` 兼容转发层；所有内部调用、测试与文档只使用唯一的领域导入路径。
- 进一步消除跨领域同名模块：索引入口为 `indexing/reindex.py`，编排工作区入口为 `orchestrator/workspace_ops.py`，benchmark case、reasoning request、walkthrough report/evaluation、audit reports 使用语义化文件名。
- 为 `core` 及所有领域目录新增 README，说明职责、依赖边界和新增代码落点。

### P2 Retrieval / Reasoning Quality Loop / 检索与推理质量闭环

- 本地安装版本提升至 `4.1.0`。
- 新增脱敏运行时契约样本与兼容校验：只接受服务、API/MQ 标识、DTO 字段名和计数，不保存 payload/body/header/message；活跃流量命中破坏性静态变更会阻断发布。
- 新增双读/双写迁移状态，已批准迁移可把受控活跃风险降为 attention；full 契约分析、任务 evidence、pre-edit guard、runtime gate 和 release gate 复用同一运行时报告。
- 本地安装版本提升至 `4.0.0`。
- 新增 API/Feign/MQ/DTO 标准化契约快照与前后 diff；删除契约、DTO 字段删除和字段类型变化会作为 high severity breaking change。
- `mc_analyze(depth="full")`、任务证据、pre-edit guard、`mc_admin(action="contract_gate")` 和 release-gate 统一使用契约语义报告，包含 Feign 服务端方法/路径、MQ producer/consumer、DTO 消费者风险和受影响消费者。
- 本地安装版本提升至 `3.9.0`。
- `mc_lookup` 新增 `cross_shard_fusion`：融合主检索/服务分片命中，按证据键去重排序，校验 active/routed generation，并输出事实/推断/派生强度、置信度、契约结论和下一步动作。
- 新增 Feign 目标解析、MQ producer/consumer 覆盖、DTO 审核提示，以及 `eval_cross_shard_fusion` Golden-like 门禁，覆盖服务选片、generation 一致性和可解释性。
- 本地安装版本提升至 `3.8.0`。
- 新增自动跨服务分片编排：未指定 project 的 MCP 查询会基于 Contract/Topology Shard 路由、按档位有界扩展 Feign 邻居，并行查询服务 JSON/SQLite 图分片；响应新增 generation 绑定的 `shard_route` 与 `shard_evidence`。
- 新增 `eval_cross_shard_replay`，以不持久化原始查询的方式统计跨服务选片 P95、选片上限和证据覆盖率。
- 本地安装版本提升至 `3.7.0`。
- generation 从路由元数据升级为真实物理分片：每次 reindex 生成不可变服务 JSON、服务 SQLite 图、契约和拓扑快照，完成后才激活；partial reindex 采用 copy-on-write，仅重建受影响服务分片；显式 project 范围的 code/hybrid 查询优先读取服务分片并保留全局兼容回退。
- watcher 的有界失效计划现在会合并提交后台 partial reindex；新增 generation 回滚、保留与默认 dry-run 的清理入口。
- 本地安装版本提升至 `3.6.0`。
- 新增 versioned index control plane：reindex 在 staging generation 内构建，完成图、检索与分片路由元数据后才激活；既有 reindex 返回结构和读模型保持兼容。状态新增 generation、分片路由和查询 P50/P95/P99 可观测性。
- 新增有界变更失效计划，按 DTO、Feign、MQ、HTTP、配置和普通代码输出传播规则；watcher 的 dirty journal 记录对应失效依据。
- `QueryPlanner` 收敛 `mc_start` / `mc_lookup` 的 fast/standard/deep 请求预算并记录性能账本；新增后台 reindex job、恢复中断 job 的状态机，以及管理入口。
- 任务空间新增与 evidence refs 关联的 ADR 决策记录；证据 GC 默认 dry-run，需显式 `force=true` 才会清理未引用块。
- 本地安装版本提升至 `3.5.29`。
- 热刷新新增 `RefreshCoordinator`，按 workspace 协调多 Agent/多进程请求；文件内容哈希、generation 和子图替换在同一 SQLite 事务中提交，并对既有图关系执行有上限的一跳依赖闭包。
- `mc_start` / `mc_lookup` 新增兼容的 `request_tier`；`mc_analyze` 新增显式后台 job、状态读取和取消入口，默认同步行为不变。
- 任务空间超大写入改存 SHA-256 内容寻址证据块，任务工件保留轻量引用，避免恢复、同步或交接读取完整大 payload。
- 热刷新摘要支持压实 generation snapshot，状态面可观测最近压实信息。
- 本地安装版本提升至 `3.5.28`。
- Workbench/status 现在显示 `hot_refresh` 的 manifest 文件数和 dirty journal 状态；dirty journal 达到阈值会自动按路径压实，只保留最新事件，不影响正式索引。
- 热刷新新增文件版本 manifest 与 dirty journal；watcher 只登记去抖后的变更，相关请求再消费这些路径。文件子图替换改为 SQLite 单事务，并重建声明、注入和方法调用出边，同时保留未变文件的调用入边。
- `mc_start` 和 `mc_lookup` 现在会在主检索前自动检查有限数量的相关源码；检测到源文件比索引更新时，仅刷新对应 File/Class/Method 图谱覆盖层，不读取或合并全量 Java/semantic 索引。响应增加 `auto_refresh`，显示检查数量、刷新文件数量、耗时与模式。
- `mc_start` 复用首次 sniff 结果，不再因自动同步重复执行同一检索；sniff 返回阶段耗时、缓存命中、检索路径与软时限状态，便于 Agent 判断是否需要补充更精确的入口。
- reindex 写入轻量 `index-summary.json`；Workbench/状态查询只读取该摘要，不再为计数加载完整 Java/semantic 索引。紧凑输出的 token 节省统计默认关闭，仅在 `MEMORY_CENTER_MEASURE_COMPACT_GAIN=1` 时启用。
- 任务工件写入、摘要历史与 change-log 压缩新增容量门禁，避免直接写入路径重新读取或拼接超大 Markdown。
- 修复大型 workspace 的正常链路分析可能长时间占用 CPU/内存的问题：`Class#method` 全链路请求现在直接走 walkthrough，跳过不必要的 sniff；sniff 候选文件改为优先使用 graph FTS，code-search/sniff 不再按文件序列化完整 Java 符号、调用和 DTO payload。
- 任务空间解析、健康检查、恢复摘要和自动同步改为有界读取任务工件；超过阈值的工件会在 health 中告警，并在自动同步时保持原样跳过，避免 GB 级 Markdown 被全文读入或拼接。
- 本地安装版本提升至 `3.5.23`。
- reindex 现在使用 workspace 级 `reindex.lock` 串行化完整索引写入；并发请求会返回可处理的 conflict 和 `--lock-timeout` 建议，不再直接暴露 SQLite 锁错误。`workspace_status` 与 Workbench Health 会显示运行中、成功、失败或中断的重建状态。
- 新增 `release-gate`：一次执行全量 reindex、重复检索冒烟检查以及可选 Golden、Java 调用解析、parser precision 检查，输出统一发布结论。它支持保存/比较 portable baseline；baseline 仅保存耗时、数量、质量分和状态，不保存私有 query、路径、case 或 payload。
- 修复 `release-gate` 会把 parser precision 的 `low` 状态误判为通过的问题；现在仅 `high` / `medium` 可通过，且失败门禁不会写入 baseline。
- Workbench Health 新增 Benchmark & Gate Summary；HTTP `/workspace/quality-gates-summary` 统一提供 benchmark score、regression alerts、replay campaign 与 Java unresolved-call 指标。接口仅返回状态、指标、分类和建议，不暴露私有路径、源码片段或服务名。
- Workbench Query 新增 walkthrough 模式、`summary / standard / deep` 报告档位、结构化 quick conclusion / main chain / risks / next actions、质量评估与导出动作；导出反馈同时显示当前 gate snapshot，原始响应收进可展开 evidence 区。
- 新增 Java 未解析调用分类报告：CLI `eval-java-call-resolution-unresolved`、HTTP `/workspace/eval-java-call-resolution-unresolved` 和 MCP `mc_admin(action="eval_java_call_resolution_unresolved")` 按 `unresolved_reason` 汇总 `CALLS_METHOD`，输出脱敏逻辑锚点样本和下一步建议，避免盲目扩大 resolver fallback。
- 新增 `eval-agent-guidance-replay-campaign`：检查真实 replay 的事件量与意图覆盖；它只读，不会把工具采纳误写成检索正确性反馈或自动修改 retrieval 权重。

- Hybrid query 与 auto-routed walkthrough 新增兼容字段 `agent_next_steps`，把 retrieval policy、freshness、completion status 和现有证据收敛成结构化下一步建议。
- `agent_next_steps` 会明确提示 Agent 读取现有 `read_targets`、切换到 walkthrough、验证 semantic 命中、细化查询或先处理 stale/pending 证据，减少重复全局搜索。
- MCP `mc_lookup` 在自动路由和直接 query/symbol/code/context/chain/trace 路由下会把 `agent_next_steps` 提升到顶层；Golden agent guidance 门禁现在也会检查 `agent_next_steps` 中的低效搜索建议。
- CLI `memory-center query`、HTTP `/workspace/query` 与 core `memory_query_hybrid` 已补三入口可见性回归测试，确保查询入口都能返回结构化 `agent_next_steps`。
- Golden Benchmark summary 现在会汇总 `agent_next_step_count` 与 `agent_next_step_action_counts`，报告层可直接看到下一步建议覆盖率和动作分布。
- Golden performance baseline / compare 现在会保存并比较 `agent_next_steps` 覆盖率、低效搜索建议数量和 reduction rate；即使 latency/token 没退化，Agent 下一步建议质量退化也会让 gate 失败。
- 新增 `memory_eval_agent_guidance` / `eval-agent-guidance` / `/workspace/eval-agent-guidance` / `mc_admin(action="eval_agent_guidance")`，日常 health、regression suite 与 workspace dashboard 现在也能看到 `agent_next_steps` 覆盖率和低效搜索建议风险。
- 新增 `memory_eval_agent_guidance_adoption` / `eval-agent-guidance-adoption` / `/workspace/eval-agent-guidance-adoption` / `mc_admin(action="eval_agent_guidance_adoption")`，可基于 `agent_guidance` session event 与后续 `tool_call` 判断建议是否真的被执行。
- CLI `memory-center query --session-id ...`、HTTP `/workspace/query?session_id=...` 与 MCP `mc_lookup(session_id=...)` 现在会自动把返回的 `agent_next_steps` 记录为 `agent_guidance` session event，adoption 指标不再依赖手工记录。
- 新增 `agent-guidance-adoption-trends.jsonl`、`eval-agent-guidance-adoption-trend`、`/workspace/eval-agent-guidance-adoption-trend` 与 `mc_admin(action="eval_agent_guidance_adoption_trend")`，Benchmark trend report / regression alerts 现在能发现 adoption rate 下降。
- Adoption 趋势点新增 `missed_action_counts`；当最新退化趋势显示某个 action 反复未被执行时，后续 query 的 `agent_next_steps` 会保留 action 并附加 `adoption_feedback`、提升 priority、强化 command。
- 新增 `memory_eval_agent_guidance_replay` / `eval-agent-guidance-replay` / `/workspace/eval-agent-guidance-replay` / `mc_admin(action="eval_agent_guidance_replay")`，可回放真实 session event 并把建议执行结果分类为 `adopted`、`missed`、`bypassed` 或 `unobservable`。
- 新增 `agent-guidance-replay-trends.jsonl`、`eval-agent-guidance-replay-trend`、`/workspace/eval-agent-guidance-replay-trend` 与 `mc_admin(action="eval_agent_guidance_replay_trend")`，Benchmark trend report / regression alerts 现在能发现 replay adoption rate 下降、绕过率升高和不可观测率升高。
- Replay 趋势点新增 query-time 反哺：当最新退化趋势显示本地搜索绕过、不可观测、缺 target 或动作不匹配时，后续 `agent_next_steps` 会附加 `replay_feedback`，并强化 command、`session_id`、`target_ref/read_targets` 或 Memory Center mode。
- 新增 `agent-guidance-trends.jsonl`、`eval-agent-guidance-trend`、`/workspace/eval-agent-guidance-trend` 与 `mc_admin(action="eval_agent_guidance_trend")`，Benchmark trend report / regression alerts 现在能发现 `agent_next_steps` 覆盖率下降或无效泛搜索建议回潮。
- 修复 replay 回放把“先本地搜索绕过、后补做匹配工具”误记为 adopted 的问题；现在按后续工具事件顺序判定。
- 修复本地搜索检测会因 payload 文本子串（例如 `application` 中的 `cat`）误报 bypass 的问题；现在只检查结构化工具名和 shell 命令入口。
- 方法级 `switch_to_walkthrough` 建议现在保留 `target_ref` 和 `read_targets`，缺目标反馈可直接执行。
- 修复 core / CLI / HTTP 直接调用 method walkthrough 时遗漏顶层 `read_targets` 的问题；现在与 MCP facade 复用同一份主链路文件目标。
- Java 调用解析现在可依据本地字段与 Lombok `@Data` / `@Getter` / `@Setter` / `@Value` 解析生成的访问器，并在低置信度调用元数据中标记未解析原因，便于真实工作空间继续分层治理。
- 修复 Java regex supplement 忽略 package-private 方法的问题；这类方法的参数和局部变量类型现在可进入调用解析，避免把可确定的同包调用误标为 `receiver_type_missing`。
- Java 调用解析 benchmark case 新增 `allowed_targets` / `forbidden_targets`；CLI、HTTP、MCP 可选择对禁止的高置信边启用严格失败门禁，避免把合法同方法旁路误判为误绑定。
- 新增 Java 调用解析审阅报告：CLI `eval-java-call-resolution-review`、HTTP `/workspace/eval-java-call-resolution-review`、MCP `eval_java_call_resolution_review` 会对未分类高置信边按逻辑锚点聚合去重，并给出回写 case 契约的下一步。
- Golden Benchmark case 现支持 `impact`、`context` 模式和可选 `project` 范围，可为全链路、影响分析、架构理解三类真实检索意图建立带禁止锚点的统一回归门禁。
- 公开 Golden case 模板补充 impact / context 示例，展示同名跨模块时的 `project` 约束和禁止锚点写法。
- 新增 `eval-golden-baseline-save`，可在本地保存不含 case、路径和 payload 的 portable Golden 性能基线，供后续 `eval-golden --baseline` 做回归比较。
- 本地安装版本提升至 `3.5.22`。
- 修复 `parser-status` 的 Tree-sitter 安装提示仍指向旧版依赖范围的问题；提示现在与 `ast` extra 的 `tree-sitter>=0.25,<0.26`、`tree-sitter-java>=0.23,<0.24` 保持一致。
- 本地安装版本提升至 `3.5.21`。

### Task Space Resume Experience / 任务空间接手体验

- 新增任务空间健康检查与只读修复计划，可通过 CLI 与 MCP `mc_admin` 检查 `current_summary`、next actions、write receipts、相似任务空间等问题。
- `resume-packet` 现在携带轻量 `task_health` 与 `repair_plan_hint`，Agent 接手时可直接判断是否需要先修复记忆空间。
- 新增 `work-resume-check` / `mc_admin(action="task_resume_check")` / `/workspace/work-resume-check` 一键接手检查入口，聚合恢复包、健康摘要、修复计划、下一步动作和近期证据。
- 新增 `artifact repair-task` / `mc_admin(action="task_repair_apply")` 保守修复执行入口，默认 dry-run，显式 apply 时只执行低风险 task space 修复。
- 本地安装版本提升至 `3.5.19`。

### Parent Workspace MCP Adoption Fix / 父级 Workspace MCP 采纳修复

- 修复聚合 workspace 位于子项目上一层时，Agent 在子项目目录里较容易忽略 Memory Center MCP 的问题。
- `memory-center init` / `memory-center reindex` 现在会把受管说明块镜像写入每个已配置 service root 的 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md`、`.github/copilot-instructions.md` 与 `.cursor/rules/memory-center.mdc`。
- `memory-center init` / `memory-center reindex` 现在也会把 `memory-center` MCP server 绑定写入聚合根目录和每个 service root 的 `.codex/mcp.json`、`.cursor/mcp.json`、`.mcp.json`。
- 新增 `memory-center setup-agent --workspace <workspace.yaml>` 一键接入命令，统一刷新说明、Hooks、MCP 绑定并输出宿主重启建议。
- `memory-center runtime-audit --workspace <workspace.yaml> --fix` 现在会检查并刷新这些绑定，用于自动修复子项目里看不到 `mc_*` 工具的问题。
- MCP server 新增 `memory-center://startup-diagnostics` resource，启动后可查看 workspace 解析、MCP 绑定状态和修复建议。
- `memory_query_hybrid`、`memory_search_code`、`memory_method_walkthrough` 未显式传 `project` 时会优先使用当前子项目；当前子项目无命中时自动回退全局。
- 子项目级说明会显式写明应复用上层 `.memory-center/workspace.yaml`，并在 MCP 缺失时提示检查本地绑定，降低“当前仓库没有本地 workspace 就不调用 MCP”的概率。
- `memory-center-mcp` 的运行时依赖现在随默认安装一起安装，不再需要额外 `pipx inject memory-center "mcp>=1.2.0"`。
- 本地安装版本提升至 `3.5.18`。

### Documentation Status Cleanup / 文档状态收口

- 新增 `docs/DOCS_STATUS.md`，明确 active docs 与 historical docs 的边界。
- 新增 `docs/README.md` 作为 `docs/` 目录导航首页，按用途组织主文档、补充说明、benchmark 与历史文档入口。
- README 不再把旧路线图、旧执行计划和旧执行日志当成默认阅读入口，而是统一指向当前主文档集合。
- 历史规划与执行文档已集中归档到 `docs/archive/`，并保留历史文档提示，减少把旧计划误读为当前状态的风险。

### 3.5.14 Documentation Refresh / 架构文档刷新

- 重写 `docs/ARCHITECTURE.md` 为面向外部评审者、集成方和维护者的独立当前架构说明。
- 新增目录、系统定位、读者视角、核心能力域、部署形态、代码目录视图、分层契约和更完整的数据流说明。
- 移除旧式推荐阅读、维护地图、路线图和 backlog 口径，避免架构说明与计划文档混杂。

### P1 Java Call Resolver Self-Loop Fix / Java 调用解析自环修复

- 真实 UCAP 工作区上发现 ~13K `CALLS_METHOD` self-loop 假边
  (`Service:m -> Service:m`),根因是 `RegexJavaParser` 把抽象 interface
  方法声明也当成 method body。bare-call 正则在 `start..end` 内匹配到方法
  自身签名,被 `_same_class_candidates` 解析成 self-call。
- 修复:`_parse_interface_methods` 给抽象方法 span 加 `is_declaration=True`
  标记;`_parse_method_calls` 跳过 declaration-only span。
- 真实 UCAP 效果:self-loop CALLS_METHOD 12,812 -> 795
  (-94%,残留 795 条是真实递归调用如 `RedisServiceImpl:hSet` 重载 dispatch);
  CALLS_METHOD 总量 294,230 -> 279,542(-14,688 条假边消除);
  same_class resolution_level 边 30,578 -> 18,558(全部去掉的都是 self-loop)。
- Java call resolution gate (15 cases) 保持全过;不影响合法 same_class
  fluent chain (`ServiceImpl#download -> ServiceImpl#buildObjectKey`)。
- 新增 `tests/test_p1_call_resolution_and_vector_gate.py` 锁住 interface
  自环不重现、default 方法体仍正常抽取调用。

### P1 Java Call Resolution Cases Expansion / 调用解析 case 扩充

- `golden/java-call-resolution-openapi.yaml` 从 15 个 case 扩到 **26 个**,
  覆盖 5 类真实路径:
  - Controller -> ServiceImpl(直接 DI Impl 注入)
  - Controller -> Service interface(多态 dispatch,3 个 case)
  - ServiceImpl -> Mapper / Dao(3 个 case)
  - ServiceImpl same-class private helper(2 个 case)
  - static_import call (Util / Helper,2 个 case)
- 全 26 个 case 通过:`edge_recall=1.0` / `high_confidence_expected_rate=1.0` /
  `resolution_level_rate=1.0` / `unresolved_rate=0.0`。
- `java-call-resolution-baseline.json` 同步更新为新基线
  (`case_count: 26`, `unexpected_high_confidence_edge_count: 42`)。

### P1.5 Vector Gate / 向量召回长期门禁

- `GoldenCase` schema 新增可选字段 `enable_vector`(默认 False),让概念
  query 类型 case 可以显式声明走 ANN 路径。`memory_query_hybrid` 在
  hybrid mode 下读取此字段并传给 retrieval policy。
- `golden/cases.yaml` 新增两个 vector-aware case 把
  [P0_5_VECTOR_VALIDATION.md](./benchmarks/P0_5_VECTOR_VALIDATION.md) 的
  收益锁进 long-term gate:
  - `vector-feign-auth-interceptor`("Feign 调用的鉴权拦截器" ->
    `FeignConfig#feignDecoder` + `FeignSpringFormConfiguration#feignContract` + ...)
  - `vector-kafka-consumer-handler`("Kafka 消费者解析消息" ->
    `KafkaOneConfig#kafkaOneContainerFactory` + `KafkaTwoConfig#kafkaTwoContainerFactory`)
- 真实 UCAP 效果:golden anchor_recall 0.6444 -> 0.8667(vector 命中
  方法级 anchor 提升 recall)。
- `_sync_retrieval_indexes` 修复:reindex 在 sparse backend 下不再清空
  之前 ST run 留下的 `VectorIndex` 嵌入。原行为会导致任意一次
  `memory-center reindex`(没传 `MEMORY_CENTER_SEMANTIC_BACKEND`)悄悄
  把 dense vectors 抹掉。新行为:`dense_items` 为空时保留现有 VectorIndex。
- Vector 增量同步完成真实验证:partial semantic rebuild 只重 encode 1 个
  changed dense candidate;VectorIndex `vector_sync_mode=partial`,只 delete/upsert
  该 changed node,embedding_count 保持 47,633。当前 partial sync 仍耗时 ~23s,
  主因是 BM25 仍全量 rebuild,后续可作为 P2 性能项单独优化。

### Vector Retrieval Real Validation / 向量检索真实场景验证

- 新增 [docs/benchmarks/P0_5_VECTOR_VALIDATION.md](./benchmarks/P0_5_VECTOR_VALIDATION.md):
  在真实 UCAP workspace (316,696 nodes / 47,633 vector candidates)
  上端到端验证 `MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers`
  + `selective` scope + ANN retrieval 全流程。`vector_status: ready`,
  query "Feign 鉴权拦截器" elapsed 13.2s -> 2.8s(-78%),top1 命中从
  file 级升级为 method 级语义命中(`vector_ann + sparse_bm25 + semantic`)。
- `retrieval_diagnostics.policy` 同时暴露 `vector_enabled`(policy
  实际选择)与 `enable_vector` / `enable_sparse_bm25` / `enable_semantic`
  (user 请求),让宿主能解释"开了 vector 却没用"或"自动 policy
  选择 vector"等情况。
- 默认仍是 `sparse` backend;`sentence-transformers` / `sqlite-vec`
  保持 optional 依赖,47K x 384 维 numpy brute_force 已经 sub-100ms,
  当前规模不需要额外向量数据库。

### Vector Observability / 向量可观测性

- reindex 汇总新增 `semantic_backend`、`requested_semantic_backend`、
  `semantic_model`、`requested_semantic_model`、`vector_scope`、
  `vector_candidate_count`、`dense_doc_count`、`vector_status`、
  `vector_disabled_reason`。当 `vector_embeddings=0` 时可直接判断是
  sparse backend 未开启、`sentence-transformers`/模型不可用、scope 无候选，
  还是 dense vector 已生成但未同步。
- `semantic_index_stats()` 同步返回上述状态字段，并保留原有
  `backend` / `requested_backend` 字段，兼容现有调用。
- English summary: reindex and semantic stats now explain vector readiness
  instead of only reporting `vector_embeddings=0`.

### P0 Index Hot Path / 索引热路径修复

- 新增 [docs/benchmarks/P0_INDEX_HOT_PATH_DESIGN.md](./benchmarks/P0_INDEX_HOT_PATH_DESIGN.md):
  P0-0 CBM 参考对齐后的索引热路径设计,锁定三个修复的共享契约(MCP /
  CLI / HTTP schema 零变化、parser 行为可观测可回滚、`RegexJavaParser`
  保留为 fallback / differential oracle、真实 UCAP reindex 不慢于基线)。
- `JavaSymbol.to_dict()` 手写浅拷贝;`core.models.to_dict` 优先调用
  对象自带 `to_dict`,回退 `dataclasses.asdict`。输出键集合、键序、
  值与 `asdict` 完全一致;本地微基准 22K JavaSymbol 实例提速 ~97x。
- 新增 `memory_center/core/storage/metadata.py`:`metadata_json` 在
  metadata 为空/`None` 时直接返回字面量 `'{}'`,非空才走 `json.dumps`。
  `GraphStore.rebuild` / `bulk_write` / `partial_rebuild` /
  `_upsert_search_rows` 以及 `retrieval/inverted.py`、`semantic.py`
  全部统一调用。空 metadata 路径本地微基准提速 ~19x。
- `TreeSitterJavaParser.parse` 不再默认全量执行 `RegexJavaParser.parse`:
  tree-sitter 成功路径改为调用新的 `RegexJavaParser.parse_supplements`,
  只补抽 `constants` / `method_variable_types` / `bean_injections` /
  `method_calls` / `dto_field_usages` / `config_usages` / `data_resources`,
  跳过 tree-sitter 已覆盖的结构性扫描。`MEMORY_CENTER_PARSER_FULL_DUAL=1`
  可一键回退到旧的“双轨全量 + merge”行为。`TreeSitterJavaParser.diagnostics`
  新增 `supplement_call_count`、`full_regex_fallback_count`、`full_dual_mode`
  三个计数。
- 在 `examples/spring-cloud-demo` 全量 Java 文件与代表性 Spring
  Controller / Feign / Kafka 样例上,supplements 路径与 legacy
  full-dual 路径 `JavaParseResult` 字段完全一致;新增
  `tests/test_p0_index_hot_path.py` 锁住这条契约。
- 同步修补 tree-sitter `_walk`,正确识别 `@interface`
  (`annotation_type_declaration` / `annotation_type_element_declaration`)、
  interface 内常量(`constant_declaration`)、wildcard / static imports,
  使 tree-sitter 节点覆盖与 legacy regex 一致或更准。
- 真实 UCAP workspace(20,516 Java files / 27 GB)验收(2026-06-24):
  Java call resolution gate edge_recall/high_confidence_rate/resolution_level
  全部 1.0、unresolved 0.0;Golden suite edge_recall=1.0、forbidden_hit=0.0、
  performance_gate=pass、anchor_recall 0.8286 与 legacy 持平;Doctor 53
  checks 0 fail;Walkthrough state=complete 5 层全部命中;Reindex 一次
  冷启动 140.6s → 139.0s(wall-clock 持平,IO 抖动主导),graph
  316,695 nodes / 1,023,066 edges(比 legacy 多 ~1.7K 节点,因为
  tree-sitter 节点覆盖更全 + fast 路径跳过了 SQL 字符串里的 false
  positive)。详情见
  [docs/benchmarks/P0_INDEX_HOT_PATH_DESIGN.md §5](./benchmarks/P0_INDEX_HOT_PATH_DESIGN.md)。
- `tests/test_parser_differential.py`、
  `tests/test_java_call_resolution_benchmark.py`、
  `tests/test_golden_benchmark.py`、`tests/test_graph_rebuild_perf.py`、
  `tests/test_benchmark_workspace_perf.py` 全绿;`pytest -q` 1496 用例
  无失败。

### Java Call Resolution Gate / Java 调用解析真实门禁

- 新增 `memory-center eval-java-call-resolution`，基于 graph 中的
  `CALLS_METHOD` 边评测 Java 调用解析的 expected-edge recall、
  high-confidence expected rate、resolution-level 命中率和 unresolved rate。
- 新增 HTTP `/workspace/eval-java-call-resolution` 与 MCP
  `mc_admin(action="eval_java_call_resolution", name="<cases.yaml>")` 入口。
- cases 文件只允许 `Class#method` 这类逻辑锚点，不允许文件系统路径；
  真实私有 UCAP 样例保存在本地 workspace `.memory-center/golden/`，不提交。
- English summary: adds a real-workspace Java CALLS_METHOD precision gate with
  logical anchors only, so resolver improvements can be compared against
  private scenarios without committing private paths or generated indexes.

### 3.5.10: Java Call Resolver / Java 调用解析器

- 新增 `memory_center/core/indexing/java_call_resolver.py`，基于全工程
  `JavaClassIndex` 将 Java `method_calls` 解析为单一最佳目标，支持
  same-class / same-package / explicit import / wildcard import /
  static import / overload evidence。
- `RegexJavaParser` 现在保留 `import static`，并为方法调用记录裸调用与
  `arg_count`，让 resolver 能处理 `normalize(...)` 这类静态导入调用和
  重载签名匹配。
- `build_graph_store` 写入 `CALLS_METHOD` 时使用 resolver 结果，边上记录
  `resolution_level`、`target_fqcn`、`matched_signature`、`inferred_target`
  等元数据；无法解析的调用保留为 `confidence=0.3` 的 inferred target，
  不再误连到随机同名真实方法。
- `memory_callers` / `memory_callees` 默认优先过滤 `confidence >= 0.85`；
  若高置信结果为空会自动降级返回低置信边并标注 `confidence_filter`。
  CLI / HTTP 增加 `min_confidence` 参数，传 `0` 可主动查看 unresolved /
  wildcard 等低置信边。
- 修正 chain 去重粒度：类名前缀不同的 `InvoiceService.create` 与
  `MissingService.create` 不再被短方法名 `create` 合并。
- 本地安装版本提升至 `3.5.10`。本次 review 额外修复裸调用抽取噪音：
  `new Foo(...)` 不再被误记为 `Foo()` 方法调用。
- English summary: P1-1 adds a Java call resolver that upgrades method-name
  matching into confidence-scored CALLS_METHOD edges using same-class,
  same-package, import, wildcard import, and static import evidence.
  Unresolved calls remain visible as low-confidence inferred targets instead
  of being bound to unrelated same-name methods.

### CBM-Inspired Evolution P1-0: Java Parsing Hot-Path Profile / Java 解析瓶颈定位

- 新增 `memory_center/core/perf/` 模块:`profile_reindex` 用 cProfile
  包裹完整 reindex,产出 `.prof` 文件 + 人类可读 top-N 表;
  `aggregate_by_module` 把函数级数据滚动到模块级,便于诊断"哪个子系统
  最热"。
- 新增 CLI `memory-center bench-profile --workspace <yaml>`,默认 top 50
  按 cumulative 排序,支持 `--by-module` 滚动 / `--label` 给 `.prof`
  文件起名 / `--sort-by` 切换排序键。
- 在真实 UCAP 工作区(20,516 Java 文件)上跑出第一份诊断报告:
  [`docs/benchmarks/P1_0_JAVA_PARSING_PROFILE.md`](./benchmarks/P1_0_JAVA_PARSING_PROFILE.md)
  。原始 pstats 由 `bench-profile` 本地生成到工作区 `.memory-center/perf-profiles/`,
  不提交到仓库。识别出三个真实瓶颈:
  - **Java parser 双轨开销 ~58s**:`TreeSitterJavaParser.parse` 即使
    tree-sitter 成功也仍然全量跑一遍 `RegexJavaParser`(~44% 总耗时)
  - **`dataclasses.asdict` 调用爆炸 ~20.8s**:22,809 个 JavaSymbol →
    13.5M 次 `_asdict_inner` 递归
  - **`json.dumps` 4.59M 次 ~14.2s**:graph metadata 序列化次数过多
- 3 个新测试覆盖 profile 输出契约(pstats 文件被写、top_n 影响 summary
  长度、模块 rollup 按 cumulative 降序)。全量套件零回归。
- English summary: P1-0 introduces a cProfile-based reindex profiler
  (CLI: `bench-profile`) and produces the first hot-path report on a
  real Java monorepo. The 71% non-SQLite bucket flagged by P0's
  benchmark turns out to be dominated by three concrete Python-level
  issues (dual-track parsing, asdict recursion, json metadata
  serialization), not by tree-sitter itself. Together these account
  for ~50-90s of saveable time, leading to a new P1-0.5 stage for
  targeted optimization before the planned P1-1 call resolver work.

### CBM-Inspired Evolution P0-2: Multi-Language Structural Indexing / 多语言结构索引

- 新增 `memory_center/core/indexing/parse_result.py` 定义跨语言通用结构:
  `SymbolSpan` / `CallSite` / `StructuralParseResult`(轻量,4 个核心字段)。
  Java 现有 `JavaParseResult` (23 字段,含 Spring 专属注解/Bean 注入等)保留,
  两条路径并行不冲突。
- 新增 `memory_center/core/indexing/language_registry.py`,注册 7 种语言:
  java / kotlin / python / typescript / tsx / javascript / go。每个 spec 记录
  tree-sitter binding 包名 + Language attribute + pip extra 名,`load_language`
  按需懒加载。
- 新增 `memory_center/core/indexing/structural_parser.py` 实现
  `TreeSitterStructuralParser`,每种语言独立 walker:Java/Python/Go/TS/Kotlin
  各自处理 class / function / import / call。Qualified name 由声明栈累积,
  receiver 文本单独抽出供 P1-1 解析器使用。
- 新增 `memory_center/core/indexing/multilang_indexer.py` 作为 indexer 主流程
  的薄粘合层:`is_structurally_indexable` 决定文件是否走 multilang 通路(Java
  排除以避免与 Spring 专属抽取双写),`parse_structural` 缓存 parser 实例,
  `emit_graph_elements` 把结构化结果翻译成 Module / Class / Function 节点
  + DEFINES / IMPORTS / CALLS 边,沿用 Java 路径的 `node_id` / `edge_id` 约定。
  CALLS 边初始 confidence=0.3 + `resolution_level=unresolved`,待 P1-1 解析器
  改写。
- `indexer.reindex_workspace` 在 Java 收尾后追加多语言结构 pass,partial
  reindex 的 `--project` / `--path` 过滤继续生效。
- `pyproject.toml` 引入 `multilang` extra(tree-sitter 0.25 + java/python/
  typescript/go/kotlin 五个 binding,版本 pin 到下一 minor 防漂)。`all` extra
  同步扩展。`ast` extra 升级到 0.25 系列。
- 端到端验证:对一个含 `pyproject.toml` 的 Python 微服务跑 `init --detect`
  +`reindex`,图谱产出 Module/Class/Function 节点 + DEFINES/IMPORTS/CALLS 边,
  与 Spring 索引并存。
- 47 个新测试通过(30 registry + 7 structural + 10 multilang glue),全量
  套件零回归。
- English summary: P0-2 lifts the indexer from "Java only" to a 7-language
  structural index (Java/Kotlin/Python/TypeScript/TSX/JavaScript/Go). The
  Spring-aware Java pipeline is untouched; non-Java files now flow through
  a generic tree-sitter walker that emits Module/Class/Function nodes and
  DEFINES/IMPORTS/CALLS edges. Call edges are intentionally left at low
  confidence with ``resolution_level=unresolved`` so P1-1's resolver can
  rewrite them in place without breaking any downstream consumer.

### CBM-Inspired Evolution P0-3: SQLite Indexing Performance / SQLite 索引性能

- 新增 `memory_center/core/storage/pragmas.py` 作为 SQLite PRAGMA 单一
  来源:`DEFAULT_PROFILE`(WAL / NORMAL / 200 MB cache / MEMORY temp_store /
  256 MB mmap / FK on)+ `FAST_WRITE_PROFILE`(synchronous=OFF)+
  `apply_pragmas` / `read_pragma_state` / `fast_write_mode` helper。
- 修复 `GraphStore.connect` / `MemoryBackendStore.connect` 之前完全
  没有应用 PRAGMA 的隐藏 bug(只有 `SQLitePool` 配过,且 cache 仅 64MB)。
  现在三处全部走 `apply_pragmas`,确保 reindex 主写库路径也走 WAL +
  大缓存 + 内存 temp store + mmap。
- `GraphStore.rebuild` / `rebuild_search_index` 从"逐条 INSERT 循环"
  改为 `executemany` + `fast_write_mode` 包裹。⚠️ **实测校准**:在真实
  UCAP Java 大仓(20,516 文件)上 reindex wall-clock **无显著变化**
  (`graph.rebuild` 仅占总耗时 18.7%,Java 解析占 ~71%);完整数据见
  [`docs/benchmarks/P0_UCAP_REAL_BENCHMARK.md`](./benchmarks/P0_UCAP_REAL_BENCHMARK.md)。
- `estimate_optimal_workers` 重新调参以适配 IO-bound 文件读取:上限
  从 8 → 32,小批量(≤4 文件)走 serial,中等批量按 `min(cpu*2, max, n)`
  并保底 2 worker。修正了"<10 文件返回 0 workers 导致悄悄退化为单线程"
  的旧 bug。
- `doctor` 输出新增 `sqlite_pragmas` 段和 `graph:pragma_wal` 检查项,
  方便用户一眼看出连接是否被正确调优。
- 21 个新测试覆盖 PRAGMA 默认值 / 幂等 / fast_write_mode 进出异常恢复 /
  store inheritance / rebuild 持久化与重置 / FTS / worker 数量边界。
  全量套件零回归。
- English summary: a hidden bug — GraphStore and MemoryBackendStore
  were opening bare SQLite connections without any PRAGMA tuning —
  dominated reindex latency on real monorepos. P0-3 unifies PRAGMA
  configuration across every store, switches the bulk reindex rewrite
  to executemany + synchronous=OFF, and modernizes the parallel
  parser's worker-count heuristic for today's IO-bound workload.

### CBM-Inspired Evolution P0-1: Service Kind Registry / 服务类型注册表

- 新增 `memory_center/core/service_kinds.py`,统一管理服务类型(11 种):
  `spring-cloud-gateway` / `spring-boot-service` / `spring-boot-task` /
  `shared-library` / `generic-jvm` / `kotlin-module` / `python-package` /
  `node-app` / `go-module` / `rust-crate` / `generic`。
- `ServiceConfig` 增加可选 `language` 字段及 `resolved_language()` 助手;
  默认 `type="spring-boot-service"` 保留,旧 workspace.yaml 零变更。
- `memory-center init` 默认开启自动探测(`--detect`,可用 `--no-detect`
  回退到旧 Spring 模板;`--dry-run` 仅预览不写文件),按子目录构建标记
  匹配 kind,并对 `*-api` / `*-common` / `*-core` 命名自动加 contract /
  common 标签。
- 真实验证:对 C 项目 `codebase-memory-mcp` 跑 `init --dry-run` 不再写入
  3 个虚假 Spring service,只识别 `graph-ui` (`node-app`)。
- 新增长期演进计划 `docs/archive/CBM_INSPIRED_EVOLUTION_PLAN.md`,记录 P0/P1/
  P2/P3 各阶段从 codebase-memory-mcp 学到的设计借鉴(多语言 parser、
  RAM-first 索引、跨服务边抽象、团队共享 graph artifact 等)。
- English summary: introduced a service kind registry that decouples
  memory-center from the Spring-only assumption (11 kinds across JVM /
  Kotlin / Python / Node / Go / Rust / generic). `init` now auto-detects
  service types per submodule, falls back gracefully on unrecognized
  repos, and exposes `--dry-run` / `--no-detect` for explicit control.

### Next: Ruff Modernization and Real Precision Gates / Ruff 现代化与真实精度门禁

- Ruff 现代化分层收口继续推进：批量清理 `UP006/UP035/UP037/UP045/UP031/UP007`，并手工判断修复剩余 `B007/B905` 语义项。
- CLI Typer 命令签名保留 `typing.List/Optional` 兼容写法，避免 Python 3.9 运行时求值 `list[str] | None` 失败；普通 core 模块继续保留现代类型写法。
- Parser 精度诊断新增 `parser_precision`：reindex、graph summary、retrieval diagnostics、reasoning diagnostics 均可显式返回 `regex_only/mixed_fallback/native_ready` 状态和下一步建议。
- 新增 `parser-status` CLI，直接输出 tree-sitter Java 启用状态、pipx/local/editable 安装命令和 parser benchmark 验证命令。
- Golden Benchmark 新增 portable coverage summary；真实场景脚本现在输出 case mode 分布、anchor/edge 覆盖和建议补齐方向。
- `workspace_next_actions` 保留兼容的字符串 `actions`，同时新增证据化 `action_items`，每条包含 action、reason、evidence、command、priority。
- 热路径索引读取改为文件快读 + backend fallback，并保留 `read_json_observed()` 做显式一致性双读；真实 UCAP walkthrough latency 从 3.5.7 基线 `2433.243ms` 降到本次验收 `313.382ms`。
- 真实 UCAP 回归通过：tree-sitter active reindex `native_success_count=16304`、`fallback_count=0`、`critical_disagreement_count=0`；私有 Golden 扩展到 7 条，覆盖 walkthrough / hybrid / MQ / config，anchor recall `1.0`、edge recall `1.0`、forbidden hit rate `0.0`，完整链路 `completion_status=complete`。

English summary: the next release continues Ruff modernization, makes parser precision visible across indexing/retrieval/reasoning, preserves Typer compatibility on Python 3.9, and improves real UCAP walkthrough latency while passing the no-regression Golden gate.

### 3.5.9: Ruff Governance Baseline / Ruff 治理基线

- 清理 legacy Ruff 运行级问题：`F/E9` 已通过，避免未使用导入、未定义名、重复导入等基础错误继续混入开发噪音。
- 统一 import 排序：`I001` 已通过，后续 diff 更容易聚焦真实逻辑变化。
- 修复 bugbear 风险项：`B006/B008/B904` 已通过，包含可变默认参数、Typer list 参数默认值和异常链处理。
- 本地安装版本提升至 `3.5.9`，并继续通过真实场景验收脚本与 performance gate。
- 下一步计划已统一收敛到 `docs/NEXT_PHASE_MASTER_PLAN.md`：优先做 Java reindex 性能热点修复，其次推进 Java Parser / Call Resolver 真实精度深化，再继续 Retrieval / Reasoning 质量闭环与输出体验产品化。

English summary: 3.5.9 establishes a practical Ruff governance baseline (`F/E9/I001/B006/B008/B904`) and documents the next staged cleanup and product-quality work.

### 3.5.8: Real Baseline No-Regression Gate / 真实基线不回归门禁

- Golden `performance_gate` 默认语义调整为“不低于当前真实基线”：token 默认不允许增加，latency 默认允许 `10%` 运行抖动；可通过参数继续设置更严格改善要求。
- `scripts/verify_real_ucap.sh` 支持 `MEMORY_CENTER_REAL_BASELINE` 和 `MEMORY_CENTER_SAVE_REAL_BASELINE=1`，可把当前已验收真实 UCAP 指标保存为后续性能基线。
- 文档明确当前 `3.5.7` 真实 UCAP Golden 可作为后续 baseline，后续版本不得低于该基线；基线保存在真实 workspace 本地，不提交私有指标文件。

English summary: real UCAP Golden performance now uses a no-regression baseline by default, with an opt-in path to save the current validated run as the private baseline.

### 3.5.7: Walkthrough Report Levels / 全链路输出视图分级

- Method walkthrough `report_level` 新增正式三档视图：`summary`、`standard`、`deep`。
- `summary` 只保留快速结论、主链路、证据文件编号、关键风险和下一步；`standard` 保持默认详细可读视图；`deep` 展开 glossary、rule groups、branch outline、anti-patterns 等深度诊断区块。
- 旧 `brief` 保留为兼容别名并归一到 `summary`；结构化字段不删减，三档只改变 `answer_markdown` 展示详略。
- 真实 UCAP 场景验证三档共享同一 `summary_lines` 主链路，`completion_status=complete`。

English summary: method walkthrough now supports summary, standard, and deep report levels without changing structured fields.

### 3.5.6: Real UCAP Verification Script / 真实 UCAP 验证脚本

- 新增 `scripts/verify_real_ucap.sh`，作为后续本地验收默认入口，固定验证用户提供的真实 UCAP workspace、私有 Golden cases 和关键全链路查询。
- 脚本只输出 doctor、Golden summary/performance gate、walkthrough completion status 等摘要字段，不打印完整 payload、源码片段或完整文件路径。
- 支持通过 `MEMORY_CENTER_REAL_WORKSPACE`、`MEMORY_CENTER_REAL_CASES`、`MEMORY_CENTER_REAL_QUERY`、`MEMORY_CENTER_REAL_PROJECT` 覆盖默认真实场景。

English summary: a real-scenario verification script now runs doctor, Golden, and the key full-chain query against the user-provided UCAP workspace without dumping private payloads.

### 3.5.5: Golden Performance Gate / Golden 性能门禁

- Golden Benchmark 新增 `performance_gate`，支持传入可选性能 baseline，对 `median_latency_ms` 和 `token_estimate` 计算改善率。
- CLI `eval-golden` 和 HTTP `/workspace/eval-golden` 新增兼容型可选 `baseline` 参数；不传 baseline 时返回 `baseline_missing` 和可保存的当前 baseline 快照，不伪造历史对比通过。
- 新增 portable baseline 生成函数，只保留 summary/performance 指标，不包含 cases、payload、文件路径或源码内容。

English summary: Golden Benchmark now has an optional performance gate for latency and token improvements. Missing historical baselines are reported explicitly with a portable current snapshot.

### 3.5.4: Golden Agent Guidance Gate / Golden Agent 建议门禁

- Golden Benchmark 新增 `agent_guidance` 指标，统计完整链路结果中是否仍存在鼓励全局 `find/grep/rg --files/sed/IDEA search` 的无效搜索建议。
- 新增 `agent_invalid_search_suggestion_count` 与 `agent_invalid_search_reduction_rate` 汇总门禁；Golden suite 通过条件现在要求无效搜索建议为 `0` 且下降率 `>= 50%`。
- 反模式提示里的“不要 find/grep”“直接读 absolute_file_path”等否定式建议不会被误判为坏建议。
- CLI、HTTP、MCP `eval_golden` 复用同一 `run_golden_suite` 输出，无需新增参数或破坏现有 schema。

English summary: Golden Benchmark now gates agent-facing guidance, ensuring complete walkthroughs tell agents to use current evidence instead of restarting broad repository searches.

### 3.5.3: Walkthrough Completion Status / 全链路完成状态

- 新增 additive 顶层字段 `completion_status`，用于标记 method walkthrough / full-chain query 当前证据是否 `complete`、`partial`、`blocked` 或 `stale`。
- 完整链路会返回 `recommended_action=use_current_evidence`，明确提示 Agent 使用当前证据而不是继续全局 find/grep；不完整链路会列出 `missing_layers` 和 `stop_reason`。
- MCP `mc_lookup` walkthrough flatten、core query walkthrough、compact walkthrough 和 Web 查询页统一透出同一状态字段。
- 默认 Markdown 快速结论中显示完成状态、终点 anchor 和建议动作，保持详细输出同时减少后续无效搜索。

English summary: walkthroughs now expose a structured completion status across core, MCP, and Web query views so agents know when to stop searching, fill missing layers, or refresh stale evidence.

### 3.5.2: Walkthrough Readability Report v2 / 全链路报告可读性优化

- 默认 method walkthrough Markdown 保留完整细节，但改为“快速结论 → 主链路 → 分层详情 → 证据文件 → 风险与数据范围”的阅读顺序。
- 新增证据文件编号（如 `[F1]`），主链路中用编号引用路径，完整 `absolute_file_path` 仍集中保留在证据文件区和结构化返回字段中。
- 性能风险按 `code` 聚合展示，重复风险会合并为出现次数和行号摘要，避免同类风险刷屏。
- Mermaid 默认只绘制主调用链，不再把风险和数据范围节点混入链路图；风险仍在独立章节保留。

English summary: walkthrough Markdown is now detailed but easier to read, with layered sections, numbered file evidence, aggregated risks, and cleaner main-chain diagrams.

### 3.5.1: Full-Chain Query Walkthrough Routing / 全链路 Query 路由修复

- 修复 CLI/core `memory_query_hybrid` 在 `Class#method + 全链路/到底层` 自然语言查询下仍走泛化 graph token 排序的问题。
- 这类查询现在会优先复用 method walkthrough，返回 `mode_used=query_walkthrough`、`summary_lines`、`answer_markdown`、`read_targets` 和 `agent_usage_policy` 等顶层字段。
- 真实 workspace 回归中，典型跨服务 `ServiceImpl#method` 全链路查询不再误返回低信号构建文件，可直接追到入口 Service、辅助 Service、Feign、下游 Controller/Impl 与同类辅助查询方法。

English summary: natural-language `Class#method` full-chain queries now route to method walkthrough from the core query entrypoint, avoiding low-signal token-ranked results.

### 3.5.0: Adaptive Retrieval Policy / 自适应检索策略

- 新增纯函数 `RetrievalPolicy`，基于查询意图、索引 freshness 和有界学习权重，在执行检索源之前确定 sources、图深度、候选数和证据预算。
- 全链路查询固定保留 exact + graph 硬约束，关闭非必要 semantic/vector/BM25，深度图遍历端点直接参与证据融合；普通查询继续兼容原多源检索行为，vector 仍默认关闭。
- 学习反馈按 intent/source 隔离并限制在 `[0.35, 0.75]`，只能轻量调权，不能覆盖 exact/graph 等规则硬约束。
- `retrieval_policy` 与 `retrieval_diagnostics.policy` 提供可解释决策；现有 MCP tool schema 和调用参数保持兼容。
- 公开 Golden 与真实 workspace Golden 均通过；隔离 A/B 中 full-chain median latency 从 `11.964 ms` 降至 `9.261 ms`（`22.6%`），估算 token 从 `7341` 降至 `2812`（`61.7%`）。

English summary: adaptive retrieval now selects bounded sources, graph depth, candidates, and evidence budgets before execution while preserving exact/graph safety constraints and backward-compatible APIs.

### 3.4.0: Java Parser Differential Gate / Java Parser 差异门禁

- 新增 `core/indexing/differential.py` 与公开 `examples/parser-corpus/`，逐项比较 class、interface、重载方法身份、行号、field、注入、调用、Controller mapping 和 Feign mapping。
- `JavaParseResult` / `JavaSymbol` 新增兼容型 `method_signatures` 与 `constants`，保留原 `methods` 和图节点 ID，不引入破坏性图谱迁移。
- 修复 interface default method 被误解析为无参重载、嵌套泛型参数类型丢失、多类型文件 Feign 注解归属错误，以及 Controller/Feign mapping 跨类型串线。
- Controller 与 Feign 现在支持同文件注解常量和组合路径；常量值从 `field_types` 语义中独立为 `constants`，旧字段继续兼容。
- reindex 新增 additive parser diagnostics：实际 parser、parse/fallback 次数、fallback 原因、native disagreement 和 critical disagreement。
- 公开 corpus 达到 critical disagreement `0`、entity recall `1.0`、最大行号差 `0`；私有真实 workspace Golden Benchmark 保持 anchor/edge recall `1.0`、forbidden hit `0`。

English summary: this release adds entity-level Java parser differential gates, overload identities, constant-path resolution, observable fallback diagnostics, and scoped Spring mapping extraction.

### 3.3.0: Evidence-Bounded Reasoning Pipeline / 证据预算化推理管线

- 新增 `ReasoningRequest` 与 `ReasoningPipeline`，统一事实、推断和派生结论，并为每条非事实结论返回来源、关系、置信度和 `why`。
- `memory_context`、`memory_impact` 和 method walkthrough 现在复用同一 Pipeline；原 `patterns` / `transitive` / `risk` 字段继续保留，MCP tool schema、CLI 和 HTTP 路径不变。
- compact 输出保留最多两条 facts / inferences / derived 及质量摘要，避免 reasoning 结果挤占主链路上下文。
- 目标级 context / impact / walkthrough 跳过全工作区 pattern scan；workspace audit 仍可运行全局模式。
- 传递推理从路径爆炸型递归 CTE 改为有界分层批量遍历。私有真实 workspace Golden Benchmark 保持 anchor/edge recall `100%`、forbidden hit `0`，延迟 `2.82s`，额外 token 约 `1.7%`。

English summary: reasoning now has one evidence-bounded pipeline, additive facade integration, compact canonical output, and bounded transitive traversal for large graphs.

### 3.2.1: Golden Benchmark on Real Workspaces

- 新增 `GoldenCase` / `run_golden_suite()`，支持对真实 `workspace.yaml + cases.yaml` 运行 portable Golden Benchmark。
- 新增 CLI `memory-center eval-golden`、MCP `mc_admin(action="eval_golden")`、HTTP `/workspace/eval-golden` 三入口适配。
- Golden evidence extraction 现在能从 walkthrough 的 `same_class_method_continuations`、`local_service_continuations`、`feign_continuations.server_walkthroughs`、`service_impl_continuations` 提取逻辑锚点与边类型。
- 新增公开示例 `examples/golden-benchmark/`：包含 demo `workspace.yaml`、公开 `cases.yaml` 和私有 benchmark 模板 `cases.template.yaml`。
- 新增 Golden Benchmark 测试，覆盖 scoring、隐私字段防护、CLI/MCP/HTTP dispatch，以及 public demo suite 真实回归。

### 3.2.0: Consistency, Incremental Indexing, and Observability

- Unified Backend 新增 observable dual-read，旧镜像、部分 JSONL 和 backend 不可用时回退文件事实源，并返回来源与一致性 diagnostics。
- 增量索引统一处理新增、修改、删除和 rename；删除或旧 rename 路径会同步清理确定性索引与 graph。
- hybrid lookup 与 walkthrough 新增兼容型 `_meta`，query、audit、drill-down 新增统一 `_quality`，明确 fact / inferred / derived、置信度和验证动作。
- 新增 `OperationObserver`，reindex 与 hybrid lookup 自动记录脱敏的 outcome、duration 和 result count。
- 新增 portable benchmark baseline，只保存拓扑规模、耗时、结果数、质量分和 parser，不记录路径或任意 payload。
- HTTP route family、walkthrough operations、Feign `REQUEST` 兼容和 metrics summary 修复一并纳入本版本。

### 内部架构收敛：walkthrough / HTTP / MCP / 检索 / indexer

这一批改动只涉及内部模块重组与回归保护，不改变任何 MCP tool schema、HTTP 路径、CLI 命令名或返回结构；既有 agent / hook / 前端调用方无需调整。

- Walkthrough 端到端组装收敛到 ``memory_center.core.walkthrough.runner.build_walkthrough_result``。``orchestrator.query.memory_method_walkthrough`` 现在只是一个 facade，提供 ``lookup_provider`` 与 ``escalation_runner`` 注入点；``cache key`` 也通过 ``runner.method_walkthrough_cache_key`` 暴露，便于直接测试。
- ``core/walkthrough/`` 按 ``symbols`` / ``continuations`` / ``risks`` / ``answer`` / ``escalation`` / ``runner`` / ``operations`` 拆分；health、quality、export 也已从 ``orchestrator.query`` 下沉，兼容 facade 只负责依赖注入。
- HTTP JSON 路由由 ``memory_center.http.route_dispatch.build_http_route_registry`` 组合 ``workspace`` / ``workflow`` / ``analysis`` 三个 route-family Module，并复用进程级 registry；请求级 ``RouteParams`` 在 dispatch 时传入，避免每请求重建全部 handler。``server._route_request`` 仅保留 ``/health`` 与未知路由错误。
- MCP ``mc_admin`` 的 81 项 action 抽到 ``memory_center.mcp.admin_actions.build_admin_registry``。``mcp/server.py`` 仅保留 FastMCP signature 与请求 adapter；``tests/test_mcp_admin_actions.py`` 直接通过 registry seam 验证 action 表。
- Hybrid retrieval fusion 默认纯函数化：``_merge_retrieval_results`` / ``_apply_type_boosting`` 不再修改 caller-owned ``RetrievalResult``（score / sources / evidence / node），新增 ``tests/test_hybrid_fusion_purity.py`` 5 项回归测试。
- Indexer Feign↔API 关联从 ``O(|feign_methods| × |apis|)`` 改为 ``O(|feign_methods|)``：``_build_api_lookup`` 按 ``(http_method, normalized_path)`` 桶索引，``_candidate_apis_for_feign_method`` 直接查表。Field 节点同时按 ``(class, field_name)`` 建立 ``field_locations_by_class`` 桶，避免 ``substring`` 过滤。``tests/test_indexer_perf.py`` 守住 ≥5× 速度比；``tests/test_benchmark_workspace_perf.py`` 用合成 8 服务 × 6 controller × 4 endpoint 的 Spring Cloud 形态 workspace 给 reindex / graph build / walkthrough / hybrid retrieval 加 wall-clock budget。
- 修复通用 ``@RequestMapping`` Feign 方法解析为 ``REQUEST`` 后无法匹配 GET/POST endpoint 的索引回归；通配桶现在按路径保留所有 HTTP 方法候选。
- 修复 ``mc_admin(action="metrics_summary")`` 未向 collector 传递指标名的问题；``name`` 现在作为 ``metric_name`` 使用，缺参仍返回结构化提示。
- 文档：``docs/ARCHITECTURE.md`` 同步 walkthrough / route_dispatch / admin_actions / hybrid purity / indexer lookup / benchmark 的拆分结构与 P2 守护条款；不再在 README / CHANGELOG 中记录这些公开 API 不变的内部 seam（变更仅作为内部参考保留在本节）。

### 3.1.15: Method Walkthrough / 方法级链路梳理

- 升级版本号到 `3.1.15`
- 新增 `memory_method_walkthrough()`，面向 `Class#method` 返回方法内已索引步骤、DTO 字段读取、Feign 续链、下游图谱摘要和后续动作。
- `mc_lookup(mode="walkthrough")` 与 `memory-center method-walkthrough` 可直接调用方法级 walkthrough。
- `mc_lookup(mode="auto")` 遇到 `Class#method` 且包含“全链路/到底层”语义时优先进入 walkthrough，减少 agent 退回手工 grep 的概率。
- `mc_admin(action="method_walkthrough")` 支持从管理路由触发同一能力。
- Feign 续链新增兼容字段 `server_walkthroughs`，会优先展开目标服务 endpoint 的 Controller 方法，并通过 `service_impl_continuations` 继续解析同项目 Service interface → Impl 的落点。
- compact walkthrough 改为优先保留关键方法调用和 Feign 调用，而不是按行号截断到 DTO 字段读取。
- 新增 `local_service_continuations`，用于展开当前方法内普通 Service interface → Impl 调用，减少 agent 退回手工读源码。
- walkthrough 的 target、matched endpoint、server walkthrough、local/server Impl 续链均新增 `absolute_file_path`，摘要行优先展示绝对路径，并提示无需再用 `find` 定位文件。
- walkthrough 新增 `agent_usage_policy`，明确 `absolute_file_path` 存在时不要再用 `find` / `grep -l` / `rg --files` / IDE 搜索定位同一 Controller 或 Impl。
- MCP `mc_lookup` 工具说明、cross-service prompt、默认 hooks 和 Cursor adapter 均同步 full-chain walkthrough 使用规则，减少宿主模型绕回搜索工具。
- 新增 `same_class_method_continuations`，运行时识别同类未限定方法调用（例如 `query2query(queryDto)`），并返回目标方法、绝对路径、局部步骤和 DTO 字段过滤摘要，减少 `sed -n` 切片追私有方法。
- `local_service_continuations` / 服务端 Impl 续链现在会继续展开内部 Feign 调用，便于直接看到 Impl 内的远程下游。
- `agent_usage_policy` 新增 `do_not_sed_when_continuation_present`，提示续链已存在时不要再用 `sed -n` 切源码片段。
- MCP `mc_lookup(auto|walkthrough)` 的 walkthrough 响应新增顶层 `answer`、`summary_lines`、`primary_flow`、`read_targets` 和 `agent_usage_policy`，避免宿主模型为了读取 `result.summary_lines` 再解析 tool-result JSON 文件。
- full-chain auto walkthrough 响应不再附带 `lookup_hint` / `candidate_paths` 大对象，减少输出体积和解析噪声；详细结构仍保留在 `result` 字段。
- 顶层 `read_targets` 只保留 walkthrough 摘要主线的 target / local impl / 首选 server controller / server impl / server impl same-class 方法；其他候选 endpoint 仅保留在 `result` 详情中。
- 新增 `workspace_escalation`：从子项目 workspace 调用 method walkthrough 时，会自动查找父级或 registry 中覆盖当前项目的聚合 workspace；若聚合 workspace 返回更完整跨服务链路，则自动切换。找不到父级或候选失败不会报错，保留当前 workspace 结果。
- 新增可配置报告模板：`.memory-center/templates/method_walkthrough.md` 或 `.memory-center/method_walkthrough_template.md` 存在时渲染 `answer_markdown`；未配置时使用内置兜底模板，agent 仍可基于顶层 `summary_lines` 自行组织。
- `same_class_method_continuations` 新增 `rule_groups` 与 `target.evidence_span`，用于把 `query2query` 这类大方法按业务规则分组并标出方法行范围。

### Packaging / 打包版本

- 升级版本号到 `3.1.5`
- 本地安装默认对齐当前仓库最新代码

### C-03: 查询意图识别与排序收敛

- `detect_query_intent()` 修复 Service/Feign 混淆：ontology 确认是 Feign 时降低 class 权重，endpoint 命名约定（Controller/Resource/Api）正确提升优先级
- `_JAVA_PATTERNS` 新增 method 模式（camelCase），`pattern.match` 改为 `pattern.search` 修复 endpoint 匹配
- `_apply_type_boosting()` 新增 contract 意图惩罚：feign/mq/endpoint 意图时对无关结构类型降权
- project filter 为空时返回一致的空结果

### C-04: Contracts 行为收口

- `_filter_contracts_by_query()` 输出新增 `_semantic_strength` 和 `_match_reason` 字段
- Feign → API 关联改用 `EntityValidator.validate_endpoint_path()` 验证路径特异性
- 关联结果标记 `_association` 和 `_association_confidence`

### C-07: Reasoning patterns 主链路化

- `memory_context()` 升级为统一 `run_reasoning_patterns()`，返回完整 `_reasoning` 字段
- `memory_impact()` not-found 分支也返回 `freshness` 和 `_reasoning`

### Retrieval、Incremental Indexing 与 Verification 修复

- reindex 自动重建 SQLite BM25，并在语义索引存在 dense vectors 时同步 VectorIndex
- 修复 BM25 命中未进入 hybrid fusion 的问题
- 修复 `enable_vector=False` 仍执行向量检索、`vector_weight` 未参与评分的问题
- vector 默认关闭，disabled / empty / unavailable / active 状态通过 diagnostics 明确可见
- 增量索引支持显式 workspace，并可从 repo root 或 graph db 路径推导 workspace
- 增量重建失败返回 `reindex_error`，不再静默伪装成功
- Verification Loop 全阶段完成后返回 `completed`，公开状态与完成度保持一致
- 修复重复测试类导致部分 E-07 测试未被收集的问题
- 全量验证：1292 collected，1277 passed，15 skipped

## 3.1.2

### 主链路一致性与 workspace 隔离 / Workflow Consistency and Workspace Isolation

- 升级版本号到 `3.1.2`
- 修复 `business-flow` / `business-flow-impact` 的 CLI、MCP、HTTP workspace 解析一致性，避免把 `workspace.yaml` 当 SQLite graph db 打开
- 修复 `memory_context` 风险分析调用不存在的 `RiskAnalyzer` 导致 `risk_patterns` 静默为空的问题，改为 `RiskPatternEngine` 并返回可见 diagnostics
- 修复 hybrid vector retrieval 的导入 / store 构造问题，并在返回中增加 `retrieval_diagnostics.vector`
- 修复 `regression-alerts` 三入口错误传入 `benchmark_name` 的问题，统一为 `threshold_pct`
- 增加 Next Phase 入口矩阵测试，覆盖 context-pack、freshness、onboard、business-flow、business-flow-impact、runtime-audit、regression-alerts
- 将统一错误模型接入真实 CLI、MCP、HTTP 入口，保持成功返回和 MCP tool schema 不变
- CLI 运行时错误现在输出安全的 `[error_type] message` 和建议动作，不再暴露 traceback
- 完成 Unified Backend 主读路径盘点，明确 `memory.db`、`graph.db`、文件事实源和 fallback 边界
- 调整测试用例，避免直接写入仓库内 `examples/spring-cloud-demo/.memory-center` 生成物
- 补充 workspace 隔离、三入口解析和后续维护要求的特殊说明

## 3.1.1

### 主链路收口 / Main Workflow Stabilization

- 升级版本号到 `3.1.1`
- 延续 v3.1 系列对 V3 / Next Phase 能力的产品化收口
- 重点面向 freshness、context、impact、business flow、retrieval、CLI / MCP / HTTP 一致性等主链路稳定性优化
- 保持 MCP facade schema 向后兼容

## 3.0.0

### NEXT_PHASE_MASTER_PLAN.md 全量实现 / Full Implementation

#### Phase A: Ontology 约束层 / Ontology Constraint Layer
- `hybrid_retrieve` 返回结果增加 `semantic_strength` (fact/inferred/derived) 和 `confidence_label` (high/medium/low)
- `_result_to_dict` 支持 dict 和 str 两种 evidence 格式的语义强度推断
- `_EDGE_SEMANTIC_STRENGTH` 映射从 `docs/ONTOLOGY.md` 定义的语义强度已接入检索结果

#### Phase B: 检索质量收口 / Retrieval Quality
- `detect_query_intent` 保持 Feign/MQ/Endpoint 的高优先级区分
- `hybrid_retrieve` 返回中增加 ontology-aware 语义强度字段
- evidence 解析支持字符串和字典两种格式，避免运行时类型错误

#### Phase C: Benchmark 趋势化 / Benchmark Trending
- `check_regression_alerts` 接入 MCP `mc_admin` (action: regression_alerts)
- `check_regression_alerts` 接入 CLI 命令 `regression-alerts`
- `check_regression_alerts` 接入 HTTP 路由 `/workspace/regression-alerts`

#### Phase D: Completion Audit 产品化 / Completion Audit
- `detect_workspace_type()` 已实现并可用于类型化审计规则

#### Phase E: Timeline/Ref/Task 体验增强
- drill-down 导航已接入 CLI / MCP / HTTP 三入口

#### Phase F: SQLite 主读路径
- `UnifiedBackendQuery` 统一后端查询已落地

#### Direction 1: Inverted Retrieval
- `InvertedIndex` 已实现并可用于稀疏检索

#### Direction 2: Graph Reasoning
- `reasoning/patterns.py`, `reasoning/transitive.py`, `reasoning/risk.py` 已实现

#### Direction 3: Indexer Upgrade
- `TreeSitterJavaParser` 已实现（CG-1），带 `RegexJavaParser` 回退
- tree-sitter 已接入 indexer.py 自动检测

#### Direction 4: Type Safety & Observability
- `MetricsCollector` 结构化指标收集器已实现（JSONL 后端，线程安全）
- `Explanation` schema 支持 persona 适配 (developer/architect/manager)

#### CG 外部思想吸收 / External Absorption (codegraph)
- **CG-1**: Tree-sitter Java Parser 已实现
- **CG-2**: `InvertedIndex` 倒排检索已实现
- **CG-3**: Freshness banner 已接入查询链路
- **CG-4**: `trigger_incremental_reindex` watcher-to-reindex 桥接已实现
- **CG-5**: `ContextPackBuilder` 已接入 MCP `mc_context_pack`
- **CG-6**: `benchmark_context_pack` 已实现
- **CG-7**: Workspace daemon 可行性研究（文件已存在）

#### UA 外部思想吸收 / External Absorption (Understand-Anything)
- **UA-1**: `ArchitectureTourGenerator` 已接入 MCP `mc_onboard`、CLI、HTTP
- **UA-2**: `Explanation` schema 已实现，支持 persona 适配
- **UA-3**: `BusinessFlowExtractor` + `BusinessFlowGraph` 已实现并接入 CLI/MCP/HTTP
- **UA-4**: `find_impact_along_flows` 流感知影响分析已实现
- **UA-5**: `adapt_for_persona` persona 视角输出已实现
- **UA-6**: freshness watcher 支持增量知识刷新

#### ECC 外部思想吸收 / External Absorption (ECC)
- **ECC-1**: `WorkflowProfile` 工作流协议档案已实现 (quick-fix/contract-change/long-task/architecture)
- **ECC-2**: `VerificationLoop` 验证闭环已实现 (analyze → checklist → verify → close)
- **ECC-3**: `PatternPromotion` 模式晋升管道已实现 (propose → promote → list)
- **ECC-4**: `HeuristicsRegister` 学习启发式注册已实现 (record → query → update_confidence)
- **ECC-5**: `audit_agent_runtime` Agent 运行时审计已实现
- **ECC-6**: `generate_agent_bundle` Agent 使用包导出已实现 (codex/claude/cursor)

#### MCP 新增 Actions
- `verification_loop`, `pattern_promotion_propose`, `pattern_promotion_list`, `pattern_promotion_promote`
- `heuristics_query`, `heuristics_record`, `workflow_profile`, `workflow_recommend`
- `bundle_export`, `runtime_audit`, `explanation`
- `business_flow`, `business_flow_impact`, `metrics_summary`, `regression_alerts`

#### CLI 新增命令
- `verification-loop`, `pattern-promotion`, `heuristics`, `workflow-profile`, `workflow-recommend`
- `bundle-export`, `runtime-audit`, `explanation`, `business-flow`, `business-flow-impact`
- `metrics-summary`, `regression-alerts`

#### HTTP 新增路由
- `/workspace/verification-loop`, `/workspace/pattern-promotion`, `/workspace/heuristics`
- `/workspace/workflow-profile`, `/workspace/workflow-recommend`, `/workspace/bundle-export`
- `/workspace/runtime-audit`, `/workspace/explanation`, `/workspace/business-flow`
- `/workspace/business-flow-impact`, `/workspace/metrics-summary`, `/workspace/regression-alerts`
- `/workspace/onboard`, `/workspace/context-pack`, `/workspace/freshness`
- `/workspace/group-status`, `/workspace/group-query`, `/workspace/group-impact`, `/workspace/group-chain`

#### Vue 前端新增页面
- `VerificationView.vue` — 验证闭环、工作流档案、运行时审计
- `FlowView.vue` — 业务流提取与影响分析
- `MetricsView.vue` — 结构化指标总览
- `OnboardView.vue` — 架构导览与新人入职

#### Bug 修复 / Bug Fixes
- 修复 `flow.py` 语法错误：合并重复的 `from __future__ import annotations`
- 修复 `_result_to_dict` 中 evidence 为字符串时的 AttributeError
- 修复 HTTP server 新路由中 `group_status` 等变量被局部 import 遮蔽导致的 UnboundLocalError

## 2.3.0

- **Vue 前端工作台**
  - 新增 `web/` 目录，Vue 3 + Vite + vue-router + axios
  - 覆盖 14 个页面：Workbench / Dashboard / Continuity / Task / Query / Impact / Group / Timeline / Receipts / Usage / Backend / Freshness / Audit / Health
  - HTTP 服务器自动在 `/app` 路径托管构建后的 Vue SPA
  - 开发模式支持热更新：`cd web && pnpm dev`
- **跨项目查询性能优化**
  - `group_status` / `group_query` 改为 `ThreadPoolExecutor` 并行执行
  - `resolve_group` 和 `_load_group_data` 增加 15 秒 TTL 缓存
  - 大幅减少多项目场景下的串行等待时间
- **跨项目链路可解释性增强**
  - `group_query` / `group_impact` / `group_chain` 返回中新增 `top_bridges`、`bridge_reasons`、`cross_workspace_path_hint`
  - 让用户和模型理解跨项目关联的原因
- **文档更新**
  - README.md 增加 Vue 前端安装和使用说明
  - ARCHITECTURE.md 增加 Vue 前端模块架构
  - NEXT_PHASE_MASTER_PLAN.md 标记已实现项

## 2.2.0

- **NEXT_PHASE 已实现能力完成收口**
  - 完成并接入主链路：hybrid retrieval、benchmark trending、unified backend query、drill-down navigation、completion audit
  - CLI / MCP / HTTP 入口同步可用
- **混合检索**
  - 新增 `memory_center/core/retrieval/hybrid.py`
  - 初始版本支持 graph + sparse + semantic 三路混合检索；当前版本已扩展为 graph / FTS / BM25 / semantic / optional vector
  - 增加查询意图自动检测与渐进式摘要输出
- **基准趋势**
  - 新增 `memory_center/core/benchmark/trending.py`
  - 支持 benchmark baseline、trend、回归检测和健康报告
- **统一后端查询**
  - 新增 `memory_center/core/backend/query.py`
  - 提供 `UnifiedBackendQuery`，统一索引、记录、引用和聚合查询
- **钻取导航**
  - 新增 `memory_center/core/navigation/drilldown.py`
  - 支持 `drill_timeline`、`drill_task`、`expand_ref`、handoff context 构建
- **完成审计**
  - 新增 `memory_center/core/audit/completion.py`
  - 支持文档、测试、实现、设计一致性检查与建议生成
- **文档结构继续收敛**
  - 删除阶段性文档 `docs/V3_PLAN.md`
  - 删除阶段性文档 `docs/NEXT_PHASE_IMPLEMENTATION_REPORT.md`
  - 删除单版本文档 `docs/CHANGELOG_v2.2.0.md`
  - 剩余计划统一并入 `docs/NEXT_PHASE_MASTER_PLAN.md`
- **本体与治理方向转入下一阶段**
  - 近期重点转为 ontology、检索质量继续收口、SQLite 主读路径推进、audit 产品化与 drill-down 体验增强

## 2.1.8

- **发布版本更新**
  - Python 包版本更新为 `2.1.8`

## 2.1.7

- **安装脚本默认目标修正**
  - 在本地仓库中执行 `bash install.sh` 时，默认安装当前 checkout，而不是回退到远端 GitHub 仓库
  - 仍然保留 `curl ... | bash` 场景下默认从 GitHub 安装的行为
  - 安装脚本会自动优先选择本机可用的 `python3.10+`，并按当前 package target 重新安装已有 `pipx` 环境
- **发布版本更新**
  - Python 包版本更新为 `2.1.7`

## 2.1.3

- **文档体系重构**
  - 补回根目录维护者文档：`TECHNICAL_GUIDE.md`、`NEXT_PHASE_MASTER_PLAN.md`
  - `README.md`、`docs/archive/ROADMAP.md`、`docs/RELEASE.md` 与技术/计划文档重新串联
  - 调整文档分层：对外使用线与对内维护线并存

## 2.1.2

- **文档结构收敛**
  - 主文档收敛为 7 份核心 docs
  - `README`、`ROADMAP`、`CHANGELOG` 的角色重新划分
  - 清理重复、阶段性和过细的旧文档入口

## 2.1.1

- **Hook 默认策略收口**
  - `user_prompt_submit` 默认禁用
  - Claude Code / Codex adapter 默认不再生成 `UserPromptSubmit`
  - 避免普通自然语言请求（如“继续”“下一步”“同步下文档”）被建议型 Hook 打断
- **Hook 配置行为修复**
  - `enabled: false` 现在会被 runner 和 adapters 一起真正视为禁用
  - `tool_matcher` 统一从 `filter.tool_matcher` 读取，配置语义与执行语义一致

## 2.1.0

- **agentmemory 风格 token benchmark**
  - 新增 `memory_eval_token_benchmark`
  - 覆盖 7 个高频函数：`sniff / status / resume / recent_evidence / continuity / dashboard / handoff`
  - 对 `small / medium / large` 三档预算输出按函数对比表和总 token 统计
- **Top-K evidence 策略**
  - `workspace_recent_evidence` 的 compact 模式采用显式 top-K
  - `small=3`、`medium=5`、`large=10`
  - 排序优先级为 `ref_id + summary + payload_ref/receipt_ref` 的信号丰富度，再按时间倒序
- **SQLite 后端读路径扩展**
  - `_resolve_memory_ref` 优先复用 backend 读取 session events / write receipts
  - timeline 和部分高频读路径进一步优先复用 SQLite backend

## 2.0.11

- **默认 compact 与短引用收口**
  - 全部 7 个高频大返回默认 `view=compact`
  - `workspace_recent_evidence` 补齐 `view=compact|full`
  - `memory_ref_get` 增加 `timeline_ref`
- **UI / workbench 增强**
  - dashboard / continuity 增加 `view / budget` 切换
  - `/ui/ref`、`/ui/timeline`、`/ui/task` 等页面钻取能力增强
  - guided tour、next action 卡片、cross-page links
- **Hook / adapter 增强**
  - Codex adapter 生成脚本可执行化
  - Cursor adapter 补充 MCP 命令与 quick reference

## 2.0.10

- `recent_evidence` 的 compact/full 与 gain 收口
- 短引用体系进一步补齐
- ref → timeline 反向导航落地

## 2.0.9

- Hook 资源模板与打包问题修复
- 默认 hooks 配置修正
- 核心数据处理与稳定性增强

## 2.0.5

- token gain 跟踪与评测
- Hook runner / adapters 基础能力
- 工作流编排评测与预算优化
- SQLite 优先读取开始接入更多路径

## 2.0.4

- 增量索引第一阶段
  - `--project`
  - `--path`
  - `--changed-only`
- `work-*` 一键工作流命令
- workbench / backend query 第一阶段

## 2.0.2

- regression suite
- compact / full
- budget
- short refs
- `memory_ref_get / batch`

## 2.0.0

- continuity / handoff / dashboard 主链路成型
- write receipt / write judge / write plan / write execute
- 多根目录 workspace 支持
- 工具使用报告与 lookup hint

## 1.3.0

- 共享工件与 sync sniff / sync case
- 自动同步模式
- 更完整的代码搜索、符号解析和调用链分析

## 1.0.0

- 项目正式命名为 **Memory Center / 记忆中心**
- Python 包统一为 `memory_center`
- CLI / MCP 命令统一为 `memory-center` / `memory-center-mcp`
- README 和公共文档体系初步建立

## 0.2.0

- Public GitHub-ready repository structure
- Apache-2.0 license, templates, basic docs, CI

## 0.1.0

- Initial MVP with workspace indexing, MCP tools, default rules and agent instructions
