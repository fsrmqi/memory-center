"""项目级向量范围；代码图与关键词索引始终独立运行。"""
from memory_center.core.foundation.catalog import CatalogError


def embedding_settings(store, workspace_id):
    try:
        return store.get('embedding_settings', 'embedding_' + workspace_id)
    except CatalogError as error:
        if error.code != 'RECORD_NOT_FOUND':
            raise
        return {'workspace_id': workspace_id, 'mode': 'inherit', 'revision': 0}


def effective_embedding_mode(settings, model_enabled):
    if not model_enabled or settings['mode'] == 'off':
        return 'off'
    return 'all' if settings['mode'] == 'inherit' else settings['mode']


class ProjectEmbedding:
    def __init__(self, platform):
        self.platform, self.store = platform, platform.store

    def settings(self, workspace_id):
        self.platform.catalog.get(workspace_id)
        return embedding_settings(self.store, workspace_id)

    def configure(self, workspace_id, mode, revision):
        self.platform.catalog.get(workspace_id)
        if mode not in {'inherit', 'all', 'knowledge', 'off'}:
            raise CatalogError('EMBEDDING_MODE_INVALID', '请选择跟随全局、全部内容、仅知识或关闭')
        with self.store.generation_lock(workspace_id):
            current = self.settings(workspace_id)
            if current['revision'] != revision:
                raise CatalogError('REVISION_CONFLICT', '向量设置已改变，请刷新后重试')
            value = {'id': 'embedding_' + workspace_id, 'workspace_id': workspace_id, 'mode': mode}
            result = (self.store.update('embedding_settings', value['id'], value, revision) if revision
                      else self.store.create('embedding_settings', value))
        self.store.audit('admin', 'embedding.configure', workspace_id)
        return result
