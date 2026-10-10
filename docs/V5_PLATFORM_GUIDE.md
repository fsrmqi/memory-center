# 5.0 多项目知识服务使用指南

> 当前：5.0.0b5，开发测试版本；不兼容 4.x 接入或导入历史数据。
> 用户已授权连续完成方案，无需每个切片再次确认。此指南描述当前服务入口；旧版文档仅作为核心算法背景。

## 安装与运行

```sh
python3 -m venv .venv
.venv/bin/python -m pip install /path/to/memory_center-5.0.0b5-py3-none-any.whl
.venv/bin/memory-center-service --data-dir /path/to/new-service-data
```

也可使用 `scripts/service/install.sh` 独立安装。`memory-center` 现在启动同一个 5.0 服务；`memory-center-mcp` 是 HTTP 服务的 stdio 代理，不读取旧 workspace；旧 `memory-center-http` 发行入口已移除。

服务前台运行，Ctrl+C 正常停止。后台常驻由 Docker Compose 的 `restart: unless-stopped` 管理。管理页 `/admin/`，就绪 `/health/ready`，MCP `/mcp`。默认 local 模式：管理页直接打开，MCP 无需令牌并开放所有已接入项目与全部工具。本机客户端共用管理身份；项目暂停与会话项目绑定继续有效。一个数据目录同时只允许一个服务实例。

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

1. 直接打开管理页，添加项目，识别预览并保存。
2. 在项目列表启动索引，后台任务页面查看状态、进度、失败原因、取消或重试。
3. 索引成功才发布 generation；取消、失败、超时与进程中断保留上一份索引。重启将遗留 running 标记为 interrupted，queued 继续执行。
4. 项目改名保留身份；调整目录需先暂停，恢复检查实际目录；配置改变后旧索引标为 stale，需重建。
5. 在知识页面检索，选择混合、关键词、向量或代码符号/调用方/被调用方。结果有文件行范围、来源修订和索引 generation。源码命中实时核对哈希，变化会标记 STALE。

资源预算：最多 2 个索引子进程、32 个排队/运行任务；单任务 10 分钟；源码最多 10000 文件/64 MiB、单文件 1 MiB、最多 30000 分块。超限明确失败，不发布缩减后索引。轻量向量精确召回最多 5000 块，超过需 PG 部署；PG 使用向量距离查询，维度不超过 2000 的档案建立 HNSW，较高维度使用精确检索。

代码事实引擎直接接收 catalog 派生的配置；派生 YAML 与工程事实库位于新服务的 generation 目录，catalog 始终是登记真源。父服务排除已归属更具体子服务的文件。代码查询保留原解析与影响分析能力，向量相似度不能证明调用关系。默认包与容器内置 Java、Python、Go、TypeScript/TSX、JavaScript/JSX 和 Vue 的 Tree-sitter 语法库；无需额外安装 multilang 扩展。Kotlin 仍是可选扩展。

## 模型与向量

模型设置支持 Ollama 和 OpenAI-compatible 批量嵌入协议；地址、模型、维度必须匹配已安装/部署的模型。兼容协议地址通常含 `/v1`。密钥通过服务环境变量 `MEMORY_CENTER_MODEL_API_KEY` 提供，数据库与前端不保存密钥。管理员可以显式验证连接；服务不会在请求中安装或下载模型。

未配置模型时，关键词/代码检索可用，向量模式明确拒绝。模型身份与参数形成档案；即便维度相同，不同模型也不混用旧向量。修改模型后重新索引。嵌入失败不发布新的索引；源码和文档会发送到管理员配置的模型地址。

关键词使用英文/标识符词项与中文 bigram 倒排，BM25 计算文档频率与平均长度，融合用 RRF。该实现没有引入 ParadeDB，不声称与 WeKnora 的中文分词或检索性能等同。候选召回有预算，结果空或来源陈旧不能据此断言项目不存在相关信息。

## 文档、Wiki 与长期记忆

- 文档：文本/Markdown、PDF、DOCX，单份文件最大 4 MiB；解析文本最大 8 MiB，PDF 最多 500 页，不支持加密 PDF。扫描件需外部 OCR。上传内容存服务数据库，不改写项目源码。
- Wiki：人工创建、修订、保留最近 100 个历史版本、回滚形成新修订。来源草稿由当前检索证据摘录生成，人工审阅后保存；没有伪装成 LLM 自动推理。保存引用身份，来源修订或删除后旧引用拒绝继续使用。
- 记忆：推断默认 pending，管理员确认/拒绝。只有 confirmed 参与检索。支持替代和含时区的过期时间。记忆隔离到项目及主体，管理员确认的空间记忆可共享给该空间授权客户端；其他主体的私有记忆不会召回。
- 删除/修订来源后立即从查询中失效，重新索引后清理派生块。每次变更后按页面提示重新索引。

### 本地 Wiki 目录

管理页“Wiki 目录”支持登记多个绝对路径，递归读取 `.md` / `.markdown`，忽略隐藏目录和符号链接。来源独立登记，可先同步，再关联一个或多个项目；关联项目的 Wiki 列表显示这些只读页面，MCP 沿用项目范围检索，无新增工具 schema。原始目录是正文真源，数据库保存派生快照和索引，不改写、移动或删除原文件。

“立即同步”更新新增、修改及删除的页面，然后提交关联项目索引任务。自动同步约每分钟扫描一次；只有内容变化才增加页面修订。索引仍使用现有完整项目 generation 发布流程；若同步与索引重叠，下轮快照检查会补交索引任务。自动同步关闭时只读取上次手动同步的快照，来源配置变化仍会更新项目索引。

每个目录最多 2000 页 / 32 MiB，单页 1 MiB，UTF-8 编码；最多登记 100 个来源。读取、编码或预算失败时整轮不发布部分快照，也不会当作文件被删除，页面显示失败原因。原文件变更会使查询命中标记 STALE，旧引用拒绝继续使用。暂停、解除项目关联或移除来源会立即退出该项目召回，不删除原文件；目录挂载失效时仍可暂停或移除来源。

OrbStack / Docker：在私有 `.env` 设置 `MEMORY_CENTER_WIKIS_DIR=/path/to/wiki-parent`，该目录下可放多个 Wiki，叠加只读挂载：

```sh
docker compose -f compose.yaml -f compose.wikis.yaml up -d --build
# 管理页填写 /wikis/personal、/wikis/engineering 等容器内路径。
```

若已有 PG 或项目挂载，在原组合上追加 `-f compose.wikis.yaml`，停止/重启保持相同组合。分散在不同父目录的 Wiki 可在私有 Compose override 增加多个只读 bind，每个使用不同 target，`bind.create_host_path: false`；管理页登记对应容器路径。不存在的宿主目录不会自动创建。容器用户需具备目录遍历和文件读取权限。Wiki 原始目录需单独备份，服务备份仅含来源配置及派生快照。

## MCP 接入

默认本机模式直接连接 `http://127.0.0.1:8765/mcp`，不需要 Authorization；MCP 接入页提供无令牌 HTTP/stdio 配置。所有已登记项目与工具动态可见，新接入项目无需重发凭据。现有凭据在本机模式不施加权限限制。任务 session/ref/job 使用本机共享管理身份，不提供客户端之间的私有隔离；显式项目范围和会话绑定仍防止项目混用。索引资源预算仍有效。

本机模式原生只允许回环监听，Host/Origin/JSON 校验保持启用。容器内部使用 `--container-local` 监听 0.0.0.0，Compose 仅将端口发布到宿主 `127.0.0.1`；该参数不能保证容器网络隔离，不要把本机模式端口公开到 LAN/公网。

需要认证时使用 `memory-center-service --auth-mode token`，或 Compose 设置 `MEMORY_CENTER_AUTH_MODE=token`。此时管理员令牌位于数据目录 `admin-token`（0600）；页面需要输入令牌，MCP 接入页恢复项目/工具/读写授权与一次性凭据配置。匿名仅可查看服务状态，撤销后已有连接立即拒绝。身份模式属于启动配置，切换后需要重新连接；不会删除现有凭据、项目或记忆。

工具：`mc_workspaces`、`mc_lookup`、`mc_analyze`、`mc_ref`、`mc_start`、`mc_resume`、`mc_close`、`mc_memory_write`、`mc_wiki_write`、`mc_index`、`mc_job_status`、`mc_job_cancel`。这是 5.0 新 schema，不承担 4.x `mc_admin` 等合同兼容。

需要 stdio 的客户端：执行 `memory-center-mcp`，配置 `MEMORY_CENTER_URL`；仅 token 模式需要 `MEMORY_CENTER_TOKEN`。代理只转发官方 HTTP 协议，服务需先启动。

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

## 多语言代码查询（5.0.0b5）

借鉴 GitNexus 的语言注册、Vue 脚本块提取和分阶段引用解析。每次索引先提取声明与导入绑定，再连接调用，写入 generation 的 `code-graph.json`；文件路径、符号类型、限定名和声明行组成符号身份，避免多个文件的同名函数覆盖。Java 的 Spring/Feign/MQ 专用分析继续保留。

| 语言 | 默认结构解析与调用范围 |
| --- | --- |
| Java | 类、接口、方法、构造器；同一类方法、明确包或导入下的类名调用（后者标为推断） |
| TypeScript/JavaScript | 类、函数、方法、箭头函数与命名函数表达式；明确相对导入、别名、命名导出、命名默认导出 |
| TSX/JSX | 上述能力与 JSX 语法；不把 JSX 标签当作函数调用 |
| Vue | normal/setup 脚本分别按 JS/TS/JSX/TSX 解析，保留原始行号；模板只作文本检索 |
| Python | 类、方法、嵌套函数；明确项目模块、相对导入和导入别名 |
| Go | 类型、函数、接收者方法；同目录同包与 go.mod 标识的项目内部导入 |

`mc_lookup` 的 symbol/callers/callees 使用新图；非 Java context 返回符号及直接调用，Java context 保留专用上下文。`mc_analyze` 对非 Java 返回直接静态调用方，Java 继续使用专用影响分析。MCP 参数未改变，新图结果提供 symbols、chain、coverage、truncated 与 negative_claim_allowed；升级前后的结果不能假设完全同形。同名锚点必须使用返回的 symbol id 或 `path:qualified_name` 精确选择，重载方法需使用 id。

索引任务和索引记录的 `code_coverage` 提供语言文件数、解析状态、符号数、已解析与未解析调用数。解析器缺失、语法错误、未知 Vue 脚本语言与外部脚本不算完整解析；未解析调用保留诊断，不能凭空结果断言无调用方。图预算为 50000 个符号、100000 个调用点，超限任务失败，旧 generation 不替换。代码与引用读取时核对来源哈希，变更后请重新索引。

当前不实现完整编译器类型推断：跨语言业务调用、继承/接口动态分派、匿名回调内部调用、外部依赖、TS 路径别名与 re-export 链、匿名默认导出、Python 动态导入等保留未解析。Go 依赖替换和 build tags 不作为已验证语义。向量检索不作为调用关系证据。原 generation 没有通用图时保留旧入口；在管理页对需要新能力的项目点击“索引”，不自动扫描或迁移所有项目。
