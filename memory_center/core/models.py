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


@dataclass
class JavaSymbol:
    project: str
    file: str
    package: Optional[str] = None
    classes: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)
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
