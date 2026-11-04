# P0 真实场景 Benchmark / Real-world P0 Benchmark

> 这是对 P0 阶段(service kind registry / 多语言 parser registry /
> SQLite PRAGMA + executemany + 并发)在**真实 Java 微服务仓库**上的
> 端到端 reindex 性能测量。
>
> Honest report — 不是"P0 一切完美"的庆功稿,而是一份用真数据校准设计假设的
> 复盘。该 benchmark 推翻了演进计划文档里此前关于"reindex 总耗时下降 5~10×"
> 的预测,详见结论部分。

---

## 测量环境

| 维度 | 值 |
|---|---|
| 工作区 | `<private-ucap-workspace>` (UCAP 内部微服务平台,真实路径已脱敏) |
| 规模 | 36 个 service,**20,516 个 Java 文件**,27 GB |
| 机器 | Apple M3 Pro / macOS Darwin 25.5.0 |
| Python | 3.11 in `.venv` |
| baseline commit | `79865c1` (P0 前最后一个 commit,P0-1 之前) |
| after commit | `e26cd38` (P0 全部完成之后) |
| 命令 | `reindex_workspace(config, store)` 直接调用 |
| 测量脚本 | `scripts/bench_p0_ucap.py` |
| 每次 reindex 都先清掉 `index/` `graph/` `semantic/` `evaluation/` 确保冷启动 |

---

## 原始数据

每个 label 下报 3 次:1 次 cold + 2 次 warm。

### Baseline (`79865c1`,P0 前)

| run | elapsed |
|---|---|
| cold | 124.4 s |
| warm 1 | 133.5 s |
| warm 2 | 133.6 s |
| **median** | **133.5 s** |

### After-P0 (`e26cd38`,P0 完成后)

| run | elapsed |
|---|---|
| cold | 133.3 s |
| warm 1 | 133.8 s |
| warm 2 | 129.0 s |
| **median** | **133.3 s** |

### 分阶段 profile(各跑一次,无 warmup)

| 阶段 | baseline | after-P0 | 备注 |
|---|---|---|---|
| **total** | 130.6 s | 134.8 s | 总耗时几乎相同 |
| `graph.rebuild` | 24.3 s | 24.0 s | P0-3 优化目标 |
| `graph.rebuild_search` | 2.8 s | 2.9 s | P0-3 优化目标 |
| `semantic.build` | 11.3 s | 11.4 s | 与 P0 无关,共参考 |
| 其他(Java 解析 + IO) | ~92.2 s | ~96.5 s | **真实 dominant cost** |
| graph.db 大小 | 2.0 GB | 2.0 GB | 持平 |
| 节点总数 | 328,502 | 333,747 | +5,245(multilang 新增) |
| 边总数 | 1,420,744 | 1,432,158 | +11,414(multilang 新增) |

### PRAGMA(P0-3 是否真生效)

| 项 | baseline (裸 sqlite3 默认值) | after-P0 (实际生效) |
|---|---|---|
| `journal_mode` | (会变 WAL 因为 DB header 持久化) | `WAL` |
| `synchronous` | `FULL` (2) | `NORMAL` |
| `cache_size` | -2,000 KB ≈ 2 MB | **-200,000 KB = 200 MB** |
| `temp_store` | `DEFAULT` (0) → 落盘 | `MEMORY` |
| `mmap_size` | 0 | **268,435,456 = 256 MB** |
| `foreign_keys` | OFF | ON |

P0-3 PRAGMA 改造**配置层面 100% 生效**。

---

## 关键发现

### 1. P0-3 在 Java-dominant 大仓上没有显著提速

**`graph.rebuild` 这一段在总耗时里只占 18.7%**(24.3 s / 130.6 s)。
P0-3 的 executemany / fast_write_mode / cache_size 提升只能影响这 18.7%,
而且实测前后差异在噪声范围内(24.3 s vs 24.0 s)。

剩余 ~71% 的耗时是 **Java 解析 + 文件 IO + Python 数据拼装**,P0 完全
没动这一层 —— 所以总耗时没变是符合算术的,不是 bug。

### 2. P0-2 multilang pass 略增了 ~4 s 的开销

P0-2 给非 Java 文件加了一遍结构扫描。UCAP 几乎都是 Java(20,516 / ~21,000),
所以 multilang pass 实际处理的文件极少,但**单次 reindex 仍要起 parser
caches、收集任务、emit graph elements 这一套**,产生了几秒钟的固定开销。

后果:**P0-2 在纯 Java 仓库上是净负担**。
不严重(<5 s / 总 134 s),但**应在多语言仓库上才能回本**。

### 3. P0-3 修了一个真实的隐藏 bug,只是收益在别处

P0 前 `GraphStore.connect()` 和 `MemoryBackendStore.connect()` **完全没
调用过 PRAGMA**(裸 `sqlite3.connect`)。

- Baseline 跑出来 PRAGMA 仍显示 WAL,是因为 `_init_schema` 走过一次
  `executescript` 触发了 SQLite 内部 WAL header 写入;但 cache / mmap /
  temp_store / foreign_keys 全部是默认值。
- After-P0 现在 cache=200MB / mmap=256MB / temp_store=MEMORY 真生效。

收益**没出现在 reindex 总耗时上**,但 query / sniff / 大量小读会有改善
(本次未单独测,留作 future work)。

### 4. P0-1 / P0-2 的能力收益是结构性的,不在 wall-clock 里

| 项 | 真实收益 |
|---|---|
| P0-1 | ✅ 11 种 service kind 注册表,对 C 项目 `init --dry-run` 不再硬塞 3 个 Spring 占位 service |
| P0-2 | ✅ 7 语言可识别,5 语言深 walker,Python 微服务 reindex 实际产出 Module/Class/Function 节点 |
| P0-3 | ⚠️ PRAGMA 修了 + 代码统一了,但**在 Java-only 大仓 reindex 上没有 wall-clock 收益** |

---

## 推翻的预测

旧版演进计划（已删除）之前 P0-3 段落里写过:

> 对中等(10w 文件)及大型(75K 文件)Java/多语言仓,reindex 总耗时下降
> 5~10×。

**这个预测在 UCAP(20,516 Java 文件)上不成立 —— 实测变化 0%。**

之所以预测错,是因为我假设 SQLite 是瓶颈,但**对 Java tree-sitter
解析这种 CPU + 字节流密集型工作负载,SQLite 写库占比只有 18.7%**。
要把"5~10×"翻出来,必须先优化解析与 IO 阶段。P1-0 后续已完成
Java 解析阶段 profile,但具体性能修复尚未全部落地。

演进计划文档已同步修正,见下个 commit。

---

## 后续行动建议

### 已完成:P1-0 Java 解析热点 profile

原先这里建议在 P1-1 (Java 调用解析器) 之前,先做一次 **Java 解析阶段的
真实热点 profile**。该诊断项已完成,详见
[P1_0_JAVA_PARSING_PROFILE.md](./P1_0_JAVA_PARSING_PROFILE.md)。

当前状态:profile 已定位三个主要热点,但不等于热点已经修复。截至
2026-06-24,Java parser 双轨执行、`dataclasses.asdict` 递归开销、
graph metadata 高频 `json.dumps` 仍在当前代码路径中,需要后续独立修复。

### 不该回滚 P0-3 的理由

虽然 reindex wall-clock 没改善:
- WAL/cache/mmap 这套配置**对未来 query 性能有用**(没测,但默认假设成立)
- 代码层面把 3 处分散 PRAGMA 收口到 `pragmas.py` 一处,长期维护性提升
- `fast_write_mode` context 为后续 batch 写操作留好了开关

### 重新评估 P0-2 在 Java-only 仓上的开销

multilang pass 给纯 Java 仓库加了几秒固定成本。可以加一个 fast-path:
当 workspace 里所有 service 的 `resolved_language()` 都是 `java` 时,
完全跳过 multilang collection。这是后续小优化,不紧迫。

---

## 复现方式

```bash
# baseline
git checkout 79865c1
.venv/bin/python scripts/bench_p0_ucap.py \
    --workspace <private-ucap-workspace>/.memory-center/workspace.yaml \
    --runs 2 \
    --label baseline \
    --out /tmp/baseline.json

# after-p0
git checkout dev
.venv/bin/python scripts/bench_p0_ucap.py \
    --workspace <private-ucap-workspace>/.memory-center/workspace.yaml \
    --runs 2 \
    --label after-p0 \
    --out /tmp/after.json
```

---

## 已知限制 / Known Limitations

这份 benchmark **不是**严格意义上的科学测量,它只支撑"P0-3 在 Java-heavy
大仓上没观测到 wall-clock 收益"这一个结论。下面列出本次测量做不到的事,
其中 P1-0 Java parsing profile 已完成,其余仍是后续需要补的 future work。

1. **样本量偏小**:每个分支只有 3 次跑(1 cold + 2 warm)。差异在 5 s
   以内的结论统计意义有限,但**百分之几的差距对 P0-3 的"5-10x"预测
   而言已经足够证伪**,所以本次没有继续加样本。

2. **未单独 profile P0-2 multilang pass 的固定开销**:`+~4 s` 的判断
   是从 total 推断出来的,**没有单独跑一次"只有 P0-1+P0-3,没有 P0-2"
   的对照**。"P0-2 在纯 Java 仓库上是净负担"这个结论需要补一次精确
   profile 才能严格成立。如果将来想做,checkout 到 `fd45202` (P0-3 完成、
   P0-2 未做)再跑一次 benchmark 即可。

3. **没测 query 性能**:P0-3 的 PRAGMA 调优(WAL / 200MB cache / mmap)
   理论上对 query 友好,但 benchmark 只覆盖 reindex 这一条路径。
   `mc_lookup` / `callers` / `callees` / `search-code` 这些读路径上
   PRAGMA 的真实收益**未测量**,只是默认假设它们有用。
   后续 P0-3 query benchmark 计划:跑 100 次 `mc_lookup` / `callers`
   /`callees` 取中位数,baseline vs after-P0 对比。

4. **baseline 选的是 `79865c1`,不是分阶段 commit**:这意味着本次 benchmark
   只能说"P0 三步加在一起的净效果",**无法区分 P0-2 单独贡献 / P0-3
   单独贡献**。如果将来想分阶段归因,需要 checkout 到 `08b3565`(P0-1
   后)和 `fd45202`(P0-3 后)各跑一次。

5. **`scripts/bench_p0_ucap.py` 不在 pytest 覆盖里**:它是 one-shot
   benchmark 工具,没有单元测试。如果将来有人改坏了它,只会在下次跑
   benchmark 时才发现。这是有意的 trade-off — 给一个一次性脚本配测试
   是过度工程,但需要意识到这个盲区。

6. **UCAP 工作区是内部闭源仓库**:外部读者无法复现这次测量。文档中的
   `<private-ucap-workspace>` 是脱敏占位符,真实路径不提交。若需要给社区
   一份可复现的 benchmark,需要用 `examples/spring-cloud-demo` 之类的
   公开 fixture 做一份配套 — 但小 fixture 上很难看到 SQLite 写库占比
   差异(因为 graph.rebuild 在小项目里只有几十毫秒,被 Python overhead
   完全淹没),所以这种公开 benchmark 的诊断价值有限。

---

## English Summary

P0 was benchmarked on a real internal Java microservice workspace
(36 services, 20,516 Java files, 27 GB). reindex wall-clock did **not**
improve meaningfully — median total time before P0 was 133.5 s vs 133.3 s
after. Profiling shows `graph.rebuild` (the part P0-3 targeted) only
accounts for 18.7% of total time; Java parsing and IO dominate at ~71%.
P0-3 did fix a real hidden bug (GraphStore/MemoryBackendStore opened
SQLite without applying any PRAGMA), but the win does not surface in
end-to-end reindex on this workload. The "5–10× reduction" prediction
in the original evolution plan is now corrected. The Java parsing profile
recommended here has since been completed in
`P1_0_JAVA_PARSING_PROFILE.md`; the identified parser/asdict/json metadata
hot-path fixes are still pending.

---

**记录日期**:2026-06-23
**owner**:cuijq
