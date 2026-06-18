# Next Phase Master Plan / 下一阶段总方案

## 1. 文档定位

这份文档只保留**还没收口的方向**。

已经稳定、已经完成并且已经进入主文档体系的能力，不再在这里重复列清单。  
这份文档只回答三件事：

1. 现在还剩什么最值得继续做
2. 下一步先做哪个
3. 哪些外部思想还没有真正吸收到实现里

当前开发以**功能可用、实际好用、稳定可维护**为优先级。本文档中的方向和顺序都是建议，不是限制；开发者可以根据真实用户问题重排任务、重构核心模块、调整公开入口、升级数据模型或引入新依赖。

如果你只是想看当前系统怎么用，优先看：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)

### 已完成并迁出 / Completed and Moved Out

以下能力已经实现完成，不再作为本文件的“待做事项”重复跟踪：

- Hybrid retrieval / 混合检索
- Benchmark trending / 基准趋势
- Unified backend query / 统一后端查询
- Drill-down navigation / 钻取导航
- Completion audit / 完成审计

实现明细见：
- 当前状态已经并入本文件，不再单独维护实现完成报告。

### V3 已完成基础版 / V3 Foundation Already Implemented

V3 不是“未来方向”，而是当前代码里已经存在的一批能力。当前至少已经有：

#### 1. V3 Core 模块

- `core/context/*`
  - `ContextPackBuilder`
  - `budget / evidence / pack`
- `core/domain/*`
  - `BusinessDomainExtractor`
  - `BusinessFlowExtractor`
  - `BusinessFlowGraph`
- `core/freshness/*`
  - `status / reconcile / watcher`
- `core/matching/*`
  - project matching
- `core/ontology.py`
  - Code Knowledge Graph ontology node / edge typing
- `core/reasoning/*`
  - patterns / transitive / risk
- `core/storage/*`
  - unified store / SQLite pool / vector index
- `core/onboarding/*`
  - glossary / guide / tour
- `core/presentation/*`
  - progressive explanation helpers

#### 2. V3 MCP / HTTP 入口

- MCP 新增：
  - `mc_context_pack`
  - `mc_onboard`
  - `mc_domain`
  - `mc_freshness`
- HTTP 新增：
  - `/workspace/context-pack`
  - `/workspace/onboard`
  - `/workspace/freshness`
  - `/workspace/business-flow`
  - `/workspace/business-flow-impact`

#### 3. 对 V3 的正确理解

这些能力当前的准确状态是：

- **基础版已实现**
- **部分主入口已接入**
- **仍需要继续产品化收口**

所以：

- 不应再把它们写成“还没做”
- 也不应误写成“已经完全收口”

### v3.1.0 新增实现 / v3.1.0 New Implementations

以下能力在 v3.1.0 中实现完成：

#### 1. Vue 前端工作台 / Vue Frontend Workbench
- **位置**: `web/` 目录，Vue 3 + Vite + vue-router + axios
- **页面覆盖**: Workbench / Dashboard / Continuity / Focus Task / Query / Impact / Group / Timeline / Receipts / Usage / Backend / Freshness / Audit / Health
- **集成方式**: HTTP 服务器在 `/app` 路径自动托管构建后的 Vue SPA，支持客户端路由
- **开发模式**: `cd web && pnpm dev` 启动 Vite 开发服务器（端口 5173），API 代理到 Python 后端（端口 8765）

#### 2. 跨项目查询性能优化 / Cross-Project Query Performance
- **并行化**: `group_status` / `group_query` 改为 `ThreadPoolExecutor` 并行执行各 workspace 查询
- **缓存**: `resolve_group` 和 `_load_group_data` 增加 TTL 缓存（15秒），避免重复加载 registry 和 workspace 数据
- **影响**: 大幅减少多项目场景下的串行等待时间

#### 3. 跨项目链路可解释性增强 / Cross-Project Chain Explainability
- **新增字段**: `group_query` / `group_impact` / `group_chain` 返回中增加 `top_bridges`、`bridge_reasons`、`cross_workspace_path_hint`
- **目的**: 让用户和模型理解跨项目关联的原因

## 2. 当前剩余重点

| 优先级 | 方向 | 目标 |
| --- | --- | --- |
| 1 | 轻量本体论 / Ontology | 已有第一版文档与部分实现，继续用统一实体、关系、语义强度收紧 `query / contracts / chain / timeline` 的边界 |
| 2 | 候选路径与权重决策层 | 不只返回命中结果，而是返回“候选路径 + 权重 + 推荐下一步”，帮助 Agent 在不确定场景中收敛决策 |
| 3 | 检索质量继续收口 | `mc_lookup`、`query` 已有混合检索与 contracts 过滤，但仍需继续减少意图误判和误关联 |
| 4 | Context Pack / Freshness / Domain 工作流化 | V3 模块已在代码中，但还没完全成为默认工作流第一入口 |
| 5 | Benchmark 趋势化真正落地 | 基础能力和入口已接好，继续强化长期趋势观察、回归阈值与治理闭环 |
| 6 | Completion audit 产品化 | audit 已可用，继续从“仓库自检工具”走向“真实 workspace 可用的治理能力” |
| 7 | Timeline / ref / task 体验增强 | drill-down 已有 CLI / MCP / HTTP 入口，继续增强真实工作流体验和摘要质量 |
| 8 | SQLite 主读路径继续推进 | unified backend query 已落地，继续让 backend 更像稳定主读底座，而不是高频优先补充层 |

## 3. 当前状态判断

这一阶段最容易产生误解的地方，不是“有没有代码”，而是“做到什么程度”。

所以这里明确分成三类：

### 3.1 已完成基础版

- `docs/ONTOLOGY.md` 已存在，ontology 第一版已经落地
- `detect_query_intent`、`memory_query_hybrid`、contracts 过滤与置信度表达已经实现
- benchmark trending 已实现，并且接入 CLI / MCP / HTTP
- drill-down navigation 已实现，并且接入 CLI / MCP / HTTP
- unified backend query / backend consistency 已实现，并且接入 CLI / MCP / HTTP
- completion audit 已实现，并且接入主入口
- V3 `context pack / onboarding / domain / freshness` 已实现，并且已有 MCP / HTTP 入口

这些项不应再被描述成“还没开始做”。

### 3.2 部分已完成，继续收口

- ontology 已有第一版，但对更多链路的约束还不够彻底
- 候选路径、权重、推荐下一步这些“决策层输出”已有零散字段，但还没有成为统一产品能力
- retrieval 已有 hybrid 主链路，但结果质量仍需继续收口
- context pack / freshness / domain 已存在，但还没彻底进入默认推荐工作流
- benchmark trend 已能跑，但长期归因、回归门槛和治理闭环还不够强
- audit 已能跑，但对不同类型 workspace 的适配还要继续加强
- drill-down 已可用，但摘要层、日常入口体验和更真实行为测试还可继续补
- backend 已承担部分高频读取，但还不是统一主读事实源

### 3.3 仍然真正未完成

- 原生向量 ANN 在真实 workspace 上的质量与性能基准，以及默认启用策略
- `tree-sitter` 解析精度继续深化
- facade 关键返回值全面类型化
- 更完整的结构化日志与指标体系
- 把 reasoning / context pack / freshness 更完整地并入默认主工作流
- V3 模块之间的解释资产复用与统一展示协议

## 4. 下一步先做什么

如果只选一个，我建议先做：

### `轻量本体论 / Ontology`

原因：

- 当前系统已经有 graph、timeline、ref、receipt、task、handoff、contracts、group chain
- 但这些能力之间还缺少一层统一的“领域语言”
- 没有 ontology 约束时，后面继续做 retrieval、chain、audit，很容易再次出现语义漂移

这一步不是去做一个很重的知识图谱工程，而是先补一层**约束文档 + 关键实现边界**。

紧接着最值得并行推进的是：

### `候选路径与权重决策层`

原因：

- 当前系统已经能产出很多“片段化判断”：confidence、risk、suggested_fixes、confirmed/probable/possible
- 但这些判断还没有收敛成一套统一的“先做什么、为什么先做”的决策表达
- `memory-center` 的更高价值不是只记住过去事实，而是帮助 Agent 在多条可能路径里更快选到更优下一步

## 5. 可调整的推荐路线

以下阶段用于组织方向，不要求严格按顺序实施。可以优先推进用户收益更高、验证路径更清晰的事项，也可以合并或替换旧方案。

### 阶段 A：定义 ontology 约束层

目标：

- 在已落地的第一版 ontology 基础上，继续统一 `memory-center` 里的核心实体、关系和推断边界

建议动作：

1. 继续维护 `docs/ONTOLOGY.md`
2. 第一版已定义：
   - 代码实体：`Service / Class / Method / Endpoint / FeignClient / FeignMethod / MQTopic / MQConsumer / ConfigKey`
   - 记忆实体：`SessionEvent / WriteReceipt / Ref / Task / Handoff / ResumePacket`
   - 关系类型：`CALLS / CALLS_SERVICE / IMPLEMENTS_FEIGN / PUBLISHES / CONSUMES / REFERENCES / BELONGS_TO_TASK / DERIVED_FROM`
   - 语义强度：`fact / inferred / derived`
3. 继续把 ontology 收紧到这些链路：
   - `detect_query_intent`
   - `memory_query_hybrid`
   - `contracts / chain / group_chain`
   - `timeline / ref / receipt / task`

完成标志：

- 查询意图更稳
- 关系语义更清楚
- 文档里能明确区分“事实关系”和“推断关系”

### 阶段 B：检索质量继续收口

目标：

- 在已有 hybrid retrieval 基础上，让 `mc_lookup / query / resume / handoff` 的结果更准

建议动作：

1. 继续收紧 Feign / API / Service 的区分逻辑
2. 为 contracts 补充层增加更强的精确匹配和置信度表达
3. 为 callers / callees / chain / context 增加更强行为测试

完成标志：

- 本地 service 查询不再被误导到 Feign contracts
- Feign / API / chain 结果更少“像命中、实际不准”

### 阶段 B2：候选路径与权重决策层

目标：

- 让 `memory-center` 从“命中结果聚合器”继续升级为“项目级决策中枢”

建议动作：

1. 为 query / lookup / sniff / impact / doctor / runtime-audit 定义统一 `candidate_paths` 结构
2. 把 `confirmed / probable / possible / rejected` 与 `confidence / risk / verification_cost` 统一起来
3. 在默认解释中补 `recommended_path` 与 `why_this_first`
4. 让验证结果能反向更新路径权重，而不是只写一条 case 就结束

完成标志：

- 至少一条主链路不只返回“查到什么”，还能返回“下一步先做什么”
- 推荐路径能解释为什么排第一
- 失败路径会被降权，成功路径能在有证据前提下逐步提升默认优先级

### 阶段 C：Context Pack / Freshness / Domain 工作流化

目标：

- 让 V3 模块从“存在能力”变成“默认工作流入口”

建议动作：

1. 让 `mc_context_pack` 成为架构理解 / 变更预热的首选入口
2. 让 `mc_freshness` 在主查询链路里给出 stale / pending 提示
3. 让 `mc_domain` / `mc_onboard` 复用同一套解释与 flow 资产

完成标志：

- 架构理解不再默认先 grep / read
- freshness 提示能跟主查询链路结合
- onboarding / domain / impact 说的是同一种领域语言

### 阶段 D：Benchmark 趋势化

目标：

- 在已有趋势记录能力基础上，长期知道哪条链路 token 又变胖了

建议动作：

1. 固定高频函数 benchmark 基线
2. 补趋势视图与回归阈值
3. 将趋势结果接到 `work-health` / `mc_admin`

完成标志：

- 每次优化都能量化收益
- 能快速定位 token 回归链路

### 阶段 E：Completion audit 产品化

目标：

- 让已存在的 audit 真正适配普通 workspace，而不是只适配当前仓库

建议动作：

1. 继续减少对仓库结构的隐式假设
2. 增加 Java / Maven / Gradle / frontend 项目规则覆盖
3. 将设计选择与真实 bug 的判断继续沉淀到 `SPECIAL_NOTES`

完成标志：

- 不同类型 workspace 跑 audit 时假阳性更少
- audit 输出更像治理建议，而不是简单报缺文件

### 阶段 F：Timeline / ref / task 体验增强

目标：

- 让已存在的 drill-down 真正参与日常工作流

建议动作：

1. 给 `DrillDownNavigator` 补更多真实行为测试
2. 继续优化 CLI / MCP / HTTP 正式入口的日常使用体验
3. 为 handoff / resume 增加更强摘要层

完成标志：

- 不只是 Python API 能用
- 人和模型都能顺着 ref 快速追到证据

### 阶段 G：SQLite 主读路径继续推进

目标：

- 让已存在的 unified backend query / `memory.db` 更稳定地承担聚合与主读职责

建议动作：

1. 继续统一高频读取到 backend
2. 避免 UI / eval / query 三套口径分叉
3. 为 backend 聚合补更稳定过滤能力

完成标志：

- 高频查询口径更一致
- JSONL fallback 继续减少

## 6. 外部思想剩余吸收点

这一节只记录**建议吸收**、并且可以进一步转化为开发计划的外部思路。

统一写法：

- `判断`：是否值得吸收
- `吸收点`：只写建议进入本项目的能力
- `开发包`：后续开发分组
- `推荐 issue`：可以直接拆分推进的工作项
- `验收标准`：完成后怎么判断真的吸收到了系统里

### `alibaba/open-code-review`

判断：

- **建议吸收架构思想，不作为必选运行时依赖**
- 适合补强 change review、verification 和 rule governance
- 官方来源：https://github.com/alibaba/open-code-review
- 本次研究快照：`0ac1193040a1b5d9f946ba72e8d889b356de41a6`

吸收点：

1. `Deterministic Engineering × Agent`
   - 确定性逻辑保证 diff 范围、文件覆盖、规则匹配、定位与结果验证
   - Agent 只负责动态上下文检索和风险判断
2. `Diff Preview + Exclusion Reasons`
   - 执行 Agent 前预览覆盖文件、排除文件和排除原因
3. `Graph-Aware Change Bundles`
   - 使用 graph / contracts / flows，把关联变更组成隔离 bundle
4. `Finding Relocation + Reflection`
   - Finding 必须定位回真实 diff，并经过证据充分性与重复检查
5. `Agent-Friendly Structured Output`
   - 结构化结果与进度输出分离，便于 verification 和 memory 消费

不吸收：

- 不把 Memory Center 改造成依赖某个 LLM endpoint 的专用审查器
- 不复制 OpenCodeReview 的 Go CLI、配置目录或命令体系
- 不让外部 review 工具成为必选依赖

开发包：

- **OCR-1 / Deterministic Diff Scope and Preview**
- **OCR-2 / Graph-Aware Change Bundles**
- **OCR-3 / Layered Rule Preview**
- **OCR-4 / Context-Aware Change Review**
- **OCR-5 / Finding Location, Validation and Deduplication**
- **OCR-6 / Review-to-Verification Memory Loop**

验收标准：

1. Agent 执行前能确定预览覆盖范围
2. 所有变更文件得到确定性处理，不依赖 Agent 自主挑选
3. Finding 必须定位到真实变更并可追溯证据
4. Review、修复、验证和经验沉淀形成闭环

### `github/spec-kit`

判断：

- **建议吸收规格驱动流程和可恢复 workflow 思想**
- 适合补强 task-space、artifacts、verification 和长期协作
- 官方来源：https://github.com/github/spec-kit
- 本次研究快照：`34ce66139e5a2d9b28cbb9e21f5a0fc27c2c5d03`

吸收点：

1. `Constitution`
   - 将稳定原则、架构约束和治理规则提升为不可静默覆盖的项目治理工件
2. `Spec → Plan → Tasks → Implement`
   - 为需求、计划、任务、变更和验证建立稳定追踪关系
3. `Clarify + Analyze`
   - 实现前澄清高风险歧义，并检查 spec / plan / tasks 的覆盖与一致性
4. `Resumable Workflow + Human Gates`
   - 每一步持久化状态，支持暂停、恢复、条件分支和人工批准
5. `Preset / Extension Boundary`
   - Preset 调整模板和术语；Extension 增加新能力；核心保持精简

不吸收：

- 不复制 `.specify` 目录和 slash command 命名
- 不把自然语言规格视为高于真实代码和运行证据的唯一事实源
- 不允许 Agent 自动绕过 Constitution 冲突或人工 gate

开发包：

- **SK-1 / Project Constitution**
- **SK-2 / Artifact Traceability Graph**
- **SK-3 / Spec Clarification and Coverage Analysis**
- **SK-4 / Resumable Workflow State Machine**
- **SK-5 / Human Review Gates**
- **SK-6 / Trusted Preset and Extension Boundary**

验收标准：

1. 任意需求可追到任务、变更和验证证据
2. 实现前能发现歧义、未覆盖需求和无来源任务
3. 长任务中断后可从确定步骤恢复
4. Constitution 冲突和人工 gate 无法被静默绕过
5. 扩展能力可选、可审计、可移除

### `colbymchenry/codegraph`

判断：

- **建议吸收**
- 适合作为 Memory Center 的“代码理解底座”参考

吸收点：

1. `tree-sitter + SQLite + FTS5`
   - 让 AST、symbol、edge、全文检索收敛到更稳定的本地底座
2. `watcher + freshness + staleness banner`
   - 让图谱状态跟真实文件变化保持一致
3. `context pack / fewer tool calls / fewer token`
   - 强化“先给足结构化上下文，再少读文件”的工作流
4. `shared warm state / daemon feasibility`
   - 为多 Agent / 多窗口协作预留后台共享能力

开发包：

- **CG-1 / Tree-sitter Java Parser Spike**
- **CG-2 / FTS & Inverted Retrieval Consolidation**
- **CG-3 / Freshness Banner Integration**
- **CG-4 / Watcher-to-Incremental-Reindex Bridge**
- **CG-5 / Context Pack First-Class Workflow**
- **CG-6 / Context Pack Benchmark**
- **CG-7 / Workspace Daemon Feasibility Study**

推荐 issue：

1. Freshness Banner 接入主查询链路
2. Context Pack 进入默认推荐工作流
3. Context Pack 完成 freshness / snippet 闭环
4. Watcher 事件驱动增量索引桥接
5. Connect-time Catch-up 与 stale 恢复策略
6. Tree-sitter Java Parser Spike
7. FTS / 倒排检索统一收口
8. Context Pack Benchmark 与采用率观测
9. Workspace Daemon 可行性研究

验收标准：

1. stale/pending 文件能在主查询链路里被清楚提示
2. context pack 真正减少 grep/read/tool call
3. Java/Spring Cloud 解析精度真实提升
4. incremental reindex 能稳定跟上高频编辑
5. 这些能力接到了 CLI / MCP / HTTP 主入口，而不是只停在 Python API

### `Lum1104/Understand-Anything`

判断：

- **建议吸收**
- 适合作为 Memory Center 的“教学型理解层 / 解释层”参考

吸收点：

1. `Guided Tour / Onboarding 导览`
   - 把已有 graph、ref、task、handoff 组织成可阅读的架构导览
2. `Business Domain / Flow / Step`
   - 让业务流成为正式输出形态，而不是只停留在底层结构关系
3. `Flow-Aware Impact Explanation`
   - 让影响分析不只说“影响谁”，还说“影响哪段业务流”
4. `Persona-Adaptive Explanation`
   - 为 developer / architect 等角色提供不同粒度的解释模板
5. `Incremental refresh for understanding assets`
   - 让 flow / tour / domain 等理解资产随代码增量更新

开发包：

- **UA-1 / Guided Tour Layer**
- **UA-2 / Layered Explanation View**
- **UA-3 / Business Flow First-Class Output**
- **UA-4 / Flow-Aware Impact Explanation**
- **UA-5 / Persona Profiles for Explanations**
- **UA-6 / Default Incremental Knowledge Refresh**

推荐 issue：

10. Guided Tour 生成器主链路化
11. 统一 Explanation Schema
12. Business Flow 正式输出
13. Flow-Aware Impact
14. Persona 视角输出
15. 理解资产增量刷新

验收标准：

1. 新人能按导览顺序理解系统入口、核心服务、关键依赖
2. 核心 Spring Cloud 示例仓库能稳定输出业务流
3. impact / handoff / onboarding 能复用 flow 与 explanation 资产
4. 至少 developer / architect 两种 persona 有稳定输出差异
5. flow / tour / domain 资产支持增量刷新，而不是每次都全量重建

### `affaan-m/ECC`

判断：

- **建议吸收**
- 适合作为 Memory Center 的“agent 工作流协议、验证闭环、持续学习、运行治理”参考

吸收点：

1. `Workflow Protocol`
   - 将任务类型映射为推荐工具顺序和执行协议
2. `Verification Loop`
   - 强化 `analyze -> checklist -> verify -> close` 闭环
3. `Continuous Learning / Pattern Promotion`
   - 从 case / rule / decision 中晋升可复用模式
4. `Agent Runtime Governance`
   - 将 hooks / MCP / agent config 纳入治理与审计
5. `Bundle / Skill / Command Packaging`
   - 把最佳实践导出为可安装的 agent 使用包

开发包：

- **ECC-1 / Workflow Protocol Profiles**
- **ECC-2 / Verification Loop Strengthening**
- **ECC-3 / Pattern Promotion Pipeline**
- **ECC-4 / Learned Heuristics Register**
- **ECC-5 / Agent Runtime Audit**
- **ECC-6 / Agent Usage Bundle Export**

推荐 issue：

16. Workflow Protocol Profiles
17. Verification Loop 强化
18. Pattern Promotion Pipeline
19. Learned Heuristics Register
20. Agent Runtime Audit
21. Agent Usage Bundle Export

验收标准：

1. 至少覆盖 quick-fix / contract-change / long-task / architecture 四类 workflow profile
2. verify / close 闭环输出口径统一
3. case / rule / skill 候选晋升逻辑可解释、可审计
4. audit 能输出 hooks / MCP / agent config 的治理问题
5. 至少能导出一组适用于 Codex / Claude Code / Cursor 的最小使用 bundle

### `概率树 / 候选路径权重视角`

判断：

- **建议吸收，但只吸收工程决策层，不吸收“四维理论”叙事**
- 适合作为 `memory-center` 从“记忆仓库”升级为“决策辅助层”的产品视角

吸收点：

1. `Candidate Paths Instead of Single Answer`
   - 不强行把复杂问题压成唯一答案，而是给候选路径列表与排序理由
2. `Weight / Confidence / Risk as First-Class Fields`
   - 将权重、置信度、风险和验证成本变成统一输出的一等字段
3. `Recommended Next Step`
   - 默认回答里不仅说“是什么”，还说“下一步先做什么”
4. `Verification Feedback Loop`
   - 验证结果反向更新路径权重，形成“成功路径升权、失败路径降权”的学习闭环
5. `Low-Cost Validation First`
   - 高不确定场景优先推荐低成本验证动作，而不是直接建议大改

不吸收：

- 不把“四维生命”“高维干预者”之类叙事引入产品文档或实现
- 不把权重伪装成客观真值；所有权重都必须可追溯到证据、规则或历史验证
- 不让单次偶然成功直接固化为长期默认策略

开发包：

- **PT-1 / Candidate Path Schema**
- **PT-2 / Recommended Next Step**
- **PT-3 / Verification Cost and Low-Cost Validation First**
- **PT-4 / Path Weight Feedback Loop**
- **PT-5 / Decision Benchmark**

验收标准：

1. 至少一条主链路返回结构化候选路径和排序理由
2. 推荐下一步不是拍脑袋，而是能追溯到 confidence、risk、freshness、contracts 或验证成本
3. 成功与失败验证都能影响后续推荐权重
4. 高不确定场景下，系统默认更偏向低成本验证而不是武断改动

### `agentmemory`

剩余重点：

- retrieval 质量继续做稳
- benchmark 趋势化与长期回归

### `rtk`

剩余重点：

- discover / 热点命令发现
- 更强命令压缩矩阵
- 命令输出前置压缩层

### `mattpocock/skills`

剩余重点：

- 更强约束模板
- 更标准的模型内工作协议
- 自动选择 `resume / start / analyze` 的更强策略

### 本体论 / UModel / STAROps 方向

剩余重点：

- 将“对象优先、关系显式、推断边界明确”的思想收成轻量 ontology
- 先约束 `memory-center` 自己的领域语言，再继续叠加 retrieval / audit / chain 能力

## 7. 3.0 中长期剩余版图

除了上面的近期收口项，3.0 还有几块中长期能力需要继续推进。既然 `V3_PLAN.md` 已移除，这部分统一收敛到这里。

### 方向 1：Native Vector + Inverted Retrieval

目标：

- 原生向量检索进入 SQLite 主存储路线
- 倒排索引替换高成本的全量扫描路径
- `graph + sparse + vector` 的融合策略继续收口

完成标志：

- 至少一种原生向量后端可用于真实 workspace
- 稀疏检索只打命中候选，不再扫全量
- `mc_lookup` 在 query 类场景下有可验证的召回与延迟收益

当前判断：

- reindex 已自动重建 SQLite BM25，查询只访问匹配 posting candidates
- BM25 已进入 hybrid fusion
- semantic index 存在 dense vectors 时会同步 VectorIndex
- vector ANN 已接入主链路，但默认关闭，真实 workspace 质量和性能基准仍需深化
- 所以这块属于“主链路已接入，继续做真实数据质量收口”

### 方向 2：Code Knowledge Graph Reasoning

目标：

- 从“邻居展开”升级到“可解释推理”
- 引入图模式匹配、传递推理、风险模式识别

完成标志：

- 至少有一组内建 graph patterns 能稳定回答高价值问题
- 推理结果能区分 `fact / inferred / derived`
- 输出里能解释“为什么判定有风险 / 为什么推导出这条链路”

当前判断：

- `reasoning/patterns.py`、`reasoning/transitive.py`、`reasoning/risk.py` 已存在并有测试
- 但还没有完全并成默认主工作流能力
- 所以这块不应写成“完全未做”，更准确是“已有底层能力，未完全主链路化”

### 方向 3：Indexer Upgrade

目标：

- 提升 Java 解析精度
- 加快 reindex 速度
- 让增量索引真正按 changed files 精确更新

完成标志：

- `tree-sitter` 成为可选稳定解析器
- 并行索引在中型 workspace 上有明确收益
- 删除、移动、修改文件的索引更新都能稳定收口

当前判断：

- freshness watcher / status、changed-file reindex、显式 workspace 解析已经存在
- 增量索引会真实调用 `reindex_workspace(paths=...)`，失败原因通过 `reindex_error` 可见
- 并行索引与 tree-sitter 自动选择已存在，但仍需在中大型真实 workspace 验证收益和精度
- 删除和移动路径已进入统一 scoped reconciliation，会同步清理确定性索引与 graph；后续只需在更多真实仓库验证边缘语法和规模收益

### 方向 4：Type Safety and Observability

目标：

- facade 层的关键返回值逐步类型化
- 增加结构化日志、延迟指标、质量指标

完成标志：

- 关键 facade 的 schema 不只“存在”，还具备稳定类型边界
- 能观测查询延迟、索引耗时、召回质量、token 回归

当前判断：

- 已新增 additive `FacadeMetadata`、统一 `_quality` 摘要和 `OperationObserver`，公开 MCP schema 保持兼容
- reindex / hybrid lookup 已记录结构化 outcome、duration、result count，路径类标签自动脱敏
- portable benchmark baseline 已支持 median/p95 延迟与质量回归比较
- 后续重点转为真实脱敏 workspace 的长期采样，不再新增平行观测实现

## 8. 当前最值得继续补的检查点

当前后续开发时，最值得继续盯住的是：

1. 新能力是否真正接到了 CLI / MCP / HTTP 主入口
2. 行为测试是否真的覆盖了真实输入输出，而不是只测“模块存在”
3. 文档是否继续收敛，避免重新出现“完成”和“未完成”混写

## 9. Done 定义

下一阶段不只看“功能有没有”，还要看：

1. 结果是不是更准
2. token 是否更稳
3. audit 是否更可信
4. ontology 是否开始真正约束代码语义
5. 文档是否继续保持收敛


---

## 10. 本轮实施记录 / Implementation Log (2026-06-04)

下一阶段的可执行计划已拆分到：

- [Memory Center Next Evolution Implementation Plan](./superpowers/plans/2026-06-18-next-evolution.md)

执行顺序为 Golden Benchmark、Reasoning Pipeline、Parser 差异评测、自适应检索、Agent 使用体验闭环。后续优化必须先通过 Golden Benchmark 证明准确率、延迟或 token 收益。

### Phase A: Ontology 约束层 ✅

**改动文件**：`memory_center/core/ontology.py`, `memory_center/core/retrieval/hybrid.py`, `memory_center/core/orchestrator/query.py`

新增 `EntityValidator` 类，实现 ONTOLOGY.md §5 约束：
- `is_feign_entity()` — 基于命名模式（Feign\*Service / \*FeignClient）+ 正则 + 注解三重判定
- `is_local_service()` — 排除 Feign 后的本地 Service 判定
- `validate_endpoint_path()` — §5.5 路径具体性验证（至少2段）
- `classify_entity_category()` — structural / declarative / contractual / inferential / memory / v3_extended
- `validate_memory_layer()` — §5.4 记忆实体层级（L0/L1/L2）

新增工具函数：
- `annotate_semantic_strength()` — 批量标注查询结果语义强度
- `multi_hop_confidence()` — 多跳链路置信度衰减（2跳×0.9, 3跳×0.8, 4+×0.7）

**接入点**：
- `hybrid.py`: detect_query_intent 新增 Phase 2b（EntityValidator 实体分类）
- `hybrid.py`: _EDGE_SEMANTIC_STRENGTH 统一从 ontology 模块获取
- `query.py`: _filter_contracts_by_query 中 EntityValidator 验证通过时置信度提升（0.95→0.97）

### Phase B: 检索质量收口 ✅

**改动文件**：`memory_center/core/orchestrator/query.py`, `memory_center/core/retrieval/hybrid.py`

- contracts 过滤中增加 EntityValidator 置信度增强
- 检索结果 `_result_to_dict` 已包含 ontology 语义强度标注

### Phase C: Freshness banner 修复 ✅

**改动文件**：`memory_center/core/orchestrator/query.py`, `memory_center/core/orchestrator/impact.py`

- 所有 `svc.get_freshness_banner()` 调用修正为 `svc.banner()`（IndexFreshnessService 的正确方法名）
- 消除了因方法名不匹配导致的静默失败

### Phase D: Benchmark 可配置回归阈值 ✅

**改动文件**：`memory_center/core/benchmark/trending.py`

- 新增 `RegressionThresholdConfig` dataclass：支持默认阈值、临界阈值、最少数据点、逐函数阈值覆盖
- 新增 `check_regression_alerts_configurable()` 函数：支持逐函数阈值的回归检测

### Phase E: Completion Audit 工作区类型检测增强 ✅

**改动文件**：`memory_center/core/audit/completion.py`

- `detect_workspace_type()` 新增：
  - Scala（build.sbt）
  - Monorepo（pnpm-workspace.yaml / lerna.json）
  - Docker 检测变量（Dockerfile / docker-compose.yml）

### Phase F+G: 行为测试 ✅

**测试文件**：`tests/test_next_phase_comprehensive.py`

新增约 60+ 测试覆盖：
- Phase A: EntityValidator（is_feign_entity, is_local_service, classify, validate_endpoint_path, validate_memory_layer）
- Phase A: 语义强度标注、多跳置信度衰减
- Phase B: 检索意图检测（feign/mq/endpoint/config/general）
- Phase C: Freshness 状态、FileWatcher
- Phase D: RegressionThresholdConfig（默认/逐函数阈值）
- Phase E: 工作区类型检测（unknown/python/node/scala/monorepo/java-maven/java-gradle）
- Phase F: DrillDownNavigator 行为测试（facade summary, quick action）
- Phase G: UnifiedBackendQuery 结构测试
- 外部 UA-5: Explanation persona 适配（architect/manager/developer）
- 外部 CG-4: Watcher 桥接结构测试

### 测试结果

```
466 passed, 5 skipped in ~9s
```

新增测试与原有 403 个测试完全兼容，无回归。
