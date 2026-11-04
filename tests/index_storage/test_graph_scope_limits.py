"""大范围图清理不依赖 SQLite 表达式深度或绑定参数上限。"""
import sqlite3

import pytest

from memory_center.core.storage.graph import GraphEdge, GraphNode
from memory_center.core.storage.runtime import RuntimeStore


def test_large_paths_and_node_ids_with_low_sqlite_limits(tmp_path):
    with RuntimeStore(tmp_path / 'graph.db') as graph:
        nodes = [GraphNode(f'n{i}', 'Class', f'Class{i}', 'parent', f'src/{i}.java') for i in range(2000)]
        child = GraphNode('child', 'Class', 'Child', 'child', 'src/nested/child.java')
        graph.rebuild([*nodes, child], [GraphEdge('incoming', 'child', 'n0', 'CALLS'),
                                      GraphEdge('outgoing', 'n0', 'child', 'CALLS')])
        graph.rebuild_search_index()
        conn = graph.connect()
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 64)
        conn.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 64)
        removed = graph.remove_by_scope(set(), [f'\\src\\{i}.java' for i in range(2000)], preserve_incoming=True)
        assert removed == {n.id for n in nodes}
        assert graph.counts() == {'nodes': 1, 'edges': 1}
        assert conn.execute('SELECT id FROM edges').fetchone()[0] == 'incoming'
        assert conn.execute('SELECT id FROM node_search').fetchone()[0] == 'child'
        # Reusing the connection must not retain the previous scope.
        assert graph.remove_by_scope({'missing'}, ['missing.java']) == set()
        assert graph.counts()['nodes'] == 1


def test_scope_union_and_incoming_edge_cleanup(tmp_path):
    with RuntimeStore(tmp_path / 'graph.db') as graph:
        nodes = [GraphNode('a', 'Class', 'A', 'parent', 'parent/a.java'),
                 GraphNode('b', 'Class', 'B', 'child', 'child/b.java'),
                 GraphNode('c', 'Class', 'C', 'other', 'other/c.java')]
        graph.rebuild(nodes, [GraphEdge('incoming', 'c', 'a', 'CALLS'),
                              GraphEdge('outgoing', 'b', 'c', 'CALLS')])
        assert graph.remove_by_scope({'parent'}, ['child/b.java']) == {'a', 'b'}
        assert graph.counts() == {'nodes': 1, 'edges': 0}


def test_scope_cleanup_rolls_back_on_delete_error(tmp_path):
    with RuntimeStore(tmp_path / 'graph.db') as graph:
        graph.rebuild([GraphNode('a', 'Class', 'A', 'demo', 'a.java')],
                      [GraphEdge('e', 'a', 'a', 'CALLS')])
        graph.rebuild_search_index()
        conn = graph.connect()
        conn.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON nodes BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match='injected failure'):
            graph.remove_by_scope(set(), ['a.java'])
        assert graph.counts() == {'nodes': 1, 'edges': 1}
        assert conn.execute('SELECT COUNT(*) FROM node_search').fetchone()[0] == 1
        conn.execute('DROP TRIGGER fail_delete')
        assert graph.remove_by_scope(set(), ['a.java']) == {'a'}


def test_partial_rebuild_large_scope_updates_search(tmp_path):
    with RuntimeStore(tmp_path / 'graph.db') as graph:
        paths = [f'src/{i}.java' for i in range(1500)]
        graph.rebuild([GraphNode('old', 'Class', 'Old', 'demo', paths[0]),
                       GraphNode('child', 'Class', 'Child', 'nested', 'nested/Child.java')], [])
        graph.rebuild_search_index()
        result = graph.partial_rebuild([GraphNode('fresh', 'Class', 'Fresh', 'demo', paths[0])], [], set(), paths)
        assert result['nodes'] == 2
        assert not graph.find_nodes('Old')
        assert graph.find_nodes('Fresh') and graph.find_nodes('Child')
