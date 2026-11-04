"""内容哈希驱动的服务事实增量；旧代际只读，新代际独立可变数据库。"""
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

from memory_center import __version__
from memory_center.core.foundation.catalog import CatalogError

SCHEMA = 1


def source_manifest(root, workspace, digests, owned):
    owners = {str(p): key for key, paths in owned.items() for p in paths}
    entries = {Path(path).relative_to(root).as_posix(): {'hash': digest, 'service': owners.get(path, '')}
               for path, digest in digests.items()}
    config = {'root': str(root), 'services': workspace['services'], 'schema': SCHEMA, 'engine': __version__}
    return {'schema': SCHEMA, 'config': hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(), 'files': entries}


def plan_incremental(previous, current, services):
    if not previous or previous.get('schema') != SCHEMA or previous.get('config') != current['config']:
        return {'mode': 'full', 'reason': '基线缺失或配置／分析器版本变化', 'changed_services': list(services), 'reused_services': [],
                'added_files': len(current['files']), 'modified_files': 0, 'deleted_files': 0, 'changed_paths': list(current['files'])}
    old, new = previous['files'], current['files']
    added, removed = set(new) - set(old), set(old) - set(new)
    changed = {p for p in set(old) & set(new) if old[p] != new[p]}
    paths = sorted(added | removed | changed)
    owners = {row['service'] for p in paths for row in (old.get(p), new.get(p)) if row}
    # 根级共享配置或资料不属于某个服务时保守重算所有服务。
    affected = set(services) if '' in owners else owners
    return {'mode': 'unchanged' if not paths else 'incremental', 'reason': '内容哈希比较',
            'changed_services': sorted(affected), 'reused_services': sorted(set(services) - affected),
            'added_files': len(added), 'modified_files': len(changed), 'deleted_files': len(removed), 'changed_paths': paths}


def seed_facts(previous_dir, directory):
    """复制可变事实库；仅 immutable 分片使用硬链接，绝不硬链接可变 graph.db。"""
    source_db = previous_dir / 'graph' / 'graph.db'
    if not source_db.is_file() or source_db.is_symlink():
        raise ValueError('事实库基线不可用')
    for name in ('index', 'graph'):
        source = previous_dir / name
        if source.is_symlink():
            raise ValueError('事实基线目录含符号链接')
        for path in source.rglob('*'):
            if path.is_symlink():
                raise ValueError('事实基线含符号链接')
            relative = path.relative_to(previous_dir)
            dest = directory / relative
            if path.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            elif path.is_file() and not (path.name.endswith(('.lock', '-wal', '-shm')) or relative == Path('graph/graph.db')):
                dest.parent.mkdir(parents=True, exist_ok=True)
                if relative.parts[:2] == ('index', 'generations'):
                    try:
                        os.link(path, dest)
                    except OSError:
                        shutil.copy2(path, dest)
                else:
                    shutil.copy2(path, dest)
    target_db = directory / 'graph' / 'graph.db'
    target_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f'file:{source_db}?mode=ro', uri=True) as source, sqlite3.connect(target_db) as target:
        source.backup(target)
        if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('事实库基线校验失败')


def load_baseline(store, workspace_id, directory, current, services):
    with store.generation_lock(workspace_id):
        try:
            index = store.get('index', workspace_id)
            previous_dir = Path(index['workspace_file']).parent
            expected = store.db.data_dir / 'workspaces' / workspace_id / 'generations'
            if previous_dir.parent != expected or previous_dir.is_symlink():
                raise ValueError('基线路径不匹配')
            manifest_file = previous_dir / 'source-manifest.json'
            if manifest_file.is_symlink():
                raise ValueError('基线清单含符号链接')
            previous = json.loads(manifest_file.read_text())
            if not isinstance(previous, dict) or not isinstance(previous.get('files'), dict):
                raise ValueError('基线清单无效')
            for path, row in previous['files'].items():
                relative = Path(path)
                if relative.is_absolute() or '..' in relative.parts or not isinstance(row, dict) or not isinstance(row.get('hash'), str) or row.get('service') not in ['', *services]:
                    raise ValueError('基线文件无效')
            plan = plan_incremental(previous, current, services)
            if plan['mode'] != 'full':
                seed_facts(previous_dir, directory)
                plan['baseline_generation'] = index['generation']
            return plan, previous
        except (CatalogError, OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            # 损坏或旧基线回退全量，不让部分复制数据混进新发布。
            for name in ('index', 'graph'):
                if (directory / name).exists():
                    shutil.rmtree(directory / name)
            return plan_incremental(None, current, services), None
