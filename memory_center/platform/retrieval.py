"""有界 BM25 候选召回、PG 向量检索与 RRF；证据按主体过滤。"""
import collections
import json
import math
import re
from datetime import datetime, timezone

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embeddings import Embedder


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
            vector_enabled = embedder.enabled
            profile_stale = embedder.enabled and index.get('embedding_profile') != embedder.profile
            if mode != 'keyword' and vector_enabled and not profile_stale:
                vector = embedder.embed([query])[0]
                if self.store.db.url:
                    dimension = len(vector)
                    rows = connection.execute(f'''SELECT * FROM chunks WHERE workspace_id=? AND generation=?
                        AND profile=? AND vector_value IS NOT NULL ORDER BY vector_value::vector({dimension}) <=> ?::vector({dimension}) LIMIT 200''',
                                              (workspace_id, generation, embedder.profile, str(vector))).fetchall()
                    vector_rows = [row for row in rows if visible(row)][:100]
                else:
                    rows = connection.execute('''SELECT * FROM chunks WHERE workspace_id=? AND generation=? AND profile=? LIMIT 5001''',
                                              (workspace_id, generation, embedder.profile)).fetchall()
                    if len(rows) > 5000:
                        raise CatalogError('VECTOR_BUDGET', '轻量向量召回上限 5000 块，请使用 PostgreSQL 部署')
                    norm = math.sqrt(sum(v * v for v in vector)) or 1
                    scored = []
                    for row in rows:
                        other = json.loads(row['embedding'])
                        if visible(row) and len(other) == len(vector):
                            denom = norm * (math.sqrt(sum(v * v for v in other)) or 1)
                            scored.append((sum(a * b for a, b in zip(vector, other, strict=False)) / denom, row))
                    vector_rows = [r for _, r in sorted(scored, key=lambda value: (-value[0], value[1]['id']))[:100]]
        if mode == 'vector' and not vector_enabled:
            raise CatalogError('MODEL_NOT_CONFIGURED', '尚未配置嵌入模型')
        fused, rows = collections.defaultdict(float), {}
        for ranked in [keyword_rows, vector_rows]:
            for position, row in enumerate(ranked):
                fused[row['id']] += 1 / (60 + position + 1)
                rows[row['id']] = row
        items = []
        for chunk_id in sorted(rows, key=lambda key: (-fused[key], key))[:limit]:
            row = rows[chunk_id]
            items.append({'chunk_id': chunk_id, 'content': row['content'][:6000],
                          'source': json.loads(row['metadata']), 'score': round(fused[chunk_id], 6),
                          'generation': generation, 'workspace_id': workspace_id})
        return {'state': 'FOUND' if items else 'NOT_FOUND', 'items': items,
                'vector_enabled': vector_enabled and not profile_stale, 'vector_reindex_required': profile_stale, 'generation': generation, 'negative_claim_allowed': False}
