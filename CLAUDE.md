# Claude Code Instructions for Memory Center

Memory Center 是面向 AI 编程助手的 MCP 项目记忆服务。

工作要求：

- 修改前先阅读 README 和 docs。
- 保持 CLI / MCP tool schema 稳定。
- 修改索引器、规则、MCP、CLI 时更新测试。
- 面向用户的文档保持中英文双语。
- 不提交真实私有 workspace 生成数据。

## MCP Facade Tools (8 个任务级工具)

MCP tool surface: 8 facade tools only. Do NOT add atomic tools back to MCP — keep facade-only surface. CLI and HTTP keep fine-grained interfaces unchanged.

**何时用哪个 facade — 自动路由规则：**

| 场景 | 自动调用 | 说明 |
|------|----------|------|
| 用户输入涉及编码/架构/调试 | `mc_start` | SessionStart hook 已自动 sniff；这里主动调用获取 session_id |
| 需要查代码/符号/调用链/契约 | `mc_lookup` | mode="auto" 自动路由到最佳策略 |
| 要修改代码前 | `mc_analyze` | PreToolUse hook 已自动 check-rules；这里主动调用获取影响面 |
| 修改过程中想保存进度 | `mc_sync` | 提供 intent（sniff-sync）或 session_id（case-sync） |
| 回到之前的任务 | `mc_resume` | 提供 intent/task_id/session_id |
| 切换模型或 session | `mc_handoff` | 提供 target_model |
| 任务完成 | `mc_close` | Stop hook 已自动 close；这里主动调用确认 |
| 查状态/工件/评估/生成 | `mc_admin` | action 参数选择子操作 |

**关键行为：**
- 编码任务开始时，先调用 `mc_start` 获取 session_id，存到 `/tmp/memory-center-session-id` 供 Stop hook 使用
- 修改代码前，调用 `mc_analyze` 获取影响面和规则检查
- 任务结束时 Stop hook 自动调用 `mc_close` 关闭 session
- 其他场景用 `mc_lookup` (mode="auto") 自动路由

Core commands:

```bash
memory-center reindex --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml
memory-center sniff --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml --intent "oldPubTime newPubTime Kafka"
pytest -q
```
