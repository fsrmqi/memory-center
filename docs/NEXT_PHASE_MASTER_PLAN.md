# Next Phase Master Plan / 下一阶段唯一开发路线

> 本文件是 Memory Center 当前唯一活跃开发路线。
>
> This is the single active development roadmap for Memory Center.

> 文档入口与 active/historical 状态请同时参考 [DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md)。
>
> Also see [DOCS_STATUS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DOCS_STATUS.md) for the current documentation entrypoints and active-vs-historical status.

---

## 1. 文档定位 / Scope

本文件整合并替代旧版执行计划、superpowers 演进计划和旧版 master plan；这些历史来源已归档到 `docs/archive/`，不再作为独立活跃文档维护。

This file consolidates and replaces the older execution plan, superpowers evolution plans, and the previous master plan. Those historical sources have been folded into this document and are no longer maintained as separate files.

旧计划中的已完成任务不再作为待办重复跟踪；未完成方向按当前代码和 benchmark 重新排序。

如果要看当前系统怎么用，优先读：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)
- [docs/TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_GUIDE.md)
- [docs/references/codebase-memory-mcp.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/references/codebase-memory-mcp.md)

---

## 2. 当前判断 / Current Assessment

当前重点不再是“补一个新工具”，而是把已有能力收敛成更快、更准、更少误导 Agent 的主链路。

当前未完成方向：

1. **可信交互历史与图谱可解释性**：统一结论证据等级，补齐运行时检查、会话版本/验证快照、后台任务进度和按需子图导出。
2. **真实任务质量运营**：积累经过人工验证的任务回放，仅依据确认结果优化检索策略与下一步建议。
3. **Java 解析与调用解析精度**：从真实未解析分类中补充逻辑锚点样例，只修复可复现的具体误判。
4. **真实性能与重建可靠性**：持续积累真实工作空间的冷/热查询、增量索引和并发重建数据，使用基准决定优化优先级。

---

## 3. 开发优先级 / Development Priorities

### P1：Java Parser / Call Resolver 真实精度深化

目标：让 method walkthrough 和跨项目链路在真实 Spring Cloud 场景下更稳。

任务：

1. 从真实未解析分类中选择最高频且可复现的一类，补充 3-5 个只含逻辑锚点的私有 case。
2. 每次仅修复一个明确的 parser 或 resolver 缺口，不以宽泛 fallback 换取表面召回率。
3. 将每个误判转成可复跑 case，并在 CLI、MCP、HTTP 中保留失败原因和缺失锚点。

验收：

- 新增 case 不得降低既有真实 case 的 anchor recall、edge recall 或 forbidden hit 指标。
- 每个失败 case 都能定位到 parser、resolver、graph 或 retrieval 中的具体一层。

### P2：Retrieval / Reasoning 质量闭环

目标：让 `mc_lookup(auto)`、walkthrough、impact、context pack 在真实任务中更少误判、更少重复搜索。

任务：

1. 用真实 session replay 验证 adaptive retrieval policy，不再用 examples 作为主要验收；每个版本至少比较 adoption、bypass、unobservable 和 Golden 指标。
2. 对每个 replay 记录人工确认的命中/偏题结果；只将确认结果写入 retrieval-source feedback。
3. 每次权重变更后运行 Golden、replay trend、cold/hot query baseline；任一质量门禁退化即回滚。

验收：

- 完整链路 case 不再建议重复全局搜索
- partial / stale case 明确指出缺失层或 stale 文件
- same input 产生确定性 retrieval policy
- token 和 latency 不低于真实基线

### P2.5：可信交互历史与图谱可解释性（下一阶段）

目标：将任务历史从调用日志提升为可复现、可归因、可审查的工程证据闭环，降低真实链路分析中的误判风险，并让长任务的状态和结果对使用者可见。

设计边界：

- 参考 Graphify 的“抽取事实与推断结论分层”思想，但不采用其放弃向量检索的路线；Memory Center 继续保留混合检索和按需索引能力。
- 参考 Grok Build 的运行时检查、会话恢复与结构化进度事件思想，但不引入其终端界面、运行时或产品依赖。
- 不保存原始对话正文、源码正文或工具载荷；继续遵守本地优先、脱敏、一个月保留期和十万条上限。

#### P2.5-1：统一证据等级

- 在图边、查询结果、分析报告、案例和交互历史中增加兼容的 `evidence_level`：`EXTRACTED`、`INFERRED`、`AMBIGUOUS`、`VERIFIED`。
- 所有摘要输出同时展示证据来源、等级统计和推断边界；不得把推断结论表述为已验证事实。
- 仅当存在验证命令结果、人工确认或可追溯运行结果时，才允许标记为 `VERIFIED`。

验收：既有 MCP 字段保持兼容；真实链路输出可以区分事实、推断和待确认项；新增单元测试覆盖等级传播与降级规则。

#### P2.5-2：运行时配置检查

- 新增 `memory-center inspect`，集中展示实际生效的工作空间、MCP 可执行文件与版本、AGENTS 指令、Hook、会话绑定、记忆生命周期、近期效果摘要和索引活动代际。
- 对配置陈旧、Hook 未安装、可执行文件版本不一致、会话未绑定等状态给出可执行的修复建议。
- 输出默认脱敏，不展示完整私有路径、原始提示词或敏感配置值。

验收：在真实工作空间可一次看清宿主实际看到的运行状态；故障场景能够给出明确原因和修复命令。

#### P2.5-3：会话代码版本与验证快照

- 在 `mc_start` 记录 Git 分支、提交标识和工作区脏文件计数；非 Git 工作空间自动跳过。
- 在 `mc_close` 关联验证命令、退出状态、结果摘要和任务结论，形成“调用 -> 改动 -> 验证 -> 结果”的最小证据链。
- 对失败、回滚、重新打开的任务保留规范化状态，支持后续效果分析。

验收：单次会话回放可定位所对应的代码版本和验证结果；未配置 Git 或验证命令时不影响主流程。

#### P2.5-4：后台任务阶段进度协议

- 为重建、增量索引、图谱计算和基准测试建立版本化进度事件：`queued`、`scanning`、`parsing`、`graph`、`retrieval`、`semantic`、`finalizing`、`failed`。
- 进度统一持久化并可通过 HTTP、MCP 后台任务和 Workbench 读取；同一任务只能有一个权威状态源。
- 对高频进度事件限流、合并和保留诊断信息，支持失败和取消后的可解释反馈。

验收：长任务不再无输出等待；进度、失败原因和最终统计一致，且不会显著影响索引热路径。

#### P2.5-5：架构社区与按需子图导出

- 在离线或显式任务中计算模块/服务社区与高中心性节点，避免影响日常检索延迟。
- 支持围绕查询链路导出受限子图（JSON、HTML、Markdown），携带证据等级、决策和规则/ADR 引用。
- 默认不导出全量图，不导出受保护的原始数据；由查询范围和权限策略约束输出。

验收：可为一次链路分析生成小而可读的证据子图；导出不会拖慢普通 MCP 查询，也不会泄露受保护内容。

#### P2.5-6：真实工作空间可复现基准

- 在真实工作空间持续记录冷/热查询 P50、P95、增量索引开销、输出 Token、证据等级覆盖率和人工复核的错误事实率。
- 将交互历史中的采纳、验证、结果和回退纳入效果指标，但不以模拟数据或外部项目宣传数据作为发布门槛。
- 每次性能优化都提供前后对比、数据范围和回归结论。

验收：每项性能或检索优化都有可复现的真实数据证据；基准报告可直接用于版本发布门禁。

### 外部方案参考边界

- Graphify 与 Grok Build 仅作为 P2.5 的架构参考，不引入其运行时依赖、命令行实现或界面形态。
- 所有吸收项必须先经过真实工作空间基准和兼容性验证，再进入默认行为或发布门禁。

---

## 4. 执行原则 / Execution Rules

这些原则从旧版执行计划合并而来，后续不再单独维护执行计划文档。

1. 功能真实可用、用户实际好用优先于遵守旧模块边界和旧任务顺序。
2. 可以重排阶段、合并任务、替换旧实现和重构核心模块。
3. 每项完成的能力应有测试、入口验证和文档同步。
4. CLI / MCP / HTTP 可以针对入口场景优化，但核心语义、结果结构和错误语义必须可解释。
5. 任何主链路 `except Exception` 都不能静默吞掉真实失败，必须返回 diagnostics、fallback reason 或明确降级说明。
6. 新入口必须优先复用 core 层能力，不在 CLI / MCP / HTTP 三处复制决策逻辑。
7. 输入 workspace 时，公共入口默认接收 `workspace.yaml` 或目录，再通过 `WorkspaceStore` 解析 graph / memory / artifact 路径。
8. 测试不得直接写入仓库内 `examples/*/.memory-center` 的运行态 graph / memory 生成物；需要写入时复制到 `tmp_path`。
9. 公开 examples 只做 smoke / fixture，真实完成判断必须优先使用用户提供的真实场景。
10. 不提交私有 workspace 的 `.memory-center/index`、`.memory-center/memory`、私有 cases、私有 baseline、完整 payload、真实路径、内部服务名或密钥。

### 三入口一致性 / CLI MCP HTTP Consistency

下列能力继续保持三入口一致性测试和文档同步：

- `context-pack`
- `freshness`
- `onboard`
- `domain`
- `business-flow`
- `business-flow-impact`
- `runtime-audit`
- `regression-alerts`
- `eval-golden`
- `eval-java-call-resolution`

验收要求：

- 同一 workspace / query / seed 在 CLI、MCP、HTTP 中返回核心字段一致。
- 错误使用统一错误模型：`invalid_input`、`not_found`、`unavailable`、`conflict`、`internal_error`。
- MCP schema 只能 additive 兼容扩展，不能破坏既有 tool 参数。

### Ruff 与代码治理 / Ruff and Code Governance

当前 Ruff 方向不再作为主路线最高优先级，但保留为持续治理要求：

- 基础门禁 `F/E9/I001/B006/B008/B904` 必须持续通过。
- `UP035 / UP006 / UP045 / UP007` 等现代化项按目录小批量处理，避免大 churn。
- `B007`、`B905` 这类语义项必须手工判断，不能机械改 `_` 或盲目加 `strict=True`。
- Ruff 清理不能替代真实场景 gate；它只证明代码卫生，不证明用户体验完成。

### 开放方向 / Open Directions

以下方向不再视为禁区。只要能明显改善真实用户问题，可以直接调研、原型验证并实施：

1. 重写 indexer，提高索引精度、增量性能和语言扩展能力。
2. 引入可选图数据库、向量数据库或搜索后端。
3. 重新设计 JSONL、SQLite、graph 和 memory 存储结构，并提供迁移工具。
4. 增加 daemon、后台任务、自动监听和持续索引能力。
5. 重做前端、可视化、配置流程和排障体验。
6. 合并或删除重复入口，重新设计 MCP、CLI、HTTP 的产品交互。
7. 引入新的语言支持、框架适配器、评测系统和 Agent 工作流。

实施前至少回答：

- 解决了哪个真实用户问题。
- 相比当前实现，体验、准确率、性能或维护性提升在哪里。
- 最小可用版本如何验证。
- 数据迁移、兼容和回滚如何处理。
- 后续维护成本是否可接受。

注意：开放方向不依赖外部项目清单驱动；后续立项必须来自真实使用问题、benchmark、gate 或当前架构缺口。

---

## 5. 统一验收门禁 / Unified Gates

后续任何“完成”判断必须优先使用真实场景：

- 默认真实 workspace 使用本地私有 `workspace.yaml`，文档只写 `<private-real-workspace>` 占位。
- 公开 examples 只作为 CI smoke test、单元测试 fixture、公开复现模板。
- 若真实 cases 缺失，结果必须标记为 `real_case_missing`，不能用 examples 指标替代真实验收。
- 若性能 baseline 缺失，可以用当前已验收版本生成新基线；后续版本只能更好，不能比基线差。

最低检查：

```bash
python3 -m compileall -q memory_center tests
git diff --check
pytest -q
scripts/verify_real_ucap.sh
```

真实场景 gate 最少包含：

- Golden anchor recall
- Golden edge recall
- forbidden hit rate
- Java call resolution recall
- walkthrough invalid search suggestion count
- median / p95 latency
- token estimate
- parser diagnostics
- completion status

---

## 6. 非目标 / Non-Goals

- 不删除 regex parser；它仍作为 fallback 和 differential oracle。
- 不默认开启 vector retrieval；真实质量和性能基准稳定后再讨论默认策略。
- 不一次性把 JSON / JSONL / Markdown 事实源迁移到 SQLite。
- 不新增平行 MCP facade tool；优先扩展现有 `mc_lookup`、`mc_analyze`、`mc_admin`。
- 不为了类型化破坏现有 dict 返回和 MCP tool schema。
- 不把私有 workspace 生成物、源码片段、真实路径或密钥写进仓库文档。

---

## 7. 下一步建议 / Recommended Next Step

下一阶段优先进入 **P2.5**，先完成“统一证据等级 + 运行时配置检查”。

原因：4.1.4 已经能够采集 Hook、MCP 调用、会话摘要和效果数据；在继续扩大图谱分析、后台任务和 Workbench 之前，必须先让使用者能判断结论是否可信、运行配置是否真正生效。否则更复杂的分析只会放大不可见的误差和排障成本。

建议实施顺序：

1. 建立 `evidence_level` 兼容字段和传播规则，复用现有事实/推断/派生判断，不改变既有 MCP 契约。
2. 实现 `memory-center inspect`，将 MCP、Hook、AGENTS、会话、生命周期和索引状态集中成一个脱敏诊断视图。
3. 在真实工作空间验证证据标签和诊断输出，再补齐 Git/验证快照。
4. 最后接入后台进度协议、按需子图导出和社区计算，并以真实基准决定是否扩大默认范围。
