# HTTP 展示迁移说明 / HTTP Display Migration

> 文档类型：迁移指南（current）
> 适用版本：4.6.28 及之后。

## 结论 / Summary

Memory Center 不再托管内置 HTML 工作台或 Vue SPA。`/ui/*` 和 `/app` 已移除，访问时会返回 `404`；服务端不提供重定向、HTML 回退页或旧前端资源。

Memory Center no longer hosts the bundled HTML workbench or Vue SPA. `/ui/*` and `/app` were removed and return `404`; the server provides no redirect, HTML fallback, or legacy frontend assets.

交互式展示请使用 Memory Center DSH Plugin。自建集成应直接消费 `/workspace/*` JSON 读模型，并仅把响应中的脱敏、有界字段展示给用户。

Use the Memory Center DSH Plugin for interactive presentation. Custom integrations should consume `/workspace/*` JSON read models directly and display only their bounded, sanitized fields.

## 旧入口映射 / Legacy Endpoint Mapping

| 已下线入口 | DSH 对应视图 | JSON 读模型 |
|---|---|---|
| `/ui`、`/ui/dashboard` | 概览 | `GET /workspace/workbench-summary`、`GET /workspace/status` |
| `/ui/continuity`、`/ui/task` | 任务 | `GET /workspace/work-resume`、`GET /workspace/task-delivery-overview` |
| `/ui/timeline`、`/ui/ref` | 任务时间线与证据 | `GET /workspace/drill-timeline`、`GET /workspace/receipts` |
| `/ui/impact`、`/ui/group` | 影响 | `GET /workspace/impact`、`GET /workspace/group-impact` |
| `/ui/usage` | 运行 | `GET /workspace/usage-report` |
| `/ui/backend` | 知识与存储诊断 | `GET /workspace/memory-backend`、`GET /workspace/backend-consistency` |
| `/ui/index-freshness` | 质量 | `GET /workspace/freshness`、`GET /workspace/quality-overview` |
| `/ui/jobs` | 运行 | `GET /workspace/job-status` |
| `/app` | DSH 原生工作台 | 不适用；选择所需 JSON 读模型 |

## 集成迁移 / Integration Migration

所有 HTTP 请求继续使用已有的 `workspace` 查询参数；写入、会话记录和受控外部动作仍必须使用 `POST`。展示场景优先使用 `GET` 的只读路由。

All HTTP requests continue to use the existing `workspace` query parameter. Writes, session recording, and controlled external actions still require `POST`. Prefer read-only `GET` routes for display.

```text
# 旧：浏览器打开 /ui/jobs?workspace=/path/to/workspace.yaml
# 新：DSH 运行视图，或由自建前端读取：
GET /workspace/job-status?workspace=/path/to/workspace.yaml&limit=20
```

```text
# 旧：浏览器打开 /ui/dashboard?workspace=/path/to/workspace.yaml
# 新：DSH 概览，或由自建前端读取：
GET /workspace/workbench-summary?workspace=/path/to/workspace.yaml
```

客户端应处理以下状态，而不是把空响应视为成功：

- `404`：请求仍在使用已下线的 `/ui/*` 或 `/app` 路径；改用本表中的读模型。
- `400`：缺少必填 `workspace` 或读模型的其他必填参数。
- `401`：服务绑定到非 loopback 地址时缺少访问令牌。
- 读模型返回的 freshness、coverage 或 evidence 标记：在界面中保留其证据边界，不把 `AMBIGUOUS` 或 `INFERRED` 展示成已验证结论。

## 边界 / Boundaries

- DSH Plugin 是交互式展示层，不保存第二套项目事实。
- Memory Center HTTP 仍是本地 JSON API；不恢复内置静态文件托管。
- 迁移不改变 MCP、CLI 或 `/workspace/*` 既有 JSON 契约。
- 自定义前端不得直接读取 `.memory-center` 下的 SQLite、JSONL、源码或 Wiki 正文。
