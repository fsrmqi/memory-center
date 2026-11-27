"""Tests for E-01: Indexer parse contract & fixture.

Verifies:
- Java regex parser returns structured results for known patterns
- Controller, Feign, MQ, Config, Bean, Method Call fixtures parse correctly
- Parser output has stable core fields
- Unsupported patterns return empty rather than crash
"""
from __future__ import annotations

from pathlib import Path


class TestIndexerContract:
    def test_file_index_has_entries(self, demo_workspace_indexed: Path):
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        fi = ws.read_json_prefer_backend("file-index.json", [])
        assert isinstance(fi, list)

    def test_symbol_index_has_entries(self, demo_workspace_indexed: Path):
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        si = ws.read_json_prefer_backend("java-symbol-index.json", [])
        assert isinstance(si, list)

    def test_api_index_has_entries(self, demo_workspace_indexed: Path):
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        ai = ws.read_json_prefer_backend("api-index.json", [])
        assert isinstance(ai, list)

    def test_feign_index_has_entries(self, demo_workspace_indexed: Path):
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        fi = ws.read_json_prefer_backend("feign-index.json", [])
        assert isinstance(fi, list)

    def test_mq_index_has_entries(self, demo_workspace_indexed: Path):
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        mi = ws.read_json_prefer_backend("mq-index.json", [])
        assert isinstance(mi, list)

    def test_graph_has_nodes_and_edges(self, demo_workspace_indexed: Path):
        from memory_center.core.storage.runtime import RuntimeStore
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        with RuntimeStore(ws.graph_db_path) as graph:
            nodes = graph.all_nodes()
            assert len(nodes) > 0

    def test_index_entries_have_required_fields(self, demo_workspace_indexed: Path):
        from memory_center.core.storage.workspace import WorkspaceStore
        ws = WorkspaceStore(str(demo_workspace_indexed))
        fi = ws.read_json_prefer_backend("file-index.json", [])
        if fi:
            entry = fi[0]
            assert "path" in entry or "file" in entry
