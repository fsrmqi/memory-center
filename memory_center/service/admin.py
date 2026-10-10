"""本机管理员令牌与管理接口访问边界。"""
import hmac
import os
import secrets
import stat
from pathlib import Path

from fastapi import HTTPException, Request
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings


def load_admin_token(data_dir: Path) -> str:
    path = data_dir / "admin-token"
    flags = getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | flags, 0o600)
    except FileExistsError:
        descriptor = None
    if descriptor is not None:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(secrets.token_hex(32))
            handle.flush()
            os.fsync(handle.fileno())
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RuntimeError("管理员令牌文件必须是普通文件，不能是软链接或特殊文件")
    with os.fdopen(os.open(path, os.O_RDONLY | flags | getattr(os, "O_NONBLOCK", 0)), "r") as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
            raise RuntimeError("管理员令牌文件必须是仅当前用户可读写的普通文件（0600）")
        token = handle.read(65)
    if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
        raise RuntimeError("管理员令牌文件格式无效，未自动替换")
    return token


async def require_admin(request: Request):
    state = request.app.state
    if not getattr(state, "catalog_ready", False):
        raise HTTPException(503, detail={"code": "SERVICE_NOT_READY", "message": "服务尚未就绪"})
    security = TransportSecurityMiddleware(TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(state.service_config.allowed_hosts),
        allowed_origins=[f"http://{host}" for host in state.service_config.allowed_hosts],
    ))
    rejection = await security.validate_request(request, is_post=request.method in {"POST", "PUT", "PATCH"})
    if rejection:
        raise HTTPException(rejection.status_code, detail={"code": "REQUEST_ORIGIN_REJECTED", "message": "请求来源、Host 或内容类型不符合管理接口要求"})
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
        raise HTTPException(403, detail={"code": "REQUEST_ORIGIN_REJECTED", "message": "管理接口写入要求同源请求"})
    if state.service_config.auth_mode == "local":
        return state.workspace_catalog
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer ") or not hmac.compare_digest(
        authorization[7:].encode(), state.admin_token.encode()
    ):
        raise HTTPException(401, detail={"code": "ADMIN_UNAUTHORIZED", "message": "需要有效的管理员令牌"},
                            headers={"WWW-Authenticate": "Bearer"})
    return state.workspace_catalog
