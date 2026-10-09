"""Ollama/OpenAI-compatible 批量嵌入；未配置时仅关键词，无伪向量。"""
import hashlib
import json
import math
import os
from urllib.parse import urlparse

import httpx

from memory_center.core.foundation.catalog import CatalogError


class Embedder:
    def __init__(self, settings):
        self.settings = settings
        self.enabled = bool(settings.get('url') and settings.get('model'))
        self.profile = hashlib.sha256(json.dumps({k: settings.get(k) for k in ['url', 'model', 'protocol', 'dimensions']}, sort_keys=True).encode()).hexdigest()[:24] if self.enabled else ''

    @staticmethod
    def validate(settings):
        if bool(settings.get('url')) != bool(settings.get('model')):
            raise CatalogError('MODEL_INVALID', '模型地址和名称需同时填写或同时留空')
        if settings.get('url'):
            try:
                parsed = urlparse(settings['url'])
                _ = parsed.port
            except ValueError as exc:
                raise CatalogError('MODEL_INVALID', '模型地址或端口无效') from exc
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                raise CatalogError('MODEL_INVALID', '模型地址需为无内嵌凭据的 HTTP/HTTPS 地址')
        if settings.get('protocol', 'ollama') not in {'ollama', 'openai'}:
            raise CatalogError('MODEL_INVALID', '模型协议不受支持')
        if not 1 <= settings.get('dimensions', 1024) <= 4096:
            raise CatalogError('MODEL_INVALID', '向量维度需介于 1–4096')
        return settings

    def _embed(self, texts):
        if not self.enabled:
            return [[] for _ in texts]
        settings = self.settings
        results = []
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            for offset in range(0, len(texts), 16):
                batch = texts[offset:offset + 16]
                endpoint = '/api/embed' if settings.get('protocol', 'ollama') == 'ollama' else '/embeddings'
                headers = {}
                key = os.environ.get('MEMORY_CENTER_MODEL_API_KEY', '')
                if key:
                    headers['Authorization'] = 'Bearer ' + key
                response = client.post(settings['url'].rstrip('/') + endpoint,
                                       json={'model': settings['model'], 'input': batch}, headers=headers)
                response.raise_for_status()
                payload = response.json()
                vectors = payload.get('embeddings') if endpoint == '/api/embed' else [
                    item['embedding'] for item in sorted(payload['data'], key=lambda item: item['index'])]
                if not isinstance(vectors, list) or len(vectors) != len(batch):
                    raise CatalogError('EMBEDDING_INVALID', '模型返回数量不匹配')
                for vector in vectors:
                    if len(vector) != settings.get('dimensions', 1024) or any(not isinstance(v, (float, int)) or isinstance(v, bool) or not math.isfinite(v) for v in vector):
                        raise CatalogError('EMBEDDING_INVALID', '模型维度或向量数值无效')
                results.extend(vectors)
        return results

    def embed(self, texts):
        try:
            return self._embed(texts)
        except CatalogError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise CatalogError('MODEL_CONNECTION_FAILED', '模型连接或响应无效，请检查服务、协议与模型配置') from exc
