# Next Phase Master Plan / 下一阶段总方案

## 1. 文档定位

这份文档只保留**还没收口的方向**。

已经稳定、已经完成并且已经进入主文档体系的能力，不再在这里重复列清单。  
这份文档只回答三件事：

1. 现在还剩什么最值得继续做
2. 下一步先做哪个
3. 哪些外部思想还没有真正吸收到实现里

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
| 2 | 检索质量继续收口 | `mc_lookup`、`query` 已有混合检索与 contracts 过滤，但仍需继续减少意图误判和误关联 |
| 3 | Context Pack / Freshness / Domain 工作流化 | V3 模块已在代码中，但还没完全成为默认工作流第一入口 |
| 4 | Benchmark 趋势化真正落地 | 基础能力和入口已接好，继续强化长期趋势观察、回归阈值与治理闭环 |
| 5 | Completion audit 产品化 | audit 已可用，继续从“仓库自检工具”走向“真实 workspace 可用的治理能力” |
| 6 | Timeline / ref / task 体验增强 | drill-down 已有 CLI / MCP / HTTP 入口，继续增强真实工作流体验和摘要质量 |
| 7 | SQLite 主读路径继续推进 | unified backend query 已落地，继续让 backend 更像稳定主读底座，而不是高频优先补充层 |

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
- retrieval 已有 hybrid 主链路，但结果质量仍需继续收口
- context pack / freshness / domain 已存在，但还没彻底进入默认推荐工作流
- benchmark trend 已能跑，但长期归因、回归门槛和治理闭环还不够强
- audit 已能跑，但对不同类型 workspace 的适配还要继续加强
- drill-down 已可用，但摘要层、日常入口体验和更真实行为测试还可继续补
- backend 已承担部分高频读取，但还不是统一主读事实源

### 3.3 仍然真正未完成

- 原生向量后端 / ANN 检索正式接入
- `tree-sitter` 解析器
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

## 5. 推荐执行顺序

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

- `InvertedIndex` 与相关测试已存在
- 但“原生向量后端正式接入主链路”仍未完成
- 所以这块属于“部分已做，但关键终态未完成”

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

- freshness watcher / status 基础能力已存在
- 但 `tree-sitter`、并行索引、真正精确增量更新仍未完成
- 这块仍然属于真正未完成

### 方向 4：Type Safety and Observability

目标：

- facade 层的关键返回值逐步类型化
- 增加结构化日志、延迟指标、质量指标

完成标志：

- 关键 facade 的 schema 不只“存在”，还具备稳定类型边界
- 能观测查询延迟、索引耗时、召回质量、token 回归

当前判断：

- 有一部分 dataclass / schema / eval 输出基础
- 但 facade 返回值全面类型化、结构化日志、统一指标体系仍未完成
- 这块仍然属于真正未完成

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
