"""停机一致性备份/恢复；恢复只写全新目录，不覆盖历史数据。"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from filelock import FileLock


def backup(data_dir: Path, destination: Path):
    data_dir = data_dir.resolve()
    if destination.resolve().is_relative_to(data_dir):
        raise ValueError('备份文件不能放在服务数据目录内部')
    if destination.exists():
        raise ValueError('备份目标已存在，请选择新文件')
    if not (data_dir / 'admin-token').is_file():
        raise ValueError('不是有效的 5.0 服务目录')
    with FileLock(str(data_dir / 'service.lock'), timeout=0), tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary) / 'snapshot'
        stage.mkdir()
        hashes = {}
        for source in sorted(data_dir.rglob('*')):
            if source.is_symlink():
                raise ValueError('数据目录含软链接，备份中止')
            if not source.is_file() or source.suffix in {'.lock', '.pid'} or source.name.endswith(('-wal', '-shm')):
                continue
            relative = source.relative_to(data_dir)
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix == '.db':
                with sqlite3.connect(source) as original, sqlite3.connect(target) as snapshot:
                    original.backup(snapshot)
            else:
                shutil.copyfile(source, target)
            hashes[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
        (stage / 'backup-manifest.json').write_text(json.dumps({'version': 1, 'files': hashes}), encoding='utf-8')
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
                for source in sorted(stage.rglob('*')):
                    if source.is_file():
                        archive.add(source, arcname=source.relative_to(stage).as_posix(), recursive=False)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def restore(source: Path, destination: Path):
    if destination.exists():
        raise ValueError('恢复目标必须是尚不存在的新目录')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary).resolve() / 'restore'
        stage.mkdir(mode=0o700)
        total = 0
        with tarfile.open(source, 'r:gz') as archive:
            names = set()
            for entry in archive:
                total += entry.size
                if not entry.isfile() or entry.name in names or total > 4 * 1024 ** 3:
                    raise ValueError('备份条目非法或超出恢复预算')
                target = (stage / entry.name).resolve()
                if not target.is_relative_to(stage) or Path(entry.name).is_absolute():
                    raise ValueError('备份含越界路径')
                names.add(entry.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(entry) as content, target.open('xb') as output:
                    shutil.copyfileobj(content, output)
                target.chmod(0o600)
        manifest_path = stage / 'backup-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        if manifest.get('version') != 1 or set(manifest['files']) != names - {'backup-manifest.json'}:
            raise ValueError('备份清单不匹配')
        for name, digest in manifest['files'].items():
            if hashlib.sha256((stage / name).read_bytes()).hexdigest() != digest:
                raise ValueError('备份内容哈希不匹配')
        manifest_path.unlink()
        # 派生 YAML 的旧数据目录位置在新目录下重新定位；源码 root 不更改。
        state = stage / 'platform.db'
        if state.exists():
            with sqlite3.connect(state) as connection:
                rows = connection.execute("SELECT id,payload FROM records WHERE kind='index'").fetchall()
                for record_id, raw in rows:
                    item = json.loads(raw)
                    item['workspace_file'] = str(destination.resolve() / 'workspaces' / item['workspace_id'] /
                                                 'generations' / item['generation'] / 'workspace.yaml')
                    connection.execute('UPDATE records SET payload=? WHERE id=?', (json.dumps(item), record_id))
        os.rename(stage, destination)


def main():
    parser = argparse.ArgumentParser(description='5.0 停机备份与全新目录恢复；PG 另需 pg_dump/pg_restore')
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'backup':
            backup(args.data_dir, args.archive)
        else:
            restore(args.archive, args.data_dir)
    except Exception as exc:
        parser.exit(1, f'操作失败：{exc}\n')
    print('备份完成' if args.action == 'backup' else '恢复完成；请核对源码挂载后启动服务')


if __name__ == '__main__':
    main()
