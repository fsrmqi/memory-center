# Special Notes / 特殊说明

## 1. 文档定位

这份文档专门记录一些**容易被误解、但其实是设计取舍**的行为。

适合放在这里的内容包括：

- 看起来像 bug，其实是有意为之
- 默认值和直觉不一致，但背后有宿主兼容性原因
- 某些接口 / Hook / facade 不是“不能做”，而是“默认不这么做”
- 为了日常使用体验、token、宿主兼容性而做的非直觉选择

如果你只是想正常使用系统，优先看：

- [README.md](/Users/cuijiaqi/Ai-common-skills/memory-center/README.md)
- [USER_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/USER_GUIDE.md)
- [MCP_GUIDE.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/MCP_GUIDE.md)

## 2. `user_prompt_submit` 默认禁用

### 现象

在 `hooks.yaml` / 默认 hook 配置中，`user_prompt_submit` 当前是：

- `mode: suggest`
- `enabled: false`

这意味着：

- 从“类型”上说，它属于建议型 Hook
- 但从“默认行为”上说，它是关闭的
- runner 会先检查 `enabled`
- 所以 `enabled: false` 时，会直接表现为“不参与执行”，不会继续进入 `suggest` 分支

### 为什么不是 bug

这不是简单写错，而是一个明确的产品策略：

- `UserPromptSubmit` 挂在**自然语言输入入口**
- 对 Claude Code / Codex 这类宿主来说，suggest 型 prompt hook 很容易被解释成一次前置判断步骤
- 普通输入例如：
  - `继续`
  - `下一步`
  - `同步下文档`
  - `接着做`
  
  都可能因此被打断，出现：
  - `Operation stopped by hook`
  - `No Memory Center context is needed`

所以当前选择是：

- 保留 `suggest` 这种 hook 类型定义
- 但默认 `enabled: false`
- Claude Code / Codex adapter 默认也不生成这条 Hook

换句话说，这不是：

- “本来想默认启用 suggest，结果代码写错了”

而是：

- “这个 Hook 的类别仍然是 suggest”
- “但默认策略明确要求它不要参与执行”

### 正确理解

当前正确语义不是：

- “`user_prompt_submit` 默认启用并以 suggest 模式运行”

而是：

- “`user_prompt_submit` 属于 suggest 型 Hook，但默认禁用”

### 什么时候才适合启用

只有在满足下面条件时，才建议启用：

1. 宿主不会把 advisory prompt 当成拦截器
2. 团队明确希望在用户输入入口做额外提示
3. 能接受普通自然语言请求有额外前置判断步骤

否则更推荐：

- `SessionStart -> mc_start`
- `PreToolUse(Edit|Write) -> mc_analyze`
- `Stop -> mc_close`

而不是把 `UserPromptSubmit` 挂成默认自动行为。

### 更推荐的自动化方式

当前默认推荐把自动调用放在**生命周期明确的节点**，而不是自然语言输入本身：

1. `SessionStart -> mc_start`
2. `PreToolUse(Edit|Write) -> mc_analyze`
3. `Stop -> mc_close`

原因是：

- 生命周期 Hook 的语义稳定
- 参数边界更清楚
- 不容易误伤普通自然语言输入
- 更适合 Claude Code / Codex 这类宿主

## 3. `mode` 与 `enabled` 的关系

Hook 配置里：

- `mode` 表示“如果启用，这条 hook 应该怎么执行”
- `enabled` 表示“这条 hook 当前是否参与执行”

所以：

- `enabled: false`
- `mode: suggest`

并不冲突。

这表示：

- 它的执行类型定义仍然是 suggest
- 但当前配置明确要求不启用它

## 4. facade 与原子能力并存，不是重复设计

当前系统里：

- MCP 默认对模型暴露 8 个 facade 工具
- CLI / HTTP / core 内部仍保留很多原子能力

这不是重复设计，而是刻意分层：

- 模型面对 facade，降低工具选择成本和 token 开销
- 人类维护者和内部实现仍然需要原子能力做细粒度控制

所以看到“原子工具还在”不代表 facade 重构失败。

## 5. SQLite `memory.db` 不是唯一真相源

当前 `memory.db` 的定位是：

- 镜像
- 高频读路径优先查询
- 聚合、观测、workbench 支撑

但它**不是唯一事实源**。

系统仍然保留：

- JSON
- JSONL
- Markdown

这样做是为了：

- 保持可读性
- 保持可追踪性
- 降低一次性强切主后端的风险

所以看到代码里同时存在：

- `read_json*`
- `read_json*_prefer_backend`

并不表示设计不统一，而是渐进切换中的有意状态。

## 6. 文档与实现冲突时怎么判断

如果出现：

- 文档说“应该这样”
- 代码实际“不是这样”

优先判断顺序建议是：

1. 先看当前代码实现
2. 再看这是不是有意的宿主兼容性 / token / UX 取舍
3. 如果是有意取舍，把原因补进这份文档
4. 如果不是有意取舍，再认定为 bug

也就是说，这份文档本身就是为了减少”把设计选择误判成 bug”的情况。

## 7. `async` 标记是宿主/Adapter 配置，不在 Runner 内消费

### 现象

`hooks.yaml` 中每条 hook 都可以声明 `async: true`，且 Claude Code adapter 会将其写入 `settings.json`：

```jsonc
// settings.json 生成结果
“async”: true
```

但 `run_hook` 函数本身始终同步执行：解析参数 → 调 facade → 返回结果 dict。runner 内部没有任何异步逻辑。

### 为什么不是 bug

`async` 标记的消费方是**宿主**（Claude Code / Codex），不是 runner。

宿主看到 `async: true` 后，决定是否在后台运行该 hook、是否设置超时、是否等待结果。runner 只是一个一次性执行器，由宿主在合适的时机调用，它不需要知道自己是被同步还是异步调用的。

### 正确理解

- `async: true` = “告诉宿主，这条 hook 适合异步执行”
- runner 内部 = “同步执行一次，返回结果”
- 两者不冲突，因为 `async` 是给宿主的建议，不是给 runner 的指令

### 什么时候需要改

只有当 runner 本身需要支持并发执行（如内部线程池、asyncio）时，才需要在 runner 内消费 `async`。当前架构下不需要。
