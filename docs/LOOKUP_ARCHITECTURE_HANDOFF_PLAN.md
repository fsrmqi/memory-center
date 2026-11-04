# Lookup Architecture Completion Handoff Plan / 查询架构收口交接计划

> 文档类型：架构契约与验收设计（decision）。
>
> 目标 / Goal：在不改变 CLI、HTTP、MCP 公开契约的前提下，定义查询层的依赖反转边界、行为回放门禁与本地样本治理规则。
>
> 已落地的字段门禁 / Shipped gates：chain 锚定负向结论门禁（`chain_anchor_gate.py` + `evaluate_claim_boundary(chain_gate=...)` + 路由 camelCase 拆词）；任务解析保守写入门禁（匹配来源分类 + `resolution_confidence` / `auto_write_allowed` + sync 停写 + mc_close 复用会话绑定）；freshness generation 快照（`observed_generation` / `refresh_in_flight` / `freshness_transition`）；AGENTS 协议的 chain 失败回退与硬锚推荐。回归测试见 `tests/domain/test_chain_anchor_gate.py`、`tests/domain/test_task_resolution_write_gate.py`。

## 1. 模块边界 / Module Boundaries

hybrid lookup 的 scope、execution、decorator、contracts、response 已拆分；context、symbol、navigation、diagnostics API 已拆分；JSONL projection 提供 watermark/repair；core/facade contract 可回放；lookup Port 按功能切分。

Completed: hybrid pipeline extraction, API aggregation extraction, JSONL projection recovery, core/facade contract replay, and feature-scoped lookup ports.

当前文件边界：

| 能力 | 模块 |
|---|---|
| Scope / execution / decorators / contracts / response | `lookup_scope.py` 等 |
| Context | `lookup_context.py` |
| Symbol | `lookup_symbols.py` |
| Call graph / search | `lookup_navigation.py` |
| Ref / backend / usage / discover | `lookup_diagnostics.py` |
| Ports 与纯共享投影 | `lookup_shared.py` |
| 兼容门面与 hybrid orchestration | `query.py` |

## 2. 不可破坏的契约 / Non-Negotiable Contracts

1. 不改变 `memory_*` 函数签名、CLI、HTTP 路由或 MCP tool schema。
2. `query.py` 是 composition root；leaf lookup module 禁止导入 query facade。
3. SQLite 是运行时事实源；JSONL 仅为可恢复导出。
4. 未提供私有 case 时，评测必须 `skipped` 或 `attention`，不得伪造通过。
5. baseline 必须显式保存；未批准语义漂移必须可见。
6. 发布报告不得包含 query 正文、绝对路径、原始 payload 或结果正文。

## 3. 架构收口阶段 / Consolidation Phases

### A. Presentation Layer Finalization

新建 `lookup_presentation.py`，迁出以下无副作用展示逻辑：

- project scope / project evidence；
- compact node evidence；
- augmented lookup payload / entrypoint projection；
- symbol display dedupe、rerank、fallback presentation；
- compact symbol output；
- chain compact 输出中的格式化 helper。

规则：优先直接 import `symbol_ranking.py`；若仍需 project matching，使用小型 `ProjectPresentationPort`，不得回填到 `SymbolLookupPort`。迁移后删除 query 内旧 helper。

### B. Port Minimization

Port 只保留 runtime/facade 依赖：

| Port | 保留能力 |
|---|---|
| Symbol | hybrid query、workspace/graph、active project inference、project matcher、telemetry |
| Context | symbol resolver、workspace/graph、reasoning/freshness、telemetry |
| Navigation | symbol resolver、workspace/graph、edge filter、project matcher、telemetry |
| Diagnostics | store/ref/schema/event adapter |

禁止：重新创建含 15+ callback 的通用依赖袋。

### C. Core and Facade Replay Completion

私有 case 样例：

    schema_version: 1
    cases:
      - case_id: symbol-project
        query: ExampleService
        project: example-service
      - case_id: session-dedup
        query: ExampleService
        session_steps: 2

最小覆盖：general/symbol 2 个、Feign/MQ/Config 各 1 个、project 1 个、stale/partial 1 个、session 1 个、full-chain 1 个。

必须比较：结果 ID/顺序、project scope、contracts/routing、knowledge state、agent next steps、served dedup。

### D. Release Gate

建议参数：

    memory-center release-gate \
      --workspace <workspace.yaml> \
      --lookup-contract-cases <private.yaml> \
      --lookup-contract-baseline <approved-core.json> \
      --lookup-facade-cases <private.yaml> \
      --lookup-facade-baseline <approved-facade.json>

| 条件 | 状态 | 阻断 |
|---|---|---|
| 未传 case | skipped | 否 |
| 有 case、无 baseline | attention | 否 |
| facade 不一致 | fail | 是 |
| session 第二次未去重 | fail | 是 |
| 与批准 baseline 漂移 | fail | 是 |
| 全部一致 | pass | 否 |

### E. JSONL Projection Reliability Campaign

必须覆盖：多 Store 并发 append；append/batch/prune/archive 交错；SQLite 提交后 JSONL 写失败；dirty 后进程重启；两次 repair 幂等；`backend-consistency` 与 quality overview 的 attention/pass 转换。

禁止：未收集到真实 dirty/recovery 数据前，把所有写路径改成后台消息系统或复杂 outbox。

### F. Documentation and Release

每阶段完成时：更新 `ARCHITECTURE.md`、`REFERENCE.md`、`CHANGELOG.md`；公开文档尽量中英双语；对齐 `pyproject.toml`、`memory_center/__init__.py`、README 版本；用 Python 3.10+ pipx 刷新本地安装；不得提交私有 case、baseline、workspace 路径或真实 session ID。

## 4. 推荐顺序 / Recommended Order

1. Phase A；2. Phase B；3. Phase C；4. Phase D；5. Phase E；6. Phase F。

不要同时调整检索算法与架构边界。每次只迁移一个能力域，先跑 contract，再审核 baseline。

## 5. 高优先级实测修复 / High-Priority Field Fixes

以下问题来自真实会话复盘（已脱敏）。它们高于展示层重构，因为会产生错误的负向结论或污染追加保护工件。

### P1-A. Chain 锚定失败不得产生 VERIFIED_NEGATIVE

**现象**：`mc_lookup(mode="chain")` 可能将包含明确类名的 query 锚定到不相关符号；路由分片也可能遗漏目标类所在项目。若 chain 为空且 index freshness/coverage 正常，当前通用 claim boundary 仍可能产生 `VERIFIED_NEGATIVE`。

**风险**：Agent 会把“错误锚点下没有边”理解为“目标没有调用方”，提前停止定位。

**目标语义**：只有同时满足以下条件，chain 空结果才允许负向结论：

1. 用户明确传入的 `symbol` 或 query 中解析出的 `Class` / `Class#method` 与实际锚点一致；
2. 路由 generation 和 selected shard 覆盖锚点所属项目；
3. freshness 为 fresh、coverage 完整、query 未截断或超时；
4. `chain_summary` 为空只是最终结果，而不是锚定失败或范围缺失的副作用。

**实现步骤**：

1. 在 chain 路径构建 `chain_anchor_validation`：

   ```json
   {
     "requested_symbol": "ExampleService",
     "resolved_anchor": "ExampleService",
     "status": "matched|mismatch|missing",
     "reason": ""
   }
   ```

2. 若 `status != "matched"`，将 `query_budget.anchor_mismatch=true` 或新增 `chain_scope.anchor_mismatch=true`；claim boundary 加入 reason code `anchor_mismatch`，强制：

   ```json
   {
     "negative_claim_allowed": false,
     "evidence_level": "AMBIGUOUS"
   }
   ```

3. 在 shard route 返回 `routed_projects`、`anchor_project`、`anchor_project_covered`。若 anchor 项目不在路由范围，加入 `scope_incomplete`，禁止负向结论。
4. 禁止给不匹配锚点赋 exact 999 分；保留候选可解释性，但将其标记 `anchor_candidate_only=true`。
5. `chain_summary` 为空时增加 `fallback_action`：`symbol` 查询、`code` 查询或有界文件搜索，不返回“无调用方”的自然语言结论。

**测试矩阵**：

- 明确类名 + 正确锚点 + 完整分片 + 空边：允许 `VERIFIED_NEGATIVE`；
- 明确类名 + 错误锚点：`AMBIGUOUS` + `anchor_mismatch`；
- 正确锚点 + 漏掉 anchor 项目的分片：`AMBIGUOUS` + `scope_incomplete`；
- 中文意图词混入 query，但显式 `symbol` 正确：仍匹配；
- 空 chain 不得自动生成“确认不存在调用方”文案。

### P1-B. 任务空间解析的保守写入门禁

**现象**：当前 task resolver 主要把完全同分当作歧义；低分且相近的候选仍可能被自动选中，进而让 `mc_start` / `mc_close` 写入错误 task space。

**风险**：`context.md`、`design.md`、`current-summary.md` 等追加保护工件会留下长期脏数据。

**实现步骤**：

1. 在 `_task_match_analysis` 中区分匹配来源：`tag_exact`、`title_exact`、`intent_exact`、`signature_overlap`、`fuzzy_token`、`numeric_or_pinyin_fragment`；不得只返回混合总分。
2. 提升 tag 精确命中权重；`type`、纯数字、拼音碎片、通用词的贡献设上限。
3. 扩展 `_is_ambiguous_task_match`：除了完全同分，还应在以下情况返回 `ambiguous`：

   - top1 低于高置信阈值；
   - top1-top2 小于最小绝对 margin；
   - top1/top2 比值低于配置阈值；
   - top1 没有 title/tag/signature 的强证据，只依赖 fuzzy token。

4. 返回 `resolution_confidence=high|medium|low`、`auto_write_allowed`、`required_action=explicit_task_id`。
5. `workspace_sync_sniff_to_artifacts` 和 `workspace_sync_case_to_artifacts` 在 `auto_write_allowed=false` 时必须停止写入并返回候选，而不是 create/sync。
6. `mc_close` 优先复用同会话 `mc_start` 已解析或显式绑定的 task ID；仅在绑定不存在、归档或显式无效时重新解析。

**建议阈值**：先在 workspace rules 配置，默认保守：低分候选需要显式 task ID；高风险 auto-sync 模式只接受 `resolution_confidence=high`。

**测试矩阵**：

- tag 强匹配任务必须压过无关 token 高分任务；
- top1=9、top2=7 且无强证据：不自动写入；
- top1 高分、tag/title 精确命中：允许写入；
- 同 session start/close 默认使用同一 task；
- 不确定解析下，断言所有 task artifact 文件保持未修改。

### P2-C. Freshness 快照需要 generation 关联

**现象**：`mc_start` 的 stale banner 是启动时快照；后台定向刷新完成后，后续 `mc_lookup.index_context` 可能已 fresh，调用者无法判断两个状态属于不同 generation。

**实现步骤**：

1. freshness 响应增加 `observed_generation`、`observed_at`、`refresh_in_flight`、`superseded_by_generation`（可为空）。
2. `mc_start` 明确标记 `freshness_snapshot=true`，并在 guidance 中说明：后续查询以 `index_context.generation` 为准。
3. 定向刷新已排队时返回 `refresh_in_flight=true` 与可选 `refresh_job_id`，但不阻塞 start。
4. 当 query 使用的 generation 与 start snapshot 不同，返回 `freshness_transition`，例如 `stale_to_fresh`。

**验收**：一次 start 后后台刷新、随后 lookup 的输出能清楚表达 generation 变化，Agent 不会把旧 stale banner 当作当前查询事实。

### P2-D. AGENTS 协议增加 chain 失败回退

在 `core/governance/instructions.py` 的调用链规则后追加：

> chain/trace 返回的锚点与请求符号不符、`chain_summary` 为空、或 `claim_boundary.negative_claim_allowed=false` 时，视为查询失败或范围不足。立即回退到 `mc_lookup(mode="symbol")`、`mc_lookup(mode="code")` 或有界文件搜索；禁止把空结果当作“确认不存在调用方”。

同时将推荐调用改为显式硬锚：

```text
mc_lookup(
  mode="chain",
  query="ExampleService",
  symbol="ExampleService",
  chain_direction="callers"
)
```

中文意图可放 `intent` 或说明文本，但 `symbol` 必须是待验证的类/方法标识。

## 6. 执行顺序 / Execution Order

字段门禁先于展示层收口落地：chain 锚定/范围负向结论门禁 → 任务解析写入门禁 → freshness generation 快照 → AGENTS 失败回退。展示层与 Port 收口按 Phase A→F 推进。

每一项门禁都必须先补可复现的失败回归 case，再允许调整排序或负向结论逻辑。

## 7. 测试矩阵 / Test Matrix

最小验证：

    pytest -q \
      tests/domain/test_lookup_module_boundaries.py \
      tests/domain/test_lookup_contract_replay.py \
      tests/domain/test_query_templates.py \
      tests/domain/test_query_quality.py \
      tests/domain/test_jsonl_export_projection.py \
      tests/entrypoints/test_capability_matrix.py \
      tests/entrypoints/test_cli_command_surface.py
    python3 -m compileall -q memory_center
    git diff --check

扩展验证：

    memory-center eval-lookup-contract --workspace <workspace.yaml> --cases <private.yaml>
    memory-center eval-lookup-facades --workspace <workspace.yaml> --cases <private.yaml>
    memory-center backend-consistency --workspace <workspace.yaml>

若完整 suite 因受保护 demo workspace 的 SQLite WAL/SHM 产生 fixture 污染，应使用临时 workspace 副本。不得提交测试产生的 WAL/SHM/graph.db 改动。

## 8. 验收矩阵 / Acceptance Matrix

| 验收项 | 验证方式 |
|---|---|
| query 内无 legacy query API；leaf module 无反向 facade import | `tests/domain/test_lookup_module_boundaries.py` |
| 各 Port 仅含必要 runtime 依赖，字段规模受测试约束 | Port 字段规模测试 |
| core/facade case 达到最小覆盖集合 | 维护者本地 case 集合，不入库 |
| 批准 baseline 的漂移能阻断 release gate | release-gate 的 `fail` 条件 |
| JSONL 故障、恢复、并发、幂等可复现 | projection/repair 回归测试 |
| 文档、版本、本地安装一致 | 发布清单 |
| 仓库不含私有 query、路径、payload、真实 session ID 或 baseline | 发布前 grep 与人工复核 |

私有 case 与 baseline 只由维护者在本地提供、不入库；仓库中只能出现脱敏的 schema 示例。
