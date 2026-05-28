# MCP Guide / MCP 接入指南

## 1. Public Surface / 对外公开面

MCP 默认公开的是 8 个 facade tools：

- `mc_start`
- `mc_lookup`
- `mc_analyze`
- `mc_sync`
- `mc_resume`
- `mc_handoff`
- `mc_close`
- `mc_admin`

设计目标是让模型看到的是“任务级接口”，而不是几十个实现层原子工具。

## 2. Facade Summary / Facade 概览

| Tool | Purpose |
|---|---|
| `mc_start` | 嗅探任务上下文、可选同步、启动 session |
| `mc_lookup` | 统一检索入口：symbol / code / query / trace / chain / context / ref / backend |
| `mc_analyze` | 统一影响分析入口：quick / standard / full |
| `mc_sync` | 将 sniff / case / task 过程同步到工件与记忆 |
| `mc_resume` | 恢复任务上下文 |
| `mc_handoff` | 为其他模型构建交接包 |
| `mc_close` | 会话收尾、同步 case、记录经验 |
| `mc_admin` | 状态、面板、评测、工件、group 等管理入口 |

## 3. Recommended Agent Behavior / 推荐 Agent 行为

推荐顺序：

1. 开始任务：`mc_start`
2. 查信息：`mc_lookup(mode="auto")`
3. 改前检查：`mc_analyze`
4. 长任务同步：`mc_sync`
5. 中断后恢复：`mc_resume`
6. 切换模型：`mc_handoff`
7. 收尾：`mc_close`

## 4. Hooks / Hook 接入

### 推荐自动执行

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

### 默认不要挂

- `UserPromptSubmit`

原因：普通自然语言请求过于依赖上下文，容易被宿主误处理成拦截步骤。

## 5. Host Strategy / 宿主策略

### Claude Code / Codex

默认建议：

- 生成 `SessionStart / PreToolUse / Stop`
- 不生成 `UserPromptSubmit`

### Cursor

更适合作为规则与工作流提示层，而不是强阻断执行层。

## 6. Security Model / 安全模型

Memory Center 默认是：

- 本地优先
- 读优先
- 不改业务源码

写入范围主要限于：

- `.memory-center/memory`
- `.memory-center/artifacts`
- 生成的 wiki / skills / dashboard

## 7. HTTP Bridge / HTTP 桥接

MCP 之外，还可通过 HTTP bridge 复用同一套能力：

```bash
memory-center serve-http --workspace /abs/path/.memory-center/workspace.yaml --host 127.0.0.1 --port 8765
```

## 8. Related Docs / 相关文档

- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
- [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
