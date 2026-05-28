# Memory Center 实施路线图 / Implementation Roadmap

> 目标：把 Memory Center 从“项目记忆工具”推进成“多模型 / 多工具 / 多会话协作底座”。

---

## 一、北极星目标

Memory Center 的最终目的，不是简单存储上下文，而是解决以下日常痛点：

1. 模型切换后任务断裂
2. 会话结束后上下文丢失
3. 工具调用产生大量证据但无法复用
4. 多 Agent 协作时缺少共享任务状态
5. 长任务缺乏持续记忆、过程审计和质量治理

最终状态应该是：

- 不同模型可低损接棒
- 不同工具结果可追溯复用
- 不同会话之间可恢复任务连续性
- 不同层级信息写入正确位置
- 整个写入链可评估、可审计、可回放

---

## 二、最终组件地图

建议把系统稳定为 8 个核心组件。

### 1. Memory Layer Engine

负责分层记忆本身。

- `L0_session_events`
- `L1_case_atoms`
- `L2_task_spaces`
- `L3_workspace_profile`

### 2. Write Governance Engine

负责“写哪层、怎么写、写完怎么查”。

- `memory_write_judge`
- `memory_plan_write`
- `memory_execute_write`
- append-only guard
- `write_receipt`
- `write-receipts.jsonl`
- `memory_eval_write_quality`

### 3. Task Continuity Engine

负责会话切断后还能继续干活。

- `workspace_resume_packet`
- `workspace_next_actions`
- `workspace_unresolved_items`
- `workspace_recent_evidence`
- `workspace_current_focus_task`

### 4. Cross-Model Handoff Engine

负责 Claude / Codex / Cursor / Gemini 之间接棒。

- `workspace_handoff_packet`
- `workspace_model_profile`
- `workspace_handoff_history`

### 5. Evidence & Replay Engine

负责证据沉淀、写入回放和过程审计。

- `source_refs`
- `payload_ref`
- `workspace_write_receipts`
- `workspace_replay_write_chain`
- `artifact-write-audit.jsonl`

### 6. Rule & Governance Engine

负责把工作方法学配置化。

- `write-quality-rules.yaml`
- `handoff-rules.yaml`
- `task-lifecycle-rules.yaml`
- `resume-rules.yaml`

### 7. Operational UX Layer

负责日常可用性。

- CLI
- MCP
- HTTP
- `workspace_dashboard`
- `workspace_status`
- `write_receipts_overview`

### 8. Evaluation Suite

负责证明系统真的提升工作效率。

- `memory_eval_write_quality`
- `memory_eval_resume`
- `memory_eval_handoff`
- `memory_eval_write_coverage`

---

## 三、分批实施计划

建议分 6 批实施，每批都能独立交付和日常使用。

---

## 第 1 批：记忆写入内核

### 目标

先把“能正确写、能安全写、能追踪写”打牢。

### 范围

- 分层记忆模型 `L0/L1/L2/L3`
- `memory_write_judge`
- `memory_plan_write`
- `memory_execute_write`
- append-only 写入保护
- `write_receipt`
- `write-receipts.jsonl`
- `workspace_write_receipts`
- `workspace_replay_write_chain`
- `memory_eval_write_quality`
- `workspace_status.write_receipts_overview`

### 当前状态

大部分已完成。

### 需收尾项

1. 统一所有写入入口的 `write_receipt` 结构
2. 统一 `layer/action/scope` 常量
3. 完整覆盖 CLI / MCP / HTTP 三条接入链
4. 完善写入质量评估规则

### 主要文件

- `memory_center/core/orchestrator.py`
- `memory_center/core/artifacts.py`
- `memory_center/core/write_receipts.py`
- `memory_center/cli/main.py`
- `memory_center/mcp/server.py`
- `memory_center/http/server.py`

### 验收标准

- 任意核心写入动作都能返回 `write_receipt`
- 所有 `write_receipt` 都能落入 `memory/write-receipts.jsonl`
- 能按 `layer/task_id/session_id/action` 查询
- 能按时间顺序回放一条写入链
- 能给出基础写入质量评分

---

## 第 2 批：任务连续性

### 目标

解决“会话断了，任务还能继续”的问题。

### 核心组件

- `workspace_resume_packet`
- `workspace_next_actions`
- `workspace_unresolved_items`
- `workspace_recent_evidence`
- `workspace_task_health`

### `resume_packet` 建议结构

```text
task_id
task_title
current_summary
current_phase
latest_risk_points
latest_receipts
relevant_files
relevant_symbols
next_recommended_actions
open_questions
verification_pending
```

### 主要文件

- `memory_center/core/orchestrator.py`
- `memory_center/core/artifacts.py`
- `memory_center/cli/main.py`
- `memory_center/mcp/server.py`
- `memory_center/http/server.py`

### 验收标准

- 给定 `task_id` 能生成标准恢复包
- 给定 `session_id` 能生成恢复包
- 恢复包可直接供下一个模型接手
- 恢复包中必须包含未完成事项和下一步动作

---

## 第 3 批：跨模型交接

### 目标

解决 Claude / Codex / Cursor / Gemini 来回切换时的理解损耗。

### 核心组件

- `workspace_handoff_packet`
- `workspace_model_profile`
- `workspace_handoff_history`
- `workspace_handoff_eval`

### `handoff_packet` 建议结构

```text
handoff_target_model
task_id
what_has_been_done
what_not_to_repeat
what_is_risky
what_to_check_next
minimal_required_context
best_tool_sequence
evidence_refs
task_space_refs
```

### 建议支持的目标模型

- `codex`
- `claude-code`
- `cursor-agent`
- `gemini`
- `generic-mcp-agent`

### 验收标准

- 相同任务可针对不同模型生成不同粒度交接包
- 交接包必须压缩冗余说明
- 交接包必须包含“不要重复做”的提醒
- 交接记录可追踪

---

## 第 4 批：规则化治理

### 目标

把你的工作方法学从代码逻辑提升成配置化系统。

### 核心配置

- `write-quality-rules.yaml`
- `handoff-rules.yaml`
- `task-lifecycle-rules.yaml`
- `resume-rules.yaml`

### 典型规则

- 有 `session_id` 必须至少写 L0
- 有 `task_id` 必须至少写 L2
- 长任务结束后必须出现 `current_summary`
- 契约变更类任务必须调用 `workspace_check_contract`
- 规则/规范类任务必须写 L3
- 高风险任务必须有 `risk_evidence`

### 验收标准

- `memory_eval_write_quality` 从硬编码切换为规则驱动
- 规则文件修改后无需改核心代码即可生效
- 规则命中结果可解释

---

## 第 5 批：日常工作面板

### 目标

让系统不只是命令行工具，而是每天都能直接看、直接用。

### 核心组件

- `workspace_dashboard`
- `workspace_focus_board`
- `workspace_low_quality_tasks`
- `workspace_recent_handoffs`
- `workspace_recent_receipts`

### 建议 dashboard 内容

- 当前活跃任务
- 当前最需要接续的任务
- 最近写入回执
- 质量最低的任务
- 未完成验证项
- 最近 handoff
- 最近高风险任务
- L3 核心规则块摘要

### 验收标准

- 命令行可输出结构化 dashboard
- HTTP 可提供 dashboard JSON
- 后续可无痛扩成 Web UI

---

## 第 6 批：评测与持续优化

### 目标

证明 Memory Center 真的解决了日常工作问题。

### 核心组件

- `memory_eval_write_quality`
- `memory_eval_resume`
- `memory_eval_handoff`
- `memory_eval_task_continuity`
- `memory_eval_regression_suite`

### 建议指标

- `write_coverage_score`
- `resume_success_rate`
- `handoff_success_rate`
- `duplicate_explanation_reduction`
- `missing_context_incidents`
- `verification_completion_rate`

### 验收标准

- 至少有一套固定 demo workspace 回归评测
- 每次核心能力改动后可跑评测
- 能比较不同模型 / 不同规则配置的效果

---

## 四、优先级建议

按你的日常收益排序：

1. 第 1 批收尾
2. 第 2 批任务连续性
3. 第 3 批跨模型交接
4. 第 4 批规则化治理
5. 第 5 批工作面板
6. 第 6 批评测优化

---

## 五、建议的近期执行顺序

下面是最值得立即推进的 10 个功能。

### P0

1. `workspace_resume_packet`
2. `workspace_next_actions`
3. `workspace_unresolved_items`
4. `workspace_handoff_packet`

### P1

5. `memory_eval_write_quality` 规则配置化
6. `workspace_model_profile`
7. `workspace_handoff_history`

### P2

8. `workspace_dashboard`
9. `memory_eval_resume`
10. `memory_eval_handoff`

---

## 六、每批交付方式

每一批建议都按相同方式交付：

1. 核心 `orchestrator` 能力
2. CLI 命令
3. MCP tool
4. HTTP route
5. 文档更新
6. 测试补齐
7. 示例 workspace 验证

---

## 七、你日常使用的理想链路

最终理想链路如下：

1. `workspace_sniff`
2. `memory_write_judge`
3. `memory_plan_write`
4. `memory_execute_write`
5. `workspace_start_session / log`
6. `workspace_sync_case_to_artifacts`
7. `workspace_record_case`
8. `workspace_replay_write_chain`
9. `memory_eval_write_quality`
10. 切模型时 `workspace_handoff_packet`
11. 第二天继续时 `workspace_resume_packet`

---

## 八、当前建议

当前最合理的下一阶段是：

- 正式进入 **第 2 批：任务连续性**
- 然后立刻进入 **第 3 批：跨模型交接**

因为这两批最直接对应你的真实目标：

> 解决多模型 / 多工具 / 多会话 / 上下文切割问题，最大程度放大 AI 的实际工作能力。
