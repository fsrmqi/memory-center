# 5.x 服务侧索引管线阶段级基线 / Service-side Index Pipeline Stage Baseline

> 目的：为「全局工作池 + 文件级并行」改造提供可复算的性能基准与验收阈值。
> 本文只回答一个问题——**当前一次完整索引的时间花在哪一段**，并给出池化后的预期区间。
> 与 `P1_0_JAVA_PARSING_PROFILE.md` 的区别：那份是 2026-06 的 **CLI 路径** profile，
> 且其列出的三大瓶颈已完成修复；本文测的是 **5.x 服务侧 `run_index` 管线**的当前代码。

---

## 测量环境

| 维度 | 值 |
|---|---|
| 被测切片 | `<private-ucap-workspace>/ucap-cloud-back`（真实项目最大单模块） |
| 切片规模 | 3,797 个可索引文件 / 3,552 个可解析文件（全为 Java）/ 14.3 MiB 源码 |
| 全工作区规模 | 20,484 个可索引文件 / 175.0 MiB 源码 |
| 机器 | Apple M3 Pro / 14 逻辑核（10 性能核）/ macOS |
| Python | 3.11.16 in `.venv`，tree-sitter 0.25.2 |
| 方式 | 直接调用管线同类函数，只读源码，不写代际、不触碰运行中服务 |
| 复现 | `.venv/bin/python tmp/baseline_stages.py`、`.venv/bin/python tmp/baseline_payload.py` |

切片与全工作区的比例系数为 **5.77×**，用于线性外推。

---

## 阶段耗时（切片）

| 阶段 | 内容 | 耗时 |
|---|---|---|
| 1 scan | 目录枚举（`source_files`，已跳过 `target/` 等） | 0.17 s |
| 2 read_only | 原生读取全部 3,797 文件 | 10.24 s |
| 3 read + sha256 | 读取并计算内容哈希 | 10.10 s |
| 4 chunking_full | 读取 + `split_text` + 哈希 → 9,459 个块 | 10.64 s |
| 5 build_code_graph | tree-sitter 逐文件解析 + 符号装配 + 关系解析 | 17.17 s |
| 6 java_second_parse | Java 专用 tree-sitter 解析（第二遍同源解析） | **42.20 s** |
| **合计** | 服务侧一遍（三遍读取 + 两遍解析） | **≈ 70.0 s** |

阶段 5 的产出：15,400 个符号、4,243 条已解析调用边、93,400 条未解析调用。

**关键分解**：单独测「只解析、不解析关系」为 16.51 s，而 `build_code_graph` 整体 17.17 s
→ **跨文件关系解析仅约 0.66 s（4%）**。即该阶段 96% 是解析本身，关系解析不是热点，
**无需并行化，留在父进程串行即可**，这显著简化了池化设计。

---

## 重复遍历账

同一份 14.3 MiB 源码在服务侧被处理如下：

| 次数 | 读取 | 哈希 | tree-sitter 解析 | 消费方 |
|---|---|---|---|---|
| 1 | ✓ | ✓ | — | `chunking`（切块与向量化输入） |
| 2 | ✓ | ✓ | ✓（通用 walker） | `build_code_graph`（通用代码图） |
| 3 | ✓ | ✓ | ✓（Java 专用 walker） | `reindex_workspace`（Spring 专用事实） |

- 源码被读 **3 次**，成本约 30.6 s（阶段 2/3/4 之和）。
- Java 文件被 tree-sitter 解析 **2 次**（阶段 5 + 阶段 6），其中阶段 6 占 42.2 s。
- 3 与 6 是**同一批字节的两次独立 AST 构建**，`language_registry` 中 `java` 在册且
  `build_code_graph` 不跳过 `.java`，故这是一条真实存在的冗余路径，
  对应改造清单中的「减少通用代码图与 Java／Spring 专用分析的重复解析」。

---

## 并行度实测（3,552 文件，串行 16.51 s）

| 模式 | 耗时 | 加速比 |
|---|---|---|
| 串行 | 16.51 s | 1.00× |
| 线程 4 | 11.74 s | 1.41× |
| 线程 8 | 21.67 s | **0.76×（劣化）** |
| 进程 2 | 9.87 s | 1.67× |
| 进程 4 | 7.20 s | 2.29× |
| 进程 8 | 6.44 s | **2.56×** |
| 进程 4（回传完整结果） | 7.07 s | 2.37× |
| 进程 8（回传完整结果） | 6.70 s | 2.50× |

所有模式的输出与串行**逐条相等**（含完整 `StructuralParseResult`）。

### 三条结论

1. **线程不可用。** tree-sitter 的 Python 绑定不释放 GIL：4 线程仅 1.41×，
   8 线程**比串行更慢**。旁证：裸 `Parser` 微基准下 4 线程等效 0.98×。
   故文件级并行**必须由进程池承载**。
2. **进程池可用且 IPC 免费。** 8 worker 达 2.56×。回传完整解析结果（13.7 MiB 总计、
   平均 4,050 B/文件）与回传计数相比，耗时差在噪声内（−0.16 s），
   因此**传输契约可直接沿用 `StructuralParseResult`**，无需另造归一化格式。
   （`StructuralParseResult` 为 frozen dataclass 组合，可 pickle。）
3. **超线性代价来自每文件工作量过小。** 单文件解析约 4.6 ms，8 worker 仅得 2.56×
   （14 核），瓶颈是文件 IO 竞争与消息往返，而非 CPU 不足。

### 附带发现：现有线程参数会起反作用

`core/indexing/parallel.py::estimate_optimal_workers` 默认返回
`min(2 × cpu_count, 32)`——本机为 28。实测 8 线程已比串行慢 24%，
该默认值在真实项目上会**主动劣化**性能。且服务侧 `reindex_workspace(..., parallel=False)`
已将其旁路，说明现状是「关掉一个会变慢的并行器」。

---

## 预期收益（增量 1：全局工作池 + 文件级并行）

可池化部分 = 阶段 5 + 阶段 6 = 58.7 s / 70.0 s = **83.9%**。

| 场景 | 切片一遍耗时 | 相对当前 |
|---|---|---|
| 当前 | ≈ 70.0 s | 1.00× |
| 两段解析入池（8 worker，2.5×） | ≈ 34.8 s | 2.01× |
| 再合并三遍读取为一遍（复用已读文本） | ≈ 25 s | 2.8× |

按 5.77× 外推，全工作区一遍由 ≈ 404 s（约 6.7 min）降至 ≈ 200 s（约 3.3 min），
合并读取后约 145 s。**以上不含向量化与逐服务开销。**

### 增量 1 验收阈值

| 项 | 阈值 |
|---|---|
| 等价性 | 同批文件的池化结果与串行结果**深度相等**，含完整 `StructuralParseResult` |
| 解析阶段加速 | 3,552 文件 ≥ 2.0×（当前实测 2.5×） |
| 端到端切片一遍 | 70.0 s → **≤ 40 s** |
| 熔断 | 不得回退为串行；不得因池不可用而静默丢文件 |
| 故障隔离 | 单文件解析失败进 coverage ledger，其余文件照常发布 |
| 既有合同 | 取消、原子发布、MCP tool schema、`StructuralParseResult` 形状均不变 |
| 回归测试 | `tests/service/test_multilanguage.py`、`test_index_limits.py`、`test_job_progress.py`、`test_large_index.py` 全绿 |

---

## 已知限制

1. **阶段 6 是下界。** 它只测了 `TreeSitterJavaParser.parse` 本身；真实
   `reindex_workspace` 每服务还含目录遍历、`JavaSymbol` 构造、注解/Feign/MQ 抽取、
   契约快照、JSON 与图存储写入，故逐服务专用分析的实际占比**高于** 60%。
2. **线性外推未经整仓实测。** 各模块单文件成本存在差异，5.77× 为估算。
3. **未测向量化阶段。** 本次运行未配置嵌入模型；`Embedder` 每次调用新建
   `httpx.Client`、批 16、逐批一次 POST 的串行行为属代码审查结论，尚无墙钟数据。
4. **单次运行，未取中位数。** 同机重复运行波动预计在 ±10%，对「定瓶颈与阈值」足够。
5. 未测多项目并发叠加场景；全局池与 `max_projects` 的预算共享效果需在增量 1 实现后复测。

---

## English Summary

Stage-level baseline for the 5.x service-side index pipeline (`run_index`), measured on the
largest real module (`<private-ucap-workspace>/ucap-cloud-back`, 3,552 parseable Java files,
14.3 MiB source; full workspace 20,484 files / 175.0 MiB). One service-side pass costs
**≈ 70 s**: three source reads (~30.6 s) plus two independent tree-sitter parses of the same
bytes — the generic code-graph walk (17.2 s, of which relation resolution is only 0.66 s) and
the Java-specific walk (**42.2 s**, a lower bound). Pool experiments show threads are
unusable (8 threads are 24% *slower* than serial; tree-sitter does not release the GIL) while
a process pool reaches **2.56×** at 8 workers, with full `StructuralParseResult` round-trips
costing nothing measurable (13.7 MiB total). Increment 1 therefore targets pooling both parse
stages: expected ≈ 2.0× on the slice (70 s → ≤ 40 s), or 2.8× if the three read passes are
also collapsed. `estimate_optimal_workers`' default of `min(2 × cpu, 32)` is shown to be
actively harmful on real projects and must not be reused by the new pool.

---

**记录日期**：2026-10-10
