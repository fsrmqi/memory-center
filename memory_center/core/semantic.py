from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from .graph import GraphStore
from .store import WorkspaceStore

SEMANTIC_INDEX_FILE = "semantic-node-index.json"
SEMANTIC_INDEX_VERSION = 3
DEFAULT_SEMANTIC_BACKEND = "sparse"
DEFAULT_SENTENCE_TRANSFORMER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
BM25_K1 = 1.5
BM25_B = 0.75


def ensure_workspace_semantic_index(workspace_file: str | Path) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        counts = graph.counts()
    cached = store.read_json_prefer_backend(SEMANTIC_INDEX_FILE, {})
    backend = _requested_backend()
    model_name = _requested_model_name(backend)
    if (
        cached.get("version") == SEMANTIC_INDEX_VERSION
        and cached.get("node_count") == counts.get("nodes")
        and cached.get("requested_backend", DEFAULT_SEMANTIC_BACKEND) == backend
        and cached.get("requested_model") == model_name
    ):
        return cached
    return build_workspace_semantic_index(workspace_file)


def build_workspace_semantic_index(workspace_file: str | Path) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    with GraphStore(store.graph_db_path) as graph:
        nodes = graph.all_nodes()
    docs = []
    df: Dict[str, int] = {}
    backend = _requested_backend()
    requested_model = _requested_model_name(backend)

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
                "text": text,
                "token_counts": counts,
            }
        )
        for token in counts:
            df[token] = df.get(token, 0) + 1

    doc_count = max(len(docs), 1)
    for doc in docs:
        vector = {}
        total = sum(doc["token_counts"].values()) or 1
        doc["doc_len"] = total
        for token, count in doc["token_counts"].items():
            idf = math.log((1 + doc_count) / (1 + df.get(token, 0))) + 1.0
            vector[token] = (count / total) * idf
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        doc["sparse_vector"] = vector
        doc["sparse_norm"] = norm
        del doc["token_counts"]

    avgdl = sum(d["doc_len"] for d in docs) / doc_count

    actual_backend = DEFAULT_SEMANTIC_BACKEND
    model_name = None
    if backend == "sentence-transformers":
        model = _load_sentence_transformer_model(requested_model)
        if model is not None and docs:
            texts = [doc["text"] for doc in docs]
            dense_vectors = model.encode(texts, normalize_embeddings=True)
            for doc, vector in zip(docs, dense_vectors):
                doc["dense_vector"] = [float(value) for value in vector]
            actual_backend = "sentence-transformers"
            model_name = requested_model
    for doc in docs:
        del doc["text"]

    payload = {
        "version": SEMANTIC_INDEX_VERSION,
        "node_count": len(nodes),
        "doc_count": len(docs),
        "avgdl": avgdl,
        "requested_backend": backend,
        "requested_model": requested_model,
        "backend": actual_backend,
        "model": model_name,
        "df": df,
        "docs": docs,
    }
    store.write_json(SEMANTIC_INDEX_FILE, payload)
    return payload


def build_workspace_semantic_index_partial(workspace_file: str | Path, changed_node_ids: set[str]) -> Dict[str, Any]:
    """Rebuild semantic docs only for changed nodes, keeping untouched docs."""
    store = WorkspaceStore(workspace_file)
    existing = store.read_json_prefer_backend(SEMANTIC_INDEX_FILE, {})
    if not existing.get("docs"):
        return build_workspace_semantic_index(workspace_file)
    kept_docs = [doc for doc in existing.get("docs", []) if doc.get("node_id") not in changed_node_ids]
    with GraphStore(store.graph_db_path) as graph:
        changed_nodes = [n for n in graph.all_nodes() if n.get("id") in changed_node_ids]
        total_node_count = graph.counts().get("nodes", 0)
    new_docs: List[Dict[str, Any]] = []
    df_existing: Dict[str, int] = existing.get("df") or {}
    existing_doc_count = max(int(existing.get("doc_count", 0)), 1)
    df_new: Dict[str, int] = {}
    for node in changed_nodes:
        text = _node_text(node)
        tokens = semantic_tokens(text)
        if not tokens:
            continue
        counts = _count_tokens(tokens)
        new_docs.append(
            {
                "node_id": node["id"],
                "type": node.get("type", ""),
                "name": node.get("name", ""),
                "project": node.get("project", ""),
                "file_path": node.get("file_path", ""),
                "token_counts": counts,
            },
        )
        for token in counts:
            df_new[token] = df_new.get(token, 0) + 1
    # Compute removed docs to include their tokens in df for accurate IDF
    removed_docs = [doc for doc in existing.get("docs", []) if doc.get("node_id") in changed_node_ids]
    # Build df including tokens from removed docs so IDF accounts for them
    df: Dict[str, int] = {}
    for doc in kept_docs:
        for token in doc.get("sparse_vector", {}):
            df[token] = df.get(token, 0) + 1
    for doc in removed_docs:
        for token in doc.get("sparse_vector", {}):
            df[token] = df.get(token, 0) + 1
    for token, count in df_new.items():
        df[token] = df.get(token, 0) + count
    merged_docs = kept_docs + new_docs
    doc_count = max(len(merged_docs), 1)
    for doc in new_docs:
        total = sum(doc["token_counts"].values()) or 1
        doc["doc_len"] = total
        vector = {}
        for token, count in doc["token_counts"].items():
            idf = math.log((1 + doc_count) / (1 + df.get(token, 0))) + 1.0
            vector[token] = (count / total) * idf
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        doc["sparse_vector"] = vector
        doc["sparse_norm"] = norm
        del doc["token_counts"]
    for doc in kept_docs:
        vector = doc.get("sparse_vector", {})
        if not vector:
            continue
        # Re-scale sparse_vector from old IDF to merged IDF so all docs share the same baseline.
        # old weight = (tf/total) * idf_old; new weight = (tf/total) * idf_new = old * idf_new / idf_old
        rescaled = {}
        for token, old_weight in vector.items():
            idf_new = math.log((1 + doc_count) / (1 + df.get(token, 0))) + 1.0
            idf_old = math.log((1 + existing_doc_count) / (1 + df_existing.get(token, 0))) + 1.0
            rescaled[token] = old_weight * idf_new / idf_old
        doc["sparse_vector"] = rescaled
        doc["sparse_norm"] = math.sqrt(sum(value * value for value in rescaled.values())) or 1.0
    backend = DEFAULT_SEMANTIC_BACKEND
    actual_backend = existing.get("backend", DEFAULT_SEMANTIC_BACKEND)
    model_name = existing.get("model")
    if backend == "sentence-transformers" and actual_backend == "sentence-transformers":
        model = _load_sentence_transformer_model(model_name)
        if model is not None and new_docs:
            texts = [f"{d.get('type', '')} {d.get('name', '')} {d.get('project', '')} {d.get('file_path', '')}" for d in new_docs]
            dense_vectors = model.encode(texts, normalize_embeddings=True)
            for doc, vector in zip(new_docs, dense_vectors):
                doc["dense_vector"] = [float(value) for value in vector]
    payload = {
        "version": SEMANTIC_INDEX_VERSION,
        "node_count": total_node_count,
        "doc_count": len(merged_docs),
        "avgdl": sum(d.get("doc_len", 0) for d in merged_docs) / doc_count,
        "requested_backend": backend,
        "requested_model": existing.get("requested_model"),
        "backend": actual_backend,
        "model": model_name,
        "df": df,
        "docs": merged_docs,
    }
    store.write_json(SEMANTIC_INDEX_FILE, payload)
    return payload


def semantic_query(workspace_file: str | Path, query: str, limit: int = 20) -> List[Dict[str, Any]]:
    index = ensure_workspace_semantic_index(workspace_file)
    if index.get("backend") == "sentence-transformers":
        dense_hits = _dense_semantic_query(index, query, limit)
        if dense_hits:
            return dense_hits
    return _sparse_semantic_query(index, query, limit)


def semantic_index_stats(workspace_file: str | Path) -> Dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    payload = store.read_json_prefer_backend(SEMANTIC_INDEX_FILE, {})
    return {
        "version": payload.get("version"),
        "node_count": int(payload.get("node_count", 0)),
        "doc_count": int(payload.get("doc_count", 0)),
        "ready": bool(payload.get("docs")),
        "backend": payload.get("backend", DEFAULT_SEMANTIC_BACKEND),
        "requested_backend": payload.get("requested_backend", DEFAULT_SEMANTIC_BACKEND),
        "model": payload.get("model"),
        "requested_model": payload.get("requested_model"),
    }


def semantic_tokens(text: str) -> List[str]:
    text = _split_camel(text or "")
    raw = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[a-zA-Z0-9_]+", text.lower())
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
        for token in doc.get("sparse_vector", {}):
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


def _requested_backend() -> str:
    value = os.getenv("MEMORY_CENTER_SEMANTIC_BACKEND", DEFAULT_SEMANTIC_BACKEND).strip().lower()
    return value if value in {"sparse", "sentence-transformers"} else DEFAULT_SEMANTIC_BACKEND


def _requested_model_name(backend: str) -> str | None:
    if backend == "sentence-transformers":
        return os.getenv("MEMORY_CENTER_EMBEDDING_MODEL", DEFAULT_SENTENCE_TRANSFORMER_MODEL).strip() or DEFAULT_SENTENCE_TRANSFORMER_MODEL
    return None


def _load_sentence_transformer_model(model_name: str | None):
    if not model_name:
        return None
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None
    try:
        return SentenceTransformer(model_name)
    except Exception:
        return None


def _dense_semantic_query(index: Dict[str, Any], query: str, limit: int) -> List[Dict[str, Any]]:
    model_name = index.get("model")
    model = _load_sentence_transformer_model(model_name)
    if model is None:
        return []
    vector = model.encode([query], normalize_embeddings=True)[0]
    query_vector = [float(value) for value in vector]
    scored = []
    for doc in index.get("docs", []):
        dense_vector = doc.get("dense_vector")
        if not dense_vector:
            continue
        score = sum(float(left) * float(right) for left, right in zip(query_vector, dense_vector))
        if score <= 0:
            continue
        scored.append({**doc, "score": score, "backend": "sentence-transformers"})
    scored.sort(key=lambda item: (-float(item.get("score", 0)), item.get("name", "")))
    return scored[:limit]


def _sparse_semantic_query(index: Dict[str, Any], query: str, limit: int) -> List[Dict[str, Any]]:
    tokens = semantic_tokens(query)
    if not tokens:
        return []
    query_counts = _count_tokens(tokens)
    doc_count = max(index.get("doc_count", 1), 1)
    df = index.get("df") or _estimate_df(index)
    avgdl = index.get("avgdl", 0)

    # Check if any doc has doc_len (BM25 mode) or fall back to TF-IDF cosine
    docs = index.get("docs", [])
    has_bm25 = avgdl > 0 and any(d.get("doc_len", 0) > 0 for d in docs[:5])

    if has_bm25:
        # Okapi BM25 scoring
        if avgdl <= 0:
            avgdl = sum(d.get("doc_len", 0) for d in docs) / max(len(docs), 1) or 1.0
        scored = []
        for doc in docs:
            doc_len = doc.get("doc_len", 0)
            if doc_len <= 0:
                continue
            vector = doc.get("sparse_vector", {})
            score = 0.0
            for token, query_count in query_counts.items():
                tf = vector.get(token, 0.0)
                if tf <= 0:
                    continue
                idf = math.log((doc_count - df.get(token, 0) + 0.5) / (df.get(token, 0) + 0.5) + 1)
                score += idf * (tf * (BM25_K1 + 1)) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / avgdl))
            if score <= 0:
                continue
            scored.append({**doc, "score": score, "backend": "bm25"})
        scored.sort(key=lambda item: (-float(item.get("score", 0)), item.get("name", "")))
        return scored[:limit]
    else:
        # Fallback: TF-IDF cosine similarity (backward compatibility with version 2 indexes)
        query_vector = {}
        total = sum(query_counts.values()) or 1
        for token, count in query_counts.items():
            idf = math.log((1 + doc_count) / (1 + df.get(token, 0))) + 1.0
            query_vector[token] = (count / total) * idf
        query_norm = math.sqrt(sum(value * value for value in query_vector.values())) or 1.0

        scored = []
        for doc in docs:
            dot = 0.0
            vector = doc.get("sparse_vector", {})
            for token, qv in query_vector.items():
                dot += qv * float(vector.get(token, 0.0))
            if dot <= 0:
                continue
            score = dot / (query_norm * float(doc.get("sparse_norm", 1.0)))
            scored.append({**doc, "score": score, "backend": "sparse"})
        scored.sort(key=lambda item: (-float(item.get("score", 0)), item.get("name", "")))
        return scored[:limit]
