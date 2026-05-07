from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List

from .graph import GraphStore
from .store import WorkspaceStore

SEMANTIC_INDEX_FILE = "semantic-node-index.json"
SEMANTIC_INDEX_VERSION = 1


def ensure_workspace_semantic_index(workspace_file: str | Path) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    graph = GraphStore(store.graph_db_path)
    counts = graph.counts()
    cached = store.read_json(SEMANTIC_INDEX_FILE, {})
    if cached.get("version") == SEMANTIC_INDEX_VERSION and cached.get("node_count") == counts.get("nodes"):
        return cached
    return build_workspace_semantic_index(workspace_file)


def build_workspace_semantic_index(workspace_file: str | Path) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    graph = GraphStore(store.graph_db_path)
    nodes = graph.all_nodes()
    docs = []
    df: Dict[str, int] = {}

    for node in nodes:
        text = _node_text(node)
        tokens = semantic_tokens(text)
        if not tokens:
            continue
        counts = _count_tokens(tokens)
        docs.append(
            {
                "node_id": node["id"],
                "type": node.get("type", ""),
                "name": node.get("name", ""),
                "project": node.get("project", ""),
                "file_path": node.get("file_path", ""),
                "token_counts": counts,
            }
        )
        for token in counts:
            df[token] = df.get(token, 0) + 1

    doc_count = max(len(docs), 1)
    for doc in docs:
        vector = {}
        total = sum(doc["token_counts"].values()) or 1
        for token, count in doc["token_counts"].items():
            idf = math.log((1 + doc_count) / (1 + df.get(token, 0))) + 1.0
            vector[token] = (count / total) * idf
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        doc["vector"] = vector
        doc["norm"] = norm
        del doc["token_counts"]

    payload = {"version": SEMANTIC_INDEX_VERSION, "node_count": len(nodes), "doc_count": len(docs), "docs": docs}
    store.write_json(SEMANTIC_INDEX_FILE, payload)
    return payload


def semantic_query(workspace_file: str | Path, query: str, limit: int = 20) -> List[Dict[str, Any]]:
    index = ensure_workspace_semantic_index(workspace_file)
    tokens = semantic_tokens(query)
    if not tokens:
        return []
    query_counts = _count_tokens(tokens)
    doc_count = max(index.get("doc_count", 1), 1)
    df = _estimate_df(index)
    query_vector = {}
    total = sum(query_counts.values()) or 1
    for token, count in query_counts.items():
        idf = math.log((1 + doc_count) / (1 + df.get(token, 0))) + 1.0
        query_vector[token] = (count / total) * idf
    query_norm = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0

    scored = []
    for doc in index.get("docs", []):
        dot = 0.0
        vector = doc.get("vector", {})
        for token, qv in query_vector.items():
            dot += qv * float(vector.get(token, 0.0))
        if dot <= 0:
            continue
        score = dot / (query_norm * float(doc.get("norm", 1.0)))
        scored.append({**doc, "score": score})
    scored.sort(key=lambda item: (-float(item.get("score", 0)), item.get("name", "")))
    return scored[:limit]


def semantic_index_stats(workspace_file: str | Path) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    payload = store.read_json(SEMANTIC_INDEX_FILE, {})
    return {
        "version": payload.get("version"),
        "node_count": int(payload.get("node_count", 0)),
        "doc_count": int(payload.get("doc_count", 0)),
        "ready": bool(payload.get("docs")),
    }


def semantic_tokens(text: str) -> List[str]:
    text = _split_camel(text or "")
    raw = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+", text.lower())
    tokens = [token for token in raw if len(token) >= 2]
    return tokens


def _split_camel(text: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)


def _count_tokens(tokens: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts


def _estimate_df(index: Dict[str, Any]) -> Dict[str, int]:
    df: Dict[str, int] = {}
    for doc in index.get("docs", []):
        for token in doc.get("vector", {}):
            df[token] = df.get(token, 0) + 1
    return df


def _node_text(node: Dict[str, Any]) -> str:
    parts = [
        node.get("type", ""),
        node.get("name", ""),
        node.get("project", ""),
        node.get("file_path", ""),
        json.dumps(node.get("metadata", {}), ensure_ascii=False),
    ]
    return " ".join(str(part) for part in parts if part)
