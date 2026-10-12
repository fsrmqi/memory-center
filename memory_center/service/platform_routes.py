"""5.0 管理页面 API：全部沿用本机管理员认证。"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embeddings import Embedder
from memory_center.platform.intelligence import ChatModel, Intelligence
from memory_center.platform.reranking import Reranker
from memory_center.platform.storage_usage import workspace_storage
from memory_center.platform.storage_maintenance import StorageMaintenance
from memory_center.platform.project_embedding import ProjectEmbedding
from memory_center.service.admin import require_admin
from memory_center.service.workspace_routes import WorkspaceID


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StoragePolicyInput(Input):
    keep_history: int = Field(ge=0, le=100, strict=True)
    revision: int = Field(ge=0)


class StoragePreviewInput(Input):
    clear_parse_cache: bool = False
    clear_embedding_cache: bool = False


class StorageApplyInput(Input):
    preview_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    confirm: bool = False


class SourceSyncInput(Input):
    enabled: bool
    interval_seconds: int = Field(default=120, ge=10, le=86400)
    debounce_seconds: int = Field(default=10, ge=1, le=3600)
    revision: int = Field(ge=0)


class CredentialInput(Input):
    name: str = Field(min_length=1, max_length=120)
    workspace_ids: list[WorkspaceID] = Field(min_length=1, max_length=100)
    writable: bool = False
    tools: list[str] | None = None
    rate: int = Field(default=60, ge=1, le=600)


class WikiSourceInput(Input):
    name: str = Field(min_length=1, max_length=120)
    root: str = Field(min_length=1, max_length=2000)
    workspace_ids: list[WorkspaceID] = Field(default_factory=list, max_length=100)
    status: Literal['active', 'paused'] = 'active'
    auto_sync: bool = True
    revision: int | None = Field(default=None, ge=1)


class ModelInput(Input):
    url: str = Field(default='', max_length=2000)
    model: str = Field(default='', max_length=200)
    protocol: Literal['ollama', 'openai'] = 'ollama'
    dimensions: int = Field(default=1024, ge=1, le=4096)


class ChatModelInput(Input):
    url: str = Field(default='', max_length=2000)
    model: str = Field(default='', max_length=200)
    protocol: Literal['ollama', 'openai'] = 'ollama'
    max_tokens: int = Field(default=4096, ge=256, le=32768)


class RerankInput(Input):
    enabled: bool = False
    url: str = Field(default='', max_length=2000)
    model: str = Field(default='', max_length=200)


class CaptureSettingsInput(Input):
    enabled: bool = False


class CaptureInput(Input):
    source_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=10000)


class KnowledgeTaskInput(Input):
    kind: Literal['wiki', 'memory', 'refresh']
    operation: Literal['organize', 'governance'] = 'organize'
    pair_limit: int = Field(default=500, ge=1, le=5000)


class GovernanceDecisionInput(Input):
    revision: int = Field(ge=1)
    decision: Literal['merge', 'keep_both', 'dismiss']
    confirm: bool = False
    title: str = Field(default='', max_length=200)
    content: str = Field(default='', max_length=200000)
    retire_source_ids: list[str] = Field(default_factory=list, max_length=2)
    confirm_memory: bool = False


class OrganizeInput(Input):
    kind: Literal['wiki', 'memory']
    record_ids: list[str] = Field(min_length=1, max_length=50)


class ApplyOrganizeInput(Input):
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=200000)


class JobSettingsInput(Input):
    max_projects: int = Field(ge=1, le=64)
    max_queued: int = Field(default=0, ge=0, le=100000)
    # 0 = 按 CPU 预算在并发项目间自动切分；正数 = 每项目固定文件级 worker 数。
    max_file_workers: int = Field(default=0, ge=0, le=64)


class AnalysisSettingsInput(Input):
    engine: Literal['auto', 'generic', 'java'] = 'auto'
    revision: int = Field(ge=0)


class EmbeddingSettingsInput(Input):
    mode: Literal['inherit', 'all', 'knowledge', 'off'] = 'inherit'
    revision: int = Field(ge=0)


class SearchInput(Input):
    query: str = Field(min_length=1, max_length=1000)
    mode: Literal['hybrid', 'keyword', 'vector', 'symbol', 'callers', 'callees', 'context'] = 'hybrid'
    limit: int = Field(default=10, ge=1, le=50)


class EvaluationCase(Input):
    query: str = Field(min_length=1, max_length=1000)
    expected_sources: list[str] = Field(min_length=1, max_length=100)
    mode: Literal['keyword', 'vector', 'hybrid'] = 'hybrid'


class EvaluationInput(Input):
    cases: list[EvaluationCase] = Field(min_length=1, max_length=100)
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

    @router.get('/workspaces/{workspace_id}/sync-settings')
    def source_sync_settings(workspace_id: WorkspaceID, request: Request):
        service = scoped(request, workspace_id)
        return service.jobs.source_sync.settings(workspace_id)

    @router.put('/workspaces/{workspace_id}/sync-settings')
    def configure_source_sync(workspace_id: WorkspaceID, value: SourceSyncInput, request: Request):
        service = scoped(request, workspace_id, True)
        return service.jobs.source_sync.configure(workspace_id, value.model_dump(exclude={'revision'}), value.revision)

    @router.get('/workspaces/{workspace_id}/sync-status')
    def source_sync_status(workspace_id: WorkspaceID, request: Request):
        service = scoped(request, workspace_id)
        return service.jobs.source_sync.state(workspace_id)

    @router.post('/workspaces/{workspace_id}/sync-check')
    def source_sync_check(workspace_id: WorkspaceID, request: Request):
        service = scoped(request, workspace_id, True)
        return service.jobs.source_sync.check(workspace_id, manual=True)

    @router.get('/workspaces/{workspace_id}/knowledge-index-status')
    def knowledge_freshness(workspace_id: WorkspaceID, request: Request,
                            kind: Literal['wiki','memory','document',''] = '',
                            page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50)):
        service = scoped(request, workspace_id)
        from memory_center.platform.project_sync import knowledge_index_status
        return knowledge_index_status(service, workspace_id, kind, page, page_size)

    @router.get('/workspaces/{workspace_id}/storage')
    def storage_usage(workspace_id: WorkspaceID, request: Request):
        return workspace_storage(scoped(request, workspace_id).store, workspace_id)

    @router.get('/workspaces/{workspace_id}/storage-policy')
    def storage_policy(workspace_id: WorkspaceID, request: Request):
        return StorageMaintenance(scoped(request, workspace_id)).settings(workspace_id)

    @router.put('/workspaces/{workspace_id}/storage-policy')
    def configure_storage(workspace_id: WorkspaceID, body: StoragePolicyInput, request: Request):
        return StorageMaintenance(scoped(request, workspace_id, True)).configure(workspace_id, body.keep_history, body.revision)

    @router.post('/workspaces/{workspace_id}/storage-cleanup/preview')
    def preview_storage(workspace_id: WorkspaceID, body: StoragePreviewInput, request: Request):
        return StorageMaintenance(scoped(request, workspace_id, True)).preview(workspace_id, **body.model_dump())

    @router.post('/workspaces/{workspace_id}/storage-cleanup/apply')
    def apply_storage(workspace_id: WorkspaceID, body: StorageApplyInput, request: Request):
        return StorageMaintenance(scoped(request, workspace_id, True)).apply(workspace_id, **body.model_dump())

    @router.get('/wiki-sources')
    def wiki_sources(request: Request):
        return {'items': [s for s in platform(request).wiki_sources.sources() if s['status'] != 'deleted']}

    @router.post('/wiki-sources', status_code=201)
    def create_wiki_source(body: WikiSourceInput, request: Request):
        return platform(request).wiki_sources.save(**body.model_dump(exclude={'revision'}))

    @router.patch('/wiki-sources/{record_id}')
    def edit_wiki_source(record_id: str, body: WikiSourceInput, request: Request):
        if body.revision is None:
            raise CatalogError('REVISION_REQUIRED', '修改 Wiki 来源必须提供 revision')
        return platform(request).wiki_sources.save(record_id=record_id, **body.model_dump())

    @router.delete('/wiki-sources/{record_id}')
    def remove_wiki_source(record_id: str, request: Request):
        return platform(request).wiki_sources.remove(record_id)

    @router.post('/wiki-sources/{record_id}/sync')
    def sync_wiki_source(record_id: str, request: Request):
        service = platform(request)
        result = service.wiki_sources.sync(record_id)
        jobs = []
        for workspace_id in result['workspace_ids']:
            if service.catalog.get(workspace_id)['status'] == 'active':
                jobs.append(service.jobs.enqueue(workspace_id, 'admin'))
        return dict(result, jobs=jobs)

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

    @router.get('/rerank-model')
    def rerank_model(request: Request):
        return {'items': platform(request).store.list('rerank_model', limit=1)}

    @router.put('/rerank-model')
    def configure_rerank(body: RerankInput, request: Request):
        service = platform(request)
        value = Reranker.validate(body.model_dump())
        with service.store.generation_lock('rerank_model'):
            current = service.store.list('rerank_model', limit=1)
            return (service.store.update('rerank_model', current[0]['id'], value) if current else
                    service.store.create('rerank_model', value))

    @router.get('/knowledge-tasks')
    def knowledge_tasks(request: Request, page: int = Query(default=1, ge=1),
                        page_size: int = Query(default=10, ge=1, le=50), q: str = Query(default='', max_length=200), status: str = Query(default='', max_length=30),
                        workspace_id: str = Query(default='', max_length=100)):
        return platform(request).store.list_page('knowledge_task', page, page_size, q, status,
                                                 ('id', 'workspace_id'), workspace_id or None)

    @router.post('/workspaces/{workspace_id}/knowledge-tasks')
    def enqueue_knowledge(workspace_id: WorkspaceID, body: KnowledgeTaskInput, request: Request):
        return scoped(request, workspace_id, True).knowledge_tasks.enqueue(workspace_id, body.kind, body.operation, body.pair_limit)

    @router.post('/knowledge-tasks/{task_id}/cancel')
    def cancel_knowledge(task_id: str, request: Request):
        return platform(request).knowledge_tasks.cancel(task_id)

    @router.post('/knowledge-tasks/{task_id}/retry')
    def retry_knowledge(task_id: str, request: Request):
        service = platform(request)
        task = service.store.get('knowledge_task', task_id)
        if task['status'] not in {'failed', 'cancelled', 'interrupted'}:
            raise CatalogError('JOB_STATE', '仅停止的任务可手动重试')
        return service.knowledge_tasks.enqueue(task['workspace_id'], task['kind'], task.get('operation', 'organize'), task.get('pair_limit', 500))

    @router.get('/workspaces/{workspace_id}/knowledge-governance')
    def governance_suggestions(workspace_id: WorkspaceID, request: Request,
                               page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=50),
                               kind: Literal['wiki', 'memory'] = 'wiki', status: Literal['', 'pending', 'merged', 'kept', 'dismissed'] = 'pending',
                               category: Literal['', 'duplicate', 'conflict'] = ''):
        from memory_center.platform.knowledge_governance import KnowledgeGovernance
        return KnowledgeGovernance(scoped(request, workspace_id)).list_page(workspace_id, kind, page, page_size, status, category)

    @router.get('/workspaces/{workspace_id}/knowledge-governance/latest')
    def governance_latest(workspace_id: WorkspaceID, request: Request, kind: Literal['wiki', 'memory'] = 'wiki'):
        service = scoped(request, workspace_id)
        field = lambda n: f"payload::jsonb->>'{n}'" if service.store.db.url else f"json_extract(payload,'$.{n}')"
        with service.store.db.connection() as connection:
            row = connection.execute(f"SELECT payload FROM records WHERE kind='knowledge_task' AND workspace_id=? AND {field('operation')}='governance' AND {field('kind')}=? ORDER BY {field('created_at')} DESC,id DESC LIMIT 1",
                                     (workspace_id, kind)).fetchone()
        return {'task': json.loads(row[0]) if row else None}

    @router.post('/workspaces/{workspace_id}/knowledge-governance/{preview_id}/decision')
    def governance_decision(workspace_id: WorkspaceID, preview_id: str, body: GovernanceDecisionInput, request: Request):
        from memory_center.platform.knowledge_governance import KnowledgeGovernance
        return KnowledgeGovernance(scoped(request, workspace_id, True)).decide(workspace_id, preview_id, **body.model_dump())

    @router.get('/workspaces/{workspace_id}/knowledge-governance/{preview_id}')
    def governance_preview(workspace_id: WorkspaceID, preview_id: str, request: Request):
        from memory_center.platform.knowledge_governance import KnowledgeGovernance
        return KnowledgeGovernance(scoped(request, workspace_id)).read(workspace_id, preview_id)

    @router.get('/knowledge-tasks/{task_id}')
    def knowledge_task(task_id: str, request: Request):
        return platform(request).store.get('knowledge_task', task_id)

    @router.get('/workspaces/{workspace_id}/organize/{preview_id}')
    def organize_preview(workspace_id: WorkspaceID, preview_id: str, request: Request):
        service = scoped(request, workspace_id)
        preview = service.store.get('intelligence_preview', preview_id)
        if preview['workspace_id'] != workspace_id:
            raise CatalogError('FORBIDDEN', '预览不属于当前项目')
        return preview

    @router.get('/workspaces/{workspace_id}/capture-settings')
    def capture_settings(workspace_id: WorkspaceID, request: Request):
        service = scoped(request, workspace_id)
        values = service.store.list('capture_settings', workspace_id, limit=1)
        return values[0] if values else {'enabled': False}

    @router.put('/workspaces/{workspace_id}/capture-settings')
    def configure_capture(workspace_id: WorkspaceID, body: CaptureSettingsInput, request: Request):
        service = scoped(request, workspace_id, True)
        with service.store.generation_lock(workspace_id):
            values = service.store.list('capture_settings', workspace_id, limit=1)
            return (service.store.update('capture_settings', values[0]['id'], body.model_dump()) if values else
                    service.store.create('capture_settings', {'workspace_id': workspace_id, **body.model_dump()}))

    @router.post('/workspaces/{workspace_id}/session-candidates')
    def capture_candidate(workspace_id: WorkspaceID, body: CaptureInput, request: Request):
        return scoped(request, workspace_id, True).knowledge_tasks.capture(workspace_id, body.source_id, body.content)

    @router.get('/models')
    def models(request: Request):
        service = platform(request)
        return {'items': service.store.list('model', limit=1), 'backend': 'postgresql' if service.store.db.url else 'sqlite'}

    @router.get('/chat-model')
    def chat_model(request: Request):
        return {'items': platform(request).store.list('chat_model', limit=1)}

    @router.put('/chat-model')
    def configure_chat(body: ChatModelInput, request: Request):
        service = platform(request)
        value = ChatModel.validate(body.model_dump())
        current = service.store.list('chat_model', limit=1)
        result = (service.store.update('chat_model', current[0]['id'], value, current[0]['revision']) if current else
                  service.store.create('chat_model', value))
        service.store.audit('admin', 'chat_model.update')
        return result

    @router.post('/chat-model/test')
    def test_chat(body: ChatModelInput):
        text = ChatModel(body.model_dump()).generate('仅返回：连接成功')
        return {'ready': True, 'response': text[:200]}

    @router.get('/job-settings')
    def job_settings(request: Request):
        return platform(request).jobs.settings()

    @router.put('/job-settings')
    def configure_jobs(body: JobSettingsInput, request: Request):
        return platform(request).jobs.configure(body.model_dump())

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

    @router.get('/workspaces/{workspace_id}/analysis-settings')
    def analysis_settings(workspace_id: WorkspaceID, request: Request):
        service = platform(request)
        return service.analysis_settings(service.administrator(), workspace_id)

    @router.get('/workspaces/{workspace_id}/embedding-settings')
    def embedding_settings(workspace_id: WorkspaceID, request: Request):
        return ProjectEmbedding(scoped(request, workspace_id)).settings(workspace_id)

    @router.put('/workspaces/{workspace_id}/embedding-settings')
    def configure_embedding(workspace_id: WorkspaceID, body: EmbeddingSettingsInput, request: Request):
        return ProjectEmbedding(scoped(request, workspace_id, True)).configure(workspace_id, body.mode, body.revision)

    @router.put('/workspaces/{workspace_id}/analysis-settings')
    def configure_analysis(workspace_id: WorkspaceID, body: AnalysisSettingsInput, request: Request):
        service = platform(request)
        return service.configure_analysis(service.administrator(), workspace_id, body.engine, body.revision)

    @router.get('/jobs')
    def jobs(request: Request, page: int | None = Query(default=None, ge=1),
             page_size: int = Query(default=20, ge=1, le=50), q: str = Query(default='', max_length=200),
             status: Literal['', 'queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted'] = '',
             workspace_id: str = Query(default='', max_length=100)):
        if page is not None:
            return platform(request).store.list_page('job', page, page_size, q, status,
                                                     ('id', 'workspace_id'), workspace_id or None)
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

    @router.delete('/jobs/{job_id}')
    def remove_job(job_id: str, request: Request):
        return platform(request).jobs.remove(job_id)

    @router.post('/jobs/prune')
    def prune_jobs(request: Request):
        return platform(request).jobs.prune()

    @router.post('/workspaces/{workspace_id}/prune-index')
    def prune_workspace_index(workspace_id: WorkspaceID, request: Request):
        service = scoped(request, workspace_id, True)
        return service.jobs.prune(workspace_id)

    @router.post('/workspaces/{workspace_id}/search')
    def search(workspace_id: WorkspaceID, body: SearchInput, request: Request):
        service = scoped(request, workspace_id)
        return service.lookup(service.administrator(), workspace_id, body.query, body.mode, body.limit)

    @router.post('/workspaces/{workspace_id}/retrieval-evaluation')
    def evaluate_retrieval(workspace_id: WorkspaceID, body: EvaluationInput, request: Request):
        from memory_center.platform.evaluation import evaluate
        service = scoped(request, workspace_id)
        return evaluate(service, service.administrator(), workspace_id,
                        [c.model_dump() for c in body.cases], body.limit)

    @router.post('/workspaces/{workspace_id}/analyze')
    def analyze(workspace_id: WorkspaceID, body: SearchInput, request: Request):
        service = scoped(request, workspace_id)
        return service.analyze(service.administrator(), workspace_id, body.query)

    @router.get('/workspaces/{workspace_id}/knowledge/{kind}')
    def items(workspace_id: WorkspaceID, kind: Literal['document', 'wiki', 'memory'], request: Request,
              page: int | None = Query(default=None, ge=1), page_size: int = Query(default=20, ge=1, le=50),
              q: str = Query(default='', max_length=200),
              status: Literal['', 'active', 'pending', 'confirmed', 'rejected', 'deleted'] = ''):
        service = scoped(request, workspace_id)
        if page is not None:
            return service.knowledge.list_page(workspace_id, kind, page, page_size, q, status)
        values = service.store.list(kind, workspace_id, limit=1000)
        if kind == 'wiki':
            values.extend(service.wiki_sources.pages(workspace_id))
        return {'items': values}

    @router.post('/workspaces/{workspace_id}/documents', status_code=201)
    def document(workspace_id: WorkspaceID, body: DocumentInput, request: Request):
        service = scoped(request, workspace_id, True)
        item = service.knowledge.document(workspace_id, body.filename, body.content, body.encoding)
        service.store.audit('admin', 'document.create', workspace_id, item['id'])
        return item

    @router.post('/workspaces/{workspace_id}/organize')
    def organize(workspace_id: WorkspaceID, body: OrganizeInput, request: Request):
        service = scoped(request, workspace_id)
        return Intelligence(service).preview(workspace_id, body.kind, body.record_ids)

    @router.post('/workspaces/{workspace_id}/organize/{preview_id}/apply')
    def apply_organize(workspace_id: WorkspaceID, preview_id: str, body: ApplyOrganizeInput, request: Request):
        service = scoped(request, workspace_id, True)
        draft = service.store.get('intelligence_preview', preview_id)
        if draft['kind'] == 'memory' and len(body.content) > 10000:
            raise CatalogError('MEMORY_LIMIT', '长期记忆最多 10000 字符，请拆分或保存为 Wiki')
        return Intelligence(service).apply(workspace_id, preview_id, body.revision, body.title, body.content)

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
        if item.get('readonly'):
            raise CatalogError('WIKI_READ_ONLY', '目录接入页面只读，请管理对应 Wiki 来源')
        if item['workspace_id'] != workspace_id or (kind != 'memory' and body.status != 'deleted'):
            raise CatalogError('FORBIDDEN', '记录范围或状态变更不合法')
        result = service.store.update(kind, record_id, {'status': body.status}, body.revision)
        service.store.audit('admin', kind + '.state', workspace_id, record_id)
        return result

    @router.get('/call-traces')
    def call_traces(request: Request, page: int = Query(1,ge=1), page_size: int = Query(20,ge=1,le=50),
                    tool: str = Query('',max_length=200), status: Literal['','running','succeeded','failed','rejected','cancelled','interrupted'] = '',
                    workspace_id: str = Query('',max_length=100), actor: str = Query('',max_length=200), client: str = Query('',max_length=200),
                    start: str = Query('',max_length=40), end: str = Query('',max_length=40), trace_id: str = Query('',max_length=100)):
        filters=trace_filters(tool,status,workspace_id,actor,client,start,end,trace_id)
        return platform(request).call_traces.list_page(page,page_size,**filters)

    def trace_filters(tool,status,workspace_id,actor,client,start,end,trace_id):
        from datetime import datetime,timezone
        result=dict(tool=tool,status=status,workspace_id=workspace_id,actor=actor,client=client,trace_id=trace_id)
        for key,value in [('start',start),('end',end)]:
            if value:
                try:
                    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
                    if stamp.tzinfo is None:raise ValueError()
                    result[key]=stamp.astimezone(timezone.utc).isoformat()
                except ValueError:raise CatalogError('TIME_INVALID','时间筛选须包含时区')
        if result.get('start') and result.get('end') and result['start']>result['end']:
            raise CatalogError('TIME_INVALID','结束时间不能早于开始时间')
        return result

    @router.get('/call-traces/statistics')
    def trace_statistics(request: Request, tool: str = Query('',max_length=200),
                         status: Literal['','running','succeeded','failed','rejected','cancelled','interrupted'] = '',
                         workspace_id: str = Query('',max_length=100), actor: str = Query('',max_length=200), client: str = Query('',max_length=200),
                         start: str = Query('',max_length=40), end: str = Query('',max_length=40), trace_id: str = Query('',max_length=100)):
        return platform(request).call_traces.statistics(**trace_filters(tool,status,workspace_id,actor,client,start,end,trace_id))

    @router.get('/call-traces/{trace_id}')
    def trace_detail(trace_id: str, request: Request):
        return platform(request).call_traces.detail(trace_id)

    @router.get('/audit')
    def audit(request: Request):
        return {'items': platform(request).store.list('audit', limit=200)}

    return router
