# User Guide / 使用指南

## Who This Is For / 适用对象

这份文档面向日常使用者：想安装、初始化、重建索引、查询上下文、做影响分析、维护 workspace 的开发者或 Agent 使用者。

## 1. Install / 安装

推荐安装方式：

```bash
pipx install /path/to/memory-center
```

开发环境：

```bash
pip install -e .
```

验证：

```bash
memory-center --version
```

## 2. Initialize Workspace / 初始化工作区

```bash
memory-center init --workspace /abs/path/.memory-center/workspace.yaml
```

初始化后重点关注：

- `workspace.yaml`
- `.memory-center/rules/`
- `.memory-center/hooks.yaml`
- `.memory-center/artifacts/`

## 3. Reindex / 重建索引

全量：

```bash
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml
```

增量：

```bash
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --project xxx
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --path module-a/src/main/java
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --changed-only --scope all
```

## 4. Daily Workflow / 日常工作流

最推荐的高频命令：

```bash
memory-center work-start --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-sync --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-resume --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-handoff --workspace /abs/path/.memory-center/workspace.yaml --target-model codex --intent "..."
memory-center work-close --workspace /abs/path/.memory-center/workspace.yaml --session-id <session_id>
memory-center work-health --workspace /abs/path/.memory-center/workspace.yaml
```

## 5. Common Queries / 常见查询

### 查任务上下文

```bash
memory-center sniff --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
```

### 查符号 / 代码 / 调用链

```bash
memory-center symbol --workspace /abs/path/.memory-center/workspace.yaml --name ArticleFeignClient
memory-center search-code --workspace /abs/path/.memory-center/workspace.yaml --query oldPubTime
memory-center callers --workspace /abs/path/.memory-center/workspace.yaml --symbol com.example.ArticleService#update
memory-center callees --workspace /abs/path/.memory-center/workspace.yaml --symbol com.example.ArticleService#update
```

### 做影响分析

```bash
memory-center impact --workspace /abs/path/.memory-center/workspace.yaml --target ArticleDTO
memory-center detect-changes --workspace /abs/path/.memory-center/workspace.yaml --scope all
```

## 6. MCP / HTTP / UI

### MCP

```bash
memory-center-mcp --workspace /abs/path/.memory-center/workspace.yaml
```

### HTTP + Workbench

```bash
memory-center serve-http --workspace /abs/path/.memory-center/workspace.yaml --host 127.0.0.1 --port 8765
```

常用页面：

- `/ui`
- `/ui/dashboard`
- `/ui/continuity`
- `/ui/task`
- `/ui/timeline`
- `/ui/ref`
- `/ui/backend`

## 7. Multi-Workspace / 多工作区

支持：

- 一个大根目录下多个服务
- 多个独立 workspace
- registry + group 聚合

典型命令：

```bash
memory-center register-workspace ...
memory-center create-group ...
memory-center add-to-group ...
```

## 8. Maintenance / 维护

建议周期性执行：

```bash
memory-center status --workspace /abs/path/.memory-center/workspace.yaml
memory-center regression-smoke --workspace /abs/path/.memory-center/workspace.yaml
memory-center eval-token-benchmark --workspace /abs/path/.memory-center/workspace.yaml
```

## 9. Keep It Small / 如何避免用法膨胀

优先顺序建议：

1. 先用 `work-*`
2. 不够时再用 facade / CLI 原子命令
3. 排障或开发系统本身时再深入 `REFERENCE.md`

## 10. Related Docs / 相关文档

- [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)
