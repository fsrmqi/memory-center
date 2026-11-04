"""Public query facades must delegate through dedicated lookup modules."""
from __future__ import annotations

import inspect
from pathlib import Path

from memory_center.core.orchestrator import query


def test_public_lookup_facades_do_not_call_legacy_implementations() -> None:
    for func in (
        query.memory_context, query.memory_symbol, query.memory_callers,
        query.memory_callees, query.memory_search_code, query.memory_ref_get,
        query.memory_ref_batch, query.memory_backend_query,
        query.memory_tool_usage_report, query.memory_discover,
    ):
        assert "_legacy_memory_" not in inspect.getsource(func)


def test_lookup_module_boundaries_exist() -> None:
    from memory_center.core.orchestrator import lookup_context, lookup_diagnostics, lookup_navigation, lookup_symbols
    assert all((lookup_context.build_context, lookup_symbols.resolve_symbol, lookup_navigation.traverse, lookup_diagnostics.backend_query))


def test_leaf_lookup_modules_never_import_query_facade() -> None:
    root = Path(query.__file__).parent
    for name in ("lookup_context.py", "lookup_symbols.py", "lookup_navigation.py", "lookup_diagnostics.py"):
        source = (root / name).read_text(encoding="utf-8")
        assert "from . import query" not in source
        assert "import query as" not in source


def test_lookup_ports_are_feature_scoped_not_service_locator() -> None:
    from memory_center.core.orchestrator.lookup_shared import (
        ContextLookupPort, DiagnosticsLookupPort, NavigationLookupPort, SymbolLookupPort,
    )
    assert len(SymbolLookupPort.__dataclass_fields__) < 16
    assert len(ContextLookupPort.__dataclass_fields__) < 12
    assert len(NavigationLookupPort.__dataclass_fields__) < 18
    assert len(DiagnosticsLookupPort.__dataclass_fields__) <= 4
