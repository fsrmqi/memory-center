# 5.0 S0 服务骨架实施回执

> 类型：历史验证证据（historical）。日期：2026-10-09。分支：`codex/service-platform`。
> 验证包版本：5.0.0a1，开发预览，未发布正式 5.0.0。S0 已完成，S1 等待用户确认。

## 实际改动与边界

新增 `memory_center/service/` 装配层和 `memory-center-service`，不导入旧 CLI/MCP 入口、不发现旧 workspace、不初始化项目索引；默认新数据目录 `~/.memory-center/v5`。
FastAPI 0.143.0、Uvicorn 0.47.0、MCP SDK 1.27.1 固定版本。采用已实测的 v1 FastMCP API；外层 lifespan 显式启动/关闭 SDK session manager。使用有状态 Streamable HTTP，让取消通知能命中同一传输 session 中的执行请求。传输 session 不承担项目身份。

新增存活/就绪、状态 API、只读 MCP `mc_service_status`、Vue 3/TypeScript/Vite 无项目页面。页面支持读取实际状态、超时错误和刷新。本阶段不暴露目录登记或旧项目工具。
新增 wheel 静态资源分发、sdist 前端源文件与锁文件、非 root Docker 多阶段镜像和 Compose；Docker 构建使用完整 Python 3.11 依赖锁及哈希校验。

源码复用边界已经在 [技术方案](../SERVICE_PLATFORM_TECHNICAL_PLAN.md) 中盘点：解析/调用图/检索/影响分析/证据治理保留为引擎；5.0 空间、授权与任务合同按 S1–S3 实施。S0 不改这些核心符号。当前公开接口及错误语义以 [运行指南](../V5_SERVICE_GUIDE.md)、路由和契约测试为准。
旧入口暂留源码供拆分，后续阶段替换/删除；不提供兼容转发，也不导入历史数据。

## 验证结果

| 验证 | 结果与限制 |
|---|---|
| `python -m pytest tests/service tests/regression/test_architecture_seams.py tests/entrypoints/test_documentation_contracts.py` | 26 通过，包含 6 项服务/文档合同测试 |
| `ruff check memory_center/service tests/service` | 通过 |
| `npm ci` / `npm run build` | Vue 类型检查与生产构建通过 |
| `python -m build` | wheel、sdist 构建通过；wheel 有 HTML/CSS/JS；sdist 有前端源文件、锁文件，无 node_modules |
| 干净虚拟环境安装 wheel，在仓库外启动 | 页面和两项静态资源、MCP initialize/call、SIGTERM、端口重新绑定均通过；运行时不依赖 Node.js |
| 生命周期与数据边界 | readiness 在启动前/关闭后为 503；启动后为 200；无效旧配置未读取/改写；新目录探测不残留文件 |
| 真实 TCP MCP | initialize、tools/list、tools/call、未知工具失败、session 结束通过 |
| MCP 取消 | 测试专用慢工具收到 notifications/cancelled 后执行 finally，返回取消错误，服务继续就绪；生产工具目录没有测试工具 |
| Host 防护 | 不受信任 Host 返回 421；回环 Host 支持带/不带端口 |
| 端口冲突 | 第二实例退出 1，明确提示地址/端口不可用，不更换端口 |
| OrbStack Linux arm64 | 镜像构建、Compose 启动、healthy、真实页面资源/MCP调用、停止和重启、命名卷保留通过 |
| 容器正常关闭 | SIGTERM 执行关闭生命周期，容器退出 143（信号退出）；停止后可重新绑定宿主端口 |
| 浏览器 | 实际打开管理页，显示 5.0.0a1 与服务就绪；刷新仍读取真实状态 |

Docker Hub 认证端点在本机连接重置，改用 Docker 官方镜像的 ECR 公共镜像源后构建成功；未改变宿主网络或代理设置。
测试出现 2 项依赖告警：Starlette TestClient 对 httpx 的弃用提醒，以及 MCP SDK Settings 的前向类型引用告警。实际启动、请求、取消和关闭均通过；升级 SDK/测试客户端时再验证兼容性，不屏蔽这些告警。

本步没有运行整个 4.x 测试套件，不声称所有旧传输仍兼容。没有创建索引 Worker，因此 Worker 排空/进程崩溃恢复由 S3 验证。Dockerfile 可按平台构建，但本步仅实测 arm64，amd64 和正式发行矩阵在 S5 验证。

GitNexus 对新增服务符号返回 UNKNOWN（尚未进入索引），本地确认模块为全新文件且未接入现有核心调用流。提交前执行 staged detect-changes；其结果需结合新文件实际调用/测试判断，不能把受索引范围限制的 0 affected processes 当作不存在影响的证明。

## 下一步

用户确认后才进入 S1：稳定 workspace ID、SQLite catalog、项目识别预览和登记/列表/改名/暂停/恢复/移除接入。S0 的 ready 不代表这些功能已实现。
