---
name: wiki
description: 使用 Memory Center 5.0 统一服务查询项目证据、长期知识，并管理知识和 Skill 的沉淀。
---

# Wiki 与项目记忆

所有工具来自同一个 `memory-center` MCP 服务。先查看服务实际的工具 schema；不要使用旧 workspace 参数或启动独立 Wiki MCP。

- 只读了解：按需调用 `assistant_knowledge(action="brief", query="任务描述")`，工程查询使用 `mc_lookup(workspace_id="已登记项目 ID", query="问题")`。只读请求不要自动创建或关闭工程任务。
- 交付任务：通过 `mc_start(workspace_id=..., intent=...)` 建立 session；后续 `mc_lookup`、`mc_analyze`、`mc_resume` 使用对应项目或 session。完成用户明确交付后再 `mc_close`。同一服务可以登记多个项目，不假设当前目录对应旧 workspace。
- 结论保留来源。当前源码和验证证据优先于长期 Wiki；冲突须指出可能过期。
- 稳定经验：`assistant_memory(action="promote", title=..., content=..., source=..., module=..., confirm=false)` 生成预览。向用户展示后，只有收到明确确认才用同样参数 `confirm=true` 写入。模块依据 `assistant_knowledge(action="analyze")` 的注册表，不猜测路由。
- 资料归档：`assistant_memory(action="archive", source_path=..., destination=..., confirm=false)`，确认后执行。源路径只能来自管理页已登记的项目或 Wiki；容器部署须使用容器内路径。
- Skill：先 `assistant_skill(action="analyze"|"extract", source_paths=[...])`，再以结构化正文 `create(confirm=false)`。确认创建后 `validate`、`inspect`；携带真实任务或验证引用 `publish(confirm=false)`，用户明确确认后才发布。`evidence_refs` 是关联依据，不代表系统已自动验证外部证据的真实性。
- 候选可 `export`；停用或删除用 `remove(confirm=false, published=...)` 预览并确认。服务保留可恢复副本。
- 私有路径、日志、密钥、未验证推断不要晋升或混入公开 Skill。知识写入和 Skill 发布的确认彼此独立。

管理页的“知识治理”和“Skill 管理”与这些 MCP 工具共用同一份数据。检索自动增量刷新；外部只读 Wiki 来源和服务内受管 Wiki 分开维护，迁入不会删除原文档。
