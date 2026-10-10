"""服务记录、修订与索引发布的事务边界。"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from memory_center.core.foundation.catalog import CatalogError


def now():
    return datetime.now(timezone.utc).isoformat()


def identity(prefix):
    return prefix + '_' + uuid4().hex


class PlatformStore:
    def __init__(self, database):
        self.db = database

    def get(self, kind, record_id):
        with self.db.connection() as connection:
            row = connection.execute('SELECT payload FROM records WHERE kind=? AND id=?', (kind, record_id)).fetchone()
        if not row:
            raise CatalogError('RECORD_NOT_FOUND', '记录不存在或不属于当前范围')
        return json.loads(row[0])

    def list(self, kind, workspace_id=None, owner=None, limit=100):
        sql = 'SELECT payload FROM records WHERE kind=?'
        args = [kind]
        for column, value in [('workspace_id', workspace_id), ('owner', owner)]:
            if value is not None:
                sql += f' AND {column}=?'
                args.append(value)
        sql += ' ORDER BY updated_at DESC LIMIT ?'
        with self.db.connection() as connection:
            return [json.loads(row[0]) for row in connection.execute(sql, (*args, limit)).fetchall()]

    def _put(self, connection, kind, item):
        connection.execute('''INSERT INTO records VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            payload=excluded.payload,updated_at=excluded.updated_at''',
                           (item['id'], kind, item.get('workspace_id', ''), item.get('owner', ''),
                            json.dumps(item, ensure_ascii=False), now()))

    def create(self, kind, item):
        item = dict(item, id=item.get('id') or identity(kind), revision=1, created_at=now(), updated_at=now())
        with self.db.connection(True) as connection:
            self._put(connection, kind, item)
        return item

    def update(self, kind, record_id, changes, revision=None):
        with self.db.connection(True) as connection:
            row = connection.execute('SELECT payload FROM records WHERE kind=? AND id=?', (kind, record_id)).fetchone()
            if not row:
                raise CatalogError('RECORD_NOT_FOUND', '记录不存在')
            current = json.loads(row[0])
            if revision is not None and current['revision'] != revision:
                raise CatalogError('REVISION_CONFLICT', '记录已改变，请刷新后重试')
            result = dict(current, **changes)
            result['revision'], result['updated_at'] = current['revision'] + 1, now()
            self._put(connection, kind, result)
            return result

    def delete(self, kind, record_id):
        """删除单条记录；不存在时以 RECORD_NOT_FOUND 明确失败，绝不静默忽略。"""
        with self.db.connection(True) as connection:
            cursor = connection.execute('DELETE FROM records WHERE kind=? AND id=?', (kind, record_id))
            if cursor.rowcount == 0:
                raise CatalogError('RECORD_NOT_FOUND', '记录不存在')
        return {'id': record_id, 'kind': kind, 'deleted': True}

    def audit(self, actor, action, workspace_id='', record_id=''):
        return self.create('audit', {'owner': actor, 'workspace_id': workspace_id,
                                     'action': action, 'target': record_id})

    def publish(self, workspace_id, job_id, chunks, workspace_file, config_version):
        with self.db.connection(True) as connection:
            row = connection.execute("SELECT payload FROM records WHERE kind='job' AND id=?", (job_id,)).fetchone()
            job = json.loads(row[0])
            if job['status'] != 'running':
                raise CatalogError('JOB_CANCELLED', '任务已取消，未发布索引')
            from memory_center.platform.retrieval import index_terms
            index_terms(connection, workspace_id, job_id, chunks)
            for chunk in chunks:
                connection.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?)' if not self.db.url else
                                   '''INSERT INTO chunks(id,workspace_id,generation,source_id,content,metadata,profile,embedding)
                                   VALUES(?,?,?,?,?,?,?,?)''',
                                   (chunk['id'], workspace_id, job_id, chunk['source_id'], chunk['content'],
                                    json.dumps(chunk['metadata'], ensure_ascii=False), chunk.get('profile', ''),
                                    json.dumps(chunk.get('embedding', []))))
                if self.db.url and chunk.get('embedding'):
                    connection.execute('UPDATE chunks SET vector_value=?::vector WHERE id=?',
                                       (str(chunk['embedding']), chunk['id']))
            if self.db.url:
                from collections import Counter
                profiles = Counter((c.get('profile'), len(c.get('embedding', []))) for c in chunks)
                for (profile, dimension), _count in profiles.items():
                    if profile and 0 < dimension <= 2000:
                        name = 'mc_vec_' + profile + '_' + str(dimension)
                        connection.execute(f"CREATE INDEX IF NOT EXISTS {name} ON chunks USING hnsw ((vector_value::vector({dimension})) vector_cosine_ops) WHERE profile='{profile}'")
            index = {'id': workspace_id, 'workspace_id': workspace_id, 'generation': job_id,
                     'workspace_file': workspace_file, 'config_version': config_version, 'revision': 1,
                     'wiki_signature': job.get('wiki_signature', ''),
                     'code_coverage': job.get('code_coverage', {}),
                     'embedding_profile': chunks[0].get('profile', '') if chunks else '', 'chunk_count': len(chunks), 'avg_length': sum(c['metadata']['length'] for c in chunks) / max(1, len(chunks)), 'updated_at': now()}
            self._put(connection, 'index', index)
            job.update(status='succeeded', progress=100, finished_at=now(), revision=job['revision'] + 1)
            self._put(connection, 'job', job)
            connection.execute('DELETE FROM chunks WHERE workspace_id=? AND generation!=?', (workspace_id, job_id))
