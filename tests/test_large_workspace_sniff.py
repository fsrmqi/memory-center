from __future__ import annotations

from pathlib import Path

from memory_center.core.orchestrator import workspace as workspace_module


class _FakeGraph:
    def __init__(self, _path: Path):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def find_nodes(self, _query: str, **_kwargs):
        return [
            {
                "type": "Method",
                "name": "processChannel",
                "project": "website-service",
                "file_path": "website-service/src/main/java/ChannelService.java",
                "metadata": {"service_name": "website-service", "suffix": ".java"},
            }
        ]


class _FakeStore:
    graph_db_path = Path("/tmp/graph.db")

    def read_json_prefer_backend(self, *_args):
        raise AssertionError("large workspace sniff must not load java-symbol-index.json when graph FTS has hits")


class _EmptyGraph(_FakeGraph):
    def find_nodes(self, _query: str, **_kwargs):
        return []


def test_large_workspace_sniff_prefers_graph_fts(monkeypatch) -> None:
    monkeypatch.setattr(workspace_module, "GraphStore", _FakeGraph)

    results = workspace_module._rank_sniff_files(
        _FakeStore(),
        [{"path": f"project/File{index}.java"} for index in range(2_000)],
        ["channel"],
        5,
    )

    assert results == [
        {
            "project": "website-service",
            "service_name": "website-service",
            "path": "website-service/src/main/java/ChannelService.java",
            "suffix": ".java",
            "score": 1,
            "symbols": [{"name": "processChannel", "type": "Method"}],
        }
    ]


def test_large_workspace_sniff_falls_back_to_paths_without_loading_symbols(monkeypatch) -> None:
    monkeypatch.setattr(workspace_module, "GraphStore", _EmptyGraph)

    results = workspace_module._rank_sniff_files(
        _FakeStore(),
        [{"path": "website-service/src/main/java/ChannelService.java"}] + [{"path": f"project/File{index}.java"} for index in range(1_999)],
        ["channel"],
        5,
    )

    assert results[0]["path"].endswith("ChannelService.java")
    assert results[0]["symbols"] == []
