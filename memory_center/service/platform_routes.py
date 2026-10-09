"""5.0 管理页面 API：全部沿用本机管理员认证。"""
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embeddings import Embedder
from memory_center.service.admin import require_admin
from memory_center.service.workspace_routes import WorkspaceID


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CredentialInput(Input):
    name: str = Field(min_length=1, max_length=120)
    workspace_ids: list[WorkspaceID] = Field(min_length=1, max_length=100)
    writable: bool = False
    tools: list[str] | None = None
    rate: int = Field(default=60, ge=1, le=600)


class ModelInput(Input):
    url: str = Field(default='', max_length=2000)
    model: str = Field(default='', max_length=200)
    protocol: Literal['ollama', 'openai'] = 'ollama'
    dimensions: int = Field(default=1024, ge=1, le=4096)


class SearchInput(Input):
    query: str = Field(min_length=1, max_length=1000)
    mode: Literal['hybrid', 'keyword', 'vector', 'symbol', 'callers', 'callees', 'context'] = 'hybrid'
    limit: int = Field(default=10, ge=1, le=50)


class DocumentInput(Input):
    filename: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=6_000_000)
    encoding: Literal['text', 'base64'] = 'text'


class WikiInput(Input):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=200000)
    revision: int | None = Field(default=None, ge=1)
    refs: list[str] = Field(default_factory=list, max_length=100)


class MemoryInput(Input):
    content: str = Field(min_length=1, max_length=10000)
    confirmed: bool = False
    replaces: str = Field(default='', max_length=100)
    expires_at: str = Field(default='', max_length=100)


class StateInput(Input):
    revision: int = Field(ge=1)
    status: Literal['deleted', 'confirmed', 'rejected', 'pending']


class RollbackInput(Input):
    revision: int = Field(ge=1)
    target_revision: int = Field(ge=1)


class DraftInput(Input):
    title: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=1000)


def platform_router():
    router = APIRouter(prefix='/api/v1', dependencies=[Depends(require_admin)], tags=['platform'])

    def platform(request):
        return request.app.state.platform

    def scoped(request, workspace_id, write=False):
        service = platform(request)
        service.access.scope(service.administrator(), workspace_id, write)
        return service

    @router.get('/credentials')
    def credentials(request: Request):
        service = platform(request)
        return {'items': [service.access.public(item) for item in service.store.list('credential', limit=1000)]}

    @router.post('/credentials', status_code=201)
    def issue(body: CredentialInput, request: Request):
        return platform(request).access.issue(body.name, body.workspace_ids, body.writable, body.tools, body.rate)

    @router.delete('/credentials/{record_id}')
    def revoke(record_id: str, request: Request):
        service = platform(request)
        item = service.store.update('credential', record_id, {'revoked': True})
        service.store.audit('admin', 'credential.revoke', record_id=record_id)
        return service.access.public(item)

    @router.get('/models')
    def models(request: Request):
        service = platform(request)
        return {'items': service.store.list('model', limit=1), 'backend': 'postgresql' if service.store.db.url else 'sqlite'}

    @router.put('/models')
    def model(body: ModelInput, request: Request):
        return platform(request).model(body.model_dump())

    @router.post('/models/test')
    def test_model(body: ModelInput):
        settings = Embedder.validate(body.model_dump())
        if not body.url or not body.model:
            raise CatalogError('MODEL_NOT_CONFIGURED', '请先填写模型地址和名称')
        embedder = Embedder(settings)
        vector = embedder.embed(['模型连接验证'])[0]
        return {'ready': True, 'dimensions': len(vector), 'profile': embedder.profile}

    @router.get('/jobs')
    def jobs(request: Request):
        return {'items': platform(request).store.list('job', limit=1000)}

    @router.post('/workspaces/{workspace_id}/index')
    def index(workspace_id: WorkspaceID, request: Request):
        service = scoped(request, workspace_id, True)
        return service.jobs.enqueue(workspace_id, 'admin')

    @router.get('/workspaces/{workspace_id}/index')
    def index_status(workspace_id: WorkspaceID, request: Request):
        service = scoped(request, workspace_id)
        try:
            return service.store.get('index', workspace_id)
        except CatalogError:
            return {'workspace_id': workspace_id, 'status': 'not_indexed'}

    @router.post('/jobs/{job_id}/cancel')
    def cancel(job_id: str, request: Request):
        return platform(request).jobs.cancel(job_id)

    @router.post('/jobs/{job_id}/retry')
    def retry(job_id: str, request: Request):
        service = platform(request)
        job = service.store.get('job', job_id)
        if job['status'] not in {'failed', 'cancelled', 'interrupted'}:
            raise CatalogError('JOB_STATE', '仅失败、取消或中断任务可重试')
        return service.jobs.enqueue(job['workspace_id'], 'admin')

    @router.post('/workspaces/{workspace_id}/search')
    def search(workspace_id: WorkspaceID, body: SearchInput, request: Request):
        service = scoped(request, workspace_id)
        return service.lookup(service.administrator(), workspace_id, body.query, body.mode, body.limit)

    @router.post('/workspaces/{workspace_id}/analyze')
    def analyze(workspace_id: WorkspaceID, body: SearchInput, request: Request):
        service = scoped(request, workspace_id)
        return service.analyze(service.administrator(), workspace_id, body.query)

    @router.get('/workspaces/{workspace_id}/knowledge/{kind}')
    def items(workspace_id: WorkspaceID, kind: Literal['document', 'wiki', 'memory'], request: Request):
        return {'items': scoped(request, workspace_id).store.list(kind, workspace_id, limit=1000)}

    @router.post('/workspaces/{workspace_id}/documents', status_code=201)
    def document(workspace_id: WorkspaceID, body: DocumentInput, request: Request):
        service = scoped(request, workspace_id, True)
        item = service.knowledge.document(workspace_id, body.filename, body.content, body.encoding)
        service.store.audit('admin', 'document.create', workspace_id, item['id'])
        return item

    @router.post('/workspaces/{workspace_id}/wiki', status_code=201)
    def wiki(workspace_id: WorkspaceID, body: WikiInput, request: Request):
        service = scoped(request, workspace_id, True)
        service.validate_wiki_refs(service.administrator(), workspace_id, body.refs)
        return service.knowledge.wiki('admin', workspace_id, body.title, body.content, refs=body.refs)

    @router.patch('/workspaces/{workspace_id}/wiki/{record_id}')
    def edit_wiki(workspace_id: WorkspaceID, record_id: str, body: WikiInput, request: Request):
        if body.revision is None:
            raise CatalogError('REVISION_REQUIRED', '编辑页面必须提供 revision')
        service = scoped(request, workspace_id, True)
        service.validate_wiki_refs(service.administrator(), workspace_id, body.refs)
        return service.knowledge.wiki('admin', workspace_id, body.title, body.content, record_id, body.revision, body.refs)

    @router.post('/workspaces/{workspace_id}/wiki/{record_id}/rollback')
    def rollback(workspace_id: WorkspaceID, record_id: str, body: RollbackInput, request: Request):
        service = scoped(request, workspace_id, True)
        return service.knowledge.rollback('admin', workspace_id, record_id, body.revision, body.target_revision)

    @router.post('/workspaces/{workspace_id}/wiki-draft')
    def draft(workspace_id: WorkspaceID, body: DraftInput, request: Request):
        service = scoped(request, workspace_id)
        return service.wiki_draft(service.administrator(), workspace_id, body.title, body.query)

    @router.post('/workspaces/{workspace_id}/memories', status_code=201)
    def memory(workspace_id: WorkspaceID, body: MemoryInput, request: Request):
        service = scoped(request, workspace_id, True)
        return service.knowledge.memory('admin', workspace_id, **body.model_dump())

    @router.patch('/workspaces/{workspace_id}/knowledge/{kind}/{record_id}')
    def state(workspace_id: WorkspaceID, kind: Literal['document', 'wiki', 'memory'], record_id: str,
              body: StateInput, request: Request):
        service = scoped(request, workspace_id, True)
        item = service.store.get(kind, record_id)
        if item['workspace_id'] != workspace_id or (kind != 'memory' and body.status != 'deleted'):
            raise CatalogError('FORBIDDEN', '记录范围或状态变更不合法')
        result = service.store.update(kind, record_id, {'status': body.status}, body.revision)
        service.store.audit('admin', kind + '.state', workspace_id, record_id)
        return result

    @router.get('/audit')
    def audit(request: Request):
        return {'items': platform(request).store.list('audit', limit=200)}

    return router
