# Roadmap / 路线图

> Historical document / 历史文档
>
> 本文档保留用于追溯早期路线图，不再作为当前版本状态或主开发路线的权威来源。
>
> For the current maintained doc set, see [DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md). For the active development roadmap, see [NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md).

## 1. Current State / 当前状态

如果你需要维护者视角的详细方案，而不是简版路线图，请看：

- [NEXT_PHASE_MASTER_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/NEXT_PHASE_MASTER_PLAN.md)
- [TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_GUIDE.md)

当前已完成的主线包括：

- 增量索引第一阶段
- 8 个 MCP facade 工具
- `work-*` 工作流
- compact / full + budget 协议
- short refs / timeline / handoff
- SQLite `memory.db` 镜像与部分高频读路径
- token gain / token benchmark / continuity eval
- Hook runner + adapters 基础能力
- hybrid retrieval
- benchmark trending
- unified backend query
- drill-down navigation
- completion audit

## 2. Current Priorities / 当前优先级

最值得继续推进的方向：

1. 轻量 ontology 约束层
2. 检索质量继续收口
3. Benchmark 趋势化真正落地
4. SQLite 进一步接管更多高频读路径
5. 更强的 timeline / ref / task drill-down 体验收口
6. completion audit 产品化与文档一致性持续收口

这些优先项的含义不是“从零开始做”，而是：

- ontology：第一版已落地，继续收紧到更多链路
- retrieval：hybrid 主链路已完成，继续收口结果质量
- benchmark trend：能力与入口已在，继续补长期治理闭环
- drill-down：CLI / MCP / HTTP 已可用，继续增强日常体验
- backend：统一查询层已存在，继续向主读底座推进
- audit：基础审计已存在，继续向通用 workspace 产品化推进

## 3. External Ideas Already Absorbed / 已吸收的外部思想

### `agentmemory`

- token benchmark
- top-K evidence
- compact + budget

### `rtk`

- token gain 观测
- 工具专用 payload 压缩

### `mattpocock/skills`

- workflow 化
- facade 化

### `Understand-Anything`

- workbench / drill-down / onboarding 方向

### `UModel / STAROps / 本体论`

- 对象优先、关系显式
- 事实 / 推断 / 派生 三层语义
- 用统一领域语言约束 retrieval / chain / timeline / audit

## 4. Near-Term Versions / 近阶段版本主线

- `2.1.x`
  - Hook 策略收口
  - token benchmark / top-K evidence
  - facade 与高频链路继续稳住

- `2.2.x`
  - 已完成：hybrid retrieval / benchmark trending / unified backend query / drill-down navigation / completion audit
  - 持续收口：ontology 约束层第一版
  - 持续收口：更深的 SQLite 主读路径统一
  - 持续收口：timeline/ref/task 联动增强

- `2.3.x`
  - 已完成：SQLite BM25 自动重建并进入 hybrid fusion
  - 已完成：dense embeddings 同步 VectorIndex，vector ANN 可选接入
  - Code Knowledge Graph reasoning 起步
  - 已完成：changed-file 增量重建真实调用与错误可见性
  - 已完成：删除/移动感知的 scoped index reconciliation
  - 已完成：additive facade 类型元数据、统一 quality summary 和结构化 operation observability
  - 已完成：不含路径或 payload 的 portable benchmark baseline 与回归比较
  - 持续收口：在真实脱敏 workspace 上积累检索、parser 和延迟趋势

## 5. Status Reading / 状态阅读方式

看这份路线图时，建议按下面三层理解：

- **已完成基础版**：功能已经存在，也通常已经接入主入口
- **持续收口**：不是没有，而是质量、边界、体验还没完全稳住
- **下一阶段推进**：确实还没达到目标终态，或还没有正式主链路化

例如：

- `hybrid retrieval` 属于已完成基础版
- ontology / audit / drill-down / backend 统一更偏持续收口
- native vector 真实数据 benchmark / tree-sitter 精度仍偏下一阶段运营验证；兼容型 facade 类型元数据已完成

## 6. Definition of Done / 阶段收口标准

某项工作不只看“功能写了”，还要看：

- CLI / MCP / HTTP 是否一致
- 文档是否同步
- 是否有测试或 smoke
- 是否改善了真实日常使用体验
