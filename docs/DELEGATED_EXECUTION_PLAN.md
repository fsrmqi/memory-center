# Delegated Execution Plan / 外部协作执行手册

## 1. 文档用途 / Purpose

本文档用于把 Memory Center 后续开发交给其他开发者执行。

执行者可以使用 AI 辅助开发。本文档是工作清单和产品方向，不是限制创新的冻结合同。

当前开发策略是：**以功能可用、实际好用、稳定可维护为第一优先级。** 执行者可以根据代码现状重新排序任务、合并工作包、主动重构核心模块、调整公开入口、升级依赖和改进数据模型。只要能说明用户价值、迁移影响和验证结果，就可以继续实施，不需要因旧设计或旧工作包边界停工等待。

## 2. 总体目标 / Outcomes

全部完成后，Memory Center 应具备以下能力：

1. CLI / MCP / HTTP 公开入口语义一致且有契约保护。
2. 主链路失败不会静默，所有降级都有可见 diagnostics。
3. 测试不会污染仓库 demo workspace。
4. Ontology 真正约束 query、contracts、chain、impact 和 memory 语义。
5. 检索质量、推理质量和跨 workspace 链路可持续回归验证。
6. Context Pack、Freshness、Domain、Onboarding 成为默认工作流的一部分。
7. Tree-sitter、增量索引、倒排和向量检索形成稳定的代码理解底座。
8. SQLite backend 承担稳定主读职责，同时保留透明 fallback。
9. Benchmark、Metrics、Audit 和 Runtime Governance 能发现质量退化。
10. Facade 返回值、文档、安装、发布和兼容性具备稳定治理流程。
11. 系统不只返回“命中结果”，还能返回“候选路径 + 权重 + 推荐下一步”，帮助 Agent 在不确定场景中做更优决策。

## 3. 开发参考资料 / Developer References

执行者开始改代码前，建议先阅读与当前任务直接相关的资料，不要求按固定顺序全部读完：

1. `AGENTS.md`
2. `README.md`
3. `docs/ARCHITECTURE.md`
4. `docs/MCP_GUIDE.md`
5. `docs/ONTOLOGY.md`
6. `docs/NEXT_PHASE_MASTER_PLAN.md`
7. `docs/NEXT_PHASE_EXECUTION_PLAN.md`
8. `docs/SPECIAL_NOTES.md`
9. `docs/RELEASE.md`

开发过程中应遵守以下底线：

- 公开入口接收 `workspace.yaml`，底层 store 需要先解析实际 db 路径。
- 会写 graph、memory、index、benchmark 的测试必须使用 `tmp_path` 临时 workspace。
- 公开入口优先保持兼容；当兼容阻碍可用性时，可以提供清晰迁移方案后改进。
- 主链路降级必须返回 diagnostics，不能用空结果伪装成功。
- 面向用户的行为变化必须同步文档，尽量保持中英文双语。
- 不得提交真实私有路径、内部服务名、密钥或私有 workspace 生成物。
- 文档写“完成”前，必须有主入口行为测试和验收证据。

## 4. 推荐执行方式 / Recommended Workflow

### 4.1 每个工作包的推荐顺序

1. 阅读涉及模块、文档和现有测试。
2. 明确用户问题、目标体验和可验证完成标准。
3. 根据风险选择先写测试、先做原型或先重构底座。
4. 做完整、可维护的实现；允许跨模块重构和清理历史债务。
5. 运行目标测试。
6. 运行全量 `pytest -q`。
7. 运行 `ruff check .`，区分本次问题与存量债务，并优先修复触及范围内的问题。
8. 运行 `git diff --check`。
9. 检查 `git status --short`，确认没有生成物污染。
10. 更新直接相关文档。
11. 提交交付说明和验证证据。
12. 根据实际收益继续推进最有价值的下一项工作。
13. 定期汇总已完成能力、剩余问题、产品体验和技术风险。

### 4.2 开发底线

- 不通过删除断言、无理由 `skip`、吞异常或伪造成功隐藏问题。
- 不提交真实密钥、私有路径、内部服务名或私有 workspace 生成物。
- 写入型测试继续使用临时 workspace，避免测试互相污染。
- 涉及不兼容变更或数据迁移时，提供迁移方式、兼容窗口或明确升级说明。
- 新依赖、外部服务和大型重构允许引入，但需要说明为什么能明显改善功能、体验或维护成本。
- 可以删除、重命名或重设计低质量公开入口，但必须同步文档、测试和迁移说明。

### 4.3 每个工作包的交付格式

```text
工作包:
状态: planned | in-progress | completed | needs-follow-up
完成范围:
当前行为:
目标行为:
行为变化:
兼容性影响:
修改文件:
新增或更新测试:
目标测试结果:
全量测试结果:
ruff 结果:
workspace 污染检查:
文档更新:
后续改进:
```

若新增或修改公开返回字段，必须附变更前后示例。

## 5. 执行顺序总览 / Execution Order

以下阶段用于帮助组织工作，不要求严格按顺序推进：

1. 阶段 A：基线、治理与安全护栏
2. 阶段 B：公开入口与类型合同
3. 阶段 C：Ontology、检索与图推理
4. 阶段 D：默认工作流与解释资产
5. 阶段 E：索引器、Freshness 与检索底座
6. 阶段 F：Backend、Metrics 与治理闭环
7. 阶段 G：Runtime、打包与产品入口
8. 阶段 H：规格驱动与变更审查治理
9. 阶段 I：文档、兼容性、发布与最终验收

执行者应优先选择最能改善真实使用体验、主链路可靠性和开发效率的任务。阶段审核闸门用于检查质量，不用于阻止其他有价值工作。

---

## 6. 阶段 A：基线、治理与安全护栏

### A-01：冻结基线并建立持续执行日志

**依赖**：无

#### 步骤

- [ ] 运行 `memory-center --version`，记录当前版本。
- [ ] 运行 `pytest -q`，记录通过、跳过和失败数量。
- [ ] 运行 `ruff check .`。
- [ ] 运行 `python3.11 -m compileall memory_center`。
- [ ] 运行 `git diff --check`。
- [ ] 运行 `git status --short`。
- [ ] 记录三个公开入口的帮助信息和可用状态。
- [ ] 创建 `docs/DELEGATED_EXECUTION_LOG.md`。
- [ ] 后续每个工作包只向执行日志追加结果，不覆盖历史。

#### 验收

- [ ] 基线命令都有证据。
- [ ] 能区分开始前已有改动与执行者改动。
- [ ] 未修改任何业务行为。

### A-02：建立 workspace 测试隔离工具

**依赖**：A-01

#### 步骤

- [ ] 盘点所有直接引用仓库 demo workspace 的测试。
- [ ] 抽取统一的临时 workspace fixture/helper。
- [ ] helper 复制 demo、改写 `workspace.yaml` root，并返回临时路径。
- [ ] 会写 graph、memory、index、benchmark 的测试全部迁移到临时 workspace。
- [ ] 只读测试明确标注只读约束。
- [ ] 连续运行两次目标测试，确认结果稳定。

#### 验收

- [ ] 写入型测试不直接使用仓库 demo。
- [ ] helper 被多个测试模块复用。
- [ ] 连续运行测试后 demo 状态不变。

### A-03：建立 workspace 污染自动检查

**依赖**：A-02

#### 步骤

- [ ] 定义受保护 demo 路径和允许变化范围。
- [ ] 增加测试前后状态比较脚本或测试。
- [ ] 在 CI 测试结束后执行污染检查。
- [ ] 模拟写入受保护目录，确认检查会失败。
- [ ] 恢复模拟写入，确认正常流程通过。
- [ ] 在 `docs/SPECIAL_NOTES.md` 更新维护规则。

#### 验收

- [ ] 污染能被自动发现。
- [ ] 正常测试不会产生误报。
- [ ] 不通过扩大 `.gitignore` 掩盖污染。

### A-04：统一主链路 diagnostics 合同

**依赖**：A-01

#### 步骤

- [ ] 盘点 query、context、impact、context pack、retrieval 中的宽泛异常捕获。
- [ ] 标记哪些异常属于可降级，哪些必须抛出。
- [ ] 为 freshness、risk、vector、evidence 定义统一状态词。
- [ ] diagnostics 至少包含 `status` 和安全的 `reason`。
- [ ] 为 success、disabled、empty、unavailable 增加测试。
- [ ] 确认 diagnostics 不暴露密钥、私有路径和完整 traceback。
- [ ] 更新相关公开文档。

#### 验收

- [ ] 主链路可选能力失败时有 diagnostics。
- [ ] 成功路径保持兼容。
- [ ] 不新增无说明的裸异常吞噬。

### 阶段 A 审核闸门

- [ ] 基线和执行日志完整。
- [ ] 测试 workspace 已隔离。
- [ ] CI 能发现 workspace 污染。
- [ ] diagnostics 合同有测试和文档。
- [ ] 全量测试和 lint 通过。

---

## 7. 阶段 B：公开入口与类型合同

### B-01：建立 CLI / MCP / HTTP 能力矩阵

**依赖**：阶段 A

#### 必须覆盖

- `context-pack`
- `freshness`
- `onboard`
- `domain`
- `business-flow`
- `business-flow-impact`
- `verification-loop`
- `workflow-profile`
- `runtime-audit`
- `regression-alerts`
- `backend-consistency`
- `drill-ref`
- `drill-timeline`
- `drill-task`

#### 步骤

- [ ] 建立能力到 CLI command、HTTP route、MCP tool/action 的映射表。
- [ ] 为每项能力定义核心字段和错误语义。
- [ ] CLI 使用 `CliRunner`。
- [ ] HTTP 直接测试 `_route_request`。
- [ ] MCP 使用项目现有 tool manager 测试模式。
- [ ] 入口只负责参数解析和序列化，业务逻辑优先复用 core helper。
- [ ] 统一 workspace 解析方式。
- [ ] 为无效 workspace、空 workspace、有效 workspace 增加测试。

#### 验收

- [ ] 三入口核心语义一致。
- [ ] 入口不会把 `workspace.yaml` 当数据库打开。
- [ ] 所有测试使用临时 workspace。

### B-02：定义 facade 核心返回类型

**依赖**：B-01

#### 步骤

- [ ] 盘点 `mc_start`、`mc_lookup`、`mc_analyze`、`mc_sync`、`mc_resume`、`mc_handoff`、`mc_close`、`mc_admin` 返回结构。
- [ ] 找出稳定核心字段和可选扩展字段。
- [ ] 在 `memory_center/core/schemas.py` 或现有 schema 层定义类型。
- [ ] 保持序列化结果与现有 dict schema 兼容。
- [ ] 为必填字段、可选字段、未知扩展字段补测试。
- [ ] 明确 schema version 策略。
- [ ] 更新 MCP Guide 和 Reference。

#### 验收

- [ ] 核心 facade 有明确类型边界。
- [ ] 现有调用方无需修改即可继续工作。
- [ ] 不删除现有字段。

### B-03：建立公开 schema 兼容性测试

**依赖**：B-02

#### 步骤

- [ ] 保存公开工具的最小 schema snapshot。
- [ ] 对比 tool 名称、必要参数、默认值和返回核心字段。
- [ ] 新增可选字段允许通过。
- [ ] 删除字段、改变必选参数、改变默认语义必须失败。
- [ ] 将兼容性测试接入 CI。
- [ ] 在 RELEASE 文档记录 breaking change 处理流程。

#### 验收

- [ ] 无意破坏 MCP schema 时 CI 会失败。
- [ ] 兼容扩展不会被误判为破坏。

### B-04：统一错误模型

**依赖**：B-02

#### 步骤

- [ ] 盘点 CLI、MCP、HTTP 的错误返回。
- [ ] 定义 `invalid_input`、`not_found`、`unavailable`、`conflict`、`internal_error`。
- [ ] 为错误增加安全 message、可选 diagnostics 和建议动作。
- [ ] HTTP 状态码与错误类型一致。
- [ ] CLI 保持可读输出和合理退出码。
- [ ] MCP 返回可供 Agent 继续决策的信息。
- [ ] 增加三入口错误矩阵测试。

#### 验收

- [ ] 相同错误在三入口语义一致。
- [ ] 不泄露堆栈、密钥和私有路径。
- [ ] 错误信息包含可执行下一步。

### 阶段 B 审核闸门

- [ ] 入口矩阵完整。
- [ ] facade 核心返回值类型化。
- [ ] schema 兼容性有 CI 保护。
- [ ] 错误模型一致。
- [ ] 文档与实现一致。

---

## 8. 阶段 C：Ontology、检索与图推理

### C-01：Ontology registry 一致性收口

**依赖**：阶段 B

#### 步骤

- [ ] 对比 `docs/ONTOLOGY.md` 与代码实体、边 registry。
- [ ] 为每个已知边定义 semantic strength。
- [ ] 未知边返回 `unknown`，不得默认为 `fact`。
- [ ] 统一 confidence label helper。
- [ ] 统一多跳置信度衰减规则。
- [ ] 为 registry 完整性、未知类型和边界补测试。
- [ ] 更新 ontology 文档。

#### 验收

- [ ] 文档和代码映射一致。
- [ ] query、chain、impact 对同一边解释一致。
- [ ] 未知类型不会提升为事实。

### C-02：建立 Query Quality 回归数据集

**依赖**：C-01

#### 步骤

- [ ] 为 Feign、Endpoint、MQ、Config、Local Service、Method、Chain 各准备正例。
- [ ] 为每类意图准备至少一个容易误判的反例。
- [ ] 数据集使用通用 fixture，不使用私有项目数据。
- [ ] 每个样例定义期望 top result 类型、来源和 confidence。
- [ ] 定义结果质量评分方法。
- [ ] 将数据集接入自动测试。

#### 验收

- [ ] 每类意图都有正反例。
- [ ] 结果质量可重复评估。
- [ ] fixture 不依赖私有路径或内部名称。

### C-03：收敛查询意图识别与排序

**依赖**：C-02

#### 步骤

- [ ] 使用回归数据集评估当前误判。
- [ ] 优先修复本地 Service 与 Feign 混淆。
- [ ] 收紧 Endpoint、MQ、Config 的实体优先级。
- [ ] 检查 project filter 后 summary 与 results 一致。
- [ ] 调整规则时同时增加正向和反向断言。
- [ ] 记录质量变化和兼容性影响。

#### 验收

- [ ] 回归数据集质量提升或保持。
- [ ] 不通过 demo 专有硬编码提高分数。
- [ ] 无明显召回退化。

### C-03A：建立候选路径与权重表达

**依赖**：C-02、C-03

#### 步骤

- [ ] 盘点 query、lookup、sniff、impact、doctor、runtime-audit 中已经存在的候选结果、风险和 confidence 字段。
- [ ] 定义统一的候选路径结构，至少包含 `candidate_type`、`target`、`weight/confidence`、`why`、`next_action`。
- [ ] 明确哪些路径属于 `confirmed`、`probable`、`possible`、`rejected`。
- [ ] 统一排序规则，避免不同入口对同一候选路径给出冲突优先级。
- [ ] 为“多个候选都合理”的场景增加正例，而不是强行压成唯一答案。
- [ ] 为错误高权重、弱证据高排序和解释缺失增加反例。
- [ ] 更新相关 schema 与文档示例。

#### 验收

- [ ] query、lookup、impact、doctor 至少一类主链路返回候选路径及权重。
- [ ] 同一候选在不同入口的权重和解释口径基本一致。
- [ ] 系统不会把低证据猜测伪装成唯一确定答案。

### C-04：Contracts 行为收口

**依赖**：C-01、C-03

#### 步骤

- [ ] 明确 contract 的实体范围和匹配层级。
- [ ] 检查 exact、method、token、全文、fallback 的 confidence。
- [ ] Feign 自动关联只接受足够具体 endpoint path。
- [ ] 为错误关联增加反例。
- [ ] 为 fallback 明确标记 `is_fallback`。
- [ ] 输出 semantic strength 和匹配原因。

#### 验收

- [ ] Contracts 不会把弱全文匹配伪装成高置信结果。
- [ ] Feign 与 Endpoint 关联可解释。

### C-05：Callers / Callees / Chain 行为收口

**依赖**：C-01、C-03

#### 步骤

- [ ] 明确结构关系和行为关系边界。
- [ ] callers / callees 主结果排除纯 `DECLARES` / `CONTAINS`。
- [ ] chain 中 inferred / derived 边携带解释。
- [ ] 多跳路径应用统一 confidence 衰减。
- [ ] 增加环、断链、重复节点、最大深度测试。
- [ ] 增加错误链路反例。

#### 验收

- [ ] 行为链路不被结构边污染。
- [ ] 多跳推断可解释。
- [ ] 结果稳定且无无限遍历。

### C-06：跨 workspace bridge 与 group chain 收口

**依赖**：C-05

#### 步骤

- [ ] 统一 bridge 类型、confidence 和 semantic strength。
- [ ] 检查 `top_bridges`、`bridge_reasons`、`cross_workspace_path_hint`。
- [ ] 跨 workspace bridge 不得标记为 fact。
- [ ] 增加 Feign、Endpoint、MQ、Config bridge 正反例。
- [ ] 增加 workspace 缺失、部分失败和超时降级测试。
- [ ] 检查并行查询结果顺序稳定性。

#### 验收

- [ ] 跨 workspace 链路有明确桥接原因。
- [ ] 部分 workspace 失败不会伪装成完整成功。

### C-07：Reasoning patterns 主链路化

**依赖**：C-05

#### 步骤

- [ ] 盘点现有 patterns、transitive、risk 能力。
- [ ] 选择高价值且可确定验证的内建模式。
- [ ] 为每个模式定义输入、输出、证据和语义强度。
- [ ] 接入 context、impact 或 analyze 主链路。
- [ ] 无匹配返回 empty，执行失败返回 diagnostics。
- [ ] 为误报、漏报和降级补测试。

#### 验收

- [ ] 至少一组 reasoning pattern 真正进入主链路。
- [ ] 推理结果能解释为什么成立。
- [ ] 推理不覆盖事实结果。

### 阶段 C 审核闸门

- [ ] Ontology registry 与文档一致。
- [ ] Query Quality 数据集稳定。
- [ ] Contracts、chain、group chain 有正反例。
- [ ] Reasoning 已主链路化且可解释。
- [ ] 所有质量调整有量化证据。

---

## 9. 阶段 D：默认工作流与解释资产

### D-01：Freshness 进入 start / lookup / analyze 主链路

**依赖**：阶段 C

#### 步骤

- [ ] 为 fresh、pending、stale、unknown 定义稳定语义。
- [ ] `mc_start` 返回 freshness 和推荐动作。
- [ ] `mc_lookup` 命中 stale file 时提高提示级别。
- [ ] `mc_analyze` 在变更前给出 stale 风险。
- [ ] pending/stale 时建议读取 live file 或 reindex。
- [ ] 避免 freshness 查询重复执行。
- [ ] 增加主入口行为测试。

#### 验收

- [ ] Freshness 不再只是独立工具。
- [ ] 主工作流能给出明确下一步。

### D-02：Context Pack 成为默认理解入口

**依赖**：D-01

#### 步骤

- [ ] 明确哪些 intent 应推荐 context pack。
- [ ] `mc_start` 对架构理解和变更预热给出推荐。
- [ ] `mc_analyze` standard/full 复用 compact context summary。
- [ ] Context Pack 包含 freshness、evidence、rules、flows 和 refs。
- [ ] 控制 payload，避免重复大内容。
- [ ] 建立 Context Pack 与传统查询方式的 benchmark。
- [ ] 增加采用路径测试。

#### 验收

- [ ] Context Pack 真正减少重复 lookup/read。
- [ ] 输出可追溯且受 budget 控制。

### D-03：统一 Explanation Schema

**依赖**：C-01、D-02

#### 步骤

- [ ] 定义 `summary`、`evidence`、`semantic_strength`、`confidence`、`next_refs`。
- [ ] 定义事实、推断和衍生内容的展示规则。
- [ ] 提供向后兼容转换 helper。
- [ ] 接入 domain、onboarding、impact、reasoning。
- [ ] 旧字段继续保留。
- [ ] 增加序列化和兼容性测试。

#### 验收

- [ ] 多入口复用同一核心解释结构。
- [ ] 每条推断能追到 evidence 或 ref。

### D-03A：把“下一步选择”纳入默认解释结构

**依赖**：D-03、C-03A

#### 步骤

- [ ] 在 explanation schema 中补充 `candidate_paths`、`recommended_path`、`why_this_first`、`verification_cost`。
- [ ] 让 `mc_start`、`mc_lookup`、`mc_analyze` 至少输出一种“先做什么”的推荐。
- [ ] 将 freshness、risk、contracts、workspace_shape 风险并入路径推荐权重。
- [ ] 高风险或高不确定场景下，优先推荐“低成本验证动作”，而不是直接建议改代码。
- [ ] 为推荐路径错误、验证成本缺失、推荐与风险矛盾增加测试。
- [ ] 更新面向用户的说明文档。

#### 验收

- [ ] 默认解释不只说“是什么”，还能说“下一步先做什么”。
- [ ] 推荐路径能解释为什么排第一。
- [ ] 高不确定场景下的推荐更偏向验证而不是武断修改。

### D-04：Domain / Business Flow 正式输出收口

**依赖**：D-03

#### 步骤

- [ ] 明确 Domain、Flow、Step 的 schema。
- [ ] 统一 flow 提取、flow impact 和入口输出。
- [ ] 为不完整 flow 返回明确 diagnostics。
- [ ] 增加稳定 demo flow fixture。
- [ ] 增加 flow 误关联反例。
- [ ] 接入 CLI / MCP / HTTP 矩阵。

#### 验收

- [ ] 业务流输出稳定且可解释。
- [ ] flow impact 能指出受影响步骤和证据。

### D-05：Onboarding 与 Persona 输出收口

**依赖**：D-03、D-04

#### 步骤

- [ ] 明确 developer、architect、tester、product 的关注点。
- [ ] 每种 persona 使用相同事实，但组织方式不同。
- [ ] 复用 Domain、Flow 和 Explanation 资产。
- [ ] 增加 persona 差异测试。
- [ ] 确认差异不是只替换标题。
- [ ] 输出下一步可钻取 refs。

#### 验收

- [ ] Persona 输出差异有实际价值。
- [ ] 所有说明可追溯到相同事实底座。

### D-06：Resume / Handoff / Drill-down 摘要增强

**依赖**：D-03

#### 步骤

- [ ] 盘点 resume、handoff、ref、timeline、task drill-down 输出。
- [ ] 统一摘要层和 refs 使用方式。
- [ ] 优先给 compact summary，详情按需展开。
- [ ] 保持 Task、Session、Receipt、Ref 语义分离。
- [ ] 增加大 payload 外置和展开测试。
- [ ] 增加缺失 ref、过期 ref 和部分数据测试。

#### 验收

- [ ] 人和 Agent 能沿 ref 快速追到证据。
- [ ] 摘要不会混淆不同记忆层对象。

### 阶段 D 审核闸门

- [ ] Freshness 和 Context Pack 已进入默认工作流。
- [ ] Explanation Schema 被多入口复用。
- [ ] Domain、Flow、Onboarding 输出稳定。
- [ ] Resume/Handoff/Drill-down 可追溯。
- [ ] Payload 和 token 没有明显退化。

---

## 10. 阶段 E：索引器、Freshness 与检索底座

### E-01：定义索引器解析合同与 fixture

**依赖**：阶段 D

#### 步骤

- [ ] 列出现有 Java regex parser 支持的语法。
- [ ] 建立 Controller、Feign、MQ、Config、Bean、Method Call fixture。
- [ ] 为删除、移动、修改文件建立增量索引 fixture。
- [ ] 定义解析结果的稳定核心字段。
- [ ] 建立 parser 对比测试框架。

#### 验收

- [ ] 索引器行为有明确合同。
- [ ] 后续 parser 改造可做结果对比。

### E-02：Tree-sitter Java Parser 可选接入

**依赖**：E-01

#### 步骤

- [ ] 检查现有 `tree_sitter_parser.py` 状态和可选依赖策略。
- [ ] 保持 regex parser 作为兼容 fallback。
- [ ] 实现最小稳定解析路径。
- [ ] 使用 parser 对比 fixture 验证准确性。
- [ ] tree-sitter 不可用时返回明确 diagnostics。
- [ ] 增加配置开关和文档。
- [ ] 不在未验证时替换默认 parser。

#### 验收

- [ ] Tree-sitter 可选启用。
- [ ] 缺依赖时系统仍可工作。
- [ ] 对比 fixture 显示真实收益。

### E-03：并行索引稳定性收口

**依赖**：E-01

#### 步骤

- [ ] 盘点并行索引共享状态。
- [ ] 增加确定性顺序和错误收集。
- [ ] 单文件失败不能静默丢失。
- [ ] 增加并发、部分失败和取消测试。
- [ ] 对比串行与并行结果一致性。
- [ ] 记录性能数据。

#### 验收

- [ ] 并行与串行核心结果一致。
- [ ] 部分失败可见。
- [ ] 性能收益有证据。

### E-04：Watcher 到增量索引桥接

**依赖**：E-01、E-03

#### 步骤

- [ ] 明确 watcher 事件格式。
- [ ] 处理 create、modify、delete、move。
- [ ] 合并连续重复事件。
- [ ] 将事件转换为增量索引任务。
- [ ] 更新 freshness 状态。
- [ ] 增加高频编辑和异常恢复测试。

#### 验收

- [ ] 文件变化能稳定驱动增量索引。
- [ ] 删除和移动不会留下幽灵索引。
- [ ] Freshness 状态与真实变化一致。

### E-05：Connect-time Catch-up 与 stale 恢复

**依赖**：E-04

#### 步骤

- [ ] 启动或连接 workspace 时比较文件状态与索引状态。
- [ ] 检测 watcher 离线期间的变化。
- [ ] 定义 catch-up 策略和最大工作量保护。
- [ ] 恢复失败时返回 diagnostics。
- [ ] 增加离线修改、批量修改和中断恢复测试。

#### 验收

- [ ] 离线变化不会永久遗漏。
- [ ] 大量变化时行为可控。

### E-06：倒排 / FTS 检索收口

**依赖**：C-02、E-01

#### 步骤

- [ ] 盘点 InvertedIndex、FTS 和 sparse retrieval 路径。
- [ ] 定义索引内容、更新策略和查询合同。
- [ ] 避免全量扫描高成本路径。
- [ ] 接入 hybrid retrieval。
- [ ] 增加精确匹配、模糊匹配、更新和删除测试。
- [ ] 对比延迟和召回质量。

#### 验收

- [ ] 稀疏检索使用候选索引而非全量扫描。
- [ ] 延迟和质量有量化证据。

### E-07：Native Vector 检索正式接入

**依赖**：E-06

#### 步骤

- [ ] 明确向量元数据、维度和版本合同。
- [ ] 选择与本地优先原则一致的后端方案。
- [ ] 保持 vector 为可选能力。
- [ ] 实现写入、更新、删除和查询。
- [ ] 接入 hybrid retrieval 融合排序。
- [ ] 为 disabled、empty、dimension mismatch、active 增加测试。
- [ ] 记录 latency、召回和资源占用。

#### 验收

- [ ] Vector 有数据时真实参与排序。
- [ ] 不可用时 diagnostics 清晰且不阻断主链路。
- [ ] 不引入未经负责人批准的必选外部服务。

### E-08：Hybrid Retrieval 融合策略收口

**依赖**：E-06、E-07

#### 步骤

- [ ] 定义 graph、sparse、vector 的权重和启用条件。
- [ ] 按 query intent 调整来源优先级。
- [ ] 去重并保留来源解释。
- [ ] 为单来源、双来源、三来源增加测试。
- [ ] 使用 Query Quality 数据集评估。
- [ ] 记录 token、latency 和 quality 变化。

#### 验收

- [ ] 融合排序可解释。
- [ ] 任一可选来源不可用时仍能稳定降级。
- [ ] 综合质量优于或不低于基线。

### 阶段 E 审核闸门

- [ ] Parser 行为有合同和对比 fixture。
- [ ] Tree-sitter 可选接入且兼容 fallback。
- [ ] 增量索引覆盖新增、修改、删除、移动。
- [ ] Catch-up 能恢复离线变化。
- [ ] Sparse 和 Vector 真正进入 hybrid 主链路。
- [ ] 性能与质量变化有证据。

---

## 11. 阶段 F：Backend、Metrics 与治理闭环

### F-01：Unified Backend 主读路径盘点

**依赖**：阶段 E

#### 步骤

- [ ] 列出 JSON/JSONL/Markdown 和 SQLite 的读取路径。
- [ ] 标记高频读、低频读和唯一事实源。
- [ ] 找出 query、UI、eval 口径分叉。
- [ ] 定义主读与 fallback 策略。
- [ ] 更新架构文档。

#### 验收

- [ ] 每类数据的主读和 fallback 清晰。
- [ ] 不误把 memory.db 描述为唯一真相源。

### F-02：迁移高频读取到 Unified Backend

**依赖**：F-01

#### 步骤

- [ ] 按风险从低到高选择高频读取路径。
- [ ] 每迁移一条路径先增加双读一致性测试。
- [ ] Backend 不可用时保留透明 fallback。
- [ ] 记录 fallback reason。
- [ ] 增加过滤、排序、分页和空数据测试。
- [ ] 删除重复读取逻辑前确认无调用方依赖。

#### 验收

- [ ] 高频读取口径一致。
- [ ] Fallback 可见且可验证。
- [ ] 不丢失可读文件事实源。

### F-03：Backend 一致性检查增强

**依赖**：F-02

#### 步骤

- [ ] 定义 JSONL 与 SQLite 可比较字段。
- [ ] 检查缺失、重复、顺序和内容漂移。
- [ ] 区分 warning 与 error。
- [ ] 提供修复建议但不自动破坏数据。
- [ ] 接入 CLI / MCP / HTTP。
- [ ] 增加故意制造漂移的测试。

#### 验收

- [ ] 一致性问题可复现、可解释。
- [ ] 正常差异不会被误判。

### F-04：统一 Metrics Schema

**依赖**：F-01

#### 步骤

- [ ] 为 lookup、context pack、analyze、resume、handoff、index 定义指标。
- [ ] 至少包含 latency、source、freshness、fallback、token estimate。
- [ ] 定义指标版本和安全字段范围。
- [ ] 指标记录失败不得阻断主业务。
- [ ] 增加序列化和失败降级测试。
- [ ] 文档化每个指标含义。

#### 验收

- [ ] 指标字段稳定。
- [ ] 不记录 prompt 全文、密钥和私有源码。

### F-05：Benchmark Baseline 与 Regression Alerts

**依赖**：F-04

#### 步骤

- [ ] 固定关键工作流 benchmark 场景。
- [ ] 定义 token、latency、quality 基线。
- [ ] 定义 `threshold_pct` 默认值和边界。
- [ ] 为无基线、正常、超阈值增加测试。
- [ ] 告警指出退化指标、比较基线和建议动作。
- [ ] 接入 health、audit 和 admin。

#### 验收

- [ ] 回归可以用测试数据稳定触发。
- [ ] 告警语义在三入口一致。

### F-06：Completion Audit workspace 类型适配

**依赖**：F-03、F-05

#### 步骤

- [ ] 为 Python、Maven、Gradle、frontend、mixed 建立 fixture。
- [ ] 减少对固定仓库结构的隐式假设。
- [ ] 区分 error、warning、info。
- [ ] 每条高优先级问题附触发证据。
- [ ] 有意设计选择写入 SPECIAL_NOTES。
- [ ] 增加假阳性反例。

#### 验收

- [ ] 不同 workspace 类型的 audit 建议准确。
- [ ] 假阳性有明显下降。

### F-07：Health 与治理闭环

**依赖**：F-03、F-05、F-06

#### 步骤

- [ ] 汇总 freshness、backend consistency、regression alerts、audit。
- [ ] 定义整体状态计算规则。
- [ ] 区分阻断问题和建议项。
- [ ] 提供下一步动作和可钻取 refs。
- [ ] 增加部分模块不可用时的降级测试。
- [ ] 接入 CLI / MCP / HTTP。

#### 验收

- [ ] Health 输出能指导实际治理动作。
- [ ] 单模块失败不会让整体状态失真。

### 阶段 F 审核闸门

- [ ] Unified Backend 主读策略明确。
- [ ] 高频读取迁移有一致性保护。
- [ ] Metrics、Benchmark、Audit、Health 形成闭环。
- [ ] 告警和治理建议可执行。
- [ ] 数据安全约束通过审核。

---

## 12. 阶段 G：Runtime、打包与产品入口

### G-01：Workflow Protocol Profiles 收口

**依赖**：阶段 F

#### 步骤

- [ ] 定义 quick-fix、contract-change、long-task、architecture profile。
- [ ] 每个 profile 指定推荐工具顺序、验证要求和结束条件。
- [ ] 将 profile 接入 start、analyze、close。
- [ ] 保持 profile 为建议，不随意强阻断。
- [ ] 增加 profile 选择和执行测试。

#### 验收

- [ ] 四类 workflow profile 行为稳定。
- [ ] 推荐顺序与任务类型匹配。

### G-02：Verification Loop 强化

**依赖**：G-01

#### 步骤

- [ ] 统一 analyze、checklist、verify、close 输出口径。
- [ ] 验证项必须可执行、可记录状态。
- [ ] close 时检查未完成验证项。
- [ ] 非阻断建议与阻断项分离。
- [ ] 增加成功、失败、部分完成测试。

#### 验收

- [ ] 验证闭环可追踪。
- [ ] 未完成项不会被伪装成完成。

### G-03：Pattern Promotion 与 Learned Heuristics

**依赖**：G-02

#### 步骤

- [ ] 明确 case、rule、decision 到候选模式的晋升条件。
- [ ] 每个候选包含证据、置信度和来源。
- [ ] 晋升必须可审计和可拒绝。
- [ ] 不自动把单次偶然经验提升为全局规则。
- [ ] 增加重复、冲突、低置信度测试。

#### 验收

- [ ] 模式晋升逻辑可解释、可审计。
- [ ] 低质量候选不会污染长期规则。

### G-04：Agent Runtime Audit

**依赖**：G-01

#### 步骤

- [ ] 审计 hooks、MCP 配置、agent 配置和推荐生命周期。
- [ ] 保持 `user_prompt_submit` 默认禁用策略。
- [ ] 检查 SessionStart、PreToolUse、Stop 配置。
- [ ] 输出问题、证据和修复建议。
- [ ] 增加 Codex、Claude Code、Cursor fixture。

#### 验收

- [ ] Runtime audit 能发现配置问题。
- [ ] 不把有意设计选择误判为 bug。

### G-05：Agent Usage Bundle Export

**依赖**：G-01、G-04

#### 步骤

- [ ] 定义最小 bundle 内容。
- [ ] 为 Codex、Claude Code、Cursor 输出适配配置。
- [ ] 不写入真实私有 workspace 路径。
- [ ] 支持预览和明确输出目录。
- [ ] 增加生成内容和安全性测试。
- [ ] 更新用户指南。

#### 验收

- [ ] Bundle 可安装、可阅读、无私有信息。
- [ ] 不覆盖用户已有配置而不提示。

### G-06：HTTP Workbench 与核心入口对齐

**依赖**：F-07

#### 步骤

- [ ] 盘点工作台页面调用的 HTTP 路由。
- [ ] 对齐新的 diagnostics、health、metrics、flow、freshness 字段。
- [ ] 保持工作台作为运维和阅读入口，不扩展成重型前端重写。
- [ ] 增加 API 合同测试。
- [ ] 进行桌面和移动视口基础验证。

#### 验收

- [ ] 工作台展示与后端语义一致。
- [ ] 不重复实现后端业务逻辑。

### G-07：安装与构建流程收口

**依赖**：阶段 G 其他工作包

#### 步骤

- [ ] 验证本地 checkout 安装。
- [ ] 验证 pipx 重装和三个命令入口。
- [ ] 解决或文档化根目录 `build/` 遮蔽 Python `build` 包的问题。
- [ ] 验证干净环境构建 wheel。
- [ ] 验证可选 extras。
- [ ] 更新安装和发布文档。

#### 验收

- [ ] 干净环境可构建并安装。
- [ ] 三个入口可运行。
- [ ] 构建问题不依赖口头说明。

### 阶段 G 审核闸门

- [ ] Workflow 与 Verification Loop 可追踪。
- [ ] Pattern Promotion 可审计。
- [ ] Runtime Audit 与 Bundle Export 可用。
- [ ] Workbench 与核心入口语义一致。
- [ ] 安装和构建流程稳定。

---

## 13. 阶段 H：规格驱动与变更审查治理

本阶段吸收 `github/spec-kit` 与 `alibaba/open-code-review` 中适合 Memory Center 的思想。

优先吸收适合 Memory Center 的架构思想和执行路线，并接入现有 task-space、artifacts、rules、refs、verification、graph 与 workflow profiles。如果直接集成、设为运行时依赖或复用其目录与命令体系能带来更好的功能和维护体验，也可以实施，但需要说明收益、许可证、升级方式和迁移影响。

### H-01：建立项目 Constitution 治理工件

**依赖**：阶段 G

#### 步骤

- [ ] 将 `team-rules`、`architecture-invariants`、`active-migration-policy` 映射为 Constitution 的事实来源。
- [ ] 定义原则、约束等级、版本、批准状态和修改记录。
- [ ] 明确 Constitution 与普通 rule、task requirement、SPECIAL_NOTES 的优先级。
- [ ] Constitution 冲突必须进入显式审核，不得由 Agent 静默覆盖。
- [ ] 在 plan、analyze、audit、close 中增加 Constitution 检查。
- [ ] 为规则冲突、版本升级和兼容迁移增加测试。

#### 验收

- [ ] 稳定原则有统一治理入口。
- [ ] Constitution 冲突可见且不能被普通任务覆盖。
- [ ] 不重复维护多份互相漂移的规则事实。

### H-02：建立 Spec → Plan → Tasks → Change → Verification 追踪链

**依赖**：H-01

#### 步骤

- [ ] 在 task-space 中定义 requirement/spec、design/plan、task、change、test、verification 的稳定关系。
- [ ] 为 requirement 和 success criterion 分配稳定 ID。
- [ ] Task 必须引用对应 requirement、计划步骤和验收标准。
- [ ] Change receipt 必须能关联 task 和 requirement。
- [ ] Verification result 必须能关联 change 和 success criterion。
- [ ] 增加追踪图查询和缺失关系 diagnostics。
- [ ] 保持 Markdown 工件可读，不引入不透明专有格式。

#### 验收

- [ ] 任意需求可追到任务、变更和验证证据。
- [ ] 任意任务都能解释来源和完成标准。
- [ ] 未映射任务和未覆盖需求可自动发现。

### H-03：规格 Clarify 与跨工件一致性分析

**依赖**：H-02

#### 步骤

- [ ] 定义规格检查维度：范围、实体、状态、失败模式、性能、安全、依赖、边界和完成信号。
- [ ] 只提出会影响架构、任务拆分或测试设计的高价值澄清项。
- [ ] 澄清结果写回 task-space requirement/spec，并留下 write receipt。
- [ ] 建立 spec、plan、tasks 跨工件只读一致性分析。
- [ ] 检测重复、歧义、术语漂移、需求无任务、任务无需求和 Constitution 冲突。
- [ ] 输出稳定 finding ID、severity、位置和修复建议。
- [ ] 在实现前设置一致性审核闸门。

#### 验收

- [ ] 高风险歧义能在实现前发现。
- [ ] 分析结果确定、可重复、默认只读。
- [ ] Constitution 冲突被标记为最高优先级。

### H-04：可恢复工作流状态机与人工 Gate

**依赖**：H-01、H-03

#### 步骤

- [ ] 将 workflow profile 扩展为显式步骤状态机。
- [ ] 定义 `created`、`running`、`paused`、`failed`、`completed`、`aborted`。
- [ ] 每一步完成后持久化状态、输入摘要、输出 refs 和 diagnostics。
- [ ] 支持 gate、条件分支、失败重试和人工拒绝。
- [ ] Gate 不得被普通 `continue_on_error` 绕过。
- [ ] resume 从失败或暂停步骤继续，不重复已完成步骤。
- [ ] 增加中断、恢复、拒绝、重试和幂等测试。

#### 验收

- [ ] 长任务中断后可确定恢复。
- [ ] 人工 gate 有明确批准记录。
- [ ] 已完成步骤不会被无意重复执行。

### H-05：建立确定性 Diff Scope 与 Preview

**依赖**：H-02

#### 步骤

- [ ] 定义 workspace、commit、branch range 三种 diff scope。
- [ ] 结构化解析 added、modified、deleted、renamed、binary。
- [ ] 使用确定性规则决定哪些文件进入审查或验证范围。
- [ ] 为排除文件返回明确原因。
- [ ] 提供 preview/dry-run，只展示范围和规则，不调用 Agent。
- [ ] 将 diff scope 与 task、requirement、impact 和 freshness 关联。
- [ ] 增加未跟踪文件、重命名、删除、二进制和空 diff 测试。

#### 验收

- [ ] 执行前能准确预览审查和验证范围。
- [ ] 重要变更不会因 Agent 自主选择而遗漏。
- [ ] 被排除文件都有可解释原因。

### H-06：基于图谱的 Change Bundle 分包

**依赖**：H-05、C-06

#### 步骤

- [ ] 使用 graph、contract、flow 和 task 关系识别关联变更文件。
- [ ] 将强关联文件组成独立 change bundle。
- [ ] 每个 bundle 包含 diff、业务背景、影响范围、匹配规则和必要 refs。
- [ ] Bundle 之间上下文隔离，避免超大变更噪声扩散。
- [ ] 对共享契约、DTO/Feign/Endpoint、producer/consumer 建立分包规则。
- [ ] 定义 bundle 最大规模和超限拆分策略。
- [ ] 增加确定性、完整覆盖和重复文件测试。

#### 验收

- [ ] 每个变更文件恰好属于一个主 bundle。
- [ ] 强关联文件不会被错误拆散。
- [ ] 分包结果可重复且可解释。

### H-07：分层规则匹配与 Rule Preview

**依赖**：H-05、H-06

#### 步骤

- [ ] 定义覆盖层级：调用参数、task/workspace、用户、系统默认。
- [ ] 每层保持确定性匹配顺序。
- [ ] 为文件和 bundle 返回实际生效规则、来源和匹配原因。
- [ ] 增加 rule preview，不执行 Agent 即可查看规则。
- [ ] 冲突规则必须可见，不得静默随机选择。
- [ ] 增加 glob、优先级、fallback 和冲突测试。

#### 验收

- [ ] 任意文件都能解释实际应用了哪条规则。
- [ ] 规则覆盖顺序稳定。
- [ ] 无规则时使用明确 fallback。

### H-08：Context-Aware Change Review

**依赖**：H-06、H-07、D-02、C-07

#### 步骤

- [ ] 为每个 change bundle 生成结构化审查上下文。
- [ ] 上下文包含 requirement、plan、impact、contracts、rules、freshness 和相关历史经验。
- [ ] Agent 只能对当前 diff 提交 finding，其他文件仅作为理解上下文。
- [ ] Finding 必须包含 severity、文件、目标代码、问题、影响、证据和建议动作。
- [ ] 对高风险或大范围 bundle 先生成 review plan，再执行检查。
- [ ] 支持 agent-friendly 结构化输出，不混入进度噪声。
- [ ] 增加真实缺陷、误报和上下文不足测试。

#### 验收

- [ ] Review 聚焦真实变更。
- [ ] Finding 有业务背景和影响证据。
- [ ] 大变更不会因单一超长上下文失控。

### H-09：Finding 定位、验证与去重

**依赖**：H-08

#### 步骤

- [ ] 使用确定性 diff hunk 定位 finding 目标行。
- [ ] 定位失败时允许受控二次定位，但必须再次用 diff 验证。
- [ ] 验证 finding 指向新增或修改代码，不对纯删除和未变更代码报问题。
- [ ] 对 finding 做证据充分性和规则符合性检查。
- [ ] 合并重复 finding，保留最强证据。
- [ ] 区分 `confirmed`、`needs-context`、`rejected`。
- [ ] 增加行号漂移、重复、错误定位和低证据 finding 测试。

#### 验收

- [ ] Finding 位置准确且可验证。
- [ ] 低证据和错误定位 finding 不进入高优先级结果。
- [ ] 去重不会丢失关键证据。

### H-10：Review Findings 进入 Verification 与 Memory

**依赖**：H-09、G-02、G-03

#### 步骤

- [ ] confirmed finding 自动进入 verification checklist。
- [ ] needs-context finding 进入待澄清项，不直接判定失败。
- [ ] rejected finding 记录原因，但不污染长期规则。
- [ ] 修复后验证 finding 是否真正关闭。
- [ ] 高价值重复 finding 可进入 pattern promotion 候选。
- [ ] 记录 coverage、precision、定位成功率和 token 使用。
- [ ] 增加 finding 生命周期和晋升测试。

#### 验收

- [ ] Review、修复、验证和经验沉淀形成闭环。
- [ ] 单次误报不会晋升为长期规则。
- [ ] 质量指标可用于 benchmark。

### H-10A：验证结果回写候选路径权重

**依赖**：H-10、C-03A、D-03A

#### 步骤

- [x] 为候选路径定义验证后状态：`confirmed`、`demoted`、`rejected`、`needs-more-context`。
- [x] query / analyze / review 的验证结果可回写到 task、receipt、heuristics 或 case。
- [x] 高价值成功路径可以提升默认推荐权重；明确失败路径要降低权重或增加排除理由。
- [x] 只允许基于真实验证证据调整权重，不允许凭主观总结直接提升长期权重。
- [x] 为“短期成功但长期误导”的场景增加保护，避免单次偶然命中污染全局策略。
- [x] 增加权重提升、降级、拒绝和回滚测试。

#### 验收

- [x] 系统能从验证结果中学习“哪条路径更值得先试”。
- [x] 权重变化可追溯到具体验证证据。
- [x] 错误经验不会轻易固化成默认推荐。

当前落地说明：

- 已通过 `heuristics_feedback` / CLI `heuristics --action feedback` / HTTP `/workspace/heuristics?action=feedback` 接入候选路径验证结果回写。
- 当前最小闭环已具备：聚合当前权重、证据门槛升权、失败降权、按聚合后权重排序。
- 当前已增加推荐层保护：单次正向样本默认只作为 provisional recommendation，不会直接固化成长期高优先级推荐。
- 当前已增加显式回滚保护与时间衰减：被回滚的路径会快速退出默认推荐，长期未验证路径会衰减推荐权重但保留原始学习值。
- 下一步重点是补跨版本策略迁移与更细粒度的衰减参数治理。
- 后续补充项（当前先忽略）：增加 learning 可视化汇总面板，直接展示哪些候选路径在升权、哪些 workflow profile 被 rollback、哪些 recommendation 正在 stale decay 退场，便于观察决策层如何学习。

### H-11：受信 Preset、Extension 与 Review Adapter 边界

**依赖**：H-04、H-07、G-05

#### 步骤

- [ ] 明确 core、project override、preset、extension/adapter 的职责和优先级。
- [ ] Preset 只调整模板、术语和治理要求。
- [ ] Extension/adapter 只增加新能力或连接外部工具。
- [ ] 为外部 review 工具预留 adapter，不把 OpenCodeReview 设为必选依赖。
- [ ] 建立受信 catalog 和仅发现 catalog 的区分。
- [ ] 安装前展示来源、版本、权限、能力和风险。
- [ ] 不受信扩展默认不可自动安装或执行。
- [ ] 增加覆盖优先级、卸载恢复和安全测试。

#### 验收

- [ ] 核心保持精简，扩展能力可选。
- [ ] 外部工具集成有明确安全边界。
- [ ] 移除扩展后能恢复到下一优先级实现。

### 阶段 H 审核闸门

- [ ] Constitution 与规格追踪链可用。
- [ ] Clarify 和跨工件一致性分析在实现前工作。
- [ ] 可恢复 workflow 和人工 gate 有行为测试。
- [ ] Diff scope、change bundle 和 rule preview 确定可重复。
- [ ] Review finding 完成定位、验证、去重和 verification 闭环。
- [ ] 外部工具只通过可选 adapter 集成。

---

## 14. 阶段 I：文档、兼容性、发布与最终验收

### I-01：文档状态收敛

**依赖**：阶段 H

#### 步骤

- [ ] 更新 README 中用户可感知行为。
- [ ] 更新 ARCHITECTURE 中稳定结构。
- [ ] 更新 MCP_GUIDE 中入口和 schema。
- [ ] 更新 ONTOLOGY 中实体、边和语义。
- [ ] 更新 NEXT_PHASE_MASTER_PLAN，将完成项迁出待办。
- [ ] 更新 NEXT_PHASE_EXECUTION_PLAN 当前状态。
- [ ] 更新 SPECIAL_NOTES 中新增设计取舍。
- [ ] 更新 ROADMAP 和 REFERENCE。
- [ ] 检查文档中的“已实现”“已接入”“已验收”没有混写。

#### 验收

- [ ] 文档与代码状态一致。
- [ ] 关键行为有中英文说明。

### I-02：兼容性审计

**依赖**：I-01

#### 步骤

- [ ] 运行公开 schema 兼容性测试。
- [ ] 对比 CLI command 和参数。
- [ ] 对比 HTTP routes 和核心字段。
- [ ] 对比 MCP tools、actions 和默认值。
- [ ] 检查 workspace、graph、memory 数据格式。
- [ ] 对任何不兼容项提供迁移方案并等待负责人批准。

#### 验收

- [ ] 无未说明的 breaking change。
- [ ] 必要 breaking change 有迁移方案和明确批准。

### I-03：安全与隐私检查

**依赖**：I-01

#### 步骤

- [ ] 搜索私有绝对路径、内部服务名、密钥和 token。
- [ ] 检查示例、fixture、docs 和生成 bundle。
- [ ] 检查 diagnostics 和 metrics 是否泄露敏感内容。
- [ ] 检查仓库是否包含私有 `.memory-center` 生成物。
- [ ] 运行依赖和基础安全检查。

#### 验收

- [ ] 无真实私有信息。
- [ ] 无不必要敏感数据记录。

### I-04：最终验证

**依赖**：I-02、I-03

#### 步骤

- [ ] 运行 `pytest -q`。
- [ ] 运行 `ruff check .`。
- [ ] 运行 `python3.11 -m compileall memory_center`。
- [ ] 运行 `git diff --check`。
- [ ] 运行 `git status --short`。
- [ ] 运行 CLI smoke。
- [ ] 运行 HTTP smoke。
- [ ] 运行 MCP facade smoke。
- [ ] 运行 workspace 污染检查。
- [ ] 运行 Query Quality、Benchmark、Backend Consistency、Health。
- [ ] 在干净环境构建 wheel。
- [ ] 安装构建产物并验证三个入口。

#### 验收

- [ ] 所有验证通过。
- [ ] 所有失败都有明确处理结论。

### I-05：版本升级与发布说明

**依赖**：I-04

#### 步骤

- [ ] 由项目负责人确认版本号。
- [ ] 同步包元数据和运行时版本。
- [ ] 更新 CHANGELOG。
- [ ] 说明新增能力、真实 bug 修复、行为变化和兼容性。
- [ ] 重新构建和安装。
- [ ] 验证安装版本。

#### 验收

- [ ] 版本号位置一致。
- [ ] 发布说明可信且不夸大完成状态。
- [ ] 安装验证通过。

---

## 15. 代码审核检查表 / Reviewer Checklist

评审每个工作包时重点检查：

- [ ] 用户问题是否真正解决，工作流是否更好用。
- [ ] 实现是否完整，是否留下明显半成品或伪完成状态。
- [ ] 重构、依赖和数据模型选择是否比旧方案更清晰、更可维护。
- [ ] CLI / MCP / HTTP 是否根据目标用户场景提供合理体验。
- [ ] 不兼容变化是否有清晰迁移说明。
- [ ] diagnostics 可见但不泄露敏感信息。
- [ ] 没有新的宽泛异常吞噬。
- [ ] 没有修改仓库 demo `.memory-center`。
- [ ] 没有把 fixture 专有名字硬编码进生产逻辑。
- [ ] 文档同步。
- [ ] 有全量测试、lint 和污染检查证据。
- [ ] 执行日志已追加。

## 16. 自主改造与风险记录 / Autonomous Changes and Risk Notes

执行者被授权主动实施能够提升功能可用性、使用体验、性能、可靠性和维护效率的改造，包括：

1. 重构或重写 indexer、store、orchestrator。
2. 调整 MCP、CLI、HTTP 公开入口和 schema。
3. 改进 workspace、graph、memory 数据格式并提供迁移。
4. 引入有明确收益的新依赖、外部服务或可选后端。
5. 删除低价值重复能力，合并分叉实现。
6. 重新设计任务顺序和模块边界。

不需要因为改动规模大、涉及核心模块或与旧计划不同而停止。遇到风险时，记录决策并继续推进可验证方案。

风险记录格式：

```text
事项:
来源工作包:
状态: investigating | implementing | needs-follow-up
当前证据:
用户价值:
影响范围:
实施方案:
迁移与回滚:
验证结果:
```

定期评审汇总应包含：

- 已完成并通过验证的工作包
- 真实用户体验变化
- 仍需跟进的问题
- 兼容性、数据迁移和新增依赖说明
- 下一批最高价值工作

## 17. 最终完成定义 / Definition of Done

当产品主链路可靠、核心功能好用、安装使用顺畅，并且剩余问题均已清晰记录时，本阶段委派工作可以结束：

1. 所有可执行工作包均完成并有执行日志证据。
2. 主链路可选能力失败时有 diagnostics。
3. 公开入口矩阵和 schema 兼容性有持续保护。
4. 测试不会污染仓库 demo workspace。
5. Ontology、检索、contracts、chain、reasoning 语义一致。
6. Query Quality 有稳定正反例和量化结果。
7. Freshness、Context Pack、Domain、Onboarding 已进入默认工作流。
8. Tree-sitter、增量索引、Sparse、Vector 均有稳定可选路径。
9. Unified Backend、Metrics、Benchmark、Audit、Health 形成治理闭环。
10. Workflow、Verification、Runtime Audit、Bundle Export 可用。
11. Constitution、规格追踪、Clarify 和跨工件分析可用。
12. Diff scope、change bundle、rule preview 和 review finding 验证形成闭环。
13. 外部 review/spec 工具仅通过受控可选 adapter 集成。
14. 文档、实现、兼容性和发布说明一致。
15. 关键测试、compile、构建、安装和入口 smoke 通过；存量 lint 债务有清晰记录和治理方向。
16. 没有私有路径、密钥或私有 workspace 生成物。
17. 所有未完成事项均转化为明确的后续工作和优先级，不因旧计划状态阻塞继续开发。
