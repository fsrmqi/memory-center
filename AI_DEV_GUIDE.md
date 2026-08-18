# AI Development Guide / AI 开发指南

> 本文档面向 AI 编程助手（Codex、Claude Code、Cursor、Copilot 等），说明如何在本仓库中进行开发。

## 1. 项目概述

Memory Center 是一个面向 AI 编程助手的本地优先项目记忆与代码知识图谱系统。核心能力：

- 将多仓、多服务工程中的代码结构、接口契约、调用关系、配置、消息链路索引到 SQLite 图谱
- 提供混合检索（精确图查询 + BM25 + 可选语义向量）
- 通过 CLI、MCP、HTTP 和 Workbench 暴露任务级接口
- 支持影响分析、任务恢复、交接和证据链

## 2. 代码架构

### 2.1 分层结构

```
memory_center/
├── cli/              # CLI 入口适配层
│   ├── main.py       # 根装配（~220 行）
│   └── commands/     # 16 个命令族模块
├── mcp/              # MCP facade 层
│   └── server.py     # 8 个 facade tool
├── http/             # HTTP 入口层
├── application/      # 应用层（跨领域用例）
├── core/
│   ├── orchestrator/ # 核心任务编排
│   │   ├── query.py  # 公共查询编排
│   │   ├── shared.py # 共享排序/文本原语
│   │   ├── impact.py # 影响分析
│   │   └── ...       # 其他按职责拆分的模块
│   ├── indexing/     # 索引层（Java/Spring 解析）
│   ├── retrieval/    # 检索层（混合检索）
│   ├── storage/      # 存储层（workspace、graph）
│   ├── knowledge/    # 知识图谱
│   ├── domain/       # 领域模型
│   └── ...
└── hooks/            # Hook 生成
```

### 2.2 关键模块

| 模块 | 职责 | 修改时注意 |
|---|---|---|
| `cli/commands/*.py` | 16 个命令族 | 新增命令需更新命令面快照测试 |
| `mcp/server.py` | MCP facade | schema 必须向后兼容 |
| `core/orchestrator/query.py` | 查询编排 | 修改需同步 symbol_ranking/guidance |
| `core/indexing/reindex.py` | 索引重建 | 修改需运行 Golden benchmark |
| `core/retrieval/` | 混合检索 | 修改需验证 retrieval policy |
| `core/storage/workspace.py` | workspace 解析 | 三入口一致性 |

### 2.3 数据流

```
源码 → 解析器(tree-sitter/regex) → 图节点/边 → graph.db
                                         ↓
                              BM25/FTS/向量索引
                                         ↓
用户查询 → 查询规划 → 精确图/BM25/向量 → RRF 融合 → 排序 → 结果
```

## 3. 开发工作流

### 3.1 修改代码前

1. **阅读相关文档**：`docs/ARCHITECTURE.md`、`docs/MCP_GUIDE.md`
2. **理解分层边界**：Adapter 层不做领域决策；Core 层不依赖入口
3. **检查测试隔离**：不要直接写入 `examples/*/.memory-center`，使用 `tmp_path`

### 3.2 修改代码时

```python
# 正确：复制到 tmp_path 后操作
source = Path("examples/spring-cloud-demo")
target = tmp_path / "demo"
shutil.copytree(source, target)
workspace = target / ".memory-center" / "workspace.yaml"

# 错误：直接写入仓库内 demo
workspace = "examples/spring-cloud-demo/.memory-center/workspace.yaml"
```

### 3.3 修改代码后

```bash
# 必须运行
python -m compileall -q memory_center tests
pytest -q

# 涉及索引/检索时额外运行
scripts/verify_real_ucap.sh
```

## 4. 测试要求

### 4.1 必须补充测试的场景

- 修改 Spring Cloud 索引器
- 修改规则匹配逻辑
- 修改 CLI 命令（更新命令面快照）
- 修改 MCP tool schema
- 修改 CLI/MCP/HTTP 入口（三入口一致性）

### 4.2 测试隔离原则

- 所有写入型测试必须使用 `tmp_path`
- 不要直接引用 `examples/spring-cloud-demo/.memory-center` 做写入
- 使用 `tests/fixtures.py` 中的 `copy_demo_workspace()` helper

### 4.3 命令面快照测试

`tests/entrypoints/test_cli_command_surface.py` 锚定完整 CLI 命令面。新增或删除命令时必须更新快照。

## 5. 文档要求

### 5.1 必须同步更新的文档

| 变更类型 | 需更新的文档 |
|---|---|
| 新增/修改 MCP tool | `docs/MCP_GUIDE.md`、`docs/CHANGELOG.md` |
| 新增/修改 CLI 命令 | `docs/REFERENCE.md`、命令面快照测试 |
| 架构变更 | `docs/ARCHITECTURE.md` |
| 用户可感知变化 | `docs/CHANGELOG.md`、`README.md` |

### 5.2 文档精简原则

当前活跃文档 8 份，不要新增独立文档。如有新内容：
- 设计决策 → 加入 `docs/ARCHITECTURE.md` 附录
- 操作指南 → 加入 `docs/USER_GUIDE.md`
- schema 约束 → 加入 `docs/REFERENCE.md`

## 6. 常见设计误解

以下行为容易被误解为 bug，但其实是有意的设计取舍：

### 6.1 `user_prompt_submit` 默认禁用

`hooks.yaml` 中 `user_prompt_submit` 是 `mode: suggest` + `enabled: false`。这不是 bug，而是产品策略——避免普通自然语言输入（"继续"、"下一步"）被 hook 拦截。

### 6.2 facade 与原子能力并存

MCP 默认暴露 8 个 facade tool，CLI/HTTP/core 内部保留很多原子能力。这是刻意分层：模型面对 facade 降低工具选择成本，人类维护者仍需原子能力。

### 6.3 影响分析的 `partial` 不等于失败

`mc_analyze` 返回 `analysis_status="partial"` 时，`impact`、`candidate_paths` 仍可用。只有 `error=true` 才表示入口级失败。

### 6.4 BM25 默认开启，Vector 默认关闭

Vector ANN 需显式启用（`enable_vector=True`）。VectorIndex 存在不代表已生成可用 embedding。

### 6.5 入口必须统一解析 workspace.yaml

入口接收 `workspace.yaml` 路径，但底层图谱是 `graph.db`。必须先 `WorkspaceStore(workspace)` 解析，再用 `workspace_store.graph_db_path` 打开图谱。

### 6.6 `async` 标记是宿主配置

`hooks.yaml` 中 `async: true` 的消费方是宿主（Claude Code / Codex），不是 runner。runner 始终同步执行。

### 6.7 Audit 是语言自适应的

`run_completion_audit()` 多语言自适应（Python/Java/JS/TS/Go/Rust），不会因为项目不是 Python 就扣分。

## 7. 性能约束

### 7.1 热路径原则

- 查询热路径只读取已发布 generation，不隐式重建索引
- 大图遍历必须有深度、边数、节点数限制
- 向量检索大索引必须走 sqlite-vec / HNSW，禁止 Python 暴力余弦
- 模型冷启动时保留基础排序，不等待加载锁

### 7.2 预算

| 指标 | 约束 |
|---|---|
| 默认查询 P95 | 热路径不触发全量重建 |
| 局部刷新 | 3 文件 < 10s |
| 完整 reindex | 不阻塞查询 |

## 8. 安全与隐私

### 8.1 本地优先

- 源码、索引、图谱、审计默认落在 `.memory-center/`
- 不上传业务代码或原始对话到中心服务
- 外部 embedding 不可用时返回可诊断降级，不静默改为云调用

### 8.2 验证执行器

- 只允许运行 workspace 维护者预注册的 argv profile
- 不执行模型输出或需求正文中的任意 shell 字符串
- 模型生成的命令属于不可信输入

### 8.3 审计与脱敏

- 审计只保留工具名、脱敏参数摘要、耗时、状态
- 默认保留一个月，最多十万条
- 不保存源码正文、原始对话、工具载荷

## 9. 提交规范

### 9.1 不要提交的内容

- 真实私有项目的 `.memory-center/index` 或 `.memory-center/memory`
- 私有路径、公司内部服务名、真实密钥
- 写入型测试直接修改仓库 demo workspace 的产物

### 9.2 提交前检查

```bash
# 编译检查
python -m compileall -q memory_center tests

# 测试
pytest -q

# 检查无遗留调试代码
git diff --check
```

## 10. 结构化推理协议（自主开发场景）

面对复杂任务或模糊需求时，不要急于回答。按以下步骤进行**双向钢人论证**并**自主决策**：

### 步骤 1：问题重述

用最完整、最有力的方式，重述真正想解决的问题。确认：
- 问题的边界在哪里
- 隐含的约束和假设是什么
- 成功标准是什么

### 步骤 2：双向钢人论证

分别给出**支持**和**反对**当前想法的最强论证：

| 支持论证 | 反对论证 |
|---|---|
| 最强理由 1 | 最强反驳 1 |
| 最强理由 2 | 最强反驳 2 |
| ... | ... |

不要构造弱论证来反驳（稻草人），要给出真正有说服力的对立观点。

### 步骤 3：识别分歧与关键变量

找出：
- 双方真正的分歧点在哪里
- 哪个变量最可能改变结论
- 是否存在不可调和的 trade-off

### 步骤 4：自主决策关键不确定性

不要等待用户回答，而是：

1. **识别关键不确定性**：哪个假设最可能改变结论？
2. **评估信息源**：
   - 项目文档（ARCHITECTURE、AGENTS.md、CHANGELOG）
   - 代码约定（现有实现模式）
   - 测试用例（预期行为）
   - 风险可逆性（决策是否容易回滚）
3. **做出合理假设**：基于上述信息，选择风险最低、最符合项目约定的方向
4. **记录假设**：在代码注释、commit message 或文档中明确说明假设
5. **设置检查点**：如果后续发现假设错误，准备回滚方案

### 步骤 5：执行与验证

1. 基于假设执行
2. 运行测试验证
3. 如果发现假设错误，立即调整

### 适用场景

- 架构决策（选 A 还是选 B）
- 需求模糊（用户说"优化一下"但没说标准）
- 风险判断（这个改动是否安全）
- 技术选型（引入新依赖的权衡）

### 决策原则

| 情况 | 决策策略 |
|---|---|
| 可逆决策 | 快速选择，执行后观察 |
| 不可逆决策 | 保守选择，符合项目约定 |
| 信息不足 | 选择风险最低的路径，记录假设 |
| 多个合理选项 | 选择最简单、最易理解的实现 |

---

## 11. 关键文件速查

| 文件 | 用途 |
|---|---|
| `docs/ARCHITECTURE.md` | 系统架构、分层边界、设计决策、常见误解 |
| `docs/MCP_GUIDE.md` | MCP facade、宿主接入 |
| `docs/USER_GUIDE.md` | 用户操作路径、常见工作流 |
| `docs/REFERENCE.md` | 命令、参数、schema 参考 |
| `docs/ONTOLOGY.md` | 轻量本体与演进计划 |
| `docs/CHANGELOG.md` | 变更记录 |
| `docs/NEXT_PHASE_MASTER_PLAN.md` | 开发路线 |
| `docs/DOCUMENT_CONSTITUTION.md` | 文档治理与发布清单 |
