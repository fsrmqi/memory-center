# KnowledgeLink Integration Plan / 长期知识关联集成计划

2026-09-08 回归加固：关闭未绑定 session 必须在任何 L2 同步之前返回 Shadow；绑定读取不依赖事件展示窗口。Wiki bridge 的原始 score 为 FTS5 BM25，越负越相关，候选层转换为 `-score` 后应用正阈值；当前文件与登记 hash 不一致或文件缺失时排除。手工附着校验任务存在和资产 owner。DSH 知识页使用 MC 候选接口，POST 附着固定到会话写 workspace，等待命令结果后才显示成功。

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
2. Memory Center 先按 workspace/task/项目标签过滤，再调用 Wiki 的受限 brief/search。传输机制固定为 `personal-assistant-wiki-bridge brief` 子进程（与 promote 同一 CLI）；传输层必须可注入，bridge 不可用时诚实返回空列表，不伪造候选。
3. 返回最多 3 条 `{knowledge_id,title,summary,relevance_reason,content_sha256,freshness}`，无直接证据时返回空列表。
4. DSH 只展示摘要、关联原因和新鲜度；正文仍由 Wiki 在用户显式打开时读取。
5. `link_status=stale|revoked` 的已登记链接一律不进入候选，无论分数高低。

任何低于阈值、缺少关联理由或 scope 不匹配的 Wiki 条目不得进入 Agent 上下文。

## Write path / 写入链路

1. DSH 的完成信号仅生成 delivery candidate，附带 Memory Center 的 task/receipt/evidence 引用；`evidence_refs` 为空的 candidate 不得生成（session 引用可作底线，task/receipt 引用可用时必须附带）。
2. Memory Center 验证 TaskBindingDecision、验证回执和隐私边界后生成 promotion preview。
3. 用户在 DSH 工作台明确确认；Personal Wiki 创建或更新长期条目。
4. Wiki 返回 `knowledge_id` 与 `content_sha256`；Memory Center 创建 KnowledgeLink，不复制正文。
5. 后续 Wiki 哈希变化时，Memory Center 将链接标记为 `stale`，不自动覆盖、不自动重新晋升。

## Delivery phases / 分阶段交付

涉及仓库：Phase 1/2/4 为 memory-center（`core/knowledge/` + CLI 命令族）；Phase 3 为 memory-center-dsh-plugin（Node 动作模块）与 dsh 工作台 UI 接线（UI 层为后续跟进，本计划验收以插件行为为准）。

### Phase 1 — KnowledgeLink contract on existing wiki assets

- 在现有 `kind=wiki` 协作资产上校验并标准化 KnowledgeLink metadata，不新增第二份 registry。
- 提供注册、列举、按 workspace/task 查询与 stale 标记；所有写入需显式调用。
- `content_sha256` 统一为 raw 字节全量哈希口径；delivery candidate 必须携带非空 `evidence_refs`，preview 无任何可溯引用时 `ready=False`。
- 验收：无正文落盘；相同 `(knowledge_id, content_sha256)` 幂等；无 task 绑定不自动创建链接；`evidence_refs` 为空的注册被拒绝。

### Phase 2 — Anchored Wiki candidates

- 新建受限 Wiki candidate facade，输入必须含 workspace 或已确认 task。
- 只返回摘要与关联理由；默认上限 3，阈值不足返回空。
- 验收：无 scope 时拒绝宽泛检索；0 分或无理由条目不返回；stale/revoked 链接不返回。

### Phase 3 — DSH interaction

- 工作台增加"附着到任务""晋升预览""确认晋升"三段式动作。
- 自动 `wiki-assets-sync` 仅刷新反向链接与 hash，不触发晋升。
- 验收：DSH 不直接写 Wiki；confirm 前无持久化副作用。

### Phase 4 — Drift and observability

- 检测 hash 漂移、scope 失配和缺失 evidence；输出只读 repair action。漂移检测依赖可复得的 `wiki_root`：注册链接时须在 workspace 配置或链接 metadata 中记录 root 路径（仅路径，不落正文），否则检测只能报告 `wiki_root_unknown`。
- 记录候选曝光、人工附着、确认晋升与 stale 率等聚合指标。
- `link_status=revoked` 仅由人工显式命令或"Wiki 条目已删除"的人工确认产生，系统不做自动 revoke。
- 验收：不自动修复或删除；每个状态变化可回溯来源（状态历史记录 from/to/时间/原因/执行者）。

## Stable identifiers / 稳定标识

跨系统只传递 `workspace_id`、`task_id`、`session_id`、`knowledge_id`、`content_sha256`、`evidence_refs` 与 `binding_mode`。其中 `task_id` 仅能来自显式选择或已记录的 `TaskBindingDecision`。

- `content_sha256` 口径固定为 **Wiki 文件 raw 字节的全量 SHA-256（64 位 hex）**；现有 `ingest_wiki_document_asset` 的 20 位截断文本哈希迁移到同一口径，禁止两种定义并存。
- `knowledge_id` 派生自 Wiki 相对路径（`pawiki-<sha256(path)[:16]>`）：条目重命名或移动会产生新 id 并使旧链接成为孤儿，由漂移检测报告 `wiki_entry_missing`，是否 revoke 由人工决定，系统不做自动迁移。
- 本计划所称 `TaskBindingDecision` 对应当前代码中的 task binding 决策记录（`task_binding.mode`，含 `shadow_only`）；若 Phase 1 需要独立持久化的决策对象，必须显式命名并落盘，不得沿用会话内临时字段。

## Safety gates / 安全门禁

- Wiki 搜索无锚点时不得作为 Agent 上下文。
- 无 `evidence_refs` 的 delivery candidate 不得晋升。
- `binding_mode=shadow_only` 的会话不得创建 task-scoped KnowledgeLink。
- 任一外部 Wiki 写入失败时停止，不补偿式猜测或写入替代内容。
- 插件和 Memory Center 仅保存引用、摘要、哈希与审计字段；不保存 Wiki 正文、prompt 或工具载荷。

## 修订记录

- 2026-09-07 第三次修订（四阶段实现落地）：
  - 实现状态：Phase 1–4 已实现于 memory-center `core/knowledge/`（`wiki_bridge.py`、`candidates.py`、`wiki_drift.py`、`knowledge_events.py`、`wiki_promotion.py`）与 CLI 命令族（`knowledge-links`、`knowledge-candidates`、`knowledge-link-attach`、`knowledge-link-mark`、`knowledge-link-drift`、`knowledge-link-metrics`）；Phase 3 宿主侧动作实现于 memory-center-dsh-plugin `wikilink.js`（工作台 UI 接线为后续 UI 层跟进）。
  - 域测试锚定：`tests/domain/test_knowledge_links.py` 覆盖全部安全门禁（证据门禁、shadow_only 限定、幂等、hash 口径、fail-closed 候选、stale 排除、只读修复建议、状态历史溯源）。
- 2026-09-07 第二次修订（源码核对评审后并入 9 项待补事项）：
  - 稳定标识：钉死 `content_sha256` 口径（raw 字节全量 SHA-256）、`knowledge_id` 的路径派生与重命名语义、`TaskBindingDecision` 与代码现状（`task_binding.mode`）的命名对应。
  - 读取链路：传输机制固定为 bridge `brief` 子进程且可注入；stale/revoked 链接一律不进候选。
  - Write path / Phase 1：delivery candidate 必须携带非空 `evidence_refs`，无证据注册被拒。
  - Phase 3：标注涉及仓库与 UI 接线边界。
  - Phase 4：漂移检测的 `wiki_root` 持久化要求；`revoked` 的唯一生产者是人工显式操作；状态变化必须留状态历史。
