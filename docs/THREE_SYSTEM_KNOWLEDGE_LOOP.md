# 三系统知识协同闭环 / Three-System Knowledge Coordination Loop

> 文档类型：架构与操作决策（current）  
> 适用范围：Memory Center、外部长期知识库、可选宿主插件。  
> **命名约定 / Naming**：下文「知识库」指外部的个人长期知识库产品，「宿主插件」指宿主侧的日常交互集成。**两者都不属于本仓库的发布物**；本文只定义 Memory Center 与它们之间的职责边界、数据流与门禁。  
> 本文定义职责边界与数据流；代码、接口字段与命令参数以 `README.md`、`REFERENCE.md`、`MCP_GUIDE.md` 和 `--help` 为准。

## 1. 目标 / Goal

将日常编程工作、当前项目证据与长期个人知识组织成一个可追溯、可控写入的闭环。

系统不追求把所有聊天内容集中到一个库中，而是让每类信息保留在最合适的位置：当前项目事实由 Memory Center 管理，长期稳定知识由知识库管理，宿主作为日常交互和可视化入口。

The goal is not to centralize every chat transcript. Each system retains the data it can govern best: Memory Center owns current project evidence, the external knowledge base owns stable long-term knowledge, and the host is the daily interaction and visualization surface.

## 2. 三个系统的职责 / System Ownership

| 系统 | 唯一职责 | 保存内容 | 明确不做 |
|---|---|---|---|
| 外部长期知识库（非本仓库发布物） | 长期、人工确认、跨项目可复用的知识 | 规则、方法论、长期决策、稳定经验 | 当前源码副本、临时会话、完整工具输出 |
| Memory Center | 当前项目的工程事实与交付闭环 | 索引图谱、任务、影响分析、证据、Case、交付摘要、资产链接 | 整库复制知识库正文、替代知识库作为事实源 |
| 宿主插件（可选，非本仓库发布物） | 日常工作入口与受限采集/展示 | 本地 UI 状态、脱敏执行事件 | 第二套项目后端、自动认定长期知识 |

因此，同一问题的来源优先级为：**当前源码与 Memory Center 工程证据 > 已关联的长期知识 > 未验证推断**。长期知识与当前工程事实冲突时，必须以当前工程证据为准，并标记知识条目可能过期。

## 3. 总体架构 / Overall Architecture

```text
                   ┌────────────────────────────┐
                   │ 外部长期知识库               │
                   │ 长期知识正文 / 两阶段晋升     │
                   └─────────────┬──────────────┘
                                 │ pawiki 反向链接、哈希、范围
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Memory Center                                                    │
│ 项目图谱 / 任务 / 影响 / 证据 / Case / 交付摘要 / 协作资产        │
└─────────────▲───────────────────────────────────┬──────────────┘
              │ 脱敏执行事件、交付摘要              │ 只读工作台数据、任务感知知识
              │                                     ▼
              │                      ┌───────────────────────────┐
              └──────────────────────┤ 宿主插件（可选）           │
                                     │ 工作台 / 任务 / 分析 / 知识 │
                                     │ 运行观测                   │
                                     └───────────────────────────┘
```

## 4. 四条正式数据链路 / Four Formal Flows

### 4.1 知识库 → Memory Center：受治理资产链接

`wiki-assets-sync` 将明确选定的长期知识入口登记为 `kind=wiki` 的私有协作资产。

持久化字段仅包括：

- `source_ref=pawiki:<relative-path>`；
- `knowledge_id`；
- `content_sha256`；
- `scope`、标签与来源任务/证据引用；
- 有界、非正文的资产说明。

知识库正文不复制到 Memory Center。同步默认只登记明确入口，而非扫描或导入整个知识库。

宿主插件首次绑定一个配置了 `wiki_bridge` 的 workspace 时，可自动执行一次同步；同一进程按 workspace 去重。

### 4.2 Memory Center → 宿主：项目工作台

宿主插件不直接读取 SQLite、JSONL 或知识库文件。浏览器仅访问宿主同源 bridge，bridge 再调用本地 Memory Center 的受限读模型。

| 宿主页面 | Memory Center 读模型 | 回答的问题 |
|---|---|---|
| 工作台 | `workbench-summary` | 当前做什么、下一步、有哪些阻塞 |
| 任务 | continuity/resume 读模型 | 中断后如何继续、缺什么证据 |
| 影响 | impact + evidence subgraph | 会影响什么、直接静态证据是什么 |
| 知识 | knowledge summary + 知识摘要 | 哪些项目记忆与长期知识和当前任务相关 |
| 执行观测 | 本地 execution summary | 当前会话的模型、工具、耗时与失败 |

首页使用轻量 `workbench-summary`，避免执行完整 dashboard 的质量评测和恢复聚合。重型查询只在用户切换到对应标签后才执行。

### 4.3 宿主 → Memory Center：执行与交付摘要

宿主插件有两类采集：

1. **执行观测**：仅记录 session/turn/step、模型/工具名、耗时、Token、状态与错误类别；不记录 prompt、消息正文、工具参数、工具结果或 cwd。
2. **交付摘要捕获**：assistant 最终消息含“修改完成”“实现完成”“已确认”“验证通过”“测试通过”等完成信号时，提取最多 1400 字符摘要。代码块会被省略，普通消息与中断消息不会捕获。

交付摘要写入独立、已关闭的 L0 会话并生成回执，因而可在“知识/近期交付与会话”中出现。它不会自动生成或发布 L1 Case。

### 4.4 Memory Center → 知识库：两阶段长期晋升

交付摘要不等于长期知识。只有完成以下两步，才会写入外部知识库：

```text
宿主交付摘要
  → Memory Center 生成晋升预览（不写）
  → 用户明确确认
  → 知识库 promote(confirm=true)
  → Memory Center 登记新 pawiki 反向资产
```

`wiki-promotion-preview` 只读取已捕获的交付摘要，生成 title/content/module/source refs 的候选。`wiki-promotion-confirm` 才调用知识库的受控写入，并将成功产物立即登记为新的 Wiki 资产。

此流程禁止宿主插件自动将任意完成消息写成长期知识。

## 5. 任务感知知识检索 / Task-Aware Knowledge Retrieval

知识页由两层组成：

1. **已关联的长期知识资产**：按 workspace scope 过滤，保证只展示该项目允许关联的长期知识入口。
2. **按需摘要 brief**：将当前焦点任务标题与标签作为查询，调用知识库 bridge 的 `brief`。返回值在宿主中进一步收缩为标题、相对路径、分组和关联原因，不返回正文或检索 snippet。

空结果是正确状态：说明知识库当前没有与该任务直接匹配的长期条目。界面仍保留 scope 内已关联资产，但不能伪造“任务命中”。

工程 scope 使用登记时配置的名称（示例：`example-scope`）；知识库查询 scope 可使用组织级范围名称。映射由用户级绑定配置维护。

## 6. 用户级知识绑定 / User-Level Knowledge Binding

宿主插件从用户级 workspace 配置读取默认 workspace 与知识库 bridge。示例：

```json
{
  "schema_version": 1,
  "default_workspace_id": "my-workspace",
  "workspaces": [
    {
      "id": "my-workspace",
      "label": "My Workspace",
      "workspace_file": "/absolute/path/to/.memory-center/workspace.yaml"
    }
  ],
  "wiki_bridge": {
    "auto_sync": true,
    "wiki_root": "/absolute/path/to/knowledge-base",
    "owner": "your-owner-id",
    "scope": "example-scope",
    "wiki_scope": "organization-scope-name"
  }
}
```

优先级：显式插件 `workspaceFile` > 用户级默认 workspace > 宿主 session cwd 自动发现。`wiki_bridge` 不写入插件源码，也不应出现在公开示例中的真实路径。

## 7. 日常操作路径 / Daily Operating Path

### 日常开发

1. 启动宿主，插件绑定 workspace 并同步受限知识资产链接。
2. 在“工作台”确认当前任务和下一步。
3. 在“知识”查看项目记忆、已关联长期知识与按需 brief 结果。
4. 改动前在“影响”查看图谱证据与影响分层。
5. 宿主完成信号自动形成交付摘要；必要时在“知识”查看该记录。

### 晋升长期知识

```sh
# 仅预览
memory-center wiki-promotion-preview \
  --workspace /path/to/.memory-center/workspace.yaml \
  --session-id <host-delivery-session-id> \
  --wiki-root /path/to/knowledge-base

# 人工审核后才确认
memory-center wiki-promotion-confirm \
  --workspace /path/to/.memory-center/workspace.yaml \
  --session-id <host-delivery-session-id> \
  --wiki-root /path/to/knowledge-base \
  --owner <owner-id>
```

## 8. 隐私、性能与失败边界 / Privacy, Performance, and Failure Boundaries

### 隐私

- 不把完整对话 transcript 写入 Memory Center；
- 不把知识库正文复制到 Memory Center 或宿主工作台；
- 不在公开文档写入真实路径、私有源码、密钥或工具载荷；
- 写入知识库必须经过预览与显式确认。

### 性能

- 首页使用轻量工作台投影与短 TTL 缓存；
- 知识库只在“知识”标签按需 brief，不在宿主启动时全文检索；
- 资产同步仅处理显式入口，同进程对同一 workspace 去重；
- 图谱查询使用有界节点、边与深度，避免全图渲染。

### 失败降级

| 失败 | 行为 |
|---|---|
| 知识库 bridge 未安装或不可用 | 宿主仍显示已关联资产；按需 brief 显示可行动错误 |
| 无直接知识命中 | 显示空结果，不伪造相关性 |
| Memory Center bridge 不可用 | 宿主原对话继续；工作台显示 bridge 状态 |
| 知识晋升失败 | 不影响项目任务、执行观测或既有知识条目；返回结构化错误 |
| 宿主未启动 | Memory Center 与知识库均可独立使用 |

## 9. 验收标准 / Acceptance Criteria

该闭环可认为可用，至少满足：

1. 宿主知识页能区分“项目记忆”“已关联长期知识”“按需知识命中”；
2. 每条知识资产可追溯到 `pawiki:` 来源、哈希和范围；
3. 完成信号能生成受限交付摘要，但普通对话不会写入长期知识；
4. 晋升预览不写知识库，确认后才写入，并自动登记反向资产；
5. 当前源码/Memory Center 证据与长期知识冲突时，界面和 Agent 协议明确以当前工程证据为准；
6. 任一系统不可用时，另外两个系统仍能独立工作。
