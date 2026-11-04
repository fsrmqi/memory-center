"""Shared pytest fixtures for Memory Center tests.

Provides isolated temporary workspace fixtures that copy the demo workspace
into tmp_path and rewrite the root path. This prevents tests from polluting
the repository demo workspace.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

_PROTECTED_DEMO_MEMORY = Path(__file__).resolve().parents[1] / "examples" / "spring-cloud-demo" / ".memory-center"


def _protected_demo_snapshot() -> dict[str, str]:
    """Hash every generated-demo file so tests cannot silently mutate fixtures.

    graph/ 目录（graph.db + -shm/-wal）是运行时 SQLite 库：读连接正常关闭时的
    WAL checkpoint 会改变 graph.db 本体字节而不改变任何语义数据，单测串行运行
    时必然触发哈希漂移——不属于 fixture 篡改，排除在快照外。工件与 memory
    内容仍在保护内。
    """
    if not _PROTECTED_DEMO_MEMORY.exists():
        return {}
    return {
        str(path.relative_to(_PROTECTED_DEMO_MEMORY)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(_PROTECTED_DEMO_MEMORY.rglob("*"))
        if path.is_file() and "graph" not in path.relative_to(_PROTECTED_DEMO_MEMORY).parts
    }


@pytest.fixture(autouse=True)
def protected_demo_workspace_unchanged():
    """Fail at the mutating test instead of discovering fixture pollution later."""
    before = _protected_demo_snapshot()
    yield
    after = _protected_demo_snapshot()
    assert after == before, "测试不得修改 examples/spring-cloud-demo/.memory-center；请使用 tmp_path 副本。"


@pytest.fixture(autouse=True)
def isolated_dsh_home(tmp_path_factory, monkeypatch):
    """Keep host-integration writes inside the test sandbox.

    MCP binding repair also covers DSH profile patch layers under ``$DSH_HOME``
    (default ``~/.dsh``). Tests run against throwaway workspaces, so without
    this isolation a ``runtime-audit --fix`` test would rewrite the developer's
    real DSH profiles with a pytest temp path.
    """
    monkeypatch.setenv("DSH_HOME", str(tmp_path_factory.mktemp("dsh-home")))


@pytest.fixture(autouse=True)
def isolated_session_id_file(tmp_path_factory, monkeypatch):
    """Hook 的 session-id 交接文件默认写在 ``~/.cache/memory-center``。

    它必须可注入：否则每个跑 hook 的测试都会写开发者真实 home，在没有权限的
    沙箱里更是直接 PermissionError。
    """
    monkeypatch.setenv(
        "MEMORY_CENTER_SESSION_ID_FILE",
        str(tmp_path_factory.mktemp("session-id") / "session-id"),
    )


@pytest.fixture()
def demo_workspace(tmp_path: Path) -> Path:
    """Copy spring-cloud-demo into tmp_path, rewrite workspace.yaml root.

    Returns the workspace.yaml Path. Does NOT reindex.
    Use ``demo_workspace_indexed`` if the test needs a fresh index.
    """
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [
        f"root: {target.as_posix()}" if line.startswith("root:") else line
        for line in lines
    ]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return workspace


@pytest.fixture()
def demo_workspace_indexed(tmp_path: Path) -> Path:
    """Same as ``demo_workspace`` but also runs reindex.

    Returns the workspace.yaml Path.
    """
    workspace = _copy_and_index(tmp_path)
    return workspace


@pytest.fixture()
def demo_workspace_str(tmp_path: Path) -> str:
    """Same as ``demo_workspace_indexed`` but returns a str path.

    Many orchestrator functions accept str workspace paths.
    """
    workspace = _copy_and_index(tmp_path)
    return str(workspace)


def _copy_and_index(tmp_path: Path) -> Path:
    source = Path("examples/spring-cloud-demo")
    target = tmp_path / "demo"
    shutil.copytree(source, target)
    workspace = target / ".memory-center" / "workspace.yaml"
    lines = workspace.read_text(encoding="utf-8").splitlines()
    lines = [
        f"root: {target.as_posix()}" if line.startswith("root:") else line
        for line in lines
    ]
    workspace.write_text("\n".join(lines) + "\n", encoding="utf-8")
    from memory_center.core.indexing.reindex import reindex_workspace
    from memory_center.core.storage.workspace import WorkspaceStore
    from memory_center.core.workspace.config import load_workspace_config

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)
    return workspace
