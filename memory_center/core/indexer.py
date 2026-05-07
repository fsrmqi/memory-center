from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import yaml

from .models import ApiEndpoint, FeignClient, JavaSymbol, MqEndpoint, WorkspaceConfig, to_dict
from .store import WorkspaceStore

JAVA_EXTENSIONS = {".java"}
CONFIG_NAMES = {"application.yml", "application.yaml", "bootstrap.yml", "bootstrap.yaml"}
IGNORED_DIRS = {".git", ".idea", ".vscode", "target", "build", "dist", "node_modules", ".memory-center", ".project-ai", ".symbio"}


def reindex_workspace(config: WorkspaceConfig, store: WorkspaceStore) -> Dict[str, int]:
    file_index: List[Dict] = []
    symbol_index: List[Dict] = []
    api_index: List[Dict] = []
    feign_index: List[Dict] = []
    mq_index: List[Dict] = []
    config_index: List[Dict] = []

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
    return {
        "files": len(file_index),
        "symbols": len(symbol_index),
        "apis": len(api_index),
        "feigns": len(feign_index),
        "mq": len(mq_index),
        "configs": len(config_index),
        "graph_nodes": graph_counts.get("nodes", 0),
        "graph_edges": graph_counts.get("edges", 0),
    }


def walk_project(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def safe_read(path: Path, limit: int = 400_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return text[:limit]
    except Exception:
        return ""


def parse_java_symbols(project: str, rel: str, text: str) -> JavaSymbol:
    package = first_group(r"package\s+([\w\.]+)\s*;", text)
    imports = re.findall(r"import\s+([\w\.\*]+)\s*;", text)
    classes = re.findall(r"\bclass\s+(\w+)", text)
    interfaces = re.findall(r"\binterface\s+(\w+)", text)
    methods = re.findall(r"(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\], ?]+\s+(\w+)\s*\(", text)
    fields = re.findall(r"(?:private|public|protected)\s+(?:static\s+)?(?:final\s+)?[\w<>\[\], ?]+\s+(\w+)\s*(?:=|;)", text)
    annotations = re.findall(r"@(\w+)(?:\(|\s|\n)", text)
    return JavaSymbol(project=project, file=rel, package=package, classes=classes, interfaces=interfaces, methods=methods, fields=fields, annotations=sorted(set(annotations)), imports=imports)


def parse_controllers(project: str, rel: str, text: str, symbol: JavaSymbol) -> List[ApiEndpoint]:
    if "RestController" not in symbol.annotations and "Controller" not in symbol.annotations:
        return []
    controller = (symbol.classes or [Path(rel).stem])[0]
    class_prefix = extract_annotation_value(text, "RequestMapping") or ""
    endpoints: List[ApiEndpoint] = []
    # crude method block scanner: annotation line followed by Java method signature
    pattern = re.compile(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?\s*(?:\n|\r|\s)*[^;{=]+?\s+(\w+)\s*\(", re.MULTILINE)
    for mapping, args, method_name in pattern.findall(text):
        if mapping == "RequestMapping":
            http = extract_method_from_args(args) or "REQUEST"
        else:
            http = mapping.replace("Mapping", "").upper()
        sub = extract_first_string(args) or ""
        full_path = join_path(class_prefix, sub)
        endpoints.append(ApiEndpoint(project, rel, controller, http, full_path, method_name))
    return endpoints


def parse_feign_clients(project: str, rel: str, text: str, symbol: JavaSymbol) -> List[FeignClient]:
    if "FeignClient" not in symbol.annotations:
        return []
    interface = (symbol.interfaces or symbol.classes or [Path(rel).stem])[0]
    ann_args = extract_annotation_args(text, "FeignClient") or ""
    target = extract_named_value(ann_args, "name") or extract_named_value(ann_args, "value") or extract_named_value(ann_args, "serviceId") or "unknown-service"
    base_path = extract_named_value(ann_args, "path") or ""
    methods: List[Dict] = []
    pattern = re.compile(r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*(?:\(([^)]*)\))?\s*(?:\n|\r|\s)*[^;{=]+?\s+(\w+)\s*\(", re.MULTILINE)
    for mapping, args, method_name in pattern.findall(text):
        http = extract_method_from_args(args) if mapping == "RequestMapping" else mapping.replace("Mapping", "").upper()
        methods.append({"method_name": method_name, "http_method": http or "REQUEST", "path": join_path(base_path, extract_first_string(args) or "")})
    return [FeignClient(project, rel, interface, target, base_path, methods)]


def parse_mq_endpoints(project: str, rel: str, text: str, symbol: JavaSymbol) -> List[MqEndpoint]:
    endpoints: List[MqEndpoint] = []
    class_name = (symbol.classes or [Path(rel).stem])[0]
    for args in re.findall(r"@KafkaListener\s*\(([^)]*)\)", text, flags=re.S):
        topic = extract_named_value(args, "topics") or extract_named_value(args, "topic") or extract_first_string(args) or "unknown-topic"
        group = extract_named_value(args, "groupId") or extract_named_value(args, "group")
        endpoints.append(MqEndpoint(project, rel, "kafka", clean_topic(topic), group, class_name))
    for args in re.findall(r"@RocketMQMessageListener\s*\(([^)]*)\)", text, flags=re.S):
        topic = extract_named_value(args, "topic") or "unknown-topic"
        group = extract_named_value(args, "consumerGroup") or extract_named_value(args, "selectorExpression")
        endpoints.append(MqEndpoint(project, rel, "rocketmq", clean_topic(topic), group, class_name))
    return endpoints


def parse_yaml_config(path: Path) -> Dict:
    try:
        return flatten_dict(yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {})
    except Exception:
        return {}


def build_topology(config: WorkspaceConfig, feigns: List[Dict], apis: List[Dict], mq: List[Dict], config_index: List[Dict]) -> Dict:
    services = [{"name": s.name, "service_name": s.service_name or s.name, "path": s.path, "type": s.type, "tags": s.tags} for s in config.services]
    service_names = {s["service_name"]: s["name"] for s in services}
    feign_edges = []
    for f in feigns:
        feign_edges.append({"from_project": f["project"], "to_service": f["target_service"], "to_project": service_names.get(f["target_service"]), "client": f["interface"], "file": f["file"]})
    mq_topics: Dict[str, Dict] = {}
    for m in mq:
        item = mq_topics.setdefault(m["topic"], {"topic": m["topic"], "consumers": [], "producers": []})
        item["consumers"].append({"project": m["project"], "file": m["file"], "class": m.get("class_name"), "kind": m["kind"]})
    return {"services": services, "feign_edges": feign_edges, "api_count": len(apis), "mq_topics": list(mq_topics.values()), "configs": config_index}


def first_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, flags=re.S)
    return m.group(1) if m else None


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


def flatten_dict(data: Dict, prefix: str = "") -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            out.update(flatten_dict(v, key))
        else:
            out[key] = str(v)
    return out

# ---- graph-first extensions -------------------------------------------------
from .graph import GraphEdge, GraphNode, GraphStore, edge_id, node_id


def build_graph_store(config: WorkspaceConfig, store: WorkspaceStore) -> Dict[str, int]:
    """Build a precomputed code/service/contract graph after normal indexes are written."""
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
    topology = store.read_json("service-topology.json", {})

    for svc in config.services:
        sid = node_id("Service", svc.name)
        nodes.append(GraphNode(sid, "Service", svc.name, svc.name, metadata={"service_name": svc.service_name or svc.name, "path": svc.path, "type": svc.type, "tags": svc.tags}))
        edges.append(GraphEdge(edge_id("CONTAINS", ws_id, sid), ws_id, sid, "CONTAINS"))

    for item in file_index:
        fid = node_id("File", item["path"])
        sid = node_id("Service", item["project"])
        nodes.append(GraphNode(fid, "File", Path(item["path"]).name, item["project"], item["path"], metadata=item))
        edges.append(GraphEdge(edge_id("CONTAINS", sid, fid), sid, fid, "CONTAINS"))

    for sym in symbols:
        fid = node_id("File", sym["file"])
        for cls in sym.get("classes", []) + sym.get("interfaces", []):
            cid = node_id("Class", sym["project"], cls)
            nodes.append(GraphNode(cid, "Class", cls, sym["project"], sym["file"], metadata={"package": sym.get("package"), "annotations": sym.get("annotations", [])}))
            edges.append(GraphEdge(edge_id("DECLARES", fid, cid), fid, cid, "DECLARES"))
            for m in sym.get("methods", []):
                mid = node_id("Method", sym["project"], cls, m)
                nodes.append(GraphNode(mid, "Method", f"{cls}.{m}", sym["project"], sym["file"]))
                edges.append(GraphEdge(edge_id("DECLARES", cid, mid), cid, mid, "DECLARES"))
            for fld in sym.get("fields", []):
                field_id = node_id("Field", sym["project"], cls, fld)
                nodes.append(GraphNode(field_id, "Field", f"{cls}.{fld}", sym["project"], sym["file"]))
                edges.append(GraphEdge(edge_id("DECLARES", cid, field_id), cid, field_id, "DECLARES"))
        # import edges as weak dependencies when imported simple name is indexed as a class
        for imp in sym.get("imports", []):
            imported_name = imp.split(".")[-1]
            for other in symbols:
                if imported_name in other.get("classes", []) + other.get("interfaces", []):
                    edges.append(GraphEdge(edge_id("IMPORTS", node_id("File", sym["file"]), node_id("File", other["file"])), node_id("File", sym["file"]), node_id("File", other["file"]), "IMPORTS", 0.55, {"import": imp}))

    for api in apis:
        eid = node_id("Endpoint", api["project"], api["http_method"], api["path"])
        cid = node_id("Class", api["project"], api["controller"])
        nodes.append(GraphNode(eid, "Endpoint", f"{api['http_method']} {api['path']}", api["project"], api["file"], metadata=api))
        edges.append(GraphEdge(edge_id("EXPOSES_ENDPOINT", cid, eid), cid, eid, "EXPOSES_ENDPOINT"))

    for f in feigns:
        fc_id = node_id("FeignClient", f["project"], f["interface"])
        cid = node_id("Class", f["project"], f["interface"])
        nodes.append(GraphNode(fc_id, "FeignClient", f["interface"], f["project"], f["file"], metadata=f))
        edges.append(GraphEdge(edge_id("DECLARES", cid, fc_id), cid, fc_id, "DECLARES"))
        target_service_id = node_id("Service", topology_service_project(topology, f.get("target_service")) or f.get("target_service", "unknown"))
        edges.append(GraphEdge(edge_id("CALLS_SERVICE", fc_id, target_service_id), fc_id, target_service_id, "CALLS_SERVICE", 0.9, {"target_service": f.get("target_service")}))
        for method in f.get("methods", []):
            fm_id = node_id("FeignMethod", f["project"], f["interface"], method.get("method_name", "unknown"))
            nodes.append(GraphNode(fm_id, "FeignMethod", f"{f['interface']}.{method.get('method_name')}", f["project"], f["file"], metadata=method))
            edges.append(GraphEdge(edge_id("DECLARES", fc_id, fm_id), fc_id, fm_id, "DECLARES"))
            for api in apis:
                if api.get("path") == method.get("path") or api.get("path") == method.get("path", "").replace(f.get("base_path", ""), ""):
                    ep_id = node_id("Endpoint", api["project"], api["http_method"], api["path"])
                    edges.append(GraphEdge(edge_id("IMPLEMENTS_FEIGN", fm_id, ep_id), fm_id, ep_id, "IMPLEMENTS_FEIGN", 0.75))

    for m in mq:
        topic_id = node_id("MQTopic", m["topic"])
        consumer_id = node_id("MQConsumer", m["project"], m.get("class_name") or Path(m["file"]).stem, m["topic"])
        nodes.append(GraphNode(topic_id, "MQTopic", m["topic"], metadata={"kind": m.get("kind")}))
        nodes.append(GraphNode(consumer_id, "MQConsumer", m.get("class_name") or Path(m["file"]).stem, m["project"], m["file"], metadata=m))
        edges.append(GraphEdge(edge_id("CONSUMES_TOPIC", consumer_id, topic_id), consumer_id, topic_id, "CONSUMES_TOPIC"))
        sid = node_id("Service", m["project"])
        edges.append(GraphEdge(edge_id("CONTAINS", sid, consumer_id), sid, consumer_id, "CONTAINS"))

    graph.bulk_write(nodes, edges)
    counts = graph.counts()
    store.write_json("graph-summary.json", counts)
    return counts


def topology_service_project(topology: Dict, service_name: str | None) -> str | None:
    for svc in topology.get("services", []):
        if svc.get("service_name") == service_name or svc.get("name") == service_name:
            return svc.get("name")
    return None
