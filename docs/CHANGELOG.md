# Changelog / 更新日志

本更新日志按**版本号**归纳，优先记录：

- 用户可感知的新能力
- 重要行为变化
- 明确修复的真实 bug

## Unreleased

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
  改为 `executemany` + `fast_write_mode` 包裹,大仓 reindex 预期可
  提速数倍(具体收益取决于文件数)。
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
- 新增长期演进计划 `docs/CBM_INSPIRED_EVOLUTION_PLAN.md`,记录 P0/P1/
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
- 下一步计划已更新到 `docs/NEXT_PHASE_EXECUTION_PLAN.md`：优先做 Ruff 现代化分层收口，其次处理剩余 bugbear 语义项，再继续输出体验、parser/retrieval/reasoning 精度深化。

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
  - `README.md`、`docs/ROADMAP.md`、`docs/RELEASE.md` 与技术/计划文档重新串联
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
