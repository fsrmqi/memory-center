from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ServiceConfig:
    name: str
    path: str
    type: str = "spring-boot-service"
    service_name: Optional[str] = None
    port: Optional[int] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class WorkspaceConfig:
    workspace: str
    root: str
    services: List[ServiceConfig]

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
    package: Optional[str] = None
    classes: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)
    class_lines: Dict[str, int] = field(default_factory=dict)
    interface_lines: Dict[str, int] = field(default_factory=dict)
    method_lines: Dict[str, int] = field(default_factory=dict)
    field_lines: Dict[str, int] = field(default_factory=dict)
    annotations: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)

    # Evidence-oriented relationship facts. These are intentionally plain dicts so
    # future parsers can add richer payloads without changing public schemas.
    field_types: Dict[str, str] = field(default_factory=dict)
    method_variable_types: Dict[str, Dict[str, str]] = field(default_factory=dict)
    bean_injections: List[Dict[str, Any]] = field(default_factory=list)
    method_calls: List[Dict[str, Any]] = field(default_factory=list)
    dto_field_usages: List[Dict[str, Any]] = field(default_factory=list)
    config_usages: List[Dict[str, Any]] = field(default_factory=list)
    data_resources: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ApiEndpoint:
    project: str
    file: str
    controller: str
    http_method: str
    path: str
    method_name: Optional[str] = None


@dataclass
class FeignClient:
    project: str
    file: str
    interface: str
    target_service: str
    base_path: str = ""
    methods: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MqEndpoint:
    project: str
    file: str
    kind: str
    topic: str
    group: Optional[str] = None
    class_name: Optional[str] = None
    method_name: Optional[str] = None
    topic_placeholder: str = ""


@dataclass
class Rule:
    id: str
    title: str
    scope: List[str]
    severity: str
    rule: str
    reason: str = ""
    file_patterns: List[str] = field(default_factory=list)
    trigger_keywords: List[str] = field(default_factory=list)
    checklist: List[str] = field(default_factory=list)


@dataclass
class TaskCase:
    task: str
    projects: List[str]
    files: List[str]
    flow: str = ""
    risk_points: List[str] = field(default_factory=list)
    verified_by: List[str] = field(default_factory=list)
    created_at: str = ""


def to_dict(obj: Any) -> Dict[str, Any]:
    return asdict(obj)
