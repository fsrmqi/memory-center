# 5.0 b15 参考能力实施回执 / Reference adoption

状态：开发中，未发版、未部署。日期：2026-10-10。Python、前端及 Compose 开发版本同步为 b15，MCP tool schema 保持兼容。本回执覆盖本轮授权的可靠性修复和参考机制吸收，不代表完整复制参考项目。

## 实现清单 / Implemented scope

| 来源 | 本轮落地 | 边界 |
| --- | --- | --- |
| WeKnora | 模型重排、独立知识刷新、全库 Wiki／记忆后台整理、来源文件更新／删除传播 | 继续使用本项目 Python 应用层、SQLite／PG；没有引入它的 Go／Redis／沙箱／IM 全套服务 |
| GitNexus | TS／JS／Vue 项目内 tsconfig／jsconfig 路径别名、命名／星号 re-export 链与循环保护；Java／Python 可确定继承调用 | 继承边为 INFERRED；外部包配置、动态派发、复杂泛型、未确定多继承不猜测；Go 沿用现有显式包解析 |
| agentmemory | 默认关闭的会话资料接入、待确认候选、全库模型提炼、精确重复分组、来源修订门禁、人工答案键检索回放 | 不扫描宿主聊天日志；不自动晋升知识；重复分组按规范化文本哈希，不称语义去重 |
| archify | 安全失败回执：错误码、阶段、对象、诊断标识与受支持的人工处理建议 | 不持久化原始异常正文；失败后不自动修复或无限重试 |
| ARTEX | 阶段事件、实际完成量、整理模型耗时和供应商 Token 用量、嵌入请求数与累计耗时 | 用量缺失显示未提供，累计请求耗时在并发时可超过墙钟；没有宿主执行链路追踪 |
| dsh-context | 已发现 Skill 的正文大小和 Token 成本估算 | 按字符数除 4 估算；不是 tokenizer 精确值或宿主实际注入用量；不调整其他 DSH 插件 |
| HowToLiveBetter、hamuleite、ai-agent-handbook | 作为资料组织参考；既有 Markdown 目录、文档导入、修订与分页机制继续承载 | 未导入真实资料，不把资料正文的指令当作工程指令 |
| academic-research-skills、academic-research-skills-codex、literature-review-skill、paper-plot-skills | 作为 Skill 目录结构参考；既有目录扫描、内容变化停用、审阅启用机制承载 | 不批量启用或发布外部 Skill；未授权的宿主配置保持原样 |

英文摘要：Reference mechanisms are adapted into the existing application, with conservative resolution and review gates. External source collections are not imported or enabled automatically; other DSH plugins are untouched.

## 管理页操作 / Admin flows

1. **模型设置**分别配置嵌入模型、普通整理模型和可选重排模型。重排地址是提供 `POST /rerank` 的根地址，格式为 `results: [{index, relevance_score}]`，需返回全部候选各一次。Ollama 普通模型接口不自动提供重排。密钥由 `MEMORY_CENTER_RERANK_API_KEY` 提供，不写入页面记录。
2. **Wiki／长期记忆 → 后台整理全部内容**：一次性读取全部来源标识与修订，分批读取正文并生成待审预览。**后台任务 → 知识任务 → 详情 → 审阅 → 确认保存**；不自动覆盖。每批最多 20 条且控制输入字符量，超大单篇明确失败，不截断。批量预览有效期 7 天，保存前仍检查每条来源修订；普通交互预览保持 30 分钟。
3. **刷新知识索引**：已经有源码索引时，只重建有效知识分块／词项／向量并在事务内替换，源码 generation、代码图和代码分块保留。配置或模型变更、来源变化、取消均阻止发布。首次项目仍需完整索引。
4. 启用了目录自动同步的 Wiki，文件更新与删除通过独立知识任务刷新。失败、取消或中断后自动刷新停止，需手动重试；停用／解除关联的来源立即从检索可见范围移除，可手动刷新回收旧分块。
5. **长期记忆 → 受控会话资料**：每项目默认关闭。启用后手动提交来源标识和资料，生成 pending 候选；同项目、同来源、同正文去重。模型提炼结果保持待确认，不自动成为有效长期记忆。
6. **知识页面 → 检索评测**：传入人工核对的查询、模式、期望来源标识，报告来源级 recall／precision 及重排状态，不自动调参。检索结果显示来源标识，便于制作答案键。
7. **后台任务 → 详情**显示诊断与阶段事件；**Skill 管理 → 全局发现 → 查看**显示正文大小和估算 Token。

## 可靠性与存储 / Reliability

- 并发项目数和每项目解析进程数共用 CPU 预算，给配置的后续项目槽位预留容量；显式 worker 值同样是受全局预算约束的上限。修改设置仅影响新任务，不强行缩减正在运行的进程池。
- 损坏 UTF-8 缓存降级为 miss；解析缓存 schema 升为 2 以避免复用缺少 inheritance／re-export 元数据的旧 IR。共享缓存键版本意味着旧向量缓存也可能失效并重算。
- 嵌入最多保留 concurrency 个在途批次，返回后检查取消；取消后不消费或写入返回结果，未开始的请求取消。已经在途的 HTTP 不能撤回，等待其超时／返回。POSIX 索引进程拥有独立进程组，终止时覆盖解析子进程；Windows 仍使用普通进程终止。
- 知识读取移除原有隐含 1000／2000 行读取截断；目录扫描的显式 2000 页／32 MiB 和单页预算仍保留，超出明确失败。
- 知识任务为独立持久队列，当前一个后台线程执行，服务重启把 running 标为 interrupted，不自动重新执行失败任务。队列与索引并发独立；普通模型 HTTP 超时为 100 秒，关闭时在途请求可能等待。
- SQL 范围清理与 Wiki 重试保护的前轮修复继续保留。没有还原大量路径 OR 查询或自动重试循环。

## HTTP 新增能力 / Additive API

管理 API 前缀 `/api/v1`，继续使用既有管理权限；未改变 MCP 工具参数。

- `GET/PUT /rerank-model`
- `POST /workspaces/{workspace_id}/knowledge-tasks`，kind 为 `wiki`、`memory`、`refresh`
- `GET /knowledge-tasks`（分页）、`GET /knowledge-tasks/{task_id}`、`POST .../cancel`、`POST .../retry`
- `GET /workspaces/{workspace_id}/organize/{preview_id}`；保存复用现有 `POST .../apply`
- `GET/PUT /workspaces/{workspace_id}/capture-settings`、`POST .../session-candidates`
- `POST /workspaces/{workspace_id}/retrieval-evaluation`

## 验证与限制 / Validation

本轮隔离用例覆盖：全局预算、损坏缓存、取消与有界请求窗口、重排响应与回退、TS 别名／JSONC／re-export／循环、Java／Python 继承与未导入基类、全库多批预览、来源变化与取消丢弃预览、候选默认关闭与幂等、独立知识刷新与删除词项传播、人工答案键评测。既有服务测试继续验证文档摄取、Skill 管理、权限隔离与 MCP 合同。

桌面验收：临时数据目录、`http://127.0.0.1:18765/admin/`、1440×1000。Browser 插件未列出，使用已打包的 Playwright；页面身份、非空、无框架错误覆盖、无页面或控制台错误、截图以及“模型设置 → Wiki 全库入队 → 后台知识任务 → 失败详情”均通过。普通模型未配置时明确显示 CHAT_NOT_CONFIGURED 与人工重试建议。截图保存在临时目录，不提交构建产物或私有数据。

PostgreSQL 集成需要隔离测试库；本机 OrbStack／Docker 当前未运行。真实大项目冷／热重建、多项目资源压力、真实模型质量、实际知识答案键和 Windows 子进程取消仍需要运行环境与真实样本；不以合成测试宣称这些已验收。正式发布保持待办。

英文摘要：Automated fixtures and desktop UI checks verify implemented behavior; PostgreSQL, real-model quality, production-scale performance and Windows descendant cleanup remain explicit validation boundaries. No deployment or release was performed.

GitNexus 已执行修改前 impact 与修改后 detect-changes：当前索引落后 7 个提交，部分符号定位异常；变更分析为 CRITICAL，不能视为干净门禁或完整覆盖，新文件尚不在旧图中。已结合源码调用方和回归测试验证；本轮没有提交或发版，正式提交前仍需修复／重建图索引并复核。

最终自动回归命令：`pytest -q tests/service tests/regression/test_structural_parser.py tests/index_storage/test_graph_scope_limits.py tests/index_storage/test_reindex_coordination.py -o addopts=''`，结果 **268 通过、45 跳过、2 条依赖告警**。前端类型检查／构建、wheel 构建及新增模块／版本／私有运行目录排除核对通过。旧协调测试的替身已同步 b11 以来的 pool／cache／source_digests 参数。

桌面成功流程另外使用本机隔离模型协议端点验证“后台整理 → 审阅 → 编辑标题 → 确认保存”，HTTP 返回 200、内容修订为 2、原文进入 versions，页面和控制台无错误；此端点是测试工件，不是实际模型质量证据。
