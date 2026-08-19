from __future__ import annotations

import re
from typing import Any

from .base import JavaParseResult

_FUNCTIONAL_INTERFACE_INPUTS: dict[str, tuple[int, ...]] = {
    "Consumer": (0,),
    "Function": (0,),
    "Predicate": (0,),
    "BiConsumer": (0, 1),
    "BiFunction": (0, 1),
    "BiPredicate": (0, 1),
    "UnaryOperator": (0,),
    "BinaryOperator": (0, 0),
}
_LAMBDA_PATTERN = re.compile(r"(?P<params>\([^(){};]*\)|[A-Za-z_$][\w$]*)\s*->", re.M)
_FUNCTIONAL_TARGET_PATTERN = re.compile(
    rf"(?:java\.util\.function\.)?(?P<interface>{'|'.join(sorted(_FUNCTIONAL_INTERFACE_INPUTS, key=len, reverse=True))})\s*"
    r"<(?P<generics>[^;=]+)>\s+[A-Za-z_$][\w$]*\s*=\s*$",
    re.S,
)
_JDK_COLLECTION_TYPES = frozenset({"Collection", "Iterable", "List", "Set", "Stream"})
# Collection operations invoked directly (no ``stream()``) whose lambda takes a
# single element parameter typed by the collection's element generic.
_JDK_COLLECTION_ELEMENT_OPERATIONS = frozenset({"forEach", "removeIf", "replaceAll"})
_JDK_STREAM_INPUT_OPERATIONS = frozenset(
    {"allMatch", "anyMatch", "filter", "flatMap", "forEach", "forEachOrdered", "map", "noneMatch", "peek"}
)


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
        imports = [
            f"{'static ' if static else ''}{target}"
            for static, target in re.findall(r"import\s+(static\s+)?([\w\.\*]+)\s*;", cleaned)
        ]
        classes, class_lines = _parse_type_declarations(cleaned, ("class", "enum", "record"))
        interfaces, interface_lines = _parse_type_declarations(cleaned, ("interface",))
        type_kinds = _parse_type_kinds(cleaned)
        type_supertypes = _parse_type_supertypes(cleaned)
        annotations = sorted(set(re.findall(r"@(\w+)(?:\(|\s|\n)", cleaned)))

        fields, field_types, field_lines = _parse_fields(cleaned)
        generic_field_types = _parse_generic_field_types(cleaned)
        constants = _parse_interface_constants(cleaned)
        field_types.update(constants)
        method_spans = _parse_method_spans(cleaned, type_names=classes)
        iface_methods = _parse_interface_methods(cleaned)
        method_spans.extend(iface_methods)
        methods = sorted({item["name"] for item in method_spans})
        method_signatures = _build_method_signatures(method_spans)
        method_lines = {
            item["name"]: int(item.get("line", 0) or 0)
            for item in sorted(method_spans, key=lambda span: int(span.get("line", 0) or 0))
            if item.get("name") and int(item.get("line", 0) or 0) > 0
        }
        method_variable_types = _parse_method_variable_types(cleaned, method_spans)
        bean_injections = _parse_bean_injections(cleaned, classes, field_types)
        method_calls = _parse_method_calls(cleaned, method_spans, field_types, generic_field_types)
        dto_field_usages = _parse_dto_field_usages(cleaned, method_spans, field_types, generic_field_types)
        config_usages = _parse_config_usages(cleaned)
        data_resources = _parse_data_resources(cleaned)

        return JavaParseResult(
            package=package,
            imports=imports,
            classes=classes,
            interfaces=interfaces,
            type_kinds=type_kinds,
            type_supertypes=type_supertypes,
            methods=methods,
            method_signatures=method_signatures,
            fields=fields,
            class_lines=class_lines,
            interface_lines=interface_lines,
            method_lines=method_lines,
            field_lines=field_lines,
            annotations=annotations,
            field_types=field_types,
            constants=constants,
            method_variable_types=method_variable_types,
            bean_injections=bean_injections,
            method_calls=method_calls,
            dto_field_usages=dto_field_usages,
            config_usages=config_usages,
            data_resources=data_resources,
        )

    def parse_supplements(
        self,
        text: str,
        file_path: str,
        *,
        classes: list[str] | None = None,
        field_types: dict[str, str] | None = None,
    ) -> JavaParseResult:
        """Run only the regex passes that tree-sitter does not yet cover.

        ``parse`` is kept untouched as a fallback / differential oracle. This
        supplement entry is used by ``TreeSitterJavaParser`` on its success
        path to avoid re-extracting structural facts (package / imports /
        classes / interfaces / methods / fields / annotations) that
        tree-sitter already produced. It returns a ``JavaParseResult`` where
        only the supplement fields are populated:

        - ``constants``
        - ``method_variable_types``
        - ``bean_injections``
        - ``method_calls``
        - ``dto_field_usages``
        - ``config_usages``
        - ``data_resources``

        Structural fields are left at their dataclass defaults so the caller
        can merge them with the tree-sitter result without losing any data.
        ``classes`` / ``field_types`` are read-only inputs that already came
        from tree-sitter; supplements use them as analysis context.
        """
        cleaned = _strip_comments(text)
        constants = _parse_interface_constants(cleaned)
        # Always run ``_parse_fields`` to keep supplements self-healing when
        # tree-sitter under-reports fields (e.g. fake parsers in tests, or
        # future Java syntax tree-sitter does not yet model). Tree-sitter
        # field info still wins when provided.
        _fields_local, regex_field_types, _field_lines = _parse_fields(cleaned)
        # Downstream analyzers (``_parse_method_calls``,
        # ``_parse_dto_field_usages``, ``_parse_bean_injections``) match
        # legacy behaviour exactly only when they see the same field-type
        # dict ``RegexJavaParser.parse`` historically built:
        # ``field_types.update(constants)``. Mixing tree-sitter's
        # ``field_types`` in changes the receivers/types these analyzers
        # see and can introduce duplicate or shifted entries vs the legacy
        # path. Keep the analyzer seed regex-only, and let the tree-sitter
        # ``field_types`` be merged in at the final ``_merge_supplements``
        # step instead.
        seed_field_types: dict[str, str] = dict(regex_field_types)
        seed_field_types.update(constants)
        generic_field_types = _parse_generic_field_types(cleaned)
        known_types = list(classes or _parse_type_declarations(cleaned, ("class", "enum", "record"))[0])
        type_supertypes = _parse_type_supertypes(cleaned)
        method_spans = _parse_method_spans(cleaned, type_names=known_types)
        method_spans.extend(_parse_interface_methods(cleaned))
        method_signatures = _build_method_signatures(method_spans)
        method_variable_types = _parse_method_variable_types(cleaned, method_spans)
        bean_injections = _parse_bean_injections(cleaned, list(classes or []), seed_field_types)
        method_calls = _parse_method_calls(cleaned, method_spans, seed_field_types, generic_field_types)
        dto_field_usages = _parse_dto_field_usages(
            cleaned, method_spans, seed_field_types, generic_field_types
        )
        config_usages = _parse_config_usages(cleaned)
        data_resources = _parse_data_resources(cleaned)
        return JavaParseResult(
            type_supertypes=type_supertypes,
            method_signatures=method_signatures,
            constants=constants,
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
                if text[j] == "\\":
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
                if text[j] == "\\":
                    j += 2
                elif text[j] == "'":
                    j += 1
                    break
                else:
                    j += 1
            result.append(text[i:j])
            i = j
        # Block comment
        elif i + 1 < n and text[i] == "/" and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = end + 2 if end != -1 else n
        # Line comment
        elif i + 1 < n and text[i] == "/" and text[i + 1] == "/":
            end = text.find("\n", i + 2)
            i = end + 1 if end != -1 else n
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def _first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.S)
    return m.group(1) if m else None


def _parse_interface_constants(text: str) -> dict[str, str]:
    """Extract String CONSTANT_NAME = "value" from Java interface bodies.
    Interface fields lack explicit access modifiers (implicitly public static final),
    so _parse_fields() misses them. This function captures those declarations
    and stores them in field_types for constant reference resolution."""
    constants: dict[str, str] = {}
    pattern = re.compile(r'String\s+(\w+)\s*=\s*"([^"]+)"\s*;', re.M)
    for name, value in pattern.findall(text):
        constants[name] = value
    return constants


def _parse_type_declarations(text: str, keywords: tuple[str, ...]) -> tuple[list[str], dict[str, int]]:
    pattern = re.compile(r"\b(" + "|".join(re.escape(keyword) for keyword in keywords) + r")\s+(\w+)", re.M)
    names: list[str] = []
    lines: dict[str, int] = {}
    for match in pattern.finditer(text):
        name = match.group(2)
        names.append(name)
        lines.setdefault(name, _line_of(text, match.start(2)))
    return sorted(set(names)), lines


def _parse_type_kinds(text: str) -> dict[str, str]:
    return {
        match.group(2): match.group(1) for match in re.finditer(r"\b(class|interface|enum|record)\s+(\w+)", text, re.M)
    }


def _parse_type_supertypes(text: str) -> dict[str, list[str]]:
    """Extract direct extends/implements names without attempting type solving."""

    result: dict[str, list[str]] = {}
    declaration = re.compile(
        r"\b(?:class|interface|enum|record)\s+(?P<name>\w+)(?:\s*<[^{}]*?>)?(?P<header>[^{}]*)\{",
        re.M,
    )
    for match in declaration.finditer(text):
        parents: list[str] = []
        header = match.group("header") or ""
        for relation in re.finditer(r"\b(?:extends|implements)\s+(.+?)(?=\s+\b(?:extends|implements)\b|$)", header):
            for candidate in _split_top_level(relation.group(1)):
                simple = _simple_type(candidate.strip())
                if simple and simple not in parents:
                    parents.append(simple)
        if parents:
            result[match.group("name")] = parents
    return result


def _parse_fields(text: str) -> tuple[list[str], dict[str, str], dict[str, int]]:
    field_types: dict[str, str] = {}
    field_lines: dict[str, int] = {}
    fields: list[str] = []
    pattern = re.compile(
        r"(?:@\w+(?:\([^)]*\))?\s*)*"
        r"(?:private|public|protected)\s+"
        r"(?:static\s+)?(?:final\s+)?"
        r"([\w<>, ?\.\[\]]+)\s+"
        r"(\w+)\s*(?:=|;)",
        re.M,
    )
    for match in pattern.finditer(text):
        typ = match.group(1)
        name = match.group(2)
        clean_type = typ.strip().split()[-1]
        fields.append(name)
        field_types[name] = clean_type
        field_lines.setdefault(name, _line_of(text, match.start(2)))
    return sorted(set(fields)), field_types, field_lines


_NON_METHOD_KEYWORDS = frozenset(
    {
        "assert",
        "catch",
        "do",
        "else",
        "for",
        "if",
        "new",
        "switch",
        "synchronized",
        "try",
        "while",
    }
)


def _parse_method_spans(text: str, *, type_names: list[str] | None = None) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"(?:@\w+(?:\([^)]*\))?\s*)*"
        r"(?:(?:public|private|protected)\s+)?"
        r"(?:static\s+)?(?P<return_type>[\w<>, ?\.\[\]]+)\s+"
        r"(?P<name>\w+)\s*\((?P<params>[^;{}]*)\)\s*(?:throws\s+[\w, ]+\s*)?\{",
        re.M,
    )
    constructors = set(type_names or [])
    spans: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        name = match.group("name")
        # The permissive return-type fragment permits indentation to satisfy
        # the type portion, so control-flow headers can otherwise be emitted
        # as pseudo methods. Constructors also have no return type and are
        # deliberately excluded because the graph models callable methods.
        if name in _NON_METHOD_KEYWORDS or name in constructors:
            continue
        body_start = match.end()
        end = _matching_brace_end(text, match.end() - 1)
        spans.append(
            {
                "name": name,
                "params": match.group("params"),
                "return_type": _normalize_type_identity(match.group("return_type")),
                "start": match.start(),
                "body_start": body_start,
                "end": end,
                "line": _line_of(text, match.start()),
            }
        )
    return spans


def _parse_interface_methods(text: str) -> list[dict[str, Any]]:
    """Parse method declarations from Java interface bodies.

    Interface methods differ from class methods:
    - No explicit access modifier required (implicitly public)
    - End with ``;`` instead of ``{`` (no method body)
    - ``default`` and ``static`` methods have bodies (end with ``{``)
    """
    spans: list[dict[str, Any]] = []
    iface_pattern = re.compile(r"\binterface\s+\w+[^{]*\{", re.M)
    for m in iface_pattern.finditer(text):
        body_start = m.end()
        body_end = _matching_brace_end(text, body_start - 1)
        body = text[body_start:body_end]

        # 1) Abstract methods ending with ;
        abstract_pattern = re.compile(
            r"(?:@\w+(?:\([^)]*\))?\s*)*"
            r"(?:public\s+|private\s+|protected\s+)?"
            r"(?:default\s+)?"
            r"(?:static\s+)?"
            r"([\w<>, ?\.\[\]]+)\s+"
            r"(\w+)\s*\(([^;{}]*)\)\s*"
            r"(?:throws\s+[\w, ]+\s*)?;",
            re.M,
        )
        for method_m in abstract_pattern.finditer(body):
            method_name = method_m.group(2)
            params = method_m.group(3)
            abs_start = body_start + method_m.start()
            abs_end = body_start + method_m.end()
            spans.append(
                {
                    "name": method_name,
                    "params": params,
                    "start": abs_start,
                    "end": abs_end,
                    "line": _line_of(text, abs_start),
                    # Abstract interface methods (and ``@interface`` element
                    # declarations) are *declarations*, not call sites. They
                    # have no body. Without this flag the bare-call pass in
                    # ``_parse_method_calls`` matches the method's own signature
                    # inside ``start..end`` and produces a spurious self-call
                    # (e.g. ``Service:pageByDto -> Service:pageByDto``).
                    "is_declaration": True,
                }
            )

        # 2) default / static methods with a body (ending with {)
        body_method_pattern = re.compile(
            r"(?:@\w+(?:\([^)]*\))?\s*)*"
            r"(?:default|static)\s+"
            r"[\w<>, ?\.\[\]]+\s+"
            r"(\w+)\s*\(([^)]*)\)\s*"
            r"(?:throws\s+[\w, ]+\s*)?\{",
            re.M,
        )
        for method_m in body_method_pattern.finditer(body):
            method_name = method_m.group(1)
            params = method_m.group(2)
            abs_start = body_start + method_m.start()
            brace_end = _matching_brace_end(body, method_m.end() - 1)
            abs_end = body_start + brace_end
            spans.append(
                {
                    "name": method_name,
                    "params": params,
                    "start": abs_start,
                    "end": abs_end,
                    "line": _line_of(text, abs_start),
                }
            )

    return spans


def _build_method_signatures(method_spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    signatures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for span in method_spans:
        name = str(span.get("name", "") or "")
        parameter_types = _parameter_types(str(span.get("params", "") or ""))
        identity = f"{name}({','.join(parameter_types)})"
        if not name or identity in seen:
            continue
        seen.add(identity)
        signatures.append(
            {
                "identity": identity,
                "name": name,
                "parameter_types": parameter_types,
                "return_type": str(span.get("return_type", "") or ""),
                "line": int(span.get("line", 0) or 0),
            }
        )
    return sorted(signatures, key=lambda item: (int(item.get("line", 0)), item["identity"]))


def _parameter_types(params: str) -> list[str]:
    types: list[str] = []
    for part in _split_top_level(params):
        cleaned = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", part).strip()
        cleaned = re.sub(r"\b(?:final|volatile|transient)\s+", "", cleaned).strip()
        match = re.match(r"(.+?)\s+[A-Za-z_$][\w$]*(?:\s*\[\])?$", cleaned)
        if not match:
            continue
        types.append(_normalize_type_identity(match.group(1)))
    return types


def _split_top_level(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(value):
        if char in "<([{":
            depth += 1
        elif char in ">)]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _normalize_type_identity(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip())
    normalized = re.sub(r"\s*,\s*", ",", normalized)
    normalized = re.sub(r"\s*<\s*", "<", normalized)
    normalized = re.sub(r"\s*>\s*", ">", normalized)
    normalized = normalized.replace("...", "[]")
    return normalized


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
                if text[pos] == "\\":
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
                if text[pos] == "\\":
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


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _parse_bean_injections(text: str, classes: list[str], field_types: dict[str, str]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    # @Autowired / @Resource field injection
    pattern = re.compile(
        r"(?P<ann>@(?:Autowired|Resource|Inject)(?:\([^)]*\))?\s*)+"
        r"(?:private|protected|public)?\s*"
        r"(?P<type>[\w<>\.]+)\s+(?P<name>\w+)\s*;",
        re.M,
    )
    for m in pattern.finditer(text):
        facts.append(
            {
                "field_name": m.group("name"),
                "type": _simple_type(m.group("type")),
                "annotation": m.group("ann").strip(),
                "line": _line_of(text, m.start()),
            }
        )

    # Lombok constructor injection via final fields in @RequiredArgsConstructor classes
    if "@RequiredArgsConstructor" in text:
        final_pattern = re.compile(r"private\s+final\s+(?P<type>[\w<>\.]+)\s+(?P<name>\w+)\s*;", re.M)
        for m in final_pattern.finditer(text):
            facts.append(
                {
                    "field_name": m.group("name"),
                    "type": _simple_type(m.group("type")),
                    "annotation": "@RequiredArgsConstructor",
                    "line": _line_of(text, m.start()),
                }
            )
    facts.extend(_parse_constructor_injections(text, classes, field_types, facts))
    return facts


def _parse_constructor_injections(
    text: str,
    classes: list[str],
    field_types: dict[str, str],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen = {(item.get("field_name"), item.get("type")) for item in existing}
    facts: list[dict[str, Any]] = []
    final_fields = {
        name: typ
        for name, typ in field_types.items()
        if re.search(rf"\bfinal\s+[\w<>\.]+\s+{re.escape(name)}\s*;", text)
    }
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
                facts.append(
                    {
                        "field_name": field_name,
                        "type": _simple_type(field_type),
                        "annotation": "@Constructor",
                        "line": _line_of(text, m.start()),
                    }
                )
                seen.add(fact)
    return facts


def _parse_params(params: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in _split_top_level(params):
        cleaned = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", part).strip()
        cleaned = re.sub(r"\b(?:final|volatile|transient)\s+", "", cleaned).strip()
        match = re.match(r"(.+?)\s+([A-Za-z_$][\w$]*)(?:\s*\[\])?$", cleaned)
        if match:
            out[match.group(2)] = _simple_type(match.group(1))
    return out


def _parse_method_variable_types(text: str, method_spans: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    ambiguous: dict[str, set[str]] = {}
    for span in method_spans:
        method_name = str(span.get("name") or "")
        if not method_name:
            continue
        merged = out.setdefault(method_name, {})
        conflicts = ambiguous.setdefault(method_name, set())
        for variable, variable_type in _method_span_variable_types(text, span).items():
            if variable in conflicts:
                continue
            previous = merged.get(variable)
            if previous and previous != variable_type:
                merged.pop(variable, None)
                conflicts.add(variable)
                continue
            merged[variable] = variable_type
    return out


def _method_span_variable_types(text: str, span: dict[str, Any]) -> dict[str, str]:
    """Extract variables for one overload without leaking sibling scopes."""

    local_decl = re.compile(
        r"(?:^|[;{]\s*|\n\s*)"
        r"(?:final\s+)?(?P<type>[\w<>, ?\.\[\]]+)\s+"
        r"(?P<name>[a-zA-Z_]\w*)\s*(?:=|;)",
        re.M,
    )
    foreach_decl = re.compile(r"for\s*\(\s*(?:final\s+)?(?P<type>[\w<>, ?\.\[\]]+)\s+(?P<name>[a-zA-Z_]\w*)\s*:", re.M)
    resource_decl = re.compile(r"try\s*\(\s*(?:final\s+)?(?P<type>[\w<>, ?\.\[\]]+)\s+(?P<name>[a-zA-Z_]\w*)\s*=", re.M)
    catch_decl = re.compile(
        r"catch\s*\(\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:final\s+)?"
        r"(?P<type>[\w<>\.\[\]]+(?:\s*\|\s*[\w<>\.\[\]]+)*)\s+"
        r"(?P<name>[a-zA-Z_]\w*)\s*\)",
        re.M,
    )
    variables = _parse_params(span.get("params", ""))
    body = text[int(span["start"]) : int(span["end"])]
    for match in local_decl.finditer(body):
        variables.setdefault(match.group("name"), _simple_type(match.group("type")))
    for match in foreach_decl.finditer(body):
        variables.setdefault(match.group("name"), _simple_type(match.group("type")))
    for match in resource_decl.finditer(body):
        variables.setdefault(match.group("name"), _simple_type(match.group("type")))
    for match in catch_decl.finditer(body):
        catch_type = match.group("type")
        # Multi-catch has more than one possible runtime type. Keeping it
        # unresolved is safer than selecting the first arm and emitting a
        # potentially false workspace call edge.
        if "|" not in catch_type:
            variables.setdefault(match.group("name"), _simple_type(catch_type))
    return variables


def _parse_generic_field_types(text: str) -> dict[str, str]:
    pattern = re.compile(
        r"\b(?:private|protected|public)\s+"
        r"(?:(?:static|final|volatile|transient)\s+)*"
        r"(?P<type>[A-Za-z_$][\w.$]*\s*<[\w.$<>, ?\[\]]+>)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:=|;)",
        re.M,
    )
    return {match.group("name"): match.group("type").strip() for match in pattern.finditer(text)}


def _method_span_generic_variable_types(text: str, span: dict[str, Any]) -> dict[str, str]:
    variables = _parse_generic_params(str(span.get("params") or ""))
    local_pattern = re.compile(
        r"(?:^|[;{]\s*|\n\s*)"
        r"(?:final\s+)?(?P<type>[A-Za-z_$][\w.$]*\s*<[\w.$<>, ?\[\]]+>)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*(?:=|;)",
        re.M,
    )
    method_text = text[int(span["start"]) : int(span["end"])]
    for match in local_pattern.finditer(method_text):
        variables.setdefault(match.group("name"), match.group("type").strip())
    return variables


def _parse_generic_params(params: str) -> dict[str, str]:
    variables: dict[str, str] = {}
    for part in _split_top_level(params):
        cleaned = re.sub(r"@\w+(?:\([^)]*\))?\s*", "", part).strip()
        cleaned = re.sub(r"\b(?:final|volatile|transient)\s+", "", cleaned).strip()
        match = re.match(
            r"(?P<type>[A-Za-z_$][\w.$]*\s*<[\w.$<>, ?\[\]]+>)\s+"
            r"(?P<name>[A-Za-z_$][\w$]*)$",
            cleaned,
        )
        if match:
            variables[match.group("name")] = match.group("type").strip()
    return variables


def _parse_lambda_scopes(body: str, generic_variable_types: dict[str, str]) -> list[dict[str, Any]]:
    if "->" not in body:
        return []
    scopes: list[dict[str, Any]] = []
    for match in _LAMBDA_PATTERN.finditer(body):
        params_text = match.group("params").strip()
        inner_params = params_text[1:-1] if params_text.startswith("(") else params_text
        variables = _parse_params(inner_params)
        origin = ""
        if variables:
            # Explicitly typed lambda parameters are declared in source.
            origin = "lambda_param"
        if not variables:
            prefix = body[max(0, match.start() - 500) : match.start()]
            target = _FUNCTIONAL_TARGET_PATTERN.search(prefix)
            if target:
                generic_types = [_simple_type(item) for item in _split_top_level(target.group("generics"))]
                parameter_names = [item.strip() for item in _split_top_level(inner_params)]
                input_indexes = _FUNCTIONAL_INTERFACE_INPUTS[target.group("interface")]
                if len(parameter_names) == len(input_indexes) and all(name.isidentifier() for name in parameter_names):
                    for name, type_index in zip(parameter_names, input_indexes, strict=True):
                        if type_index < len(generic_types) and generic_types[type_index]:
                            variables[name] = generic_types[type_index]
                    if variables:
                        origin = "lambda_param"
            if not variables:
                variables.update(_jdk_collection_lambda_types(prefix, inner_params, generic_variable_types))
                if variables:
                    origin = "lambda_param"
            if not variables:
                class_literal_type = _class_literal_lambda_type(prefix, inner_params)
                if class_literal_type:
                    # Heuristic: the callee signature is not visible here, so
                    # keep this origin distinct from the provable lambda_param.
                    origin = "class_literal_lambda"
                    for name in _split_top_level(inner_params):
                        variables[name.strip()] = class_literal_type
        if not variables:
            continue
        expression_start = match.end()
        while expression_start < len(body) and body[expression_start].isspace():
            expression_start += 1
        if expression_start < len(body) and body[expression_start] == "{":
            expression_end = _matching_brace_end(body, expression_start)
        else:
            expression_end = _lambda_expression_end(body, expression_start)
        scopes.append({"start": expression_start, "end": expression_end, "variables": variables, "origin": origin})
    return scopes


def _class_literal_lambda_type(prefix: str, inner_params: str) -> str:
    """Infer a single lambda parameter type from an adjacent ``X.class`` argument.

    Covers generic factory idioms such as
    ``randomPojo(UserDO.class, o -> o.setStatus(...))`` where the callee
    declares ``<T> T randomPojo(Class<T>, Consumer<T>...)``. The callee
    signature is not visible to the regex parser, so this stays a heuristic:
    it only fires for exactly one untyped parameter whose invocation argument
    list contains a class literal.
    """
    parameter_names = [item.strip() for item in _split_top_level(inner_params)]
    if len(parameter_names) != 1 or not parameter_names[0].isidentifier():
        return ""
    open_match = None
    depth = 0
    for index in range(len(prefix) - 1, -1, -1):
        char = prefix[index]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth == 0:
                open_match = index
                break
            depth -= 1
    if open_match is None:
        return ""
    invocation_name = prefix[:open_match].rstrip()
    if not re.search(r"[A-Za-z_$][\w$]*$", invocation_name):
        return ""
    literal = re.search(r"(?P<type>[A-Z][\w$]*)\.class\b", prefix[open_match + 1 :])
    return _simple_type(literal.group("type")) if literal else ""


def _jdk_collection_lambda_types(
    prefix: str,
    inner_params: str,
    generic_variable_types: dict[str, str],
) -> dict[str, str]:
    parameter_names = [item.strip() for item in _split_top_level(inner_params)]
    if not parameter_names or not all(name.isidentifier() for name in parameter_names):
        return {}

    direct = re.search(
        rf"(?P<source>[A-Za-z_$][\w$]*)\s*\.\s*"
        rf"(?P<operation>{'|'.join(sorted(_JDK_COLLECTION_ELEMENT_OPERATIONS))})\s*\(\s*$",
        prefix,
        re.S,
    )
    streamed = re.search(
        rf"(?P<source>[A-Za-z_$][\w$]*)\s*\.\s*stream\s*\(\s*\)\s*\.\s*"
        rf"(?P<operation>{'|'.join(sorted(_JDK_STREAM_INPUT_OPERATIONS))})\s*\(\s*$",
        prefix,
        re.S,
    )
    stream_variable = re.search(
        rf"(?P<source>[A-Za-z_$][\w$]*)\s*\.\s*"
        rf"(?P<operation>{'|'.join(sorted(_JDK_STREAM_INPUT_OPERATIONS))})\s*\(\s*$",
        prefix,
        re.S,
    )
    invocation = streamed or direct or stream_variable
    if not invocation:
        return {}
    source_type = generic_variable_types.get(invocation.group("source"), "")
    raw_type, generic_arguments = _generic_type_parts(source_type)
    if not raw_type or not generic_arguments:
        return {}

    if direct and invocation.group("operation") == "forEach" and raw_type == "Map" and len(parameter_names) == 2 and len(generic_arguments) == 2:
        inferred = generic_arguments
    elif len(parameter_names) == 1 and (
        raw_type in _JDK_COLLECTION_TYPES or (stream_variable and raw_type == "Stream")
    ):
        inferred = generic_arguments[:1]
    else:
        return {}
    if len(inferred) != len(parameter_names) or any(_generic_argument_is_ambiguous(item) for item in inferred):
        return {}
    return {name: _simple_type(type_name) for name, type_name in zip(parameter_names, inferred, strict=True)}


def _generic_type_parts(type_name: str) -> tuple[str, list[str]]:
    match = re.match(r"\s*(?P<raw>[\w.$]+)\s*<(?P<arguments>.*)>\s*$", type_name)
    if not match:
        return "", []
    return match.group("raw").split(".")[-1], _split_top_level(match.group("arguments"))


def _generic_argument_is_ambiguous(type_name: str) -> bool:
    normalized = type_name.strip()
    return not normalized or "?" in normalized or bool(re.fullmatch(r"[A-Z]", normalized))


def _lambda_expression_end(text: str, start: int) -> int:
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    pos = start
    while pos < len(text):
        char = text[pos]
        if char in {'"', "'"}:
            quote = char
            pos += 1
            while pos < len(text):
                if text[pos] == "\\":
                    pos += 2
                elif text[pos] == quote:
                    pos += 1
                    break
                else:
                    pos += 1
            continue
        if char in depths:
            depths[char] += 1
        elif char in closing:
            opener = closing[char]
            if depths[opener] == 0:
                return pos
            depths[opener] -= 1
        elif char in {",", ";"} and not any(depths.values()):
            return pos
        pos += 1
    return len(text)


def _lambda_receiver_type(scopes: list[dict[str, Any]], position: int, receiver: str) -> tuple[str, str]:
    candidates = [
        scope
        for scope in scopes
        if int(scope["start"]) <= position < int(scope["end"]) and receiver in scope["variables"]
    ]
    if not candidates:
        return "", ""
    scope = min(candidates, key=lambda item: int(item["end"]) - int(item["start"]))
    return str(scope["variables"].get(receiver) or ""), str(scope.get("origin") or "")


def _parse_method_calls(
    text: str,
    method_spans: list[dict[str, Any]],
    field_types: dict[str, str],
    generic_field_types: dict[str, str],
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    # Use a lookahead so nested calls remain visible. A consuming match for
    # ``items.forEach(item -> item.submit())`` used to swallow ``item.submit``
    # together with the outer invocation.
    qualified_pattern = re.compile(
        r"(?=(?P<receiver>\b[a-zA-Z_]\w*)\s*\.\s*(?P<method>[a-zA-Z_]\w*)\s*\((?P<args>[^)]*)\))",
        re.M,
    )
    chained_pattern = re.compile(
        r"(?P<receiver>\b[a-zA-Z_]\w*)\s*\.\s*(?P<first>[a-zA-Z_]\w*)\s*\((?P<first_args>[^)]*)\)\s*\.\s*(?P<method>[a-zA-Z_]\w*)\s*\((?P<args>[^)]*)\)",
        re.M,
    )
    bare_pattern = re.compile(r"(?<![\.\w])(?P<method>[a-zA-Z_]\w*)\s*\((?P<args>[^)]*)\)", re.M)
    ignored = {
        "log",
        "logger",
        "System",
        "Objects",
        "String",
        "Collections",
        "Arrays",
        "Optional",
        "Map",
        "List",
        "Set",
    }
    ignored_methods = {
        "stream",
        "map",
        "filter",
        "collect",
        "of",
        "empty",
        "println",
        "if",
        "for",
        "while",
        "switch",
        "catch",
        "return",
    }
    seen: set[tuple[int, str, str]] = set()
    for span in method_spans:
        # Skip declaration-only spans (abstract interface methods,
        # ``@interface`` element declarations). Their ``start..end``
        # contains only the signature, not a method body, and treating
        # them as bodies makes the bare-call regex match the method's
        # own signature -- producing a fake ``Class:m -> Class:m``
        # self-call edge after resolution.
        if span.get("is_declaration"):
            continue
        body_start = int(span.get("body_start") or span.get("start") or 0)
        body_end = max(body_start, int(span.get("end") or body_start))
        body = text[body_start:body_end]
        owner_method = str(span.get("name") or "")
        span_variable_types = _method_span_variable_types(text, span)
        generic_variable_types = dict(generic_field_types)
        generic_variable_types.update(_method_span_generic_variable_types(text, span))
        lambda_scopes = _parse_lambda_scopes(body, generic_variable_types)
        for m in chained_pattern.finditer(body):
            # ``foo.bar(convert(value).setFlag(flag))`` is not a chain on
            # ``foo``. The regex cannot balance nested invocation arguments,
            # so accepting it would manufacture ``foo.setFlag``. Leave the
            # nested expression unexpanded until a syntax-aware parser can
            # prove its receiver type.
            if "(" in (m.group("first_args") or ""):
                continue
            receiver = m.group("receiver")
            chained_lambda_type, chained_lambda_origin = _lambda_receiver_type(lambda_scopes, m.start(), receiver)
            calls.append(
                {
                    "receiver": receiver,
                    "receiver_type": chained_lambda_type
                    or span_variable_types.get(receiver)
                    or field_types.get(receiver),
                    "receiver_type_origin": chained_lambda_origin if chained_lambda_type else "",
                    "method_name": m.group("method"),
                    "owner_method": owner_method,
                    "line": _line_of(text, body_start + m.start()),
                    "arg_count": len(_split_top_level(m.group("args") or "")),
                    "chain_receiver_method": m.group("first"),
                }
            )
        for m in qualified_pattern.finditer(body):
            receiver = m.group("receiver")
            method = m.group("method")
            if receiver in ignored or method in ignored_methods:
                continue
            absolute_method_pos = body_start + m.start("method")
            qualified_lambda_type, qualified_lambda_origin = _lambda_receiver_type(lambda_scopes, m.start(), receiver)
            receiver_type = (
                qualified_lambda_type
                or span_variable_types.get(receiver)
                or field_types.get(receiver)
            )
            receiver_type_origin = qualified_lambda_origin if qualified_lambda_type else ""
            seen.add((absolute_method_pos, receiver, method))
            calls.append(
                {
                    "receiver": receiver,
                    "receiver_type": receiver_type,
                    "receiver_type_origin": receiver_type_origin,
                    "method_name": method,
                    "owner_method": owner_method,
                    "line": _line_of(text, body_start + m.start()),
                    "arg_count": len(_split_top_level(m.group("args") or "")),
                }
            )
        for m in bare_pattern.finditer(body):
            absolute_method_pos = body_start + m.start("method")
            method = m.group("method")
            key = (absolute_method_pos, "", method)
            if key in seen or method in ignored_methods or _preceded_by_new_keyword(text, absolute_method_pos):
                continue
            calls.append(
                {
                    "receiver": "",
                    "receiver_type": "",
                    "method_name": method,
                    "owner_method": span.get("name"),
                    "line": _line_of(text, body_start + m.start()),
                    "arg_count": len(_split_top_level(m.group("args") or "")),
                }
            )
    return calls


def _preceded_by_new_keyword(text: str, pos: int) -> bool:
    prefix = text[max(0, pos - 8) : pos]
    return bool(re.search(r"\bnew\s+$", prefix))


def _parse_dto_field_usages(
    text: str,
    method_spans: list[dict[str, Any]],
    field_types: dict[str, str],
    generic_field_types: dict[str, str],
) -> list[dict[str, Any]]:
    usages: list[dict[str, Any]] = []
    pattern = re.compile(r"(?P<receiver>\b[a-zA-Z_]\w*)\s*\.\s*(?P<accessor>get|set|is)(?P<field>[A-Z]\w*)\s*\(", re.M)
    for span in method_spans:
        if span.get("is_declaration"):
            continue
        body_start = int(span.get("body_start") or span.get("start") or 0)
        body_end = max(body_start, int(span.get("end") or body_start))
        body = text[body_start:body_end]
        owner_method = str(span.get("name") or "")
        span_variable_types = _method_span_variable_types(text, span)
        generic_variable_types = dict(generic_field_types)
        generic_variable_types.update(_method_span_generic_variable_types(text, span))
        lambda_scopes = _parse_lambda_scopes(body, generic_variable_types)
        for m in pattern.finditer(body):
            receiver = m.group("receiver")
            field = m.group("field")
            field_name = field[:1].lower() + field[1:]
            usages.append(
                {
                    "receiver": receiver,
                    "receiver_type": (
                        _lambda_receiver_type(lambda_scopes, m.start(), receiver)[0]
                        or span_variable_types.get(receiver)
                        or field_types.get(receiver)
                    ),
                    "accessor": m.group("accessor"),
                    "field": field_name,
                    "owner_method": owner_method,
                    "line": _line_of(text, body_start + m.start()),
                }
            )
    return usages


def _parse_config_usages(text: str) -> list[dict[str, Any]]:
    usages: list[dict[str, Any]] = []
    for m in re.finditer(r"@Value\s*\(\s*\"\$\{([^}:\"]+)(?::[^\"]*)?}\"\s*\)", text):
        usages.append({"key": m.group(1), "line": _line_of(text, m.start()), "annotation": "@Value"})
    for m in re.finditer(r"@ConfigurationProperties\s*\(\s*(?:prefix\s*=\s*)?\"([^\"]+)\"\s*\)", text):
        usages.append({"key": m.group(1), "line": _line_of(text, m.start()), "annotation": "@ConfigurationProperties"})
    return usages


def _parse_data_resources(text: str) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for m in re.finditer(r"@Document\s*\(([^)]*)\)", text, flags=re.S):
        args = m.group(1)
        name = _named_or_first_string(args, "collection") or _named_or_first_string(args, "value")
        if name:
            resources.append(
                {"kind": "MongoCollection", "name": name, "operation": "declares", "line": _line_of(text, m.start())}
            )
    for m in re.finditer(r"(?:getCollection|collectionName)\s*\(\s*\"([^\"]+)\"\s*\)", text):
        resources.append(
            {"kind": "MongoCollection", "name": m.group(1), "operation": "uses", "line": _line_of(text, m.start())}
        )
    for m in re.finditer(r"(?:indexName|IndexName|index)\s*=\s*\"([^\"]+)\"", text):
        resources.append(
            {"kind": "EsIndex", "name": m.group(1), "operation": "uses", "line": _line_of(text, m.start())}
        )
    if "ElasticsearchRestTemplate" in text or "elasticsearch" in text.lower():
        resources.append({"kind": "EsIndex", "name": "unknown-es-index", "operation": "uses-template", "line": 1})
    if "MongoTemplate" in text or "mongoTemplate" in text:
        resources.append(
            {"kind": "MongoCollection", "name": "unknown-mongo-collection", "operation": "uses-template", "line": 1}
        )
    return resources


def _simple_type(value: str) -> str:
    return value.strip().split(".")[-1].split("<")[0]


def _named_or_first_string(args: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*=\s*\"([^\"]+)\"", args or "")
    if m:
        return m.group(1)
    m = re.search(r'"([^"]+)"', args or "")
    return m.group(1) if m else None
