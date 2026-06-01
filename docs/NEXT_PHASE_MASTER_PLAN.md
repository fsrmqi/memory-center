# Next Phase Master Plan / 下一阶段总方案

## 1. 文档定位

这份文档只保留**还没收口的方向**。

已经做完、已经稳定的能力，不再在这里重复罗列；它们应该体现在：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)

这份文档回答的是：

- 现在还剩什么最值得做
- 下一步先做哪个
- 外部思想还剩哪些没有真正落地

## 2. 当前剩余重点

| 优先级 | 方向 | 目标 |
| --- | --- | --- |
| 1 | 检索质量继续收口 | 让 `mc_lookup`、`query`、`resume` 不再因为意图误判或 contracts 关联过宽而偏航 |
| 2 | Benchmark 真正趋势化 | 不只是能跑 benchmark，而是能长期看哪条链路又变胖了 |
| 3 | Completion audit 产品化 | 让 audit 从“仓库自检工具”继续走向“真实 workspace 可用的治理能力” |
| 4 | Timeline/ref/task 体验增强 | 让 drill-down 不只是底层类存在，而是真正融入日常入口 |
| 5 | SQLite 主读路径继续推进 | 让 backend 更像稳定主读底座，而不是高频优先补充层 |

## 3. 下一步先做什么

如果只选一个，我建议先做：

### `检索质量继续收口`

原因：

- 这是日常体验最直接的部分
- 当前 `hybrid retrieval` 已经接入主入口，但意图判断和 contracts 关联仍有偏航空间
- 一旦查错方向，后面的 benchmark、timeline、backend 都是在优化错误结果

建议先收这 3 件事：

1. 收紧 Feign 意图识别，避免把普通 `*Service` 误判成 Feign
2. 继续收紧 Feign → API 的关联条件，降低误关联
3. 为 `memory_query_hybrid` 补更强的行为测试，而不是只测模块存在性

## 4. 分阶段流程

### 阶段 A：检索质量

目标：

- `mc_lookup` / `query` / `resume` 结果更准
- contracts / graph / semantic 的融合更稳

建议动作：

1. 收紧意图识别规则
2. 优化 contracts 补充层的精确匹配逻辑
3. 为 callers / callees / chain / contracts 查询补更强行为测试

完成标志：

- 本地 service 查询不再被误导到 Feign contracts
- Feign / API 结果更少“看起来像命中，实际不准”

### 阶段 B：Benchmark 趋势化

目标：

- 长期知道哪条链路 token 又变胖了

建议动作：

1. 固定高频函数 benchmark 基线
2. 补趋势视图与回归阈值
3. 将趋势结果接到 `work-health` / `mc_admin`

完成标志：

- 每次优化后都能量化收益
- 能快速定位回归链路

### 阶段 C：Completion audit 产品化

目标：

- 让 audit 真正适配普通 workspace，而不是只适配当前仓库

建议动作：

1. 继续减少对仓库结构的隐式假设
2. 增加 Java / Maven / Gradle / frontend 项目的规则覆盖
3. 将设计选择与真实 bug 的判断继续沉淀到 `SPECIAL_NOTES`

完成标志：

- 不同类型 workspace 跑 audit 时假阳性更少
- audit 输出更像治理建议，而不是简单报缺文件

### 阶段 D：Timeline / ref / task 体验增强

目标：

- 让 drill-down 真正参与日常工作流

建议动作：

1. 给 `DrillDownNavigator` 补真实行为测试
2. 评估是否接入 CLI / MCP / HTTP 的正式入口
3. 为 handoff / resume 增加更强摘要层

完成标志：

- 不是只有 Python API 能用
- 人和模型都能顺着 ref 快速追到证据

### 阶段 E：SQLite 主读路径继续推进

目标：

- 让 `memory.db` 更稳定地承担聚合与主读职责

建议动作：

1. 继续统一高频读取到 backend
2. 避免 UI / eval / query 三套口径分叉
3. 为 backend 聚合补更稳定过滤能力

完成标志：

- 高频查询口径更一致
- JSONL fallback 继续减少

## 5. 当前明确还要补的代码问题

截至目前，我认为最值得尽快收的有：

1. `tests/test_public_mvp.py` 里存在断言串位  
   `test_merge_artifact_section_preserves_following_sections()` 下面挂进了不属于它的 `sniffed` 相关断言，变量作用域都不对。

2. `detect_query_intent()` 的 Feign 规则偏宽  
   当前 `^[A-Z][a-zA-Z]*Service$` 会把很多普通本地 service 也判成 Feign，这会把查询路径带偏。

3. `tests/test_next_phase.py` 里不少是“模块存在性测试”  
   还不够支撑文档里已经宣称的行为级能力，需要继续补真实输入/输出测试。

## 6. 外部思想剩余吸收点

### `agentmemory`

剩余重点：

- retrieval 质量继续做稳
- benchmark 趋势化与长期回归

### `rtk`

剩余重点：

- discover / 热点命令发现
- 更强命令压缩矩阵
- 命令输出前置压缩层

### `mattpocock/skills`

剩余重点：

- 更强约束模板
- 更标准的模型内工作协议
- 自动选择 `resume / start / analyze` 的更强策略

### `Understand-Anything`

剩余重点：

- 更强 onboarding
- 更强图形化导航
- 更直观的 task / timeline / ref 导航链

## 7. Done 定义

下一阶段不只看“功能有没有”，而要看：

1. 结果是不是更准
2. token 是否更稳
3. audit 是否更可信
4. 文档是否继续收敛
5. 新增能力是否真正接到了用户入口
