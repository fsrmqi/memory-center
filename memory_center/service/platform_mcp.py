"""5.0 MCP 工具目录按凭据过滤，调用再次授权；传输会话绑定主体。"""
import time
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from memory_center.core.foundation.catalog import CatalogError


class ScopedMCP(FastMCP):
    platform = None

    def actor(self):
        request = self.get_context().request_context.request
        header = request.headers.get('authorization', '') if request else ''
        token = header[7:] if header.startswith('Bearer ') else ''
        return self.platform.access.authenticate(token)

    async def list_tools(self):
        actor = self.actor()
        return [tool for tool in await super().list_tools() if tool.name in actor.tools]

    async def call_tool(self, name, arguments):
        try:
            if name not in self.actor().tools:
                raise CatalogError('FORBIDDEN', '工具不在当前凭据授权范围内')
            result = await super().call_tool(name, arguments)
            self.platform.store.audit(self.actor().id, name, arguments.get('workspace_id', ''),
                                      arguments.get('session_id', arguments.get('job_id', '')))
            return result
        except CatalogError as exc:
            raise ToolError(exc.code + '：' + exc.message) from None


def register_tools(mcp):
    def service():
        return mcp.platform

    @mcp.tool()
    def mc_workspaces() -> dict[str, Any]:
        """列出当前凭据可访问的项目，不提供管理员路径登记操作。"""
        actor = mcp.actor()
        items = []
        for workspace_id in actor.workspaces:
            try:
                workspace = service().catalog.get(workspace_id)
                items.append({key: workspace[key] for key in ['workspace_id', 'name', 'status', 'services']})
            except CatalogError:
                pass
        return {'items': items}

    @mcp.tool()
    async def mc_lookup(workspace_id: str, query: str, mode: str = 'hybrid', limit: int = 10, session_id: str = '') -> dict[str, Any]:
        """按显式项目查询：keyword/vector/hybrid/symbol/callers/callees/context，返回来源与私有引用。"""
        if len(query) > 1000 or not 1 <= limit <= 50:
            raise CatalogError('QUERY_INVALID', '查询参数超出范围')
        return await anyio.to_thread.run_sync(lambda: service().lookup(mcp.actor(), workspace_id, query, mode, limit, session_id))

    @mcp.tool()
    async def mc_analyze(workspace_id: str, target: str) -> dict[str, Any]:
        """在授权项目的代码事实图上查询影响，向量相似度不参与调用关系判定。"""
        actor = mcp.actor()
        if not target or len(target) > 1000:
            raise CatalogError('QUERY_INVALID', '目标无效')
        return await anyio.to_thread.run_sync(lambda: service().analyze(actor, workspace_id, target))

    @mcp.tool()
    def mc_start(workspace_id: str, intent: str) -> dict[str, Any]:
        """创建绑定当前主体和项目的任务会话。"""
        return service().access.start(mcp.actor(), workspace_id, intent)

    @mcp.tool()
    def mc_resume(session_id: str) -> dict[str, Any]:
        """恢复当前凭据拥有的任务会话，不能跨主体或跨项目使用。"""
        return service().access.owned(mcp.actor(), 'session', session_id)

    @mcp.tool()
    def mc_close(session_id: str, outcome: str) -> dict[str, Any]:
        """关闭当前凭据拥有的任务会话并记录结果。"""
        return service().access.close(mcp.actor(), session_id, outcome)

    @mcp.tool()
    def mc_ref(ref_id: str) -> dict[str, Any]:
        """读取当前主体拥有的来源引用；空间和来源修订必须仍有效。"""
        return service().resolve_reference(mcp.actor(), ref_id)

    @mcp.tool()
    def mc_memory_write(workspace_id: str, content: str, confirmed: bool = False) -> dict[str, Any]:
        """写入长期记忆；推断默认待确认，明确事实可声明 confirmed。"""
        actor = mcp.actor()
        service().access.scope(actor, workspace_id, True)
        if not content or len(content) > 10000:
            raise CatalogError('MEMORY_INVALID', '记忆长度需介于 1–10000')
        return service().knowledge.memory(actor.id, workspace_id, content, confirmed)

    @mcp.tool()
    def mc_wiki_write(workspace_id: str, title: str, content: str, record_id: str = '', revision: int = 0) -> dict[str, Any]:
        """创建或修订 Wiki；更新要求当前 revision，保留版本历史。"""
        actor = mcp.actor()
        service().access.scope(actor, workspace_id, True)
        if not title or len(title) > 200 or len(content) > 200000:
            raise CatalogError('WIKI_INVALID', 'Wiki 内容超出范围')
        return service().knowledge.wiki(actor.id, workspace_id, title, content, record_id,
                                         revision if record_id else None)

    @mcp.tool()
    def mc_index(workspace_id: str) -> dict[str, Any]:
        """启动授权项目的后台索引，返回持久 job_id；最多并行两个 Worker。"""
        actor = mcp.actor()
        service().access.scope(actor, workspace_id, True)
        return service().jobs.enqueue(workspace_id, actor.id)

    @mcp.tool()
    def mc_job_status(job_id: str) -> dict[str, Any]:
        """读取当前主体拥有的后台任务。"""
        return service().access.owned(mcp.actor(), 'job', job_id)

    @mcp.tool()
    def mc_job_cancel(job_id: str) -> dict[str, Any]:
        """取消当前主体的后台任务，取消 generation 不发布。"""
        actor = mcp.actor()
        job = service().access.owned(actor, 'job', job_id)
        service().access.scope(actor, job['workspace_id'], True)
        return service().jobs.cancel(job_id)


class MCPBoundary:
    def __init__(self, app, mcp):
        self.app, self.mcp = app, mcp
        self.bindings, self.rates = {}, {}

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope)
        try:
            header = request.headers.get('authorization', '')
            if header and not header.startswith('Bearer '):
                raise CatalogError('UNAUTHORIZED', '需要 Bearer 凭据')
            actor = self.mcp.platform.access.authenticate(header[7:] if header else '')
            session_id = request.headers.get('mcp-session-id')
            if session_id and self.bindings.get(session_id) != actor.id:
                raise CatalogError('FORBIDDEN', '传输会话不属于当前主体或已失效')
            window = int(time.time() / 60)
            key = actor.id
            if len(self.rates) > 1100:
                self.rates = {k: v for k, v in self.rates.items() if v[0] == window}
            old_window, count = self.rates.get(key, (window, 0))
            count = count + 1 if old_window == window else 1
            if actor.id == 'anonymous':
                rate = 120
            else:
                rate = self.mcp.platform.store.get('credential', actor.id)['rate']
            self.rates[key] = (window, count)
            if count > rate:
                return await JSONResponse({'error': {'code': 'RATE_LIMITED', 'message': '凭据请求速率已达上限'}}, 429)(scope, receive, send)
            if not session_id and len(self.bindings) >= 1000:
                return await JSONResponse({'error': {'code': 'SESSION_LIMIT', 'message': '传输会话已达上限'}}, 429)(scope, receive, send)
        except CatalogError as exc:
            status = 401 if exc.code == 'UNAUTHORIZED' else 403
            return await JSONResponse({'error': {'code': exc.code, 'message': exc.message}}, status)(scope, receive, send)

        async def bind(message):
            if message['type'] == 'http.response.start':
                headers = dict(message.get('headers', []))
                sid = headers.get(b'mcp-session-id')
                if sid and message['status'] < 400:
                    self.bindings[sid.decode()] = actor.id
                if request.method == 'DELETE' and message['status'] < 400 and session_id:
                    self.bindings.pop(session_id, None)
            await send(message)
        await self.app(scope, receive, bind)
