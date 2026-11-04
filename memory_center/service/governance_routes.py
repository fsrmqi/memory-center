"""受管 Wiki 与 Skill 管理 API。"""
from typing import Any, Literal

import anyio
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from memory_center.service.admin import require_admin
from memory_center.platform.skill_discovery import SkillDiscovery


class Operation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    parameters: dict[str, Any] = Field(default_factory=dict)


class ImportSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1, max_length=100)
    confirm: bool = False


class SkillSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    root: str = Field(min_length=1, max_length=2000)
    enabled: bool = False
    max_depth: int = Field(default=4, ge=0, le=8)
    revision: int | None = Field(default=None, ge=1)


class SkillEnabled(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    revision: int = Field(ge=1)


def governance_router():
    router = APIRouter(prefix='/api/v1/governance', dependencies=[Depends(require_admin)], tags=['governance'])

    def discovery(request):
        manager = request.app.state.platform.governance
        return SkillDiscovery(manager.store, manager.base)

    @router.get('/skill-sources')
    def skill_sources(request: Request):
        manager = request.app.state.platform.governance
        return {'items': discovery(request).sources(), 'suggested_roots': [str(manager.published)]}

    @router.post('/skill-sources')
    def create_skill_source(request: Request, body: SkillSource):
        return discovery(request).configure(**body.model_dump())

    @router.patch('/skill-sources/{source_id}')
    def update_skill_source(source_id: str, request: Request, body: SkillSource):
        if body.revision is None:
            from memory_center.core.foundation.catalog import CatalogError
            raise CatalogError('REVISION_REQUIRED', '更新目录配置需要当前修订号')
        return discovery(request).configure(record_id=source_id, **body.model_dump())

    @router.delete('/skill-sources/{source_id}')
    def remove_skill_source(source_id: str, request: Request, revision: int = Query(ge=1)):
        return discovery(request).remove_source(source_id, revision)

    @router.post('/skill-sources/{source_id}/scan')
    def scan_skills(source_id: str, request: Request):
        return discovery(request).scan(source_id)

    @router.get('/discovered-skills')
    def discovered_skills(request: Request, page: int = Query(default=1, ge=1),
                          page_size: int = Query(default=20, ge=1, le=50), q: str = Query(default='', max_length=200),
                          status: Literal['', 'enabled', 'disabled', 'missing'] = '', source_id: str = Query(default='', max_length=100)):
        return discovery(request).list_page(page, page_size, q, status, source_id)

    @router.patch('/discovered-skills/{record_id}')
    def enable_skill(record_id: str, request: Request, body: SkillEnabled):
        return discovery(request).set_enabled(record_id, body.enabled, body.revision)

    @router.get('/discovered-skills/{record_id}')
    def read_skill(record_id: str, request: Request):
        return discovery(request).read(record_id)

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
