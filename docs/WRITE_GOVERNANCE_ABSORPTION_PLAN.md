# Write Governance Absorption Plan / 写入治理吸收方案

- **类型**：决策（absorption plan / 吸收方案）
- **状态**：current · 只记录未完成承诺；完成项迁入 CHANGELOG、ADR 或 decision
- **来源**：2026-09-06 与 Utopia（deeplethe/utopia，`dev@db316ee`，本地 `../utopia`）写入判定的代码级对比。Utopia 是外部设计参照，不引入其代码或依赖。
- **回答的问题**：memory-center 的记忆写入治理（判定、晋升、替代、拒绝）从 Utopia 吸收哪些原则，按什么顺序落地。
- **上游**：`docs/NEXT_PHASE_MASTER_PLAN.md` §P2（Retrieval / Reasoning 质量闭环）的写入治理子计划。
- **明确不是**：不是双时序（bitemporal）迁移方案；不是逐条人审方案；不引入新存储引擎。

---

## 1. 已核实的现状 / Verified Baseline

以下每一条都核对过代码，标注 file:line。** "?" 表示未核实，列入 §7 前置验证。**

### 1.1 写入路径 × 入口矩阵

（2026-09-07 已按 V1/V2 验证结果回填 "?" 单元格；G1–G3 落地后的新增行以 **加粗** 标注。）

| 写入路径 | 层 | CLI | HTTP | MCP | 审核 |
|---|---|---|---|---|---|
| `write_judge` / `write_plan` | 建议 | ✓ | ✓ | ✓ `mc_admin` | 不适用（只读，不写入） |
| `note_record` / `note_supersede` / `note_forget` | L0.5 | ✗ | ✗ | ✓ `mc_admin` | supersede/forget 已改追加决策行 + 投影（G2 已完成） |
| `record_case`（L1 直写） | L1 | ✓ | ✗（无直写路由；HTTP 面为 `suggest-case` 草稿与 `work-close` 捆绑） | **✗** | receipt 携带 decision 块（G3 已完成） |
| `mc_close` 捆绑案例记录 | L1 | — | ✓ `work-close` | ✓ | **无（自动写入）**；receipt 携带 decision 块（G3） |
| **`case_supersede` / `case_reinstate` / `case_decision_list`（G1 新增）** | L1 治理 | ✓ `case-supersede` 等 | ✓ `/workspace/case-supersede` 等 | ✓ `mc_admin` | append-only 决策行 + 投影，原行不改写 |
| consolidation `stage → decide` | L1 | ✓ | ✓ | **✗** | 有（冲突分类 + 人审）；decide-apply receipt 带 decision 块（G3） |
| `artifact_update` | L3 | ✓ | ? | ✓ `mc_admin` | 无（append-only merge 兜底） |

（MCP 动作清单见 `memory_center/application/admin.py` 的 dispatch 表；`record_case` 与 consolidation 仍不在其中——G6 的收敛目标。）

### 1.2 关键事实

- **F1 · judge 是建议器**。`memory_write_judge`（`core/orchestrator/write.py:38-138`）只做关键词加权打分，返回 `selected_layer / confidence / reasons / suggested_tool`，**不写任何数据**。confidence 是 top1−top2 分差（≥3 high），语义是"路由把握"而非真假。
- **F2 · L1 案例替代是模型缺口**（✅ 已由 G1 补全）。`superseded_by` 语义是**指向后继**的前向指针，携带它的行即非 current-truth（`write.py:417-418`；`tests/domain/test_session_consolidation.py:96-121` 的种子行印证）。但 `record_case` 只会 append 新行，**没有任何写入路径能给既有行打上 `superseded_by`**——读取路径认识它，写入路径产生不了它。只有测试种子能造出这种行。
- **F3 · L0.5 替代原地改状态**（✅ 已由 G2 修复）。`supersede_note` 直接 `target["status"] = "superseded"`（`core/tasks/session_notes.py:169`），替代的 who/when/why 不落任何记录。忘改 = 过期笔记被当作 current truth 读出。
- **F4 · 审核门与 agent 入口错位**。带人审的 consolidation 只有 CLI/HTTP；agent 经 MCP 能做的 L1 写入是 `mc_close` 的**自动**案例记录，恰好绕过审核。L3 `artifact_update` 可从 MCP 直写（append-only merge 是唯一兜底）。
- **F5 · 相似度阈值无测量依据**。候选冲突判定用 `difflib.SequenceMatcher ≥ 0.72`（`consolidate.py:37,53`），键为 task + ≤4 项目名 + ≤8 文件名；改写表述会掉到阈值下变成假 ADD。
- **F6 · 无 agent 归因**。`source` 是自由字符串（note/tool_call/...），分不出写入者是哪个 agent。consolidation 冲突投影（`consolidate.py:88-102`）只带 `source_session_id`。

### 1.3 已经做对的（不需要改）

- judge 不写入（失败方向正确：忘了调 judge 的最坏后果是信息留在 L0，不是 L3 被污染）。
- consolidation 的 stage → decide、candidate 稳定 ID、decide 时重查冲突（`consolidate.py:377` `candidate_conflict_changed`）、REVIEW 候选拒绝自动应用（`:367-374`）。
- L3 `artifact_update` 的 append-only 合并 + 审计 + write_receipt（`core/tasks/artifacts.py:140-180`）。
- `workspace_replay_write_chain` 的写入链回放。

---

## 2. 吸收的原则 / Absorbed Principles

每条都给出 Utopia 出处；落地映射见 §3 工作项。

| # | 原则 | Utopia 出处 |
|---|---|---|
| P1 | **失败方向准则**：选数据形状先问"有人忘了/搞错时会坏成什么样"，选坏得安静、可发现的那一侧 | ADR 0013（`derived_facts` 分表）、迁移 `0018` 注释（56 处 `invalidated_at IS NULL` 查询是论据） |
| P2 | **门的放置经济学**：确认成本最低处设门；门的粗细是写入形状的函数，不是内容危险度的函数 | ADR 0015 |
| P3 | **归因是裁决前提**："一条来自代码助手的记忆和一条来自会议纪要 agent 的记忆，可信度不是一回事" | 迁移 `0026`（`proposed_token`） |
| P4 | **决策是事件，不是字段**：不把二元状态编码成浮点；人的态度进审计台账 | ADR 0011（`UPDATE facts SET confidence=1.0` 事故） |
| P5 | **先造尺子再调参**：没有外部答案键，调参只是收紧过拟合；编造的答案键比没有分数更糟 | ADR 0006 状态行、ADR 0016 C1、`scripts/bench/` 纪律 |
| P6 | **矛盾指向上游，争议可见**：冲突是调查线索不是待清除噪音；分歧本身是需要渲染的状态 | ADR 0017、#243（contested edges / ghost edges） |

---

## 3. 工作项 / Workstreams

依赖顺序：**G1 + G2（独立，先修失败方向）→ G3（事件打底）→ G4 ∥ G5 → G6（依赖 G3 与 V2）→ G7**。

（2026-09-07 更新：G1 / G2 / G3 已全部落地并通过回归，细节迁入 CHANGELOG Unreleased「写入治理吸收 G1–G3」；下列小节保留为设计决策记录。剩余未完成：G4、G5、G6、G7。）

### G1（P0）补全 L1 案例替代操作

- **状态**：✅ 已完成（2026-09-07）。采用方案 a（决策行 + 投影）；接线点为 `consolidate._existing_cases`（同时覆盖候选分类与 decide 复检两个消费方）；新增 MCP action `case_supersede` / `case_reinstate` / `case_decision_list`；`superseded_cases` 口径 = 存储字段 `superseded_by` 非空 **或** 最新决策为 supersede。

- **现状**：F2。替代语义只存在于读取侧。
- **方案取舍**（append-only 存储上二选一）：
  - **a) 决策行 + 投影（采用）**：旁路追加 `record_type: "case_decision"`（`case_id / superseded_by / actor / decided_at / note`），`current_truth` 从**存储字段改为投影函数**计算：无未撤销的替代记录、且无 `valid_to`。先例：consolidation 候选投影（`consolidate.py:130-160`，candidate/decision 双记录型）。
  - b) 墓碑行（否决）：追加旧行副本打 `superseded_by` —— 同一 case 双行，读取歧义。
- **改动点**：application 层新增 supersede action；`workspace_ops.py:803-860` 的统计改读投影；`consolidate._find_conflicting_cases` 读投影。
- **兼容**：JSONL 老行的 `current_truth` 字段保留不删；读取一律以投影为准（含老种子行）。
- **验收**：supersede 后旧 case 不再投影为 current-truth；替代可撤销；被替代的旧行与同主题新候选相撞时分类为 `ADD` 而非 `REVIEW`（`consolidate.py:241-247` 分支）；CLI/HTTP/MCP 三入口行为一致。
- **测试**：新增 `tests/domain/test_case_supersede.py`，风格对齐 `test_session_consolidation.py`。

### G2（P0）L0.5 note 替代改追加式

- **状态**：✅ 已完成（2026-09-07）。`_update_note_row` 原地改写已删除；决策行落 `memory/session-note-decisions.jsonl`，投影函数 `project_note_statuses` 被 fingerprint 幂等门、`note_list` 行注记、`note_search` 与 overview `active_note_count` 共同消费；被投影遗忘的 note 允许同 fingerprint 重录（失败方向声明得到加强）。stored `status` 保留为兼容基线。

- **现状**：F3。
- **方案**：note 文件保持 append；`supersede` / `forget` 改为追加决策记录，`NOTE_STATUSES` 变为投影结果（`_note_projection`）。
- **失败方向声明（P1）**：漏读决策行的后果是"替代未生效"（同指纹两条 active，可发现）；原地改的后果是"替代悄悄生效且替代过程本身丢失"。前者是对的。
- **改动点**：`core/tasks/session_notes.py`（supersede_note / 忘记路径）；`mc_admin` 的 `note_supersede` 语义不变（`admin.py:782`），只换存储行为。
- **验收**：supersede 后历史 note 仍可追溯（谁、何时、被哪个 note 替代）；指纹 no-op 行为不变。
- **测试**：`tests/domain/test_session_notes.py` 增补。

### G3（P0）写入决策事件化

- **状态**：✅ 已完成（2026-09-07）。实现为 additive `decision` 块嵌入 write receipt（schema `write_decision`，必填 `actor`），未新建独立 decision 文件——避免双台账；覆盖三条 L1 路径 + G1 的 supersede/reinstate；`workspace_replay_write_chain` 与 timeline 回放按行透出 `decision`。

- **现状**：write_receipts 记录"写了什么"，不记录"为什么生效、谁决定的"；`mc_close` 自动案例记录没有决定事件（F4 的一部分）。
- **目标**：所有 L1/L3 生效写入产生统一 **decision 事件**（actor、来源 agent、路由得分与 reasons、触发的候选/规则、refs），复用 `write_receipts` + `timeline_query` 回放（P4：人的态度进事件，不进字段）。
- **改动点**：`core/tasks/receipts.py` 增 decision 类型（或新 decision 文件）；`workspace_replay_write_chain` 纳入 decision。
- **兼容**：纯增量。
- **验收**：三条产生 L1 的路径（`record_case`、decide-apply、`mc_close`）之后，timeline 回放均能还原完整决策链。
- **测试**：receipts/timeline 单测 + 一条端到端回放测试。

### G4（P1）agent 归因

- **现状**：F6。
- **目标**：写入与 decision 事件携带 `agent_id / agent_kind / trust_tier`，MCP 侧从 token 解析；consolidation 冲突投影与 decide 视图展示两侧 agent（P3）。
- **兼容**：字段可选、缺省 `unknown`；MCP tool schema 不变（AGENTS.md 规则 2）。
- **验收**：MCP 写入带身份；冲突项显示"代码助手 说 X / 规则引擎 说 ¬X"的可裁决形状；`docs/MCP_GUIDE.md`、`docs/REFERENCE.md`、`docs/USER_GUIDE.md`、CHANGELOG 四件套同步（宪法"更新与验证"）。
- **测试**：MCP admin action 归因字段测试。

### G5（P1）拒绝记忆 + 相似度尺子

- **现状**：候选拒绝仅按 candidate_id（内容哈希，`consolidate.py:63-67`）生效，改写措辞可绕过；0.72 阈值无测量（F5）。
- **目标 a · rejected claims**：拒绝时按归一化 claim key（复用 `_normalize_case_key`）落拒绝记录，带**范围档位**：`exact`（挡同 key 重提）/ `topic`（显式升级才生效）。**拒绝不自动升级为主题禁令**——对应 Utopia `rejected_facts` 不查字面值事实的豁免原则（"宁可多问一次，不替人拒掉一个新值"）。
- **目标 b · 答案键先行（P5）**：先构造带标注的候选对集（改写 / 同义 / 类型漂移 / 跨语言），接入现有 eval 框架（对齐 `eval_retrieval_replay` 的使用方式），产出阈值-准确率曲线入 `docs/benchmarks/`；**曲线落地前禁止调整 0.72**。
- **验收**：同 key 拒绝后再 stage 标记 `already_rejected`；改写候选被分类为 `REVIEW` 而非 `ADD`；bench 文档给出当前阈值在该答案键上的实测数字。
- **测试**：`tests/domain/test_rejected_claims.py` + eval 用例。

### G6（P2）晋升门机械化（MCP 收敛）

- **现状**：F4。带审核的路径 agent 够不着，够得着的路径不审核——失败方向错位。
- **目标**：MCP 写入默认产出 staged 候选、由 decide 生效；`record_case` / `artifact_update` 的直写保留为显式配置。**分两步**：
  1. **影子模式**：直写照旧，但同步产出候选与 decision 事件（依赖 G3），观察一个迭代，量化"若门已生效"会有多少写入被拦、多少误拦。
  2. **翻转默认**：`mc_close` 捆绑案例记录改为产候选；直写需配置开启。
- **兼容**：新增 `mc_admin` action（`consolidation_stage` / `consolidation_decide`），schema 增量不破坏；行为变化在 README / CHANGELOG / `docs/MCP_GUIDE.md` 明示（AGENTS.md 规则 2）。
- **风险**：改变 agent 日常流（`mc_close` 语义）。必须等 G3 打底 + V2 核实 `mc_close` 案例记录的代码路径后再动。
- **验收**：默认配置下 agent 无法绕过审核写入 L1/L3；影子模式期间公开行为零回归；三入口一致。
- **测试**：MCP 集成测试覆盖"默认拒绝直写 / 开关直写"两态。

### G7（P2）争议可见化 + judge 低置信不硬选层

- **现状**：REVIEW 候选是一行待处理数据；judge 恒选 top-1（`write.py:102-106`），低置信时也硬指一层。
- **目标 a**：decide 视图渲染两侧出处（session、agent（G4）、时间、暂存以来的变化——`candidate_conflict_changed` 已有信号）（P6）。
- **目标 b**：judge 增加 `no_layer` 建议：低置信时建议留在 L0 并产出 proposal，不硬选层——对应 Utopia 0009/0010 的"宁可留空，不要猜"。
- **验收**：judge 输出 `no_layer` 的可发现路径与测试；REVIEW 视图字段清单进 `docs/REFERENCE.md`。

---

## 4. 明确不做 / Non-Goals

- **不引入双时序双轴 ledger**。`valid_from/valid_to/superseded_by` 单轴 + write_receipts 时间线已够用；记录轴在操作层（receipt/decision 事件）而非行层，对记忆服务是合理取舍。
- **不做逐三元组 / 逐条人审**。Utopia 的确认粒度是 fact，memory-center 是 candidate；写入形状不同（P2），门的粗细必须不同。
- **G6 之前不把 judge 升级为强制器**；任何时候不用浮点分数表达人工决定（P4）。
- **不迁移存储引擎**、不引入外部服务；JSONL/SQLite 既有格局不动（宪法架构不可变量 L48）。

## 5. 执行原则 / Execution Rules

- **三入口一致性**（主计划 §4）：每个 G 项 CLI/MCP/HTTP 行为一致；入口矩阵中新增或改变的能力同步回填 §1.1。
- **宪法"更新与验证"四件套**：改公开面的 G 项同步 操作文档 / 参考文档 / MCP 文档 / CHANGELOG。
- **AGENTS.md 规则 3**：规则匹配、CLI、MCP Server 变更必须补测试（每个 G 项的验收里已列）。
- **AGENTS.md 规则 2**：MCP tool schema 向后兼容；G6 是唯一有意的行为变化项，须显式记录。
- **投影函数是唯一读取口径**：G1/G2 落地后，`current_truth` 与 note status 只从投影读，存储字段不再被业务逻辑直接消费。

## 6. 前置验证清单 / Pre-verification

（2026-09-07 已完成 V1–V3 验证；V4 随主计划任务空间误绑定修复一并解决。）

| # | 事项 | 影响 | 验证结果 |
|---|---|---|---|
| V1 | §1.1 矩阵中所有 "?" 单元格（HTTP `record_case`、note 系列的 CLI/HTTP 分布） | G1/G6 范围 | ✅ note 系列仅 MCP `mc_admin`（无 CLI/HTTP 路由）；HTTP 无 `record-case` 直写路由，L1 的 HTTP 写入面是 `suggest-case`（草稿）与 `work-close`（捆绑 `record_case=True` 默认值，`http/routes/workflow.py:151,166`）。结果已回填 §1.1 |
| V2 | `mc_close` 案例记录的代码路径（直连 `record_case` 还是经 `suggest_case`） | G6 影子模式范围 | ✅ `close_case_records` → `workspace_suggest_case` 产草稿 → 满足条件（有 projects+files 且 `record_case=True`）时**直连** `workspace_record_case`（`application/task_shadow_flow.py:243-249`），不经 staged 候选池。G6 影子模式的插入点即此条件分支 |
| V3 | 证据索引 / 渐进式披露与 L0.5 的关系 | 确认 G2 不冲突 | ✅ evidence-index 只读消费 note 命中（`note_matches`、`ref_id=note:<note_id>`），不读 stored `status` 字段做过滤语义之外的事；G2 的投影对 evidence-index 透明（active 才可命中由检索层保证），无冲突 |
| V4 | 任务空间误绑定（自写自匹配）修复后的候选锚定语义 | 确认 G5 的 claim key 不冲突 | ✅ 误绑定修复（匹配源排除 current_summary、通名弱化、status_boost 强证据前置）只影响 task space 匹配路径；G5 的 claim key 走 `_normalize_case_key`（task + 项目 + 文件），两者正交 |

## 7. 与 Utopia 的对照表 / Cross-Reference

| memory-center 工作项 | Utopia 参照 |
|---|---|
| G1 | `facts` 的 `supersedes` 链 + `close_superseded`（`crates/utopia-store/src/temporal.rs:322`）：纠错是插入新关系而非原地改 |
| G2 | 同上；"改变信念的过程本身是信息" |
| G3 | 决策台账（`pending.rs:196` snapshot；`fact.nod_confirmed` 审计事件） |
| G4 | 迁移 `0026`（`proposed_token`） |
| G5 | `rejected_facts` + 字面值豁免（`crates/utopia-store/src/pending.rs:90-93`）；`scripts/bench/` 与 ADR 0016 C1 |
| G6 | `pending_facts` 独立表 + `is_memory_document` 单点触发（`extraction.rs:699`）：失败方向与门的放置 |
| G7 | ADR 0017 / #243（contested edges）；ADR 0009/0010（宁可留空） |
