from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import yaml

from .graph import GraphEdge, GraphNode, GraphStore, edge_id, node_id

# Keep the tree-sitter wrapper active so fallback reasons remain observable.
try:
    from .indexing.tree_sitter_parser import TreeSitterJavaParser
    _ts_parser = TreeSitterJavaParser()
    _JAVA_PARSER = _ts_parser
    from .indexing import RegexJavaParser  # keep import for emergency fallback path
except Exception:
    from .indexing import RegexJavaParser
    _JAVA_PARSER = RegexJavaParser()
from .models import ApiEndpoint, FeignClient, JavaSymbol, MqEndpoint, WorkspaceConfig, to_dict
from .observability import observe_operation
from .parser_precision import parser_precision_from_diagnostics
from .semantic import build_workspace_semantic_index, build_workspace_semantic_index_partial, semantic_index_stats
from .store import WorkspaceStore

JAVA_EXTENSIONS = {".java"}
CONFIG_NAMES = {"application.yml", "application.yaml", "bootstrap.yml", "bootstrap.yaml"}
IGNORED_DIRS = {
    ".git", ".idea", ".vscode", "target", "build", "dist", "node_modules",
    ".memory-center", ".project-ai", ".symbio", ".claude", ".codex", ".codex-hooks", "__pycache__",
}


@observe_operation(
    "reindex_workspace",
    workspace_resolver=lambda args, kwargs: args[1].workspace_file if len(args) > 1 else kwargs["store"].workspace_file,
    tags_resolver=lambda args, kwargs: {"parallel": bool(kwargs.get("parallel", False))},
)
def reindex_workspace(
    config: WorkspaceConfig,
    store: WorkspaceStore,
    *,
    projects: Sequence[str] | None = None,
    paths: Sequence[str] | None = None,
    parallel: bool = False,
) -> dict[str, Any]:
    """Rebuild deterministic indexes and the local evidence graph."""
    project_filter = {item.strip() for item in (projects or []) if item and item.strip()}
    path_filters = [item.strip() for item in (paths or []) if item and item.strip()]
    partial = bool(project_filter or path_filters)

    old_file_index: list[dict[str, Any]] = store.read_json_prefer_backend("file-index.json", [])
    old_symbol_index: list[dict[str, Any]] = store.read_json_prefer_backend("java-symbol-index.json", [])
    old_api_index: list[dict[str, Any]] = store.read_json_prefer_backend("api-index.json", [])
    old_feign_index: list[dict[str, Any]] = store.read_json_prefer_backend("feign-index.json", [])
    old_mq_index: list[dict[str, Any]] = store.read_json_prefer_backend("mq-index.json", [])
    old_config_index: list[dict[str, Any]] = store.read_json_prefer_backend("config-index.json", [])

    file_index: list[dict[str, Any]] = []
    symbol_index: list[dict[str, Any]] = []
    api_index: list[dict[str, Any]] = []
    feign_index: list[dict[str, Any]] = []
    mq_index: list[dict[str, Any]] = []
    config_index: list[dict[str, Any]] = []
    # Collect feign files for deferred parsing (need complete constant_map first)
    pending_feigns: list[tuple] = []
    java_tasks: list[tuple] = []

    reset_parser_diagnostics = getattr(_JAVA_PARSER, "reset_diagnostics", None)
    if callable(reset_parser_diagnostics):
        reset_parser_diagnostics()

    for svc in config.services:
        if project_filter and svc.name not in project_filter:
            continue
        service_root = config.resolve_service_path(svc)
        if not service_root.exists():
            continue
        for path in walk_project(service_root):
            if path_filters and not _path_matches_filters(config, svc, path, path_filters):
                continue
            rel = config.service_logical_file_path(svc, path)
            file_index.append(
                {
                    "project": svc.name,
                    "service_name": svc.service_name or svc.name,
                    "path": rel,
                    "abs_path": str(path.resolve()),
                    "service_root": str(service_root),
                    "suffix": path.suffix,
                }
            )
            if path.suffix in JAVA_EXTENSIONS:
                java_tasks.append((svc.name, rel, path))
            elif path.name in CONFIG_NAMES:
                config_index.append({"project": svc.name, "path": rel, **parse_yaml_config(path)})

    # Parse Java files (sequential or parallel)
    if parallel and len(java_tasks) > 10:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from .indexing.parallel import estimate_optimal_workers
        workers = estimate_optimal_workers(len(java_tasks))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_parse_java_file, s, r, p): (s, r) for s, r, p in java_tasks}
            for future in as_completed(futures):
                result = future.result()
                if result["symbol"]:
                    symbol_index.append(result["symbol"])
                api_index.extend(result["apis"])
                if result["pending_feign"]:
                    pending_feigns.append(result["pending_feign"])
                mq_index.extend(result["mq"])
    else:
        for svc_name, rel, path in java_tasks:
            result = _parse_java_file(svc_name, rel, path)
            if result["symbol"]:
                symbol_index.append(result["symbol"])
            api_index.extend(result["apis"])
            if result["pending_feign"]:
                pending_feigns.append(result["pending_feign"])
            mq_index.extend(result["mq"])

    # Build constant map from completed symbol scan, then resolve feign target_service
    if partial:
        merged_symbol_index = _merge_index_rows(old_symbol_index, symbol_index, project_filter, path_filters, path_key="file")
    else:
        merged_symbol_index = symbol_index
    constant_map = _build_constant_map(merged_symbol_index)
    for project, rel, text, symbol in pending_feigns:
        feign_index.extend(to_dict(x) for x in parse_feign_clients(project, rel, text, symbol, constant_map))

    if partial:
        merged_file_index = _merge_index_rows(old_file_index, file_index, project_filter, path_filters)
        merged_api_index = _merge_index_rows(old_api_index, api_index, project_filter, path_filters, path_key="file")
        merged_feign_index = _merge_index_rows(old_feign_index, feign_index, project_filter, path_filters, path_key="file")
        merged_mq_index = _merge_index_rows(old_mq_index, mq_index, project_filter, path_filters, path_key="file")
        merged_config_index = _merge_index_rows(old_config_index, config_index, project_filter, path_filters)
    else:
        merged_file_index = file_index
        merged_api_index = api_index
        merged_feign_index = feign_index
        merged_mq_index = mq_index
        merged_config_index = config_index

    topology = build_topology(config, merged_feign_index, merged_api_index, merged_mq_index, merged_config_index)
    store.write_json("file-index.json", merged_file_index)
    store.write_json("java-symbol-index.json", merged_symbol_index)
    store.write_json("api-index.json", merged_api_index)
    store.write_json("feign-index.json", merged_feign_index)
    store.write_json("mq-index.json", merged_mq_index)
    store.write_json("config-index.json", merged_config_index)
    store.write_json("service-topology.json", topology)
    graph_counts = build_graph_store(config, store, project_filter=project_filter, path_filters=path_filters)
    if partial:
        changed_ids = set(graph_counts.get("changed_node_ids", []))
        semantic_counts = build_workspace_semantic_index_partial(store.workspace_file, changed_ids) if changed_ids else {
            **semantic_index_stats(store.workspace_file),
            "mode": "partial-noop",
            "changed_node_count": 0,
        }
    else:
        semantic_counts = build_workspace_semantic_index(store.workspace_file)
    retrieval_counts = _sync_retrieval_indexes(store, semantic_counts)
    parser_diagnostics = _parser_diagnostics(len(java_tasks))
    parser_precision = parser_precision_from_diagnostics(parser_diagnostics)
    graph_summary = {
        **graph_counts,
        "parser": parser_diagnostics["selected_parser"],
        "parser_diagnostics": parser_diagnostics,
        "parser_precision": parser_precision,
    }
    store.write_json("graph-summary.json", graph_summary)
    return {
        "mode": "partial" if partial else "full",
        "filtered_projects": sorted(project_filter),
        "filtered_paths": path_filters,
        "scanned_files": len(file_index),
        "files": len(merged_file_index),
        "symbols": len(merged_symbol_index),
        "apis": len(merged_api_index),
        "feigns": len(merged_feign_index),
        "mq": len(merged_mq_index),
        "configs": len(merged_config_index),
        "graph_nodes": graph_counts.get("nodes", 0),
        "graph_edges": graph_counts.get("edges", 0),
        "semantic_docs": semantic_counts.get("doc_count", 0),
        "parser": parser_diagnostics["selected_parser"],
        "parser_fallback_count": parser_diagnostics["fallback_count"],
        "parser_critical_disagreement_count": parser_diagnostics["critical_disagreement_count"],
        "parser_diagnostics": parser_diagnostics,
        "parser_precision": parser_precision,
        **retrieval_counts,
    }


def _parser_diagnostics(parse_count: int) -> dict[str, Any]:
    diagnostics = getattr(_JAVA_PARSER, "diagnostics", None)
    if isinstance(diagnostics, dict):
        return dict(diagnostics)
    return {
        "selected_parser": getattr(_JAVA_PARSER, "name", "regex") or "regex",
        "tree_sitter_available": False,
        "parse_count": parse_count,
        "native_success_count": 0,
        "fallback_count": 0,
        "fallback_reasons": {},
        "native_disagreement_count": 0,
        "critical_disagreement_count": 0,
    }


def _path_matches_filters(config: WorkspaceConfig, svc, path: Path, path_filters: Sequence[str]) -> bool:
    logical = config.service_logical_file_path(svc, path).replace("\\", "/")
    absolute = str(path.resolve()).replace("\\", "/")
    candidates = {logical, absolute}
    for raw_filter in path_filters:
        normalized = raw_filter.replace("\\", "/").strip("/")
        normalized_abs = raw_filter.replace("\\", "/")
        for candidate in candidates:
            probe = candidate.strip("/")
            if probe == normalized or probe.startswith(normalized + "/"):
                return True
            if candidate == normalized_abs or candidate.startswith(normalized_abs.rstrip("/") + "/"):
                return True
    return False


def _row_matches_scope(
    row: dict[str, Any],
    project_filter: set[str],
    path_filters: Sequence[str],
    *,
    path_key: str = "path",
) -> bool:
    project = str(row.get("project", "") or "")
    # A row is in scope if it matches BOTH project AND path filters.
    # If only project_filter is given (no path_filters), project match suffices.
    # If only path_filters is given (no project_filter), path match suffices.
    # If both are given, the row must match at least one of them.
    project_match = project_filter and project in project_filter
    path_match = False
    if path_filters:
        path_value = str(row.get(path_key, "") or row.get("path", "") or "")
        abs_path = str(row.get("abs_path", "") or "")
        for raw_filter in path_filters:
            normalized = raw_filter.replace("\\", "/").strip("/")
            normalized_abs = raw_filter.replace("\\", "/")
            probe = path_value.replace("\\", "/").strip("/")
            if probe == normalized or probe.startswith(normalized + "/"):
                path_match = True
                break
            if probe and (normalized.endswith(probe) or normalized_abs.endswith(probe)):
                path_match = True
                break
            if abs_path and (abs_path == normalized_abs or abs_path.startswith(normalized_abs.rstrip("/") + "/")):
                path_match = True
                break
    if project_filter and path_filters:
        # Both filters present: row must match project AND/OR path.
        # For _merge_index_rows (removal), we want to remove rows that
        # match the project filter, but only those that also match path
        # if path filters are specified — otherwise over-deletion occurs.
        return project_match and (not path_filters or path_match)
    return project_match or path_match


def _merge_index_rows(
    existing: list[dict[str, Any]],
    refreshed: list[dict[str, Any]],
    project_filter: set[str],
    path_filters: Sequence[str],
    *,
    path_key: str = "path",
) -> list[dict[str, Any]]:
    kept = [
        row for row in existing
        if not _row_matches_scope(row, project_filter, path_filters, path_key=path_key)
    ]
    return kept + refreshed


def walk_project(root: Path) -> Iterable[Path]:
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories so os.walk doesn't descend into them
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            yield path


def safe_read(path: Path, limit: int = 600_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def _parse_java_file(project: str, rel: str, path: Path) -> dict[str, Any]:
    """Parse a single Java file for deferred assembly into indexes."""
    try:
        text = safe_read(path)
        symbol = parse_java_symbols(project, rel, text)
        apis = [to_dict(x) for x in parse_controllers(project, rel, text, symbol)]
        pending_feign = None
        if "FeignClient" in symbol.annotations:
            pending_feign = (project, rel, text, symbol)
        mq = [to_dict(x) for x in parse_mq_endpoints(project, rel, text, symbol)]
        mq.extend(to_dict(x) for x in parse_mq_producers(project, rel, text))
        return {"symbol": to_dict(symbol), "apis": apis, "pending_feign": pending_feign, "mq": mq}
    except Exception:
        return {"symbol": None, "apis": [], "pending_feign": None, "mq": []}


def _sync_retrieval_indexes(store: WorkspaceStore, semantic_index: dict[str, Any]) -> dict[str, int]:
    """Synchronize BM25 and dense vector indexes from the rebuilt graph."""
    from .retrieval.inverted import InvertedIndex
    from .storage.unified import UnifiedStore
    from .storage.vector_index import VectorIndex

    with GraphStore(store.graph_db_path) as graph:
        nodes = graph.all_nodes()

    dense_items = [
        (str(doc.get("node_id", "")), [float(value) for value in doc.get("dense_vector", [])])
        for doc in semantic_index.get("docs", [])
        if doc.get("node_id") and doc.get("dense_vector")
    ]

    with UnifiedStore(store.graph_db_path) as unified:
        bm25_stats = InvertedIndex(unified).rebuild(nodes)

        vector_dimension = len(dense_items[0][1]) if dense_items else 384
        vector_index = VectorIndex(unified, dimension=vector_dimension)
        vector_index.clear()
        vector_count = vector_index.upsert_embeddings_batch(dense_items) if dense_items else 0

    return {
        "bm25_docs": int(bm25_stats.get("doc_count", 0)),
        "vector_embeddings": vector_count,
    }


def _method_line(symbol_by_project_file: dict[tuple[str, str], dict[str, Any]], project: str, file_path: str, method: str) -> int:
    sym = symbol_by_project_file.get((project, file_path), {})
    return int((sym.get("method_lines") or {}).get(method, 0) or 0)


def _class_or_interface_line(symbol_by_project_file: dict[tuple[str, str], dict[str, Any]], project: str, file_path: str, name: str) -> int:
    sym = symbol_by_project_file.get((project, file_path), {})
    return int((sym.get("class_lines") or {}).get(name, 0) or (sym.get("interface_lines") or {}).get(name, 0) or 0)


def parse_java_symbols(project: str, rel: str, text: str) -> JavaSymbol:
    parsed = _JAVA_PARSER.parse(text, rel)
    return JavaSymbol(
        project=project,
        file=rel,
        parser=getattr(_JAVA_PARSER, "selected_parser", getattr(_JAVA_PARSER, "name", "")),
        package=parsed.package,
        classes=parsed.classes,
        interfaces=parsed.interfaces,
        methods=parsed.methods,
        method_signatures=parsed.method_signatures,
        fields=parsed.fields,
        class_lines=parsed.class_lines,
        interface_lines=parsed.interface_lines,
        method_lines=parsed.method_lines,
        field_lines=parsed.field_lines,
        annotations=parsed.annotations,
        imports=parsed.imports,
        field_types=parsed.field_types,
        constants=parsed.constants,
        method_variable_types=parsed.method_variable_types,
        bean_injections=parsed.bean_injections,
        method_calls=parsed.method_calls,
        dto_field_usages=parsed.dto_field_usages,
        config_usages=parsed.config_usages,
        data_resources=parsed.data_resources,
    )


def parse_controllers(project: str, rel: str, text: str, symbol: JavaSymbol) -> list[ApiEndpoint]:
    if "RestController" not in symbol.annotations and "Controller" not in symbol.annotations:
        return []
    context = (
        _annotated_type_context(text, "RestController", ("class",))
        or _annotated_type_context(text, "Controller", ("class",))
    )
    controller = context[0] if context else (symbol.classes or [Path(rel).stem])[0]
    declaration = context[1] if context else text
    body = context[2] if context else text
    constant_map = dict(symbol.constants)
    class_prefix = _mapping_path(extract_annotation_args(declaration, "RequestMapping") or "", constant_map)
    endpoints: list[ApiEndpoint] = []
    pattern = re.compile(
        r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?"
        r"\s*(?:\n|\r|\s)*(?:@[\w()\"=,{}./\s]+\s*)*[^;{=]+?\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    for mapping, args, method_name in pattern.findall(body):
        http = extract_method_from_args(args) if mapping == "RequestMapping" else mapping.replace("Mapping", "").upper()
        endpoints.append(ApiEndpoint(project, rel, controller, http or "REQUEST", join_path(class_prefix, _mapping_path(args, constant_map)), method_name))
    return endpoints


def parse_feign_clients(project: str, rel: str, text: str, symbol: JavaSymbol, constant_map: dict[str, str] | None = None) -> list[FeignClient]:
    if "FeignClient" not in symbol.annotations:
        return []
    interface = (
        _annotated_type_name(text, "FeignClient", ("interface", "class"))
        or (symbol.interfaces or symbol.classes or [Path(rel).stem])[0]
    )
    context = _annotated_type_context(text, "FeignClient", ("interface", "class"))
    body = context[2] if context else text
    ann_args = extract_annotation_args(text, "FeignClient") or ""
    resolved_constants = {**dict(symbol.constants), **dict(constant_map or {})}
    target = extract_named_value(ann_args, "name") or extract_named_value(ann_args, "value") or extract_named_value(ann_args, "serviceId")
    if not target and resolved_constants:
        ref = extract_named_ref(ann_args, "name") or extract_named_ref(ann_args, "value") or extract_named_ref(ann_args, "serviceId")
        if ref:
            target = resolved_constants.get(ref) or resolved_constants.get(ref.split(".")[-1])
    if not target:
        target = "unknown-service"
    # 优化 4: 当 target 是类名格式（驼峰、小写开头）而非服务名时，尝试从 url 获取外部地址
    if target and target[0].islower() and not target.startswith("ucap-") and "-" not in target:
        url = extract_named_value(ann_args, "url") or ""
        if url:
            target = f"external:{url}"
    base_path = (
        _named_constant_or_value(ann_args, "path", resolved_constants)
        or extract_named_value(ann_args, "url")
        or ""
    )
    methods: list[dict[str, Any]] = []
    pattern = re.compile(
        r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?"
        r"\s*(?:\n|\r|\s)*(?:@[\w()\"=,{}./\s]+\s*)*[^;{=]+?\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    for mapping, args, method_name in pattern.findall(body):
        http = extract_method_from_args(args) if mapping == "RequestMapping" else mapping.replace("Mapping", "").upper()
        methods.append({"method_name": method_name, "http_method": http or "REQUEST", "path": join_path(base_path, _mapping_path(args, resolved_constants))})
    return [FeignClient(project, rel, interface, target, base_path, methods)]


def parse_mq_endpoints(project: str, rel: str, text: str, symbol: JavaSymbol) -> list[MqEndpoint]:
    endpoints: list[MqEndpoint] = []
    class_name = (symbol.classes or [Path(rel).stem])[0]
    for args, method_name in _listener_annotations(text, "KafkaListener"):
        raw_topic = extract_named_value(args, "topics") or extract_named_value(args, "topic") or extract_first_string(args) or ""
        topic, placeholder = _topic_value(raw_topic)
        if not topic and not placeholder:
            topic = "unknown-topic"
        group = extract_named_value(args, "groupId") or extract_named_value(args, "group")
        endpoints.append(MqEndpoint(project, rel, "kafka", topic, group, class_name, method_name, topic_placeholder=placeholder))
    for args, method_name in _listener_annotations(text, "RocketMQMessageListener"):
        raw_topic = extract_named_value(args, "topic") or ""
        topic, placeholder = _topic_value(raw_topic)
        if not topic and not placeholder:
            topic = "unknown-topic"
        group = extract_named_value(args, "consumerGroup") or extract_named_value(args, "selectorExpression")
        endpoints.append(MqEndpoint(project, rel, "rocketmq", topic, group, class_name, method_name, topic_placeholder=placeholder))
    if _is_function_consumer(text):
        binding_name = _camel_to_binding_name(class_name)
        endpoints.append(MqEndpoint(
            project=project, file=rel, kind="kafka-stream",
            topic="", group="", class_name=class_name, method_name="apply",
            topic_placeholder=f"spring.cloud.stream.bindings.{binding_name}-in-0.destination",
        ))
    return endpoints


def parse_yaml_config(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
        values = flatten_dict(data)
        stream_bindings = _extract_stream_bindings(data)
        custom_kafka = _extract_custom_kafka_consumers(data)
        return {"values": values, "stream_bindings": stream_bindings, "custom_kafka_consumers": custom_kafka}
    except Exception:
        return {"values": {}, "stream_bindings": {}, "custom_kafka_consumers": {}}


def _extract_stream_bindings(data: dict[str, Any]) -> dict[str, str]:
    """Extract spring.cloud.stream.bindings.<name>.destination → topic mapping."""
    result: dict[str, str] = {}
    spring = data.get("spring", {})
    cloud = spring.get("cloud", {}) if isinstance(spring, dict) else {}
    stream = cloud.get("stream", {}) if isinstance(cloud, dict) else {}
    bindings = stream.get("bindings", {}) if isinstance(stream, dict) else {}
    if isinstance(bindings, dict):
        for binding_name, config in bindings.items():
            if isinstance(config, dict) and "destination" in config:
                result[binding_name] = str(config["destination"])
    return result


def _extract_custom_kafka_consumers(data: dict[str, Any]) -> dict[str, str]:
    """Extract ucap.kafka.consumers.<name>.topic → topic mapping."""
    result: dict[str, str] = {}
    ucap = data.get("ucap", {})
    kafka = ucap.get("kafka", {}) if isinstance(ucap, dict) else {}
    consumers = kafka.get("consumers", {}) if isinstance(kafka, dict) else {}
    if isinstance(consumers, dict):
        for consumer_name, config in consumers.items():
            if isinstance(config, dict) and "topic" in config:
                result[consumer_name] = str(config["topic"])
    return result


def build_topology(config: WorkspaceConfig, feigns: list[dict], apis: list[dict], mq: list[dict], config_index: list[dict]) -> dict[str, Any]:
    services = [
        {
            "name": s.name,
            "service_name": s.service_name or s.name,
            "path": s.path,
            "resolved_path": str(config.resolve_service_path(s)),
            "logical_prefix": config.service_logical_prefix(s),
            "type": s.type,
            "tags": s.tags,
        }
        for s in config.services
    ]
    service_names = {s["service_name"]: s["name"] for s in services}
    feign_edges = [{"from_project": f["project"], "to_service": f["target_service"], "to_project": service_names.get(f["target_service"]), "client": f["interface"], "file": f["file"]} for f in feigns]
    mq_topics: dict[str, dict[str, Any]] = {}
    for m in mq:
        kind = m.get("kind", "")
        is_producer = kind in ("kafka-producer", "rocketmq-producer")
        key = m["topic"] or m.get("topic_placeholder", "unknown")
        if not key:
            key = "unknown-topic"
        item = mq_topics.setdefault(key, {"topic": key, "consumers": [], "producers": []})
        entry = {"project": m["project"], "file": m["file"], "class": m.get("class_name"), "kind": kind}
        if is_producer:
            item["producers"].append(entry)
        else:
            item["consumers"].append(entry)
    return {"services": services, "feign_edges": feign_edges, "api_count": len(apis), "mq_topics": list(mq_topics.values()), "configs": config_index}


def extract_annotation_args(text: str, annotation: str) -> str | None:
    m = re.search(rf"@{annotation}\s*\((.*?)\)", text, flags=re.S)
    return m.group(1) if m else None


def _annotated_type_name(text: str, annotation: str, type_keywords: tuple[str, ...]) -> str:
    context = _annotated_type_context(text, annotation, type_keywords)
    return context[0] if context else ""


def _annotated_type_context(
    text: str,
    annotation: str,
    type_keywords: tuple[str, ...],
) -> tuple[str, str, str] | None:
    pattern = re.compile(
        rf"@{re.escape(annotation)}\s*(?:\([^)]*\))?"
        rf"(?:\s*@\w+(?:\([^)]*\))?)*"
        rf"\s*(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+)*"
        rf"(?:{'|'.join(re.escape(keyword) for keyword in type_keywords)})\s+(\w+)[^{{]*{{",
        re.S,
    )
    match = pattern.search(text)
    if not match:
        return None
    open_brace = text.find("{", match.start(), match.end())
    if open_brace < 0:
        return None
    close_brace = _matching_brace(text, open_brace)
    return match.group(1), text[match.start():open_brace], text[open_brace + 1:close_brace]


def _matching_brace(text: str, open_brace: int) -> int:
    depth = 0
    for index in range(open_brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return len(text)


def _named_constant_or_value(args: str, name: str, constant_map: dict[str, str]) -> str:
    value = extract_named_value(args, name)
    if value is not None:
        return value
    ref = extract_named_ref(args, name)
    if not ref:
        return ""
    return constant_map.get(ref) or constant_map.get(ref.split(".")[-1], "")


def _mapping_path(args: str, constant_map: dict[str, str]) -> str:
    value = extract_named_value(args, "value") or extract_named_value(args, "path") or extract_first_string(args)
    if value is not None:
        return value
    ref = extract_named_ref(args, "value") or extract_named_ref(args, "path")
    if not ref:
        match = re.search(r"^\s*([\w.]+)\s*$", args or "")
        ref = match.group(1) if match else ""
    return constant_map.get(ref) or constant_map.get(ref.split(".")[-1], "") if ref else ""


def extract_annotation_value(text: str, annotation: str) -> str | None:
    args = extract_annotation_args(text, annotation)
    if args is None:
        return None
    return extract_named_value(args, "value") or extract_first_string(args)


def extract_first_string(args: str) -> str | None:
    m = re.search(r'"([^"]*)"', args or "")
    return m.group(1) if m else None


def extract_named_value(args: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*=\s*(?:\{{\s*)?\"([^\"]+)\"", args or "")
    return m.group(1) if m else None


def extract_named_ref(args: str, name: str) -> str | None:
    """Extract a non-string named value (constant reference like ClassName.CONSTANT_NAME)."""
    m = re.search(rf'\b{name}\s*=\s*([\w.]+)', args or "")
    # Filter out string literals that were already handled by extract_named_value
    if m and m.group(1).startswith('"'):
        return None
    return m.group(1) if m else None


def _build_constant_map(symbol_index: list[dict[str, Any]]) -> dict[str, str]:
    """Build a map from CONSTANT_NAME and ClassName.CONSTANT_NAME to string values,
    using dedicated constants with field_types as a legacy fallback."""
    constant_map: dict[str, str] = {}
    for sym in symbol_index:
        values = sym.get("constants") or sym.get("field_types", {})
        for fname, fval in values.items():
            if fval and isinstance(fval, str) and not fval.startswith(("com.", "java.", "org.", "List", "Map", "Set", "Integer", "Long", "Boolean")):
                constant_map[fname] = fval
                for cls in sym.get("classes", []) + sym.get("interfaces", []):
                    constant_map[f"{cls}.{fname}"] = fval
    return constant_map


def _extract_topic_placeholder(raw: str | None) -> str:
    m = re.search(r"\$\{([^}:]+)(?::[^}]*)?\}", raw or "")
    return m.group(1) if m else ""


def _topic_value(raw: str | None) -> tuple[str, str]:
    if not raw:
        return "", ""
    placeholder = _extract_topic_placeholder(raw)
    if placeholder:
        return "", placeholder
    return clean_topic(raw), ""


def _camel_to_binding_name(value: str) -> str:
    if not value:
        return ""
    return value[:1].lower() + value[1:]


def extract_method_from_args(args: str) -> str | None:
    m = re.search(r"RequestMethod\.(GET|POST|PUT|DELETE|PATCH)", args or "")
    return m.group(1) if m else None


def join_path(a: str, b: str) -> str:
    left = (a or "").strip()
    right = (b or "").strip()
    value = "/" + "/".join(x.strip("/") for x in [left, right] if x.strip("/"))
    return value if value != "/" else ""


def clean_topic(topic: str) -> str:
    return topic.strip().strip("{}").strip().strip('"')


def _listener_annotations(text: str, annotation: str) -> list[tuple[str, str | None]]:
    pattern = re.compile(
        rf"@{annotation}\s*\(([^)]*)\)\s*(?:\n|\r|\s)*(?:@[\w()\"=,{{}}./\s]+\s*)*"
        r"(?:public|private|protected)\s+(?:static\s+)?[\w<>, ?\.\[\]]+\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    return [(args, method_name) for args, method_name in pattern.findall(text)]


def _is_function_consumer(text: str) -> bool:
    """Detect Spring Cloud Stream function-style consumers: implements Function<ConsumerRecord<...>> or similar patterns."""
    if re.search(r'\b(?:implements|extends)\s+[\w\s,<>.]*Function\s*<', text):
        if 'ConsumerRecord' in text:
            return True
        # Also detect spring.messaging Message<?> pattern
        if 'Message<' in text or 'org.springframework.messaging' in text:
            return True
    return False


def parse_mq_producers(project: str, rel: str, text: str) -> list[MqEndpoint]:
    producers: list[MqEndpoint] = []
    # KafkaTemplate.send(topic, ...) - literal topic
    for m in re.finditer(r'kafkaTemplate\s*\.\s*(?:send|sendDefault)\s*\(\s*"([^"]+)"', text):
        producers.append(MqEndpoint(project=project, file=rel, kind="kafka-producer", topic=m.group(1)))
    # RocketMQTemplate.syncSend / asyncSend / send(topic, ...) - literal topic
    for m in re.finditer(r'rocketMQTemplate\s*\.\s*(?:syncSend|asyncSend|send)\s*\(\s*"([^"]+)"', text):
        producers.append(MqEndpoint(project=project, file=rel, kind="rocketmq-producer", topic=m.group(1)))
    return producers


def flatten_dict(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten_dict(v, key))
        else:
            out[key] = str(v)
    return out


def build_graph_store(config: WorkspaceConfig, store: WorkspaceStore, *, project_filter: set[str] | None = None, path_filters: Sequence[str] | None = None) -> dict[str, Any]:
    with GraphStore(store.graph_db_path) as graph:
        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        partial = bool(project_filter or path_filters)
        pf = project_filter or set()
        pfs = list(path_filters or [])

        ws_id = node_id("Workspace", config.workspace)
        nodes.append(GraphNode(ws_id, "Workspace", config.workspace))

        file_index = store.read_json_prefer_backend("file-index.json", [])
        symbols = store.read_json_prefer_backend("java-symbol-index.json", [])
        apis_full = store.read_json_prefer_backend("api-index.json", [])
        feigns = store.read_json_prefer_backend("feign-index.json", [])
        mq = store.read_json_prefer_backend("mq-index.json", [])
        configs = store.read_json_prefer_backend("config-index.json", [])
        topology = store.read_json_prefer_backend("service-topology.json", {})
        symbol_by_project_file = {
            (sym.get("project", ""), sym.get("file", "")): sym
            for sym in symbols
        }
        if partial:
            file_index = [r for r in file_index if _row_matches_scope(r, pf, pfs)]
            symbols = [r for r in symbols if _row_matches_scope(r, pf, pfs, path_key="file")]
            apis = [r for r in apis_full if _row_matches_scope(r, pf, pfs, path_key="file")]
            feigns = [r for r in feigns if _row_matches_scope(r, pf, pfs, path_key="file")]
            mq = [r for r in mq if _row_matches_scope(r, pf, pfs, path_key="file")]
            configs = [r for r in configs if _row_matches_scope(r, pf, pfs)]
        else:
            apis = apis_full

        # Index APIs by (http_method, normalized_path) so the Feign->Endpoint
        # association becomes O(|feign_methods|) instead of |feign_methods| *
        # |apis|.  Partial reindex still wires Feign methods against the full
        # API set so cross-project links survive a scoped rebuild.
        feign_match_pool = apis_full if partial else apis
        api_lookup = _build_api_lookup(feign_match_pool)

        class_locations: dict[str, list[dict[str, Any]]] = {}
        method_locations: dict[str, list[str]] = {}
        declared_method_ids: set[str] = set()
        field_locations: dict[str, list[str]] = {}
        field_locations_by_class: dict[tuple[str, str], list[str]] = {}
        field_type_by_file: dict[str, dict[str, str]] = {}
        method_variable_types_by_file: dict[str, dict[str, dict[str, str]]] = {}

        for svc in config.services:
            if pf and svc.name not in pf:
                continue
            sid = node_id("Service", svc.name)
            nodes.append(GraphNode(sid, "Service", svc.name, svc.name, metadata={"service_name": svc.service_name or svc.name, "path": svc.path, "type": svc.type, "tags": svc.tags}))
            edges.append(GraphEdge(edge_id("CONTAINS", ws_id, sid), ws_id, sid, "CONTAINS", 1.0, {"evidence": "workspace.yaml service"}))

        for item in file_index:
            fid = node_id("File", item["path"])
            sid = node_id("Service", item["project"])
            nodes.append(GraphNode(fid, "File", Path(item["path"]).name, item["project"], item["path"], metadata=item))
            edges.append(GraphEdge(edge_id("CONTAINS", sid, fid), sid, fid, "CONTAINS", 1.0, {"evidence": "file path under service root"}))

        for cfg in configs:
            fid = node_id("File", cfg["path"])
            for key, value in cfg.get("values", {}).items():
                kid = node_id("ConfigKey", cfg["project"], key)
                nodes.append(GraphNode(kid, "ConfigKey", key, cfg["project"], cfg["path"], metadata={"value": value}))
                edges.append(GraphEdge(edge_id("DECLARES_CONFIG", fid, kid), fid, kid, "DECLARES_CONFIG", 1.0, {"evidence": "YAML config key"}))

        for sym in symbols:
            fid = node_id("File", sym["file"])
            field_type_by_file[sym["file"]] = sym.get("field_types", {})
            method_variable_types_by_file[sym["file"]] = sym.get("method_variable_types", {})
            class_lines = sym.get("class_lines", {})
            interface_lines = sym.get("interface_lines", {})
            method_lines = sym.get("method_lines", {})
            field_lines = sym.get("field_lines", {})
            for cls in sym.get("classes", []) + sym.get("interfaces", []):
                cid = node_id("Class", sym["project"], cls)
                class_locations.setdefault(cls, []).append({"id": cid, "project": sym["project"], "file": sym["file"]})
                class_line = int(class_lines.get(cls) or interface_lines.get(cls) or 0)
                nodes.append(
                    GraphNode(
                        cid,
                        "Class",
                        cls,
                        sym["project"],
                        sym["file"],
                        class_line,
                        metadata={
                            "package": sym.get("package"),
                            "annotations": sym.get("annotations", []),
                            "parser": sym.get("parser") or "regex",
                        },
                    )
                )
                edges.append(GraphEdge(edge_id("DECLARES", fid, cid), fid, cid, "DECLARES", 1.0, {"evidence": "class/interface declaration"}))
                for m in sym.get("methods", []):
                    mid = node_id("Method", sym["project"], cls, m)
                    declared_method_ids.add(mid)
                    method_locations.setdefault(m, []).append(mid)
                    method_line = int(method_lines.get(m) or 0)
                    nodes.append(GraphNode(mid, "Method", f"{cls}.{m}", sym["project"], sym["file"], method_line, metadata={"method": m}))
                    edges.append(GraphEdge(edge_id("DECLARES", cid, mid), cid, mid, "DECLARES", 1.0, {"evidence": "method declaration"}))
                for fld in sym.get("fields", []):
                    field_id = node_id("Field", sym["project"], cls, fld)
                    field_locations.setdefault(fld, []).append(field_id)
                    field_locations_by_class.setdefault((cls, fld), []).append(field_id)
                    field_line = int(field_lines.get(fld) or 0)
                    nodes.append(GraphNode(field_id, "Field", f"{cls}.{fld}", sym["project"], sym["file"], field_line, metadata={"type": sym.get("field_types", {}).get(fld)}))
                    edges.append(GraphEdge(edge_id("DECLARES", cid, field_id), cid, field_id, "DECLARES", 1.0, {"evidence": "field declaration"}))

        # Import edges are file-level probable dependencies.
        for sym in symbols:
            for imp in sym.get("imports", []):
                imported_name = imp.split(".")[-1]
                for target in class_locations.get(imported_name, []):
                    edges.append(GraphEdge(edge_id("IMPORTS", node_id("File", sym["file"]), node_id("File", target["file"])), node_id("File", sym["file"]), node_id("File", target["file"]), "IMPORTS", 0.55, {"evidence": f"import {imp}", "import": imp}))

        for api in apis:
            eid = node_id("Endpoint", api["project"], api["http_method"], api["path"])
            cid = node_id("Class", api["project"], api["controller"])
            mid = node_id("Method", api["project"], api["controller"], api.get("method_name") or "unknown")
            endpoint_line = _method_line(symbol_by_project_file, api["project"], api["file"], api.get("method_name") or "")
            nodes.append(GraphNode(eid, "Endpoint", f"{api['http_method']} {api['path']}", api["project"], api["file"], endpoint_line, metadata=api))
            edges.append(GraphEdge(edge_id("EXPOSES_ENDPOINT", cid, eid), cid, eid, "EXPOSES_ENDPOINT", 1.0, {"evidence": "Spring MVC mapping annotation"}))
            edges.append(GraphEdge(edge_id("HANDLES_ENDPOINT", mid, eid), mid, eid, "HANDLES_ENDPOINT", 0.9, {"evidence": "mapping method"}))

        for f in feigns:
            fc_id = node_id("FeignClient", f["project"], f["interface"])
            cid = node_id("Class", f["project"], f["interface"])
            feign_line = _class_or_interface_line(symbol_by_project_file, f["project"], f["file"], f["interface"])
            nodes.append(GraphNode(fc_id, "FeignClient", f["interface"], f["project"], f["file"], feign_line, metadata=f))
            edges.append(GraphEdge(edge_id("DECLARES", cid, fc_id), cid, fc_id, "DECLARES", 1.0, {"evidence": "@FeignClient"}))
            target_project = topology_service_project(topology, f.get("target_service")) or f.get("target_service", "unknown")
            target_service_id = node_id("Service", target_project)
            edges.append(GraphEdge(edge_id("CALLS_SERVICE", fc_id, target_service_id), fc_id, target_service_id, "CALLS_SERVICE", 0.9, {"evidence": "@FeignClient target service", "target_service": f.get("target_service")}))
            for method in f.get("methods", []):
                fm_id = node_id("FeignMethod", f["project"], f["interface"], method.get("method_name", "unknown"))
                feign_method_line = _method_line(symbol_by_project_file, f["project"], f["file"], method.get("method_name", "unknown"))
                nodes.append(GraphNode(fm_id, "FeignMethod", f"{f['interface']}.{method.get('method_name')}", f["project"], f["file"], feign_method_line, metadata=method))
                edges.append(GraphEdge(edge_id("DECLARES", fc_id, fm_id), fc_id, fm_id, "DECLARES", 1.0, {"evidence": "Feign interface method"}))
                for api in _candidate_apis_for_feign_method(api_lookup, f, method):
                    if _endpoint_matches(f, method, api):
                        ep_id = node_id("Endpoint", api["project"], api["http_method"], api["path"])
                        edges.append(GraphEdge(edge_id("IMPLEMENTS_FEIGN", fm_id, ep_id), fm_id, ep_id, "IMPLEMENTS_FEIGN", 0.78, {"evidence": "HTTP method/path matched Feign method to Controller endpoint"}))

        for m in mq:
            kind = m.get("kind", "")
            topic = m["topic"] or m.get("topic_placeholder", "unknown")
            if not topic:
                topic = "unknown-topic"
            topic_id = node_id("MQTopic", topic)
            is_producer = kind in ("kafka-producer", "rocketmq-producer")
            node_kind = "MQProducer" if is_producer else "MQConsumer"
            node_name = m.get("class_name") or Path(m["file"]).stem
            node_id_val = node_id(node_kind, m["project"], node_name, topic)
            edge_type = "PRODUCES_TOPIC" if is_producer else "CONSUMES_TOPIC"
            evidence = f"{kind} {'producer' if is_producer else 'listener'}"
            nodes.append(GraphNode(topic_id, "MQTopic", topic, metadata={"kind": kind}))
            nodes.append(GraphNode(node_id_val, node_kind, node_name, m["project"], m["file"], metadata=m))
            edges.append(GraphEdge(edge_id(edge_type, node_id_val, topic_id), node_id_val, topic_id, edge_type, 1.0, {"evidence": evidence}))
            edges.append(GraphEdge(edge_id("CONTAINS", node_id("Service", m["project"]), node_id_val), node_id("Service", m["project"]), node_id_val, "CONTAINS"))

        # Relationship facts extracted from Java bodies/fields.
        for sym in symbols:
            owner_classes = sym.get("classes", []) + sym.get("interfaces", [])
            owner_class = owner_classes[0] if owner_classes else Path(sym["file"]).stem
            owner_class_id = node_id("Class", sym["project"], owner_class)
            file_field_types = field_type_by_file.get(sym["file"], {})
            file_method_variable_types = method_variable_types_by_file.get(sym["file"], {})

            for inj in sym.get("bean_injections", []):
                target_type = inj.get("type")
                target_candidates = class_locations.get(target_type, [])
                target_id = target_candidates[0]["id"] if target_candidates else node_id("Bean", sym["project"], target_type or inj.get("field_name", "unknown"))
                if not target_candidates:
                    nodes.append(
                        GraphNode(
                            target_id,
                            "Bean",
                            target_type or inj.get("field_name", "unknown"),
                            sym["project"],
                            sym["file"],
                            metadata=inj,
                        )
                    )
                edges.append(GraphEdge(edge_id("INJECTS_BEAN", owner_class_id, target_id), owner_class_id, target_id, "INJECTS_BEAN", 0.82, {"evidence": inj}))

            for call in sym.get("method_calls", []):
                target_method = call.get("method_name")
                receiver = call.get("receiver")
                owner_method = call.get("owner_method") or ""
                receiver_type = call.get("receiver_type") or file_method_variable_types.get(owner_method, {}).get(receiver) or file_field_types.get(receiver)
                source_id = _source_method_id(sym, owner_class, call) or owner_class_id
                target_ids = []
                if receiver_type and class_locations.get(receiver_type):
                    for loc in class_locations[receiver_type]:
                        target_ids.append(node_id("Method", loc["project"], receiver_type, target_method))
                target_ids.extend(method_locations.get(target_method, [])[:3])
                for tid in sorted(set(target_ids)):
                    if tid not in declared_method_ids:
                        nodes.append(GraphNode(tid, "Method", tid.split(":")[-1], metadata={"inferred": True}))
                    edges.append(GraphEdge(edge_id("CALLS_METHOD", source_id, tid), source_id, tid, "CALLS_METHOD", 0.58 if not receiver_type else 0.68, {"evidence": call, "receiver_type": receiver_type}))

            for usage in sym.get("dto_field_usages", []):
                source_id = _source_method_id(sym, owner_class, usage) or owner_class_id
                receiver_type = usage.get("receiver_type")
                matching_fields = []
                if receiver_type:
                    matching_fields.extend(
                        field_locations_by_class.get((receiver_type, usage.get("field")), [])
                    )
                if not matching_fields:
                    matching_fields = field_locations.get(usage.get("field"), [])[:5]
                for fid in matching_fields[:5]:
                    edges.append(
                        GraphEdge(
                            edge_id("READS_FIELD", source_id, fid),
                            source_id,
                            fid,
                            "READS_FIELD",
                            0.74 if receiver_type else 0.62,
                            {"evidence": usage, "receiver_type": receiver_type},
                        )
                    )

            for usage in sym.get("config_usages", []):
                key = usage.get("key")
                kid = node_id("ConfigKey", sym["project"], key)
                nodes.append(GraphNode(kid, "ConfigKey", key, sym["project"], sym["file"], metadata=usage))
                edges.append(GraphEdge(edge_id("READS_CONFIG", owner_class_id, kid), owner_class_id, kid, "READS_CONFIG", 0.84, {"evidence": usage}))

            for resource in sym.get("data_resources", []):
                rid = node_id(resource.get("kind", "DataResource"), resource.get("name", "unknown"))
                nodes.append(GraphNode(rid, resource.get("kind", "DataResource"), resource.get("name", "unknown"), sym["project"], sym["file"], metadata=resource))
                edges.append(GraphEdge(edge_id("USES_DATA_RESOURCE", owner_class_id, rid), owner_class_id, rid, "USES_DATA_RESOURCE", 0.72, {"evidence": resource}))

        # ── Multi-language structural pass ────────────────────────────────
        #
        # Non-Java files registered in language_registry get walked by
        # the cross-language structural parser and contribute generic
        # graph nodes/edges (Module / Class / Function + DEFINES /
        # IMPORTS / CALLS). This is the entry point added in P0-2.
        #
        # The path filter mirrors the Java collection above so partial
        # reindex still respects --project / --path scopes.
        from .indexing import multilang_indexer

        def _multilang_filter(svc, path):
            if path_filters and not _path_matches_filters(config, svc, path, path_filters):
                return False
            return True

        multilang_tasks = multilang_indexer.collect_multilang_files(
            (s for s in config.services if not project_filter or s.name in project_filter),
            config,
            walk_project,
            _multilang_filter,
        )
        for ml_project, ml_rel, ml_path in multilang_tasks:
            ml_result = multilang_indexer.parse_structural(ml_path)
            if ml_result is None or ml_result.is_empty():
                continue
            ml_nodes, ml_edges = multilang_indexer.emit_graph_elements(
                ml_project, ml_rel, ml_result
            )
            nodes.extend(ml_nodes)
            edges.extend(ml_edges)

        if partial:
            graph_counts = graph.partial_rebuild(nodes, edges, pf, pfs)
        else:
            graph.rebuild(nodes, edges)
            graph.rebuild_search_index()
            graph_counts = graph.counts()
        store.write_json("graph-summary.json", graph_counts)
        return graph_counts


_STANDARD_HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}

def _normalize_path_params(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{param}", path)


_API_LOOKUP_WILDCARD = ""


def _build_api_lookup(apis: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Index APIs by ``(http_method, normalized_path)``.

    Two keys are stored per API: the http method, and the "wildcard" key
    ``""`` for methods whose http method is non-standard (rare).  The
    wildcard bucket is consulted as a fallback so legacy non-standard methods
    keep matching exactly like the legacy linear scan.
    """
    lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for api in apis:
        method = (api.get("http_method") or "").upper()
        norm = _normalize_path_params((api.get("path") or "").strip("/"))
        lookup.setdefault((method, norm), []).append(api)
        lookup.setdefault((_API_LOOKUP_WILDCARD, norm), []).append(api)
    return lookup


def _candidate_apis_for_feign_method(
    api_lookup: dict[tuple[str, str], list[dict[str, Any]]],
    feign: dict[str, Any],
    method: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return APIs that could match a Feign method without scanning the full list.

    We consult two normalized keys: the path declared on the Feign method and
    the composed ``base_path + method_path``.  The standard http method is
    used as the primary key; the wildcard bucket is consulted if the method's
    http method is non-standard so legacy behaviour is preserved.
    """
    feign_http = (method.get("http_method") or "").upper()
    method_norm = _normalize_path_params((method.get("path") or "").strip("/"))
    base_path = feign.get("base_path") or ""
    composed_norm = (
        _normalize_path_params(join_path(base_path, method.get("path") or "").strip("/"))
        if base_path
        else ""
    )
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    def _extend(key: tuple[str, str]) -> None:
        for api in api_lookup.get(key, []):
            ident = id(api)
            if ident in seen:
                continue
            seen.add(ident)
            out.append(api)

    keys: list[tuple[str, str]] = [
        (feign_http, method_norm),
    ]
    if composed_norm and composed_norm != method_norm:
        keys.append((feign_http, composed_norm))
    if feign_http not in _STANDARD_HTTP_METHODS:
        keys.append((_API_LOOKUP_WILDCARD, method_norm))
        if composed_norm and composed_norm != method_norm:
            keys.append((_API_LOOKUP_WILDCARD, composed_norm))
    for key in keys:
        _extend(key)
    return out


def _endpoint_matches(feign: dict[str, Any], method: dict[str, Any], api: dict[str, Any]) -> bool:
    api_path = (api.get("path") or "").strip("/")
    feign_http = (method.get("http_method") or "").upper()
    api_http = (api.get("http_method") or "").upper()

    if feign_http in _STANDARD_HTTP_METHODS and api_http in _STANDARD_HTTP_METHODS and feign_http != api_http:
        return False

    feign_norm = _normalize_path_params((method.get("path") or "").strip("/"))
    api_norm = _normalize_path_params(api_path)

    # Direct match: method path already includes base_path prefix
    if feign_norm == api_norm:
        return True

    # Compose full path: base_path + method_path for cases where method.path
    # does NOT include the base (e.g. base=/article, method path=/move)
    base_norm = _normalize_path_params((feign.get("base_path") or "").strip("/"))
    if base_norm:
        composed_norm = _normalize_path_params(join_path(feign.get("base_path") or "", method.get("path") or "").strip("/"))
        if composed_norm == api_norm:
            return True

    return False


def _source_method_id(sym: dict[str, Any], owner_class: str, fact: dict[str, Any]) -> str | None:
    owner_method = fact.get("owner_method")
    if not owner_method:
        return None
    return node_id("Method", sym["project"], owner_class, owner_method)


def topology_service_project(topology: dict[str, Any], service_name: str | None) -> str | None:
    if not service_name:
        return None
    for svc in topology.get("services", []):
        if svc.get("service_name") == service_name or svc.get("name") == service_name:
            return svc.get("name")
    # Fuzzy: strip -app suffix from either side (Spring app name vs workspace project name)
    service_no_app = service_name[:-4] if service_name.endswith("-app") else service_name
    for svc in topology.get("services", []):
        svc_name = svc.get("service_name") or ""
        svc_proj = svc.get("name") or ""
        if svc_name == service_no_app or svc_proj == service_no_app:
            return svc.get("name")
        svc_name_no_app = svc_name[:-4] if svc_name.endswith("-app") else svc_name
        svc_proj_no_app = svc_proj[:-4] if svc_proj.endswith("-app") else svc_proj
        if service_no_app == svc_name_no_app or service_no_app == svc_proj_no_app:
            return svc.get("name")
    return None
