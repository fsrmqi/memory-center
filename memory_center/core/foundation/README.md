# 基础层

提供共享类型、错误、Schema、分发机制和纯文本、Token 辅助能力。

本层还有两份**纯数据**清单，都不导入上层模块：

- `capabilities.py`：4.x B-01 能力契约目录（`core_fields` / `error_semantics`），供引擎回归测试校验返回结构；**不声明任何入口**。
- `entry_registry.py`：5.0 唯一的用户可达入口注册表（MCP 工具、`/mcp`、`/admin/`、`/api/v1/*`、CLI 启动器），以及 4.x 退役标识的否定清单。真值由 `tests/entrypoints/test_entry_registry.py` 对运行态服务校验。

不得在此加入工作区 I/O、配置加载、图查询或领域工作流逻辑。这是系统最低层的应用代码。
