# Gemini Instructions for Memory Center

This repository builds Memory Center, an MCP-native project memory service for coding agents.

Follow the same rules as AGENTS.md. Prefer bilingual documentation updates and keep examples generic.

<!-- memory-center:start -->
# Memory Center 5.0 Agent Protocol

本仓库采用独立常驻 Memory Center 5.0 服务；管理页和统一 MCP 共用同一应用层。不要绑定旧 workspace 文件或启动独立 Wiki MCP。当前参数以服务实际 tool schema 为准，参考 `docs/V5_PLATFORM_GUIDE.md`。

- 源码根目录：本仓库根目录；本文件覆盖该目录及其子项目。用 `mc_workspaces()` 选择覆盖该目录的已登记 workspace；5.0 不读取旧 workspace 文件，也不要为子项目单独绑定服务。
- Source root: this repository root. Pick the registered workspace covering it with `mc_workspaces()`; 5.0 never reads the legacy workspace file, and do not bind the service per subproject.

1. 开始工程交付前先 `mc_workspaces()` 查看已登记项目，只选择与当前源码目录明确匹配的 `workspace_id`。尚未登记时使用本地 GitNexus 和源码验证，说明服务已配置但本项目未登记；不得借用其它业务项目的会话或记忆。项目接入通过管理页处理。
2. 已匹配的交付任务调用 `mc_start(workspace_id=..., intent=...)`，保存返回的 `id` 作为 session_id；只读了解不自动创建/关闭会话。
3. 工程查询用 `mc_lookup(workspace_id=..., query=..., mode=...)`，mode 为 hybrid/symbol/callers/callees/context。调用关系结果须核对覆盖、新鲜度与来源，空结果不是不存在的证明。
4. 修改前先做本仓库 GitNexus impact；已登记且需要服务影响证据时调用 `mc_analyze(workspace_id=..., target=...)`。不要调用旧 `mc_admin`、`mc_sync`、旧深度/文件参数或旧 ANN 指令。
5. 长任务用 `mc_resume(session_id=...)` 恢复；完成明确交付后 `mc_close(session_id=..., outcome=...)`。不要认领或关闭其他项目的会话。
6. 长期知识由同一服务的 `assistant_knowledge(action="brief"|"search"|"read"|"analyze", ...)` 查询。事实和验证证据优先；冲突应指出 Wiki 可能过期。
7. 知识晋升/资料归档、Skill 创建/发布均先 `confirm=false` 预览，展示后等待对应写入的明确确认。Skill 来源、工件哈希和验证引用应保留；引用不等于自动证明外部内容真实。
8. 管理页“知识治理”和“Skill 管理”可维护受管 Wiki 与候选/发布目录；原 Wiki 只读来源和受管知识分别维护。`assistant_admin(action="scan")` 只报告垃圾，不删除。
9. 普通项目记忆写入用 `mc_memory_write(workspace_id=..., content=..., confirmed=...)`，区分待确认与已确认记录。不要将会话、源码、日志、私有路径或未验证推断直接晋升为长期 Wiki。
10. 宿主配置变更后刷新会话以重新发现工具；已配置但快照未刷新时不要误称服务不可用。MCP 地址默认 `http://127.0.0.1:8765/mcp`；stdio 代理为 `memory-center-mcp`，不带旧 `--workspace`。

English: Use one Memory Center 5.0 service and select only a registered workspace matching the current repository. Never reuse an unrelated project's session. Wiki and Skill governance use the integrated assistant tools; preview and explicit confirmation precede governed writes. Old workspace-bound MCP contracts are retired.
<!-- memory-center:end -->
