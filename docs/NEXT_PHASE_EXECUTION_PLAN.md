# Next Phase Execution Plan / 下一阶段执行计划

## 1. 文档目标 / Purpose

本文档是 `docs/NEXT_PHASE_MASTER_PLAN.md` 的执行版。

总方案回答“方向是什么”，本文档回答“接下来一步一步怎么做，做到哪里算结束”。

若需要把后续工作交给其他开发者配合 AI 持续执行，使用
`docs/DELEGATED_EXECUTION_PLAN.md`。该文档提供可自由调整的工作清单、产品优先级、验收建议和风险记录方式。

当前判断：

- V3 / Next Phase 基础能力已经大量存在。
- 主要风险不是缺少模块，而是主链路接入、三入口一致性、静默失败、文档与实现状态漂移。
- 下一阶段应先做收口，再做扩展。
- 截至 `3.5.9`，基础 Ruff 门禁已经从“历史债务”收敛到可执行分层门禁：`F/E9/I001/B006/B008/B904` 已清零；剩余主要是 Python 语法现代化、少量 bugbear 建议和旧式语句整理。
- 后续开发验收必须继续优先使用真实场景验证脚本；公开 examples 只作为兼容性 smoke 和文档模板，不作为真实体验完成证明。

执行原则：

1. 功能真实可用、用户实际好用优先于遵守旧模块边界和旧任务顺序。
2. 可以重排阶段、合并任务、替换旧实现和重构核心模块。
3. 每项完成的能力应有测试、入口验证和文档同步。
4. 兼容性是一项重要权衡，但不应阻止明显更好的设计；不兼容调整需要迁移说明。
5. 先解决真实主链路问题，再增加能够明显改善使用体验的新能力。
6. CLI / MCP / HTTP 可以针对入口场景优化，但核心语义和结果应可解释。
7. 任何被 `except Exception` 吞掉的主链路失败，都要转成可见诊断或明确降级说明。
8. 不提交私有 workspace 生成的 `.memory-center/index`、`.memory-center/memory` 内容。

## 2. 已识别问题与当前状态 / Findings and Current Status

> 本节保留早期问题的完整背景，便于回归验证。以下 P0 项已完成首轮修复，不应继续按“当前仍存在”理解；最新执行状态以 `DELEGATED_EXECUTION_LOG.md` 文末的当前权威策略和最新完成记录为准，后续顺序可按用户价值重新安排。

### P0：主链路静默失败

当前状态：

- freshness 方法名不一致问题已修复。
- context risk、vector retrieval、business-flow 三入口一致性已进入 3.1.2 主链路收口。
- 后续重点从“已知 P0 修复”转为“三入口矩阵持续覆盖、静默降级 diagnostics、测试 workspace 隔离”。

#### 2.1 Freshness 主查询链路失效（已修复，保留回归验证）

现象：

- `IndexFreshnessService` 实现了 `banner()`。
- `memory_query_hybrid`、`memory_context`、`memory_impact` 调用了不存在的 `get_freshness_banner()`。
- 异常被捕获后返回 `unknown`，导致 freshness 看似接入，实际效果打折。

涉及位置：

- `memory_center/core/freshness/status.py`
- `memory_center/core/orchestrator/query.py`
- `memory_center/core/orchestrator/impact.py`

期望：

- 主查询、上下文、影响分析都返回真实 freshness banner。
- 测试覆盖 fresh / pending / stale / empty-index 场景。

#### 2.2 Context risk patterns 不生效（已修复，保留回归验证）

现象：

- `memory_context` 里调用 `RiskAnalyzer(store)`，但 `store` 未在函数作用域定义。
- 异常被吞掉后 `risk_patterns` 长期为空。

涉及位置：

- `memory_center/core/orchestrator/query.py`

期望：

- `memory_context` 能稳定返回 risk patterns。
- 若风险分析不可用，返回 `_diagnostics`，不要静默丢失。

#### 2.3 Vector / BM25 retrieval 主链路（已修复，仍需真实数据质量验证）

历史问题：

- `hybrid.py` 内 `_vector_retrieval` 使用错误相对导入。
- `VectorIndex` 构造需要 `UnifiedStore`，当前逻辑传入 db path。
- 异常被吞掉后 vector 分支实际不参与结果。
- BM25 命中虽然生成，但曾未进入融合排序。
- `enable_vector=False` 曾无法阻止向量检索执行，`vector_weight` 曾未参与评分。

当前状态：

- reindex 自动重建 SQLite BM25。
- BM25 命中正式进入 hybrid fusion。
- semantic index 存在 dense vectors 时自动同步 VectorIndex。
- vector 默认关闭；启用、空索引、不可用和 active 状态均通过 diagnostics 可见。
- vector 使用独立 `vector_weight`，不会再复用 semantic 权重。

涉及位置：

- `memory_center/core/retrieval/hybrid.py`
- `memory_center/core/storage/vector_index.py`

后续深化：

- 在真实 workspace 上量化 BM25 / vector 的召回、延迟和排序收益。
- 增加 vector backend、模型和维度变更后的迁移测试。
- 根据 benchmark 调整默认权重和是否开放默认启用。

#### 2.4 Business flow CLI / MCP 路径错误（已修复，保留三入口回归验证）

现象：

- HTTP business-flow 路由通过 `WorkspaceStore(workspace).graph_db_path` 找 graph db。
- CLI / MCP 直接把 `workspace.yaml` 传给 `GraphStore` 或 `UnifiedStore`。
- 这会导致同一能力三入口行为不一致。

涉及位置：

- `memory_center/cli/main.py`
- `memory_center/mcp/server.py`
- `memory_center/http/server.py`

期望：

- CLI / MCP / HTTP 都从 workspace.yaml 解析出 graph db。
- 同一 seed / node_id 在三入口返回一致结构。

### P1：测试与治理缺口

#### 2.5 测试偏“存在性”，缺真实入口行为

现象：

- 当前 `pytest -q` 通过。
- 但 freshness、risk、vector、business-flow 入口问题未被测出。

期望：

- 增加三入口契约测试。
- 增加异常降级可见性测试。
- 增加真实 demo workspace smoke 测试。

当前进展：

- 已增加 Next Phase HTTP 入口矩阵测试。
- 已增加 MCP 入口矩阵测试骨架；当 MCP 依赖不可用时按现有策略跳过。
- 已覆盖 business-flow CLI 不再把 workspace.yaml 当 SQLite 的回归测试。

#### 2.6 生成内容污染工作树

现象：

- 跑测试后 `examples/spring-cloud-demo/.memory-center/graph/graph.db`、`memory.db`、`token-gain-log.jsonl` 可能被修改。
- 这些内容属于生成物，容易误提交。

期望：

- 明确 demo fixture 的可跟踪范围。
- 测试写入临时 workspace，而不是修改已跟踪 demo 数据。
- `.gitignore` 和文档说明保持一致。

当前进展：

- `test_public_mvp.py` 中直接使用仓库内 demo workspace 的污染点已改为复制到 `tmp_path`。
- 示例 workspace 的运行态 memory DB、operation/token gain log、metrics 已改为生成物策略：不再跟踪这些会被测试/验证写入的文件，并通过 `.gitignore` 固化忽略规则。
- 示例中仍保留可复现的 workspace 配置、源码、index、graph 快照和 Golden cases；运行态 memory/metrics 由测试或本地验证按需重新生成。
- 后续新增测试必须继续遵守 `docs/SPECIAL_NOTES.md` 中的 workspace 隔离规则。

### P2：文档状态漂移

现象：

- `CHANGELOG.md` 和 `NEXT_PHASE_MASTER_PLAN.md` 中部分描述已经写成“完成”，但实际主链路仍需复核。
- 例如 freshness、tree-sitter、vector、business flow 三入口接入。

期望：

- 文档区分：
  - 已实现模块
  - 已接入入口
  - 已完成真实主链路验收
  - 仍需产品化收口

当前进展：

- `3.5.6` 起新增真实场景验收脚本，后续完成说明必须明确真实场景结果或说明未运行原因。
- `3.5.8` 起 Golden performance gate 支持真实 baseline 不回归语义。
- `3.5.9` 起 Ruff 基础治理已形成可复用门禁：`F/E9/I001/B006/B008/B904` 通过，剩余 lint 债务不再与运行级错误混在一起描述。

## 3. 总体执行路线 / Execution Roadmap

下面 8 个阶段用于组织问题域，可根据用户价值和技术依赖自由重排：

1. Phase 0：基线冻结与问题复现
2. Phase 1：主链路 P0 修复
3. Phase 2：三入口一致性收口
4. Phase 3：测试体系补强
5. Phase 4：Ontology 约束层主链路化
6. Phase 5：Context Pack / Freshness / Domain 工作流化
7. Phase 6：Benchmark / Audit / Observability 治理闭环
8. Phase 7：文档、发布与最终验收

## 4. Phase 0：基线冻结与问题复现

目标：

- 在改代码前确认当前状态。
- 把已发现问题变成可重复失败的测试或 smoke。

步骤：

1. 确认工作树状态。
   - 命令：`git status --short`
   - 验收：明确哪些变更是本次产生，哪些是已有生成物。

2. 跑现有测试。
   - 命令：`pytest -q`
   - 验收：记录通过数量、跳过数量、耗时。

3. 补最小复现测试，不急着修。
   - freshness：断言 `memory_query_hybrid(... )["freshness"]` 包含 `freshness` 和 `banner`。
   - context risk：构造有风险边的节点，断言 `memory_context(... )["risk_patterns"]` 可见或有 `_diagnostics`。
   - business-flow CLI/MCP：构造 demo seed，验证入口不会把 workspace.yaml 当 SQLite。
   - vector retrieval：若 vector index 有数据，断言 `vector_ann` source 可出现；若无数据，断言 diagnostics 说明 disabled。

完成标志：

- 至少 3 个当前问题能被测试暴露。
- 测试失败原因和当前代码问题一致。

## 5. Phase 1：主链路 P0 修复

### 5.1 修复 freshness API

步骤：

1. 在 `IndexFreshnessService` 增加兼容方法：
   - `get_freshness_banner()` 调用 `banner()`。
   - 或统一所有调用点改成 `banner()`。

2. 修复调用点：
   - `memory_query_hybrid`
   - `memory_context`
   - `memory_impact`

3. 统一返回结构：

```json
{
  "freshness": {
    "status": "fresh|pending|stale|unknown",
    "last_indexed_at": "...",
    "changed_files": [],
    "pending_files": [],
    "staleness_level": "low|medium|high|unknown",
    "message": "..."
  },
  "banner": "[FRESH] ..."
}
```

验收：

- `memory_query_hybrid` 返回真实 freshness。
- `memory_context` 返回真实 freshness。
- `memory_impact` 返回真实 freshness。
- 不再因为方法名错误退化成 `unknown`。

### 5.2 修复 context risk patterns

步骤：

1. 在 `memory_context` 开始处保留 `config, store = load_context(workspace_file)`。
2. 传入正确 store 给 `RiskAnalyzer`。
3. 如果风险分析失败，返回：

```json
{
  "risk_patterns": [],
  "_diagnostics": {
    "risk_patterns": "unavailable",
    "reason": "..."
  }
}
```

验收：

- 有风险模式时能返回 `risk_patterns`。
- 无风险或模块不可用时不静默失败。

### 5.3 Vector / BM25 retrieval 深化

当前实现已完成：

1. 正确解析 workspace 并使用 `UnifiedStore` 构造 VectorIndex。
2. 明确启用条件：
   - 有 vector metadata。
   - 有 query embedding 来源。
   - 维度匹配。
3. 如果不能启用，返回 diagnostics。
4. reindex 自动重建 BM25 并同步 dense vectors。
5. BM25 / vector 均进入融合排序并使用独立配置。

```json
{
  "vector_status": "disabled|empty|unavailable|active",
  "vector_reason": "..."
}
```

后续验收：

- 在至少一个真实 workspace 上验证 vector active 路径。
- 为模型或维度变化建立稳定迁移策略。
- benchmark 能证明排序质量或延迟收益。

### 5.4 修复 business-flow CLI / MCP

步骤：

1. CLI `business-flow`：
   - 使用 `WorkspaceStore(workspace).graph_db_path` 初始化 `GraphStore`。

2. CLI `business-flow-impact`：
   - 使用 `WorkspaceStore(workspace).graph_db_path` 初始化 `UnifiedStore`。

3. MCP helper：
   - `_business_flow_action`
   - `_business_flow_impact_action`
   - 与 HTTP 路由保持同一写法。

验收：

- CLI / MCP / HTTP 不再把 workspace.yaml 当 graph db。
- 同一 seed 的结果结构一致。

## 6. Phase 2：CLI / MCP / HTTP 三入口一致性

目标：

- 防止“HTTP 可用、CLI/MCP 不可用”的情况再次出现。

覆盖能力：

1. `context-pack`
2. `freshness`
3. `onboard`
4. `domain`
5. `business-flow`
6. `business-flow-impact`
7. `verification-loop`
8. `workflow-profile`
9. `runtime-audit`
10. `regression-alerts`

步骤：

1. 建立入口矩阵测试。
   - 每个能力列出 CLI 命令、HTTP route、MCP action/tool。
   - 至少验证返回结构中的 `workflow`、核心字段、错误语义。

2. 对于 MCP helper action，优先拆成可直接测试的普通函数。

3. 为所有入口统一 workspace 解析方式：
   - 输入永远是 workspace.yaml。
   - 入口内部再解析 graph db / memory db。

验收：

- 任意新增入口必须有矩阵测试。
- 三入口字段命名不再明显分叉。
- 测试不得直接写入仓库内 `examples/*/.memory-center` 的 graph / memory 生成物。

## 7. Phase 3：测试体系补强

目标：

- 从“模块存在”升级到“真实行为可信”。

新增测试分组：

### 7.1 主链路 smoke tests

覆盖：

- `memory_query_hybrid`
- `memory_context`
- `memory_impact`
- `ContextPackBuilder`
- `mc_context_pack`
- `mc_freshness`

验收：

- 返回包含 freshness。
- 返回包含 evidence / progressive。
- 异常降级有 diagnostics。

### 7.2 Demo workspace 隔离测试

步骤：

1. 每个测试复制 `examples/spring-cloud-demo` 到 `tmp_path`。
2. 在临时目录 reindex。
3. 禁止写回仓库内已跟踪 `.memory-center` 数据。

验收：

- 跑完测试后 `git status --short` 不出现 demo graph / memory 生成物改动。

### 7.3 Query quality regression tests

覆盖：

- Feign 查询不会误命中普通 Service。
- Endpoint 查询优先 API path / controller。
- MQ 查询优先 Topic / Consumer。
- Config 查询优先 ConfigKey。
- project filter 后 summary 与 results 一致。

验收：

- 每个 intent 至少 2 个真实样例。
- 每个样例断言 top result 类型和 confidence。

### 7.4 Chain / contracts behavior tests

覆盖：

- callers / callees 不返回纯 DECLARES / CONTAINS 作为调用链主结果。
- Feign contract 自动关联 API 时只关联足够具体路径。
- group chain 返回 bridge reasons。

验收：

- 链路结果更可解释。
- 误关联减少。

## 8. Phase 4：Ontology 约束层主链路化

目标：

- 让 ontology 不只是文档，而是约束 query / contracts / chain / timeline / task 的统一语义。

步骤：

1. 更新 `docs/ONTOLOGY.md`。
   - 明确实体类型。
   - 明确边类型。
   - 明确 `fact / inferred / derived`。
   - 明确 confidence label。

2. 在代码里建立统一映射。
   - node type registry。
   - edge type registry。
   - semantic strength registry。
   - confidence label helper。

3. 应用到主链路：
   - `hybrid_retrieve`
   - `memory_contracts`
   - `memory_callers`
   - `memory_callees`
   - `memory_context`
   - `memory_impact`
   - timeline / ref / receipt 输出。

4. 增加 ontology tests。
   - 每个边类型必须有 semantic strength。
   - 未知边类型不能默默当 fact。
   - 输出字段必须包含 confidence label。

验收：

- 查询结果能解释“为什么是事实 / 推断 / 派生”。
- chain / impact 不再混用声明关系和行为关系。
- 文档和代码映射一致。

## 9. Phase 5：Context Pack / Freshness / Domain 工作流化

目标：

- 让 V3 能力从“可调用”变成“默认工作流”。

步骤：

1. `mc_start` 输出推荐下一步。
   - 架构理解：建议 `mc_context_pack`。
   - 变更预热：建议 `mc_context_pack` + `mc_analyze`。
   - 新人导览：建议 `mc_onboard` + `mc_domain`。

2. `mc_lookup(mode="auto")` 融合 freshness。
   - 如果 stale / pending，输出“先读 live file”的提示。
   - 如果 query 命中 stale file，提升警告级别。

3. `mc_analyze` 融合 context pack。
   - standard / full 模式附带 compact context summary。
   - 避免再次重复 grep/read。

4. `mc_domain` / `mc_onboard` 复用 explanation schema。
   - developer / architect / tester 输出有稳定差异。
   - flow / impact / onboarding 使用同一套业务流字段。

验收：

- 模型开始任务后能看到清晰下一步。
- freshness 不是独立工具，而是主链路可见信号。
- domain / onboard / impact 说同一种领域语言。

## 10. Phase 6：Benchmark / Audit / Observability 治理闭环

目标：

- 能持续发现质量退化，而不是靠人工偶然发现。

步骤：

1. 固定 benchmark 基线。
   - `mc_lookup`
   - `mc_context_pack`
   - `mc_analyze`
   - `mc_resume`
   - `mc_handoff`

2. 设置回归阈值。
   - token 增长阈值。
   - latency 增长阈值。
   - result quality 降级阈值。

3. 接入 health / audit。
   - `mc_admin(action="health")`
   - `mc_admin(action="audit")`
   - `mc_admin(action="regression_alerts")`

4. 补结构化 metrics。
   - 查询耗时。
   - 命中来源。
   - freshness 状态。
   - fallback reason。
   - token estimate。

验收：

- 一次优化能量化 token / latency / quality 变化。
- 回归能被 `regression_alerts` 发现。
- audit 输出更像治理建议，而不是简单文件检查。

## 11. Phase 7：文档、发布与最终验收

目标：

- 让代码、测试、文档、发布说明完全对齐。

步骤：

1. 更新主文档。
   - `README.md`
   - `docs/ARCHITECTURE.md`
   - `docs/MCP_GUIDE.md`
   - `docs/NEXT_PHASE_MASTER_PLAN.md`
   - `docs/ROADMAP.md`
   - `docs/CHANGELOG.md`

2. 明确状态术语。
   - 已实现模块
   - 已接入入口
   - 已完成主链路验收
   - 待产品化收口

3. 写 release note。
   - 记录修复项。
   - 记录行为变化。
   - 记录兼容性说明。

4. 最终验证。
   - `pytest -q`
   - CLI smoke
   - HTTP smoke
   - MCP facade smoke
   - `git status --short` 确认无生成物污染。

完成标志：

- 所有 P0 / P1 项完成。
- 三入口一致性测试通过。
- 文档不再把“基础版存在”误写成“完全收口”。
- 生成物不会污染工作树。

## 12. 可调整执行清单 / Flexible Task Order

以下 Sprint 是建议组合，不是固定顺序。执行者可以拆分、合并、跳转或重写工作包，优先完成最能改善真实使用体验的事项。

### 12.1 当前推荐顺序（3.5.9 之后）/ Recommended Order After 3.5.9

本节覆盖当前最值得继续开发的顺序。旧 Sprint 仍保留在下方作为能力域索引，但实际执行优先看本节。

#### P0：Ruff 现代化分层收口

目标：

- 把剩余 lint 债务继续拆成低风险、可验证的小批次，避免一次性大 churn。
- 每一批都必须保持 `F/E9/I001/B006/B008/B904` 继续通过。

执行顺序：

1. `UP035` deprecated typing imports。
   - 把 `typing.Dict/List/Optional/Union/...` 的旧导入逐步迁到现代写法所需的最小导入。
   - 先做 `memory_center/core/retrieval`、`memory_center/core/walkthrough`、`memory_center/core/benchmark` 等相对独立目录。
   - 不建议一口气覆盖 `orchestrator` 和全部 tests。

2. `UP006 / UP045 / UP007` 类型语法现代化。
   - `Dict[str, Any]` 改为 `dict[str, Any]`。
   - `Optional[str]` 改为 `str | None`。
   - 每次按目录提交，避免大范围 diff 难以 review。

3. `UP037 / UP031` 小型语法清理。
   - 清理 quoted annotation 和 printf-style formatting。
   - 仅在相关文件已有测试覆盖或改动很小的时候处理。

完成标准：

- 对应 Ruff selector 清零或在明确范围内清零。
- `ruff check --select F,E9,I001,B006,B008,B904 memory_center tests` 继续通过。
- `pytest -q` 和真实场景验收脚本通过。

#### P1：剩余 bugbear 语义项手工治理

目标：

- 优先修真正可能导致行为歧义或长期维护问题的告警。

执行顺序：

1. `B007` unused loop control variable。
   - 判断是确实不需要变量，还是循环逻辑遗漏了变量使用。
   - 不能机械改 `_`，除非确认语义不需要。

2. `B905` zip without explicit strict。
   - 对长度必须一致的业务逻辑使用 `strict=True`。
   - 对允许截断的逻辑显式加注释或局部 noqa，避免误改行为。

完成标准：

- 每处修复有语义判断。
- 相关单测覆盖或至少有 targeted smoke。

#### P2：入口输出体验继续优化

目标：

- 保持“输出详细，但更可读”的方向，不减少结构化信息。

优先事项：

1. Walkthrough report 的章节稳定性。
   - 继续优化 `summary / standard / deep` 的阅读层级。
   - 保证三档共享同一主链路事实，不出现链路解释分叉。

2. Recommended next step 统一化。
   - `mc_start`、`mc_lookup`、`mc_analyze`、`mc_resume` 的下一步建议要可追溯到 freshness、confidence、risk、contracts 或验证成本。
   - 避免泛泛建议，例如“继续查看代码”，应给出具体下一步动作和证据入口。

3. MCP flatten 字段契约稳定。
   - 继续把 agent 最常用字段提升到顶层。
   - 新字段只能 additive，不能破坏现有 MCP schema。

完成标准：

- 真实场景 walkthrough `completion_status=complete`。
- 输出可读性提升但 token 不低于真实 baseline 门禁。
- 不引导 agent 回到无效全局搜索。

#### P3：Parser / Retrieval / Reasoning 真实精度深化

目标：

- 把 parser、retrieval、reasoning 的优化继续放到真实主链路里验证，不只做模块级存在性测试。

优先事项：

1. Java Parser 差异评测继续扩展真实 case 类型。
   - Controller、Feign、Service interface、Impl、DTO field、config、MQ consumer 都要有稳定对比。
   - tree-sitter 与 regex 的差异要区分“真实回归”和“更完整抽取”。

2. Adaptive retrieval policy 的真实查询 A/B。
   - 对全链路、定位类、影响面类、配置类查询分别记录 source 选择、延迟和 token。
   - 学习权重只能基于真实验证证据更新。

3. Reasoning 输出证据化。
   - 风险、下一步、反模式建议必须能回溯到 evidence/ref。
   - 不增加不可验证的解释性噪音。

完成标准：

- 真实 Golden case 不回归。
- parser benchmark critical disagreement 为 0 或有明确可接受解释。
- retrieval policy diagnostics 可解释 source 选择。

#### P4：发布与文档治理

目标：

- 文档继续作为“当前事实 + 下一步计划”，避免回到旧的完成/未完成混写。

执行事项：

1. 每个版本至少更新 `CHANGELOG.md`。
2. 改动主架构或入口语义时，同步 `ARCHITECTURE.md` / `MCP_GUIDE.md`。
3. 每次调整计划时，同步本文件当前推荐顺序。
4. 不提交真实 workspace 的生成物、私有 cases、私有 baseline 或完整 payload。

完成标准：

- 文档中的验收命令和实际验证一致。
- 文档明确区分公开 examples smoke 与真实场景验收。
- `git status --short` 不包含生成物污染。

### Sprint 1：修 P0 主链路

1. 新增 freshness 失败测试。
2. 修 freshness API。
3. 新增 context risk 失败测试。
4. 修 `memory_context` store 作用域。
5. 新增 business-flow CLI/MCP 失败测试。
6. 修 business-flow workspace 解析。
7. 跑 `pytest -q`。

### Sprint 2：深化 vector、BM25 与 diagnostics

1. 在真实 workspace 构建 dense embeddings 并验证 active 路径。
2. 比较 graph / FTS / BM25 / semantic / vector 的召回贡献。
3. 调整融合权重和阈值。
4. 梳理主链路 `except Exception`。
5. 跑 benchmark 与全量测试。

### Sprint 3：入口矩阵测试

1. 建 CLI / HTTP / MCP 能力矩阵。
2. 覆盖 context-pack / freshness / onboard / domain。
3. 覆盖 business-flow / business-flow-impact。
4. 覆盖 verification-loop / runtime-audit / regression-alerts。
5. 跑 `pytest -q`。

### Sprint 4：Ontology 主链路化

1. 更新 `docs/ONTOLOGY.md`。
2. 抽出 ontology registry helper。
3. 接入 query / contracts / chain / impact。
4. 增加 ontology consistency tests。
5. 跑 `pytest -q`。

### Sprint 5：Workflow 产品化

1. `mc_start` 增加 context-pack / freshness 推荐。
2. `mc_lookup` stale/pending 提示主链路化。
3. `mc_analyze` 加 context summary。
4. `mc_domain` / `mc_onboard` 复用 explanation schema。
5. 跑 `pytest -q`。

### Sprint 6：治理闭环

1. 固定 benchmark baseline。
2. 接入 regression alerts。
3. 强化 audit workspace type。
4. 增加 metrics summary 字段。
5. 跑 `pytest -q`。

### Sprint 7：文档与发布

1. 更新 README / ARCHITECTURE / MCP_GUIDE。
2. 更新 NEXT_PHASE_MASTER_PLAN，把已完成和待收口拆清楚。
3. 更新 ROADMAP / CHANGELOG。
4. 检查 demo `.memory-center` 生成物策略。
5. 最终验证并准备发布。

## 13. 最终 Done Definition / 最终完成定义

下一阶段结束时，应达到：

1. P0 问题全部修复。
2. `pytest -q` 通过。
3. CLI / MCP / HTTP 主入口 smoke 通过。
4. freshness、risk、vector、business-flow 不再静默失败。
5. `mc_lookup` / `mc_analyze` 能清楚展示 freshness 和证据来源。
6. ontology 映射约束至少覆盖 query / contracts / chain / impact。
7. benchmark / audit 能发现质量退化。
8. 文档状态与实现状态一致。
9. 测试不会修改仓库内已跟踪的生成物。
10. 没有真实私有路径、内部服务名或密钥进入示例。

## 14. 开放方向 / Open Directions

以下方向不再视为禁区。只要能够明显改善功能可用性、使用体验、性能、可靠性或维护效率，就可以直接调研、原型验证并实施：

1. 重写 indexer，提高索引精度、增量性能和语言扩展能力。
2. 引入可选或默认的外部图数据库、向量数据库和搜索后端。
3. 重新设计 JSONL、SQLite、graph 和 memory 存储结构，并提供迁移工具。
4. 增加 daemon、后台任务、自动监听和持续索引能力。
5. 重做前端、可视化、配置流程和排障体验。
6. 合并或删除重复入口，重新设计 MCP、CLI、HTTP 的产品交互。
7. 引入新的语言支持、框架适配器、评测系统和 Agent 工作流。

选择开放方向时，至少回答：

- 解决了哪个真实用户问题。
- 相比当前实现，体验或能力提升在哪里。
- 最小可用版本如何验证。
- 数据迁移、兼容和回滚如何处理。
- 后续维护成本是否可接受。
