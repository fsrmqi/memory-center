# Changelog / 更新日志

本更新日志按**版本号**归纳，优先记录：

- 用户可感知的新能力
- 重要行为变化
- 明确修复的真实 bug

## Unreleased

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
