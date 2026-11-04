import pytest

from memory_center.application.task_shadow_flow import close_case_records, session_task_binding
from memory_center.core.knowledge.candidates import wiki_knowledge_candidates
from memory_center.core.knowledge.wiki_bridge import attach_knowledge_link_to_task
from memory_center.core.orchestrator import workspace_end_session, workspace_log_session_event, workspace_start_session
from memory_center.core.tasks.artifacts import list_task_spaces
from tests.domain.test_knowledge_links import _RELATIVE, _register, _transport_of, _wiki_entry
from tests.fixtures import copy_demo_workspace


def test_unbound_close_never_creates_task(tmp_path):
    w = copy_demo_workspace(tmp_path)
    s = workspace_start_session(w, 'independent exploration')['session_id']
    workspace_end_session(w, s, outcome='done')
    before = list_task_spaces(w)
    r = close_case_records(w, s, close_task_id='', title='', auto_sync_mode='balanced', outcome='done', record_case=False, verified_by=[])
    assert r['synced']['synced'] is False
    assert list_task_spaces(w) == before


def test_binding_survives_display_window(tmp_path):
    w = copy_demo_workspace(tmp_path)
    s = workspace_start_session(w, 'work', metadata={'task_binding': {'mode': 'auto_direct_anchor', 'task_id': 't'}})['session_id']
    for i in range(60):
        workspace_log_session_event(w, s, 'test', {'n': i})
    assert session_task_binding(w, s)['task_id'] == 't'


def test_attachment_rejects_unknown_task_and_wrong_owner(tmp_path):
    w = copy_demo_workspace(tmp_path)
    _wiki_entry(tmp_path)
    kid = _register(w, tmp_path)['knowledge_id']
    with pytest.raises(PermissionError):
        attach_knowledge_link_to_task(w, kid, task_id='missing', evidence_refs=['task:missing'], actor='other')
    with pytest.raises(ValueError, match='unknown task'):
        attach_knowledge_link_to_task(w, kid, task_id='missing', evidence_refs=['task:missing'], actor='tester')


def test_real_bm25_and_changed_hash(tmp_path):
    w = copy_demo_workspace(tmp_path)
    root = _wiki_entry(tmp_path)
    _register(w, tmp_path)
    transport = _transport_of([{'path': _RELATIVE, 'score': -9.0, 'snippet': '摘要'}])
    assert wiki_knowledge_candidates(w, task='订单中心', wiki_root=root, transport=transport)['candidates']
    (root / _RELATIVE).write_text('changed', encoding='utf-8')
    assert not wiki_knowledge_candidates(w, task='订单中心', wiki_root=root, transport=transport)['candidates']
    (root / _RELATIVE).unlink()
    assert not wiki_knowledge_candidates(w, task='订单中心', wiki_root=root, transport=transport)['candidates']
