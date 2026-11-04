"""大项目扫描及大 Java 文件尾部事实完整性回归。"""
import json
from pathlib import Path

from memory_center.core.indexing.reindex import _parse_java_file, safe_read
from memory_center.platform.jobs import source_files
from tests.service.test_platform import service as service  # noqa: F401
from tests.service.test_wiki_sources import wait_job


def test_scan_large_scope_preserves_directory_boundaries(tmp_path):
    # 同时超过旧总字节和文件数预算；稀疏文件避免测试占用大量磁盘。
    for i in range(65):
        with (tmp_path / f'large{i}.txt').open('wb') as file:
            file.truncate(1024 * 1024 + 1)
    for i in range(10001):
        (tmp_path / f'small{i}.py').touch()
    ignored = tmp_path / 'node_modules'
    ignored.mkdir()
    (ignored / 'ignored.js').touch()
    (tmp_path / 'linked.py').symlink_to(tmp_path / 'small0.py')
    files = list(source_files(tmp_path))
    assert len(files) == 10066
    assert all(p.name != 'linked.py' and ignored not in p.parents for p in files)


def test_large_java_tail_survives_real_worker(service):
    client, headers, platform, spaces = service
    workspace = spaces[0]
    path = Path(workspace['root']) / 'LargeController.java'
    text = ('/* ' + 'padding\n' * 150000 + ' */\n'
            'package demo;\n@RestController\n@RequestMapping("/large")\n'
            'public class LargeController {\n@GetMapping("/tail")\n'
            'public String tailEndpoint() { return "completeTailEvidence"; }\n}\n')
    path.write_text(text)
    assert path.stat().st_size > 1024 * 1024
    assert safe_read(path).endswith('}\n')
    assert len(safe_read(path, limit=128)) == 128
    facts = _parse_java_file('demo', path.name, path)
    assert 'LargeController' in facts['symbol']['classes']
    assert any(api['path'] == '/large/tail' for api in facts['apis'])
    response = client.post(f'/api/v1/workspaces/{workspace["workspace_id"]}/index', headers=headers, json={})
    assert response.status_code == 200, response.text
    status = wait_job(platform, response.json())
    assert status['status'] == 'succeeded', status
    index = platform.store.get('index', workspace['workspace_id'])
    graph = json.loads((Path(index['workspace_file']).parent / 'code-graph.json').read_text())
    assert any(symbol['name'] == 'tailEndpoint' for symbol in graph['symbols'])
    result = platform.lookup(platform.administrator(), workspace['workspace_id'], 'completeTailEvidence', 'keyword')
    assert result['items']
