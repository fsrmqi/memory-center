"""来源、版本与记忆治理；原文存储在服务目录，索引可重建。"""
import base64
import hashlib
import io
import json
import math
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

from memory_center.core.foundation.catalog import CatalogError


def parse_document(filename, content, encoding='text'):
    if encoding == 'text':
        return content
    try:
        raw = base64.b64decode(content, validate=True)
    except ValueError as exc:
        raise CatalogError('DOCUMENT_INVALID', '文件编码无效') from exc
    if len(raw) > 4 * 1024 * 1024:
        raise CatalogError('DOCUMENT_LIMIT', '单份文档不能超过 4 MiB')
    extension = Path(filename).suffix.lower()
    if extension == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted or len(reader.pages) > 500:
            raise CatalogError('DOCUMENT_LIMIT', '不支持加密 PDF 或超过 500 页的文档')
        return '\n\n'.join(f'<!-- page:{index + 1} -->\n{page.extract_text() or ""}'
                           for index, page in enumerate(reader.pages))
    if extension == '.docx':
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entry = archive.getinfo('word/document.xml')
            if entry.file_size > 16 * 1024 * 1024:
                raise CatalogError('DOCUMENT_LIMIT', 'DOCX 解压内容超出限制')
            xml = ElementTree.fromstring(archive.read(entry))
            return '\n'.join(''.join(node.itertext()) for node in xml.iter()
                             if node.tag.endswith('}p'))
    if extension not in {'.txt', '.md', '.rst', '.csv', '.json', '.yaml', '.yml'}:
        raise CatalogError('DOCUMENT_FORMAT', '支持文本、Markdown、PDF 与 DOCX')
    return raw.decode('utf-8')


class Knowledge:
    def __init__(self, store, data_dir):
        self.store, self.data_dir = store, data_dir

    def list_page(self, workspace_id, kind, page=1, page_size=20, query='', status=''):
        """对项目内容和已关联目录统一分页，不提前加载全部正文。"""
        from memory_center.platform.wiki_sources import WikiSources
        sources = {s['id']: s['name'] for s in WikiSources(self.store).sources()
                   if kind == 'wiki' and s['status'] == 'active' and workspace_id in s['workspace_ids']}
        def field(name):
            return f"payload::jsonb->>'{name}'" if self.store.db.url else f"json_extract(payload,'$.{name}')"
        scope = 'workspace_id=?'
        args = [kind, workspace_id]
        if sources:
            scope += f" OR (workspace_id IN ({','.join('?' for _ in sources)}) AND {field('status')}='active')"
            args.extend(sources)
        predicate = f'kind=? AND ({scope})'
        if status:
            predicate += f" AND {field('status')}=?"
            args.append(status)
        else:
            predicate += f" AND COALESCE({field('status')},'active')!='deleted'"
        if query.strip():
            # LIKE 中的用户通配符按文字匹配，参数绑定防止 SQL 注入。
            pattern = '%' + query.strip().lower().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
            predicate += f" AND (LOWER(COALESCE({field('title')},'')) LIKE ? ESCAPE '!' OR LOWER(COALESCE({field('relative_path')},'')) LIKE ? ESCAPE '!')"
            args.extend([pattern, pattern])
        with self.store.db.connection() as connection:
            if self.store.db.url:
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            total = connection.execute(f'SELECT COUNT(*) FROM records WHERE {predicate}', args).fetchone()[0]
            pages = max(1, math.ceil(total / page_size))
            page = min(page, pages)
            rows = connection.execute(f'SELECT payload FROM records WHERE {predicate} ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?',
                                      (*args, page_size, (page - 1) * page_size)).fetchall()
        items = []
        for row in rows:
            item = json.loads(row[0])
            if item['workspace_id'] in sources:
                item.update(workspace_id=workspace_id, source_name=sources[item['workspace_id']])
            items.append(item)
        return {'items': items, 'total': total, 'page': page, 'page_size': page_size, 'pages': pages}

    def document(self, workspace_id, filename, content, encoding='text'):
        try:
            text = parse_document(filename, content, encoding)
        except CatalogError:
            raise
        except Exception as exc:
            raise CatalogError('DOCUMENT_INVALID', '无法解析文档，请检查格式') from exc
        if not text.strip() or len(text.encode()) > 8 * 1024 * 1024:
            raise CatalogError('DOCUMENT_LIMIT', '文档为空或解析文本超出 8 MiB')
        return self.store.create('document', {'workspace_id': workspace_id, 'title': filename[:200],
                                               'content': text, 'status': 'active',
                                               'hash': hashlib.sha256(text.encode()).hexdigest()})

    def wiki(self, actor, workspace_id, title, content, record_id='', revision=None, refs=None):
        if record_id:
            current = self.store.get('wiki', record_id)
            if current.get('readonly'):
                raise CatalogError('WIKI_READ_ONLY', '目录接入页面只读，请修改来源文件后同步')
            if current['workspace_id'] != workspace_id:
                raise CatalogError('FORBIDDEN', '页面不属于当前空间')
            histories = [*current.get('versions', []), {'revision': current['revision'], 'title': current['title'],
                          'content': current['content'], 'refs': current.get('refs', []), 'editor': current['owner']}]
            return self.store.update('wiki', record_id, {'title': title, 'content': content, 'refs': refs or [],
                                      'versions': histories[-100:], 'owner': actor, 'status': 'active'}, revision)
        return self.store.create('wiki', {'workspace_id': workspace_id, 'owner': actor, 'title': title,
                                         'content': content, 'refs': refs or [], 'versions': [], 'status': 'active'})

    def rollback(self, actor, workspace_id, record_id, revision, target_revision):
        current = self.store.get('wiki', record_id)
        if current['workspace_id'] != workspace_id:
            raise CatalogError('FORBIDDEN', '页面不属于当前空间')
        version = next((v for v in current['versions'] if v['revision'] == target_revision), None)
        if not version:
            raise CatalogError('RECORD_NOT_FOUND', '历史版本不存在')
        return self.wiki(actor, workspace_id, version['title'], version['content'], record_id, revision, version['refs'])

    def memory(self, actor, workspace_id, content, confirmed=False, replaces='', expires_at=''):
        if expires_at:
            try:
                timestamp = datetime.fromisoformat(expires_at)
                if timestamp.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise CatalogError('MEMORY_EXPIRY_INVALID', '过期时间需为包含时区的 ISO 时间') from None
        if replaces:
            previous = self.store.get('memory', replaces)
            if previous['workspace_id'] != workspace_id or previous['owner'] != actor:
                raise CatalogError('FORBIDDEN', '被替代记忆不属于当前主体')
        return self.store.create('memory', {'workspace_id': workspace_id, 'owner': actor, 'title': content[:80],
                          'content': content, 'status': 'confirmed' if confirmed else 'pending',
                          'replaces': replaces, 'expires_at': expires_at})

    def active(self, workspace_id):
        from memory_center.platform.wiki_sources import WikiSources
        result = [('wiki', page) for page in WikiSources(self.store).pages(workspace_id)]
        for kind in ['document', 'wiki', 'memory']:
            with self.store.db.connection() as connection:
                rows = connection.execute('SELECT payload FROM records WHERE kind=? AND workspace_id=? ORDER BY id',
                                          (kind, workspace_id)).fetchall()
            for row in rows:
                item = json.loads(row[0])
                if item['status'] == 'active' or (kind == 'memory' and item['status'] == 'confirmed'):
                    result.append((kind, item))
        return result
