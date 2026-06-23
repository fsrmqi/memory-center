# Memory Center 演进改造计划

> 本计划基于对 [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)(以下简称 **CBM**)的分析,
> 结合 memory-center 现有架构,给出**逐步可执行**的能力扩展与性能优化路线。
>
> 目标:让 memory-center 从"Spring Cloud 专用工程记忆"演进为"以 Java 为主、多语言通用、跨服务/跨进程可观测的 AI 编程协作记忆中枢",
> 同时保留现有的核心壁垒(facade、任务语义、规则护栏)。
>
> **创建日期**:2026-06-23
> **目标里程碑**:P0(2 周内)→ P1(1 个月内)→ P2(按需)→ P3(远期)
> **执行方式**:按阶段顺序执行;每一步都给出"代码定位 / 变更内容 / 测试 / 验收标准"。

---

## 0. 战略原则(执行前先读)

1. **不重写技术栈**:Python 保留。CBM 的纯 C 不是模仿对象,是参照对象。
2. **不追求 158 语言**:Java/Kotlin/Python/TS/Go 五语言深做 > 158 语言浅扫。
3. **MCP facade 不动**:8 个 facade tool 数量、schema、语义保持稳定。新能力从内部接入,facade 通过参数路由暴露。
4. **CLI / HTTP 接口向后兼容**:新增子命令允许,既有命令不破坏。
5. **每步必有测试**:`pytest -q` 不能变红;新增能力必须配单测;面向用户文档保持中英双语。
6. **每步必可回滚**:每阶段独立分支 + 独立 PR,失败就 revert 单个 PR。

---

## 阶段总览

| 阶段 | 主题 | 价值 | 预估工作量 | 风险 |
|------|------|------|------------|------|
| P0-1 | service.type 解耦 + workspace schema 扩展 | 摆脱 Spring 假设 | 1 天 | 低 |
| P0-2 | 多语言 tree-sitter parser registry | Java 之外能用 | 3~5 天 | 中 |
| P0-3 | SQLite 索引性能优化(PRAGMA + 批写) | 大仓索引 5~10× 加速 | 1~2 天 | 低 |
| P1-1 | Java 深度类型解析(import + 同包 + 同类 3 级 resolver) | 调用边准确率从 ~60% 到 ~85% | 1 周 | 中 |
| P1-2 | 跨服务边抽象化(RemoteCallEdge / ChannelEdge / ProtocolContract) | 通用化 Feign/MQ,可扩 gRPC | 1~2 周 | 中 |
| P1-3 | gRPC + 通用 HTTP + 通用 MQ detector | 跨进程边覆盖非 Spring 项目 | 1 周 | 中 |
| P2-1 | `.memory-center/graph.db.zst` 团队共享产物 | 团队 onboarding 跳过全量索引 | 3 天 | 低 |
| P2-2 | Hybrid LSP 思路落到 Python(jedi) / TS(tsserver) | 跨语言深度推断 | 2 周 | 高 |
| P2-3 | `mc_lookup` 增加 `architecture-overview` mode | 单次聚合视图 | 2 天 | 低 |
| P3 | 单二进制发布 + 多 host(Codex/Zed/...)适配 | 发布形态扩展 | 按需 | 中 |

---

# P0:基础能力解耦(必做,1~2 周)

## P0-1:`service.type` 解耦与 workspace schema 扩展

### 目标
让 workspace 配置不再写死 `spring-boot-service` 假设,允许 `generic-jvm` / `spring-boot` / `python-package` / `node-app` / `go-module` / `rust-crate` 等 type;
现有 Spring 项目无需迁移(默认值兼容)。

### 代码定位
- `memory_center/core/models.py:9-15` — `ServiceConfig` 默认 `type="spring-boot-service"`
- `memory_center/core/workspace_shape.py:209-218` — `_looks_like_module_root` 只看 pom/gradle
- `memory_center/templates/instructions/`(如果有)— `memory-center init` 模板
- `examples/spring-cloud-demo/.memory-center/workspace.yaml` — 参考样例
- `memory_center/cli/main.py` 中 `init` 命令

### 变更内容
1. 新增 `memory_center/core/service_kinds.py`:
   ```python
   SERVICE_KIND_REGISTRY = {
       "spring-boot-service": {"language": "java", "build": ["pom.xml", "build.gradle", "build.gradle.kts"]},
       "spring-cloud-gateway": {"language": "java", "build": ["pom.xml", "build.gradle"]},
       "spring-boot-task": {"language": "java", "build": ["pom.xml", "build.gradle"]},
       "shared-library":     {"language": "java", "build": ["pom.xml", "build.gradle"]},
       "generic-jvm":        {"language": "java", "build": ["pom.xml", "build.gradle", "build.gradle.kts"]},
       "kotlin-module":      {"language": "kotlin","build": ["build.gradle.kts", "settings.gradle.kts"]},
       "python-package":     {"language": "python","build": ["pyproject.toml", "setup.py", "setup.cfg"]},
       "node-app":           {"language": "typescript","build": ["package.json"]},
       "go-module":          {"language": "go",   "build": ["go.mod"]},
       "rust-crate":         {"language": "rust", "build": ["Cargo.toml"]},
       "generic":            {"language": None,   "build": []},
   }
   ```
2. `workspace_shape._looks_like_module_root` 改为按 `service.type` 查 registry 决定 marker 列表;type 未知或 `generic` 时退化为现行逻辑。
3. `ServiceConfig` 增加可选字段 `language: str | None = None`(自动从 `type` 推断,允许显式覆盖)。
4. `memory-center init` 时不再硬编码 services,改为扫描 `workspace-root`:发现 `pom.xml` → 建议 `spring-boot-service`,`go.mod` → `go-module`,以此类推。无法识别时不写 services,只生成空模板 + 注释引导。
5. `memory-center init` 新增 `--detect/--no-detect` 开关,默认 `--detect`。

### 测试
- 新增 `tests/test_service_kinds.py`:覆盖每种 type 的 marker 推断、language 字段默认推断、未知 type 降级。
- 现有 `tests/test_workspace_shape.py` 保持通过(用默认 `spring-boot-service` 行为保持一致)。
- E2E:用 codebase-memory-mcp 本身(C 项目)跑 `memory-center init --workspace-root /path/to/cbm --detect`,产出 `services: []` + 警告提示。

### 验收标准
- [ ] `examples/spring-cloud-demo` 不修改 yaml 仍能 `reindex` 通过
- [ ] 新增一个 `examples/python-flask-demo/`,type 全为 `python-package`,能成功跑 `init` + `status`
- [ ] `memory-center init --detect` 对纯 C 项目能识别"未支持"并给出友好提示而非崩溃
- [ ] 文档:在 `docs/USER_GUIDE.md` 加 "Supported service types" 表(中英双语)

### 提交粒度
- 1 个 PR,2 个 commit:`feat: introduce service kind registry` + `feat: auto-detect service types in init`

---

## P0-2:多语言 tree-sitter parser registry

### 目标
不再只能解析 Java。引入 `tree-sitter-languages` 一次拉齐 40+ 语言;新增统一 parser 接口,首批深做 **Java/Kotlin/Python/TypeScript/Go** 五语言的 class / function / import / call 抽取。

### 前置依赖
- 完成 P0-1(否则 service.type 还假设是 Spring)

### 代码定位
- `memory_center/core/indexing/base.py` — 现有 `JavaParseResult` / `JavaParser` Protocol
- `memory_center/core/indexing/tree_sitter_parser.py` — `TreeSitterJavaParser`
- `memory_center/core/indexing/java_regex_parser.py` — fallback
- `memory_center/core/indexer.py` — 路由 parser 的入口
- `pyproject.toml` — 依赖声明

### 变更内容
1. **抽象通用 ParseResult**(新文件 `memory_center/core/indexing/parse_result.py`):
   ```python
   @dataclass
   class StructuralParseResult:
       language: str           # "java" / "python" / "go" / ...
       module: str | None      # package / namespace / module path
       imports: list[str]
       classes: list[SymbolSpan]
       functions: list[SymbolSpan]   # 包含 method
       calls: list[CallSite]
       constants: dict[str, str]
       raw: dict[str, Any]      # 给特定语言保留 escape hatch (Java 的 annotations / bean_injections 仍走这里)
   ```
   `SymbolSpan` 包含 `name / qualified_name / line / span / parent_qualified_name`。
   `CallSite` 包含 `caller_qualified_name / callee_text / line / receiver_text`。

2. **`JavaParseResult` 不删除**,把它视作 `StructuralParseResult` 在 Java 维度的扩展(saved in `raw["java"]` 或者维持现有字段),保留向后兼容。

3. **新增 `memory_center/core/indexing/language_registry.py`**:
   ```python
   @dataclass
   class LanguageSpec:
       name: str                                # "java"
       extensions: tuple[str, ...]              # (".java",)
       ts_module: str                           # "tree_sitter_java"
       query_path: str                          # "queries/java.scm"

   REGISTRY: dict[str, LanguageSpec] = {...}    # java / kotlin / python / typescript / go
   ```
4. **新增 `memory_center/core/indexing/queries/`**:每个语言一个 `.scm` 文件,描述抽取规则。
   - `java.scm`:覆盖 class/interface/enum/record/method/field/annotation/import_declaration
   - `kotlin.scm`:class/object/fun/property/import
   - `python.scm`:class_definition/function_definition/import_statement/import_from_statement/call
   - `typescript.scm`:class_declaration/method_definition/function_declaration/import_statement/call_expression
   - `go.scm`:type_declaration/method_declaration/function_declaration/import_spec/call_expression

5. **新增 `TreeSitterStructuralParser`**(`memory_center/core/indexing/structural_parser.py`):
   - 构造函数接收 `language_name`,从 registry 读 spec
   - 用 `tree_sitter.Language` + `tree_sitter.Query` 执行抽取
   - 输出 `StructuralParseResult`

6. **Java 路径双轨**:
   - 现有 `TreeSitterJavaParser` 保留,继续输出 `JavaParseResult`(因为 Spring 语义抽取严重依赖 annotation/bean injection,迁移成本大)
   - 新的 `TreeSitterStructuralParser("java")` 同时输出 `StructuralParseResult`,作为"通用结构层"灌入图谱

7. **`memory_center/core/indexer.py` 入口路由**:
   - 按文件扩展名查 registry → 选 parser
   - Java:走双轨(JavaParseResult + StructuralParseResult 合并写库)
   - 非 Java:只走 StructuralParseResult

8. **图模型扩展**:`nodes.type` 已存在,补充 `function`/`module` 通用 type(原 Java 走 `method`/`class`,保留兼容);`edges.type` 复用 `CALLS`/`IMPORTS`/`DEFINES`。

9. **依赖**:`pyproject.toml` 加 `tree-sitter-languages>=1.10` 作为可选 extra:
   ```toml
   [project.optional-dependencies]
   multilang = ["tree-sitter-languages>=1.10"]
   ```
   未安装时 fallback 到"仅 Java"模式,日志 `WARN multilang extra not installed`。

### 测试
- `tests/test_structural_parser_python.py`:对一段 Python flask app 抽取 class/function/import/call,断言数量与名字
- `tests/test_structural_parser_go.py`:同上,Go 简单 main.go
- `tests/test_structural_parser_typescript.py`:同上
- `tests/test_structural_parser_kotlin.py`:同上
- `tests/test_structural_parser_java_dualtrack.py`:Java 双轨同时产出 `JavaParseResult` 和 `StructuralParseResult`,字段不矛盾
- 性能基线:`tests/perf/test_index_python_repo.py` 索引一个中等 Python 仓 < 30s(本机)

### 验收标准
- [ ] `pip install -e ".[multilang]"` 后,对一个 Python 仓 reindex 能生成 function 节点 + CALLS 边
- [ ] `mc_lookup keyword=foo` 在 Python/Go/TS 项目中能返回结果
- [ ] Java 行为零回归:`pytest tests/` 全绿
- [ ] 文档:`docs/USER_GUIDE.md` 加多语言支持矩阵 + 安装指引(中英)

### 提交粒度
- PR 1:`feat: add StructuralParseResult and language registry`
- PR 2:`feat: implement TreeSitterStructuralParser with java/kotlin queries`
- PR 3:`feat: add python/typescript/go queries and indexer routing`
- PR 4:`docs: multilang support matrix`

---

## P0-3:SQLite 索引性能优化

### 目标
对中等(10w 文件)及大型(75K 文件)Java/多语言仓,reindex 总耗时下降 5~10×。不引入新依赖。

### 代码定位
- `memory_center/core/storage/pool.py:39-42` — 现有 PRAGMA(已开 WAL + synchronous=NORMAL + cache=64MB + foreign_keys=ON)
- `memory_center/core/storage/unified.py` — 表 DDL
- `memory_center/core/indexer.py` — 调用 store 写入的位置(逐条 INSERT 是主要瓶颈)
- `memory_center/core/indexing/incremental.py` — 增量写入

### 现状评估
- ✅ WAL 已开
- ✅ synchronous=NORMAL
- ⚠️ cache=-64000(64MB)对大仓略小
- ❌ temp_store 未设
- ❌ 写入是逐条 INSERT,没有显式 batch / transaction
- ❌ 没有索引阶段切到 `synchronous=OFF` 的 fast-path

### 变更内容
1. **`pool.py` 升级 PRAGMA**:
   ```python
   conn.execute("PRAGMA journal_mode=WAL")
   conn.execute("PRAGMA synchronous=NORMAL")
   conn.execute("PRAGMA cache_size=-200000")    # 200 MB
   conn.execute("PRAGMA temp_store=MEMORY")
   conn.execute("PRAGMA mmap_size=268435456")   # 256 MB mmap
   conn.execute("PRAGMA foreign_keys=ON")
   ```
2. **新增 indexing fast-path 上下文**:
   ```python
   @contextmanager
   def fast_write_mode(conn):
       prev_sync = conn.execute("PRAGMA synchronous").fetchone()[0]
       conn.execute("PRAGMA synchronous=OFF")
       try:
           yield
       finally:
           conn.execute(f"PRAGMA synchronous={prev_sync}")
   ```
   在 `reindex` 全程包一层(增量更新不开,避免突发崩溃导致丢数据)。

3. **批量写入**:
   - 新增 `store.bulk_upsert_nodes(rows: list[NodeRow])` 与 `bulk_upsert_edges`,内部用 `executemany` + 显式 `BEGIN/COMMIT`
   - 批大小常量 `BATCH_SIZE = 500`
   - 改造 `indexer.py` 把"每个文件解析完立刻写"改为"积累到 500 条再写"
   - 增量索引保留逐条接口(单文件变更)

4. **VACUUM 收尾**:
   - `reindex` 完成后 `conn.execute("VACUUM")`(可选,加 `--vacuum` 开关)
   - 在 `memory-center status` 中显示 `db_size_bytes` 与 `node_count` / `edge_count`

5. **索引阶段读源码**:
   - 现在是逐文件 `Path.read_text()`,IO 串行
   - 新增 `memory_center/core/indexing/source_loader.py`,用 `concurrent.futures.ThreadPoolExecutor`(I/O bound)并发预读
   - 默认并发 `min(32, os.cpu_count() * 2)`

### 测试
- `tests/perf/test_indexing_perf.py`(用 `pytest-benchmark`):
  - 准备 `examples/spring-cloud-demo` 当基线
  - 断言 `reindex` 耗时不退化(P0-2 之前 vs 之后)
- 单测:`tests/test_bulk_upsert.py` 覆盖 batch 写、失败回滚、空批次

### 验收标准
- [ ] `examples/spring-cloud-demo` reindex 耗时下降至少 3×(本地基准)
- [ ] 中等 Python 仓(从 P0-2 引入)reindex < 10s
- [ ] `memory-center doctor` 报告 PRAGMA 状态
- [ ] 增量索引行为不变(单文件改动只触发该文件 reparse)

### 提交粒度
- PR 1:`perf: tune sqlite pragmas and add fast_write_mode`
- PR 2:`perf: bulk_upsert for nodes/edges in reindex`
- PR 3:`perf: parallel source loading in indexer`

---

# P1:语义深度 + 跨服务通用化(1 个月)

## P1-1:Java 深度类型解析(3 级 call resolver)

### 目标
Java 调用边从"按方法名匹配"(假阳性多)升级为"按 `import + 同包 + 同类` 三级解析"。
准确率目标:中型 Spring 项目调用边正确率 ≥ 85%(由 `tests/golden/` 配套金标对照)。

### 前置依赖
- P0-2(StructuralParseResult 已建立)

### 代码定位
- `memory_center/core/indexing/tree_sitter_parser.py` — `JavaParseResult.method_calls` 已抽取
- `memory_center/core/indexing/java_regex_parser.py` — fallback method_calls
- `memory_center/core/indexer.py` — 把 method_calls 落到 CALLS 边的位置
- `memory_center/core/reasoning/` — 后续推理用到

### 变更内容
1. **新增 `memory_center/core/indexing/java_call_resolver.py`**:
   - 输入:`JavaSymbol`(单文件)+ 全工程符号表(`class_index: dict[fqcn, ClassInfo]`)
   - 三级解析:
     1. **同类**:同 `JavaSymbol` 内的方法 → 直接匹配
     2. **同包**:同 `package` 的其他 class → 匹配 simple class name
     3. **import**:解析 `imports` → 匹配 `qualified_name`
   - 通配符 import(`com.foo.*`)用包级目录扫描兜底
   - 静态导入(`import static`)单独处理
   - 输出:`list[ResolvedCall]`,每条带 `confidence`(同类=1.0,同包=0.9,import=0.85,wildcard=0.6,unknown=0.3)
2. **全工程符号表**:在 `reindex` 一次性建立 `class_index`(in-memory dict),复用现有 `nodes` 表的 `class` type 节点
3. **写库**:CALLS 边的 `metadata_json.resolution_level` 记录解析层级
4. **保留 fallback**:无法解析的调用仍写入,但 `confidence=0.3`,`resolution_level="unresolved"`
5. **`mc_lookup mode=callers/callees`** 默认过滤 `confidence ≥ 0.85`(可参数覆盖)

### 测试
- `tests/test_java_call_resolver.py`:6 种 case(same-class / same-package / import / wildcard / static / overload)
- `tests/golden/spring-cloud-demo/calls.json`:金标 100 条调用边,断言 precision ≥ 85%
- 性能:单文件 resolve < 5ms

### 验收标准
- [ ] `spring-cloud-demo` golden 通过
- [ ] `mc_lookup callers --symbol OrderService.process` 返回结果按 confidence 排序
- [ ] 文档:`docs/TECHNICAL_GUIDE.md` 新章节"Java call resolution levels"

### 提交粒度
- PR 1:`feat: java call resolver with 3-level fallback`
- PR 2:`feat: persist resolution confidence on CALLS edges`
- PR 3:`feat: filter by confidence in mc_lookup`

---

## P1-2:跨服务边抽象化

### 目标
现有 Feign + MQ 是 Spring 专属;抽象为 `RemoteCallEdge` + `ChannelEdge` + `ProtocolContract`,
让后续 gRPC / GraphQL / 通用 HTTP / 通用 MQ 都能复用同一图模型。

### 前置依赖
- P0-2

### 代码定位
- `memory_center/core/indexer.py` — Feign/MQ detection
- `memory_center/core/contracts/`(如有)— DTO 契约
- `memory_center/core/orchestrator/` — 现有跨服务查询

### 变更内容
1. **新增 `memory_center/core/cross_service/`**:
   ```
   cross_service/
     __init__.py
     edges.py            # RemoteCallEdge / ChannelEdge dataclass
     contracts.py        # ProtocolContract (HTTP body / proto / avro / json schema)
     protocols.py        # ProtocolKind enum: HTTP, GRPC, GRAPHQL, KAFKA, RABBITMQ, REDIS_STREAM, WEBSOCKET, GENERIC_PUBSUB
   ```
2. **`RemoteCallEdge`**:
   ```python
   @dataclass
   class RemoteCallEdge:
       caller_node_id: str           # 发起调用的方法节点
       target_service: str | None    # 目标服务名(可能 unresolved)
       target_endpoint: str          # /api/orders, OrderService/Create, GetUser query
       protocol: ProtocolKind
       producer_kind: str            # "feign-client", "rest-template", "webclient", "grpc-stub", "okhttp"
       confidence: float
       evidence: dict[str, Any]      # raw 注解/调用代码片段
   ```
3. **`ChannelEdge`**:
   ```python
   @dataclass
   class ChannelEdge:
       node_id: str
       direction: Literal["EMITS", "LISTENS_ON"]
       channel_name: str             # topic / queue / event name
       protocol: ProtocolKind        # KAFKA, RABBITMQ, REDIS_STREAM, WEBSOCKET, GENERIC_PUBSUB
       producer_kind: str            # "spring-kafka", "pulsar-client", "socketio", "node-events"
       payload_contract_id: str | None
       confidence: float
   ```
4. **`ProtocolContract`**:
   ```python
   @dataclass
   class ProtocolContract:
       id: str
       kind: Literal["http-body", "proto-message", "graphql-type", "kafka-payload", "json-schema"]
       service: str
       name: str
       fields: list[ContractField]
       source_file: str
       source_line: int
   ```
5. **现有 Feign / MQ detector 迁移**:
   - `FeignClientDetector` → 产出 `RemoteCallEdge(protocol=HTTP, producer_kind="feign-client")`
   - `SpringKafkaDetector` → 产出 `ChannelEdge(protocol=KAFKA, producer_kind="spring-kafka")`
   - DTO 契约 → `ProtocolContract(kind="http-body")`
6. **图谱落库**:`edges.type` 新增 `REMOTE_CALL`, `EMITS`, `LISTENS_ON`,旧的 `FEIGN_CALL` / `MQ_PUB` 在 view 层做映射保持向后兼容
7. **MCP facade 路由**:`mc_lookup mode="cross-service"` 增加参数 `protocol=any|http|grpc|kafka|...`

### 测试
- `tests/test_cross_service_edges.py`:从 Feign 注解抽出 `RemoteCallEdge`,字段断言
- `tests/test_protocol_contract.py`:DTO → ProtocolContract 转换
- 向后兼容:旧 fixture(走 `FEIGN_CALL` 名字)在新模型下仍能查到

### 验收标准
- [ ] `examples/spring-cloud-demo` 跨服务查询结果数量不退化
- [ ] 新模型下 `mc_lookup mode=cross-service` 支持按 `protocol` 过滤
- [ ] 文档:`docs/ARCHITECTURE.md` 新章节"Cross-Service Edge Model"(中英)

### 提交粒度
- PR 1:`feat: introduce RemoteCallEdge / ChannelEdge / ProtocolContract`
- PR 2:`refactor: migrate FeignClient detector to RemoteCallEdge`
- PR 3:`refactor: migrate Spring Kafka detector to ChannelEdge`
- PR 4:`docs: cross-service edge model`

---

## P1-3:gRPC + 通用 HTTP + 通用 MQ detector

### 目标
非 Spring 项目(Python FastAPI、Go gin、Node express、Java grpc-stub)的跨进程边能被识别。

### 前置依赖
- P0-2(多语言 parser)
- P1-2(通用边抽象)

### 代码定位
- `memory_center/core/cross_service/`(P1-2 新建)
- `memory_center/core/indexing/` 各语言 query

### 变更内容
1. **HTTP 路由 detector**:
   - Spring `@RequestMapping/@GetMapping` 已有
   - FastAPI `@app.get/@router.post` (Python)
   - Express `app.get('/...', handler)` (TS/JS)
   - Gin `r.GET("/...", handler)` (Go)
   - Spring WebFlux `RouterFunctions.route(...)` (Java)
2. **HTTP 调用 detector**:
   - `RestTemplate.getForObject` / `WebClient.get().uri(...)` / `OkHttpClient.newCall(...)` (Java)
   - `requests.get(...)` / `httpx.get(...)` (Python)
   - `fetch('/...')` / `axios.get('/...')` (TS)
   - `http.Get(...)` (Go)
   - 抽取 URL 字符串字面量,匹配到对应 `Route` 节点 → `RemoteCallEdge(protocol=HTTP, producer_kind=<lib>)`
3. **gRPC**:
   - 解析 `.proto` 文件(独立 parser,用 tree-sitter-proto 或简单正则)
   - 抽取 service / rpc → 注册 `Route` 节点(protocol=GRPC)
   - 抽取 `XxxBlockingStub.someMethod(...)` (Java) / `client.SomeMethod(...)` (Go) → `RemoteCallEdge(protocol=GRPC)`
4. **通用 MQ**:
   - Kafka: `KafkaTemplate.send` (Spring Kafka,已有) / `kafka-python` `producer.send` / `confluent-kafka` / `sarama` (Go) / `kafkajs` (TS)
   - RabbitMQ: `RabbitTemplate.convertAndSend` / `pika` (Python) / `amqplib` (TS)
   - 抽取 topic / queue 字符串字面量 → `ChannelEdge`

### 测试
- `examples/python-fastapi-demo/`:2 个 FastAPI 服务通过 httpx 互调
- `examples/grpc-demo/`:1 个 proto + Java 客户端 + Go 服务端
- 各 detector 单测

### 验收标准
- [ ] FastAPI 跨服务调用能在 graph 中显示
- [ ] gRPC stub 调用边正确指向 proto service
- [ ] 文档:每个 detector 在 `docs/REFERENCE.md` 有支持矩阵

### 提交粒度
- PR 1:`feat: HTTP route/call detectors for Python/TS/Go`
- PR 2:`feat: gRPC proto parsing and stub call detection`
- PR 3:`feat: generic MQ detectors (kafka-python, sarama, kafkajs, pika)`
- PR 4:`docs: cross-service support matrix`

---

# P2:工程效率 + 跨语言深度(按需,1~2 个月)

## P2-1:`.memory-center/graph.db.zst` 团队共享产物

### 目标
团队新人 clone 仓库后,首次启动跳过全量索引(可能数分钟到数小时),只跑增量,5s 内可用。

### 代码定位
- `memory_center/core/storage/unified.py` — DB 文件路径
- `memory_center/cli/main.py` — `reindex` 命令
- `memory_center/core/orchestrator/workspace.py` — workspace 启动逻辑

### 变更内容
1. **依赖**:`pyproject.toml` 加 `zstandard>=0.22`
2. **新增 `memory_center/core/storage/artifact.py`**:
   - `export_artifact(db_path: Path, output_path: Path, tier: Literal["best", "fast"])`
     - tier=best:`VACUUM INTO` 临时 db → 删除索引 → `zstd -9`
     - tier=fast:直接 `zstd -3`
   - `import_artifact(artifact_path: Path, db_path: Path)`:`zstd -d` → 用 SQLite `ATTACH` 验证完整性
3. **`memory-center reindex --export-artifact`** 命令选项:索引完成后写 `.memory-center/graph.db.zst`(best tier)
4. **`memory-center init`** 自动追加 `.gitattributes`:
   ```
   .memory-center/graph.db.zst merge=ours
   ```
5. **启动时探测**:`workspace.py` 启动逻辑:
   - 本地有 `db.sqlite` → 直接用
   - 本地无 db、artifact 存在 → import → 跑增量
   - 本地无 db、artifact 也无 → 走全量索引
6. **watcher fast 档**:可选,watcher 触发增量后写 fast tier(`tier=fast`),供频繁更新

### 测试
- `tests/test_artifact_roundtrip.py`:export → import → 节点/边数量一致
- E2E:删除本地 db,只保留 artifact,启动后能用

### 验收标准
- [ ] artifact 文件 < 原 db 30%(zstd -9)
- [ ] import 耗时 < 5s(中等仓)
- [ ] 文档:`docs/USER_GUIDE.md` 新章节"Sharing the graph with your team"

### 提交粒度
- PR 1:`feat: zstd artifact export/import`
- PR 2:`feat: auto-bootstrap from artifact on first run`

---

## P2-2:Python/TS 深度推断接入

### 目标
Python:用 `jedi` 给函数调用做 type-aware 解析(参数类型、return type)
TS:用 `tsserver`(子进程)做同等能力
不重写 LSP,只调用现成工具。

### 代码定位
- 新建 `memory_center/core/semantic/`
- `memory_center/core/indexing/structural_parser.py`(P0-2)

### 变更内容
1. **接口抽象**:
   ```python
   class SemanticEnricher(Protocol):
       language: str
       def enrich(self, file_path: Path, struct: StructuralParseResult) -> StructuralParseResult:
           ...
   ```
2. **`PythonJediEnricher`**:对每个 call site,用 `jedi.Script(...).goto(line, column)` 解析,把 callee 写到 `CallSite.resolved_callee_qualified_name`
3. **`TypeScriptTsserverEnricher`**:启动 `tsserver` 子进程(stdio 协议),`definition` 请求解析 call site
4. **可选 extra**:`pip install -e ".[semantic-python]"` 装 jedi
5. **降级**:enricher 失败 → 退化为结构层解析

### 测试
- `tests/test_python_jedi_enricher.py`:5 个 case
- `tests/test_typescript_tsserver_enricher.py`:5 个 case(需 node 在 CI)

### 验收标准
- [ ] Python 项目 CALLS 边 resolution rate 提升至少 30%
- [ ] tsserver 启动 < 3s
- [ ] 文档:`docs/TECHNICAL_GUIDE.md` "Semantic enrichers"

### 提交粒度
- PR 1:`feat: SemanticEnricher protocol`
- PR 2:`feat: PythonJediEnricher`
- PR 3:`feat: TypeScriptTsserverEnricher`

---

## P2-3:`mc_lookup` 增加 `architecture-overview` mode

### 目标
一次调用返回:languages / services / packages / entry_points / routes / hotspots / boundaries / contracts。
对应 CBM 的 `get_architecture`,但符合 facade 哲学。

### 代码定位
- `memory_center/mcp/` facade 实现
- `memory_center/core/orchestrator/`

### 变更内容
1. **`mc_lookup mode="architecture-overview"`**:聚合现有 `contracts` / `topology` / `hotspots` / `routes` 数据,返回单个 dict
2. **输出 schema**:
   ```json
   {
     "languages": [{"name": "java", "files": 412, "loc": 38291}],
     "services": [{"name": "order", "kind": "spring-boot-service", "endpoints": 14}],
     "entry_points": [...],
     "hot_files": [...],          // 入度高
     "boundary_edges": [...],     // 跨服务边
     "contracts": [...]
   }
   ```
3. **缓存**:结果可缓存 60s(workspace 不变时)

### 测试
- `tests/test_architecture_overview.py`:`spring-cloud-demo` 跑一次,断言字段齐全

### 验收标准
- [ ] 单次 facade 调用返回完整概览 < 500ms
- [ ] 文档:`docs/MCP_GUIDE.md` 加示例

---

# P3:发布形态扩展(远期,按需)

- **P3-1**:`pyinstaller`/`shiv` 出 single-binary,降低非 Python 用户安装门槛
- **P3-2**:`memory-center generate-hooks --host codex-cli / zed / opencode / aider` 多 host 适配
- **P3-3**:可选 backend `provider: cbm` —— 把 codebase-memory-mcp 作为底层 KG provider(若你想避免重做通用图)
- **P3-4**:graph-ui 静态导出(轻量 HTML 可视化,不做 3D)

---

# 执行节奏建议

**第 1 周**:P0-1 + P0-3(都是基础设施,无大风险)
**第 2 周**:P0-2(多语言 parser)
**第 3~4 周**:P1-1(Java 深度解析)
**第 5~6 周**:P1-2(跨服务抽象)
**第 7 周**:P1-3(非 Spring detector)
**第 8 周起**:看用户反馈和真实仓库使用情况,决定 P2 / P3 优先级

---

# 每个阶段的统一 checklist

每完成一个 P-x,执行:

- [ ] `pytest -q` 全绿
- [ ] `ruff check .` / `mypy memory_center/` 不引入新错误
- [ ] 更新 `docs/CHANGELOG.md` (中英双语)
- [ ] 更新 `docs/ROADMAP.md` 勾选完成项
- [ ] `examples/spring-cloud-demo` 跑一次 `reindex` + `status` 不退化
- [ ] 如新增依赖 → 更新 `pyproject.toml` 并测试 `pip install -e .` 干净环境
- [ ] commit message 遵循 `<type>: <description>` 格式
- [ ] PR 描述:背景 + 变更点 + 测试方法 + 风险 + 回滚方式

---

# 风险与回退

| 风险 | 触发 | 应对 |
|------|------|------|
| 多语言 parser 抽取质量差 | 用户反馈 Python 调用边漏检 | 单语言独立开关,通过 workspace.yaml `language_overrides` 关闭 |
| Java 双轨导致内存翻倍 | 大仓 reindex OOM | StructuralParseResult 在 Java 路径上只保存 raw=None,字段最小化 |
| `synchronous=OFF` 崩溃丢数据 | reindex 中途 kill | 失败后自动 `--full-reindex`,artifact 不在崩溃路径上覆盖 |
| 跨服务抽象迁移破坏现有查询 | 旧 fixture 失败 | 在 view 层做新旧 edge type 双向映射,持续 2 个 minor 版本后再删 |
| tree-sitter-languages 版本漂移 | grammar 升级导致 AST 节点名改变 | 每个 query 文件加版本注释 + CI 锁版本 |

---

# 与 codebase-memory-mcp 的长期关系

- **不竞争**:CBM 专注通用 KG 后端,memory-center 专注"Java 工程语义 + 任务级 facade + 规则护栏"
- **可互操作**:P3-3 留接口,允许把 CBM 当作 backend
- **可借鉴**:每阶段都从 CBM 同名能力的 C 实现中学其工程效率技巧(批处理、in-memory pipeline、artifact 共享),不照搬实现

---

**变更日志**:
- 2026-06-23:初稿,基于对 codebase-memory-mcp 的分析创建
- 2026-06-23:**P0-1 完成**(commits `bdbaf5f` + `95477b1`)
  - `service_kinds.py` registry(11 种 kind)+ `ServiceConfig.language`
  - `workspace_shape._looks_like_module_root` 改查 registry
  - `write_default_workspace` 支持 `detect=True/False` + `dry_run=True`
  - CLI `init` 增加 `--detect/--no-detect/--dry-run` 选项
  - `USER_GUIDE.md` 新增"Supported service types"双语表
  - 38 个新测试通过(30 + 8),全量套件零回归
- 2026-06-23:**P0-3 完成**(commits `b1bba40` + `b7f30a9` + `80fc950`)
  - `storage/pragmas.py` 统一 SQLite PRAGMA 配置(`DEFAULT_PROFILE` +
    `FAST_WRITE_PROFILE` + `apply_pragmas` + `fast_write_mode`)
  - 修复 `GraphStore` / `MemoryBackendStore` 之前完全没应用 PRAGMA 的
    隐藏 bug,主写库路径现在也走 WAL + 200MB cache + MEMORY temp_store
  - `GraphStore.rebuild` / `rebuild_search_index` 从逐条 INSERT 改为
    `executemany` + `fast_write_mode`(synchronous=OFF for reindex)
  - `estimate_optimal_workers` 重调参:上限 8→32,修小批量退化为 0
    worker 的旧 bug
  - `doctor` 输出 SQLite PRAGMA 状态,新增 `graph:pragma_wal` 检查
  - 21 个新测试通过(8 + 6 + 7),全量套件零回归
- 2026-06-23:**下一步 P0-2(多语言 parser registry)**,工程量 3~5 天

**owner**:cuijq
**reviewers**:待补
