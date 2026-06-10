"""Tree-sitter Java parser — optional high-accuracy parser.

Falls back to RegexJavaParser when tree-sitter is unavailable.
Same JavaParser protocol as RegexJavaParser.
"""
from __future__ import annotations

import json
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
        if _HAS_TREE_SITTER:
            try:
                self._parser = Parser(Language(tsjava.language()))
            except Exception:
                self._parser = None

    @property
    def available(self) -> bool:
        return self._parser is not None

    def parse(self, text: str, file_path: str) -> JavaParseResult:
        regex_result = RegexJavaParser().parse(text, file_path)
        if not self._parser:
            return regex_result

        try:
            tree = self._parser.parse(text.encode("utf-8"))
            root = tree.root_node
        except Exception:
            return regex_result

        package = ""
        imports: list[str] = []
        classes: list[str] = []
        interfaces: list[str] = []
        annotations: list[str] = []
        methods: list[str] = []
        fields: list[str] = []
        field_types: dict[str, str] = {}

        def _walk(node, depth=0):
            nonlocal package
            if node.type == "package_declaration":
                # Extract package name
                for child in node.children:
                    if child.type in {"scoped_identifier", "identifier"}:
                        package = _node_text(child)
            elif node.type == "import_declaration":
                for child in node.children:
                    if child.type in {"scoped_identifier", "identifier", "asterisk"}:
                        imports.append(_node_text(child))
            elif node.type in ("class_declaration", "enum_declaration", "record_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    classes.append(_node_text(name_node))
            elif node.type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    interfaces.append(_node_text(name_node))
            elif node.type == "annotation" or node.type.endswith("_annotation"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    annotations.append(_simple_name(_node_text(name_node)))
            elif node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    methods.append(_node_text(name_node))
            elif node.type == "field_declaration":
                type_node = node.child_by_field_name("type")
                type_text = _node_text(type_node) if type_node else ""
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            fname = _node_text(name_node)
                            fields.append(fname)
                            if type_text:
                                field_types[fname] = type_text

            for child in node.children:
                _walk(child, depth + 1)

        _walk(root)

        tree_result = JavaParseResult(
            package=package,
            imports=imports,
            classes=classes,
            interfaces=interfaces,
            methods=methods,
            fields=fields,
            annotations=sorted(set(annotations)),
            field_types=field_types,
            method_variable_types={},
            bean_injections=[],
            method_calls=[],
            dto_field_usages=[],
            config_usages=[],
            data_resources=[],
        )
        return _merge_parse_results(tree_result, regex_result)


def _node_text(node: Any) -> str:
    if node is None:
        return ""
    value = getattr(node, "text", b"")
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _simple_name(value: str) -> str:
    return value.split(".")[-1].strip()


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
        methods=_merge_unique_strings(tree_result.methods, regex_result.methods),
        fields=_merge_unique_strings(tree_result.fields, regex_result.fields),
        annotations=_merge_unique_strings(tree_result.annotations, regex_result.annotations),
        field_types=field_types,
        method_variable_types=method_variable_types,
        bean_injections=_merge_unique_dicts(tree_result.bean_injections, regex_result.bean_injections),
        method_calls=_merge_unique_dicts(tree_result.method_calls, regex_result.method_calls),
        dto_field_usages=_merge_unique_dicts(tree_result.dto_field_usages, regex_result.dto_field_usages),
        config_usages=_merge_unique_dicts(tree_result.config_usages, regex_result.config_usages),
        data_resources=_merge_unique_dicts(tree_result.data_resources, regex_result.data_resources),
    )
