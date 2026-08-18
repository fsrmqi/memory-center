"""Retrieval 命令族:按业务域从 cli/main.py 拆出的命令组(ADR-0002)。"""
from __future__ import annotations

import json

import typer

from memory_center.core.storage.workspace import WorkspaceStore


def register_retrieval_commands(app: typer.Typer) -> None:
    @app.command("vector-ann-status")
    def vector_ann_status(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    ):
        """Show dense-vector ANN readiness without querying or rebuilding the index."""
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex

        store = WorkspaceStore(workspace)
        with RuntimeStore(store.graph_db_path) as runtime:
            typer.echo(json.dumps(VectorIndex(runtime).stats(), ensure_ascii=False, indent=2))

    @app.command("vector-ann-rebuild")
    def vector_ann_rebuild(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
    ):
        """Explicitly rebuild the persistent HNSW index from existing dense vectors."""
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex

        store = WorkspaceStore(workspace)
        with RuntimeStore(store.graph_db_path) as runtime:
            typer.echo(json.dumps(VectorIndex(runtime).rebuild_ann(), ensure_ascii=False, indent=2))

    @app.command("vector-ann-tune")
    def vector_ann_tune(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        sample_size: int = typer.Option(48, min=8, max=128),
    ):
        """Tune HNSW query ef using bounded self-recall probes."""
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.vector_index import VectorIndex

        store = WorkspaceStore(workspace)
        with RuntimeStore(store.graph_db_path) as runtime:
            typer.echo(json.dumps(VectorIndex(runtime).tune_ann(sample_size), ensure_ascii=False, indent=2))

    @app.command("retrieval-reranker-status")
    def retrieval_reranker_status_cmd(
        model: str = typer.Option("", help="Optional Cross-Encoder model name."),
    ):
        """Show whether the optional reranker is already cached locally."""
        from memory_center.core.retrieval.hybrid import reranker_status

        typer.echo(json.dumps(reranker_status(model or None), ensure_ascii=False, indent=2))

    @app.command("retrieval-reranker-prewarm")
    def retrieval_reranker_prewarm_cmd(
        model: str = typer.Option("", help="Optional Cross-Encoder model name."),
    ):
        """Explicitly download and load the optional reranker outside MCP query requests."""
        from memory_center.core.retrieval.hybrid import prewarm_reranker

        typer.echo(json.dumps(prewarm_reranker(model or None), ensure_ascii=False, indent=2))

    @app.command("retrieval-model-profile")
    def retrieval_model_profile_cmd(
        workspace: str = typer.Option(..., help="Path to .memory-center/workspace.yaml"),
        profile: str = typer.Option("", help="balanced|multilingual"),
        apply: bool = typer.Option(False, help="Persist the selected profile; a full reindex is still explicit."),
    ):
        """Preview or select an embedding profile without implicitly rebuilding indexes."""
        from memory_center.core.retrieval.model_profiles import retrieval_model_profile

        typer.echo(json.dumps(retrieval_model_profile(workspace, profile, apply), ensure_ascii=False, indent=2))

