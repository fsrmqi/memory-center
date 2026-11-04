"""管理 API 的可行动错误；不回显请求正文、令牌或底层 SQL。"""
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from memory_center.core.foundation.catalog import CatalogError

_NOT_FOUND = {"ROOT_NOT_FOUND", "WORKSPACE_NOT_FOUND"}
_CONFLICT = {"NAME_CONFLICT", "ROOT_DUPLICATE", "ROOT_OVERLAP", "REVISION_CONFLICT",
             "ROOT_CHANGE_REQUIRES_PAUSE", "ROOT_CHANGED", "CATALOG_LIMIT"}


def register_catalog_errors(app: FastAPI):
    @app.exception_handler(CatalogError)
    async def catalog_error(request: Request, exc: CatalogError):
        status = 404 if exc.code in _NOT_FOUND else 409 if exc.code in _CONFLICT else 422
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=status)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
        return JSONResponse({"error": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "请检查字段、参数类型或范围"}}, status_code=422)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request: Request, exc: sqlite3.Error):
        return JSONResponse({"error": {"code": "CATALOG_STORAGE_ERROR", "message": "项目目录暂时无法访问，请稍后重试并检查服务日志"}}, status_code=503)
