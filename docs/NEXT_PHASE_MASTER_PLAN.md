# Next Phase Master Plan / 下一阶段唯一开发路线

> 本文件是 Memory Center 当前唯一活跃开发路线。
>
> This is the single active development roadmap for Memory Center.

> 文档入口与 active/historical 状态请同时参考 [DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md)。
>
> Also see [DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md) for the current documentation entrypoints and active-vs-historical status.

---

## 1. 文档定位 / Scope

本文件整合并替代旧版执行计划、superpowers 演进计划和旧版 master plan；这些历史来源已归档到 `docs/archive/`，不再作为独立活跃文档维护。

This file consolidates and replaces the older execution plan, superpowers evolution plans, and the previous master plan. Those historical sources have been folded into this document and are no longer maintained as separate files.

旧计划中的已完成任务不再作为待办重复跟踪；未完成方向按当前代码和 benchmark 重新排序。

如果要看当前系统怎么用，优先读：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [docs/TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_GUIDE.md)
- [docs/references/codebase-memory-mcp.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/references/codebase-memory-mcp.md)

---

## 2. 当前判断 / Current Assessment

当前重点不再是“补一个新工具”，而是把已有能力收敛成更快、更准、更少误导 Agent 的主链路。

当前未完成方向：

1. **真实任务质量运营**：积累经过人工验证的任务回放，仅依据确认结果优化检索策略与下一步建议。
2. **Java 解析与调用解析精度**：从真实未解析分类中补充逻辑锚点样例，只修复可复现的具体误判。
3. **真实性能与重建可靠性**：持续积累真实工作空间的冷/热查询、增量索引和并发重建数据，使用基准决定优化优先级。查询必须输出阶段耗时，并受热查询 P95 预算保护；只在确认的最高耗时阶段优化。
4. **证据优先的需求交付闭环**：将已有任务、索引、治理和验证能力收敛为可拆解、可定位、可验证、可恢复的需求交付状态机；Skill 契约与脱敏 replay 已完成，后续只用真实回放校准推荐质量。

已完成的外部协同基线：受限 MCP Client Bridge 已可直接调用策略白名单中的 HTTP MCP；声明 `code_navigation` 的只读工具已接入 Provider 健康路由；跨 Provider EvidenceRef 已可对显式结构化 Claim 返回一致、冲突或证据不足，并在冲突时生成验证 Action。后续只依据真实 replay 校准可信排序，不把外部正文写入长期层。

---

## 3. 开发优先级 / Development Priorities

### 已交付基线：图感知变更审查与实证评测（4.3.77）

4.3.77 已完成加权最佳路径、统一 Change Review Plan、渐进上下文与调用预算、离线架构健康算法、Git co-change 独立评测及发布门禁。实现复用现有 `graph.db`、generation、EvidenceRef 和 Action，不建立第二套长期图存储；高成本社区与中心性算法仅显式离线执行。该工作包不再列入后续待办，使用与算法边界见架构、MCP、参考文档及更新日志。

### P1：Java Parser / Call Resolver 真实精度深化

目标：让 method walkthrough 和跨项目链路在真实 Spring Cloud 场景下更稳。

任务：

1. 先运行 `eval-java-call-resolution-unresolved`；报告会把静态类/外部依赖、基础继承方法与实例接收者缺少类型分开，不能把外部 API 或 `Object` 基础方法误当作本地解析缺陷。
2. 从真实未解析分类中选择最高频且可复现的一类，补充 3-5 个只含逻辑锚点的私有 case。
3. 每次仅修复一个明确的 parser 或 resolver 缺口，不以宽泛 fallback 换取表面召回率。
4. 将每个误判转成可复跑 case，并在 CLI、MCP、HTTP 中保留失败原因和缺失锚点。`expected_resolution_levels` 必须作为门禁条件；用聚合 metrics 观察解析等级与链式边变化，用私有 case 判定正确/错误边。

验收：

- 新增 case 不得降低既有真实 case 的 anchor recall、edge recall 或 forbidden hit 指标。
- 每个失败 case 都能定位到 parser、resolver、graph 或 retrieval 中的具体一层。

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

### P3：证据优先的需求交付闭环 / Evidence-First Delivery Loop

目标：把 Memory Center 从“提供分析与任务组件”收敛为 Agent 可默认遵循的需求交付流程。每个阶段都必须有结构化输入、可审查产物、可执行门禁和可追溯证据；不能以模型自报“已完成”代替验证。

现有基础：任务空间已具备 `requirements.json`、`subtasks.json`、`acceptance.json`、验证回执、阶段流转和交付 Skill 候选；本体已具备 `Policy`、`Constraint`、`GateResult`、`Waiver`、`Validation`、`Action`；索引已具备定向刷新、freshness 和图谱定位。P3 只补齐编排与约束，不重建这些领域能力。

#### P3-1：确定性需求拆解契约

1. 将需求项扩展为可追溯结构：`source_refs`、`scope`、`out_of_scope`、`evidence_refs`、`search_terms`、`candidate_modules`、`acceptance_ids`、`ambiguities` 与 `decision_required`。
2. 提供需求拆解服务：输入可引用的需求材料或人工摘要，输出候选需求项和缺失项；范围、归属、重复、未覆盖验收项由确定性规则检查，LLM 只负责语义解释和候选补充。
3. 将“联想用于搜索、引用用于决策”固化为规则：搜索词可扩展，但会影响实现范围的条目必须带来源引用；没有证据时只能标记 `AMBIGUOUS` 或 `UNKNOWN`，不得自动进入实现。
4. 为每个需求项建立 `Requirement -> Subtask -> CodeTarget -> Acceptance` 链接，定位阶段只能使用已索引目标；索引 stale 时先排队定向刷新并向用户说明使用的 generation。

验收：需求项可回溯来源和范围；未关联验收、未定位代码目标、存在未决歧义时不能进入相应后续阶段；CLI、MCP、HTTP、Workbench 返回同一交付状态与下一步 Action。

#### P3-2：按需三级项目地图与语义桥

1. 将现有 `generate-wiki` 升级为派生读模型，而非新的人工事实源：L1 为受限大小的 workspace/module 总览，L2 为模块内文件与符号职责地图，L3 为业务术语、接口契约、配置键、设计规范到代码实体的语义桥。
2. 每个地图条目保存来源 generation、输入 hash、最后刷新时间和 stale 状态；只对 dirty path 涉及的模块重建，禁止为了生成 Wiki 触发全量 reindex 或读取全库源码。
3. L1 作为任务定位的默认轻量上下文；L2 仅在模块候选确定后读取；L3 仅由需求类型或命中的语义桥触发。生成结果必须能在没有 LLM 的情况下被人和 Agent 阅读。
4. 语义桥采用 workspace profile 扩展。Spring Cloud、Web、移动端和设计系统规则不得硬编码到核心；没有对应 profile 时返回 `UNKNOWN` 与配置建议。

验收：同一 dirty path 的地图刷新只写受影响模块；地图命中可减少无关文件读取；索引新鲜度和地图新鲜度不一致时明确提示，不能伪装为最新。

#### P3-3：策略化门禁与真实验证回执

1. 复用统一本体中的 `Policy`、`Constraint`、`GateResult`、`Waiver` 和 `Validation`，为 intake、breakdown、locate、implement、verify、close 定义版本化门禁；禁止再建一套未关联治理读模型的红线 YAML。
2. 增加受 workspace policy 限制的验证执行适配器：仅允许运行预注册命令/profile，记录命令 ID、参数摘要、超时、退出码、受限输出摘要、产物路径及 hash；不执行来自需求正文、模型输出或外部材料的任意 shell 字符串。
3. 支持外部验证回执，但必须标记 `recorded_external` 并提供脱敏证据引用；只有执行器产物、人工确认或可追溯运行时证据才能将断言提升为 `VERIFIED`。
4. 失败按“可自动修复、配置/环境阻塞、需求/路径错误、人工决策”分类；每类给出停止条件，重试上限由 policy 配置，不能在失败状态无限循环。

验收：任务关闭的每项必需验收都能追溯到有效验证证据；伪造 `passed`、越权命令、缺失豁免或超过重试上限必须阻断门禁；所有阻断都返回可行动的下一步，而不是笼统错误。

#### P3-4：交付矩阵、恢复说明与已验证 Skill 提炼

1. 从既有 JSON 工件和时间线派生 `delivery-matrix.json` 与可读的 `TECH_SPEC.md`，作为只读投影，不引入第二套真源。矩阵展示需求、范围、代码目标、验收、验证、决策、豁免、当前阶段和缺口。
2. `task_resume_check` 直接消费该投影，优先展示未决歧义、失败验证、stale 目标和下一条最小 Action；长任务归档继续使用有界摘要与压缩归档，不恢复巨型原始上下文。
3. 仅从已关闭、验收完整、验证通过且不存在未决豁免的任务生成交付 Skill 候选。候选内容只提炼结构化经验、逻辑锚点和安全验证步骤，不包含私有源码、原始需求正文或工具载荷。
4. 增加任务级效果度量：需求覆盖率、定位覆盖率、验收覆盖率、验证成功率、人工阻断率、阶段耗时、Agent 建议采纳/绕过率；真实 replay 充足前只观测，不自动调权。

验收：新会话可以通过一份有界恢复包理解任务边界、证据和未完成事项；Skill 只能由已验证交付生成；任务级质量指标不读取或保存原始私有正文。

#### P3 性能、迁移与测试约束

- 需求拆解、地图读取、阶段状态和门禁判断必须使用有界 JSON、索引和派生视图，禁止在 MCP/HTTP 热路径全量扫描 workspace、重建图或加载完整需求附件。
- 只有显式维护动作可以生成地图、执行验证、刷新索引或提炼 Skill；普通查询只返回已发布 generation 和排队状态。任何新增默认读取的 P95 延迟不得超过当前同类入口真实基线的 10%。
- 新字段只做 additive 扩展；已有任务空间采用惰性创建和只读投影。旧的人工回执继续可读，但必须显式标为外部记录，不能被误认为执行器证据。
- 新增单元与系统测试覆盖：需求范围/歧义、需求到验收完整性、定向地图刷新、policy/waiver、命令白名单与超时、失败分类/停止条件、矩阵投影、Skill 提炼资格、CLI/MCP/HTTP/Workbench 一致性及真实 workspace 指标格式。

非目标：不将移动端设计稿、Figma、模拟器、Bazel 或任何单一技术栈规则放入核心；不强制所有任务使用交付流程；不让 Agent 自动执行不可逆操作、下载模型或全量重建索引。

### P4：可验证 Skill 演进闭环（已完成，按真实样本持续校准）

目标：让已验证交付产生可回滚、可度量、不会自我污染的可复用经验，而不是把模型自评或原始对话直接写入 Skill 库。

1. Skill 统一使用稳定 ID、版本、结构签名、来源证据、`candidate -> canary -> published|rolled_back` 生命周期和有界 registry；结构相似候选先提示人工合并，避免库膨胀。
2. canary 不参与默认检索。只有不少于三条带证据引用的成功观测、且没有失败观测时，才可显式发布；记录成功、失败、绕过、耗时和 Token 后仅生成建议，不自动改变状态。
3. 默认检索仅返回 `published` Skill；回滚立即撤出默认推荐，但历史观测和来源证据继续保留以便审计。
4. 失败经验提炼和多轨迹归纳均为显式离线维护操作。前者仅按验证 profile、验收标识、哈希任务引用和证据引用聚类，后者仅在至少三条独立已验证候选的共同结构上输出待审核不变量；两者都不保存原始源码、需求正文或日志。
5. CLI、MCP admin 和 HTTP 共享同一应用服务：`delivery-skill-contract-update|canary|observe|evaluate|publish|rollback|recommend|replay`、`delivery-failure-candidates`、`delivery-skill-synthesize`。契约、自动脱敏 replay 与发布门禁已完成；不把离线扫描加入查询热路径。

验收：未验证候选和 canary 永远不会默认被检索；模型自评无法作为发布依据；发布、回滚和观测均可追溯；失败归纳不泄露私有正文；常规 MCP/HTTP 查询不增加全 workspace 扫描。

### P2.5：可信交互历史与图谱可解释性（已收口，按真实反馈维护）

目标：将任务历史从调用日志提升为可复现、可归因、可审查的工程证据闭环，降低真实链路分析中的误判风险，并让长任务的状态和结果对使用者可见。

设计边界：

- 参考 Graphify 的“抽取事实与推断结论分层”思想，但不采用其放弃向量检索的路线；Memory Center 继续保留混合检索和按需索引能力。
- 参考 Grok Build 的运行时检查、会话恢复与结构化进度事件思想，但不引入其终端界面、运行时或产品依赖。
- 不保存原始对话正文、源码正文或工具载荷；继续遵守本地优先、脱敏、一个月保留期和十万条上限。

#### P2.5-1：统一证据等级（已完成）

- 在图边、查询结果、分析报告、案例和交互历史中增加兼容的 `evidence_level`：`EXTRACTED`、`INFERRED`、`AMBIGUOUS`、`VERIFIED`。
- 所有摘要输出同时展示证据来源、等级统计和推断边界；不得把推断结论表述为已验证事实。
- 仅当存在验证命令结果、人工确认或可追溯运行结果时，才允许标记为 `VERIFIED`。

验收：既有 MCP 字段保持兼容；真实链路输出可以区分事实、推断和待确认项；新增单元测试覆盖等级传播与降级规则。

#### P2.5-2：运行时配置检查（已完成）

- 新增 `memory-center inspect`，集中展示实际生效的工作空间、MCP 可执行文件与版本、AGENTS 指令、Hook、会话绑定、记忆生命周期、近期效果摘要和索引活动代际。
- 对配置陈旧、Hook 未安装、可执行文件版本不一致、会话未绑定等状态给出可执行的修复建议。
- 输出默认脱敏，不展示完整私有路径、原始提示词或敏感配置值。

验收：在真实工作空间可一次看清宿主实际看到的运行状态；故障场景能够给出明确原因和修复命令。

#### P2.5-3：会话代码版本与验证快照（已完成）

- 在 `mc_start` 记录 Git 分支、提交标识和工作区脏文件计数；非 Git 工作空间自动跳过。
- 在 `mc_close` 关联验证命令、退出状态、结果摘要和任务结论，形成“调用 -> 改动 -> 验证 -> 结果”的最小证据链。
- 对失败、回滚、重新打开的任务保留规范化状态，支持后续效果分析。

验收：单次会话回放可定位所对应的代码版本和验证结果；未配置 Git 或验证命令时不影响主流程。

#### P2.5-4：后台任务阶段进度协议（已完成）

- 为重建、增量索引、图谱计算和基准测试建立版本化进度事件：`queued`、`scanning`、`parsing`、`graph`、`retrieval`、`semantic`、`finalizing`、`failed`。
- 进度统一持久化并可通过 HTTP、MCP 后台任务和 Workbench 读取；同一任务只能有一个权威状态源。
- 对高频进度事件限流、合并和保留诊断信息，支持失败和取消后的可解释反馈。

验收：长任务不再无输出等待；进度、失败原因和最终统计一致，且不会显著影响索引热路径。

#### P2.5-6：真实工作空间可复现基准（随真实使用持续积累）

- 在真实工作空间持续记录冷/热查询 P50、P95、增量索引开销、输出 Token、证据等级覆盖率和人工复核的错误事实率。
- 将交互历史中的采纳、验证、结果和回退纳入效果指标，但不以模拟数据或外部项目宣传数据作为发布门槛。
- 每次性能优化都提供前后对比、数据范围和回归结论。

验收：每项性能或检索优化都有可复现的真实数据证据；基准报告可直接用于版本发布门禁。

### 外部方案参考边界

- Graphify 与 Grok Build 仅作为 P2.5 的架构参考，不引入其运行时依赖、命令行实现或界面形态。
- code-review-graph 仅作为 P0 的算法、审查流程和评测方法参考；不安装为默认运行依赖，不复制其 SQLite 图、全图 NetworkX 分析、记忆回灌或自动写入重构能力。
- 所有吸收项必须先经过真实工作空间基准和兼容性验证，再进入默认行为或发布门禁。

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
2. 将项目地图与语义桥保持为按需派生视图，优先减少定位阶段无关文件读取。
3. 将通过校准的 `skill-up` 结果作为外部评测证据接入 canary 观测，但仍要求现有人工或执行器证据门禁。
4. 用真实关闭任务衡量范围覆盖、验收覆盖、验证成功率、阻断率、阶段时延与建议绕过率；样本不足时只观测不自动调权。

完成条件：新会话能从有界恢复包得到目标、证据、未决项和最小下一步；任何关闭结论都可回溯到验证证据。

### 阶段 4：按数据决定的扩展

只有阶段 0 至 3 的数据证明当前架构存在明确瓶颈，才评估新语言、图数据库、向量后端、可视化或新的 Agent 工作流。每个候选必须先给出真实问题、最小原型、性能/准确率对比、迁移与回滚方案；未通过 gate 的实验不进入默认路径。

### 当前建议 / Current Recommendation

4.3.78 已完成首轮 Java 调用解析真实精度闭环和 co-change v2 校准：3 个私有链式锚点严格门禁全部通过；66 个真实共变 case 的 precision 从 0.0438 提升到 0.0706，recall 从 0.2191 提升到 0.2229。后续 Java 解析只由新增真实失败样本驱动，不再把可解释的外部边界当作缺陷。

4.3.79 已完成局部刷新性能治理：真实单文件刷新由 12.58 秒降至 5.81 秒，阶段耗时、10 秒预算和 CLI/HTTP/MCP/运行治理趋势已闭环。下一优先级调整为 **walk-forward 共变/replay 校准 -> 新增真实 Java 失败样本**。共变学习只能使用时间前向、脱敏且经验证的数据，不能让未来提交泄漏到历史预测。4.3.77 的图感知审查能力继续作为唯一稳定入口，不建设平行图存储或第二套审查服务。
