# Graph.db 只读空间诊断报告 / Read-Only Storage Space Diagnostic

> 日期：2026-08-28 · 工作区：真实多服务 Java 工作区 · **只读诊断，未执行任何清理**
> 范围：`graph.db`（4.1GB）+ `generations/`（5.8GB）空间构成与可回收评估

## 1. 总体空间构成

| 区域 | 体积 | 说明 |
|---|---|---|
| `generations/` 服务分片 | **5.76 GB** | 3 个 generation × 1.9GB（72 个服务分片/每个，物理复制） |
| `graph.db`（SQLite） | 4.07 GB | 节点/边/FTS/倒排/ANN + index_mirror + freelist |
| **合计** | **~9.8 GB** | — |

## 2. graph.db 内部构成（dbstat，只读）

| 对象 | 体积 | 必要性 |
|---|---|---|
| edges + 索引 | ~1.5 GB | 必要（109.6 万边） |
| **index_mirror（JSON 镜像）** | **614.6 MB** | **部分可优化** |
| FTS（node_search_data/content） | ~520 MB | 必要 |
| 倒排 inv_postings + 索引 | ~500 MB | 必要 |
| nodes | 147 MB | 必要 |
| **freelist（空闲页）** | **343 MB** | **可安全回收（VACUUM）** |
| ANN（vec_*） | ~50 MB | 必要 |

### index_mirror 明细（614.6MB）
- **java-ir-index.json：341.8 MB**（IR 候选 67.8 万，additive 诊断用）
- **java-symbol-index.json：247.2 MB**（必要，符号索引）
- 其他：file-index 11.5MB、contract 6.9MB 等

**关键浪费**：`java-ir-index.json` **双重占用**——既在 SQLite index_mirror（341.8MB）又写 `index/java-ir-index.json` 文件（341.8MB）≈ **684MB**。IR 索引是 diff-gate 评测的 additive 诊断产物，对运行时查询非必需。

## 3. generation 分片（5.76GB）

| generation | 角色 | 分片体积 |
|---|---|---|
| gen-…60d7bead | **ACTIVE** | 1.9 GB（必要保留） |
| gen-…8bab00ab | **PREVIOUS** | 1.9 GB（必要保留，回滚点） |
| **gen-perf-test** | **孤立/测试污染** | **1.9 GB（可安全回收）** |

- 每个 generation 的 72 个服务分片**物理复制**（无软链）→ **分片继承（reuse）虽存在但未减少物理体积**，是"服务分片导出压缩/继承优化"的候选
- **gen-perf-test** 是 profile 测试创建的孤立 generation，**未在 shard-manifest 注册**（generation-gc dry-run 报 0 候选因它不被识别），但物理存在 1.9GB

## 4. dry-run 结果（全部只读）

| 工具 | 结果 |
|---|---|
| `generation-gc --dry-run` | 0 候选（active/previous 保留，gen-perf-test 未注册故不被 GC 识别） |
| `semantic-index-compact --dry-run` | 无候选（语义状态已精简） |
| `storage-vacuum --dry-run` | 未执行（需显式授权） |

## 5. 可回收对象汇总（预计）

| 对象 | 预计回收 | 是否影响 active/previous |
|---|---|---|
| **孤立 gen-perf-test** | **1.9 GB** | 否（非 active/previous，未注册） |
| **IR 双重占用**（SQLite 或文件去重） | **~342 MB** | 否（IR 是 additive 诊断） |
| **SQLite freelist**（VACUUM） | **343 MB** | 否（空闲页） |
| **合计可安全回收** | **~2.5 GB** | — |

## 6. 建议（不执行）

1. **删除孤立 gen-perf-test**（1.9GB）：需确认后手动删目录 + 移除其 manifest 引用（不属 generation-gc 管理范围）；
2. **IR 双重去重**（~342MB）：`java-ir-index.json` 改为仅 SQLite 权威（加入 RUNTIME_ONLY_INDEXES）或仅文件（从 index_mirror 移除），消除 684MB 双重占用的一半；
3. **SQLite VACUUM**（343MB freelist）：在以上清理后执行 `storage-vacuum --apply` 回收空闲页；
4. **服务分片继承优化**（长期，~1.9GB/代）：将未变更服务的分片改为软链/hardlink 继承而非物理复制，需用户授权评估；
5. **generation_publish 压缩**（上一任务 known limit）：服务级 payload 缩小，属更大架构优化。

## 7. 明确不执行

- 未运行任何 `--apply`（generation-gc / semantic-compact / storage-vacuum 均只读审查）；
- 未删除 gen-perf-test（尽管可安全回收，需用户显式授权）；
- 未做 IR 去重/VACUUM（属代码改动或破坏性操作，需授权）。

> 结论：4.1GB 主要来自**服务分片物理复制**（generations/ 5.8GB）与**必要索引**（edges/FTS/倒排）；**可安全回收约 2.5GB**（孤立 gen-perf-test 1.9GB + IR 双重 342MB + freelist 343MB），不影响 active/previous generation。
