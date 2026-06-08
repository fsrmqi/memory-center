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

如果工作需要交给其他开发者执行，必须同时阅读：

- [DELEGATED_EXECUTION_PLAN.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/DELEGATED_EXECUTION_PLAN.md)

交接计划中的执行顺序、范围边界、验收标准和禁止变更规则用于避免外部协作时误改公开 schema、污染 workspace 或扩大重构范围。遇到禁止变更时应记录并跳过，继续执行其他任务，最后统一评审。

## 2. 测试必须隔离 workspace，不能直接写仓库内 demo `.memory-center`

### 现象

`examples/spring-cloud-demo/.memory-center` 里存在示例 workspace、索引、graph、memory 和规则文件。它适合作为 demo 和 fixture 来源，但不适合作为测试运行时的写入目标。

很多操作会修改 `.memory-center` 下的生成物，例如：

- `reindex_workspace`
- `memory_query_hybrid`
- `ContextPackBuilder`
- `workspace_start_session`
- `memory_eval_token_gain`
- `business-flow` / `business-flow-impact` smoke
- HTTP / MCP / CLI 入口测试

这些操作可能改动：

- `.memory-center/graph/graph.db`
- `.memory-center/graph/graph.db-wal`
- `.memory-center/graph/graph.db-shm`
- `.memory-center/memory/memory.db`
- `.memory-center/memory/*.jsonl`
- `.memory-center/index/*.json`

### 为什么要特别说明

仓库规则要求不要提交真实私有项目生成的 `.memory-center/index` 或 `.memory-center/memory` 内容。即使这里是 demo workspace，直接写仓库内示例数据也会带来两个问题：

1. 测试后 `git status` 变脏，容易误提交生成物。
2. 测试之间共享同一个 graph / memory 状态，结果可能互相污染。

### 正确做法

新增测试时，不要这样写：

```python
workspace = "examples/spring-cloud-demo/.memory-center/workspace.yaml"
store = WorkspaceStore(workspace)
reindex_workspace(config, store)
```

应该这样做：

```python
source = Path("examples/spring-cloud-demo")
target = tmp_path / "demo"
shutil.copytree(source, target)
workspace = target / ".memory-center" / "workspace.yaml"

lines = workspace.read_text(encoding="utf-8").splitlines()
lines = [f"root: {target.as_posix()}" if line.startswith("root:") else line for line in lines]
workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

也就是：

1. 复制 demo 到 `tmp_path`
2. 改写 `workspace.yaml` 里的 `root`
3. 在临时副本中 reindex / query / run CLI / run HTTP route
4. 测试结束后让 pytest 清理临时目录

### 后续维护要求

任何新增测试只要会触发 reindex、session、memory write、graph write、benchmark write，都必须使用临时 workspace。

如果确实需要检查仓库内示例文件是否存在，只能做只读断言，不要调用会写入 `.memory-center` 的函数。

## 3. CLI / MCP / HTTP 入口必须统一解析 `workspace.yaml`

### 现象

Memory Center 的公开入口通常接收的是：

```text
/path/to/.memory-center/workspace.yaml
```

但底层图谱存储打开的是 SQLite graph db，例如：

```text
/path/to/.memory-center/graph/graph.db
```

如果入口直接把 `workspace.yaml` 传给 `GraphStore` 或 `UnifiedStore`，运行时会出现：

```text
DatabaseError: file is not a database
```

### 正确做法

入口层不要直接写：

```python
graph = GraphStore(workspace)
store = UnifiedStore(workspace)
```

应先解析 workspace：

```python
workspace_store = WorkspaceStore(workspace)
graph = GraphStore(workspace_store.graph_db_path)
store = UnifiedStore(workspace_store.graph_db_path)
```

更推荐复用 core helper，例如：

```python
extract_business_flows_for_workspace(workspace, seed, max_depth=4)
business_flow_impact_for_workspace(workspace, node_id, max_depth=3)
```

这样 CLI / MCP / HTTP 三入口可以共用同一套 workspace 解析逻辑。

### 后续维护要求

新增或修改以下能力时，必须确认 CLI / MCP / HTTP 语义一致：

- `context-pack`
- `freshness`
- `onboard`
- `domain`
- `business-flow`
- `business-flow-impact`
- `verification-loop`
- `runtime-audit`
- `regression-alerts`

至少应补一类入口矩阵测试：

- HTTP route matrix：直接调用 `_route_request`
- MCP matrix：调用 `create_server(...)._tool_manager._tools[...]`
- CLI smoke：用 `CliRunner` 调用关键命令

测试里要断言：

1. 返回是 dict
2. 包含核心字段
3. 输出中不包含 `file is not a database`
4. 使用的是临时 workspace，不污染仓库 demo

## 4. regression-alerts 使用 `threshold_pct`，不是 `benchmark_name`

### 现象

`check_regression_alerts(workspace_file, threshold_pct=10.0)` 的语义是根据 token 回归百分比阈值生成告警。

它不接受 `benchmark_name` 参数。

### 正确入口语义

CLI：

```bash
memory-center regression-alerts --workspace /path/to/.memory-center/workspace.yaml --threshold-pct 10
```

HTTP：

```text
/workspace/regression-alerts?workspace=/path/to/.memory-center/workspace.yaml&threshold_pct=10
```

MCP：

```text
mc_admin(action="regression_alerts")
```

当前 MCP admin 使用默认阈值。后续如果要让 MCP 也支持阈值，应先扩展 `mc_admin` 参数 schema，并保持向后兼容。

## 5. `user_prompt_submit` 默认禁用

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

## 6. `mode` 与 `enabled` 的关系

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

## 7. facade 与原子能力并存，不是重复设计

当前系统里：

- MCP 默认对模型暴露 8 个 facade 工具
- CLI / HTTP / core 内部仍保留很多原子能力

这不是重复设计，而是刻意分层：

- 模型面对 facade，降低工具选择成本和 token 开销
- 人类维护者和内部实现仍然需要原子能力做细粒度控制

所以看到“原子工具还在”不代表 facade 重构失败。

## 8. SQLite `memory.db` 不是唯一真相源

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

完整读取路径与后续迁移边界见 [UNIFIED_BACKEND_READ_PATHS.md](/Users/cuijiaqi/Ai-common-skills/memory-center/docs/UNIFIED_BACKEND_READ_PATHS.md)。

需要注意：当前镜像写入是 best-effort，而 backend-first 读取尚未返回 `source` 或 `fallback_reason`。如果文件写入成功但镜像失败，旧 backend 数据可能暂时覆盖文件中的新数据。新增迁移必须先补双读一致性测试，不允许直接删除文件 fallback。

## 9. 文档与实现冲突时怎么判断

如果出现：

- 文档说“应该这样”
- 代码实际“不是这样”

优先判断顺序建议是：

1. 先看当前代码实现
2. 再看这是不是有意的宿主兼容性 / token / UX 取舍
3. 如果是有意取舍，把原因补进这份文档
4. 如果不是有意取舍，再认定为 bug

也就是说，这份文档本身就是为了减少”把设计选择误判成 bug”的情况。

## 10. `async` 标记是宿主/Adapter 配置，不在 Runner 内消费

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

## 11. Audit 是语言自适应的，不是只检查 Python 项目

### 现象

`run_completion_audit()` 会检查测试文件和测试框架配置。早期版本只检测 Python（`**/*.py` + pytest 配置），非 Python 项目会收到误报的 `no_tests` 和 `no_pytest_config`。

### 当前行为

审计系统现在是多语言自适应的：

- 测试文件检测：Python (`*.py`)、Java (`*Test.java`)、JS/TS (`*.test.js`, `*.spec.ts`)、Go (`*_test.go`)、Rust (`*_test.rs`)
- 测试框架配置：pytest、Maven Surefire、Gradle JUnit、package.json `test` script、Cargo.toml `[dev-dependencies]`
- 文档检查：自适应检测 `docs/` 目录和任意 `.md` 文件，不硬编码特定文件名
- 评分权重：审计分数与健康分数使用统一权重（文档 -5、测试 -8、实现 -10）

### 正确理解

审计不会因为项目不是 Python 就扣分。它会根据项目实际使用的语言和框架进行检测。如果某个语言/框架组合未被覆盖，那是因为还没有添加对应的检测规则，而不是设计限制。

## 12. workspace 污染自动检测 / Workspace Pollution Auto-Detection

### 现象

仓库 demo workspace `examples/spring-cloud-demo/.memory-center/` 包含 30 个文件，用于示例和测试 fixture 来源。如果测试意外写入该目录，会导致 `git status` 变脏、测试间互相污染。

### 自动保护

`tests/test_workspace_pollution.py` 包含两个测试：

1. `test_demo_workspace_not_polluted` — 在测试 session 结束时校验 demo 文件 SHA-256，若有任何文件被修改则失败。
2. `test_pollution_detection_catches_modification` — 临时写入 marker 文件，验证检测机制本身工作正常，然后自动清理。

### 正确做法

任何新增测试只要会触发 reindex、session、memory write、graph write、benchmark write，都**必须**使用 `tests/fixtures.py` 中的 `copy_demo_workspace()` 或 `setup_demo_workspace()` helper，将 demo 复制到 `tmp_path` 后操作。

不要直接引用仓库内 demo workspace 路径做写入操作。

### 维护要求

- demo 目录新增文件后，污染检测会自动适应（基于文件列表 + SHA-256）。
- 不要通过扩大 `.gitignore` 来掩盖污染。
- CI 流程中 `pytest -q` 已包含污染检测，无需额外步骤。

## 13. Stop Conditions 只阻止对应高风险改造，不阻止其他工作

### 正确解释

`DELEGATED_EXECUTION_PLAN.md` 中的 Stop Conditions 是高风险变更审核边界，不是“只要涉及某个模块就停止”的模块禁改清单。

例如：

- “大规模重写 indexer、store、orchestrator”不等于禁止任何小范围修改。
- “引入新的运行时必选依赖”不等于禁止经过 fallback 设计的可选依赖。
- 文档盘点、只读分析、测试补充、兼容性验证通常可以继续执行。

执行者遇到 Stop Condition 时必须：

1. 只将实际触发禁止条件的具体方案标记为 `deferred-review`。
2. 记录触发证据、影响范围、替代方案和验证方法。
3. 继续执行其他不依赖该方案的工作包。
4. 不得仅因为工作包涉及 `store`、`indexer` 或 `orchestrator` 就直接延后。
5. 最终统一提交延后事项给负责人评审。

### 完成状态要求

- 新增 helper、schema 或测试，但尚未接入计划要求的主链路时，状态必须是 `partial`。
- 只有实际入口、主链路、验收测试和文档均满足计划验收标准时，才能标记 `completed`。
- `pytest` 通过不代表 lint 通过；只有执行 `ruff check .` 成功后，才能记录“全量测试和 lint 通过”。
- 跳过的测试必须记录原因，不能作为对应能力已完整验证的证据。

## 14. 统一错误模型位于公开入口边界

统一错误模型通过 CLI、MCP、HTTP 的集中入口边界接入，不要求每个 core 函数都改为抛出 `MCError`。

这样做的原因：

- core 层现有 `ValueError`、`FileNotFoundError` 等调用合同保持兼容。
- HTTP 会映射到状态码和结构化 body。
- MCP 会返回 Agent 可判断的结构化错误。
- 安装后的 CLI 会输出安全错误信息和退出码，不暴露 traceback。

维护要求：

- 新增公开入口必须复用 `normalize_exception()` 或现有入口边界。
- 不要在入口直接返回未经清洗的 `str(exc)`。
- 不要为了统一错误格式改变成功返回 schema。
- MCP tool 必须通过安全注册装饰器注册，避免绕过统一错误边界。
