# 代码图谱基础设施验证回执 / Code Graph Foundation Implementation Receipt

> 对应决策：[CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md](../../docs/decisions/CODE_GRAPH_FOUNDATION_IMPLEMENTATION.md)
> 版本：4.5.0 · 日期：2026-08 · 真实工作区：`ucap`（约 19.6k 索引文件 / 34.5 万图节点 / 114 万边）

## 1. 执行命令与结果 / Executed Commands

| 命令 | 结果 |
|---|---|
| `pytest tests/index_storage/ tests/domain/` | 全绿 |
| `pytest tests/entrypoints/` | 仅 3 个既有基线失败（subgroup snapshot、2 个 architecture seams，与本次无关） |
| ucap 全量 `reindex_workspace(parallel=True)` | 完成，job `completed`，publish smoke 通过 |
| `performance-snapshot`（ucap, standard） | hybrid P95 94ms；find_symbols 3.5ms；trace_call_paths 3.9ms |

## 2. 真实工作区指标 / Real-Workspace Metrics

- 全量 reindex：**373 秒**（parse 240s、retrieval 29s、generation publish 17s）；coverage 17,017 parsed / 2,609 skipped / 0 failed
- 局部刷新（534 文件 scope）：43 秒，coverage 424 parsed / 110 skipped
- 未解析调用（20k 采样内，truncated=true）：12351 例，按 reason 排序 external_static_call 2307 / receiver_type_not_indexed 2256 / inherited_method_out_of_scope 942 / unqualified_or_dynamic 903
- 契约消费者：Feign 抽样 8/8 命中；MQ 绑定名 6/6 命中（修复前 MQ 点号名无法锚定）

## 3. 修复的关键缺陷 / Fixed Defects

1. 旧代工作区无 coverage_summary 时全零覆盖被误判为完整 → 标 `coverage_unknown` 并强制拒绝否定性结论（Phase A 门禁）
2. 解析诊断 per-file 归因全部落入 `(unknown)` → 分块 join nodes 表补齐 node→路径映射（Phase D）
3. `find_contract_consumers` 对 Spring Cloud Stream 点号绑定名 FTS 无法匹配 → 新增 `node_by_name_exact` 精确锚定（Phase B）

## 4. 已知限制与下一步 / Known Limits and Next Steps

- 解析诊断读取 CALLS_METHOD 有 20k 上限并如实标记 `truncated=true`；全量统计需显式 deep 档（未提供默认路径）
- 三轮采样（external_static_call / receiver_type_not_indexed / inherited_method_out_of_scope）均确认未解析源自外部依赖边界，源码级 resolver 无收益空间；保持 AMBIGUOUS 并清晰标注
- Phase E（通用语言 adapter 试点）维持 P2：等待真实非 Java workspace 需求与可脱敏评测集，不得预设语言
- 性能基线已固化为可重复快照，后续改动按 +10% P95 门禁复采对比
