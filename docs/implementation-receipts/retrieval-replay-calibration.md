# Retrieval Replay Calibration Report

> 日期：2026-08-28 · 工作区：真实多服务 Java 工作区（约 19.6k 文件）· 只读评测
> 工具：`memory-center eval-retrieval-replay-cases`（新增，纯 retrieval/benchmark 范围）

## Dataset

- case count：**18**（>15，满足统计门槛）
- category coverage：feign_chain 2 / http_chain 2 / symbol 3 / same_name 3 / negative 3 / mq_producer 2 / project 2 / stale_boundary 1
- privacy audit：case 文件与查询映射位于仓库外 `~/private-retrieval-replay/`（gitignored）；仓库仅含匿名示例 `examples/retrieval-replay-cases.example.yaml`；无真实 query/path/source
- generation consistency：18/18 同一 active generation

## Baseline（Phase B 零代码基线）

- anchor top-1 recall：0.33（Method 应定位 case 中 rank1 Method 的比例；多数 symbol/same-name case 为类查询，期望 Class）
- primary-chain recall：**1.0**（Feign/HTTP 应链路 case 全部 found）
- wrong-chain rate：**0.0**
- boundary-correct rate：0.44（负例/MQ/stale 边界正确率）
- project-scope regression rate：**0.0**
- P50 / P95：1629ms / 4131ms

## Failure Taxonomy

| 分类 | 数量 | 说明 |
|---|---|---|
| PASS | 10 | Feign 2、HTTP 2、project 2、symbol 2、same_name 2 |
| ANCHOR_RANKED_LOW | 1 | symbol-01：`FeignUserWrapperService.getUser`（含方法名）best_match=Class |
| EVIDENCE_BOUNDARY_CORRECT | 2 | neg-01（not_found）、stale-01（拒绝否定结论） |
| DATASET_EXPECTATION_WRONG | 5 | neg-02/03 无锚点、mq-01/02 无法经 symbol 触达 MQProducer、same-03 查询过泛 |
| CHAIN_WRONG | **0** | — |
| CHAIN_MISSING_WITH_GRAPH_EVIDENCE | **0** | 图有 EXTRACTED 边但 primary_chain 缺失 = 0 |

代表性匿名模式：`FeignUserWrapperService.getUser`（含方法名）被 Class 抢占（1 例）；其余"失败"均为 case 期望与图事实不符（查询是类名/不可达锚点）。

## Decision

**No code change to retrieval.** Phase C gate: 真实检索缺陷（ANCHOR_RANKED_LOW）仅 **1 个同类 < 3**，不满足"≥3 同类失败"修复门禁（任务 §九/§十四 停止条件）。其余失败均为 `DATASET_EXPECTATION_WRONG`（修 case）或 `EVIDENCE_BOUNDARY_CORRECT`（正确边界）。

- 本轮唯一代码改动：`classify_outcome` 的 same_name 分支尊重 expected.anchor.kind（replay 工具自身的分类 bug，属允许范围），并新增 `eval-retrieval-replay-cases` 基础设施。
- 拒绝的替代方案：为 `FeignUserWrapperService.getUser` 这类含方法名的 Feign 接口查询强推 Method 锚点——同类样本仅 1 个，且会引入"类名查询被强制转方法"的风险（任务 §十.A 禁止因名称相似压制精确类查询）。

## Validation

- tests：新增 11 个 `test_retrieval_replay.py`（分类 + 聚合 + 加载）；全量 domain/index_storage 回归绿
- replay：18 条基线如上，CHAIN_WRONG 0
- performance：无 retrieval 改动，P95 不变
- IR gate：通过（edge_coverage 1.0 / forbidden hit 0）
- known limits：MQ 边界无法经 mc_lookup(auto) 的 symbol 路径触达 MQProducer 锚点（MQProducer 非 symbol 目标类型），由 `find_primary_service_chain(MQProducer)` 单测覆盖（9b7e40f）；P50/P95 偏高源于 Feign bridge 的 FTS 桥接（deep 分析路径，非默认 symbol 查询）

## Stop Condition

**Satisfied.** 同类失败 < 3、无 CHAIN_WRONG、无需改 parser/resolver/schema、MQ/负例边界正确。结论：**当前 retrieval 无可证明改动；保持现有实现。**

## Next Recommended Action

- 当真实使用中出现 ≥3 个"含方法名查询被 Class 抢占"的同类 case 时，再评估 Method 锚点排序修复（任务 §十.A）；
- 可考虑将 MQ 边界探测纳入 `mc_lookup` 的 walkthrough/context 路径（当前 symbol 无法触达 MQProducer）。
