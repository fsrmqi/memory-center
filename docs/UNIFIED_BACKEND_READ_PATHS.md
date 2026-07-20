# Runtime Storage Read Paths / 运行时存储读取路径

## Current model / 当前模型

Memory Center uses `.memory-center/graph/graph.db` as the single runtime fact
store. It contains graph data, index metadata, memory records, refs,
assertions, retrieval structures and runtime state.

Memory Center 使用 `.memory-center/graph/graph.db` 作为唯一运行时事实库，存放图数据、索引元数据、记忆记录、refs、断言、检索结构和运行状态。

`index/*.json` and `memory/*.jsonl` are inspectable exports. They are written
alongside SQLite but never used as transparent query fallbacks. A missing or
unavailable SQLite fact store must produce a structured diagnostic or
`knowledge_state`, not a result assembled from an old export.

`index/*.json` 和 `memory/*.jsonl` 是可审查导出，会与 SQLite 同步写入，但绝不作为运行时查询的透明回退。SQLite 事实库缺失或不可用时必须返回结构化诊断或 `knowledge_state`，不能使用旧导出拼装结果。

## Read matrix / 读取矩阵

| Data / 数据 | Runtime read / 运行时读取 | File role / 文件职责 |
|---|---|---|
| Index metadata and workspace state | `WorkspaceStore.read_json_prefer_backend()` | Inspectable JSON export |
| Sessions, audit, cases, receipts, verification | `read_jsonl_prefer_backend()` or `read_jsonl_via_backend()` | Inspectable JSONL export |
| Graph, FTS, vectors, reasoning | `GraphStore` / `UnifiedStore` on `runtime_db_path` | No file query fallback |
| Assertions, aliases, governance | SQLite assertion and index tables | JSONL/JSON audit export |
| Payload refs | SQLite refs table | Inspectable JSON export |
| Markdown artifacts | Explicit file reads | Human-authored artifacts, not query fallback |
| Workspace YAML, rules, source code | Explicit file reads | External configuration and source inputs |

## Error and recovery policy / 错误与恢复策略

1. Runtime read failures return structured diagnostics; they do not read an
   export as a replacement.
2. Reindex rebuilds derived index and graph state from workspace source.
3. Explicit import or disaster-recovery tooling may consume exports, but must
   report records read, records written, validation outcome and generation.
4. Scoped queries use active service shards. Missing shards return
   `NOT_INDEXED`; stale scoped hybrid queries may perform a bounded local
   refresh before returning.

1. 运行时读取失败返回结构化诊断，不以导出文件替代。
2. `reindex` 从工作区源码重建派生索引和图状态。
3. 显式导入或灾难恢复工具可以读取导出，但必须报告读取条数、写入条数、校验结果和 generation。
4. 范围查询使用 active service shard。分片缺失返回 `NOT_INDEXED`；过期的范围 hybrid 查询可先执行有界局部刷新。
