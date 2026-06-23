"""Tests for the language registry and structural parse result.

Pure data-layer tests — no tree-sitter dependency is exercised here.
The actual AST walker is covered separately under
``tests/test_structural_parser*``.
"""
from __future__ import annotations

import pytest

from memory_center.core.indexing.language_registry import (
    LanguageSpec,
    get_language_spec,
    get_language_spec_for_extension,
    supported_extensions,
    supported_languages,
)
from memory_center.core.indexing.parse_result import (
    CallSite,
    StructuralParseResult,
    SymbolSpan,
)


# ── Registry contents ──────────────────────────────────────────────────────


def test_supported_languages_includes_target_five() -> None:
    """P0-2 ships with at least the five focus languages registered."""
    langs = set(supported_languages())
    expected = {"java", "kotlin", "python", "typescript", "go"}
    assert expected.issubset(langs)


def test_supported_extensions_returns_dot_prefixed_lowercase() -> None:
    exts = supported_extensions()
    assert all(ext.startswith(".") for ext in exts)
    assert all(ext == ext.lower() for ext in exts)
    # No duplicates even when multiple languages share a binding module.
    assert len(exts) == len(set(exts))


# ── get_language_spec ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    ["java", "kotlin", "python", "typescript", "tsx", "javascript", "go"],
)
def test_lookup_by_canonical_name(name: str) -> None:
    spec = get_language_spec(name)
    assert spec is not None
    assert spec.name == name


def test_lookup_by_alias() -> None:
    """Aliases must match without re-registering the same language."""
    ts = get_language_spec("ts")
    assert ts is not None and ts.name == "typescript"
    js = get_language_spec("js")
    assert js is not None and js.name == "javascript"


def test_lookup_case_insensitive() -> None:
    assert get_language_spec("JAVA") is get_language_spec("java")
    assert get_language_spec("TypeScript") is get_language_spec("typescript")


def test_lookup_unknown_returns_none() -> None:
    assert get_language_spec("brainfuck") is None
    assert get_language_spec("") is None


# ── get_language_spec_for_extension ────────────────────────────────────────


@pytest.mark.parametrize(
    ("ext", "language"),
    [
        (".java", "java"),
        (".kt", "kotlin"),
        (".kts", "kotlin"),
        (".py", "python"),
        (".pyi", "python"),
        (".ts", "typescript"),
        (".tsx", "tsx"),
        (".js", "javascript"),
        (".jsx", "javascript"),
        (".mjs", "javascript"),
        (".cjs", "javascript"),
        (".go", "go"),
    ],
)
def test_lookup_by_extension(ext: str, language: str) -> None:
    spec = get_language_spec_for_extension(ext)
    assert spec is not None
    assert spec.name == language


def test_lookup_by_extension_accepts_bare_name() -> None:
    """Callers sometimes forget the leading dot; the registry must DTRT."""
    assert get_language_spec_for_extension("py") is get_language_spec_for_extension(".py")


def test_lookup_by_extension_case_insensitive() -> None:
    assert get_language_spec_for_extension(".JAVA") is get_language_spec_for_extension(".java")


def test_lookup_by_extension_unknown() -> None:
    assert get_language_spec_for_extension(".bf") is None
    assert get_language_spec_for_extension("") is None


# ── LanguageSpec.load_language ─────────────────────────────────────────────


def test_load_language_raises_when_binding_missing() -> None:
    """The lazy import must surface a ModuleNotFoundError when the
    optional tree-sitter binding isn't installed. Callers catch this and
    suggest the right pip extra."""
    bogus = LanguageSpec(name="nope", extensions=(".nope",), module="memory_center_nope_xyz")
    with pytest.raises(ModuleNotFoundError):
        bogus.load_language()


# ── StructuralParseResult ──────────────────────────────────────────────────


def test_parse_result_is_empty_for_default() -> None:
    assert StructuralParseResult(language="python").is_empty()


def test_parse_result_not_empty_when_any_field_populated() -> None:
    r = StructuralParseResult(language="python", imports=["os"])
    assert not r.is_empty()

    r = StructuralParseResult(
        language="python",
        functions=[SymbolSpan(name="f", qualified_name="m.f", line=1, kind="function")],
    )
    assert not r.is_empty()

    r = StructuralParseResult(
        language="python",
        calls=[CallSite(caller_qualified_name="m.f", callee_text="print(1)", line=2)],
    )
    assert not r.is_empty()
