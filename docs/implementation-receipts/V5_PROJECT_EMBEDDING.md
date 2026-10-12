# b18／b19 项目向量范围 / Per-project vector scope

b19 已于 2026-10-11 部署本地 OrbStack，Python／Compose `5.0.0b19`、前端 `5.0.0-beta.19`，容器 healthy、服务 ready。本会话未执行提交、推送或发行；工作期间检测到外部提交已纳入 b18 改动及 b19 幂等保存修复，已保留。

- 项目设置四种范围：`inherit` 跟随全局（兼容既有项目）、`all` 全部、`knowledge` 仅 Wiki／记忆、`off` 关闭。全局聊天／重排模型独立，其他项目设置不变。
- 相同范围保存保持原修订，只有实际范围变化才影响发布门禁；旧修订仍冲突。
- 图、符号、影响分析和关键词索引不依赖向量。关闭后索引／知识刷新跳过嵌入调用，混合检索使用关键词；显式 vector 查询提示 `VECTOR_DISABLED`。保存不自动创建索引任务，已有向量通过重建移除，不自动删除缓存。
- 查询按实际发布覆盖决定是否需重建；扩大范围或更换模型需手动重建。知识向量过滤在数据库排序／扫描预算之前，避免被源码向量挤出候选或错误触发预算。
- 发布事务核对项目设置修订，变化后 `EMBEDDING_SETTINGS_CHANGED`，保留上一代。API `GET/PUT .../embedding-settings`，请求 `mode`、`revision`；MCP 参数未变，结果新增 `embedding_mode`。
- 回归 **293 passed / 64 skipped**；隔离 PostgreSQL + pgvector 与 SQLite 目标补测 **40 passed / 1 skipped**。包含无模型调用、图／关键词可查、仅知识范围、跨项目隔离、修订冲突和在途设置变更的发布保护。正式服务仍为 SQLite。收尾同值保存修复另测 SQLite／PostgreSQL 项目向量专项 **12 passed**。
- 前端／wheel 构建、源码与打包文件核对、容器依赖检查通过。b19 升级前两个 SQLite 数据库在线备份和 `quick_check` 通过，原数据卷与源码／Wiki／Skill 挂载保留，服务报告 b19、ready。
- 1440×1000 Playwright 桌面验证：默认继承、新建关闭、编辑重新读取、同值保存保持修订、修改为仅知识、项目隔离、正常流程控制台无异常、无错误遮罩；截图为隔离样例。无 Browser 插件，使用本地 Playwright 运行时。
- 用户明确取消大项目向量化于 12,480/103,948 分块；该取消不算完整向量验收通过。随后关闭项目向量，图／关键词重建已成功发布：133 服务、18,474 解析文件、103,948 分块，嵌入模型请求数及数据库向量数均为 0。任务起止时间计算总耗时约 41 分 24 秒，其中服务专用分析约 39 分 22 秒；关闭向量不消除这部分耗时。
- b19 升级后真实 HTTP MCP 验证关键词／符号／调用方／被调用方查询，并以当前源码 SHA256 和实际调用行核对抽样调用边；显式向量查询提示项目已关闭向量。升级前抽样查询分别约 0.72／1.04／0.97／0.97 秒，属于单次抽样，不能代表整体性能基准。
- 升级后同值保存不改变设置修订，大项目当前代际保留，另一项目的继承设置和已发布代际保留。存储清理只预览：当前代际受保护、默认不清缓存，未执行删除。静态图含未解析调用及部分解析文件，抽样验证不代表全部调用覆盖或问答质量已验收。

图索引已刷新，新入口已补充影响分析与源码调用检查；`run_index` 的图上游为 UNKNOWN，确认父进程通过 `multiprocessing.Process(target=run_index)` 调用，并补充真实流程验证。外部提交后的收尾工作树图检查仍为 CRITICAL（11 文件、10 符号、489 流程）；与本轮前基线 `79381bf` 对比为 CRITICAL（55 文件、225 符号、500 流程），不宣称整体图门禁通过。共享设置模块的预编辑分析同样为 CRITICAL；已明确告知，并将收尾改动限于同值保存短路和专项验证。当前仓库未登记服务项目，不借用业务项目工程会话。

English: Project-level embedding scope keeps graph and keyword retrieval independent. Publication validates settings revisions; coverage expansion requires manual indexing. Regression, isolated database checks, desktop interactions and local deployment passed. Full live reindexing is tracked above; no commit or release was performed. Static call-graph coverage and semantic answer quality remain separate validation concerns.
