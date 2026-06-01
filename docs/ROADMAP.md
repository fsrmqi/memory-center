# Roadmap / 路线图

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

## 2. Current Priorities / 当前优先级

最值得继续推进的方向：

1. 轻量 ontology 约束层
2. hybrid retrieval
3. 更系统的 token benchmark 趋势化
4. SQLite 进一步接管更多高频读路径
5. 更强的 timeline / ref / task drill-down
6. completion audit 与文档一致性持续收口

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
  - ontology 约束层第一版
  - hybrid retrieval
  - 更深的 SQLite 主读路径统一
  - timeline/ref/task 联动增强

## 5. Definition of Done / 阶段收口标准

某项工作不只看“功能写了”，还要看：

- CLI / MCP / HTTP 是否一致
- 文档是否同步
- 是否有测试或 smoke
- 是否改善了真实日常使用体验
