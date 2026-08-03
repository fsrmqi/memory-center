"""受限外部 MCP Client Bridge。"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urlsplit

POLICY_FILENAME = "provider-mcp-policy.json"
_MAX_OUTPUT_CHARS = 12_000
_MAX_TIMEOUT_SECONDS = 60.0


class McpBridgeClient(Protocol):
    def invoke(self, *, url: str, transport: str, tool: str, arguments: dict[str, Any], timeout_seconds: float) -> dict[str, Any]: ...


@dataclass(frozen=True)
class McpToolPolicy:
    action: str
    tool: str
    mode: str
    arguments: dict[str, str]
    confirmation_required: bool


@dataclass(frozen=True)
class McpProviderPolicy:
    provider_id: str
    server: str
    url: str
    transport: str
    timeout_seconds: float
    tools: tuple[McpToolPolicy, ...]


def bridge_policy_path(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / ".memory-center" / POLICY_FILENAME


def load_mcp_bridge_policy(root: str | Path) -> dict[str, McpProviderPolicy]:
    """加载工作区维护者登记的 MCP Bridge 策略；缺失即为空。"""
    path = bridge_policy_path(root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    providers: dict[str, McpProviderPolicy] = {}
    for item in raw.get("providers", []) if isinstance(raw.get("providers"), list) else []:
        policy = _normalize_provider_policy(item)
        if policy is not None:
            providers[policy.provider_id] = policy
    return providers


def mcp_bridge_policy_status(root: str | Path) -> dict[str, Any]:
    policies = load_mcp_bridge_policy(root)
    return {
        "schema_version": 1,
        "policy_path": str(bridge_policy_path(root)),
        "providers": [
            {
                "provider": policy.provider_id,
                "server": policy.server,
                "transport": policy.transport,
                "timeout_seconds": policy.timeout_seconds,
                "actions": [
                    {"action": tool.action, "tool": tool.tool, "mode": tool.mode, "confirmation_required": tool.confirmation_required}
                    for tool in policy.tools
                ],
            }
            for policy in policies.values()
        ],
        "next_action": "在 provider-mcp-policy.json 登记白名单 Server 与 tool 后使用 mcp-bridge-action。" if not policies else "选择已登记的 provider 和 action 执行。",
    }


class McpBridgeProvider:
    """仅通过策略登记的 HTTP MCP Server 调用白名单工具。"""

    def __init__(self, policy: McpProviderPolicy, client: McpBridgeClient | None = None) -> None:
        self.name = policy.provider_id
        self._policy = policy
        self._client = client or HttpMcpBridgeClient()

    def action_descriptors(self) -> list[dict[str, Any]]:
        return [
            {
                "action": tool.action,
                "tool": tool.tool,
                "mode": tool.mode,
                "confirmation_required": tool.confirmation_required,
            }
            for tool in self._policy.tools
        ]

    def execute(self, action: str, *, query: str = "", target: str = "", confirm: bool = False) -> dict[str, Any]:
        tool_policy = next((item for item in self._policy.tools if item.action == action.strip()), None)
        if tool_policy is None:
            return {
                "provider": self.name,
                "status": "action_not_allowed",
                "action": action,
                "next_action": "在 provider-mcp-policy.json 的 tools 白名单中登记该 action。",
            }
        if tool_policy.confirmation_required and not confirm:
            return {
                "provider": self.name,
                "status": "confirmation_required",
                "action": tool_policy.action,
                "mode": tool_policy.mode,
                "next_action": f"确认后以 confirm=true 调用外部 MCP action={tool_policy.action}。",
            }
        arguments = _render_arguments(tool_policy.arguments, query=query, target=target)
        started_at = monotonic()
        try:
            response = self._client.invoke(
                url=self._policy.url,
                transport=self._policy.transport,
                tool=tool_policy.tool,
                arguments=arguments,
                timeout_seconds=self._policy.timeout_seconds,
            )
        except Exception as exc:
            return {
                "provider": self.name,
                "status": "unavailable",
                "reason": "mcp_bridge_call_failed",
                "action": tool_policy.action,
                "mode": tool_policy.mode,
                "diagnostic": type(exc).__name__,
                "duration_ms": round((monotonic() - started_at) * 1000, 3),
                "scope_checked": _scope_checked(self._policy, tool_policy),
                "next_action": "检查外部 MCP Server 状态、策略 URL、transport 与白名单 tool。",
            }
        return {
            "provider": self.name,
            "status": "ready",
            "action": tool_policy.action,
            "tool": tool_policy.tool,
            "mode": tool_policy.mode,
            "arguments": arguments,
            "output": _bounded_response(response),
            "duration_ms": round((monotonic() - started_at) * 1000, 3),
            "scope_checked": _scope_checked(self._policy, tool_policy),
            "persistence": "session_ephemeral",
        }


class HttpMcpBridgeClient:
    """使用官方 MCP Python Client 连接 SSE 或 Streamable HTTP Server。"""

    def invoke(self, *, url: str, transport: str, tool: str, arguments: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        return _run_async(
            asyncio.wait_for(
                _invoke_mcp_tool(url, transport, tool, arguments, timeout_seconds),
                timeout=timeout_seconds,
            )
        )


async def _invoke_mcp_tool(url: str, transport: str, tool: str, arguments: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    from mcp import ClientSession

    normalized = transport.strip().lower()
    if normalized == "sse":
        from mcp.client.sse import sse_client

        async with sse_client(url, timeout=timeout_seconds, sse_read_timeout=timeout_seconds) as streams:
            return await asyncio.wait_for(
                _invoke_in_session(ClientSession, streams, tool, arguments), timeout=timeout_seconds
            )
    if normalized == "streamable_http":
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(url) as streams:
            return await asyncio.wait_for(
                _invoke_in_session(ClientSession, streams, tool, arguments), timeout=timeout_seconds
            )
    raise ValueError("unsupported_mcp_transport")


async def _invoke_in_session(session_type: Any, streams: tuple[Any, Any], tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with session_type(*streams) as session:
        await session.initialize()
        available = await session.list_tools()
        names = {item.name for item in available.tools}
        if tool not in names:
            raise ValueError("mcp_tool_not_exposed")
        response = await session.call_tool(tool, arguments)
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        return {"result": str(response)}


def _run_async(coro: Any) -> dict[str, Any]:
    """同步入口在已有事件循环时转交独立线程，避免嵌套 asyncio.run。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict[str, Any] = {}
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.update(asyncio.run(coro))
        except BaseException as exc:  # pragma: no cover - mirrors caller failure
            error.append(exc)

    thread = threading.Thread(target=runner, name="memory-center-mcp-bridge", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result


def _normalize_provider_policy(raw: Any) -> McpProviderPolicy | None:
    if not isinstance(raw, dict):
        return None
    provider_id = str(raw.get("id", "") or "").strip()
    server = str(raw.get("server", provider_id) or provider_id).strip()
    url = str(raw.get("url", "") or "").strip()
    transport = str(raw.get("transport", "sse") or "sse").strip().lower()
    if not provider_id or not server or not _valid_http_url(url) or transport not in {"sse", "streamable_http"}:
        return None
    tools: list[McpToolPolicy] = []
    for item in raw.get("tools", []) if isinstance(raw.get("tools"), list) else []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "") or "").strip()
        tool = str(item.get("tool", "") or "").strip()
        mode = str(item.get("mode", "read_only") or "read_only").strip()
        arguments = item.get("arguments", {})
        normalized_arguments = {str(key): str(value) for key, value in arguments.items()} if isinstance(arguments, dict) else {}
        if (
            action
            and tool
            and mode in {"read_only", "controlled_write", "destructive"}
            and isinstance(arguments, dict)
            and _valid_argument_template(normalized_arguments)
        ):
            tools.append(
                McpToolPolicy(
                    action,
                    tool,
                    mode,
                    normalized_arguments,
                    bool(item.get("confirmation_required", False)) or mode != "read_only",
                )
            )
    return McpProviderPolicy(
        provider_id,
        server,
        url,
        transport,
        _bounded_timeout(raw.get("timeout_seconds", 10.0)),
        tuple(tools),
    )


def _valid_http_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _bounded_timeout(value: Any) -> float:
    try:
        return min(_MAX_TIMEOUT_SECONDS, max(1.0, float(value or 10.0)))
    except (TypeError, ValueError):
        return 10.0


def _render_arguments(template: dict[str, str], *, query: str, target: str) -> dict[str, str]:
    values = {"query": query.strip()[:2_000], "target": target.strip()[:2_000]}
    return {key: value.format(**values)[:2_000] for key, value in template.items()}


def _valid_argument_template(arguments: dict[str, str]) -> bool:
    """仅允许常量与 query/target 占位符，禁止格式化属性、索引和未知字段。"""
    formatter = Formatter()
    try:
        for key, value in arguments.items():
            if not key or len(key) > 128:
                return False
            for _, field_name, format_spec, conversion in formatter.parse(value):
                if field_name not in {None, "query", "target"} or format_spec or conversion:
                    return False
    except ValueError:
        return False
    return True


def _scope_checked(policy: McpProviderPolicy, tool: McpToolPolicy) -> dict[str, Any]:
    return {
        "provider": policy.provider_id,
        "server": policy.server,
        "transport": policy.transport,
        "tool": tool.tool,
        "mode": tool.mode,
    }


def _bounded_response(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)[:_MAX_OUTPUT_CHARS]
