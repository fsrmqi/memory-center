from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class JavaParseResult:
    package: str | None = None
    imports: list[str] = field(default_factory=list)
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
    field_types: dict[str, str] = field(default_factory=dict)
    constants: dict[str, str] = field(default_factory=dict)
    method_variable_types: dict[str, dict[str, str]] = field(default_factory=dict)
    bean_injections: list[dict[str, Any]] = field(default_factory=list)
    method_calls: list[dict[str, Any]] = field(default_factory=list)
    dto_field_usages: list[dict[str, Any]] = field(default_factory=list)
    config_usages: list[dict[str, Any]] = field(default_factory=list)
    data_resources: list[dict[str, Any]] = field(default_factory=list)


class JavaParser(Protocol):
    name: str

    def parse(self, text: str, file_path: str) -> JavaParseResult:
        """Parse a Java source file into extractable facts."""
