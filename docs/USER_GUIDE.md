# User Guide / 使用指南

## Who This Is For / 适用对象

这份文档面向日常使用者：想安装、初始化、重建索引、查询上下文、做影响分析、维护 workspace 的开发者或 Agent 使用者。

## 1. Install / 安装

推荐安装方式：

```bash
pipx install /path/to/memory-center
```

开发环境：

```bash
pip install -e .
```

验证：

```bash
memory-center --version
```

## 2. Initialize Workspace / 初始化工作区

```bash
memory-center init --workspace-root /abs/path/to/repo
```

`init` automatically scans the workspace root and registers one service per
recognized child directory. Hidden directories and conventional build
outputs (`target`, `build`, `dist`, `node_modules`, `.venv`, …) are skipped.

`init` 默认会自动扫描工作区根目录,为每个被识别的子模块生成一条 service 记录,
忽略隐藏目录和常见的构建产物目录。

```bash
# Preview what would be detected without writing anything.
# 预览将生成的内容,但不写入文件。
memory-center init --workspace-root /abs/path/to/repo --dry-run

# Use the legacy Spring-Cloud placeholder template
# (gateway / common-api / common-core).
# 使用旧版 Spring Cloud 占位模板。
memory-center init --workspace-root /abs/path/to/repo --no-detect
```

### Supported service types / 支持的服务类型

| `type` | Language | Build markers | 用途 / Purpose |
|--------|----------|---------------|----------------|
| `spring-cloud-gateway` | java | `pom.xml` / `build.gradle` + `spring-cloud-starter-gateway` | Spring Cloud Gateway 网关 |
| `spring-boot-service` | java | `pom.xml` / `build.gradle` + `spring-boot` | Spring Boot 业务服务 |
| `spring-boot-task` | java | `pom.xml` + `spring-boot` | Spring Boot 定时/批处理任务 |
| `shared-library` | java | `pom.xml` / `build.gradle` + `spring-boot` | 共享库 / 契约模块 |
| `generic-jvm` | java | `pom.xml` / `build.gradle(.kts)` (无 Spring 信号) | 通用 JVM 项目 |
| `kotlin-module` | kotlin | `build.gradle.kts` / `settings.gradle.kts` | Kotlin 模块 |
| `python-package` | python | `pyproject.toml` / `setup.py` / `setup.cfg` | Python 包 |
| `node-app` | typescript | `package.json` | Node.js / TypeScript 应用 |
| `go-module` | go | `go.mod` | Go 模块 |
| `rust-crate` | rust | `Cargo.toml` | Rust crate |
| `generic` | (none) | fallback | 未识别类型 / 通用目录 |

Unknown types fall back to `generic` with a runtime warning.
Set `language: <lang>` explicitly in `workspace.yaml` to override the
language inferred from `type` (e.g. `type: generic` + `language: scala`).

未识别的 `type` 会回退到 `generic` 并发出运行时警告。
可在 `workspace.yaml` 中显式设置 `language: <lang>` 来覆盖从 `type` 推断的语言。

### Files created / 初始化后重点关注

- `workspace.yaml`
- `.memory-center/rules/`
- `.memory-center/hooks.yaml`
- `.memory-center/artifacts/`

### Multi-language structural index / 多语言结构索引

Beyond Java's Spring-aware extractors (Feign / MQ / DTO contracts),
memory-center can index a generic structural graph for several other
languages. After the language bindings are installed, ``reindex``
emits ``Module`` / ``Class`` / ``Function`` nodes plus ``DEFINES`` /
``IMPORTS`` / ``CALLS`` edges for every supported source file alongside
the Java pipeline.

除 Java 的 Spring 专属抽取(Feign/MQ/DTO 契约)外,memory-center 还能为多种
语言构建通用结构图谱。安装对应 binding 后,`reindex` 会和 Java 流水线并行,
为每个被识别的源文件产出 Module/Class/Function 节点和 DEFINES/IMPORTS/CALLS 边。

| Language | Extensions | Binding |
|----------|------------|---------|
| Java | `.java` | `tree-sitter-java` (already required by `[ast]`) |
| Kotlin | `.kt`, `.kts` | `tree-sitter-kotlin` |
| Python | `.py`, `.pyi` | `tree-sitter-python` |
| TypeScript | `.ts` | `tree-sitter-typescript` (`language_typescript`) |
| TSX | `.tsx` | `tree-sitter-typescript` (`language_tsx`) |
| JavaScript | `.js`, `.mjs`, `.cjs`, `.jsx` | `tree-sitter-typescript` (`language_tsx`) |
| Go | `.go` | `tree-sitter-go` |

Install all bindings at once with the `multilang` extra:

```bash
pip install -e ".[multilang]"
```

Without these packages reindex still works — non-Java files are
silently skipped from the structural pass. Run `memory-center doctor`
to see which bindings are missing.

未安装 `[multilang]` 时,reindex 仍能正常工作,只是非 Java 文件不会进入结构
索引。运行 `memory-center doctor` 可查看哪些 binding 缺失。

Call edges from the structural pass start at low confidence
(``confidence=0.3``, ``metadata.resolution_level=unresolved``) because
the cross-language walker only has textual evidence. P1-1's Java call
resolver will rewrite these in place with higher-confidence targets
once it ships.

结构 pass 的调用边初始 `confidence=0.3` 且标记 `resolution_level=unresolved`,
P1-1 的 Java 调用解析器上线后会就地改写为更高置信度的目标。

## 3. Reindex / 重建索引

全量：

```bash
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml
```

增量：

```bash
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --project xxx
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --path module-a/src/main/java
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --changed-only --scope all
```

## 4. Daily Workflow / 日常工作流

最推荐的高频命令：

```bash
memory-center work-start --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-sync --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-resume --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-handoff --workspace /abs/path/.memory-center/workspace.yaml --target-model codex --intent "..."
memory-center work-close --workspace /abs/path/.memory-center/workspace.yaml --session-id <session_id>
memory-center work-health --workspace /abs/path/.memory-center/workspace.yaml
```

## 5. Common Queries / 常见查询

### 查任务上下文

```bash
memory-center sniff --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
```

### 查符号 / 代码 / 调用链

```bash
memory-center symbol --workspace /abs/path/.memory-center/workspace.yaml --name ArticleFeignClient
memory-center search-code --workspace /abs/path/.memory-center/workspace.yaml --query oldPubTime
memory-center callers --workspace /abs/path/.memory-center/workspace.yaml --symbol com.example.ArticleService#update
memory-center callees --workspace /abs/path/.memory-center/workspace.yaml --symbol com.example.ArticleService#update
```

### 做影响分析

```bash
memory-center impact --workspace /abs/path/.memory-center/workspace.yaml --target ArticleDTO
memory-center detect-changes --workspace /abs/path/.memory-center/workspace.yaml --scope all
```

## 6. MCP / HTTP / UI

### MCP

```bash
memory-center-mcp --workspace /abs/path/.memory-center/workspace.yaml
```

### HTTP + Workbench

```bash
memory-center serve-http --workspace /abs/path/.memory-center/workspace.yaml --host 127.0.0.1 --port 8765
```

常用页面：

- `/ui`
- `/ui/dashboard`
- `/ui/continuity`
- `/ui/task`
- `/ui/timeline`
- `/ui/ref`
- `/ui/backend`

## 7. Multi-Workspace / 多工作区

支持：

- 一个大根目录下多个服务
- 多个独立 workspace
- registry + group 聚合

典型命令：

```bash
memory-center register-workspace ...
memory-center create-group ...
memory-center add-to-group ...
```

## 8. Maintenance / 维护

建议周期性执行：

```bash
memory-center status --workspace /abs/path/.memory-center/workspace.yaml
memory-center regression-smoke --workspace /abs/path/.memory-center/workspace.yaml
memory-center eval-token-benchmark --workspace /abs/path/.memory-center/workspace.yaml
memory-center eval-golden --workspace /abs/path/.memory-center/workspace.yaml --cases /abs/path/private-cases.yaml
```

## 9. Keep It Small / 如何避免用法膨胀

优先顺序建议：

1. 先用 `work-*`
2. 不够时再用 facade / CLI 原子命令
3. 排障或开发系统本身时再深入 `REFERENCE.md`

## 10. Related Docs / 相关文档

- [ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [SPECS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/SPECS.md)

## 11. Implemented Features (3.x / V3 Foundation) / 已实现功能（3.x / V3 基础版）

这一节是当前可用功能说明，主要帮助使用者理解系统里已经能用什么，不代表这些功能仍处于待实现状态。

### 11.1 Hybrid Retrieval / 混合检索

**何时使用**: 需要查询代码、符号、调用链时，hybrid retrieval 比旧的 `memory_query` 更稳定。

**使用方式**: 通过 `memory_query_hybrid()` 或在 Python 代码中直接调用。

```python
from memory_center.core.retrieval import hybrid_retrieve, HybridRetrievalConfig

# 默认配置
result = hybrid_retrieve(graph, workspace_file, "asyncBusinessOperationExport")

# 自定义配置（调整权重）
config = HybridRetrievalConfig(
    graph_weight=0.5,      # 增加 graph 权重
    sparse_weight=0.3,
    semantic_weight=0.2,
    vector_weight=0.15,
    enable_sparse_bm25=True,
    enable_vector=False,   # 真实 dense embeddings 就绪后再启用
)
result = hybrid_retrieve(graph, workspace_file, query, config=config)
```

**返回内容**:
- `results`: 匹配结果（带分数、来源、邻居）
- `intent`: 检测到的意图（feign/mq/endpoint 等）
- `retrieval_summary`: 检索统计
- `progressive`: 渐进式摘要
- `retrieval_diagnostics`: BM25 / Vector 的 disabled、empty、unavailable 或 active 状态

默认情况下，reindex 会自动构建 SQLite BM25；Vector ANN 默认关闭。启用本地 embedding backend 并重新 reindex 后，dense vectors 会同步到 VectorIndex，再根据真实查询 benchmark 决定是否开启 vector。

**意图检测示例**:
- `"feign client"` → feign 意图
- `"/api/users"` → endpoint 意图
- `"kafka topic"` → mq 意图
- `"调用链"` → chain 意图

### 11.2 Benchmark Trending / 基准趋势

**何时使用**: 需要监控 token 使用变化，检测回归问题。

如果你想验证真实 Spring Cloud workspace 中 `regex` 与 `tree-sitter` 解析结果是否收敛，可以运行：

```bash
memory-center eval-parser-benchmark --workspace /abs/path/.memory-center/workspace.yaml

### Golden Benchmark / 金标基准

```bash
memory-center reindex --workspace examples/golden-benchmark/workspace.yaml
memory-center eval-golden --workspace examples/golden-benchmark/workspace.yaml --cases examples/golden-benchmark/cases.yaml

memory-center eval-golden \
  --workspace /abs/path/.memory-center/workspace.yaml \
  --cases /abs/path/private-cases.yaml
```

- `--workspace` 可以直接指向真实项目的 `.memory-center/workspace.yaml`
- `--cases` 建议使用本地私有文件，不要把真实业务链路直接提交进仓库
- 公开模板见 [examples/golden-benchmark/cases.template.yaml](/Users/cuijiaqi/Ai-common-skills/memory-center/examples/golden-benchmark/cases.template.yaml)
```

**使用方式**:

```python
from memory_center.core.benchmark import (
    record_benchmark_trend,
    get_benchmark_trends,
    generate_benchmark_report
)

# 记录趋势点（每次调用后）
record_benchmark_trend(
    workspace_file,
    "mc_lookup",           # 函数名
    raw_tokens=1000,       # 原始 token
    compact_tokens=300,    # 压缩后 token
    budget="medium"
)

# 获取趋势分析
trends = get_benchmark_trends(
    workspace_file,
    function_name="mc_lookup",
    days=30                # 最近 30 天
)

# 生成综合报告
report = generate_benchmark_report(workspace_file)
```

**返回内容**:
- `function_trends`: 按函数分组的趋势数据
- `regressions`: 检测到的回归问题
- `summary`: 摘要统计
- `health_score`: 健康评分

**回归检测**: 自动比较近期 vs 历史平均，超过 10% 增长则标记为回归。

### 11.3 Unified Backend Query / 统一后端查询

**何时使用**: 需要查询 session、receipt、timeline 等高频数据。

**使用方式**:

```python
from memory_center.core.backend import UnifiedBackendQuery

with UnifiedBackendQuery(db_path) as backend:
    # 查询记录
    records = backend.query_records(collection="session-events.jsonl")

    # 查询特定 session
    events = backend.query_session_events(session_id="xyz")

    # 查询写入收据
    receipts = backend.query_write_receipts(project="test")

    # 聚合统计
    session_stats = backend.aggregate_by_session()
    project_stats = backend.aggregate_by_project()

    # 时间线查询
    timeline = backend.query_timeline(session_id="xyz", task_id="task-001")

    # 健康检查
    health = backend.check_health()
```

**返回内容**:
- 统一的记录格式
- 聚合统计
- 健康状态

### 11.4 Drill-Down Navigation / 钻取导航

**何时使用**: 需要深入查看 ref、timeline、task 的详情。

**使用方式**:

```python
from memory_center.core.navigation import DrillDownNavigator

with DrillDownNavigator(workspace_file) as nav:
    # 展开引用（渐进式）
    ref = nav.expand_ref("session-event:abc123")
    # ref 包含:
    #   - level_1_summary: 摘要
    #   - level_2_details: 详情
    #   - level_3_related: 相关项
    #   - reverse_links: 反向导航

    # 钻取时间线
    timeline = nav.drill_timeline(
        session_id="xyz",
        start_event_id="event-001",  # 从某个事件开始
        limit=50
    )
    # 包含: events, summary, navigation hints

    # 钻取任务
    task = nav.drill_task(task_id="task-001")
    # 包含: summary, timeline, write_receipts

    # 构建切换上下文（模型切换时使用）
    handoff = nav.build_handoff_context(session_id="xyz")
    # 包含: session_summary, key_points, open_questions, next_steps

    # 构建 Facade 摘要
    summary = nav.build_facade_summary(intent="查 Feign", results={...})
    # 包含: level_1_summary, level_2_results, level_3_refs
```

**渐进式披露**:
- Level 1: 快速摘要（始终显示，token 最少）
- Level 2: 详细信息（按需展开）
- Level 3: 相关项（进一步探索）

### 11.5 Completion Audit / 完成审计

**何时使用**: 需要检查文档对齐、测试覆盖、实现完整性。

**使用方式**:

```python
from memory_center.core.audit import (
    run_completion_audit,
    record_design_decision,
    get_design_decisions,
    generate_audit_report
)

# 运行完成审计
audit = run_completion_audit(
    workspace_file,
    work_package="Phase A",      # 可选：特定工作包
    check_docs=True,              # 检查文档
    check_tests=True,             # 检查测试
    check_implementation=True     # 检查实现
)

# 记录设计决策
record_design_decision(
    workspace_file,
    topic="hybrid_retrieval",
    decision="使用 RRF 合并三种检索源",
    rationale="平衡精确性和召回率",
    alternatives=["简单加权", "学习排序"],
    impact="high"
)

# 查询设计决策
decisions = get_design_decisions(workspace_file, topic="hybrid_retrieval")

# 生成综合报告
report = generate_audit_report(workspace_file)
```

**返回内容**:
- `score`: 健康评分（0-100）
- `quality`: 质量等级（high/medium/low）
- `findings`: 发现的问题
- `recommendations`: 改进建议
- `overall_health`: 整体健康评估

**审计维度**:
- 文档: 关键文档存在性、SPECIAL_NOTES 完整性
- 测试: 测试文件、pytest 配置
- 实现: 模块完整性
- 设计: 冲突决策检测

### 11.6 最佳实践

**日常开发流程**:
1. 开始任务 → `mc_start`
2. 查询代码 → 使用 `hybrid_retrieve` 或 `mc_lookup`
3. 修改前 → `mc_analyze` 检查影响面
4. 记录趋势 → `record_benchmark_trend`
5. 结束任务 → `mc_close`

**定期维护**:
```bash
# 每周运行审计
from memory_center.core.audit import run_completion_audit
audit = run_completion_audit(workspace_file)

# 每天检查趋势
from memory_center.core.benchmark import get_benchmark_trends
trends = get_benchmark_trends(workspace_file, days=7)

# 记录重要设计决策
from memory_center.core.audit import record_design_decision
record_design_decision(workspace_file, topic="...", decision="...", rationale="...")
```

## 12. Troubleshooting / 故障排除

### 12.1 检索结果不理想

**问题**: 查询返回太多/太少结果。

**解决**:
1. 调整 `HybridRetrievalConfig` 权重
2. 使用更具体的查询词
3. 检查意图检测是否正确

### 12.2 回归检测误报

**问题**: 检测到假回归。

**解决**:
1. 检查阈值设置（默认 10%）
2. 增加历史数据点
3. 手动标记为已知变化

### 12.3 审计分数低

**问题**: 审计分数低于预期。

**解决**:
1. 查看 `findings` 列表
2. 按优先级修复（high → medium → low）
3. 补充缺失的文档/测试

### 12.4 导航找不到数据

**问题**: `expand_ref` 或 `drill_timeline` 返回空。

**解决**:
1. 检查 ref_id/session_id 是否正确
2. 确认数据已写入 backend
3. 使用 `check_health()` 检查后端状态

## 13. API Reference Quick Links / API 参考快速链接

- **Retrieval**: `memory_center.core.retrieval`
  - `hybrid_retrieve()`, `HybridRetrievalConfig`, `detect_query_intent()`
- **Benchmark**: `memory_center.core.benchmark`
  - `record_benchmark_trend()`, `get_benchmark_trends()`, `generate_benchmark_report()`
- **Backend**: `memory_center.core.backend`
  - `UnifiedBackendQuery`
- **Navigation**: `memory_center.core.navigation`
  - `DrillDownNavigator`
- **Audit**: `memory_center.core.audit`
  - `run_completion_audit()`, `record_design_decision()`, `generate_audit_report()`

详见各模块的 docstring 和 [TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_GUIDE.md)。
