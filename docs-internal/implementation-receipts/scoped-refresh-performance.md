# Scoped Refresh Performance and Generation Health Report

> 日期：2026-08-28 · 工作区：真实多服务 Java 工作区（约 19.6k 文件 / 4GB graph.db）
> 边界：仅修改 `core/indexing/`（IR 部分重算）；未改 parser/resolver/retrieval/schema

## Dataset

- case count：**8 次真实定向刷新**（Controller / DTO / MQ / Config 各 1-2 次，单文件 scope，`scanned_files=1`）
- change categories：Controller 路由、DTO 契约、MQ Producer、配置键（覆盖高风险契约类）
- privacy：仅记录脱敏相对路径与聚合 timing，无源码/服务名全文
- generation consistency：每次刷新 active generation 轮转、staging 空、status ready

## Performance

| 变更 | 修复前总耗时 | 修复后 | dominant（修复后） |
|---|---|---|---|
| Controller | 70s | 55s | generation_publish 16s |
| DTO | 51s | — | generation_publish |
| MQ | 52s | — | graph_update |
| Config | 57s | — | generation_publish |

- 历史 62 样本：P50 8.7s / P95 51.5s（budget 10s）
- **dominant stage 分布**：graph_update 与 generation_publish 交替 dominant（各 ~3/8），合并为"图与分片重投影"家族 6/8

### 根因与修复（graph_update 热点）

Profile 定位：`build_java_ir_index` 每次局部刷新**全量重算 67.8 万候选（13s）**，且被 `mark("graph_update")` 错误计入 graph_update 阶段。这是单文件刷新 graph_update 17-25s 的真实根因。

**修复**：partial 刷新改用 `_merge_ir_partial`——只对 scoped 文件重算 IR 候选 + 继承未变更文件候选（类似 file-index 的 merge）。

- `_merge_ir_partial` 单文件：**1.9s vs 全量 13s（6.8×）**
- 真实 Controller 刷新：**70s → 55s**（graph_update 25s → 14s）
- candidates 保持 678023（覆盖不降）

## Scope Correctness

- **SCOPE_CORRECT**：8/8 次刷新 `scanned_files=1`（单文件 scope，无无关项目扩大）
- active generation 可读：100%（刷新中旧 gen 持续服务，发布原子）
- 失败/取消保留旧 generation：由 Phase C 既有测试覆盖（test_job_coordinator 等）
- 删除/重命名残留：IR partial merge 测试锚定（全量重建 drop 删除文件候选）
- 高风险契约变更（Controller/DTO/MQ）：刷新正常，deep-analysis 建议由既有 change review 覆盖

## Storage Health（只读）

- **graph.db：4.1 GB**（空间增长风险，需用户授权后评估 GC/vacuum）
- generation 目录：3（active/previous/staging 合理）
- job 账本：11 completed，无活动/过期 lease/失败 staging（健康）
- generation_publications：19 条（发布审计完整）
- **未执行任何清理**（generation-gc/vacuum/compact 均只读审查，遵守任务禁令）

## Decision

**选 1 项修复（graph_update/IR 热点）**：
- 证据：≥5 case（8 次）、graph_update 家族 ≥3 dominant、可定位到 `build_java_ir_index` 全量重算、不降质量
- 修复：`_merge_ir_partial` 部分重算 + 继承
- 拒绝的替代：generation_publish 分片导出优化——分片继承（reuse_generation）已存在，服务级 payload 缩小是更大重构，且任务"只修一个有证据的瓶颈"；留作后续

## Validation

- 新增 `test_ir_partial_merge.py`（继承未变更候选、全量重建 drop 删除文件）
- 全量回归（index_storage/domain）绿
- **IR gate**：通过（anchor 0.9977 / edge_coverage 1.0 / forbidden hit 0）
- coverage：17028/19639 不降
- 查询 smoke：刷新后 mc_lookup 正常（primary_chain 等不受影响）

## Known Limits

- generation_publish 仍是单服务全量 payload 的 JSON dump 热点（16s），分片继承已生效；缩小到字段级/增量导出是后续优化
- graph.db 4GB 增长需用户授权后评估（任务禁止自动清理）
- p95 仍超 10s budget（因 publish），优化后 graph_update 显著改善但整体仍受 publish 制约

## Stop Condition

**Partially satisfied**：已定位并修复一个可证明瓶颈（graph_update/IR）；publish 热点有证据但属更大重构，未在本次扩大（避免破坏原子发布）。其余（删除残留/scope 扩大/stale 读）均为 0。
