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
        try:
            tree = self._parser.parse(source.encode("utf-8"))
        except Exception:
            with self._diagnostics_lock:
                self._fail_count += 1
            return empty
        walker = _WALKERS.get(self.language_name)
        if walker is None:
            return empty
        result = walker(tree.root_node, source)
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
                qual_stack.append(name)
                for child in node.children:
                    visit(child)
                qual_stack.pop()
                return
        elif kind == "method_declaration":
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
                _collect_calls(node, source, qual_stack[-1] if qual_stack else "", result)
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
            for child in node.children:
                if child.type == "dotted_name" and child is not module_node:
                    result.imports.append(
                        f"{module_name}.{_node_text(child, source)}" if module_name else _node_text(child, source)
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
                _collect_python_calls(node, source, fn_qual, result)
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
        elif kind in {"function_declaration", "method_definition", "function_signature"}:
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
                _collect_ts_calls(node, source, fn_qual, result)
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
