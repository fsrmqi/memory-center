"""请求正文总预算，包含分块传输，解析前拒绝超限正文。"""
from starlette.responses import JSONResponse


class BodyLimit:
    def __init__(self, app, limit=8 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST', 'PUT', 'PATCH'}:
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > self.limit:
                return await JSONResponse({'error': {'code': 'BODY_LIMIT', 'message': '请求正文不能超过 8 MiB'}}, 413)(scope, receive, send)
            messages.append(message)
            if not message.get('more_body'):
                break
        async def replay():
            return messages.pop(0) if messages else await receive()
        await self.app(scope, replay, send)
