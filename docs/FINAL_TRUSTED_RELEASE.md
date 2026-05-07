# Memory Center Trusted Release Notes / 记忆中心可信版说明

## 中文

本版本把 Memory Center 从“可用 MVP”升级为更适合公开发布的可信工程记忆组件：

- **索引器插件化**：新增 `memory_center.core.indexing`，默认提供零依赖 `RegexJavaParser`，后续可接入 `tree-sitter-java` 或 JavaParser sidecar。
- **关系图谱加深**：在基础 Service/File/Class/Method/Endpoint/Feign/MQ 图谱外，新增 Bean 注入、方法调用、DTO 字段访问、配置键访问、Mongo/ES 数据资源等证据边。
- **影响分析分级**：`memory_impact` 不再只返回笼统 impacts，而是输出 `confirmed_impacts`、`probable_impacts`、`possible_impacts`、`unknown_risks`，避免 AI Agent 把弱推断当成精确事实。
- **SQLite FTS5 混合检索**：图节点支持 FTS5；若本地 SQLite 不支持 FTS5，会自动回退到 LIKE 查询。
- **doctor self-test**：`memory-center doctor --self-test` 可以在没有 pytest 的环境里做基础健康检查。
- **安全默认只读**：查询、上下文、影响分析、契约查看默认只读；经验记录、wiki/skill 生成只写 `.memory-center` 或指定输出目录，不修改业务源码。

## English

This release upgrades Memory Center from a usable MVP to a more trustworthy public component:

- **Parser plug-in architecture**: `memory_center.core.indexing` provides a dependency-free regex parser by default and leaves room for `tree-sitter-java` or a JavaParser sidecar.
- **Deeper graph relationships**: Beyond Service/File/Class/Method/Endpoint/Feign/MQ, the graph now records Bean injection, method-call hints, DTO field access, configuration key usage, and Mongo/Elasticsearch resource usage.
- **Evidence-based impact analysis**: `memory_impact` returns `confirmed_impacts`, `probable_impacts`, `possible_impacts`, and `unknown_risks` so agents do not treat weak static-analysis hints as exact compiler truth.
- **SQLite FTS5 hybrid search**: Graph nodes are indexed through FTS5 when available and gracefully fall back to LIKE search.
- **Doctor self-test**: `memory-center doctor --self-test` provides a smoke test even without pytest.
- **Read-only by default**: Query/context/impact/contract tools are read-only; write tools only write Memory Center artifacts unless explicitly directed.

## Safety boundaries / 安全边界

Memory Center never runs arbitrary project commands during indexing. `detect-changes` only calls local `git diff --name-only` and never sends source code outside the machine. Optional semantic providers must be explicitly configured by the user.
