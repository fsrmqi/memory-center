# Next Phase Master Plan / 下一阶段总方案

## 1. 文档定位

这份文档不是给首次使用者看的快速指南，而是给维护者看的：

- 当前已经做到哪里
- 后面最值得继续做什么
- 哪些外部思想已经吸收
- 哪些还只是方向

对外简版路线图请看：

- [docs/ROADMAP.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ROADMAP.md)

## 2. 当前已完成的主线

### 工作包 1：增量索引

已完成：

- `reindex --project`
- `reindex --path`
- `reindex --changed-only`
- `--scope staged|head|all`
- 局部 graph rebuild
- 局部 semantic rebuild
- 删除文件处理

### 工作包 2：轻量上下文协议

已完成：

- `view=compact|full`
- `budget=small|medium|large`
- 7 个高频大返回统一支持
- token gain
- token benchmark
- top-K evidence

### 工作包 3：引用与时间线

已完成：

- short refs
- `memory_ref_get / batch`
- timeline substrate
- handoff / receipt / session_event 统一到 timeline 模型

### 工作包 4：工作流系统

已完成：

- `work-*` CLI
- MCP facade 8 工具
- HTTP workflow 入口
- Hook runner / adapters 基础能力

### 工作包 5：可视化工作台

已完成：

- `/ui`
- `dashboard`
- `continuity`
- `task`
- `timeline`
- `ref`
- `usage`
- `backend`
- `index-freshness`

### 工作包 6：统一后端与评测

已完成：

- SQLite `memory.db` 镜像
- backend query
- 高频读路径部分优先走 backend
- continuity / handoff / token / index freshness 等评测

## 3. 当前最值得继续推进的方向

按收益排序，我建议是：

1. `hybrid retrieval`
2. benchmark 趋势化与长期回归
3. SQLite 继续接更多主读路径
4. timeline / ref / task 更强 drill-down
5. completion audit

## 4. 下一阶段完整优化流程

这一阶段不建议再“哪里痛补哪里”，而是按一条稳定主线推进。推荐顺序如下：

### 阶段 A：检索层继续收口

目标：

- 让 `mc_lookup`、`query`、`resume`、`handoff` 在真实复杂项目里更稳定
- 减少 “查得到一点，但接不下去” 的半截结果

建议动作：

1. 完成 `hybrid retrieval`
2. 将 graph / sparse / semantic 的路由规则明确下来
3. 为 Feign、MQ、config、timeline 这类高频场景补更稳定的召回策略
4. 对跨 workspace 链路补 summary 层，而不是只返回长结果

阶段完成标志：

- `lookup` 在本地项目中不再频繁退化为人工补搜
- callers / callees / chain / context 的结果更一致
- benchmark 能看出召回质量提升而不是纯返回变大

### 阶段 B：token 与 benchmark 体系产品化

目标：

- 不只是“现在 token 少了”，而是长期知道哪条链路又变胖了

建议动作：

1. 将 `token benchmark` 扩展为趋势记录
2. 固定高频函数 benchmark 基线
3. 输出每个 budget 下的 token 变化曲线
4. 将 benchmark 结果接入 `work-health` / `mc_admin` / workbench

阶段完成标志：

- 每次改动后能快速判断 token 是升是降
- 能定位是哪条链路变重
- 可以对 `compact / budget / top-K` 的收益做长期回归

### 阶段 C：SQLite 主读路径继续推进

目标：

- 让 `memory.db` 从“高频路径优先”继续走向“稳定主读底座”

建议动作：

1. 将更多 `session / receipt / handoff / task summary / evidence` 读取优先切到 backend
2. 统一 `read_json*_prefer_backend` 的调用策略
3. 将 UI 和 eval 尽量复用 backend 查询结果
4. 为 backend 查询增加更稳定的聚合与过滤能力

阶段完成标志：

- 高频查询不再到处分叉读 JSONL
- timeline / usage / continuity / receipt 口径一致
- backend 成为默认观察与聚合层

### 阶段 D：timeline / ref / task 的使用体验增强

目标：

- 让 Memory Center 更像“会协作的工作台”，不是一组数据结构

建议动作：

1. 加强 ref 展开与反向跳转
2. 增强 task → timeline → receipt → ref 的 drill-down
3. 为 handoff / resume 增加更强摘要层
4. 让 facade 输出优先给摘要、细节按 ref 展开

阶段完成标志：

- 模型和人都能沿着一条线快速追到证据
- 不再需要大量人工切换工具和文件

### 阶段 E：completion audit 与文档持续收口

目标：

- 防止实现继续走、文档再漂

建议动作：

1. 定期按工作包做 completion audit
2. 每轮能力增强后同步：
   - `README`
   - `MCP_GUIDE`
   - `REFERENCE`
   - `SPECIAL_NOTES`
3. 将“设计选择”与“真实 bug”继续分离记录

阶段完成标志：

- 文档能真实反映实现
- 新人读文档不容易误判行为
- 维护成本继续下降

## 5. 外部思想吸收现状

### `agentmemory`

已经吸收：

- token benchmark
- top-K evidence
- compact + budget

待继续：

- hybrid retrieval
- benchmark 趋势化
- benchmark 持久化与回归基线

### `rtk`

已经吸收：

- token gain
- 工具专用 payload 压缩器

待继续：

- discover / 热点命令发现
- 更强命令压缩矩阵
- 命令输出前置压缩层

### `mattpocock/skills`

已经吸收：

- workflow 化
- facade 化

待继续：

- 更强约束模板
- 更标准的模型内工作协议
- 自动选择 resume / start / analyze 的更强策略

### `Understand-Anything`

已经吸收：

- workbench
- ref / timeline / task drill-down 方向

待继续：

- 更强 onboarding
- 更强图形化导航
- 更直观的 task / timeline / ref 导航链

## 6. 推荐落地顺序

如果按“先做什么最值钱”排，我建议顺序是：

1. `hybrid retrieval`
2. benchmark 趋势化
3. SQLite 主读路径继续推进
4. timeline / ref / task 体验增强
5. completion audit + 文档收口

这条顺序的核心原则是：

- 先提升结果质量
- 再控制成本
- 再巩固底座
- 最后做体验和治理

## 7. 当前阶段判断

项目已经不再是 MVP，也不是单纯“功能集合”，而是进入了：

- 收口
- 稳定化
- 长期维护体验优化

当前真正大的风险，不再是“功能没有”，而是：

- 入口太多导致心智混乱
- 高级能力和默认行为可能继续分叉
- 文档与实现再次漂移

## 8. 下一阶段 Done 定义

下一阶段不应只看“又加了什么功能”，而应看：

1. 真实日常使用是不是更顺
2. token 是否更稳
3. 模型切换是否更自然
4. SQLite 是否承担更多真实查询
5. 文档是不是继续保持收敛而不再膨胀

## 9. 关联文档

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/TECHNICAL_GUIDE.md)
- [docs/ROADMAP.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ROADMAP.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
