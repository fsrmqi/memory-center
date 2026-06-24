from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ServiceConfig:
    name: str
    path: str
    # Default kept as ``spring-boot-service`` for backward compatibility with
    # existing workspace.yaml files. See ``memory_center.core.service_kinds``
    # for the full registry of supported kinds.
    type: str = "spring-boot-service"
    service_name: str | None = None
    port: int | None = None
    tags: list[str] = field(default_factory=list)
    # Optional explicit language override. When ``None`` the language is
    # inferred from ``type`` via ``service_kinds.resolve_kind``. Set this
    # when a generic kind serves a non-default language (e.g. ``type:
    # generic`` with ``language: scala``).
    language: str | None = None

    def resolved_language(self) -> str | None:
        """Return the explicit language override, or the language inferred
        from the registered kind. Falls back to ``None`` for unknown kinds.
        """
        if self.language:
            return self.language
        # Import locally to avoid a circular import: service_kinds is a
        # pure module but lives in the same package and may grow helpers
        # that import from models in the future.
        from .service_kinds import resolve_kind

        return resolve_kind(self.type).language


@dataclass
class WorkspaceConfig:
    workspace: str
    root: str
    services: list[ServiceConfig]

    @property
    def root_path(self) -> Path:
        return Path(self.root).expanduser().resolve()

    def resolve_service_path(self, service: ServiceConfig) -> Path:
        raw = Path(service.path).expanduser()
        if raw.is_absolute():
            return raw.resolve()
        return (self.root_path / raw).resolve()

    def service_logical_prefix(self, service: ServiceConfig) -> str:
        raw = Path(service.path).expanduser()
        if not raw.is_absolute():
            return raw.as_posix().strip("/") or service.name
        resolved = raw.resolve()
        try:
            return resolved.relative_to(self.root_path).as_posix().strip("/") or service.name
        except ValueError:
            return service.name

    def service_logical_file_path(self, service: ServiceConfig, file_path: Path) -> str:
        service_root = self.resolve_service_path(service)
        try:
            relative = file_path.resolve().relative_to(service_root).as_posix()
        except ValueError:
            relative = file_path.name
        prefix = self.service_logical_prefix(service)
        return f"{prefix}/{relative}".strip("/")


@dataclass
class JavaSymbol:
    project: str
    file: str
    parser: str = ""
    package: str | None = None
    classes: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    method_signatures: list[dict[str, Any]] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    class_lines: dict[str, int] = field(default_factory=dict)
    interface_lines: dict[str, int] = field(default_factory=dict)
    method_lines: dict[str, int] = field(default_factory=dict)
    field_lines: dict[str, int] = field(default_factory=dict)
    annotations: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)

    # Evidence-oriented relationship facts. These are intentionally plain dicts so
    # future parsers can add richer payloads without changing public schemas.
    field_types: dict[str, str] = field(default_factory=dict)
    constants: dict[str, str] = field(default_factory=dict)
    method_variable_types: dict[str, dict[str, str]] = field(default_factory=dict)
    bean_injections: list[dict[str, Any]] = field(default_factory=list)
    method_calls: list[dict[str, Any]] = field(default_factory=list)
    dto_field_usages: list[dict[str, Any]] = field(default_factory=list)
    config_usages: list[dict[str, Any]] = field(default_factory=list)
    data_resources: list[dict[str, Any]] = field(default_factory=list)

    # Hand-written shallow ``to_dict`` to avoid ``dataclasses.asdict`` recursion.
    # P1-0 profile showed 22K JavaSymbol instances produced ~13.5M
    # ``_asdict_inner`` calls and ~20s of total time on a real UCAP workspace.
    # The output schema, key set, key order, and value types must match what
    # ``dataclasses.asdict(self)`` returned, so downstream graph rebuild,
    # benchmarks, and reports do not need any change.
    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "file": self.file,
            "parser": self.parser,
            "package": self.package,
            "classes": list(self.classes),
            "interfaces": list(self.interfaces),
            "methods": list(self.methods),
            "method_signatures": list(self.method_signatures),
            "fields": list(self.fields),
            "class_lines": dict(self.class_lines),
            "interface_lines": dict(self.interface_lines),
            "method_lines": dict(self.method_lines),
            "field_lines": dict(self.field_lines),
            "annotations": list(self.annotations),
            "imports": list(self.imports),
            "field_types": dict(self.field_types),
            "constants": dict(self.constants),
            "method_variable_types": {
                method: dict(variables)
                for method, variables in self.method_variable_types.items()
            },
            "bean_injections": list(self.bean_injections),
            "method_calls": list(self.method_calls),
            "dto_field_usages": list(self.dto_field_usages),
            "config_usages": list(self.config_usages),
            "data_resources": list(self.data_resources),
        }


@dataclass
class ApiEndpoint:
    project: str
    file: str
    controller: str
    http_method: str
    path: str
    method_name: str | None = None


@dataclass
class FeignClient:
    project: str
    file: str
    interface: str
    target_service: str
    base_path: str = ""
    methods: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MqEndpoint:
    project: str
    file: str
    kind: str
    topic: str
    group: str | None = None
    class_name: str | None = None
    method_name: str | None = None
    topic_placeholder: str = ""


@dataclass
class Rule:
    id: str
    title: str
    scope: list[str]
    severity: str
    rule: str
    reason: str = ""
    file_patterns: list[str] = field(default_factory=list)
    trigger_keywords: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)


@dataclass
class TaskCase:
    task: str
    projects: list[str]
    files: list[str]
    flow: str = ""
    risk_points: list[str] = field(default_factory=list)
    verified_by: list[str] = field(default_factory=list)
    created_at: str = ""


def to_dict(obj: Any) -> dict[str, Any]:
    # Prefer the object's own ``to_dict`` when present so hot-path types
    # (e.g. ``JavaSymbol``) can skip the recursive ``dataclasses.asdict``
    # path. Fall back to ``asdict`` for other dataclasses so callers stay
    # source-compatible.
    custom = getattr(obj, "to_dict", None)
    if callable(custom) and not isinstance(obj, type):
        return custom()
    return asdict(obj)
