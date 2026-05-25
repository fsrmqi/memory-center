# Memory Center 下一阶段总方案 / Next Phase Master Plan

> 目标：把 Memory Center 从“功能丰富的项目记忆工具”推进成“真正提升日常效率的多模型协作底座”。

---

## 一、最终目标

这份方案的目标不是继续堆功能，而是围绕日常使用体验，系统性解决以下问题：

1. 模型切换后任务断裂
2. 会话中断后上下文丢失
3. 大项目返回过肥，token 消耗过高
4. 多工具产生了证据，但无法自然复用
5. 写入、恢复、交接、回放、观测之间存在割裂
6. 大 workspace 每次全量重建索引过慢

最终理想状态：

- 不同模型之间可低损接棒
- 不同会话之间可持续恢复
- 不同工具证据可按需展开
- 模型默认只吃轻量上下文
- 写入链、恢复链、交接链都可评估、可观测、可回放
- 常用操作可通过一键工作流完成

---

## 二、设计原则

### 1. 默认轻量

- 所有高频返回默认 `compact`
- 所有 `compact` 返回支持 `budget=small|medium|large`
- 原始细节通过 `ref_id` 按需展开

### 2. 渐进披露

- 第一层：摘要
- 第二层：结构化证据
- 第三层：原始详情

### 3. 多入口一致

同一能力必须在以下入口保持一致：

- CLI
- MCP
- HTTP
- HTML / Web 工作台

### 4. 先做高频动作

优先优化这些日常高频路径：

- 开始任务
- 找类 / 找调用链
- 会话记录
- 恢复任务
- 交接模型
- 查看全局状态
- 增量索引

---

## 三、一次性整体改造的 6 个工作包

### 当前完成度总览

| 工作包 | 当前状态 | 已实现 | 仍待推进 |
|---|---|---|---|
| 工作包 1：增量索引系统 | `进行中` | `reindex --project`、`--path`、`--changed-only`、`--scope staged|head|all` 第一版已落地 | 真正的局部 graph rebuild、局部 semantic rebuild、更精细的 changed-only 更新 |
| 工作包 2：统一轻量上下文协议 | `大部分完成` | `view=compact|full`、`budget=small|medium|large` 已覆盖高频大返回 | 更细的 token 估算与模型偏好预算映射 |
| 工作包 3：统一引用与时间线系统 | `大部分完成` | `ref_id + summary`、`memory_ref_get`、`memory_ref_batch`、timeline 短引用化 | 更彻底的 `timeline <-> ref` 双向导航与页面级 drill-down |
| 工作包 4：一键工作流系统 | `大部分完成` | `work-start/work-log/work-sync/work-resume/work-handoff/work-close/work-health` 已覆盖 CLI/MCP/HTTP | 更强的自动策略编排与 workflow 质量评测 |
| 工作包 5：可视化工作台 | `进行中` | `/ui`、`/ui/dashboard`、`/ui/continuity`、`/ui/task`、`/ui/timeline`、`/ui/receipts`、`/ui/usage`、`/ui/backend`、`/ui/index-freshness` | 更强交互、筛选、联动、展开细节、常驻更像产品 |
| 工作包 6：统一后端与评测体系 | `进行中` | SQLite `memory.db` 镜像后端、后端查询入口、`memory_eval_*` 增强、`timeline/recent_sessions/session_summary/write_receipts` 优先复用 SQLite 读路径 | 更深层查询路径切换到 SQLite、真正统一 backend 策略、更多长期趋势评测 |

### 当前阶段判断

当前系统已经从“功能集合”推进到了“可日常使用的协作底座”，但还没有达到“全部实现”的验收状态。  
离最终目标最近的剩余重点是：

1. 让增量索引从第一版变成更真实的局部重建
2. 让 SQLite 后端从镜像/局部查询推进到更多真实读路径
3. 让工作台从可看推进到更强交互和联动
4. 做一轮更系统的 completion audit 与文档一致性审计

## 工作包 1：增量索引系统

### 目标

让大 workspace 不再每次全量 `reindex`。

### 交付内容

- `reindex --project <name>`
- `reindex --path <path>`
- `reindex --changed-only`
- `reindex --scope staged|unstaged|all`
- 基于 `memory_detect_changes` 的变更文件收集
- 局部更新：
  - `file-index.json`
  - `java-symbol-index.json`
  - `api-index.json`
  - `feign-index.json`
  - `mq-index.json`
  - `config-index.json`
- 局部 `service-topology` 刷新
- 局部 graph rebuild
- 局部 semantic index rebuild

### 验收标准

- 改一个项目时只重建该项目索引
- 改几处文件时可只重建对应路径
- 局部重建后 `status`、`query`、`impact` 一致性不丢

---

## 工作包 2：统一轻量上下文协议

### 目标

继续压缩 token，统一所有大返回的轻量行为。

### 当前基础

已存在：

- `view=compact|full`
- `budget=small|medium|large`
- `short refs`

### 继续增强

- 覆盖全部高频大返回：
  - `workspace_sniff`
  - `workspace_status`
  - `workspace_resume_packet`
  - `workspace_recent_evidence`
  - `workspace_continuity_dashboard`
  - `workspace_dashboard`
  - `workspace_handoff_packet`
- 引入统一预算器
- 记录每种 budget 的命中规模
- 增加模型偏好预算映射

### 验收标准

- 模型侧默认拿到 `compact + medium`
- `small` 明显少于 `large`
- 不丢决策必要字段

---

## 工作包 3：统一引用与时间线系统

### 目标

把 refs、receipts、timeline 收成一个统一 substrate。

### 交付内容

- 统一 `ref_id`
- 统一 `summary`
- 统一 `kind`
- 统一 `raw locator`
- `memory_ref_get`
- `memory_ref_batch`
- `timeline_item -> ref`
- `ref -> timeline`
- 所有高频 evidence 默认返回短引用

### 重点对象

- `session_event`
- `write_receipt`
- `handoff`
- `source_ref`
- `evidence_ref`
- `payload_ref`

### 验收标准

- 任意短引用都可展开
- timeline 中所有关键事件都可追溯
- dashboard / resume / handoff / recent_evidence 使用统一短引用体系

---

## 工作包 4：一键工作流系统

### 目标

把复杂链路收成自然的日常命令。

### 交付内容

- `work-start`
- `work-log`
- `work-sync`
- `work-close`
- `work-resume`
- `work-handoff`
- `work-health`

### 推荐命令语义

- `work-start`
  - sniff
  - lookup hint
  - 可选 sync-sniff
  - start-session

- `work-close`
  - end-session
  - sync-case
  - record-case

- `work-health`
  - regression smoke
  - usage report
  - quality eval

### 验收标准

- 高频日常动作不需要手拼 5 到 8 条命令
- 一次命令能完成一个工作阶段

---

## 工作包 5：可视化工作台

### 目标

让 Memory Center 成为真正能每天打开的工作台。

### 交付内容

#### 第一阶段

- 增强版 HTML 导出
- 更清晰的 dashboard sections
- budget / compact 命中情况展示
- refs 可展开提示

#### 第二阶段

- 本地常驻 Web UI
- 任务详情页
- timeline 页
- receipt 页
- usage report 页
- index freshness 页

### 验收标准

- 不查命令也能理解当前状态
- 每天打开看一眼就知道当前该做什么

---

## 工作包 6：统一后端与评测体系

### 目标

让这套系统长期更稳、更好维护。

### 后端增强

- 保留当前文件系统模式
- 增加可选 `sqlite unified backend`
  - session summaries
  - write receipts
  - handoff history
  - case atoms
  - refs metadata

### 评测增强

- `memory_eval_write_quality`
- `memory_eval_resume`
- `memory_eval_handoff`
- `memory_eval_regression_suite`
- 新增：
  - `memory_eval_index_freshness`
  - `memory_eval_tool_adoption`
  - `memory_eval_context_weight`

### 验收标准

- 每次升级后可一键跑完整回归
- 能量化“这版是不是更省 token / 更适合模型”

---

## 四、推荐实施顺序

如果不是分散地做，而是作为连续工程推进，我建议顺序如下：

1. 增量索引系统
2. 统一轻量上下文协议
3. 统一引用与时间线系统
4. 一键工作流系统
5. 可视化工作台
6. 统一后端与评测体系

这样做的原因：

- 先解决大项目实际使用痛点
- 再解决模型侧 token 问题
- 然后收口底层数据结构
- 最后做体验层和平台层

---

## 五、面向日常使用的最终状态

理想情况下，日常工作流应变成：

1. 开始任务：`work-start`
2. 找入口：`lookup-hint`
3. 只改局部：`reindex --changed-only`
4. 模型拿 `compact + medium`
5. 要细节时：`memory_ref_get`
6. 中途换模型：`work-handoff`
7. 第二天继续：`work-resume`
8. 收尾：`work-close`
9. 打开工作台看全局状态

---

## 六、收益排序

如果只按“真正提升效率”的角度排序，收益最高的是：

1. 增量索引
2. 预算化轻量返回
3. 一键工作流
4. 常驻工作台
5. 统一后端
6. 更完整评测

---

## 七、当前状态说明

截至当前版本，以下能力已经有基础或已部分完成：

- 分层记忆 `L0/L1/L2/L3`
- write governance
- receipts / replay / eval
- resume / handoff / dashboard
- compact/full 视图
- `budget=small|medium|large`
- short refs
- `memory_ref_get / memory_ref_batch`
- `regression-smoke`
- first-step SQLite unified memory mirror (`memory.db`)

因此这份文档不是从零规划，而是下一阶段的统一收口方案。

---

## 八、外部参考与吸收方向

以下外部项目已经被纳入本方案的参考范围，目的不是照搬，而是吸收对日常使用体验最有价值的部分。

### 参考落地时机总览

| 参考来源 | 当前阶段立即做 | 下一阶段继续做 | 后续产品化阶段再做 |
|---|---|---|---|
| `mattpocock/skills` | `work-*` 一键工作流、低 token 输出风格 | 更强约束的 workflow 模板、面向模型的超压缩输出 | 更完整的 skill 体系与自动生成 |
| `rohitg00/agentmemory` | `compact/full + budget`、short refs、`memory_ref_get / batch`、`memory_eval_context_weight` | 正式 token benchmark、top-K only 策略加强、hybrid retrieval 优化 | 更深层数据库化与长期成本对比 |
| `Understand-Anything` | `/ui/dashboard`、`/ui/continuity`、`/ui/task`、`/ui/timeline`、`/ui/usage`、`/ui/backend`、`/ui/index-freshness` | guided tour、任务学习路径、页面联动 | 更强交互式图形体验与 persona-adaptive UI |

### 1. `mattpocock/skills`

最值得借鉴的是：

- 把高频工程动作收成 skill / workflow
- 用超压缩输出降低 token
- 把 handoff 做成结构化技能，而不是临时口头说明

已吸收：

- `work-start / work-sync / work-resume / work-handoff / work-close / work-health`
- 低 token 的 `compact + budget`

还可继续吸收：

- 更强约束的 workflow skill 模板
- 面向不同模型的超压缩输出模式

建议落地时机：

- 当前阶段：保持现有 `work-*` 工作流持续打磨
- 下一阶段：把 workflow 模板再标准化，减少模型自由发挥
- 后续阶段：再考虑 skill 自动生成与更大规模 skill 市场化组织

### 2. `rohitg00/agentmemory`

最值得借鉴的是：

- 用 benchmark 驱动 token 优化
- top-K only 的上下文策略
- `BM25 + vector + graph` 组合检索思路
- “记忆数据库”而不是“把所有内容喂进上下文”

已吸收：

- `compact/full`
- `budget=small|medium|large`
- `short refs`
- `memory_ref_get / memory_ref_batch`
- `memory_eval_context_weight`

还可继续吸收：

- 更正式的 token benchmark
- 更系统的向量 / hybrid 检索权重策略

建议落地时机：

- 当前阶段：继续沿 `compact + budget + short refs` 这条线收口
- 下一阶段：补 benchmark、top-K only 和 hybrid retrieval 的量化验证
- 后续阶段：再考虑更深的数据库化与长期成本仪表盘

### 3. `Lum1104/Understand-Anything`

最值得借鉴的是：

- 图不是为了炫技，而是为了教学和导航
- 交互式 dashboard / guided tour
- 结构图、timeline、usage、diff/impact 可视化

已吸收：

- `/ui/dashboard`
- `/ui/continuity`
- `/ui/task`
- `/ui/timeline`
- `/ui/receipts`
- `/ui/usage`
- `/ui/backend`
- `/ui/index-freshness`

还可继续吸收：

- guided tour / onboarding
- 更强的人设/视角自适应视图
- 更深入的图形交互

建议落地时机：

- 当前阶段：把现有工作台页面补全到能日常看
- 下一阶段：加入 guided tour / onboarding 与 task/timeline 联动
- 后续阶段：再做更重的交互图与 persona-adaptive UI
