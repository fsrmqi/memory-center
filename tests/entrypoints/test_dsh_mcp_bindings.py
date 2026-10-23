"""DSH host binding detection and repair for the 5.0 Streamable HTTP contract.

Covers the regression that a DSH profile silently kept working against a command
path that no longer existed, and that nothing in Memory Center knew DSH profile
patch layers existed at all. Since 5.0 the binding is a URL to the long-running
service, so the stale cases are a retired 4.x stdio entry and a wrong URL.
"""

import json
from pathlib import Path

import pytest
import yaml

from memory_center.core.governance import instructions as instructions_module
from memory_center.core.governance.instructions import (
    DSH_PATCH_ENTRY_ID,
    _render_dsh_patch_entry,
    command_available,
    dsh_mcp_config_targets,
    inspect_agent_mcp_bindings,
    repair_agent_mcp_bindings,
    resolve_mcp_executable,
)
from memory_center.core.storage.workspace import WorkspaceStore
from tests.fixtures import copy_demo_workspace

DEAD_COMMAND = "/opt/homebrew/bin/memory-center-mcp"
EXPECTED_URL = "http://127.0.0.1:8765/mcp"
STALE_URL = "http://127.0.0.1:9999/mcp"

PATCH_WITHOUT_BINDING = """# Your patch layer for this dsh profile, applied after every bundle layer:
- id: ui-chat
  name: "@deepseek-ai/dsh-client-ui-chat"
  config:
    transcriptView: standard
- insert:
    - id: preset-research
      name: "@deepseek-ai/dsh-agent-preset"
      config:
        id: research
        plugins:
          - id: tool-bash
            name: "@deepseek-ai/dsh-tool-bash"
            disabled: !!js process.platform === 'win32'
"""

# 4.x 形态：stdio 代理 + --workspace，且命令路径已经不存在。
PATCH_WITH_STALE_STDIO_BINDING = PATCH_WITHOUT_BINDING + """- insert:
    - id: mcp-memory-center
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: memory-center
        transport: stdio
        command: "/opt/homebrew/bin/memory-center-mcp"
        args:
          [
            "--workspace",
            "/stale/.memory-center/workspace.yaml"
          ]
        env: {}
        toolCallTimeoutMs: 60000
        failOnStartupError: false
"""

# 5.0 形态但地址已经过期（例如换了端口）。
PATCH_WITH_STALE_URL_BINDING = PATCH_WITHOUT_BINDING + f"""- insert:
    - id: mcp-memory-center
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: memory-center
        transport: streamable-http
        url: "{STALE_URL}"
        toolCallTimeoutMs: 60000
        failOnStartupError: false
"""


@pytest.fixture(autouse=True)
def _default_service_url(monkeypatch):
    monkeypatch.delenv("MEMORY_CENTER_URL", raising=False)


def _make_dsh_profile(tmp_path: Path, monkeypatch, profile: str = "web", patch_text: str | None = None) -> Path:
    dsh_home = tmp_path / "dsh"
    profile_dir = dsh_home / "profiles" / profile
    profile_dir.mkdir(parents=True)
    (profile_dir / "package.json").write_text(json.dumps({"name": f"dsh-profile-{profile}"}), encoding="utf-8")
    if patch_text is not None:
        (profile_dir / "cordis.patch.yml").write_text(patch_text, encoding="utf-8")
    monkeypatch.setenv("DSH_HOME", str(dsh_home))
    return profile_dir / "cordis.patch.yml"


def _dsh_binding(result: dict, profile: str = "web") -> dict:
    return next(item for item in result["bindings"] if item["host"] == "dsh" and item["profile"] == profile)


class _PatchLoader(yaml.SafeLoader):
    """PyYAML needs a constructor for the `!!js` tag DSH patch layers carry."""


_PatchLoader.add_multi_constructor("tag:yaml.org,2002:js", lambda loader, suffix, node: f"<js:{suffix}>")


def _load_patch(path: Path):
    """Parse a DSH patch layer, tolerating `!!js` tags.

    Text assertions alone would accept a structurally broken file, so every
    repair test parses the result as YAML.
    """
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_PatchLoader)


def _patch_entries(path: Path) -> list[dict]:
    entries: list[dict] = []
    for item in _load_patch(path) or []:
        if isinstance(item, dict) and "insert" in item:
            entries.extend(item["insert"])
        else:
            entries.append(item)
    return entries


def _memory_center_entry(path: Path) -> dict:
    found = [entry for entry in _patch_entries(path) if entry.get("id") == DSH_PATCH_ENTRY_ID]
    assert len(found) == 1, found
    return found[0]


def _js_tags(value) -> list[str]:
    if isinstance(value, dict):
        return [tag for item in value.values() for tag in _js_tags(item)]
    if isinstance(value, list):
        return [tag for item in value for tag in _js_tags(item)]
    if isinstance(value, str) and value.startswith("<js:"):
        return [value]
    return []


def test_dsh_targets_are_empty_without_a_profiles_directory(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "absent"))
    assert dsh_mcp_config_targets() == []


def test_a_profile_without_a_manifest_is_not_a_target(tmp_path: Path, monkeypatch):
    profile_dir = tmp_path / "dsh" / "profiles" / "scratch"
    profile_dir.mkdir(parents=True)
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "dsh"))
    assert dsh_mcp_config_targets() == []


def test_inspect_flags_a_retired_stdio_binding(tmp_path: Path, monkeypatch):
    _make_dsh_profile(tmp_path, monkeypatch, patch_text=PATCH_WITH_STALE_STDIO_BINDING)
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    result = inspect_agent_mcp_bindings(store, workspace.parent.parent)

    binding = _dsh_binding(result)
    assert binding["ok"] is False
    assert binding["has_memory_center"] is True
    assert binding["transport"] == "stdio"
    assert binding["url"] == ""
    assert binding["expected_url"] == EXPECTED_URL
    assert binding["parse_error"] == ""
    assert binding in result["missing_or_stale"]


def test_inspect_flags_a_profile_without_any_binding(tmp_path: Path, monkeypatch):
    _make_dsh_profile(tmp_path, monkeypatch, profile="headless", patch_text=PATCH_WITHOUT_BINDING)
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    binding = _dsh_binding(inspect_agent_mcp_bindings(store, workspace.parent.parent), profile="headless")

    assert binding["ok"] is False
    assert binding["has_memory_center"] is False
    assert binding["transport"] == ""
    assert binding["url"] == ""


def test_inspect_flags_a_stale_service_url(tmp_path: Path, monkeypatch):
    _make_dsh_profile(tmp_path, monkeypatch, patch_text=PATCH_WITH_STALE_URL_BINDING)
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    binding = _dsh_binding(inspect_agent_mcp_bindings(store, workspace.parent.parent))

    assert binding["ok"] is False
    assert binding["has_memory_center"] is True
    assert binding["transport"] == "streamable-http"
    assert binding["url"] == STALE_URL


def test_repair_appends_the_binding_and_preserves_the_patch_layer(tmp_path: Path, monkeypatch):
    patch_path = _make_dsh_profile(tmp_path, monkeypatch, profile="headless", patch_text=PATCH_WITHOUT_BINDING)
    original_lines = patch_path.read_text(encoding="utf-8").splitlines()
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    result = repair_agent_mcp_bindings(store, workspace.parent.parent)

    text = patch_path.read_text(encoding="utf-8")
    assert text.splitlines()[: len(original_lines)] == original_lines
    assert text.count(f"- id: {DSH_PATCH_ENTRY_ID}") == 1
    assert "!!js process.platform === 'win32'" in text
    assert "- insert:" in text
    assert "--workspace" not in text
    assert "workspace.yaml" not in text
    assert _dsh_binding(result, profile="headless")["ok"] is True
    entry = _memory_center_entry(patch_path)
    assert entry["name"] == "@deepseek-ai/dsh-mcp-client"
    assert entry["config"]["serverName"] == "memory-center"
    assert entry["config"]["transport"] == "streamable-http"
    assert entry["config"]["url"] == EXPECTED_URL
    assert "command" not in entry["config"]
    assert _js_tags(_load_patch(patch_path)), "!!js 表达式必须仍可解析"


def test_repair_replaces_only_the_stale_entry_in_place(tmp_path: Path, monkeypatch):
    patch_path = _make_dsh_profile(tmp_path, monkeypatch, patch_text=PATCH_WITH_STALE_STDIO_BINDING)
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    result = repair_agent_mcp_bindings(store, workspace.parent.parent)

    text = patch_path.read_text(encoding="utf-8")
    assert text.count(f"- id: {DSH_PATCH_ENTRY_ID}") == 1
    assert DEAD_COMMAND not in text
    assert "/stale/.memory-center/workspace.yaml" not in text
    assert "--workspace" not in text
    assert "!!js process.platform === 'win32'" in text
    assert "- id: ui-chat" in text
    assert _dsh_binding(result)["ok"] is True
    entry = _memory_center_entry(patch_path)
    assert entry["config"]["transport"] == "streamable-http"
    assert entry["config"]["url"] == EXPECTED_URL
    assert _js_tags(_load_patch(patch_path)), "!!js 表达式必须仍可解析"


def test_repair_rewrites_only_the_url_of_a_stale_http_binding(tmp_path: Path, monkeypatch):
    patch_path = _make_dsh_profile(tmp_path, monkeypatch, patch_text=PATCH_WITH_STALE_URL_BINDING)
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    result = repair_agent_mcp_bindings(store, workspace.parent.parent)

    text = patch_path.read_text(encoding="utf-8")
    assert STALE_URL not in text
    assert text.count(f"- id: {DSH_PATCH_ENTRY_ID}") == 1
    assert "- id: ui-chat" in text
    assert _dsh_binding(result)["ok"] is True
    assert _memory_center_entry(patch_path)["config"]["url"] == EXPECTED_URL


def test_rendered_entry_is_valid_yaml_for_any_url(tmp_path: Path):
    for index, url in enumerate(
        (EXPECTED_URL, "https://memory.example.com/mcp", "http://10.0.0.5:8765/mcp")
    ):
        patch = tmp_path / f"patch-{index}.yml"
        patch.write_text(
            "- insert:\n" + "\n".join(_render_dsh_patch_entry({"type": "http", "url": url}, "    ")) + "\n",
            encoding="utf-8",
        )
        entry = _memory_center_entry(patch)
        assert entry["config"]["transport"] == "streamable-http", url
        assert entry["config"]["url"] == url


def test_repair_is_idempotent(tmp_path: Path, monkeypatch):
    patch_path = _make_dsh_profile(tmp_path, monkeypatch, patch_text=PATCH_WITHOUT_BINDING)
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    repair_agent_mcp_bindings(store, workspace.parent.parent)
    first = patch_path.read_text(encoding="utf-8")
    repair_agent_mcp_bindings(store, workspace.parent.parent)

    assert patch_path.read_text(encoding="utf-8") == first


def test_repair_creates_a_patch_layer_when_the_profile_has_none(tmp_path: Path, monkeypatch):
    patch_path = _make_dsh_profile(tmp_path, monkeypatch, profile="tui")
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    result = repair_agent_mcp_bindings(store, workspace.parent.parent)

    assert patch_path.is_file()
    assert patch_path.read_text(encoding="utf-8").startswith("- insert:")
    assert _dsh_binding(result, profile="tui")["ok"] is True


def test_inspect_flags_a_patch_layer_that_is_not_valid_yaml(tmp_path: Path, monkeypatch):
    """A present, correct-looking entry inside unparseable YAML is still not ok."""
    # Deliberately missing the comma between flow-sequence items.
    broken = (
        "- insert:\n"
        f"    - id: {DSH_PATCH_ENTRY_ID}\n"
        "      name: '@deepseek-ai/dsh-mcp-client'\n"
        "      config:\n"
        "        serverName: memory-center\n"
        "        transport: streamable-http\n"
        f'        url: "{EXPECTED_URL}"\n'
        "        args:\n"
        "          [\n"
        '            "a"\n'
        '            "b"\n'  # 缺少逗号 → 非法 flow sequence
        "          ]\n"
        "        toolCallTimeoutMs: 60000\n"
        "        failOnStartupError: false\n"
    )
    patch_path = _make_dsh_profile(tmp_path, monkeypatch, patch_text=broken)
    workspace = copy_demo_workspace(tmp_path)
    store = WorkspaceStore(workspace)

    binding = _dsh_binding(inspect_agent_mcp_bindings(store, workspace.parent.parent))

    assert binding["has_memory_center"] is True
    assert binding["parse_error"], "非法 YAML 必须被识别"
    assert binding["ok"] is False

    repair_agent_mcp_bindings(store, workspace.parent.parent)

    assert _memory_center_entry(patch_path)["config"]["url"] == EXPECTED_URL
    repaired = _dsh_binding(inspect_agent_mcp_bindings(store, workspace.parent.parent))
    assert repaired["parse_error"] == ""
    assert repaired["ok"] is True


def test_resolve_mcp_executable_falls_back_to_known_install_dirs(tmp_path: Path, monkeypatch):
    """The stdio adapter is still shipped for hosts that cannot speak HTTP."""
    bin_dir = tmp_path / "custom-bin"
    bin_dir.mkdir()
    fake = bin_dir / "memory-center-mcp"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.delenv("MEMORY_CENTER_BIN", raising=False)
    monkeypatch.setattr(instructions_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(instructions_module, "MCP_EXECUTABLE_DIRS", (str(bin_dir),))

    assert resolve_mcp_executable() == str(fake)
    assert command_available(str(fake)) is True
    assert command_available(str(bin_dir / "absent")) is False
    assert command_available("memory-center-not-installed-anywhere") is False
