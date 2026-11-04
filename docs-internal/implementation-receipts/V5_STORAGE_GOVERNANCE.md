# b17 存储治理与真实索引验收 / Storage governance and live indexing

本轮延续 b15／b16 改动，版本同步为 Python／Compose `5.0.0b17`、前端 `5.0.0-beta.17`。已更新本地 OrbStack 常驻服务，保留数据卷与已有挂载；未提交代码、未推送、未发布发行版。

## 已实现 / Implemented

- 项目存储治理：按项目设置额外保留的历史成功代际数量，默认 2，当前可用索引另行保护。保存策略不自动删除；预览候选目录后明确确认执行。候选列表分页，解析／向量缓存独立勾选，默认保留。
- 删除前检查项目归属、当前代际、全部排队／运行任务及尚未退出的进程、策略修订与文件元数据指纹。预览 15 分钟过期；变化后重新预览；部分失败显示已删除目录并禁止重放。源码、Wiki、记忆与任务历史不在删除范围，数据库物理页回收尚未实现。
- SQLite 精确向量查询按游标扫描、保留 Top-K，减少候选向量的常驻内存。`MEMORY_CENTER_SQLITE_VECTOR_SCAN_LIMIT` 默认 5,000，正数限制扫描规模，0 关闭；本机部署已显式设为 0。扫描时间仍随向量量线性增长。
- 真实模型调用发现空白分块被拒绝，现过滤空白、完整拆分超长源码行并保留行／列位置。HTTP 拒绝与超时分别报告 `MODEL_HTTP_ERROR`、`MODEL_TIMEOUT`。MCP 工具参数未改动。
- 新管理 API：读取／保存 `storage-policy`、生成 `storage-cleanup/preview`、确认 `storage-cleanup/apply`。旧 prune API 保持原语义；管理页面改用新预览流程。

English: Per-project retention and confirmed cleanup protect active/in-flight generations, with optional caches, stale-plan checks, expiry and non-replayable partial results. SQLite recall streams exact Top-K with a configurable scan budget. Blank and oversized source chunks are corrected; model HTTP errors and timeouts are distinguished. Existing MCP tool schemas remain unchanged.

## 验证 / Validation

- 服务、结构解析、图范围和重建协调回归：**287 passed / 58 skipped**；跳过项主要为未配置数据库环境的分支，不视为通过。
- 临时隔离 PostgreSQL + pgvector 补测：统计、存储治理、向量载荷目标测试 **28 passed / 1 skipped**，包含 12 个 PostgreSQL 专项案例；临时数据库已销毁。正式服务仍使用 SQLite，未验收 PostgreSQL 生产部署。
- 前端构建、wheel 构建、容器依赖检查通过；正式服务报告 b17、ready，容器健康，原数据卷和源码／Wiki／Skill 挂载保留。升级前已在线备份 SQLite 并校验。
- 桌面 Playwright，1440×1000，隔离测试服务：页面正常、无错误遮罩、正常流程控制台无异常。验证未保存策略阻止预览、保存、15 个候选按 10／5 分页、预览不删、明确确认删除、当前和保留代际保护、未勾选缓存保留、单独清理解析缓存，以及后台任务页面导航到项目存储治理。未配置 Browser 插件，使用本地 Playwright 运行时。
- 真实 8 服务项目完成索引，当前 **5,290 个向量**。数据库选取实际短源码分块进行向量自召回和统一 MCP 混合查询，命中原分块，源文件 SHA-256 一致；调用关系使用精确符号 ID 核对双方查询、源码哈希及调用行。取消额外运行任务后进程退出，成功代际仍可查询。失败任务未自行产生重试。
- **133 服务项目**：完成全部服务分析，进入 103,948 分块向量化。用户选择关闭该项目向量后，明确取消于 12,480 分块；取消任务不算完整向量验收通过。后续无向量重建与项目开关的结果见 b18 回执。

## 证据边界 / Limits

GitNexus 已重新建立索引。新存储治理及相关函数的上游影响分析为 LOW；工作树整体变更涉及多轮尚未提交修改，`detect-changes --scope all` 汇总仍为 CRITICAL（35 文件、173 符号、59 流程），不宣称整体图门禁通过。当前仓库未登记到服务项目目录，未借用业务项目工程会话。

精确检索的自召回验证不是业务问答质量评测；静态调用解析仍有未解析边，空结果不能证明调用不存在。已保留的历史代际是文件工件，不能据此承诺历史数据库向量可直接回滚。清理统计为逻辑字节，不能等同于共享数据库／容器卷物理释放量。

English: Unit/regression tests, isolated SQLite/PostgreSQL checks, desktop interactions and local deployment passed. Live indexing validation is tracked separately above. Whole-working-tree graph review remains CRITICAL; no commit or release was performed. Retrieval smoke checks do not establish semantic quality or complete call-graph coverage.
