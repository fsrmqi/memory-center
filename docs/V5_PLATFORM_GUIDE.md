# 5.0 多项目知识服务使用指南

> 当前：5.0.0b13，开发测试版本；不兼容 4.x 接入或导入历史数据。
> 用户已授权连续完成方案，无需每个切片再次确认。此指南描述当前服务入口；旧版文档仅作为核心算法背景。

## 安装与运行

```sh
python3 -m venv .venv
.venv/bin/python -m pip install /path/to/memory_center-5.0.0b10-py3-none-any.whl
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

资源预算：最多 2 个索引子进程、32 个排队/运行任务；源码索引不设置单文件体积、文件总量、总字节数、分块数量硬上限，也不设置默认任务超时；可手动取消。项目规模由实际机器资源决定，失败或取消不发布缩减后索引。轻量向量精确召回最多 5000 块，超过需 PG 部署；PG 使用向量距离查询，维度不超过 2000 的档案建立 HNSW，较高维度使用精确检索。

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

“立即同步”更新新增、修改及删除的页面，然后提交关联项目索引任务。自动同步约每分钟扫描一次；只有内容变化才增加页面修订。索引仍使用现有完整项目 generation 发布流程；若同步与索引重叠，下轮快照检查会补交索引任务。自动同步关闭或来源暂停时，只读取上次手动同步的快照，不自动提交项目索引；需要更新时使用“立即同步”或手动重新索引。索引失败、取消或中断后，自动调度停止，Wiki 目录仍可同步；服务重启或删除失败记录不会重新触发，手动“重试”或“重新索引”才恢复。

Automatic project indexing is enabled only for active sources with auto-sync enabled. Failed, cancelled or interrupted indexing attempts stop automatic scheduling while directory synchronization continues. This state survives restart and job-history deletion; an explicit manual retry or reindex resumes scheduling.

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

## 多语言代码查询（5.0.0b10）

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

索引任务和索引记录的 `code_coverage` 提供语言文件数、解析状态、符号数、已解析与未解析调用数。解析器缺失、语法错误、未知 Vue 脚本语言与外部脚本不算完整解析；未解析调用保留诊断，不能凭空结果断言无调用方。代码图不设置符号和调用点数量硬上限，完整构建登记范围的事实；失败或取消保留旧 generation。代码与引用读取时核对来源哈希，变更后请重新索引。

当前不实现完整编译器类型推断：跨语言业务调用、继承/接口动态分派、匿名回调内部调用、外部依赖、TS 路径别名与 re-export 链、匿名默认导出、Python 动态导入等保留未解析。Go 依赖替换和 build tags 不作为已验证语义。向量检索不作为调用关系证据。原 generation 没有通用图时保留旧入口；在管理页对需要新能力的项目点击“索引”，不自动扫描或迁移所有项目。

## 统一知识治理与 Skill 管理（b6）

旧 Wiki MCP 的治理与多格式资料处理已迁入本仓库。统一 `/mcp` 新增四个入口：`assistant_knowledge`（search/read/brief/analyze/initialize/status）、`assistant_memory`（promote/archive）、`assistant_skill`（analyze/extract/create/list/inspect/validate/publish/published/export/remove）、`assistant_admin`（validate/scan/index）。这是 5.0 的增量合同；旧 4.x workspace 和独立 Wiki MCP 配置不兼容，不再启动旧服务。

管理页新增“知识治理”和“Skill 管理”。写入先生成完整预览，再确认；Skill 发布必须携带任务验证引用。引用会进入发布清单，但系统不自动核验外部引用的真实性，不可表述为普遍验证通过。候选支持正文审阅、来源/哈希校验、导出；删除或停用移入服务回收目录，保留可恢复副本。已有全局 Skill 也可以列表管理。

已登记 Wiki 来源可完整迁入 `/data/governance/wiki`（本机部署为指定 data-dir 下的同名目录）。仅复制支持的文档，不修改原目录；最多 20000 个文档、5 GiB，完整导入仅允许一次且受管库不能已有新内容。此后晋升和归档写入受管库。外部 Wiki 的只读目录同步与受管知识分别维护，来源变动不会自动覆盖受管知识。查询自动增量刷新 FTS 索引；没有独立后台 Wiki watcher；完整迁入先索引文本和附件元数据，再由服务管理的子进程解析附件，停止时终止、重启后继续。未完成时查询携带 indexing 状态，空结果不可作为不存在的结论。`assistant_admin(action="scan")` 返回扫描报告，不自动删除文件。

Skill 默认发布到服务数据目录 `governance/skills`。要供宿主 Agent 实际使用，可私有 Compose override 将专用宿主 Skill 目录挂载为可写 `/agent-skills`，并设置 `MEMORY_CENTER_SKILLS_DIR=/agent-skills`。仅将需要管理的 Skill 目录挂载为可写，源码和原 Wiki 仍可只读。候选和回收目录留在服务数据卷中。备份应同时包括数据卷和宿主 Skill 目录；停用的 Skill 可以从 `governance/trash` 恢复。

默认 local 模式统一管理身份开放全部四个入口。显式 token 模式下，它们只供管理 API 的管理员使用；项目 MCP 凭据不获得全局私有 Wiki 和 Skill 管理权限。

```sh
# 新安装包包含统一的 Wiki Skill，更新现有文件需明确使用 --force（自动保留 .before-v5 副本）。
memory-center-integrations --target agents --target codex --force
# 仅支持 stdio 的宿主使用 memory-center-mcp，无 --workspace、无独立 Wiki MCP。
# MEMORY_CENTER_URL 默认为 http://127.0.0.1:8765/mcp
```

宿主只保留一个 `memory-center` MCP 接入；支持 HTTP 的宿主直接连接 `http://127.0.0.1:8765/mcp`，其余使用上面的代理。移除旧 `personal-assistant-wiki` MCP 配置及 Memory Center DSH 管理插件后，需要刷新宿主会话/重启 DSH 才会重新发现工具。其它 DSH 插件源码不随此次迁移改动；仍调用旧 Memory 工具合同的插件需另行适配。

English: b6 integrates Wiki governance and Skill lifecycle into the single Memory Center service. The four assistant tools are additive to the 5.0 schema. Managed Wiki data, candidate Skills and recoverable removals live in the service data directory; source Wiki documents are retained. Skill publication can target a dedicated writable host mount. Replace the separate Wiki MCP connection with the unified endpoint and refresh host sessions. Other DSH components are outside this migration.


## 项目分析引擎与可选资源限制（b8）

管理页“项目管理 → 编辑项目 → 影响分析引擎”可选择：

- `auto`（默认）：唯一 Java 锚点使用 Java/Spring 专用分析，其他语言使用通用分析；未命中或歧义锚点不回落为 Java 否定结论。
- `generic`：使用通用多语言代码图，只报告有证据的静态关系。
- `java`：使用 Java/Spring 专用分析；非 Java 或不明确的锚点返回边界说明。

设置按项目独立保存，不需要重建索引。管理员 API 为 `GET/PUT /api/v1/workspaces/{workspace_id}/analysis-settings`；PUT 传 `engine` 与 `revision`（未配置时为 0），过期修订返回 409。

索引资源限制默认均为 0（关闭）；设置以下环境变量的正数可启用对应上限：`MEMORY_CENTER_INDEX_MAX_FILES`、`MEMORY_CENTER_INDEX_MAX_TOTAL_MB`、`MEMORY_CENTER_INDEX_MAX_FILE_MB`、`MEMORY_CENTER_INDEX_MEMORY_LIMIT_MB`、`MEMORY_CENTER_INDEX_TIMEOUT_SECONDS`。`MEMORY_CENTER_ALLOW_LARGE_INDEX=1` 可绕过文件数/体积限制，但不绕过显式内存或超时限制。限制在服务启动时读取，修改后需要重启。

清理旧索引会保留当前生效代际和尚未退出的索引进程。删除取消任务时先等待进程退出，失败时保留记录可重试；文件系统删除失败不会计为成功释放空间。

English: Choose Auto, Generic or Java/Spring analysis per project. Auto routes by a unique anchor's language. Settings do not invalidate the index. All resource limits default to zero and become active only when explicitly configured. Generation cleanup is serialized with publication and worker lifecycle management.

## 管理页阅读与分页 / Admin reading and pagination

顶部项目切换仅在知识库、Wiki、长期记忆中显示；项目管理、后台任务、Wiki 目录、知识治理、Skill 与服务设置使用各自页面的范围。已保存内容默认每页 10 条，可切换 20/50 条，按最近更新时间及记录 ID 稳定排序；标题/相对路径和状态筛选作用于全部匹配记录。默认隐藏已移除内容，仍可通过状态筛选查看。正文在独立阅读区展示，编辑使用弹窗；目录来源保持只读。

管理接口 `GET /api/v1/workspaces/{workspace_id}/knowledge/{kind}` 可选参数 `page>=1`、`page_size=1..50`、`q`（最多 200 字符）、`status`。指定 `page` 时返回 `items,total,page,page_size,pages`，页码超出末页时自动回到末页，空结果为第 1/1 页。项目 Wiki 与关联的活动目录来源合并分页；不带 `page` 保留原响应合同。

Project selection appears only in document, Wiki and long-term memory views. Saved content uses server-side pagination, title/path and status filters, a separate Markdown reader and modal editing. Linked directory pages remain read-only. The optional paged API returns items, total, page, page_size and pages; the existing unpaged contract is unchanged.

## 全局 Skill 发现与控制 / Global Skill discovery

在“Skill 管理 → 全局 Skill 发现”登记服务可访问的一个或多个目录；默认扫描关闭，手动启用后点击扫描。Docker 使用挂载后的容器路径。扫描寻找 `SKILL.md`，支持深度 0–8（默认 4），不跟随符号链接、不执行内容或脚本，最多 20000 个目录项，单文档最多 1 MiB；失败保留上次完整快照并明确报错。发现元数据保存在服务数据库，原目录只读。

新发现的 Skill 默认停用；查看正文后可单条启用或停用。来源暂停后不通过 MCP 提供其 Skill；内容发生变化后，读取会报告陈旧，重新扫描会将变更条目停用，需要重新审阅。文件缺失显示为缺失，移除扫描目录只删除服务元数据。此控制不影响 Codex/Claude 等宿主的原有启用状态。

`assistant_skill(action="discovered")` 只列出目录与条目均启用的发现结果，最多检查 20000 条元数据并报告 `truncated`；完整翻页使用管理页面。`assistant_skill(action="discovered_read", name="discovered_<id>")` 读取已启用条目并核对内容哈希，参数 schema 不变。`published` / `read(published=true)` / `remove(published=true)` 现在只作用于带 `publication.json` 的受管发布内容；既有全局目录内容改由发现流程控制，不能通过发布移除动作移动原文件。

Global discovery is opt-in and read-only. Administrators register directories, explicitly scan, review and enable individual Skills. New or changed items default to disabled; paused sources and stale files are excluded from MCP reads. Controls affect only Memory Center. Published lifecycle actions now apply only to managed publications; external global files use discovery and are never moved or deleted.

分页覆盖项目、服务划分、后台任务、知识内容、Wiki 目录、扫描目录、发现 Skill、候选/发布 Skill 及凭据。后台任务与发现结果在数据库分页；已有限额的元数据集合在客户端分页，正文只按知识页或单份 Skill 读取。筛选发生在分页之前，切换筛选/项目/每页条数后回到第一页；删除后页码自动收敛。


## 普通模型与智能整理 / Chat models and organization（b10）

管理页“模型设置”分别保存向量模型与普通模型。普通模型 Ollama 填根地址；OpenAI-compatible 填 API 基础地址（通常以 `/v1` 结尾），服务追加 `/chat/completions`。普通模型密钥用 `MEMORY_CENTER_CHAT_API_KEY` 环境变量，不在页面或数据库保存。调用远程模型会发送本次所选正文；验证连接只发送测试文字。

Wiki 或长期记忆选择一条内容后点击“智能整理”，或点击“整理当前页”汇总本页有效内容；这不是整个知识库的整理。一次最多 50 条、12 万字符，超过时显式提示分批。模型返回正文可编辑，点击“确认保存整理结果”才写入。单篇项目 Wiki 生成新修订并保留历史；只读目录来源及多条汇总生成新内容，原文保留；记忆保存为待确认。预览 30 分钟有效，来源修订或目录文件改变必须重新整理。

API：`GET/PUT /api/v1/chat-model`、`POST /api/v1/chat-model/test`；`POST /api/v1/workspaces/{workspace_id}/organize` 请求 `{kind:"wiki"|"memory",record_ids:[...]}`；返回预览 id/revision/content/sources/copy。`POST .../organize/{preview_id}/apply` 请求 `{revision,title,content}`，对相同预览重复确认返回已保存结果。

English: Separate chat and embedding configurations. Remote chat models receive selected content only. Review and edit previews before applying. Read-only directory sources and multi-item summaries are copied; single project Wiki edits preserve history, and organized memories require confirmation. Previews expire after 30 minutes and enforce source revision/freshness checks.

## 任务进度与并发 / Task progress and concurrency（b10）

`GET/PUT /api/v1/job-settings` 配置 `max_projects`（1–64）、`max_queued`（0–100000，0 表示不限）与 `max_file_workers`（0–64）。默认基于可用 CPU（含 cgroup v2 配额）选择 1–4 个项目进程。设置立即影响新任务，降低并发不终止已运行任务。自 b11 起单项目内的文件解析走进程池：`max_file_workers=0` 表示把同一份 CPU 预算在同时运行的项目之间切分（项目进程本身占一个槽位），填正数表示每项目固定宽度。并行的只能是进程——tree-sitter 的 Python 绑定不释放 GIL，实测 8 线程比串行慢 24%。自 b12 起解析结果按内容缓存：缓存键含内容 sha256 与文件身份，文件内容不变即跳过 tree-sitter 解析，命中与未命中产出逐值相等的对象；缓存只存文件级事实，跨文件关系每次重算，因此改动文件的影响不会被掩盖。缓存位于工作区目录下（不在可被清理的代际目录内），字节预算由 `MEMORY_CENTER_PARSE_CACHE_MB` 配置（默认按可解析源码规模自适应，见下；0 表示关闭缓存），超出后按最近使用淘汰。自 b13 起，扫描/切块阶段顺带算出的内容 sha256 会传给两条解析路径，解析先按键查缓存，命中即不再读取源码：热跑时每个文件只读一次、解析阶段零读取，冷跑仍为解析读取文本但每个文件只算一次哈希。

任务新增 `phase/completed/total/unit/detail/progress_scope/elapsed_seconds/heartbeat_at`；`progress_scope=phase` 时 `progress` 仅为当前阶段完成比例，并非总体耗时比例。`total=null` 表示尚无法确定总量；扫描、解析、关系、服务、向量等阶段分别计数。专用分析显示已完成服务数及当前内部阶段；发布阶段为不确定进度。成功仍为 100%。资源上限继续为可选配置，默认关闭。

English: Job progress is explicitly per-phase, with real counters and indeterminate totals where necessary. Project concurrency is configurable and running jobs are retained when reducing capacity. Since b11, file parsing inside one project runs on a process pool (threads cannot help — tree-sitter does not release the GIL); `max_file_workers=0` splits one CPU budget across concurrently running projects, while a positive value pins a per-project width. Since b12, parse results are cached by content: the key includes the content sha256 and the file identity, so an unchanged file skips tree-sitter entirely while hits and misses return value-identical objects. Only file-level facts are cached and cross-file relations are recomputed every time, so a changed file's influence is never masked. The cache lives in the workspace directory (outside prunable generations) and is bounded by `MEMORY_CENTER_PARSE_CACHE_MB` (default scales with the parseable source size — see below; 0 disables), evicting by least-recently-used. Since b13 the content sha256 computed during scanning/chunking is handed to both parse paths, which probe the cache by that key first and, on a hit, no longer read the source: a warm run reads each file once with zero reads at parse time, while a cold run still reads for parsing but hashes each file only once. The default budget is `max(512 MiB, parseable source bytes × 6)` capped at 4 GiB, so a 175 MiB workspace gets about 1050 MiB instead of a fixed 512 MiB.
