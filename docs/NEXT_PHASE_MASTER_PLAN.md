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

| 工作包 | 当前状态 | 已交付 | 后续可迭代方向 |
|---|---|---|---|
| 工作包 1：增量索引系统 | ✅ 已交付 | `reindex --project`、`--path`、`--changed-only`、`--scope staged|head|all`、局部 JSON index merge、局部 graph rebuild（`partial_rebuild`）、局部 semantic rebuild（`build_workspace_semantic_index_partial`）、删除文件检测与处理、语义 IDF 一致性修复、跨项目 Feign→Endpoint 边保留、`semantic_index_stats` 统一 `read_json_prefer_backend`、`read_json` 全面替换 | 更细粒度的增量策略（如 file-level diff-based partial rebuild） |
| 工作包 2：统一轻量上下文协议 | ✅ 已交付 | `view=compact|full`、`budget=small|medium|large` 已覆盖全部 7 个高频大返回（含 `workspace_recent_evidence`）、模型偏好预算映射（`MODEL_BUDGET_PROFILES`）、handoff packet 使用目标模型预算、`token_utils` 估算函数、`tracking` token gain 日志、工具专用 payload 压缩器（git/pytest/grep）、`memory_eval_token_gain`、compact 函数内置 gain 测量 | rtk discover 模式、per-command 压缩器矩阵扩展 |
| 工作包 3：统一引用与时间线系统 | ✅ 已交付 | `ref_id + summary`、`memory_ref_get`（含 `timeline_ref` 反向导航）、`memory_ref_batch`、timeline 短引用化、`/ui/ref` 已落地 + "在时间线中查看"交叉链接 | timeline↔ref 页面联动 drill-down、高频接口严格默认短引用模式 |
| 工作包 4：一键工作流系统 | ✅ 已交付 | CLI `work-start/work-log/work-sync/work-resume/work-handoff/work-close/work-health`、`memory_eval_workflow_orchestration` 工作流编排评测、**MCP facade 工具重构（82→8：mc_start/mc_lookup/mc_analyze/mc_sync/mc_resume/mc_handoff/mc_close/mc_admin）**、**Hook 声明式规范与 runner/adapters 基础已实现（hooks.yaml + run-hook runner + Claude Code adapter + Codex/Cursor placeholder）** | 更强约束的 workflow 模板、mc_admin 拆分（如未来需要）、Codex/Cursor adapter 丰富化、宿主真实生命周期自动接入 |
| 工作包 5：可视化工作台 | ✅ 大部分已交付 | `/ui` 侧栏导航 + 快速入门指引、`/ui/dashboard` 筛选表单 + budget/compact 下拉切换、`/ui/task` 跨页链接到 timeline、`/ui/timeline` 链接到 ref + 内联 `<details>` 展开、`/ui/receipts` 筛选 + 内联展开、`/ui/backend` 筛选、`/ui/receipts` 筛选、`/ui/continuity` + budget/compact 切换、`/ui/usage`、`/ui/index-freshness`、所有列表渲染函数支持 `<details>` 展开 | guided tour / onboarding 交互、更多页面 budget/compact 切换 |
| 工作包 6：统一后端与评测体系 | ✅ 已交付 | SQLite `memory.db` 镜像后端（含 `index_mirror` 表）、后端查询入口支持 project/type 过滤、确定性索引读路径切换到 `read_json_prefer_backend`（workspace status / query / impact / eval / group / wiki / semantic）、`memory_eval_*` 增强（含 `workflow_orchestration`、`token_gain`、`token_benchmark` 评测） | 更多主读路径切到 SQLite、长期趋势仪表盘 |

### 当前阶段判断

当前系统已经从”功能集合”推进到了”可日常使用的协作底座”，6 个工作包全部达到已交付状态。

**已完成的收口项（v2.0.10 之后新增）：**

1. ~~**WP1 增量索引**~~：**已完成**
2. ~~**rtk-ai/rtk 吸收**~~：**已完成** — token 估算、gain 日志、payload 压缩器、eval_token_gain
3. ~~**MCP facade 重构**~~：**已完成** — 82→8 facade 工具，92% token 减少
4. ~~**WP2 recent_evidence 收口**~~：**已完成** — 新增 `view=compact|full` 参数，`view=full` 返回完整条目，`view=compact` 走压缩 + `log_token_gain`
5. ~~**WP3 ref→timeline 反向导航**~~：**已完成** — `memory_ref_get` 返回 `timeline_ref` 字段，`/ui/ref` 页面新增”在时间线中查看”链接
6. ~~**WP5 refs 内联展开**~~：**已完成** — 所有列表渲染函数添加 `<details><summary>` 展开
7. ~~**WP5 budget/compact UI 切换**~~：**已完成** — Dashboard 和 Continuity 页面新增 view/budget `<select>` 控件
8. ~~**WP3 默认 compact**~~：**已完成** — 全部 7 高频函数默认 view 从 full 改为 compact
9. ~~**WP3 compact 收紧**~~：**已完成** — compact 模式下 recent_evidence/receipts/handoffs/focus_task 全部提取为严格短引用
10. ~~**Hooks 收口**~~：**已完成** — Codex adapter chmod +x、Cursor adapter 增强 MCP 命令指令

**下一阶段待推进（按优先级）：**

1. **外部参考思想吸收**：agentmemory benchmark/top-K/hybrid、skills 强约束模板
2. **timeline↔ref 页面联动**：timeline 中点击 ref 直接展开而非跳转
3. **长期趋势仪表盘**：token benchmark 趋势化、index freshness 长期对比
4. **SQLite 后端**：从镜像推进到更多真实读路径（优先级最低，最后推进）

### 版本技术路线

| 版本 | 聚焦工作包 | 核心交付 | 当前状态 |
|---|---|---|---|
| v2.0.8 | WP4 MCP facade | 82→8 facade 工具、hooks.yaml + runner + adapters | ✅ 已交付 |
| v2.0.9 | WP1 增量索引 | `--project/--path/--changed-only`、局部 graph/semantic rebuild、IDF 一致性、跨项目边保留 | ✅ 已交付 |
| v2.0.9 | WP6 评测体系 | 7 个 eval 工具 + token_gain、SQLite memory.db + index_mirror | ✅ 已交付 |
| v2.0.10 | WP2/WP3 收口 | `recent_evidence` view/gain、`memory_ref_get` timeline_ref、短引用体系 | ✅ 已交付 |
| v2.0.10 | WP5 交互增强 | budget/compact UI 下拉切换、`<details>` 内联展开、ref→timeline 交叉链接 | ✅ 已交付 |
| v2.0.11 | WP5 深化 | guided tour overlay（首次打开 /ui 引导）、Next Action hero 卡片（dashboard 显示下一步）、continuity→task / task→receipts 跨页 drill-down | ✅ 已交付 |
| v2.0.11 | WP3 深化 | 全部 7 高频函数默认 view=compact、compact 模式收紧为严格短引用（ref_id+summary only） | ✅ 已交付 |
| v2.0.11 | Hooks 收口 | Codex adapter 生产化（chmod +x）、Cursor adapter 增强（MCP 命令指令 + Quick Reference） | ✅ 已交付 |
| v2.1.0 | 外部吸收 | agentmemory token benchmark（7 高频函数）+ top-K evidence（3/5/10），skills 强约束模板、hybrid retrieval | 进行中 |
| v2.1.0 | WP3/WP5 联动 | timeline↔ref 页面联动、长期趋势仪表盘 | 待推进 |
| v2.2.0 | WP6 深化 | 更多主读路径切 SQLite、长期趋势仪表盘深化 | 最后推进 |

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
2. 外部参考思想吸收
3. 统一轻量上下文协议
4. 统一引用与时间线系统
5. 一键工作流系统
6. 可视化工作台
7. 统一后端与评测体系

这样做的原因：

- 先解决大项目实际使用痛点
- 再把外部项目里最值钱的“降 token / 强工作流 / 强检索”思路真正内化
- 然后收口底层数据结构
- 最后做体验层和平台层

### 当前主线（WP1 + rtk 已完成后的下一步）

WP1（增量索引）和 rtk-ai/rtk 吸收都已完成，下一阶段优先顺序：

1. `rohitg00/agentmemory`
   - 正式 token benchmark
   - top-K only
   - hybrid retrieval 强化
2. `mattpocock/skills`
   - 更强约束的 workflow 模板
   - 更激进的超压缩输出模式
3. `Understand-Anything`
   - guided tour
   - onboarding
   - 页面联动
4. 更系统的 completion audit 与文档一致性审计
5. SQLite 后端进一步接管统一读取（优先级最低，最后推进）

---

## 五、面向日常使用的最终状态

理想情况下，日常工作流应变成：

1. 开始任务：`mc_start`（或 `work-start` CLI）
2. 找入口/查代码：`mc_lookup` mode=auto（自动路由到最佳检索策略）
3. 修改代码前：`mc_analyze`（影响面+规则检查+契约检查）
4. 保存进度：`mc_sync`
5. 只改局部：`reindex --changed-only`
6. 模型拿 `compact + medium`
7. 要细节时：`mc_lookup` mode=ref（展开短引用）
8. 中途换模型：`mc_handoff`
9. 第二天继续：`mc_resume`
10. 收尾：`mc_close`

**推荐 Hook 映射补充（需宿主支持）：**

- SessionStart → 自动 sniff 加载工作区上下文
- PreToolUse (Edit|Write) → 自动 check-rules 检查架构规则
- Stop → 自动 end-session 关闭并同步
- UserPromptSubmit → LLM 判断是否编码任务，提醒调用 mc_start

---

## 六、收益排序

如果只按”真正提升效率”的角度排序，收益最高的是：

1. ~~增量索引~~ **已完成**
2. ~~命令输出前置压缩层 / token gain 观测（rtk）~~ **已完成**
3. ~~MCP facade 重构~~ **已完成**（82→8 facade 工具，92% token 减少）；Hook 事件映射 **基础已实现** — hooks.yaml + run-hook runner + Claude Code adapter，但宿主自动挂接仍待各宿主侧落地
4. token benchmark + top-K only + hybrid retrieval（agentmemory）
5. 更强约束的 workflow 模板（mattpocock/skills）
6. 常驻工作台 guided tour + timeline↔ref 页面联动
7. 统一后端（SQLite 优先级最低，最后推进）
8. 更完整评测

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
- **token 估算与 gain 观测**（`token_utils.py` + `tracking.py`）
- **工具专用 payload 压缩器**（git/pytest/grep Stats Extraction / Failure Focus / Grouping）
- **`memory_eval_token_gain`** per-tool savings 评测
- **增量索引真正可用**（IDF 一致性修复、跨项目边保留、read_json_prefer_backend 全面统一）
- **MCP facade 工具重构**（82→8：mc_start/mc_lookup/mc_analyze/mc_sync/mc_resume/mc_handoff/mc_close/mc_admin，token 开销从 ~28k 降至 ~2.3k）
- **推荐 Hook 映射**（SessionStart→sniff、PreToolUse→check-rules、Stop→close、UserPromptSubmit→任务类型判断，需宿主支持）
- **CLAUDE.md facade 路由规则**（明确每个 facade 的触发场景和自动行为）

因此这份文档不是从零规划，而是下一阶段的统一收口方案。

---

## 八、外部参考与吸收方向

以下外部项目已经被纳入本方案的参考范围，目的不是照搬，而是吸收对日常使用体验最有价值的部分。

### 参考落地时机总览

| 参考来源 | 当前阶段立即做 | 下一阶段继续做 | 后续产品化阶段再做 |
|---|---|---|---|
| `mattpocock/skills` | `work-*` 一键工作流、低 token 输出风格、**MCP facade 工具重构（82→8）**、**推荐 Hook 映射设计** | 更强约束的 workflow 模板、面向模型的超压缩输出 | 更完整的 skill 体系与自动生成 |
| `rohitg00/agentmemory` | `compact/full + budget`、short refs、`memory_ref_get / batch`、`memory_eval_context_weight`、**facade mc_lookup 统一检索路由**、**`memory_eval_token_benchmark`（7 高频函数）**、**recent_evidence top-K only（3/5/10）** | hybrid retrieval 优化、更正式的长期 benchmark 趋势化 | 更深层数据库化与长期成本对比 |
| `Understand-Anything` | `/ui/dashboard`、`/ui/continuity`、`/ui/task`、`/ui/timeline`、`/ui/usage`、`/ui/backend`、`/ui/index-freshness` | guided tour、任务学习路径、页面联动 | 更强交互式图形体验与 persona-adaptive UI |
| `rtk-ai/rtk` | `compact/full + budget`、short refs、工作流压缩思路、**`token_utils`**、**`tracking` gain 日志**、**工具专用 payload 压缩器（git/pytest/grep）**、**`memory_eval_token_gain`** | rtk discover 模式、更完整命令压缩器矩阵、per-model 趋势仪表盘 | 更强的代理层、自动命令重写与长期压缩策略 |

### 1. `mattpocock/skills`

最值得借鉴的是：

- 把高频工程动作收成 skill / workflow
- 用超压缩输出降低 token
- 把 handoff 做成结构化技能，而不是临时口头说明

已吸收：

- `work-start / work-sync / work-resume / work-handoff / work-close / work-health`
- 低 token 的 `compact + budget`
- **MCP facade 工具重构（82→8 个任务级 facade）**：把原子工具从"实现层接口"重构为"任务层接口"，模型选择成本从 82 个选项降到 8 个
- **推荐 Hook 映射**：SessionStart→sniff、PreToolUse→check-rules、Stop→close、UserPromptSubmit→任务类型判断，需宿主支持

还可继续吸收：

- 更强约束的 workflow skill 模板
- 面向不同模型的超压缩输出模式
- 更强的 workflow 质量评测

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

- 更系统的向量 / hybrid 检索权重策略
- benchmark 趋势化与长期回归基线
- 更强的 top-K only 与预算量化体系

建议落地时机：

- 当前阶段：继续沿 `compact + budget + short refs` 这条线收口，并保持 benchmark / top-K 结果可回归
- 下一阶段：补 hybrid retrieval 的量化验证与 benchmark 趋势化
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

### 4. `rtk-ai/rtk`

最值得借鉴的是：

- 把命令输出在进入模型前就做压缩
- 针对不同命令类型做专门压缩器，而不是一刀切
- 对压缩前后 token/字符收益做可观测统计

已吸收：

- `compact/full`
- `budget=small|medium|large`
- short refs
- 轻量工作流输出风格
- `token_utils.py`：token 估算函数（`estimate_tokens`、`measure_payload_size`、`compute_savings`）
- `tracking.py`：token gain 日志（`token-gain-log.jsonl`）、per-tool / per-budget 汇总查询
- 工具专用 payload 压缩器（git Stats Extraction、pytest Failure Focus、grep Grouping by Pattern）
- `memory_eval_token_gain`：token gain 评测工具（MCP + CLI）
- `memory_eval_context_weight` 增强：token 数 + savings_pct 量化
- compact 函数内置 gain 测量（workspace_sniff/status/dashboard/continuity/resume/handoff）

还可继续吸收：

- rtk `discover` 模式：扫描会话历史找"未压缩"的高频命令
- `rtk gain` 更细粒度的 per-model / per-budget 趋势仪表盘
- 更多命令专用压缩器（docker / npm / cargo / go）

建议落地时机：

- 当前阶段：~~沿 `compact + budget + short refs` 压上下文~~ **已完成**
- 下一阶段：~~补命令输出前置压缩层与高频命令压缩器~~ **已完成**
- 后续阶段：补 discover 模式、更完整的命令压缩器矩阵、长期趋势仪表盘

---

## 九、真正的实现思想 / Implementation Tactics

这一节描述“具体应该怎么做”，避免主计划只停留在目标和清单层面。

### 1. 增量索引的真正做法

- 先确定作用域：`project / path / changed_files`
- JSON 索引层继续做 merge，而不是整份重写
- graph 层做局部删除 + 局部重建
- semantic 层保留未变节点，只重建 changed node，并修正必要的全局统计

### 2. 轻量上下文协议的真正做法

- 高层返回统一遵循：
  - 摘要
  - top-K
  - ref 展开
- `compact` 负责结构裁剪
- `budget` 负责条目裁剪
- 所有高频入口尽量统一 token 估算与 gain 记录

### 3. 引用与时间线的真正做法

- 所有引用统一：
  - `ref_id`
  - `kind`
  - `summary`
  - `raw`
- 所有 timeline item 统一：
  - `kind`
  - `ref_id`
  - `summary`
  - `task_id / session_id / created_at`
- 页面优先展示 summary，点击再 drill-down 到 `/ui/ref`

### 4. 工作流系统的真正做法

- `work-*` 保持为 orchestrator 能力的组合层
- **MCP facade 工具**提供任务级接口（mc_start/mc_lookup/mc_analyze/mc_sync/mc_resume/mc_handoff/mc_close/mc_admin），内部路由到 orchestrator 原子函数
- 不重复发明业务逻辑
- 每个 workflow 都应返回：
  - `workflow`
  - `核心步骤结果`
  - `receipts`
  - `next actions / unresolved`
- **推荐 Hook 映射**在关键时机执行，需宿主支持：
  - SessionStart → `memory-center sniff` 加载工作区上下文
  - PreToolUse (Edit|Write) → `memory-center check-rules` 检查架构规则
  - Stop → `memory-center end-session` 关闭并同步
  - UserPromptSubmit → LLM 判断是否编码任务，提醒调用 mc_start

### 5. 工作台系统的真正做法

- `/ui` 作为目录页
- `/ui/dashboard` 看全局
- `/ui/continuity` 看恢复
- `/ui/task` 看任务
- `/ui/timeline` 看事件/回执链
- `/ui/ref` 看原始细节
- `/ui/backend` 看统一后端

### 6. 统一后端的真正做法

- 文件系统继续保留为兼容层
- SQLite 优先接管“高频读路径”
- 新增能力先写镜像，再切查询，再看是否值得切主路径
- 避免一次性全量切换，始终保留 fallback

---

## 十、当前审计结论 / Current Audit Notes

基于当前代码结构、CLI/MCP/HTTP 入口、工作台页面、SQLite 后端与主计划对照，当前判断如下：

- 未发现新的明显阻断性运行时 bug
- 主计划里的多数高频能力已经落地
- 剩余工作主要集中在：
  - 更深的 SQLite 主读路径统一
  - 更完整的 guided tour / onboarding / 页面联动
  - 更正式的 token benchmark / top-K only / hybrid retrieval
  - completion audit 与最终文档一致性审计

这意味着系统已经从”功能集合”进入”收口与产品化”阶段。

**最新完成的工作（facade + hook / host integration groundwork）**：

- MCP tool surface 从 82 个原子工具重构为 8 个任务级 facade（mc_start/mc_lookup/mc_analyze/mc_sync/mc_resume/mc_handoff/mc_close/mc_admin），token 开销从 ~28k 降至 ~2.3k（92% 减少）
- 4 个 hook 映射建议：SessionStart→sniff、PreToolUse→check-rules、Stop→close、UserPromptSubmit→任务类型判断
- hooks.yaml 声明式规范、`memory-center run-hook` runner 与 Claude Code adapter 已落地，为宿主自动挂接提供基础
- CLAUDE.md 增加 facade 路由规则，明确每个 facade 的触发场景和自动行为
- CLI/HTTP 保持不变（82+ 原子命令仍供人类使用）
- 新增 `tests/test_mcp_facades.py` 覆盖 facade 路由
