"""可选模型重排；只接收授权过滤后的候选，失败显式回退至原排序。"""
import math
import os

import httpx

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.embeddings import Embedder


class Reranker:
    @staticmethod
    def validate(settings):
        Embedder.validate({**settings, 'protocol': 'openai', 'dimensions': 1024})
        if settings.get('enabled') and not (settings.get('url') and settings.get('model')):
            raise CatalogError('RERANK_INVALID', '启用重排前请填写模型与地址')
        return settings

    def __init__(self, settings):
        self.settings = self.validate(settings)

    def rank(self, query, items):
        if not self.settings.get('enabled') or not items:
            return items, {'enabled': False, 'state': 'disabled'}
        try:
            key = os.environ.get('MEMORY_CENTER_RERANK_API_KEY', '')
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                result = client.post(self.settings['url'].rstrip('/') + '/rerank',
                    headers={'Authorization': 'Bearer ' + key} if key else {},
                    json={'model': self.settings['model'], 'query': query,
                          'documents': [i['content'] for i in items], 'top_n': len(items)})
                result.raise_for_status()
                rows = result.json()['results']
            if not isinstance(rows, list) or len(rows) != len(items):
                raise ValueError('count')
            indices = [r['index'] for r in rows]
            if any(type(i) is not int for i in indices) or sorted(indices) != list(range(len(items))):
                raise ValueError('indices')
            for row in rows:
                score = row['relevance_score']
                if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                    raise ValueError('score')
            ranked = [dict(items[r['index']], rerank_score=r['relevance_score'])
                      for r in sorted(rows, key=lambda r: (-r['relevance_score'], r['index']))]
            return ranked, {'enabled': True, 'state': 'applied', 'model': self.settings['model']}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return items, {'enabled': True, 'state': 'fallback', 'error': 'RERANK_FAILED'}
