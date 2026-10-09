# 存储

提供工作区文件系统访问、统一运行时 SQLite、向量索引和数据库 pragma。

持久化机制应放在此处；解释、检索策略和任务工作流属于上层。

交付回执的 JSONL 是可检查审计源，`delivery_receipts` 表是按任务惰性回填和增量同步的查询读模型。`delivery_receipt_acceptance` 与 `delivery_receipt_evidence_refs` 只保存验收和证据引用的稀疏关系，用于门禁覆盖查询。旧日志在锁内按 500 条分批回填，`projection_version` 触发惰性 schema 升级；同步水位只能登记读取前的文件状态，禁止跨过并发追加。业务代码不得另建 SQLite 连接，也不得在热路径扫描或反序列化完整回执历史。

5.0 控制面由 `CatalogStore` 独立管理服务级 `catalog.db`：登记配置、稳定身份、revision 与事务冲突检查。它不替代每个 workspace 的索引/记忆事实库，不读取 4.x registry。各应用用例通过 Store 访问目录，不自行创建 SQLite 连接。
