"""受管 Wiki 与 Skill 管理 API。"""
from typing import Any, Literal

import anyio
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from memory_center.service.admin import require_admin


class Operation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    parameters: dict[str, Any] = Field(default_factory=dict)


class ImportSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1, max_length=100)
    confirm: bool = False


def governance_router():
    router = APIRouter(prefix='/api/v1/governance', dependencies=[Depends(require_admin)], tags=['governance'])

    @router.get('')
    async def state(request: Request):
        return await anyio.to_thread.run_sync(request.app.state.platform.governance.state)

    @router.post('/import')
    async def import_source(request: Request, body: ImportSource):
        manager = request.app.state.platform.governance
        return await anyio.to_thread.run_sync(lambda: manager.import_source(body.source_id, body.confirm))

    @router.post('/{tool}')
    async def execute(request: Request, tool: Literal['assistant_knowledge', 'assistant_memory', 'assistant_skill', 'assistant_admin'], body: Operation):
        manager = request.app.state.platform.governance
        return await anyio.to_thread.run_sync(lambda: manager.call(tool, body.parameters))

    return router
