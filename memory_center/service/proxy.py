"""全新 5.0 stdio 客户端适配：转发至常驻 HTTP 服务，无本地 workspace。"""
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


async def run():
    url = os.environ.get('MEMORY_CENTER_URL', 'http://127.0.0.1:8765/mcp')
    token = os.environ.get('MEMORY_CENTER_TOKEN', '')
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30, read=300)) as http_client, streamable_http_client(url, http_client=http_client) as (reader, writer, _):
        async with ClientSession(reader, writer) as remote:
            await remote.initialize()
            server = Server('Memory Center 5.0 代理')

            @server.list_tools()
            async def tools():
                return (await remote.list_tools()).tools

            @server.call_tool()
            async def call(name, arguments):
                return await remote.call_tool(name, arguments)

            async with stdio_server() as (input_stream, output_stream):
                await server.run(input_stream, output_stream, server.create_initialization_options())


def main():
    asyncio.run(run())


if __name__ == '__main__':
    main()
