# Next Phase Master Plan / 下一阶段唯一开发路线

> 本文件是 Memory Center 当前唯一活跃开发路线。
>
> This is the single active development roadmap for Memory Center.

> **2026-10-09 分支路线调整**：`codex/service-platform` 的目标发行版正式确定为 **5.0.0**，主线是“独立服务 + 多 workspace + 管理页面”，依次实施 S0 服务骨架、S1 空间目录、S2 请求隔离、S3 后台任务、S4 管理页面、S5 接入与发行。详细流程、WeKnora 参考映射与全新安装验收见 [5.0 改造流程方案](V5_IMPLEMENTATION_PLAN.md)，技术合同见 [SERVICE_PLATFORM_TECHNICAL_PLAN.md](SERVICE_PLATFORM_TECHNICAL_PLAN.md)，产品决策见 [ADR-0004](adr/0004-service-platform-and-admin.md)。S0 已完成服务与打包验证（5.0.0a1），证据见 [S0 回执](implementation-receipts/V5_S0_SERVICE.md)；下一步为 S1 空间目录，等待用户确认，不自动进入。下文旧 P0 的“DSH 为主要展示入口”不再决定本开发分支的优先级；5.0 不维护旧 workspace、接口或 DSH 兼容层，Parser/Retrieval 等未完成事项在服务化基线稳定后重新排序。版本保留分支 `codex/release-4.6.30` 不受本分支路线调整影响。

> 文档入口与 active/historical 状态请同时参考 [DOCUMENT_CONSTITUTION.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCUMENT_CONSTITUTION.md)。

> **5.0 全新安装约束**：采用 FastAPI + Uvicorn、官方 Python MCP SDK、Vue 3 + TypeScript + Vite、SQLite 和有界进程 Worker。项目从源码目录重新登记、重建；不导入旧 workspace/registry/记忆，不维护旧 CLI/MCP/HTTP/DSH 兼容层。下文属于 4.x 的 additive schema、旧数据迁移与旧入口兼容要求不约束 5.0；核心准确性、证据治理、空间隔离与故障恢复要求继续有效。旧数据由用户自行清理，不自动删除。
>
> Also see [DOCUMENT_CONSTITUTION.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCUMENT_CONSTITUTION.md) for the current documentation entrypoints and active-vs-historical status.

---

## 1. 文档定位 / Scope

本文件整合并替代旧版执行计划、superpowers 演进计划和旧版 master plan；这些历史来源已合并入本文档，不再作为独立活跃文档维护。

This file consolidates and replaces the older execution plan, superpowers evolution plans, and the previous master plan. Those historical sources have been folded into this document and are no longer maintained as separate files.

旧计划中的已完成任务不再作为待办重复跟踪；未完成方向按当前代码和 benchmark 重新排序。

如果要看当前系统怎么用，优先读：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [docs/references/codebase-memory-mcp.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/references/codebase-memory-mcp.md)

---

## 2. 当前判断 / Current Assessment

### 4.6.12 reconciliation / 4.6.12 现状收敛

下列能力已完成并移入 CHANGELOG、决策与验证回执，不再作为本计划待办：Java IR 差分门禁、generation-local staging、跨服务 `primary_chain`、MQ `insufficient_evidence` 边界、真实 retrieval replay、局部刷新分桶预算、SQLite-first 索引镜像收敛、只读 `quality-gate`、`change_review.validation_plan` 与 Workbench 质量总览。

The following capabilities are complete and are tracked in the changelog, decisions, and receipts rather than as roadmap work: Java IR differential gating, generation-local staging, cross-service `primary_chain`, the MQ `insufficient_evidence` boundary, real retrieval replay, bucketed refresh budgets, SQLite-first index mirror convergence, the read-only `quality-gate`, `change_review.validation_plan`, and the Workbench quality overview.

当前重点不再是“补一个新工具”，而是把已有能力收敛成更快、更准、更少误导 Agent 的主链路。

当前未完成方向：

1. **真实任务质量运营**：积累经过人工验证的任务回放，仅依据确认结果优化检索策略与下一步建议。
2. **Java 解析与调用解析精度**：仅在新的私有失败 case 满足可证明性门禁时修复；外部泛型、动态、多态和配置中心缺失映射保持 `UNKNOWN/AMBIGUOUS`。
3. **真实性能与重建可靠性**：持续积累真实工作空间的冷/热查询与分桶增量刷新样本。只有同一 bucket 至少 5 个真实样本且 P95 超预算，才优化可定位的 dominant stage。
4. **证据优先的需求交付闭环**：将已有任务、索引、治理和验证能力收敛为可拆解、可定位、可验证、可恢复的需求交付状态机；Skill 契约与脱敏 replay 已完成，后续只用真实回放校准推荐质量。

已完成的外部协同基线：受限 MCP Client Bridge 已可直接调用策略白名单中的 HTTP MCP；声明 `code_navigation` 的只读工具已接入 Provider 健康路由；跨 Provider EvidenceRef 已可对显式结构化 Claim 返回一致、冲突或证据不足，并在冲突时生成验证 Action。后续只依据真实 replay 校准可信排序，不把外部正文写入长期层。

---

## 3. 开发优先级 / Development Priorities

> 已交付内容（4.3.77 图感知审查、4.3.81-4.3.84 Java 解析与性能闭环、ADR-0002 内部重构）详见 CHANGELOG。

### P0：DSH Memory Center Workbench / DSH 记忆中心工作台

目标：将 DSH Web 定位为单个 Memory Center workspace 的主力**展示与操作入口**，而不是仅显示 DSH 本次会话的模型、工具和 Token 统计。现有“执行观测”保留为会话级子页；新的工作台优先展示已有 Memory Center 的项目、任务、记忆和质量读模型。

实现状态：P0-0 至 P0-4 的代码与本地 smoke 已完成；尚待真实私有 workspace 覆盖空 workspace、无焦点任务、blocked task、stale 索引和可恢复任务五类验收后，才能从主计划移入 CHANGELOG。

这是一项产品呈现与集成收敛工作，**不新建第二套图谱、任务、Case 或评测真源**。Memory Center core 继续拥有查询、影响分析、治理和持久化语义；DSH 插件只负责工作区自动发现、本地只读访问、渲染和有限的显式跳转/操作入口。

#### P0-0：访问边界与数据合同（先做）

1. 固定 DSH 插件的 workspace 发现规则：优先 session cwd 向上寻找 `.memory-center/workspace.yaml`，显式 `MEMORY_CENTER_WORKSPACE` 仅作为覆盖；未发现 workspace 时显示空态，不影响 DSH。
2. 为插件定义单一只读数据边界：浏览器端只访问 DSH 同源的 host bridge；host bridge 再调用 Memory Center 已有 `workspace_dashboard`、`workspace_continuity_dashboard`、`workspace_status`、`workspace_recent_sessions`、`workspace_session_summary`、`impact` 等 core/HTTP facade。浏览器不得读取 SQLite、JSONL 或 `.memory-center` 文件。
3. DSH host 负责按需启动、复用和停止该本地只读查询通道；用户启动 DSH 后不需要再手工运行 `memory-center serve-http`。通道只绑定 loopback、按 workspace 隔离，并随 DSH plugin 生命周期清理；Memory Center 不启动 DSH 时仍可独立通过 CLI、MCP、HTTP 使用。
4. bridge 必须使用短 TTL 缓存、fail-open；缺少 `memory-center` 命令、工作区未初始化、索引 stale 或读取失败时返回结构化状态与下一步，而不是让 DSH 页面白屏或阻断 Agent。
5. 统一 DSH 插件与 Memory Center 的隐私投影：默认不向浏览器返回 prompt、消息正文、工具参数/结果、完整源码、私有绝对路径或原始 session payload。详情页只按现有 evidence/ref 的有界摘要与授权规则展开。
6. 同步修正 `docs/DSH_LOCAL_TELEMETRY.md` 与插件实际行为的陈旧描述，尤其是“安装即启用、自动导入、无 OFF/METADATA 开关”的当前语义。

验收：一个真实私有 workspace 中，启动 DSH 后无需额外填写 workspace 路径或启动 Memory Center HTTP 服务即可取得只读工作台数据；缺少 workspace 或 bridge 失败时，DSH 原对话和执行观测均保持可用；关闭 DSH 不影响独立运行的 Memory Center。

#### P0-1：工作台首页（当前最合适的第一个实现）

新增 DSH 会话视图 `Memory Center`，默认落在“工作台”页，使用 `workspace_dashboard(view="compact")` 与 `workspace_status(view="compact")` 的既有投影。首版只放能指导下一步工作的信息：

- 当前焦点任务：状态、优先级、可恢复性、最近更新时间；
- 下一步行动与未解决项：最多 3–5 条，保留来源/状态而非展示正文；
- 活跃、阻塞和低质量任务概览；
- 最近回执、交接与证据摘要；
- 索引新鲜度与可解释的 health 状态；
- 一条明确的“下一步建议”，例如恢复任务、定向刷新或执行影响分析。

不要在首页展示大图、全量时间线、所有 Case 或纯装饰性指标；首页的判断标准是“打开后能知道接下来该做什么”。

验收：工作台在空 workspace、无焦点任务、存在 blocked task、索引 stale、存在可恢复任务五类状态下都有明确空态/风险态/下一步；不复制 `workspace_dashboard` 的决策逻辑。

#### P0-2：任务连续性页

新增“任务”页，复用 `workspace_continuity_dashboard` 与 `task_resume_check`：展示当前任务的 resume packet、下一步、未解决项、最近回执、交接和有限 recent evidence。支持从工作台选择其他 active task，但不在浏览器中直接编辑任务工件。

验收：用户从 DSH 切回一个中断任务时，可在一屏内区分“可直接继续 / 需要修复 / 被阻断”，并能定位到最小下一动作；大 payload 仍保持在 Memory Center 的渐进披露与 budget 约束内。

#### P0-3：影响分析与记忆浏览（工作台稳定后）

1. 新增“影响”页：输入一个明确 target（类、接口、Feign、MQ、配置键），调用既有 `mc_analyze` / impact facade，按 confirmed / probable / possible / unknown risks 分层展示；证据图采用 focus + 节点详情的交互，只使用已有的有界 subgraph/export 结果，并明确区分 EXTRACTED 与 INFERRED，不能把可达关系表述为运行时影响。
2. 新增“记忆”页：浏览最近 Case、待审批 consolidation candidate、决策与来源摘要；审批、写入和 Case 生命周期仍走 Memory Center 已有显式命令/API，前端不绕过人工门禁。
3. 新增“质量”页：索引新鲜度、resume/retrieval/guidance 的已有评测摘要。没有真实 case 的指标必须显示 `real_case_missing`，不得用样例伪装质量结论。

验收：影响页不因模糊输入触发无界全局搜索；记忆页不直接自动 approve / merge / supersede；质量页不把缺样本解释为通过。

#### P0-4：会话执行观测的定位

保留当前“执行观测”页作为 **DSH 当前会话** 的诊断面板，仅负责模型、工具、耗时、Token、失败和本地脱敏事件。它不承担项目记忆、跨任务恢复或跨 Agent 总览职责；工作台可链接到它，但不把两类数据混为同一口径。

验收：页面显式标记数据范围（`当前 DSH 会话` 或 `当前 Memory Center workspace`）和采集覆盖度，避免将局部 DSH 数据误读为项目全量数据。

#### P0 非目标与后续门槛

- 本阶段不采集或展示 Codex、Claude Code、Cursor 等外部 Agent 的执行轨迹；它们是后续“跨 Agent 活动适配器”专题，不能通过解析私有日志临时接入。
- 本阶段不把 DSH 变成 Memory Center 的第二个后端，不复制索引、SQLite、JSONL、Case 决策或任务状态机。
- 本阶段不默认展示 prompt、正文、工具参数、工具结果、源码全文或完整 session payload。
- 只有 P0-1 / P0-2 在真实 workspace 中稳定使用后，才评估 P0-3；只有存在稳定、公开、可脱敏的事件入口后，才设计外部 Agent adapter。

#### P0 测试与发布要求

- 插件单元测试：workspace 自动发现、bridge 正常/缺失/超时、脱敏字段、空态与错误态、视图 tab 注册；
- Memory Center 测试：既有 dashboard/continuity/impact 的 HTTP 或 core 输出兼容性不退化；
- DSH smoke：独立插件安装、Web 启动清单含浏览器模块、无 workspace 的 DSH 会话仍正常；
- 真实私有 workspace：验证焦点任务、blocked task、stale 索引和恢复任务至少各一例；不提交生成的 `.memory-center` 内容、私有路径或原始 payload；
- 每个切片完成后更新插件使用说明与 CHANGELOG；若涉及公开 Memory Center CLI/HTTP/MCP schema，再按文档宪章同步 README、ARCHITECTURE、MCP_GUIDE、REFERENCE。

### P1：Java Parser / Call Resolver 真实精度深化

目标：让 method walkthrough 和跨项目链路在真实 Spring Cloud 场景下更稳。

任务：

1. 先运行 `eval-java-call-resolution-unresolved`；报告会把静态类/外部依赖、基础继承方法与实例接收者缺少类型分开，不能把外部 API 或 `Object` 基础方法误当作本地解析缺陷。
2. 从剩余 `receiver_type_missing` 中选择下一类最高频且可复现缺口，补充 3-5 个只含逻辑锚点的私有 case；不要重复处理已完成的重载作用域、显式/函数接口 Lambda 和 JDK 集合泛型问题。
3. 每次仅修复一个明确的 parser 或 resolver 缺口，不以宽泛 fallback 换取表面召回率。
4. 将每个误判转成可复跑 case，并在 CLI、MCP、HTTP 中保留失败原因和缺失锚点。`expected_resolution_levels` 必须作为门禁条件；用聚合 metrics 观察解析等级与链式边变化，用私有 case 判定正确/错误边。

验收：

- 新增 case 不得降低既有真实 case 的 anchor recall、edge recall 或 forbidden hit 指标。
- 每个失败 case 都能定位到 parser、resolver、graph 或 retrieval 中的具体一层。

已交付（Lombok @Builder 轮次）：

- 真实 ucap 工作空间 unresolved 分析确认本地可证明缺口为 Lombok `@Builder` 静态工厂与链式 setter（736 + 350 未解析调用）；外部依赖类（external_or_missing_source 176k）按 campaign 契约不作为 resolver 修复目标。
- resolver 新增 `*_lombok_builder`（0.85）、`chain_lombok_builder_setter`（0.78）、`chain_lombok_builder_build`（0.80）三个解析级别；未解析率 52.26% → 48.34%，`missing_method_or_polymorphism` 10,671 → 2,768。
- 私有锚点 case（v4390，3 个）门禁 3/3 通过；下一轮候选缺口：`receiver_type_missing`（5,655，多为 lambda 参数与 `@Slf4j log`）与 `chain_return_type_not_indexed`（5,572）。

### P2：Retrieval / Reasoning 质量闭环

目标：让 `mc_lookup(auto)`、walkthrough、impact、context pack 在真实任务中更少误判、更少重复搜索。

任务：

1. 用真实 session replay 验证 adaptive retrieval policy，不再用 examples 作为主要验收；每个版本至少比较 adoption、bypass、unobservable 和 Golden 指标。
2. 对每个 replay 记录人工确认的命中/偏题结果；只将确认结果写入 retrieval-source feedback。
3. 每次权重变更后运行 Golden、replay trend、cold/hot query baseline；任一质量门禁退化即回滚。

验收：

- 完整链路 case 不再建议重复全局搜索
- partial / stale case 明确指出缺失层或 stale 文件
- same input 产生确定性 retrieval policy
- token 和 latency 不低于真实基线

已交付（replay 校准轮次）：

- 修复 agent guidance replay 匹配器（`inspect_*` 动作分支 + `mc_*` CLI 别名），真实 ucap 数据 adoption 0.0 → 0.947；剩余 missed 均为真实 `guidance_missing_target_hint` 缺口。
- replay trend 已用真实数据记录趋势点；campaign 覆盖缺口（walkthrough/impact/config intent）需真实任务 session 补齐，属数据采集而非代码缺口。
- `eval-retrieval-replay` 校准在无带证据人工验证记录时正确返回 `insufficient_replay`，不产生无证据权重变更。
- 向量检索默认开启评估完成：ucap 真实链路（49,897 dense embeddings + hnswlib ANN，self_recall 1.0）对比显示 vector-on 使 MQ 契约查询 anchor recall 1.0 → 0.0（泛化匹配稀释契约锚点）；决策维持 `enable_vector=False` 默认，默认开启前置条件为融合权重校准后契约锚点不掉出 top-N。

### P3：证据优先的需求交付闭环 / Evidence-First Delivery Loop

目标：把 Memory Center 从“提供分析与任务组件”收敛为 Agent 可默认遵循的需求交付流程。每个阶段都必须有结构化输入、可审查产物、可执行门禁和可追溯证据；不能以模型自报“已完成”代替验证。

现有基础：任务空间已具备 `requirements.json`、`subtasks.json`、`acceptance.json`、验证回执、阶段流转和交付 Skill 候选；本体已具备 `Policy`、`Constraint`、`GateResult`、`Waiver`、`Validation`、`Action`；索引已具备定向刷新、freshness 和图谱定位。P3 只补齐编排与约束，不重建这些领域能力。

#### P3-1：确定性需求拆解契约

1. 将需求项扩展为可追溯结构：`source_refs`、`scope`、`out_of_scope`、`evidence_refs`、`search_terms`、`candidate_modules`、`acceptance_ids`、`ambiguities` 与 `decision_required`。
2. 提供需求拆解服务：输入可引用的需求材料或人工摘要，输出候选需求项和缺失项；范围、归属、重复、未覆盖验收项由确定性规则检查，LLM 只负责语义解释和候选补充。
3. 将“联想用于搜索、引用用于决策”固化为规则：搜索词可扩展，但会影响实现范围的条目必须带来源引用；没有证据时只能标记 `AMBIGUOUS` 或 `UNKNOWN`，不得自动进入实现。
4. 为每个需求项建立 `Requirement -> Subtask -> CodeTarget -> Acceptance` 链接，定位阶段只能使用已索引目标；索引 stale 时先排队定向刷新并向用户说明使用的 generation。

验收：需求项可回溯来源和范围；未关联验收、未定位代码目标、存在未决歧义时不能进入相应后续阶段；CLI、MCP、HTTP、Workbench 返回同一交付状态与下一步 Action。

#### P3-2：策略化门禁与真实验证回执

1. 复用统一本体中的 `Policy`、`Constraint`、`GateResult`、`Waiver` 和 `Validation`，为 intake、breakdown、locate、implement、verify、close 定义版本化门禁；禁止再建一套未关联治理读模型的红线 YAML。
2. 增加受 workspace policy 限制的验证执行适配器：仅允许运行预注册命令/profile，记录命令 ID、参数摘要、超时、退出码、受限输出摘要、产物路径及 hash；不执行来自需求正文、模型输出或外部材料的任意 shell 字符串。
3. 支持外部验证回执，但必须标记 `recorded_external` 并提供脱敏证据引用；只有执行器产物、人工确认或可追溯运行时证据才能将断言提升为 `VERIFIED`。
4. 失败按“可自动修复、配置/环境阻塞、需求/路径错误、人工决策”分类；每类给出停止条件，重试上限由 policy 配置，不能在失败状态无限循环。

验收：任务关闭的每项必需验收都能追溯到有效验证证据；伪造 `passed`、越权命令、缺失豁免或超过重试上限必须阻断门禁；所有阻断都返回可行动的下一步，而不是笼统错误。

#### P3-3：交付矩阵、恢复说明与已验证 Skill 提炼

1. 从既有 JSON 工件和时间线派生 `delivery-matrix.json` 与可读的 `TECH_SPEC.md`，作为只读投影，不引入第二套真源。矩阵展示需求、范围、代码目标、验收、验证、决策、豁免、当前阶段和缺口。
2. `task_resume_check` 直接消费该投影，优先展示未决歧义、失败验证、stale 目标和下一条最小 Action；长任务归档继续使用有界摘要与压缩归档，不恢复巨型原始上下文。
3. 仅从已关闭、验收完整、验证通过且不存在未决豁免的任务生成交付 Skill 候选。候选内容只提炼结构化经验、逻辑锚点和安全验证步骤，不包含私有源码、原始需求正文或工具载荷。
4. 增加任务级效果度量：需求覆盖率、定位覆盖率、验收覆盖率、验证成功率、人工阻断率、阶段耗时、Agent 建议采纳/绕过率；真实 replay 充足前只观测，不自动调权。

验收：新会话可以通过一份有界恢复包理解任务边界、证据和未完成事项；Skill 只能由已验证交付生成；任务级质量指标不读取或保存原始私有正文。

#### P3 性能、迁移与测试约束

- 需求拆解、阶段状态和门禁判断必须使用有界 JSON、索引和派生视图，禁止在 MCP/HTTP 热路径全量扫描 workspace、重建图或加载完整需求附件。
- 只有显式维护动作可以执行验证、刷新索引或提炼 Skill；普通查询只返回已发布 generation 和排队状态。任何新增默认读取的 P95 延迟不得超过当前同类入口真实基线的 10%。
- 新字段只做 additive 扩展；已有任务空间采用惰性创建和只读投影。旧的人工回执继续可读，但必须显式标为外部记录，不能被误认为执行器证据。
- 新增单元与系统测试覆盖：需求范围/歧义、需求到验收完整性、policy/waiver、命令白名单与超时、失败分类/停止条件、矩阵投影、Skill 提炼资格、CLI/MCP/HTTP/Workbench 一致性及真实 workspace 指标格式。

非目标：不将移动端设计稿、Figma、模拟器、Bazel 或任何单一技术栈规则放入核心；不强制所有任务使用交付流程；不让 Agent 自动执行不可逆操作、下载模型或全量重建索引。

### 外部方案参考边界

- 所有吸收项必须先经过真实工作空间基准和兼容性验证，再进入默认行为或发布门禁。
- Archify（tt-a1i/archify v2.15）深度调研已完成，见 `docs/ARCHIFY_ABSORPTION_RESEARCH.md`。生成式 Wiki 方案已整体移除，不再吸收其原子发布候选；仅保留“失败分类附加 code / subject / evidence / supported_fixes 与轮次停止条件”这一证据触发候选。初版的 delta 回执（无消费方，同 ADR-0003 教训）与 commit SHA 钉住（freshness 的 content_hash 已覆盖且更精确）也已撤下。
- AI 记忆项目全景调研已完成，见 `docs/MEMORY_LANDSCAPE_RESEARCH.md`。结论是不新增 P0 项：会话→知识候选整合已落地为 P1 人工切片（stage → 逐条 approve|reject → L1），当前只支持 ADD/REVIEW；`UPDATE / SUPERSEDE / NOOP` 仍须 stable case ID、旧 case 状态回写和真实数据验证。跨会话召回已落地为 P2 只读评测切片（`eval-session-recall`），在多轮真实 case 稳定复现前不改变默认检索；历史图 / as-of impact 与 Skill 装载量化仍为 P2 观察项。Graphiti 式时间语义必须同时具备历史来源与可复放 case，不能只给现有图边加时间字段；Mem0 当前 ADD-only 路径不作为操作算子依据。

---

## 4. 执行原则 / Execution Rules

这些原则从旧版执行计划合并而来，后续不再单独维护执行计划文档。

1. 功能真实可用、用户实际好用优先于遵守旧模块边界和旧任务顺序。
2. 可以重排阶段、合并任务、替换旧实现和重构核心模块。
3. 每项完成的能力应有测试、入口验证和文档同步。
4. CLI / MCP / HTTP 可以针对入口场景优化，但核心语义、结果结构和错误语义必须可解释。
5. 任何主链路 `except Exception` 都不能静默吞掉真实失败，必须返回 diagnostics、fallback reason 或明确降级说明。
6. 新入口必须优先复用 core 层能力，不在 CLI / MCP / HTTP 三处复制决策逻辑。
7. 输入 workspace 时，公共入口默认接收 `workspace.yaml` 或目录，再通过 `WorkspaceStore` 解析 graph / memory / artifact 路径。
8. 测试不得直接写入仓库内 `examples/*/.memory-center` 的运行态 graph / memory 生成物；需要写入时复制到 `tmp_path`。
9. 公开 examples 只做 smoke / fixture，真实完成判断必须优先使用用户提供的真实场景。
10. 不提交私有 workspace 的 `.memory-center/index`、`.memory-center/memory`、私有 cases、私有 baseline、完整 payload、真实路径、内部服务名或密钥。

### 三入口一致性 / CLI MCP HTTP Consistency

下列能力继续保持三入口一致性测试和文档同步：

- `context-pack`
- `freshness`
- `onboard`
- `domain`
- `business-flow`
- `business-flow-impact`
- `runtime-audit`
- `regression-alerts`
- `eval-golden`
- `eval-java-call-resolution`
- `change-review`
- `eval-cochange`
- `architecture-communities`

验收要求：

- 同一 workspace / query / seed 在 CLI、MCP、HTTP 中返回核心字段一致。
- 错误使用统一错误模型：`invalid_input`、`not_found`、`unavailable`、`conflict`、`internal_error`。
- MCP schema 只能 additive 兼容扩展，不能破坏既有 tool 参数。

### Ruff 与代码治理 / Ruff and Code Governance

当前 Ruff 方向不再作为主路线最高优先级，但保留为持续治理要求：

- 基础门禁 `F/E9/I001/B006/B008/B904` 必须持续通过。
- `UP035 / UP006 / UP045 / UP007` 等现代化项按目录小批量处理，避免大 churn。
- `B007`、`B905` 这类语义项必须手工判断，不能机械改 `_` 或盲目加 `strict=True`。
- Ruff 清理不能替代真实场景 gate；它只证明代码卫生，不证明用户体验完成。

### 开放方向 / Open Directions

以下方向不再视为禁区。只要能明显改善真实用户问题，可以直接调研、原型验证并实施：

1. 重写 indexer，提高索引精度、增量性能和语言扩展能力。
2. 引入可选图数据库、向量数据库或搜索后端。
3. 重新设计 JSONL、SQLite、graph 和 memory 存储结构，并提供迁移工具。
4. 增加 daemon、后台任务、自动监听和持续索引能力。
5. 重做前端、可视化、配置流程和排障体验。
6. 合并或删除重复入口，重新设计 MCP、CLI、HTTP 的产品交互。
7. 引入新的语言支持、框架适配器、评测系统和 Agent 工作流。

实施前至少回答：

- 解决了哪个真实用户问题。
- 相比当前实现，体验、准确率、性能或维护性提升在哪里。
- 最小可用版本如何验证。
- 数据迁移、兼容和回滚如何处理。
- 后续维护成本是否可接受。

注意：开放方向不依赖外部项目清单驱动；后续立项必须来自真实使用问题、benchmark、gate 或当前架构缺口。

---

## 5. 统一验收门禁 / Unified Gates

后续任何“完成”判断必须优先使用真实场景：

- 默认真实 workspace 使用本地私有 `workspace.yaml`，文档只写 `<private-real-workspace>` 占位。
- 公开 examples 只作为 CI smoke test、单元测试 fixture、公开复现模板。
- 若真实 cases 缺失，结果必须标记为 `real_case_missing`，不能用 examples 指标替代真实验收。
- 若性能 baseline 缺失，可以用当前已验收版本生成新基线；后续版本只能更好，不能比基线差。

最低检查：

```bash
python3 -m compileall -q memory_center tests
git diff --check
pytest -q
scripts/verify_real_ucap.sh
```

真实场景 gate 最少包含：

- Golden anchor recall
- Golden edge recall
- forbidden hit rate
- Java call resolution recall
- walkthrough invalid search suggestion count
- median / p95 latency
- token estimate
- parser diagnostics
- completion status

---

## 6. 非目标 / Non-Goals

- 不删除 regex parser；它仍作为 fallback 和 differential oracle。
- 不默认开启 vector retrieval；真实质量和性能基准稳定后再讨论默认策略。
- 不一次性把 JSON / JSONL / Markdown 事实源迁移到 SQLite。
- 不新增平行 MCP facade tool；优先扩展现有 `mc_lookup`、`mc_analyze`、`mc_admin`。
- 不为了类型化破坏现有 dict 返回和 MCP tool schema。
- 不把私有 workspace 生成物、源码片段、真实路径或密钥写进仓库文档。

---

## 7. 下一步路线图 / Next-Step Roadmap

路线图按真实收益和前置关系排序，不按功能数量排序。一个阶段只有在完成条件满足后才进入下一阶段；失败、数据不足或性能退化时回到上一阶段校准，而不是继续堆叠能力。

### 阶段 1：Java 调用解析真实精度（4.3.78 第一轮已交付）

目标：降低真实 Spring Cloud 链路中的本地漏连和误连，而不是提高外部依赖的表面“解析率”。

1. 每次运行 `eval-java-call-resolution-unresolved`，排除 `external_or_missing_source`、JDK 基础方法和动态调用。
2. 从 `target_method_not_indexed` 与 `receiver_type_missing` 中选择一个可证明的规则缺口，补 3 至 5 个逻辑锚点 case 后再改 resolver 或 parser。
3. 优先修复 Lombok、唯一继承、接口单实现、局部变量和注入字段类型；多实现、反射、外部类型继续保留未解析并返回原因。
4. 每项修复同时检查 anchor recall、edge recall、forbidden hit 和局部 reindex 耗时。

完成条件：新规则在真实分类中减少目标类别，且不降低已有真实 case 的 precision；无法证明唯一目标时绝不生成本地调用边。

暂停条件：若收益只来自把外部类型伪装成工作区类型，立即回退该规则。

### 阶段 2：性能与存储运行治理（并行观测，不主动大改）

目标：保持当前“按需刷新、SQLite 单副本、倒排加 ANN”的架构在真实工作空间稳定可用。

1. 定期记录冷/热查询 P50/P95、局部 refresh、完整 reindex、FTS 同步和 vector ANN 状态。
2. 跟踪 `graph.db`、generation、HNSW 和任务工件空间；只通过 `generation-gc`、`semantic-index-compact`、`storage-vacuum` 等显式维护动作回收空间。
3. 对超过预算的阶段先做 profile，再针对最高耗时 SQL、解析或编码步骤优化；禁止将全量扫描放回 MCP 查询热路径。

完成条件：每次性能改动均有真实工作空间前后指标；默认查询 P95、局部刷新和完整重建持续满足既有发布预算。

暂停条件：没有真实基线时只采集，不依据合成 benchmark 宣称性能提升。

### 阶段 3：证据优先交付闭环收口

目标：使一次需求从范围、定位、实现、验证到恢复都可审查，且 Agent 不会把自评当成完成。

1. 以现有 `Requirement -> Subtask -> CodeTarget -> Acceptance -> Validation` 为唯一交付主线，补齐真实任务中暴露的缺口。
2. 定位阶段直接使用已发布索引、图证据和有界检索结果，避免引入第二套项目地图或语义桥真源。
3. 将通过校准的 `skill-up` 结果作为外部评测证据接入 canary 观测，但仍要求现有人工或执行器证据门禁。
4. 用真实关闭任务衡量范围覆盖、验收覆盖、验证成功率、阻断率、阶段时延与建议绕过率；样本不足时只观测不自动调权。

完成条件：新会话能从有界恢复包得到目标、证据、未决项和最小下一步；任何关闭结论都可回溯到验证证据。

### 阶段 4：按数据决定的扩展

只有阶段 0 至 3 的数据证明当前架构存在明确瓶颈，才评估新语言、图数据库、向量后端、可视化或新的 Agent 工作流。每个候选必须先给出真实问题、最小原型、性能/准确率对比、迁移与回滚方案；未通过 gate 的实验不进入默认路径。

### 当前建议 / Current Recommendation

当前版本为 **4.6.12**。优先继续真实使用观察：积累 retrieval replay 与 refresh bucket 样本，运行只读 `quality-gate`，只在其返回的可证明问题达到门槛后修改 planner、索引或存储。服务分片物理复制与 `generation_publish` 是已知的长期候选，但在单机样本未达到分桶 P95 门槛前不得提前重构。
