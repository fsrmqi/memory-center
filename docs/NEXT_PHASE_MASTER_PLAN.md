# Next Phase Master Plan / 下一阶段总方案

## 1. 文档定位

这份文档只保留**还没收口的方向**。

已经稳定、已经完成并且已经进入主文档体系的能力，不再在这里重复列清单。  
这份文档只回答三件事：

1. 现在还剩什么最值得继续做
2. 下一步先做哪个
3. 哪些外部思想还没有真正吸收到实现里

如果你只是想看当前系统怎么用，优先看：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
- [docs/MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)
- [docs/REFERENCE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/REFERENCE.md)

## 2. 当前剩余重点

| 优先级 | 方向 | 目标 |
| --- | --- | --- |
| 1 | 轻量本体论 / Ontology | 用统一实体、关系、语义强度收紧 `query / contracts / chain / timeline` 的边界 |
| 2 | 检索质量继续收口 | 让 `mc_lookup`、`query`、`resume` 不再因意图误判或 contracts 关联过宽而偏航 |
| 3 | Benchmark 趋势化真正落地 | 不只是能跑 benchmark，而是能长期看哪条链路又变胖了 |
| 4 | Completion audit 产品化 | 让 audit 从“仓库自检工具”继续走向“真实 workspace 可用的治理能力” |
| 5 | Timeline / ref / task 体验增强 | 让 drill-down 真正融入日常入口 |
| 6 | SQLite 主读路径继续推进 | 让 backend 更像稳定主读底座，而不是高频优先补充层 |

## 3. 下一步先做什么

如果只选一个，我建议先做：

### `轻量本体论 / Ontology`

原因：

- 当前系统已经有 graph、timeline、ref、receipt、task、handoff、contracts、group chain
- 但这些能力之间还缺少一层统一的“领域语言”
- 没有 ontology 约束时，后面继续做 retrieval、chain、audit，很容易再次出现语义漂移

这一步不是去做一个很重的知识图谱工程，而是先补一层**约束文档 + 关键实现边界**。

## 4. 推荐执行顺序

### 阶段 A：定义 ontology 约束层

目标：

- 统一 `memory-center` 里的核心实体、关系和推断边界

建议动作：

1. 新建 `docs/ONTOLOGY.md`
2. 第一版只定义：
   - 代码实体：`Service / Class / Method / Endpoint / FeignClient / FeignMethod / MQTopic / MQConsumer / ConfigKey`
   - 记忆实体：`SessionEvent / WriteReceipt / Ref / Task / Handoff / ResumePacket`
   - 关系类型：`CALLS / CALLS_SERVICE / IMPLEMENTS_FEIGN / PUBLISHES / CONSUMES / REFERENCES / BELONGS_TO_TASK / DERIVED_FROM`
   - 语义强度：`fact / inferred / derived`
3. 把 ontology 先作用到：
   - `detect_query_intent`
   - `memory_query_hybrid`
   - `contracts / chain / group_chain`
   - `timeline / ref / receipt / task`

完成标志：

- 查询意图更稳
- 关系语义更清楚
- 文档里能明确区分“事实关系”和“推断关系”

### 阶段 B：检索质量继续收口

目标：

- `mc_lookup / query / resume / handoff` 的结果更准

建议动作：

1. 继续收紧 Feign / API / Service 的区分逻辑
2. 为 contracts 补充层增加更强的精确匹配和置信度表达
3. 为 callers / callees / chain / context 增加更强行为测试

完成标志：

- 本地 service 查询不再被误导到 Feign contracts
- Feign / API / chain 结果更少“像命中、实际不准”

### 阶段 C：Benchmark 趋势化

目标：

- 长期知道哪条链路 token 又变胖了

建议动作：

1. 固定高频函数 benchmark 基线
2. 补趋势视图与回归阈值
3. 将趋势结果接到 `work-health` / `mc_admin`

完成标志：

- 每次优化都能量化收益
- 能快速定位 token 回归链路

### 阶段 D：Completion audit 产品化

目标：

- 让 audit 真正适配普通 workspace，而不是只适配当前仓库

建议动作：

1. 继续减少对仓库结构的隐式假设
2. 增加 Java / Maven / Gradle / frontend 项目规则覆盖
3. 将设计选择与真实 bug 的判断继续沉淀到 `SPECIAL_NOTES`

完成标志：

- 不同类型 workspace 跑 audit 时假阳性更少
- audit 输出更像治理建议，而不是简单报缺文件

### 阶段 E：Timeline / ref / task 体验增强

目标：

- 让 drill-down 真正参与日常工作流

建议动作：

1. 给 `DrillDownNavigator` 补更多真实行为测试
2. 继续评估并扩展 CLI / MCP / HTTP 正式入口
3. 为 handoff / resume 增加更强摘要层

完成标志：

- 不只是 Python API 能用
- 人和模型都能顺着 ref 快速追到证据

### 阶段 F：SQLite 主读路径继续推进

目标：

- 让 `memory.db` 更稳定地承担聚合与主读职责

建议动作：

1. 继续统一高频读取到 backend
2. 避免 UI / eval / query 三套口径分叉
3. 为 backend 聚合补更稳定过滤能力

完成标志：

- 高频查询口径更一致
- JSONL fallback 继续减少

## 5. 外部思想剩余吸收点

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

### 本体论 / UModel / STAROps 方向

剩余重点：

- 将“对象优先、关系显式、推断边界明确”的思想收成轻量 ontology
- 先约束 `memory-center` 自己的领域语言，再继续叠加 retrieval / audit / chain 能力

## 6. 当前最值得继续补的检查点

当前后续开发时，最值得继续盯住的是：

1. 新能力是否真正接到了 CLI / MCP / HTTP 主入口
2. 行为测试是否真的覆盖了真实输入输出，而不是只测“模块存在”
3. 文档是否继续收敛，避免重新出现“完成”和“未完成”混写

## 7. Done 定义

下一阶段不只看“功能有没有”，还要看：

1. 结果是不是更准
2. token 是否更稳
3. audit 是否更可信
4. ontology 是否开始真正约束代码语义
5. 文档是否继续保持收敛
