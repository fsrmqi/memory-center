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

因此这份文档不是从零规划，而是下一阶段的统一收口方案。
