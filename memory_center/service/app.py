"""FastAPI and MCP share a single, explicitly managed ASGI lifespan."""
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryFile
from typing import TypedDict

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from memory_center import __version__
from memory_center.application.workspaces import WorkspaceCatalog
from memory_center.core.storage.catalog import CatalogStore
from memory_center.service.admin import load_admin_token
from memory_center.service.config import ServiceConfig
from memory_center.service.errors import register_catalog_errors
from memory_center.service.workspace_routes import workspace_router


class ServiceStatus(TypedDict):
    schema_version: str
    version: str
    stage: str
    ready: bool
    capabilities: list[str]
    project_management: str


def create_service_app(config: ServiceConfig, *, static_dir: Path | None = None) -> FastAPI:
    static_dir = static_dir or Path(__file__).parent / "static"
    ready = False
    mcp = FastMCP(
        "Memory Center 5.0",
        stateless_http=False,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(config.allowed_hosts),
            allowed_origins=[f"http://{host}" for host in config.allowed_hosts],
        ),
    )

    def status() -> ServiceStatus:
        return {
            "schema_version": "5.0",
            "version": __version__,
            "stage": "S1",
            "ready": ready,
            "capabilities": ["service_status", "workspace_catalog"],
            "project_management": "api_ready",
        }

    @mcp.tool()
    def mc_service_status() -> ServiceStatus:
        """返回服务就绪状态与已实现能力，不读取项目或历史配置。"""
        return status()

    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal ready
        if not (static_dir / "index.html").is_file():
            raise RuntimeError("管理页面资源缺失，请重新构建安装包")
        config.data_dir.mkdir(parents=True, exist_ok=True)
        # Probe only the new service directory; leave no persistent probe file.
        with TemporaryFile(dir=config.data_dir) as probe:
            probe.write(b"ready")
            probe.flush()
        catalog = CatalogStore(config.data_dir)
        catalog.initialize()
        app.state.admin_token = load_admin_token(config.data_dir)
        app.state.workspace_catalog = WorkspaceCatalog(catalog)
        async with mcp.session_manager.run():
            app.state.catalog_ready = True
            ready = True
            try:
                yield
            finally:
                ready = False
                app.state.catalog_ready = False
                app.state.admin_token = ""

    app = FastAPI(title="Memory Center", version=__version__, lifespan=lifespan)

    app.state.service_config = config
    register_catalog_errors(app)
    app.include_router(workspace_router())

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def readiness():
        return JSONResponse({"ready": ready}, status_code=200 if ready else 503)

    @app.get("/api/v1/service/status")
    def service_status():
        return status()

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/admin/")

    app.mount("/admin", StaticFiles(directory=static_dir, html=True, check_dir=False), name="admin")
    # Register last: SDK handles /mcp directly without mount slash redirects.
    app.mount("/", mcp_app)
    return app
