"""Multi-language structural parser built on tree-sitter.

Walks a tree-sitter AST and emits a :class:`StructuralParseResult` for
Java / Kotlin / Python / TypeScript / TSX / JavaScript / Go. Each
language has its own walker function because tree-sitter node names
differ even when the underlying concepts (class, function, import,
call) are the same.

The walker design follows three rules:

1. **One pass per file.** We collect classes, functions, imports and
   calls in a single DFS to keep parse cost dominated by the underlying
   tree-sitter walk, not Python overhead.
2. **Qualified names are derived from the surrounding declaration
   stack.** A method ``run`` inside class ``Order`` inside package
   ``com.example`` becomes ``com.example.Order.run``. The stack tracks
   the in-progress qualified prefix.
3. **Unknown nodes are silently skipped.** Tree-sitter grammars evolve;
   we don't want a new node kind to crash the indexer. Anything we
   don't recognise is just walked through.

每种语言一个独立 walker;qualified name 由声明栈累积;未知节点静默跳过
以容忍 grammar 升级。
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .language_registry import LanguageSpec, get_language_spec
from .parse_result import CallSite, StructuralParseResult, SymbolSpan

# ── tree-sitter availability ────────────────────────────────────────────────

try:
    from tree_sitter import Language, Parser  # type: ignore[import-not-found]

    _HAS_TREE_SITTER = True
except ImportError:
    _HAS_TREE_SITTER = False


# ── Public parser class ─────────────────────────────────────────────────────


class TreeSitterStructuralParser:
    """Parse one language's source text into a structural result.

    One instance is bound to one language so the parser / language
    objects can be cached across calls (tree-sitter parsers are
    relatively expensive to construct). The instance is thread-safe for
    concurrent ``parse`` calls because the underlying tree-sitter
    objects are immutable after construction; the only mutable state is
    a per-instance counter used for diagnostics.
    """

    def __init__(self, language_name: str):
        self.language_name = language_name
        self.spec: LanguageSpec | None = get_language_spec(language_name)
        self._parser = None
        self._language = None
        self._init_error: str | None = None
        self._diagnostics_lock = threading.Lock()
        self._parse_lock = threading.Lock()
        self._parse_count = 0
        self._fail_count = 0

        if not _HAS_TREE_SITTER:
            self._init_error = "tree-sitter package not installed"
            return
        if self.spec is None:
            self._init_error = f"language not registered: {language_name!r}"
            return
        try:
            language_capsule = self.spec.load_language()
            self._language = Language(language_capsule)
            self._parser = Parser(self._language)
        except ModuleNotFoundError as exc:
            self._init_error = (
                f"binding for {language_name!r} not installed "
                f"(pip install 'memory-center[{self.spec.installed_with}]'); "
                f"underlying error: {exc.name}"
            )
        except Exception as exc:  # noqa: BLE001 — we surface the message
            self._init_error = f"failed to load {language_name!r}: {exc}"

    @property
    def available(self) -> bool:
        return self._parser is not None

    @property
    def init_error(self) -> str | None:
        return self._init_error

    @property
    def diagnostics(self) -> dict[str, Any]:
        with self._diagnostics_lock:
            return {
                "language": self.language_name,
                "available": self.available,
                "init_error": self._init_error,
                "parse_count": self._parse_count,
                "fail_count": self._fail_count,
            }

    def parse(self, source: str, file_path: str = "") -> StructuralParseResult:
        """Return the structural facts for ``source``.

        When the parser is unavailable (no tree-sitter or no binding),
        returns an empty result rather than raising — the indexer keeps
        running on other languages.
        """
        empty = StructuralParseResult(language=self.language_name)
        if not self._parser:
            return empty
        if self.language_name == "vue":
            return _parse_vue(source, file_path)
        try:
            with self._parse_lock:
                tree = self._parser.parse(source.encode("utf-8"))
        except Exception:
            with self._diagnostics_lock:
                self._fail_count += 1
            return empty
        walker = _WALKERS.get(self.language_name)
        if walker is None:
            return empty
        result = walker(tree.root_node, source)
        result.raw['parse_status'] = 'partial' if tree.root_node.has_error else 'parsed'
        result.raw['syntax_errors'] = bool(tree.root_node.has_error)
        _import_bindings(tree.root_node, source, result)
        with self._diagnostics_lock:
            self._parse_count += 1
        return result


# ── Walker helpers ──────────────────────────────────────────────────────────


def _node_text(node: Any, source: str) -> str:
    """Decode the slice of ``source`` covered by ``node``.

    Tree-sitter exposes ``node.text`` (bytes) but the encoding round-trip
    is wasteful when we already have the source string in hand. Slicing
    by byte offset is exact because tree-sitter operates on the same
    UTF-8 bytes.
    """
    if node is None:
        return ""
    try:
        start, end = node.start_byte, node.end_byte
        return source.encode("utf-8")[start:end].decode("utf-8", errors="replace")
    except Exception:
        value = getattr(node, "text", b"")
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)


def _node_line(node: Any) -> int:
    if node is None:
        return 0
    start_point = getattr(node, "start_point", None)
    if start_point is None:
        return 0
    # tree-sitter returns a 2-tuple (row, col) zero-indexed.
    return int(start_point[0]) + 1


def _node_end_line(node: Any) -> int:
    if node is None:
        return 0
    end_point = getattr(node, "end_point", None)
    if end_point is None:
        return 0
    return int(end_point[0]) + 1


def _named_child(node: Any, field_name: str) -> Any:
    """Tree-sitter ``child_by_field_name`` returns ``None`` for absent
    fields; this helper centralizes the access so walkers stay tidy."""
    if node is None:
        return None
    try:
        return node.child_by_field_name(field_name)
    except Exception:
        return None


# ── Java walker ─────────────────────────────────────────────────────────────


def _walk_java(root: Any, source: str) -> StructuralParseResult:
    result = StructuralParseResult(language="java")
    qual_stack: list[str] = []  # ["com.example", "Order"] etc.

    def qual(name: str) -> str:
        parts = [p for p in (*qual_stack, name) if p]
        return ".".join(parts)

    def visit(node: Any) -> None:
        if node is None:
            return
        kind = node.type
        if kind == "package_declaration":
            for child in node.children:
                if child.type in {"scoped_identifier", "identifier"}:
                    qual_stack.append(_node_text(child, source))
                    # Walk through siblings without descending into the
                    # package identifier itself.
                    for sib in node.children:
                        for c in sib.children:
                            visit(c)
                    return
        elif kind == "import_declaration":
            for child in node.children:
                if child.type in {"scoped_identifier", "identifier", "asterisk"}:
                    result.imports.append(_node_text(child, source))
            return
        elif kind in {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}:
            name_node = _named_child(node, "name")
            if name_node is not None:
                name = _node_text(name_node, source)
                parent = qual(name)  # qualified including this class
                span = SymbolSpan(
                    name=name,
                    qualified_name=parent,
                    line=_node_line(name_node),
                    end_line=_node_end_line(node),
                    parent_qualified_name=".".join(qual_stack),
                    kind="interface" if kind == "interface_declaration" else "class",
                )
                result.classes.append(span)
                superclass = _named_child(node, 'superclass')
                if superclass is not None:
                    bases = re.findall(r'[A-Za-z_$][\w.$]*', _node_text(superclass, source))
                    if len(bases) == 2 and bases[0] == 'extends':
                        result.raw.setdefault('inheritance', {})[parent] = [bases[1]]
                qual_stack.append(name)
                for child in node.children:
                    visit(child)
                qual_stack.pop()
                return
        elif kind in {"method_declaration", "constructor_declaration"}:
            name_node = _named_child(node, "name")
            if name_node is not None:
                name = _node_text(name_node, source)
                span = SymbolSpan(
                    name=name,
                    qualified_name=qual(name),
                    line=_node_line(name_node),
                    end_line=_node_end_line(node),
                    parent_qualified_name=".".join(qual_stack),
                    kind="method",
                )
                result.functions.append(span)
                qual_stack.append(name)
                _local_bindings(node, source, ".".join(qual_stack), result)
                _collect_calls(node, source, ".".join(qual_stack), result)
                qual_stack.pop()
                return
        for child in node.children:
            visit(child)

    visit(root)
    return result


def _collect_calls(method_node: Any, source: str, caller_short: str, result: StructuralParseResult) -> None:
    """Walk a Java method body and append every method invocation."""
    if method_node is None:
        return

    def visit(node: Any) -> None:
        if node is None:
            return
        if node.type == "method_invocation":
            name_node = _named_child(node, "name")
            obj_node = _named_child(node, "object")
            if name_node is not None:
                result.calls.append(
                    CallSite(
                        caller_qualified_name=caller_short,
                        callee_text=_node_text(name_node, source),
                        line=_node_line(name_node),
                        receiver_text=_node_text(obj_node, source) if obj_node else "",
                    )
                )
        for child in node.children:
            visit(child)

    visit(method_node)


# ── Python walker ───────────────────────────────────────────────────────────


def _walk_python(root: Any, source: str) -> StructuralParseResult:
    result = StructuralParseResult(language="python")
    qual_stack: list[str] = []

    def qual(name: str) -> str:
        parts = [p for p in (*qual_stack, name) if p]
        return ".".join(parts)

    def visit(node: Any) -> None:
        if node is None:
            return
        kind = node.type
        if kind == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    result.imports.append(_node_text(child, source))
        elif kind == "import_from_statement":
            module_node = _named_child(node, "module_name")
            module_name = _node_text(module_node, source) if module_node else ""
            # ``import_from_statement`` children include the module_name
            # itself (as a dotted_name) and the imported symbols (also
            # dotted_name children). Tree-sitter Python bindings return a
            # fresh ``Node`` object per access, so identity (``is``) does
            # not detect the duplicate — compare byte ranges instead.
            module_range = (module_node.start_byte, module_node.end_byte) if module_node else None
            for child in node.children:
                if child.type != "dotted_name":
                    continue
                if module_range and (child.start_byte, child.end_byte) == module_range:
                    continue
                sym = _node_text(child, source)
                if not sym:
                    continue
                result.imports.append(
                    f"{module_name}.{sym}" if module_name else sym
                )
        elif kind == "class_definition":
            name_node = _named_child(node, "name")
            if name_node is not None:
                name = _node_text(name_node, source)
                result.classes.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=qual(name),
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=".".join(qual_stack),
                        kind="class",
                    )
                )
                superclass = _named_child(node, 'superclasses')
                if superclass is not None:
                    bases = [_node_text(c, source) for c in superclass.named_children
                             if c.type in {'identifier', 'attribute'}]
                    result.raw.setdefault('inheritance', {})[qual(name)] = bases
                qual_stack.append(name)
                body = _named_child(node, "body")
                if body is not None:
                    for child in body.children:
                        visit(child)
                qual_stack.pop()
                return
        elif kind == "function_definition":
            name_node = _named_child(node, "name")
            if name_node is not None:
                name = _node_text(name_node, source)
                inside_class = bool(qual_stack)
                fn_qual = qual(name)
                result.functions.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=fn_qual,
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=".".join(qual_stack),
                        kind="method" if inside_class else "function",
                    )
                )
                _local_bindings(node, source, fn_qual, result)
                _collect_python_calls(node, source, fn_qual, result)
                qual_stack.append(name)
                body = _named_child(node, "body")
                if body is not None:
                    for child in body.children:
                        visit(child)
                qual_stack.pop()
                return
        for child in node.children:
            visit(child)

    visit(root)
    return result


def _collect_python_calls(fn_node: Any, source: str, caller_qual: str, result: StructuralParseResult) -> None:
    if fn_node is None:
        return

    def visit(node: Any) -> None:
        if node is None:
            return
        if node != fn_node and node.type in {"function_definition", "class_definition"}:
            return
        if node.type == "call":
            fn_field = _named_child(node, "function")
            callee_text = _node_text(fn_field, source) if fn_field else ""
            receiver = ""
            if fn_field is not None and fn_field.type == "attribute":
                obj = _named_child(fn_field, "object")
                if obj is not None:
                    receiver = _node_text(obj, source)
            if callee_text:
                result.calls.append(
                    CallSite(
                        caller_qualified_name=caller_qual,
                        callee_text=callee_text,
                        line=_node_line(node),
                        receiver_text=receiver,
                    )
                )
        for child in node.children:
            visit(child)

    visit(fn_node)


# ── Go walker ───────────────────────────────────────────────────────────────


def _walk_go(root: Any, source: str) -> StructuralParseResult:
    result = StructuralParseResult(language="go")

    def visit(node: Any) -> None:
        if node is None:
            return
        kind = node.type
        if kind == "package_clause":
            for child in node.children:
                if child.type == "package_identifier":
                    result.module = _node_text(child, source)
        elif kind == "import_spec":
            for child in node.children:
                if child.type == "interpreted_string_literal":
                    result.imports.append(_node_text(child, source).strip('"'))
        elif kind == "type_declaration":
            for spec in node.children:
                if spec.type == "type_spec":
                    name_node = _named_child(spec, "name")
                    if name_node is not None:
                        name = _node_text(name_node, source)
                        result.classes.append(
                            SymbolSpan(
                                name=name,
                                qualified_name=f"{result.module}.{name}" if result.module else name,
                                line=_node_line(name_node),
                                end_line=_node_end_line(spec),
                                parent_qualified_name=result.module or "",
                                kind="class",
                            )
                        )
        elif kind == "function_declaration":
            name_node = _named_child(node, "name")
            if name_node is not None:
                name = _node_text(name_node, source)
                qual = f"{result.module}.{name}" if result.module else name
                result.functions.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=qual,
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=result.module or "",
                        kind="function",
                    )
                )
                _local_bindings(node, source, qual, result)
                _collect_go_calls(node, source, qual, result)
                return
        elif kind == "method_declaration":
            name_node = _named_child(node, "name")
            recv_node = _named_child(node, "receiver")
            if name_node is not None:
                name = _node_text(name_node, source)
                # Receiver looks like ``(o *Order)``; pull out the type name.
                recv_type = ""
                if recv_node is not None:
                    for child in recv_node.children:
                        if child.type == "parameter_declaration":
                            tn = _named_child(child, "type")
                            if tn is not None:
                                recv_type = _node_text(tn, source).lstrip("*")
                qual_base = (
                    f"{result.module}.{recv_type}.{name}"
                    if result.module and recv_type
                    else f"{recv_type}.{name}" if recv_type else name
                )
                result.functions.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=qual_base,
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=recv_type,
                        kind="method",
                    )
                )
                if recv_node is not None:
                    for parameter in recv_node.named_children:
                        receiver_name = _named_child(parameter, "name")
                        if receiver_name is not None:
                            result.raw.setdefault('receivers', {})[qual_base] = _node_text(receiver_name, source)
                _local_bindings(node, source, qual_base, result)
                _collect_go_calls(node, source, qual_base, result)
                return
        for child in node.children:
            visit(child)

    visit(root)
    return result


def _collect_go_calls(fn_node: Any, source: str, caller_qual: str, result: StructuralParseResult) -> None:
    if fn_node is None:
        return

    def visit(node: Any) -> None:
        if node is None:
            return
        if node.type == "call_expression":
            fn_field = _named_child(node, "function")
            if fn_field is not None:
                result.calls.append(
                    CallSite(
                        caller_qualified_name=caller_qual,
                        callee_text=_node_text(fn_field, source),
                        line=_node_line(node),
                        receiver_text="",
                    )
                )
        for child in node.children:
            visit(child)

    visit(fn_node)


# ── TypeScript / TSX / JavaScript walker ───────────────────────────────────


def _walk_typescript(root: Any, source: str) -> StructuralParseResult:
    return _walk_ts_like(root, source, language_name="typescript")


def _walk_tsx(root: Any, source: str) -> StructuralParseResult:
    return _walk_ts_like(root, source, language_name="tsx")


def _walk_javascript(root: Any, source: str) -> StructuralParseResult:
    return _walk_ts_like(root, source, language_name="javascript")


def _walk_ts_like(root: Any, source: str, language_name: str) -> StructuralParseResult:
    result = StructuralParseResult(language=language_name)
    qual_stack: list[str] = []

    def qual(name: str) -> str:
        parts = [p for p in (*qual_stack, name) if p]
        return ".".join(parts)

    def visit(node: Any) -> None:
        if node is None:
            return
        kind = node.type
        if kind == "import_statement":
            for child in node.children:
                if child.type == "string":
                    raw = _node_text(child, source).strip("'\"`")
                    result.imports.append(raw)
        elif kind in {"class_declaration", "abstract_class_declaration"}:
            name_node = _named_child(node, "name")
            if name_node is not None:
                name = _node_text(name_node, source)
                result.classes.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=qual(name),
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=".".join(qual_stack),
                        kind="class",
                    )
                )
                qual_stack.append(name)
                for child in node.children:
                    visit(child)
                qual_stack.pop()
                return
        elif kind == "interface_declaration":
            name_node = _named_child(node, "name")
            if name_node is not None:
                name = _node_text(name_node, source)
                result.classes.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=qual(name),
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=".".join(qual_stack),
                        kind="interface",
                    )
                )
        elif kind in {"function_declaration", "generator_function_declaration", "method_definition", "function_signature"}:
            name_node = _named_child(node, "name")
            if name_node is not None:
                name = _node_text(name_node, source)
                inside_class = bool(qual_stack)
                fn_qual = qual(name)
                result.functions.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=fn_qual,
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=".".join(qual_stack),
                        kind="method" if inside_class else "function",
                    )
                )
                _local_bindings(node, source, fn_qual, result)
                _collect_ts_calls(node, source, fn_qual, result)
                qual_stack.append(name)
                body = _named_child(node, "body")
                if body is not None:
                    for child in body.children:
                        visit(child)
                qual_stack.pop()
                return
        elif kind in {"variable_declarator", "pair"}:
            name_node = _named_child(node, "name") or _named_child(node, "key")
            value = _named_child(node, "value")
            if name_node is not None and value is not None and value.type in {"arrow_function", "function_expression", "function"}:
                name = _node_text(name_node, source)
                fn_qual = qual(name)
                result.functions.append(SymbolSpan(name, fn_qual, _node_line(name_node),
                                                   _node_end_line(value), ".".join(qual_stack), "function"))
                _local_bindings(value, source, fn_qual, result)
                _collect_ts_calls(value, source, fn_qual, result)
                qual_stack.append(name)
                body = _named_child(value, "body")
                if body is not None:
                    for child in body.children:
                        visit(child)
                qual_stack.pop()
                return
        for child in node.children:
            visit(child)

    visit(root)
    return result


def _collect_ts_calls(fn_node: Any, source: str, caller_qual: str, result: StructuralParseResult) -> None:
    if fn_node is None:
        return

    def visit(node: Any) -> None:
        if node is None:
            return
        if node != fn_node and node.type in {"function_declaration", "method_definition", "arrow_function", "function_expression", "function"}:
            return
        if node.type == "call_expression":
            fn_field = _named_child(node, "function")
            callee_text = _node_text(fn_field, source) if fn_field else ""
            receiver = ""
            if fn_field is not None and fn_field.type == "member_expression":
                obj = _named_child(fn_field, "object")
                if obj is not None:
                    receiver = _node_text(obj, source)
            if callee_text:
                result.calls.append(
                    CallSite(
                        caller_qualified_name=caller_qual,
                        callee_text=callee_text,
                        line=_node_line(node),
                        receiver_text=receiver,
                    )
                )
        for child in node.children:
            visit(child)

    visit(fn_node)


# ── Kotlin walker ───────────────────────────────────────────────────────────


def _walk_kotlin(root: Any, source: str) -> StructuralParseResult:
    result = StructuralParseResult(language="kotlin")
    qual_stack: list[str] = []

    def qual(name: str) -> str:
        parts = [p for p in (*qual_stack, name) if p]
        return ".".join(parts)

    def visit(node: Any) -> None:
        if node is None:
            return
        kind = node.type
        if kind == "package_header":
            # tree-sitter-kotlin wraps the dotted package name in a
            # ``qualified_identifier`` (or sometimes a flat ``identifier``
            # on simple package names). Accept both shapes.
            for child in node.children:
                if child.type in {"qualified_identifier", "identifier"}:
                    result.module = _node_text(child, source)
                    qual_stack.append(result.module or "")
                    break
        elif kind == "import_header":
            for child in node.children:
                if child.type in {"qualified_identifier", "identifier"}:
                    result.imports.append(_node_text(child, source))
        elif kind in {"class_declaration", "object_declaration"}:
            name_node = _named_child(node, "name") or _find_first_identifier(node)
            if name_node is not None:
                name = _node_text(name_node, source)
                result.classes.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=qual(name),
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=".".join(qual_stack),
                        kind="class",
                    )
                )
                qual_stack.append(name)
                for child in node.children:
                    visit(child)
                qual_stack.pop()
                return
        elif kind == "function_declaration":
            name_node = _named_child(node, "name") or _find_first_identifier(node)
            if name_node is not None:
                name = _node_text(name_node, source)
                inside_class = len(qual_stack) > (1 if result.module else 0)
                result.functions.append(
                    SymbolSpan(
                        name=name,
                        qualified_name=qual(name),
                        line=_node_line(name_node),
                        end_line=_node_end_line(node),
                        parent_qualified_name=".".join(qual_stack),
                        kind="method" if inside_class else "function",
                    )
                )
                _collect_kotlin_calls(node, source, qual(name), result)
                return
        for child in node.children:
            visit(child)

    visit(root)
    return result


def _find_first_identifier(node: Any) -> Any:
    """Kotlin's tree-sitter grammar varies on whether ``name`` is a
    named field. Fall back to the first ``simple_identifier`` child."""
    if node is None:
        return None
    for child in node.children:
        if child.type in {"simple_identifier", "identifier", "type_identifier"}:
            return child
    return None


def _collect_kotlin_calls(fn_node: Any, source: str, caller_qual: str, result: StructuralParseResult) -> None:
    if fn_node is None:
        return

    def visit(node: Any) -> None:
        if node is None:
            return
        if node.type == "call_expression":
            # The callee can be a direct identifier or a navigation_expression
            # like ``obj.method``. Either way we grab the first identifier
            # for the call text.
            callee_text = ""
            receiver = ""
            for child in node.children:
                if child.type in {"simple_identifier", "identifier"}:
                    callee_text = _node_text(child, source)
                    break
                if child.type == "navigation_expression":
                    callee_text = _node_text(child, source)
                    parts = callee_text.rsplit(".", 1)
                    if len(parts) == 2:
                        receiver, callee_text = parts
                    break
            if callee_text:
                result.calls.append(
                    CallSite(
                        caller_qualified_name=caller_qual,
                        callee_text=callee_text,
                        line=_node_line(node),
                        receiver_text=receiver,
                    )
                )
        for child in node.children:
            visit(child)

    visit(fn_node)


# ── Walker dispatch ─────────────────────────────────────────────────────────


def _local_bindings(node: Any, source: str, qualified: str, result: StructuralParseResult) -> None:
    names = set()

    def identifiers(part):
        if part is None or part.type in {'type_annotation', 'type_identifier', 'predefined_type'}:
            return
        if part.type == 'identifier':
            names.add(_node_text(part, source))
            return
        name = _named_child(part, 'name') or _named_child(part, 'pattern')
        if name is not None:
            identifiers(name)
        else:
            for child in part.named_children:
                identifiers(child)

    identifiers(_named_child(node, 'parameters') or _named_child(node, 'parameter'))

    def visit(part):
        if part != node and part.type in {'function_definition', 'function_declaration', 'arrow_function', 'function_expression'}:
            return
        if part.type in {'import_statement', 'import_from_statement'}:
            for child in part.named_children:
                if child == _named_child(part, 'module_name'):
                    continue
                if child.type == 'aliased_import':
                    identifiers(_named_child(child, 'alias'))
                elif child.type == 'dotted_name':
                    names.add(_node_text(child, source).split('.')[0])
        if part.type in {'variable_declarator', 'assignment', 'short_var_declaration'}:
            identifiers(_named_child(part, 'name') or _named_child(part, 'left'))
        for child in part.named_children:
            visit(child)

    visit(node)
    result.raw.setdefault('local_bindings', {})[qualified] = sorted(names)


def _import_bindings(root: Any, source: str, result: StructuralParseResult) -> None:
    """保存 AST 导入绑定；解析阶段不猜测目标项目文件。"""
    bindings = result.raw.setdefault('import_bindings', [])

    def add(local, module, symbol='', namespace=False):
        if local and module:
            bindings.append({'local': local, 'module': module, 'symbol': symbol, 'namespace': namespace})

    def visit(node):
        if node.type in {'function_definition', 'class_definition'}:
            return  # 函数或类内部导入不作为模块级绑定。
        if result.language in {'typescript', 'tsx', 'javascript'} and node.type == 'export_statement':
            exports = result.raw.setdefault('exports', {})
            declaration = _named_child(node, 'declaration') or _named_child(node, 'value')
            if declaration is not None:
                name = _named_child(declaration, 'name')
                names = [_node_text(name, source)] if name is not None else []
                if declaration.type in {'lexical_declaration', 'variable_declaration'}:
                    names = [_node_text(_named_child(c, 'name'), source) for c in declaration.named_children
                             if c.type == 'variable_declarator']
                if declaration.type == 'identifier':
                    names = [_node_text(declaration, source)]
                if re.search(r'^export\s+default\b', _node_text(node, source)):
                    if len(names) == 1:
                        exports['default'] = names[0]
                else:
                    exports.update({name: name for name in names})
            module = _node_text(_named_child(node, 'source'), source).strip("'\"")
            if module:
                forwards = result.raw.setdefault('reexports', [])
                for clause in node.named_children:
                    if clause.type == 'export_clause':
                        for spec in clause.named_children:
                            name = _node_text(_named_child(spec, 'name'), source)
                            alias = _node_text(_named_child(spec, 'alias'), source) or name
                            forwards.append({'module': module, 'symbol': name, 'exported': alias})
                if re.match(r'^export\s+\*\s+from\b', _node_text(node, source)):
                    forwards.append({'module': module, 'symbol': '*', 'exported': '*'})
            if _named_child(node, 'source') is None:
                for clause in node.named_children:
                    if clause.type == 'export_clause':
                        for spec in clause.named_children:
                            name = _node_text(_named_child(spec, 'name'), source)
                            alias = _node_text(_named_child(spec, 'alias'), source) or name
                            exports[alias] = name
        if result.language in {'typescript', 'tsx', 'javascript'} and node.type == 'import_statement':
            module = _node_text(_named_child(node, 'source'), source).strip("'\"")
            for clause in node.named_children:
                if clause.type != 'import_clause':
                    continue
                for child in clause.named_children:
                    if child.type == 'identifier':
                        add(_node_text(child, source), module, 'default')
                    elif child.type == 'namespace_import':
                        add(_node_text(child.named_children[-1], source), module, namespace=True)
                    elif child.type == 'named_imports':
                        for spec in child.named_children:
                            name = _named_child(spec, 'name')
                            alias = _named_child(spec, 'alias') or name
                            add(_node_text(alias, source), module, _node_text(name, source))
        elif result.language == 'python' and node.type in {'import_statement', 'import_from_statement'}:
            module_node = _named_child(node, 'module_name')
            module = _node_text(module_node, source)
            for child in node.named_children:
                if child == module_node:
                    continue
                if child.type == 'aliased_import':
                    name = _node_text(_named_child(child, 'name'), source)
                    alias = _node_text(_named_child(child, 'alias'), source)
                elif child.type == 'dotted_name':
                    name = alias = _node_text(child, source)
                else:
                    continue
                if node.type == 'import_from_statement':
                    add(alias, module, name)
                else:
                    add(alias, name, namespace=True)
        elif result.language == 'go' and node.type == 'import_spec':
            module = _node_text(_named_child(node, 'path'), source).strip('"`')
            name = _node_text(_named_child(node, 'name'), source) or module.rsplit('/', 1)[-1]
            if name not in {'_', '.'}:
                add(name, module, namespace=True)
        for child in node.named_children:
            visit(child)

    visit(root)


def _parse_vue(source: str, file_path: str) -> StructuralParseResult:
    """分别解析 SFC 脚本块，空白占位保留原始行号，模板不作为 JS 解析。"""
    result = StructuralParseResult(language='vue')
    result.raw.update(parse_status='parsed', import_bindings=[], script_languages=[])
    visible = re.sub(r'<!--.*?-->', lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), source, flags=re.S)
    for match in re.finditer(r'<script\b([^>]*)>(.*?)</script[^>]*>', visible, re.I | re.S):
        attrs = match[1]
        if re.search(r'\bsrc\s*=', attrs):
            result.raw['parse_status'] = 'partial'
            continue
        lang_match = re.search(r'\blang\s*=\s*[\"\']([^\"\']+)', attrs, re.I)
        lang = lang_match[1].lower() if lang_match else 'js'
        language = {'ts': 'typescript', 'tsx': 'tsx', 'js': 'javascript', 'jsx': 'javascript'}.get(lang)
        if language is None:
            result.raw['parse_status'] = 'partial'
            continue
        parser = TreeSitterStructuralParser(language)
        if not parser.available:
            result.raw['parse_status'] = 'unavailable'
            continue
        prefix = ''.join('\n' if c == '\n' else ' ' for c in source[:match.start(2)])
        parsed = parser.parse(prefix + match[2], file_path)
        result.classes.extend(parsed.classes)
        result.functions.extend(parsed.functions)
        result.calls.extend(parsed.calls)
        result.imports.extend(parsed.imports)
        result.raw['import_bindings'].extend(parsed.raw.get('import_bindings', []))
        result.raw.setdefault('local_bindings', {}).update(parsed.raw.get('local_bindings', {}))
        result.raw.setdefault('exports', {}).update(parsed.raw.get('exports', {}))
        result.raw.setdefault('reexports', []).extend(parsed.raw.get('reexports', []))
        result.raw.setdefault('inheritance', {}).update(parsed.raw.get('inheritance', {}))
        result.raw['script_languages'].append(language)
        if parsed.raw.get('parse_status') != 'parsed':
            result.raw['parse_status'] = 'partial'
    return result


_WALKERS: dict[str, Callable[[Any, str], StructuralParseResult]] = {
    "java": _walk_java,
    "python": _walk_python,
    "go": _walk_go,
    "typescript": _walk_typescript,
    "tsx": _walk_tsx,
    "javascript": _walk_javascript,
    "kotlin": _walk_kotlin,
}


@dataclass(frozen=True)
class StructuralParserStatus:
    """Snapshot of a parser's runtime state for diagnostics."""

    language: str
    available: bool
    init_error: str | None = None
