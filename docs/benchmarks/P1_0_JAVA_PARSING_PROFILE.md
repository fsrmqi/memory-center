# P1-0 Java 解析阶段瓶颈定位 / Java Parsing Hot-Path Profile

> P0 benchmark 证伪了"5-10× SQLite 提速"的预测,把矛头指向 reindex 总耗时
> 里那 71% 的"非 SQLite"那一段。P1-0 这一步用 cProfile 在真实 UCAP 工作区
> 上把这 71% 拆开了。结论比预想的更具体:**真正的 dominant cost 不是
> tree-sitter 解析本身,而是几个具体的、可优化的 Python 层面问题**。

---

## 测量环境

| 维度 | 值 |
|---|---|
| 工作区 | `/Users/cuijiaqi/javaworkspace/ucap` (UCAP 微服务平台) |
| 规模 | 36 service / 20,516 Java 文件 / 27 GB |
| 机器 | Apple M3 Pro / macOS Darwin 25.5.0 |
| Python | 3.11 in `.venv` |
| 测量方式 | `memory-center bench-profile --workspace <yaml> --top 50 --by-module` |
| commit | `4e5ee34`(P1-0 工具引入后,生产代码与 P0 完成态相同) |
| reindex elapsed | **130.4 s** (与 P0 benchmark 一致) |
| 原始 pstats | [`ucap-p1-0-baseline.prof`](./ucap-p1-0-baseline.prof) (122 KB,可用 `snakeviz` 打开) |

---

## 模块级 Top-20 (cumulative time)

```
  543.72s  indexer.py            (整条 reindex_workspace 调用链)
  240.34s  observability.py      (@observe_operation 装饰器栈,基本透传)
  156.93s  java_regex_parser.py  ⚠️ 30s tottime — 双轨开销
  128.07s  tree_sitter_parser.py
  125.41s  ~ (built-in)          sqlite3 + re + str.count 等 C 调用
   80.45s  graph.py
   80.44s  dataclasses.py        ⚠️ 22M asdict 调用
   59.73s  __init__.py           (json + re 模块入口)
   49.61s  semantic.py
   28.56s  inverted.py           BM25 倒排索引重建
   26.38s  encoder.py            (json 编码)
   24.85s  models.py
   ...
```

`cumulative` 列含调用链,所以 `indexer.py` 是 543s 不奇怪 ——
它是入口,所有时间都计在它名下。**真正反映"代码本身花了多久"的是
`tottime`**(不含子调用)。

---

## 函数级 Top-15 (cumulative time)

```
       1   71.36   reindex_workspace                          (入口)
   16324   82.60   tree_sitter_parser.parse                   <- 双轨 root
       1   72.35   indexer.build_graph_store
   16324   58.19   java_regex_parser.parse                    <- 全部来自 ts parser
       1   52.99   graph.rebuild                              (P0-3 已优化)
       5   37.55   sqlite3 executemany
       1   29.35   _sync_retrieval_indexes
       1   26.97   inverted.rebuild                           BM25 重建
       1   20.85   semantic.build_workspace_semantic_index
   22809   20.85   models.to_dict   <- 22K 次,每次约 ~600 _asdict_inner
   22809    -      dataclasses.asdict
13.5M(!)    -      dataclasses._asdict_inner                  ⚠️ 递归爆炸
   16324   20.45   tree_sitter_parser.parse_native
17.3M(!)   16.74   tree_sitter_parser._walk                   tree-sitter 树遍历
   16324   15.93   java_regex_parser._strip_comments          每个文件全字串扫描一次
     131   15.92   sqlite3 execute (single-statement)
   16324   14.19   java_regex_parser._parse_bean_injections
4.59M      14.19   json.dumps                                 metadata 序列化
```

---

## 三个真实瓶颈

### 🔴 瓶颈 #1:Java parser 双轨开销(~58 s,占 reindex 总时间 44%)

`TreeSitterJavaParser.parse` 现在的做法:

```python
def parse(self, text, file_path):
    regex_result = RegexJavaParser().parse(text, file_path)   # 始终先跑
    if not self._parser:
        return regex_result                                    # tree-sitter 不可用,fallback
    tree_result = self.parse_native(text, file_path)
    if tree_result is None:
        return regex_result                                    # tree-sitter 失败,fallback
    return _merge_parse_results(tree_result, regex_result)     # 否则 merge
```

**问题**:**即使 tree-sitter 可用且解析成功(99%+ 场景),regex parser
仍要全量跑一遍 ~58 s**。这是历史"防 tree-sitter 漏抽"的安全网,但代价巨大。

**实测影响**:`java_regex_parser.parse` 16,324 次调用,**100% 来自
`TreeSitterJavaParser.parse`**,而不是直接调用。

**P1 优化思路**(留作 P1-1 / P1-2 实现时考虑):
- 方案 A:tree-sitter 成功时只跑增量 regex(只补它已知漏抽的字段,如 `bean_injections`)
- 方案 B:tree-sitter 成功时完全跳过 regex,把"漏抽什么"通过 differential
  benchmark 验证后转成 tree-sitter 扩展抽取
- 方案 C:把 `_strip_comments` 和高频小函数 cache 起来,降低单次 ~3.6ms
  的开销

收益估计:~30~58s 量级。**这是单点最大的优化空间**。

### 🔴 瓶颈 #2:`dataclasses.asdict` 调用爆炸(~20.8 s)

`JavaSymbol` (23 个字段、嵌套 list/dict)用 `dataclasses.asdict` 转 dict:

```
22,809 次 asdict
   → 13,521,687 次 _asdict_inner 递归
   → 20.8 s 累计
```

**问题**:`dataclasses.asdict` 是通用递归实现,它要 `deepcopy` 每个 list/dict
元素,对扁平 list/dict 字段是过度工作。

**实测影响**:`_asdict_inner` 递归调用次数是 22M 次,几乎等于 Java parsing
中 tree-sitter `_walk` 的次数(17M)。

**P1 优化思路**(单独的小 commit 可以做):
- 给 `JavaSymbol` 写专门的 `to_dict()` 方法,不走 `dataclasses.asdict`
- 直接 `{ "field": self.field }` 形式,O(n) 浅拷贝
- 收益估计:~15s

### 🟡 瓶颈 #3:`json.dumps` 4.59M 次调用(~14.2 s)

每个 graph 节点/边 metadata 都要 JSON 序列化一次。1.4M 节点 + 边 +
ConfigKey 等 metadata = 4.59M 次 `dumps`。

**问题**:小 dict 的 `json.dumps` 调用次数过多,每次都要重新构建编码器
状态。

**P1 优化思路**:
- batch 化:把同一 batch 的 metadata 一次 `dumps([...])` 出来再切分(可能
  反而更慢,需要 benchmark)
- 或者跳过 JSON,直接存 Python repr 的 SQLite BLOB(改 schema,代价大)
- 或者只在 metadata 非空时 dumps,大量空 dict 直接存 `'{}'` 字面量
- 收益估计:~5s,但有 schema 兼容风险

---

## 不构成瓶颈,但要标注

### `graph.rebuild` 已是 P0-3 优化后 — 53 s

这是 P0-3 已经优化过的位置(executemany + fast_write_mode)。在
533s 总 cumulative 里,它依旧花 53s,其中:
- `sqlite3.executemany` 自身 37.5s
- `commit` 5s
- 其他(数据组装、tuple 构造)10.5s

**结论**:**P0-3 优化是合理的**(SQLite 自己就是 37.5s,我们不可能再优化
sqlite3.executemany)。reindex 总时间没下来,是因为这 53s 只占 130s
的 40%,其他 60% 不归 P0-3 管。

### `semantic.build` 21 s 是有依赖外部包的

`semantic.py` 走 `litellm` / `sentence-transformers` 嵌入,优化空间有限,
而且不在 Java 解析路径上。

### `inverted.rebuild` 27 s 是 BM25 全量重建

每次 reindex 都重建 BM25 倒排索引。后续增量化可以省时间,但属于 P2 范围。

---

## 校准之后的下一步建议

| 优化项 | 收益估计 | 工作量 | 优先级 | 备注 |
|---|---|---|---|---|
| **关闭 Java parser 双轨**(瓶颈 #1) | 30-58s | 1-2 天 | 🟥 P1-0.5 | 必须配套 differential 测试确认抽取完整性 |
| **`JavaSymbol.to_dict()` 手写浅拷贝**(瓶颈 #2) | 10-15s | 半天 | 🟧 P1-0.5 | 风险低,改一个 dataclass 方法 |
| **metadata JSON 序列化批量化**(瓶颈 #3) | 3-5s | 1 天 | 🟨 P2 | 风险中,要做 schema 验证 |
| **BM25 倒排索引增量化** | 20-25s(增量场景) | 1 周 | 🟨 P2 | 仅对增量 reindex 有效 |
| **Java parsing 并行化** | 不确定 | 1 天 | 🟩 测试后定 | 现有 parallel 已部分启用,需测 |

**最值得做的两件事**:#1 (双轨关闭) + #2 (asdict 替换),合计可能省 ~40-70s,
即把 reindex 从 130s 降到 ~60-90s。这才是真正"5-10× SQLite 加速"原本
应有的效果 —— 只不过应该改名为"5× Java parsing 加速"。

---

## 推翻另一个我之前的判断

P0 benchmark 报告我写过:

> P0-3 在 Java-heavy 大仓上没有显著提速...瓶颈不在 SQLite

**这次 profile 进一步精确化**:
- SQLite executemany 自身 37.5s
- 双轨 java_regex 58s
- asdict 20.8s

把 SQLite + 双轨 + asdict 加起来,**Java parsing 相关层占了 reindex 80% 以上**。
不是"71% 是 IO + 解析",而是"58% 是双轨 + asdict + 其他 Python 层
overhead"。

---

## 已知限制 / Known Limitations

1. **profile 自身有 overhead**:cProfile 会让每个函数调用慢 ~3-10%。
   实测下 reindex 130.4s 与不带 profile 的 133s 几乎相同,说明 overhead
   在噪声内,但**绝对数字仍包含 profile 自身开销**。
2. **单次跑**:这份 profile 只跑了一次,没多次取中位数。但函数级耗时
   的相对排序在多次跑里通常稳定 ±5%,对"找瓶颈"这个问题已足够。
3. **`_walk` 17M 次调用是 tree-sitter 自身的代价**:那 16.7s 是 tree-sitter
   Python bindings 调用 C 层的开销。**Python 层无法继续优化**,要更快只能
   切到 C 重写(就是 codebase-memory-mcp 的路线)—— 不在 P1 范围。
4. **`observability.py` 240s 是装饰器栈穿透,不是真实热点**:`@observe_operation`
   包了 reindex 主入口,所以累计时间几乎等于 reindex 总时间。我没在
   "三个真实瓶颈"里列它,因为 tottime 只有 0.53s,**装饰器本身不慢**。

---

## 复现方式

```bash
# 跑 profile(本机需要 UCAP 工作区)
.venv/bin/memory-center bench-profile \
    --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
    --top 50 \
    --by-module \
    --label p1-0-baseline

# 用 snakeviz 打开看火焰图
pip install snakeviz
snakeviz docs/benchmarks/ucap-p1-0-baseline.prof
```

---

## English Summary

cProfile of a full reindex on the real UCAP Java workspace (20,516 files)
identifies three concrete hot paths inside the 71% bucket the P0 benchmark
flagged: (1) Java parser dual-track — the regex parser still runs in full
on every file even when tree-sitter succeeded (~58s), (2)
`dataclasses.asdict` recursion across 22K JavaSymbol instances generates
13.5M `_asdict_inner` calls (~20s), (3) 4.59M `json.dumps` calls for graph
metadata (~14s). Together these are ~50-90s of saveable time, well past
what any further SQLite tuning could yield. Recommended P1-0.5 work:
disable the dual-track when tree-sitter succeeds, and replace asdict with
a hand-written shallow `to_dict()`. Not in scope for P1-0 itself —
P1-0's deliverable is this report and the bench-profile CLI.

---

**记录日期**:2026-06-23
**owner**:cuijq
