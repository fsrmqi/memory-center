"""全局工作池：预算切分、顺序保持、失败语义与池化等价性。

对应改动：``platform/work_pool.py``、``platform/code_graph.py``（文件级并行）、
``platform/jobs.py``（预算切分与作业装配）。
"""
import pytest

from memory_center.core.indexing.language_registry import get_language_spec_for_extension
from memory_center.platform.code_graph import build_code_graph
from memory_center.platform.jobs import Jobs
from memory_center.platform.work_pool import (
    MIN_PARALLEL_ITEMS,
    WorkPool,
    cpu_budget,
    share_budget,
)

SOURCES = {
    'pkg/helpers.py': 'def assist():\n    return 1\n',
    'pkg/main.py': 'from .helpers import assist as aid\ndef python_entry():\n    return aid()\n',
    'web/helpers.ts': 'export const assist = () => 1;',
    'web/main.ts': 'import {assist as aid} from "./helpers"; export const ts_entry = () => aid();',
    'Entry.java': 'package demo; class Entry { void java_entry() { helper(); } void helper() {} }',
    'go.mod': 'module example.test/demo\n\ngo 1.22\n',
    'main.go': 'package main\nimport aid "example.test/demo/pkg"\nfunc go_entry() { aid.Assist() }\n',
}


def write_tree(root, sources=SOURCES):
    paths = []
    for relative, text in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        paths.append(path)
    return paths


def parseable(paths):
    """``build_code_graph`` 只处理语言注册表认得后缀的文件（``go.mod`` 不在内）。"""
    return [path for path in paths if get_language_spec_for_extension(path.suffix) is not None]


def test_cpu_budget_is_positive():
    assert cpu_budget() >= 1


@pytest.mark.parametrize(('budget', 'concurrent', 'expected'), [
    (14, 1, 14),
    (14, 4, 3),
    (14, 14, 1),
    (14, 40, 1),
    (8, 3, 2),
    (1, 8, 1),
])
def test_share_budget_splits_without_oversubscribing(budget, concurrent, expected):
    assert share_budget(budget, concurrent) == expected


def test_pool_falls_back_to_serial_below_min_items():
    with WorkPool(4) as pool:
        payload = list(range(MIN_PARALLEL_ITEMS - 1))
        assert pool.map(str, payload) == [str(item) for item in payload]
        snapshot = pool.snapshot()
        assert snapshot['submitted'] == 0
        assert snapshot['serial_fallbacks'] == 1
        assert snapshot['worker_pids'] == []


def test_pool_width_one_never_spawns():
    with WorkPool(1) as pool:
        assert pool.parallel is False
        assert pool.map(str, [1, 2, 3]) == ['1', '2', '3']
        snapshot = pool.snapshot()
        assert snapshot['submitted'] == 0
        assert snapshot['serial_fallbacks'] == 1
        assert snapshot['worker_pids'] == []


def test_pool_preserves_input_order_and_reports_workers():
    payload = list(range(200))
    with WorkPool(3, min_items=1) as pool:
        assert pool.map(str, payload) == [str(item) for item in payload]
        snapshot = pool.snapshot()
        assert snapshot['submitted'] == len(payload)
        assert snapshot['completed'] == len(payload)
        assert len(snapshot['worker_pids']) > 1


def test_pool_propagates_worker_failure_instead_of_silently_dropping():
    with WorkPool(2, min_items=1) as pool:
        with pytest.raises(ValueError):
            pool.map(int, ['1', 'not-a-number'])


def test_pool_rejects_callables_spawn_cannot_import():
    with WorkPool(2, min_items=1) as pool:
        with pytest.raises(ValueError):
            pool.map(lambda item: item, [1, 2])


def test_build_code_graph_pooled_equals_serial(tmp_path):
    paths = write_tree(tmp_path)
    serial = build_code_graph(tmp_path, paths, None)
    assert serial['symbols']
    with WorkPool(2, min_items=1) as pool:
        pooled = build_code_graph(tmp_path, paths, None, pool)
        assert pool.snapshot()['submitted'] == len(parseable(paths))
    assert pooled == serial


def test_build_code_graph_serial_path_unchanged_when_width_one(tmp_path):
    paths = write_tree(tmp_path)
    serial = build_code_graph(tmp_path, paths, None)
    with WorkPool(1) as pool:
        assert build_code_graph(tmp_path, paths, None, pool) == serial


def test_build_code_graph_isolates_single_file_failure(tmp_path):
    paths = write_tree(tmp_path)
    broken = tmp_path / 'broken.py'
    broken.mkdir()
    paths.append(broken)
    graph = build_code_graph(tmp_path, paths, None)
    assert graph['coverage']['broken.py']['status'].startswith('failed:')
    assert not any(symbol['path'] == 'broken.py' for symbol in graph['symbols'])
    assert any(symbol['path'] == 'pkg/helpers.py' for symbol in graph['symbols'])


def test_build_code_graph_records_parse_progress_per_file(tmp_path):
    paths = write_tree(tmp_path)
    expected = len(parseable(paths))
    seen = []
    build_code_graph(tmp_path, paths, lambda stage, *args: seen.append((stage, *args)), None)
    parsing = [item for item in seen if item[0] == 'parsing']
    assert len(parsing) == expected
    assert parsing[-1][1] == parsing[-1][2] == expected


class _StubJobs:
    def __init__(self, configured):
        self._configured = configured

    def settings(self):
        return {'max_file_workers': self._configured, 'max_projects': 4}


def test_file_workers_default_splits_cpu_budget_across_projects():
    stub = _StubJobs(0)
    assert Jobs.file_workers_for(stub, 1) == max(0, share_budget(cpu_budget(), min(4, cpu_budget())) - 1)
    assert Jobs.file_workers_for(stub, 4) == max(0, share_budget(cpu_budget(), 4) - 1)
    # 并发项目数超过预算时，项目内退化为串行而不是超卖。
    assert Jobs.file_workers_for(stub, 64) == 0


def test_file_workers_explicit_setting_is_per_project_width():
    assert Jobs.file_workers_for(_StubJobs(6), 1) == min(6, max(0, share_budget(cpu_budget(), min(4, cpu_budget())) - 1))
    assert Jobs.file_workers_for(_StubJobs(6), 4) == min(6, max(0, share_budget(cpu_budget(), 4) - 1))
