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

AGENT_PROTOCOL_TEMPLATE = """# Memory Center 5.0 Agent Protocol

本仓库采用独立常驻 Memory Center 5.0 服务；管理页和统一 MCP 共用同一应用层。不要绑定旧 workspace 文件或启动独立 Wiki MCP。当前参数以服务实际 tool schema 为准，参考 `docs/V5_PLATFORM_GUIDE.md`。

{workspace_binding_note}

1. 开始工程交付前先 `mc_workspaces()` 查看已登记项目，只选择与当前源码目录明确匹配的 `workspace_id`。尚未登记时使用本地 GitNexus 和源码验证，说明服务已配置但本项目未登记；不得借用其它业务项目的会话或记忆。项目接入通过管理页处理。
2. 已匹配的交付任务调用 `mc_start(workspace_id=..., intent=...)`，保存返回的 `id` 作为 session_id；只读了解不自动创建/关闭会话。
3. 工程查询用 `mc_lookup(workspace_id=..., query=..., mode=...)`，mode 为 hybrid/symbol/callers/callees/context。调用关系结果须核对覆盖、新鲜度与来源，空结果不是不存在的证明。
4. 修改前先做本仓库 GitNexus impact；已登记且需要服务影响证据时调用 `mc_analyze(workspace_id=..., target=...)`。不要调用旧 `mc_admin`、`mc_sync`、旧深度/文件参数或旧 ANN 指令。
5. 长任务用 `mc_resume(session_id=...)` 恢复；完成明确交付后 `mc_close(session_id=..., outcome=...)`。不要认领或关闭其他项目的会话。
6. 长期知识由同一服务的 `assistant_knowledge(action="brief"|"search"|"read"|"analyze", ...)` 查询。事实和验证证据优先；冲突应指出 Wiki 可能过期。
7. 知识晋升/资料归档、Skill 创建/发布均先 `confirm=false` 预览，展示后等待对应写入的明确确认。Skill 来源、工件哈希和验证引用应保留；引用不等于自动证明外部内容真实。
8. 管理页“知识治理”和“Skill 管理”可维护受管 Wiki 与候选/发布目录；原 Wiki 只读来源和受管知识分别维护。`assistant_admin(action="scan")` 只报告垃圾，不删除。
9. 普通项目记忆写入用 `mc_memory_write(workspace_id=..., content=..., confirmed=...)`，区分待确认与已确认记录。不要将会话、源码、日志、私有路径或未验证推断直接晋升为长期 Wiki。
10. 宿主配置变更后刷新会话以重新发现工具；已配置但快照未刷新时不要误称服务不可用。MCP 地址默认 `http://127.0.0.1:8765/mcp`；stdio 代理为 `memory-center-mcp`，不带旧 `--workspace`。

English: Use one Memory Center 5.0 service and select only a registered workspace matching the current repository. Never reuse an unrelated project's session. Wiki and Skill governance use the integrated assistant tools; preview and explicit confirmation precede governed writes. Old workspace-bound MCP contracts are retired."""


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


MCP_DEFAULT_URL = "http://127.0.0.1:8765/mcp"


def mcp_service_url() -> str:
    """Unified MCP endpoint; `MEMORY_CENTER_URL` overrides the local default."""
    override = (os.environ.get("MEMORY_CENTER_URL") or "").strip()
    return override or MCP_DEFAULT_URL


def _memory_center_mcp_server_config(workspace_file: Path | None = None) -> dict[str, object]:
    """5.0 host binding: Streamable HTTP straight at the long-running service.

    The 4.x stdio binding (`memory-center-mcp --workspace <file>`) is retired, so
    `workspace_file` is accepted only for call-site compatibility and ignored.
    """
    return {"type": "http", "url": mcp_service_url()}


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
    return [
        f"{indent}- id: {DSH_PATCH_ENTRY_ID}",
        f"{indent}  name: '{DSH_PATCH_ENTRY_NAME}'",
        f"{indent}  config:",
        f"{indent}    serverName: {MCP_SERVER_NAME}",
        f"{indent}    transport: streamable-http",
        f'{indent}    url: "{server["url"]}"',
        f"{indent}    toolCallTimeoutMs: 60000",
        f"{indent}    failOnStartupError: false",
    ]


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


def _read_dsh_patch_binding(config_path: Path) -> dict[str, Any]:
    """Extract binding facts from a DSH patch layer without re-serialising it."""
    facts: dict[str, Any] = {"present": False, "transport": "", "url": "", "parse_error": ""}
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
    transport = re.search(r'^\s*transport:\s*"?([^"\n]+?)"?\s*$', block, re.MULTILINE)
    if transport:
        facts["transport"] = transport.group(1).strip()
    url = re.search(r'^\s*url:\s*"?([^"\n]+?)"?\s*$', block, re.MULTILINE)
    if url:
        facts["url"] = url.group(1).strip()
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
    expected_url: str,
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
    transport = str(server.get("type", "")) if server else ""
    url = str(server.get("url", "")) if server else ""
    ok = bool(server) and not parse_error and url == expected_url and transport in ("", "http")
    return {
        "host": target["host"],
        "format": "json",
        "root": instruction_root,
        "service": service_name,
        "config_path": str(config_path),
        "exists": config_path.exists(),
        "has_memory_center": bool(server),
        "transport": transport,
        "url": url,
        "expected_url": expected_url,
        "parse_error": parse_error,
        "ok": ok,
    }


def _inspect_dsh_binding(target: dict[str, Any], expected_url: str) -> dict[str, Any]:
    config_path: Path = target["path"]
    facts = _read_dsh_patch_binding(config_path)
    transport = str(facts["transport"])
    url = str(facts["url"])
    ok = (
        bool(facts["present"])
        and transport == "streamable-http"
        and url == expected_url
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
        "transport": transport,
        "url": url,
        "expected_url": expected_url,
        "parse_error": str(facts["parse_error"]),
        "ok": ok,
    }


def inspect_agent_mcp_bindings(store: WorkspaceStore, workspace_root: str | Path) -> dict[str, Any]:
    """Inspect Memory Center MCP bindings in the workspace, service roots and DSH profiles."""
    root = Path(workspace_root).expanduser().resolve()
    workspace_file = store.workspace_file.resolve()
    expected_server = _memory_center_mcp_server_config()
    expected_url = str(expected_server["url"])
    bindings: list[dict[str, Any]] = []
    for instruction_root, service_name in _instruction_roots(store, root):
        for target in _mcp_config_targets(instruction_root):
            bindings.append(_inspect_json_binding(target, service_name, str(instruction_root), expected_url))
    for target in dsh_mcp_config_targets():
        bindings.append(_inspect_dsh_binding(target, expected_url))
    missing = [item for item in bindings if not item["ok"]]
    return {
        "ok": not missing,
        "workspace_file": str(workspace_file),
        "mcp_url": expected_url,
        "expected_server": expected_server,
        "dsh_home": str(dsh_home()),
        "bindings": bindings,
        "missing_or_stale": missing,
    }


def repair_agent_mcp_bindings(store: WorkspaceStore, workspace_root: str | Path) -> dict[str, Any]:
    """Write or refresh Memory Center MCP bindings for all known agent roots."""
    root = Path(workspace_root).expanduser().resolve()
    write_agent_instructions(store, root)
    server = _memory_center_mcp_server_config()
    expected_url = str(server["url"])
    for target in dsh_mcp_config_targets():
        facts = _read_dsh_patch_binding(target["path"])
        current = (
            bool(facts["present"])
            and str(facts["transport"]) == "streamable-http"
            and str(facts["url"]) == expected_url
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
            f"- 源码根目录：`{workspace_root}`；本文件覆盖该目录及其子项目。"
            f"用 `mc_workspaces()` 选择覆盖该目录的已登记 workspace，5.0 不读取旧 workspace 文件 `{workspace_path}`。\n"
            f"- Source root: `{workspace_root}`. Pick the registered workspace covering it with `mc_workspaces()`; "
            f"5.0 never reads the legacy workspace file `{workspace_path}`."
        )
    else:
        binding_note = (
            f"- 当前目录是聚合工作区下的子项目：`{service_name or instruction_root.name}`，源码根目录 `{workspace_root}`。\n"
            f"- 用 `mc_workspaces()` 选择覆盖该目录的已登记 workspace；5.0 不读取旧 workspace 文件 `{workspace_path}`，也不要为子项目单独绑定服务。\n"
            f"- Current directory is a service root under the aggregate workspace "
            f"(`{service_name or instruction_root.name}`). Pick the registered workspace with `mc_workspaces()`; "
            f"5.0 never reads the legacy workspace file `{workspace_path}`."
        )
    return (
        AGENT_PROTOCOL_TEMPLATE
        .replace("{workspace_binding_note}", binding_note)
        .replace("{workspace_config_path}", workspace_path)
    )


