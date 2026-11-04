# 核心架构

`core/` 是 Memory Center 的领域边界。根目录不包含具体实现，应按职责选择对应的子包。

- `foundation/` 与 `storage/` 属于底层，不得依赖编排层或适配器层。
- 领域包提供事实或边界明确的操作，由 `orchestrator/` 进行组合。
- CLI、MCP、HTTP 与 hooks 位于本目录外，只能调用各领域的规范路径。
