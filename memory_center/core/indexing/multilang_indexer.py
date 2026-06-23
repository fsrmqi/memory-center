"""Indexer-side glue for multi-language structural parsing.

This module sits between :mod:`memory_center.core.indexer` and the
generic ``TreeSitterStructuralParser``. Indexer's main loop is already
big and Java-shaped; the goal here is to add multi-language support
without rewriting it.

Responsibilities:

1. Decide whether a file path is eligible for structural parsing
   (extension known to the language registry, and not a Java file —
   Java keeps the richer dual-track pipeline).
2. Run the appropriate parser, cached per language.
3. Translate the :class:`StructuralParseResult` into graph nodes and
   edges that follow the same ID conventions as the Java path
   (``node_id(kind, name)`` / ``edge_id(type, src, tgt)``).

The output is intentionally minimal: ``Class`` / ``Function`` /
``Module`` nodes plus ``DEFINES`` / ``IMPORTS`` / ``CALLS`` edges. More
language-specific edges (Python decorators, TypeScript JSX components,
Go interface satisfies) will be layered on in P1 once the basic graph
is exercised in the wild.

多语言索引粘合层 —— 非 Java 文件走 StructuralParseResult,
把 class/function/import/call 翻译成与 Java 一致的图节点/边。
"""
from __future__ import annotations

import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..graph import GraphEdge, GraphNode, edge_id, node_id
from .language_registry import (
    get_language_spec_for_extension,
    supported_extensions,
)
from .parse_result import StructuralParseResult
from .structural_parser import TreeSitterStructuralParser

# Extensions handled by the Java-specific dual-track pipeline. The
# structural parser still has a Java walker (mainly used in tests), but
# during real indexing Java goes through tree_sitter_parser.py so the
# Spring-aware extractors fire. Skipping ``.java`` here avoids duplicate
# Class/Function nodes.
_JAVA_EXTENSIONS = frozenset({".java"})

# Cache parsers per language so we don't reload tree-sitter for every file.
_PARSER_CACHE: dict[str, TreeSitterStructuralParser] = {}
_CACHE_LOCK = threading.Lock()


def is_structurally_indexable(path: Path) -> bool:
    """True when the structural parser should be invoked for ``path``."""
    ext = path.suffix.lower()
    if ext in _JAVA_EXTENSIONS:
        return False
    return ext in supported_extensions()


def get_parser_for_path(path: Path) -> TreeSitterStructuralParser | None:
    """Return a cached parser instance for ``path``'s language.

    ``None`` when the path is not structurally indexable or when the
    underlying tree-sitter binding isn't installed. Caller decides
    whether to log the absence — for unavailable parsers we don't want
    to spam the log once per file.
    """
    spec = get_language_spec_for_extension(path.suffix)
    if spec is None:
        return None
    with _CACHE_LOCK:
        parser = _PARSER_CACHE.get(spec.name)
        if parser is None:
            parser = TreeSitterStructuralParser(spec.name)
            _PARSER_CACHE[spec.name] = parser
    return parser if parser.available else None


def parse_structural(
    path: Path,
    text: str | None = None,
) -> StructuralParseResult | None:
    """Parse ``path`` and return the structural result, or ``None``.

    ``text`` may be passed in by callers that already have the file in
    memory (e.g. the parallel reader); when ``None`` the file is read
    from disk. Read failures swallow silently and return ``None`` so a
    single bad file doesn't abort a reindex.
    """
    parser = get_parser_for_path(path)
    if parser is None:
        return None
    if text is None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return parser.parse(text, str(path))


def emit_graph_elements(
    project: str,
    rel_path: str,
    result: StructuralParseResult,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Convert one structural result into graph nodes and edges.

    The translation mirrors the conventions established by the Java
    indexer:

    - ``Module``:  one node per file, named by its logical path.
    - ``Class``:   one node per class/interface; ``DEFINES`` edge from
                   the containing Module.
    - ``Function``: one node per function/method; ``DEFINES`` edge from
                    the enclosing Class (when present) else from the
                    Module.
    - ``IMPORTS``: from Module to a synthetic ``Module`` node named by
                   the import string. The target may not resolve to an
                   indexed file (e.g. ``axios`` in a TS project that
                   doesn't index node_modules); that's fine — orphan
                   targets show up as Module nodes with no incoming
                   DEFINES edge.
    - ``CALLS``:   from the containing Function node to a synthetic
                   ``Function`` node keyed by the callee text. P1-1
                   will swap these synthetic targets for resolved
                   qualified-name nodes; the edge type stays stable so
                   downstream queries don't need to migrate.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    module_qual = result.module or rel_path
    module_id = node_id("Module", module_qual or rel_path)
    nodes.append(
        GraphNode(
            id=module_id,
            type="Module",
            name=module_qual or Path(rel_path).stem,
            project=project,
            file_path=rel_path,
            line=1,
            metadata={"language": result.language, "module": result.module},
        )
    )

    for cls in result.classes:
        cls_id = node_id("Class", cls.qualified_name or cls.name)
        nodes.append(
            GraphNode(
                id=cls_id,
                type="Class",
                name=cls.name,
                project=project,
                file_path=rel_path,
                line=cls.line,
                metadata={
                    "language": result.language,
                    "qualified_name": cls.qualified_name,
                    "kind": cls.kind,
                    "parent_qualified_name": cls.parent_qualified_name,
                },
            )
        )
        edges.append(
            GraphEdge(
                id=edge_id("DEFINES", module_id, cls_id),
                source_id=module_id,
                target_id=cls_id,
                type="DEFINES",
                confidence=0.95,
                metadata={"language": result.language},
            )
        )

    # Index class nodes by qualified name so we can wire DEFINES edges
    # for methods directly to the class node when there is one.
    class_by_qual: dict[str, str] = {
        cls.qualified_name: node_id("Class", cls.qualified_name)
        for cls in result.classes
        if cls.qualified_name
    }

    for fn in result.functions:
        fn_id = node_id("Function", fn.qualified_name or fn.name)
        nodes.append(
            GraphNode(
                id=fn_id,
                type="Function",
                name=fn.name,
                project=project,
                file_path=rel_path,
                line=fn.line,
                metadata={
                    "language": result.language,
                    "qualified_name": fn.qualified_name,
                    "kind": fn.kind,
                    "parent_qualified_name": fn.parent_qualified_name,
                },
            )
        )
        parent_id = class_by_qual.get(fn.parent_qualified_name) or module_id
        edges.append(
            GraphEdge(
                id=edge_id("DEFINES", parent_id, fn_id),
                source_id=parent_id,
                target_id=fn_id,
                type="DEFINES",
                confidence=0.95,
                metadata={"language": result.language},
            )
        )

    for imp in result.imports:
        target_id = node_id("Module", imp)
        # Stub Module node for the import target. We don't add it to
        # ``nodes`` if it's exactly the same as our module_id (rare but
        # avoids a self-loop on weird grammars).
        if target_id == module_id:
            continue
        nodes.append(
            GraphNode(
                id=target_id,
                type="Module",
                name=imp,
                project="",  # unknown until cross-reference resolves it
                file_path="",
                line=0,
                metadata={"stub": True, "import_text": imp},
            )
        )
        edges.append(
            GraphEdge(
                id=edge_id("IMPORTS", module_id, target_id),
                source_id=module_id,
                target_id=target_id,
                type="IMPORTS",
                confidence=0.9,
                metadata={"language": result.language},
            )
        )

    # Build a lookup of function qualified-name -> id so we can resolve
    # in-file caller IDs directly. Callers identified by the walker via
    # ``caller_qualified_name`` won't always have a matching function
    # node (anonymous/lambda); skip those rather than guess.
    fn_by_qual: dict[str, str] = {
        fn.qualified_name: node_id("Function", fn.qualified_name)
        for fn in result.functions
        if fn.qualified_name
    }

    for call in result.calls:
        caller_id = fn_by_qual.get(call.caller_qualified_name)
        if caller_id is None:
            continue
        callee_key = f"{call.receiver_text}.{call.callee_text}" if call.receiver_text else call.callee_text
        callee_id = node_id("Function", callee_key)
        nodes.append(
            GraphNode(
                id=callee_id,
                type="Function",
                name=call.callee_text,
                project="",  # resolution happens in P1-1
                file_path="",
                line=0,
                metadata={
                    "stub": True,
                    "callee_text": call.callee_text,
                    "receiver_text": call.receiver_text,
                },
            )
        )
        edges.append(
            GraphEdge(
                id=edge_id("CALLS", caller_id, callee_id),
                source_id=caller_id,
                target_id=callee_id,
                type="CALLS",
                # Low confidence because the callee is unresolved text.
                # P1-1's resolver will rewrite the edge with a higher
                # confidence once same-class / same-package / import
                # matching is in place.
                confidence=0.3,
                metadata={
                    "language": result.language,
                    "resolution_level": "unresolved",
                    "line": call.line,
                },
            )
        )

    return nodes, edges


def collect_multilang_files(
    services: Iterable[Any],
    config: Any,
    walk_project: Any,
    path_filter: Any,
) -> list[tuple[str, str, Path]]:
    """Walk all services and collect (project, rel_path, abs_path) for
    every multi-language file that the structural parser can handle.

    This is the multilang counterpart of the Java task collection loop
    in ``indexer.reindex_workspace``. It lives here rather than inline
    so the indexer body stays readable.
    """
    tasks: list[tuple[str, str, Path]] = []
    for svc in services:
        service_root = config.resolve_service_path(svc)
        if not service_root.exists():
            continue
        for path in walk_project(service_root):
            if path_filter is not None and not path_filter(svc, path):
                continue
            if is_structurally_indexable(path):
                rel = config.service_logical_file_path(svc, path)
                tasks.append((svc.name, rel, path))
    return tasks


def diagnostics() -> dict[str, Any]:
    """Snapshot of every cached parser's state — surfaced via
    ``memory-center doctor`` so users can tell which languages are
    actually wired up vs. which need a pip extra."""
    snapshot: dict[str, Any] = {}
    with _CACHE_LOCK:
        for name, parser in _PARSER_CACHE.items():
            snapshot[name] = parser.diagnostics
    return snapshot
