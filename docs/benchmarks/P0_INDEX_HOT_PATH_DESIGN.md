# P0-0 Index Hot Path Design / 索引热路径收口设计

> 本文档是 [NEXT_PHASE_MASTER_PLAN.md](../NEXT_PHASE_MASTER_PLAN.md) 中
> **P0-0 CBM 参考设计对齐** 的产出。目的只有一个:在动 P0 三个热点修复
> 前,把它们放进同一条 Java 索引热路径策略里,避免零散返工。
>
> This document is the P0-0 output described in
> [NEXT_PHASE_MASTER_PLAN.md](../NEXT_PHASE_MASTER_PLAN.md). It locks the
> contract shared by the three P0 fixes before any code change.

---

## 1. 背景 / Background

### 1.1 已经吸收的 CBM 思路 / Already absorbed

对照 [docs/references/codebase-memory-mcp.md](../references/codebase-memory-mcp.md)
的六个关键设计,逐项在当前代码里查证后的结论是:**CBM 列出的设计绝大
多数 Memory Center 已经实现**。

| CBM 关键设计 | Memory Center 落地 |
|---|---|
| 2.2 tree-sitter + 类型解析层 | `TreeSitterJavaParser` + `JavaCallResolver`(same_class / same_package / imports / static_import / wildcard)+ `eval_java_call_resolution` gate |
| 2.3 Graph-first query surface | `GraphStore` + `walkthrough/` + `domain/flow.py` + `reasoning/`(fact / inferred / derived);walkthrough 已带 completion status |
| 2.4 FTS / BM25 / semantic 候选 + graph 硬约束 | `graph.node_search`(FTS5)+ `retrieval/inverted.py`(posting-list BM25)+ `retrieval/policy.py`(exact + graph 硬约束,其它源可选)+ `retrieval_diagnostics` |
| 2.5 Watcher / incremental | `freshness/watcher.py`(mtime polling + 防抖)+ `freshness/reconcile.py`(connect-time catch-up)+ `indexing/incremental.py`(新增/修改/删除/移动) |
| 2.6 Evaluation methodology | `benchmark/golden.py` / `benchmark/java_call_resolution.py` / `benchmark/trending.py` / `benchmark/baseline.py` + 真实 UCAP gate |

### 1.2 尚未做的两块 / Still open

- **2.1 RAM-first indexing pipeline** 在本阶段的具体落地就是 **Python 热路径
  优化**:parser 双轨、`JavaSymbol` `asdict` 递归、graph metadata 高频
  `json.dumps`。这三个热点在
  [P1_0_JAVA_PARSING_PROFILE.md](./P1_0_JAVA_PARSING_PROFILE.md) 里已经被
  cProfile 定位,代码里也仍然存在。
- **2.5 compressed shared graph artifact (`graph.db.zst`)** 暂不做,
  master plan 已经把它归入“中期评估”,不在 P0 / P1 主线上。

所以 P0-0 真正要锁定的,是这三个 Python 热点修复的共同契约。

---

## 2. 共享契约 / Shared Contract

### 2.1 不变量 / Invariants

P0 三个修复必须共同满足:

1. **MCP / CLI / HTTP 公共 schema 零变化**。`JavaSymbol` 序列化输出的
   字段集合、字段类型、字段顺序对 downstream(graph、benchmark、报告)
   全部保持兼容。
2. **parser 行为可观测、可回滚**。任何路径选择(双轨 / 单轨 / fallback)
   都必须能从 `TreeSitterJavaParser.diagnostics` 看出来,且能通过环境
   变量一键回到当前行为。
3. **`RegexJavaParser` 不删**。它是 tree-sitter 不可用时的 fallback,
   也是 [tests/test_parser_differential.py](../../tests/test_parser_differential.py)
   的 oracle。
4. **质量 gate 优先于性能**。parser differential critical disagreement
   保持 `=0`;Java call resolution gate 不退步;Golden anchor recall /
   edge recall 不退步;forbidden hit `=0`。
5. **真实 UCAP reindex 不慢于当前基线**(节奏与
   [P0_UCAP_REAL_BENCHMARK.md](./P0_UCAP_REAL_BENCHMARK.md) 一致)。

### 2.2 输出契约 / Output contract

- `JavaSymbol.to_dict()` 是字段级浅拷贝。`list` / `dict` 字段返回浅拷贝,
  内部 `list[dict]` 元素本身仍是原引用。下游路径(graph rebuild、benchmark、
  report)只读这些值,允许浅拷贝。
- `core.models.to_dict(obj)` 仍然存在,但优先调用对象自带的 `to_dict()`,
  否则回退到 `dataclasses.asdict`。这保证 `indexer.py` 等调用点零修改。
- graph metadata 序列化统一走一个本地 `_metadata_json(meta)`:空 metadata
  直接返回字面量 `'{}'`,非空才 `json.dumps(..., ensure_ascii=False)`。
  `bulk_write` / `rebuild` / `partial_rebuild` / `_upsert_search_rows`
  和 `retrieval/inverted.py`、`semantic.py` 中等价位置全部走它。

### 2.3 Parser 双轨收敛策略 / Parser dual-track convergence

当前 `TreeSitterJavaParser.parse()` 行为是:每个文件先跑完整
`RegexJavaParser().parse()`,然后跑 tree-sitter,再 merge。P1-0 profile
显示 regex parser 的 58 s tottime 全部来自 tree-sitter 入口。

本阶段把双轨从“parse 时永远全量跑”降级为“仅补抽取”:

1. tree-sitter `parse_native` 已覆盖的字段(package / imports / classes /
   interfaces / methods / method_signatures / fields / annotations /
   field_types / 各 `*_lines`)由 tree-sitter 直接产出,**不再回头调 regex**。
2. tree-sitter 暂未覆盖的字段(`constants` / `method_variable_types` /
   `bean_injections` / `method_calls` / `dto_field_usages` /
   `config_usages` / `data_resources`)由 `RegexJavaParser.parse_supplements()`
   单独抽取。这个入口走和原来一样的解析子函数,但不再重复构造 classes /
   methods / imports / fields 等结构。
3. tree-sitter 不可用或 parse 失败时,`TreeSitterJavaParser.parse()` 仍
   fallback 到完整 `RegexJavaParser.parse()`(零行为变化)。
4. 提供 `MEMORY_CENTER_PARSER_FULL_DUAL=1` 兜底:一旦 differential 报警,
   设置该环境变量即可恢复到当前“双轨全量”行为,不需要 revert 代码。
5. `TreeSitterJavaParser.diagnostics` 增补两个计数:`supplement_calls`、
   `full_regex_fallback_calls`,便于真实 workspace 上观察。

### 2.4 验收门禁 / Acceptance gates

每个修复独立提交,通过同一组门禁:

- `python3 -m compileall -q memory_center tests`
- `pytest -q`
- `tests/test_parser_differential.py` critical disagreement `=0`
- `tests/test_java_call_resolution_benchmark.py` 不退步
- `tests/test_golden_benchmark.py` anchor recall / edge recall 不退步
- `tests/test_graph_rebuild_perf.py` / `tests/test_benchmark_workspace_perf.py`
  在本地不退步(focused micro benchmark)
- 在 `<private-real-workspace>` 上跑 `scripts/verify_real_ucap.sh`,reindex
  不低于 [P0_UCAP_REAL_BENCHMARK.md](./P0_UCAP_REAL_BENCHMARK.md) 基线

真实 baseline 由各自的 P0 修复者在私有 workspace 上跑;公开仓库内不提交
任何真实 workspace 输出或私有路径。

---

## 3. 实施顺序 / Implementation order

三步按风险从低到高执行,每步一个独立 commit:

1. **Step 1: `JavaSymbol.to_dict()` 浅拷贝**。最稳,只动序列化层,
   不改 parser 行为,不改 graph 写入路径。
2. **Step 2: Graph metadata 空 dict 快路径**。schema 不变,只改
   metadata 序列化函数 + 调用点。
3. **Step 3: Parser 双轨改为补抽取**。最敏感,必须依赖 differential /
   call resolution / golden gate 一起兜底,并保留 `MEMORY_CENTER_PARSER_FULL_DUAL`
   兜底开关。

任意一步红线只回滚自己,不影响前一步。

---

## 4. 非目标 / Non-goals

- 不引入 C 重写、不引入 zstd / lz4 / mmap pipeline 等运行时依赖。
- 不删除 `RegexJavaParser.parse`,它继续作为 fallback 和 differential oracle。
- 不调整 `JavaParseResult` 字段。tree-sitter 仍可补字段,但本阶段不改 schema。
- 不引入 `graph.db.zst` 共享 artifact;留作后续单独立项。
- 不在公开 examples 里跑真实 UCAP benchmark,baseline 留本地。

---

## 5. 真实 UCAP 验收结果 / Real UCAP gate results

2026-06-24 在私有 UCAP workspace
(`<private-real-workspace>` / 36 services / 20,516 Java files / 27 GB)
上跑完整 P0 修复后的真实门禁,所有结果均不退步:

- **Java call resolution gate**(`mc_admin eval-java-call-resolution`):
  - case_count: 15 / passed_cases: **15**
  - edge_recall: **1.0**
  - high_confidence_expected_rate: **1.0**
  - resolution_level_rate: **1.0**
  - unresolved_rate: **0.0**
  - 与 `golden/java-call-resolution-baseline.json` 完全一致。
- **Golden suite**(`scripts/verify_real_ucap.sh`):
  - case_count: 7 / edge_recall: **1.0** / forbidden_hit_rate: **0.0**
  - performance_gate_status: **pass**
  - median_latency_ms: 711 / p95_latency_ms: 1502
  - anchor_recall: 0.8286(与 legacy full-dual 同值;非 P0 引入)
- **Walkthrough**(targeted private query):
  - state: **complete** / 5 expected layers 全部命中
  - target: `WebsiteInfoLeakageMasterServiceImpl#listByDto`
- **Doctor**: 53 checks / 0 failed
- **Reindex wall-clock**(`scripts/bench_p0_ucap.py`,冷启动 1 run):
  - legacy (full-dual): 140.6 s / 314,964 nodes / 1,021,697 edges
  - after-p0(supplements + tree-sitter 节点覆盖修补):
    139.0 s / 316,695 nodes / 1,023,066 edges
  - 真实净效果:wall-clock 与 legacy 持平(IO 抖动主导),graph 反而
    多出 ~1.7K 节点和 ~1.4K 边——tree-sitter 现在正确识别
    `@interface` / `annotation_type_element_declaration` /
    `constant_declaration` 和 wildcard imports,同时跳过 legacy
    regex 在 SQL 字符串里的伪 method / 伪 class false positive。
- **结论**:P0 修复在最关键的 call resolution gate 和 golden gate 上
  零退步,parser 质量改进可见,wall-clock 收益不显著(被
  graph rebuild ~53s + semantic build ~21s 等不可改部分稀释)。
  这与 [P0_UCAP_REAL_BENCHMARK.md](./P0_UCAP_REAL_BENCHMARK.md) 在
  2026-06-23 的判断一致:**Python 解析层修复对 reindex wall-clock 的
  影响有限,但是修复仍是必要的**(尤其是 tree-sitter 节点覆盖)。
- **门禁通过条件**:
  - parser differential critical disagreement = 0 ✓
  - Java call resolution gate 不下降 ✓
  - Golden anchor recall 不下降(0.8286 = 0.8286) ✓
  - Golden edge recall 不下降(1.0 = 1.0) ✓
  - forbidden hit rate = 0 ✓
  - 真实 reindex 不慢于基线(140.6s baseline → 139.0s after-p0) ✓

真实 cases / 路径 / 时间 / token 等私有数据保存在
`<private-real-workspace>/.memory-center/`,不进入公开仓库。
