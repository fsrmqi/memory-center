# Changelog / 更新日志

本更新日志按**版本号**归纳，优先记录：

- 用户可感知的新能力
- 重要行为变化
- 明确修复的真实 bug

## 3.1.1

### 主链路收口 / Main Workflow Stabilization

- 升级版本号到 `3.1.1`
- 延续 v3.1 系列对 V3 / Next Phase 能力的产品化收口
- 重点面向 freshness、context、impact、business flow、retrieval、CLI / MCP / HTTP 一致性等主链路稳定性优化
- 保持 MCP facade schema 向后兼容
- 修复 `business-flow` / `business-flow-impact` 的 CLI、MCP、HTTP workspace 解析一致性，避免把 `workspace.yaml` 当 SQLite graph db 打开
- 修复 `memory_context` 风险分析调用不存在的 `RiskAnalyzer` 导致 `risk_patterns` 静默为空的问题，改为 `RiskPatternEngine` 并返回可见 diagnostics
- 修复 hybrid vector retrieval 的导入 / store 构造问题，并在返回中增加 `retrieval_diagnostics.vector`
- 修复 `regression-alerts` 三入口错误传入 `benchmark_name` 的问题，统一为 `threshold_pct`
- 增加 Next Phase 入口矩阵测试，覆盖 context-pack、freshness、onboard、business-flow、business-flow-impact、runtime-audit、regression-alerts
- 调整测试用例，避免直接写入仓库内 `examples/spring-cloud-demo/.memory-center` 生成物

## 3.0.0

### NEXT_PHASE_MASTER_PLAN.md 全量实现 / Full Implementation

#### Phase A: Ontology 约束层 / Ontology Constraint Layer
- `hybrid_retrieve` 返回结果增加 `semantic_strength` (fact/inferred/derived) 和 `confidence_label` (high/medium/low)
- `_result_to_dict` 支持 dict 和 str 两种 evidence 格式的语义强度推断
- `_EDGE_SEMANTIC_STRENGTH` 映射从 `docs/ONTOLOGY.md` 定义的语义强度已接入检索结果

#### Phase B: 检索质量收口 / Retrieval Quality
- `detect_query_intent` 保持 Feign/MQ/Endpoint 的高优先级区分
- `hybrid_retrieve` 返回中增加 ontology-aware 语义强度字段
- evidence 解析支持字符串和字典两种格式，避免运行时类型错误

#### Phase C: Benchmark 趋势化 / Benchmark Trending
- `check_regression_alerts` 接入 MCP `mc_admin` (action: regression_alerts)
- `check_regression_alerts` 接入 CLI 命令 `regression-alerts`
- `check_regression_alerts` 接入 HTTP 路由 `/workspace/regression-alerts`

#### Phase D: Completion Audit 产品化 / Completion Audit
- `detect_workspace_type()` 已实现并可用于类型化审计规则

#### Phase E: Timeline/Ref/Task 体验增强
- drill-down 导航已接入 CLI / MCP / HTTP 三入口

#### Phase F: SQLite 主读路径
- `UnifiedBackendQuery` 统一后端查询已落地

#### Direction 1: Inverted Retrieval
- `InvertedIndex` 已实现并可用于稀疏检索

#### Direction 2: Graph Reasoning
- `reasoning/patterns.py`, `reasoning/transitive.py`, `reasoning/risk.py` 已实现

#### Direction 3: Indexer Upgrade
- `TreeSitterJavaParser` 已实现（CG-1），带 `RegexJavaParser` 回退
- tree-sitter 已接入 indexer.py 自动检测

#### Direction 4: Type Safety & Observability
- `MetricsCollector` 结构化指标收集器已实现（JSONL 后端，线程安全）
- `Explanation` schema 支持 persona 适配 (developer/architect/manager)

#### CG 外部思想吸收 / External Absorption (codegraph)
- **CG-1**: Tree-sitter Java Parser 已实现
- **CG-2**: `InvertedIndex` 倒排检索已实现
- **CG-3**: Freshness banner 已接入查询链路
- **CG-4**: `trigger_incremental_reindex` watcher-to-reindex 桥接已实现
- **CG-5**: `ContextPackBuilder` 已接入 MCP `mc_context_pack`
- **CG-6**: `benchmark_context_pack` 已实现
- **CG-7**: Workspace daemon 可行性研究（文件已存在）

#### UA 外部思想吸收 / External Absorption (Understand-Anything)
- **UA-1**: `ArchitectureTourGenerator` 已接入 MCP `mc_onboard`、CLI、HTTP
- **UA-2**: `Explanation` schema 已实现，支持 persona 适配
- **UA-3**: `BusinessFlowExtractor` + `BusinessFlowGraph` 已实现并接入 CLI/MCP/HTTP
- **UA-4**: `find_impact_along_flows` 流感知影响分析已实现
- **UA-5**: `adapt_for_persona` persona 视角输出已实现
- **UA-6**: freshness watcher 支持增量知识刷新

#### ECC 外部思想吸收 / External Absorption (ECC)
- **ECC-1**: `WorkflowProfile` 工作流协议档案已实现 (quick-fix/contract-change/long-task/architecture)
- **ECC-2**: `VerificationLoop` 验证闭环已实现 (analyze → checklist → verify → close)
- **ECC-3**: `PatternPromotion` 模式晋升管道已实现 (propose → promote → list)
- **ECC-4**: `HeuristicsRegister` 学习启发式注册已实现 (record → query → update_confidence)
- **ECC-5**: `audit_agent_runtime` Agent 运行时审计已实现
- **ECC-6**: `generate_agent_bundle` Agent 使用包导出已实现 (codex/claude/cursor)

#### MCP 新增 Actions
- `verification_loop`, `pattern_promotion_propose`, `pattern_promotion_list`, `pattern_promotion_promote`
- `heuristics_query`, `heuristics_record`, `workflow_profile`, `workflow_recommend`
- `bundle_export`, `runtime_audit`, `explanation`
- `business_flow`, `business_flow_impact`, `metrics_summary`, `regression_alerts`

#### CLI 新增命令
- `verification-loop`, `pattern-promotion`, `heuristics`, `workflow-profile`, `workflow-recommend`
- `bundle-export`, `runtime-audit`, `explanation`, `business-flow`, `business-flow-impact`
- `metrics-summary`, `regression-alerts`

#### HTTP 新增路由
- `/workspace/verification-loop`, `/workspace/pattern-promotion`, `/workspace/heuristics`
- `/workspace/workflow-profile`, `/workspace/workflow-recommend`, `/workspace/bundle-export`
- `/workspace/runtime-audit`, `/workspace/explanation`, `/workspace/business-flow`
- `/workspace/business-flow-impact`, `/workspace/metrics-summary`, `/workspace/regression-alerts`
- `/workspace/onboard`, `/workspace/context-pack`, `/workspace/freshness`
- `/workspace/group-status`, `/workspace/group-query`, `/workspace/group-impact`, `/workspace/group-chain`

#### Vue 前端新增页面
- `VerificationView.vue` — 验证闭环、工作流档案、运行时审计
- `FlowView.vue` — 业务流提取与影响分析
- `MetricsView.vue` — 结构化指标总览
- `OnboardView.vue` — 架构导览与新人入职

#### Bug 修复 / Bug Fixes
- 修复 `flow.py` 语法错误：合并重复的 `from __future__ import annotations`
- 修复 `_result_to_dict` 中 evidence 为字符串时的 AttributeError
- 修复 HTTP server 新路由中 `group_status` 等变量被局部 import 遮蔽导致的 UnboundLocalError

## 2.3.0

- **Vue 前端工作台**
  - 新增 `web/` 目录，Vue 3 + Vite + vue-router + axios
  - 覆盖 14 个页面：Workbench / Dashboard / Continuity / Task / Query / Impact / Group / Timeline / Receipts / Usage / Backend / Freshness / Audit / Health
  - HTTP 服务器自动在 `/app` 路径托管构建后的 Vue SPA
  - 开发模式支持热更新：`cd web && pnpm dev`
- **跨项目查询性能优化**
  - `group_status` / `group_query` 改为 `ThreadPoolExecutor` 并行执行
  - `resolve_group` 和 `_load_group_data` 增加 15 秒 TTL 缓存
  - 大幅减少多项目场景下的串行等待时间
- **跨项目链路可解释性增强**
  - `group_query` / `group_impact` / `group_chain` 返回中新增 `top_bridges`、`bridge_reasons`、`cross_workspace_path_hint`
  - 让用户和模型理解跨项目关联的原因
- **文档更新**
  - README.md 增加 Vue 前端安装和使用说明
  - ARCHITECTURE.md 增加 Vue 前端模块架构
  - NEXT_PHASE_MASTER_PLAN.md 标记已实现项

## 2.2.0

- **NEXT_PHASE 已实现能力完成收口**
  - 完成并接入主链路：hybrid retrieval、benchmark trending、unified backend query、drill-down navigation、completion audit
  - CLI / MCP / HTTP 入口同步可用
- **混合检索**
  - 新增 `memory_center/core/retrieval/hybrid.py`
  - 支持 graph + sparse + semantic 三路混合检索
  - 增加查询意图自动检测与渐进式摘要输出
- **基准趋势**
  - 新增 `memory_center/core/benchmark/trending.py`
  - 支持 benchmark baseline、trend、回归检测和健康报告
- **统一后端查询**
  - 新增 `memory_center/core/backend/query.py`
  - 提供 `UnifiedBackendQuery`，统一索引、记录、引用和聚合查询
- **钻取导航**
  - 新增 `memory_center/core/navigation/drilldown.py`
  - 支持 `drill_timeline`、`drill_task`、`expand_ref`、handoff context 构建
- **完成审计**
  - 新增 `memory_center/core/audit/completion.py`
  - 支持文档、测试、实现、设计一致性检查与建议生成
- **文档结构继续收敛**
  - 删除阶段性文档 `docs/V3_PLAN.md`
  - 删除阶段性文档 `docs/NEXT_PHASE_IMPLEMENTATION_REPORT.md`
  - 删除单版本文档 `docs/CHANGELOG_v2.2.0.md`
  - 剩余计划统一并入 `docs/NEXT_PHASE_MASTER_PLAN.md`
- **本体与治理方向转入下一阶段**
  - 近期重点转为 ontology、检索质量继续收口、SQLite 主读路径推进、audit 产品化与 drill-down 体验增强

## 2.1.8

- **发布版本更新**
  - Python 包版本更新为 `2.1.8`

## 2.1.7

- **安装脚本默认目标修正**
  - 在本地仓库中执行 `bash install.sh` 时，默认安装当前 checkout，而不是回退到远端 GitHub 仓库
  - 仍然保留 `curl ... | bash` 场景下默认从 GitHub 安装的行为
  - 安装脚本会自动优先选择本机可用的 `python3.10+`，并按当前 package target 重新安装已有 `pipx` 环境
- **发布版本更新**
  - Python 包版本更新为 `2.1.7`

## 2.1.3

- **文档体系重构**
  - 补回根目录维护者文档：`TECHNICAL_GUIDE.md`、`NEXT_PHASE_MASTER_PLAN.md`
  - `README.md`、`docs/ROADMAP.md`、`docs/RELEASE.md` 与技术/计划文档重新串联
  - 调整文档分层：对外使用线与对内维护线并存

## 2.1.2

- **文档结构收敛**
  - 主文档收敛为 7 份核心 docs
  - `README`、`ROADMAP`、`CHANGELOG` 的角色重新划分
  - 清理重复、阶段性和过细的旧文档入口

## 2.1.1

- **Hook 默认策略收口**
  - `user_prompt_submit` 默认禁用
  - Claude Code / Codex adapter 默认不再生成 `UserPromptSubmit`
  - 避免普通自然语言请求（如“继续”“下一步”“同步下文档”）被建议型 Hook 打断
- **Hook 配置行为修复**
  - `enabled: false` 现在会被 runner 和 adapters 一起真正视为禁用
  - `tool_matcher` 统一从 `filter.tool_matcher` 读取，配置语义与执行语义一致

## 2.1.0

- **agentmemory 风格 token benchmark**
  - 新增 `memory_eval_token_benchmark`
  - 覆盖 7 个高频函数：`sniff / status / resume / recent_evidence / continuity / dashboard / handoff`
  - 对 `small / medium / large` 三档预算输出按函数对比表和总 token 统计
- **Top-K evidence 策略**
  - `workspace_recent_evidence` 的 compact 模式采用显式 top-K
  - `small=3`、`medium=5`、`large=10`
  - 排序优先级为 `ref_id + summary + payload_ref/receipt_ref` 的信号丰富度，再按时间倒序
- **SQLite 后端读路径扩展**
  - `_resolve_memory_ref` 优先复用 backend 读取 session events / write receipts
  - timeline 和部分高频读路径进一步优先复用 SQLite backend

## 2.0.11

- **默认 compact 与短引用收口**
  - 全部 7 个高频大返回默认 `view=compact`
  - `workspace_recent_evidence` 补齐 `view=compact|full`
  - `memory_ref_get` 增加 `timeline_ref`
- **UI / workbench 增强**
  - dashboard / continuity 增加 `view / budget` 切换
  - `/ui/ref`、`/ui/timeline`、`/ui/task` 等页面钻取能力增强
  - guided tour、next action 卡片、cross-page links
- **Hook / adapter 增强**
  - Codex adapter 生成脚本可执行化
  - Cursor adapter 补充 MCP 命令与 quick reference

## 2.0.10

- `recent_evidence` 的 compact/full 与 gain 收口
- 短引用体系进一步补齐
- ref → timeline 反向导航落地

## 2.0.9

- Hook 资源模板与打包问题修复
- 默认 hooks 配置修正
- 核心数据处理与稳定性增强

## 2.0.5

- token gain 跟踪与评测
- Hook runner / adapters 基础能力
- 工作流编排评测与预算优化
- SQLite 优先读取开始接入更多路径

## 2.0.4

- 增量索引第一阶段
  - `--project`
  - `--path`
  - `--changed-only`
- `work-*` 一键工作流命令
- workbench / backend query 第一阶段

## 2.0.2

- regression suite
- compact / full
- budget
- short refs
- `memory_ref_get / batch`

## 2.0.0

- continuity / handoff / dashboard 主链路成型
- write receipt / write judge / write plan / write execute
- 多根目录 workspace 支持
- 工具使用报告与 lookup hint

## 1.3.0

- 共享工件与 sync sniff / sync case
- 自动同步模式
- 更完整的代码搜索、符号解析和调用链分析

## 1.0.0

- 项目正式命名为 **Memory Center / 记忆中心**
- Python 包统一为 `memory_center`
- CLI / MCP 命令统一为 `memory-center` / `memory-center-mcp`
- README 和公共文档体系初步建立

## 0.2.0

- Public GitHub-ready repository structure
- Apache-2.0 license, templates, basic docs, CI

## 0.1.0

- Initial MVP with workspace indexing, MCP tools, default rules and agent instructions
