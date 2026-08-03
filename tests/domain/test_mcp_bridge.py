"""受限外部 MCP Client Bridge 的策略与调用边界测试。"""
from __future__ import annotations

import json
from pathlib import Path

from memory_center.core.providers.mcp_bridge import (
    McpBridgeProvider,
    load_mcp_bridge_policy,
    mcp_bridge_policy_status,
)


class _FakeMcpClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke(self, *, url, transport, tool, arguments, timeout_seconds):
        self.calls.append({
            "url": url,
            "transport": transport,
            "tool": tool,
            "arguments": arguments,
            "timeout_seconds": timeout_seconds,
        })
        return {"content": [{"type": "text", "text": "symbol context"}]}


def _write_policy(root: Path, providers: list[dict]) -> None:
    state = root / ".memory-center"
    state.mkdir(parents=True)
    (state / "provider-mcp-policy.json").write_text(
        json.dumps({"schema_version": 1, "providers": providers}), encoding="utf-8"
    )


def test_bridge_invokes_only_registered_tool_with_fixed_template(tmp_path: Path) -> None:
    _write_policy(tmp_path, [{
        "id": "idea_mcp",
        "server": "idea",
        "url": "http://127.0.0.1:64342/sse",
        "transport": "sse",
        "timeout_seconds": 9,
        "tools": [{
            "action": "symbol_context",
            "tool": "get_symbol_info",
            "mode": "read_only",
            "arguments": {"symbol": "{target}", "query": "{query}"},
        }],
    }])
    policy = load_mcp_bridge_policy(tmp_path)["idea_mcp"]
    client = _FakeMcpClient()

    result = McpBridgeProvider(policy, client).execute(
        "symbol_context", query="payment", target="PaymentService"
    )

    assert result["status"] == "ready"
    assert result["scope_checked"]["tool"] == "get_symbol_info"
    assert result["persistence"] == "session_ephemeral"
    assert client.calls == [{
        "url": "http://127.0.0.1:64342/sse",
        "transport": "sse",
        "tool": "get_symbol_info",
        "arguments": {"symbol": "PaymentService", "query": "payment"},
        "timeout_seconds": 9.0,
    }]
    assert McpBridgeProvider(policy, client).execute("arbitrary")["status"] == "action_not_allowed"


def test_bridge_requires_confirmation_for_every_mutating_mode(tmp_path: Path) -> None:
    _write_policy(tmp_path, [{
        "id": "gitnexus_mcp",
        "server": "gitnexus",
        "url": "http://127.0.0.1:3333/mcp",
        "transport": "streamable_http",
        "tools": [{
            "action": "refresh_index",
            "tool": "index_workspace",
            "mode": "controlled_write",
            "confirmation_required": False,
            "arguments": {"scope": "{target}"},
        }],
    }])
    policy = load_mcp_bridge_policy(tmp_path)["gitnexus_mcp"]
    client = _FakeMcpClient()
    bridge = McpBridgeProvider(policy, client)

    assert bridge.execute("refresh_index", target="module")["status"] == "confirmation_required"
    assert bridge.execute("refresh_index", target="module", confirm=True)["status"] == "ready"
    assert len(client.calls) == 1


def test_bridge_ignores_unsafe_policy_and_status_does_not_create_state(tmp_path: Path) -> None:
    assert mcp_bridge_policy_status(tmp_path)["providers"] == []
    assert not (tmp_path / ".memory-center").exists()
    _write_policy(tmp_path, [{
        "id": "unsafe",
        "url": "stdio://run-anything",
        "tools": [{"action": "bad", "tool": "shell", "arguments": {"cmd": "{query.__class__}"}}],
    }])

    assert load_mcp_bridge_policy(tmp_path) == {}


def test_bridge_ignores_policy_url_credentials_and_invalid_timeout(tmp_path: Path) -> None:
    _write_policy(tmp_path, [
        {
            "id": "credentialed",
            "url": "https://token@example.invalid/mcp",
            "tools": [{"action": "lookup", "tool": "lookup", "arguments": {}}],
        },
        {
            "id": "bounded",
            "url": "https://example.invalid/mcp",
            "timeout_seconds": "not-a-number",
            "tools": [{"action": "lookup", "tool": "lookup", "arguments": {}}],
        },
    ])

    policies = load_mcp_bridge_policy(tmp_path)
    assert set(policies) == {"bounded"}
    assert policies["bounded"].timeout_seconds == 10.0
