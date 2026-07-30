from __future__ import annotations

import math
import os
import re
from pathlib import Path
from threading import Lock
from typing import Any

from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

from ..storage.metadata import metadata_json as _metadata_json

SEMANTIC_INDEX_FILE = "semantic-node-index.json"
SEMANTIC_INDEX_VERSION = 4
DEFAULT_SEMANTIC_BACKEND = "sparse"
DEFAULT_SENTENCE_TRANSFORMER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_VECTOR_SCOPE = "selective"
BM25_K1 = 1.5
BM25_B = 0.75

_VECTOR_ELIGIBLE_TYPES = {
    "Endpoint",
    "FeignClient",
    "MQConsumer",
    "MQProducer",
    "ConfigKey",
}
_VECTOR_CLASS_KEYWORDS = (
    "service",
    "controller",
    "job",
    "task",
    "scheduler",
    "config",
    "configuration",
    "listener",
    "consumer",
    "producer",
    "handler",
)
_METHOD_EXCLUDE_PREFIXES = ("get", "set", "is", "to", "hash", "equals", "test")
_MODEL_CACHE: dict[str, Any] = {}
_MODEL_CACHE_LOCK = Lock()


def ensure_workspace_semantic_index(workspace_file: str | Path) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
        counts = graph.counts()
    cached = store.read_json_prefer_backend(SEMANTIC_INDEX_FILE, {})
    backend = _requested_backend()
    model_name = _requested_model_name(backend, workspace_file)
    if (
        cached.get("version") == SEMANTIC_INDEX_VERSION
        and cached.get("node_count") == counts.get("nodes")
        and cached.get("requested_backend", DEFAULT_SEMANTIC_BACKEND) == backend
        and cached.get("requested_model") == model_name
        and cached.get("requested_vector_scope", DEFAULT_VECTOR_SCOPE) == _requested_vector_scope()
    ):
        return cached
    return build_workspace_semantic_index(workspace_file)


def build_workspace_semantic_index(workspace_file: str | Path) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
        nodes = graph.all_nodes()
    docs = []
    df: dict[str, int] = {}
    backend = _requested_backend()
    requested_model = _requested_model_name(backend, workspace_file)
    requested_vector_scope = _requested_vector_scope()

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
    dense_docs = [doc for doc in docs if _doc_is_vector_eligible(doc, scope=requested_vector_scope)]
    vector_candidate_count = len(dense_docs)
    vector_model_unavailable = False
    if backend == "sentence-transformers":
        model = _load_sentence_transformer_model(requested_model)
        if model is not None and dense_docs:
            texts = [doc["text"] for doc in dense_docs]
            dense_vectors = model.encode(texts, normalize_embeddings=True)
            if len(dense_docs) != len(dense_vectors):
                raise RuntimeError("semantic encoder returned an unexpected vector count")
            for doc, vector in zip(dense_docs, dense_vectors):  # noqa: B905 - lengths validated above
                doc["dense_vector"] = [float(value) for value in vector]
            actual_backend = "sentence-transformers"
            model_name = requested_model
        elif dense_docs:
            vector_model_unavailable = True
    for doc in docs:
        del doc["text"]
    dense_doc_count = sum(1 for doc in docs if doc.get("dense_vector"))
    vector_state = _vector_state(
        requested_backend=backend,
        actual_backend=actual_backend,
        vector_scope=requested_vector_scope,
        vector_candidate_count=vector_candidate_count,
        dense_doc_count=dense_doc_count,
        model_unavailable=vector_model_unavailable,
    )

    payload = {
        "version": SEMANTIC_INDEX_VERSION,
        "node_count": len(nodes),
        "doc_count": len(docs),
        "avgdl": avgdl,
        "requested_backend": backend,
        "requested_model": requested_model,
        "requested_vector_scope": requested_vector_scope,
        "backend": actual_backend,
        "model": model_name,
        "vector_candidate_count": vector_candidate_count,
        "dense_doc_count": dense_doc_count,
        **vector_state,
        "df": df,
        "docs": docs,
    }
    store.write_json(SEMANTIC_INDEX_FILE, payload)
    return payload


def build_workspace_semantic_index_partial(workspace_file: str | Path, changed_node_ids: set[str]) -> dict[str, Any]:
    """Rebuild semantic docs only for changed nodes, keeping untouched docs."""
    store = WorkspaceStore(workspace_file)
    existing = store.read_json_prefer_backend(SEMANTIC_INDEX_FILE, {})
    if not existing.get("docs"):
        return build_workspace_semantic_index(workspace_file)
    kept_docs = [doc for doc in existing.get("docs", []) if doc.get("node_id") not in changed_node_ids]
    with RuntimeStore(store.graph_db_path) as graph:
        changed_nodes = [n for n in graph.all_nodes() if n.get("id") in changed_node_ids]
        total_node_count = graph.counts().get("nodes", 0)
    new_docs: list[dict[str, Any]] = []
    df_existing: dict[str, int] = existing.get("df") or {}
    existing_doc_count = max(int(existing.get("doc_count", 0)), 1)
    df_new: dict[str, int] = {}
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
    df: dict[str, int] = {}
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
    backend = _requested_backend()
    actual_backend = existing.get("backend", DEFAULT_SEMANTIC_BACKEND)
    requested_model = _requested_model_name(backend, workspace_file)
    model_name = existing.get("model")
    requested_vector_scope = _requested_vector_scope()
    vector_candidate_count = sum(
        1 for doc in merged_docs if _doc_is_vector_eligible(doc, scope=requested_vector_scope)
    )
    if backend == "sentence-transformers" and actual_backend == "sentence-transformers":
        dense_new_docs = [doc for doc in new_docs if _doc_is_vector_eligible(doc, scope=requested_vector_scope)]
        model = _load_sentence_transformer_model(model_name)
        if model is not None and dense_new_docs:
            texts = [_dense_text_for_doc(d) for d in dense_new_docs]
            dense_vectors = model.encode(texts, normalize_embeddings=True)
            if len(dense_new_docs) != len(dense_vectors):
                raise RuntimeError("semantic encoder returned an unexpected vector count")
            for doc, vector in zip(dense_new_docs, dense_vectors):  # noqa: B905 - lengths validated above
                doc["dense_vector"] = [float(value) for value in vector]
    dense_doc_count = sum(1 for doc in merged_docs if doc.get("dense_vector"))
    vector_state = _vector_state(
        requested_backend=backend,
        actual_backend=actual_backend,
        vector_scope=requested_vector_scope,
        vector_candidate_count=vector_candidate_count,
        dense_doc_count=dense_doc_count,
        model_unavailable=backend == "sentence-transformers"
        and actual_backend != "sentence-transformers"
        and vector_candidate_count > 0,
    )
    payload = {
        "version": SEMANTIC_INDEX_VERSION,
        "node_count": total_node_count,
        "doc_count": len(merged_docs),
        "avgdl": sum(d.get("doc_len", 0) for d in merged_docs) / doc_count,
        "requested_backend": backend,
        "requested_model": requested_model,
        "requested_vector_scope": requested_vector_scope,
        "backend": actual_backend,
        "model": model_name,
        "vector_candidate_count": vector_candidate_count,
        "dense_doc_count": dense_doc_count,
        **vector_state,
        "df": df,
        "docs": merged_docs,
    }
    store.write_json(SEMANTIC_INDEX_FILE, payload)
    return payload


def semantic_query(workspace_file: str | Path, query: str, limit: int = 20) -> list[dict[str, Any]]:
    # 查询只读取已发布代际。索引过期由 freshness/后台 refresh 处理，不能在 MCP
    # 热路径隐式重建完整语义索引。
    index = WorkspaceStore(workspace_file).read_json_prefer_backend(SEMANTIC_INDEX_FILE, {}) or {}
    if not index.get("docs"):
        return []
    if index.get("backend") == "sentence-transformers":
        dense_hits = _dense_semantic_query(workspace_file, index, query, limit)
        if dense_hits:
            return dense_hits
    return _sparse_semantic_query(index, query, limit)


def semantic_index_stats(workspace_file: str | Path) -> dict[str, Any]:
    store = WorkspaceStore(workspace_file)
    payload = store.read_json_prefer_backend(SEMANTIC_INDEX_FILE, {})
    backend = payload.get("backend", DEFAULT_SEMANTIC_BACKEND)
    requested_backend = payload.get("requested_backend", DEFAULT_SEMANTIC_BACKEND)
    vector_scope = payload.get("requested_vector_scope", DEFAULT_VECTOR_SCOPE)
    vector_candidate_count = int(payload.get("vector_candidate_count", 0))
    dense_doc_count = int(payload.get("dense_doc_count", 0))
    vector_state = _vector_state(
        requested_backend=requested_backend,
        actual_backend=backend,
        vector_scope=vector_scope,
        vector_candidate_count=vector_candidate_count,
        dense_doc_count=dense_doc_count,
        model_unavailable=requested_backend == "sentence-transformers"
        and backend != "sentence-transformers"
        and vector_candidate_count > 0,
    )
    return {
        "version": payload.get("version"),
        "node_count": int(payload.get("node_count", 0)),
        "doc_count": int(payload.get("doc_count", 0)),
        "ready": bool(payload.get("docs")),
        "backend": backend,
        "requested_backend": requested_backend,
        "semantic_backend": backend,
        "requested_semantic_backend": requested_backend,
        "model": payload.get("model"),
        "requested_model": payload.get("requested_model"),
        "vector_scope": vector_scope,
        "vector_candidate_count": vector_candidate_count,
        "dense_doc_count": dense_doc_count,
        **vector_state,
    }


def semantic_tokens(text: str) -> list[str]:
    text = _split_camel(text or "")
    raw = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+|[a-zA-Z0-9_]+", text.lower())
    tokens = [token for token in raw if len(token) >= 2]
    return tokens


def _split_camel(text: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)


def _count_tokens(tokens: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    return counts


def _estimate_df(index: dict[str, Any]) -> dict[str, int]:
    df: dict[str, int] = {}
    for doc in index.get("docs", []):
        for token in doc.get("sparse_vector", {}):
            df[token] = df.get(token, 0) + 1
    return df


def _node_text(node: dict[str, Any]) -> str:
    parts = [
        node.get("type", ""),
        node.get("name", ""),
        node.get("project", ""),
        node.get("file_path", ""),
        _metadata_json(node.get("metadata")),
    ]
    return " ".join(str(part) for part in parts if part)


def _requested_backend() -> str:
    value = os.getenv("MEMORY_CENTER_SEMANTIC_BACKEND", DEFAULT_SEMANTIC_BACKEND).strip().lower()
    return value if value in {"sparse", "sentence-transformers"} else DEFAULT_SEMANTIC_BACKEND


def _dense_text_for_doc(doc: dict[str, Any]) -> str:
    parts = [
        doc.get("type", ""),
        doc.get("name", ""),
        doc.get("project", ""),
        doc.get("file_path", ""),
    ]
    return " ".join(str(part) for part in parts if part)


def _doc_is_vector_eligible(doc: dict[str, Any], *, scope: str) -> bool:
    if scope == "off":
        return False
    if scope == "all":
        return True

    node_type = str(doc.get("type", "") or "")
    name = str(doc.get("name", "") or "")
    file_path = str(doc.get("file_path", "") or "").lower()
    lower_name = name.lower()

    if node_type in _VECTOR_ELIGIBLE_TYPES:
        return True
    if node_type == "Class":
        return any(keyword in lower_name for keyword in _VECTOR_CLASS_KEYWORDS)
    if node_type == "Method":
        owner_class, _, method_name = name.partition(".")
        method_lower = method_name.lower()
        owner_lower = owner_class.lower()
        if method_lower.startswith(_METHOD_EXCLUDE_PREFIXES):
            return False
        return any(keyword in owner_lower for keyword in _VECTOR_CLASS_KEYWORDS)
    if node_type == "File":
        return file_path.endswith(".md") and (
            file_path.endswith("readme.md")
            or "/docs/" in f"/{file_path.lstrip('/')}"
        )
    return False


def _requested_vector_scope() -> str:
    value = os.getenv("MEMORY_CENTER_VECTOR_SCOPE", DEFAULT_VECTOR_SCOPE).strip().lower()
    return value if value in {"off", "selective", "all"} else DEFAULT_VECTOR_SCOPE


def _requested_model_name(backend: str, workspace_file: str | Path | None = None) -> str | None:
    if backend == "sentence-transformers":
        configured = os.getenv("MEMORY_CENTER_EMBEDDING_MODEL", "").strip()
        if configured:
            return configured
        if workspace_file:
            try:
                from memory_center.core.retrieval.model_profiles import MODEL_PROFILE_FILE

                profile = WorkspaceStore(workspace_file).read_json_prefer_backend(MODEL_PROFILE_FILE, {})
                selected = str(profile.get("embedding_model", "") or "") if isinstance(profile, dict) else ""
                if selected:
                    return selected
            except Exception:
                pass
        return DEFAULT_SENTENCE_TRANSFORMER_MODEL
    return None


def _vector_state(
    *,
    requested_backend: str,
    actual_backend: str,
    vector_scope: str,
    vector_candidate_count: int,
    dense_doc_count: int,
    model_unavailable: bool = False,
) -> dict[str, str | None]:
    if vector_scope == "off":
        return {"vector_status": "disabled", "vector_disabled_reason": "vector_scope_off"}
    if requested_backend != "sentence-transformers":
        return {"vector_status": "disabled", "vector_disabled_reason": "semantic_backend_sparse"}
    if model_unavailable or actual_backend != "sentence-transformers":
        return {"vector_status": "unavailable", "vector_disabled_reason": "sentence_transformers_model_unavailable"}
    if vector_candidate_count <= 0:
        return {"vector_status": "no_candidates", "vector_disabled_reason": "no_vector_eligible_docs"}
    if dense_doc_count <= 0:
        return {"vector_status": "unavailable", "vector_disabled_reason": "dense_embeddings_not_built"}
    return {"vector_status": "ready", "vector_disabled_reason": None}


def _load_sentence_transformer_model(model_name: str | None, *, allow_download: bool = False):
    """加载进程内单例 embedding 模型。

    默认仅使用本地缓存，避免普通请求被 Hugging Face 下载或重复加载权重阻塞。
    ``allow_download`` 仅供显式 reindex/预热维护窗口使用。
    """
    if not model_name:
        return None
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(model_name)
        if cached is not None:
            return cached
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None
    try:
        model = SentenceTransformer(model_name, local_files_only=not allow_download)
    except Exception:
        return None
    with _MODEL_CACHE_LOCK:
        # embedding 模型由工作区 profile 决定，最多保留当前和上一个，避免管理面
        # 切换 profile 后在常驻 MCP 进程中无界积累。
        if model_name not in _MODEL_CACHE and len(_MODEL_CACHE) >= 2:
            _MODEL_CACHE.pop(next(iter(_MODEL_CACHE)))
        _MODEL_CACHE[model_name] = model
    return model


def _dense_semantic_query(workspace_file: str | Path, index: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
    model_name = index.get("model")
    model = _load_sentence_transformer_model(model_name)
    if model is None:
        return []
    vector = model.encode([query], normalize_embeddings=True)[0]
    query_vector = [float(value) for value in vector]
    dense_docs = [doc for doc in index.get("docs", []) if doc.get("dense_vector")]
    # 小索引保留精确校验；大型工作区必须经 VectorIndex 的 ANN 查询，避免 Python
    # 全量扫描和排序占用 MCP 请求线程。
    if len(dense_docs) > 64:
        try:
            from memory_center.core.storage.vector_index import VectorIndex

            workspace_store = WorkspaceStore(workspace_file)
            runtime = RuntimeStore(workspace_store.graph_db_path)
            try:
                hits = VectorIndex(runtime, dimension=len(query_vector)).query(query_vector, limit=limit)
            finally:
                runtime.close()
            by_id = {str(doc.get("node_id", "")): doc for doc in dense_docs}
            return [
                {**by_id[str(hit["node_id"])], "score": float(hit.get("score", 1.0 - float(hit.get("distance", 1.0)))), "backend": "sentence-transformers-ann"}
                for hit in hits
                if str(hit.get("node_id", "")) in by_id
            ]
        except Exception:
            return []
    scored = []
    for doc in dense_docs:
        dense_vector = doc.get("dense_vector")
        if not dense_vector:
            continue
        if len(query_vector) != len(dense_vector):
            continue
        score = sum(float(left) * float(right) for left, right in zip(query_vector, dense_vector))  # noqa: B905 - lengths validated above
        if score <= 0:
            continue
        scored.append({**doc, "score": score, "backend": "sentence-transformers"})
    scored.sort(key=lambda item: (-float(item.get("score", 0)), item.get("name", "")))
    return scored[:limit]


def _sparse_semantic_query(index: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
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
            for token in query_counts:
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
    # Sparse cosine remains a supported scoring mode for documents whose token
    # vectors are not suitable for BM25 normalization.
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
