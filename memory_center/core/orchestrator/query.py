from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any

from memory_center.core.assessment.quality import build_quality_summary
from memory_center.core.foundation.result_types import attach_facade_metadata
from memory_center.core.foundation.schemas import with_schema
from memory_center.core.governance.rules import match_rules
from memory_center.core.observability.diagnostics import DIAG, diag_entry
from memory_center.core.observability.operations import observe_operation
from memory_center.core.observability.tracking import log_token_gain
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

from ..verification.heuristics import apply_candidate_path_learning
from ..walkthrough import analysis as _walkthrough_analysis
from ..walkthrough import answer as _wt_answer
from ..walkthrough import escalation as _wt_escalation
from ..walkthrough import operations as _walkthrough_operations
from .compact import _measure_compact_gain
from .contract_filter import _filter_contracts_by_query
from .guidance import _build_agent_next_steps_for_query, _build_agent_next_steps_for_walkthrough
from .lookup_scope import (
    infer_project_from_workspace_context,
    refresh_scoped_query_if_stale,
    resolve_effective_project,
)
from .lookup_shared import ContextLookupPort, DiagnosticsLookupPort, NavigationLookupPort, SymbolLookupPort
from .ranking import (
    _best_match,
    _rrf,
    _symbol_search_text,
    tokenize,
)
from .session_payloads import _event_payload
from .shared import (
    SESSION_EVENTS_FILE,
    _budget_limits,
    _build_progressive_levels,
    _filter_call_edges,
    _is_compact_view,
    _resolve_memory_ref,
    load_context,
    preferred_edge_types,
    summarize_chain_edges,
)
from .symbol_ranking import (
    _dedupe_symbol_display_matches,
    _pick_symbol_declaration_fallback,
    _project_matches,
    _rebuild_summary_after_filter,
    _rerank_symbol_like_matches,
)

METHOD_WALKTHROUGH_SCHEMA_VERSION = _walkthrough_analysis.METHOD_WALKTHROUGH_SCHEMA_VERSION
_METHOD_WALKTHROUGH_CACHE_TTL_SECONDS = _walkthrough_analysis.DEFAULT_CACHE_TTL_SECONDS
_METHOD_WALKTHROUGH_CACHE_MAX_ITEMS = _walkthrough_analysis.DEFAULT_CACHE_MAX_ITEMS
_METHOD_WALKTHROUGH_CACHE = _walkthrough_analysis.default_walkthrough_cache()
_JAVA_CHAIN_SYMBOL_RE = re.compile(
    r"((?:[a-z_][\w$]*\.)+[A-Z][\w$]*(?:#[a-zA-Z_][\w$]*)?|[A-Z][\w$]*(?:#[a-zA-Z_][\w$]*)?)"
)


def _symbol_port() -> SymbolLookupPort:
    return SymbolLookupPort(load_context=load_context, hybrid_query=memory_query_hybrid, infer_active_project=infer_project_from_workspace_context, project_matches=_project_matches, build_lookup_payload=_build_lookup_payload, dedupe_symbols=_dedupe_symbol_display_matches, rerank_symbols=_rerank_symbol_like_matches, best_match=_best_match, fallback_symbol=_pick_symbol_declaration_fallback, project_evidence=_build_project_evidence, augmented_lookup=_build_augmented_lookup_payload, is_compact=_is_compact_view, compact_symbol=_compact_symbol_result, measure_compact=_measure_compact_gain)


def _context_port() -> ContextLookupPort:
    return ContextLookupPort(load_context=load_context, symbol_resolver=memory_symbol, build_project_scope=_build_project_scope, project_evidence=_build_project_evidence, is_compact=_is_compact_view, compact_context=_compact_context_result, measure_compact=_measure_compact_gain)


def _navigation_port() -> NavigationLookupPort:
    return NavigationLookupPort(load_context=load_context, symbol_resolver=memory_symbol, resolve_project=resolve_effective_project, project_matches=_project_matches, project_evidence=_build_project_evidence, build_project_scope=_build_project_scope, preferred_edges=preferred_edge_types, filter_edges=_filter_call_edges, is_compact=_is_compact_view, compact_chain=_compact_chain_result, measure_compact=_measure_compact_gain, symbol_search_text=_symbol_search_text)


def _diagnostics_port() -> DiagnosticsLookupPort:
    return DiagnosticsLookupPort(load_context=load_context, event_payload=_event_payload, resolve_ref=_resolve_memory_ref, with_schema=with_schema)


def _extract_symbol_like_token(*values: str) -> str:
    for raw in values:
        text = (raw or "").strip()
        if not text:
            continue
        matches = _JAVA_CHAIN_SYMBOL_RE.findall(text)
        if matches:
            matches.sort(key=len, reverse=True)
            return matches[0]
    return ""


def _walkthrough_symbol_from_query(query: str, intent: dict[str, Any]) -> str:
    if not intent.get("is_full_chain"):
        return ""
    symbol = _extract_symbol_like_token(query)
    if "#" not in symbol:
        return ""
    return symbol


def _assertion_summary(store: WorkspaceStore) -> dict[str, Any]:
    """Return a constant-size assertion view for default query responses."""
    try:
        # 默认 lookup 仅展示聚合计数；断言正文和时间排序只在 assertion 详情页读取。
        from memory_center.core.knowledge.assertions import sparse_assertion_summary
        from memory_center.core.storage.runtime import RuntimeStore

        with RuntimeStore(store.graph_db_path) as graph:
            summary = sparse_assertion_summary(store, static_count=int(graph.counts().get("edges", 0)))
    except Exception:
        return {"active": 0, "verified": 0, "inferred": 0, "stale": 0, "next_action": "运行 reindex 生成断言侧车"}
    statuses = summary.get("by_status", {}) if isinstance(summary, dict) else {}
    stale = int(statuses.get("STALE", 0) or 0)
    verified = int(statuses.get("VERIFIED", 0) or 0)
    inferred = int(statuses.get("INFERRED", 0) or 0)
    result = {
        "active": int(summary.get("active", 0) or 0),
        "verified": verified,
        "inferred": inferred,
        "stale": stale,
        "next_action": "刷新关联索引" if stale else ("验证高风险推断" if inferred else "按需展开证据"),
    }
    return result


@observe_operation(
    "memory_query_hybrid",
    workspace_resolver=lambda args, kwargs: args[0] if args else kwargs["workspace_file"],
    tags_resolver=lambda args, kwargs: {"limit": kwargs.get("limit", args[2] if len(args) > 2 else 20)},
)
def memory_query_hybrid(
    workspace_file: str | Path,
    query: str,
    limit: int = 20,
    node_types: list[str] | None = None,
    config: Any = None,
    project: str = "",
    *,
    enable_vector: bool | None = None,
    vector_weight: float | None = None,
    enable_reranker: bool | None = None,
    session_id: str = "",
) -> dict[str, Any]:
    """Enhanced query using hybrid retrieval engine.

    Combines graph, sparse, and semantic search with intelligent routing.
    Provides stable, evidence-scoped retrieval for the active workspace.

    session_id 可选:提供时,本会话此前已交付过的文件会被有界降权(跨调用
    去重);账本读取失败降级为不去重,不影响查询。
    """
    # Lazy import to avoid circular dependency
    from ..retrieval.hybrid import HybridRetrievalConfig, detect_query_intent
    from .lookup_execution import execute_hybrid_retrieval
    from .lookup_decorators import apply_project_scope

    started = time.perf_counter()
    timings: dict[str, float] = {}
    config_obj = load_context(workspace_file)
    store = config_obj[1]
    from memory_center.core.knowledge.aliases import expand_verified_alias_query

    alias_expansion = expand_verified_alias_query(store, query)
    query = str(alias_expansion["query"])
    project_scope = resolve_effective_project(workspace_file, project)
    effective_project = str(project_scope.get("project", "") or "")
    timings["setup"] = _elapsed_ms(started)
    phase_started = time.perf_counter()

    # Convert config if needed
    if config is None:
        config = HybridRetrievalConfig()
    else:
        config = copy.deepcopy(config)

    if enable_vector is not None:
        config.enable_vector = bool(enable_vector)
    if vector_weight is not None:
        config.vector_weight = max(0.0, float(vector_weight))
    if enable_reranker is not None:
        config.enable_reranker = bool(enable_reranker)

    # Detect query intent first
    intent = detect_query_intent(query)
    walkthrough_symbol = _walkthrough_symbol_from_query(query, intent)
    if walkthrough_symbol:
        result = memory_method_walkthrough(
            workspace_file,
            walkthrough_symbol,
            depth=4,
            limit=max(limit, 20),
            project=effective_project,
            view="compact",
            budget="small",
            report_level="standard",
        )

        result["mode_used"] = "query_walkthrough"
        result["query"] = query
        result["query_symbol"] = walkthrough_symbol
        result["intent_analysis"] = intent
        result["workspace"] = result.get("workspace") or config_obj[0].workspace
        result["agent_next_steps"] = _build_agent_next_steps_for_walkthrough(result)
        from memory_center.core.knowledge.state import attach_knowledge_state

        return attach_knowledge_state(store, result, query=query, project=effective_project, mode="memory_query_hybrid")

    freshness_banner: dict[str, Any]
    try:
        from ..freshness.status import IndexFreshnessService

        freshness_banner = IndexFreshnessService(workspace_file).banner()
    except Exception as exc:
        freshness_banner = diag_entry(DIAG.UNKNOWN, exc=exc)
    freshness_input = (
        freshness_banner.get("freshness", {})
        if isinstance(freshness_banner, dict)
        else {}
    )
    targeted_refresh = refresh_scoped_query_if_stale(
        workspace_file,
        query,
        effective_project,
        freshness_status=str(freshness_input.get("status", "") or ""),
    )
    try:
        from ..verification.heuristics import load_retrieval_source_weights

        learned_weights = load_retrieval_source_weights(
            workspace_file,
            intent=str(intent.get("primary_intent", "general") or "general"),
        )
    except Exception:
        learned_weights = {}
    timings["freshness_and_policy"] = _elapsed_ms(phase_started)
    phase_started = time.perf_counter()

    result, shard_graph_used, shard_available = execute_hybrid_retrieval(
        store, workspace_file, query, config=config, node_types=node_types, limit=limit,
        freshness=freshness_input, learned_weights=learned_weights, effective_project=effective_project,
    )
    timings["core_retrieval"] = _elapsed_ms(phase_started)
    phase_started = time.perf_counter()

    # 已服务文件有界降权(跨调用去重):仅当提供 session_id 且账本可读时生效。
    from .lookup_session import apply_served_file_downweight, record_lookup_delivery

    result = apply_served_file_downweight(result, workspace_file, session_id)

    result = apply_project_scope(
        result, effective_project=effective_project, shard_available=shard_available, intent=intent,
        project_matches=_project_matches, rebuild_summary=_rebuild_summary_after_filter,
    )

    # Enrich with workspace context
    result["workspace"] = config_obj[0].workspace
    result["intent_analysis"] = intent
    result["project_scope"] = {
        "requested": project,
        "effective": effective_project,
        "source": project_scope.get("source", "none"),
    }
    result["targeted_refresh"] = targeted_refresh

    from .lookup_contracts import attach_contract_context

    result = attach_contract_context(
        result, workspace_file=str(workspace_file), query=query, intent=intent,
        effective_project=effective_project, contract_loader=memory_contracts,
        filter_contracts=_filter_contracts_by_query, project_matches=_project_matches,
    )
    timings["scope_and_contracts"] = _elapsed_ms(phase_started)
    phase_started = time.perf_counter()

    # 向后兼容：添加 matches 字段（旧接口返回 matches，新接口返回 results）
    if "results" in result and "matches" not in result:
        result["matches"] = result["results"]
    elif "results" in result:
        result["matches"] = result["results"]

    result["results"] = _rerank_symbol_like_matches(result.get("results", []), query)
    result["matches"] = result["results"]
    result["assertion_summary"] = _assertion_summary(store)
    result["identity_resolution"] = alias_expansion["identity_resolution"]
    timings["assertion_summary"] = _elapsed_ms(phase_started)
    phase_started = time.perf_counter()

    # 确保 retrieval_summary 包含旧接口期望的字段
    if "retrieval_summary" in result:
        summary = result["retrieval_summary"]
        if "exact_matches" not in summary:
            summary["exact_matches"] = summary.get("source_distribution", {}).get("graph", 0)
        if "semantic_matches" not in summary:
            summary["semantic_matches"] = summary.get("source_distribution", {}).get("semantic", 0)

    from .lookup_response import finalize_hybrid_response

    response_started = time.perf_counter()
    result = finalize_hybrid_response(
        result, store=store, workspace_file=workspace_file, query=query, effective_project=effective_project,
        freshness_banner=freshness_banner, session_id=session_id, timings=timings, elapsed=_elapsed_ms,
        started=started, phase_started=phase_started, guidance_builder=_build_agent_next_steps_for_query,
        record_delivery=record_lookup_delivery,
    )
    timings["response_envelope"] = _elapsed_ms(response_started)
    result["performance"]["timing_ms"]["response_envelope"] = timings["response_envelope"]
    return result


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def memory_context(
    workspace_file: str | Path,
    name: str,
    max_depth: int = 2,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
) -> dict[str, Any]:
    """Compatibility facade; context aggregation lives in lookup_context."""
    from .lookup_context import build_context

    return build_context(workspace_file, name, max_depth=max_depth, project=project, view=view, budget=budget, deps=_context_port())


def memory_symbol(
    workspace_file: str | Path, name: str, limit: int = 10, project: str = "", view: str = "full", budget: str = "medium",
) -> dict[str, Any]:
    """Compatibility facade; symbol resolution lives in lookup_symbols."""
    from .lookup_symbols import resolve_symbol
    return resolve_symbol(workspace_file, name, limit=limit, project=project, view=view, budget=budget, deps=_symbol_port())


def _infer_project_from_fqn(fqn: str, workspace_file: str | Path) -> str:
    """Try to infer the project name from a fully-qualified class name.

    E.g.  cn.kaipuyun.cloud.openapi.biz.service.impl.website.safe.FooServiceImpl
    → segments = [cn, kaipuyun, cloud, openapi, biz, service, impl, ...]
    → try matching 'openapi' against known project names in the workspace.

    Scoring: prefer segments that appear as a distinct word-boundary in the
    project name (e.g. 'openapi' in 'ucap-cloud-open-api' splits on '-'
    and 'openapi' matches the concatenation of adjacent parts 'open'+'api').
    """
    parts = fqn.replace("#", ".").split(".")
    segments = [p for p in parts[:-1] if p and p[0].islower()]

    # Common Java package segments that are useless for project disambiguation
    _PACKAGE_STOPWORDS = {
        "cn", "com", "org", "net", "io", "app", "api", "biz", "service",
        "impl", "common", "core", "dto", "vo", "entity", "config", "util",
        "utils", "controller", "mapper", "dao", "repository", "model",
        "bean", "factory", "handler", "listener", "filter", "interceptor",
        "aspect", "annotation", "web", "rest", "rpc", "client", "server",
        "base", "lib", "sdk", "starter", "autoconfigure", "properties",
        "website", "safe", "back", "front", "admin", "manager", "task",
        "job", "schedule", "message", "mq", "cache", "data", "storage",
    }

    config, _store = load_context(workspace_file)
    projects = [s.name for s in config.services] if hasattr(config, "services") else []

    best_proj = ""
    best_score = 0
    for seg in reversed(segments):
        if len(seg) < 3 or seg in _PACKAGE_STOPWORDS:
            continue
        candidates: list[tuple[str, int]] = []
        for proj in projects:
            proj_lower = proj.lower()
            proj_parts = proj_lower.replace("-", "_").split("_")

            if seg == proj_lower:
                score = 100
            elif seg in proj_parts:
                score = 80
            else:
                matched = False
                for i in range(len(proj_parts)):
                    for j in range(i + 2, min(i + 5, len(proj_parts) + 1)):
                        if "".join(proj_parts[i:j]) == seg:
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    score = 70
                elif seg in proj_lower:
                    score = 50
                else:
                    continue
            candidates.append((proj, score))

        # Prefer unique matches: if only one project matches this segment, bonus +20
        if len(candidates) == 1:
            proj, score = candidates[0]
            score += 20
            if score > best_score:
                best_score = score
                best_proj = proj
        elif len(candidates) > 1:
            # Multiple projects match — pick highest score, but no uniqueness bonus
            for proj, score in candidates:
                if score > best_score:
                    best_score = score
                    best_proj = proj

        if best_score >= 90:
            break

    return best_proj


def memory_callers(workspace_file: str | Path, symbol: str, depth: int = 2, limit: int = 80, edge_type_filter: list[str] | None = None, project: str = "", view: str = "full", budget: str = "medium", min_confidence: float = 0.85, explicit_symbol: str = "") -> dict[str, Any]:
    from .lookup_navigation import traverse
    return traverse(workspace_file, symbol, direction="upstream", depth=depth, limit=limit, edge_type_filter=edge_type_filter, project=project, view=view, budget=budget, min_confidence=min_confidence, explicit_symbol=explicit_symbol, deps=_navigation_port())


def memory_callees(workspace_file: str | Path, symbol: str, depth: int = 2, limit: int = 80, edge_type_filter: list[str] | None = None, project: str = "", view: str = "full", budget: str = "medium", min_confidence: float = 0.85, explicit_symbol: str = "") -> dict[str, Any]:
    from .lookup_navigation import traverse
    return traverse(workspace_file, symbol, direction="downstream", depth=depth, limit=limit, edge_type_filter=edge_type_filter, project=project, view=view, budget=budget, min_confidence=min_confidence, explicit_symbol=explicit_symbol, deps=_navigation_port())


def memory_method_walkthrough(
    workspace_file: str | Path,
    symbol: str,
    depth: int = 4,
    limit: int = 80,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
    report_level: str = "standard",
    _allow_workspace_escalation: bool = True,
) -> dict[str, Any]:
    """Build a method-level walkthrough from indexed Java evidence.

    This is intentionally evidence-bounded: it explains indexed method calls,
    DTO field reads, config/data-resource hints, and graph downstream edges.
    It does not pretend to execute Java control flow.
    """
    project_scope = resolve_effective_project(workspace_file, project)
    effective_project = str(project_scope.get("project", "") or "")

    def _lookup_provider(ws: Path, sym: str, proj: str) -> dict[str, Any]:
        return memory_symbol(ws, sym, limit=5, project=proj).get("lookup", {}) or {}

    def _escalation_runner(**call_kwargs: Any) -> dict[str, Any]:
        return _try_escalated_method_walkthrough(
            call_kwargs["workspace_file"],
            call_kwargs["symbol"],
            call_kwargs["depth"],
            call_kwargs["limit"],
            call_kwargs["project"],
            call_kwargs["view"],
            call_kwargs["budget"],
            call_kwargs["report_level"],
            current_result=call_kwargs.get("current_result"),
            allow=True,
        )

    result = _walkthrough_analysis.build_walkthrough_result(
        workspace_file,
        symbol,
        depth=depth,
        limit=limit,
        project=effective_project,
        view=view,
        budget=budget,
        report_level=report_level,
        allow_workspace_escalation=_allow_workspace_escalation,
        cache=_METHOD_WALKTHROUGH_CACHE,
        lookup_provider=_lookup_provider,
        escalation_runner=_escalation_runner,
    )
    result.setdefault("project_scope", {}).update(
        {
            "requested": project,
            "effective": effective_project,
            "source": project_scope.get("source", "none"),
        }
    )
    return result


def memory_walkthrough_health(
    workspace_file: str | Path,
    symbol: str = "",
    project: str = "",
    report_level: str = "standard",
) -> dict[str, Any]:
    """Check method walkthrough readiness and output contract for a workspace."""
    return _walkthrough_operations.build_walkthrough_health(
        workspace_file, symbol=symbol, project=project, report_level=report_level,
        walkthrough_provider=memory_method_walkthrough, cache=_METHOD_WALKTHROUGH_CACHE,
    )


def memory_eval_walkthrough_quality(
    workspace_file: str | Path,
    symbol: str,
    project: str = "",
    report_level: str = "standard",
) -> dict[str, Any]:
    """Evaluate whether a method walkthrough result is agent-ready."""
    return _walkthrough_operations.evaluate_walkthrough(
        workspace_file, symbol, project=project, report_level=report_level,
        walkthrough_provider=memory_method_walkthrough,
    )


def memory_export_walkthrough_artifact(
    workspace_file: str | Path,
    symbol: str,
    project: str = "",
    report_level: str = "deep",
    title: str = "",
) -> dict[str, Any]:
    """Export a method walkthrough Markdown artifact under artifacts/walkthroughs."""
    return _walkthrough_operations.export_walkthrough(
        workspace_file, symbol, project=project, report_level=report_level,
        title=title, walkthrough_provider=memory_method_walkthrough,
    )


def _walkthrough_index_signature(store: Any) -> dict[str, float]:
    return _wt_escalation.walkthrough_index_signature(store)


def _method_walkthrough_cache_key(
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
            "index_signature": _walkthrough_index_signature(store),
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def _try_escalated_method_walkthrough(
    workspace_file: str | Path,
    symbol: str,
    depth: int,
    limit: int,
    project: str,
    view: str,
    budget: str,
    report_level: str,
    current_result: dict[str, Any] | None,
    allow: bool,
) -> dict[str, Any]:
    if not allow:
        return {}
    candidate = _wt_escalation.find_parent_or_covering_workspace(workspace_file)
    if not candidate:
        return {}
    candidate_path = str(candidate)
    current_path = str(Path(workspace_file).expanduser().resolve())
    if candidate_path == current_path:
        return {}
    try:
        escalated = memory_method_walkthrough(
            candidate_path,
            symbol,
            depth=depth,
            limit=limit,
            project=project,
            view="full",
            budget=budget,
            report_level=report_level,
            _allow_workspace_escalation=False,
        )
    except Exception as exc:
        if current_result is not None:
            current_result["workspace_escalation"] = _wt_escalation.build_workspace_escalation_status(
                workspace_file,
                status="candidate_failed",
                candidate_workspace=candidate_path,
                reason=str(exc),
            )
        return {}
    if not escalated.get("found"):
        return {}
    if current_result is not None and _wt_escalation.walkthrough_quality_score(escalated) <= _wt_escalation.walkthrough_quality_score(current_result):
        return {}
    escalated["workspace_escalation"] = _wt_escalation.build_workspace_escalation_status(
        workspace_file,
        status="escalated",
        candidate_workspace=candidate_path,
        reason="父级或覆盖当前项目的聚合 workspace 返回了更完整的跨服务 walkthrough。",
    )
    escalated["answer_markdown"] = _render_method_walkthrough_answer(escalated, candidate_path, report_level=report_level)
    if _is_compact_view(view):
        compact = _compact_method_walkthrough_result(escalated, budget=budget)
        compact["workspace_escalation"] = escalated["workspace_escalation"]
        compact["answer_markdown"] = escalated["answer_markdown"]
        return compact
    return escalated


def _compact_method_walkthrough_result(result: dict[str, Any], budget: str = "medium") -> dict[str, Any]:
    return _wt_answer.compact_method_walkthrough_result(result, budget=budget, cache_ttl_seconds=_METHOD_WALKTHROUGH_CACHE_TTL_SECONDS)


def _render_method_walkthrough_answer(result, workspace_file, report_level: str = "standard") -> str:
    return _wt_answer.render_method_walkthrough_answer(result, workspace_file, report_level=report_level)


def _steps_to_calls(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [step for step in steps if step.get("kind") == "method_call"]


# === End walkthrough helper shims =========================================


def memory_search_code(workspace_file: str | Path, query: str, scope: str = "", limit: int = 20, project: str = "") -> dict[str, Any]:
    from .lookup_navigation import search_code
    return search_code(workspace_file, query, scope=scope, limit=limit, project=project, deps=_navigation_port())


def memory_contracts(workspace_file: str | Path, project: str = "") -> dict[str, Any]:
    _, store = load_context(workspace_file)
    def scoped(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not project:
            return rows
        return [row for row in rows if _project_matches(project, str(row.get("project", "") or ""))]

    return {
        "feign_contracts": scoped(store.read_json_prefer_backend("feign-index.json", [])),
        "mq_contracts": scoped(store.read_json_prefer_backend("mq-index.json", [])),
        "api_contracts": scoped(store.read_json_prefer_backend("api-index.json", [])),
        "config_contracts": scoped(store.read_json_prefer_backend("config-index.json", [])),
        "rules": match_rules(store, intent="contract feign dto message api", scopes=["contract", "dto", "feign", "message"]),
    }


def memory_ref_get(workspace_file: str | Path, ref_id: str) -> dict[str, Any]:
    from .lookup_diagnostics import get_ref
    return get_ref(workspace_file, ref_id, deps=_diagnostics_port())


def memory_ref_batch(workspace_file: str | Path, ref_ids: list[str]) -> dict[str, Any]:
    from .lookup_diagnostics import get_ref_batch
    return get_ref_batch(workspace_file, ref_ids, deps=_diagnostics_port())


def memory_backend_query(workspace_file: str | Path, **filters: Any) -> dict[str, Any]:
    from .lookup_diagnostics import backend_query
    return backend_query(workspace_file, deps=_diagnostics_port(), **filters)


def memory_tool_usage_report(workspace_file: str | Path, limit: int = 200) -> dict[str, Any]:
    from .lookup_diagnostics import tool_usage_report
    return tool_usage_report(workspace_file, limit=limit, deps=_diagnostics_port())


def memory_discover(workspace_file: str | Path, limit: int = 50) -> dict[str, Any]:
    from .lookup_diagnostics import discover
    return discover(workspace_file, limit=limit, deps=_diagnostics_port())


# ---- internal helpers -------------------------------------------------------

def _compress_chain_tree(edges: list[dict[str, Any]]) -> dict[str, Any]:
    tree: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        src = e.get("source", {}).get("name", "?")
        tgt = e.get("target", {}).get("name", "?")
        tgt_proj = e.get("target", {}).get("project", "")
        edge_type = e.get("type", "")
        depth = e.get("depth", 0)
        tree.setdefault(src, []).append({
            "target": tgt, "type": edge_type,
            "project": tgt_proj, "depth": depth,
        })
    return {
        "tree": tree,
        "depth_reached": max((e.get("depth", 0) for e in edges), default=0),
        "total_edges": len(edges),
        "unique_sources": len(tree),
    }


def _format_chain_endpoint(node: dict[str, Any]) -> str:
    name = str(node.get("name", "") or "?")
    line = int(node.get("line", 0) or 0)
    return f"{name}:{line}" if line > 0 else name


def _format_compact_node_summary(node: dict[str, Any]) -> str:
    node_type = str(node.get("type", "") or "").strip()
    name = str(node.get("name", "") or "?").strip()
    project = str(node.get("project", "") or "").strip()
    line = int(node.get("line", 0) or 0)
    parts = [part for part in (node_type, name) if part]
    text = " ".join(parts) if parts else name
    if project and line > 0:
        return f"{text} @ {project}:{line}"
    if project:
        return f"{text} @ {project}"
    if line > 0:
        return f"{text} @ line {line}"
    return text


def _build_edge_summary_lines(prefix: str, items: list[dict[str, Any]], limit: int) -> list[str]:
    lines: list[str] = []
    for item in items[:limit]:
        text = str(item.get("text", "") or "").strip()
        if text:
            lines.append(f"{prefix}: {text}")
    return lines


def _compact_node_evidence(item: dict[str, Any]) -> dict[str, Any]:
    node = item.get("node", item) or {}
    return {
        "type": node.get("type", ""),
        "name": node.get("name", ""),
        "project": node.get("project", ""),
        "file_path": node.get("file_path", ""),
        "line": node.get("line", 0),
        "score": round(float(item.get("score", item.get("exact_score", 0.0)) or 0.0), 4),
    }


def _build_project_scope(requested_project: str, anchor: dict[str, Any]) -> dict[str, Any]:
    anchor_project = str(anchor.get("project", "") or "")
    requested = str(requested_project or "").strip()
    return {
        "requested_project": requested,
        "anchor_project": anchor_project,
        "uses_cross_project_anchor": bool(requested and anchor_project and not _project_matches(requested, anchor_project)),
    }


def _build_project_evidence(items: list[dict[str, Any]], anchor: dict[str, Any], requested_project: str, limit: int = 5) -> list[dict[str, Any]]:
    requested = str(requested_project or "").strip()
    if not requested:
        return []
    anchor_id = str(anchor.get("id", "") or "")
    evidence: list[dict[str, Any]] = []
    for item in items:
        node = item.get("node", item) or {}
        if not _project_matches(requested, str(node.get("project", "") or "")):
            continue
        if anchor_id and str(node.get("id", "") or "") == anchor_id:
            continue
        evidence.append(_compact_node_evidence(item))
    return evidence[:limit]


def _build_lookup_entrypoint(item: dict[str, Any], *, role: str = "") -> dict[str, Any]:
    node = item.get("node", {}) or {}
    payload = {
        "node": node,
        "retrieval_sources": item.get("retrieval_sources", item.get("sources", [])),
        "exact_score": item.get("exact_score", item.get("rrf_score", item.get("score", 0.0))),
        "semantic_score": item.get("semantic_score", item.get("score", 0.0) if "semantic" in item.get("sources", []) else 0.0),
        "workspace_ref": item.get("workspace_ref", ""),
        "workspace": item.get("workspace", ""),
    }
    if role:
        payload["role"] = role
    return payload


def _node_to_lookup_item(node: dict[str, Any], *, role: str, score: float = 0.0, sources: list[str] | None = None) -> dict[str, Any]:
    return {
        "node": node,
        "score": score,
        "exact_score": score,
        "sources": sources or [],
        "retrieval_sources": sources or [],
        "role": role,
    }


def _build_augmented_lookup_payload(
    result: dict[str, Any],
    *,
    anchor_node: dict[str, Any] | None = None,
    project_evidence: list[dict[str, Any]] | None = None,
    match_key: str = "matches",
    limit: int = 5,
) -> dict[str, Any]:
    matches = _dedupe_symbol_display_matches(result.get(match_key, []))[:limit]
    entrypoints: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_signatures: set[tuple[str, str, str, int]] = set()

    def add_entry(item: dict[str, Any], role: str = "") -> None:
        node = item.get("node", {}) or {}
        node_id = str(node.get("id", "") or f"{node.get('type','')}::{node.get('project','')}::{node.get('name','')}")
        signature = (
            str(node.get("type", "") or ""),
            str(node.get("project", "") or ""),
            str(node.get("name", "") or ""),
            int(node.get("line", 0) or 0),
        )
        if node_id in seen_ids:
            return
        if signature in seen_signatures:
            return
        seen_ids.add(node_id)
        seen_signatures.add(signature)
        entrypoints.append(_build_lookup_entrypoint(item, role=role or item.get("role", "")))

    if anchor_node:
        add_entry(_node_to_lookup_item(anchor_node, role="anchor", score=999.0, sources=["symbol_anchor"]), role="anchor")
    for evidence in (project_evidence or [])[:limit]:
        add_entry(
            _node_to_lookup_item(
                evidence,
                role="project_evidence",
                score=float(evidence.get("score", 0.0) or 0.0),
                sources=["project_scope"],
            ),
            role="project_evidence",
        )
    for item in matches:
        add_entry(item)

    return {
        "query": result.get("query", result.get("target", result.get("name", ""))),
        "retrieval_summary": result.get("retrieval_summary", {}),
        "entrypoints": entrypoints[:limit],
    }


def _summarize_chain_edges(edges: list[dict[str, Any]]) -> dict[str, Any]:
    return summarize_chain_edges(edges)


def _compact_focus_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not edges:
        return []
    filtered = [
        edge for edge in edges
        if not (
            (edge.get("source", {}) or {}).get("name", "") == (edge.get("target", {}) or {}).get("name", "")
            and (edge.get("source", {}) or {}).get("project", "") == (edge.get("target", {}) or {}).get("project", "")
        )
    ]
    if not filtered:
        filtered = list(edges)
    structural_types = {"DECLARES", "CONTAINS", "IMPORTS"}
    if any(edge.get("type") not in structural_types for edge in filtered):
        focused = [edge for edge in filtered if edge.get("type") not in structural_types]
        if focused:
            return focused
    return filtered


def _compact_chain_result(result: dict[str, Any], direction: str, budget: str = "medium") -> dict[str, Any]:

    limits = _budget_limits(budget)
    target = result.get("target", {}) or {}
    lookup = result.get("lookup", {}) or {}
    entrypoints = lookup.get("entrypoints", []) or []
    summary = result.get("chain_summary", {}) or {}
    items = summary.get("items", []) or []
    summary_lines = [f"Target {_format_compact_node_summary(target)}"]
    project_evidence = result.get("project_evidence", []) or []
    if result.get("project_scope", {}).get("uses_cross_project_anchor"):
        summary_lines.append(
            f"Project scope {result.get('project_scope', {}).get('requested_project', '')} uses anchor {target.get('project', '')}"
        )
    for evidence in project_evidence[: limits["events"]]:
        summary_lines.append(f"Project evidence: {_format_compact_node_summary(evidence)}")
    summary_lines.extend(
        _build_edge_summary_lines("Caller" if direction == "callers" else "Callee", items, limits["steps"] + limits["events"])
    )
    # P1-A: anchor/scope validation must survive compaction — the claim
    # boundary gate reads them from the compact chain payload.
    compact = {
        "symbol": result.get("symbol", ""),
        "found": result.get("found", False),
        "direction": direction,
        "depth": result.get("depth", 0),
        "target": {
            "type": target.get("type", ""),
            "name": target.get("name", ""),
            "project": target.get("project", ""),
            "file_path": target.get("file_path", ""),
            "line": target.get("line", 0),
        },
        "chain_summary": {
            "items": items[: limits["steps"] + limits["events"]],
            "total_edges": summary.get("total_edges", 0),
            "depth_reached": summary.get("depth_reached", 0),
            "type_counts": summary.get("type_counts", {}),
        },
        "project_scope": result.get("project_scope", {}),
        "project_evidence": project_evidence[: limits["events"]],
        "summary_lines": summary_lines,
        "lookup": {
            "query": lookup.get("query", ""),
            "retrieval_summary": lookup.get("retrieval_summary", {}),
            "entrypoints": [
                {
                    "type": (item.get("node", {}) or {}).get("type", ""),
                    "name": (item.get("node", {}) or {}).get("name", ""),
                    "project": (item.get("node", {}) or {}).get("project", ""),
                    "line": (item.get("node", {}) or {}).get("line", 0),
                    "exact_score": item.get("exact_score", 0),
                }
                for item in entrypoints[: limits["events"]]
            ],
        },
    }
    if isinstance(result.get("chain_anchor_validation"), dict):
        compact["chain_anchor_validation"] = result["chain_anchor_validation"]
    if isinstance(result.get("chain_scope_validation"), dict):
        compact["chain_scope_validation"] = result["chain_scope_validation"]
    if isinstance(result.get("fallback_action"), dict):
        compact["fallback_action"] = result["fallback_action"]
    if result.get("anchor_candidate_only"):
        compact["anchor_candidate_only"] = True
    return compact


def _compact_symbol_result(result: dict[str, Any], budget: str = "medium") -> dict[str, Any]:

    limits = _budget_limits(budget)
    best = result.get("best_match", {}) or {}
    matches = result.get("matches", []) or []
    compact_matches = []
    for item in matches[: limits["events"]]:
        node = item.get("node", {}) or {}
        compact_matches.append(
            {
                "type": node.get("type", ""),
                "name": node.get("name", ""),
                "project": node.get("project", ""),
                "line": node.get("line", 0),
                "score": round(float(item.get("score", item.get("exact_score", 0.0)) or 0.0), 4),
            }
        )
    summary_lines: list[str] = []
    if best:
        summary_lines.append(f"Best {_format_compact_node_summary(best)}")
    for item in compact_matches:
        summary_lines.append(f"Match {_format_compact_node_summary(item)} (score={item['score']})")
    payload = {
        "name": result.get("name", ""),
        "found": result.get("found", False),
        "best_match": {
            "type": best.get("type", ""),
            "name": best.get("name", ""),
            "project": best.get("project", ""),
            "file_path": best.get("file_path", ""),
            "line": best.get("line", 0),
        },
        "matches": compact_matches,
        "lookup": {
            "query": (result.get("lookup", {}) or {}).get("query", ""),
            "retrieval_summary": (result.get("lookup", {}) or {}).get("retrieval_summary", {}),
        },
        "summary_lines": summary_lines,
    }
    if result.get("disambiguation"):
        payload["disambiguation"] = result.get("disambiguation", {})
    return payload


def _compact_context_result(result: dict[str, Any], budget: str = "medium") -> dict[str, Any]:
    from ..reasoning.integration import compact_reasoning_view

    limits = _budget_limits(budget)
    node = result.get("node", {}) or {}
    incoming = result.get("incoming", []) or []
    outgoing = result.get("outgoing", []) or []
    incoming_summary = _summarize_chain_edges(_compact_focus_edges(incoming))
    outgoing_summary = _summarize_chain_edges(_compact_focus_edges(outgoing))
    lookup = result.get("lookup", {}) or {}
    summary_lines = [f"Node {_format_compact_node_summary(node)}"]
    project_evidence = result.get("project_evidence", []) or []
    if result.get("project_scope", {}).get("uses_cross_project_anchor"):
        summary_lines.append(
            f"Project scope {result.get('project_scope', {}).get('requested_project', '')} uses anchor {node.get('project', '')}"
        )
    for evidence in project_evidence[: limits["events"]]:
        summary_lines.append(f"Project evidence: {_format_compact_node_summary(evidence)}")
    summary_lines.extend(
        _build_edge_summary_lines("Incoming", incoming_summary.get("items", []), limits["steps"] + limits["events"])
    )
    summary_lines.extend(
        _build_edge_summary_lines("Outgoing", outgoing_summary.get("items", []), limits["steps"] + limits["events"])
    )
    return {
        "name": result.get("name", ""),
        "found": result.get("found", False),
        "node": {
            "type": node.get("type", ""),
            "name": node.get("name", ""),
            "project": node.get("project", ""),
            "file_path": node.get("file_path", ""),
            "line": node.get("line", 0),
        },
        "evidence_summary": result.get("evidence_summary", {}),
        "incoming_summary": {
            "items": incoming_summary.get("items", [])[: limits["steps"] + limits["events"]],
            "total_edges": incoming_summary.get("total_edges", 0),
            "depth_reached": incoming_summary.get("depth_reached", 0),
            "type_counts": incoming_summary.get("type_counts", {}),
        },
        "outgoing_summary": {
            "items": outgoing_summary.get("items", [])[: limits["steps"] + limits["events"]],
            "total_edges": outgoing_summary.get("total_edges", 0),
            "depth_reached": outgoing_summary.get("depth_reached", 0),
            "type_counts": outgoing_summary.get("type_counts", {}),
        },
        "project_scope": result.get("project_scope", {}),
        "project_evidence": project_evidence[: limits["events"]],
        "summary_lines": summary_lines,
        "lookup": {
            "query": lookup.get("query", ""),
            "retrieval_summary": lookup.get("retrieval_summary", {}),
            "entrypoints": [
                {
                    "type": (item.get("node", {}) or {}).get("type", ""),
                    "name": (item.get("node", {}) or {}).get("name", ""),
                    "project": (item.get("node", {}) or {}).get("project", ""),
                    "line": (item.get("node", {}) or {}).get("line", 0),
                    "exact_score": item.get("exact_score", 0),
                }
                for item in (lookup.get("entrypoints", []) or [])[: limits["events"]]
            ],
        },
        "_reasoning": compact_reasoning_view(result.get("_reasoning", {}), limit=2),
    }


def _annotate_phantom_nodes(chain_result: dict[str, Any], workspace_file: str | Path) -> None:
    config, store = load_context(workspace_file)
    topology = store.read_json_prefer_backend("service-topology.json", {})
    local_services = {svc.get("service_name") or svc.get("name") for svc in topology.get("services", [])}
    edges_key = "callers" if "callers" in chain_result else "callees"
    for edge in chain_result.get(edges_key, []):
        if edge.get("type") != "CALLS_SERVICE":
            continue
        target = edge.get("target", {})
        if target.get("type") == "Service" and target.get("name", "") not in local_services:
            hint = edge.get("metadata", {}).get("target_service") or target.get("name", "")
            target["_is_external_service"] = True
            target["_external_service_hint"] = hint
            edge["_is_external_service"] = True
            edge["_external_service_hint"] = hint
            edge["_boundary_type"] = "feign-service-phantom"


def _merge_workspace_query_hits(
    graph: RuntimeStore,
    query: str,
    exact_nodes: list[dict[str, Any]],
    semantic_hits: list[dict[str, Any]],
    limit: int,
    alpha: float | None = None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    target_types = set()
    for rank, node in enumerate(exact_nodes, start=1):
        node_id = node.get("id")
        if not node_id:
            continue
        target_types.add(node.get("type", ""))
        item = merged.setdefault(
            node_id,
            {
                "node": node,
                "neighbors": graph.traverse_edges(node_id, direction="both", max_depth=1, limit=20),
                "exact_score": 0.0,
                "semantic_score": 0.0,
                "best_rank": rank,
                "retrieval_sources": [],
            },
        )
        item["exact_score"] += _rrf(rank)
        item["best_rank"] = min(item["best_rank"], rank)
        if "exact" not in item["retrieval_sources"]:
            item["retrieval_sources"].append("exact")
    for semantic_rank, hit in enumerate(semantic_hits, start=1):
        node_id = hit.get("node_id")
        if not node_id:
            continue
        node = graph.node_by_id(node_id)
        if not node:
            continue
        target_types.add(node.get("type", ""))
        item = merged.setdefault(
            node_id,
            {
                "node": node,
                "neighbors": graph.traverse_edges(node_id, direction="both", max_depth=1, limit=20),
                "exact_score": 0.0,
                "semantic_score": 0.0,
                "best_rank": semantic_rank + 1000,
                "retrieval_sources": [],
            },
        )
        item["semantic_score"] = max(item["semantic_score"], float(hit.get("score", 0.0)))
        if "semantic" not in item["retrieval_sources"]:
            item["retrieval_sources"].append("semantic")
    resolved_target_types = _resolve_query_target_types(query, sorted(t for t in target_types if t))
    matches = list(merged.values())
    matches.sort(key=lambda item: _workspace_query_match_key(item, resolved_target_types, alpha=alpha))
    return matches[:limit]


def _workspace_query_match_key(item: dict[str, Any], target_types: list[str], alpha: float | None = None) -> tuple:
    node = item.get("node", {})
    priority = _query_node_priority(node.get("type", ""), target_types)
    sources = set(item.get("retrieval_sources", []))
    hybrid_rank = 0 if {"exact", "semantic"} <= sources else 1 if "exact" in sources else 2 if "semantic" in sources else 3
    exact_score = float(item.get("exact_score", 0.0))
    semantic_score = float(item.get("semantic_score", 0.0))
    if alpha is not None:
        # Blended scoring: alpha * exact + (1-alpha) * semantic + dual_bonus
        dual_bonus = 0.1 if {"exact", "semantic"} <= sources else 0.0
        blended = alpha * exact_score + (1 - alpha) * semantic_score + dual_bonus
        return (priority, -blended, -exact_score, -semantic_score, int(item.get("best_rank", 9999)), node.get("name", ""))
    return (
        priority,
        hybrid_rank,
        -exact_score,
        -semantic_score,
        int(item.get("best_rank", 9999)),
        node.get("name", ""),
    )


def _query_node_priority(node_type: str, target_types: list[str]) -> int:
    priorities: dict[str, int] = {}
    types = set(target_types)
    if {"FeignClient", "FeignMethod", "Endpoint"} & types:
        priorities.update({"FeignClient": 0, "FeignMethod": 1, "Endpoint": 2, "Class": 3, "Method": 4, "File": 5})
    if {"MQTopic", "MQConsumer"} & types:
        priorities.update({"MQTopic": 0, "MQConsumer": 1, "ConfigKey": 2, "Class": 3, "File": 4})
    if "ConfigKey" in types:
        priorities.update({"ConfigKey": 0, "Class": 1, "File": 2})
    if not priorities:
        priorities.update({"Class": 0, "Method": 1, "Field": 2, "File": 3})
    return priorities.get(node_type, 20)


def _resolve_query_target_types(target: str, target_types: list[str]) -> list[str]:
    resolved = set(t for t in target_types if t)
    target_lower = target.lower()
    service_indicators = {"service", "api", "common", "gateway", "server", "app", "web", "ui", "frontend", "backend", "admin", "portal"}
    hyphen_like = "-" in target_lower and not any(ind in target_lower for ind in service_indicators)
    topic_like = hyphen_like or any(token in target_lower for token in ["topic", "kafka", "rocketmq", "consumer", "producer", "listener"])
    if "feign" in target_lower:
        resolved.update({"FeignClient", "FeignMethod"})
    if target_lower.startswith("/") or any(token in target_lower for token in ["controller", "endpoint"]):
        resolved.add("Endpoint")
    if topic_like:
        resolved.add("MQTopic")
    if "." in target_lower and not topic_like:
        resolved.add("ConfigKey")
    if topic_like and "MQTopic" in resolved:
        resolved.discard("ConfigKey")
    return _sort_target_types(list(resolved))


def _sort_target_types(target_types: list[str]) -> list[str]:
    priority = {
        "FeignClient": 0, "FeignMethod": 1, "Endpoint": 2, "MQTopic": 3, "MQConsumer": 4,
        "ConfigKey": 5, "Field": 6, "Method": 7, "Class": 8, "File": 20,
    }
    return sorted({item for item in target_types if item}, key=lambda item: (priority.get(item, 10), item))


def _summarize_query_matches(matches: list[dict[str, Any]], limit: int) -> dict[str, int]:
    summary = {"exact_matches": 0, "semantic_matches": 0, "hybrid_matches": 0, "total_matches": len(matches), "returned_matches": min(len(matches), limit)}
    for item in matches:
        sources = set(item.get("retrieval_sources", []))
        if "exact" in sources:
            summary["exact_matches"] += 1
        if "semantic" in sources:
            summary["semantic_matches"] += 1
        if {"exact", "semantic"} <= sources:
            summary["hybrid_matches"] += 1
    return summary


def _build_search_progressive_view(query: str, scope: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_progressive_levels(
        {"query": query, "scope": scope, "top_hit_count": len(hits), "top_paths": [item.get("path", "") for item in hits[:3]]},
        {
            "top_projects": sorted({item.get("project", "") for item in hits[:5] if item.get("project")}),
            "scored_hits": [{"path": item.get("path", ""), "score": item.get("score", 0)} for item in hits[:5]],
        },
        {"next_action": "对 top_paths 调用 memory_symbol / memory_context 深挖。", "full_paths": [item.get("path", "") for item in hits]},
    )


def _build_query_progressive_view(query: str, matches: list[dict[str, Any]], semantic_hits: list[dict[str, Any]], related_cases: list[dict[str, Any]]) -> dict[str, Any]:
    top_nodes = [item.get("node", {}) for item in matches[:3]]
    return _build_progressive_levels(
        {
            "query": query,
            "top_nodes": [f"{item.get('type', '')}:{item.get('name', '')}" for item in top_nodes if item.get("name")],
            "top_sources": [item.get("retrieval_sources", []) for item in matches[:3]],
        },
        {
            "entrypoints": [
                {
                    "id": item.get("node", {}).get("id", ""),
                    "type": item.get("node", {}).get("type", ""),
                    "name": item.get("node", {}).get("name", ""),
                    "exact_score": item.get("exact_score", 0.0),
                    "semantic_score": item.get("semantic_score", 0.0),
                }
                for item in matches[:5]
            ],
            "semantic_candidates": [
                {"node_id": item.get("node_id", ""), "name": item.get("node", {}).get("name", ""), "score": item.get("score", 0.0)}
                for item in semantic_hits[:5]
            ],
        },
        {
            "neighbor_preview": {
                item.get("node", {}).get("name", ""): [edge.get("type", "") for edge in item.get("neighbors", [])[:4]]
                for item in matches[:3]
            },
            "related_case_tasks": [item.get("task", "") for item in related_cases[-3:]],
        },
    )


def _build_context_progressive_view(node: dict[str, Any], incoming: list[dict[str, Any]], outgoing: list[dict[str, Any]]) -> dict[str, Any]:
    return _build_progressive_levels(
        {
            "node": f"{node.get('type', '')}:{node.get('name', '')}",
            "incoming_count": len(incoming),
            "outgoing_count": len(outgoing),
        },
        {
            "incoming_edge_types": sorted({item.get("type", "") for item in incoming if item.get("type")}),
            "outgoing_edge_types": sorted({item.get("type", "") for item in outgoing if item.get("type")}),
            "high_confidence_edges": [
                item.get("type", "")
                for item in (incoming + outgoing)
                if float(item.get("confidence", 0.0)) >= 0.80
            ][:8],
        },
        {
            "incoming_preview": [f"{item.get('source', {}).get('name', '')} -> {item.get('type', '')}" for item in incoming[:8]],
            "outgoing_preview": [f"{item.get('type', '')} -> {item.get('target', {}).get('name', '')}" for item in outgoing[:8]],
        },
    )


def _build_lookup_payload(result: dict[str, Any], match_key: str = "matches", limit: int = 5) -> dict[str, Any]:
    return _build_augmented_lookup_payload(result, match_key=match_key, limit=limit)


def _build_context_evidence_summary(incoming: list[dict[str, Any]], outgoing: list[dict[str, Any]]) -> dict[str, Any]:
    all_edges = incoming + outgoing
    return {
        "incoming_edges": len(incoming),
        "outgoing_edges": len(outgoing),
        "high_confidence_edges": sum(1 for item in all_edges if float(item.get("confidence", 0.0)) >= 0.80),
        "edge_types": sorted({item.get("type", "") for item in all_edges if item.get("type")}),
    }


def _build_impact_evidence_summary(confirmed: list[dict[str, Any]], probable: list[dict[str, Any]], possible: list[dict[str, Any]]) -> dict[str, Any]:
    impacts = confirmed + probable + possible
    return {
        "confirmed_count": len(confirmed),
        "probable_count": len(probable),
        "possible_count": len(possible),
        "edge_types": sorted({item.get("type", "") for item in impacts if item.get("type")}),
    }
