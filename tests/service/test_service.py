import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from memory_center.service.app import create_service_app
from memory_center.service.config import ServiceConfig


def test_lifespan_and_fresh_data(tmp_path, monkeypatch):
    legacy = tmp_path / ".memory-center" / "workspace.yaml"
    legacy.parent.mkdir()
    legacy.write_text("invalid legacy configuration")
    monkeypatch.chdir(tmp_path)
    app = create_service_app(ServiceConfig(tmp_path / "v5", auth_mode="token"))
    assert TestClient(app).get("/health/ready").status_code == 503
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        assert client.get("/health/ready").json() == {"ready": True}
        status = client.get("/api/v1/service/status").json()
        assert {"service_status", "workspace_catalog", "scoped_mcp", "background_index", "knowledge"} <= set(status["capabilities"])
        assert str(tmp_path) not in str(status)
        assert client.get("/admin/").status_code == 200
        assert client.get("/mcp").status_code != 307
    assert TestClient(app).get("/health/ready").status_code == 503
    assert legacy.read_text() == "invalid legacy configuration"
    assert {p.name for p in (tmp_path / "v5").iterdir()} == {"catalog.db", "admin-token", "platform.db", "service.lock"}


def test_missing_assets_fail_startup(tmp_path):
    with pytest.raises(RuntimeError, match="管理页面资源缺失"):
        with TestClient(create_service_app(ServiceConfig(tmp_path / "v5", auth_mode="token"), static_dir=tmp_path)):
            pass


def test_invalid_port(tmp_path):
    with pytest.raises(ValueError, match="端口"):
        ServiceConfig(tmp_path, port=0)


def test_tcp_mcp_shutdown_and_port_conflict(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-m", "memory_center.service.main", "--port", str(port),
               "--data-dir", str(tmp_path / "data"), "--auth-mode", "token"]
    env = dict(os.environ, PYTHONPATH=str(root))
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(command, cwd=tmp_path, env=env, stdout=log, stderr=log)
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    if httpx.get(url + "/health/ready", timeout=.2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    log.seek(0)
                    pytest.fail(log.read())
                time.sleep(.05)
            else:
                pytest.fail("服务未就绪")
            conflict = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
            assert conflict.returncode == 1
            assert "端口已被占用" in conflict.stderr

            async def check_mcp():
                async with streamable_http_client(url + "/mcp") as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert [t.name for t in tools.tools] == ["mc_service_status"]
                        result = await session.call_tool("mc_service_status")
                        assert not result.isError
                        assert result.structuredContent["ready"] is True
                        # Unknown tools must fail explicitly without changing service state.
                        failure = await session.call_tool("mc_lookup", {"query": "anything"})
                        assert failure.isError
            asyncio.run(check_mcp())
            assert httpx.get(url + "/health/ready").status_code == 200
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                pytest.fail("关闭超时")
        assert process.returncode in (0, -signal.SIGTERM)
        with socket.socket() as released:
            released.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            released.bind(("127.0.0.1", port))
        log.seek(0)
        assert "Application shutdown complete" in log.read()


def test_mcp_cancellation_and_host_guard(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import anyio

    import memory_center.service.app as app_module

    started = threading.Event()
    cancelled = threading.Event()
    original = app_module.FastMCP

    def test_server(*args, **kwargs):
        server = original(*args, **kwargs)
        from memory_center.platform.security import Principal
        server.actor = lambda: Principal("anonymous", (), frozenset({"mc_service_status", "slow_probe"}))

        @server.tool()
        async def slow_probe() -> str:
            started.set()
            try:
                await anyio.sleep(30)
                return "unexpected"
            finally:
                cancelled.set()

        return server

    monkeypatch.setattr(app_module, "FastMCP", test_server)
    app = create_service_app(ServiceConfig(tmp_path / "data", auth_mode="token"))
    with TestClient(app, base_url="http://localhost") as client:
        headers = {"Accept": "application/json, text/event-stream"}
        body = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "cancellation-test", "version": "1"},
        }}
        assert client.post("/mcp", json=body, headers={**headers, "Host": "untrusted.invalid"}).status_code == 421
        init = client.post("/mcp", json=body, headers=headers)
        assert init.status_code == 200
        headers.update({"Mcp-Session-Id": init.headers["mcp-session-id"],
                        "MCP-Protocol-Version": init.json()["result"]["protocolVersion"]})
        assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers).status_code == 202
        with ThreadPoolExecutor(max_workers=1) as pool:
            call = pool.submit(client.post, "/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "slow_probe", "arguments": {}},
            })
            assert started.wait(3)
            response = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "method": "notifications/cancelled",
                "params": {"requestId": 2, "reason": "test"},
            })
            assert response.status_code == 202
            assert cancelled.wait(3)
            assert "cancelled" in call.result(timeout=3).json()["error"]["message"].lower()
        assert client.get("/health/ready").status_code == 200
        assert client.delete("/mcp", headers=headers).status_code == 200


def test_service_documentation_is_discoverable():
    root = Path(__file__).resolve().parents[2]
    for name in ("README.md", "docs/USER_GUIDE.md", "docs/REFERENCE.md", "docs/MCP_GUIDE.md"):
        content = (root / name).read_text()
        assert "memory-center-service" in content
        assert "mc_service_status" in content
        assert "V5_SERVICE_GUIDE.md" in content
