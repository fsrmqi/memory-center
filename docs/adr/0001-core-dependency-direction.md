# ADR-0001：核心依赖方向

## 状态

已接受。

## 决策

Memory Center 的依赖方向固定为：`foundation/workspace/storage` 提供基础事实与访问能力；索引、检索、知识、链路分析等引擎在其上构建派生事实；`orchestrator` 只组合任务级用例；CLI、MCP、HTTP、hooks 属于 Adapter。

低层包不得导入 `orchestrator` 或任一 Adapter。任务级查询冒烟、展示组合和传输格式必须由应用或 Adapter 层发起。

## 后果

- `workspace.doctor` 只返回基础健康事实，任务级查询通过入口注入的 probe 执行。
- `knowledge`、`retrieval` 不得使用 `orchestrator.shared` 作为工具来源。
- 新增跨层依赖必须先调整所属 Module，而不是以延迟导入规避循环。
