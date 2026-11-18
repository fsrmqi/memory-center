# 5.0 项目目录管理指南

> **适用版本 / Version**：5.0.0b32。当前入口与合同见 [5.0 平台指南](V5_PLATFORM_GUIDE.md)，用户可感知的变化见 [CHANGELOG](CHANGELOG.md)。


> 类型：操作与接口事实（current）。项目通过管理页 `http://127.0.0.1:8765/admin/` 或管理员 HTTP API 管理；项目 MCP 与授权随服务提供。

## 存储与身份

服务目录内的 `catalog.db` 是项目登记配置的唯一权威来源，使用 SQLite WAL 和 schema version 1。
项目具有随机稳定 `workspace_id`（`ws_` 加 32 位十六进制），服务具有基于项目 ID 和相对路径生成的稳定 `service_id`。
项目名称或源码根目录改变不改变项目 ID；同一服务相对路径不变时服务 ID 保留。
服务配置包含名称、相对路径、类型和子服务排除路径；`revision` 用于并发更新，`config_version` 只在名称/路径配置更新时递增。

项目状态为 `active`、`paused`、`removed`。列表和详情不返回 removed 项目；移除保留目录记录与所有运行数据，再登记分配新 ID，不复用原项目数据。
控制面最多登记 1000 个未移除项目；索引事实、规则、任务和记忆以后按 `<服务目录>/workspaces/<workspace_id>/` 隔离。
登记只写 catalog 与管理员令牌，不创建索引、规则、任务或记忆文件，也不创建源码目录下的 `.memory-center`。

源码根目录要求服务器可访问的绝对目录路径，登记时解析软链接为实际路径。
未移除项目之间不允许名称重复（去空格、Unicode NFC、忽略大小写）、相同实际路径或父子根目录重叠；暂停项目仍占用名称和路径。
源码与服务数据目录不能互相包含。预览/登记均不读取旧 workspace.yaml、旧 registry、Hook 或 AGENTS 内容，不写源码说明文件。

## 管理员访问

首次启动自动生成 `<服务目录>/admin-token`，权限 0600；重启继续使用相同令牌。令牌文件无效或权限不安全时启动失败，不静默重置。
每个项目管理接口都要求 `Authorization: Bearer <管理员令牌>`；令牌不显示在网页、服务状态或 MCP 返回中。
管理员令牌拥有本机目录管理权限，与普通 MCP 凭据分开。当前按本机单用户部署，不开放远程管理。
Host 必须为已允许的回环主机或显式 `--allowed-host`；浏览器 Origin 必须与实际请求同源，POST/PATCH 要使用 JSON。
没有 Origin 的 CLI 请求仍需令牌。服务不开放跨域 CORS，页面尚未存储管理员令牌。

本机示例（使用默认服务目录；不要把令牌写入提交或共享日志）：

```sh
ADMIN_TOKEN="$(cat ~/.memory-center/v5/admin-token)"
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://127.0.0.1:8765/api/v1/workspaces

curl -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"root":"/path/to/project-a"}' \
  http://127.0.0.1:8765/api/v1/workspaces/preview

curl -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"项目 A","root":"/path/to/project-a"}' \
  http://127.0.0.1:8765/api/v1/workspaces
unset ADMIN_TOKEN
```

容器令牌通过 `docker compose exec -T memory-center cat /data/admin-token` 在本机读取；令牌无需作为镜像构建参数或提交到 Compose 文件。

## 接口合同

所有成功响应均为 JSON；登记返回 201，其余操作返回 200。更新或移除必须携带最近读取到的 revision，过期返回 409，不覆盖并发变更。

| 接口 | 输入与行为 |
|---|---|
| `POST /api/v1/workspaces/preview` | `root`，可选 `workspace_id`（调整已登记项目路径时排除自身）；只读返回建议名称、服务候选与扫描范围 |
| `POST /api/v1/workspaces` | `name`、`root`；重新预览并在同一 SQLite 写事务内验证冲突、写入项目和服务配置 |
| `GET /api/v1/workspaces` | `limit` 默认 20、范围 1–100；`after` 使用上一页 `next_cursor`；返回 `items` 与 `next_cursor` |
| `GET /api/v1/workspaces/{workspace_id}` | 读取登记配置与服务划分，`index_status="not_indexed"` 表示本阶段尚未索引 |
| `PATCH /api/v1/workspaces/{workspace_id}` | `revision`，以及至少一个 `name`/`root`；修改根目录前必须暂停；重新识别服务，不搬运或删除源码 |
| `POST /api/v1/workspaces/{workspace_id}/pause` | `revision`；状态改为 paused |
| `POST /api/v1/workspaces/{workspace_id}/resume` | `revision`；验证源码仍可访问、实际位置没有改变后改为 active |
| `DELETE /api/v1/workspaces/{workspace_id}?revision=N` | 移除接入，返回 `data_retained=true`；不删除源码或服务中的数据 |

登记和服务配置原子提交；事务内再次检查名称、真实路径、父子重叠与 revision。失败回滚，不让未完成登记对外可见。
同一目录并发登记只允许一个成功；同一 revision 的并发更新只允许一个成功。登记后源目录被移走/删除不改变 ID，恢复前需要先暂停并更新路径。
移除不可从普通列表恢复，重新登记会创建新身份；备份与恢复须在服务停止后按版本契约执行，当前不提供在线迁移工具。

## 识别范围与错误

预览扫描根目录及最多两层子目录，总共最多检查 2048 个目录项、返回 256 个服务候选；单个 JVM 构建标记只读取前 16 KiB。
复用已有服务类型注册表，识别 Spring/JVM/Python/Node/Go 等构建标记；不执行脚本、不遍历文件正文、不解析构建模块依赖。
跳过隐藏目录、构建产物、依赖目录、src/test/tests/docs/vendor 和子目录软链接。识别到根服务与子服务时，为根服务记录子服务排除路径，后续索引必须遵守这个划分。
`scan.complete` 只表示上述有界范围内完成，不能推断深层模块都已识别。深层模块需要选择更具体的源码根目录。
没有识别到类型时使用 generic 候选并给出警告；超预算或无法读取目录会返回不完整预览，登记返回 `PREVIEW_INCOMPLETE`，要求缩小范围后重试。

错误统一为 `{"error":{"code":"...","message":"..."}}`，不回显请求正文或令牌。

| HTTP 状态 | 代表性错误 |
|---|---|
| 401 | `ADMIN_UNAUTHORIZED`：管理员令牌缺失/无效 |
| 400 / 403 / 421 | `REQUEST_ORIGIN_REJECTED`：JSON 内容类型、Origin 或 Host 不符合要求 |
| 404 | `ROOT_NOT_FOUND`、`WORKSPACE_NOT_FOUND` |
| 409 | `NAME_CONFLICT`、`ROOT_DUPLICATE`、`ROOT_OVERLAP`、`REVISION_CONFLICT`、`ROOT_CHANGE_REQUIRES_PAUSE`、`ROOT_CHANGED`、`CATALOG_LIMIT` |
| 422 | `INVALID_REQUEST`、`ROOT_INVALID`、`ROOT_NOT_ABSOLUTE`、`ROOT_NOT_DIRECTORY`、`ROOT_NOT_READABLE`、`ROOT_DATA_OVERLAP`、`NAME_INVALID`、`UPDATE_EMPTY`、`PREVIEW_INCOMPLETE` |
| 503 | `SERVICE_NOT_READY`、`CATALOG_STORAGE_ERROR`：刷新或检查服务日志/存储后重试 |

未知 catalog schema、损坏数据库、软链接数据库或无效管理员令牌会阻止就绪；不覆盖为新库。

## OrbStack 接入源码

默认 Compose 不挂载源码。使用可选配置并指定源码父目录：

```sh
MEMORY_CENTER_PROJECTS_DIR=/path/to/source-parent \
  docker compose -f compose.yaml -f compose.projects.yaml up -d --build
```

宿主目录必须已存在，Compose 不自动创建；挂载为只读 `/projects`。登记 `/projects/project-a` 等容器内路径，不能直接填宿主路径。
源码分散时可在自己的 Compose override 中添加多个只读挂载。catalog、索引与记忆始终写入 `/data` 命名卷。
没有旧 workspace 接入或 external/managed 双模式。旧 registry API 源码暂留在旧入口中，5.0 服务装配与应用用例不导入这些路径。

5.0.0b5 增加 `scan.service_limit`；达到服务数量或目录项预算时仍返回 `complete=false`，登记拒绝截断结果，错误信息区分数量超限与读取失败。该预算只影响预览，索引预算独立。
