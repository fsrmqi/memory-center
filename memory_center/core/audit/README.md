# 审计

提供完成度审计报告、运行时集成审计和交互历史治理。

`reports.py` 负责完成度审计记录；`runtime.py` 负责宿主运行时接入审计；`inspect.py` 聚合脱敏运行时检查；`snapshots.py` 负责 Git 与验证快照；`interactions.py` 负责 MCP/宿主交互的脱敏记录、thread-session 绑定、分层保留和效果摘要。

本包只保存可验证的元数据与聚合指标，不保存原始对话正文、源码正文或工具 payload。
