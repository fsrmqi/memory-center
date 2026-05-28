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

## 4. 外部思想吸收现状

### `agentmemory`

已经吸收：

- token benchmark
- top-K evidence
- compact + budget

待继续：

- hybrid retrieval
- benchmark 趋势化

### `rtk`

已经吸收：

- token gain
- 工具专用 payload 压缩器

待继续：

- discover / 热点命令发现
- 更强命令压缩矩阵

### `mattpocock/skills`

已经吸收：

- workflow 化
- facade 化

待继续：

- 更强约束模板
- 更标准的模型内工作协议

### `Understand-Anything`

已经吸收：

- workbench
- ref / timeline / task drill-down 方向

待继续：

- 更强 onboarding
- 更强图形化导航

## 5. 当前阶段判断

项目已经不再是 MVP，也不是单纯“功能集合”，而是进入了：

- 收口
- 稳定化
- 长期维护体验优化

当前真正大的风险，不再是“功能没有”，而是：

- 入口太多导致心智混乱
- 高级能力和默认行为可能继续分叉
- 文档与实现再次漂移

## 6. 下一阶段 Done 定义

下一阶段不应只看“又加了什么功能”，而应看：

1. 真实日常使用是不是更顺
2. token 是否更稳
3. 模型切换是否更自然
4. SQLite 是否承担更多真实查询
5. 文档是不是继续保持收敛而不再膨胀

## 7. 关联文档

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [TECHNICAL_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/TECHNICAL_GUIDE.md)
- [docs/ROADMAP.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ROADMAP.md)
- [docs/ARCHITECTURE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/ARCHITECTURE.md)
