from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

from .graph import GraphEdge, GraphNode, GraphStore, edge_id, node_id
from .indexing import RegexJavaParser
from .models import ApiEndpoint, FeignClient, JavaSymbol, MqEndpoint, WorkspaceConfig, to_dict
from .semantic import build_workspace_semantic_index
from .store import WorkspaceStore

JAVA_EXTENSIONS = {".java"}
CONFIG_NAMES = {"application.yml", "application.yaml", "bootstrap.yml", "bootstrap.yaml"}
IGNORED_DIRS = {
    ".git", ".idea", ".vscode", "target", "build", "dist", "node_modules",
    ".memory-center", ".project-ai", ".symbio", "__pycache__",
}


def reindex_workspace(config: WorkspaceConfig, store: WorkspaceStore) -> Dict[str, int]:
    """Rebuild deterministic indexes and the local evidence graph."""
    file_index: List[Dict[str, Any]] = []
    symbol_index: List[Dict[str, Any]] = []
    api_index: List[Dict[str, Any]] = []
    feign_index: List[Dict[str, Any]] = []
    mq_index: List[Dict[str, Any]] = []
    config_index: List[Dict[str, Any]] = []

    for svc in config.services:
        service_root = config.root_path / svc.path
        if not service_root.exists():
            continue
        for path in walk_project(service_root):
            rel = path.relative_to(config.root_path).as_posix()
            file_index.append({"project": svc.name, "service_name": svc.service_name or svc.name, "path": rel, "suffix": path.suffix})
            if path.suffix in JAVA_EXTENSIONS:
                text = safe_read(path)
                symbol = parse_java_symbols(svc.name, rel, text)
                symbol_index.append(to_dict(symbol))
                api_index.extend(to_dict(x) for x in parse_controllers(svc.name, rel, text, symbol))
                feign_index.extend(to_dict(x) for x in parse_feign_clients(svc.name, rel, text, symbol))
                mq_index.extend(to_dict(x) for x in parse_mq_endpoints(svc.name, rel, text, symbol))
            elif path.name in CONFIG_NAMES:
                config_index.append({"project": svc.name, "path": rel, "values": parse_yaml_config(path)})

    topology = build_topology(config, feign_index, api_index, mq_index, config_index)
    store.write_json("file-index.json", file_index)
    store.write_json("java-symbol-index.json", symbol_index)
    store.write_json("api-index.json", api_index)
    store.write_json("feign-index.json", feign_index)
    store.write_json("mq-index.json", mq_index)
    store.write_json("config-index.json", config_index)
    store.write_json("service-topology.json", topology)
    graph_counts = build_graph_store(config, store)
    semantic_counts = build_workspace_semantic_index(store.workspace_file)
    return {
        "files": len(file_index),
        "symbols": len(symbol_index),
        "apis": len(api_index),
        "feigns": len(feign_index),
        "mq": len(mq_index),
        "configs": len(config_index),
        "graph_nodes": graph_counts.get("nodes", 0),
        "graph_edges": graph_counts.get("edges", 0),
        "semantic_docs": semantic_counts.get("doc_count", 0),
    }


def walk_project(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def safe_read(path: Path, limit: int = 600_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def parse_java_symbols(project: str, rel: str, text: str) -> JavaSymbol:
    parsed = RegexJavaParser().parse(text, rel)
    return JavaSymbol(
        project=project,
        file=rel,
        package=parsed.package,
        classes=parsed.classes,
        interfaces=parsed.interfaces,
        methods=parsed.methods,
        fields=parsed.fields,
        annotations=parsed.annotations,
        imports=parsed.imports,
        field_types=parsed.field_types,
        bean_injections=parsed.bean_injections,
        method_calls=parsed.method_calls,
        dto_field_usages=parsed.dto_field_usages,
        config_usages=parsed.config_usages,
        data_resources=parsed.data_resources,
    )


def parse_controllers(project: str, rel: str, text: str, symbol: JavaSymbol) -> List[ApiEndpoint]:
    if "RestController" not in symbol.annotations and "Controller" not in symbol.annotations:
        return []
    controller = (symbol.classes or [Path(rel).stem])[0]
    class_prefix = extract_annotation_value(text, "RequestMapping") or ""
    endpoints: List[ApiEndpoint] = []
    pattern = re.compile(
        r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?"
        r"\s*(?:\n|\r|\s)*(?:@[\w()\"=,{}./\s]+\s*)*[^;{=]+?\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    for mapping, args, method_name in pattern.findall(text):
        http = extract_method_from_args(args) if mapping == "RequestMapping" else mapping.replace("Mapping", "").upper()
        endpoints.append(ApiEndpoint(project, rel, controller, http or "REQUEST", join_path(class_prefix, extract_first_string(args) or ""), method_name))
    return endpoints


def parse_feign_clients(project: str, rel: str, text: str, symbol: JavaSymbol) -> List[FeignClient]:
    if "FeignClient" not in symbol.annotations:
        return []
    interface = (symbol.interfaces or symbol.classes or [Path(rel).stem])[0]
    ann_args = extract_annotation_args(text, "FeignClient") or ""
    target = extract_named_value(ann_args, "name") or extract_named_value(ann_args, "value") or extract_named_value(ann_args, "serviceId") or "unknown-service"
    base_path = extract_named_value(ann_args, "path") or extract_named_value(ann_args, "url") or ""
    methods: List[Dict[str, Any]] = []
    pattern = re.compile(
        r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?"
        r"\s*(?:\n|\r|\s)*(?:@[\w()\"=,{}./\s]+\s*)*[^;{=]+?\s+(\w+)\s*\(",
        re.MULTILINE,
    )
    for mapping, args, method_name in pattern.findall(text):
        http = extract_method_from_args(args) if mapping == "RequestMapping" else mapping.replace("Mapping", "").upper()
        methods.append({"method_name": method_name, "http_method": http or "REQUEST", "path": join_path(base_path, extract_first_string(args) or "")})
    return [FeignClient(project, rel, interface, target, base_path, methods)]


def parse_mq_endpoints(project: str, rel: str, text: str, symbol: JavaSymbol) -> List[MqEndpoint]:
    endpoints: List[MqEndpoint] = []
    class_name = (symbol.classes or [Path(rel).stem])[0]
    method_name = (symbol.methods or [None])[0]
    for args in re.findall(r"@KafkaListener\s*\(([^)]*)\)", text, flags=re.S):
        topic = extract_named_value(args, "topics") or extract_named_value(args, "topic") or extract_first_string(args) or "unknown-topic"
        group = extract_named_value(args, "groupId") or extract_named_value(args, "group")
        endpoints.append(MqEndpoint(project, rel, "kafka", clean_topic(topic), group, class_name, method_name))
    for args in re.findall(r"@RocketMQMessageListener\s*\(([^)]*)\)", text, flags=re.S):
        topic = extract_named_value(args, "topic") or "unknown-topic"
        group = extract_named_value(args, "consumerGroup") or extract_named_value(args, "selectorExpression")
        endpoints.append(MqEndpoint(project, rel, "rocketmq", clean_topic(topic), group, class_name, method_name))
    return endpoints


def parse_yaml_config(path: Path) -> Dict[str, str]:
    try:
        return flatten_dict(yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {})
    except Exception:
        return {}


def build_topology(config: WorkspaceConfig, feigns: List[Dict], apis: List[Dict], mq: List[Dict], config_index: List[Dict]) -> Dict[str, Any]:
    services = [{"name": s.name, "service_name": s.service_name or s.name, "path": s.path, "type": s.type, "tags": s.tags} for s in config.services]
    service_names = {s["service_name"]: s["name"] for s in services}
    feign_edges = [{"from_project": f["project"], "to_service": f["target_service"], "to_project": service_names.get(f["target_service"]), "client": f["interface"], "file": f["file"]} for f in feigns]
    mq_topics: Dict[str, Dict[str, Any]] = {}
    for m in mq:
        item = mq_topics.setdefault(m["topic"], {"topic": m["topic"], "consumers": [], "producers": []})
        item["consumers"].append({"project": m["project"], "file": m["file"], "class": m.get("class_name"), "kind": m["kind"]})
    return {"services": services, "feign_edges": feign_edges, "api_count": len(apis), "mq_topics": list(mq_topics.values()), "configs": config_index}


def extract_annotation_args(text: str, annotation: str) -> str | None:
    m = re.search(rf"@{annotation}\s*\((.*?)\)", text, flags=re.S)
    return m.group(1) if m else None


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


def flatten_dict(data: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten_dict(v, key))
        else:
            out[key] = str(v)
    return out


def build_graph_store(config: WorkspaceConfig, store: WorkspaceStore) -> Dict[str, int]:
    graph = GraphStore(store.graph_db_path)
    graph.clear()
    nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []

    ws_id = node_id("Workspace", config.workspace)
    nodes.append(GraphNode(ws_id, "Workspace", config.workspace))

    file_index = store.read_json("file-index.json", [])
    symbols = store.read_json("java-symbol-index.json", [])
    apis = store.read_json("api-index.json", [])
    feigns = store.read_json("feign-index.json", [])
    mq = store.read_json("mq-index.json", [])
    configs = store.read_json("config-index.json", [])
    topology = store.read_json("service-topology.json", {})

    class_locations: Dict[str, List[Dict[str, Any]]] = {}
    method_locations: Dict[str, List[str]] = {}
    declared_method_ids: set[str] = set()
    field_locations: Dict[str, List[str]] = {}
    field_type_by_file: Dict[str, Dict[str, str]] = {}

    for svc in config.services:
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
        for cls in sym.get("classes", []) + sym.get("interfaces", []):
            cid = node_id("Class", sym["project"], cls)
            class_locations.setdefault(cls, []).append({"id": cid, "project": sym["project"], "file": sym["file"]})
            nodes.append(GraphNode(cid, "Class", cls, sym["project"], sym["file"], metadata={"package": sym.get("package"), "annotations": sym.get("annotations", []), "parser": "regex"}))
            edges.append(GraphEdge(edge_id("DECLARES", fid, cid), fid, cid, "DECLARES", 1.0, {"evidence": "class/interface declaration"}))
            for m in sym.get("methods", []):
                mid = node_id("Method", sym["project"], cls, m)
                declared_method_ids.add(mid)
                method_locations.setdefault(m, []).append(mid)
                nodes.append(GraphNode(mid, "Method", f"{cls}.{m}", sym["project"], sym["file"], metadata={"method": m}))
                edges.append(GraphEdge(edge_id("DECLARES", cid, mid), cid, mid, "DECLARES", 1.0, {"evidence": "method declaration"}))
            for fld in sym.get("fields", []):
                field_id = node_id("Field", sym["project"], cls, fld)
                field_locations.setdefault(fld, []).append(field_id)
                nodes.append(GraphNode(field_id, "Field", f"{cls}.{fld}", sym["project"], sym["file"], metadata={"type": sym.get("field_types", {}).get(fld)}))
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
        nodes.append(GraphNode(eid, "Endpoint", f"{api['http_method']} {api['path']}", api["project"], api["file"], metadata=api))
        edges.append(GraphEdge(edge_id("EXPOSES_ENDPOINT", cid, eid), cid, eid, "EXPOSES_ENDPOINT", 1.0, {"evidence": "Spring MVC mapping annotation"}))
        edges.append(GraphEdge(edge_id("HANDLES_ENDPOINT", mid, eid), mid, eid, "HANDLES_ENDPOINT", 0.9, {"evidence": "mapping method"}))

    for f in feigns:
        fc_id = node_id("FeignClient", f["project"], f["interface"])
        cid = node_id("Class", f["project"], f["interface"])
        nodes.append(GraphNode(fc_id, "FeignClient", f["interface"], f["project"], f["file"], metadata=f))
        edges.append(GraphEdge(edge_id("DECLARES", cid, fc_id), cid, fc_id, "DECLARES", 1.0, {"evidence": "@FeignClient"}))
        target_project = topology_service_project(topology, f.get("target_service")) or f.get("target_service", "unknown")
        target_service_id = node_id("Service", target_project)
        edges.append(GraphEdge(edge_id("CALLS_SERVICE", fc_id, target_service_id), fc_id, target_service_id, "CALLS_SERVICE", 0.9, {"evidence": "@FeignClient target service", "target_service": f.get("target_service")}))
        for method in f.get("methods", []):
            fm_id = node_id("FeignMethod", f["project"], f["interface"], method.get("method_name", "unknown"))
            nodes.append(GraphNode(fm_id, "FeignMethod", f"{f['interface']}.{method.get('method_name')}", f["project"], f["file"], metadata=method))
            edges.append(GraphEdge(edge_id("DECLARES", fc_id, fm_id), fc_id, fm_id, "DECLARES", 1.0, {"evidence": "Feign interface method"}))
            for api in apis:
                if _endpoint_matches(f, method, api):
                    ep_id = node_id("Endpoint", api["project"], api["http_method"], api["path"])
                    edges.append(GraphEdge(edge_id("IMPLEMENTS_FEIGN", fm_id, ep_id), fm_id, ep_id, "IMPLEMENTS_FEIGN", 0.78, {"evidence": "HTTP method/path matched Feign method to Controller endpoint"}))

    for m in mq:
        topic_id = node_id("MQTopic", m["topic"])
        consumer_id = node_id("MQConsumer", m["project"], m.get("class_name") or Path(m["file"]).stem, m["topic"])
        nodes.append(GraphNode(topic_id, "MQTopic", m["topic"], metadata={"kind": m.get("kind")}))
        nodes.append(GraphNode(consumer_id, "MQConsumer", m.get("class_name") or Path(m["file"]).stem, m["project"], m["file"], metadata=m))
        edges.append(GraphEdge(edge_id("CONSUMES_TOPIC", consumer_id, topic_id), consumer_id, topic_id, "CONSUMES_TOPIC", 1.0, {"evidence": "Kafka/RocketMQ listener annotation"}))
        edges.append(GraphEdge(edge_id("CONTAINS", node_id("Service", m["project"]), consumer_id), node_id("Service", m["project"]), consumer_id, "CONTAINS"))

    # Relationship facts extracted from Java bodies/fields.
    for sym in symbols:
        owner_classes = sym.get("classes", []) + sym.get("interfaces", [])
        owner_class = owner_classes[0] if owner_classes else Path(sym["file"]).stem
        owner_class_id = node_id("Class", sym["project"], owner_class)
        file_field_types = field_type_by_file.get(sym["file"], {})

        for inj in sym.get("bean_injections", []):
            target_type = inj.get("type")
            target_candidates = class_locations.get(target_type, [])
            target_id = target_candidates[0]["id"] if target_candidates else node_id("Bean", sym["project"], target_type or inj.get("field_name", "unknown"))
            nodes.append(GraphNode(target_id, "Bean" if not target_candidates else "Class", target_type or inj.get("field_name", "unknown"), target_candidates[0]["project"] if target_candidates else sym["project"], target_candidates[0]["file"] if target_candidates else sym["file"], metadata=inj))
            edges.append(GraphEdge(edge_id("INJECTS_BEAN", owner_class_id, target_id), owner_class_id, target_id, "INJECTS_BEAN", 0.82, {"evidence": inj}))

        for call in sym.get("method_calls", []):
            target_method = call.get("method_name")
            receiver = call.get("receiver")
            receiver_type = file_field_types.get(receiver)
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
            for fid in field_locations.get(usage.get("field"), [])[:5]:
                edges.append(GraphEdge(edge_id("READS_FIELD", source_id, fid), source_id, fid, "READS_FIELD", 0.62, {"evidence": usage}))

        for usage in sym.get("config_usages", []):
            key = usage.get("key")
            kid = node_id("ConfigKey", sym["project"], key)
            nodes.append(GraphNode(kid, "ConfigKey", key, sym["project"], sym["file"], metadata=usage))
            edges.append(GraphEdge(edge_id("READS_CONFIG", owner_class_id, kid), owner_class_id, kid, "READS_CONFIG", 0.84, {"evidence": usage}))

        for resource in sym.get("data_resources", []):
            rid = node_id(resource.get("kind", "DataResource"), resource.get("name", "unknown"))
            nodes.append(GraphNode(rid, resource.get("kind", "DataResource"), resource.get("name", "unknown"), sym["project"], sym["file"], metadata=resource))
            edges.append(GraphEdge(edge_id("USES_DATA_RESOURCE", owner_class_id, rid), owner_class_id, rid, "USES_DATA_RESOURCE", 0.72, {"evidence": resource}))

    graph.bulk_write(nodes, edges)
    graph.rebuild_search_index()
    counts = graph.counts()
    store.write_json("graph-summary.json", counts)
    return counts


def _endpoint_matches(feign: Dict[str, Any], method: Dict[str, Any], api: Dict[str, Any]) -> bool:
    feign_path = method.get("path") or ""
    api_path = api.get("path") or ""
    if feign_path == api_path:
        return True
    base = feign.get("base_path") or ""
    return bool(base and feign_path.replace(base, "") == api_path)


def _source_method_id(sym: Dict[str, Any], owner_class: str, fact: Dict[str, Any]) -> str | None:
    owner_method = fact.get("owner_method")
    if not owner_method:
        return None
    return node_id("Method", sym["project"], owner_class, owner_method)


def topology_service_project(topology: Dict[str, Any], service_name: str | None) -> str | None:
    for svc in topology.get("services", []):
        if svc.get("service_name") == service_name or svc.get("name") == service_name:
            return svc.get("name")
    return None
