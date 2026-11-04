"""多模块预览预算及失败原因验证。"""
from pathlib import Path

import pytest

from memory_center.application.workspaces import WorkspaceCatalog
from memory_center.core.foundation.catalog import CatalogError
from memory_center.core.storage.catalog import CatalogStore
from memory_center.core.workspace import discovery


def project(root, count):
    root.mkdir()
    for number in range(count):
        module = root / f'module-{number:03}'
        module.mkdir()
        (module / 'pom.xml').write_text('<project/>')
    return root


def test_register_133_modules(tmp_path):
    root = project(tmp_path / 'source', 133)
    store = CatalogStore(tmp_path / 'data')
    store.initialize()
    catalog = WorkspaceCatalog(store)
    result = catalog.preview(str(root))
    assert result['scan']['complete'] and result['scan']['service_limit'] == 256
    assert len(result['services']) == 133
    saved = catalog.register('多模块', str(root))
    assert len(saved['services']) == 133


def test_over_service_budget_rejected(tmp_path):
    root = project(tmp_path / 'source', 257)
    store = CatalogStore(tmp_path / 'data')
    store.initialize()
    catalog = WorkspaceCatalog(store)
    assert catalog.preview(str(root))['scan']['warnings'] == ['service_limit']
    with pytest.raises(CatalogError, match='服务超过 256'):
        catalog.register('超限', str(root))
    assert catalog.store.list(20)['items'] == []


def test_entry_budget_error(tmp_path, monkeypatch):
    root = project(tmp_path / 'source', 3)
    monkeypatch.setattr(discovery, '_MAX_ENTRIES', 1)
    store = CatalogStore(tmp_path / 'data')
    store.initialize()
    catalog = WorkspaceCatalog(store)
    with pytest.raises(CatalogError, match='目录项超过 1'):
        catalog.register('超限', str(root))


def test_unreadable_marker_error(tmp_path, monkeypatch):
    root = project(tmp_path / 'source', 1)
    original = Path.open

    def inaccessible(path, *args, **kwargs):
        if path.name == 'pom.xml':
            raise PermissionError('测试读取失败')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', inaccessible)
    store = CatalogStore(tmp_path / 'data')
    store.initialize()
    catalog = WorkspaceCatalog(store)
    with pytest.raises(CatalogError, match='构建标记无法读取'):
        catalog.register('无法读取', str(root))
