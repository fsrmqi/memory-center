# 当前焦点任务的 Session-first 改造方案 / Session-first Focus Task Proposal

> 文档类型：架构与交互改造方案（proposal）  
> 状态：待评审  
> 范围：Memory Center、Memory Center DSH Plugin；不改变 Personal Assistant Wiki 的权威边界。

## 1. 问题定义 / Problem

当前 DSH 工作台将工作区所有 L2 task space 中“仍为 `active` 且最近更新”的第一项直接展示为“当前焦点任务”。这是一种**工作区级排序结果**，却被呈现为**当前会话级事实**。

结果是：用户在另一个仓库、另一段对话，甚至只是做只读排查时，旧的 UCap L2 任务仍会出现在首页的“当前焦点任务”“现在就做”“最近进展”和交付面板中。它会制造错误的归属感，并可能诱导后续恢复、附着或晋升操作使用错误的 task ID。

另有一个写入门禁缺口：调用方传入 `sync_task_space=false` 时，`mc_start` 仍可能因自动解析命中候选任务而将 session/shadow 绑定到该 L2 task。`sync_task_space=false` 的合理语义应是“不进行任何自动 L2 绑定或写入”，而非“只禁止本次同步”。

## 2. 已确认的现状 / Verified Current Behavior

| 位置 | 当前行为 | 问题 |
| --- | --- | --- |
| `workspace_status` | `current_focus_task = active_tasks[0]` | 没有 session、线程或显式 task 绑定输入。 |
| `_active_task_summaries` | 按 `active` 优先、`updated_at` 倒序排列 | “最近更新”不等于“当前正在做”。 |
| DSH bridge | 工作台固定请求 `/workspace/workbench-summary?limit=5` | 请求未携带 `session_id`、host thread ID 或 task 选择。 |
| DSH UI | 将返回的 `focus_task` 标为“当前焦点任务” | 把工作区候选误展示为当前事实。 |
| `mc_start` | `sync_task_space=false` 下仍可能用 `auto_bindable` 设置 `bound_task_id` | 违背调用方要求的无自动绑定语义。 |

Task Shadow（L1）的设计方向仍然正确：未明确绑定的工作应留在 session-first 的临时连续性层，不得污染 L2。问题在于目前的首页投影和 `mc_start` 的绑定条件没有完整贯彻这个边界。

## 3. 目标与非目标 / Goals and Non-goals

### 目标

1. **无可信 session 绑定，就没有当前焦点任务。**
2. L1 Task Shadow 成为新会话/未归类工作的默认首页上下文。
3. L2 task space 只在用户显式选择，或标题/标签直接锚定且调用方允许自动绑定时才成为当前焦点。
4. 历史 L2 任务保留为“可恢复任务”，不再自动占用当前工作区域。
5. Wiki 只按当前可信锚点（绑定任务或 Shadow 意图）提供长期知识候选；不得参与焦点任务判定。

### 非目标

- 不删除、重命名或批量迁移既有 L2 任务空间。
- 不改变 Task Shadow、L2 工件或 MCP tool 的既有公开 schema；新增字段必须 additive。
- 不自动把当前对话、Wiki 条目或 DSH 完成消息升级为 L2 或长期知识。

## 4. 目标交互模型 / Target Interaction Model

```text
当前 DSH session / host thread
          |
          +-- 有 explicit_task_id 或可信 direct anchor
          |        -> L2 已绑定任务 = Current Focus
          |
          +-- 没有可信绑定
                   -> L1 Task Shadow = Current Work (unbound)
                   -> L2 active tasks = Resumable Tasks（仅候选列表）
```

首页必须展示以下三种互斥状态：

| 状态 | 首页主标题 | 可用动作 |
| --- | --- | --- |
| `bound` | 当前焦点任务：`<L2 title>` | 继续、查看任务、解除/切换任务。 |
| `shadow_only` | 当前工作尚未绑定工程任务 | 继续 Shadow、选择已有任务、显式创建/绑定任务。 |
| 无 session 上下文 | 未连接当前会话 | 浏览工作区任务；不得展示任何任务为“当前”。 |

“可恢复任务”可展示旧 L2 的标题、更新时间和摘要，但文案不能使用“当前”“现在就做”，也不能把其 `next_actions`、交付进度或 Wiki 候选灌入当前会话。

## 5. P0：必须先修复的语义门禁 / P0 Gates

### P0-1：`sync_task_space=false` 必须禁止自动绑定

`mc_start` 的 `bound_task_id` 应满足：

```text
auto_bind = sync_task_space
         AND auto_bindable_direct_anchor
         AND resolved_task_id is present
```

当 `sync_task_space=false` 时：

- session metadata 的 `task_binding.mode` 必须是 `shadow_only`；
- 不得向 Shadow 调用 `bind_shadow_to_task`；
- 返回解析候选仅用于 UI 建议，`candidate_tasks` 不代表绑定；
- `mc_close`、`mc_sync(auto)` 必须继续沿用 `shadow_only`，除非后续收到明确 `task_id`。

建议新增 additive 审计字段 `binding_reason_code`，至少区分：`explicit_task_id`、`direct_anchor`、`auto_binding_disabled`、`ambiguous_candidate`、`no_session_context`。

### P0-2：焦点计算改为 session-aware

为 `workspace_workbench_summary` 和连续性读模型新增可选输入 `session_id`（以及宿主可用时的 thread ID）。选择优先级固定为：

1. 显式请求的 `task_id`，仅用于用户明确选择的详情页；
2. 当前 session 已记录且可信的 `task_binding.task_id`；
3. 当前 session 的未绑定 Task Shadow；
4. 无焦点（不允许回退到 `active_tasks[0]`）。

`active_tasks[0]` 只能作为 `resumable_tasks[0]` 的排序候选，不能再赋给 `focus_task`。

### P0-3：DSH bridge 与 UI 传递 session 语境

DSH bridge 的 `workbench`、`continuity`、`task-delivery` 读取必须携带当前 DSH session ID。若 bridge 无法获得 session，必须传入 `context_state=unbound` 或不传并接受“无焦点”的响应；禁止伪造 task ID。

UI 应按 `focus.kind` 或 `focus.binding_mode` 渲染：

- `task`：展示“当前焦点任务”；
- `shadow`：展示“当前工作（未绑定）”；
- `none`：展示“尚未选择工程任务”。

## 6. P1：可用性与防误操作 / P1 Improvements

1. 在“可恢复任务”卡片提供显式的“设为当前任务”动作，要求用户确认 task title；该动作创建可审计的显式绑定。
2. 为已超过阈值未活动的 L2 显示 `stale`，并在默认列表中折叠；只影响显示，不修改任务状态。
3. 在工作区切换时清空前一个 workspace 的 session/task 选择，不允许跨 workspace 继承 L2 task ID。
4. 在 Wiki 知识页仅以当前 `task_id` 或 Shadow 的受限意图检索；无锚点时返回空状态或仅展示已注册的 workspace 资产。
5. 在工作台加入“为什么显示这个任务”的简短说明，显示 `binding_reason_code` 和绑定时间，避免不可解释的自动归属。

## 7. 接口与兼容性 / API Compatibility

保持既有返回字段兼容，新增字段：

```json
{
  "focus": {
    "kind": "task | shadow | none",
    "task_id": "",
    "shadow_id": "",
    "binding_mode": "explicit | auto_direct_anchor | shadow_only | none",
    "binding_reason_code": "",
    "is_current_session_bound": false
  },
  "resumable_tasks": []
}
```

过渡期可继续返回旧字段 `focus_task`，但其含义必须改为：仅在 `focus.kind="task"` 时为非空。新客户端优先读取 `focus`；旧客户端看到空 `focus_task` 时应显示无焦点而不是选择首个活跃任务。

## 8. 实施顺序 / Implementation Plan

1. 在 `mc_start` 收紧 `sync_task_space=false` 的自动绑定条件，并新增回归测试。
2. 抽出 `resolve_session_focus(...)`：只接受显式 task、可信 session binding 或 Shadow；禁止读取 `active_tasks[0]` 作为回退。
3. 为 `workspace_workbench_summary`、continuity dashboard 和 HTTP routes 添加可选 `session_id` 参数及 additive `focus` 输出。
4. 调整 DSH bridge，传递 session ID；调整 UI 的 hero、下一步、交付中心及 Wiki 查询的状态分支。
5. 将旧的 `current_focus_task` 在页面文案上降级为“最近可恢复任务”或删除其 global fallback。
6. 以真实 UCap workspace 和非 UCap workspace 各做一次回放，验证不会跨 workspace 或跨 session 继承焦点。

## 9. 测试与验收 / Tests and Acceptance

### 单元/领域测试

- `sync_task_space=false` + 任意高分历史候选：返回 `shadow_only`，无 `bound_task_id`，不调用 bind。
- `sync_task_space=true` + `title_exact/tag_exact`：允许 `auto_direct_anchor`。
- 仅 fuzzy/signature 候选：始终 `shadow_only`。
- 未传 `session_id` 的 workbench summary：`focus.kind=none`，不得从活跃任务列表补焦点。
- 已绑定 session：只返回该绑定的 L2 task，即使另一任务更新更晚。
- 未绑定 session：返回该 Shadow，`next_actions`、交付和 Wiki 查询不得借用任一 L2。
- workspace A 的 session/task ID 不得在 workspace B 的 summary 中生效。

### DSH 集成测试

- 新会话打开首页显示“当前工作尚未绑定工程任务”，旧 UCap 任务只在可恢复列表。
- 用户点击“设为当前任务”后，页面才切换到对应 L2 的下一步和交付时间线。
- session 未绑定时不展示历史任务的 Wiki 候选为“当前任务知识”。

### 验收标准

1. 当前用户在任意与 UCap 无关的工作中打开 DSH，不会看到 UCap 历史任务被标为当前焦点。
2. `sync_task_space=false` 不产生隐式 L2 绑定、L2 工件写入或 task-scoped Wiki 附着。
3. 用户仍可一键恢复真正想继续的历史任务，但这一操作可见、可解释、可审计。
4. 所有既有 MCP consumer 在不传新参数时保持可用，且不会获得错误焦点。

## 10. 决策建议 / Recommended Decision

先实施 P0，再讨论自动绑定率等优化。这里的优先级应是**避免错误归属**，而不是提高“自动恢复”的命中数量：误把历史任务当作当前任务的成本，远高于要求用户点击一次“继续该任务”的成本。

