"""有界 BM25 候选召回、PG 向量检索与 RRF；证据按主体过滤。"""
import collections
import heapq
import json
import math
import os
import re
from datetime import datetime, timezone

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embeddings import Embedder
from memory_center.platform.reranking import Reranker
from memory_center.platform.project_embedding import embedding_settings, effective_embedding_mode


def sqlite_vector_limit():
    try:
        value = int(os.environ.get('MEMORY_CENTER_SQLITE_VECTOR_SCAN_LIMIT', '5000'))
        if value < 0:
            raise ValueError()
        return value
    except ValueError as error:
        raise CatalogError('VECTOR_CONFIG_INVALID', 'SQLite 向量扫描上限须为非负整数，0 表示不限制') from error


def tokens(text):
    latin = re.findall(r'[a-zA-Z0-9_]+', text.lower())
    chinese = re.findall(r'[\u3400-\u9fff]+', text)
    return latin + [part[i:i + 2] for part in chinese for i in range(max(1, len(part) - 1))]


def initialize_terms(database):
    with database.connection(True) as connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS chunk_terms(
            chunk_id TEXT NOT NULL,workspace_id TEXT NOT NULL,generation TEXT NOT NULL,
            term TEXT NOT NULL,frequency INTEGER NOT NULL,PRIMARY KEY(chunk_id,term))''')
        connection.execute('CREATE INDEX IF NOT EXISTS chunk_terms_query ON chunk_terms(workspace_id,generation,term)')


def index_terms(connection, workspace_id, generation, chunks):
    connection.execute('DELETE FROM chunk_terms WHERE workspace_id=?', (workspace_id,))
    for chunk in chunks:
        counts = collections.Counter(tokens(chunk['content']))
        chunk['metadata']['length'] = sum(counts.values())
        connection.executemany('INSERT INTO chunk_terms VALUES(?,?,?,?,?)',
                               [(chunk['id'], workspace_id, generation, term, frequency)
                                for term, frequency in counts.items()])


class Retrieval:
    def __init__(self, store, knowledge):
        self.store, self.knowledge = store, knowledge

    def search(self, workspace, actor, query, mode='hybrid', limit=10):
        if not query.strip() or len(query) > 1000 or mode not in {'keyword', 'vector', 'hybrid'} or not 1 <= limit <= 50:
            raise CatalogError('QUERY_INVALID', '查询内容、模式或数量无效')
        workspace_id = workspace['workspace_id']
        try:
            index = self.store.get('index', workspace_id)
        except CatalogError:
            return {'state': 'NOT_INDEXED', 'items': [], 'negative_claim_allowed': False}
        if index['config_version'] != workspace['config_version']:
            return {'state': 'STALE', 'items': [], 'negative_claim_allowed': False}
        live = {item['id']: item for _, item in self.knowledge.active(workspace_id)}
        replaced = {item['replaces'] for item in live.values() if item.get('replaces')}

        def visible(row):
            metadata = json.loads(row['metadata'])
            if metadata.get('kind') != 'code':
                current = live.get(row['source_id'])
                if not current or current['revision'] != metadata['source_revision'] or current['id'] in replaced:
                    return False
                if current.get('expires_at') and datetime.fromisoformat(current['expires_at']) < datetime.now(timezone.utc):
                    return False
                if metadata.get('kind') == 'memory' and current['owner'] not in {actor.id, 'admin'}:
                    return False
            return True

        keyword_rows, vector_rows = [], []
        generation = index['generation']
        with self.store.db.connection() as connection:
            if mode != 'vector':
                terms = sorted(set(tokens(query)))[:40]
                if terms:
                    marks = ','.join('?' for _ in terms)
                    # 候选只来自倒排匹配；限定 2000，避免加载整个库。
                    rows = connection.execute(f'''SELECT c.*,t.term,t.frequency FROM chunks c JOIN chunk_terms t ON c.id=t.chunk_id
                        WHERE c.workspace_id=? AND c.generation=? AND t.term IN ({marks}) LIMIT 2000''',
                                              (workspace_id, generation, *terms)).fetchall()
                    n = max(1, index['chunk_count'])
                    candidates, scores = {}, collections.defaultdict(float)
                    for term in terms:
                        df = connection.execute('''SELECT count(*) FROM chunk_terms WHERE workspace_id=? AND generation=? AND term=?''',
                                                (workspace_id, generation, term)).fetchone()[0]
                        idf = math.log(1 + (n - df + .5) / (df + .5))
                        for row in rows:
                            if row['term'] == term and visible(row):
                                candidates[row['id']] = row
                                length = max(1, json.loads(row['metadata']).get('length', 200))
                                frequency = row['frequency']
                                scores[row['id']] += idf * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * length / max(1, index.get('avg_length', 200))))
                    keyword_rows = sorted(candidates.values(), key=lambda row: (-scores[row['id']], row['id']))[:100]
            settings = self.store.list('model', limit=1)
            embedder = Embedder(settings[0] if settings else {})
            project_settings = embedding_settings(self.store, workspace_id)
            embedding_mode = effective_embedding_mode(project_settings, embedder.enabled)
            vector_enabled = embedding_mode != 'off'
            indexed_mode = index.get('embedding_mode', 'all' if index.get('embedding_profile') else 'off')
            profile_stale = vector_enabled and (index.get('embedding_profile') != embedder.profile or
                indexed_mode == 'off' or (embedding_mode == 'all' and indexed_mode != 'all'))
            kind_field = "metadata::jsonb->>'kind'" if self.store.db.url else "json_extract(metadata,'$.kind')"
            vector_scope = f" AND {kind_field}!='code'" if embedding_mode == 'knowledge' else ''
            if mode != 'keyword' and vector_enabled and not profile_stale:
                vector = embedder.embed([query])[0]
                if self.store.db.url:
                    dimension = len(vector)
                    rows = connection.execute(f'''SELECT * FROM chunks WHERE workspace_id=? AND generation=?
                        AND profile=? AND vector_value IS NOT NULL{vector_scope} ORDER BY vector_value::vector({dimension}) <=> ?::vector({dimension}) LIMIT 200''',
                                              (workspace_id, generation, embedder.profile, str(vector))).fetchall()
                    vector_rows = [row for row in rows if visible(row)][:100]
                else:
                    budget = sqlite_vector_limit()
                    count = connection.execute(f'''SELECT count(*) FROM chunks WHERE workspace_id=? AND generation=? AND profile=?{vector_scope}''',
                                               (workspace_id, generation, embedder.profile)).fetchone()[0]
                    if budget and count > budget:
                        raise CatalogError('VECTOR_BUDGET', '向量分块超过可选 SQLite 扫描上限；可调整 MEMORY_CENTER_SQLITE_VECTOR_SCAN_LIMIT（0 为不限制）或使用 PostgreSQL')
                    rows = connection.execute(f'''SELECT * FROM chunks WHERE workspace_id=? AND generation=? AND profile=?{vector_scope}''',
                                              (workspace_id, generation, embedder.profile))
                    norm = math.sqrt(sum(v * v for v in vector)) or 1

                    def scored_rows():
                        for row in rows:
                            other = json.loads(row['embedding'])
                            if visible(row) and len(other) == len(vector):
                                denom = norm * (math.sqrt(sum(v * v for v in other)) or 1)
                                yield sum(a * b for a, b in zip(vector, other, strict=False)) / denom, row

                    vector_rows = [r for _, r in heapq.nsmallest(100, scored_rows(), key=lambda value: (-value[0], value[1]['id']))]
        if mode == 'vector' and not vector_enabled:
            if project_settings['mode'] == 'off':
                raise CatalogError('VECTOR_DISABLED', '该项目已关闭向量，请使用关键词、符号或调用图查询')
            raise CatalogError('MODEL_NOT_CONFIGURED', '尚未配置嵌入模型')
        fused, rows = collections.defaultdict(float), {}
        for ranked in [keyword_rows, vector_rows]:
            for position, row in enumerate(ranked):
                fused[row['id']] += 1 / (60 + position + 1)
                rows[row['id']] = row
        items = []
        for chunk_id in sorted(rows, key=lambda key: (-fused[key], key))[:min(100, max(limit, limit * 3))]:
            row = rows[chunk_id]
            items.append({'chunk_id': chunk_id, 'content': row['content'][:6000],
                          'source': json.loads(row['metadata']), 'score': round(fused[chunk_id], 6),
                          'generation': generation, 'workspace_id': workspace_id})
        rerank_settings = self.store.list('rerank_model', limit=1)
        items, reranking = Reranker(rerank_settings[0] if rerank_settings else {}).rank(query, items)
        return {'state': 'FOUND' if items else 'NOT_FOUND', 'items': items[:limit], 'reranking': reranking,
                'vector_enabled': vector_enabled and not profile_stale, 'vector_reindex_required': profile_stale,
                'embedding_mode': embedding_mode, 'generation': generation, 'negative_claim_allowed': False}
