from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from memory_center.core.storage.workspace import WorkspaceStore
from memory_center.core.workspace.config import load_workspace_config

AGENT_PROTOCOL_TEMPLATE = """# Memory Center Agent Protocol

本 workspace 使用 Memory Center 作为 AI 编程助手的项目记忆 MCP 服务。

{workspace_binding_note}

## MCP 工具速查

| 工具 | 用途 |
|------|------|
| `mc_start` | 开始任务：sniff 上下文 + 同步任务空间 + 启动 session |
| `mc_lookup` | 统一查询（mode 控制策略：auto/symbol/code/query/trace/chain/context/contracts/ref） |
| `mc_analyze` | 变更影响分析（depth: quick/standard/full） |
| `mc_sync` | 同步上下文到任务空间（intent=sniff-sync, session_id=case-sync） |
| `mc_resume` | 恢复任务：汇总上下文、下一步动作、未解决问题 |
| `mc_handoff` | 构建跨模型/session 的交接包 |
| `mc_close` | 关闭任务：结束 session + 同步 + 记录案例 |
| `mc_admin` | 管理操作（action 子命令：status, session_log, write_judge, write_plan 等） |

## 必须遵守

1. 任何编码/架构/调试任务开始时，先调用 `mc_start(intent=...)` 获取 session_id。
2. 如果用户要"找类 / 找方法 / 找 Feign / 找 Topic / 找配置项 / 找调用链"，用 `mc_lookup`：
   - 找符号：`mc_lookup(query="类名或方法名", mode="symbol")`
   - 搜代码：`mc_lookup(query="关键词", mode="code")`
   - 跨服务追踪：`mc_lookup(query="入口类", mode="trace", entry="类名或Feign名")`
   - 查调用方：`mc_lookup(query="符号名", mode="chain", symbol="符号名", chain_direction="callers")`
   - 查被调用方：`mc_lookup(query="符号名", mode="chain", symbol="符号名", chain_direction="callees")`
   - 不确定用哪个：`mc_lookup(query="...", mode="auto")` 让系统自动路由
3. 在写入任何记忆前，先调用 `mc_admin(action="write_judge", text=..., source=..., intent=...)`；需要可执行步骤时，再调用 `mc_admin(action="write_plan", ...)`。
4. 如果任务会持续一段时间，在 `mc_start` 之后用 `mc_sync(intent=..., auto_sync_mode="balanced")` 同步上下文到任务空间。
5. 对于长任务，`mc_start` 已自动启动 session；关键步骤用 `mc_admin(action="session_log", session_id=..., event_type=..., payload=...)` 记录。
6. 修改 Feign、DTO、MQ Message、公共 API 前，调用 `mc_analyze(target=..., depth="full", contract_file=..., change_type=...)`。
7. 修改任何核心文件前，调用 `mc_analyze(target=..., depth="standard", projects=[...], files=[...])` 检查规则。
8. 任务结束后，调用 `mc_close(session_id=..., outcome=..., record_case=True)` 结束并沉淀案例。
9. 完成验证后，`mc_close` 已自动包含 record_case，无需额外操作。
10. `context.md`、`requirement.md`、`design.md`、`plan.md`、`test-plan.md`、`change-log.md`、`current-summary.md` 属于追加保护工件，只允许尾部追加或去重，不允许整篇覆盖。
11. 首轮工具列表没有 `mc_*` 不等于 Memory Center 不可用。先执行延迟工具发现并查找 `mcp__memory_center__mc_freshness`；发现后调用一次 `mc_freshness(scope="workspace")` 完成端到端验证。
12. 延迟发现后仍缺少工具时，先检查宿主绑定：Codex 使用 `codex mcp get memory-center`，其他宿主检查对应 MCP 配置。若配置存在且 enabled，状态应表达为“Memory Center 已配置，当前宿主工具快照尚未刷新”，提示刷新或新建会话，禁止表述为“未加载”或“不可用”。
13. 只有绑定不存在、命令不存在，或 MCP initialize / 轻量调用明确失败时，才说明：`Memory Center MCP 当前不可用，以下基于本地代码搜索完成。` 若当前目录是子项目，先运行 `memory-center runtime-audit --workspace {workspace_config_path} --fix` 修复绑定。
14. 当 `mc_lookup` 的 `agent_next_steps` 返回 `rebuild_vector_ann` 时，必须依次调用 `mc_admin(action="vector_ann_rebuild")` 和 `mc_admin(action="vector_ann_tune")`，再重试原查询；不得对大型向量库使用 Python 全量扫描。
15. 对概念型、中文需求与代码混合查询，优先调用 `mc_admin(action="advanced_query", text="原查询")`，它会启用 ANN 和有界 Cross-Encoder 重排；重排器只使用当前 MCP 进程已预热模型，返回 `reranker_not_prewarmed` 时保留基础排序，不得在请求链路加载或下载模型。只有用户明确同意时，管理员才可在当前 MCP 进程调用 `mc_admin(action="retrieval_reranker_prewarm")`；普通符号查找仍使用 `mc_lookup`。
16. `mc_admin(action="retrieval_model_profile", text="multilingual", force=true)` 会选择 BGE-M3 档案，但随后必须显式完整 reindex；Agent 不得自行切换模型档案或触发全量 reindex，除非用户明确要求。
17. 定期调用 `mc_admin(action="eval_retrieval_replay")` 检查带 evidence 的人工验证样本；只有返回 `ready` 才可使用 `force=true` 应用融合权重提案。
18. 代码审查、提交前检查或用户要求“看下变更影响”时，优先调用 `mc_admin(action="change_review", scope="all", view="minimal")`。它会定向刷新相关文件并一次返回加权影响链、契约风险、测试缺口和验证 Action；不要手工重复串联全局搜索。
19. 遵守 `invocation_budget`：默认按 `minimal -> standard -> deep` 渐进展开；只有 `knowledge_state` 证据不足、结果被截断或用户明确要求时才升级。达到 `stop_condition`、预算耗尽或出现 `user_confirmation_required` 后必须停止工具调用。
20. 相同 `fingerprint` 和 generation 的审查结果视为等价证据；短时间内不得重复调用 `lookup/analyze/change_review/provider` 获取同一范围。需要重试时必须先有 generation 变化、范围变化或新的验证证据。

## 推荐任务链路

1. `mc_start(intent="任务描述")` — 获取 session_id、上下文、风险等级
2. 查找代码：`mc_lookup(query="...", mode="symbol/code/trace/chain")` 按需选 mode
3. `mc_admin(action="write_judge", text="意图", source="sniff_intent", intent="意图")`
4. `mc_admin(action="write_plan", text="意图", source="sniff_intent", intent="意图")`
5. `mc_sync(intent="任务描述", auto_sync_mode="balanced")` — 同步上下文
6. 开发过程中：`mc_admin(action="session_log", session_id="...", event_type="分析", payload="{...}")`
7. 变更前：`mc_analyze(target="文件或符号", depth="standard/full")`
8. 提交或审查前：`mc_admin(action="change_review", scope="all", view="minimal")`
9. 任务完成：`mc_close(session_id="...", outcome="完成描述", record_case=True)`

## 重要说明

- `mc_start` 默认只读 sniff + 自动同步建议 + 启动 session，返回 session_id 供后续使用。
- "找类 / 找方法 / 找 Feign / 找 Topic / 找配置项 / 找调用链" 属于 Memory Center 的强项，优先用 `mc_lookup`，不要一上来就全仓库 grep。
- `mc_admin(action="write_judge")` 负责决定信息应进入 L0 session、L1 case、L2 task space 还是 L3 workspace profile。
- `mc_admin(action="write_plan")` 不直接写入，而是返回执行计划。
- `mc_close` 包含：结束 session + 同步案例到任务空间 + 记录到 cross-service memory，一步到位。
- L3 级别信息优先进入 `workspace_profile`、`team_rules`、`architecture_invariants`、`active_migration_policy` 等核心记忆块。
- 若首轮看不到 `mc_*` 工具，先做延迟工具发现；配置已启用但工具仍不可见时刷新宿主会话。只有绑定缺失时才运行 `memory-center runtime-audit --workspace {workspace_config_path} --fix`，避免把工具快照延迟误诊为服务不可用。
- `vector_ann_status`、`vector_ann_rebuild`、`vector_ann_tune`、`advanced_query`、`retrieval_reranker_status`、`retrieval_reranker_prewarm`、`retrieval_model_profile` 和 `eval_retrieval_replay` 都通过 `mc_admin(action=...)` 调用；先遵守返回的 stop_condition 和 next_action，再进入宽泛搜索。
- `change_review` 是变更审查默认入口；同一 fingerprint 命中缓存时直接复用，不再追加等价搜索。`eval_cochange` 是显式离线评测，不得放入普通查询链路。

## Spring Cloud 重点风险

- Feign 契约变更必须做调用方影响分析。
- MQ 消费必须保证幂等、重试、死信或补偿。
- 公共 DTO 不允许破坏性删除字段或改变字段语义。
- ES 写入必须确认 write index，并处理 bulk item 级失败。
- 核心链路日志必须包含 chainId、siteCode、uid、业务主键和阶段码。
- 跨时间分表/索引迁移必须支持重复执行和失败补偿。
"""


def write_agent_instructions(store: WorkspaceStore, workspace_root: str | Path) -> None:
    root = Path(workspace_root).expanduser().resolve()
    workspace_file = store.workspace_file
    for instruction_root, service_name in _instruction_roots(store, root):
        content = _render_agent_protocol(
            workspace_file=workspace_file,
            instruction_root=instruction_root,
            workspace_root=root,
            service_name=service_name,
        )
        targets = [
            instruction_root / "AGENTS.md",
            instruction_root / "CLAUDE.md",
            instruction_root / "GEMINI.md",
            instruction_root / ".github" / "copilot-instructions.md",
            instruction_root / ".cursor" / "rules" / "memory-center.mdc",
        ]
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            block = managed_block(content)
            if "<!-- memory-center:start -->" in current and "<!-- memory-center:end -->" in current:
                start = current.index("<!-- memory-center:start -->")
                end = current.index("<!-- memory-center:end -->") + len("<!-- memory-center:end -->")
                next_text = current[:start] + block + current[end:]
            else:
                next_text = (current.rstrip() + "\n\n" if current.strip() else "") + block
            target.write_text(next_text, encoding="utf-8")
        _write_mcp_configs(instruction_root, workspace_file)


def managed_block(content: str) -> str:
    return f"<!-- memory-center:start -->\n{content.rstrip()}\n<!-- memory-center:end -->\n"


def _memory_center_mcp_server_config(workspace_file: Path) -> dict[str, object]:
    return {
        "type": "stdio",
        "command": shutil.which("memory-center-mcp") or "memory-center-mcp",
        "args": ["--workspace", str(workspace_file.resolve())],
        "startup_timeout_sec": 30,
    }


def _merge_mcp_server_config(config_path: Path, workspace_file: Path) -> None:
    current: dict[str, object] = {}
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            current = {}
    servers = current.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers["memory-center"] = _memory_center_mcp_server_config(workspace_file)
    current["mcpServers"] = servers
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_mcp_configs(instruction_root: Path, workspace_file: Path) -> None:
    for target in _mcp_config_targets(instruction_root):
        _merge_mcp_server_config(target["path"], workspace_file)


def _mcp_config_targets(instruction_root: Path) -> list[dict[str, Any]]:
    return [
        {"host": "codex", "path": instruction_root / ".codex" / "mcp.json"},
        {"host": "cursor", "path": instruction_root / ".cursor" / "mcp.json"},
        {"host": "generic", "path": instruction_root / ".mcp.json"},
    ]


def inspect_agent_mcp_bindings(store: WorkspaceStore, workspace_root: str | Path) -> dict[str, Any]:
    """Inspect generated MCP bindings in the aggregate root and service roots."""
    root = Path(workspace_root).expanduser().resolve()
    workspace_file = store.workspace_file.resolve()
    expected_server = _memory_center_mcp_server_config(workspace_file)
    bindings: list[dict[str, Any]] = []
    for instruction_root, service_name in _instruction_roots(store, root):
        for target in _mcp_config_targets(instruction_root):
            config_path = target["path"]
            server: dict[str, Any] = {}
            parse_error = ""
            if config_path.exists():
                try:
                    loaded = json.loads(config_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        servers = loaded.get("mcpServers", {})
                        if isinstance(servers, dict) and isinstance(servers.get("memory-center"), dict):
                            server = servers["memory-center"]
                except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                    parse_error = str(exc)
            expected_args = expected_server["args"]
            ok = (
                bool(server)
                and str(server.get("command", "")) == str(expected_server["command"])
                and list(server.get("args", []) or []) == expected_args
                and int(server.get("startup_timeout_sec", 0) or 0) == int(expected_server["startup_timeout_sec"])
            )
            bindings.append(
                {
                    "host": target["host"],
                    "root": str(instruction_root),
                    "service": service_name,
                    "config_path": str(config_path),
                    "exists": config_path.exists(),
                    "has_memory_center": bool(server),
                    "command": server.get("command", "") if server else "",
                    "args": server.get("args", []) if server else [],
                    "expected_command": expected_server["command"],
                    "expected_args": expected_args,
                    "startup_timeout_sec": int(server.get("startup_timeout_sec", 0) or 0),
                    "expected_startup_timeout_sec": expected_server["startup_timeout_sec"],
                    "parse_error": parse_error,
                    "ok": ok,
                }
            )
    missing = [item for item in bindings if not item["ok"]]
    return {
        "ok": not missing,
        "workspace_file": str(workspace_file),
        "command_available": bool(shutil.which("memory-center-mcp")),
        "expected_server": expected_server,
        "bindings": bindings,
        "missing_or_stale": missing,
    }


def repair_agent_mcp_bindings(store: WorkspaceStore, workspace_root: str | Path) -> dict[str, Any]:
    """Write or refresh Memory Center MCP bindings for all known agent roots."""
    root = Path(workspace_root).expanduser().resolve()
    write_agent_instructions(store, root)
    return inspect_agent_mcp_bindings(store, root)


def _instruction_roots(store: WorkspaceStore, workspace_root: Path) -> list[tuple[Path, str]]:
    roots: list[tuple[Path, str]] = [(workspace_root, "")]
    seen = {str(workspace_root)}
    try:
        config = load_workspace_config(store.workspace_file)
    except Exception:
        return roots
    for service in config.services:
        service_root = config.resolve_service_path(service)
        if not service_root.exists() or not service_root.is_dir():
            continue
        key = str(service_root)
        if key in seen:
            continue
        seen.add(key)
        roots.append((service_root, service.name))
    return roots


def _render_agent_protocol(
    workspace_file: Path,
    instruction_root: Path,
    workspace_root: Path,
    service_name: str = "",
) -> str:
    workspace_path = str(workspace_file)
    if instruction_root == workspace_root:
        binding_note = (
            f"- 默认 workspace 配置文件：`{workspace_path}`\n"
            f"- 如果你当前在某个子项目目录中执行任务，也要继续复用这个上层 workspace，而不是假设当前目录必须有独立的 `.memory-center/workspace.yaml`。\n"
            f"- Default workspace file: `{workspace_path}`. Subprojects under this workspace should reuse it instead of assuming each repo needs its own local `.memory-center/workspace.yaml`."
        )
    else:
        binding_note = (
            f"- 当前目录是聚合 workspace 下的子项目：`{service_name or instruction_root.name}`。\n"
            f"- 即使当前目录没有自己的 `.memory-center/workspace.yaml`，也要复用上层 workspace：`{workspace_path}`。\n"
            f"- Current directory is a service root under the aggregate workspace. Reuse `{workspace_path}` even when this repo does not contain its own local `.memory-center/workspace.yaml`."
        )
    return (
        AGENT_PROTOCOL_TEMPLATE
        .replace("{workspace_binding_note}", binding_note)
        .replace("{workspace_config_path}", workspace_path)
    )
