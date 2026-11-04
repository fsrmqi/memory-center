"""人工答案键驱动检索回放；报告不保存查询正文，不调整检索权重。"""
import hashlib


def evaluate(platform, actor, workspace_id, cases, limit=10):
    reports = []
    for case in cases:
        result = platform.lookup(actor, workspace_id, case['query'], case.get('mode', 'hybrid'), limit)
        found = {i['source'].get('source_id') or i['source'].get('path') for i in result.get('items', [])}
        found.discard(None)
        expected = set(case['expected_sources'])
        hits = len(expected & found)
        reports.append({'query_hash': hashlib.sha256(case['query'].encode()).hexdigest(),
            'expected_count': len(expected), 'retrieved_count': len(found), 'hits': hits,
            'recall': hits / len(expected), 'precision': hits / max(1, len(found)),
            'state': result['state'], 'reranking': result.get('reranking'),
            'vector_enabled': result.get('vector_enabled', False)})
    return {'cases': reports, 'mean_recall': sum(r['recall'] for r in reports) / len(reports),
            'mean_precision': sum(r['precision'] for r in reports) / len(reports),
            'answer_source': 'user_supplied', 'automatic_tuning': False}
