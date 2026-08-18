# Archify 深度调研与吸收提案 / Archify Deep Research & Absorption Proposal

日期：2026-08-18（同日复核修订）
调研对象：[tt-a1i/archify](https://github.com/tt-a1i/archify) v2.15（本地副本 `/Users/cuijiaqi/Ai-common-skills/archify`，源码位于 `archify/` 子目录）
状态：调研完成。初版提案 4 项，经代码复核后收敛为 2 项候选 + 2 项明确不吸收（见 §3 复核后明确不吸收），待评审（未排期）。

## 1. 调研背景 / Background

Archify 是一个 agent skill：输入自然语言或 Mermaid，产出**带类型化 JSON IR、通过确定性校验后原子交付**的单文件交互式架构图（architecture / workflow / sequence / dataflow / lifecycle 五类）。它与 memory-center 同属"agent 基础设施"，其工程纪律（typed IR、fail-closed 交付、诚实回执）与本仓库哲学高度同构。本文记录对其实现机制的深度调研，并给出有边界的吸收提案。

本文只做机制吸收评估；**不引入 Archify 依赖、不复制其渲染器**。

## 2. 机制调研结论 / Mechanism Findings

### 2.1 Typed JSON IR + Schema 驱动校验

- 每类图有独立 JSON Schema（2020-12，`schemas/*.schema.json`），公共定义在 `common.schema.json`；全部 `additionalProperties: false`，字段枚举封闭。
- `scripts/generate-validators.mjs` 把 schema 编译为 `generated-validators.mjs`，校验零运行时依赖。
- Schema 错误不直接抛 ajv 原文，而是逐条翻译成结构化诊断：`code = schema/<keyword>`，`subject` 带 JSON Pointer 且**自动标注最近的 id/label 身份**（`/nodes/3 (id: "router") /label`），`supportedFixes` 按 keyword 映射为可直接执行的修复动作（见 `renderers/shared/validator.mjs`）。

→ 启发：IR 先于渲染；校验错误必须翻译成"改哪个字段、怎么改"，而不是堆栈。

### 2.2 Repair Receipt（修复回执）

- 统一诊断形状（`renderers/shared/diagnostics.mjs`）：`{ code, severity, message, subject, evidence, supportedFixes[] }`。
- **任何失败路径都产出恰好一个 JSON 对象**：渲染器内部崩溃由 `installRendererDiagnosticBoundary` 的 uncaughtException 边界兜底，写 JSON 到 stderr 后退出，绝不让 agent 拿到 Node 堆栈猜测。
- 未分类失败有 fallback 分类（`input/json-parse`、`input/read`、`internal/unclassified`），失败也带 `supportedFixes`。
- deliver 失败按**阶段**分类：`input / prepare / render / check / receipt / commit`，每阶段有独立 code（如 `delivery/freeze-specification`、`delivery/commit`）。
- Skill 层纪律：最多两轮聚焦修正；只改被诊断主体；连续两轮目标错误数不下降即停止并如实报告——禁止整图重写。

→ 启发：修复建议白名单 + 轮次上限，是约束 agent 无限重试的可执行契约。

### 2.3 原子交付与快照冻结（deliver）

`bin/archify.mjs commandDeliver` 的流程：

1. 读取 spec **一次**，将原始字节以 `flag: 'wx'` 冻结为同目录私有 staging 快照（`specification.snapshot.json`）。
2. 渲染器只渲染快照（不是原输入），保证"渲染的即冻结的"。
3. `scripts/check-render-output.mjs` 做终检（见 2.4）。
4. 全部通过才 `fs.renameSync` 同文件系统原子提交；**任何一步失败：保留上一个可信产物、清理 staging、非零退出**。
5. 回执含 spec 与 artifact 各自的 SHA-256 + 字节数，证明字节级同一。

另有两条诚实边界：

- `visual-check` 只测量、截图，从不修改产物，回执永远报 `visualReview: "pending"`——自动证据不得声称感知审查。
- Handoff receipt 只允许三种真值：`visual_review: passed | skipped | failed`，`correction_rounds: 0|1|2`。

→ 启发：candidate → validate → atomic replace → keep last-good；确定性回执与感知审查严格分离。

### 2.4 产物检查器（9 项检查 + composition 门禁）

`check-render-output.mjs`：`single_svg`、`finite_svg`（无 NaN/Infinity）、`orthogonal_arrows`、`container_border_runs`、`label_route_clearance`、`relationship_crossings`、`relationship_corridors`、`route_rhythm`、`legend_clearance`。几何问题带像素级证据（overlap 长度、坐标区间、阈值）和**渲染器支持的修复控件名**。showcase 阈值比 standard 更严（label clearance 4px vs 2px）。

### 2.5 Architecture Delta（compare）

`delta/architecture-delta.mjs` + 冻结合同（`docs/research-architecture-delta-pr-proof-2026-07-23.md`）：

- **纯确定性比较器**：相同输入 → 相同 compare IR；不读时间、随机数、locale、网络。
- 身份只认稳定 ID：`components[].id`、`connections[].id`（缺失即逐条失败，不退化为 (from,to)）；boundary 用 `(kind,label)` 保守键，重复即失败。两侧零共享组件 ID → `delta/no-shared-component-id`，**不按相似度猜 rename**。
- 字段变化分类矩阵：component = semantic / evidence / geometry；connection = topology / semantic / geometry；boundary = scope / geometry；另有 provenance 与 presentation 独立计数。状态优先级：added/removed → changed → evidence-changed → moved/rerouted → same。"换坐标"绝不显示为"职责改变"。
- 双哈希：`rawSha256`（精确输入）+ `semanticSha256`（规范化后），语义等价输入产物必须相同。
- `proofLevel: authored | revision-pinned`；回执自带 `limitations`：不推断运行时影响、因果、风险、可合并性。
- 渲染侧：removed 用 base 几何做 phantom（`−` 标记），不重排联合图，viewBox 取确定性并集。

### 2.6 证据钉住 commit（repository evidence）

`renderers/shared/repository-evidence.mjs`：`meta.repository` 必须含公开 GitHub URL + 40 位 SHA；校验链为 git toplevel → origin slug 匹配 → commit 存在 → 每条 source 在该 revision 下 `cat-file` 存在且行范围有效。每个分支都有 fail-closed 诊断。证据是**显式 opt-in**：普通产物保持无源码状态。

### 2.7 Viewer 真相契约

`references/viewer-runtime.md` + `docs/research-authored-reachability-2026-07-23.md`：

- 所有交互（focus / reach / route probe / lens / story）只复用 authored 事实；Route Probe **从不从几何推断路由**。
- Upstream/Downstream 叫 "authored reachability"，**禁止**称为 impact / blast radius / breakage；story 只分类相邻 stop 间的精确关系，不推断传递边。
- 规范导出剥离全部 viewer 状态；viewer 导出只是沟通资产，不替代校验回执。

## 3. 吸收提案 / Absorption Proposal

以下映射均已核对 memory-center 现状，并遵守 ADR-0003（不恢复 persona 化图谱视图；新增呈现必须从既有输出派生且有需求证据）。初版曾列 4 项候选；同日复核发现 C/D 两项或无消费方、或与既有机制重复，已降级为明确不吸收（见本节末尾"复核后明确不吸收"），仅保留 A/B 两项候选。

### A. Wiki 原子交付（candidate → validate → atomic replace → keep last-good）

- 落点：[wiki.py](../memory_center/core/knowledge/wiki.py) `generate_wiki`。现有 generation 追踪是现成地基。
- 真实缺口（已核实）：当前逐文件直写（overview → service 页 → module 页 → bridge），manifest 最后才写；中途失败会留下"文件已是新内容、manifest 仍描述旧状态"的混合态，增量刷新场景下难排查。
- 内容：三层地图与语义桥先写入候选目录，做完整性校验（bridge 引用闭合、L1/L2 预算一致、manifest 与产物 hash 一致），通过后才原子替换发布目录并更新 manifest；失败保留上一个已发布 generation，并把失败阶段写入 manifest 状态。
- 严重度与优先级：中。wiki 是可完全再生的产物，最坏情况是重跑 `generate_wiki`，不会损坏索引或记忆数据；值得做，不排 P0。
- 触发条件：在真实工作空间复现一次混合 generation 状态（或增量刷新读到不一致 manifest）即实施。

### B. 结构化失败回执（code / subject / evidence / supported_fixes + 轮次上限）

- 落点：[delivery.py](../memory_center/core/tasks/delivery.py) `classify_delivery_failure` 与统一错误模型（`invalid_input` / `not_found` / `unavailable` / `conflict` / `internal_error`）。
- 内容：在既有四分类之上，附加机器可读的 `code`（稳定规则码）、`subject`（被诊断对象）、`evidence`（测量值）、`supported_fixes`（允许动作白名单）；`auto_repairable` 已有 `max_retries`，补充"连续两轮无进展即升级 human_decision_required"的停止条件。
- 收益：直接落实执行原则第 5 条；约束 agent 无限重试，与 P3 交付闭环天然衔接。
- 风险：低。只做 additive 字段扩展。
- 触发条件：等 P3 交付闭环在真实任务中出现"agent 拿到失败后乱重试"的证据再实施，避免为假设问题预建结构。

#### 复核后明确不吸收 / Rejected After Re-verification

初版提案的 C（change-review 确定性 delta 回执）与 D（generation 钉住 commit SHA）经代码复核后撤下：

- **C. Delta 回执 —— 无消费方的假设性接缝**。change_review 的文本影响链目前没有任何真实抱怨记录；这与 ADR-0003 删除 GraphViewBuilder 的教训完全同构（"只有一个适配器的假设性接缝"）。若未来真实 session 中出现"文本 diff 不够用"的证据，可重启本项；届时借鉴 Archify 冻结合同：只认稳定 ID、变化按 拓扑/语义/证据/几何/呈现 分类计数、双哈希、自带 limitations。
- **D. Commit SHA 钉住 —— 与既有机制重复且更弱**。freshness 已有 `content_hash`（文件内容 SHA-256）的 generation 比对（见 `core/freshness/targeted_refresh.py`），对本地文件过期判定比 commit SHA 更精确。commit 钉住只在"证据跨机器分享"场景有增量价值，memory-center 目前无此场景。

### 其余非目标 / Other Non-Goals

- 不引入通用绘图编辑器、Mermaid 主题层或 persona 化图谱视图（ADR-0003）。
- 不引入 hosted 服务、新依赖或移动端面。
- 不复制 Archify 的几何/布局检查器——memory-center 的产物是数据回执而非像素图，composition 门禁不适用。
- 不在没有真实需求证据前交付 HTML viewer。

### 建议顺序

A 与 B 均由各自的触发条件（§3 各条）驱动，不预排期；两者互相独立、均为 additive，可并行。两项均属工程卫生级改进，不挤占 P1（Java 解析精度）与 P2（检索质量）的优先级。

### 最大启示（非功能项）

Archify 对本项目最大的价值不是任何具体功能，而是印证与纪律：它的回执诚实边界（自动证据不声称感知审查、reachability 不声称 impact）与 memory-center 已有的 `resolution_level` / `inferred_target` 标记、统一错误模型是同一种哲学。真正可搬的是这份纪律，不是渲染器或图。

## 4. 一手材料索引 / Primary Sources

- 交付合同：`archify/references/delivery-contract.md`、`bin/archify.mjs`（`commandDeliver` / `commandCompare`）
- 诊断与校验：`archify/renderers/shared/diagnostics.mjs`、`validator.mjs`
- Delta 冻结合同：`docs/research-architecture-delta-pr-proof-2026-07-23.md`（含 drawio-skill / GitNexus / GitDiagram / EMF Compare / RFC 8785 的竞品边界分析）
- Reachability 真相边界：`docs/research-authored-reachability-2026-07-23.md`、`archify/references/viewer-runtime.md`
- 证据钉住：`archify/renderers/shared/repository-evidence.mjs`
