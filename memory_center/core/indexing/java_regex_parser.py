from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .base import JavaParseResult


class RegexJavaParser:
    """Dependency-free Java/Spring parser.

    This parser is intentionally conservative: it extracts evidence that is useful
    for AI-agent context while remaining easy to install. It is not a replacement
    for a compiler or symbol solver. Future accurate parsers can implement the same
    JavaParser protocol and produce the same relationship facts.
    """

    name = "regex"

    def parse(self, text: str, file_path: str) -> JavaParseResult:
        cleaned = _strip_comments(text)
        package = _first_group(r"package\s+([\w\.]+)\s*;", cleaned)
        imports = re.findall(r"import\s+([\w\.\*]+)\s*;", cleaned)
        classes = re.findall(r"\bclass\s+(\w+)", cleaned)
        interfaces = re.findall(r"\binterface\s+(\w+)", cleaned)
        annotations = sorted(set(re.findall(r"@(\w+)(?:\(|\s|\n)", cleaned)))

        fields, field_types = _parse_fields(cleaned)
        methods = _parse_methods(cleaned)
        bean_injections = _parse_bean_injections(cleaned)
        method_calls = _parse_method_calls(cleaned)
        dto_field_usages = _parse_dto_field_usages(cleaned)
        config_usages = _parse_config_usages(cleaned)
        data_resources = _parse_data_resources(cleaned)

        return JavaParseResult(
            package=package,
            imports=imports,
            classes=classes,
            interfaces=interfaces,
            methods=methods,
            fields=fields,
            annotations=annotations,
            field_types=field_types,
            bean_injections=bean_injections,
            method_calls=method_calls,
            dto_field_usages=dto_field_usages,
            config_usages=config_usages,
            data_resources=data_resources,
        )


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.S)
    return m.group(1) if m else None


def _parse_fields(text: str) -> Tuple[List[str], Dict[str, str]]:
    field_types: Dict[str, str] = {}
    fields: List[str] = []
    pattern = re.compile(
        r"(?:@\w+(?:\([^)]*\))?\s*)*"
        r"(?:private|public|protected)\s+"
        r"(?:static\s+)?(?:final\s+)?"
        r"([\w<>, ?\.\[\]]+)\s+"
        r"(\w+)\s*(?:=|;)",
        re.M,
    )
    for typ, name in pattern.findall(text):
        clean_type = typ.strip().split()[-1]
        fields.append(name)
        field_types[name] = clean_type
    return sorted(set(fields)), field_types


def _parse_methods(text: str) -> List[str]:
    pattern = re.compile(
        r"(?:@\w+(?:\([^)]*\))?\s*)*"
        r"(?:public|private|protected)\s+"
        r"(?:static\s+)?[\w<>, ?\.\[\]]+\s+"
        r"(\w+)\s*\([^;{}]*\)\s*(?:throws\s+[\w, ]+\s*)?\{",
        re.M,
    )
    return sorted(set(pattern.findall(text)))


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _parse_bean_injections(text: str) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    # @Autowired / @Resource field injection
    pattern = re.compile(
        r"(?P<ann>@(?:Autowired|Resource|Inject)(?:\([^)]*\))?\s*)+"
        r"(?:private|protected|public)?\s*"
        r"(?P<type>[\w<>\.]+)\s+(?P<name>\w+)\s*;",
        re.M,
    )
    for m in pattern.finditer(text):
        facts.append({"field_name": m.group("name"), "type": _simple_type(m.group("type")), "annotation": m.group("ann").strip(), "line": _line_of(text, m.start())})

    # Lombok constructor injection via final fields in @RequiredArgsConstructor classes
    if "@RequiredArgsConstructor" in text:
        final_pattern = re.compile(r"private\s+final\s+(?P<type>[\w<>\.]+)\s+(?P<name>\w+)\s*;", re.M)
        for m in final_pattern.finditer(text):
            facts.append({"field_name": m.group("name"), "type": _simple_type(m.group("type")), "annotation": "@RequiredArgsConstructor", "line": _line_of(text, m.start())})
    return facts


def _parse_method_calls(text: str) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    pattern = re.compile(r"(?P<receiver>\b[a-zA-Z_]\w*)\s*\.\s*(?P<method>[a-zA-Z_]\w*)\s*\(", re.M)
    ignored = {"log", "logger", "System", "Objects", "String", "Collections", "Arrays", "Optional", "Map", "List", "Set"}
    for m in pattern.finditer(text):
        receiver = m.group("receiver")
        method = m.group("method")
        if receiver in ignored or method in {"stream", "map", "filter", "collect", "of", "empty", "println"}:
            continue
        calls.append({"receiver": receiver, "method_name": method, "line": _line_of(text, m.start())})
    return calls


def _parse_dto_field_usages(text: str) -> List[Dict[str, Any]]:
    usages: List[Dict[str, Any]] = []
    pattern = re.compile(r"(?P<receiver>\b[a-zA-Z_]\w*)\s*\.\s*(?P<accessor>get|set|is)(?P<field>[A-Z]\w*)\s*\(", re.M)
    for m in pattern.finditer(text):
        field = m.group("field")
        field_name = field[:1].lower() + field[1:]
        usages.append({"receiver": m.group("receiver"), "accessor": m.group("accessor"), "field": field_name, "line": _line_of(text, m.start())})
    return usages


def _parse_config_usages(text: str) -> List[Dict[str, Any]]:
    usages: List[Dict[str, Any]] = []
    for m in re.finditer(r"@Value\s*\(\s*\"\$\{([^}:\"]+)(?::[^\"]*)?}\"\s*\)", text):
        usages.append({"key": m.group(1), "line": _line_of(text, m.start()), "annotation": "@Value"})
    for m in re.finditer(r"@ConfigurationProperties\s*\(\s*(?:prefix\s*=\s*)?\"([^\"]+)\"\s*\)", text):
        usages.append({"key": m.group(1), "line": _line_of(text, m.start()), "annotation": "@ConfigurationProperties"})
    return usages


def _parse_data_resources(text: str) -> List[Dict[str, Any]]:
    resources: List[Dict[str, Any]] = []
    for m in re.finditer(r"@Document\s*\(([^)]*)\)", text, flags=re.S):
        args = m.group(1)
        name = _named_or_first_string(args, "collection") or _named_or_first_string(args, "value")
        if name:
            resources.append({"kind": "MongoCollection", "name": name, "operation": "declares", "line": _line_of(text, m.start())})
    for m in re.finditer(r"(?:getCollection|collectionName)\s*\(\s*\"([^\"]+)\"\s*\)", text):
        resources.append({"kind": "MongoCollection", "name": m.group(1), "operation": "uses", "line": _line_of(text, m.start())})
    for m in re.finditer(r"(?:indexName|IndexName|index)\s*=\s*\"([^\"]+)\"", text):
        resources.append({"kind": "EsIndex", "name": m.group(1), "operation": "uses", "line": _line_of(text, m.start())})
    if "ElasticsearchRestTemplate" in text or "elasticsearch" in text.lower():
        resources.append({"kind": "EsIndex", "name": "unknown-es-index", "operation": "uses-template", "line": 1})
    if "MongoTemplate" in text or "mongoTemplate" in text:
        resources.append({"kind": "MongoCollection", "name": "unknown-mongo-collection", "operation": "uses-template", "line": 1})
    return resources


def _simple_type(value: str) -> str:
    return value.strip().split(".")[-1].split("<")[0]


def _named_or_first_string(args: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*=\s*\"([^\"]+)\"", args or "")
    if m:
        return m.group(1)
    m = re.search(r'"([^"]+)"', args or "")
    return m.group(1) if m else None
