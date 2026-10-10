"""FastAPI and MCP share a single, explicitly managed ASGI lifespan."""
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryFile
from typing import TypedDict

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from mcp.server.transport_security import TransportSecuritySettings

from memory_center import __version__
from memory_center.application.workspaces import WorkspaceCatalog
from memory_center.platform.application import Platform
from memory_center.platform.database import Database, ManagedCatalog, PostgresCatalog
from memory_center.service.admin import load_admin_token
from memory_center.service.body_limit import BodyLimit
from memory_center.service.config import ServiceConfig
from memory_center.service.errors import register_catalog_errors
from memory_center.service.platform_mcp import MCPBoundary, register_tools
from memory_center.service.platform_mcp import ScopedMCP as FastMCP
from memory_center.service.platform_routes import platform_router
from memory_center.service.workspace_routes import workspace_router


class ServiceStatus(TypedDict):
    schema_version: str
    version: str
    stage: str
    ready: bool
    capabilities: list[str]
    project_management: str
    auth_mode: str


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

    mcp.service_config = config

    def status() -> ServiceStatus:
        return {
            "schema_version": "5.0",
            "version": __version__,
            "stage": "S4",
            "ready": ready,
            "capabilities": ["service_status", "workspace_catalog", "scoped_mcp", "background_index", "knowledge", "wiki", "memory", "knowledge_governance", "skill_management"],
            "project_management": "ready",
            "auth_mode": config.auth_mode,
        }

    @mcp.tool()
    def mc_service_status() -> ServiceStatus:
        """返回服务就绪状态与已实现能力，不读取项目或历史配置。"""
        return status()

    register_tools(mcp)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal ready
        if not (static_dir / "index.html").is_file():
            raise RuntimeError("管理页面资源缺失，请重新构建安装包")
        config.data_dir.mkdir(parents=True, exist_ok=True)
        with FileLock(str(config.data_dir / 'service.lock'), timeout=0):
            # Probe only the new service directory; leave no persistent probe file.
            with TemporaryFile(dir=config.data_dir) as probe:
                probe.write(b"ready")
                probe.flush()
            catalog = PostgresCatalog(config.data_dir, config.database_url) if config.database_url else ManagedCatalog(config.data_dir)
            catalog.initialize()
            app.state.admin_token = load_admin_token(config.data_dir)
            app.state.workspace_catalog = WorkspaceCatalog(catalog)
            database = Database(config.data_dir, config.database_url)
            database.initialize()
            platform = Platform(database, catalog)
            catalog.index_store = platform.store
            app.state.platform = mcp.platform = platform
            await platform.jobs.start()
            await platform.governance.start()
            try:
                async with mcp.session_manager.run():
                    app.state.catalog_ready = True
                    ready = True
                    yield
            finally:
                ready = False
                app.state.catalog_ready = False
                app.state.admin_token = ""
                await platform.governance.close()
                await platform.jobs.close()
    app = FastAPI(title="Memory Center", version=__version__, lifespan=lifespan)

    app.add_middleware(BodyLimit)
    app.state.service_config = config
    register_catalog_errors(app)
    app.include_router(workspace_router())
    app.include_router(platform_router())
    from memory_center.service.governance_routes import governance_router
    app.include_router(governance_router())

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def readiness():
        worker_ready = ready and not app.state.platform.jobs.task.done()
        return JSONResponse({"ready": worker_ready}, status_code=200 if worker_ready else 503)

    @app.get("/api/v1/service/status")
    def service_status():
        return status()

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/admin/")

    app.mount("/admin", StaticFiles(directory=static_dir, html=True, check_dir=False), name="admin")
    # Register last: SDK handles /mcp directly without mount slash redirects.
    app.mount("/", MCPBoundary(mcp_app, mcp))
    return app
