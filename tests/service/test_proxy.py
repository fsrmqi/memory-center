"""stdio 代理必须使用发行 SDK 的真实 HTTP 客户端合同。"""
import asyncio
import os
import socket
import subprocess
import sys
import time

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_proxy_real_transport(tmp_path):
    with socket.socket() as socket_probe:
        socket_probe.bind(('127.0.0.1', 0))
        port = socket_probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with (tmp_path / 'server.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'memory_center.service.main', '--port', str(port),
                                    '--data-dir', str(tmp_path / 'data')], stdout=log, stderr=log)
        try:
            for _ in range(100):
                try:
                    if httpx.get(url + '/health/ready', timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    raise AssertionError((tmp_path / 'server.log').read_text())
                time.sleep(.1)
            else:
                raise AssertionError('服务未就绪')

            async def verify():
                params = StdioServerParameters(command=sys.executable,
                        args=['-m', 'memory_center.service.proxy'],
                        env={**os.environ, 'MEMORY_CENTER_URL': url + '/mcp', 'MEMORY_CENTER_TOKEN': ''})
                async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
                    await session.initialize()
                    assert [tool.name for tool in (await session.list_tools()).tools] == ['mc_service_status']
                    result = await session.call_tool('mc_service_status', {})
                    assert not result.isError and result.structuredContent['ready']
                    assert result.structuredContent['schema_version'] == '5.0'
            asyncio.run(verify())
        finally:
            process.terminate()
            process.wait(timeout=15)


def test_restore_relative_directory(tmp_path, monkeypatch):
    from memory_center.service.maintenance import backup, restore
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'admin-token').write_text('test-only-backup-token')
    archive = tmp_path / 'backup.tar.gz'
    backup(data, archive)
    monkeypatch.chdir(tmp_path)
    from pathlib import Path
    restore(archive, Path('restored'))
    assert (tmp_path / 'restored' / 'admin-token').read_text() == 'test-only-backup-token'
