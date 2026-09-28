from __future__ import annotations

import json
import os
import re
import shutil

import yaml
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
   - 查调用方：`mc_lookup(mode="chain", query="符号名", symbol="符号名", chain_direction="callers")`
   - 查被调用方：`mc_lookup(mode="chain", query="符号名", symbol="符号名", chain_direction="callees")`
   - 中文意图可放 `query` 或说明文本，但 `symbol` 必须是待验证的类/方法标识（硬锚），否则查询可能锚定到不相关符号。
   - chain/trace 返回的锚点与请求符号不符（`chain_anchor_validation.status != "matched"`）、`chain_summary` 为空、或 `claim_boundary.negative_claim_allowed=false` 时，视为查询失败或范围不足。立即回退到 `mc_lookup(mode="symbol")`、`mc_lookup(mode="code")` 或有界文件搜索；禁止把空结果当作"确认不存在调用方"。
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
- `change_review` 是变更审查默认入口；同一 fingerprint 命中缓存时直接复用，不再追加等价搜索。`eval_cochange` 是显式离线 walk-forward 评测，不得放入普通查询链路；只有 `calibration.eligible=true` 时才允许用户通过 CLI `--apply` 或 MCP `force=true` 写入哈希先验。

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


MCP_SERVER_NAME = "memory-center"
MCP_EXECUTABLE = "memory-center-mcp"
DSH_PATCH_ENTRY_ID = "mcp-memory-center"
DSH_PATCH_ENTRY_NAME = "@deepseek-ai/dsh-mcp-client"
# GUI-launched hosts (the macOS desktop app, IDE integrations) inherit only
# /usr/bin:/bin:/usr/sbin:/sbin, so `shutil.which` alone cannot decide whether
# the CLI exists. These are the documented install locations, in search order.
MCP_EXECUTABLE_DIRS = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin")


def mcp_executable_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    override = os.environ.get("MEMORY_CENTER_BIN", "").strip()
    if override:
        dirs.append(Path(override).expanduser().parent)
    dirs.extend(Path(raw).expanduser() for raw in MCP_EXECUTABLE_DIRS)
    return dirs


def resolve_mcp_executable() -> str:
    """Absolute path of the memory-center MCP entry point, or the bare name.

    Falls back to the documented install locations when PATH cannot see the CLI,
    mirroring the DSH plugin's PATH repair so generated bindings never point at a
    command the host cannot execute.
    """
    found = shutil.which(MCP_EXECUTABLE)
    if found:
        return found
    for directory in mcp_executable_search_dirs():
        candidate = directory / MCP_EXECUTABLE
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return MCP_EXECUTABLE


def command_available(command: str) -> bool:
    """True when `command` can actually be executed by the current process."""
    if not command:
        return False
    if os.sep in command:
        return os.path.isfile(command) and os.access(command, os.X_OK)
    return shutil.which(command) is not None


def _memory_center_mcp_server_config(workspace_file: Path) -> dict[str, object]:
    return {
        "type": "stdio",
        "command": resolve_mcp_executable(),
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
    servers[MCP_SERVER_NAME] = _memory_center_mcp_server_config(workspace_file)
    current["mcpServers"] = servers
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_mcp_configs(instruction_root: Path, workspace_file: Path) -> None:
    for target in _mcp_config_targets(instruction_root):
        _merge_mcp_server_config(target["path"], workspace_file)


def _mcp_config_targets(instruction_root: Path) -> list[dict[str, Any]]:
    return [
        {"host": "codex", "format": "json", "path": instruction_root / ".codex" / "mcp.json"},
        {"host": "cursor", "format": "json", "path": instruction_root / ".cursor" / "mcp.json"},
        {"host": "generic", "format": "json", "path": instruction_root / ".mcp.json"},
    ]


def dsh_home() -> Path:
    """DSH state root; `DSH_HOME` wins over the `~/.dsh` default."""
    override = (os.environ.get("DSH_HOME") or os.environ.get("MEMORY_CENTER_DSH_HOME") or "").strip()
    return Path(override).expanduser() if override else Path.home() / ".dsh"


def dsh_mcp_config_targets() -> list[dict[str, Any]]:
    """DSH profiles that declare a plugin manifest, as YAML patch targets.

    DSH keeps MCP servers in each profile's `cordis.patch.yml`, a patch layer
    that also carries `!!js` expressions and comments. It is therefore edited
    textually and never re-serialised. Every profile with a `package.json` is
    returned, including ones without a patch file yet, so a repair can create
    the binding. Hosts without a `profiles` directory yield no targets.
    """
    profiles = dsh_home() / "profiles"
    if not profiles.is_dir():
        return []
    targets: list[dict[str, Any]] = []
    for profile_dir in sorted(path for path in profiles.iterdir() if path.is_dir()):
        if not (profile_dir / "package.json").is_file():
            continue
        targets.append(
            {
                "host": "dsh",
                "format": "yaml-patch",
                "profile": profile_dir.name,
                "path": profile_dir / "cordis.patch.yml",
            }
        )
    return targets


def _dsh_patch_entry_span(lines: list[str], entry_id: str = DSH_PATCH_ENTRY_ID) -> tuple[int, int, str]:
    """Locate the `- id: <entry_id>` line and its block as (start, end, indent)."""
    pattern = re.compile(r"^(\s*)- id:\s*" + re.escape(entry_id) + r"\s*$")
    for index, line in enumerate(lines):
        match = pattern.match(line.rstrip())
        if not match:
            continue
        indent = match.group(1)
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            stripped = candidate.strip()
            if not stripped:
                end += 1
                continue
            current_indent = len(candidate) - len(candidate.lstrip(" "))
            if current_indent < len(indent) or (current_indent == len(indent) and stripped.startswith("- ")):
                break
            end += 1
        return index, end, indent
    return -1, -1, ""


def _render_dsh_patch_entry(server: dict[str, object], indent: str) -> list[str]:
    args = [str(value) for value in server["args"]]  # type: ignore[index]
    lines = [
        f"{indent}- id: {DSH_PATCH_ENTRY_ID}",
        f"{indent}  name: '{DSH_PATCH_ENTRY_NAME}'",
        f"{indent}  config:",
        f"{indent}    serverName: {MCP_SERVER_NAME}",
        f"{indent}    transport: stdio",
        f'{indent}    command: "{server["command"]}"',
        f"{indent}    args:",
        f"{indent}      [",
    ]
    lines.extend(
        f'{indent}        "{value}",' if index < len(args) - 1 else f'{indent}        "{value}"'
        for index, value in enumerate(args)
    )
    lines.extend(
        [
            f"{indent}      ]",
            f"{indent}    env: {{}}",
            f"{indent}    toolCallTimeoutMs: 60000",
            f"{indent}    failOnStartupError: false",
        ]
    )
    return lines


class _PatchLayerLoader(yaml.SafeLoader):
    """SafeLoader that tolerates the `!!js` tag DSH patch layers carry."""


_PatchLayerLoader.add_multi_constructor("tag:yaml.org,2002:js", lambda loader, suffix, node: None)


def _dsh_patch_parse_error(text: str) -> str:
    """Return why a patch layer is not loadable YAML, or an empty string.

    A text-spliced entry can be perfectly present yet sit in a file the loader
    would reject, so structural validity is reported separately from the
    binding's own fields.
    """
    try:
        yaml.load(text, Loader=_PatchLayerLoader)
    except yaml.YAMLError as exc:
        return f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
    return ""


def _read_dsh_patch_binding(config_path: Path, expected_args: list[str]) -> dict[str, Any]:
    """Extract binding facts from a DSH patch layer without re-serialising it."""
    facts: dict[str, Any] = {"present": False, "command": "", "workspace_bound": False, "parse_error": ""}
    if not config_path.is_file():
        return facts
    try:
        text = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return facts
    facts["parse_error"] = _dsh_patch_parse_error(text)
    lines = text.splitlines()
    start, end, _ = _dsh_patch_entry_span(lines)
    if start < 0:
        return facts
    block = "\n".join(lines[start:end])
    facts["present"] = True
    match = re.search(r'^\s*command:\s*"?([^"\n]+?)"?\s*$', block, re.MULTILINE)
    if match:
        facts["command"] = match.group(1).strip()
    facts["workspace_bound"] = len(expected_args) > 1 and expected_args[1] in block
    return facts


def _upsert_dsh_patch_binding(config_path: Path, server: dict[str, object]) -> None:
    """Insert or replace only the memory-center entry, preserving every other byte."""
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    lines = text.splitlines()
    start, end, indent = _dsh_patch_entry_span(lines)
    if start >= 0:
        replacement = _render_dsh_patch_entry(server, indent)
        next_lines = lines[:start] + replacement + lines[end:]
    else:
        block = ["- insert:"] + _render_dsh_patch_entry(server, "    ")
        next_lines = lines + ([""] if lines and lines[-1].strip() else []) + block
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("\n".join(next_lines).rstrip("\n") + "\n", encoding="utf-8")


def _inspect_json_binding(
    target: dict[str, Any],
    service_name: str,
    instruction_root: str,
    expected_server: dict[str, object],
    expected_args: list[str],
    expected_command: str,
) -> dict[str, Any]:
    config_path: Path = target["path"]
    server: dict[str, Any] = {}
    parse_error = ""
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                servers = loaded.get("mcpServers", {})
                if isinstance(servers, dict) and isinstance(servers.get(MCP_SERVER_NAME), dict):
                    server = servers[MCP_SERVER_NAME]
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            parse_error = str(exc)
    command = str(server.get("command", "")) if server else ""
    command_exists = command_available(command)
    ok = (
        bool(server)
        and command == expected_command
        and list(server.get("args", []) or []) == expected_args
        and int(server.get("startup_timeout_sec", 0) or 0) == int(expected_server["startup_timeout_sec"])  # type: ignore[arg-type]
        and command_exists
    )
    return {
        "host": target["host"],
        "format": "json",
        "root": instruction_root,
        "service": service_name,
        "config_path": str(config_path),
        "exists": config_path.exists(),
        "has_memory_center": bool(server),
        "command": command,
        "args": list(server.get("args", []) or []) if server else [],
        "expected_command": expected_command,
        "expected_args": expected_args,
        "startup_timeout_sec": int(server.get("startup_timeout_sec", 0) or 0),
        "expected_startup_timeout_sec": int(expected_server["startup_timeout_sec"]),  # type: ignore[arg-type]
        "command_exists": command_exists,
        "parse_error": parse_error,
        "ok": ok,
    }


def _inspect_dsh_binding(target: dict[str, Any], expected_args: list[str], expected_command: str) -> dict[str, Any]:
    config_path: Path = target["path"]
    facts = _read_dsh_patch_binding(config_path, expected_args)
    command = str(facts["command"])
    command_exists = command_available(command)
    ok = (
        bool(facts["present"])
        and command == expected_command
        and bool(facts["workspace_bound"])
        and command_exists
        and not facts["parse_error"]
    )
    return {
        "host": target["host"],
        "format": "yaml-patch",
        "profile": target["profile"],
        "root": str(dsh_home()),
        "service": "",
        "config_path": str(config_path),
        "exists": config_path.exists(),
        "has_memory_center": bool(facts["present"]),
        "command": command,
        "args": list(expected_args) if facts["workspace_bound"] else [],
        "expected_command": expected_command,
        "expected_args": expected_args,
        "startup_timeout_sec": 0,
        "expected_startup_timeout_sec": 0,
        "command_exists": command_exists,
        "workspace_bound": bool(facts["workspace_bound"]),
        "parse_error": str(facts["parse_error"]),
        "ok": ok,
    }


def inspect_agent_mcp_bindings(store: WorkspaceStore, workspace_root: str | Path) -> dict[str, Any]:
    """Inspect Memory Center MCP bindings in the workspace, service roots and DSH profiles."""
    root = Path(workspace_root).expanduser().resolve()
    workspace_file = store.workspace_file.resolve()
    expected_server = _memory_center_mcp_server_config(workspace_file)
    expected_args = [str(value) for value in expected_server["args"]]  # type: ignore[index]
    expected_command = str(expected_server["command"])
    bindings: list[dict[str, Any]] = []
    for instruction_root, service_name in _instruction_roots(store, root):
        for target in _mcp_config_targets(instruction_root):
            bindings.append(
                _inspect_json_binding(target, service_name, str(instruction_root), expected_server, expected_args, expected_command)
            )
    for target in dsh_mcp_config_targets():
        bindings.append(_inspect_dsh_binding(target, expected_args, expected_command))
    missing = [item for item in bindings if not item["ok"]]
    return {
        "ok": not missing,
        "workspace_file": str(workspace_file),
        "command_available": command_available(expected_command),
        "expected_server": expected_server,
        "dsh_home": str(dsh_home()),
        "bindings": bindings,
        "missing_or_stale": missing,
    }


def repair_agent_mcp_bindings(store: WorkspaceStore, workspace_root: str | Path) -> dict[str, Any]:
    """Write or refresh Memory Center MCP bindings for all known agent roots."""
    root = Path(workspace_root).expanduser().resolve()
    write_agent_instructions(store, root)
    server = _memory_center_mcp_server_config(store.workspace_file.resolve())
    expected_args = [str(value) for value in server["args"]]  # type: ignore[index]
    expected_command = str(server["command"])
    for target in dsh_mcp_config_targets():
        facts = _read_dsh_patch_binding(target["path"], expected_args)
        current = (
            bool(facts["present"])
            and str(facts["command"]) == expected_command
            and bool(facts["workspace_bound"])
            and command_available(expected_command)
            and not facts["parse_error"]
        )
        if not current:
            _upsert_dsh_patch_binding(target["path"], server)
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
