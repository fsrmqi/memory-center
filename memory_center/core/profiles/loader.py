"""Profile loading: YAML documents, file lookup and resolution order."""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import fields
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..profiles.model import (
    DEFAULT_PROFILE,
    PROFILE_SCHEMA_VERSION,
    ConfigExtractor,
    Profile,
    ProfileError,
    WikiTopology,
)

PROFILE_ENV = "MEMORY_CENTER_PROFILE"
PROFILE_DIR_ENV = "MEMORY_CENTER_PROFILE_DIR"
PROFILE_SUFFIXES = (".yaml", ".yml")

_WIKI_KEYS = {"documents", "governance_paths", "top_level_dirs", "skip_names"}
_EXTRACTOR_KEYS = {"id", "root", "value_key", "output"}


def profile_search_dirs() -> tuple[Path, ...]:
    """Directories searched for ``<name>.yaml`` profile documents."""
    dirs: list[Path] = []
    override = os.environ.get(PROFILE_DIR_ENV, "").strip()
    if override:
        dirs.append(Path(override).expanduser())
    dirs.append(Path.home() / ".memory-center" / "profile.d")
    return tuple(dirs)


def _as_str_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        items = tuple(str(item).strip() for item in value)
        return tuple(item for item in items if item)
    raise ProfileError(f"{field_name} 需为字符串或字符串列表")


def _as_str_set(value: Any, field_name: str) -> frozenset[str]:
    return frozenset(_as_str_tuple(value, field_name))


def _parse_extractor(raw: Any, index: int) -> ConfigExtractor:
    if not isinstance(raw, Mapping):
        raise ProfileError(f"config_extractors[{index}] 需为映射")
    unknown = set(raw) - _EXTRACTOR_KEYS
    if unknown:
        raise ProfileError(f"config_extractors[{index}] 含未知字段：{sorted(unknown)}")
    root = _as_str_tuple(raw.get("root"), f"config_extractors[{index}].root")
    if not root:
        raise ProfileError(f"config_extractors[{index}].root 不能为空")
    extractor_id = str(raw.get("id") or "").strip()
    if not extractor_id:
        raise ProfileError(f"config_extractors[{index}].id 不能为空")
    return ConfigExtractor(
        id=extractor_id,
        root=root,
        value_key=str(raw.get("value_key") or "topic"),
        output=str(raw.get("output") or "custom_kafka_consumers"),
    )


def _parse_wiki(raw: Any) -> WikiTopology:
    if raw is None:
        return WikiTopology()
    if not isinstance(raw, Mapping):
        raise ProfileError("wiki 需为映射")
    unknown = set(raw) - _WIKI_KEYS
    if unknown:
        raise ProfileError(f"wiki 含未知字段：{sorted(unknown)}")
    return WikiTopology(
        documents=_as_str_tuple(raw.get("documents"), "wiki.documents"),
        governance_paths=_as_str_tuple(raw.get("governance_paths"), "wiki.governance_paths"),
        top_level_dirs=_as_str_tuple(raw.get("top_level_dirs"), "wiki.top_level_dirs"),
        skip_names=_as_str_set(raw.get("skip_names"), "wiki.skip_names"),
    )


def _parse_date(raw: Any) -> date | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError as exc:  # pragma: no cover - message asserted by tests
        raise ProfileError(f"module_alias_until 需为 ISO 日期（YYYY-MM-DD）：{raw}") from exc


def load_profile(data: Mapping[str, Any], *, name: str = "") -> Profile:
    """Build a :class:`Profile` from an already-parsed document.

    Unknown top-level keys are rejected so typos fail loudly instead of being
    silently ignored (a silently-dropped ``default_scope`` would be very hard to
    diagnose).
    """
    if data is None:
        return DEFAULT_PROFILE if not name else Profile(name=name)
    if not isinstance(data, Mapping):
        raise ProfileError("profile 文档根节点需为映射")

    allowed = {item.name for item in fields(Profile)}
    unknown = set(data) - allowed
    if unknown:
        raise ProfileError(f"profile 含未知字段：{sorted(unknown)}")

    version = int(data.get("version", PROFILE_SCHEMA_VERSION) or PROFILE_SCHEMA_VERSION)
    if version != PROFILE_SCHEMA_VERSION:
        raise ProfileError(f"不支持的 profile version：{version}（期望 {PROFILE_SCHEMA_VERSION}）")

    raw_aliases = data.get("module_aliases") or {}
    if not isinstance(raw_aliases, Mapping):
        raise ProfileError("module_aliases 需为映射（别名 -> 目标）")
    aliases = {str(key): str(value) for key, value in raw_aliases.items()}

    raw_extractors = data.get("config_extractors") or ()
    if isinstance(raw_extractors, Mapping) or isinstance(raw_extractors, str):
        raise ProfileError("config_extractors 需为列表")
    extractors = tuple(_parse_extractor(item, index) for index, item in enumerate(raw_extractors))

    default_scope = data.get("default_scope")
    return Profile(
        name=str(data.get("name") or name or "default"),
        version=version,
        default_scope=str(default_scope).strip() if default_scope else None,
        module_aliases=aliases,
        module_alias_until=_parse_date(data.get("module_alias_until")),
        module_alias_hint=str(data.get("module_alias_hint") or ""),
        wiki=_parse_wiki(data.get("wiki")),
        config_extractors=extractors,
        weak_tokens=_as_str_set(data.get("weak_tokens"), "weak_tokens"),
    )


@lru_cache(maxsize=64)
def _load_cached(path_str: str, mtime_ns: int) -> Profile:
    """Load a profile file, keyed by path and mtime so edits are picked up."""
    del mtime_ns  # cache key only
    path = Path(path_str)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:  # pragma: no cover - filesystem race
        raise ProfileError(f"无法读取 profile 文件：{path}") from exc
    except yaml.YAMLError as exc:
        raise ProfileError(f"profile 文件不是合法 YAML：{path}") from exc
    return load_profile(data, name=path.stem)


def load_profile_file(path: str | Path) -> Profile:
    """Load one profile document from disk."""
    resolved = Path(path).expanduser()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise ProfileError(f"profile 文件不存在：{resolved}") from exc
    return _load_cached(str(resolved.resolve()), stat.st_mtime_ns)


def _find_named_profile(name: str) -> Path | None:
    for directory in profile_search_dirs():
        for suffix in PROFILE_SUFFIXES:
            candidate = directory / f"{name}{suffix}"
            if candidate.is_file():
                return candidate
    return None


def _resolve_reference(reference: str, *, required: bool) -> Profile:
    """Resolve a path or a profile name into a profile."""
    reference = reference.strip()
    if not reference:
        return DEFAULT_PROFILE
    as_path = Path(reference).expanduser()
    if as_path.is_file():
        return load_profile_file(as_path)
    named = _find_named_profile(reference)
    if named is not None:
        return load_profile_file(named)
    if required:
        searched = ", ".join(str(directory) for directory in profile_search_dirs())
        raise ProfileError(f"未找到 profile：{reference}（已搜索：{searched}）")
    return DEFAULT_PROFILE


def resolve_profile(
    explicit: Profile | str | Path | None = None,
    *,
    workspace_profile: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Profile:
    """Resolve the effective profile.

    Priority (first match wins): explicit value (object / path / name), then
    ``workspace.yaml``'s ``profile:`` field, then ``MEMORY_CENTER_PROFILE``,
    then the neutral :data:`DEFAULT_PROFILE`.
    """
    if isinstance(explicit, Profile):
        return explicit

    environment = os.environ if env is None else env
    for reference, required in (
        (str(explicit) if explicit is not None else "", True),
        (workspace_profile or "", False),
        (environment.get(PROFILE_ENV, "") or "", True),
    ):
        if not reference.strip():
            continue
        profile = _resolve_reference(reference, required=required)
        if profile is not DEFAULT_PROFILE:
            return profile
    return DEFAULT_PROFILE


def active_profile() -> Profile:
    """Process-wide profile resolution honouring ``MEMORY_CENTER_PROFILE``."""
    return resolve_profile()


@lru_cache(maxsize=128)
def _workspace_profile_ref(path_str: str, mtime_ns: int) -> str:
    """Read only the ``profile:`` key of a workspace file (cheap, no full parse)."""
    del mtime_ns  # cache key only
    try:
        data = yaml.safe_load(Path(path_str).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(data, Mapping):
        return ""
    raw = data.get("profile")
    return str(raw).strip() if raw else ""


def profile_for_workspace(workspace_file: str | Path | None) -> Profile:
    """Resolve the profile for one workspace file.

    Precedence matches :func:`resolve_profile`: explicit operator override, then
    the workspace's own ``profile:`` declaration, then the neutral default.
    """
    if workspace_file:
        path = Path(workspace_file).expanduser()
        try:
            stat = path.stat()
        except OSError:
            return active_profile()
        reference = _workspace_profile_ref(str(path.resolve()), stat.st_mtime_ns)
        if reference:
            return _resolve_reference(reference, required=True)
    return active_profile()
