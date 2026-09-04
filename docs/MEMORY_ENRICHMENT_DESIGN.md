# Memory Enrichment Design / 记忆增强设计：借鉴 MemOS / claude-mem / MemoraX

> **状态 / Status**：A（Evidence Index）与 B（Session Notes）**已实现**（2026-09-04，见 [CHANGELOG Unreleased](CHANGELOG.md)），D（四类记忆用户模型）已落入 [USER_GUIDE](USER_GUIDE.md) "Memory boundaries" 小节；C（Memory Cube）仍为 P2 草案待评审。设计与实现差异见文末"实现差异记录"。
> **日期 / Date**：2026-09-04
> **来源 / Sources**：对三个 AML 高分记忆系统的调研——
> - [MemOS 2.0（MemTensor/MemOS，~11k★）](https://github.com/MemTensor/MemOS)：记忆操作系统，图存储、混合检索、L1/L2/L3/Skills 分层、OmniMemEval 评测叙事。
> - [claude-mem / Grok Mem（thedotmack/claude-mem，~93k★）](https://github.com/thedotmack/claude-mem)：捕获-压缩-注入三件套，SQLite FTS5 + 向量混合检索，三层渐进式披露（search → timeline → get_observations），宣称约 10× token 节省。
> - [MemoraX Code（memorax-ai/memorax-code，~1.2k★）](https://github.com/memorax-ai/memorax-code)：四类记忆边界（Coding / Repo / Personal / Procedure）+ NL 去重/更新/遗忘语义 + 默认关闭自动检索。
>
> **范围 / Scope**：只覆盖调研结论中"值得借鉴且 MC 当前没有"的中高优先级能力，共四项。低优先级（NL 修正入口）与明确不借鉴项（云端账号制、自动注入、无方法背书的分数）不在本文档范围内，见文末"明确不做"。

---

## 0. 结论摘要 / Executive Summary

| # | 能力 | 来源启发 | 优先级 | 核心改动 | 主要收益 |
|---|---|---|---|---|---|
| A | **Evidence Index 渐进式披露** | claude-mem 三层工具 + AML `selected` 契约 | P0 | `mc_lookup` 新增 `view="evidence-index"` 只读输出模式 | 降 token、AML Textual 适配、Workbench 紧凑证据 |
| B | **叙事记忆层（Session Notes）** | claude-mem observations / MemOS 自演进 | P1 | L0.5 新存储集合 + AI 压缩入口 + 独立检索 | 跨任务"我们决定了什么/下一步"记忆；AML 叙事题 |
| C | **Memory Cube 隔离与受控共享** | MemOS multi-cube | P2 | workspace 级 cube 注册表 + 读写 ACL + 跨 cube 只读引用 | 多项目/多团队隔离、受控联邦 |
| D | **四类记忆用户模型（文档层）** | MemoraX 四边界 | P2 | 把现有 L3 块映射为四类边界的用户文档 | 用户可决策"记什么到哪层"；零代码 |

实现顺序即优先级顺序：A 是纯输出层改动、无新存储、风险最低；B 需要新存储与压缩管线、收益最大；C 是多工作区治理演进；D 是纯文档。

---

## 1. 现状基线（引用已验证代码）/ Current Baseline

所有引用均已在 2026-09-04 于本仓库核实：

- **检索输出**：`memory_query_hybrid`（`core/orchestrator/query.py:136`）返回 agent 定向的富结果——`matches/results`、`_quality`、`agent_next_steps`、guidance、freshness banner、`claim_boundary`（由 `lookup_response.py:14` `finalize_hybrid_response` 附加）。没有"紧凑索引 → 按需展开"的两段式输出。
- **分层模型**：`LAYER_L0..L3`（`core/orchestrator/shared.py:20-23`）= session events / case atoms / task spaces / workspace profile。L0 是结构化事件（JSONL），不是可检索的叙事文本。
- **核心记忆块**：`CORE_MEMORY_BLOCKS`（`core/tasks/artifacts.py:31-36`）= `workspace_profile`、`team_rules`、`architecture_invariants`、`active_migration_policy`。
- **证据边界**：`evaluate_claim_boundary`（`core/freshness/contract.py:160`）+ `attach_knowledge_state`（`core/knowledge/state.py`）+ chain 锚点门禁（`core/orchestrator/chain_anchor_gate.py`）。
- **混合检索引擎**：`hybrid_retrieve`（`core/retrieval/hybrid.py:263`），图 + 稀疏 + 语义 + 可选向量。
- **时间线**：`timeline_query`（`core/tasks/timeline.py`）按 `created_at` 排序 session_event / write_receipt / handoff。

---

## 2. 能力 A：Evidence Index 渐进式披露（P0）

### 2.1 问题

`mc_lookup` 一次返回全部富块（evidence + guidance + next steps + chain 分析）。对于"先扫一眼有什么、再深入某几条"的用法，这是浪费：agent 端要在大响应里自行挑拣；AML 评测侧则完全无法消费（AML pipeline 只把有序的 `selected: [{created_at, text}]` 渲染进 `{{memories}}`）。claude-mem 用 `search(~100 tok) → timeline → get_observations(~1k tok)` 三层把"先过滤再展开"做成了产品级模式。

### 2.2 设计

新增一个**只读输出视图**，不加新工具、不加新端点：

```
mc_lookup(query=..., mode="query", view="evidence-index")
```

响应收缩为：

```json
{
  "schema_version": 1,
  "kind": "evidence_index",
  "query": "...",
  "selected": [
    {
      "ref_id": "case:2026-09-01:feign-retry",
      "created_at": "2026-09-01T10:12:00+08:00",
      "text": "Feign 重试需配合幂等键，否则 MQ 重复消费（来源：L1 case）",
      "source_layer": "L1_case_atoms",
      "source_kind": "case|note|timeline|artifact_block",
      "score": 0.82,
      "approx_tokens": 48
    }
  ],
  "total_candidates": 37,
  "truncated": true,
  "expand_hint": "用 mc_lookup(mode=\"ref\", ref_ids=[...]) 或 view=\"full\" 展开"
}
```

要点：

1. **字段来源**：`selected` 从既有 `results` 投影——`text` 由每条命中的 `summary/name/evidence` 组装为单行自然语言（不泄漏文件绝对路径，规则沿用 observation 层的绝对路径拒收语义）；`created_at` 来自命中项的时间戳（case `created_at` / event `time` / artifact mtime）；`ref_id` 复用已有 ref 机制（`mc_lookup(mode="ref")` 已支持 ref_ids 解引用）。
2. **展开路径**：第二跳用现有 `mc_lookup(mode="ref", ref_ids=[...])` 拉详情；`view="full"` 保留当前富输出作为兼容默认。**默认值不变**（`view` 缺省 = 现行为），保证 MCP schema 向后兼容。
3. **`approx_tokens`**：按 `len(text)//4` 估算，标注 `estimated: true`；不引入 tokenizer 依赖。
4. **`claim_boundary` 保留**：evidence-index 响应仍携带 `claim_boundary` 与 `knowledge_state`（压缩为两个标量字段而非完整块），因为"空结果不等于不存在"的负向门禁在紧凑视图下同样必须成立。
5. **AML 适配复用**：未来 AML 适配器只需消费此视图（Add→既有写入面，Search→`view="evidence-index"`），不需要为评测单独开检索路径。

### 2.3 验收标准

- [ ] `view` 参数在三入口（MCP/CLI/HTTP）语义一致，缺省行为与当前逐字节兼容；
- [ ] `selected` 单条 ≤ 240 字符、列表默认 ≤ 20 条且 `truncated` 诚实标注；
- [ ] `selected` 中不出现绝对私有路径（复用 `_ABSOLUTE_PATH_RE` 同源规则）；
- [ ] 空 result + 门禁不全时 `claim_boundary.negative_claim_allowed=false`，不输出"确认不存在"措辞；
- [ ] 回归：CLI/MCP/HTTP 三层 entrypoint 测试 + 现有 47 个 shadow/lookup 测试不回归。

### 2.4 不做什么

- 不做 claude-mem 式自动注入（SessionStart 自动拉记忆）——与显式查询 + 证据边界原则冲突；
- 不做向量库新依赖；`approx_tokens` 只做估算。

---

## 3. 能力 B：叙事记忆层 Session Notes（P1）

### 3.1 问题

MC 的 L0 是结构化事件（tool 名、turn、耗时），L1 case 是"可复用工程单元"，L3 是稳定治理块。**缺的是中间态**："这次会话我们决定了什么、为什么、下一步做什么"的自然语言记忆——跨任务可检索、可修正、可遗忘。三个对标项目全部把这个作为产品核心（claude-mem 的 observations、MemOS 的自演进记忆、MemoraX 的四边界），AML Textual track 的时间/偏好/规则题也直接考察它。

### 3.2 设计

新增 **Session Notes**：L0 事件之上的轻量叙事层，存储与检索独立于工程图。

**存储**：`memory/session-notes.jsonl`（与 case atoms 同级的新集合，不进 SQLite 图），每条：

```json
{
  "note_id": "note:{session_id}:{seq}",
  "session_id": "sess_...",
  "created_at": "2026-09-04T10:00:00+08:00",
  "kind": "decision|preference|rule|next_step|fact",
  "text": "决定：网关限流改用 Redis 令牌桶，放弃本地 Guava（QPS 跨实例不均）",
  "status": "active|superseded|forgotten",
  "superseded_by": "",
  "origin": "agent_summary|user_explicit|promotion",
  "source_refs": ["event:...:seq12", "case:..."]
}
```

**写入（Add）**，三个入口，全部显式：

1. `mc_admin(action="note_record", text=..., kind=..., session_id=...)` —— agent/用户显式记一条；
2. 会话关闭时（`mc_close`）从 L0 事件 + 交付摘要生成 draft notes（复用 `workspace_suggest_case` 的 draft 模式：**只建议、不自动入库**，用户确认后写入）；
3. L1 case 晋升时可附带派生 note（`promotion` origin）。

**修正与遗忘（Governance）**，对齐 MemoraX 语义：

- 同 fingerprint（`kind + text 归一化哈希`）重复写入 → no-op；
- 文本细化命中既有 note → 原条 `status=superseded`，`superseded_by` 指向新条（**不物理删除**，保留审计链）；
- 显式 forget（`note_forget`）→ `status=forgotten`，只作用具名 note_id；
- 检索默认只返回 `active`。

**检索（Search）**：

- 并入 `mc_lookup(mode="query")` 的候选源（notes 作为独立 source 与 case/graph 并列、带 `source_kind="note"` 标注）；
- 同时进入能力 A 的 `evidence-index` 视图（`source_layer="L0.5_session_notes"`）；
- FTS 起步（SQLite FTS5 或 JSONL 线性 + BM25 打分，规模到万条再评估向量）。

**隐私边界**：notes 是自由文本，风险高于结构化层——

- 写入时过绝对路径/密钥启发式（与 observation allowlist 同源规则），命中即拒收（fail-closed）；
- `<private>...</private>` 标签段在存储前剥除（借 claude-mem 的用户侧隐私标记，但落地为"剥除 + 记一条 redacted 回执"，不是存原文）；
- notes 不进入 `export-evidence-subgraph`、不进 graph 节点、不出 workspace。

**与 L0–L3 的关系**：Session Notes 定位为 **L0.5**（叙事事实层，介于原始事件与结构化 case 之间）；它不替代 case 晋升链路，而是给"还不足以成为 case、但比原始事件可读"的记忆一个家。`MEMORY_LAYER_ORDER` 增加 L0.5 仅作展示排序，不改变写入门禁语义。

### 3.3 验收标准

- [ ] note 记录/列出/遗忘/检索单元测试（含 fingerprint no-op、supersede 链、forget 只删具名）；
- [ ] 绝对路径/密钥启发式拒收测试；
- [ ] `mc_lookup(mode="query")` 能返回 note 命中且 `source_kind="note"`；
- [ ] evidence-index 视图含 notes 且带 `approx_tokens`；
- [ ] `mc_close` 的 draft notes 流程：不确认不落库（有一条"拒绝即丢弃"的回归测试）；
- [ ] 双语文档（REFERENCE/MCP_GUIDE 增补）。

### 3.4 不做什么

- 不做 AI 自动压缩管线（claude-mem 式"全量捕获→模型压缩"）：v1 只做显式记录 + close 时的确定性 draft（从事件/摘要机械抽取），是否引入模型压缩等有真实需求再评；
- 不做跨 workspace 同步；
- 不做向量索引（先 FTS）。

---

## 4. 能力 C：Memory Cube 隔离与受控共享（P2）

### 4.1 问题

MC 目前只有 workspace 单层边界 + 子目录向上聚合（`workspace_escalation`）。多团队共用一台机器或一个 workspace 服务多条产品线时，缺"多个可组合记忆库 + 显式读写授权"的模型。MemOS 的 cube API（`writable_cube_ids` / `readable_cube_ids` 显式随请求传递）证明了该模型在 agent 场景的可用性。

### 4.2 设计（草案级，实现前需二次评审）

- **Cube 注册表**：workspace 内新增 `memory/cubes.yaml`，每个 cube = `{cube_id, label, owners[], default_access: "private|workspace-read"}`；cube 是 notes + case 的**逻辑分区标签**（v1 不复制存储，只在记录上打 `cube_ids: []`）。
- **请求级授权**：`mc_lookup` / 写入面新增可选 `readable_cubes` / `writable_cubes` 参数（缺省 = workspace 默认 cube）；跨 cube 访问只在显式传 id 且 ACL 匹配时发生。
- **受控共享**：cube 可声明 `shared_with: ["workspace:b", "agent:codex"]`；被共享方查询时结果带 `via_cube` 溯源字段。
- **与 workspace 的关系**：cube 是 workspace 内的分区，不跨 workspace；跨 workspace 联邦仍走既有 registry/escalation 路径。

### 4.3 验收标准（草案）

- [ ] 未授权 cube 的读写请求返回结构化 `cube_access_denied`；
- [ ] 共享 cube 的结果带 `via_cube` 溯源；
- [ ] 既有单 cube（默认）行为与当前完全一致。

### 4.4 依赖

建议在能力 B 落地后评估——notes 的 `kind`/来源结构已经为打 cube 标签做好了准备；工程图节点不参与 v1 cube 化。

---

## 5. 能力 D：四类记忆用户模型（P2，纯文档）

### 5.1 内容

把 MemoraX 的"四类记忆边界"作为**用户文档的心智模型**写进 `docs/USER_GUIDE.md`（不新增任何机制，只重述既有机制）：

| MemoraX 边界 | MC 对应（现有机制） | 用户决策问题 |
|---|---|---|
| Coding Memory | L1 case atoms（`workspace_record_case`）+ 交付 Skill | "这个工程教训下个任务还要用吗？" |
| Repo Memory | 图谱 + `architecture_invariants` + workspace_profile | "Agent 该知道这个仓库的什么？" |
| Personal Memory | L3 `workspace_profile`（沟通偏好记录在此） | "Agent 该怎么和我协作？" |
| Procedure Memory | `team_rules` + 交付矩阵/验证设计契约 | "这类任务的标准流程是什么？" |

配合能力 B 落地后补一行：Session Notes = "还不足以上升为上述四类的临时叙事记忆"。

### 5.2 验收标准

- [ ] USER_GUIDE 新增"记忆边界"小节（双语），表格映射准确、不虚构机制；
- [ ] 文档评审通过：每行映射都能指出真实代码落点。

---

## 6. 实施顺序与依赖

```
A evidence-index (P0) ──► B session notes (P1) ──► C memory cubes (P2)
                                    │
                                    └──► D 四边界文档 (P2, 随时可做)
```

- A 先行：零存储变更、AML 适配的前置、token 收益直接；
- B 依赖 A 的视图作为检索出口之一；
- C 依赖 B 的数据结构（cube 标签挂在 note/case 上）；
- D 独立，可在任意时点合入。

## 7. 明确不做 / Non-goals

- **云端记忆同步/账号体系**（claude-mem cmem.ai、MemOS Cloud 的产品形态）：违反本地优先与不出私有数据的原则；
- **自动检索注入**（SessionStart 自动拉记忆进上下文）：削弱显式查询与证据边界的可证伪性；MC 的等价物是 `mc_start` 的 sniff + 上下文包，由 agent 显式调用；
- **未给方法的 benchmark 分数**：MC 参与外部评测（如 AML）时必须附可复现评测配置；对内继续用 `eval_retrieval_replay` / `eval_golden` 体系；
- **AI 自动压缩为默认路径**：v1 notes 只做确定性 draft；模型压缩引入前需要真实的 token 成本证据。

## 8. 失效条件 / Revisit Triggers

- AML Coding track 发布且其检索契约与 `evidence-index` 不兼容 → 重评 A 的输出形状；
- Session Notes 规模超过 5 万条且 FTS 延迟不可接受 → 评估向量/ANN（届时按 AGENTS.md 规则走 `vector_ann` 管理流程）；
- 出现真实的跨团队共享需求 → C 从 P2 提级并做完整 ADR。

## 9. 实现差异记录 / Implementation Notes（2026-09-04）

与本文档设计条款的已确认差异（实现为准）：

- **B 存储落点**：设计写"不进 SQLite 图"，实现为 SQLite `json_records`（`RuntimeStore`，`note_id` 作 record_id）权威 + `memory/session-notes.jsonl` 投影——与 L0 事件等其他 memory 集合同构，非图节点。
- **B 检索**：v1 用 token 重叠评分（`search_notes`），非 FTS5 索引；规模触发条件见第 8 节。
- **A 展开第二跳**：`mc_lookup(mode="ref")` 现有 ref 机制对 `node:`/`note:` 前缀的解析在后续迭代补齐；当前 `ref_id` 作为稳定标识返回。
- **L0.5 层常量**：`LAYER_L0_5 = "L0.5_session_notes"` 已加入 `MEMORY_LAYER_ORDER`（展示排序），workspace overview 的 `memory_layers` 输出含 `note_count`/`active_note_count`；写入门禁语义不变。

### 真实工作区验证回执（ucap，~2 万文件级，2026-09-04）

- note 生命周期：record → fingerprint no-op → search 命中 → supersede 审计链 → forget 只隐藏具名条，全部通过。
- evidence-index（真实图谱混合）：11 条 selected（36 候选），note 命中与真实图谱方法并列，`knowledge_state=FOUND`；默认视图逐字节兼容。
- `mode="query"` note 合并：命中 note 的查询返回 `note_matches`，已 forget 的词返回空（隐藏语义正确）。
- 隐私门：绝对路径 `absolute_path_rejected`；密钥形态 `secret_shape_rejected`；`<private>` 片段剥除为 `[已省略私有片段]` 后入库。
- `mc_close` 草稿：真实 DSH session 的 intent 正确抽出 decision 草稿，未确认 0 条落盘。
- CLI `query --view evidence-index` 与 HTTP `/workspace/query?view=evidence-index` 冒烟通过。
- 验证数据已清理：notes 从 JSONL 与 backend 全删，常态内容（session-events 1243 行、case 14 行）零污染；追加式 L0.5 write receipts 按审计语义保留。
