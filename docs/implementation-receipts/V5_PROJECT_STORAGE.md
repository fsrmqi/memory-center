# b16 项目空间统计交付 / Project storage accounting

本轮仅追加项目空间统计，保留 b15 已有开发改动。版本同步为 Python／Compose `5.0.0b16`、前端 `5.0.0-beta.16`。未提交、未发版、未部署，未处理其他插件。

- 后端：只读项目范围 API，数据库内聚合 UTF-8 文本与原生向量载荷；文件统计区分当前／其他代际、解析缓存、向量缓存和其他项目文件。源码、外部 Wiki 与共享数据库页不归入项目总量。
- 前端：项目管理中选择项目后显示明细、计数、时间与统计口径，按需刷新。向量载荷明确是数据库载荷子项；部分读取、空项目、请求失败与快速切换项目均有明确状态。
- 验证：服务测试、结构解析回归及图范围／重建协调测试共 **272 passed / 49 skipped**。新增统计测试 SQLite 分支 4 项通过；PostgreSQL 4 项因未配置隔离验证库而跳过，不视为已验收。
- `npm run build --prefix frontend` 与 wheel 构建通过；wheel 中版本、新统计模块、管理页产物与源码核对一致。
- 隔离服务桌面验收（1440×1000，Playwright）：页面身份、非空、无框架错误遮罩、正常流程控制台无异常；项目切换隔离、文件大小变化后的刷新、请求失败恢复、延迟旧响应保护均通过。模拟 500 的预期浏览器错误未计为正常流程异常。无 Browser 插件，使用现有 Playwright 运行时；未验收生产容器或真实大项目。
- GitNexus 文件影响分析报告 `Projects.vue` 的上游为 `App.vue`，风险 LOW，但索引落后 7 个提交；路由和新统计函数无法定位，结果 UNKNOWN，补充源码调用检查与隔离测试，未宣称图门禁通过。

English: This development delivery adds scoped storage accounting and refreshable project UI, with explicit payload/file-size semantics and shared-storage exclusions. SQLite tests, desktop interactions and package consistency passed. PostgreSQL, production containers and real large projects remain unverified. No commit, release or deployment was performed.
