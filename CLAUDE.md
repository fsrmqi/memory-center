# Claude Code Instructions for Memory Center

Memory Center 是面向 AI 编程助手的 MCP 项目记忆服务。

工作要求：

- 修改前先阅读 README 和 docs。
- 保持 CLI / MCP tool schema 稳定。
- 修改索引器、规则、MCP、CLI 时更新测试。
- 面向用户的文档保持中英文双语。
- 不提交真实私有 workspace 生成数据。

MCP tool surface: 8 facade tools (mc_start, mc_lookup, mc_analyze, mc_sync, mc_resume, mc_handoff, mc_close, mc_admin). Do NOT add atomic tools back to MCP — keep facade-only surface. CLI and HTTP keep fine-grained interfaces unchanged.

Core commands:

```bash
memory-center reindex --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml
memory-center sniff --workspace examples/spring-cloud-demo/.memory-center/workspace.yaml --intent "oldPubTime newPubTime Kafka"
pytest -q
```
