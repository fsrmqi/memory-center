# 真实闭环首轮运行数据 / First Real-Loop Data Run

日期 / Date：2026-08-22
Workspace：`/Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml`（真实 ucap 多模块工程）
样本 / Sample：5 个已结束真实会话
目的 / Purpose：跑通 consolidate-session 候选 → 审核 → 决策闭环，收集五项指标，为下一步功能取舍提供数据。

## 1. 闭环执行记录 / Execution

| 步骤 | 命令 | 结果 |
|---|---|---|
| 候选暂存 | `consolidate-session --stage`（5 sessions） | staged=True，5 条候选写入 `session-consolidation-candidates.jsonl` |
| 列出候选 | `consolidation-candidates`（pending） | 5 条 ADD 候选，均带 source_refs/evidence_refs |
| 审核决策 | `decide-consolidation-candidate` | 4 approve + 1 reject |
| 写入确认 | 读 `cross-service-task-memory.jsonl` | 4 条新 case 写入（1→5），均带 source_session 溯源 |

## 2. 五项指标 / Five Metrics

### 2.1 来源完整率（source_refs / evidence_refs）

| candidate_id | session | src_refs | ev_refs | 决策 |
|---|---|---|---|---|
| session-consolidation-3c54d8a82c9024d2 | session-ef715af9f15b | 10 | 10 | approve |
| session-consolidation-c03355f0f1acc448 | session-cbb5fd498816 | 7 | 7 | approve |
| session-consolidation-c7321eff834df662 | session-6e5ad722bfcf | 7 | 7 | approve |
| session-consolidation-fb94a9ad9d5a739c | session-1bd4a7fc51fe | 5 | 5 | approve |
| session-consolidation-69d22d82a791b4e9 | session-23a5403a41b1 | 3 | 3 | **reject** |

来源完整率 = source_refs ≥ 3 全部完整；reject 项来源最少（3）。

### 2.2 REVIEW / reject 原因

- **1 条 rejected**（session-23a5403a41b1 任务动态核查）：来源仅 3 条 refs 且无 `verified_by`，属分析性结论 → 暂不沉淀。
- 模式观察：**来源 ≤ 3 或缺少 verified_by 的候选倾向被拒**，可作为后续自动 REVIEW 分流的信号（当前未实现，仅记录）。

### 2.3 是否重复写入

- 4 个 approve 的 source_session 均只有 1 条 case，**无重复写入**。
- 幂等验证：重复 `--stage` 同一批 session，`staged_candidate_ids` 为空（candidate_id 基于 session+key 的 SHA-256，稳定去重生效）。

### 2.4 审批耗时（staged → decided）

- 单条 CLI 间隔 ~44-50s（人工审核为批量动作，此值主要反映操作间隔而非审核思考时间）。
- 结论：当前数据不足以评估真实审批耗时；需人工实际使用后记录。

### 2.5 后续是否被 `mc_resume` / `mc_context_pack` 使用

- `mc_resume` 的 `related_cases` 消费 `cross-service-task-memory.jsonl`（token 匹配 intent）。
- 探测结果：
  - intent「Feign 契约变更影响评估」→ 命中 2 条新写入 case（Feign 密集度 + 公共导入 v2）✅
  - intent「多次接单」/「数据自动隔离」→ 命中「多次接单任务数据自动隔离」case ✅
  - intent「任务自动隔离」「接单人查看当前接单周期」→ 命中 0 ❌（中文长意图 token 粒度局限）
- 结论：**新写入 case 可被后续 resume 消费**；但中文长意图的 token 匹配有漏召回信号（数据量小，待更多真实任务验证）。

## 3. 数据驱动的下一步建议 / Next Steps by Data

| 信号 | 出现情况 | 建议 |
|---|---|---|
| REVIEW 偏高 | 本轮 1/5 reject，比例 20% | 暂不需 stable case ID / UPDATE/SUPERSEDE；继续观察 reject 是否因来源不足成为常态 |
| L1 被后续任务命中 | 是（Feign/多次接单意图命中） | L1 消费链路有效；L3 审批路径暂不优先 |
| 跨会话恢复漏关键事实 | 中文长意图 token 匹配漏召回（2 例） | 若后续多轮仍复现 → 做 `eval-session-recall`；样本不足时只观测 |
| 无显著问题 | 无重复写入、来源完整、决策闭环可用 | 优先回到 Java 解析精度与检索质量（P1/P2） |

## 4. 备注 / Notes

- 本次运行**未修改任何代码**，仅使用已有 `consolidate-session` / `consolidation-candidates` / `decide-consolidation-candidate` 命令跑真实数据。
- 演示 workspace（`examples/spring-cloud-demo`）未被污染；全部写入发生在真实 ucap workspace。
- 五项指标需多轮真实使用积累后才有统计意义；本轮为基线首轮。
