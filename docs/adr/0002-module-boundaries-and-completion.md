# ADR-0002：模块边界与架构重构验收

## 状态

已接受。

## 背景

Memory Center 同时提供 CLI、MCP、HTTP、hooks 和本地 Workbench。仅用文件行数驱动拆分会制造没有业务所有者的薄文件；完全不设边界又会让入口层和编排层持续膨胀。本 ADR 定义模块归属、拆分触发器与本轮架构重构的可验收条件。

## 决策

### 1. 分层与依赖方向

`adapter -> application -> core/orchestrator -> core engines -> storage/foundation` 是唯一允许的主方向。

- Adapter：协议、参数、错误边界、公开 schema 注册；不得实现跨领域决策。
- Application：入口共享的任务用例、局部刷新、结果装配；可以依赖 core，core 不得反向依赖 application。
- Orchestrator：稳定的任务语义与核心组合；不得依赖 adapter 或 application。
- Core engines：索引、检索、图谱、walkthrough、规则和评测等确定性能力。
- Foundation/storage：模型、配置、持久化和纯工具；不得依赖编排或入口。

### 2. 文件拆分触发器

单个实现文件满足任一条件时必须评估拆分，而非自动拆分：

1. 同时承载两个以上可独立测试、可独立命名的业务职责。
2. 同时处理传输协议与业务编排。
3. 新增功能需要跨越不同职责的私有状态或缓存。
4. 文件超过 900 行且其中存在可独立导出的公共用例或完整私有辅助簇。

仅因文件较长、存在紧密协作的算法步骤，或拆分会引入循环依赖时，不强制拆分。此时应补充模块 README、公共入口和架构测试。

### 3. 目标模块归属

- `cli/main.py` 只负责根 Typer 应用和跨域装配；有独立命令组的能力放入 `cli/commands/`。
- `mcp/server.py` 只负责任务工具族装配；运行时、资源、提示词和独立工具族放入 `mcp/` 子模块。
- `orchestrator/query.py` 只承载公共查询编排；walkthrough 细节必须位于 `core/walkthrough/`，检索排序/展示辅助应按独立职责拆出。
- `orchestrator/workspace_ops.py` 只承载 workspace status/sniff/trace/lookup hint；恢复检查、仪表盘和连续性视图在形成独立用例后单独归属。

### 4. 本轮验收条件

以下全部满足即视为本轮六项架构重构完成：

1. HTTP 路由不直接依赖非 foundation 的 core 业务包。
2. MCP 运行时、资源/提示词/洞察工具与任务工具入口分离，公开名称不变。
3. CLI 至少将 registry、group、workspace、artifact 等独立命令组移至 `cli/commands/`。
4. core 非 orchestrator 包零依赖 `core.orchestrator`；presentation、tasks、benchmark 不反向依赖 orchestrator/application。
5. 已从超大入口/编排文件拆出至少一个具备独立测试边界的真实用例模块，且关键模块有 README/ADR 说明。
6. 架构测试、静态检查、完整测试套件和 diff 格式检查通过。

## 后果

- 后续重构以职责和依赖为验收依据，不以任意行数作为发布阻塞条件。
- 新增大文件必须在 PR/变更说明中写出所属层与职责；命中触发器时补充拆分或说明为何保持聚合。
- 公开 CLI、MCP、HTTP 合约仍以兼容为默认原则。
