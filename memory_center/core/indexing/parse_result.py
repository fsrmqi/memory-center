"""Language-agnostic structural parse result.

This is the multi-language counterpart of :class:`JavaParseResult` in
``base.py``. ``JavaParseResult`` is intentionally kept around because the
Spring-aware extractors (annotations, Bean injection, Feign clients, MQ
detection, DTO usages) lean on Java-specific fields. ``StructuralParseResult``
holds only the cross-language facts that every supported language can
produce — class / function / import / call — and is what feeds the
generic graph for Python / Go / TypeScript / Kotlin / Rust / … files.

Why a separate result type instead of expanding ``JavaParseResult``?

- Backward compatibility: 5604 tests pin the Java result shape.
- Smaller surface for new languages: a Python parser only needs to fill
  three lists (classes / functions / imports) plus a call list, not the
  23 Java-specific fields.
- Java keeps a "dual track": the existing Java parser keeps producing
  ``JavaParseResult`` for Spring extractors; the same Java tree is also
  walked through :class:`TreeSitterStructuralParser` to feed the generic
  graph. The two paths share the source bytes but not the AST walker —
  see ``indexer.py`` for the routing.

通用结构化解析结果。Java 保留专属字段,其他语言只填这里的通用字段。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SymbolSpan:
    """Location of a named declaration inside a source file.

    ``qualified_name`` is the dotted/slashed form that disambiguates the
    symbol across the project: ``com.example.Order.process`` for Java,
    ``mypkg.helpers.do_thing`` for Python, ``example.com/foo/Handler``
    for Go. When the language has no obvious notion of qualification
    (e.g. top-level Kotlin functions) callers should reuse ``name``.

    ``parent_qualified_name`` is non-empty for methods (parent = class)
    and for nested classes (parent = enclosing class). It's empty for
    top-level declarations. The indexer uses this to wire ``DEFINES``
    and ``INHERITS`` edges without re-parsing.
    """

    name: str
    qualified_name: str
    line: int
    end_line: int = 0
    parent_qualified_name: str = ""
    kind: str = ""  # "class" | "interface" | "function" | "method" | …


@dataclass(frozen=True)
class CallSite:
    """One observed call expression.

    Cross-language call extraction can rarely resolve the target without
    full type information, so we record the textual evidence and leave
    final resolution to a downstream resolver (see P1-1).

    ``caller_qualified_name`` is the function/method that contains the
    call. ``callee_text`` is the raw call expression as it appears in
    source (``foo.bar()``, ``self.do(x)``, ``pkg.Helper.run()``). The
    receiver is split out when available so the resolver can prefer
    same-class > same-package > import-based matches.
    """

    caller_qualified_name: str
    callee_text: str
    line: int
    receiver_text: str = ""


@dataclass
class StructuralParseResult:
    """Cross-language structural facts about one source file.

    Languages with a stable concept of module / package fill ``module``
    (Python ``pkg.sub``, Go ``example.com/foo``, Java package, TS module
    path). Languages without one (free-floating JS / Kotlin scripts)
    leave it as ``None``.

    ``raw`` is an opaque escape hatch where language-specific extractors
    can stash extra evidence (e.g. Python decorators, TS JSX components)
    without polluting the cross-language contract.
    """

    language: str
    module: str | None = None
    imports: list[str] = field(default_factory=list)
    classes: list[SymbolSpan] = field(default_factory=list)
    functions: list[SymbolSpan] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    constants: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """True iff the file produced no structural information.

        Useful for indexer routing — when ``is_empty()`` we can fall
        back to a plain text/regex pass without spending tokens on an
        empty parse result.
        """
        return not (
            self.imports
            or self.classes
            or self.functions
            or self.calls
            or self.constants
        )
