# MCP 入口

本目录承载 `memory-center-mcp` 的传输协议适配，不承载跨领域业务用例。

- `server.py`：任务工具族注册与 MCP 进程入口。
- `runtime.py`：工作区入参解析、启动诊断、统一异常边界。
- `insights.py`：资源、提示词、上下文包、架构导览、领域和新鲜度工具注册。
- `action_registry.py`：面向管理动作的分发定义。

业务编排应放在 `memory_center/application/` 或 `memory_center/core/`；MCP 层只完成 schema 保持、参数绑定和错误转换。
