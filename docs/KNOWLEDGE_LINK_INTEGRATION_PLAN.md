# KnowledgeLink Integration Plan / 长期知识关联集成计划

## Goal / 目标

建立 DSH 插件、Memory Center 与 Personal Wiki 的受控知识闭环。代码事实、任务状态和验证回执仍由 Memory Center 权威保存；Personal Wiki 仍是人类维护的长期知识源；DSH 插件只负责脱敏感知与人工交互。

不复制 Wiki 正文到 Memory Center，不让 DSH 自动写 Wiki，不把模型完成信号当作长期知识成立的证据。

## Authority / 权威边界

| 系统 | 可写对象 | 禁止写入 |
| --- | --- | --- |
| DSH plugin | 脱敏事件、Task Shadow 快照、用户确认请求 | L2 task、Wiki 正文、长期结论 |
| Memory Center | 工程图、session、receipt、TaskBindingDecision、KnowledgeLink | Wiki 正文、未验证个人知识 |
| Personal Wiki | 人工确认的长期条目与其 `knowledge_id` | 原始会话、工具载荷、源码正文 |

`KnowledgeLink` 不新建平行 registry，而是复用现有协作资产中的 `kind=wiki`。其 metadata 最小字段为 `knowledge_id`、`content_sha256`、`workspace_id`、可选 `task_id`、`relation_reason`、`evidence_refs` 与 `link_status=active|stale|revoked`；`source_ref` 固定为 `pawiki:<path>`。

## Read path / 读取链路

1. DSH 绑定 workspace 与 session；插件请求 Memory Center 的有界知识候选。
2. Memory Center 先按 workspace/task/项目标签过滤，再调用 Wiki 的受限 brief/search。
3. 返回最多 3 条 `{knowledge_id,title,summary,relevance_reason,content_sha256,freshness}`，无直接证据时返回空列表。
4. DSH 只展示摘要、关联原因和新鲜度；正文仍由 Wiki 在用户显式打开时读取。

任何低于阈值、缺少关联理由或 scope 不匹配的 Wiki 条目不得进入 Agent 上下文。

## Write path / 写入链路

1. DSH 的完成信号仅生成 delivery candidate，附带 Memory Center 的 task/receipt/evidence 引用。
2. Memory Center 验证 TaskBindingDecision、验证回执和隐私边界后生成 promotion preview。
3. 用户在 DSH 工作台明确确认；Personal Wiki 创建或更新长期条目。
4. Wiki 返回 `knowledge_id` 与 `content_sha256`；Memory Center 创建 KnowledgeLink，不复制正文。
5. 后续 Wiki 哈希变化时，Memory Center 将链接标记为 `stale`，不自动覆盖、不自动重新晋升。

## Delivery phases / 分阶段交付

### Phase 1 — KnowledgeLink contract on existing wiki assets

- 在现有 `kind=wiki` 协作资产上校验并标准化 KnowledgeLink metadata，不新增第二份 registry。
- 提供注册、列举、按 workspace/task 查询与 stale 标记；所有写入需显式调用。
- 验收：无正文落盘；相同 `(knowledge_id, content_sha256)` 幂等；无 task 绑定不自动创建链接。

### Phase 2 — Anchored Wiki candidates

- 新建受限 Wiki candidate facade，输入必须含 workspace 或已确认 task。
- 只返回摘要与关联理由；默认上限 3，阈值不足返回空。
- 验收：无 scope 时拒绝宽泛检索；0 分或无理由条目不返回。

### Phase 3 — DSH interaction

- 工作台增加“附着到任务”“晋升预览”“确认晋升”三段式动作。
- 自动 `wiki-assets-sync` 仅刷新反向链接与 hash，不触发晋升。
- 验收：DSH 不直接写 Wiki；confirm 前无持久化副作用。

### Phase 4 — Drift and observability

- 检测 hash 漂移、scope 失配和缺失 evidence；输出只读 repair action。
- 记录候选曝光、人工附着、确认晋升与 stale 率等聚合指标。
- 验收：不自动修复或删除；每个状态变化可回溯来源。

## Stable identifiers / 稳定标识

跨系统只传递 `workspace_id`、`task_id`、`session_id`、`knowledge_id`、`content_sha256`、`evidence_refs` 与 `binding_mode`。其中 `task_id` 仅能来自显式选择或已记录的 `TaskBindingDecision`。

## Safety gates / 安全门禁

- Wiki 搜索无锚点时不得作为 Agent 上下文。
- 无 `evidence_refs` 的 delivery candidate 不得晋升。
- `binding_mode=shadow_only` 的会话不得创建 task-scoped KnowledgeLink。
- 任一外部 Wiki 写入失败时停止，不补偿式猜测或写入替代内容。
- 插件和 Memory Center 仅保存引用、摘要、哈希与审计字段；不保存 Wiki 正文、prompt 或工具载荷。
