"""索引资源软上限与代码图否定结论边界。"""
import json
from pathlib import Path

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.code_graph import build_code_graph, claim_boundary, query_code_graph
from memory_center.platform.jobs import IndexLimits, scan_source_files
from memory_center.service.app import release_stage
from tests.service.test_platform import service as service  # noqa: F401
from tests.service.test_wiki_sources import wait_job


def test_release_stage_derives_from_version():
    # 阶段标签必须由版本派生，避免手写迁移切片（如 "S4"）随版本漂移。
    assert release_stage('5.0.0b7') == 'development'
    assert release_stage('5.0.0rc1') == 'development'
    assert release_stage('5.0.0a1') == 'development'
    assert release_stage('5.0.0') == 'stable'


def test_index_limits_defaults_are_generous(monkeypatch):
    for name in ['MEMORY_CENTER_INDEX_MAX_FILES', 'MEMORY_CENTER_INDEX_MAX_TOTAL_MB',
                 'MEMORY_CENTER_INDEX_MAX_FILE_MB', 'MEMORY_CENTER_ALLOW_LARGE_INDEX',
                 'MEMORY_CENTER_INDEX_MEMORY_LIMIT_MB', 'MEMORY_CENTER_INDEX_TIMEOUT_SECONDS']:
        monkeypatch.delenv(name, raising=False)
    limits = IndexLimits.from_env()
    # 默认大小限制必须关闭，且不施加内存与超时约束（保留 5.0.0b7 的放开策略）。
    assert limits.max_files == 0
    assert limits.max_total_bytes == 0
    assert limits.max_file_bytes == 0
    assert limits.allow_large is False
    assert limits.memory_limit_bytes == 0 and limits.timeout_seconds == 0


def test_index_limits_env_overrides_and_invalid_values(monkeypatch):
    monkeypatch.setenv('MEMORY_CENTER_INDEX_MAX_FILES', '5')
    monkeypatch.setenv('MEMORY_CENTER_INDEX_MEMORY_LIMIT_MB', '512')
    monkeypatch.setenv('MEMORY_CENTER_INDEX_TIMEOUT_SECONDS', '600')
    monkeypatch.setenv('MEMORY_CENTER_ALLOW_LARGE_INDEX', '1')
    limits = IndexLimits.from_env()
    assert (limits.max_files, limits.memory_limit_bytes, limits.timeout_seconds) == (5, 512 * 1024 ** 2, 600)
    assert limits.allow_large is True
    # 非法值回退默认，不静默变成 0 或负数。
    monkeypatch.setenv('MEMORY_CENTER_INDEX_MAX_FILES', 'not-a-number')
    assert IndexLimits.from_env().max_files == 0
    monkeypatch.setenv('MEMORY_CENTER_INDEX_MAX_FILES', '-3')
    assert IndexLimits.from_env().max_files == 0


def test_scan_source_files_enforces_file_budget(tmp_path):
    for index in range(4):
        (tmp_path / f'module{index}.py').write_text('x = 1\n')
    with pytest.raises(CatalogError, match='软上限'):
        scan_source_files(tmp_path, IndexLimits(max_files=3))
    assert len(scan_source_files(tmp_path, IndexLimits(max_files=10))) == 4
    # 显式批准后完整扫描，不做静默截断。
    assert len(scan_source_files(tmp_path, IndexLimits(max_files=1, allow_large=True))) == 4


def test_scan_source_files_rejects_oversized_single_file(tmp_path):
    (tmp_path / 'big.py').write_text('x' * 4096)
    (tmp_path / 'small.py').write_text('y = 1\n')
    with pytest.raises(CatalogError, match='单文件超过'):
        scan_source_files(tmp_path, IndexLimits(max_file_bytes=1024))
    assert len(scan_source_files(tmp_path, IndexLimits(max_file_bytes=1024, allow_large=True))) == 2


def _snapshot(tmp_path, graph):
    directory = tmp_path / 'snapshot'
    directory.mkdir(exist_ok=True)
    (directory / 'code-graph.json').write_text(json.dumps(graph))
    return directory / 'workspace.yaml'


def test_claim_boundary_blocks_negative_claim_on_unresolved_calls():
    graph = {'coverage': {'a.py': {'status': 'parsed', 'language': 'python'}},
             'unresolved': [{'path': 'a.py', 'caller': 'a', 'callee': 'b', 'line': 1, 'reason': 'unresolved'}],
             'symbols': [], 'edges': []}
    # 符号不存在只要求覆盖完整。
    assert claim_boundary(graph, (), require_no_unresolved=False) == (True, '')
    # 断言“无调用方”还要求范围内没有未解析调用。
    allowed, reason = claim_boundary(graph, (), require_no_unresolved=True)
    assert allowed is False and '未解析调用' in reason


def test_code_graph_negative_claim_needs_complete_coverage(tmp_path):
    (tmp_path / 'ok.py').write_text('def good():\n    return 1\n')
    (tmp_path / 'broken.py').write_text('def bad(:\n')
    graph = build_code_graph(tmp_path, [tmp_path / 'ok.py', tmp_path / 'broken.py'])
    assert graph['coverage']['broken.py']['status'] != 'parsed'
    workspace_file = _snapshot(tmp_path, graph)
    summary = query_code_graph(workspace_file, 'good', 'symbol')['coverage']
    assert summary['complete'] is False and summary['incomplete_files'] >= 1
    missing = query_code_graph(workspace_file, 'nothing_here', 'symbol')
    assert missing['state'] == 'NOT_FOUND'
    assert missing['negative_claim_allowed'] is False
    assert '未完整解析' in missing['negative_claim_reason']


def test_code_graph_negative_claim_allowed_when_complete(tmp_path):
    (tmp_path / 'ok.py').write_text('def good():\n    return 1\n')
    graph = build_code_graph(tmp_path, [tmp_path / 'ok.py'])
    assert graph['coverage']['ok.py']['status'] == 'parsed'
    workspace_file = _snapshot(tmp_path, graph)
    missing = query_code_graph(workspace_file, 'nothing_here', 'symbol')
    assert missing['state'] == 'NOT_FOUND' and missing['negative_claim_allowed'] is True
    assert missing['negative_claim_reason'] == ''
    # 命中的结果不主张否定，仍为 False。
    found = query_code_graph(workspace_file, 'good', 'symbol')
    assert found['state'] == 'FOUND' and found['negative_claim_allowed'] is False
    callers = query_code_graph(workspace_file, 'good', 'callers')
    assert callers['state'] == 'INSUFFICIENT_EVIDENCE'
    assert callers['negative_claim_allowed'] is True


def test_analyze_does_not_silently_fall_back_for_non_java(service):
    client, admin, platform, spaces = service
    space = spaces[0]
    root = Path(space['root'])
    (root / 'pkg').mkdir(exist_ok=True)
    (root / 'pkg' / 'helpers.py').write_text('def assist():\n    return 1\n')
    wait_job(platform, platform.jobs.enqueue(space['workspace_id'], 'admin'))
    actor = platform.administrator()
    # 覆盖里已经含有非 Java 语言，因此未命中必须显式表达为 anchor_not_found，
    # 而不是静默回落到 Java 专用影响分析——旧实现按命中符号判定，未命中时会返回
    # 不含 state / impact_scope 的结果，把“未解析”表述成“无调用方”。
    missing = platform.analyze(actor, space['workspace_id'], 'pkg/helpers.py:not_there')
    assert missing['state'] == 'NOT_FOUND', missing
    assert missing['impact_scope'] == 'anchor_not_found', missing
    assert isinstance(missing['negative_claim_allowed'], bool)
    # “锚点不存在”与“锚点存在但无静态调用方”必须区分，不能都标成 direct_static_callers。
    present = platform.analyze(actor, space['workspace_id'], 'pkg/helpers.py:assist')
    assert present['impact_scope'] == 'no_static_callers_in_scope', present
