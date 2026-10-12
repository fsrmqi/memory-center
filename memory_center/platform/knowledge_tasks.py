"""全库知识整理与受控会话候选；后台只创建预览，不自动发布。"""
import asyncio
import hashlib
import json
import threading

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.diagnostics import failure_receipt
from memory_center.platform.intelligence import Intelligence
from memory_center.platform.store import now
from datetime import datetime, timedelta, timezone


class KnowledgeTasks:
    def __init__(self, platform):
        self.platform, self.store = platform, platform.store
        self.stopping = False
        self.runner = None
        self.lock = threading.RLock()

    def enqueue(self, workspace_id, kind, operation='organize', pair_limit=500):
        self.platform.catalog.get(workspace_id)
        if kind == 'refresh':
            if operation != 'organize':
                raise CatalogError('CONTENT_KIND_INVALID', '知识刷新不支持智能治理')
            return self.enqueue_refresh(workspace_id)
        if kind not in {'wiki', 'memory'}:
            raise CatalogError('CONTENT_KIND_INVALID', '请选择 Wiki 或记忆')
        with self.lock:
            for task in self.store.list_page('knowledge_task', page_size=50, status='running', workspace_id=workspace_id)['items'] + self.store.list_page('knowledge_task', page_size=50, status='queued', workspace_id=workspace_id)['items']:
                if task['kind'] == kind and task.get('operation', 'organize') == operation and task['status'] in {'queued', 'running'}:
                    return task
            scopes = [workspace_id]
            if kind == 'wiki':
                scopes.extend(s['id'] for s in self.platform.wiki_sources.sources()
                              if s['status'] == 'active' and workspace_id in s['workspace_ids'])
            def field(name):
                return f"payload::jsonb->>'{name}'" if self.store.db.url else f"json_extract(payload,'$.{name}')"
            with self.store.db.connection() as connection:
                rows = connection.execute(f"SELECT id,{field('revision')} AS source_revision,{field('status')} AS source_status FROM records WHERE kind=? AND workspace_id IN ({','.join('?' for _ in scopes)}) ORDER BY id",
                                          (kind, *scopes)).fetchall()
            snapshots = [{'id': r[0], 'revision': int(r[1])} for r in rows if r[2] not in {'deleted', 'rejected'}]
            if not snapshots:
                raise CatalogError('CONTENT_EMPTY', '没有可整理的内容')
            return self.store.create('knowledge_task', {'workspace_id': workspace_id, 'kind': kind,
                'status': 'queued', 'sources': snapshots, 'completed': 0, 'total': len(snapshots),
                'operation': operation, 'pair_limit': pair_limit,
                'preview_ids': [], 'duplicate_groups': [], 'requires_review': True})

    def cancel(self, task_id):
        with self.lock:
            task = self.store.get('knowledge_task', task_id)
            if task['status'] in {'queued', 'running'}:
                task = self.store.update('knowledge_task', task_id, {'status': 'cancelled', 'finished_at': now()})
            return task

    def enqueue_refresh(self, workspace_id, automatic=False):
        self.platform.catalog.get(workspace_id)
        with self.lock:
            # Last attempt is durable, including cancellation and deletion of source files.
            attempt = self.store.list('knowledge_refresh_attempt', workspace_id, limit=1)
            if automatic and attempt:
                previous = self.store.get('knowledge_task', attempt[0]['task_id'])
                if previous['status'] != 'succeeded':
                    return previous
            for status in ('queued', 'running'):
                for task in self.store.list_page('knowledge_task', page_size=50, status=status,
                                                 workspace_id=workspace_id)['items']:
                    if task['kind'] == 'refresh':
                        return task
            index = self.store.get('index', workspace_id)
            task = self.store.create('knowledge_task', {'workspace_id': workspace_id, 'kind': 'refresh',
                'status': 'queued', 'generation': index['generation'], 'completed': 0, 'total': 0,
                'preview_ids': [], 'requires_review': False})
            if attempt:
                self.store.update('knowledge_refresh_attempt', attempt[0]['id'], {'task_id': task['id']})
            else:
                self.store.create('knowledge_refresh_attempt', {'workspace_id': workspace_id, 'task_id': task['id']})
            return task

    def run_refresh(self, task_id):
        from collections import Counter
        from memory_center.platform.embeddings import Embedder, EmbeddingCancelled
        from memory_center.platform.jobs import split_text
        from memory_center.platform.retrieval import tokens
        task = self.store.get('knowledge_task', task_id)
        workspace_id = task['workspace_id']
        with self.lock:
            if task['status'] != 'queued':
                return
            self.store.update('knowledge_task', task_id, {'status': 'running', 'started_at': now()})
        def stopped():
            return self.stopping or self.store.get('knowledge_task', task_id)['status'] != 'running'
        try:
            workspace = self.platform.catalog.get(workspace_id)
            index = self.store.get('index', workspace_id)
            if index['generation'] != task['generation'] or index['config_version'] != workspace['config_version']:
                raise CatalogError('INDEX_STALE', '源码索引已变化，请重新提交知识刷新')
            signature = self.platform.wiki_sources.signature(workspace_id)
            sources = self.platform.knowledge.active(workspace_id)
            if any(item.get('wiki_source_id') and not self.platform.wiki_sources.fresh(item) for _, item in sources):
                raise CatalogError('WIKI_CHANGED', 'Wiki 文件已变化，请先同步来源再刷新知识')
            snapshots = [(kind, item['id'], item['revision']) for kind, item in sources]
            chunks = []
            for kind, item in sources:
                metadata = {'kind': kind, 'source_id': item['id'], 'source_revision': item['revision'],
                            'title': item['title'], 'owner': item.get('owner', '')}
                if item.get('wiki_source_id'):
                    metadata.update({k: item[k] for k in ('wiki_source_id', 'relative_path', 'hash', 'source_name')})
                    metadata['path'] = item['source_name'] + '/' + item['relative_path']
                chunks.extend(split_text(item['content'], metadata))
            settings = self.store.list('model', limit=1)
            embedder = Embedder(settings[0] if settings else {})
            from memory_center.platform.project_embedding import embedding_settings, effective_embedding_mode
            project_settings = embedding_settings(self.store, workspace_id)
            embedding_mode = effective_embedding_mode(project_settings, embedder.enabled)
            profile = embedder.profile if embedding_mode != 'off' else ''
            if embedding_mode != 'off' and profile != index['embedding_profile']:
                raise CatalogError('INDEX_STALE', '向量模型已改变，请先重新建立完整索引')
            self.store.update('knowledge_task', task_id, {'total': len(chunks),
                              'phase': 'embedding' if embedding_mode != 'off' else 'keyword', 'embedding_mode': embedding_mode})
            completed = 0
            def progress(count):
                nonlocal completed
                completed += count
                self.store.update('knowledge_task', task_id, {'completed': completed})
            vectors = (embedder.embed_many([c['content'] for c in chunks], should_stop=stopped, on_batch=progress)
                       if embedding_mode != 'off' else [[] for _ in chunks])
            self.store.update('knowledge_task', task_id, {'model_metrics': dict(embedder.metrics)})
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.update(profile=profile, embedding=vector)
                chunk['metadata']['length'] = len(tokens(chunk['content']))
            # Knowledge and code share a retrieval generation; replace only knowledge rows atomically.
            with self.lock, self.store.generation_lock(workspace_id), self.store.db.connection(True) as connection:
                if stopped():
                    return
                current = self.store.get('index', workspace_id)
                fresh = [(kind, item['id'], item['revision']) for kind, item in self.platform.knowledge.active(workspace_id)]
                if (current['generation'] != task['generation'] or fresh != snapshots or
                    embedding_settings(self.store, workspace_id)['revision'] != project_settings['revision'] or
                    self.platform.catalog.get(workspace_id)['config_version'] != workspace['config_version'] or
                    signature != self.platform.wiki_sources.signature(workspace_id)):
                    raise CatalogError('REVISION_CONFLICT', '来源或源码索引已变化，未发布知识刷新')
                field = "metadata::jsonb->>'kind'" if self.store.db.url else "json_extract(metadata,'$.kind')"
                connection.execute(f"DELETE FROM chunk_terms WHERE chunk_id IN (SELECT id FROM chunks WHERE workspace_id=? AND {field}!='code')", (workspace_id,))
                connection.execute(f"DELETE FROM chunks WHERE workspace_id=? AND {field}!='code'", (workspace_id,))
                for c in chunks:
                    connection.execute('INSERT INTO chunks(id,workspace_id,generation,source_id,content,metadata,profile,embedding) VALUES(?,?,?,?,?,?,?,?)',
                        (c['id'], workspace_id, current['generation'], c['source_id'], c['content'],
                         json.dumps(c['metadata'], ensure_ascii=False), c['profile'], json.dumps(c['embedding'])))
                    if self.store.db.url and c['embedding']:
                        connection.execute('UPDATE chunks SET vector_value=?::vector WHERE id=?', (str(c['embedding']), c['id']))
                    connection.executemany('INSERT INTO chunk_terms VALUES(?,?,?,?,?)',
                        [(c['id'], workspace_id, current['generation'], term, n) for term, n in Counter(tokens(c['content'])).items()])
                rows = connection.execute('SELECT metadata FROM chunks WHERE workspace_id=? AND generation=?', (workspace_id, current['generation'])).fetchall()
                current.update(wiki_signature=signature, chunk_count=len(rows),
                    embedding_mode=embedding_mode, embedding_profile=profile,
                    embedding_settings_revision=project_settings['revision'],
                    avg_length=sum(json.loads(r[0])['length'] for r in rows) / max(1, len(rows)),
                    updated_at=now(), revision=current['revision'] + 1)
                self.store._put(connection, 'index', current)
                receipt = self.store.get('knowledge_task', task_id)
                receipt.update(status='succeeded', phase='published', completed=len(chunks), finished_at=now(), revision=receipt['revision'] + 1)
                self.store._put(connection, 'knowledge_task', receipt)
        except EmbeddingCancelled:
            return
        except Exception as exc:
            with self.lock:
                if not stopped():
                    self.store.update('knowledge_task', task_id, {'status': 'failed', 'finished_at': now(),
                        **failure_receipt(exc, phase='knowledge_refresh', subject=task_id)})

    def run(self, task_id):
        task = self.store.get('knowledge_task', task_id)
        if task['kind'] == 'refresh':
            return self.run_refresh(task_id)
        if task.get('operation') == 'governance':
            from memory_center.platform.knowledge_governance import KnowledgeGovernance
            return KnowledgeGovernance(self.platform).run(task_id)
        with self.lock:
            task = self.store.get('knowledge_task', task_id)
            if task['status'] != 'queued':
                return
            self.store.update('knowledge_task', task_id, {'status': 'running', 'started_at': now()})
        intelligence = Intelligence(self.platform)
        batch, size, duplicates = [], 0, {}
        def stopped():
            return self.stopping or self.store.get('knowledge_task', task_id)['status'] != 'running'
        def process():
            if stopped():
                return False
            result = intelligence.preview(task['workspace_id'], task['kind'], [s['id'] for s in batch])
            if [(s['id'], s['revision']) for s in result['sources']] != [(s['id'], s['revision']) for s in batch]:
                self.store.delete('intelligence_preview', result['id'])
                raise CatalogError('REVISION_CONFLICT', '来源在整理期间已变化，请重新提交')
            result = self.store.update('intelligence_preview', result['id'], {'expires_at':
                (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()})
            with self.lock:
                if stopped():
                    # Unpublished intermediate drafts cannot be applied after cancellation.
                    self.store.delete('intelligence_preview', result['id'])
                    return False
                current = self.store.get('knowledge_task', task_id)
                self.store.update('knowledge_task', task_id, {'completed': current['completed'] + len(batch),
                    'preview_ids': [*current['preview_ids'], result['id']]})
            return True
        try:
            for snapshot in task['sources']:
                if stopped():
                    return
                item = intelligence.source(task['workspace_id'], task['kind'], snapshot['id'])
                if item['revision'] != snapshot['revision']:
                    raise CatalogError('REVISION_CONFLICT', '来源在排队期间已变化，请重新提交整理')
                length = len(item['content']) + len(item['title']) + 100
                if length > 110000:
                    raise CatalogError('CHAT_INPUT_LIMIT', '单篇内容超过模型整理预算，请拆分后重试')
                if batch and (len(batch) >= 20 or size + length > 110000):
                    if not process():
                        return
                    batch, size = [], 0
                batch.append(snapshot)
                size += length
                digest = hashlib.sha256(' '.join(item['content'].split()).encode()).hexdigest()
                duplicates.setdefault(digest, []).append(item['id'])
            if batch and not process():
                return
            with self.lock:
                if not stopped():
                    self.store.update('knowledge_task', task_id, {'status': 'succeeded', 'finished_at': now(),
                        'duplicate_groups': [v for v in duplicates.values() if len(v) > 1]})
        except Exception as exc:
            with self.lock:
                if not stopped():
                    self.store.update('knowledge_task', task_id, {'status': 'failed', 'finished_at': now(),
                        **failure_receipt(exc, phase='organize', subject=task_id)})

    async def start(self):
        with self.store.db.connection() as connection:
            rows = connection.execute("SELECT payload FROM records WHERE kind='knowledge_task'").fetchall()
        for row in rows:
            task = json.loads(row[0])
            if task['status'] == 'running':
                self.store.update('knowledge_task', task['id'], {'status': 'interrupted', 'finished_at': now()})
        self.runner = asyncio.create_task(self.loop())

    async def loop(self):
        while not self.stopping:
            field = "payload::jsonb->>'status'" if self.store.db.url else "json_extract(payload,'$.status')"
            with self.store.db.connection() as connection:
                row = connection.execute(f"SELECT id FROM records WHERE kind='knowledge_task' AND {field}='queued' ORDER BY updated_at LIMIT 1").fetchone()
            if row:
                await asyncio.to_thread(self.run, row[0])
            else:
                await asyncio.sleep(.3)

    async def close(self):
        self.stopping = True
        if self.runner:
            await self.runner
        for task in self.store.list_page('knowledge_task', page_size=50, status='running')['items']:
            self.store.update('knowledge_task', task['id'], {'status': 'interrupted', 'finished_at': now()})

    def capture(self, workspace_id, source_id, content):
        self.platform.catalog.get(workspace_id)
        controls = self.store.list('capture_settings', workspace_id, limit=1)
        if not controls or not controls[0].get('enabled'):
            raise CatalogError('CAPTURE_DISABLED', '请先明确启用本项目会话采集')
        digest = hashlib.sha256((workspace_id + '\0' + source_id + '\0' + content).encode()).hexdigest()
        record_id = 'capture_' + digest
        with self.store.generation_lock(workspace_id):
            try:
                return self.store.get('memory', record_id)
            except CatalogError as exc:
                if exc.code != 'RECORD_NOT_FOUND':
                    raise
            return self.store.create('memory', {'id': record_id, 'workspace_id': workspace_id,
                'owner': 'admin', 'title': '待提炼的会话资料', 'content': content, 'status': 'pending',
                'source_kind': 'session_capture', 'source_id': source_id, 'source_hash': digest,
                'requires_review': True})
