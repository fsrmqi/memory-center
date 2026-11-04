# 5.0.0b6 知识治理与 Skill 集成回执

独立 Wiki MCP 的知识读取、全文检索、任务简报、晋升、归档、模块路由校验、垃圾扫描，以及多格式资料提取、Skill 候选/来源校验/发布实现已迁入 `memory_center.platform.assistant`。不存在对旧项目目录或旧 Python 包的运行时依赖。迁移来源为此前独立 Wiki MCP 的本地实现；不改动其它 DSH 插件源码。

统一平台通过 Governance 应用对象复用四个 MCP 入口和 `/api/v1/governance` 管理接口。管理页增加知识治理、Skill 管理；默认本机模式开放四个入口。token 模式保留管理员 API，项目凭据不暴露全局治理能力。

受管知识、候选和回收目录位于服务数据目录；Wiki 原始来源可只读挂载，完整迁入保留文档和附件，不修改来源。20000 文件/5 GiB 预算覆盖当前迁移规模。初始文本和附件元数据索引后，服务子进程逐步解析附件，定期提交进度，退出时终止并在重启后恢复。历史附件抽取错误有单独统计，不假定每个附件可全文查询；旧二进制格式和图像默认只有元数据，不提供 OCR。

Skill 发布支持专用可写宿主挂载，默认数据目录持久化。校验核对来源和生成工件哈希；发布记录任务引用，不自动验证外部引用真实性。移除保留可恢复副本。发行包包含统一 Wiki Skill 与 `memory-center-integrations` 安装器，避免继续维护独立仓库。

验证：

- 完整服务测试（SQLite + 隔离 PostgreSQL）106 项通过；新增附件后台索引/退出验证通过。
- 前端类型检查和生产构建通过；真实浏览器完成 Wiki 迁入/检索和 Skill 预览、创建、校验、发布、停用，控制台错误 0。Browser 插件未提供，采用 Playwright。
- wheel/sdist 和 Docker 镜像构建通过；发行包含内部治理包、统一 Skill 资源与页面静态产物。
- 官方 MCP SDK 验证运行服务 HTTP 和 stdio 代理各列出 17 个工具，四个 assistant 入口均实际调用成功。
- 实际用户迁移 8310 个文档和附件，逐文件 SHA-256 比对无差异。8284 个可索引条目（临时 Office 文件不索引），10 个附件抽取失败已在结构分析中显式报告；其原始文件仍已保留。
- 已登记旧独立 Wiki MCP/DSH 管理插件移除宿主接入，旧组件从原路径移至可恢复废纸篓；原 Wiki 内容目录保留。现有 Wiki Skill 切换统一服务协议，其它插件源码未改。

共享 Platform 接入入口的图影响检查为 CRITICAL；新组件首次分析 UNKNOWN 时已核对实际 HTTP/MCP/UI 调用位置。提交前刷新 GitNexus 并检查全量变更，测试通过不改变共享入口的风险等级。

English: Wiki governance and Skill management now live in one Memory Center service. Source Wiki documents are retained, migrated copies were hash-verified, and historical extraction failures remain explicit. Other DSH components are unchanged. Host sessions must refresh to discover the unified tool set.
