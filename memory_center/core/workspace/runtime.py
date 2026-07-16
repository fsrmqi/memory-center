"""工作区运行时装配：将配置与本地存储作为一个受控读取上下文返回。"""
from __future__ import annotations

from pathlib import Path

from memory_center.core.storage.workspace import WorkspaceStore

from .config import load_workspace_config


def load_workspace_context(workspace_file: str | Path):
    """加载工作区配置与存储访问对象，不包含业务编排。"""
    return load_workspace_config(workspace_file), WorkspaceStore(workspace_file)
