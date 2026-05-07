from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class JavaParseResult:
    package: Optional[str] = None
    imports: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    interfaces: List[str] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    field_types: Dict[str, str] = field(default_factory=dict)
    method_variable_types: Dict[str, Dict[str, str]] = field(default_factory=dict)
    bean_injections: List[Dict[str, Any]] = field(default_factory=list)
    method_calls: List[Dict[str, Any]] = field(default_factory=list)
    dto_field_usages: List[Dict[str, Any]] = field(default_factory=list)
    config_usages: List[Dict[str, Any]] = field(default_factory=list)
    data_resources: List[Dict[str, Any]] = field(default_factory=list)


class JavaParser(Protocol):
    name: str

    def parse(self, text: str, file_path: str) -> JavaParseResult:
        """Parse a Java source file into extractable facts."""
