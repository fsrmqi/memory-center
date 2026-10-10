# 5.0.0b4 多语言适配实施记录

日期：2026-10-10。开发分支：`codex/service-platform`。

## 已交付范围

参考本地 GitNexus 的语言注册、Vue SFC 脚本提取和声明/引用分阶段处理，沿用本项目 Python 服务架构实现。默认 wheel 和容器提供 Java、Python、Go、TypeScript/TSX、JavaScript/JSX、Vue 解析，无需另装 multilang 扩展。Kotlin 保持可选。

新 generation 写入 `code-graph.json`，以文件路径、类型、限定名和声明行建立稳定符号身份。解析作用域、明确导入及别名、前端命名导出和命名默认导出、Go 同包和项目模块；函数参数与局部变量遮蔽阻止错误导入关联。Vue 脚本保留原文件行号，模板不作为脚本解析。

MCP 参数保持兼容。symbol/callers/callees 返回通用 symbols/chain、覆盖统计、歧义和截断状态；非 Java context/影响分析提供直接静态关系，Java 专用 Spring/Feign/MQ 分析保留。响应字段变化已在 README、MCP_GUIDE、CHANGELOG 和平台指南说明。旧 generation 不自动迁移，需要在管理页对目标项目重新索引。

## 验证结果

- 122 项相关测试通过：服务完整回归（SQLite 和隔离 PostgreSQL）、结构解析、语言注册、多语言索引、Java IR。
- 新增跨文件导入、别名、命名默认导出、同名隔离、参数及闭包遮蔽、Vue 行号、Go 包与接收者、语法错误和未解析调用测试。
- 真实 Worker → MCP 查询验证目标语言；项目授权隔离和源码变化后引用失效通过。
- 默认镜像真实服务验收：只读挂载 10 个源码文件，七类语言状态均为 parsed，13 个符号、6 条解析调用；官方 MCP SDK 完成 7 个入口查询。
- Ruff、Git diff 空白检查、管理页构建、wheel/sdist 与 Docker 构建通过。运行中的本机服务更新为 5.0.0b4。
- GitNexus 变更检查完整返回，partial=false、truncated=false；暂存后检查为 35 个变更符号、19 个关联流程，风险级别 CRITICAL。风险来自共享解析器及服务入口，不能用零调用方或测试通过声称无影响；上述回归覆盖已改变的解析和服务查询行为。新通用图函数未出现在变更符号锚点清单中，已通过 Jobs、Platform 的直接引用核对与专项测试补充验证，未把图中的零结果视为无影响。

## 已知边界

此版不是完整编译器或 GitNexus 全功能移植。跨语言业务调用、继承/接口动态分派、匿名回调内部调用、外部依赖、TS 路径别名与 re-export 链、匿名默认导出、Python 动态及函数内导入、Go replace/build tags 等不作为已验证解析能力。无法静态确认的调用保留未解析，不允许据此作“没有调用方”的负面结论。Java 类名限定调用标记为推断。

源码变化后索引需重建；语法错误及缺少语法库显示 partial/unavailable。图预算为 50000 个符号和 100000 个调用点，超限失败并保留旧 generation。完整能力与操作见 [平台指南](../V5_PLATFORM_GUIDE.md)。
