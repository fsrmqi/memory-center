# 5.0 多项目知识服务使用指南

> 当前：5.0.0b1，开发测试版本；不兼容 4.x 接入或导入历史数据。
> 用户已授权连续完成方案，无需每个切片再次确认。此指南描述当前服务入口；旧版文档仅作为核心算法背景。

## 安装与运行

```sh
python3 -m venv .venv
.venv/bin/python -m pip install /path/to/memory_center-5.0.0b1-py3-none-any.whl
.venv/bin/memory-center-service --data-dir /path/to/new-service-data
```

也可使用 `scripts/service/install.sh` 独立安装。`memory-center` 现在启动同一个 5.0 服务；`memory-center-mcp` 是 HTTP 服务的 stdio 代理，不读取旧 workspace；旧 `memory-center-http` 发行入口已移除。

服务前台运行，Ctrl+C 正常停止。后台常驻由 Docker Compose 的 `restart: unless-stopped` 管理。管理页 `/admin/`，就绪 `/health/ready`，MCP `/mcp`。管理员令牌位于数据目录 `admin-token`，0600，页面只放在当前内存中，刷新后需重新输入。一个数据目录同时只允许一个服务实例。

### OrbStack

轻量部署保持 `docker compose up -d --build`，使用 SQLite。
标准部署用 `compose.postgres.yaml` 增加 PostgreSQL + pgvector：

```sh
# 数据库密码使用自行生成的 URL 安全随机字符串；保存到私有 .env（0600）。
# .env 中设置 MEMORY_CENTER_DB_PASSWORD，不要提交。
docker compose -f compose.yaml -f compose.postgres.yaml up -d --build
```

源码目录需要容器内可见，叠加 `compose.projects.yaml`，在私有 `.env` 设置 `MEMORY_CENTER_PROJECTS_DIR` 为宿主项目父目录；页面填写容器路径 `/projects/<project>`。该挂载只读，不创建不存在的宿主目录。不得把服务数据目录作为源码根。

PG 目录是独立真源，不自动导入现有 SQLite catalog；两种部署的数据不能只靠切换连接串转换。PG 端口不对宿主公开。数据库镜像使用 `pgvector/pgvector:pg17`，正式发布应固定验收镜像摘要。

停止与重启必须使用相同 Compose 文件组合：

```sh
docker compose -f compose.yaml -f compose.postgres.yaml stop
docker compose -f compose.yaml -f compose.postgres.yaml up -d
```

不用 `down -v` 停服务，它会删除数据卷。

## 项目、后台任务与检索

1. 输入管理员令牌，添加项目，识别预览并保存。
2. 在项目列表启动索引，后台任务页面查看状态、进度、失败原因、取消或重试。
3. 索引成功才发布 generation；取消、失败、超时与进程中断保留上一份索引。重启将遗留 running 标记为 interrupted，queued 继续执行。
4. 项目改名保留身份；调整目录需先暂停，恢复检查实际目录；配置改变后旧索引标为 stale，需重建。
5. 在知识页面检索，选择混合、关键词、向量或代码符号/调用方/被调用方。结果有文件行范围、来源修订和索引 generation。源码命中实时核对哈希，变化会标记 STALE。

资源预算：最多 2 个索引子进程、32 个排队/运行任务；单任务 10 分钟；源码最多 10000 文件/64 MiB、单文件 1 MiB、最多 30000 分块。超限明确失败，不发布缩减后索引。轻量向量精确召回最多 5000 块，超过需 PG 部署；PG 使用向量距离查询，维度不超过 2000 的档案建立 HNSW，较高维度使用精确检索。

代码事实引擎直接接收 catalog 派生的配置；派生 YAML 与工程事实库位于新服务的 generation 目录，catalog 始终是登记真源。父服务排除已归属更具体子服务的文件。代码查询保留原解析与影响分析能力，向量相似度不能证明调用关系。默认包保留 Java 基础解析；Python/Go/TypeScript 等 AST 事实解析需安装 `memory-center[multilang]`，默认容器不包含该扩展。多语言源码的关键词检索不依赖 AST 扩展。

## 模型与向量

模型设置支持 Ollama 和 OpenAI-compatible 批量嵌入协议；地址、模型、维度必须匹配已安装/部署的模型。兼容协议地址通常含 `/v1`。密钥通过服务环境变量 `MEMORY_CENTER_MODEL_API_KEY` 提供，数据库与前端不保存密钥。管理员可以显式验证连接；服务不会在请求中安装或下载模型。

未配置模型时，关键词/代码检索可用，向量模式明确拒绝。模型身份与参数形成档案；即便维度相同，不同模型也不混用旧向量。修改模型后重新索引。嵌入失败不发布新的索引；源码和文档会发送到管理员配置的模型地址。

关键词使用英文/标识符词项与中文 bigram 倒排，BM25 计算文档频率与平均长度，融合用 RRF。该实现没有引入 ParadeDB，不声称与 WeKnora 的中文分词或检索性能等同。候选召回有预算，结果空或来源陈旧不能据此断言项目不存在相关信息。

## 文档、Wiki 与长期记忆

- 文档：文本/Markdown、PDF、DOCX，单份文件最大 4 MiB；解析文本最大 8 MiB，PDF 最多 500 页，不支持加密 PDF。扫描件需外部 OCR。上传内容存服务数据库，不改写项目源码。
- Wiki：人工创建、修订、保留最近 100 个历史版本、回滚形成新修订。来源草稿由当前检索证据摘录生成，人工审阅后保存；没有伪装成 LLM 自动推理。保存引用身份，来源修订或删除后旧引用拒绝继续使用。
- 记忆：推断默认 pending，管理员确认/拒绝。只有 confirmed 参与检索。支持替代和含时区的过期时间。记忆隔离到项目及主体，管理员确认的空间记忆可共享给该空间授权客户端；其他主体的私有记忆不会召回。
- 删除/修订来源后立即从查询中失效，重新索引后清理派生块。每次变更后按页面提示重新索引。

## MCP 接入

管理页创建凭据，明确项目范围与读写权限；原始令牌只显示一次，数据库只保存 SHA-256 摘要。页面生成客户端私有连接配置；不把它提交到 Git。

匿名只允许 `mc_service_status`；项目查询与写入需要 Bearer 凭据。`tools/list` 隐藏未授权工具，直接 `tools/call` 再次验证。传输 session 固定凭据，任务 session/ref/job 绑定主体和项目；撤销凭据立即拒绝已有连接。cwd 与客户端 roots 不授予权限。

工具：`mc_workspaces`、`mc_lookup`、`mc_analyze`、`mc_ref`、`mc_start`、`mc_resume`、`mc_close`、`mc_memory_write`、`mc_wiki_write`、`mc_index`、`mc_job_status`、`mc_job_cancel`。这是 5.0 新 schema，不承担 4.x `mc_admin` 等合同兼容。

需要 stdio 的客户端：执行 `memory-center-mcp`，用私有环境配置 `MEMORY_CENTER_URL` 与 `MEMORY_CENTER_TOKEN`。代理只转发官方 HTTP 协议，服务需先启动。

## 备份与恢复

先停服务，执行：

```sh
memory-center-maintenance backup --data-dir /path/to/service-data --archive /path/to/new-backup.tar.gz
memory-center-maintenance restore --data-dir /path/to/new-restore-directory --archive /path/to/new-backup.tar.gz
```

备份含管理员令牌与数据，0600；拒绝覆盖已有备份或恢复目录；恢复校验清单与内容哈希，拒绝软链接、重复条目和越界路径。SQLite 用数据库 backup API 创建一致快照，恢复重新定位派生索引配置路径。

PG 标准部署还必须同时备份数据库。停服务、保持 postgres 运行后，在相同 Compose 项目导出：

```sh
docker compose -f compose.yaml -f compose.postgres.yaml exec -T postgres pg_dump -U memory -d memory -Fc > /path/to/new-database.dump
```

恢复服务文件快照与 PG 数据库到同一组全新数据卷，保持容器数据路径 `/data`；导入数据库使用 `pg_restore -U memory -d memory`，不覆盖正在使用的数据库。若恢复到不同运行路径，重新索引以发布新的工程事实目录。PG dump 与文件快照需作为一组管理，不能只恢复一侧。本轮已在隔离数据库完成 PG 导出 + 文件快照恢复，验证目录、凭据、Wiki 历史、知识检索及重新索引。大规模项目性能仍需正式发行前验证。

## 当前验证边界

协议夹具只验证嵌入数量/维度、模型档案隔离、数据库向量距离、HNSW 与融合，不代表真实语义质量。当前网络的 Ollama registry 证书校验失败，未关闭 TLS 验证；真实模型语义评测未完成。没有宣称图片中的 IM、浏览器沙箱、联网搜索、Neo4j、所有外部模型厂商等已实现，它们不属于此次 Memory Center 服务化核心闭环。
