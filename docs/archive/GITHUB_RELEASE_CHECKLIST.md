# GitHub Release Checklist / GitHub 发布清单

## 中文

发布到 GitHub 前建议检查：

- [ ] 修改 `pyproject.toml` 中的 `Homepage`、`Documentation`、`Issues`、`Source`。
- [ ] 确认包名为 `memory-center`。
- [ ] 确认命令为 `memory-center` 和 `memory-center-mcp`。
- [ ] 运行 `pytest -q`。
- [ ] 运行 `python -m build`。
- [ ] 检查 README 中文和英文说明。
- [ ] 检查 `LICENSE`。
- [ ] 检查 `.github/workflows/ci.yml`。
- [ ] 创建 GitHub Topics。
- [ ] 创建 v1.0.0 tag。

推荐仓库描述：

```text
Memory Center is an MCP-native project memory service and multi-agent shared context center for AI coding agents, with first-class support for Spring Cloud workspaces.
```

中文描述：

```text
记忆中心：面向 AI 编程助手的 MCP 项目记忆服务，用于多 Agent 公共空间、项目上下文、跨服务影响分析和经验沉淀。
```

## English

Before publishing:

- Update project URLs.
- Run tests.
- Build the package.
- Verify bilingual docs.
- Add GitHub topics.
- Create the first release tag.
