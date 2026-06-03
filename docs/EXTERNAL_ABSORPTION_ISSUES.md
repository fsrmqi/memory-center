# External Absorption Issue Drafts / 外部能力吸收 Issue 草案

本文档把 [docs/NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md) 中外部能力吸收项，整理成可直接发布的 issue 草案。

使用原则：

- 每个 issue 都尽量是可以独立推进和验证的纵向切片
- `AFK` 表示可以直接开发推进
- `HITL` 表示中途需要做明确的评审或决策
- `Blocked by` 只写最直接的依赖

---

## CodeGraph

### Issue 1. Freshness Banner 接入主查询链路

- **Type**: AFK
- **Blocked by**: None - can start immediately

#### What to build

将 freshness 状态并入核心查询输出，让 `mc_lookup` 在命中 stale / pending 文件时明确提示需要读取 live file 验证，而不是只在独立工具里暴露 freshness。

#### Acceptance criteria

- [ ] `mc_lookup` 返回结构中包含 freshness 字段
- [ ] query 命中 stale / pending 文件时，返回结果中出现明确 freshness 提示
- [ ] query 未命中 stale 文件时，只返回弱提示或不提示
- [ ] MCP / HTTP / CLI 的 freshness 提示口径一致

### Issue 2. Context Pack 进入默认推荐工作流

- **Type**: AFK
- **Blocked by**: Issue 1

#### What to build

让 `mc_context_pack` 成为架构问答、变更分析前的默认推荐入口，并在 `mc_start` / `mc_lookup` 的提示与文档里明确这条工作流。

#### Acceptance criteria

- [ ] 对架构类查询返回明确的 “先 pack 后 deep dive” 推荐
- [ ] `mc_context_pack` 的返回结构在文档中被正式说明
- [ ] 至少有一组行为测试覆盖推荐逻辑
- [ ] `mc_start` / `mc_lookup` 的推荐行为不破坏现有兼容性

### Issue 3. Context Pack 完成 freshness / snippet 闭环

- **Type**: AFK
- **Blocked by**: Issue 1, Issue 2

#### What to build

补全 `ContextPackBuilder` 当前缺失的 freshness 集成与 snippet 提取能力，让 context pack 不再只返回结构信息，而是能提供最小必要上下文闭环。

#### Acceptance criteria

- [ ] `ContextPackBuilder` 的 `freshness` 字段不再是空对象占位
- [ ] `snippets` 至少能覆盖 top entrypoints 的最小代码片段
- [ ] token estimate 不显著失控
- [ ] 至少有一组测试覆盖 freshness + snippet 同时生效的场景

### Issue 4. Watcher 事件驱动增量索引桥接

- **Type**: AFK
- **Blocked by**: Issue 1

#### What to build

把 watcher 事件从“状态观测”推进到“增量索引触发”，通过 changed-file queue + debounce 机制驱动增量更新。

#### Acceptance criteria

- [ ] watcher 事件可进入 changed-file queue
- [ ] debounce 后触发增量索引，而不是重复全量重建
- [ ] 修改单个 Java/YAML 文件后，索引能在可接受时间内更新
- [ ] 至少有一个端到端增量测试

### Issue 5. Connect-time Catch-up 与 stale 恢复策略

- **Type**: AFK
- **Blocked by**: Issue 4

#### What to build

在服务启动或首次查询前，识别明显过期的索引状态，并根据场景执行自动 catch-up 或给出明确的人工恢复建议。

#### Acceptance criteria

- [ ] 首次查询前能发现 pending / stale 状态
- [ ] 能区分“自动 catch-up”与“只提示人工 reindex”的场景
- [ ] MCP / HTTP 启动路径中可以复用这套判断
- [ ] 文档中有相应操作说明

### Issue 6. Tree-sitter Java Parser Spike

- **Type**: HITL
- **Blocked by**: None - can start immediately

#### What to build

实现 Java / Spring Cloud `tree-sitter` 解析器原型，并对比现有 regex parser，形成替换范围、兼容策略和风险评估结论。

#### Acceptance criteria

- [ ] 有可运行的 `TreeSitterJavaParser` 原型
- [ ] 有与现有 regex parser 的对照测试
- [ ] 有复杂注解、多行泛型、内部类等样例差异报告
- [ ] 形成“继续推进 / 暂缓”的明确评审结论

### Issue 7. FTS / 倒排检索统一收口

- **Type**: AFK
- **Blocked by**: Issue 6

#### What to build

统一 file / symbol / snippet / sparse retrieval 的候选集策略，减少全量扫描与重复排序，并与现有 hybrid retrieval 主链路兼容。

#### Acceptance criteria

- [ ] query latency 与 candidate size 可观测
- [ ] 高频 query 不再退化为全量扫描
- [ ] 与现有 hybrid retrieval 兼容
- [ ] 至少有一组 benchmark 或行为测试验证收敛效果

### Issue 8. Context Pack Benchmark 与采用率观测

- **Type**: AFK
- **Blocked by**: Issue 2, Issue 3

#### What to build

量化 context pack 对 token、tool calls、首答可用率的收益，并把结果接到 `work-health` 或 `mc_admin`。

#### Acceptance criteria

- [ ] 至少有一组 A/B benchmark 输出
- [ ] 能看到 context pack adoption 与收益趋势
- [ ] benchmark 报告可通过 CLI 或 MCP 获取
- [ ] 指标定义在文档中清晰可见

### Issue 9. Workspace Daemon 可行性研究

- **Type**: HITL
- **Blocked by**: Issue 4, Issue 5

#### What to build

评估是否值得引入共享后台 daemon / warm state，并分析多 Agent / 多窗口共享场景的性能收益与复杂度成本。

#### Acceptance criteria

- [ ] 输出启动耗时分析
- [ ] 输出 watcher / SQLite / graph 预热成本拆分
- [ ] 输出 daemon 方案草图
- [ ] 给出“值得做 / 暂不做 / 需要前置条件”的明确结论

---

## Understand-Anything

### Issue 10. Guided Tour 生成器主链路化

- **Type**: AFK
- **Blocked by**: None - can start immediately

#### What to build

把 architecture tour 从辅助能力推进成正式输出，让新人或接手者可以按推荐顺序理解系统入口、核心服务和关键依赖。

#### Acceptance criteria

- [ ] tour 可通过 MCP / HTTP 获取
- [ ] 至少覆盖 workspace / service 两种范围
- [ ] tour 输出结构稳定，包含步骤、解释和关联引用
- [ ] 文档中提供推荐使用方式

### Issue 11. 统一 Explanation Schema

- **Type**: AFK
- **Blocked by**: Issue 10

#### What to build

统一 entity / service / task explanation 输出结构，让 drill-down、context pack、onboarding 共享一套解释资产。

#### Acceptance criteria

- [ ] drill-down / context pack / onboarding 的解释字段对齐
- [ ] explanation 至少包含摘要、关系、业务意义、风险四层
- [ ] 相同节点在不同入口的解释口径一致
- [ ] 有对应测试或快照校验

### Issue 12. Business Flow 正式输出

- **Type**: AFK
- **Blocked by**: Issue 10, Issue 11

#### What to build

让 business flow 成为稳定输出，而不是只停留在底层实验模块，并支持从 endpoint / feign / mq / config 组合出可读业务流。

#### Acceptance criteria

- [ ] 核心 Spring Cloud 示例仓库中能稳定提取若干业务流
- [ ] flow 输出可在 MCP 返回中展示
- [ ] flow schema 明确包含 domain / flow / step
- [ ] handoff / onboarding 至少有一处复用 flow 资产

### Issue 13. Flow-Aware Impact

- **Type**: AFK
- **Blocked by**: Issue 12

#### What to build

让影响分析不仅返回“影响谁”，还返回“影响哪段业务流”，并将 flow segment 接入 plan / checklist。

#### Acceptance criteria

- [ ] impact 输出可标注受影响 flow segment
- [ ] plan / checklist 可引用 flow 阶段信息
- [ ] DTO / Feign / MQ 变更场景至少覆盖一类 flow-aware 输出
- [ ] 有对应行为测试

### Issue 14. Persona 视角输出

- **Type**: HITL
- **Blocked by**: Issue 11

#### What to build

定义第一版 persona 输出策略，为 `developer / architect` 等角色提供不同粒度的解释模板。

#### Acceptance criteria

- [ ] 至少支持 developer / architect 两种稳定 persona
- [ ] 两种 persona 的输出差异可见且可解释
- [ ] `mc_onboard` 或相关入口支持 persona 参数
- [ ] 形成是否继续扩展到 product / tester 的评审结论

### Issue 15. 理解资产增量刷新

- **Type**: AFK
- **Blocked by**: Issue 12, Issue 13

#### What to build

让 flow / tour / domain 这类理解资产支持增量刷新，不再每次都全量重算。

#### Acceptance criteria

- [ ] 局部代码变更后，无需全量重算全部理解资产
- [ ] 增量刷新与 freshness 状态联动
- [ ] flow / tour / domain 至少各有一类增量刷新路径
- [ ] 有对应端到端或集成测试

---

## ECC

### Issue 16. Workflow Protocol Profiles

- **Type**: AFK
- **Blocked by**: None - can start immediately

#### What to build

将不同任务类型映射为推荐 workflow profile，明确 Memory Center 的推荐工具顺序和执行协议。

#### Acceptance criteria

- [ ] 至少覆盖 quick-fix / contract-change / long-task / architecture 四类 profile
- [ ] 每类 profile 有明确推荐工具顺序
- [ ] 文档中能看到 profile 说明
- [ ] workflow orchestration eval 能识别 profile 执行情况

### Issue 17. Verification Loop 强化

- **Type**: AFK
- **Blocked by**: Issue 16

#### What to build

强化 `analyze -> checklist -> verify -> close` 闭环，让 verify 阶段和 close 阶段的输出更明确、更统一。

#### Acceptance criteria

- [ ] verify / close 输出口径统一
- [ ] contract-change 类任务能看到更清晰的验证闭环
- [ ] 至少有一组行为测试覆盖 verify loop
- [ ] 文档里明确推荐用法

### Issue 18. Pattern Promotion Pipeline

- **Type**: HITL
- **Blocked by**: None - can start immediately

#### What to build

定义 case / rule / skill 候选的晋升标准，并形成从历史经验到可复用模式的第一版晋升管道。

#### Acceptance criteria

- [ ] 形成清晰的晋升规则
- [ ] 有候选输出结构
- [ ] 至少能从历史 case 中提取候选模式
- [ ] 形成是否继续自动化推进的评审结论

### Issue 19. Learned Heuristics Register

- **Type**: AFK
- **Blocked by**: Issue 18

#### What to build

建立长期启发式注册表，记录 heuristic 的来源、置信度、命中记录和可追溯信息。

#### Acceptance criteria

- [ ] 每条 heuristic 可追溯来源与置信度
- [ ] 至少记录最近命中信息
- [ ] registry 可被查询或导出
- [ ] 有最小文档说明

### Issue 20. Agent Runtime Audit

- **Type**: AFK
- **Blocked by**: Issue 17

#### What to build

在 completion audit 里加入 agent runtime config 治理，包括 hooks / MCP / agent config 的风险项检查。

#### Acceptance criteria

- [ ] audit 能输出 hooks / MCP / agent config 的治理问题
- [ ] 至少覆盖配置漂移、危险暴露、重复 hook 等一类风险
- [ ] runtime audit 与现有 audit 结果可共存
- [ ] 文档里明确 audit 范围

### Issue 21. Agent Usage Bundle Export

- **Type**: AFK
- **Blocked by**: Issue 16, Issue 20

#### What to build

导出面向常见 agent 宿主的最小使用 bundle，把最佳实践转成可安装的 command / prompt / skill / hook 配置包。

#### Acceptance criteria

- [ ] 至少能导出一组适用于 Codex / Claude Code / Cursor 的最小 bundle
- [ ] bundle 内容可解释、可追踪来源
- [ ] 文档中说明 bundle 的用途与安装方式
- [ ] 至少有一组导出行为测试或 smoke
