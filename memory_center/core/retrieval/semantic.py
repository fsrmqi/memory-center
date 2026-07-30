from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Lock
from typing import Any

from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore

from ..storage.metadata import metadata_json as _metadata_json

SEMANTIC_INDEX_FILE = "semantic-node-index.json"
SEMANTIC_INDEX_VERSION = 5
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
    backend = _requested_backend()
    requested_model = _requested_model_name(backend, workspace_file)
    requested_vector_scope = _requested_vector_scope()

    for node in nodes:
        text = _node_text(node)
        tokens = semantic_tokens(text)
        if not tokens:
            continue
        docs.append(
            {
                "node_id": node["id"],
                "type": node.get("type", ""),
                "name": node.get("name", ""),
                "project": node.get("project", ""),
                "file_path": node.get("file_path", ""),
                "text": text,
            }
        )
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

    metadata = {
        "version": SEMANTIC_INDEX_VERSION,
        "node_count": len(nodes),
        "doc_count": len(docs),
        "storage_mode": "runtime_indexes_v1",
        "requested_backend": backend,
        "requested_model": requested_model,
        "requested_vector_scope": requested_vector_scope,
        "backend": actual_backend,
        "model": model_name,
        "vector_candidate_count": vector_candidate_count,
        "dense_doc_count": dense_doc_count,
        **vector_state,
    }
    # BM25 posting lists and dense vectors have dedicated runtime stores.  The
    # returned docs are build-scoped input for vector synchronization only;
    # persisting them here used to duplicate the complete graph payload.
    store.write_json(SEMANTIC_INDEX_FILE, metadata)
    return {**metadata, "docs": docs}


def build_workspace_semantic_index_partial(workspace_file: str | Path, changed_node_ids: set[str]) -> dict[str, Any]:
    """Build only changed dense documents; BM25 is updated by InvertedIndex."""
    store = WorkspaceStore(workspace_file)
    existing = store.read_json_prefer_backend(SEMANTIC_INDEX_FILE, {})
    if not existing or existing.get("version") != SEMANTIC_INDEX_VERSION:
        return build_workspace_semantic_index(workspace_file)
    with RuntimeStore(store.graph_db_path) as graph:
        changed_nodes = graph.nodes_by_ids(changed_node_ids)
        total_node_count = graph.counts().get("nodes", 0)
    new_docs: list[dict[str, Any]] = []
    for node in changed_nodes:
        text = _node_text(node)
        tokens = semantic_tokens(text)
        if not tokens:
            continue
        new_docs.append(
            {
                "node_id": node["id"],
                "type": node.get("type", ""),
                "name": node.get("name", ""),
                "project": node.get("project", ""),
                "file_path": node.get("file_path", ""),
                "text": text,
            },
        )
    backend = _requested_backend()
    actual_backend = existing.get("backend", DEFAULT_SEMANTIC_BACKEND)
    requested_model = _requested_model_name(backend, workspace_file)
    model_name = existing.get("model")
    requested_vector_scope = _requested_vector_scope()
    vector_candidate_count = int(existing.get("vector_candidate_count", 0))
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
    for doc in new_docs:
        del doc["text"]
    dense_doc_count = int(existing.get("dense_doc_count", 0))
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
        "doc_count": total_node_count,
        "storage_mode": "runtime_indexes_v1",
        "requested_backend": backend,
        "requested_model": requested_model,
        "requested_vector_scope": requested_vector_scope,
        "backend": actual_backend,
        "model": model_name,
        "vector_candidate_count": vector_candidate_count,
        "dense_doc_count": dense_doc_count,
        **vector_state,
    }
    store.write_json(SEMANTIC_INDEX_FILE, payload)
    return {**payload, "docs": new_docs}


def semantic_query(workspace_file: str | Path, query: str, limit: int = 20) -> list[dict[str, Any]]:
    # 查询只读取已发布代际。索引过期由 freshness/后台 refresh 处理，不能在 MCP
    # 热路径隐式重建完整语义索引。
    index = WorkspaceStore(workspace_file).read_json_prefer_backend(SEMANTIC_INDEX_FILE, {}) or {}
    if not index.get("doc_count"):
        return []
    if index.get("backend") == "sentence-transformers":
        dense_hits = _dense_semantic_query(workspace_file, index, query, limit)
        if dense_hits:
            return dense_hits
    return _sparse_semantic_query(workspace_file, query, limit)


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
        "ready": bool(payload.get("doc_count")),
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
    try:
        from memory_center.core.storage.vector_index import VectorIndex

        workspace_store = WorkspaceStore(workspace_file)
        with RuntimeStore(workspace_store.graph_db_path) as runtime:
            hits = VectorIndex(runtime, dimension=len(query_vector)).query(query_vector, limit=limit)
            nodes = runtime.nodes_by_ids({str(hit.get("node_id", "")) for hit in hits})
        return _hydrate_hits(nodes, hits, backend="sentence-transformers-ann")
    except Exception:
        return []


def _sparse_semantic_query(workspace_file: str | Path, query: str, limit: int) -> list[dict[str, Any]]:
    from memory_center.core.retrieval.inverted import InvertedIndex

    workspace_store = WorkspaceStore(workspace_file)
    with RuntimeStore(workspace_store.graph_db_path) as runtime:
        hits = InvertedIndex(runtime).query(query, limit=limit)
        nodes = runtime.nodes_by_ids({str(hit.get("node_id", "")) for hit in hits})
    # Keep the established public source label; the implementation is the
    # SQLite inverted index rather than the retired in-memory sparse mirror.
    return _hydrate_hits(nodes, hits, backend="bm25")


def _hydrate_hits(nodes: list[dict[str, Any]], hits: list[dict[str, Any]], *, backend: str) -> list[dict[str, Any]]:
    """Join bounded index hits to graph metadata without materializing all nodes."""
    by_id = {str(node.get("id", "")): node for node in nodes}
    results = []
    for hit in hits:
        node = by_id.get(str(hit.get("node_id", "")))
        if node is None:
            continue
        results.append({
            "node_id": node["id"], "type": node.get("type", ""), "name": node.get("name", ""),
            "project": node.get("project", ""), "file_path": node.get("file_path", ""),
            "score": float(hit.get("score", 1.0 - float(hit.get("distance", 1.0)))), "backend": backend,
        })
    return results
