# Context Engineering Narrative and Review Checklist / 上下文工程叙事与设计评审清单

> **Purpose / 用途**：本文件将 Context Engineering 的通用原则转化为 Memory Center 的产品叙事与设计评审问题。它不替代 [ARCHITECTURE.md](ARCHITECTURE.md)、[MCP_GUIDE.md](MCP_GUIDE.md) 或接口契约。
>
> **Baseline / 基线**：当前能力的逐项结论和后续候选项见 [CONTEXT_ENGINEERING_BASELINE_REVIEW.md](CONTEXT_ENGINEERING_BASELINE_REVIEW.md)。

## 1. Product Narrative / 产品叙事

### One sentence / 一句话

Memory Center gives coding Agents the smallest trustworthy engineering context needed for the next decision, instead of asking them to repeatedly reread an entire multi-service workspace.

Memory Center 的目标不是向 Agent 堆入更多资料，而是在每次关键决策前，提供最小、可信、可追溯的工程上下文，避免它在多服务 workspace 中反复从零搜索和猜测。

### The problem / 要解决的问题

大型工程中的 Agent 常有三种失效方式：上下文不足时靠猜测行动；上下文过多时淹没关键约束；会话中断后又重复探索。单纯扩大上下文窗口不能解决信噪比、事实新鲜度、契约影响面和经验可信度的问题。

Memory Center 将代码结构、跨服务关系、规则、任务状态和验证证据留在工作区的外部记忆中。Agent 按需通过任务级接口定位、展开和验证，而不是把完整仓库、完整历史或完整工具输出预先注入会话。

### The promise / 产品承诺

| 用户问题 | Memory Center 的回答方式 |
|---|---|
| 这次改动会影响谁？ | 基于图谱和契约返回有边界的影响分析，而非关键词猜测。 |
| 这个结论可靠吗？ | 返回 evidence level、freshness、coverage 与 `claim_boundary`。 |
| 上次做到哪里？ | 由 Session、Task Shadow、task artifacts、resume/handoff 提供有界恢复。 |
| 为什么推荐这一步？ | 返回可审查的证据、风险、下一步和验证要求。 |
| 会不会把原始对话或私有内容带走？ | 默认本地优先、脱敏持久化；完整宿主会话不进入 Memory Center。 |

## 2. Context Engineering Mapping / 上下文工程映射

| Context Engineering 要素 | Memory Center 的责任 | 明确不负责 |
|---|---|---|
| Instructions / 指令 | 提供可版本化的规则、workflow profile 与 Skill 证据 | 代替宿主系统提示或覆盖宿主策略 |
| State and history / 状态与历史 | Session、Task Shadow、任务工件、resume/handoff | 保存完整对话正文 |
| Long-term memory / 长期记忆 | L0.5 notes、L1 case、L2 task、L3 workspace profile | 未验证内容的自动晋升 |
| Retrieved information / 检索信息 | 图谱、BM25、语义/ANN、evidence ref、渐进展开 | 全量预加载或把空结果说成不存在 |
| Tools / 工具 | 面向任务的 MCP facade、结构化结果和审计 | 暴露无边界、职责重叠的原子工具集 |
| Structured output / 结构化输出 | evidence level、claim boundary、read targets、next actions | 用自然语言掩盖证据不足 |
| Context budget / 上下文预算 | 限制自身响应、证据展开和工件读取的体积 | 管理宿主 token 预算或自动压缩宿主会话 |

## 3. Ownership Boundary / 职责边界

Agent host owns the complete transcript, model-specific token accounting, conversation compaction, and recent-file state. Memory Center owns evidence-bounded retrieval, durable task continuity, and its own response/storage limits.

Agent 宿主负责完整会话、模型特定 token 统计、会话压缩与最近文件状态；Memory Center 负责有证据边界的检索、可持久化的任务连续性，以及自身响应和存储的容量控制。

因此，`mc_context_pack` 的预算、evidence-index 的渐进披露、任务工件归档、会话事件归档都仍然存在；它们控制的是 Memory Center 自己处理的数据量，不会自动压缩或重写宿主会话。

## 4. Design Review Checklist / 设计评审清单

在新增 MCP 能力、检索源、记忆层、宿主 adapter 或自动化流程前，逐项回答：

### 4.1 Context value / 上下文价值

- [ ] 这条信息会改变 Agent 的哪一项近期决策？
- [ ] 是否能在需要时 JIT 检索，而不是默认注入？
- [ ] 是否提供紧凑索引或引用，再按需展开正文？
- [ ] 是否删除或降级了过期、重复、无关的信息？

### 4.2 Trust and freshness / 可信度与新鲜度

- [ ] 每项结论是否标明直接事实、推断、歧义或已验证？
- [ ] 索引过期、覆盖不完整或查询截断时，是否限制负向断言？
- [ ] 涉及 DTO、Feign、MQ、HTTP、配置时，是否走契约消费者分析？
- [ ] 是否存在可复现的验证步骤或验证回执？

### 4.3 Memory lifecycle / 记忆生命周期

- [ ] 信息应进入 L0、L0.5、L1、L2 还是 L3？
- [ ] 是否保留 source reference、时间和 supersede/forget 审计？
- [ ] 未绑定的 Shadow 是否仍被限制在临时层？
- [ ] 是否避免把未经确认的模型摘要自动提升为长期经验？

### 4.4 Host and privacy / 宿主与隐私

- [ ] 宿主是否仍是完整对话和 token 预算的唯一权威方？
- [ ] 输入是否只包含允许持久化的脱敏字段，而非 prompt、源码正文或工具载荷？
- [ ] 新能力是否会默认注入、阻塞用户输入或扩大读取范围？如会，是否有显式配置和回滚？

### 4.5 Cost and operability / 成本与可运维性

- [ ] 是否有候选数、图遍历、响应大小、超时和重排等硬预算？
- [ ] 是否可观测检索质量、延迟、失败和 Agent 采纳情况？
- [ ] 是否能在 provider、索引或可选模型不可用时安全降级？
- [ ] MCP schema 是否 additive 且与 CLI/HTTP 入口保持一致？

## 5. Review Outcome / 评审结论模板

```text
Decision: adopt | revise | reject
User decision improved:
Minimal context supplied:
Evidence and freshness boundary:
Host ownership boundary:
Memory lifecycle and retention:
Budgets and safe degradation:
Validation evidence required:
Non-goals:
```

将结论写入 ADR、技术设计或 task artifact；不要把该清单本身当作功能需求或自动化门禁。具体实现仍以现行架构、MCP 协议和测试为准。
