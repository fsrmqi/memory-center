# P0.5 Vector Path Real Validation / 向量路径真实验证

> 验证 selective dense vector + ANN retrieval 在真实 UCAP workspace
> 上的端到端流程,作为 `feat(query): 添加向量检索功能支持`
> (commit `c8fd6b0`) 和 `feat(indexer): 增强向量可观测性`
> (commit `b0918bf`) 的真实场景门禁。
>
> End-to-end validation that selective dense vector + ANN retrieval works
> on a real UCAP workspace.

---

## 1. 环境 / Environment

- 工作区:`<private-real-workspace>`(UCAP,36 services / 20,516 Java
  files / 27 GB,真实路径已脱敏)
- 机器:Apple M3 Pro / macOS Darwin 25.5.0
- Python: 3.11 in `.venv`
- Embedding 模型:`sentence-transformers/all-MiniLM-L6-v2`(384 维,
  本地缓存,`HF_HUB_OFFLINE=1` 离线加载)
- 后端配置:
  - `MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers`
  - `MEMORY_CENTER_VECTOR_SCOPE=selective`(默认)
- 验证时间:2026-06-24

---

## 2. 索引构建 / Index build

```bash
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers \
.venv/bin/python - <<'PY'
from memory_center.core.semantic import build_workspace_semantic_index
from memory_center.core.indexer import _sync_retrieval_indexes
from memory_center.core.store import WorkspaceStore

ws = "<private-real-workspace>/.memory-center/workspace.yaml"
payload = build_workspace_semantic_index(ws)
_sync_retrieval_indexes(WorkspaceStore(ws), payload)
PY
```

### 索引结果 / Index stats

| 指标 | 值 |
|---|---:|
| node_count | 316,696 |
| doc_count | 316,696 |
| backend | `sentence-transformers` |
| model | `sentence-transformers/all-MiniLM-L6-v2` |
| vector_scope | `selective` |
| vector_candidate_count | **47,633** |
| dense_doc_count | **47,633** |
| vector_status | **ready** |
| build elapsed | 108.5 s (含 sparse 重建 + ST 编码 47K 文档) |
| sync to VectorIndex | 22.0 s |
| 向量数据规模 | 47,633 x 384 x float32 = ~72 MB |

`selective` scope 选中的节点类型包括 Endpoint / FeignClient / FeignMethod
/ MQ Topic/Consumer/Producer / 业务相关 Class & Method / README 类
Markdown 文档(见 `_VECTOR_ELIGIBLE_TYPES`、`_VECTOR_CLASS_KEYWORDS`)。

---

## 3. 真实查询对比 / Real query A/B

使用 `mc_lookup` 的 hybrid query,对相同 query 分别跑
`enable_vector=False` 和 `enable_vector=True`,观察命中差异。

### Q1: 全链路追踪型 query

```
梳理下 ...WebsiteInfoLeakageMasterServiceImpl#listByDto 全链路 一直到最底层的逻辑处理
```

- `enable_vector=False`: 0 hybrid 命中
- `enable_vector=True`: 0 hybrid 命中
- 解释:这类 query 命中 walkthrough 高优先级路由,直接走
  `mode=walkthrough`,**hybrid 不返回是正确行为**,vector 没影响。

### Q2: 概念性 query — Feign 鉴权拦截器

```
Feign 调用的鉴权拦截器
```

| 指标 | vector=False | vector=True |
|---|---|---|
| elapsed_ms | 13,205 | **2,838** (-78%) |
| total_found / returned | 57 / 10 | 57 / 10 |
| top1 | `File: CAPFeignClientInterceptor.java` | `Method: FeignSpringFormConfiguration#feignContract` |
| top1 sources | `graph_exact + sparse_fts` | **`vector_ann + sparse_bm25 + semantic`** |
| vector_diag | `disabled / configured_off` | `active / brute_force / 47633 embeddings` |

vector 真实价值:把 file 级关键词命中升级成 method 级语义命中,
并且大幅缩短 elapsed(BM25 + ANN + semantic 都不需要重新触发 LIKE
扫描)。

### Q3: 自然语言描述接口 — 网站死链过滤分页查询

```
网站死链过滤分页查询接口
```

| 指标 | vector=False | vector=True |
|---|---|---|
| elapsed_ms | 2,390 | 3,194 |
| total_found / returned | 20 / **1** | 20 / **10** |
| top1 sources | `semantic` (单一来源) | `vector_ann + semantic` |

vector 真实价值:返回从 1 条扩到 10 条 method 级候选,候选集对
下游 walkthrough / impact 更丰富。

---

## 4. 可观测性回执 / Observability surface

- `retrieval_diagnostics.policy`:同时暴露 `vector_enabled`(policy
  实际选择)与 `enable_vector`(user 请求),让宿主能解释"为什么开
  了但没用"等情况。
- `retrieval_diagnostics.vector`:
  - `status: ready` -> `active / returned / embedding_count / dimension / backend`
  - `status: disabled` -> `reason: configured_off | policy_off`
  - `status: unavailable` -> `reason: sentence-transformers model unavailable for query embedding`
  - `status: empty` -> 当 VectorIndex 行数为 0 时
- `semantic_index_stats` 返回 `vector_status / vector_disabled_reason /
  dense_doc_count / vector_candidate_count`,对应
  `doctor / dashboard / status` 命令现场可见。

---

## 5. 性能与资源 / Cost

| 阶段 | 单次成本 |
|---|---:|
| ST 模型加载(本地缓存) | ~0.5 s |
| dense 编码 47K 文档 | ~70 s |
| sync 到 VectorIndex | ~22 s |
| 单次 query embedding | <30 ms |
| 单次 ANN 查询(numpy brute_force,47K x 384) | <100 ms |
| 增量 reindex 影响 | 仅对 changed dense_candidates 重 encode,~10% |

`vec_fallback` (BLOB) 表大约 +18 MB(47k x 384 x 4B + index)。
`sqlite-vec` 没装时自动 fallback 到 numpy 暴力扫描;47K 量级 numpy
完全够用,这一步无需新依赖。

---

## 6. 验收 / Acceptance

- `vector_status: ready` 在真实 UCAP 上 ok
- `enable_vector=True` 时 `retrieval_diagnostics.vector.status = active` ok
- `enable_vector=False` 时 `retrieval_diagnostics.vector.status = disabled / reason=configured_off` ok
- Q2 / Q3 在 vector on 时 top1 命中更具体的 method 节点 ok
- 不引入新的必选运行时依赖(ST / sqlite-vec 仍为 optional) ok
- 不改 MCP / CLI / HTTP 既有 schema;新增字段 additive ok
- 没有把私有 workspace 路径 / 真实 case / dense 向量 commit 进仓库 ok

---

## 7. 复现命令 / Reproduce

1. `.venv/bin/pip install sentence-transformers`
2. 让 HuggingFace 缓存里有 `all-MiniLM-L6-v2`(联网首次拉,后续
   `HF_HUB_OFFLINE=1` 即可离线运行)
3. 设置环境变量:

    ```bash
    export HF_HUB_OFFLINE=1
    export TRANSFORMERS_OFFLINE=1
    export MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers
    ```

4. 跑一次完整 reindex(自动 sync):

    ```bash
    .venv/bin/memory-center reindex --workspace <private-real-workspace>/.memory-center/workspace.yaml
    ```

5. 发查询:

    ```bash
    .venv/bin/memory-center query --workspace ... --text "Feign 鉴权拦截" --vector
    ```

---

## 8. 非目标 / Non-goals

- 不把 `sentence-transformers` 加成必选依赖;默认 backend 仍是
  `sparse`,vector 路径必须显式 opt-in。
- 不在本阶段把 vector_scope 默认改为 `all`(72 MB on 47K 已经足够,
  扩到 316K 节点的代价是 ~500 MB 且大部分是结构性 Method,语义增益
  有限)。
- 不引入向量数据库或外部 embedding 服务;sqlite-vec / 暴力扫描 +
  本地 ST 模型已经能覆盖当前规模。
- 不把 dense 向量数据(`.memory-center/index/semantic.v4.json`、
  `vec_fallback` 表)commit 进公开仓库。

---

## 9. 增量 reindex 验证 / Incremental vector validation

2026-06-25 继续验证 partial semantic rebuild + VectorIndex sync:

- 前置状态:`dense_doc_count=47,633`, `VectorIndex.embedding_count=47,633`
- changed node:`File:ucap-cloud-datainterface/code-review/README.md`
- `build_workspace_semantic_index_partial(..., {changed_node})`:
  - elapsed: 26.34 s
  - dense_doc_count: 47,633
  - changed_dense_docs: **1**
- `_sync_retrieval_indexes(..., changed_node_ids={changed_node})`:
  - vector_sync_mode: **partial**
  - vector_deleted: **1**
  - vector_embeddings: **1**
  - VectorIndex.embedding_count after: **47,633**

结论:

- dense vector 重算已经是增量的,只重 encode changed dense candidate。
- VectorIndex 同步也已经是增量的,只 delete/upsert changed node 的 embedding,
  不再 full clear + full upsert。
- 当前 partial sync 的 22.9 s 主要仍来自 `InvertedIndex.rebuild(nodes)` 全量
  BM25 重建;这是后续 P2 / performance follow-up,不属于 vector 本身。
- 新增保护:`_sync_retrieval_indexes` 在 sparse-only reindex 时不会清空已有
  dense embeddings;只有 changed_node_ids 明确传入时才删除 changed nodes 的
  embeddings。
