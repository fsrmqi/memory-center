# 应用层

组合核心 Module 为任务级用例，供 CLI、MCP、HTTP 和 hooks 等入口适配器调用。

本层可以依赖 `core/`，但不得承载传输协议、命令行参数解析或 HTTP/MCP 响应格式。
