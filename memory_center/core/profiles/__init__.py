"""Workspace profile: user-supplied project conventions.

A profile carries *conventions*, never company data. The built-in default is
empty so the open-source distribution stays neutral; private conventions
(module aliases, default scope, wiki topology, config namespaces) are supplied
by the user through ``workspace.yaml`` or a profile file that lives outside the
repository (``~/.memory-center/profile.d/<name>.yaml``).

设计约定：

- profile 是**数据**，不是代码插件：内部使用方只需提供一份 YAML，公开仓库与
  内部使用之间不存在代码分歧。
- 所有消费方在 profile 为空时必须能降级运行（中性默认），不得抛错。
- 字段新增保持向后兼容：未知字段报错以便尽早发现拼写错误。
"""
from __future__ import annotations

from .loader import (
    PROFILE_ENV,
    ProfileError,
    active_profile,
    load_profile,
    load_profile_file,
    profile_for_workspace,
    profile_search_dirs,
    resolve_profile,
)
from .model import DEFAULT_PROFILE, PROFILE_SCHEMA_VERSION, ConfigExtractor, Profile, WikiTopology

__all__ = [
    "DEFAULT_PROFILE",
    "PROFILE_ENV",
    "PROFILE_SCHEMA_VERSION",
    "ConfigExtractor",
    "Profile",
    "ProfileError",
    "WikiTopology",
    "active_profile",
    "load_profile",
    "load_profile_file",
    "profile_for_workspace",
    "profile_search_dirs",
    "resolve_profile",
]
