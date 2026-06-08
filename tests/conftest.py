"""Shared pytest fixtures for Memory Center tests.

Provides isolated temporary workspace fixtures that copy the demo workspace
into tmp_path and rewrite the root path. This prevents tests from polluting
the repository demo workspace.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest


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
    from memory_center.core.config import load_workspace_config
    from memory_center.core.indexer import reindex_workspace
    from memory_center.core.store import WorkspaceStore

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)
    return workspace
