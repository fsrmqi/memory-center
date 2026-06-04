"""Tree-sitter Java parser — optional high-accuracy parser.

Falls back to RegexJavaParser when tree-sitter is unavailable.
Same JavaParser protocol as RegexJavaParser.
"""
from __future__ import annotations

from typing import Any

from .base import JavaParseResult

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
        if _HAS_TREE_SITTER:
            self._parser = Parser(Language(tsjava.language()))
        else:
            self._parser = None

    @property
    def available(self) -> bool:
        return _HAS_TREE_SITTER

    def parse(self, text: str, file_path: str) -> JavaParseResult:
        if not self._parser:
            # Fallback to regex parser
            from .java_regex_parser import RegexJavaParser
            return RegexJavaParser().parse(text, file_path)

        tree = self._parser.parse(text.encode("utf-8"))
        root = tree.root_node

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
                    if child.type == "scoped_identifier":
                        package = child.text.decode("utf-8")
            elif node.type == "import_declaration":
                for child in node.children:
                    if child.type == "scoped_identifier":
                        imports.append(child.text.decode("utf-8"))
            elif node.type in ("class_declaration", "enum_declaration", "record_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    classes.append(name_node.text.decode("utf-8"))
            elif node.type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    interfaces.append(name_node.text.decode("utf-8"))
            elif node.type == "annotation":
                name_node = node.child_by_field_name("name")
                if name_node:
                    annotations.append(name_node.text.decode("utf-8"))
            elif node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    methods.append(name_node.text.decode("utf-8"))
            elif node.type == "field_declaration":
                # Extract field name and type
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            fname = name_node.text.decode("utf-8")
                            fields.append(fname)
                            # Find type from parent
                            type_child = node.children[0] if node.children else None
                            if type_child and type_child.type != "variable_declarator":
                                field_types[fname] = type_child.text.decode("utf-8")

            for child in node.children:
                _walk(child, depth + 1)

        _walk(root)

        return JavaParseResult(
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
