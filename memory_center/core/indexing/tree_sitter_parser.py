"""Tree-sitter Java parser — optional high-accuracy parser.

Falls back to RegexJavaParser when tree-sitter is unavailable.
Same JavaParser protocol as RegexJavaParser.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from .base import JavaParseResult
from .java_regex_parser import RegexJavaParser

# Try to import tree_sitter
try:
    import tree_sitter_java as tsjava
    from tree_sitter import Language, Parser
    _HAS_TREE_SITTER = True
except ImportError:
    _HAS_TREE_SITTER = False


class TreeSitterJavaParser:
    """High-accuracy Java parser using tree-sitter.

    Falls back gracefully when tree-sitter is not installed.
    Same output format as RegexJavaParser (JavaParseResult).
    """

    name = "tree-sitter"

    def __init__(self):
        self._parser = None
        self._diagnostics_lock = threading.Lock()
        self._local = threading.local()
        self.reset_diagnostics()
        if _HAS_TREE_SITTER:
            try:
                self._parser = Parser(Language(tsjava.language()))
            except Exception:
                self._parser = None

    @property
    def available(self) -> bool:
        return self._parser is not None

    def parse(self, text: str, file_path: str) -> JavaParseResult:
        # tree-sitter unavailable / parse failed -> full regex fallback.
        if not self._parser:
            regex_result = RegexJavaParser().parse(text, file_path)
            self._local.selected_parser = "regex"
            self._record_parse(
                fallback_reason="tree_sitter_unavailable",
                full_regex_fallback=True,
            )
            return regex_result
        tree_result = self.parse_native(text, file_path)
        if tree_result is None:
            regex_result = RegexJavaParser().parse(text, file_path)
            self._local.selected_parser = "regex"
            self._record_parse(
                fallback_reason="tree_sitter_parse_error",
                full_regex_fallback=True,
            )
            return regex_result

        # Opt-in escape hatch: if differential gates ever regress in the
        # field, set ``MEMORY_CENTER_PARSER_FULL_DUAL=1`` to restore the
        # legacy behaviour (always run the full regex parser and merge).
        if _full_dual_enabled():
            regex_result = RegexJavaParser().parse(text, file_path)
            merged = _merge_parse_results(tree_result, regex_result)
            self._local.selected_parser = self.name
            self._record_parse(
                native_disagreements=_structural_missing_count(regex_result, tree_result),
                critical_disagreements=_structural_missing_count(regex_result, merged),
                full_regex_fallback=True,
            )
            return merged

        # Normal hot path: tree-sitter handles structural facts; regex runs
        # only the supplements tree-sitter does not yet cover. This skips
        # the ~58 s wall-clock that ``_parse_type_declarations`` /
        # ``_parse_fields`` / ``_build_method_signatures`` previously
        # contributed when called on every Java file in a 16K-file repo.
        supplements = RegexJavaParser().parse_supplements(
            text,
            file_path,
            classes=list(tree_result.classes) + list(tree_result.interfaces),
            field_types=tree_result.field_types,
        )
        merged = _merge_supplements(tree_result, supplements)
        self._local.selected_parser = self.name
        self._record_parse(supplement_call=True)
        return merged

    @property
    def selected_parser(self) -> str:
        return str(getattr(self._local, "selected_parser", self.name if self.available else "regex"))

    def reset_diagnostics(self) -> None:
        self._parse_count = 0
        self._native_success_count = 0
        self._fallback_count = 0
        self._fallback_reasons: dict[str, int] = {}
        self._native_disagreement_count = 0
        self._critical_disagreement_count = 0
        self._supplement_call_count = 0
        self._full_regex_fallback_count = 0

    @property
    def diagnostics(self) -> dict[str, Any]:
        with self._diagnostics_lock:
            return {
                "selected_parser": self.name if self.available else "regex",
                "tree_sitter_available": self.available,
                "parse_count": self._parse_count,
                "native_success_count": self._native_success_count,
                "fallback_count": self._fallback_count,
                "fallback_reasons": dict(sorted(self._fallback_reasons.items())),
                "native_disagreement_count": self._native_disagreement_count,
                "critical_disagreement_count": self._critical_disagreement_count,
                "supplement_call_count": self._supplement_call_count,
                "full_regex_fallback_count": self._full_regex_fallback_count,
                "full_dual_mode": _full_dual_enabled(),
            }

    def _record_parse(
        self,
        *,
        fallback_reason: str = "",
        native_disagreements: int = 0,
        critical_disagreements: int = 0,
        supplement_call: bool = False,
        full_regex_fallback: bool = False,
    ) -> None:
        with self._diagnostics_lock:
            self._parse_count += 1
            if fallback_reason:
                self._fallback_count += 1
                self._fallback_reasons[fallback_reason] = self._fallback_reasons.get(fallback_reason, 0) + 1
            else:
                self._native_success_count += 1
            self._native_disagreement_count += max(0, native_disagreements)
            self._critical_disagreement_count += max(0, critical_disagreements)
            if supplement_call:
                self._supplement_call_count += 1
            if full_regex_fallback:
                self._full_regex_fallback_count += 1

    def parse_native(self, text: str, file_path: str) -> JavaParseResult | None:
        """Return AST-only facts, or ``None`` when tree-sitter cannot parse."""
        if not self._parser:
            return None

        try:
            tree = self._parser.parse(text.encode("utf-8"))
            root = tree.root_node
        except Exception:
            return None

        # Use ``None`` for "no package declaration found" so the value
        # matches ``RegexJavaParser`` (which returns ``None`` from
        # ``_first_group``). Without this the supplements hot path was
        # producing ``""`` for default-package files while the legacy
        # full-dual path was producing ``None`` after the
        # ``tree.package or regex.package`` fallback.
        package: str | None = None
        imports: list[str] = []
        classes: list[str] = []
        interfaces: list[str] = []
        annotations: list[str] = []
        methods: list[str] = []
        method_signatures: list[dict[str, Any]] = []
        fields: list[str] = []
        class_lines: dict[str, int] = {}
        interface_lines: dict[str, int] = {}
        method_lines: dict[str, int] = {}
        field_lines: dict[str, int] = {}
        field_types: dict[str, str] = {}
        method_calls: list[dict[str, Any]] = []

        def _walk(node, depth=0, owner_method: str = ""):
            nonlocal package
            if node.type == "package_declaration":
                # Extract package name
                for child in node.children:
                    if child.type in {"scoped_identifier", "identifier"}:
                        nonlocal_package = _node_text(child)
                        if nonlocal_package:
                            package = nonlocal_package
            elif node.type == "import_declaration":
                # Build one import string per ``import`` statement so wildcard
                # imports stay attached to their package and ``import static``
                # keeps the ``static`` prefix. Tree-sitter emits the path
                # parts as siblings (``scoped_identifier`` + ``asterisk`` for
                # ``java.util.*``; an ``identifier`` child ``static`` for
                # static imports). Without this assembly each child would be
                # appended individually, producing ``['java.util', '*']``
                # instead of ``['java.util.*']``.
                is_static = False
                path_parts: list[str] = []
                has_wildcard = False
                for child in node.children:
                    child_type = child.type
                    if child_type == "static":
                        is_static = True
                        continue
                    if child_type == "identifier" and _node_text(child) == "static":
                        is_static = True
                        continue
                    if child_type == "asterisk":
                        has_wildcard = True
                        continue
                    if child_type in {"scoped_identifier", "identifier"}:
                        text = _node_text(child)
                        if text and text != "static":
                            path_parts.append(text)
                base = ".".join(path_parts)
                if base:
                    statement = f"{base}.*" if has_wildcard else base
                    if is_static:
                        statement = f"static {statement}"
                    imports.append(statement)
            elif node.type in ("class_declaration", "enum_declaration", "record_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    class_name = _node_text(name_node)
                    classes.append(class_name)
                    class_lines.setdefault(class_name, _node_line(name_node))
            elif node.type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    interface_name = _node_text(name_node)
                    interfaces.append(interface_name)
                    interface_lines.setdefault(interface_name, _node_line(name_node))
            elif node.type == "annotation_type_declaration":
                # ``public @interface XXX { ... }`` -- modelled as an
                # interface by ``RegexJavaParser`` (it treats ``@interface``
                # as ``interface`` for the purpose of cataloging the type
                # and its members), so mirror that here. Also push the
                # literal ``interface`` token into annotations to match the
                # legacy behaviour of ``@(\w+)`` regex matching ``@interface``.
                name_node = node.child_by_field_name("name")
                if name_node:
                    interface_name = _node_text(name_node)
                    interfaces.append(interface_name)
                    interface_lines.setdefault(interface_name, _node_line(name_node))
                annotations.append("interface")
            elif node.type == "annotation_type_element_declaration":
                # Methods inside ``@interface`` bodies; the regex parser
                # picks these up via ``_parse_interface_methods``.
                name_node = node.child_by_field_name("name")
                if name_node:
                    method_name = _node_text(name_node)
                    methods.append(method_name)
                    method_lines.setdefault(method_name, _node_line(name_node))
                    method_signatures.append(
                        {
                            "identity": f"{method_name}()",
                            "name": method_name,
                            "parameter_types": [],
                            "line": _node_line(name_node),
                        }
                    )
            elif node.type == "annotation" or node.type.endswith("_annotation"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    annotations.append(_simple_name(_node_text(name_node)))
            elif node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    method_name = _node_text(name_node)
                    methods.append(method_name)
                    method_lines.setdefault(method_name, _node_line(name_node))
                    parameter_types = _tree_parameter_types(node.child_by_field_name("parameters"))
                    method_signatures.append(
                        {
                            "identity": f"{method_name}({','.join(parameter_types)})",
                            "name": method_name,
                            "parameter_types": parameter_types,
                            "return_type": _normalize_type_identity(_node_text(node.child_by_field_name("type"))),
                            "line": _node_line(name_node),
                        }
                    )
                    owner_method = method_name
            elif node.type == "method_invocation" and owner_method:
                chain_call = _tree_sitter_chain_call(node, owner_method)
                if chain_call:
                    method_calls.append(chain_call)
            elif node.type == "field_declaration":
                type_node = node.child_by_field_name("type")
                type_text = _node_text(type_node) if type_node else ""
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            fname = _node_text(name_node)
                            fields.append(fname)
                            field_lines.setdefault(fname, _node_line(name_node))
                            if type_text:
                                field_types[fname] = type_text
            elif node.type == "constant_declaration":
                # ``interface X { String FOO = "bar"; }`` and
                # ``public static final String BAR = ...``. Tree-sitter
                # models these as ``constant_declaration`` (not
                # ``field_declaration``), so mirror the regex parser's
                # behaviour and treat them as fields.
                type_node = node.child_by_field_name("type")
                type_text = _node_text(type_node) if type_node else ""
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            fname = _node_text(name_node)
                            fields.append(fname)
                            field_lines.setdefault(fname, _node_line(name_node))
                            if type_text:
                                field_types[fname] = type_text

            for child in node.children:
                _walk(child, depth + 1, owner_method)

        _walk(root)

        tree_result = JavaParseResult(
            package=package,
            imports=imports,
            classes=classes,
            interfaces=interfaces,
            methods=methods,
            method_signatures=_merge_unique_dicts(method_signatures, []),
            fields=fields,
            class_lines=class_lines,
            interface_lines=interface_lines,
            method_lines=method_lines,
            field_lines=field_lines,
            annotations=sorted(set(annotations)),
            field_types=field_types,
            constants={},
            method_variable_types={},
            bean_injections=[],
            method_calls=_merge_unique_dicts(method_calls, []),
            dto_field_usages=[],
            config_usages=[],
            data_resources=[],
        )
        return tree_result


def _node_text(node: Any) -> str:
    if node is None:
        return ""
    value = getattr(node, "text", b"")
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _node_line(node: Any) -> int:
    if node is None:
        return 0
    start_point = getattr(node, "start_point", None)
    if isinstance(start_point, tuple) and start_point:
        try:
            return int(start_point[0]) + 1
        except Exception:
            return 0
    return 0


def _tree_sitter_chain_call(node: Any, owner_method: str) -> dict[str, Any] | None:
    """Extract one statically provable call-result chain from an AST node.

    Only ``receiver.first(...).second(...)`` is emitted. Longer chains are
    represented by their first resolvable transition, because advancing beyond
    it would require guessing an intermediate return type. This deliberately
    complements the regex supplement, which cannot balance nested arguments.
    """

    outer_object = node.child_by_field_name("object")
    outer_name = node.child_by_field_name("name")
    if outer_object is None or outer_object.type != "method_invocation" or outer_name is None:
        return None

    inner_object = outer_object.child_by_field_name("object")
    inner_name = outer_object.child_by_field_name("name")
    if inner_object is None or inner_name is None or inner_object.type == "method_invocation":
        return None

    receiver = _tree_sitter_chain_receiver(inner_object)
    if not receiver:
        return None
    arguments = node.child_by_field_name("arguments")
    inner_arguments = outer_object.child_by_field_name("arguments")
    return {
        "receiver": receiver,
        "receiver_type": receiver if receiver[:1].isupper() else "",
        "method_name": _node_text(outer_name),
        "owner_method": owner_method,
        "line": _node_line(node),
        "arg_count": len(getattr(arguments, "named_children", []) or []),
        "chain_receiver_method": _node_text(inner_name),
        "chain_arg_count": len(getattr(inner_arguments, "named_children", []) or []),
        "chain_argument_names": [
            _node_text(argument)
            for argument in getattr(inner_arguments, "named_children", []) or []
            if argument.type == "identifier" and _node_text(argument)
        ],
        "extraction": "tree_sitter_chain",
    }


def _tree_sitter_chain_receiver(node: Any) -> str:
    """Return the root receiver without inferring an unknown member type."""

    if node.type == "identifier":
        return _node_text(node)
    if node.type == "field_access":
        named = list(getattr(node, "named_children", []) or [])
        return _node_text(named[0]) if named else ""
    return ""


def _simple_name(value: str) -> str:
    return value.split(".")[-1].strip()


def _tree_parameter_types(parameters_node: Any) -> list[str]:
    if parameters_node is None:
        return []
    result: list[str] = []
    for child in getattr(parameters_node, "named_children", []):
        if child.type not in {"formal_parameter", "spread_parameter", "receiver_parameter"}:
            continue
        type_node = child.child_by_field_name("type")
        type_text = _node_text(type_node)
        if child.type == "spread_parameter" and type_text:
            type_text += "[]"
        if type_text:
            result.append(_normalize_type_identity(type_text))
    return result


def _normalize_type_identity(value: str) -> str:
    return "".join(str(value or "").split()).replace("...", "[]")


def _structural_missing_count(expected: JavaParseResult, actual: JavaParseResult) -> int:
    count = 0
    for field in ("classes", "interfaces", "fields"):
        count += len(set(getattr(expected, field)) - set(getattr(actual, field)))
    expected_methods = {item.get("identity") for item in expected.method_signatures if item.get("identity")}
    actual_methods = {item.get("identity") for item in actual.method_signatures if item.get("identity")}
    count += len(expected_methods - actual_methods)
    return count


def _merge_unique_strings(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in primary + secondary:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return merged


def _merge_unique_dicts(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in primary + secondary:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def _merge_line_maps(primary: dict[str, int], secondary: dict[str, int]) -> dict[str, int]:
    merged = dict(secondary)
    for name, line in primary.items():
        if int(line or 0) > 0:
            merged[name] = int(line)
    return merged


def _merge_parse_results(tree_result: JavaParseResult, regex_result: JavaParseResult) -> JavaParseResult:
    field_types = dict(regex_result.field_types)
    field_types.update(tree_result.field_types)
    method_variable_types = dict(regex_result.method_variable_types)
    method_variable_types.update(tree_result.method_variable_types)
    return JavaParseResult(
        package=tree_result.package or regex_result.package,
        imports=_merge_unique_strings(tree_result.imports, regex_result.imports),
        classes=_merge_unique_strings(tree_result.classes, regex_result.classes),
        interfaces=_merge_unique_strings(tree_result.interfaces, regex_result.interfaces),
        type_supertypes={**regex_result.type_supertypes, **tree_result.type_supertypes},
        methods=_merge_unique_strings(tree_result.methods, regex_result.methods),
        method_signatures=_merge_unique_dicts(tree_result.method_signatures, regex_result.method_signatures),
        fields=_merge_unique_strings(tree_result.fields, regex_result.fields),
        class_lines=_merge_line_maps(tree_result.class_lines, regex_result.class_lines),
        interface_lines=_merge_line_maps(tree_result.interface_lines, regex_result.interface_lines),
        method_lines=_merge_line_maps(tree_result.method_lines, regex_result.method_lines),
        field_lines=_merge_line_maps(tree_result.field_lines, regex_result.field_lines),
        annotations=_merge_unique_strings(tree_result.annotations, regex_result.annotations),
        field_types=field_types,
        constants={**regex_result.constants, **tree_result.constants},
        method_variable_types=method_variable_types,
        bean_injections=_merge_unique_dicts(tree_result.bean_injections, regex_result.bean_injections),
        method_calls=_merge_unique_dicts(tree_result.method_calls, regex_result.method_calls),
        dto_field_usages=_merge_unique_dicts(tree_result.dto_field_usages, regex_result.dto_field_usages),
        config_usages=_merge_unique_dicts(tree_result.config_usages, regex_result.config_usages),
        data_resources=_merge_unique_dicts(tree_result.data_resources, regex_result.data_resources),
    )


def _merge_supplements(tree_result: JavaParseResult, supplements: JavaParseResult) -> JavaParseResult:
    """Merge tree-sitter structural facts with regex-only supplements.

    Tree-sitter is authoritative for the structural fields it already
    produces (package / imports / classes / interfaces / methods /
    method_signatures / fields / annotations / field_types / *_lines);
    the supplements pass only populates ``constants``,
    ``method_variable_types``, ``bean_injections``, ``method_calls``,
    ``dto_field_usages``, ``config_usages``, ``data_resources``.

    ``field_types`` keeps tree-sitter values; regex-derived ``constants``
    are layered in to mirror ``RegexJavaParser.parse`` behaviour
    (``field_types.update(constants)``).
    """
    # Match RegexJavaParser.parse() merge order: ``field_types.update(constants)``
    # is applied first, then any tree-sitter-derived types take precedence.
    # Match the legacy ``_merge_parse_results`` field-types merge order:
    # ``regex.field_types`` first (regex behaviour itself did
    # ``field_types.update(constants)``), then tree-sitter values win.
    field_types = dict(supplements.constants)
    field_types.update(tree_result.field_types)
    method_variable_types = dict(tree_result.method_variable_types)
    method_variable_types.update(supplements.method_variable_types)
    # All list-typed fields go through the same dedup helpers as legacy
    # ``_merge_parse_results`` so the supplements hot path emits the same
    # value the legacy "full regex + merge" path emitted. Tree-sitter may
    # locally produce duplicates (e.g. method overloads, ``count`` field
    # repeated in inheritance), and ``_parse_*`` helpers on the regex side
    # do not internally dedup either; the legacy merge layer absorbed
    # both. Keep that behaviour here.
    return JavaParseResult(
        package=tree_result.package,
        imports=_merge_unique_strings(list(tree_result.imports), []),
        classes=_merge_unique_strings(list(tree_result.classes), []),
        interfaces=_merge_unique_strings(list(tree_result.interfaces), []),
        type_supertypes=dict(supplements.type_supertypes),
        methods=_merge_unique_strings(list(tree_result.methods), []),
        method_signatures=_merge_unique_dicts(
            list(tree_result.method_signatures),
            list(supplements.method_signatures),
        ),
        fields=_merge_unique_strings(list(tree_result.fields), []),
        class_lines=dict(tree_result.class_lines),
        interface_lines=dict(tree_result.interface_lines),
        method_lines=dict(tree_result.method_lines),
        field_lines=dict(tree_result.field_lines),
        annotations=_merge_unique_strings(list(tree_result.annotations), []),
        field_types=field_types,
        constants=dict(supplements.constants),
        method_variable_types=method_variable_types,
        bean_injections=_merge_unique_dicts([], list(supplements.bean_injections)),
        # Tree-sitter adds only AST-proven nested call chains. Regex remains
        # responsible for direct calls and variable-type extraction.
        method_calls=_merge_unique_dicts(list(tree_result.method_calls), list(supplements.method_calls)),
        dto_field_usages=_merge_unique_dicts([], list(supplements.dto_field_usages)),
        config_usages=_merge_unique_dicts([], list(supplements.config_usages)),
        data_resources=_merge_unique_dicts([], list(supplements.data_resources)),
    )


def _full_dual_enabled() -> bool:
    """Return True when ``MEMORY_CENTER_PARSER_FULL_DUAL`` opts back in to
    the legacy "always run full regex parser and merge" behaviour. Useful
    as a safety hatch if differential gates ever regress in production.
    """
    value = os.getenv("MEMORY_CENTER_PARSER_FULL_DUAL", "").strip().lower()
    return value in {"1", "true", "yes", "on"}
