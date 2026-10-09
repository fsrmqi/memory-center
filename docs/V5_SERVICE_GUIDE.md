# 5.0 服务运行指南

> 2026-10-09 当前实施更新：5.0.0b1 已接入多项目授权 MCP、后台索引、知识库/Wiki/记忆管理与 PG/向量后端，已完成本地测试版验收；正式发行仍需真实模型语义与规模评测。用户已授权连续实施。本轮证据见 [实施回执](implementation-receipts/V5_PLATFORM.md)，当前入口与合同见 [5.0 平台指南](V5_PLATFORM_GUIDE.md)。下方较早的 S1/S2 等待确认记录仅保留决策演进背景。


> 类型：操作与接口事实（current）。适用版本：5.0.0a2 / S1，尚未发布正式 5.0.0。

## 安装、启动与关闭

构建者需要 Python 3.11、Node.js 22；安装构建好的 wheel 后运行服务不需要 Node.js。

```sh
npm ci --prefix frontend
npm run build --prefix frontend
python -m build
pipx install --python python3.11 dist/memory_center-5.0.0a2-py3-none-any.whl
memory-center-service
```

Docker 使用 `requirements-service.lock` 锁定 Python 3.11 的完整服务依赖并校验下载哈希；wheel 声明固定的 FastAPI/Uvicorn/MCP 版本。

默认监听 `127.0.0.1:8765`，管理页面为 `http://127.0.0.1:8765/admin/`。
命令以前台方式运行：终端按 Ctrl+C 关闭；服务管理器发送 SIGTERM 也会执行相同的退出流程。
Uvicorn 在退出时关闭 MCP session manager，最多等待 10 秒处理已有 HTTP 请求。当前没有索引 Worker；Worker 排空与恢复在 S3 验证。
不实现 PID 文件或根据端口杀进程的 stop 命令。后台运行由 Compose 或操作系统服务管理器负责。

| 参数 | 默认值与含义 |
|---|---|
| `--host` | `127.0.0.1`；也可用 `MEMORY_CENTER_HOST` |
| `--port` | `8765`；也可用 `MEMORY_CENTER_PORT`；必须为 1–65535 |
| `--data-dir` | `~/.memory-center/v5`；也可用 `MEMORY_CENTER_DATA_DIR` |
| `--allowed-host` | 可重复；为 MCP 添加允许的 Host，如 `memory.local:*` |

CLI 参数优先于环境变量。服务检测新数据目录可写，启动会初始化新的 catalog 与管理员令牌，不查找 cwd 中的 `.memory-center/workspace.yaml`，不读取旧 registry 或绑定。缺页面资源/数据目录不可写则启动失败；监听冲突给出明确诊断，不自动换端口。5.0 的项目能力不通过旧入口转发；旧入口暂留源码，按后续切片替换或移除，不构成兼容承诺。

## Docker、Compose 与 OrbStack

在 OrbStack 启动后，使用 Docker CLI：

```sh
docker compose up -d --build
docker compose ps
docker compose logs -f memory-center
docker compose stop
docker compose start
```

Compose 只向本机开放 `127.0.0.1:8765`，命名卷 `memory-center-data` 挂载到 `/data`。停止/重建容器保留命名卷；不要用 `down -v` 作为日常停止命令。镜像使用非 root 用户运行，包含健康检查和 SIGTERM；Compose 使用 init 进程并留出 15 秒关闭时间。

Docker Hub 连接失败时，可以使用 Docker 官方镜像的 ECR 公共镜像源构建同一 Dockerfile：

```sh
docker compose build \
  --build-arg NODE_IMAGE=public.ecr.aws/docker/library/node:22-alpine \
  --build-arg PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.11-slim
docker compose up -d --no-build
```

Dockerfile 不固定 CPU 平台，可为 Linux arm64/amd64 构建。本步实测 OrbStack arm64；amd64 构建与运行作为 S5 发行矩阵验收项，尚未验证。
默认不挂载源码；S1 提供 `compose.projects.yaml` 只读挂载 `/projects`，登记容器内路径。详见 [项目目录管理指南](V5_CATALOG_GUIDE.md)。配置、索引和记忆写入服务卷。

自启动策略：容器采用 `restart: unless-stopped`，在 OrbStack/Docker 启动后恢复未被手动停止的服务。OrbStack 的登录启动由用户设置；S0 不修改宿主登录项。wheel 前台运行不提供自动启动，S5 再提供可选系统服务安装说明。

## 当前接口合同

| 接口 | 当前行为 |
|---|---|
| `GET /health/live` | 200，`{"status":"alive"}` |
| `GET /health/ready` | 生命周期就绪时 200，否则 503；`{"ready":true/false}` |
| `GET /api/v1/service/status` | 返回服务版本、阶段、已实现能力和项目管理状态 |
| `GET /admin/` | Vue 静态页面；页面刷新读取实际状态 |
| `/mcp` | 官方 SDK Streamable HTTP；支持 initialize、tools/list、tools/call、取消通知与 session 关闭 |
| MCP `mc_service_status` | 无参数，只读；返回与状态 API 相同的结构化对象 |

状态字段固定为 `schema_version="5.0"`、`version="5.0.0a2"`、`stage="S1"`、`ready`、`capabilities=["service_status","workspace_catalog"]`、`project_management="api_ready"`。不返回服务目录或私有项目路径，不将未实现的项目列表伪装为已登记项目。

MCP 采用有状态传输以支持同一传输 session 的请求取消；传输 session 不代表 workspace、任务 session 或访问授权。SDK 子应用挂载在最后，FastAPI 外层 lifespan 显式管理 SDK session manager，避免子应用 lifespan 未执行。
MCP Host/Origin 默认只允许 localhost、127.0.0.1、IPv6 回环及其端口形式，其他 Host 被拒绝（421）；无效 JSON-RPC、未知工具和协议错误使用 SDK 的错误合同。readiness 只说明服务可接收请求，不说明项目索引健康。

S1 已实现独立管理员令牌和受控目录登记 API，见 [项目目录管理指南](V5_CATALOG_GUIDE.md)。MCP 仍仅提供只读状态；项目工具与凭据隔离在 S2 实施，完整管理页面在 S4。
