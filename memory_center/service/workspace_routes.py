"""项目目录管理 API；不向 MCP 暴露管理员操作。"""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from memory_center.application.workspaces import WorkspaceCatalog
from memory_center.service.admin import require_admin

Admin = Annotated[WorkspaceCatalog, Depends(require_admin)]
Root = Annotated[str, Field(min_length=1, max_length=4096)]
Name = Annotated[str, Field(min_length=1, max_length=120)]
Revision = Annotated[int, Field(ge=1, strict=True)]
WorkspaceID = Annotated[str, Field(pattern=r"^ws_[0-9a-f]{32}$")]


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root: Root
    workspace_id: WorkspaceID | None = None


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    root: Root


class UpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Revision
    name: Name | None = None
    root: Root | None = None


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: Revision


def workspace_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1/workspaces", tags=["workspace_catalog"])

    @router.post("/preview")
    def preview(body: PreviewRequest, admin: Admin):
        return admin.preview(body.root, body.workspace_id)

    @router.post("", status_code=201)
    def register(body: RegisterRequest, admin: Admin):
        return admin.register(body.name, body.root)

    @router.get("")
    def list_workspaces(admin: Admin, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                        after: Annotated[str, Query(pattern=r"^(ws_[0-9a-f]{32})?$", max_length=35)] = ""):
        return admin.store.list(limit, after)

    @router.get("/{workspace_id}")
    def get_workspace(workspace_id: WorkspaceID, admin: Admin):
        return admin.store.get(workspace_id)

    @router.patch("/{workspace_id}")
    def update(workspace_id: WorkspaceID, body: UpdateRequest, admin: Admin):
        return admin.update(workspace_id, body.revision, name=body.name, root=body.root)

    @router.post("/{workspace_id}/pause")
    def pause(workspace_id: WorkspaceID, body: StatusRequest, admin: Admin):
        return admin.set_status(workspace_id, body.revision, "paused")

    @router.post("/{workspace_id}/resume")
    def resume(workspace_id: WorkspaceID, body: StatusRequest, admin: Admin):
        return admin.set_status(workspace_id, body.revision, "active")

    @router.delete("/{workspace_id}")
    def remove(workspace_id: WorkspaceID, admin: Admin, revision: Annotated[int, Query(ge=1)]):
        return admin.set_status(workspace_id, revision, "removed")

    return router
