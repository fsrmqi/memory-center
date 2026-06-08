"""Unified workspace test fixtures for Memory Center tests.

All write-type tests MUST use these helpers to copy the demo workspace into
tmp_path before touching graph, memory, index, benchmark, or artifact files.
This prevents test runs from polluting the repository demo workspace.

Usage:
    from tests.fixtures import copy_demo_workspace, setup_demo_workspace

    # Lightweight: copy + rewrite root, no reindex
    ws = copy_demo_workspace(tmp_path)

    # Full setup: copy + rewrite root + reindex
    ws = setup_demo_workspace(tmp_path)
"""
from __future__ import annotations

import shutil
from pathlib import Path


def copy_demo_workspace(tmp_path: Path) -> Path:
    """Copy the spring-cloud-demo workspace into *tmp_path*, rewrite workspace.yaml root, and return the workspace.yaml path.

    This does NOT reindex — use :func:`setup_demo_workspace` if the test
    needs an indexed workspace.
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


def setup_demo_workspace(tmp_path: Path, *, ensure_rules: bool = False, ensure_hooks: bool = False) -> Path:
    """Copy demo, rewrite root, reindex, and optionally ensure default rules/hooks.

    Returns the workspace.yaml Path inside the temporary copy.
    """
    workspace = copy_demo_workspace(tmp_path)
    from memory_center.core.config import load_workspace_config
    from memory_center.core.indexer import reindex_workspace
    from memory_center.core.store import WorkspaceStore

    config = load_workspace_config(workspace)
    store = WorkspaceStore(workspace)
    reindex_workspace(config, store)

    if ensure_rules:
        from memory_center.core.rules import ensure_default_rules
        ensure_default_rules(store)

    if ensure_hooks:
        from memory_center.hooks.spec import ensure_default_hooks
        ensure_default_hooks(store)

    return workspace
