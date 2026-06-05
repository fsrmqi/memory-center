# Next Phase Execution Plan / 下一阶段执行计划

## 1. 文档目标 / Purpose

本文档是 `docs/NEXT_PHASE_MASTER_PLAN.md` 的执行版。

总方案回答“方向是什么”，本文档回答“接下来一步一步怎么做，做到哪里算结束”。

当前判断：

- V3 / Next Phase 基础能力已经大量存在。
- 主要风险不是缺少模块，而是主链路接入、三入口一致性、静默失败、文档与实现状态漂移。
- 下一阶段应先做收口，再做扩展。

执行原则：

1. 先修真实主链路问题，再继续堆新能力。
2. 每一阶段必须有测试、入口验证和文档同步。
3. CLI / MCP / HTTP 同一能力必须尽量保持同一语义。
4. 任何被 `except Exception` 吞掉的主链路失败，都要转成可见诊断或明确降级说明。
5. 不提交私有 workspace 生成的 `.memory-center/index`、`.memory-center/memory` 内容。

## 2. 当前问题清单 / Current Findings

### P0：主链路静默失败

当前状态：

- freshness 方法名不一致问题已修复。
- context risk、vector retrieval、business-flow 三入口一致性已进入 3.1.2 主链路收口。
- 后续重点从“已知 P0 修复”转为“三入口矩阵持续覆盖、静默降级 diagnostics、测试 workspace 隔离”。

#### 2.1 Freshness 主查询链路失效

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

#### 2.2 Context risk patterns 不生效

现象：

- `memory_context` 里调用 `RiskAnalyzer(store)`，但 `store` 未在函数作用域定义。
- 异常被吞掉后 `risk_patterns` 长期为空。

涉及位置：

- `memory_center/core/orchestrator/query.py`

期望：

- `memory_context` 能稳定返回 risk patterns。
- 若风险分析不可用，返回 `_diagnostics`，不要静默丢失。

#### 2.3 Vector retrieval 分支不可用

现象：

- `hybrid.py` 内 `_vector_retrieval` 使用错误相对导入。
- `VectorIndex` 构造需要 `UnifiedStore`，当前逻辑传入 db path。
- 异常被吞掉后 vector 分支实际不参与结果。

涉及位置：

- `memory_center/core/retrieval/hybrid.py`
- `memory_center/core/storage/vector_index.py`

期望：

- 如果 vector 还没准备好，应明确标为 disabled / unavailable。
- 如果要启用，必须能真实读取 vector index 并参与融合排序。

#### 2.4 Business flow CLI / MCP 路径错误

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

## 3. 总体执行路线 / Execution Roadmap

推荐分 8 个阶段执行：

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

### 5.3 修复 vector retrieval

步骤：

1. 修正导入：
   - `from ..store import WorkspaceStore`
   - `from ..storage.unified import UnifiedStore`
   - `from ..storage.vector_index import VectorIndex`

2. 正确构造：
   - `workspace_store = WorkspaceStore(workspace_file)`
   - `unified = UnifiedStore(workspace_store.graph_db_path)`
   - `vector = VectorIndex(unified)`

3. 明确启用条件：
   - 有 vector metadata。
   - 有 query embedding 来源。
   - 维度匹配。

4. 如果不能启用，返回 diagnostics：

```json
{
  "vector_status": "disabled|empty|unavailable|active",
  "vector_reason": "..."
}
```

验收：

- vector index 为空时不会假装启用。
- vector index 有数据时能参与结果来源。
- `hybrid_retrieve` 的 summary 能显示 vector source。

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

## 12. 推荐执行顺序 / Concrete Task Order

### Sprint 1：修 P0 主链路

1. 新增 freshness 失败测试。
2. 修 freshness API。
3. 新增 context risk 失败测试。
4. 修 `memory_context` store 作用域。
5. 新增 business-flow CLI/MCP 失败测试。
6. 修 business-flow workspace 解析。
7. 跑 `pytest -q`。

### Sprint 2：修 vector 与 diagnostics

1. 新增 vector disabled / active 测试。
2. 修 `_vector_retrieval` 导入与 `UnifiedStore` 构造。
3. 给 hybrid result 增加 vector diagnostics。
4. 梳理主链路 `except Exception`。
5. 跑 `pytest -q`。

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

下一阶段结束时，必须同时满足：

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

## 14. 暂不优先事项 / Explicit Non-Goals

下一阶段先不优先做：

1. 大规模重写 indexer。
2. 引入重型外部图数据库。
3. 把所有 JSONL 立即迁到 SQLite。
4. 完整 daemon 常驻服务。
5. 前端大改版。

这些方向可以保留，但必须排在主链路收口之后。
