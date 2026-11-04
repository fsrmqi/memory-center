"""多语言文件身份、明确导入、调用隔离与真实服务索引验证。"""
import json

import pytest

from memory_center.core.foundation.catalog import CatalogError
from memory_center.core.indexing.structural_parser import TreeSitterStructuralParser
from memory_center.platform.code_graph import build_code_graph, query_code_graph
from tests.service.test_platform import call, credential, mcp_connect
from tests.service.test_platform import service as service  # noqa: F401
from tests.service.test_wiki_sources import wait_job

SOURCES = {
    'pkg/helpers.py': 'def assist():\n    return 1\n',
    'pkg/main.py': 'from .helpers import assist as aid\ndef python_entry():\n    return aid()\n',
    'web/helpers.ts': 'export const assist = () => 1; export default function defaultHelp() { return 2; }',
    'web/main.ts': 'import {assist as aid} from "./helpers"; export const ts_entry = () => aid();',
    'web/default.js': 'import help from "./helpers"; export function js_entry() { return help(); }',
    'web/Page.vue': '<template><p>中文</p></template>\n<script setup lang="ts">\nimport {assist} from "./helpers";\nconst vue_entry = () => assist();\n</script>',
    'web/Widget.tsx': 'export function tsx_entry() { return <div/>; }',
    'go.mod': 'module example.test/demo\n\ngo 1.22\n',
    'tools/help.go': 'package tools\nfunc Assist() {}\n',
    'main.go': 'package main\nimport aid "example.test/demo/tools"\nfunc go_entry() { aid.Assist() }\n',
    'Entry.java': 'package demo; class Entry { void java_entry() { helper(); } void helper() {} }',
}


def write_sources(root, sources=SOURCES):
    for relative, text in sources.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    return [root / relative for relative in sources]


def query_graph(root, graph, name, mode='callees'):
    directory = root / 'snapshot'
    directory.mkdir(exist_ok=True)
    (directory / 'code-graph.json').write_text(json.dumps(graph))
    return query_code_graph(directory / 'workspace.yaml', name, mode)


@pytest.mark.parametrize('entry,target,language', [
    ('python_entry', 'assist', 'python'), ('ts_entry', 'assist', 'typescript'),
    ('js_entry', 'defaultHelp', 'javascript'), ('vue_entry', 'assist', 'vue'),
    ('go_entry', 'Assist', 'go'), ('java_entry', 'helper', 'java'),
])
def test_explicit_cross_file_and_scope(tmp_path, entry, target, language):
    graph = build_code_graph(tmp_path, write_sources(tmp_path))
    result = query_graph(tmp_path, graph, entry)
    assert result['state'] == 'FOUND', result
    assert result['symbols'][0]['language'] == language
    assert [link['symbol']['name'] for link in result['chain']] == [target]
    reverse = query_graph(tmp_path, graph, result['chain'][0]['symbol']['id'], 'callers')
    assert entry in [link['symbol']['name'] for link in reverse['chain']]
    assert not result['negative_claim_allowed']


def test_identity_shadowing_exports_and_ambiguity(tmp_path):
    sources = {
        'a.ts': 'export const same = () => 1; const privateFn = () => 2;',
        'b.ts': 'export const same = () => 2;',
        'entry.ts': 'import {same, privateFn} from "./a";\nfunction shadow(same: () => number) { same(); }\nfunction hidden() { privateFn(); }\nfunction good() { same(); }',
        'bad.ts': 'import {same} from "external"; function outside() { same(); }',
        'broken.ts': 'export function syntax( { same();',
    }
    graph = build_code_graph(tmp_path, write_sources(tmp_path, sources))
    assert len({s['id'] for s in graph['symbols']}) == len(graph['symbols'])
    assert query_graph(tmp_path, graph, 'same', 'callers')['state'] == 'AMBIGUOUS'
    for name in ['shadow', 'hidden', 'outside']:
        result = query_graph(tmp_path, graph, name)
        assert not result['chain'] and result['unresolved_calls'], result
    assert query_graph(tmp_path, graph, 'good')['chain'][0]['symbol']['path'] == 'a.ts'
    assert graph['coverage']['broken.ts']['status'] == 'partial'
    again = build_code_graph(tmp_path, [tmp_path / p for p in sources])
    assert [s['id'] for s in again['symbols']] == [s['id'] for s in graph['symbols']]


def test_nested_call_ownership_and_vue_lines():
    parser = TreeSitterStructuralParser('python')
    result = parser.parse('def outer():\n    def inner():\n        target()\n    inner()\n')
    assert [(c.caller_qualified_name, c.callee_text) for c in result.calls] == [('outer', 'inner'), ('outer.inner', 'target')]
    vue = TreeSitterStructuralParser('vue').parse('<!-- <script>function fake(){}</script> -->\r\n<template>中文</template>\r\n<script setup lang="ts">\r\nconst entry = () => target();\r\n</script>')
    assert [(f.name, f.line) for f in vue.functions] == [('entry', 4)]
    assert vue.calls[0].line == 4 and vue.raw['parse_status'] == 'parsed'
    assert not TreeSitterStructuralParser('vue').parse('<template>中文</template>').functions
    assert TreeSitterStructuralParser('vue').parse('<script src="./a.ts"></script>').raw['parse_status'] == 'partial'


def test_go_same_package_and_python_namespace(tmp_path):
    sources = {'a.go': 'package demo\nfunc Entry() { Helper() }',
               'b.go': 'package demo\nfunc Helper() {}',
               'other/b.go': 'package demo\nfunc Helper() {}',
               'pkg/helper.py': 'def help():\n    pass',
               'main.py': 'import pkg.helper as mod\ndef run():\n    mod.help()'}
    graph = build_code_graph(tmp_path, write_sources(tmp_path, sources))
    assert query_graph(tmp_path, graph, 'Entry')['chain'][0]['symbol']['path'] == 'b.go'
    assert query_graph(tmp_path, graph, 'run')['chain'][0]['symbol']['path'] == 'pkg/helper.py'


def test_service_worker_mcp_and_stale_refs(service):
    client, admin, platform, spaces = service
    space = spaces[0]
    root = __import__('pathlib').Path(space['root'])
    write_sources(root)
    wait_job(platform, platform.jobs.enqueue(space['workspace_id'], 'admin'))
    index = platform.store.get('index', space['workspace_id'])
    assert set(index['code_coverage']['languages']) >= {'java', 'python', 'go', 'typescript', 'javascript', 'tsx', 'vue'}
    headers = mcp_connect(client, credential(client, admin, [space['workspace_id']])['token'])
    for entry in ['java_entry', 'ts_entry', 'js_entry', 'vue_entry', 'python_entry', 'go_entry']:
        result = call(client, headers, 'mc_lookup', {'workspace_id': space['workspace_id'], 'query': entry, 'mode': 'callees'})
        assert not result.get('isError'), result
        evidence = result['structuredContent']
        assert evidence['chain'] and evidence['workspace_id'] == space['workspace_id']
        assert evidence['symbols'][0]['freshness'] == 'CURRENT'
    assert call(client, headers, 'mc_lookup', {'workspace_id': spaces[1]['workspace_id'], 'query': 'python_entry', 'mode': 'symbol'})['isError']
    actor = platform.administrator()
    reference = platform.lookup(actor, space['workspace_id'], 'python_entry', 'callees')
    assert platform.resolve_reference(actor, reference['ref_id'])
    (root / 'pkg/helpers.py').write_text('def assist():\n    return 999')
    with pytest.raises(CatalogError, match='代码符号'):
        platform.resolve_reference(actor, reference['ref_id'])
    assert platform.lookup(actor, space['workspace_id'], 'python_entry', 'callees')['chain'][0]['symbol']['freshness'] == 'STALE'
    assert platform.analyze(actor, space['workspace_id'], 'pkg/helpers.py:assist')['impact_scope'] == 'direct_static_callers'


def test_closure_and_single_arrow_parameter_shadow(tmp_path):
    sources = {'help.ts': 'export function aid() {}',
               'main.ts': 'import {aid} from "./help"; export const arrow = aid => aid();',
               'help.py': 'def aid():\n    pass',
               'main.py': 'from help import aid\ndef outer(aid):\n    def inner():\n        aid()\n    inner()'}
    graph = build_code_graph(tmp_path, write_sources(tmp_path, sources))
    for name in ['arrow', 'outer.inner']:
        assert not query_graph(tmp_path, graph, name)['chain']


def test_export_alias_namespace_and_go_receiver(tmp_path):
    sources = {'lib.ts': 'const helper = () => 1; export {helper as renamed};',
               'main.js': 'import * as mod from "./lib"; function entry() { mod.renamed(); }',
               'receiver.go': 'package demo\ntype Service struct {}\nfunc (s *Service) Entry() { s.Help() }\nfunc (s *Service) Help() {}',
               'X.java': 'package demo; class X { static void Help() {} }',
               'Y.java': 'package demo; class Y { void entryJava() { X.Help(); } }'}
    graph = build_code_graph(tmp_path, write_sources(tmp_path, sources))
    assert query_graph(tmp_path, graph, 'entry')['chain'][0]['symbol']['name'] == 'helper'
    assert query_graph(tmp_path, graph, 'demo.Service.Entry')['chain'][0]['symbol']['qualified_name'] == 'demo.Service.Help'
    assert query_graph(tmp_path, graph, 'entryJava')['evidence_level'] == 'INFERRED'
    assert query_graph(tmp_path, graph, 'demo.Service', 'callers')['chain']
