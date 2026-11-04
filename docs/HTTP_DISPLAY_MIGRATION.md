# HTTP 展示迁移说明 / HTTP Display Migration

> 文档类型：迁移参考（historical）。适用 4.6.28 起的展示面下线；5.0 的服务入口与接口合同以 [5.0 平台指南](./V5_PLATFORM_GUIDE.md) 与 [REFERENCE](./REFERENCE.md) 为准。

## 结论 / Summary

Memory Center 不再托管内置 HTML 工作台或 Vue SPA。`/ui/*` 和 `/app` 已移除，访问时会返回 `404`；服务端不提供重定向、HTML 回退页或旧前端资源。

Memory Center no longer hosts the bundled HTML workbench or Vue SPA. `/ui/*` and `/app` were removed and return `404`; the server provides no redirect, HTML fallback, or legacy frontend assets.

交互式展示请使用服务自带的管理页 `/admin/`。自建集成应直接消费 `/workspace/*` 的 JSON 读模型，并仅把响应中的脱敏、有界字段展示给用户。第三方宿主前端（如有）属于可选的独立集成，不在本仓库发布范围内。

Use the bundled management page at `/admin/` for interactive presentation. Custom integrations should consume the `/workspace/*` JSON read models directly and display only their bounded, sanitized fields. Any third-party host frontend is an optional, separately distributed integration and is not part of this repository.

## 旧入口映射 / Legacy Endpoint Mapping

| 已下线入口 | 现在的替代 | JSON 读模型 |
|---|---|---|
| `/ui`、`/ui/dashboard` | 管理页概览 | `GET /workspace/workbench-summary`、`GET /workspace/status` |
| `/ui/continuity`、`/ui/task` | 管理页任务视图 | `GET /workspace/work-resume`、`GET /workspace/work-resume-check` |
| `/ui/timeline`、`/ui/ref` | 管理页证据视图 | `GET /workspace/drill-timeline`、`GET /workspace/drill-ref` |
| `/ui/impact`、`/ui/group` | 管理页影响视图 | `GET /workspace/impact` |
| `/ui/usage` | 管理页运行视图 | `GET /workspace/dashboard` |
| `/ui/backend` | 管理页知识与存储诊断 | `GET /workspace/memory-backend-query`、`GET /workspace/backend-consistency` |
| `/ui/index-freshness` | 管理页质量视图 | `GET /workspace/freshness` |
| `/ui/jobs` | 管理页运行视图 | 任务终态见 `GET /workspace/status` 与 [REFERENCE](./REFERENCE.md) |
| `/app` | 管理页 `/admin/` | 不适用；选择所需 JSON 读模型 |

完整端点列表以 [REFERENCE](./REFERENCE.md) 的 HTTP 端点章节与服务实际的 OpenAPI schema 为准。

The complete endpoint list lives in [REFERENCE](./REFERENCE.md) and the live OpenAPI schema.

## 集成迁移 / Integration Migration

所有 HTTP 请求继续使用已有的 `workspace` 查询参数；写入、会话记录和受控外部动作仍必须使用 `POST`。展示场景优先使用 `GET` 的只读路由。

All HTTP requests continue to use the existing `workspace` query parameter. Writes, session recording, and controlled external actions still require `POST`. Prefer read-only `GET` routes for display.

```text
# 旧：浏览器打开 /ui/jobs?workspace=/path/to/workspace.yaml
# 新：管理页任务视图，或由自建前端读取：
GET /workspace/status?workspace=/path/to/workspace.yaml

# 旧：浏览器打开 /ui/dashboard?workspace=/path/to/workspace.yaml
# 新：管理页概览，或由自建前端读取：
GET /workspace/workbench-summary?workspace=/path/to/workspace.yaml
```

客户端应处理以下状态，而不是把空响应视为成功：

- `404`：请求仍在使用已下线的 `/ui/*` 或 `/app` 路径；改用本表中的读模型。
- `400`：缺少必填 `workspace` 或读模型的其他必填参数。
- `401`：服务绑定到非 loopback 地址时缺少访问令牌。
- 读模型返回的 freshness、coverage 或 evidence 标记：在界面中保留其证据边界，不把 `AMBIGUOUS` 或 `INFERRED` 展示成已验证结论。

## 边界 / Boundaries

- 管理页是展示层，不保存第二套项目事实。
- Memory Center HTTP 仍是本地 JSON API；不恢复内置静态文件托管。
- 迁移不改变 MCP、CLI 或 `/workspace/*` 既有 JSON 契约。
- 自定义前端不得直接读取 `.memory-center` 下的 SQLite、JSONL、源码或 Wiki 正文。
- 服务按 `workspace_id` 登记项目；登记与预览接口见 [项目目录管理指南](./V5_CATALOG_GUIDE.md)。
