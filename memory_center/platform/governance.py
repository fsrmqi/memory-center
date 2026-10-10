"""统一知识治理与 Skill 生命周期；所有写入归服务数据目录。"""
import asyncio
import inspect
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from filelock import FileLock

from memory_center.core.foundation.catalog import CatalogError
from memory_center.platform.assistant import core, skill_catalog
from memory_center.platform.assistant.tools import create_server

ASSISTANT_TOOLS = {'assistant_knowledge', 'assistant_memory', 'assistant_skill', 'assistant_admin'}


class Governance:
    def __init__(self, store, catalog, wiki_sources, data_dir):
        self.store, self.catalog, self.wiki_sources = store, catalog, wiki_sources
        self.base = Path(data_dir) / 'governance'
        self.root = self.base / 'wiki'
        self.candidates = self.base / 'skill-candidates'
        self.published = Path(os.environ.get('MEMORY_CENTER_SKILLS_DIR', str(self.base / 'skills'))).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        registry = self.root / '模块注册表.md'
        if not registry.exists():
            registry.write_text('# 模块注册表\n\n| module | 所属位置 |\n| --- | --- |\n| `system` | `助手规则/` |\n| `personal` | `个人档案/` |\n', encoding='utf-8')
        rules = self.root / '助手规则/最高宪法.md'
        if not rules.exists():
            rules.parent.mkdir(exist_ok=True)
            rules.write_text('# 知识治理规则\n\n区分事实、推断和未决项；写入先预览，确认后执行；保留来源。\n', encoding='utf-8')
        self.index_job = self.base / 'index-job.json'
        self.index_task = None
        self.index_process = None
        self.lock = FileLock(str(self.base / 'governance.lock'), timeout=120)

    def allowed_roots(self):
        return tuple([self.root, *[Path(w['root']) for w in self.catalog.list(1000)['items'] if w['status'] == 'active'],
                      *[Path(s['root']) for s in self.wiki_sources.sources() if s['status'] == 'active']])

    def call(self, tool, parameters, administrator=True):
        if not administrator:
            raise CatalogError('FORBIDDEN', '全局知识与 Skill 管理仅供管理员使用')
        if tool not in ASSISTANT_TOOLS or len(json.dumps(parameters, ensure_ascii=False)) > 1_000_000:
            raise CatalogError('GOVERNANCE_INVALID', '工具或参数预算无效')
        if tool == 'assistant_skill' and parameters.get('action') in {'remove', 'published', 'export', 'read'}:
            try:
                return self.skill_lifecycle(parameters)
            except (core.WikiError, TypeError, ValueError, OSError) as exc:
                raise CatalogError("GOVERNANCE_INVALID", str(exc)) from exc
        indexing = self.index_job.exists() and json.loads(self.index_job.read_text()).get('state') in {'queued', 'running'}
        if indexing and parameters.get('action') in {'initialize', 'index'}:
            return {'status': 'indexing', 'negative_claim_allowed': False}
        # 请求使用当前 catalog 的明确源授权，不接受任意额外路径或候选/发布目录覆盖。
        if parameters.get('workdir'):
            raise CatalogError('GOVERNANCE_INVALID', '提取工作目录由服务管理，请留空')
        with self.lock:
            server = create_server(str(self.root), tuple(str(p) for p in self.allowed_roots()), 'full',
                                   str(self.candidates), str(self.published))
            fn = server._tool_manager.get_tool(tool).fn
            if set(parameters) - set(inspect.signature(fn).parameters):
                raise CatalogError('GOVERNANCE_INVALID', '存在未知参数')
            try:
                result = fn(**parameters)
                if parameters.get('confirm') and tool == 'assistant_memory' and not indexing:
                    core.indexer.build_index(self.root)
                self.store.audit('admin', tool + '.' + str(parameters.get('action', '')))
                return result
            except (core.WikiError, TypeError, ValueError, OSError) as exc:
                raise CatalogError('GOVERNANCE_INVALID', str(exc)) from exc

    def state(self):
        return {'knowledge': core.analyze(self.root), 'skills': skill_catalog.list_candidates(self.candidates),
                'published': self.skill_lifecycle({'action': 'published'}),
                'storage': 'managed_service_data', 'index_job': json.loads(self.index_job.read_text()) if self.index_job.exists() else {'state': 'idle'}, 'source_roots': [str(p) for p in self.allowed_roots()]}

    def skill_lifecycle(self, parameters):
        action, name = parameters['action'], parameters.get('name', '')
        with self.lock:
            if action == 'published':
                items = []
                for p in sorted(self.published.glob('*/SKILL.md'))[:1000]:
                    if p.is_symlink() or p.parent.is_symlink():
                        continue
                    manifest = p.parent / 'publication.json'
                    items.append({'name': p.parent.name, 'status': '已启用',
                                  'publication': json.loads(manifest.read_text()) if manifest.exists() else None})
                return {'items': items}
            if action == 'read':
                # 读取候选或已发布 Skill 的正文与文件清单；名称经 _safe_name 校验防路径穿越，
                # 目录/文件一律拒绝符号链接，正文总量设上限并以显式错误失败而非静默截断。
                published = bool(parameters.get('published'))
                target_root = self.published if published else self.candidates
                path = target_root / skill_catalog._safe_name(name)
                if not path.is_dir() or path.is_symlink():
                    raise CatalogError('SKILL_NOT_FOUND', 'Skill 不存在')
                body_path = path / 'SKILL.md'
                if not body_path.is_file() or body_path.is_symlink():
                    raise CatalogError('SKILL_NOT_FOUND', 'Skill 不存在')
                files, total = {}, 0
                for item in sorted(path.rglob('*')):
                    if not item.is_file() or item.is_symlink():
                        continue
                    try:
                        text = item.read_text(encoding='utf-8')
                    except (OSError, UnicodeDecodeError):
                        continue
                    total += len(text)
                    if total > 200_000:
                        raise CatalogError('SKILL_READ_TOO_LARGE', 'Skill 内容超过 200000 字符上限')
                    files[item.relative_to(path).as_posix()] = text
                manifest = path / 'publication.json'
                publication = None
                if manifest.is_file() and not manifest.is_symlink():
                    try:
                        publication = json.loads(manifest.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        publication = None
                return {'name': name, 'published': published, 'body': files.get('SKILL.md', ''),
                        'files': files, 'publication': publication}
            path = self.candidates / skill_catalog._safe_name(name)
            if action == 'export':
                skill_catalog.inspect_candidate(self.candidates, name)
                return {'name': name, 'files': {p.relative_to(path).as_posix(): p.read_text(encoding='utf-8')
                        for p in path.rglob('*') if p.is_file() and not p.is_symlink()}}
            if action == 'remove':
                if parameters.get('published'):
                    path = self.published / skill_catalog._safe_name(name)
                if not path.is_dir() or path.is_symlink():
                    raise CatalogError('SKILL_NOT_FOUND', 'Skill 不存在')
                if not parameters.get('confirm'):
                    return {'name': name, 'status': '需要确认', 'action': 'remove'}
                trash = self.base / 'trash'
                trash.mkdir(exist_ok=True)
                target = Path(tempfile.mkdtemp(prefix=name + '-', dir=trash)) / name
                shutil.move(str(path), str(target))
                self.store.audit('admin', 'skill.remove', record_id=name)
                return {'name': name, 'status': '已移除', 'recoverable': True}
            raise CatalogError('SKILL_ACTION_INVALID', '未知管理动作')

    def import_source(self, source_id, confirm=False):
        source = self.store.get('wiki_source', source_id)
        if source['status'] != 'active':
            raise CatalogError('WIKI_SOURCE_PAUSED', '来源已暂停')
        root = Path(source['root'])
        if not root.is_dir() or root.is_symlink():
            raise CatalogError('WIKI_ROOT_UNAVAILABLE', '来源目录不可读取')
        # 保留原相对结构，导入仅复制文档，原目录不改动；预览与执行均重新核对预算。
        files, total = [], 0
        for parent, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'node_modules', 'vendor', 'build', 'dist'}
                       and not (Path(parent) / d).is_symlink()]
            for name in names:
                path = Path(parent) / name
                if path.is_symlink() or name.startswith('.') or path.suffix.lower() not in core.ALLOWED_ARCHIVE_SUFFIXES:
                    continue
                total += path.stat().st_size
                files.append(path)
                if len(files) > 20000 or total > 5 * 1024 * 1024 * 1024:
                    raise CatalogError('IMPORT_BUDGET', '导入上限 20000 个文档、5 GiB')
        result = {'source_id': source_id, 'files': len(files), 'bytes': total, 'confirmed': confirm}
        if not confirm:
            return dict(result, status='需要确认')
        with self.lock:
            # 文件已存在且内容不同则整体拒绝；模板初始文件可被首次真实来源替换。
            receipt = self.base / 'import-receipt.json'
            if receipt.exists():
                raise CatalogError('IMPORT_EXISTS', '完整 Wiki 已迁入；外部增量请继续使用 Wiki 目录同步')
            stage = Path(tempfile.mkdtemp(prefix='.wiki-import-', dir=self.base))
            try:
                for path in files:
                    target = stage / path.relative_to(root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                for existing in self.root.rglob('*'):
                    if existing.is_file() and existing.relative_to(self.root).as_posix() not in {'模块注册表.md', '助手规则/最高宪法.md'}:
                        raise CatalogError('IMPORT_NOT_EMPTY', '受管 Wiki 已有新内容，请先处理后导入')
                for template in ['模块注册表.md', '助手规则/最高宪法.md']:
                    if not (stage / template).exists():
                        (stage / template).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(self.root / template, stage / template)
                backup = self.base / '.wiki-before-import'
                os.replace(self.root, backup)
                try:
                    os.replace(stage, self.root)
                except OSError:
                    os.replace(backup, self.root)
                    raise
                shutil.rmtree(backup)
                receipt.write_text(json.dumps(result, ensure_ascii=False))
                core.indexer.build_index(self.root, defer_binary=True)
                pending = core.indexer.index_stats(self.root)['by_extractor'].get('pending', 0)
                self.index_job.write_text(json.dumps({'state': 'queued' if pending else 'ready', 'pending': pending}))
                self.store.audit('admin', 'wiki.import', record_id=source_id)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        return dict(result, status='已迁入')

    async def start(self):
        self.index_task = asyncio.create_task(self._index_loop())

    async def close(self):
        self.index_task.cancel()
        if self.index_process and self.index_process.returncode is None:
            self.index_process.terminate()
            try:
                await asyncio.wait_for(self.index_process.wait(), 5)
            except TimeoutError:
                self.index_process.kill()
                await self.index_process.wait()
            self.index_job.write_text(json.dumps({'state': 'queued'}))
        try:
            await self.index_task
        except asyncio.CancelledError:
            pass

    async def _index_loop(self):
        while True:
            if self.index_job.exists() and json.loads(self.index_job.read_text()).get('state') in {'queued', 'running'}:
                self.index_job.write_text(json.dumps({'state': 'running'}))
                script = ('import sys; from pathlib import Path; from filelock import FileLock; '
                          'from memory_center.platform.assistant.indexer import build_index; '
                          'root=Path(sys.argv[1]); '
                          'lock=FileLock(str(root.parent/"attachment-index.lock")); '
                          'lock.acquire(); build_index(root); lock.release()')
                with (self.base / 'index-worker.log').open('w') as log:
                    self.index_process = await asyncio.create_subprocess_exec(
                        sys.executable, '-c', script, str(self.root), stdout=log, stderr=log)
                    code = await self.index_process.wait()
                self.index_job.write_text(json.dumps({'state': 'ready' if code == 0 else 'failed', 'exit_code': code}))
            await asyncio.sleep(2)
