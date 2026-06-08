# Unified Backend Read Paths / 统一后端读取路径

## 1. Purpose / 目的

本文档是 F-01 Unified Backend 主读路径盘点结果。它定义当前各类数据的事实源、主读路径、fallback、读取频率和后续迁移边界。

This document records the F-01 read-path inventory. It defines the current source of truth, preferred read path, fallback, read frequency, and migration boundary for each data category.

当前结论：

- `memory.db` 是 memory/index 数据的 SQLite 镜像和高频查询后端，不是唯一事实源。
- `graph.db` 是派生知识图谱的主查询后端，不是 `memory.db` 的替代名称。
- JSON、JSONL、Markdown、YAML 和源码仍承担可读、可追踪或配置事实源职责。
- 迁移高频读取前，必须先解决镜像不完整、旧镜像优先和 fallback 不可观测问题。

## 2. Storage Roles / 存储角色

| 存储 | 当前角色 | 是否唯一事实源 |
|---|---|---|
| `workspace.yaml`、rules/config YAML | 工作区和规则配置事实源 | 是 |
| 业务源码与配置文件 | 索引与上下文提取的原始事实源 | 是 |
| `.memory-center/index/*.json` | 可读的确定性索引落盘；写入时镜像到 `memory.db.index_mirror` | 否，但当前是镜像恢复的重要事实来源 |
| `.memory-center/memory/*.jsonl` | 会话、case、receipt、benchmark 等追加式记录的可读落盘 | 否，但当前是镜像恢复的重要事实来源 |
| `.memory-center/artifacts/**/*.md` | task-space、计划、设计、变更记录等人类可读工件 | 是 |
| `.memory-center/memory/refs/**/*.json` | 大 payload 和证据 ref 的可读落盘 | 当前读取事实源 |
| `.memory-center/memory/memory.db` | JSON/JSONL/ref 镜像、高频过滤与聚合查询 | 否 |
| `.memory-center/graph/graph.db` | 派生 graph、关系查询、部分 retrieval/reasoning 数据 | 对派生图查询是主读后端；原始事实仍来自源码和索引 |

## 3. Read Path Matrix / 读取路径矩阵

| 数据类别 | 典型内容 | 频率 | 当前主读 | Fallback / 恢复路径 | 主要调用方 |
|---|---|---:|---|---|---|
| 确定性索引 JSON | file、symbol、API、Feign、MQ、config、topology | 高 | `WorkspaceStore.read_json_prefer_backend()` → `memory.db.index_mirror` | `.memory-center/index/*.json` | query、workspace status/sniff/dashboard、indexer、freshness、context pack |
| 会话与协作 JSONL | session events/summaries、handoff、case、write receipts | 高 | `read_jsonl_prefer_backend()` 或 `UnifiedBackendQuery` → `memory.db.json_records` | `.memory-center/memory/*.jsonl` | timeline、resume、session、dashboard、drill-down |
| Benchmark / audit JSONL | token gain、benchmark、decision、promotion、heuristics | 中 | 多数走 `read_jsonl_prefer_backend()` | 对应 JSONL | eval、audit、verification |
| Refs | `memory/refs/**/*.json` | 中 | 普通 ref 展开直接读文件；drill-down 可查询 `memory.db.refs` | 文件读取目前没有 backend fallback | ref get、drill-down、handoff |
| Graph | nodes、edges、FTS、reasoning 数据 | 高 | `GraphStore` / `UnifiedStore(graph.db)` | 无透明文件 fallback；需要 reindex/reconcile | query、impact、domain、reasoning、hybrid retrieval |
| Artifacts Markdown | context、requirement、design、plan、change-log、summary | 中 | `WorkspaceStore.read_artifact()` / 直接文件读取 | 无 SQLite fallback；使用 archive/audit 保持可追踪 | task-space、sync、resume、audit |
| Workspace / rules / registry | workspace YAML、rules、registry JSON | 低到中 | 直接文件读取 | 无 SQLite fallback | config、rules、group、runtime |
| 业务源码 | Java/Python/配置等 live files | 按需，高风险任务中高频 | 直接文件读取 | 无 SQLite fallback；索引只能作为定位辅助 | indexer、context pack、audit |

## 4. Current Preferred Paths / 当前主读路径

### 4.1 高频索引读取

以下索引已广泛使用 `read_json_prefer_backend()`：

- `file-index.json`
- `service-topology.json`
- `mq-index.json`
- `feign-index.json`
- `api-index.json`
- `java-symbol-index.json`
- `config-index.json`

`memory.db.index_mirror` 当前是优先读取路径，JSON 文件是 fallback 和可读恢复来源。

### 4.2 高频 memory 读取

以下链路已经优先使用 `memory.db`：

- timeline
- recent sessions / session summary
- write receipts
- drill-down navigation
- 部分 resume、dashboard、eval、backend query

`UnifiedBackendQuery` 当前只包装 `memory.db`，主要提供 session、receipt、timeline、refs、聚合和一致性检查。

### 4.3 Graph 主读

graph 查询通过 `GraphStore` 或 `UnifiedStore(graph.db)` 完成。`graph.db` 与 `memory.db` 是两个不同职责的 SQLite 文件：

- `graph.db`：派生图和检索结构。
- `memory.db`：memory/index/ref 镜像与聚合查询。

不得把 `UnifiedStore(graph.db)` 的存在解释为所有 memory 数据已迁移到 graph 数据库。

## 5. Known Splits and Risks / 已知分叉与风险

### 5.1 旧镜像可能覆盖更新文件

`WorkspaceStore.write_json()` 和 `append_jsonl()` 先写文件，再 best-effort 写入 `memory.db`，镜像异常会被捕获并忽略。

但 `read_json_prefer_backend()` 和 `read_jsonl_prefer_backend()` 只要 backend 返回非空结果就优先使用 backend。结果是：

- 文件写入成功、镜像失败时，旧 backend 数据可能继续被读取。
- JSONL backend 只有部分记录时，文件中的较新记录可能被隐藏。
- 当前返回值没有 `source`、`fallback_reason` 或 consistency 状态，调用方无法判断数据来自哪里。

这是 F-02 迁移前必须优先解决的问题。

### 5.2 空集合与缺失镜像无法区分

`read_jsonl_prefer_backend()` 使用 `rows or file_rows`。因此 backend 中“合法空集合”和“没有镜像数据”都会触发文件 fallback，语义不可区分。

### 5.3 两套 SQLite 容易被混淆

`memory.db` 和 `graph.db` 都包含结构化读取能力，但用途不同。入口和文档必须明确传递正确路径：

- `UnifiedBackendQuery` 使用 `WorkspaceStore.memory_db_path`。
- `GraphStore` / graph-oriented `UnifiedStore` 使用 `WorkspaceStore.graph_db_path`。

### 5.4 Refs 和 artifacts 尚未统一

- refs 写入文件并镜像，但普通 ref 读取仍以文件为主。
- artifacts/Markdown 没有 SQLite 主读计划，当前应继续保持文件事实源。

## 6. Migration Policy / 后续迁移策略

F-02 及后续迁移必须遵循：

1. 保留 JSON、JSONL、Markdown 的可读落盘，不做一次性强切。
2. 每迁移一条高频读路径，先增加文件与 backend 双读一致性测试。
3. 返回或 diagnostics 中记录 `source`、`fallback_used`、`fallback_reason`、`consistency_status`。
4. backend 缺失、为空、过期、部分同步或不可用时，必须有可验证 fallback。
5. 在确认镜像完整前，不删除文件读取逻辑。
6. graph 与 memory backend 分别治理，不混用数据库路径。
7. artifacts、workspace 配置、规则和业务源码继续以文件为事实源。

## 7. Recommended F-02 Order / 建议 F-02 顺序

1. 为 `read_json_prefer_backend()` 和 `read_jsonl_prefer_backend()` 增加可观测读取结果或 diagnostics。
2. 增加“文件更新、backend 旧数据”“backend 部分 JSONL”“backend 不可用”“合法空集合”测试。
3. 收口 recent sessions、session summary、write receipts、timeline 的重复 fallback 逻辑。
4. 收口 workspace status/sniff/dashboard 的高频 index 读取，并验证镜像新鲜度。
5. 统一 refs 的主读与 fallback 语义。
6. 最后评估是否扩大 `UnifiedBackendQuery` 使用范围。

## 8. Acceptance Result / F-01 验收结果

- 已列出 JSON、JSONL、Markdown、YAML、源码、`memory.db` 和 `graph.db` 读取路径。
- 已标记高频、中低频和当前事实源。
- 已识别 query、resume、dashboard、eval、refs 和 graph 的主要口径分叉。
- 已定义主读与 fallback 策略。
- 明确 `memory.db` 不是唯一事实源。

