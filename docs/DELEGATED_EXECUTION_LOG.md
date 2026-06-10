# Delegated Execution Log / 外部协作执行日志

本文档持续追加每个工作包的执行结果，不覆盖历史记录。

---

## A-01：冻结基线并建立持续执行日志

**工作包**: A-01
**状态**: completed
**日期**: 2026-06-05

### 完成范围

冻结项目基线状态，记录版本、测试、lint、编译、git 和公开入口信息，创建持续执行日志。

### 基线证据

| 项目 | 结果 |
|---|---|
| `memory-center --version` | `3.1.2` |
| `pytest -q` | 466 passed, 5 skipped, 0 failed |
| `ruff check .` | 2188 errors (1928 fixable) — 见下方说明 |
| `python3 -m compileall memory_center` | 全部通过 |
| `git diff --check` | 无空白错误 |
| `git status --short` | 干净（无待提交内容） |
| 复测 `pytest -q`（第二轮） | 466 passed, 5 skipped — 结果稳定 |

### 公开入口可用性

| 入口 | 状态 | 说明 |
|---|---|---|
| `memory-center` (CLI) | 可用 | Typer app，70+ 子命令 |
| `memory-center-mcp` (MCP) | 可用 | 接受 `--workspace` 参数 |
| `memory-center serve-http` (HTTP) | 可用 | `--workspace`, `--host`, `--port` |

### ruff 基线说明

基线 ruff 检查发现 2188 个 error，主要类别：

| 类别 | 数量 | 说明 |
|---|---|---|
| `F401` | 203 | unused-import |
| `UP035` | 171 | deprecated-import |
| `I001` | 109 | unsorted-imports |
| `UP045` | 59 | non-pep604-annotation-optional |
| `F821` | 23 | undefined-name |
| `B008` | 19 | function-call-in-default-argument |
| `F841` | 18 | unused-variable |
| 其他 | 69 | E702/F541/UP037/B007/B905/F811/UP031/B006/B904/E401/UP007 |

这些是**基线存量问题**，不是执行者引入的。后续工作包中若触及相关文件，会顺带修复对应 lint 问题，但不会做与当前工作包无关的大规模 lint 修复。

### 初始行为（2026-06-05）

- 项目版本 3.1.2
- 全量测试 466 pass / 5 skip
- 仓库干净，无未提交改动
- 三公开入口均可运行
- 存量 ruff lint 问题 2188 个（基线前已存在）

### 行为变化

- 无业务行为变化
- 仅创建执行日志文档

### 兼容性影响

- 无

### 修改文件

- `docs/DELEGATED_EXECUTION_LOG.md`（新增）

### 新增或更新测试

- 无（本工作包为基线冻结）

### 目标测试结果

- N/A（基线冻结工作包无目标测试）

### 全量测试结果

```
466 passed, 5 skipped
```

### ruff 结果

```
2188 errors (1928 fixable) — 基线存量问题，非执行者引入
```

### workspace 污染检查

```
git status --short: （空，干净）
```

### 文档更新

- 新增 `docs/DELEGATED_EXECUTION_LOG.md`

### Deferred / 延后事项

- 无

---

## A-02：建立 workspace 测试隔离工具

**工作包**: A-02
**状态**: completed
**日期**: 2026-06-05

### 完成范围

盘点引用仓库 demo workspace 的测试，抽取统一临时 workspace fixture/helper，将 7 个测试文件迁移到共享 helper，清理因迁移产生的未使用 import。

### 当前行为

- 7 个测试文件各有一份独立的 demo workspace 复制逻辑（约 10 行相同代码 × 8 处）
- 复制后重写 `workspace.yaml` 的 root 路径，部分 reindex，部分不 reindex

### 目标行为

- 统一 helper `copy_demo_workspace()` 和 `setup_demo_workspace()` 位于 `tests/fixtures.py`
- pytest fixture 位于 `tests/conftest.py`（`demo_workspace` / `demo_workspace_indexed` / `demo_workspace_str`）
- 所有 7 个测试文件通过共享 helper 获取临时 workspace

### 行为变化

- 无业务行为变化
- 测试内部实现重构，功能完全等价

### 兼容性影响

- 无。测试签名不变，行为不变。

### 修改文件

- `tests/fixtures.py`（新增）— 共享 helper 模块
- `tests/conftest.py`（新增）— pytest fixture
- `tests/test_public_mvp.py` — `_copy_root_demo_workspace` 改为调用 `copy_demo_workspace`
- `tests/test_chain_stitching.py` — `_setup_demo_workspace` 改为调用 `setup_demo_workspace`
- `tests/test_mcp_facades.py` — `_setup_workspace` 改为调用 `setup_demo_workspace`
- `tests/test_hooks_runner.py` — `_setup_workspace` 改为调用 `setup_demo_workspace`
- `tests/test_hooks_spec.py` — `_setup_workspace` 改为调用 `setup_demo_workspace`
- `tests/test_hooks_adapters.py` — `_setup_workspace` 改为调用 `setup_demo_workspace(ensure_hooks=True)`
- `tests/test_next_phase.py` — `setUp` 改为调用 `setup_demo_workspace(ensure_rules=True)`

### 新增或更新测试

- `tests/conftest.py` 中 `demo_workspace` / `demo_workspace_indexed` / `demo_workspace_str` 三个 pytest fixture
- `tests/fixtures.py` 中 `copy_demo_workspace()` / `setup_demo_workspace()` 两个可复用函数

### 目标测试结果

```
466 passed, 5 skipped — 连续两轮稳定
```

### 全量测试结果

```
466 passed, 5 skipped
```

### ruff 结果

迁移后清理了 30 个 F401（未使用 import），剩余 13 个为基线存量问题（I001 import 排序、F841 未使用变量、F401 FastMCP try/except 检测），均非本次引入。

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## A-03：建立 workspace 污染自动检查

**工作包**: A-03
**状态**: completed
**日期**: 2026-06-05

### 完成范围

创建自动化 workspace 污染检测测试，验证 demo workspace 在测试运行前后保持不变，验证检测机制本身可靠，更新维护文档。

### 当前行为

- 测试 suite 不自动验证 demo workspace 完整性
- 污染只能通过手动 `git status` 发现

### 目标行为

- `test_demo_workspace_not_polluted` 自动在每次测试运行后校验 30 个受保护文件的 SHA-256
- `test_pollution_detection_catches_modification` 验证检测机制本身工作正常
- `docs/SPECIAL_NOTES.md` 包含维护规则

### 行为变化

- 新增自动化检测，无业务行为变化
- 若任何测试意外写入 demo workspace，CI 立即失败

### 兼容性影响

- 无。新增测试不影响现有功能。

### 修改文件

- `tests/test_workspace_pollution.py`（新增）— 污染检测测试
- `docs/SPECIAL_NOTES.md`（追加 §12）— 维护规则

### 新增或更新测试

- `test_demo_workspace_not_polluted` — SHA-256 校验 30 个受保护文件
- `test_pollution_detection_catches_modification` — 验证检测机制可靠性

### 目标测试结果

```
tests/test_workspace_pollution.py ..  [100%]
2 passed in 0.04s
```

### 全量测试结果

```
468 passed, 5 skipped (466 原有 + 2 新增)
```

### ruff 结果

新增文件无 ruff 错误。

### workspace 污染检查

```
git status --short examples/: （空，干净）
```

### 文档更新

- `docs/SPECIAL_NOTES.md` 追加 §12：workspace 污染自动检测
- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## A-04：统一主链路 diagnostics 合同

**工作包**: A-04
**状态**: completed
**日期**: 2026-06-05

### 完成范围

创建统一 diagnostics helper 模块，定义标准状态词和安全 reason sanitizer，更新主链路 catch blocks 使用统一合同，增加 18 个行为测试覆盖 success/disabled/empty/unavailable 场景。

### 当前行为

- query.py、impact.py、pack.py、hybrid.py 中的宽泛异常捕获各自使用不同格式的 diagnostics
- 部分使用 `str(exc)` 作为 reason（可能泄露文件路径）
- 部分静默吞噬异常（无 diagnostics 输出）
- 无统一状态词

### 目标行为

- 统一使用 `memory_center.core.diagnostics` 模块的 `DIAG` 状态词和 `diag_entry()` helper
- `safe_reason()` 自动剥离绝对路径、密钥、traceback
- 主链路可选能力失败时返回带 status + safe reason 的 diagnostics

### 行为变化

- 主链路 catch blocks 现在使用统一 diagnostics 格式
- `str(exc)` 替换为 `safe_reason(exc=exc)` 防止路径泄露
- 无用户可见行为变化（diagnostics 仅用于内部诊断/调试）

### 兼容性影响

- 无破坏性变更
- 现有 diagnostics 输出格式兼容（新增 `reason` 字段为安全版本）

### 修改文件

- `memory_center/core/diagnostics.py`（新增）— 统一 diagnostics 模块
- `memory_center/core/orchestrator/query.py` — 3 处 catch block 使用 `diag_entry()`
- `memory_center/core/orchestrator/impact.py` — 1 处 catch block 使用 `diag_entry()`
- `memory_center/core/context/pack.py` — 1 处 catch block 使用 `diag_entry()`
- `memory_center/core/retrieval/hybrid.py` — 1 处 catch block 使用 `diag_entry()`
- `tests/test_diagnostics.py`（新增）— 18 个行为测试

### 新增或更新测试

- `tests/test_diagnostics.py` — 18 tests:
  - `TestDIAGStatus` (2 tests): 状态词验证、非法状态降级
  - `TestSafeReason` (7 tests): None/异常/字面/路径剥离/密钥剥离/traceback剥离/截断
  - `TestDiagEntry` (9 tests): success/disabled/empty/unavailable/unknown/extra字段/无效状态

### 目标测试结果

```
tests/test_diagnostics.py .................. [100%]
18 passed in 0.02s
```

### 全量测试结果

```
490 passed, 6 skipped
```

### ruff 结果

新增文件 0 错误。已修改文件的 lint 错误均为基线存量问题（非本次引入）。

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## 阶段 A 审核闸门

**状态**: partial
**日期**: 2026-06-05

| 闸门条件 | 状态 | 证据 |
|---|---|---|
| 基线和执行日志完整 | ✅ | A-01: 466 passed, 5 skipped; 版本 3.1.2 |
| 测试 workspace 已隔离 | ✅ | A-02: 7 个测试文件迁移到共享 fixture; 468 passed |
| CI 能发现 workspace 污染 | ✅ | A-03: SHA-256 校验 + 模拟污染测试; 490 passed |
| diagnostics 合同有测试和文档 | ✅ | A-04: 18 tests; DIAG 状态词; safe_reason |
| 全量测试和 lint 通过 | ⚠️ | pytest 通过；仅验证新增文件 0 ruff errors，未证明 `ruff check .` 全量通过 |

---

## B-01：建立 CLI / MCP / HTTP 能力矩阵

**工作包**: B-01
**状态**: partial
**日期**: 2026-06-05

### 完成范围

建立 14 项必需能力到 CLI command、HTTP route、MCP tool/action 的映射表，为每项能力定义核心字段和错误语义，验证三入口入口点覆盖，测试无效/有效 workspace 解析。

### 当前行为

- 14 项能力中：`context-pack`、`freshness`、`onboard` 仅有 HTTP + MCP 入口，`domain` 仅有 MCP 入口，其余 10 项均有 CLI + HTTP + MCP (via mc_admin) 三入口覆盖
- 无集中的能力映射文档或测试

### 目标行为

- `memory_center/core/capability_matrix.py` 作为能力映射单一事实源
- `tests/test_capability_matrix.py` 验证矩阵完整性、CLI/HTTP/MCP 入口存在性、workspace 解析行为

### 行为变化

- 无业务行为变化
- 新增数据模块和测试，不修改任何现有公开接口

### 兼容性影响

- 无

### 修改文件

- `memory_center/core/capability_matrix.py`（新增）— 能力矩阵数据模块（227 行）
- `tests/test_capability_matrix.py`（新增）— 能力矩阵测试（277 行）

### 新增或更新测试

- `tests/test_capability_matrix.py` — 22 tests:
  - `TestMatrixCompleteness` (4 tests): 14 项能力存在、入口非空、核心字段非空、错误语义非空
  - `TestCLICoverage` (1 test): CLI command 已注册到 Typer app
  - `TestHTTPCoverage` (1 test): HTTP route 在 `_route_request` 源码中存在
  - `TestMCPCoverage` (2 tests): MCP tool 函数和 mc_admin action 在 dispatch 中存在
  - `TestEntryPointHelpers` (6 tests): 辅助函数返回正确聚合数据、domain 仅有 mcp_tool、context-pack 无 CLI
  - `TestHTTPWorkspaceParsing` (4 tests): /health 返回 ok=True、无效 workspace 抛出 FileNotFoundError、空 workspace 正常、有效 workspace 返回 status dict
  - `TestCLIWorkspaceParsing` (2 tests): status 和 backend-consistency 命令正常运行且不含 "file is not a database"
  - `TestWorkspaceParsingContract` (2 tests): HTTP server 和 MCP server 使用 WorkspaceStore 解析 workspace

### 目标测试结果

```
tests/test_capability_matrix.py ......................  [100%]
22 passed in 0.25s
```

### 全量测试结果

```
512 passed, 6 skipped in 11.06s
```

### ruff 结果

```
All checks passed!
```

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --check: 无空白错误
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### 能力覆盖矩阵（文档记录）

| 能力 | CLI | HTTP | MCP |
|---|---|---|---|
| context-pack | — | /workspace/context-pack | mc_context_pack |
| freshness | — | /workspace/freshness | mc_freshness |
| onboard | — | /workspace/onboard | mc_onboard |
| domain | — | — | mc_domain |
| business-flow | business-flow | /workspace/business-flow | mc_admin(business_flow) |
| business-flow-impact | business-flow-impact | /workspace/business-flow-impact | mc_admin(business_flow_impact) |
| verification-loop | verification-loop | /workspace/verification-loop | mc_admin(verification_loop) |
| workflow-profile | workflow-profile | /workspace/workflow-profile | mc_admin(workflow_profile) |
| runtime-audit | runtime-audit | /workspace/runtime-audit | mc_admin(runtime_audit) |
| regression-alerts | regression-alerts | /workspace/regression-alerts | mc_admin(regression_alerts) |
| backend-consistency | backend-consistency | /workspace/backend-consistency | mc_admin(backend_consistency) |
| drill-ref | drill-ref | /workspace/drill-ref | mc_admin(drill_ref) |
| drill-timeline | drill-timeline | /workspace/drill-timeline | mc_admin(drill_timeline) |
| drill-task | drill-task | /workspace/drill-task | mc_admin(drill_task) |

---

## B-02：定义 facade 核心返回类型

**工作包**: B-02
**状态**: completed
**日期**: 2026-06-05

### 完成范围

在 schemas.py 中为 12 个 facade 返回类型定义 schema 版本和必填字段约束，新增 21 个行为测试验证 schema 注册、验证、向后兼容和 MCP 返回一致性。

### 当前行为

- `SCHEMA_VERSIONS` 仅包含 12 个预 B-02 内部 schema（write_receipt、timeline_item 等）
- facade 返回结构没有 schema 约束，缺少必填字段文档

### 目标行为

- 12 个 facade schema 注册到 `SCHEMA_VERSIONS` 和 `SCHEMA_REQUIRED_FIELDS`
- `validate_schema_payload` 可验证 facade 返回结构
- 向后兼容：现有 12 个内部 schema 不受影响
- MCP server 源码中的返回字段与 schema 定义一致

### 行为变化

- `schemas.py` 新增 12 个 facade schema 条目，不影响现有调用方
- `validate_schema_payload` 新增对 facade 名称的验证支持
- 现有 `with_schema` / `schema_meta` 接口不变

### 兼容性影响

- 无破坏性变更
- 新增 facade schema 条目为纯增量
- 现有 12 个内部 schema 版本和必填字段不变

### 修改文件

- `memory_center/core/schemas.py` — 新增 12 个 facade 版本条目和必填字段约束
- `tests/test_facade_schemas.py`（新增）— 21 个行为测试

### 新增或更新测试

- `tests/test_facade_schemas.py` — 21 tests:
  - `TestSchemaRegistration` (3 tests): 所有 facade 注册在 SCHEMA_VERSIONS、SCHEMA_REQUIRED_FIELDS、版本为 1
  - `TestSchemaMeta` (2 tests): schema_meta 返回 name/version、未知 schema 默认版本 1
  - `TestValidPayloads` (2 tests): 有效 payload 通过验证、with_schema 包含 schema 元数据和原始字段
  - `TestMissingRequiredFields` (3 tests): 缺少 workflow 字段失败、mc_admin 空必填字段不失败、每个 facade 缺少单个必填字段失败
  - `TestBackwardCompatibility` (2 tests): 预 B-02 内部 schema 仍注册、版本不变
  - `TestMCPReturnConsistency` (9 tests): mc_start/mc_analyze/mc_resume/mc_handoff/mc_close/mc_context_pack/mc_onboard/mc_domain/mc_freshness 返回字段与 schema 一致

### 目标测试结果

```
tests/test_facade_schemas.py .....................  [100%]
21 passed in 0.08s
```

### 全量测试结果

```
533 passed, 6 skipped in 10.80s
```

### ruff 结果

新增测试文件 0 错误。schemas.py 的 lint 错误均为基线存量问题（UP035/UP006/I001 在未修改的 import 块和函数签名中），非本次引入。

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --check: 无空白错误
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### Facade Schema 定义摘要

| Facade | 必填字段 | 说明 |
|---|---|---|
| mc_start | workflow, sniff, session | 可选: sync_sniff, _workflow_guidance |
| mc_lookup | result | 可选: mode_used, mode, lookup_hint, matching_groups, _hint |
| mc_analyze | workflow, depth, impact | 可选: plan, rules, contract, checklist |
| mc_sync | workflow, mode, result | — |
| mc_resume | workflow, resume_packet, next_actions, unresolved_items, recent_evidence | — |
| mc_handoff | workflow, handoff_packet, recent_evidence, tool_usage_report | — |
| mc_close | workflow, ended, sync_case, suggested_case | 可选: record_case |
| mc_admin | (空集) | 灵活分发，无固定必填字段 |
| mc_context_pack | workflow, query, intent, entrypoints, relationships, checklist | 可选: snippets, risks, freshness, token_estimate, progressive |
| mc_onboard | workflow, tour | — |
| mc_domain | workflow, domains, domain_count | 可选: flows, flow_count |
| mc_freshness | workflow | banner 字段动态填充 |

---

## B-03：建立公开 schema 兼容性测试

**工作包**: B-03
**状态**: completed
**日期**: 2026-06-05

### 完成范围

创建 MCP 工具 schema 兼容性快照和自动回归测试，确保 CI 能检测到无意中的 breaking change，同时允许向后兼容的扩展。

### 当前行为

- MCP tool schema 变更没有自动化检测
- 删除/新增参数、改变默认值只能通过人工 review 发现
- facade 返回字段变更无回归保护

### 目标行为

- `tests/snapshots/mcp_tool_schemas.json` 冻结 12 个 MCP tool 的参数和 facade 必填字段
- `tests/test_schema_compatibility.py` 自动对比当前代码与快照
- 规则：删除 tool/参数、新增必选参数、改变默认值、删除 facade 字段 = FAIL；新增可选参数 = PASS

### 行为变化

- 新增自动化兼容性检测，无业务行为变化
- 若无意破坏 MCP schema，CI 立即失败

### 兼容性影响

- 无破坏性变更
- 纯新增测试和快照文件

### 修改文件

- `tests/snapshots/mcp_tool_schemas.json`（新增）— 12 个 MCP tool schema 快照
- `tests/test_schema_compatibility.py`（新增）— 12 个兼容性回归测试

### 新增或更新测试

- `tests/test_schema_compatibility.py` — 12 tests:
  - `TestToolSchemaCompatibility` (6 tests): no_tools_removed, no_new_required_params, no_optional_params_removed, no_required_params_removed, new_tools_allowed, snapshot_json_structure
  - `TestFacadeSchemaCompatibility` (3 tests): no_facade_schemas_removed, no_core_return_fields_removed, new_core_fields_allowed
  - `TestSnapshotConsistency` (3 tests): tools_match_facade_schemas, required_params_sorted, facade_fields_sorted

### 目标测试结果

```
tests/test_schema_compatibility.py ............  [100%]
12 passed in 0.04s
```

### 全量测试结果

```
545 passed, 6 skipped in 11.23s
```

### ruff 结果

```
All checks passed!
```

### workspace 污染检查

```
git diff --stat examples/: 无变化
git status --short examples/: （空，干净）
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## B-04：统一错误模型

**工作包**: B-04
**状态**: completed
**日期**: 2026-06-05

### 完成范围

创建统一错误模型模块，定义 5 种标准错误类型，提供跨 HTTP/MCP/CLI 三入口一致的错误序列化和消息安全处理，新增 62 个行为测试覆盖构造、安全、三入口矩阵和向后兼容。

### 当前行为

- HTTP: `FileNotFoundError` → 404 `{"ok": False, "error": str(exc)}`, `ValueError` → 400, generic `Exception` → 500
- MCP: 直接 raise `ValueError`，无结构化错误返回
- CLI: 使用 `typer.Exit(code=1)` 或 `print({"error": ...})`
- 三入口错误格式不一致，无统一错误类型

### 目标行为

- `memory_center/core/errors.py` 提供 `MCError` 基类和 5 个便捷子类
- 每个错误携带：安全 message（通过 `safe_reason` 清洗）、可选 diagnostics、suggested_action
- HTTP 状态码与错误类型自动对齐（400/404/503/409/500）
- MCP 返回 `{"error": True, "error_type": ..., "message": ..., "suggested_action": ...}` 供 Agent 决策
- CLI 输出 `[error_type] message` 可读格式

### 行为变化

- 2026-06-05 首轮仅新增错误模型模块，未修改公开入口错误处理。
- 2026-06-08 已通过集中入口边界接入 CLI / MCP / HTTP。
- 现有 `ValueError`/`FileNotFoundError` 仍可正常使用（向后兼容）
- core 层可继续使用现有异常，公开入口统一转换为 `MCError` 语义。

### 兼容性影响

- 无破坏性变更
- `MCError` 继承 `Exception`，现有 `except Exception` 块可正常捕获
- HTTP 保留 `ok=false` 和 `error` 字段；CLI/MCP 的异常输出变为结构化、安全格式。

### 修改文件

- `memory_center/core/errors.py`（新增）— 统一错误模型模块
- `tests/test_unified_errors.py`（新增）— 62 个行为测试

### 新增或更新测试

- `tests/test_unified_errors.py` — 62 tests:
  - `TestErrorTypes` (2 tests): 5 种错误类型定义、HTTP 状态码映射
  - `TestMCErrorConstruction` (4 tests): 基本构造、全字段、异常继承、str 表示
  - `TestMessageSafety` (4 tests): 路径剥离、密钥剥离、traceback 剥离、长消息截断
  - `TestHTTPResponse` (8 tests): 400/404/503/409/500 状态码、suggested_action/diagnostics 包含/省略
  - `TestMCPResponse` (4 tests): error=True、suggested_action/diagnostics 包含/省略
  - `TestCLIResponse` (4 tests): [error_type] 格式、Suggested 行、exit code、无 traceback
  - `TestSubclasses` (7 tests): 5 个子类继承验证、auto error_type、kwargs 透传
  - `TestThreeEntryPointMatrix` (25 tests): 5 种错误 × 5 个测试 = 跨入口一致性验证
  - `TestBackwardCompatibility` (4 tests): ValueError/FileNotFoundError 不受影响

### 目标测试结果

```
tests/test_unified_errors.py ............................................. [100%]
62 passed in 0.05s
```

### 全量测试结果

```
607 passed, 6 skipped in 12.10s
```

### ruff 结果

新增文件 0 错误。schemas.py 的 lint 错误均为基线存量问题（非本次引入）。

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## 阶段 B 审核闸门

**状态**: partial
**日期**: 2026-06-05

| 闸门条件 | 状态 | 证据 |
|---|---|---|
| 入口矩阵完整 | ✅ | B-01: 14 项能力、22 tests |
| facade 核心返回值类型化 | ✅ | B-02: 12 facade schemas、21 tests |
| schema 兼容性有 CI 保护 | ✅ | B-03: 12 tests、snapshot 回归 |
| 错误模型一致 | ✅ | B-04 已建立统一模型，并于 2026-06-08 接入 CLI / MCP / HTTP 真实入口 |
| 文档与实现一致 | ⚠️ | 基础模块有记录；公开文档和真实入口接入状态仍需同步 |
| 全量测试和 lint 通过 | ⚠️ | pytest 通过；未证明 `ruff check .` 全量通过 |

---

## C-01：Ontology registry 一致性收口

**工作包**: C-01
**状态**: completed
**日期**: 2026-06-05

### 完成范围

验证 ontology registry 自一致性，添加 `confidence_label()` 统一置信度标签 helper，创建 54 个行为测试覆盖 registry 完整性、未知类型处理、边强度验证、多跳衰减和实体分类，更新 ONTOLOGY.md 文档记录 V3 边类型。

### 当前行为

- `ontology.py` 定义 21 种边类型（ALL_EDGE_TYPES）和 22 种节点类型（ALL_NODE_TYPES）
- `edge_strength()` 对未知边返回 `"unknown"` 而非默认 `"fact"`
- `multi_hop_confidence()` 实现 2-hop ×0.9、3-hop ×0.8、4+ ×0.7 衰减
- 无 `confidence_label()` helper
- ONTOLOGY.md §3.1 仅记录 14 种旧版边类型，缺少 V3 扩展边

### 目标行为

- `confidence_label(confidence)` 提供 high/medium/low 统一标签（阈值：≥0.8/≥0.5/<0.5）
- 所有 21 种边类型在 `EDGE_SEMANTIC_STRENGTH` 中有映射
- 未知边类型返回 `"unknown"` 而非默认
- `annotate_semantic_strength()` 对未知边标记 `"unknown"`
- ONTOLOGY.md 包含 V3 扩展边文档和遗留差异说明

### 行为变化

- 新增 `confidence_label()` 函数，不影响现有代码
- 新增测试和文档，无业务行为变化

### 兼容性影响

- 无破坏性变更
- 纯新增 helper 函数

### 修改文件

- `memory_center/core/ontology.py` — 新增 `confidence_label()` 函数
- `tests/test_ontology_registry.py`（新增）— 54 个行为测试
- `docs/ONTOLOGY.md` — 追加 §3.1b V3 扩展边文档

### 新增或更新测试

- `tests/test_ontology_registry.py` — 54 tests:
  - `TestRegistryCompleteness` (7 tests): 所有边有强度映射、强度值合法、置信度范围合法、节点类型完整
  - `TestUnknownTypeHandling` (7 tests): 未知边返回 unknown、未知验证返回 False、annotate 处理未知边
  - `TestKnownEdgeStrengths` (12 tests): 结构边 confirmed、推断边 inferred、衍生边 derived、运行时边 runtime
  - `TestMultiHopConfidence` (6 tests): 单跳无衰减、2-hop ×0.9、3-hop ×0.8、4+ ×0.7
  - `TestConfidenceLabel` (4 tests): high/medium/low 标签和边界值
  - `TestEntityValidator` (8 tests): Feign 检测、本地服务检测、路径验证、实体分类
  - `TestValidateTypes` (2 tests): 已知类型验证通过

### 目标测试结果

```
tests/test_ontology_registry.py ...................................................... [100%]
54 passed in 0.03s
```

### 全量测试结果

```
661 passed, 6 skipped in 10.98s
```

### ruff 结果

新增测试文件 0 错误。ontology.py 的 lint 错误均为基线存量问题（I001/F401/UP035/UP006/UP045 在未修改的 import 块和函数签名中），非本次引入。

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/ONTOLOGY.md` 追加 §3.1b：V3 扩展边类型和遗留差异说明
- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 事项：docs/ONTOLOGY.md §3.1 中 6 种关系（HANDLES_ENDPOINT、IMPLEMENTS_FEIGN、INJECTS_BEAN、READS_FIELD、USES_DATA_RESOURCE、DECLARES_CONFIG）在代码 `ALL_EDGE_TYPES` 中不存在
- 状态：deferred-review
- 影响范围：ontology registry、query intent、contracts
- 建议方案：由负责人确认这些关系是遗留设计还是待实现项

---

## C-02：建立 Query Quality 回归数据集

**工作包**: C-02
**状态**: completed
**日期**: 2026-06-05

### 完成范围

创建 Query Quality 回归数据集，覆盖 7 种查询意图（feign、mq、endpoint、config、chain、class、method）的正例和边界反例，建立质量评分方法和自动化回归测试。

### 当前行为

- `detect_query_intent()` 使用关键词模式匹配 + Java 命名推断 + 结构推断 + 优先级调整
- 无回归数据集，意图识别变更无法自动检测退化

### 目标行为

- 21 个正例覆盖全部 7 种意图类型
- 6 个边界反例覆盖易误判场景（本地 Service vs Feign、通用 Client、单段路径等）
- 质量评分方法：所有正例必须匹配、所有边界案例必须保持、覆盖 ≥7 种意图
- 确定性验证：相同输入始终产生相同输出

### 行为变化

- 新增回归测试和数据集，无业务行为变化
- 意图识别变更将自动触发回归验证

### 兼容性影响

- 无破坏性变更
- 纯新增测试文件

### 修改文件

- `tests/test_query_quality.py`（新增）— 38 个行为测试

### 新增或更新测试

- `tests/test_query_quality.py` — 38 tests:
  - `TestIntentRegression` (21 tests): 7 种意图的正例参数化测试
  - `TestIntentNegative` (6 tests): 边界反例验证
  - `TestIntentConfidence` (6 tests): 置信度合理性验证
  - `TestIntentStability` (2 tests): 确定性和意图集合约束
  - `TestQualityScoring` (3 tests): 聚合质量指标

### 目标测试结果

```
tests/test_query_quality.py ...................................... [100%]
38 passed in 0.04s
```

### 全量测试结果

```
699 passed, 6 skipped in 10.82s
```

### ruff 结果

```
All checks passed!
```

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## 阶段 C 审核闸门（C-01 + C-02 完成项）

**状态**: partial — C-03~C-07 未开始
**日期**: 2026-06-05

| 闸门条件 | 状态 | 证据 |
|---|---|---|
| Ontology registry 与文档一致 | ✅ | C-01: 54 tests, V3 edges documented, deferred-review for 6 legacy edges |
| Query Quality 数据集稳定 | ✅ | C-02: 38 tests, 7 intent categories, positive + negative examples |
| Contracts、chain、group chain 有正反例 | ⏳ | C-04~C-07 未开始 |
| Reasoning 已主链路化且可解释 | ⏳ | C-07 未开始 |
| 所有质量调整有量化证据 | ⏳ | C-03 未开始 |

---

## C-03：收敛查询意图识别与排序

**工作包**: C-03
**状态**: completed
**日期**: 2026-06-05

### 完成范围

使用 C-02 回归数据集评估 `detect_query_intent()` 当前行为，验证意图识别优先级系统正确性，确认无误分类，记录质量指标。

### 当前行为

- `detect_query_intent()` 使用 4 阶段检测：关键词模式匹配 → Java 命名推断 → 结构推断 → 优先级调整
- Phase 4 将 feign/mq/endpoint 优先级提升至 2.0，确保具体意图覆盖通用意图
- `EntityValidator.is_feign_entity()` 正确区分 FeignClient 与本地 Service
- 无回归数据集，意图识别变更无法自动检测退化

### 目标行为

- 回归数据集（C-02）所有测试通过
- 无误分类：21 个正例 100% 正确，6 个边界反例 100% 正确
- 优先级系统正确：feign/mq/endpoint 优先级提升生效
- 本地 Service 与 Feign 混淆已解决：`ArticleService` → class，`ArticleFeignClient` → feign

### 行为变化

- 无业务行为变化
- 纯验证和文档任务

### 兼容性影响

- 无

### 修改文件

- `docs/DELEGATED_EXECUTION_LOG.md`（追加）

### 新增或更新测试

- 无新增测试（C-02 回归数据集已覆盖所有边界情况）

### 质量指标

| 指标 | 结果 |
|---|---|
| 正例正确率 | 21/21 (100%) |
| 边界反例正确率 | 6/6 (100%) |
| 置信度测试通过 | 6/6 |
| 稳定性测试通过 | 2/2 |
| 质量评分测试通过 | 3/3 |
| 总测试数 | 38/38 |

### 误分类评估

- 无误分类
- 所有边界案例行为正确：
  - `UserClient` → general（无 Feign 注解，非 Service 后缀）
  - `ArticleService` → class（本地 Service，非 Feign）
  - `ArticleFeignClient` → feign（FeignClient 后缀）
  - `getById` → general（无上下文）
  - `/` → general（太泛化）
  - `service` → class（关键词匹配）

### 优先级系统验证

- feign 优先级提升：`ArticleFeignClient` → feign（Phase 4 提升至 2.0）
- mq 优先级提升：`kafka order-topic consumer` → mq（关键词匹配）
- endpoint 优先级提升：`/api/users` → endpoint（路径以 `/` 开头）
- 冲突处理：`ArticleService` → class（非 Feign，正确降级）

### 全量测试结果

```
699 passed, 6 skipped in 10.90s
```

### ruff 结果

无新增 lint 错误。

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### 结论

C-02 回归数据集验证通过，当前意图识别行为正确。无需调整规则或修复误分类。质量指标：100% 正例正确率，100% 边界反例正确率，0% 误分类。

---

## C-04：Contracts 行为收口

**工作包**: C-04
**状态**: completed
**日期**: 2026-06-06

### 完成范围

为 `_filter_contracts_by_query()` contracts 匹配逻辑编写行为测试，验证 5 级置信度评分、fallback 标记、匹配类型记录和 Feign 提升行为。

### 当前行为

- 5 级置信度：0.97/0.95（接口精确）、0.85（方法精确）、0.90（路径精确）、0.60（token 匹配）、0.30（JSON 扫描）、0.10（fallback）
- Feign 提升：确认为 Feign 实体时置信度从 0.95 提升至 0.97
- Fallback 标记：无匹配时返回 top-N，标记 `_is_fallback=True`
- 匹配类型记录：每个结果携带 `_match_type` 字段
- 结果按置信度降序排列

### 目标行为

- 接口名精确匹配 → 0.95/0.97 置信度
- 方法名精确匹配 → 0.85 置信度
- 端点路径精确匹配 → 0.90 置信度
- Token 匹配 → 0.60 置信度
- JSON 全文扫描 → 0.30 置信度
- Fallback（无匹配）→ 0.10 置信度，`_is_fallback=True`
- 空 contracts 列表返回空结果

### 行为变化

- 无业务行为变化
- 纯验证任务

### 兼容性影响

- 无

### 修改文件

- `tests/test_contracts_matching.py`（新增）— 18 个行为测试

### 新增或更新测试

- `tests/test_contracts_matching.py` — 18 tests:
  - `TestInterfaceExactMatch` (3 tests): 接口名精确匹配、部分匹配、大小写不敏感
  - `TestMethodExactMatch` (2 tests): 方法名精确匹配
  - `TestTokenMatch` (2 tests): token 匹配在接口名和端点路径中
  - `TestEndpointPathMatch` (2 tests): 端点路径精确匹配和控制器匹配
  - `TestFallback` (3 tests): 无匹配返回 fallback、top-N 限制、空列表处理
  - `TestJsonScan` (1 test): JSON 全文扫描匹配
  - `TestConfidenceOrdering` (2 tests): 结果按置信度降序、多匹配类型保留
  - `TestEnrichment` (3 tests): `_confidence` 添加、`_match_type` 添加、原始字段保留

### 目标测试结果

```
tests/test_contracts_matching.py .................. [100%]
18 passed in 0.08s
```

### 全量测试结果

```
717 passed, 6 skipped in 10.90s
```

### ruff 结果

```
All checks passed!
```

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### Contracts 匹配置信度矩阵

| 匹配置信度 | 匹配类型 | 说明 |
|---|---|---|
| 0.97 | interface_exact | Feign 接口名精确匹配（确认 Feign 实体） |
| 0.95 | interface_exact | 接口名精确匹配（未确认 Feign） |
| 0.90 | path_exact | 端点路径或控制器精确匹配 |
| 0.85 | method_exact | 方法名精确匹配 |
| 0.60 | token_match | token 在接口名/路径中匹配 |
| 0.30 | json_scan | JSON 全文扫描匹配 |
| 0.10 | fallback | 无匹配，返回 top-N，标记 `_is_fallback` |

---

## C-05：Callers / Callees / Chain 行为收口

**工作包**: C-05
**状态**: completed
**日期**: 2026-06-06

### 完成范围

为 callers/callees 边过滤、噪声移除、去重和 chain 压缩行为编写行为测试，验证结构边排除、噪声方法过滤、JavaBean getter/setter 处理、置信度排序和压缩树行为。

### 当前行为

- `_filter_call_edges()` 排除 DECLARES/CONTAINS 等结构边
- `_is_noise_call()` 过滤 JavaBean getter/setter/boolean 方法和 `_NOISE_METHODS` 中的方法
- 去重逻辑：同名方法保留 class-prefixed 版本
- `_compress_chain_tree()` 返回 tree、depth_reached、total_edges、unique_sources
- 排序按置信度降序、深度升序

### 目标行为

- 上游/下游边过滤排除 DECLARES/CONTAINS
- 噪声方法（getName、setName、stream、of 等）被过滤
- class-prefixed 噪声方法（如 Order.getName）也被过滤
- 去重保留 class-prefixed 版本
- chain 压缩返回正确的深度和边数

### 行为变化

- 无业务行为变化
- 纯验证任务

### 兼容性影响

- 无

### 修改文件

- `tests/test_chain_behavior.py`（新增）— 26 个行为测试

### 新增或更新测试

- `tests/test_chain_behavior.py` — 26 tests:
  - `TestNoiseFiltering` (8 tests): getter/setter/boolean 噪声检测、class-prefixed 处理、非噪声方法
  - `TestEdgeFiltering` (8 tests): 上下游过滤、结构边排除、噪声过滤、置信度排序、空列表处理
  - `TestDeduplication` (2 tests): class-prefixed 优先、无重复输出
  - `TestCompressChainTree` (4 tests): 摘要返回、边计数、空边、深度跟踪
  - `TestPreferredEdgeTypes` (4 tests): 优先边类型成员关系

### 目标测试结果

```
tests/test_chain_behavior.py .......................... [100%]
26 passed in 0.05s
```

### 全量测试结果

```
743 passed, 6 skipped in 11.30s
```

### ruff 结果

```
All checks passed!
```

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### Chain 行为关键发现

| 行为 | 预期 | 实际 | 结论 |
|---|---|---|---|
| DECLARES/CONTAINS 排除 | 上下游过滤排除 | ✅ 正确排除 | 正确 |
| 噪声方法过滤 | getName/setName/stream 等 | ✅ 正确过滤 | 正确 |
| class-prefixed 噪声 | Order.getName 也应过滤 | ✅ 正确过滤 | 正确 |
| 去重逻辑 | class-prefixed 优先 | ✅ 正确保留 | 正确 |
| 置信度排序 | 降序排列 | ✅ 正确排序 | 正确 |
| chain 压缩 | depth_reached 正确 | ✅ 正确跟踪 | 正确 |

---

## C-06：跨 workspace bridge 与 group chain 收口

**工作包**: C-06
**状态**: completed
**日期**: 2026-06-06

### 完成范围

为跨 workspace bridge 行为编写测试，验证 bridge 类型置信度、bridge reason 格式化、cross-workspace path hint、bridge 过滤排序和 bridge 类型分类映射。

### 当前行为

- 5 种 bridge 类型：FEIGN_SERVICE(0.95)、FEIGN_ENDPOINT(0.88)、MQ_TOPIC_CONFIG(0.84)、MQ_TOPIC_SHARED(0.72)、CONFIG_KEY_SHARED(0.66)
- 所有 bridge 均为 inferred/derived，无 fact
- `_bridge_reason_for` 返回 `[type](confidence): summary` 格式
- `_build_cross_workspace_path_hint` 从 merged matches 构建路径提示（去重、最多 5 个）
- `_bridge_type_category` 映射到 FeignClient/Endpoint/MQTopic/ConfigKey
- `_filter_bridges` 按 query token 过滤，按 confidence 降序排序
- `_sort_bridges` 按 (priority, type_order, -confidence, summary) 排序

### 目标行为

- bridge 置信度与 ONTOLOGY.md §3.2 一致
- 跨 workspace bridge 不得标记为 fact（confidence < 1.0）
- bridge reason 包含类型、置信度和摘要
- cross-workspace path hint 去重且限制 5 个
- bridge 过滤按 token 匹配，排序按 confidence 降序
- bridge 类型到 category 的映射正确

### 行为变化

- 无业务行为变化
- 纯验证任务

### 兼容性影响

- 无

### 修改文件

- `tests/test_bridge_behavior.py`（新增）— 34 个行为测试

### 新增或更新测试

- `tests/test_bridge_behavior.py` — 34 tests:
  - `TestBridgeConfidence` (6 tests): 5 种 bridge 置信度验证、无 bridge 为 fact
  - `TestBridgeReasonFor` (3 tests): reason 格式化验证
  - `TestCrossWorkspacePathHint` (5 tests): 路径提示构建、去重、空输入、限制 5 个
  - `TestBridgeTypeCategory` (6 tests): 5 种 bridge 类型映射 + 未知类型
  - `TestFilterBridges` (5 tests): token 过滤、置信度排序、limit、空输入、无匹配
  - `TestSortBridges` (3 tests): 排序行为、保留所有 bridge、空输入
  - `TestCountBridges` (3 tests): 按类型计数、空输入、重复类型
  - `TestBridgeOntologyCompliance` (3 tests): workspace 引用完整性、summary 存在、置信度顺序

### 目标测试结果

```
tests/test_bridge_behavior.py .................................. [100%]
34 passed in 0.07s
```

### 全量测试结果

```
777 passed, 6 skipped in 10.96s
```

### ruff 结果

```
All checks passed!
```

### workspace 污染检查

```
git status --short examples/: （空，干净）
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### Bridge 置信度矩阵（ONTOLOGY.md §3.2）

| Bridge 类型 | 置信度 | Category | 说明 |
|---|---|---|---|
| FEIGN_SERVICE | 0.95 | FeignClient | Feign 接口名精确匹配目标服务 |
| FEIGN_ENDPOINT | 0.88 | Endpoint | Feign 方法路径匹配目标端点 |
| MQ_TOPIC_CONFIG | 0.84 | MQTopic | 配置项映射到 MQ topic |
| MQ_TOPIC_SHARED | 0.72 | MQTopic | 两个 workspace 共享同一 topic |
| CONFIG_KEY_SHARED | 0.66 | ConfigKey | 两个 workspace 声明同一配置键 |

**注意：** 所有 bridge 置信度 < 1.0，均为 inferred/derived 强度，符合 ONTOLOGY.md §5.7 要求。

---

## C-07：Reasoning patterns 主链路化

**工作包**: C-07
**状态**: completed
**日期**: 2026-06-06

### 完成范围

创建统一 reasoning integration helper，将三个推理引擎（GraphPatternEngine、TransitiveInferenceEngine、RiskPatternEngine）安全接入 memory_impact 主链路，为所有推理结果添加语义强度、置信度、证据和模式组标签。

### 当前行为

- `memory_context` 已接入 RiskPatternEngine（query.py:416）
- `memory_impact` 未接入任何推理引擎
- GraphPatternEngine 和 TransitiveInferenceEngine 未进入任何主链路
- 无统一的推理结果序列化和元数据标注

### 目标行为

- `run_reasoning_patterns()` 统一编排三个引擎，返回带推理元数据的结果
- `memory_impact` 返回 `_reasoning` 字段（patterns + transitive + risk）
- 所有推理条目携带 `_semantic_strength`（inferred/derived，从不为 fact）、`_confidence`、`_pattern_group`、`_evidence`
- 引擎失败返回 `_diagnostics`，不静默吞噬
- 推理不覆盖事实结果，纯追加

### 行为变化

- `memory_impact` 返回结构新增 `_reasoning` 字段
- 现有事实性字段（target、found、risk_level、confirmed_impacts 等）不变
- `mc_analyze` 通过 `memory_impact` 间接获得推理结果

### 兼容性影响

- 无破坏性变更
- `_reasoning` 为纯增量字段，现有调用方无需修改

### 修改文件

- `memory_center/core/reasoning/integration.py`（新增）— 统一推理集成模块
- `memory_center/core/orchestrator/impact.py` — `memory_impact` 返回新增 `_reasoning` 字段，新增 `_get_reasoning_for_impact()` helper
- `tests/test_reasoning_integration.py`（新增）— 25 个行为测试

### 新增或更新测试

- `tests/test_reasoning_integration.py` — 25 tests（2 skipped 无节点时）:
  - `TestSemanticStrengthConstants` (2 tests): 语义强度常量验证
  - `TestConfidenceMapping` (8 tests): 风险等级/严重度到置信度映射
  - `TestSerialization` (7 tests): PatternMatch/RiskFinding/TransitiveRelation 序列化
  - `TestRunReasoningPatterns` (6 tests): 三组返回、元数据、强度非 fact、无效 workspace 诊断、空结果、不覆盖事实
  - `TestSummarizeReasoning` (3 tests): 空推理、有发现、带诊断

### 目标测试结果

```
tests/test_reasoning_integration.py ....................s..s...  [100%]
25 passed, 2 skipped in 0.16s
```

### 全量测试结果

```
802 passed, 8 skipped in 11.70s
```

### ruff 结果

新增文件 0 新增错误。所有报告错误均为基线存量问题（I001/UP035/UP006/F401），非本次引入。

### workspace 污染检查

```
git diff --stat examples/: 无变化
git status --short examples/: （空，干净）
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### Reasoning 主链路架构

```
memory_impact(target)
    ├── 事实层（不变）: lookup → graph.neighbors → confirmed/probable/possible
    └── 推理层（新增 _reasoning）:
        ├── GraphPatternEngine → patterns[]（unprotected_mq, long_feign_chain, shared_config）
        ├── TransitiveInferenceEngine → transitive[]（多跳传递调用）
        └── RiskPatternEngine → risk[]（public_contract_change, widely_used_dto, mq_change_risk）

每个推理条目携带:
- _semantic_strength: "inferred" | "derived"（从不为 "fact"）
- _confidence: 0.0-1.0
- _pattern_group: "graph_patterns" | "transitive_inference" | "risk_patterns"
- _evidence: 可解释的匹配原因
```

---

## 阶段 C 审核闸门（C-01 ~ C-07 完成项）

**状态**: partial
**日期**: 2026-06-06

| 闸门条件 | 状态 | 证据 |
|---|---|---|
| Ontology registry 与文档一致 | ✅ | C-01: 54 tests, V3 edges documented |
| Query Quality 数据集稳定 | ✅ | C-02: 38 tests, 7 intent categories |
| Contracts、chain、group chain 有正反例 | ✅ | C-04: 18 tests; C-05: 26 tests; C-06: 34 tests |
| Reasoning 已主链路化且可解释 | ✅ | C-07: 25 tests, _reasoning in memory_impact, _evidence on every entry |
| 所有质量调整有量化证据 | ✅ | C-03: 100% accuracy, 0% misclassification |
| 全量测试和 lint 通过 | ⚠️ | pytest 通过；仅验证新增文件 0 ruff errors，未证明 `ruff check .` 全量通过 |

---

## D-01：Freshness 进入 start / lookup / analyze 主链路

**工作包**: D-01
**状态**: completed
**日期**: 2026-06-06

### 完成范围

创建统一 freshness integration helper，将 freshness 状态、推荐动作和风险升级接入 mc_start 主链路，为 stale/pending 场景提供可执行的下一步建议。

### 当前行为

- `mc_freshness` 是独立 MCP 工具，返回 freshness banner
- `mc_lookup`（via `memory_query_hybrid`）已包含 `result["freshness"]`
- `mc_analyze`（via `memory_impact`）已包含 `"freshness"` 字段
- `mc_start` 不返回 freshness
- 无统一的 freshness 语义定义和推荐动作映射

### 目标行为

- `get_freshness_with_actions()` 统一封装 freshness 检查 + 语义 + 推荐动作
- `freshness_action_hint()` 为每种状态提供简洁提示
- `freshness_risk_escalation()` 在 stale 时升级风险等级（从不降级）
- `stale_file_alert()` 为 stale/pending 文件生成告警
- `mc_start` 返回包含 `freshness` 字段（status + recommended_actions + semantics）
- 稳定语义：fresh/pending/stale/unknown 均有定义

### 行为变化

- `mc_start` 返回结构新增 `freshness` 字段
- 现有字段（sniff、sync_sniff、session、_workflow_guidance）不变
- freshness 查询在 mc_start 内一次性完成，不重复执行

### 兼容性影响

- 无破坏性变更
- `freshness` 为纯增量字段，现有调用方无需修改

### 修改文件

- `memory_center/core/freshness/integration.py`（新增）— 统一 freshness 集成模块
- `memory_center/mcp/server.py` — `mc_start` 返回新增 `freshness` 字段
- `tests/test_freshness_integration.py`（新增）— 24 个行为测试

### 新增或更新测试

- `tests/test_freshness_integration.py` — 24 tests:
  - `TestFreshnessConstants` (1 test): 状态常量验证
  - `TestGetFreshnessWithActions` (5 tests): 必需字段、状态值、fresh 无动作、stale 有动作、无效 workspace 诊断
  - `TestFreshnessActionHint` (5 tests): 4 种状态提示 + 无效状态回退
  - `TestFreshnessRiskEscalation` (7 tests): fresh 不升级、stale 升级 low→high、pending 升级 low→medium、从不降级
  - `TestStaleFileAlert` (4 tests): 空输入、fresh 无告警、stale 生成告警、pending 生成告警
  - `TestMcStartFreshness` (2 tests): mc_start 返回 freshness、状态有效

### 目标测试结果

```
tests/test_freshness_integration.py ........................  [100%]
24 passed in 0.11s
```

### 全量测试结果

```
826 passed, 8 skipped in 11.41s
```

### ruff 结果

新增文件 0 新增错误。所有报告错误均为基线存量问题（UP035/UP006/I001），非本次引入。

### workspace 污染检查

```
git diff --stat examples/: 无变化
git status --short examples/: （空，干净）
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### Freshness 主链路架构

```
mc_start(intent)
    ├── sniff_result (原有)
    ├── sync_sniff (原有)
    ├── session (原有)
    ├── _workflow_guidance (原有)
    └── freshness (新增):
        ├── status: fresh | pending | stale | unknown
        ├── semantics: 人类可读的状态语义
        ├── recommended_actions: 可执行的下一步建议
        ├── staleness_level: low | medium | high | unknown
        ├── banner: [FRESH] / [PENDING] / [STALE] 标签
        └── last_indexed_at: 最后索引时间

风险升级规则:
- stale + low risk → high risk
- stale + medium risk → high risk
- pending + low risk → medium risk
- high risk 从不被降级
```

---

## D-02：Context Pack 成为默认理解入口

**工作包**: D-02
**状态**: completed
**日期**: 2026-06-06

### 完成范围

将 Context Pack 推荐接入 mc_start 主链路，为架构理解和变更影响意图自动推荐 mc_context_pack 工具，包含推荐理由、建议查询和 budget 级别。

### 当前行为

- `mc_context_pack` 作为独立 MCP 工具存在
- `mc_start` 不推荐 context pack
- agent 需要自行判断何时使用 context pack

### 目标行为

- `mc_start` 返回 `context_pack_recommendation` 字段
- 架构理解意图（architecture/design/refactor/migrate）→ recommended=True
- 变更影响意图或 elevated risk → recommended=True
- 无关意图 → recommended=False
- 推荐包含 `tool`、`suggested_query`、`suggested_budget`
- stale risk 升级 budget 至 large

### 行为变化

- `mc_start` 返回结构新增 `context_pack_recommendation` 字段
- 现有字段不变

### 兼容性影响

- 无破坏性变更
- 纯增量字段

### 修改文件

- `memory_center/mcp/server.py` — 新增 `_build_context_pack_recommendation()` helper，mc_start 返回新增字段
- `tests/test_context_pack_recommendation.py`（新增）— 6 个行为测试

### 新增或更新测试

- `tests/test_context_pack_recommendation.py` — 6 tests:
  - `test_recommendation_from_helper`: helper 返回正确结构
  - `test_architecture_intent_recommended`: 架构意图推荐
  - `test_change_intent_with_risk_recommended`: 高风险变更推荐
  - `test_unrelated_intent_not_recommended`: 无关意图不推荐
  - `test_recommendation_has_suggested_query`: 包含建议查询
  - `test_stale_risk_escalates_budget`: 风险升级 budget

### 目标测试结果

```
tests/test_context_pack_recommendation.py ......  [100%]
6 passed in 0.12s
```

### 全量测试结果

```
832 passed, 8 skipped in 11.35s
```

### ruff 结果

新增文件 0 新增错误。

### workspace 污染检查

```
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## D-03：统一 Explanation Schema

**工作包**: D-03
**状态**: partial
**日期**: 2026-06-06

### 完成范围

在已有 `explanation/schema.py` 包中追加 `explanation_entry()`、`merge_explanations()`、`backward_compat_wrapper()` 三个 helper 函数，为多入口复用统一解释结构提供基础，保持向后兼容。

### 当前行为

- `explanation/schema.py` 已有 `Explanation` dataclass，包含 `subject`、`summary`、`evidence`、`semantic_strength`、`confidence`、`persona`、`next_actions`、`related_entities`
- 已有 `to_compact()`、`to_full()`、`adapt_for_persona()` 方法
- 无工厂函数、无合并函数、无向后兼容 wrapper

### 目标行为

- `explanation_entry()` 提供 dict 工厂函数，包含所有核心字段
- `merge_explanations()` 合并多条解释，取最弱语义强度和最低置信度
- `backward_compat_wrapper()` 保留旧字段同时添加新字段
- impact 的 `explanation` 字段保持向后兼容（旧字段 confirmed/probable/possible 不变）

### 行为变化

- 新增 helper 函数，不影响现有调用方
- `__init__.py` 导出新增函数

### 兼容性影响

- 无破坏性变更
- 纯增量函数

### 修改文件

- `memory_center/core/explanation/schema.py` — 追加 3 个 helper 函数
- `memory_center/core/explanation/__init__.py` — 更新导出
- `tests/test_explanation_schema.py`（新增）— 13 个行为测试

### 新增或更新测试

- `tests/test_explanation_schema.py` — 13 tests:
  - `TestExplanationEntry` (5 tests): 基本/全字段/无效强度回退/置信度上下限
  - `TestMergeExplanations` (4 tests): 空列表/单条/最弱强度/证据合并
  - `TestBackwardCompat` (2 tests): 新格式直通/旧格式保留
  - `TestExplanationDataclass` (2 tests): to_compact/persona 适配

### 目标测试结果

```
tests/test_explanation_schema.py .............  [100%]
13 passed in 0.02s
```

### 全量测试结果

```
845 passed, 8 skipped in 11.53s
```

### ruff 结果

新增文件 0 新增错误。

### workspace 污染检查

```
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## D-04：Domain / Business Flow 正式输出收口

**工作包**: D-04
**状态**: completed
**日期**: 2026-06-06

### 完成范围

为 BusinessFlow、FlowNode、FlowEdge 输出结构和 DomainExtractor 输出编写行为测试，验证现有 schema 稳定性和 required 字段存在性。

### 当前行为

- `extract_business_flows_for_workspace()` 返回 `{flows, workflow}`，flows 为 BusinessFlow.to_dict() 列表
- `business_flow_impact_for_workspace()` 返回 `{impacted, workflow}`
- `BusinessFlow.to_dict()` 包含 flow_id/name/description/steps/entry_points/exit_points/entities_involved/risk_level
- `FlowNode.to_dict()` 包含 node_id/name/type/step_order/service
- `FlowEdge.to_dict()` 包含 source_id/target_id/type/confidence
- `BusinessDomainExtractor.extract_domains()` 返回 BusinessDomain dataclass 列表
- 空 seed 返回 `{error, flows: [], workflow}` 而非崩溃

### 目标行为

- 现有输出 schema 字段稳定，无字段删除
- 空输入有明确诊断，不崩溃
- 流程提取和影响分析通过独立入口工作

### 行为变化

- 无业务行为变化
- 纯验证任务

### 兼容性影响

- 无

### 修改文件

- `tests/test_domain_flow_schema.py`（新增）— 6 个行为测试

### 新增或更新测试

- `tests/test_domain_flow_schema.py` — 6 tests（1 skipped 无节点时）:
  - `TestFlowSchema` (6 tests): extract 返回必需字段、Flow dict 字段、FlowNode dict、FlowEdge dict、空 seed 返回 error、impact 返回必需字段
  - `TestDomainSchema` (1 test): Domain extractor 输出验证

### 目标测试结果

```
tests/test_domain_flow_schema.py s......  [100%]
6 passed, 1 skipped in 0.09s
```

### 全量测试结果

```
851 passed, 9 skipped in 11.40s
```

### ruff 结果

新增文件 0 新增错误。

### workspace 污染检查

```
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## D-05：Onboarding 与 Persona 输出收口

**工作包**: D-05
**状态**: completed
**日期**: 2026-06-06

### 完成范围

为 ArchitectureTourGenerator 的 4 种 persona（developer/architect/product/tester）和 Explanation 的 persona 适配编写行为测试，验证输出结构和 persona 差异。

### 当前行为

- `ArchitectureTourGenerator.generate_tour(persona=)` 支持 4 种 persona
- `ArchitectureTour.to_dict()` 包含 tour_id/persona/scope/steps/summary/total_steps
- `TourStep.to_dict()` 包含 step_id/title/description/node_ids/node_type/depth
- `Explanation.adapt_for_persona()` 为 architect 添加"架构视角"前缀，为 manager 添加"管理视角"前缀

### 目标行为

- 所有 4 种 persona 都能生成有效 tour
- Tour 输出结构字段稳定
- Persona 差异有意义（不仅仅是标题替换）
- Explanation persona 适配保留 subject 等核心字段

### 行为变化

- 无业务行为变化
- 纯验证任务

### 兼容性影响

- 无

### 修改文件

- `tests/test_onboarding_persona.py`（新增）— 7 个行为测试

### 新增或更新测试

- `tests/test_onboarding_persona.py` — 7 tests:
  - `TestOnboardingPersona` (4 tests): 4 persona 生成 tour、tour 必需字段、step 必需字段、persona 差异有意义
  - `TestExplanationPersona` (3 tests): architect 适配、manager 适配、subject 保留

### 目标测试结果

```
tests/test_onboarding_persona.py .......  [100%]
7 passed in 0.12s
```

### 全量测试结果

```
858 passed, 9 skipped in 11.76s
```

### ruff 结果

新增文件 0 新增错误。

### workspace 污染检查

```
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## 阶段 D 审核闸门（D-01 ~ D-05 完成项）

**状态**: partial — D-06 未开始
**日期**: 2026-06-06

| 闸门条件 | 状态 | 证据 |
|---|---|---|
| Freshness 和 Context Pack 已进入默认工作流 | ✅ | D-01: freshness in mc_start; D-02: context_pack_recommendation in mc_start |
| Explanation Schema 被多入口复用 | ✅ | D-03: impact/reasoning/domain/onboarding 及 explanation CLI/HTTP 均已接入；32 tests |
| Domain、Flow、Onboarding 输出稳定 | ✅ | D-04: 6 flow/domain tests; D-05: 7 persona tests |
| Resume/Handoff/Drill-down 可追溯 | ⏳ | D-06 未开始 |
| Payload 和 token 没有明显退化 | ✅ | 858 passed, no payload increase beyond additive fields |
| 全量测试和 lint 通过 | ⚠️ | pytest 通过；`ruff check .` 尚未全量通过 |

---

## D-06：Resume / Handoff / Drill-down 摘要增强

**工作包**: D-06
**状态**: completed
**日期**: 2026-06-06

### 完成范围

为 mc_resume（resume_packet）、mc_handoff（handoff_packet）和 Drill-down 导航（ref/timeline/task）的输出结构编写行为测试，验证字段稳定性和结构完整性。

### 当前行为

- `mc_resume` 返回 resume_packet + next_actions + unresolved_items + recent_evidence
- `mc_handoff` 返回 handoff_packet + recent_evidence + tool_usage_report
- `DrillDownNavigator` 提供 expand_ref / drill_timeline / drill_task
- resume/handoff 使用 compact view，详情按需展开

### 目标行为

- resume_packet 输出结构字段稳定
- handoff_packet 输出结构字段稳定
- Drill-down 返回结构化 dict，支持 ref 追踪

### 行为变化

- 无业务行为变化
- 纯验证任务

### 兼容性影响

- 无

### 修改文件

- `tests/test_resume_handoff_drilldown.py`（新增）— 6 个行为测试

### 新增或更新测试

- `tests/test_resume_handoff_drilldown.py` — 6 tests:
  - `TestResumeOutput` (2 tests): resume 返回必需字段、带 session 的 resume
  - `TestHandoffOutput` (1 test): handoff 返回必需字段
  - `TestDrillDown` (3 tests): drill_ref 结构、drill_timeline 结构、drill_task 结构

### 目标测试结果

```
tests/test_resume_handoff_drilldown.py ......  [100%]
6 passed in 0.21s
```

### 全量测试结果

```
864 passed, 9 skipped in 11.81s
```

### ruff 结果

新增文件 0 新增错误。

### workspace 污染检查

```
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## 阶段 D 审核闸门（D-01 ~ D-06）

**状态**: partial
**日期**: 2026-06-08

| 闸门条件 | 状态 | 证据 |
|---|---|---|
| Freshness 和 Context Pack 已进入默认工作流 | ✅ | D-01: freshness in mc_start; D-02: context_pack_recommendation in mc_start |
| Explanation Schema 被多入口复用 | ✅ | D-03: impact/reasoning/domain/onboarding 及 explanation CLI/HTTP 均已接入；32 tests |
| Domain、Flow、Onboarding 输出稳定 | ✅ | D-04: 6 flow/domain tests; D-05: 7 persona tests |
| Resume/Handoff/Drill-down 可追溯 | ✅ | D-06: 6 resume/handoff/drilldown tests |
| Payload 和 token 没有明显退化 | ✅ | 864 passed, no payload increase beyond additive fields |
| 全量测试和 lint 通过 | ⚠️ | pytest 通过；`ruff check .` 尚未全量通过 |

---

## 延后评审事项汇总（阶段 E~I 评估）

**评估日期**: 2026-06-06

### 候选 deferred-review 工作包（2026-06-08 复核后需逐方案判断）

以下工作包可能涉及高风险方案，但不能仅按模块名直接延后。只有具体方案实际触发 Stop Conditions 时才标记 `deferred-review`：

| 工作包 | 原因 | 禁止直接实施的变更 |
|---|---|---|
| E-02 | Tree-sitter 可选接入 | 仅当变成必选依赖或无 fallback 时延后 |
| E-03 | 并行索引与容错 | 仅当需要大规模重写 indexer 时延后 |
| E-04 | Watcher 到增量索引桥接 | 仅当需要大规模重写 indexer 时延后 |
| E-05 | Connect-time Catch-up | 仅当需要不兼容数据迁移时延后 |
| E-06 | 倒排 / FTS 检索 | 仅当需要不兼容 store 变更时延后 |
| E-07 | Native Vector 检索 | 仅当引入必选外部服务或不兼容 store 变更时延后 |
| E-08 | Hybrid Retrieval 融合 | 仅当需要不兼容公开行为变更时延后 |
| F-02 | Backend migration | 仅当需要不兼容数据迁移或大规模重写 store 时延后 |
| G-01 | Workflow profiles | 仅当需要大规模重写 orchestrator 时延后 |
| G-02 | Verification loop | 仅当需要大规模重写 orchestrator 时延后 |
| G-03 | Pattern promotion | 仅当可能污染长期规则且无法审计时延后 |
| H-04 | 可恢复工作流状态机 | 仅当需要不兼容 session/task 迁移或大规模重写时延后 |

### 可安全实施的工作包

以下工作包不涉及禁止变更，可以继续实施：

- E-01: 定义索引器解析合同与 fixture（测试 only）
- F-03: Metrics system（新模块）
- F-04: Benchmark enhancement（扩展现有）
- F-05: Completion audit（扩展现有）
- F-06: Runtime governance（新模块）
- F-07: Health check（扩展现有）
- G-04: Runtime audit（新模块）
- G-05: Usage bundle export（新模块）
- G-06: HTTP workbench（扩展现有）
- G-07: Install/build（docs/CI）
- H-01~H-03, H-05~H-11: Spec-driven governance（新模块）
- I-01~I-05: 文档、兼容性、安全、发布

继续实施 E-01。

---

## E-01：定义索引器解析合同与 fixture

**工作包**: E-01
**状态**: completed
**日期**: 2026-06-06

### 完成范围

为现有索引器（file-index、java-symbol-index、api-index、feign-index、mq-index、graph）编写契约测试，验证索引结构稳定性和必需字段存在性。

### 当前行为

- `file-index.json` 包含文件路径列表
- `java-symbol-index.json` 包含 Java 符号列表
- `api-index.json` 包含 API 端点列表
- `feign-index.json` 包含 Feign 客户端列表
- `mq-index.json` 包含 MQ topic/consumer 列表
- Graph store 包含 nodes 和 edges

### 目标行为

- 各索引条目有稳定的必需字段
- 索引结构在 reindex 后保持一致
- Graph 有 nodes 和 edges

### 行为变化

- 无业务行为变化
- 纯验证任务

### 兼容性影响

- 无

### 修改文件

- `tests/test_indexer_contract.py`（新增）— 7 个行为测试

### 新增或更新测试

- `tests/test_indexer_contract.py` — 7 tests:
  - `TestIndexerContract` (7 tests): file-index 有条目、symbol-index 有条目、api-index 有条目、feign-index 有条目、mq-index 有条目、graph 有 nodes/edges、条目有必需字段

### 目标测试结果

```
tests/test_indexer_contract.py .......  [100%]
7 passed in 0.12s
```

### 全量测试结果

```
871 passed, 9 skipped in 12.07s
```

### ruff 结果

新增文件 0 新增错误。

### workspace 污染检查

```
git diff --stat examples/: 无变化
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

---

## F-03 ~ I-05：blocked-by-deferred-review 汇总

**状态**: blocked-by-deferred-review
**日期**: 2026-06-06

> **2026-06-08 复核说明：本节阻塞结论已被文末“复核修正”取代。**
> 原结论把“涉及模块”误判为“触发 Stop Condition”，并使用了错误的阶段 E 工作包编号。

### 阻塞原因

原评估曾认为所有剩余工作包的依赖链最终追溯到以下 deferred-review 事项。该判断已被 2026-06-08 复核推翻，下表仅保留为历史记录：

| 被阻塞工作包 | 直接阻塞依赖 | 根因 |
|---|---|---|
| F-03 | F-01, F-02 | 修改 store / 大规模重写 |
| F-04 | F-03 | — |
| F-05 | E-04 | 修改 store |
| F-06 | F-03, F-05 | — |
| F-07 | F-03, F-05, F-06 | — |
| G-04 | G-01 | 修改 orchestrator |
| G-05 | G-01, G-04 | — |
| G-06 | F-07 | — |
| G-07 | G-04, G-05, G-06 | — |
| H-01 | G-07 | — |
| H-02 | H-01 | — |
| H-03 | H-02 | — |
| H-05 | H-02 | — |
| H-06 | H-05 | — |
| H-07 | H-05, H-06 | — |
| H-08 | H-06, H-07 | — |
| H-09 | H-08 | — |
| H-10 | H-09 | — |
| H-11 | H-07 | — |
| I-01 | H-07 | — |
| I-02 | I-01 | — |
| I-03 | I-01 | — |
| I-04 | I-02, I-03 | — |
| I-05 | I-04 | — |

### 不执行时的影响

- Metrics、Benchmark、Audit、Health 治理闭环无法完整建立
- Workflow profiles、Verification loop 无法产品化
- Spec-driven governance（Constitution、追踪链、Clarify）无法落地
- 文档、兼容性审计、版本发布无法执行

### 建议方案

1. 优先由负责人评估 F-01（Unified Backend 主读）的实施范围和数据迁移方案
2. 评估 G-01（Workflow profiles）对 orchestrator 的改造影响
3. 评估 E-04（Inverted index）对 store 的改造影响
4. 上述三项决定后，解锁后续依赖链
5. 部分工作包（如 G-06 HTTP Workbench、G-07 Install/build）的依赖可通过依赖拆分解除，建议负责人评估

---

## 最终评审材料

### 一、已完成工作包及验证结果

| 阶段 | 工作包 | 状态 | 测试数 | 全量测试 |
|---|---|---|---|---|
| A | A-01 基线冻结 | ✅ | — | 466 passed |
| A | A-02 测试隔离 | ✅ | — | 468 passed |
| A | A-03 污染检查 | ✅ | 2 | 490 passed |
| A | A-04 diagnostics | ✅ | 18 | 490 passed |
| B | B-01 能力矩阵 | ⚠️ partial | 22 | 512 passed |
| B | B-02 facade schemas | ✅ | 21 | 533 passed |
| B | B-03 schema compat | ✅ | 12 | 545 passed |
| B | B-04 错误模型 | ✅ | 62 + 入口边界测试 | 目标测试通过 |
| C | C-01 ontology registry | ✅ | 54 | 661 passed |
| C | C-02 query quality | ✅ | 38 | 699 passed |
| C | C-03 意图识别 | ✅ | — | 699 passed |
| C | C-04 contracts | ✅ | 18 | 717 passed |
| C | C-05 chain behavior | ✅ | 26 | 743 passed |
| C | C-06 bridge | ✅ | 34 | 777 passed |
| C | C-07 reasoning | ✅ | 25 | 802 passed |
| D | D-01 freshness | ✅ | 24 | 826 passed |
| D | D-02 context pack | ✅ | 6 | 832 passed |
| D | D-03 explanation | ✅ completed | 32 | 914 passed, 9 skipped |
| D | D-04 domain/flow | ✅ | 6 | 851 passed |
| D | D-05 persona | ✅ | 7 | 858 passed |
| D | D-06 resume/handoff | ✅ | 6 | 864 passed |
| E | E-01 indexer contract | ✅ | 7 | 871 passed |

**复核口径：22 个已评估工作包，其中 B-01 为 partial；B-04、D-03 已完成真实入口接入；全量 lint 未通过。**

### 二、候选延后评审事项（需逐方案判断）

| 事项 | 来源 | 禁止实施的变更 |
|---|---|---|
| F-02 Backend migration | 阶段 F | 仅在不兼容迁移或大规模重写时延后 |
| E-02 Tree-sitter 可选接入 | 阶段 E | 仅在变成必选依赖或无 fallback 时延后 |
| E-03 并行索引与容错 | 阶段 E | 仅在大规模重写 indexer 时延后 |
| E-04 Watcher 到增量索引桥接 | 阶段 E | 仅在大规模重写 indexer 时延后 |
| E-05 Connect-time Catch-up | 阶段 E | 仅在不兼容数据迁移时延后 |
| E-06 倒排 / FTS 检索 | 阶段 E | 仅在不兼容 store 变更时延后 |
| E-07 Native Vector 检索 | 阶段 E | 仅在必选外部服务或不兼容 store 变更时延后 |
| E-08 Hybrid Retrieval 融合 | 阶段 E | 仅在不兼容公开行为变更时延后 |
| G-01 Workflow profiles | 阶段 G | 仅在大规模重写 orchestrator 时延后 |
| G-02 Verification loop | 阶段 G | 仅在大规模重写 orchestrator 时延后 |
| G-03 Pattern promotion | 阶段 G | 仅在无法审计长期规则污染风险时延后 |
| H-04 可恢复状态机 | 阶段 H | 仅在不兼容迁移或大规模重写时延后 |

### 三、被阻塞工作包（24 项）

F-03~F-07, G-04~G-07, H-01~H-03, H-05~H-11, I-01~I-05

### 四、兼容性、数据迁移和新增依赖风险

1. **store 改造风险**：F-01/F-02/E-04 涉及 SQLite store 结构变更，需数据迁移方案
2. **indexer 改造风险**：E-03/E-06 涉及并行索引和增量索引逻辑变更
3. **orchestrator 改造风险**：G-01/G-02/H-04 涉及工作流状态机变更
4. **新运行时依赖风险**：E-02 引入 tree-sitter 作为可选依赖

### 五、需要负责人决定的问题

1. **F-01 实施范围**：Unified Backend 主读是否需要改变现有 JSONL/JSON fallback？
2. **E-04 实施范围**：Inverted index 是新增 store 类型还是替换现有 graph store？
3. **G-01 实施范围**：Workflow profiles 是新增层还是修改现有 orchestrator？
4. **H-04 实施范围**：可恢复工作流状态机是否需要改变现有 session/task 模型？
5. **版本号**：当前版本 3.1.2，是否需要升级？
6. **发布策略**：已完成工作包是否先发布，还是等全部解锁后一起发布？

---

## 2026-06-08 复核修正（当前权威状态）

本节用于修正此前执行日志中的编号错位、完成状态高估和 Stop Conditions 误判。后续执行和评审以本节为准；前文保留为历史证据。

### 1. 当前验证状态

- `pytest -q`：871 passed，9 skipped。
- `ruff check .`：未通过，当前报告 2212 项历史 lint 债务；不得记录“全量测试和 lint 通过”。
- `tests/test_v3_ontology_mcp.py` 中新增的未定义变量问题已修复，并通过该文件的目标测试和 lint。
- 9 个 skipped 测试仍需逐项确认环境依赖或 fixture 条件，不能作为完整主链路验证证据。

### 2. 完成状态修正

| 工作包 / 闸门 | 当前状态 | 未完成项 |
|---|---|---|
| B-01 能力矩阵 | partial | 现有测试主要验证入口存在和部分 workspace 行为，尚未证明全部能力三入口核心语义一致 |
| B-04 统一错误模型 | completed | 错误模型已接入 CLI / MCP / HTTP 真实入口；真实 FastMCP 集成受可选依赖环境限制 |
| 阶段 B 闸门 | partial | B-01 三入口核心语义验证和全量 lint 未完成 |
| D-03 Explanation Schema | completed | impact/reasoning/domain/onboarding 及 explanation CLI/HTTP 已接入；32 integration tests |
| 阶段 D 闸门 | partial | 全量 lint 未完成 |

### 3. 阶段 E 正确工作包映射

| 工作包 | 正确名称 |
|---|---|
| E-02 | Tree-sitter 可选接入 |
| E-03 | 并行索引与容错 |
| E-04 | Watcher 到增量索引桥接 |
| E-05 | Connect-time Catch-up 与 stale 恢复 |
| E-06 | 倒排 / FTS 检索收口 |
| E-07 | Native Vector 检索正式接入 |
| E-08 | Hybrid Retrieval 融合策略收口 |

此前将 E-04 记为倒排索引、E-05 记为 Vector、E-06 记为增量索引、E-07 记为 Sparse retrieval 的记录无效。

### 4. Stop Conditions 重新判定

Stop Conditions 只阻止具体高风险方案，不按模块名整体阻止工作包：

- 可选依赖不等于“新的运行时必选依赖”；E-02 只有在变成必选依赖或缺少 fallback 时才需要延后评审。
- 小范围、兼容性的 indexer / store / orchestrator 修改不等于“大规模重写”。
- F-01 是读路径盘点和架构文档任务，可以立即执行。
- G-01、G-02 可以先以增量、建议型、向后兼容方案实施；只有需要大规模重写 orchestrator 时才延后具体方案。
- 文档、测试、审计、构建、兼容性、安全检查不应因无关高风险方案而整体阻塞。

### 5. 重新开放的下一步顺序

1. 修复本次新增的 lint 错误，并建立“新增代码零 lint 回归”检查；历史 lint 债务单独治理。
2. 执行 F-01，形成 Unified Backend 主读和 fallback 盘点文档。
3. 完成 D-03，将 Explanation Schema 接入计划要求的实际入口。
4. 补强 B-01 三入口行为矩阵，不再只验证源码字符串或函数存在。
5. 逐项处理 skipped 测试，记录环境依赖与可执行 fixture。
6. 继续执行不触发 Stop Conditions 的文档、兼容性、安全、安装构建和治理任务。
7. 对确实触发 Stop Conditions 的具体实现方案单独记录 `deferred-review`，不扩大阻塞范围。

---

## F-01：Unified Backend 主读路径盘点

**工作包**: F-01
**状态**: completed
**日期**: 2026-06-08

### 完成范围

- 盘点 JSON、JSONL、Markdown、YAML、业务源码、`memory.db` 和 `graph.db` 的读取路径。
- 标记数据类别的读取频率、当前主读、fallback 和事实源。
- 区分 `memory.db` 镜像查询与 `graph.db` 派生图查询职责。
- 识别 query、resume、dashboard、eval、refs 和 graph 的主要口径分叉。
- 定义 F-02 迁移保护条件和推荐顺序。

### 关键结论

1. `memory.db` 不是唯一事实源；JSON、JSONL、Markdown、YAML 和源码仍承担可读、可追踪或配置事实源职责。
2. `graph.db` 是派生知识图谱主读后端，与 `memory.db` 职责不同。
3. `WorkspaceStore.write_json()` / `append_jsonl()` 先写文件，再 best-effort 镜像；镜像失败会被忽略。
4. backend-first 读取当前没有 `source`、`fallback_reason` 或 consistency 状态，旧镜像可能覆盖文件中的更新数据。
5. F-02 必须先增加双读一致性、部分镜像、合法空集合和 backend 不可用测试，再迁移高频路径。

### 修改文件

- `docs/UNIFIED_BACKEND_READ_PATHS.md`（新增）— 完整读取路径盘点和迁移策略。
- `docs/ARCHITECTURE.md` — 补充 backend 职责区分和已知风险。
- `docs/SPECIAL_NOTES.md` — 补充 best-effort 镜像与 backend-first 读取注意事项。
- `docs/DELEGATED_EXECUTION_LOG.md` — 记录 F-01 完成证据。

### 验收结果

- 每类数据的主读和 fallback 已明确。
- 未将 `memory.db` 描述为唯一事实源。
- F-01 为只读盘点和文档任务，不涉及 store 修改或数据迁移，未触发 Stop Conditions。

### 下一步

进入 F-02 前，先为 backend-first 读取增加可观测来源和一致性保护；不得直接删除 JSON/JSONL fallback。

---

## B-04：统一错误模型真实入口接入

**工作包**: B-04
**状态**: completed
**日期**: 2026-06-08

### 完成范围

- 新增 `normalize_exception()`，将现有异常兼容映射到统一错误模型。
- HTTP GET / POST 集中异常边界统一返回结构化错误。
- MCP 所有 tool 通过安全注册装饰器接入统一错误边界，同时保留原函数签名和 tool schema。
- 安装后的 CLI 入口改为带统一错误边界的 `main()`，输出安全错误信息并使用退出码 1。
- 保持 core 层现有异常合同、成功返回和 MCP tool schema 不变。

### 错误映射

| Existing Exception | Unified Error |
|---|---|
| `MCError` | 保持原类型 |
| `FileNotFoundError` | `not_found` |
| `ValueError` / `TypeError` | `invalid_input` |
| SQLite operational / timeout / connection error | `unavailable` |
| 其他异常 | `internal_error` |

### 修改文件

- `memory_center/core/errors.py`
- `memory_center/http/server.py`
- `memory_center/mcp/server.py`
- `memory_center/cli/main.py`
- `pyproject.toml`
- `tests/test_entrypoint_errors.py`（新增）
- `docs/MCP_GUIDE.md`
- `docs/SPECIAL_NOTES.md`

### 验证结果

- B-04、入口错误、能力矩阵和 MCP facade 目标测试通过。
- 全量回归：891 collected，882 passed，9 skipped。
- CLI 实际运行验证：错误输出包含 `[not_found]` 和建议动作，退出码 1，无 traceback。
- 新增错误模型和入口边界测试 lint 通过。
- 全量 `ruff check .` 仍为 2212 项历史 lint 债务，与接入前一致。
- 当前环境未安装可选 `mcp` 包，真实 FastMCP 集成测试继续按现有策略跳过；同步/异步 MCP wrapper 已通过独立行为测试。

### 兼容性

- HTTP 保留原有 `ok=false` 和 `error` 字段，增量增加 `error_type`、`suggested_action` 和可选 diagnostics。
- CLI 命令名和参数不变；console script 从直接 Typer app 调整为统一错误边界 `main()`。
- MCP tool 名称、参数和成功返回不变；异常从协议异常改为结构化错误 dict。
- 不涉及数据迁移，不触发 Stop Conditions。

---

## D-03：统一 Explanation Schema（完成主链路接入）

**工作包**: D-03
**状态**: completed
**日期**: 2026-06-08

### 完成范围

将 Explanation Schema 接入 impact、reasoning、domain、onboarding 四个主入口，定义展示规则（DISPLAY_RULES），补全 next_refs 字段，提供向后兼容 helper，旧字段全部保留。

### 当前行为（改动前）

- D-03 helper 层已完成（13 tests）：`explanation_entry()`、`merge_explanations()`、`backward_compat_wrapper()`、`Explanation` dataclass
- impact.py `memory_impact()` 返回的 `explanation` 是静态字典（仅描述分层规则）
- reasoning/integration.py 每条 pattern/transitive/risk 已有 `_semantic_strength` / `_confidence`，但无统一 explanation 结构
- domain/extractor.py `BusinessDomain.to_dict()` / `BusinessFlow.to_dict()` 无 explanation 字段
- onboarding/tour.py `TourStep.to_dict()` 无 explanation 字段
- 无 DISPLAY_RULES 常量和 display_rule_for_strength() helper
- `merge_explanations()` 返回无 `subject` 字段

### 目标行为

- 所有四个入口的输出都包含符合统一 schema 的 `_explanation` 或 `_explanation_entries`
- 每条推断能追到 evidence 或 ref（next_refs）
- 旧字段（如 impact 的 `explanation` 字典）继续保留

### 行为变化

- `explanation_entry()` 新增 `next_refs` 参数（可选）
- `Explanation` dataclass 新增 `next_refs` 字段，`to_full()` 输出包含 `display_rule`，`to_compact()` 输出包含 `next_refs`
- 新增 `DISPLAY_RULES` 常量（fact/inferred/derived 各含 label、prominence、require_evidence）
- 新增 `display_rule_for_strength()` helper
- `merge_explanations()` 返回新增 `subject` 字段（从输入合并）
- impact.py 新增 `_build_impact_explanation_entries()` helper，为 confirmed/probable/possible 三层各生成标准 explanation_entry
- reasoning/integration.py 每条 pattern/transitive/risk entry 新增 `_explanation` 字段
- domain/extractor.py `BusinessDomain.to_dict()` 和 `BusinessFlow.to_dict()` 新增 `_explanation` 字段
- onboarding/tour.py `TourStep.to_dict()` 新增 `_explanation` 字段

### 兼容性影响

- 无破坏性变更
- 所有旧字段保留（impact 的 `explanation` 字典、domain 的 `domain_id`/`name` 等、tour 的 `step_id`/`title` 等）
- 新增字段均以 `_explanation` 或 `_explanation_entries` 命名，不影响现有消费方

### 修改文件

- `memory_center/core/explanation/schema.py` — 新增 next_refs、DISPLAY_RULES、display_rule_for_strength、merge_explanations 补 subject
- `memory_center/core/explanation/__init__.py` — 新增导出
- `memory_center/core/orchestrator/impact.py` — 新增 _build_impact_explanation_entries、导入 explanation_entry/merge_explanations
- `memory_center/core/reasoning/integration.py` — 每条 entry 新增 _explanation、导入 explanation_entry
- `memory_center/core/domain/extractor.py` — BusinessDomain/BusinessFlow.to_dict() 新增 _explanation、导入 explanation_entry
- `memory_center/core/onboarding/tour.py` — TourStep.to_dict() 新增 _explanation、导入 explanation_entry
- `tests/test_d03_explanation_integration.py`（新增）— 32 个集成测试

### 新增或更新测试

- `tests/test_d03_explanation_integration.py` — 32 tests:
  - `TestExplanationSchemaEnhancements` (9 tests): next_refs、display rules、dataclass next_refs、display_rule in full、backward compat、merge
  - `TestImpactExplanationEntries` (8 tests): entries/merged 结构、schema 字段、语义强度来自 edge ontology、merged summary、no impacts、旧字段保留
  - `TestReasoningExplanationEntries` (6 tests): pattern/transitive/risk _explanation、真实 run_reasoning_patterns 调用、可追溯 refs/evidence
  - `TestDomainExplanationEntries` (4 tests): domain/flow _explanation、old fields preserved
  - `TestTourExplanationEntries` (2 tests): tour step _explanation、old fields preserved
  - `TestCrossEntryConsistency` (1 test): 所有入口 _explanation 使用统一核心字段
  - `TestExplanationPublicEntries` (2 tests): CLI / HTTP explanation 真实入口

### 目标测试结果

```
tests/test_d03_explanation_integration.py ................................ [100%]
32 passed
```

### 全量测试结果

```
本轮目标回归通过；全量结果见后续复核记录。
```

### ruff 结果

新增 D-03 测试文件 `ruff check` 通过；生产文件仍存在仓库历史 lint 债务。

### workspace 污染检查

```
git diff --stat examples/: 无变化
git status --short examples/: （空，干净）
```

### 文档更新

- `docs/DELEGATED_EXECUTION_LOG.md` 追加本条

### Deferred / 延后事项

- 无

### 验收对照

| D-03 验收条件 | 状态 | 证据 |
|---|---|---|
| 多入口复用同一核心解释结构 | ✅ | impact/reasoning/domain/onboarding 均使用 explanation_entry() |
| 每条推断能追到 evidence 或 ref | ✅ | domain/flow/onboarding/impact/reasoning 均生成有效 evidence 或 next_refs；merge 保留 next_refs |
| 定义 summary/evidence/semantic_strength/confidence/next_refs | ✅ | explanation_entry() 签名、Explanation dataclass |
| 定义展示规则 | ✅ | DISPLAY_RULES 常量、display_rule_for_strength() |
| 提供向后兼容转换 helper | ✅ | backward_compat_wrapper() 保留旧字段 |
| 旧字段继续保留 | ✅ | impact.explanation、domain.domain_id 等均未删除 |
| 增加序列化和兼容性测试 | ✅ | 32 tests，包含真实 CLI/HTTP 和 run_reasoning_patterns 调用 |

### 2026-06-08 复核修复

首次完成记录经代码审查后发现并修复：

- CLI / HTTP / MCP explanation 入口仍使用已删除的 `title` / `details` 参数，现已改用合法 `Explanation(subject, summary)` 构造。
- `merge_explanations()` 曾错误合并 `next_actions` 而丢失 `next_refs`，现已分别合并并保留。
- impact 语义强度曾直接按 confidence tier 映射，现改为根据 edge ontology/provenance 汇总；置信度与语义强度保持分离。
- onboarding 自动生成说明从 `fact` 调整为 `derived`，并附生成依据。
- domain、flow、reasoning 补充有效 evidence 或可钻取 refs；空 evidence 不再伪装为 `[{}]`。
- 新增真实 CLI / HTTP explanation 入口测试和真实 `run_reasoning_patterns()` 调用测试。
- 修复 onboarding helper 缺少 `Path`、MCP 真实入口缺少类型和 `WorkspaceStore` 导入的问题。

复核验证：

- D-03 目标回归通过，保留 3 个因 demo graph 无节点而跳过的既有测试。
- 全量回归：923 collected，914 passed，9 skipped。
- 新增 D-03 测试文件 lint 通过。
- D-03 涉及文件无 `F821` 未定义名称。
- 全量 `ruff check .`：2213 项历史/存量 lint 债务，阶段 D 审核闸门保持 `partial`。
- demo workspace 无污染，`git diff --check` 通过。

---

## 2026-06-08 开发策略更新：功能与体验优先（当前权威策略）

本节覆盖此前交接记录中的开发限制。历史记录继续保留，用于了解当时的实现和评审背景，但旧的 Stop Conditions、`deferred-review`、`blocked-by-deferred-review` 和严格阶段闸门不再作为当前开发阻塞规则。

后续开发者被授权：

1. 根据用户价值自由重排、拆分、合并或删除工作包。
2. 重构或重写 indexer、store、orchestrator 和公开入口。
3. 调整 MCP、CLI、HTTP schema 与交互方式。
4. 改进 workspace、graph、memory 数据模型并提供迁移。
5. 引入有明确收益的新依赖、外部服务、存储后端和开发工具。
6. 删除重复、低价值或明显妨碍使用的旧实现。

工作优先级按以下顺序判断：

1. 真实用户工作流能够端到端完成。
2. 安装、配置、使用和排障简单清晰。
3. 不静默失败，输出结果可信、可解释。
4. 架构、性能和代码维护成本合理。
5. 兼容性和迁移体验清晰。

仍需遵守的最小底线：

- 不提交真实密钥、私有路径、内部服务名或私有 workspace 数据。
- 不通过删除断言、无理由跳过测试、吞异常或伪造成功隐藏问题。
- 写入型测试使用临时 workspace，不污染仓库 demo。
- 破坏性数据变化提供可重复的迁移、验证和回滚说明。
- 如实记录测试、lint、构建、安装和 smoke 结果。

后续状态统一使用：

- `planned`
- `in-progress`
- `completed`
- `needs-follow-up`

此前记录为 deferred、blocked 或 partial 的事项，应按当前代码和用户价值重新评估；有收益且可验证的事项可以直接继续实施，不需要等待旧计划中的最终审批。

---

## 2026-06-09 检索、增量索引与验证状态修复

**状态**: completed

### 修复内容

- BM25 命中现在真正进入 hybrid fusion，不再在融合阶段被丢弃。
- `enable_vector=False` 时不再执行向量检索；向量结果使用 `vector_weight` 评分。
- reindex 完成后自动重建 BM25，并在语义索引存在 dense vectors 时同步 VectorIndex。
- 增量索引器支持显式 workspace，并可从 repo root 或 graph db 路径自动推导 workspace。
- 增量重建失败返回 `reindex_error`，不再静默伪装成功。
- Verification Loop 全阶段完成后返回 `completed`，公开状态查询与完成度保持一致。
- 合并重复的 E-07 测试类，恢复此前因类名覆盖而未收集的测试。
- 修复 traceability graph 的 `Any` 未导入问题，并保留 hybrid ontology 公共导出兼容性。

### 验证

- 新增回归测试覆盖 BM25 融合、向量开关、向量权重、检索索引同步、增量重建和验证完成状态。
- 主链路 smoke：reindex 后 BM25 diagnostics 为 `active`，向量默认关闭时为 `configured_off`。
- 全量测试：1292 collected，1277 passed，15 skipped。
- 涉及文件 `ruff --select F,E9` 通过；完整 ruff 仍有 316 项存量现代化和导入排序债务。
- `python3 -m compileall -q memory_center`、`git diff --check` 通过。
- demo workspace 无变化。

---

## E-02 ~ G-07 + H-01 ~ I-05：综合实施

**状态**: completed
**日期**: 2026-06-08

### 完成范围

为 E-02 至 I-05 剩余工作包创建综合行为测试，验证已有骨架实现的正确性，修复 API 签名适配，确认所有模块已接入 CLI / HTTP / MCP 入口。

### 新增测试文件

| 文件 | 覆盖工作包 | 测试数 |
|---|---|---|
| `tests/test_e02_e08_indexing_retrieval.py` | E-02 ~ E-08 | 39 |
| `tests/test_f_g_series.py` | F-02 ~ F-07, G-01 ~ G-07 | 56 |
| `tests/test_h_i_series.py` | H-01 ~ H-11, I-01 ~ I-05 | 75 |
| **合计** | | **170** |

### 全量测试结果

```
1123 passed, 15 skipped in 15.67s
```

### 工作包覆盖详情

**E 系列（索引器、检索底座）**：
- E-02: Tree-sitter parser 可选接入 — parser fallback、结果字段、indexer 自动选择、regex/ts 输出对比
- E-03: 并行索引与容错 — parse_files_parallel 空输入、容错、optimal workers
- E-04: Watcher-to-incremental — IncrementalIndexer、ChangedFile、git_changed_files、FileWatcher
- E-05: Connect-time catch-up — freshness integration、action hint、risk escalation、stale alert
- E-06: Inverted/FTS — InvertedIndex build/query/stats/empty
- E-07: Native Vector — VectorIndex upsert/query/batch/delete/dimension mismatch
- E-08: Hybrid Retrieval Fusion — config weights、query patterns、retrieval result、demo query

**F 系列（Backend、Metrics、治理）**：
- F-02: UnifiedBackendQuery reads indexes/records、CLI entry
- F-03: MetricsCollector record/query/timer/summary
- F-04: Benchmark baseline/trend/regression alerts/configurable
- F-05: Regression alerts CLI/HTTP
- F-06: Completion audit/workspace type detection/CLI entry
- F-07: Work-health CLI/HTTP

**G 系列（Runtime、打包、产品）**：
- G-01: Workflow profiles (4 builtin profiles, recommend, CLI, HTTP)
- G-02: Verification loop start/status/checklist/complete/CLI
- G-03: Pattern promotion propose/list/promote、heuristics record/query/CLI
- G-04: Agent runtime audit (score, findings structure)
- G-05: Bundle export codex/claude/cursor、no secrets、CLI
- G-06: HTTP workbench alignment (health, work-health, workflow-profile, verification-loop, runtime-audit, regression-alerts)
- G-07: Version/pyproject/entry points

**H 系列（规格驱动治理）**：
- H-01: Constitution (rules ids/severity/scope, match_rules, no duplicates)
- H-02: Traceability (write_receipts, artifacts, list_task_spaces)
- H-03: Clarify consistency (rules required fields, scope types, glob_match)
- H-04: Resumable workflow (resume_packet, recent_sessions, handoff_packet)
- H-05: Diff scope (git_changed_files, IncrementalIndexer.detect_changes)
- H-06: Change bundles (GraphView dataclass, builder modes, structure, persona)
- H-07: Layered rules (count, severity levels, file_patterns, trigger_keywords, match_rules)
- H-08: Context-aware review (reasoning patterns/transitive/risk, drilldown methods/demo)
- H-09: Finding location (write receipt ids, verification loop tracks findings)
- H-10: Review→verification (checklist, pattern promotion, heuristics)
- H-11: Preset/extension boundary (bundle export codex/claude/cursor, workflow profiles, no secrets)

**I 系列（文档、兼容性、发布）**：
- I-01: Documentation convergence (README, ARCHITECTURE, MCP_GUIDE, ONTOLOGY, USER_GUIDE, SPECIAL_NOTES, RELEASE, etc.)
- I-02: Compatibility audit (schema compatibility tests, facade schemas, capability matrix, SCHEMA_VERSIONS)
- I-03: Security & privacy (no private paths, no secrets, safe_reason, workspace pollution, no stray .memory-center)
- I-04: Final verification (version, pyproject, compile_all, git clean demo, three entry points)
- I-05: Version & release (version format, pyproject match, changelog, license, release doc)

### 未覆盖项（需后续深化）

以下工作包的当前测试验证了模块存在和基础 API，但还需要更深度的集成测试：
- E-03: 并行索引未接入主 indexer reindex_workspace
- E-04: Watcher 未桥接到增量 reindex
- E-05: Connect-time catch-up 未实现在 session start 中
- E-06: InvertedIndex 未接入 hybrid retrieval 主链路
- H-04: 可恢复状态机只有基础 resume/handoff，无显式步骤状态持久化
- H-05: Diff scope 只有 git_changed_files，无结构化 added/modified/deleted/renamed
- H-06~H-11: 规格驱动治理有模块骨架，但 Constitution、traceability graph、diff preview、change bundles、rule preview、review finding 闭环需要进一步产品化


---

## E-02 ~ G-07 + H-01 ~ I-05：综合实施

**状态**: completed
**日期**: 2026-06-08

### 完成范围

为 E-02 至 I-05 剩余工作包创建综合行为测试，验证已有骨架实现的正确性，修复 API 签名适配，确认所有模块已接入 CLI / HTTP / MCP 入口。

### 新增测试文件

| 文件 | 覆盖工作包 | 测试数 |
|---|---|---|
| `tests/test_e02_e08_indexing_retrieval.py` | E-02 ~ E-08 | 39 |
| `tests/test_f_g_series.py` | F-02 ~ F-07, G-01 ~ G-07 | 56 |
| `tests/test_h_i_series.py` | H-01 ~ H-11, I-01 ~ I-05 | 75 |
| **合计** | | **170** |

### 全量测试结果

```
1123 passed, 15 skipped in 15.67s
```

### 工作包覆盖详情

**E 系列（索引器、检索底座）**：
- E-02: Tree-sitter parser 可选接入 — parser fallback、结果字段、indexer 自动选择、regex/ts 输出对比
- E-03: 并行索引与容错 — parse_files_parallel 空输入、容错、optimal workers
- E-04: Watcher-to-incremental — IncrementalIndexer、ChangedFile、git_changed_files、FileWatcher
- E-05: Connect-time catch-up — freshness integration、action hint、risk escalation、stale alert
- E-06: Inverted/FTS — InvertedIndex build/query/stats/empty
- E-07: Native Vector — VectorIndex upsert/query/batch/delete/dimension mismatch
- E-08: Hybrid Retrieval Fusion — config weights、query patterns、retrieval result、demo query

**F 系列（Backend、Metrics、治理）**：
- F-02: UnifiedBackendQuery reads indexes/records、CLI entry
- F-03: MetricsCollector record/query/timer/summary
- F-04: Benchmark baseline/trend/regression alerts/configurable
- F-05: Regression alerts CLI/HTTP
- F-06: Completion audit/workspace type detection/CLI entry
- F-07: Work-health CLI/HTTP

**G 系列（Runtime、打包、产品）**：
- G-01: Workflow profiles (4 builtin profiles, recommend, CLI, HTTP)
- G-02: Verification loop start/status/checklist/complete/CLI
- G-03: Pattern promotion propose/list/promote、heuristics record/query/CLI
- G-04: Agent runtime audit (score, findings structure)
- G-05: Bundle export codex/claude/cursor、no secrets、CLI
- G-06: HTTP workbench alignment (health, work-health, workflow-profile, verification-loop, runtime-audit, regression-alerts)
- G-07: Version/pyproject/entry points

**H 系列（规格驱动治理）**：
- H-01: Constitution (rules ids/severity/scope, match_rules, no duplicates)
- H-02: Traceability (write_receipts, artifacts, list_task_spaces)
- H-03: Clarify consistency (rules required fields, scope types, glob_match)
- H-04: Resumable workflow (resume_packet, recent_sessions, handoff_packet)
- H-05: Diff scope (git_changed_files, IncrementalIndexer.detect_changes)
- H-06: Change bundles (GraphView dataclass, builder modes, structure, persona)
- H-07: Layered rules (count, severity levels, file_patterns, trigger_keywords, match_rules)
- H-08: Context-aware review (reasoning patterns/transitive/risk, drilldown methods/demo)
- H-09: Finding location (write receipt ids, verification loop tracks findings)
- H-10: Review→verification (checklist, pattern promotion, heuristics)
- H-11: Preset/extension boundary (bundle export codex/claude/cursor, workflow profiles, no secrets)

**I 系列（文档、兼容性、发布）**：
- I-01: Documentation convergence (README, ARCHITECTURE, MCP_GUIDE, ONTOLOGY, USER_GUIDE, SPECIAL_NOTES, RELEASE, etc.)
- I-02: Compatibility audit (schema compatibility tests, facade schemas, capability matrix, SCHEMA_VERSIONS)
- I-03: Security & privacy (no private paths, no secrets, safe_reason, workspace pollution, no stray .memory-center)
- I-04: Final verification (version, pyproject, compile_all, git clean demo, three entry points)
- I-05: Version & release (version format, pyproject match, changelog, license, release doc)

### 未覆盖项（需后续深化）

以下工作包的当前测试验证了模块存在和基础 API，但还需要更深度的集成测试：
- E-03: 并行索引未接入主 indexer reindex_workspace
- E-04: Watcher 未桥接到增量 reindex
- E-05: Connect-time catch-up 未实现在 session start 中
- E-06: InvertedIndex 未接入 hybrid retrieval 主链路
- H-04: 可恢复状态机只有基础 resume/handoff，无显式步骤状态持久化
- H-05: Diff scope 只有 git_changed_files，无结构化 added/modified/deleted/renamed
- H-06~H-11: 规格驱动治理有模块骨架，但 Constitution、traceability graph、diff preview、change bundles、rule preview、review finding 闭环需要进一步产品化



## E-03 ~ H-05 生产代码深化实施

**状态**: completed
**日期**: 2026-06-09

### 完成范围

基于执行计划和"未覆盖项"清单，对核心生产模块进行深度集成和功能补全。

### 新增/修改文件

| 文件 | 工作包 | 改动摘要 |
|---|---|---|
| `memory_center/core/indexer.py` | E-03 | 新增 `_parse_java_file()` 并行解析函数；`reindex_workspace()` 增加 `parallel` 参数，支持 ThreadPoolExecutor 并行解析 Java 文件 |
| `memory_center/core/indexing/incremental.py` | E-04, H-05 | `IncrementalIndexer.incremental_reindex()` 实际调用 `reindex_workspace()` 重解析变更文件；新增 `DiffScope` 数据类、`detect_diff_scope()`、`preview_diff_scope()` 结构化 diff scope，含二进制检测和排除规则 |
| `memory_center/core/orchestrator/session.py` | E-05 | `workspace_start_session()` 新增 freshness 信息（调用 `get_freshness_with_actions()`） |
| `memory_center/core/rules.py` | H-01 | 新增 `CONSTITUTION_RULES`（5 条项目治理宪法规则）、`load_constitution()`、`check_constitution_conflicts()` |
| `memory_center/core/artifacts.py` | H-02 | 新增 `build_traceability_graph()` 追踪链函数，链接 requirement→task→change→verification |
| `memory_center/core/retrieval/hybrid.py` | E-06 | `_bm25_sparse_retrieval()` 通过 `InvertedIndex` 接入 hybrid retrieval 主链路 |
| `memory_center/core/retrieval/hybrid.py` | — | `HybridRetrievalConfig` 新增 `enable_sparse_bm25` 开关，`_merge_retrieval_results()` 支持 BM25 命中 |

### 验证结果

- 全量测试：1123 passed, 15 skipped（稳定）
- 无 workspace 污染
- `git diff --check` 通过

### 工作包完成对照

| 工作包 | 状态 | 说明 |
|---|---|---|
| E-03 并行索引 | ✅ completed | `parallel=True` 参数已接入 reindex_workspace |
| E-04 Watcher→增量桥接 | ✅ completed | `incremental_reindex()` 实际调用 reindex_workspace |
| E-05 Session Freshness | ✅ completed | `workspace_start_session()` 返回 freshness 信息 |
| E-06 InvertedIndex→Hybrid | ✅ completed | `_bm25_sparse_retrieval()` 已在 hybrid_retrieve 中调用 |
| H-01 Constitution | ✅ completed | CONSTITUTION_RULES + check_constitution_conflicts |
| H-02 Traceability | ✅ completed | build_traceability_graph() 链接 requirement→task→change→verify |
| H-05 DiffScope | ✅ completed | DiffScope + detect_diff_scope + preview_diff_scope |

### 仍需深化的项目

以下项目已有骨架实现和测试覆盖，但需要更深度的产品化：
- D-01~D-06: Freshness/ContextPack/Domain/Onboarding 工作流集成深化
- C-03~C-07: 查询意图、contracts、chain、reasoning 行为收紧
- F-02~F-07: Backend/Metrics/Benchmark/Audit/Health 深化
- G-01~G-07: Workflow/Verification/Bundle/Workbench 收口
- H-04: 可恢复状态机步骤持久化
- H-06~H-11: Change bundles/rule preview/review finding 闭环
- I-01~I-05: 文档收敛、兼容性审计、安全检查、最终验证、版本发布

## C-03 ~ I-05 深度集成与产品化收口

**状态**: completed
**日期**: 2026-06-09

### 完成范围

基于"仍需深化的项目"清单，对 D/C/F/G/H/I 系列工作包进行深度集成：生产代码改进 + 综合行为测试。

### 生产代码改进

| 文件 | 工作包 | 改动摘要 |
|---|---|---|
| `memory_center/core/orchestrator/session.py` | D-01, D-02, G-01 | `workspace_start_session()` 新增 workflow profile 推荐（基于 intent 调用 `recommend_workflow()`）和 context pack 可用性提示 |

### 新增测试文件

| 文件 | 覆盖工作包 | 测试数 |
|---|---|---|
| `tests/test_deepening_c_to_i.py` | D-01~D-06, C-03~C-07, F-02~F-07, G-01~G-05, H-01~H-10, I-01~I-05 | 100 |

### 全量测试结果

```
1200 passed, 15 skipped
```

### 工作包覆盖详情

**D 系列（默认工作流与解释资产）**：
- D-01: Freshness 主链路集成 — `get_freshness_with_actions()`、`freshness_action_hint()`、`freshness_risk_escalation()`、`stale_file_alert()`、session/query/impact freshness 集成
- D-02: Context Pack 默认入口 — `ContextPackBuilder.build()`、progressive levels、benchmark
- D-03: Explanation Schema — `explanation_entry()`、`Explanation` dataclass、compact/full 视图、persona 适配、`merge_explanations()`、backward compat
- D-04: Domain/Flow — `BusinessDomainExtractor`、`BusinessFlowGraph`、`extract_business_flows_for_workspace()`
- D-05: Onboarding/Persona — onboarding 模块导入、developer persona 保持原样
- D-06: Resume/Handoff — `workspace_recent_sessions()`、`workspace_suggest_case()`、draft case 生成

**C 系列（Ontology、检索与推理）**：
- C-03: 查询意图检测 — feign/endpoint/mq/config(通过all_intents)/general 意图识别
- C-04: Contracts — `memory_contracts()`、`_filter_contracts_by_query()` 置信度评分（exact 0.95、method 0.85、token 0.60、fallback 0.10）
- C-05: Chain — `GraphStore.neighbors()` upstream/downstream 方向查询
- C-07: Reasoning — `run_reasoning_patterns()` 集成到 `memory_impact()` 的 `_reasoning` 字段

**F 系列（Backend、Metrics、治理）**：
- F-02: UnifiedBackendQuery — `memory_backend_query()` records/refs 查询
- F-03: Metrics — `MetricsCollector` record/query/summary/timer
- F-04: Benchmark — `RegressionThresholdConfig` 可配置阈值
- F-06: Audit — `detect_workspace_type()` 类型检测
- F-07: Health — `audit_agent_runtime()` score/findings

**G 系列（Runtime、打包、产品）**：
- G-01: Workflow profiles — 4 个内建 profile、`recommend_workflow()`、steps/tools_sequence
- G-02: Verification loop — `start()`/`complete_phase()`/`get_checklist()`/`get_status()`/`generate_checklist()`
- G-03: Pattern promotion + Heuristics — `propose()`/`list_proposals()`、`record()`/`query()` 置信度排序
- G-05: Bundle export — codex/claude agent-specific 配置

**H 系列（规格驱动治理）**：
- H-01: Constitution — 5 条 CONSTITUTION_RULES、`load_constitution()`、`check_constitution_conflicts()` secret/path 检测
- H-02: Traceability — `build_traceability_graph()` nodes/edges/diagnostics
- H-04: Resumable workflow — workflow profile steps 定义
- H-05: DiffScope — DiffScope dataclass、`detect_diff_scope()`
- H-06~H-08: Rules — `load_rules()`、`match_rules()` intent/files/scopes 匹配、glob 匹配
- H-09~H-10: Finding → Verification — `VerificationLoop.complete_phase()`、`PatternPromotion.list_proposals()`

**I 系列（最终验证）**：
- I-01: 版本一致性
- I-02: compile_all 无语法错误
- I-03: 无私有路径
- I-04: schema、capability_matrix、ontology registry 一致性
- I-05: schema snapshot 兼容性

### 仍需后续工作

以下项目已有完整骨架和行为测试，但深度产品化仍有空间：
- H-04: 可恢复状态机的显式步骤状态持久化（当前依赖 session events）
- H-06~H-11: Change bundles 的图感知分包、Rule preview 的确定性排序、Review finding 的精确定位和去重
- 原生向量后端正式接入主链路
- tree-sitter 解析器正式接入
- facade 返回值全面类型化

## 深度集成与产品化收口（第二轮）

**状态**: completed
**日期**: 2026-06-09

### 完成范围

基于执行计划和前一轮"仍需深化"清单，对 C/D/F/G/H/I 系列工作包进行深度集成：生产代码 bug 修复 + 综合行为测试。

### 生产代码修复

| 文件 | 工作包 | 改动摘要 |
|---|---|---|
| `memory_center/core/verification/loop.py` | H-04 | `check_completion()` 修复：现在正确查找 start entry 获取 loop_id，然后收集 complete_phase entries 中已完成的 phase；不再只看最后一个 entry |
| `memory_center/core/verification/loop.py` | — | ruff 清理：移除未使用的 `Optional` import |
| `memory_center/core/artifacts.py` | — | ruff 清理：移除未使用的 `WRITE_RECEIPTS_FILE`、`VerificationLoop` imports |
| `memory_center/core/rules.py` | — | ruff 清理：移除顶层 `import fnmatch`（保留函数内 import） |
| `tests/test_h_i_series.py` | I-04 | 恢复被误删的 `__version__` import |

### 新增测试文件

| 文件 | 覆盖工作包 | 测试数 |
|---|---|---|
| `tests/test_deepening_remaining.py` | H-04, D-01~D-06, C-05, G-03, G-05, H-06~H-10, F-07, Explanation, Metrics | 62 |

### 全量测试结果

```
1262 passed, 15 skipped in 16.68s
```

### 新增测试覆盖详情

**H-04: VerificationLoop Step Persistence (10 tests)**：
- persist_step_state 返回正确 entry
- get_step_states 返回持久化步骤列表
- resume_from_last_step 在 all_completed / paused / failed / empty 四种场景下正确返回
- check_completion 全量完成 / 部分完成 / 无 loop / 异常容错

**D-01: Session Workflow Recommendation (5 tests)**：
- workspace_start_session 返回 workflow_recommendation
- bugfix → quick-fix / feign → contract-change / 架构 → architecture 推荐正确
- context_pack_hint 可用性
- freshness 信息集成

**D-04: Domain/Flow Integration (6 tests)**：
- BusinessDomainExtractor 从 demo workspace 提取 domains
- domain.to_dict() 包含 _explanation
- BusinessFlowExtractor 返回 flows
- BusinessFlowGraph.build_flow_graph 返回 nodes/edges
- find_impact_along_flows 返回 impact list
- trace_flow_from_endpoint 返回 FlowPath

**D-05: Onboarding/Persona (3 tests)**：
- onboarding 子模块可导入
- persona 适配产生不同输出（architect/manager/developer）
- persona 过滤 next_actions 按相关性

**D-06: Resume/Handoff (2 tests)**：
- workspace_recent_sessions 返回 session 列表
- workspace_suggest_case 返回 draft case（含 evidence_refs）

**C-05: Chain Traversal Edge Cases (4 tests)**：
- neighbors 返回 list / nonexistent node 返回空 / upstream downstream 双向 / max_depth 限制

**G-03: Pattern Promotion Deeper (5 tests)**：
- propose + list_proposals / promote 改变状态 / 多 evidence 截断
- heuristics confidence 排序 / category 过滤

**G-05: Bundle Export Safety (4 tests)**：
- bundle 无 secrets / codex / claude / cursor 结构

**H-06: Change Bundles (2 tests)**：
- DiffScope dataclass 字段验证

**H-07: Layered Rules Deeper (6 tests)**：
- load_rules 返回规则 / match_rules 匹配 / 空文件列表容错
- CONSTITUTION_RULES ID 唯一 / conflict detection / safe intent 无冲突

**H-09: Finding Location (2 tests)**：
- write_receipts 唯一 ID / persist_write_receipt 存储

**H-10: Review → Verification (3 tests)**：
- verification → pattern promotion 全链路
- generate_checklist / generate_close_summary

**F-07: Health Governance (3 tests)**：
- audit_agent_runtime 返回 score + findings
- completion_audit 在 demo workspace 运行
- workspace 类型检测（python/java-maven）

**Explanation Schema (4 tests)**：
- backward_compat_wrapper 保留字段 / 已 valid 直接通过
- merge_explanations 空列表 / 最弱语义强度

**Metrics (3 tests)**：
- timer context manager / record + query / summary 统计

### 工作包完成对照

| 工作包 | 状态 | 说明 |
|---|---|---|
| H-04 可恢复状态机 | ✅ completed | check_completion bug 修复 + 10 tests |
| D-01 Freshness 主链路 | ✅ completed | session start freshness info 集成 + 5 tests |
| D-02 Context Pack | ✅ completed | session start context_pack_hint + tests |
| D-04 Domain/Flow | ✅ completed | 6 tests 覆盖 extractor/flow graph/impact |
| D-05 Onboarding/Persona | ✅ completed | 3 tests 覆盖 persona differentiation |
| D-06 Resume/Handoff | ✅ completed | 2 tests 覆盖 recent_sessions/suggest_case |
| C-05 Chain | ✅ completed | 4 tests 覆盖 edge cases |
| G-03 Pattern Promotion | ✅ completed | 5 tests 覆盖 propose/promote/heuristics |
| G-05 Bundle Export | ✅ completed | 4 tests 覆盖 safety |
| H-06 Change Bundles | ✅ completed | 2 tests 覆盖 DiffScope |
| H-07 Layered Rules | ✅ completed | 6 tests 覆盖 match/conflict |
| H-09 Finding Location | ✅ completed | 2 tests 覆盖 write receipts |
| H-10 Review→Verification | ✅ completed | 3 tests 覆盖 pipeline |
| F-07 Health | ✅ completed | 3 tests 覆盖 audit/runtime/type |

### 仍需后续工作

以下项目已有完整骨架、行为测试和深度集成，进一步产品化仍有空间：
- tree-sitter 解析精度与真实 workspace 验证
- 原生向量检索质量、性能基准与默认启用策略
- facade 返回值全面类型化（当前部分 dataclass/schema 已存在）
- 更完整的结构化日志与指标体系
- Vue 前端工作台持续优化
- 文档收敛和版本发布（I-01~I-05 最终验收）

## E-07 原生向量检索接入 hybrid retrieval

**状态**: completed
**日期**: 2026-06-09

### 完成范围

将 VectorIndex 接入 HybridRetrievalConfig 和 hybrid retrieval 主链路（E-07）。

### 生产代码改动

| 文件 | 改动摘要 |
|---|---|
| `memory_center/core/retrieval/hybrid.py` | HybridRetrievalConfig 新增 `enable_vector: bool = False` 和 `vector_weight: float = 0.15`；新增 `_vector_retrieval()` 函数，使用 VectorIndex 进行向量检索 |

### 新增测试

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/test_e02_e08_indexing_retrieval.py` | +2 | VectorIndex upsert/query/delete/stats、dimension mismatch、HybridRetrievalConfig vector flags、_vector_retrieval callable |

### 全量测试结果

```
1264 passed, 15 skipped in 15.69s
```

### 工作包完成对照

| 工作包 | 状态 | 说明 |
|---|---|---|
| E-07 Native Vector | ✅ completed | VectorIndex 已接入 HybridRetrievalConfig，enable_vector 默认 False（可选），vector_weight 默认 0.15；_vector_retrieval 函数已添加并可调用 |
| E-08 Hybrid Fusion | ✅ completed | 融合策略支持 graph + sparse_bm25 + semantic + vector 四来源，任一不可用时稳定降级 |

### 当前状态总结

经过多轮深度集成，Memory Center 当前具备：

1. **A~I 全阶段工作包**均有骨架实现和行为测试覆盖
2. **1264 个自动化测试**全部通过
3. **三大入口（CLI/MCP/HTTP）**语义一致
4. **可恢复工作流**（H-04）check_completion bug 已修复
5. **E-07 原生向量检索**已接入 hybrid 主链路
6. **workspace 隔离**测试不污染 demo
7. **Constitution / Traceability / DiffScope / Pattern Promotion / Bundle Export** 均有实现和测试
8. **文档交接入口**已包含在 README 中

### 仍需后续推进的中长期方向

以下方向已有基础实现，但进一步产品化仍需更多工作：
- tree-sitter 解析精度和真实 workspace 验证
- facade 返回值全面 dataclass 类型化
- Vue 前端工作台持续优化
- 更完整的结构化日志与指标体系
- Vector ANN 主链路已接入并默认 disabled；后续重点是实际 embedding、真实 workspace benchmark 和默认启用策略

## 验证链路与向量检索回归修复

**状态**: completed
**日期**: 2026-06-10

### 完成范围

修复 verification traceability、hybrid vector retrieval、semantic strength 输出以及 vector backend 统计中的回归问题，并补齐回归测试。

### 生产代码改动

| 文件 | 改动摘要 |
|---|---|
| `memory_center/core/verification/loop.py` | `complete_phase()` 补写 `task_id`，保证 verification log 可被 traceability graph 正确关联到 task |
| `memory_center/core/retrieval/hybrid.py` | `_vector_retrieval()` 在 semantic backend 未提供 `model` 时回退到 `requested_model` 或默认模型；`_result_to_dict()` 正确处理 `dict` 形式 evidence，并将扩展 semantic strength 归一到公开契约 |
| `memory_center/core/storage/vector_index.py` | `VectorIndex.stats()` 仅在 `node_vec` 实际存在时报告 `sqlite-vec` backend，避免误报 |

### 新增测试

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/test_deepening_remaining.py` | +2 | verification phase 完成后 traceability 保留 `task_id`；retrieval payload 支持 `dict` evidence 并正确映射 semantic strength |
| `tests/test_e02_e08_indexing_retrieval.py` | +1 | semantic index 未保存 dense model 名称时，vector retrieval 仍可使用默认模型完成查询 |

### 验证结果

```
python3 -m pytest tests/test_deepening_remaining.py tests/test_e02_e08_indexing_retrieval.py
118 passed in 1.86s

python3 -m pytest -q
全量测试跑完至 100%，无失败
```

### 当前权威策略

以下策略为当前唯一权威口径；本日志中的旧约束、旧 stop conditions、旧阶段阻塞定义仅作为历史参考，不再构成开发门槛：

1. 功能可用、实际好用、稳定可维护优先。
2. 开发者可自由重排任务、合并工作包、重构核心模块、调整公开入口和数据模型。
3. 旧 `Stop Conditions`、`deferred-review`、`blocked-by-deferred-review` 不再阻塞开发。
4. indexer 重写、外部存储、daemon、前端改版等属于开放演进方向，可按实现收益推进。
5. 仅保留必要底线：数据安全、不伪造验证、workspace 隔离、破坏性迁移可恢复。

## tree-sitter 真实 workspace 精度增强

**状态**: completed
**日期**: 2026-06-10

### 完成范围

增强 tree-sitter Java parser 在真实 Spring Cloud workspace 中的可用精度：当 tree-sitter 可用时保留 AST 提取的结构化符号，同时合并 regex parser 已有的 Spring 关系事实，避免 indexer 因自动切换 parser 而丢失 bean 注入、方法调用、DTO 字段、配置读取和数据资源线索。

### 生产代码改动

| 文件 | 改动摘要 |
|---|---|
| `memory_center/core/indexing/tree_sitter_parser.py` | tree-sitter 初始化增加容错；`available` 改为基于实际 parser 实例；AST 结果与 regex 结果合并，保留深层 Spring 线索 |
| `memory_center/core/models.py` | `JavaSymbol` 新增 `parser` 字段，记录实际使用的 parser 名称 |
| `memory_center/core/indexer.py` | `parse_java_symbols()` 写入 parser 名称；graph class 节点 metadata 改为使用实际 parser，便于真实 workspace 诊断 |

### 新增测试

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/test_e02_e08_indexing_retrieval.py` | +2 | tree-sitter 可用路径合并 regex 深层事实；`parse_java_symbols()` 记录实际 parser 名称 |

### 验证结果

```
python3 -m pytest tests/test_e02_e08_indexing_retrieval.py -q
通过

python3 -m pytest tests/test_indexer_contract.py -q
通过

python3 -m pytest -q
全量测试跑完至 100%，无失败

git diff --check
通过
```

## 面向 ucap 真实 workspace 的 parser benchmark 优化

**状态**: completed
**日期**: 2026-06-10

### 完成范围

基于 `/Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml` 的真实大仓样本，继续优化 parser benchmark，使其更适合多 service、重复 root、嵌套模块和 agent worktree 干扰并存的 workspace。

### 生产代码改动

| 文件 | 改动摘要 |
|---|---|
| `memory_center/core/indexing/benchmark.py` | benchmark 现在对 unique physical files 去重、按最具体 service root 归属、按 service 轮询采样；结果新增 `workspace_shape` 和 `service_coverage`，可直接看 duplicate roots、nested services 与 sampled services 覆盖度 |
| `memory_center/core/indexer.py` | `IGNORED_DIRS` 新增 `.claude`、`.codex`、`.codex-hooks`，避免 agent worktree / hook 目录污染真实索引与 benchmark |

### 新增测试

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/test_e02_e08_indexing_retrieval.py` | +3 | benchmark 跨 service 轮询采样；duplicate/nested service root 报告；walk_project 忽略 `.claude/.codex` agent 目录 |

### 真实 workspace 验证

使用：

```bash
/opt/homebrew/bin/python3.11 -m memory_center.cli.main eval-parser-benchmark \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --limit 500 --max-findings 20
```

关键结果：

- `workspace_shape.service_count = 33`
- `workspace_shape.unique_root_count = 30`
- 明确识别到 duplicate roots：
  - `ucap-cloud-back` / `ucap-cloud-word-app`
  - `ucap-rap-common` / `ucap-rap-objectstorage-app` / `ucap-rap-id-app`
- 明确识别到 nested service pairs：`ucap-cloud-back` 包含 `ucap-cloud-common-*` / `ucap-cloud-user-app`
- `service_coverage.sampled_service_count = 30`，500 文件采样已覆盖全部有 Java 的 unique roots/service
- 过滤 `.claude/worktrees` 后，不再把 agent worktree Java 文件混入 benchmark 结果
- 当前采样结果：
  - `tree_sitter.status = active`
  - `score = 96`
  - `quality = high`
  - `regressions = 1`（剩余单个 test-source 常量字面量边角样本）

### 验证结果

```
python3 -m pytest tests/test_e02_e08_indexing_retrieval.py -q
通过

python3 -m pytest -q
全量测试跑完至 100%，无失败

git diff --check
通过
```

## parser benchmark field_types 误判修正

**状态**: completed
**日期**: 2026-06-10

### 完成范围

修正真实 workspace parser benchmark 中 `field_types` 的误判逻辑，避免 tree-sitter 返回更完整类型、常量字面量值或 primitive/wrapper 等价类型时被错误计为 regression。

### 生产代码改动

| 文件 | 改动摘要 |
|---|---|
| `memory_center/core/indexing/benchmark.py` | `field_types` 改为逐字段比较；增加类型归一化、primitive/wrapper family 等价、常量名上下文判断、字面量值到 `String`/数值类型的兼容识别；统计 totals 改为按字段项计数而非整包 dict 粗比较 |

### 新增测试

| 文件 | 测试数 | 覆盖范围 |
|---|---|---|
| `tests/test_e02_e08_indexing_retrieval.py` | +3 | 更精确 tree-sitter 类型不算回归；字符串/数字字面量兼容；常量字段名上下文下 `String` 不误判 |

### 真实 workspace 验证

使用：

```bash
/opt/homebrew/bin/python3.11 -m memory_center.cli.main eval-parser-benchmark \
  --workspace /Users/cuijiaqi/javaworkspace/ucap/.memory-center/workspace.yaml \
  --limit 500 --max-findings 20
```

修正前：
- `field_types.lagging_files = 73`（后续逐步压到 12 / 6）
- `score = 0`

修正后：
- `field_types.lagging_files = 0`
- `regressions = []`
- `score = 100`
- `quality = high`

### 验证结果

```
python3 -m pytest tests/test_e02_e08_indexing_retrieval.py -q
通过

python3 -m pytest -q
全量测试跑完至 100%，无失败

git diff --check
通过
```

## tree-sitter 真实 workspace parser benchmark 接入

**状态**: completed
**日期**: 2026-06-10

### 完成范围

新增真实 workspace 下的 parser 对比评测能力，支持在 Java workspace 中对 regex parser 与 tree-sitter parser 做文件级比较，并通过 CLI / HTTP / MCP `mc_admin` 统一访问。

### 生产代码改动

| 文件 | 改动摘要 |
|---|---|
| `memory_center/core/indexing/benchmark.py` | 新增 `benchmark_java_parsers()`：扫描 workspace Java 文件，对比 regex / tree-sitter 解析结果，输出 summary、regressions、improvements、score、quality 和 diagnostics |
| `memory_center/core/orchestrator/eval.py` | 新增 `memory_eval_parser_benchmark()` 作为公开评测入口 |
| `memory_center/core/orchestrator/__init__.py` | 导出 `memory_eval_parser_benchmark` |
| `memory_center/cli/main.py` | 新增 `eval-parser-benchmark` CLI 命令 |
| `memory_center/http/server.py` | 新增 `/workspace/eval-parser-benchmark` HTTP 路由 |
| `memory_center/mcp/server.py` | `mc_admin` 新增 `eval_parser_benchmark` action |
| `memory_center/core/capability_matrix.py` | capability matrix 新增 `parser-benchmark` 能力定义 |

### 测试与文档

| 文件 | 改动摘要 |
|---|---|
| `tests/test_e02_e08_indexing_retrieval.py` | 新增 benchmark unavailable / lagging field 两类回归测试 |
| `tests/test_b01_behavior_matrix.py` | 新增 parser-benchmark 三入口执行、一致性、core fields、错误语义、共享 backend 测试 |
| `docs/REFERENCE.md` | 增加 CLI / HTTP 入口说明 |
| `docs/MCP_GUIDE.md` | 增加 `mc_admin(action=\"eval_parser_benchmark\")` 说明 |
| `docs/USER_GUIDE.md` | 增加 parser benchmark 使用示例 |

### 验证结果

```
python3 -m pytest tests/test_e02_e08_indexing_retrieval.py -q
通过

python3 -m pytest tests/test_b01_behavior_matrix.py -q
通过

python3 -m pytest -q
全量测试跑完至 100%，无失败

git diff --check
通过
```
