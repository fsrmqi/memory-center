# 应用层

组合核心 Module 为任务级用例，供 CLI、MCP、HTTP 和 hooks 等入口适配器调用。

本层可以依赖 `core/`，但不得承载传输协议、命令行参数解析或 HTTP/MCP 响应格式。

当前模块按用例划分：

- `task_start.py`：任务启动、工作区探测与会话准备。
- `lookup.py`：查询计划、定向索引刷新、跨服务分片路由和结果融合。
- `analysis.py`：上下文包、架构导览、领域视图、新鲜度和运行时诊断。
- `tasks.py`：任务空间修复等带安全边界的写入用例。
- `jobs.py`：后台分析任务与任务证据写入。
- `admin.py`、`groups.py`、`quality_gates.py`：管理、工作区组和质量门禁用例。
- `golden.py`、`release_gate.py`：基准执行和发布门禁。
- `presentation.py`：可导出 Markdown、HTML、Mermaid 的展示组装。
- `wiki_promotion.py`：Wiki 晋升的确认编排（执行 bridge 子进程、读取会话不可变决策、登记 KnowledgeLink 与事件）；只读预览仍在 `core/knowledge/wiki_promotion.py`。
