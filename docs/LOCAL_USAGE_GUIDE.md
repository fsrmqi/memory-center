# Local Usage Guide / 本地使用指南

本文档面向本地长期使用 `Memory Center` 的开发者，重点回答：

- 怎么初始化一个项目？
- 多项目怎么组织？
- 历史记忆怎么沉淀、怎么复用？
- 本地语义检索和可选 embedding backend 怎么启用？

This guide is for long-term local use of `Memory Center`. It covers initialization, multi-project organization, historical memory, and local semantic retrieval.

---

## 1. Core Concepts / 核心概念

先区分两个层级：

### `workspace`

`workspace` 是一个代码根目录下的“项目记忆空间”。它通常对应一套业务系统或一个多服务仓库根目录。

典型内容：

- 一个 `root`
- 多个 `services`
- 一套 `.memory-center/` 本地索引、图谱、历史记忆、规则

你可以把它理解成：

`一个业务上下文 = 一个 workspace`

### `registry + group`

`registry` 是你机器上的全局工作区注册表，默认在：

```text
~/.memory-center/registry.json
```

它解决的是“我本地有多个 workspace，怎么统一管理”。

`group` 是在 registry 之上的逻辑分组，用来做：

- 多 workspace 聚合查询
- 跨 workspace 影响分析
- 组织级别的 bridge 观察

你可以把它理解成：

- `workspace`：单套系统记忆
- `registry`：本机所有 workspace 清单
- `group`：跨 workspace 组合视图

---

## 2. Installation / 安装

### 基础安装

```bash
git clone <your-repo>
cd memory-center
pip install -e .
```

如果你需要 MCP：

```bash
pip install -e .[mcp]
```

如果你需要 AST 解析实验能力：

```bash
pip install -e .[ast]
```

如果你需要本地 embedding backend：

```bash
pip install -e .[semantic-local]
```

---

## 3. Initialize One Workspace / 初始化一个工作区

假设你的代码根目录是：

```text
/path/to/backend-platform
```

执行：

```bash
memory-center init \
  --workspace-root /path/to/backend-platform \
  --name backend-platform
```

执行后会生成：

```text
/path/to/backend-platform/.memory-center/
  workspace.yaml
  rules/
  instructions/
  memory/
  index/
  graph/
```

### 初始化后要做的第一件事

打开：

[`workspace.yaml`](../examples/spring-cloud-demo/.memory-center/workspace.yaml)

把 `services` 改成你的真实服务列表，例如：

```yaml
workspace: backend-platform
root: /path/to/backend-platform
language:
  - zh-CN
  - en-US
services:
  - name: gateway
    path: gateway
    type: spring-cloud-gateway
    service_name: gateway
  - name: user-service
    path: user-service
    type: spring-boot-service
    service_name: user-service
  - name: order-service
    path: order-service
    type: spring-boot-service
    service_name: order-service
  - name: common-api
    path: common-api
    type: shared-library
    tags: [contract]
```

### 然后重建索引

```bash
memory-center reindex \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml
```

建议紧接着做健康检查：

```bash
memory-center doctor \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml \
  --self-test
```

查看状态：

```bash
memory-center status \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml
```

---

## 4. Workspace Directory Layout / 工作区目录结构

一个 workspace 的本地状态主要都在 `.memory-center/` 下：

```text
.memory-center/
  workspace.yaml
  index/
    file-index.json
    java-symbol-index.json
    api-index.json
    feign-index.json
    mq-index.json
    config-index.json
    service-topology.json
    semantic-node-index.json
  graph/
    graph.db
  memory/
    cross-service-task-memory.jsonl
  rules/
    default-rules.yaml
  instructions/
```

含义如下：

- `index/`：离线结构化索引
- `graph/graph.db`：图谱数据库
- `memory/cross-service-task-memory.jsonl`：历史任务记忆
- `rules/`：规则库
- `semantic-node-index.json`：本地语义索引

---

## 5. Daily Single-Workspace Workflow / 单工作区日常工作流

### 5.1 理解任务上下文

```bash
memory-center sniff \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml \
  --intent "修改用户迁移逻辑，需要看 DTO、Feign、Kafka"
```

### 5.2 查符号 / 接口 / Topic

```bash
memory-center query \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml \
  --text "UserFeignClient MoveUserRequest user-migrate-topic"
```

返回里重点关注：

- `matches`
- `semantic_hits`
- `retrieval_summary`
- `retrieval_sources`

### 5.3 看节点上下文

```bash
memory-center context \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml \
  --name UserFeignClient
```

重点字段：

- `lookup`
- `incoming`
- `outgoing`
- `evidence_summary`

### 5.4 做影响分析

```bash
memory-center impact \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml \
  --target MoveUserRequest \
  --direction upstream
```

重点字段：

- `confirmed_impacts`
- `probable_impacts`
- `possible_impacts`
- `lookup`
- `evidence_summary`
- `required_rules`

### 5.5 看当前本地改动的影响

```bash
memory-center detect-changes \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml \
  --scope staged
```

---

## 6. Historical Memory / 历史记忆怎么用

历史记忆默认保存在：

```text
.memory-center/memory/cross-service-task-memory.jsonl
```

每一条记录本质上是一个“做过且验证过的任务经验”。

### 6.1 用 CLI 写入历史记忆

现在可以直接本地写入：

```bash
memory-center record-case \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml \
  --task "修复用户迁移时 DTO 字段兼容问题" \
  --project user-service \
  --project common-api \
  --file common-api/src/main/java/com/example/api/MoveUserRequest.java \
  --file user-service/src/main/java/com/example/user/UserMoveService.java \
  --flow "query -> context -> impact -> change -> verify" \
  --risk-point "Feign 请求字段兼容" \
  --risk-point "历史消息反序列化兼容" \
  --verified-by integration-test \
  --verified-by replay
```

### 6.2 历史记忆会在哪里发挥作用

它会进入：

- `sniff`
- `query`
- MCP tool 的 `historical_cases`
- `generate-skills`
- `generate-wiki`

也就是说，后续相似任务进来时，Agent 会把这些经验当成上下文的一部分。

### 6.3 推荐什么情况下记录历史记忆

建议只记录“已经验证过”的任务，例如：

- 改过公共 DTO，并确认兼容
- 修过 Feign 契约不一致
- 处理过 MQ topic / group / 重试 / 幂等等风险
- 一次跨服务重构已经联调通过

不建议记录：

- 纯猜测
- 没验证的临时方案
- 一次性的无复用价值操作

---

## 7. Multi-Project Usage / 多项目怎么使用

这里有两种常见模式。

### 模式 A：一个大根目录，里面有多个服务

这种情况下：

- 建一个 workspace
- 在 `workspace.yaml` 里列出所有服务

适合：

- monorepo
- 一套系统的多模块目录
- 一个大仓库里有多个 Spring Boot 服务

### 模式 B：多个独立根目录，每个根目录一个 workspace

这种情况下：

1. 每个项目各自 `init`
2. 每个项目各自 `reindex`
3. 把每个 workspace 注册到全局 registry
4. 再把它们组织进 group

这更适合：

- 多个独立 Git 仓库
- 多套业务系统
- 组织级别跨仓库影响分析

---

## 8. Register Multiple Workspaces / 注册多个工作区

假设你本地有三个独立项目：

- `/work/content-platform`
- `/work/risk-platform`
- `/work/task-platform`

每个项目都先执行一次：

```bash
memory-center init --workspace-root /work/content-platform --name content-platform
memory-center init --workspace-root /work/risk-platform --name risk-platform
memory-center init --workspace-root /work/task-platform --name task-platform
```

各自配置好 `workspace.yaml` 并 `reindex` 之后，注册到全局 registry：

```bash
memory-center registry add \
  --name content-platform \
  --workspace /work/content-platform/.memory-center/workspace.yaml

memory-center registry add \
  --name risk-platform \
  --workspace /work/risk-platform/.memory-center/workspace.yaml

memory-center registry add \
  --name task-platform \
  --workspace /work/task-platform/.memory-center/workspace.yaml
```

查看已注册工作区：

```bash
memory-center registry list
```

注册表默认写入：

```text
~/.memory-center/registry.json
```

---

## 9. Create Groups / 创建逻辑分组

例如创建一个组织级分组：

```bash
memory-center group create --name backend-platform
memory-center group add --name backend-platform --repo content-platform
memory-center group add --name backend-platform --repo risk-platform
memory-center group add --name backend-platform --repo task-platform
```

查看 group 状态：

```bash
memory-center group status --name backend-platform
```

可以看到：

- `index_totals`
- `semantic_index`
- `bridge_counts`
- `workspaces`

其中 `semantic_index.backends` 会告诉你当前分组里各 workspace 用的是哪种语义 backend。

---

## 10. Cross-Workspace Query / 跨工作区查询

### 聚合查询

```bash
memory-center group query \
  --name backend-platform \
  --text "ArticleFeignClient article-pubtime-change"
```

重点字段：

- `merged_matches`
- `retrieval_summary`
- `target_types`
- `related_bridges`
- `workspace_results`

### 跨工作区影响分析

```bash
memory-center group impact \
  --name backend-platform \
  --target ArticleFeignClient
```

重点字段：

- `confirmed_impacts`
- `probable_impacts`
- `possible_impacts`
- `related_bridges`
- `lookup`
- `evidence_summary`
- `impacted_workspaces`

这一步最适合用来回答：

- 改这个 Feign，会影响哪些仓库？
- 这个 MQ topic 改了，哪些 workspace 会受影响？
- 某个配置键是不是多个系统共用？

---

## 11. Historical Memory in Multi-Project Mode / 多项目模式下的历史记忆

这一点很重要：

### 11.1 历史记忆默认还是“按 workspace 存”

也就是说，每个 workspace 都有自己的：

```text
.memory-center/memory/cross-service-task-memory.jsonl
```

这意味着：

- `content-platform` 的历史记忆默认在它自己的 workspace 下
- `risk-platform` 也是
- `task-platform` 也是

### 11.2 group 不会把所有历史记忆合并成一个全局文件

group 的作用是：

- 聚合查询
- 聚合影响分析
- bridge 观察

不是把所有 workspace 的记忆写进一个统一 JSONL。

### 11.3 那多项目历史记忆怎么复用？

当前推荐做法：

1. 每个 workspace 记录自己的高质量 case
2. 用 `group query` / `group impact` 做跨 workspace 检索
3. 用 `generate-skills` / `generate-wiki` 把高价值经验转成结构化产物

也就是说：

- 原始记忆按 workspace 管
- 检索和分析按 group 聚合

这是当前实现最稳的方式。

---

## 12. Enable Local Embedding Backend / 启用本地 Embedding Backend

默认使用零依赖稀疏后端：

- 无需额外模型
- 本地可直接跑
- 可解释性强

如果你想启用本地 embedding backend：

```bash
pip install -e .[semantic-local]
export MEMORY_CENTER_SEMANTIC_BACKEND=sentence-transformers
export MEMORY_CENTER_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

然后重新构建索引：

```bash
memory-center reindex \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml
```

再看状态：

```bash
memory-center status \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml
```

你会在 `semantic_index` 里看到类似：

```json
{
  "backend": "sentence-transformers",
  "requested_backend": "sentence-transformers",
  "model": "sentence-transformers/all-MiniLM-L6-v2"
}
```

如果依赖没装好或模型加载失败，系统会自动退回 `sparse`。

---

## 13. HTTP Bridge / 本地 HTTP Bridge

如果你想让本地脚本、IDE 插件、其他 Agent 通过 HTTP 调用：

```bash
memory-center serve-http \
  --workspace /path/to/backend-platform/.memory-center/workspace.yaml \
  --host 127.0.0.1 \
  --port 8765
```

常用接口：

- `GET /health`
- `GET /workspace/status?workspace=/path/to/.memory-center/workspace.yaml`
- `GET /workspace/query?text=ArticleFeignClient`
- `GET /group/status?group=backend-platform`
- `GET /group/query?group=backend-platform&text=ArticleFeignClient`
- `GET /group/impact?group=backend-platform&target=ArticleFeignClient`

---

## 14. Recommended Long-Term Workflow / 推荐长期使用方式

如果你是自己本地长期维护多个项目，建议按下面的节奏：

### 第一次接入

1. 每个项目执行 `init`
2. 补真实 `workspace.yaml`
3. 执行 `reindex`
4. 执行 `doctor --self-test`
5. 注册到 `registry`
6. 建立 `group`

### 日常开发

1. 改代码前先 `sniff`
2. 查符号先 `query`
3. 动公共契约前先 `context` / `impact`
4. 提交前看一次 `detect-changes`
5. 验证通过后 `record-case`

### 定期维护

1. 项目结构有明显变化后执行 `reindex`
2. 增加新服务后更新 `workspace.yaml`
3. 新增新仓库后执行 `registry add`
4. 组织关系变化后更新 `group add`
5. 定期把高价值记忆转成 `generate-skills` / `generate-wiki`

---

## 15. Common Questions / 常见问题

### Q1：一个 Git 仓库必须对应一个 workspace 吗？

不一定。

- 如果一个根目录里本来就有多个服务，通常一个 workspace 就够
- 如果是多个独立根目录，建议每个根目录一个 workspace

### Q2：历史记忆是全局共享的吗？

不是默认全局共享。

默认是：

- 每个 workspace 一份历史记忆
- group 负责跨 workspace 聚合查询和影响分析

### Q3：我新增了一个服务，怎么接入？

1. 编辑对应 workspace 的 `workspace.yaml`
2. 把新服务加到 `services`
3. 重新执行 `reindex`

### Q4：我新增了一个全新的项目根目录，怎么接入？

1. 对新根目录执行 `init`
2. 配好 `workspace.yaml`
3. 执行 `reindex`
4. 执行 `registry add`
5. 如有需要，执行 `group add`

### Q5：什么时候需要重新 `reindex`？

建议在这些场景重建：

- 新增服务/模块
- 大量文件移动
- 公共契约变化
- 想切换语义 backend
- 图谱结果明显过旧

---

## 16. Minimal Command Cheat Sheet / 最小命令速查

```bash
# 1. 初始化
memory-center init --workspace-root /path/to/project --name project-name

# 2. 重建索引
memory-center reindex --workspace /path/to/project/.memory-center/workspace.yaml

# 3. 健康检查
memory-center doctor --workspace /path/to/project/.memory-center/workspace.yaml --self-test

# 4. 查询
memory-center query --workspace /path/to/project/.memory-center/workspace.yaml --text "UserFeignClient"

# 5. 影响分析
memory-center impact --workspace /path/to/project/.memory-center/workspace.yaml --target MoveUserRequest

# 6. 记录历史记忆
memory-center record-case \
  --workspace /path/to/project/.memory-center/workspace.yaml \
  --task "修复 DTO 兼容问题" \
  --project user-service \
  --file user-service/src/main/java/com/example/user/UserService.java

# 7. 注册工作区
memory-center registry add --name project-name --workspace /path/to/project/.memory-center/workspace.yaml

# 8. 建 group
memory-center group create --name backend-platform
memory-center group add --name backend-platform --repo project-name

# 9. group 查询
memory-center group query --name backend-platform --text "UserFeignClient"
memory-center group impact --name backend-platform --target UserFeignClient
```

---

## 17. Recommended Reading / 进一步阅读

- [README.md](../README.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [MCP_TOOLS.md](./MCP_TOOLS.md)
- [WORKSPACE_SPEC.md](./WORKSPACE_SPEC.md)
