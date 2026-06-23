"""End-to-end walkthrough assembly.

This module owns the full ``build_walkthrough_result`` pipeline: input
resolution, store loading, cache check, target resolution, continuation
assembly, freshness/diff/risk enrichment, escalation, answer rendering, and
compact view shaping.  ``orchestrator.query.memory_method_walkthrough``
becomes a thin facade that calls into this runner so the orchestrator stops
owning walkthrough internals.

The runner stays decoupled from the orchestrator by:

- Importing ``load_context`` and a few shared helpers from
  ``orchestrator.common`` (these are workspace primitives, not
  walkthrough-specific code).
- Receiving the ``GraphStore`` neighbour-edges loader through a callable
  (defaults to using the workspace store's graph DB).
- Receiving the optional ``memory_symbol`` lookup callable through a parameter
  so that unit tests can stub it without spinning up the full orchestrator.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..completion import evaluate_walkthrough_completion
from ..graph import GraphStore, node_id
from ..result_types import attach_facade_metadata
from ..tracking import log_token_gain
from . import answer as _wt_answer
from . import continuations as _wt_continuations
from . import escalation as _wt_escalation
from . import risks as _wt_risks
from . import symbols as _wt_symbols
from .cache import WalkthroughCache

__all__ = [
    "METHOD_WALKTHROUGH_SCHEMA_VERSION",
    "DEFAULT_CACHE_TTL_SECONDS",
    "DEFAULT_CACHE_MAX_ITEMS",
    "default_walkthrough_cache",
    "method_walkthrough_cache_key",
    "build_walkthrough_result",
]


METHOD_WALKTHROUGH_SCHEMA_VERSION = _wt_answer.METHOD_WALKTHROUGH_SCHEMA_VERSION
DEFAULT_CACHE_TTL_SECONDS = 15
DEFAULT_CACHE_MAX_ITEMS = 64


_DEFAULT_CACHE: WalkthroughCache = WalkthroughCache(
    ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
    max_items=DEFAULT_CACHE_MAX_ITEMS,
)


def default_walkthrough_cache() -> WalkthroughCache:
    """Return the process-wide walkthrough cache.

    Tests that want isolation can construct their own ``WalkthroughCache`` and
    pass it via ``build_walkthrough_result(..., cache=...)``.
    """
    return _DEFAULT_CACHE


def method_walkthrough_cache_key(
    workspace_file: str | Path,
    symbol: str,
    depth: int,
    limit: int,
    project: str,
    view: str,
    budget: str,
    report_level: str,
    store: Any,
) -> str:
    """Stable cache key for one walkthrough invocation.

    The store-derived ``index_signature`` invalidates cached results whenever
    any of the underlying index files changes, without needing to plumb
    explicit invalidation calls.
    """
    return json.dumps(
        {
            "workspace_file": str(Path(workspace_file).expanduser().resolve()),
            "symbol": symbol,
            "depth": depth,
            "limit": limit,
            "project": project,
            "view": view,
            "budget": budget,
            "report_level": report_level,
            "index_signature": _wt_escalation.walkthrough_index_signature(store),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _is_compact_view(view: str) -> bool:
    return (view or "").lower() in {"compact", "lite", "small"}


def _build_initial_target(entry: dict[str, Any], parsed: dict[str, str], file_abs_map: dict[tuple, str]) -> dict[str, Any]:
    class_name = entry["class_name"]
    method_name = parsed["method"]
    method_node_id = node_id("Method", entry["project"], class_name, method_name)
    method_abs_path = _wt_symbols.resolve_indexed_abs_path(file_abs_map, entry["project"], entry["file"])
    method_line = int((entry["symbol"].get("method_lines") or {}).get(method_name, 0) or 0)
    return {
        "package": entry["symbol"].get("package", ""),
        "class": class_name,
        "method": method_name,
        "project": entry["project"],
        "file_path": entry["file"],
        "absolute_file_path": method_abs_path,
        "line": method_line,
        "node_id": method_node_id,
    }


def _collect_owner_calls_and_dto(entry: dict[str, Any], method_name: str) -> tuple:
    method_calls = [
        dict(call)
        for call in entry["symbol"].get("method_calls", [])
        if call.get("owner_method") == method_name
    ]
    method_calls.sort(key=lambda row: int(row.get("line", 0) or 0))
    dto_field_usages = [
        dict(usage)
        for usage in entry["symbol"].get("dto_field_usages", [])
        if usage.get("owner_method") == method_name
    ]
    dto_field_usages.sort(key=lambda row: int(row.get("line", 0) or 0))
    return method_calls, dto_field_usages


def _build_method_not_found(workspace_file: Path, config: Any, symbol: str, lookup: dict[str, Any]) -> dict[str, Any]:
    return attach_facade_metadata({
        "schema_version": METHOD_WALKTHROUGH_SCHEMA_VERSION,
        "fields_contract": _wt_answer.method_walkthrough_fields_contract(),
        "workspace": getattr(config, "workspace", ""),
        "workspace_file": str(workspace_file),
        "symbol": symbol,
        "found": False,
        "reason": "method not found in java-symbol-index",
        "lookup": lookup,
        "workspace_escalation": _wt_escalation.build_workspace_escalation_status(workspace_file, status="not_found_no_better_workspace"),
    }, operation="memory_method_walkthrough", result_kind="walkthrough", evidence_level="indexed_static_analysis")


def _build_invalid_symbol(workspace_file: Path, config: Any, symbol: str) -> dict[str, Any]:
    return attach_facade_metadata({
        "schema_version": METHOD_WALKTHROUGH_SCHEMA_VERSION,
        "fields_contract": _wt_answer.method_walkthrough_fields_contract(),
        "workspace": getattr(config, "workspace", ""),
        "workspace_file": str(workspace_file),
        "symbol": symbol,
        "found": False,
        "reason": "method_walkthrough requires Class#method",
        "example": "com.example.ArticleService#listByDto",
    }, operation="memory_method_walkthrough", result_kind="walkthrough", evidence_level="input_validation")


def build_walkthrough_result(
    workspace_file: str | Path,
    symbol: str,
    *,
    depth: int = 4,
    limit: int = 80,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
    report_level: str = "standard",
    allow_workspace_escalation: bool = True,
    cache: WalkthroughCache | None = None,
    lookup_provider: Callable[[Path, str, str], dict[str, Any]] | None = None,
    escalation_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one method walkthrough result end-to-end.

    Parameters mirror ``memory_method_walkthrough``.  ``cache`` defaults to the
    process-wide cache; ``lookup_provider`` is invoked when the requested
    symbol is not found and the runner needs a ``lookup`` payload to attach;
    ``escalation_runner`` is the callback used to retry against a parent /
    covering / sibling workspace and is normally provided by the orchestrator.
    """

    # Lazy imports keep the runner decoupled from orchestrator-level pipelines
    # while still re-using their already-tested helpers.
    from ..orchestrator.common import (
        _budget_limits,
        _filter_call_edges,
        load_context,
        summarize_chain_edges,
    )

    walkthrough_cache = cache or default_walkthrough_cache()
    workspace_file = _wt_escalation.resolve_walkthrough_workspace_input(workspace_file)
    config, store = load_context(workspace_file)
    active_workspace_file = str(Path(workspace_file).expanduser().resolve())

    symbols = store.read_json_prefer_backend("java-symbol-index.json", [])
    feigns = store.read_json_prefer_backend("feign-index.json", [])
    apis = store.read_json_prefer_backend("api-index.json", [])
    file_abs_map = _wt_symbols.build_file_abs_path_map(config, store)

    cache_key = method_walkthrough_cache_key(
        workspace_file, symbol, depth, limit, project, view, budget, report_level, store,
    )
    cached = walkthrough_cache.get(cache_key)
    if cached:
        return cached

    parsed = _wt_symbols.parse_method_walkthrough_symbol(symbol)
    if not parsed.get("method"):
        return _build_invalid_symbol(workspace_file, config, symbol)

    entry = _wt_symbols.find_method_symbol_entry(symbols, parsed, project=project)
    if not entry:
        if allow_workspace_escalation and escalation_runner is not None:
            escalated = escalation_runner(
                workspace_file=workspace_file,
                symbol=symbol,
                depth=depth,
                limit=limit,
                project=project,
                view=view,
                budget=budget,
                report_level=report_level,
                current_result=None,
            )
            if escalated:
                return escalated
        lookup = {}
        if lookup_provider is not None:
            try:
                lookup = lookup_provider(workspace_file, symbol, project) or {}
            except Exception:
                lookup = {}
        return _build_method_not_found(workspace_file, config, symbol, lookup)

    target = _build_initial_target(entry, parsed, file_abs_map)
    method_name = parsed["method"]
    method_calls, dto_field_usages = _collect_owner_calls_and_dto(entry, method_name)

    local_steps = _wt_continuations.build_method_local_steps(method_calls, dto_field_usages, feigns)
    feign_continuations = _wt_continuations.build_method_feign_continuations(
        entry, method_name, method_calls, feigns, apis, symbols, file_abs_map,
    )
    local_service_continuations = _wt_continuations.build_service_impl_continuations(
        symbols, entry, method_calls, file_abs_map, feigns, apis,
    )
    same_class_continuations = _wt_continuations.build_same_class_method_continuations(
        symbols, entry, method_name, file_abs_map, feigns, apis,
    )

    downstream_edges: list[dict[str, Any]] = []
    with GraphStore(store.graph_db_path) as graph:
        downstream_edges = graph.neighbors(
            target["node_id"],
            direction="downstream",
            max_depth=depth,
            limit=limit,
            edge_types={"HANDLES_ENDPOINT", "PRODUCES_TOPIC", "CALLS_METHOD", "CALLS_SERVICE", "IMPLEMENTS_FEIGN", "INJECTS_BEAN"},
        )
    downstream_edges = _filter_call_edges(downstream_edges, direction="downstream")[:limit]
    downstream_summary = summarize_chain_edges(downstream_edges)

    result: dict[str, Any] = {
        "schema_version": METHOD_WALKTHROUGH_SCHEMA_VERSION,
        "fields_contract": _wt_answer.method_walkthrough_fields_contract(),
        "workspace": getattr(config, "workspace", ""),
        "workspace_file": active_workspace_file,
        "symbol": symbol,
        "found": True,
        "target": target,
        "evidence_level": "indexed_static_analysis",
        "local_steps": local_steps,
        "local_service_continuations": local_service_continuations,
        "same_class_method_continuations": same_class_continuations,
        "method_calls": method_calls,
        "dto_field_usages": dto_field_usages,
        "config_usages": entry["symbol"].get("config_usages", []),
        "data_resources": entry["symbol"].get("data_resources", []),
        "feign_continuations": feign_continuations,
        "downstream_summary": downstream_summary,
        "downstream_edges": downstream_edges,
        "anti_patterns": _wt_answer.build_method_walkthrough_anti_patterns(),
        "agent_usage_policy": _wt_answer.build_method_walkthrough_agent_policy(),
        "next_actions": _wt_continuations.build_method_walkthrough_next_actions(
            feign_continuations, downstream_summary, local_service_continuations, same_class_continuations,
        ),
        "limitations": [
            "基于 reindex 后的静态索引，不展开运行时分支、动态代理和反射。",
            "如果 Feign 服务端不在同一 workspace/group 索引中，只返回 Feign 契约和 endpoint 候选。",
        ],
    }
    result = attach_facade_metadata(
        result,
        operation="memory_method_walkthrough",
        result_kind="walkthrough",
        evidence_level="indexed_static_analysis",
        schema_version=METHOD_WALKTHROUGH_SCHEMA_VERSION,
    )
    result["summary_lines"] = _wt_answer.build_method_walkthrough_summary_lines(
        result["target"],
        local_steps,
        local_service_continuations,
        same_class_continuations,
        feign_continuations,
        downstream_summary,
        _budget_limits(budget),
    )
    result["glossary_hits"] = _wt_answer.build_glossary_hits(workspace_file, result)
    result["performance_risks"] = _wt_risks.build_walkthrough_performance_risks(result)
    result["data_scope_guards"] = _wt_risks.build_data_scope_guards(result)
    result["diff_context"] = _wt_risks.build_walkthrough_diff_context(config, result)
    result["index_freshness"] = _wt_risks.build_walkthrough_index_freshness(
        _wt_escalation.walkthrough_index_signature(store), result,
    )
    result["completion_status"] = evaluate_walkthrough_completion(result)
    result["branch_outline"] = _wt_risks.build_walkthrough_branch_outline(result)
    result["mermaid_flow"] = _wt_risks.build_method_walkthrough_mermaid(result)
    try:
        from ..reasoning.integration import canonical_reasoning_view, run_reasoning_patterns

        result["_reasoning"] = canonical_reasoning_view(
            run_reasoning_patterns(
                str(workspace_file),
                target_id=target["node_id"],
                target_name=symbol,
                max_transitive_depth=depth,
                max_pattern_limit=min(6, max(1, limit)),
                intent="walkthrough",
            )
        )
    except Exception as exc:
        from ..diagnostics import DIAG, diag_entry

        result["_reasoning"] = {
            "facts": [],
            "inferences": [],
            "derived": [],
            "quality": {"status": "unavailable", "verification_required": False},
            "_diagnostics": {"pipeline": diag_entry(DIAG.UNAVAILABLE, exc=exc)},
        }

    if allow_workspace_escalation and escalation_runner is not None:
        escalated = escalation_runner(
            workspace_file=workspace_file,
            symbol=symbol,
            depth=depth,
            limit=limit,
            project=project,
            view=view,
            budget=budget,
            report_level=report_level,
            current_result=result,
        )
        if escalated:
            walkthrough_cache.put(cache_key, escalated)
            return copy.deepcopy(escalated)

    result["workspace_escalation"] = _wt_escalation.build_workspace_escalation_status(
        workspace_file, status="not_needed_or_not_found",
    )
    result["answer_markdown"] = _wt_answer.render_method_walkthrough_answer(
        result, workspace_file, report_level=report_level,
    )
    result["cache"] = {"hit": False, "ttl_seconds": walkthrough_cache.ttl_seconds}

    if _is_compact_view(view):
        from ..orchestrator.compact import _measure_compact_gain  # local import keeps cycles away

        compact = _wt_answer.compact_method_walkthrough_result(
            result, budget=budget, cache_ttl_seconds=walkthrough_cache.ttl_seconds,
        )
        compact = attach_facade_metadata(
            compact,
            operation="memory_method_walkthrough",
            result_kind="walkthrough",
            evidence_level="indexed_static_analysis",
            schema_version=METHOD_WALKTHROUGH_SCHEMA_VERSION,
        )
        gain = _measure_compact_gain(result, compact)
        log_token_gain(
            workspace_file,
            "memory_method_walkthrough",
            budget=budget,
            model="",
            raw_tokens=gain["raw_tokens"],
            compact_tokens=gain["compact_tokens"],
            view=view,
        )
        walkthrough_cache.put(cache_key, compact)
        return copy.deepcopy(compact)

    walkthrough_cache.put(cache_key, result)
    return copy.deepcopy(result)
