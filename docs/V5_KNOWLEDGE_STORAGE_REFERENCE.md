# 5.0 知识流水线、向量化与存储参考方案

> 类型：设计建议。日期：2026-10-09。参考 WeKnora 本地提交 `602d0c388bf17d894f467fe0cd65d1d62c73d303`。
> 当前 S1 使用 SQLite catalog；本文不改变已实施存储、不启动知识库改造。标准部署选型与实施时点待用户确认，按切片推进。

## 架构吸收

用户提供的 WeKnora 架构图有参考价值：多个接入渠道共享授权和业务用例，RAG、Wiki、记忆共享来源与知识处理流水线，耗时操作异步执行，模型与存储通过适配器接入。

Memory Center 保留 Python 模块化单体、FastAPI、官方 MCP SDK 和 Vue 管理页面。代码事实与文档知识采用不同来源处理器：代码保留符号、调用边和契约解析；文档采用解析、分块和引用定位。两者共享空间身份、权限、任务状态、检索接口和证据投影。自动 Wiki 和记忆归纳不能覆盖源码事实。

IM、沙箱、联网搜索、Neo4j、Langfuse 为后续独立能力，不作为 5.0 启动必需组件。

## 本地源码证据

以下路径相对 WeKnora 仓库，结论来自固定版本源码阅读，未对 WeKnora 运行性能作验证。

| 证据 | 已核对设计 | 吸收方式 |
|---|---|---|
| `docs/LITE.md` | Lite：SQLite、内存队列、单空间；标准版：多空间、多服务部署 | 借鉴部署分档，不复制 Lite 的单空间限制；本项目轻量版仍需多项目 |
| `internal/infrastructure/chunker/heading_splitter.go`、`fenced_code.go` | 标题与代码块相关分块处理 | 文档按结构切块，代码按符号切块；保留源位置与父块 |
| `internal/models/embedding/batch.go` | 批量嵌入、池并发、结果数量校验 | 有界任务、超时、取消、重试和失败状态，避免请求内同步全量嵌入 |
| `internal/application/repository/retriever/postgres/repository.go` | pgvector halfvec、维度过滤、知识库/文档范围；关键词使用 ParadeDB 操作符与评分 | 候选召回前限定空间/来源；独立评估关键词扩展与向量精度 |
| `internal/application/repository/retriever/sqlite/repository.go` | FTS5、中文 bigram、按维度 vec0 表、索引写入错误处理 | 中文与代码标识符分别评测；关键词/向量状态不能伪装成功 |
| `internal/application/service/knowledgebase_search_fusion.go` | 按召回列表归一化、去重、加权 RRF | 各后端分数不能直接混加；权重须由本项目回放评测确定 |
| `internal/application/repository/memory_vector.go` | 长期记忆独立向量检索；PG 距离查询与有界回退 | 记忆有独立主体、生命周期、确认状态，不能只当文档块保存 |

注意：图中“PostgreSQL：BM25、pgvector”是能力组合。pgvector 提供向量检索；该版本 WeKnora 的 PostgreSQL 关键词检索使用 ParadeDB，不能把普通 PostgreSQL + pgvector 当成已有相同 BM25 能力。官方说明见 [pgvector](https://github.com/pgvector/pgvector) 与 [ParadeDB 索引](https://www.paradedb.com/docs/reference/indexing/create-index)。

## 存储职责与部署建议

| 数据职责 | 当前轻量部署 | 后续标准部署建议 |
|---|---|---|
| 项目登记、授权、配置 | 服务级 SQLite catalog | PostgreSQL 控制面；切换需单独切片，不保留双写真源 |
| 工程符号、调用关系、索引状态 | 每空间事实库与现有索引引擎 | 先保留事实引擎；是否合并到 PG 由规模与并发证据决定 |
| 文档块、Wiki 版本、记忆条目及来源 | 知识阶段再定义领域表 | 优先 PostgreSQL，主体/空间/来源/版本为显式字段 |
| 向量与关键词派生索引 | 复用现有检索能力，后续接适配器 | 优先 pgvector；BM25 独立选择实现并评测中文效果 |
| 原始文档、附件、导出 | 服务数据目录的本地文件存储 | 先 Docker 持久卷，再按需增加 S3/MinIO 适配器 |
| 后台任务 | S3 有界进程 Worker，持久任务状态 | 单机先保留；多实例再评估 Redis/独立队列 |

对于用户计划的 OrbStack 常驻知识服务，推荐标准部署的第一组外部依赖为 PostgreSQL + pgvector；暂不同时引入 Qdrant/Milvus、Redis、MinIO 和 Neo4j。这个建议是后续选型，不代表当前 5.0.0a2 已具备 PostgreSQL 后端。

如果决定正式 5.0 就以 PostgreSQL 为默认，先在 S2 前增加独立的“存储合同与 PG 可行性”切片，验证 arm64 镜像、中文关键词、事务、空间隔离、备份与重启，再修订 S1 catalog 和后续计划；不能仅换连接串。用户不要求历史兼容，但本次新服务数据是否丢弃仍须明确，不自动清理。

## 向量化合同

写入链路：来源登记 → 解析 → 结构化分块 → 批量嵌入 → 写入派生索引 → 发布可查询 generation。摘要、标签、Wiki 生成属于独立富化任务，不阻塞基础索引就绪。

- 块必须记录空间、来源、内容哈希、源版本、位置（文件行/页码/标题）、父块和解析器版本。代码块再关联符号 ID。
- 嵌入档案记录模型身份、模型版本、维度、归一化和分块策略版本；同维度不同模型也不能混用。更换模型建立新索引 generation，验证后切换，不在查询中下载或冷启动模型。
- 来源修改只重建受影响块；删除立即使旧块不可检索。批次失败不能发布半完成 generation，需可重试与清理孤立索引。
- 查询先授权空间与来源，再分别执行符号/关键词/向量召回，去重融合、可选有界重排，最后投影原始证据。向量结果不证明真实调用边。
- 中文自然语言、精确类名、配置项、跨项目同名符号、删除来源和不同模型分别建立回放样本；评估召回率、延迟、内存和泄漏，避免只看主观回答效果。

## 分阶段落地

1. S2：固定授权范围与请求上下文，为查询适配器保留空间和来源参数；不提前实现文档知识库。
2. S3：后台任务状态、取消、重试、预算与索引 generation 发布合同。
3. 5.0 服务闭环完成后：知识库第一切片验证一份中文文档的解析、引用、关键词/向量混合检索与删除失效；独立确认 PG 部署。
4. 后续：管理页面配置模型与来源，再加入 Wiki 版本和长期记忆治理；按测量结果增加外部队列或专用向量库。
