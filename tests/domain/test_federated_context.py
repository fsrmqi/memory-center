from __future__ import annotations

import subprocess
from pathlib import Path

from memory_center.core.orchestrator.bootstrap import (
    bootstrap_workspace_context,
    execute_provider_action,
)
from memory_center.core.providers.gitnexus import GitNexusProvider
from memory_center.core.providers.registry import ProviderRegistry, ProviderSpec
from memory_center.http.server import _route_request


class _ReadyProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def lookup(self, root, query, *, target="", intent="", limit=8):
        self.calls.append((str(root), query))
        return {
            "provider": "gitnexus",
            "status": "ready",
            "duration_ms": 3.0,
            "output": "Process: payment -> validate -> persist",
            "scope_checked": {"root": str(root), "limit": limit},
        }


class _UnavailableProvider:
    def lookup(self, root, query, *, target="", intent="", limit=8):
        return {"provider": "gitnexus", "status": "unavailable", "reason": "gitnexus_not_installed", "scope_checked": {"root": str(root)}}


def test_uninitialized_workspace_uses_ephemeral_gitnexus_evidence(tmp_path: Path) -> None:
    root = tmp_path / "plain-repo"
    root.mkdir()
    provider = _ReadyProvider()

    result = bootstrap_workspace_context(root, query="payment flow", provider=provider)

    assert result["context_state"] == "FEDERATED"
    assert result["provider"] == "gitnexus"
    assert result["persistence"] == "session_ephemeral_no_workspace_write"
    assert result["evidence"]["provenance_kind"] == "external_extracted"
    assert result["evidence_ref"]["provenance_kind"] == "EXTRACTED"
    assert "Process: payment" not in result["evidence_ref"].values()
    assert provider.calls == [(str(root), "payment flow")]
    assert not (root / ".memory-center").exists()


def test_uninitialized_workspace_falls_back_to_bounded_live_search(tmp_path: Path) -> None:
    root = tmp_path / "plain-repo"
    root.mkdir()

    result = bootstrap_workspace_context(root, intent="find controller", provider=_UnavailableProvider())

    assert result["context_state"] == "LIVE_SEARCH"
    assert result["provider"] == "local_search"
    assert result["tool_plan"][0]["tool"] == "rg"
    assert result["persistence"] == "none"


def test_unindexed_gitnexus_returns_confirmation_gated_refresh_action(tmp_path: Path) -> None:
    class UnindexedProvider:
        name = "gitnexus"

        def lookup(self, root, query, **_kwargs):
            return {
                "provider": self.name,
                "status": "unavailable",
                "reason": "gitnexus_index_not_found",
                "scope_checked": {"root": str(root)},
            }

    result = bootstrap_workspace_context(tmp_path, query="payment flow", provider=UnindexedProvider())

    assert result["context_state"] == "LIVE_SEARCH"
    assert result["freshness"]["status"] == "not_indexed"
    assert result["action_cards"] == [{
        "action_id": "provider-index-gitnexus",
        "title": "建立或刷新 GitNexus 索引",
        "provider": "gitnexus",
        "action": "analyze",
        "arguments": {"path": str(tmp_path), "provider": "gitnexus", "action": "analyze", "confirm": True},
        "mode": "controlled_write",
        "requires_confirmation": True,
        "reason": "GitNexus 索引未建立或已陈旧；仅在确认后执行受限 index-only 分析。",
        "stop_condition": "Provider status 恢复为 ready，或用户取消操作。",
    }]


def test_existing_workspace_remains_primary_and_does_not_call_provider(tmp_path: Path) -> None:
    from tests.fixtures import setup_demo_workspace

    workspace = setup_demo_workspace(tmp_path)

    result = bootstrap_workspace_context(workspace.parent.parent, intent="ArticleFeignClient", provider=_UnavailableProvider())

    assert result["context_state"] == "READY"
    assert result["provider"] == "memory_center"
    assert result["persistence"] == "existing_memory_center"
    assert result["provider_selection"]["selected"] == "memory_center"


def test_gitnexus_provider_uses_only_fixed_read_only_commands(tmp_path: Path) -> None:
    invocations: list[list[str]] = []

    def runner(argv, **_kwargs):
        invocations.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="indexed", stderr="")

    provider = GitNexusProvider(runner=runner, executable="gitnexus")
    result = provider.lookup(tmp_path, "payment flow", intent="trace request", limit=99)

    assert result["status"] == "ready"
    assert invocations == [
        ["gitnexus", "status"],
        ["gitnexus", "query", "payment flow", "--limit", "12", "--context", "trace request"],
    ]
    assert all("--content" not in command for command in invocations)


def test_gitnexus_provider_actions_require_confirmation_and_use_fixed_argv(tmp_path: Path) -> None:
    invocations: list[list[str]] = []

    def runner(argv, **_kwargs):
        invocations.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="done", stderr="")

    provider = GitNexusProvider(runner=runner, executable="gitnexus")

    pending = provider.execute(tmp_path, "analyze", force=True)
    impact = provider.execute(tmp_path, "impact", target="PaymentService", depth=99, limit=99)
    executed = provider.execute(tmp_path, "analyze", confirm=True, force=True)

    assert pending["status"] == "confirmation_required"
    assert impact["status"] == "ready"
    assert executed["status"] == "ready"
    assert invocations == [
        ["gitnexus", "impact", "PaymentService", "--depth", "5", "--limit", "12"],
        ["gitnexus", "analyze", "--index-only", "--force"],
    ]
    assert all("--content" not in command for command in invocations)


def test_provider_registry_falls_back_to_next_read_only_provider(tmp_path: Path) -> None:
    class UnavailableProvider:
        name = "unavailable"

        def lookup(self, root, query, **_kwargs):
            return {"provider": self.name, "status": "unavailable", "scope_checked": {"root": str(root)}}

    class ReadyProvider:
        name = "ready"

        def lookup(self, root, query, **_kwargs):
            return {"provider": self.name, "status": "ready", "output": query, "scope_checked": {"root": str(root)}}

    registry = ProviderRegistry(
        [
            ProviderSpec("unavailable", ("code_navigation",), UnavailableProvider, priority=1),
            ProviderSpec("ready", ("code_navigation",), ReadyProvider, priority=2),
        ]
    )

    result, selection = registry.lookup(tmp_path, "payment flow")

    assert result["provider"] == "ready"
    assert selection["selected"] == "ready"
    assert selection["attempted"] == [
        {"provider": "unavailable", "status": "unavailable"},
        {"provider": "ready", "status": "ready"},
    ]
    assert all(item["mutation_mode"] == "read_only" for item in selection["registry"])
    assert selection["health"]["ready"]["samples"] == 1


def test_provider_health_penalizes_repeated_failures(tmp_path: Path) -> None:
    class FlakyProvider:
        name = "flaky"

        def lookup(self, root, query, **_kwargs):
            return {"provider": self.name, "status": "unavailable", "duration_ms": 1_000, "scope_checked": {"root": str(root)}}

    registry = ProviderRegistry([ProviderSpec("flaky", ("code_navigation",), FlakyProvider)])
    registry.lookup(tmp_path, "first")
    _, selection = registry.lookup(tmp_path, "second")

    assert selection["health"]["flaky"]["status"] == "degraded"
    assert selection["health"]["flaky"]["error_rate"] == 1.0


def test_provider_action_rejects_unknown_provider_without_running_external_command(tmp_path: Path) -> None:
    result = execute_provider_action(tmp_path, provider="idea_mcp", action="rename", confirm=True)

    assert result["executed"] is False
    assert result["reason"] == "provider_not_registered"
    assert result["persistence"] == "external_provider_managed"


def test_http_bootstrap_context_keeps_uninitialized_project_write_free(tmp_path: Path) -> None:
    project = tmp_path / "plain-http-project"
    project.mkdir()

    result = _route_request(
        "/workspace/bootstrap-context",
        {"path": [str(project)], "query": ["payment handler"]},
        None,
    )

    assert result["context_state"] in {"FEDERATED", "LIVE_SEARCH"}
    assert not (project / ".memory-center").exists()
    assert not (tmp_path / "index").exists()
    assert not (tmp_path / "memory").exists()
