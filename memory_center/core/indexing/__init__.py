"""Parser plug-ins used by Memory Center indexers."""

from . import multilang_indexer
from .base import JavaParser, JavaParseResult
from .differential import compare_parser_corpus, compare_parsers
from .java_regex_parser import RegexJavaParser
from .language_registry import (
    LanguageSpec,
    get_language_spec,
    get_language_spec_for_extension,
    supported_extensions,
    supported_languages,
)
from .parse_result import CallSite, StructuralParseResult, SymbolSpan
from .structural_parser import TreeSitterStructuralParser

__all__ = [
    "CallSite",
    "JavaParseResult",
    "JavaParser",
    "LanguageSpec",
    "RegexJavaParser",
    "StructuralParseResult",
    "SymbolSpan",
    "TreeSitterStructuralParser",
    "compare_parser_corpus",
    "compare_parsers",
    "get_language_spec",
    "get_language_spec_for_extension",
    "multilang_indexer",
    "supported_extensions",
    "supported_languages",
]
