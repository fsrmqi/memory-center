# Memory Center Next Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用可复现的 Golden Benchmark 驱动推理主链路、Java parser 精度、自适应检索和 Agent 使用体验继续进化。

**Architecture:** 先建立一个不包含私有源码的 evaluation Module，后续所有优化都必须通过同一 Interface 证明准确率、延迟或 token 收益。Reasoning、parser 和 retrieval 保持独立 Implementation，通过现有 facade seam 接入；CLI、MCP、HTTP 只做参数和结果适配，不复制决策逻辑。

**Tech Stack:** Python 3.10+、pytest、SQLite graph/BM25/vector、tree-sitter-java、现有 Memory Center CLI/MCP/HTTP facade。

---

## 执行顺序

1. `P0` Golden Benchmark 与质量门禁
2. `P1` Reasoning Pipeline 主链路化
3. `P1` Java Parser 差异评测与精度修复
4. `P1` 自适应检索策略
5. `P2` Agent 使用体验闭环与 Workbench 展示

没有完成 Task 1 前，不开始基于主观感受调整 retrieval 权重或 reasoning 深度。

---

### Task 1: Golden Benchmark 与质量门禁

**Files:**
- Create: `memory_center/core/benchmark/golden.py`
- Create: `memory_center/core/benchmark/models.py`
- Create: `examples/golden-benchmark/workspace.yaml`
- Create: `examples/golden-benchmark/cases.yaml`
- Create: `tests/test_golden_benchmark.py`
- Modify: `memory_center/core/benchmark/__init__.py`
- Modify: `memory_center/cli/main.py`
- Modify: `memory_center/mcp/admin_actions.py`
- Modify: `memory_center/http/routes/analysis.py`
- Modify: `docs/TECHNICAL_GUIDE.md`

**Interface:**

```python
@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    query: str
    mode: str
    expected_anchors: tuple[str, ...]
    expected_edges: tuple[str, ...]
    forbidden_anchors: tuple[str, ...] = ()
    max_latency_ms: float = 5000.0

def run_golden_suite(workspace_file: str | Path, cases_file: str | Path) -> dict:
    ...
```

- [x] **Step 1: Write failing schema and scoring tests**

```python
def test_golden_case_scores_anchor_recall_and_forbidden_hits():
    result = score_golden_case(
        expected_anchors=["Entry#run", "RemoteController#list"],
        actual_anchors=["Entry#run", "WrongController#list"],
        forbidden_anchors=["WrongController#list"],
    )
    assert result["anchor_recall"] == 0.5
    assert result["forbidden_hit_count"] == 1
    assert result["passed"] is False
```

- [x] **Step 2: Run RED**

Run: `pytest -q tests/test_golden_benchmark.py`

Expected: FAIL because `golden.py` and the scoring Interface do not exist.

- [x] **Step 3: Implement portable case loading and scoring**

只允许保存逻辑 symbol、edge type、耗时和 token，不保存绝对路径、源码片段、公司服务名或业务数据。

- [x] **Step 4: Add a portable public demo suite and private-case template**

使用仓库公开 `spring-cloud-demo` 作为可复现 demo suite，并提供私有 `cases.template.yaml` 用于真实 workspace。覆盖入口方法、同类私有方法、Service interface → Impl、Feign → Controller、Controller → Service Impl。

- [x] **Step 5: Expose one shared operation through adapters**

```text
CLI: memory-center eval-golden
MCP: mc_admin(action="eval_golden")
HTTP: /workspace/eval-golden
```

- [x] **Step 6: Verify GREEN and set quality gates**

Run: `pytest -q tests/test_golden_benchmark.py tests/test_capability_matrix.py`

Acceptance:
- anchor recall `>= 0.90`
- edge recall `>= 0.85`
- forbidden hit rate `= 0`
- suite 输出 median/p95 latency 与 token estimate
- 同一 fixture 连续执行结果稳定

---

### Task 2: Reasoning Pipeline 主链路化

**Files:**
- Create: `memory_center/core/reasoning/pipeline.py`
- Create: `memory_center/core/reasoning/models.py`
- Modify: `memory_center/core/reasoning/integration.py`
- Modify: `memory_center/core/orchestrator/query.py`
- Modify: `memory_center/core/orchestrator/impact.py`
- Modify: `memory_center/core/walkthrough/runner.py`
- Create: `tests/test_reasoning_pipeline.py`
- Modify: `tests/test_golden_benchmark.py`

**Interface:**

```python
@dataclass(frozen=True)
class ReasoningRequest:
    target_id: str
    intent: str
    max_depth: int
    evidence_budget: int

class ReasoningPipeline:
    def analyze(self, request: ReasoningRequest) -> dict:
        ...
```

- [x] **Step 1: Write a failing fact/inferred/derived test**

```python
def test_reasoning_pipeline_explains_transitive_risk(graph_store):
    result = ReasoningPipeline(graph_store).analyze(
        ReasoningRequest("Method:A#run", "impact", 4, 20)
    )
    assert result["facts"]
    assert result["inferences"]
    assert all(item["why"] for item in result["inferences"])
    assert result["quality"]["verification_required"] is True
```

- [x] **Step 2: Run RED**

Run: `pytest -q tests/test_reasoning_pipeline.py`

- [x] **Step 3: Move orchestration behind the pipeline seam**

复用现有 `patterns.py`、`transitive.py`、`risk.py`，不要复制 graph traversal。Pipeline 负责预算、去重、语义层级和 explanation；各 facade 只提交 request。

- [x] **Step 4: Integrate lookup, impact, and walkthrough additively**

返回新增 `_reasoning`，保留现有字段；任何推断必须包含来源节点、关系、confidence 和 `why`。

- [x] **Step 5: Verify against Golden Benchmark**

Acceptance:
- 不降低 Task 1 anchor/edge recall
- 每条 inferred/derived 结果都有 explanation
- reasoning 关闭时保持原行为
- standard 模式额外 token 不超过基线 `20%`

验证记录（2026-06-18）：私有真实 workspace case anchor recall `1.0`、edge recall `1.0`、forbidden hit rate `0`、latency `2818.687ms`、token estimate `60828`；相对 Task 1 基线 latency 增加约 `11.3%`、token 增加约 `1.7%`。

---

### Task 3: Java Parser 差异评测与精度修复

**Files:**
- Create: `memory_center/core/indexing/differential.py`
- Create: `examples/parser-corpus/`
- Create: `tests/test_parser_differential.py`
- Modify: `memory_center/core/indexing/tree_sitter_parser.py`
- Modify: `memory_center/core/indexing/parser.py`
- Modify: `memory_center/core/indexer.py`

**Corpus 必须覆盖:**
- 方法重载
- 泛型与嵌套泛型
- 内部类和匿名类
- interface default method
- 继承与实现
- Lombok constructor injection
- 注解常量和组合路径
- `@RequestMapping` 通用方法
- Feign interface 与 fallback
- switch expression、lambda、method reference

- [x] **Step 1: Write failing parser parity tests**

```python
def test_parsers_agree_on_public_method_identity(parser_corpus):
    report = compare_parsers(parser_corpus / "OverloadedService.java")
    assert report["missing_in_tree_sitter"] == []
    assert report["critical_disagreements"] == []
```

- [x] **Step 2: Run RED and capture disagreements**

Run: `pytest -q tests/test_parser_differential.py`

- [x] **Step 3: Implement differential report**

比较 classes、methods、method lines、fields、injections、calls、Feign mappings、Controller mappings；禁止只比较总数量。

- [x] **Step 4: Fix critical parser gaps one category at a time**

每个修复必须先增加最小 corpus 文件，不允许用真实私有项目源码做 fixture。

- [x] **Step 5: Add parser selection diagnostics**

reindex 返回 parser、fallback count、critical disagreement count；tree-sitter 失败时明确回退原因。

Acceptance:
- corpus critical disagreement `= 0`
- method/class/endpoint recall `>= 0.98`
- 行号误差不超过 1 行
- parser fallback 可观测

验证记录（2026-06-22）：公开 6-file corpus critical disagreement `0`、entity recall `1.0`、max line delta `0`；AST-enabled 与 fallback 两套完整测试均通过。私有真实 workspace Golden case anchor recall `1.0`、edge recall `1.0`、forbidden hit rate `0`、latency `2807.67ms`。

---

### Task 4: 自适应检索策略

**Files:**
- Create: `memory_center/core/retrieval/policy.py`
- Modify: `memory_center/core/retrieval/hybrid.py`
- Modify: `memory_center/core/verification/heuristics.py`
- Create: `tests/test_retrieval_policy.py`
- Modify: `tests/test_golden_benchmark.py`

**Interface:**

```python
@dataclass(frozen=True)
class RetrievalPolicy:
    sources: tuple[str, ...]
    graph_depth: int
    candidate_limit: int
    semantic_enabled: bool
    vector_enabled: bool
    evidence_budget: int

def select_retrieval_policy(intent: dict, freshness: dict, learned_weights: dict) -> RetrievalPolicy:
    ...
```

- [ ] **Step 1: Write failing deterministic policy tests**

```python
def test_full_chain_prefers_graph_and_disables_unneeded_vector():
    policy = select_retrieval_policy(
        {"primary_intent": "walkthrough", "is_full_chain": True},
        {"status": "fresh"},
        {},
    )
    assert policy.sources[:2] == ("exact", "graph")
    assert policy.semantic_enabled is False
    assert policy.graph_depth >= 4
```

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_retrieval_policy.py`

- [ ] **Step 3: Implement policy selection as a pure Module**

策略输入只包含 intent、freshness、学习权重；不得直接读取全局配置或修改 result 对象。

- [ ] **Step 4: Integrate policy before source execution**

未启用的 source 不应执行，不能在融合阶段才把结果丢弃。

- [ ] **Step 5: Feed verified outcomes back into bounded weights**

学习权重只能在配置上下限内轻量调整，不得覆盖规则生成的硬约束。

Acceptance:
- Golden recall 不降低
- walkthrough/query median latency 至少改善 `15%`
- compact token 至少改善 `10%`
- 相同输入产生确定性 policy

---

### Task 5: Agent 使用体验闭环与 Workbench 展示

**Files:**
- Create: `memory_center/core/completion.py`
- Modify: `memory_center/core/walkthrough/answer.py`
- Modify: `memory_center/core/orchestrator/query.py`
- Modify: `memory_center/mcp/server.py`
- Modify: `memory_center/http/routes/analysis.py`
- Modify: `web/src/views/WorkbenchView.vue`
- Create: `tests/test_completion_status.py`
- Modify: `tests/test_mcp_facades.py`

**Interface:**

```python
@dataclass(frozen=True)
class CompletionStatus:
    state: str  # complete | partial | blocked | stale
    terminal_anchor: str
    missing_layers: tuple[str, ...]
    stop_reason: str
    recommended_action: str
```

- [ ] **Step 1: Write failing completion-state tests**

```python
def test_complete_chain_tells_agent_to_stop_searching():
    status = evaluate_completion(
        expected_layers=["entry", "service", "remote", "data"],
        observed_layers=["entry", "service", "remote", "data"],
        freshness="fresh",
    )
    assert status.state == "complete"
    assert status.recommended_action == "use_current_evidence"
```

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_completion_status.py`

- [ ] **Step 3: Add completion status to lookup/walkthrough**

`complete` 必须明确告诉 Agent 停止重复 find/grep；`partial` 必须列出缺失层；`stale` 必须优先建议 reindex 或 live read。

- [ ] **Step 4: Surface quality in MCP and HTTP without schema breakage**

复用 `_quality`、`_reasoning`、`completion_status`，不新增平行评分结构。

- [ ] **Step 5: Add Workbench visualization**

页面展示：链路完成状态、anchor recall、freshness、median/p95 latency、缺失层和推荐动作；移动端保持可读。

Acceptance:
- 完整链路不再建议全局搜索
- 不完整链路明确缺失位置和停止原因
- MCP、HTTP、Workbench 对同一结果显示一致状态
- Golden suite 中 Agent 无效搜索建议数量下降 `>= 50%`

---

## 全阶段验收

- [ ] `python3 -m compileall -q memory_center tests`
- [ ] `git diff --check`
- [ ] `pytest -q`
- [ ] Golden anchor recall `>= 0.90`
- [ ] Golden edge recall `>= 0.85`
- [ ] forbidden hit rate `= 0`
- [ ] walkthrough median latency 相比 3.2.0 基线改善 `>= 15%`
- [ ] compact token 相比 3.2.0 基线改善 `>= 10%`
- [ ] 不提交真实 workspace 的 `.memory-center/index`、memory、源码或绝对路径

## 非目标

- 不在本阶段删除 regex parser。
- 不默认开启 vector retrieval。
- 不把 JSON/JSONL/Markdown 文件事实源一次性迁移到 SQLite。
- 不增加新的 MCP facade tool；优先扩展现有 `mc_lookup`、`mc_analyze`、`mc_admin`。
- 不为了类型化破坏现有 dict 返回和 MCP tool schema。
