"""Language registry for the multi-language structural parser.

Maps file extensions and language names to the tree-sitter binding that
provides their grammar. Adding a new language only requires:

1. Installing the corresponding ``tree-sitter-<lang>`` package (declared
   as an optional dependency in pyproject.toml under the ``multilang``
   extra).
2. Registering a :class:`LanguageSpec` here.
3. Wiring an AST walker in ``structural_walker.py`` (a small ``walk_*``
   function per language).

The registry stays decoupled from tree-sitter itself: callers ask for a
:class:`LanguageSpec` and use ``spec.load_language()`` only when they
actually need to parse. This keeps importing the registry cheap and
lets the module load even when no tree-sitter package is installed.

语言注册表 —— 文件扩展名/语言名 → tree-sitter binding。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LanguageSpec:
    """One entry in the language registry.

    Attributes:
        name: Canonical language name. Matches the value stored on
            :class:`StructuralParseResult.language` and the keys used by
            the AST walker dispatch in ``structural_walker.py``.
        extensions: File extensions (with leading dot) that map to this
            language. Lowercase. ``.tsx`` and ``.ts`` both map to TS
            because they share enough AST shape to be walked together —
            the walker checks for JSX nodes when present.
        module: Python module providing the tree-sitter binding (e.g.
            ``tree_sitter_java``). Imported lazily inside
            ``load_language``.
        language_attr: Attribute on the binding module that returns the
            tree-sitter ``Language`` capsule. Almost always ``"language"``;
            TypeScript ships two grammars (``language_typescript`` /
            ``language_tsx``) so a callable indirection lets us pick the
            right one without inflating the spec.
        installed_with: pip extra name that pulls in the binding. Used
            by diagnostic output (``memory-center doctor``) when a
            language is registered but its binding is missing.
    """

    name: str
    extensions: tuple[str, ...]
    module: str
    language_attr: str = "language"
    installed_with: str = "multilang"
    aliases: tuple[str, ...] = ()

    def load_language(self) -> Any:
        """Import the binding lazily and return the tree-sitter Language.

        Raises :class:`ModuleNotFoundError` when the binding is not
        installed. Callers (``TreeSitterStructuralParser``) catch this
        and surface a friendly hint pointing at the ``multilang`` extra.
        """
        import importlib

        module = importlib.import_module(self.module)
        attr = getattr(module, self.language_attr)
        return attr() if callable(attr) else attr


# ── Built-in registry ───────────────────────────────────────────────────────


_REGISTRY: dict[str, LanguageSpec] = {
    "java": LanguageSpec(
        name="java",
        extensions=(".java",),
        module="tree_sitter_java",
    ),
    "kotlin": LanguageSpec(
        name="kotlin",
        extensions=(".kt", ".kts"),
        module="tree_sitter_kotlin",
    ),
    "python": LanguageSpec(
        name="python",
        extensions=(".py", ".pyi"),
        module="tree_sitter_python",
    ),
    "typescript": LanguageSpec(
        name="typescript",
        extensions=(".ts",),
        module="tree_sitter_typescript",
        language_attr="language_typescript",
        aliases=("ts",),
    ),
    "tsx": LanguageSpec(
        name="tsx",
        extensions=(".tsx",),
        module="tree_sitter_typescript",
        language_attr="language_tsx",
    ),
    "javascript": LanguageSpec(
        # JavaScript reuses the TS-without-types grammar via the JSX
        # variant; in practice tree_sitter_typescript handles ``.js``
        # files well enough for the structural facts we collect. A
        # dedicated tree-sitter-javascript binding can replace this in
        # the future without changing the registry interface.
        name="javascript",
        extensions=(".js", ".mjs", ".cjs", ".jsx"),
        module="tree_sitter_typescript",
        language_attr="language_tsx",
        aliases=("js",),
    ),
    "go": LanguageSpec(
        name="go",
        extensions=(".go",),
        module="tree_sitter_go",
    ),
}


# ── Public helpers ──────────────────────────────────────────────────────────


def get_language_spec(name_or_alias: str) -> LanguageSpec | None:
    """Look up a spec by canonical name or alias.

    Case-insensitive. Returns ``None`` for unknown languages instead of
    raising — callers typically fall back to a regex / no-op path on
    miss rather than aborting the whole index.
    """
    if not name_or_alias:
        return None
    needle = name_or_alias.lower()
    if needle in _REGISTRY:
        return _REGISTRY[needle]
    for spec in _REGISTRY.values():
        if needle in spec.aliases:
            return spec
    return None


def get_language_spec_for_extension(extension: str) -> LanguageSpec | None:
    """Look up a spec by file extension (e.g. ``".py"``).

    The leading dot is required so callers don't accidentally match
    against bare names. Case-insensitive on the extension itself so
    ``.JAVA`` works the same as ``.java``.
    """
    if not extension:
        return None
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    for spec in _REGISTRY.values():
        if ext in spec.extensions:
            return spec
    return None


def supported_languages() -> list[str]:
    """All registered canonical language names, in stable order."""
    return list(_REGISTRY.keys())


def supported_extensions() -> tuple[str, ...]:
    """Every extension covered by the registry. Useful for the indexer
    to decide whether a file is worth handing to the structural parser
    at all."""
    seen: list[str] = []
    for spec in _REGISTRY.values():
        for ext in spec.extensions:
            if ext not in seen:
                seen.append(ext)
    return tuple(seen)
