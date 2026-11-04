"""Profile data model: neutral defaults plus declarative extraction rules."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType
from typing import Any

PROFILE_SCHEMA_VERSION = 1


class ProfileError(ValueError):
    """Raised when a profile document is malformed or cannot be resolved."""


@dataclass(frozen=True)
class ConfigExtractor:
    """声明式配置抽取规则。

    把 ``<root>.<entry>.<value_key>`` 形式的配置节点抽成 ``名称 -> 值`` 映射，
    因此「某个工程用自定义命名空间配置 MQ」这件事不需要写代码：提供一条规则即可。

    例：``root=("acme", "kafka", "consumers")``、``value_key="topic"``：:

        acme:
          kafka:
            consumers:
              orderCreated: {topic: order-created}

    抽取结果：``{"orderCreated": "order-created"}``。
    """

    id: str
    root: tuple[str, ...]
    value_key: str = "topic"
    output: str = "custom_kafka_consumers"

    def extract(self, data: Mapping[str, Any]) -> dict[str, str]:
        """Return the ``entry -> value`` mapping for a parsed YAML document."""
        node: Any = data
        for segment in self.root:
            if not isinstance(node, Mapping):
                return {}
            node = node.get(segment)
        if not isinstance(node, Mapping):
            return {}
        result: dict[str, str] = {}
        for name, entry in node.items():
            if isinstance(entry, Mapping) and self.value_key in entry:
                result[str(name)] = str(entry[self.value_key])
        return result


@dataclass(frozen=True)
class WikiTopology:
    """Personal-knowledge-base layout conventions (all optional)."""

    documents: tuple[str, ...] = ()
    governance_paths: tuple[str, ...] = ()
    top_level_dirs: tuple[str, ...] = ()
    skip_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Profile:
    """Resolved conventions for one workspace.

    Every field has a neutral default so ``Profile()`` is a valid, empty
    profile: consumers must degrade gracefully instead of failing.
    """

    name: str = "default"
    version: int = PROFILE_SCHEMA_VERSION
    #: Scope used when a caller does not pass one explicitly.
    default_scope: str | None = None
    #: Alias -> canonical module/target mapping (e.g. short business name -> module).
    module_aliases: Mapping[str, str] = field(default_factory=lambda: MappingProxyType(dict[str, str]()))
    #: Date after which ``module_aliases`` stop being applied; ``None`` means no expiry.
    module_alias_until: date | None = None
    #: Free-form hint appended to "module not registered" errors; empty by default.
    module_alias_hint: str = ""
    wiki: WikiTopology = field(default_factory=WikiTopology)
    config_extractors: tuple[ConfigExtractor, ...] = ()
    #: Extra low-signal tokens for task-title matching (additive only).
    weak_tokens: frozenset[str] = frozenset()

    def alias_target(self, requested: str, *, today: date | None = None) -> str:
        """Resolve ``requested`` through ``module_aliases``; return it unchanged when absent.

        Aliases stop applying after ``module_alias_until`` so a temporary
        migration window can expire without a code change.
        """
        key = (requested or "").strip()
        if not key:
            return key
        resolved = self.module_aliases.get(key) or self.module_aliases.get(key.lower())
        if not resolved:
            return key
        if self.module_alias_until is not None:
            current = today or date.today()
            if current > self.module_alias_until:
                return key
        return resolved

    def alias_active(self, *, today: date | None = None) -> bool:
        """Whether any alias can still apply (used for error hints)."""
        if not self.module_aliases:
            return False
        if self.module_alias_until is None:
            return True
        return (today or date.today()) <= self.module_alias_until


DEFAULT_PROFILE = Profile()


def neutralize_example(value: str, fallback: str = "") -> str:
    """Return a neutral placeholder for example/sample text.

    Kept here so call sites that must render an example symbol or path have one
    shared, obviously-fake convention instead of inventing their own.
    """
    cleaned = (value or "").strip()
    return cleaned or fallback
