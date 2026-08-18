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
from memory_center.core.knowledge.ontology import EntityValidator
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
from .shared import (
    SESSION_EVENTS_FILE,
    _best_match,
    _budget_limits,
    _build_progressive_levels,
    _event_payload,
    _filter_call_edges,
    _is_compact_view,
    _resolve_memory_ref,
    _rrf,
    _symbol_search_text,
    load_context,
    preferred_edge_types,
    summarize_chain_edges,
    tokenize,
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


def _infer_project_from_workspace_context(workspace_file: str | Path) -> str:
    """Prefer the active service when the process is running inside one service root.

    This keeps multi-repo aggregate workspaces ergonomic for auto-routed agent
    calls: if the current cwd is already inside one configured service root,
    same-name symbols should resolve to that service first. If no service root
    matches cwd, or multiple nested roots would match, fall back to no hint.
    """
    try:
        config, _store = load_context(workspace_file)
    except Exception:
        return ""

    cwd = Path.cwd().expanduser().resolve()
    candidates: list[tuple[int, str]] = []
    for service in getattr(config, "services", []) or []:
        try:
            service_root = config.resolve_service_path(service)
            relative = cwd.relative_to(service_root)
        except Exception:
            continue
        depth = len(relative.parts)
        candidates.append((depth, str(service.name or "")))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def _resolve_effective_project(workspace_file: str | Path, project: str = "") -> dict[str, Any]:
    explicit = (project or "").strip()
    if explicit:
        return {"project": explicit, "source": "explicit"}
    inferred = _infer_project_from_workspace_context(workspace_file)
    if inferred:
        return {"project": inferred, "source": "active_service_root"}
    return {"project": "", "source": "none"}


def _refresh_scoped_query_if_stale(
    workspace_file: str | Path,
    query: str,
    project: str,
    *,
    freshness_status: str = "",
) -> dict[str, Any]:
    """Refresh a small relevant scope before a scoped read when freshness requires it."""
    if not project:
        return {"attempted": False, "reason": "no_project_scope"}
    if freshness_status not in {"stale", "pending"}:
        return {"attempted": False, "reason": "index_current"}
    try:
        from ..freshness.targeted_refresh import refresh_query_targets

        return {"attempted": True, **refresh_query_targets(workspace_file, query, limit=4)}
    except Exception as exc:
        return {"attempted": True, "refreshed": False, "reason": f"refresh_unavailable:{type(exc).__name__}"}


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
) -> dict[str, Any]:
    """Enhanced query using hybrid retrieval engine.

    Combines graph, sparse, and semantic search with intelligent routing.
    Provides stable, evidence-scoped retrieval for the active workspace.
    """
    # Lazy import to avoid circular dependency
    from ..retrieval.hybrid import HybridRetrievalConfig, detect_query_intent, hybrid_retrieve

    started = time.perf_counter()
    timings: dict[str, float] = {}
    config_obj = load_context(workspace_file)
    store = config_obj[1]
    from memory_center.core.knowledge.aliases import expand_verified_alias_query

    alias_expansion = expand_verified_alias_query(store, query)
    query = str(alias_expansion["query"])
    project_scope = _resolve_effective_project(workspace_file, project)
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
    targeted_refresh = _refresh_scoped_query_if_stale(
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

    graph_path = store.graph_db_path
    shard_graph_used = False
    shard_available = True
    if effective_project:
        try:
            from ..indexing.control_plane import index_control_status
            from ..indexing.shards import service_shard_graph_path

            generation = str(index_control_status(store).get("active_generation", "") or "")
            shard_path = service_shard_graph_path(store, generation, effective_project) if generation else None
            if shard_path:
                graph_path = shard_path
                shard_graph_used = True
            else:
                shard_available = False
        except Exception:
            shard_available = False
    if not shard_available:
        result = {
            "results": [],
            "total_found": 0,
            "returned": 0,
            "retrieval_summary": {"total": 0, "reason": "service_shard_not_published"},
            "progressive": {"summary": [], "details": [], "evidence": []},
            "index_scope_unavailable": True,
            "index_source": "service_shard_unavailable",
        }
    else:
        with RuntimeStore(graph_path) as graph:
            result = hybrid_retrieve(
                graph=graph,
                workspace_file=str(workspace_file),
                query=query,
                config=config,
                node_types=node_types,
                limit=limit,
                freshness=freshness_input,
                learned_weights=learned_weights,
            )
        result["index_source"] = "service_graph_shard" if shard_graph_used else "global_graph"
    timings["core_retrieval"] = _elapsed_ms(phase_started)
    phase_started = time.perf_counter()

    # Project filtering: explicit project is strict; inferred active-service
    # scope is preferred only when it has evidence, otherwise keep global hits.
    if effective_project and shard_available:
        results = result.get("results", [])
        project_results = [r for r in results if _project_matches(effective_project, r.get("node", {}).get("project", ""))]
        if project_results:
            for r in project_results:
                r["score"] = r.get("score", 0) * 2.0
                r["_project_boost"] = True
            project_results.sort(key=lambda x: x.get("score", 0), reverse=True)
            result["results"] = project_results
            # Rebuild summary fields so they match the filtered result set
            rebuild = _rebuild_summary_after_filter(project_results, intent)
            result["total_found"] = rebuild["total_found"]
            result["returned"] = rebuild["returned"]
            result["retrieval_summary"] = rebuild["retrieval_summary"]
            result["progressive"] = rebuild["progressive"]
        else:
            # No results match the project filter — return empty but consistent
            empty_rebuild = _rebuild_summary_after_filter([], intent)
            result["results"] = []
            result["total_found"] = 0
            result["returned"] = 0
            result["retrieval_summary"] = empty_rebuild["retrieval_summary"]
            result["progressive"] = empty_rebuild["progressive"]

    # Enrich with workspace context
    result["workspace"] = config_obj[0].workspace
    result["intent_analysis"] = intent
    result["project_scope"] = {
        "requested": project,
        "effective": effective_project,
        "source": project_scope.get("source", "none"),
    }
    result["targeted_refresh"] = targeted_refresh

    # 根据意图补充 contracts 索引数据
    primary_intent = intent.get("primary_intent", "general")
    if primary_intent in ("feign", "mq", "endpoint", "config"):
        contracts = memory_contracts(workspace_file, project=effective_project)
        filtered_feign = _filter_contracts_by_query(contracts.get("feign_contracts", []), query, primary_intent)
        filtered_mq = _filter_contracts_by_query(contracts.get("mq_contracts", []), query, primary_intent)
        filtered_api = _filter_contracts_by_query(contracts.get("api_contracts", []), query, primary_intent)
        filtered_config = _filter_contracts_by_query(contracts.get("config_contracts", []), query, primary_intent)

        # Feign 去重（worktree 可能产生重复）
        if filtered_feign:
            seen_interfaces = set()
            deduped_feign = []
            for fc in filtered_feign:
                key = (fc.get("interface", ""), fc.get("project", ""))
                if key not in seen_interfaces:
                    seen_interfaces.add(key)
                    deduped_feign.append(fc)
            filtered_feign = deduped_feign

        # Feign → API 自动关联：只关联查询直接匹配的方法，且路径足够具体
        linked_api = []
        if primary_intent == "feign" and filtered_feign:
            api_by_path = {}
            for c in contracts.get("api_contracts", []):
                p = c.get("path", "")
                # 使用 EntityValidator 验证路径特异性（≥2段）
                validation = EntityValidator.validate_endpoint_path(p)
                if validation["is_specific"]:
                    api_by_path[p] = c
            query_lower_local = query.lower()
            for fc in filtered_feign:
                for m in fc.get("methods", []):
                    method_name = m.get("method_name", "").lower()
                    m_path = m.get("path", "")
                    # 只关联查询直接匹配的方法
                    if query_lower_local in method_name or method_name in query_lower_local:
                        if m_path and m_path in api_by_path:
                            matched_api = dict(api_by_path[m_path])
                            matched_api["_association"] = "feign_method_path"
                            matched_api["_association_confidence"] = 0.85
                            if matched_api not in linked_api:
                                linked_api.append(matched_api)
            # feign 意图：只返回关联的 API
            filtered_api = linked_api

        if effective_project:
            project_feign = [c for c in filtered_feign if _project_matches(effective_project, c.get("project", ""))]
            project_mq = [c for c in filtered_mq if _project_matches(effective_project, c.get("project", ""))]
            project_api = [c for c in filtered_api if _project_matches(effective_project, c.get("project", ""))]
            project_config = [c for c in filtered_config if _project_matches(effective_project, c.get("project", ""))]
            filtered_feign = project_feign
            filtered_mq = project_mq
            filtered_api = project_api
            filtered_config = project_config

        result["contracts"] = {
            "feign_contracts": filtered_feign if primary_intent != "mq" and primary_intent != "config" else [],
            "mq_contracts": filtered_mq if primary_intent != "config" else [],
            "api_contracts": filtered_api if primary_intent != "mq" and primary_intent != "config" else [],
            "config_contracts": filtered_config if primary_intent != "mq" else [],
        }
        if primary_intent in {"mq", "config"}:
            result["contract_routing"] = {
                "mode": "index_first",
                "intent": primary_intent,
                "evidence_count": len(filtered_mq if primary_intent == "mq" else filtered_config),
            }
        # 标记 contracts 数据来源
        if "retrieval_sources" not in result:
            result["retrieval_sources"] = []
        result["retrieval_sources"].append("contracts_index")
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

    # NEXT_PHASE: integrate freshness warnings into query results
    try:
        banner = freshness_banner
        result["freshness"] = banner
        # D-01: Stale risk escalation - if freshness is stale/pending, add warning
        freshness_status = (banner.get("freshness", {}) or {}).get("status", "unknown")
        if freshness_status in ("stale", "pending"):
            from ..freshness.integration import freshness_action_hint, freshness_risk_escalation
            result["_freshness_warning"] = {
                "status": freshness_status,
                "hint": freshness_action_hint(freshness_status),
                "risk_escalation": freshness_risk_escalation(
                    result.get("intent_analysis", {}).get("risk_level", "low"),
                    freshness_status,
                ),
            }
    except Exception as exc:
        result["freshness"] = diag_entry(DIAG.UNKNOWN, exc=exc)

    # F-03: Record query metrics (best-effort)
    try:
        from memory_center.core.observability.metrics import MetricsCollector
        mc = MetricsCollector(workspace_file)
        mc.record("memory_query_hybrid", len(json.dumps(result, ensure_ascii=False)), unit="chars")
    except Exception:
        pass

    freshness_status = str(((result.get("freshness", {}) or {}).get("freshness", {}) or {}).get("status", "unknown"))
    quality_evidence = []
    for item in result.get("results", []) or []:
        sources = set(item.get("sources", []) or item.get("retrieval_sources", []) or [])
        quality_evidence.append({
            "confidence": item.get("score", 0.0),
            "evidence_type": "fact" if sources & {"exact", "graph_exact", "direct_lookup"} else "inferred",
            "evidence_level": item.get("evidence_level", ""),
            "_is_fallback": bool(item.get("_is_fallback", False)),
        })
    result["_quality"] = build_quality_summary(quality_evidence, freshness_status=freshness_status)
    result["agent_next_steps"] = _build_agent_next_steps_for_query(result, query=query, workspace_file=workspace_file)
    try:
        from memory_center.core.knowledge.governance import record_actions

        result["agent_actions"] = record_actions(store, origin=f"memory_query_hybrid:{query}", actions=list(result["agent_next_steps"]))
    except Exception:
        result["agent_actions"] = []
    timings["quality_and_actions"] = _elapsed_ms(phase_started)
    phase_started = time.perf_counter()
    result = attach_facade_metadata(
        result,
        operation="memory_query_hybrid",
        result_kind="lookup",
        evidence_level="hybrid_indexed",
    )
    from memory_center.core.knowledge.state import attach_knowledge_state

    result = attach_knowledge_state(store, result, query=query, project=effective_project, mode="memory_query_hybrid")
    timings["response_envelope"] = _elapsed_ms(phase_started)
    result["performance"] = {"timing_ms": {**timings, "total": _elapsed_ms(started)}}
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
    _, store = load_context(workspace_file)
    symbol_info = memory_symbol(workspace_file, name, limit=8, project=project)
    if not symbol_info.get("found"):
        return {"name": name, "found": False, "matches": [], "lookup": symbol_info.get("lookup", {})}
    node = symbol_info.get("best_match", {}) or {}
    with RuntimeStore(store.graph_db_path) as graph:
        incoming = graph.traverse_edges(node["id"], direction="upstream", max_depth=max_depth, limit=100)
        outgoing = graph.traverse_edges(node["id"], direction="downstream", max_depth=max_depth, limit=100)
    # Integrate unified reasoning patterns into context (C-07)
    reasoning: dict[str, Any] = {"patterns": [], "transitive": [], "risk": []}
    diagnostics: dict[str, Any] = {}
    try:
        from ..reasoning.integration import run_reasoning_patterns
        reasoning = run_reasoning_patterns(
            str(workspace_file),
            target_id=node.get("id", ""),
            target_name=name,
            intent="context",
        )
    except Exception as exc:
        diagnostics["reasoning"] = diag_entry(DIAG.UNAVAILABLE, exc=exc)
    risk_patterns = reasoning.get("risk", [])

    # NEXT_PHASE: integrate freshness into context
    freshness = {}
    try:
        from ..freshness.status import IndexFreshnessService
        svc = IndexFreshnessService(workspace_file)
        freshness = svc.banner()
    except Exception as exc:
        diagnostics["freshness"] = diag_entry(DIAG.UNAVAILABLE, exc=exc)

    result = {
        "name": name,
        "found": True,
        "node": node,
        "incoming": incoming,
        "outgoing": outgoing,
        "lookup": symbol_info.get("lookup", {}),
        "project_scope": _build_project_scope(project, node),
        "project_evidence": _build_project_evidence(symbol_info.get("matches", []), node, project),
        "evidence_summary": _build_context_evidence_summary(incoming, outgoing),
        "progressive": _build_context_progressive_view(node, incoming, outgoing),
        "risk_patterns": risk_patterns,
        "freshness": freshness,
        "_reasoning": reasoning,
    }
    if diagnostics:
        result["_diagnostics"] = diagnostics
    if _is_compact_view(view):
        compact = _compact_context_result(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_context", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def memory_symbol(
    workspace_file: str | Path,
    name: str,
    limit: int = 10,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
) -> dict[str, Any]:
    """Resolve a symbol name to graph nodes.

    When multiple nodes match (e.g. same class name in different modules),
    use ``project`` to disambiguate.  If ``project`` is empty but the query
    looks like a FQN (contains dots and a capitalised tail), the package
    segments are used to guess the project.
    """
    # Prefer the active service root for bare symbols, then fall back to FQN inference.
    inferred_project = project or _infer_project_from_workspace_context(workspace_file)
    if not inferred_project and "." in name and not name.startswith("."):
        inferred_project = _infer_project_from_fqn(name, workspace_file)
    internal_limit = max(limit, min(max(limit * 3, 12), 50))

    lookup = memory_query_hybrid(
        workspace_file,
        name,
        limit=internal_limit,
        node_types=["Class", "Method", "Field", "FeignClient", "FeignMethod", "Endpoint", "MQTopic", "MQConsumer", "ConfigKey", "File"],
        project=inferred_project,
    )
    all_lookup_matches = list(lookup.get("matches", []) or [])
    if inferred_project:
        global_lookup = memory_query_hybrid(
            workspace_file,
            name,
            limit=internal_limit,
            node_types=["Class", "Method", "Field", "FeignClient", "FeignMethod", "Endpoint", "MQTopic", "MQConsumer", "ConfigKey", "File"],
            project="",
        )
        all_lookup_matches = list(global_lookup.get("matches", []) or all_lookup_matches)
        if not lookup.get("matches"):
            lookup = global_lookup
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]

    # If inferred_project is known but no match found in that project,
    # try a direct graph lookup by class name + project
    if inferred_project and not any(_project_matches(inferred_project, m.get("project", "")) for m in matches):
        from memory_center.core.storage.runtime import RuntimeStore
        store = load_context(workspace_file)[1]
        with RuntimeStore(store.graph_db_path) as g:
            # Extract class name from FQN (last segment)
            class_name = name.replace("#", ".").split(".")[-1]
            direct = g.find_nodes(class_name, types=["Class"], limit=50)
            project_nodes = [n for n in direct if _project_matches(inferred_project, n.get("project", ""))]
            if project_nodes:
                # Prepend project-matched nodes
                lookup.setdefault("matches", [])
                for node in project_nodes:
                    lookup["matches"].insert(0, {"node": node, "score": 999.0, "sources": ["direct_lookup"]})
                matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]
    if not matches:
        return {"name": name, "found": False, "matches": [], "lookup": _build_lookup_payload(lookup)}

    # If project is known, filter ALL results to that project
    if inferred_project:
        project_matches = [m for m in matches if _project_matches(inferred_project, m.get("project", ""))]
        if project_matches:
            matches = project_matches
        # Also filter the lookup matches list to stay consistent
        lookup_matches = lookup.get("matches", [])
        project_lookup = [m for m in lookup_matches if _project_matches(inferred_project, (m.get("node") or {}).get("project", ""))]
        if project_lookup:
            lookup["matches"] = project_lookup

    lookup["matches"] = _dedupe_symbol_display_matches(_rerank_symbol_like_matches(lookup.get("matches", []), name))
    matches = [item.get("node", {}) for item in lookup.get("matches", []) if item.get("node")]

    best = _best_match(matches, name)
    fallback_best = _pick_symbol_declaration_fallback(all_lookup_matches, name)
    if fallback_best and best.get("type") == "Field":
        best = fallback_best

    # Group remaining matches by project for disambiguation
    projects_seen: dict[str, int] = {}
    for m in matches:
        p = m.get("project") or ""
        projects_seen[p] = projects_seen.get(p, 0) + 1

    filtered_lookup = lookup.get("matches", [])[:limit]
    project_evidence = _build_project_evidence(filtered_lookup, best, inferred_project, limit=5)
    result: dict[str, Any] = {
        "name": name,
        "found": True,
        "best_match": best,
        "matches": filtered_lookup,
        "lookup": _build_augmented_lookup_payload(lookup, anchor_node=best, project_evidence=project_evidence),
    }
    if len(projects_seen) > 1:
        result["disambiguation"] = {
            "projects": projects_seen,
            "hint": "多个模块包含同名符号，用 project 参数或 FQN 消歧",
        }
    if _is_compact_view(view):
        compact = _compact_symbol_result(result, budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_symbol", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


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


def memory_callers(
    workspace_file: str | Path,
    symbol: str,
    depth: int = 2,
    limit: int = 80,
    edge_type_filter: list[str] | None = None,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
    min_confidence: float = 0.85,
) -> dict[str, Any]:
    info = memory_symbol(workspace_file, symbol, limit=8, project=project)
    if not info.get("found"):
        return {"symbol": symbol, "found": False, "callers": [], "lookup": info.get("lookup", {})}
    node = info["best_match"]
    et = edge_type_filter or preferred_edge_types("upstream")
    with RuntimeStore(load_context(workspace_file)[1].graph_db_path) as graph:
        edges = graph.traverse_edges(node["id"], direction="upstream", max_depth=depth, limit=limit, edge_types=et)
    filtered_edges = _filter_call_edges(edges, direction="upstream")
    callers, confidence_filter = _apply_confidence_filter_with_fallback(filtered_edges, min_confidence, limit)
    result = {
        "symbol": symbol,
        "found": True,
        "target": node,
        "depth": depth,
        "callers": callers,
        "chain_tree": _compress_chain_tree(callers),
        "chain_summary": _summarize_chain_edges(callers),
        "project_scope": _build_project_scope(project, node),
        "project_evidence": _build_project_evidence(info.get("matches", []), node, project),
        "confidence_filter": confidence_filter,
        "lookup": info.get("lookup", {}),
    }
    if _is_compact_view(view):
        compact = _compact_chain_result(result, direction="callers", budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_callers", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def memory_callees(
    workspace_file: str | Path,
    symbol: str,
    depth: int = 2,
    limit: int = 80,
    edge_type_filter: list[str] | None = None,
    project: str = "",
    view: str = "full",
    budget: str = "medium",
    min_confidence: float = 0.85,
) -> dict[str, Any]:
    info = memory_symbol(workspace_file, symbol, limit=8, project=project)
    if not info.get("found"):
        return {"symbol": symbol, "found": False, "callees": [], "lookup": info.get("lookup", {})}
    node = info["best_match"]
    et = edge_type_filter or preferred_edge_types("downstream")
    with RuntimeStore(load_context(workspace_file)[1].graph_db_path) as graph:
        edges = graph.traverse_edges(node["id"], direction="downstream", max_depth=depth, limit=limit, edge_types=et)
    filtered_edges = _filter_call_edges(edges, direction="downstream")
    callees, confidence_filter = _apply_confidence_filter_with_fallback(filtered_edges, min_confidence, limit)
    result = {
        "symbol": symbol,
        "found": True,
        "target": node,
        "depth": depth,
        "callees": callees,
        "chain_tree": _compress_chain_tree(callees),
        "chain_summary": _summarize_chain_edges(callees),
        "project_scope": _build_project_scope(project, node),
        "project_evidence": _build_project_evidence(info.get("matches", []), node, project),
        "confidence_filter": confidence_filter,
        "lookup": info.get("lookup", {}),
    }
    if _is_compact_view(view):
        compact = _compact_chain_result(result, direction="callees", budget=budget)
        gain = _measure_compact_gain(result, compact)
        log_token_gain(workspace_file, "memory_callees", budget=budget, model="", raw_tokens=gain["raw_tokens"], compact_tokens=gain["compact_tokens"], view=view)
        return compact
    return result


def _apply_confidence_filter_with_fallback(
    edges: list[dict[str, Any]],
    min_confidence: float,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    threshold = max(0.0, min(1.0, float(min_confidence or 0.0)))
    status = {
        "requested_min_confidence": threshold,
        "applied_min_confidence": threshold,
        "fallback_to_low_confidence": False,
    }
    if threshold <= 0:
        return edges[:limit], status
    filtered = [item for item in edges if float(item.get("confidence", 0.0) or 0.0) >= threshold]
    if filtered or not edges:
        return filtered[:limit], status
    status["applied_min_confidence"] = 0.0
    status["fallback_to_low_confidence"] = True
    return edges[:limit], status


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
    project_scope = _resolve_effective_project(workspace_file, project)
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
    config, store = load_context(workspace_file)
    keywords = tokenize(query)
    project_scope = _resolve_effective_project(workspace_file, project)
    effective_project = str(project_scope.get("project", "") or "")
    shard_used = False
    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    if effective_project:
        try:
            from ..indexing.control_plane import index_control_status
            from ..indexing.shards import load_service_shard

            generation = str(index_control_status(store).get("active_generation", "") or "")
            shard = load_service_shard(store, generation, effective_project) if generation else None
            if shard:
                files = list(shard.get("files", []) or [])
                symbols = list(shard.get("symbols", []) or [])
                shard_used = True
        except Exception:
            pass
    shard_unavailable = bool(effective_project and not shard_used)
    if not shard_used and not shard_unavailable:
        files = store.read_json_prefer_backend("file-index.json", [])
        symbols = store.read_json_prefer_backend("java-symbol-index.json", [])
    symbol_entries = {}
    for item in symbols:
        key = item.get("file", "")
        symbol_entries.setdefault(key, []).append(item)
    scope_l = scope.lower().strip()

    def collect_hits(project_filter: str = "") -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for item in files:
            path = item.get("path", "")
            if scope_l and scope_l not in path.lower():
                continue
            item_project = item.get("project", "")
            if project_filter and not _project_matches(project_filter, item_project):
                continue
            text = f"{path} {item.get('project', '')} {item.get('service_name', '')}".lower()
            file_symbols = symbol_entries.get(path, [])
            symbol_text = _symbol_search_text(file_symbols).lower()
            score = sum(1 for token in keywords if token in text or token in symbol_text)
            if score <= 0:
                continue
            collected.append(
                {
                    "project": item.get("project", ""),
                    "service_name": item.get("service_name", ""),
                    "path": path,
                    "score": score,
                    "symbol_count": sum(
                        int(sym.get("class_count", 0)) + int(sym.get("method_count", 0)) + int(sym.get("field_count", 0))
                        for sym in file_symbols
                    ),
                    "suffix": item.get("suffix", ""),
                }
            )
        collected.sort(key=lambda row: (-int(row.get("score", 0)), -int(row.get("symbol_count", 0)), row.get("path", "")))
        return collected

    hits = collect_hits(effective_project)
    hits.sort(key=lambda row: (-int(row.get("score", 0)), -int(row.get("symbol_count", 0)), row.get("path", "")))
    result = {
        "workspace": config.workspace,
        "query": query,
        "scope": scope,
        "project_scope": {
            "requested": project,
            "effective": effective_project,
            "source": project_scope.get("source", "none"),
        },
        "hits": hits[:limit],
        "total_hits": len(hits),
        "index_source": "service_shard" if shard_used else ("service_shard_unavailable" if shard_unavailable else "global_graph"),
        "index_scope_unavailable": shard_unavailable,
        "progressive": _build_search_progressive_view(query, scope, hits[:limit]),
        "tips": [
            "命中后可继续调用 memory_symbol / memory_context 深挖。",
            "改动前建议调用 memory_impact 和 workspace_check_rules。",
        ],
    }
    from memory_center.core.knowledge.state import attach_knowledge_state

    return attach_knowledge_state(store, result, query=query, project=effective_project, mode="memory_search_code")


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
    config, store = load_context(workspace_file)
    resolved = _resolve_memory_ref(store, ref_id)
    if not resolved:
        return with_schema(
            "memory_ref",
            {
                "workspace": config.workspace,
                "ref_id": ref_id,
                "kind": "unknown",
                "summary": "",
                "raw": None,
                "timeline_ref": None,
                "found": False,
            },
        )
    raw = resolved.get("raw")
    # Build reverse timeline link from session_id/task_id in raw data
    timeline_ref = None
    if isinstance(raw, dict):
        sid = raw.get("session_id") or (raw.get("event", {}) or {}).get("session_id", "")
        tid = raw.get("task_id") or (raw.get("event", {}) or {}).get("task_id", "")
        if sid or tid:
            params = []
            if tid:
                params.append(f"task_id={tid}")
            if sid:
                params.append(f"session_id={sid}")
            timeline_ref = "/ui/timeline?" + "&".join(params)
    return with_schema(
        "memory_ref",
        {
            "workspace": config.workspace,
            "ref_id": ref_id,
            "kind": resolved.get("kind", "unknown"),
            "summary": resolved.get("summary", ""),
            "raw": resolved.get("raw"),
            "timeline_ref": timeline_ref,
            "found": True,
        },
    )


def memory_ref_batch(workspace_file: str | Path, ref_ids: list[str]) -> dict[str, Any]:
    from memory_center.core.workspace.config import load_workspace_config

    refs = [memory_ref_get(workspace_file, ref_id) for ref_id in ref_ids]
    return with_schema(
        "memory_ref_batch",
        {
            "workspace": load_workspace_config(workspace_file).workspace,
            "requested": ref_ids,
            "found_count": sum(1 for item in refs if item.get("found")),
            "refs": refs,
        },
    )


def memory_backend_query(
    workspace_file: str | Path,
    *,
    collection: str = "",
    record_id: str = "",
    created_after: str = "",
    ref_path: str = "",
    project: str = "",
    payload_type: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    return {
        "workspace": config.workspace,
        "records": store.memory_backend_query_records(collection=collection, record_id=record_id, created_after=created_after, project=project, payload_type=payload_type, limit=limit),
        "refs": store.memory_backend_query_refs(ref_path=ref_path, limit=limit),
    }


def memory_tool_usage_report(
    workspace_file: str | Path,
    limit: int = 200,
) -> dict[str, Any]:
    config, store = load_context(workspace_file)
    events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=max(limit, 1))
    tool_counts: dict[str, int] = {}
    lookup_tool_counts: dict[str, int] = {}
    memory_center_calls = 0
    external_calls = 0
    suspected_bypass: list[dict[str, Any]] = []
    lookup_tools = {
        "memory_symbol_tool", "memory_search_code_tool", "workspace_trace_tool",
        "memory_callers_tool", "memory_callees_tool", "memory_context_tool",
        "memory_impact_tool", "workspace_sniff_tool",
    }
    for event in events:
        if event.get("event_type") != "tool_call":
            continue
        payload = _event_payload(event)
        tool_name = str(payload.get("tool_name") or payload.get("name") or "")
        if not tool_name:
            continue
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        is_memory_center = tool_name.startswith("memory_") or tool_name.startswith("workspace_")
        if is_memory_center:
            memory_center_calls += 1
        else:
            external_calls += 1
        if tool_name in lookup_tools:
            lookup_tool_counts[tool_name] = lookup_tool_counts.get(tool_name, 0) + 1
        payload_text = json.dumps(payload, ensure_ascii=False).lower()
        if not is_memory_center and any(token in payload_text for token in ["class", "method", "feign", "topic", "caller", "callee", "symbol", "controller", "service", "类", "方法", "调用链"]):
            suspected_bypass.append(
                {
                    "session_id": event.get("session_id", ""),
                    "tool_name": tool_name,
                    "query": payload.get("query", "") or payload.get("target", "") or payload.get("text", ""),
                    "reason": "看起来是在做类/符号/调用链检索，但没有走 Memory Center 工具。",
                }
            )
    total_tool_calls = memory_center_calls + external_calls
    summary = {
        "total_tool_calls": total_tool_calls,
        "memory_center_calls": memory_center_calls,
        "external_calls": external_calls,
        "memory_center_ratio": round((memory_center_calls / total_tool_calls), 3) if total_tool_calls else 0.0,
        "lookup_tool_total": sum(lookup_tool_counts.values()),
        "suspected_bypass_count": len(suspected_bypass),
    }
    adoption_hints: list[str] = []
    if sum(lookup_tool_counts.values()) == 0:
        adoption_hints.append("最近会话里几乎没有使用 Memory Center 的 lookup 工具，找类/符号很可能仍主要依赖本地搜索。")
    if suspected_bypass:
        adoption_hints.append("检测到疑似绕过案例，建议继续把类/符号/调用链检索优先协议前置到生成指令里。")
    if summary["memory_center_ratio"] < 0.4 and total_tool_calls:
        adoption_hints.append("Memory Center 工具调用占比较低，可能意味着协议优先级还不够高，或返回结果还不够有吸引力。")
    if not adoption_hints:
        adoption_hints.append("近期使用情况正常，Memory Center 已经开始承担主要检索与连续性职责。")
    return with_schema(
        "tool_usage_report",
        {
            "workspace": config.workspace,
            "summary": summary,
            "tool_counts": dict(sorted(tool_counts.items(), key=lambda item: (-item[1], item[0]))[:20]),
            "lookup_tool_counts": dict(sorted(lookup_tool_counts.items(), key=lambda item: (-item[1], item[0]))),
            "suspected_bypass": suspected_bypass[:20],
            "adoption_hints": adoption_hints,
        },
    )


def memory_discover(
    workspace_file: str | Path,
    limit: int = 50,
) -> dict[str, Any]:
    """Discover hot commands and recommend next actions based on workspace state.

    Inspired by rtk's discover pattern:
    - Hot commands: most frequently used tools/commands
    - Recommended next actions: based on current workspace state
    - Command compression matrix: compact output patterns for common queries
    """
    config, store = load_context(workspace_file)
    events = store.read_jsonl_prefer_backend(SESSION_EVENTS_FILE, limit=max(limit, 200))

    # Analyze hot commands
    tool_counts: dict[str, int] = {}
    recent_queries: list = []
    for event in events:
        if event.get("event_type") != "tool_call":
            continue
        payload = _event_payload(event)
        tool_name = str(payload.get("tool_name") or payload.get("name") or "")
        if tool_name:
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        query = payload.get("query", "") or payload.get("target", "") or payload.get("text", "")
        if query:
            recent_queries.append(query)

    hot_commands = sorted(tool_counts.items(), key=lambda x: -x[1])[:10]

    # Recommended next actions based on workspace state
    recommendations: list = []
    candidate_paths: list[dict[str, Any]] = []
    try:
        from .workspace_ops import workspace_status
        status = workspace_status(workspace_file, view="compact", budget="medium")
        layers = status.get("memory_layers", {})
        if layers.get("L0", {}).get("count", 0) == 0:
            recommendations.append("还没有会话事件，建议先运行 `work-start` 启动工作流")
            candidate_paths.append(
                {
                    "candidate_type": "session_bootstrap",
                    "target": "work-start",
                    "status": "probable",
                    "weight": 0.76,
                    "why": "当前还没有会话事件，先启动工作流能尽快建立上下文轨迹。",
                    "next_action": "先运行 `work-start` 或 `mc_start` 启动任务",
                    "verification_cost": "low",
                }
            )
        if layers.get("L1", {}).get("count", 0) == 0:
            recommendations.append("还没有案例记忆，建议在完成关键操作后运行 `work-sync`")
            candidate_paths.append(
                {
                    "candidate_type": "memory_write",
                    "target": "L1_case_atom",
                    "status": "possible",
                    "weight": 0.7,
                    "why": "当前缺少案例记忆，补齐 case 沉淀可以提升后续复用价值。",
                    "next_action": "在关键阶段后运行 `work-sync` 或 `mc_sync`",
                    "verification_cost": "low",
                }
            )
        if layers.get("L2", {}).get("count", 0) == 0:
            recommendations.append("还没有任务空间，建议运行 `artifact create-task` 创建任务")
            candidate_paths.append(
                {
                    "candidate_type": "task_sync",
                    "target": "new-task-space",
                    "status": "probable",
                    "weight": 0.78,
                    "why": "当前缺少任务空间，先创建 task 能让长任务协作更稳定。",
                    "next_action": "运行 `artifact create-task` 或 `mc_sync(intent=...)`",
                    "verification_cost": "low",
                    "_learning_aliases": [
                        {"candidate_type": "task_sync", "target": "new-task-space"},
                    ],
                }
            )
    except Exception:
        pass

    if not candidate_paths:
        candidate_paths.append(
            {
                "candidate_type": "runtime_governance",
                "target": "continue-current-workflow",
                "status": "possible",
                "weight": 0.62,
                "why": "当前工作区状态整体正常，可继续沿现有工作流推进。",
                "next_action": "继续当前任务；必要时用 `mc_lookup` / `mc_analyze` 深挖",
                "verification_cost": "low",
            }
        )
    candidate_paths = apply_candidate_path_learning(workspace_file, candidate_paths)

    # Command compression matrix — compact aliases for common queries
    compression_matrix = {
        "quick_context": {"command": "mc_lookup", "mode": "auto", "view": "compact", "budget": "small"},
        "full_chain": {"command": "mc_lookup", "mode": "chain", "scope": "cross-service"},
        "impact_check": {"command": "mc_analyze", "depth": "quick"},
        "sync_progress": {
            "command": "mc_sync",
            "usage": "Provide `intent` for sniff sync, or `session_id` for case sync.",
            "required_one_of": ["intent", "session_id"],
        },
        "resume_work": {"command": "mc_resume"},
        "handoff_model": {"command": "mc_handoff"},
        "health_check": {"command": "mc_admin", "action": "health"},
        "audit_check": {"command": "mc_admin", "action": "audit"},
    }

    return {
        "workspace": config.workspace,
        "hot_commands": [{"tool": t, "count": c} for t, c in hot_commands],
        "recent_queries": recent_queries[:10],
        "recommendations": recommendations if recommendations else ["工作区状态正常，继续当前工作"],
        "candidate_paths": candidate_paths,
        "recommended_path": dict(candidate_paths[0]) if candidate_paths else {},
        "compression_matrix": compression_matrix,
    }


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
    return {
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
