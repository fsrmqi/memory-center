# User Guide / 使用指南

> **适用版本 / Version**：5.0.0b31。5.0 以独立常驻服务为唯一入口：管理页 `/admin/`、统一 MCP `/mcp` 与 `/api/v1/*` 管理 API 共用同一应用层（`memory-center` 命令只用于启动服务，没有子命令）。当前入口与合同见 [5.0 平台指南](V5_PLATFORM_GUIDE.md)，用户可感知的变化见 [CHANGELOG](CHANGELOG.md)。下方较早的版本记录保留作决策演进背景，不代表当前入口。
>
> **Version**: 5.0.0b31. The resident service is the single entry point of 5.0: the `/admin/` UI, the unified `/mcp` endpoint and the `/api/v1/*` management API share one application layer (the `memory-center` command only launches the service and has no subcommands). See the [platform guide](V5_PLATFORM_GUIDE.md) for current contracts and the [CHANGELOG](CHANGELOG.md) for user-visible changes; older sections below are historical background only.


> **当前入口 / Current entry**：`memory-center-service` 独立常驻服务，管理页 `/admin/`、MCP `/mcp`、项目目录 API `/api/v1/workspaces`。服务生命周期、状态与错误合同、安装与关闭见 [5.0 服务运行指南](V5_SERVICE_GUIDE.md)；项目登记与管理见 [项目目录管理指南](V5_CATALOG_GUIDE.md)；17 个 MCP 工具与 4.x→5.0 迁移对照见 [MCP 接入指南](MCP_GUIDE.md)。
>
> **章节边界 / Reading scope**：本文的**任务地图、§1 安装与 §6 的 MCP / 宿主绑定 / HTTP 三段是 5.0 现行入口**（§6 末尾另有一节明确标注为 4.x 历史能力）；§2、§3、§4、§5、§7、§8、§11、§12 中大量 `memory-center <subcommand>` 示例（`init`、`reindex`、`work-start`、`symbol`…），以及 `mc_admin(action=…)`、`mc_freshness`、`serve-http` 和 `/workspace/*` 读模型，都是 4.x 的 CLI / facade 命令。5.0 的 `memory-center` **只启动服务、没有任何子命令**；这些示例保留下来是为说明仍在 `core/` 中的引擎能力与历史决策背景，**不能照抄执行，也不构成 5.0 兼容承诺**。
>
> The resident service is the only 5.0 entry. **The Task Map, §1 Install and the MCP / host-bindings / HTTP parts of §6 describe current 5.0 surfaces** (the closing subsection of §6 is explicitly labelled 4.x historical). The many `memory-center <subcommand>` examples in §2/§3/§4/§5/§7/§8/§11/§12 (plus `mc_admin(action=…)`, `mc_freshness`, `serve-http` and `/workspace/*` read models) are 4.x CLI/facade commands. In 5.0 `memory-center` only launches the service and has **no subcommands** — those examples document engine capabilities still living under `core/` and are not executable.

> **只读状态 / Read-only status**：MCP 的 `mc_service_status` 无参数、只读，返回服务就绪状态、版本、能力、存储与索引预算；也可用 `GET /health/live`、`GET /health/ready` 与状态 API。完整 tool 合同见 [MCP 接入指南](MCP_GUIDE.md)。
>
> `mc_service_status` is the parameterless, read-only MCP tool returning readiness, version, capabilities, storage and index budgets; `GET /health/live`, `GET /health/ready` and the status API expose the same facts. See the [MCP guide](MCP_GUIDE.md) for the full contract.

## Who This Is For / 适用对象

这份文档面向日常使用者：想安装、初始化、重建索引、查询上下文、做影响分析、维护 workspace 的开发者或 Agent 使用者。

## 任务地图 / Task Map

不要从命令列表开始。按当前任务选择一条路径，完成停止条件后再升级。下表全部是 **5.0 可用的入口**（工具名与参数见 [MCP 接入指南](MCP_GUIDE.md)）：

| 任务 | 主入口 | 停止条件 | 升级路径 |
|---|---|---|---|
| 首次接入 | `memory-center-service` 启动 → 管理页 `/admin/` 登记项目 → `mc_workspaces()` 取 `workspace_id` | 项目状态 `active`、`mc_service_status.ready=true` | 按 MCP 接入指南配置宿主端点 |
| 建立索引 | `mc_index(workspace_id)` → `mc_job_status(job_id)` | job 到终态、generation 已发布 | 失败用 `POST /api/v1/jobs/{job_id}/retry` |
| 日常定位 | `mc_lookup(workspace_id, query, mode=...)` | 拿到证据路径与明确下一步 | 换 `mode` 或用 `mc_analyze` |
| 变更影响 | `mc_analyze(workspace_id, target)` | 影响链与风险明确 | 沿 `candidate_paths` 先验证高置信项 |
| 会话生命周期 | `mc_start` → `mc_resume` / `mc_close` | 会话轨迹与结论完整 | `mc_ref(ref_id)` 回取证据 |
| 宿主排障 | `mc_service_status` + `GET /health/ready` | 端点与认证确认 | 配好 Streamable HTTP 或 `memory-center-mcp` 代理后重启宿主会话 |

`mc_lookup` 的 `mode` 取值为 `keyword` / `vector` / `hybrid` / `symbol` / `callers` / `callees` / `context`；4.x 的 `auto` / `walkthrough` / `code` / `trace` 已退役。

## 1. Install / 安装

推荐安装方式：

```bash
bash /path/to/memory-center/install.sh
```

安装脚本会自动选择 Python 3.10+。如需手工刷新本地 `pipx` 安装，请显式指定符合版本要求的解释器：

```bash
pipx install --python python3.11 --force /path/to/memory-center
```

The install script automatically selects Python 3.10+. For a manual local `pipx` refresh, explicitly select a supported interpreter:

```bash
pipx install --python python3.11 --force /path/to/memory-center
```

开发环境：

```bash
pip install -e .
```

验证服务已就绪。5.0 **没有** `memory-center --version`：`memory-center` 只启动服务，不接受版本参数。

```bash
memory-center-service          # 前台启动，默认 127.0.0.1:8765
curl -s http://127.0.0.1:8765/health/ready
```

版本、就绪状态、能力与索引预算由无参数的 MCP 工具 `mc_service_status` 返回（或 `GET /health/live`、`GET /health/ready`）。字段约定见 [5.0 服务运行指南](V5_SERVICE_GUIDE.md)。

## 2. Initialize Workspace / 初始化工作区

```bash
memory-center init --workspace-root /abs/path/to/repo
```

`init` automatically scans the workspace root and registers one service per
recognized child directory. Hidden directories and conventional build
outputs (`target`, `build`, `dist`, `node_modules`, `.venv`, …) are skipped.

`init` 默认会自动扫描工作区根目录,为每个被识别的子模块生成一条 service 记录,
忽略隐藏目录和常见的构建产物目录。

```bash
# Preview what would be detected without writing anything.
# 预览将生成的内容,但不写入文件。
memory-center init --workspace-root /abs/path/to/repo --dry-run

```

### Supported service types / 支持的服务类型

| `type` | Language | Build markers | 用途 / Purpose |
|--------|----------|---------------|----------------|
| `spring-cloud-gateway` | java | `pom.xml` / `build.gradle` + `spring-cloud-starter-gateway` | Spring Cloud Gateway 网关 |
| `spring-boot-service` | java | `pom.xml` / `build.gradle` + `spring-boot` | Spring Boot 业务服务 |
| `spring-boot-task` | java | `pom.xml` + `spring-boot` | Spring Boot 定时/批处理任务 |
| `shared-library` | java | `pom.xml` / `build.gradle` + `spring-boot` | 共享库 / 契约模块 |
| `generic-jvm` | java | `pom.xml` / `build.gradle(.kts)` (无 Spring 信号) | 通用 JVM service |
| `kotlin-module` | kotlin | `build.gradle.kts` / `settings.gradle.kts` | Kotlin 模块 |
| `python-package` | python | `pyproject.toml` / `setup.py` / `setup.cfg` | Python 包 |
| `node-app` | typescript | `package.json` | Node.js / TypeScript 应用 |
| `go-module` | go | `go.mod` | Go 模块 |
| `rust-crate` | rust | `Cargo.toml` | Rust crate |
| `generic` | (none) | fallback | 未识别类型 / 通用目录 |

Unknown types fall back to `generic` with a runtime warning.
Set `language: <lang>` explicitly in `workspace.yaml` to override the
language inferred from `type` (e.g. `type: generic` + `language: scala`).

未识别的 `type` 会回退到 `generic` 并发出运行时警告。
可在 `workspace.yaml` 中显式设置 `language: <lang>` 来覆盖从 `type` 推断的语言。

### Files created / 初始化后重点关注

- `workspace.yaml`
- `.memory-center/rules/`
- `.memory-center/hooks.yaml`
- `.memory-center/artifacts/`

### Multi-language structural index / 多语言结构索引

Beyond Java's Spring-aware extractors (Feign / MQ / DTO contracts),
memory-center can index a generic structural graph for several other
languages. After the language bindings are installed, ``reindex``
emits ``Module`` / ``Class`` / ``Function`` nodes plus ``DEFINES`` /
``IMPORTS`` / ``CALLS`` edges for every supported source file alongside
the Java pipeline.

除 Java 的 Spring 专属抽取(Feign/MQ/DTO 契约)外,memory-center 还能为多种
语言构建通用结构图谱。安装对应 binding 后,`reindex` 会和 Java 流水线并行,
为每个被识别的源文件产出 Module/Class/Function 节点和 DEFINES/IMPORTS/CALLS 边。

| Language | Extensions | Binding |
|----------|------------|---------|
| Java | `.java` | `tree-sitter-java` (already required by `[ast]`) |
| Kotlin | `.kt`, `.kts` | `tree-sitter-kotlin` |
| Python | `.py`, `.pyi` | `tree-sitter-python` |
| TypeScript | `.ts` | `tree-sitter-typescript` (`language_typescript`) |
| TSX | `.tsx` | `tree-sitter-typescript` (`language_tsx`) |
| JavaScript | `.js`, `.mjs`, `.cjs`, `.jsx` | `tree-sitter-typescript` (`language_tsx`) |
| Go | `.go` | `tree-sitter-go` |

Install all bindings at once with the `multilang` extra:

```bash
pip install -e ".[multilang]"
```

Without these packages reindex still works — non-Java files are
silently skipped from the structural pass. Run `memory-center doctor`
to see which bindings are missing.

未安装 `[multilang]` 时,reindex 仍能正常工作,只是非 Java 文件不会进入结构
索引。运行 `memory-center doctor` 可查看哪些 binding 缺失。

Call edges from the structural pass start at low confidence
(``confidence=0.3``, ``metadata.resolution_level=unresolved``) because
the cross-language walker only has textual evidence. P1-1's Java call
resolver is already active for Java and rewrites resolvable calls with
higher-confidence targets; other languages remain structural evidence until
their language-specific resolver is added.

结构 pass 的调用边初始 `confidence=0.3` 且标记 `resolution_level=unresolved`；
Java 调用解析器会将可证明的本地调用改写为更高置信度目标。4.3.78 起，enum
生成方法、外部返回类型链和最终继承外部框架接口的方法会保留为明确的索引边界，
不会为了提高表面解析率而绑定到工作区内同名方法。

## 3. Reindex / 重建索引

全量：

```bash
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml
```

只刷新明确文件时使用 `--path`；4.3.79 会直接定位该文件，不再遍历完整服务目录。刷新后查看性能：

```bash
memory-center scoped-refresh-performance --workspace /abs/path/.memory-center/workspace.yaml
```

`status=healthy` 时停止重复刷新；`warning` 时根据 `latest.dominant_stage` 定位瓶颈，不要改为隐式全量重建。

显式校准共变先验时先预检，再应用：

```bash
memory-center eval-cochange --workspace /abs/path/.memory-center/workspace.yaml --max-commits 20 --warmup-commits 5
memory-center eval-cochange --workspace /abs/path/.memory-center/workspace.yaml --max-commits 20 --warmup-commits 5 --apply
```

只有第一条返回 `calibration.eligible=true` 才执行第二条。检索 replay 使用 `eval-retrieval-replay`，样本不足或留出集退化时不要使用 `--apply`。

增量：

```bash
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --project xxx
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --path module-a/src/main/java
memory-center reindex --workspace /abs/path/.memory-center/workspace.yaml --changed-only --scope all
```

## 4. Daily Workflow / 日常工作流

最推荐的高频命令：

```bash
memory-center work-start --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-sync --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-resume --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
memory-center work-handoff --workspace /abs/path/.memory-center/workspace.yaml --target-model codex --intent "..."
memory-center work-close --workspace /abs/path/.memory-center/workspace.yaml --session-id <session_id>
memory-center work-health --workspace /abs/path/.memory-center/workspace.yaml
```

### Memory boundaries: what goes where / 记忆边界：什么记到哪

Memory Center 有四类记忆边界。每类回答一个问题，对应真实存在的机制；记不住"该记到哪层"时按这张表决策：

| 边界 / Boundary | 回答的问题 / Question | 对应机制 / Mechanism |
|---|---|---|
| Coding Memory（工程教训） | "这个教训下个任务还要用吗？" | L1 case atoms（`memory-center record-case` / `mc_admin(action="write_judge")`） |
| Repo Memory（仓库该知道什么） | "Agent 应该知道这个仓库的哪些事实？" | 图谱索引 + `architecture_invariants` / `workspace_profile` 记忆块 |
| Personal Memory（协作偏好） | "Agent 该怎么和我沟通？" | L3 `workspace_profile` 记忆块 |
| Procedure Memory（流程规范） | "这类任务的标准流程是什么？" | `team_rules` 记忆块 + 交付验证设计契约 |

介于四类之下还有一层 **Session Notes（L0.5 叙事记忆）**：还不够成为 case、但比原始事件可读的"这次决定了什么/下一步做什么"。用 `mc_admin(action="note_record", text=..., event_type=decision|fact|preference|rule|next_step, session_id=...)` 显式记录，`note_list` / `note_search` 查看，`note_supersede` 修正（追加替代决策行 + 新条，原条永不改写），`note_forget` 遗忘（追加决策行，只隐藏具名条目；被遗忘后同 fingerprint 可重新记录）；两类决策行都记录操作者（`source` 作为 actor）。隐私门 fail-closed：绝对路径与密钥形态直接拒收，`<private>...</private>` 片段落盘前剥除。

## 5. Common Queries / 常见查询

### 查任务上下文

```bash
memory-center sniff --workspace /abs/path/.memory-center/workspace.yaml --intent "..."
```

### 查符号 / 代码 / 调用链

```bash
memory-center symbol --workspace /abs/path/.memory-center/workspace.yaml --name ArticleFeignClient
memory-center search-code --workspace /abs/path/.memory-center/workspace.yaml --query oldPubTime
memory-center callers --workspace /abs/path/.memory-center/workspace.yaml --symbol com.example.ArticleService#update
memory-center callees --workspace /abs/path/.memory-center/workspace.yaml --symbol com.example.ArticleService#update
```

### 做影响分析

```bash
memory-center impact --workspace /abs/path/.memory-center/workspace.yaml --target ArticleDTO
memory-center detect-changes --workspace /abs/path/.memory-center/workspace.yaml --scope all
memory-center change-review --workspace /abs/path/.memory-center/workspace.yaml --scope all --detail-level minimal
```

`change-review` 是日常改动的默认入口：它自动识别变更，对最多 12 个相关文件执行定向刷新，再一次返回加权影响链、契约风险、测试缺口、验证动作和停止条件，不会触发全量重建。默认先看 `minimal`；只有证据不足或需要更完整说明时再使用 `--detail-level standard|deep`。MCP 对应 `mc_admin(action="change_review", scope="all", view="minimal")`。

### 影响分析的结果与降级

MCP 使用 `mc_analyze` 时，参数边界为：`depth=quick|standard|full`、`direction=upstream|downstream|both`、`max_depth=1..6`。`quick` 只返回影响图；`standard` 增加变更计划和规则；`full` 再增加契约检查与验证清单。

当影响图已成功、但计划或契约等辅助阶段暂时不可用时，返回 `analysis_status="partial"`。这表示已返回的 `impact` 仍可使用，应先沿 `candidate_paths` 验证高置信影响，再根据 `diagnostics` 修复或单独重试失败阶段；不要把它误解为“完全分析失败”。只有 MCP 返回 `error=true` 时才是入口级失败，此时使用 `diagnostics.trace_id` 对照本地审计并检查宿主、工作区和索引状态。

## 6. MCP / HTTP / UI

### MCP

默认安装已包含 MCP 运行时依赖，`memory-center-mcp` 安装后应直接可用。

The default install includes MCP runtime dependencies, so `memory-center-mcp` should work immediately after install.

```bash
MEMORY_CENTER_URL=http://127.0.0.1:8765/mcp memory-center-mcp
```

stdio 代理不接收 `--workspace`：它只是把 stdio 转发到常驻服务，连接目标由 `MEMORY_CENTER_URL` 决定，凭据由 `MEMORY_CENTER_TOKEN` 决定。因此一个代理进程可以服务任意 workspace，workspace 归属由 `mc_*` 调用里的参数或服务端会话决定。

The stdio proxy takes no `--workspace`: it forwards stdio to the resident service. The endpoint comes from `MEMORY_CENTER_URL` and credentials from `MEMORY_CENTER_TOKEN`, so one proxy process can serve any workspace.

工具面以服务实际返回的 `tools/list` 为准，当前 17 个：`mc_service_status`、`mc_workspaces`、`mc_lookup`、`mc_analyze`、`mc_start`、`mc_resume`、`mc_close`、`mc_ref`、`mc_memory_write`、`mc_wiki_write`、`mc_index`、`mc_job_status`、`mc_job_cancel`、`assistant_admin`、`assistant_knowledge`、`assistant_memory`、`assistant_skill`。逐项签名见 [MCP 接入指南](MCP_GUIDE.md)。

常见的 4.x 名字在 5.0 已退役，不要照抄：`mc_admin(action=…)`、`mc_context_pack`、`mc_freshness`、`mc_onboard`、`mc_domain`、`mc_sync`、`mc_handoff`。特别注意 `assistant_admin` 只支持 `validate` / `scan` / `index` 三个知识库动作，**不是** `mc_admin` 的替代品；4.x 管理路由的现做法见 MCP 接入指南的迁移对照表。

The 5.0 tool surface is defined by the live `tools/list` response (17 tools today; see the [MCP guide](MCP_GUIDE.md)). 4.x names such as `mc_admin(action=…)`, `mc_freshness` and `mc_context_pack` are retired. `assistant_admin` only supports `validate` / `scan` / `index` and is **not** a replacement for `mc_admin`.

### 宿主绑定 / Host bindings

MCP 绑定由 `core/governance/instructions.py` 写入：`write_agent_instructions()` 落受管协议块，`repair_agent_mcp_bindings()` 补齐聚合根与各 service 子目录的 `.codex/mcp.json`、`.cursor/mcp.json`、`.mcp.json`，装有 DSH 时还覆盖各 profile 的 `cordis.patch.yml`。5.0 既没有 CLI 子命令，也没有 MCP 工具暴露该动作——它们是内部函数，只由宿主集成脚本或测试调用。用户侧按上文把 `/mcp` 端点配置到宿主即可；`memory-center-integrations` 只打印配置模板，不会修复绑定。

MCP bindings are written by `core/governance/instructions.py` (`write_agent_instructions()` / `repair_agent_mcp_bindings()`). 5.0 exposes neither a CLI subcommand nor an MCP tool for that action — they are internal functions called by host integration scripts or tests. Configure the `/mcp` endpoint in your host; `memory-center-integrations` only prints a template and does not repair bindings.

服务子目录里看不到 `mc_*` 工具时，先确认宿主指向 `/mcp` 端点且凭据正确，再重启宿主会话。4.x 的 `setup-agent`、`runtime-audit --fix`、`generate-hooks` 在 5.0 均已移除；`hooks.yaml` 只被审计读取、不执行任何 hook。

If a service sub-directory does not expose `mc_*` tools, verify the host points at `/mcp` with the right credentials, then restart the host session. The 4.x `setup-agent`, `runtime-audit --fix` and `generate-hooks` commands are gone; `hooks.yaml` is read by the audit and never executed.

如果 Agent 首轮没有看到 `mc_*`，先把状态视为“装载中或未知”：执行延迟工具发现，并用无参数的 `mc_service_status` 或 `GET /health/ready` 做轻量验证。Codex 中可运行 `codex mcp get memory-center`；若显示 `enabled: true`，但当前会话仍无工具，应刷新或新建会话，不要误报“Memory Center 未加载”。只有绑定缺失、命令不存在或 MCP 调用明确失败时才执行降级流程。

### 4.x 引擎能力（历史背景，非 5.0 入口）

`clarify_change_request`、`audit_project_claim`、`design_minimal_validation`、`compare_change_options` 四个模板仍作为静态资源留在 `core/governance/reasoning_prompts.py`，但 5.0 **没有注册任何 MCP Prompt**，也没有 `memory-center eval-reasoning-prompts` 命令。它们由 benchmark 评估脚本消费，属于引擎能力而非 5.0 入口，不能通过 MCP 调用。真实验收的 `examples/reasoning-prompt-eval` 模板同样属于 4.x 流程。

The four reasoning-prompt templates still exist as static resources under `core/governance/reasoning_prompts.py`, but 5.0 registers **no MCP prompts** and has no `eval-reasoning-prompts` command. They are consumed by benchmark tooling only — engine capabilities, not 5.0 entry points.

`evidence-subgraph` 同理：`core/presentation/evidence_subgraph.py` 提供有界证据图导出（从 node id 或受限 symbol 定位根节点，最多 3 跳、120 条边、80 个节点，输出 JSON / Markdown / HTML），实现仍在且被回归测试覆盖，但 5.0 没有对应的 MCP 工具或 `/api/v1` 路由。4.x 的 `memory-center export-evidence-subgraph` 与 `GET /workspace/evidence-subgraph` 已退役；契约细节见 [ARCHITECTURE.md](ARCHITECTURE.md) §11。

Likewise, `core/presentation/evidence_subgraph.py` still implements bounded evidence-graph export, but 5.0 exposes no MCP tool or `/api/v1` route for it. The 4.x `export-evidence-subgraph` CLI entry and `/workspace/evidence-subgraph` route are retired; see [ARCHITECTURE.md](ARCHITECTURE.md) §11.

### HTTP JSON API + 管理页 / Admin UI

5.0 **不需要** `serve-http`：启动 `memory-center-service` 即为 HTTP 服务，默认监听 `127.0.0.1:8765`，管理页为 `http://127.0.0.1:8765/admin/`。

```bash
memory-center-service
curl -s http://127.0.0.1:8765/health/live
curl -s http://127.0.0.1:8765/health/ready
```

常用接口（完整合同见 [项目目录管理指南](V5_CATALOG_GUIDE.md) 与 [5.0 平台指南](V5_PLATFORM_GUIDE.md)）：

- 项目目录：`GET/POST /api/v1/workspaces`、`POST /api/v1/workspaces/preview`、`GET /api/v1/workspaces/{workspace_id}`、`PATCH` / `pause` / `resume`
- 后台作业：`GET /api/v1/jobs`、`POST /api/v1/jobs/{job_id}/retry`、`POST /api/v1/jobs/{job_id}/cancel`
- 健康检查：`GET /health/live`、`GET /health/ready`

项目登记、暂停、更新等管理接口要求 `Authorization: Bearer <管理员令牌>`；令牌文件在 `<服务目录>/admin-token`（默认 `~/.memory-center/v5/admin-token`），权限 0600，首次启动自动生成。服务默认只监听 loopback；需要非回环地址时用 `--container-local` 与 `--allowed-host`，并遵循服务运行指南的发布约束。

Project-management endpoints require `Authorization: Bearer <admin token>`; the token file is `<data-dir>/admin-token` (0600, generated on first start). The service listens on loopback by default; see the service guide before exposing a non-loopback address.

4.x 的 `memory-center serve-http`、`MEMORY_CENTER_HTTP_TOKEN`、`/workspace/*` JSON 读模型、`/ui/*` 页面与 `/app` Vue SPA 在 5.0 均已退役。旧页面与替代读模型仅作历史背景，见 [HTTP 展示迁移说明](HTTP_DISPLAY_MIGRATION.md)。

The 4.x `serve-http` command, `MEMORY_CENTER_HTTP_TOKEN`, `/workspace/*` read models, `/ui/*` pages and `/app` SPA are all retired in 5.0. The old display migration note is kept as historical background only.

## 7. Multi-Workspace / 多工作区

支持：

- 一个大根目录下多个服务
- 多个独立 workspace
- registry + group 聚合

典型命令：

```bash
memory-center register-workspace ...
memory-center create-group ...
memory-center add-to-group ...
```

## 8. Maintenance / 维护

### Quality and storage / 质量与存储（4.6.12）

发布或较大改动前可运行只读质量门禁：

```bash
memory-center quality-gate --workspace .memory-center/workspace.yaml
```

它汇总 generation、coverage、retrieval replay、IR diff gate、局部刷新与存储健康。`attention` 表示需要阅读原因或积累真实样本；只有 `block` 才代表存在不可发布的事实不一致。该命令不会重建索引、执行清理或运行外部测试。

局部刷新性能会按变更类别和 scope 自动记录；只有同一分桶积累至少 5 个真实样本且 P95 超预算时才建议优化。可用以下只读命令查看：

```bash
memory-center scoped-refresh-performance --workspace .memory-center/workspace.yaml
memory-center runtime-governance --workspace .memory-center/workspace.yaml
```

空间维护始终先 dry-run；确认后才使用 `--apply`。运行时事实已以 SQLite 为准，部分索引 JSON 是可选导出，不应手工恢复为查询回退。

### Case 治理：替代与恢复 / Case supersede and reinstate

L1 case 过时（方案已演进、结论被新实践取代）时不要手工编辑 case 文件，用追加式决策治理：

```bash
memory-center case-supersede --workspace /abs/path/.memory-center/workspace.yaml \
  --case-id <old-case-id> --superseded-by <new-case-id> --actor <your-name> --note "方案过时"
memory-center case-decisions --workspace /abs/path/.memory-center/workspace.yaml --case-id <old-case-id>
```

决策行写入 `memory/case-decisions.jsonl`，case 原始行永不改写；`status`/workspace overview 计数按投影实时计算（latest wins）。写错时可 `case-reinstate` 恢复，错误决策也保留在审计链里。`mc_admin` 同义 action 为 `case_supersede` / `case_reinstate` / `case_decision_list`，HTTP 入口为 `/workspace/case-supersede` 等。所有 L1 写入路径（record-case、整合候选审批、work-close 自动案例）的 write receipt 均带 additive `decision` 块（actor/reason），可用 timeline 回放完整审计"谁在什么依据下写了这条记忆"。

建议周期性执行：

```bash
memory-center status --workspace /abs/path/.memory-center/workspace.yaml
memory-center regression-smoke --workspace /abs/path/.memory-center/workspace.yaml
memory-center eval-token-benchmark --workspace /abs/path/.memory-center/workspace.yaml
memory-center eval-golden --workspace /abs/path/.memory-center/workspace.yaml --cases /abs/path/private-cases.yaml
```

### 可验证交付 Skill

长期重复的已验证交付可以沉淀为 Skill，但不会自动进入默认检索。最小流程是：

```bash
memory-center artifact delivery-skill-candidate --workspace /abs/path/.memory-center/workspace.yaml --task-id <task_id>
memory-center artifact delivery-record-validation --workspace /abs/path/.memory-center/workspace.yaml --task-id <task_id> --status passed --acceptance-ids '["AC-1"]' --evidence-kind manual_verified --actor <reviewer>
memory-center artifact delivery-skill-contract-update --workspace /abs/path/.memory-center/workspace.yaml --task-id <task_id> --contract '{"languages":["java"],"applicability_conditions":["目标范围与已验证交付一致"],"prohibited_conditions":["需求边界不清时禁止使用"],"preconditions":["已完成定位"],"acceptance_evidence":{"accepted_kinds":["executor","manual_verified"],"required_fields":["acceptance_ids","evidence_refs"]},"stop_conditions":["索引陈旧时停止"],"rollback":{"triggers":["出现失败观测"],"action":"执行 delivery-skill-rollback 并回退到常规交付流程"},"input_contract":{"required_fields":["intent","task_id"]},"output_contract":{"required_fields":["next_action","validation_evidence"]},"replay_policy":{"redacted":true,"minimum_verified_passed":3}}'
memory-center artifact delivery-skill-canary --workspace /abs/path/.memory-center/workspace.yaml --task-id <task_id>
memory-center artifact delivery-skill-observe --workspace /abs/path/.memory-center/workspace.yaml --skill-id <skill_id> --outcome passed --evidence-refs '["delivery-validation:<task-ref>:<receipt-id>"]'
memory-center artifact delivery-skill-evaluate --workspace /abs/path/.memory-center/workspace.yaml --skill-id <skill_id>
memory-center artifact delivery-skill-replay --workspace /abs/path/.memory-center/workspace.yaml --skill-id <skill_id>
memory-center artifact delivery-skill-publish --workspace /abs/path/.memory-center/workspace.yaml --task-id <task_id>
```

契约必须含至少一种明确语言、适用条件、禁止条件、前置条件、验收证据、停止条件、回滚方式、输入字段、输出字段及 `replay_policy.redacted=true`；`unknown` 不能进入灰度。人工验证必须显式传入 `actor`，并会自动生成脱敏、可解析的 `delivery-validation` 引用；返回的 `identity_assurance=self_asserted` 表示该身份由调用方声明。成功观测必须引用实际存在的 `passed` 回执，并核对证据种类和原始引用归属，同一回执不能重复计数。JSONL 保留完整审计，SQLite 读模型按任务锁内分批回填，并通过稀疏验收关系查询门禁；早期有效证据不会因新增记录而失效，也不会每次扫描或反序列化全部历史。每次 canary 使用独立 `activation_id`，契约修订、回滚重启后的旧观测和 replay 会在应用数量上限前被过滤，不会挤掉当前评估证据。`minimum_verified_passed` 默认是 3，评估和发布使用完全相同的阈值。默认检索只使用契约完整的 `published` Skill，并同时返回禁止条件、停止条件与回滚动作；发现回归时使用 `delivery-skill-rollback`，历史证据仍保留。`delivery-failure-candidates` 与 `delivery-skill-synthesize` 是显式离线维护命令，不在日常查询中自动运行。

### 选择交付画像并约束任务范围

`mc_start` 会按任务意图返回 workflow 推荐。除常规修复、契约变更、长期任务和架构变更外，`maintenance` 适用于健康检查、技术债治理与架构演进。画像只决定推荐的上下文层与操作顺序，实际状态仍由 `feature_delivery_v2` 管理。

对子任务建议同时记录：

```json
{
  "id": "SUB-1",
  "title": "实现发布接口",
  "code_targets": ["ArticleController#publish"],
  "read_targets": ["ArticleController", "ArticleService"],
  "write_targets": ["ArticleController#publish"],
  "stop_conditions": ["发现跨服务契约变更时停止并重新运行影响分析"]
}
```

对高风险验收建议同时记录可证伪验证设计：

```json
{
  "id": "AC-1",
  "title": "旧客户端兼容",
  "critical_hypothesis": "旧客户端仍能解析新响应",
  "continue_if": "旧版回归和契约门禁均通过",
  "stop_if": "旧版反序列化失败",
  "rollback": "恢复旧契约",
  "evidence_required": ["contract-gate", "executor-receipt"]
}
```

需要严格控制 Agent 修改边界时，由工作区维护者在 `delivery-policy.json` 中设置：

```json
{
  "enforce_scope_contract": true,
  "enforce_validation_design_contract": true,
  "enforce_evidence_contract": true,
  "validation_profiles": [{
    "id": "contract-gate",
    "argv": ["python3", "-m", "pytest", "tests/contracts"],
    "evidence_types": ["contract-gate"]
  }]
}
```

前三项分别阻止范围不完整的子任务进入实现阶段、验证设计不完整的验收进入代码定位阶段，以及所需证据未闭环的任务关闭。执行器回执自动提供 `executor-receipt`，并合并 profile 的 `evidence_types`；人工确认可通过 `delivery-record-validation --evidence-types` 声明证据类型。三项门禁默认均关闭，因此旧任务仍可继续；策略不会执行模型传入的命令，也不会修改源码。

## 9. Keep It Small / 如何避免用法膨胀

优先顺序建议：

1. 先用 `work-*`
2. 不够时再用 facade / CLI 原子命令
3. 排障或开发系统本身时再深入 `REFERENCE.md`

## 10. Related Docs / 相关文档

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [MCP_GUIDE.md](./MCP_GUIDE.md)
- [REFERENCE.md](./REFERENCE.md)
- [ONTOLOGY.md](./ONTOLOGY.md)

## 11. Implemented Features / 已实现功能（当前 4.6.12）

这一节是当前可用功能说明，主要帮助使用者理解系统里已经能用什么，不代表这些功能仍处于待实现状态。

### 11.1 Hybrid Retrieval / 混合检索

**何时使用**: 需要查询代码、符号、调用链时，使用 hybrid retrieval。

**使用方式**: 通过 `memory_query_hybrid()` 或在 Python 代码中直接调用。

```python
from memory_center.core.retrieval import hybrid_retrieve, HybridRetrievalConfig

# 默认配置
result = hybrid_retrieve(graph, workspace_file, "asyncBusinessOperationExport")

# 自定义配置（调整权重）
config = HybridRetrievalConfig(
    graph_weight=0.5,      # 增加 graph 权重
    sparse_weight=0.3,
    semantic_weight=0.2,
    vector_weight=0.15,
    enable_sparse_bm25=True,
    enable_vector=False,   # 真实 dense embeddings 就绪后再启用
)
result = hybrid_retrieve(graph, workspace_file, query, config=config)
```

**返回内容**:
- `results`: 匹配结果（带分数、来源、邻居）
- `intent`: 检测到的意图（feign/mq/endpoint 等）
- `retrieval_summary`: 检索统计
- `progressive`: 渐进式摘要
- `retrieval_diagnostics`: BM25 / Vector 的 disabled、empty、unavailable 或 active 状态

默认情况下，reindex 会自动构建 SQLite BM25；Vector ANN 默认关闭。启用本地 embedding backend 并重新 reindex 后，dense vectors 会同步到 VectorIndex，再根据真实查询 benchmark 决定是否开启 vector。reindex 汇总会返回 `semantic_backend`、`requested_semantic_backend`、`vector_scope`、`vector_candidate_count`、`dense_doc_count`、`vector_status`、`vector_disabled_reason`，用于解释 `vector_embeddings=0` 是因为 sparse backend、模型不可用、scope 无候选，还是 dense vector 已就绪。

增量 / 指定路径 reindex 时，VectorIndex 也会按 changed node 增量同步：变更节点先删除旧 embedding，再对仍然可向量化的节点 upsert 新 embedding；未变化节点的 dense embeddings 会保留。一次默认 sparse backend 的 reindex 不会清空之前本地 embedding backend 生成的 VectorIndex。

Golden Benchmark 的 hybrid case 可以通过 `enable_vector: true` 显式启用 ANN，用于给概念查询建立长期门禁：

```yaml
schema_version: 1
cases:
  - case_id: vector-feign-auth-interceptor
    query: Feign 调用的鉴权拦截器
    mode: hybrid
    enable_vector: true
    expected_anchors:
      - FeignConfig#feignDecoder
      - FeignSpringFormConfiguration#feignContract
    expected_edges: []
    forbidden_anchors:
      - VideoSolutionAudioService
    max_latency_ms: 8000
```

**意图检测示例**:
- `"feign client"` → feign 意图
- `"/api/users"` → endpoint 意图
- `"kafka topic"` → mq 意图
- `"调用链"` → chain 意图

### 11.2 Benchmark Trending / 基准趋势

**何时使用**: 需要监控 token 使用变化，检测回归问题。

如果你想验证真实 Spring Cloud workspace 中 `regex` 与 `tree-sitter` 解析结果是否收敛，可以运行：

```bash
memory-center eval-parser-benchmark --workspace /abs/path/.memory-center/workspace.yaml

### Golden Benchmark / 金标基准

```bash
memory-center reindex --workspace examples/golden-benchmark/workspace.yaml
memory-center eval-golden --workspace examples/golden-benchmark/workspace.yaml --cases examples/golden-benchmark/cases.yaml

memory-center eval-golden \
  --workspace /abs/path/.memory-center/workspace.yaml \
  --cases /abs/path/private-cases.yaml
```

- `--workspace` 可以直接指向真实 workspace 的 `.memory-center/workspace.yaml`
- `--cases` 建议使用本地私有文件，不要把真实业务链路直接提交进仓库
- 公开模板见 [examples/golden-benchmark/cases.template.yaml](../examples/golden-benchmark/cases.template.yaml)
```

**使用方式**:

```python
from memory_center.core.benchmark import (
    record_benchmark_trend,
    get_benchmark_trends,
    generate_benchmark_report
)

# 记录趋势点（每次调用后）
record_benchmark_trend(
    workspace_file,
    "mc_lookup",           # 函数名
    raw_tokens=1000,       # 原始 token
    compact_tokens=300,    # 压缩后 token
    budget="medium"
)

# 获取趋势分析
trends = get_benchmark_trends(
    workspace_file,
    function_name="mc_lookup",
    days=30                # 最近 30 天
)

# 生成综合报告
report = generate_benchmark_report(workspace_file)
```

**返回内容**:
- `function_trends`: 按函数分组的趋势数据
- `regressions`: 检测到的回归问题
- `summary`: 摘要统计
- `health_score`: 健康评分

**回归检测**: 自动比较近期 vs 历史平均，超过 10% 增长则标记为回归。

### 11.3 Unified Backend Query / 统一后端查询

**何时使用**: 需要查询 session、receipt、timeline 等高频数据。

**使用方式**:

```python
from memory_center.core.backend import UnifiedBackendQuery

with UnifiedBackendQuery(db_path) as backend:
    # 查询记录
    records = backend.query_records(collection="session-events.jsonl")

    # 查询特定 session
    events = backend.query_session_events(session_id="xyz")

    # 查询写入收据
    receipts = backend.query_write_receipts(project="test")

    # 聚合统计
    session_stats = backend.aggregate_by_session()
    project_stats = backend.aggregate_by_project()

    # 时间线查询
    timeline = backend.query_timeline(session_id="xyz", task_id="task-001")

    # 健康检查
    health = backend.check_health()
```

**返回内容**:
- 统一的记录格式
- 聚合统计
- 健康状态

### 11.4 Drill-Down Navigation / 钻取导航

**何时使用**: 需要深入查看 ref、timeline、task 的详情。

**使用方式**:

```python
from memory_center.core.navigation import DrillDownNavigator

with DrillDownNavigator(workspace_file) as nav:
    # 展开引用（渐进式）
    ref = nav.expand_ref("session-event:abc123")
    # ref 包含:
    #   - level_1_summary: 摘要
    #   - level_2_details: 详情
    #   - level_3_related: 相关项
    #   - reverse_links: 反向导航

    # 钻取时间线
    timeline = nav.drill_timeline(
        session_id="xyz",
        start_event_id="event-001",  # 从某个事件开始
        limit=50
    )
    # 包含: events, summary, navigation hints

    # 钻取任务
    task = nav.drill_task(task_id="task-001")
    # 包含: summary, timeline, write_receipts

    # 构建切换上下文（模型切换时使用）
    handoff = nav.build_handoff_context(session_id="xyz")
    # 包含: session_summary, key_points, open_questions, next_steps

    # 构建 Facade 摘要
    summary = nav.build_facade_summary(intent="查 Feign", results={...})
    # 包含: level_1_summary, level_2_results, level_3_refs
```

**渐进式披露**:
- Level 1: 快速摘要（始终显示，token 最少）
- Level 2: 详细信息（按需展开）
- Level 3: 相关项（进一步探索）

### 11.5 Completion Audit / 完成审计

**何时使用**: 需要检查文档对齐、测试覆盖、实现完整性。

**使用方式**:

```python
from memory_center.core.audit import (
    run_completion_audit,
    record_design_decision,
    get_design_decisions,
    generate_audit_report
)

# 运行完成审计
audit = run_completion_audit(
    workspace_file,
    work_package="Phase A",      # 可选：特定工作包
    check_docs=True,              # 检查文档
    check_tests=True,             # 检查测试
    check_implementation=True     # 检查实现
)

# 记录设计决策
record_design_decision(
    workspace_file,
    topic="hybrid_retrieval",
    decision="使用 RRF 合并三种检索源",
    rationale="平衡精确性和召回率",
    alternatives=["简单加权", "学习排序"],
    impact="high"
)

# 查询设计决策
decisions = get_design_decisions(workspace_file, topic="hybrid_retrieval")

# 生成综合报告
report = generate_audit_report(workspace_file)
```

**返回内容**:
- `score`: 健康评分（0-100）
- `quality`: 质量等级（high/medium/low）
- `findings`: 发现的问题
- `recommendations`: 改进建议
- `overall_health`: 整体健康评估

**审计维度**:
- 文档: 关键文档存在性、ARCHITECTURE 完整性
- 测试: 测试文件、pytest 配置
- 实现: 模块完整性
- 设计: 冲突决策检测

### 11.6 最佳实践

**日常开发流程**:
1. 开始任务 → `mc_start`
2. 查询代码 → 使用 `hybrid_retrieve` 或 `mc_lookup`
3. 修改前 → `mc_analyze` 检查影响面
4. 记录趋势 → `record_benchmark_trend`
5. 结束任务 → `mc_close`

**定期维护**:
```bash
# 每周运行审计
from memory_center.core.audit import run_completion_audit
audit = run_completion_audit(workspace_file)

# 每天检查趋势
from memory_center.core.benchmark import get_benchmark_trends
trends = get_benchmark_trends(workspace_file, days=7)

# 记录重要设计决策
from memory_center.core.audit import record_design_decision
record_design_decision(workspace_file, topic="...", decision="...", rationale="...")
```

## 12. Troubleshooting / 故障排除

### 12.1 真实工作区性能与后台任务

性能快照是显式、低频的运维动作，不会在普通查询中自动执行：

```bash
memory-center performance-snapshot --workspace /abs/path/.memory-center/workspace.yaml --samples 5 --tier fast
memory-center performance-status --workspace /abs/path/.memory-center/workspace.yaml
memory-center http-route-contract-audit
```

快照仅保留 generation、P50/P95/P99、最大耗时和成功/失败计数。它不保留探针查询、路径或源码。长任务可通过 `memory-center job-status --workspace <workspace.yaml> --job-id <job-id>` 查看 `progress_percent`、ETA、是否可取消和恢复动作；DSH 或自建集成使用 `GET /workspace/job-status?workspace=<workspace.yaml>` 轮询同一份紧凑状态。

### 12.2 检索结果不理想

**问题**: 查询返回太多/太少结果。

**解决**:
1. 调整 `HybridRetrievalConfig` 权重
2. 使用更具体的查询词
3. 检查意图检测是否正确

### 12.3 回归检测误报

**问题**: 检测到假回归。

**解决**:
1. 检查阈值设置（默认 10%）
2. 增加历史数据点
3. 手动标记为已知变化

### 12.4 审计分数低

**问题**: 审计分数低于预期。

**解决**:
1. 查看 `findings` 列表
2. 按优先级修复（high → medium → low）
3. 补充缺失的文档/测试

### 12.5 导航找不到数据

**问题**: `expand_ref` 或 `drill_timeline` 返回空。

**解决**:
1. 检查 ref_id/session_id 是否正确
2. 确认数据已写入 backend
3. 使用 `check_health()` 检查后端状态

### 12.6 `mc_analyze` 返回错误或部分结果

**问题**：MCP 返回 `error=true`，或 `analysis_status="partial"`。

**解决**：
1. `error_type=invalid_input`：检查 `depth`、`direction`、`max_depth` 和 `execution_mode` 是否在允许范围内。
2. `analysis_status=partial`：保留并使用 `impact`，查看 `diagnostics` 中的失败阶段，必要时改用 `depth="quick"` 或在依赖恢复后重试。
3. 入口级错误：记录 `diagnostics.trace_id`，运行 `memory-center inspect --workspace <workspace.yaml>`，必要时重启宿主 MCP 会话。

## 13. API Reference Quick Links / API 参考快速链接

- **Retrieval**: `memory_center.core.retrieval`
  - `hybrid_retrieve()`, `HybridRetrievalConfig`, `detect_query_intent()`
- **Benchmark**: `memory_center.core.benchmark`
  - `record_benchmark_trend()`, `get_benchmark_trends()`, `generate_benchmark_report()`
- **Backend**: `memory_center.core.backend`
  - `UnifiedBackendQuery`
- **Navigation**: `memory_center.core.navigation`
  - `DrillDownNavigator`
- **Audit**: `memory_center.core.audit`
  - `run_completion_audit()`, `record_design_decision()`, `generate_audit_report()`

详见各模块的 docstring 和 [ARCHITECTURE.md](./ARCHITECTURE.md) 附录 B。
