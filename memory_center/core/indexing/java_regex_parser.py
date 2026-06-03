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
        field_types.update(_parse_interface_constants(cleaned))
        method_spans = _parse_method_spans(cleaned)
        iface_methods = _parse_interface_methods(cleaned)
        method_spans.extend(iface_methods)
        methods = sorted({item["name"] for item in method_spans})
        method_variable_types = _parse_method_variable_types(cleaned, method_spans)
        bean_injections = _parse_bean_injections(cleaned, classes, field_types)
        method_calls = _parse_method_calls(cleaned, method_spans, method_variable_types, field_types)
        dto_field_usages = _parse_dto_field_usages(cleaned, method_spans, method_variable_types, field_types)
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
            method_variable_types=method_variable_types,
            bean_injections=bean_injections,
            method_calls=method_calls,
            dto_field_usages=dto_field_usages,
            config_usages=config_usages,
            data_resources=data_resources,
        )


def _strip_comments(text: str) -> str:
    """Remove Java comments while preserving string and character literals."""
    result: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        # Skip string literals
        if text[i] == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                elif text[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            result.append(text[i:j])
            i = j
        # Skip char literals
        elif text[i] == "'":
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                elif text[j] == "'":
                    j += 1
                    break
                else:
                    j += 1
            result.append(text[i:j])
            i = j
        # Block comment
        elif i + 1 < n and text[i] == '/' and text[i + 1] == '*':
            end = text.find("*/", i + 2)
            i = end + 2 if end != -1 else n
        # Line comment
        elif i + 1 < n and text[i] == '/' and text[i + 1] == '/':
            end = text.find("\n", i + 2)
            i = end + 1 if end != -1 else n
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.S)
    return m.group(1) if m else None


def _parse_interface_constants(text: str) -> Dict[str, str]:
    """Extract String CONSTANT_NAME = "value" from Java interface bodies.
    Interface fields lack explicit access modifiers (implicitly public static final),
    so _parse_fields() misses them. This function captures those declarations
    and stores them in field_types for constant reference resolution."""
    constants: Dict[str, str] = {}
    pattern = re.compile(r'String\s+(\w+)\s*=\s*"([^"]+)"\s*;', re.M)
    for name, value in pattern.findall(text):
        constants[name] = value
    return constants


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


def _parse_method_spans(text: str) -> List[Dict[str, Any]]:
    pattern = re.compile(
        r"(?:@\w+(?:\([^)]*\))?\s*)*"
        r"(?:public|private|protected)\s+"
        r"(?:static\s+)?[\w<>, ?\.\[\]]+\s+"
        r"(\w+)\s*\(([^;{}]*)\)\s*(?:throws\s+[\w, ]+\s*)?\{",
        re.M,
    )
    spans: List[Dict[str, Any]] = []
    for match in pattern.finditer(text):
        end = _matching_brace_end(text, match.end() - 1)
        spans.append({"name": match.group(1), "params": match.group(2), "start": match.start(), "end": end, "line": _line_of(text, match.start())})
    return spans


def _matching_brace_end(text: str, open_pos: int) -> int:
    depth = 0
    n = len(text)
    pos = open_pos
    while pos < n:
        ch = text[pos]
        # Skip string literals
        if ch == '"':
            pos += 1
            while pos < n:
                if text[pos] == '\\':
                    pos += 2
                elif text[pos] == '"':
                    pos += 1
                    break
                else:
                    pos += 1
            continue
        # Skip char literals
        if ch == "'":
            pos += 1
            while pos < n:
                if text[pos] == '\\':
                    pos += 2
                elif text[pos] == "'":
                    pos += 1
                    break
                else:
                    pos += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return n


def _owner_method(method_spans: List[Dict[str, Any]], pos: int) -> str | None:
    for span in method_spans:
        if span["start"] <= pos < span["end"]:
            return span["name"]
    return None


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _parse_bean_injections(text: str, classes: List[str], field_types: Dict[str, str]) -> List[Dict[str, Any]]:
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
    facts.extend(_parse_constructor_injections(text, classes, field_types, facts))
    return facts


def _parse_constructor_injections(
    text: str,
    classes: List[str],
    field_types: Dict[str, str],
    existing: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen = {(item.get("field_name"), item.get("type")) for item in existing}
    facts: List[Dict[str, Any]] = []
    final_fields = {name: typ for name, typ in field_types.items() if re.search(rf"\bfinal\s+[\w<>\.]+\s+{re.escape(name)}\s*;", text)}
    for class_name in classes:
        pattern = re.compile(rf"\b{re.escape(class_name)}\s*\((?P<params>[^)]*)\)\s*\{{(?P<body>.*?)\n\s*\}}", re.S)
        for m in pattern.finditer(text):
            params = _parse_params(m.group("params"))
            body = m.group("body")
            for field_name, field_type in final_fields.items():
                if field_name not in params:
                    continue
                if not re.search(rf"(?:this\.)?{re.escape(field_name)}\s*=\s*{re.escape(field_name)}\s*;", body):
                    continue
                fact = (field_name, _simple_type(field_type))
                if fact in seen:
                    continue
                facts.append({"field_name": field_name, "type": _simple_type(field_type), "annotation": "@Constructor", "line": _line_of(text, m.start())})
                seen.add(fact)
    return facts


def _parse_params(params: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in [p.strip() for p in params.split(",") if p.strip()]:
        cleaned = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", part).strip()
        pieces = cleaned.split()
        if len(pieces) >= 2:
            out[pieces[-1]] = _simple_type(pieces[-2])
    return out


def _parse_method_variable_types(text: str, method_spans: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    local_decl = re.compile(
        r"(?:^|[;{]\s*|\n\s*)"
        r"(?:final\s+)?(?P<type>[\w<>\.\[\]]+)\s+"
        r"(?P<name>[a-zA-Z_]\w*)\s*(?:=|;)",
        re.M,
    )
    foreach_decl = re.compile(r"for\s*\(\s*(?:final\s+)?(?P<type>[\w<>\.\[\]]+)\s+(?P<name>[a-zA-Z_]\w*)\s*:", re.M)
    for span in method_spans:
        vars_for_method = _parse_params(span.get("params", ""))
        body = text[span["start"]:span["end"]]
        for match in local_decl.finditer(body):
            vars_for_method.setdefault(match.group("name"), _simple_type(match.group("type")))
        for match in foreach_decl.finditer(body):
            vars_for_method.setdefault(match.group("name"), _simple_type(match.group("type")))
        out[span["name"]] = vars_for_method
    return out


def _parse_method_calls(
    text: str,
    method_spans: List[Dict[str, Any]],
    method_variable_types: Dict[str, Dict[str, str]],
    field_types: Dict[str, str],
) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    pattern = re.compile(r"(?P<receiver>\b[a-zA-Z_]\w*)\s*\.\s*(?P<method>[a-zA-Z_]\w*)\s*\(", re.M)
    ignored = {"log", "logger", "System", "Objects", "String", "Collections", "Arrays", "Optional", "Map", "List", "Set"}
    for m in pattern.finditer(text):
        receiver = m.group("receiver")
        method = m.group("method")
        if receiver in ignored or method in {"stream", "map", "filter", "collect", "of", "empty", "println"}:
            continue
        owner_method = _owner_method(method_spans, m.start())
        receiver_type = (method_variable_types.get(owner_method or "", {}).get(receiver) or field_types.get(receiver))
        calls.append(
            {
                "receiver": receiver,
                "receiver_type": receiver_type,
                "method_name": method,
                "owner_method": owner_method,
                "line": _line_of(text, m.start()),
            }
        )
    return calls


def _parse_dto_field_usages(
    text: str,
    method_spans: List[Dict[str, Any]],
    method_variable_types: Dict[str, Dict[str, str]],
    field_types: Dict[str, str],
) -> List[Dict[str, Any]]:
    usages: List[Dict[str, Any]] = []
    pattern = re.compile(r"(?P<receiver>\b[a-zA-Z_]\w*)\s*\.\s*(?P<accessor>get|set|is)(?P<field>[A-Z]\w*)\s*\(", re.M)
    for m in pattern.finditer(text):
        field = m.group("field")
        field_name = field[:1].lower() + field[1:]
        owner_method = _owner_method(method_spans, m.start())
        usages.append({
            "receiver": m.group("receiver"),
            "receiver_type": (method_variable_types.get(owner_method or "", {}).get(m.group("receiver")) or field_types.get(m.group("receiver"))),
            "accessor": m.group("accessor"),
            "field": field_name,
            "owner_method": owner_method,
            "line": _line_of(text, m.start()),
        })
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
