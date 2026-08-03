# 外部 Provider

本模块定义受控外部能力的接入边界，不承载业务编排，也不把外部工具正文写入长期索引。

- `registry.py`：Provider 能力、优先级和选择策略。
- `health.py`：进程内 P95、错误率和成本信号，用于健康路由。
- `gitnexus.py`：GitNexus 固定能力适配。
- `mcp_bridge.py`：受策略白名单约束的 HTTP MCP Client Bridge。
- `evidence.py`：脱敏 `EvidenceRef` 及跨 Provider Claim 融合。

新增 Provider 必须声明能力、调用边界、超时和证据产出；索引、写入或清理动作必须经过显式确认，外部正文不得进入长期存储。
