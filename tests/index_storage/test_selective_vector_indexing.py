from __future__ import annotations

from pathlib import Path

from memory_center.core.retrieval.semantic import (
    _doc_is_vector_eligible,
    build_workspace_semantic_index,
    semantic_index_stats,
)
from memory_center.core.storage.graph import GraphNode
from memory_center.core.storage.runtime import RuntimeStore
from memory_center.core.storage.workspace import WorkspaceStore


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / ".memory-center" / "workspace.yaml"
    workspace.parent.mkdir(parents=True, exist_ok=True)
    workspace.write_text(
        f"workspace: selective-vector\nroot: {tmp_path.as_posix()}\nservices: []\n",
        encoding="utf-8",
    )
    return workspace


def test_vector_eligibility_selective_scope_filters_low_value_nodes() -> None:
    assert _doc_is_vector_eligible({"type": "Endpoint", "name": "GET /api/orders"}, scope="selective") is True
    assert _doc_is_vector_eligible({"type": "FeignClient", "name": "OrderFeignClient"}, scope="selective") is True
    assert _doc_is_vector_eligible({"type": "MQConsumer", "name": "OrderListener"}, scope="selective") is True
    assert _doc_is_vector_eligible({"type": "ConfigKey", "name": "app.timeout"}, scope="selective") is True
    assert _doc_is_vector_eligible({"type": "Class", "name": "OrderService"}, scope="selective") is True
    assert _doc_is_vector_eligible({"type": "Method", "name": "OrderService.processOrder"}, scope="selective") is True
    assert _doc_is_vector_eligible({"type": "Method", "name": "OrderService.getStatus"}, scope="selective") is False
    assert _doc_is_vector_eligible({"type": "Field", "name": "OrderService.status"}, scope="selective") is False
    assert _doc_is_vector_eligible({"type": "File", "name": "README", "file_path": "README.md"}, scope="selective") is True
    assert _doc_is_vector_eligible({"type": "File", "name": "notes", "file_path": "src/main/java/OrderService.java"}, scope="selective") is False


def test_build_semantic_index_generates_dense_vectors_only_for_selective_nodes(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)

    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("Endpoint:demo:GET:/api/orders", "Endpoint", "GET /api/orders", "demo", "src/api/OrderController.java"),
                GraphNode("Class:demo:OrderService", "Class", "OrderService", "demo", "src/service/OrderService.java"),
                GraphNode("Method:demo:OrderService:processOrder", "Method", "OrderService.processOrder", "demo", "src/service/OrderService.java"),
                GraphNode("Method:demo:OrderService:getStatus", "Method", "OrderService.getStatus", "demo", "src/service/OrderService.java"),
                GraphNode("Field:demo:OrderService:status", "Field", "OrderService.status", "demo", "src/service/OrderService.java"),
                GraphNode("FeignClient:demo:OrderFeignClient", "FeignClient", "OrderFeignClient", "demo", "src/feign/OrderFeignClient.java"),
                GraphNode("MQConsumer:demo:OrderListener:orders", "MQConsumer", "OrderListener", "demo", "src/mq/OrderListener.java"),
                GraphNode("ConfigKey:demo:app.timeout", "ConfigKey", "app.timeout", "demo", "application.yml"),
                GraphNode("File:demo:README", "File", "README", "demo", "README.md"),
            ],
            [],
        )

    monkeypatch.setenv("MEMORY_CENTER_SEMANTIC_BACKEND", "sentence-transformers")
    monkeypatch.setenv("MEMORY_CENTER_VECTOR_SCOPE", "selective")

    class _FakeModel:
        def encode(self, texts, normalize_embeddings=True):
            return [[float(i + 1), 0.0, 0.0] for i, _text in enumerate(texts)]

    monkeypatch.setattr("memory_center.core.retrieval.semantic._load_sentence_transformer_model", lambda _name: _FakeModel())

    payload = build_workspace_semantic_index(workspace)
    docs = {doc["node_id"]: doc for doc in payload["docs"]}
    persisted = store.read_json_prefer_backend("semantic-node-index.json", {})

    assert payload["backend"] == "sentence-transformers"
    assert payload["requested_vector_scope"] == "selective"
    assert payload["vector_candidate_count"] == 7
    assert payload["dense_doc_count"] == 7
    assert persisted["storage_mode"] == "runtime_indexes_v1"
    assert "docs" not in persisted
    assert "df" not in persisted

    assert "dense_vector" in docs["Endpoint:demo:GET:/api/orders"]
    assert "dense_vector" in docs["Class:demo:OrderService"]
    assert "dense_vector" in docs["Method:demo:OrderService:processOrder"]
    assert "dense_vector" in docs["FeignClient:demo:OrderFeignClient"]
    assert "dense_vector" in docs["MQConsumer:demo:OrderListener:orders"]
    assert "dense_vector" in docs["ConfigKey:demo:app.timeout"]

    assert "dense_vector" not in docs["Method:demo:OrderService:getStatus"]
    assert "dense_vector" not in docs["Field:demo:OrderService:status"]
    assert "dense_vector" in docs["File:demo:README"]

    stats = semantic_index_stats(workspace)
    assert stats["vector_scope"] == "selective"
    assert stats["vector_candidate_count"] == 7
    assert stats["dense_doc_count"] == 7
    assert stats["vector_status"] == "ready"
    assert stats["vector_disabled_reason"] is None


def test_semantic_index_stats_explain_default_sparse_vector_status(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)

    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("Endpoint:demo:GET:/api/orders", "Endpoint", "GET /api/orders", "demo", "src/api/OrderController.java"),
            ],
            [],
        )

    monkeypatch.delenv("MEMORY_CENTER_SEMANTIC_BACKEND", raising=False)
    monkeypatch.delenv("MEMORY_CENTER_VECTOR_SCOPE", raising=False)

    payload = build_workspace_semantic_index(workspace)
    stats = semantic_index_stats(workspace)

    assert payload["requested_backend"] == "sparse"
    assert stats["semantic_backend"] == "sparse"
    assert stats["requested_semantic_backend"] == "sparse"
    assert stats["vector_scope"] == "selective"
    assert stats["vector_candidate_count"] == 1
    assert stats["dense_doc_count"] == 0
    assert stats["vector_status"] == "disabled"
    assert stats["vector_disabled_reason"] == "semantic_backend_sparse"


def test_semantic_index_stats_explain_unavailable_dense_backend(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    store = WorkspaceStore(workspace)

    with RuntimeStore(store.graph_db_path) as graph:
        graph.rebuild(
            [
                GraphNode("Endpoint:demo:GET:/api/orders", "Endpoint", "GET /api/orders", "demo", "src/api/OrderController.java"),
            ],
            [],
        )

    monkeypatch.setenv("MEMORY_CENTER_SEMANTIC_BACKEND", "sentence-transformers")
    monkeypatch.setenv("MEMORY_CENTER_VECTOR_SCOPE", "selective")
    monkeypatch.setattr("memory_center.core.retrieval.semantic._load_sentence_transformer_model", lambda _name: None)

    payload = build_workspace_semantic_index(workspace)
    stats = semantic_index_stats(workspace)

    assert payload["requested_backend"] == "sentence-transformers"
    assert stats["semantic_backend"] == "sparse"
    assert stats["requested_semantic_backend"] == "sentence-transformers"
    assert stats["vector_candidate_count"] == 1
    assert stats["dense_doc_count"] == 0
    assert stats["vector_status"] == "unavailable"
    assert stats["vector_disabled_reason"] == "sentence_transformers_model_unavailable"
