"""Explicit retention and portable snapshots of application-owned workspace data."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import time
import uuid
from zipfile import ZipFile, ZIP_DEFLATED

from src.datasets import digest, file_digest
from src.storage import EvidenceStore, restore_evidence
from src.acquisition import write_json

DATA_DIRECTORIES = ('datasets', 'acquisition', 'inspection-results', 'review-studies')
MAX_FILES = 50000
MAX_BYTES = 20 * 1024**3


def managed_paths(database):
    database = Path(database).resolve()
    return [*(database.parent / name for name in DATA_DIRECTORIES),
            database.with_name(database.name + '-model.json'),
            database.with_name(database.name + '-vision-models'),
            database.parent / 'archives']


def workspace_inventory(database):
    files = []
    for root in managed_paths(database):
        if root.is_symlink(): raise ValueError('受管目录包含符号链接，须先将数据移入真实目录再备份')
        if not root.exists(): continue
        for path in root.rglob('*') if root.is_dir() else [root]:
            if path.is_symlink(): raise ValueError('受管数据包含符号链接，不能创建完整工作空间备份')
            if path.is_file(): files.append(path)
    if len(files) > MAX_FILES: raise ValueError('工作空间文件数超过备份上限 50000')
    total = sum(p.stat().st_size for p in files)
    if total > MAX_BYTES: raise ValueError('受管文件超过单次备份上限 20 GiB，请先归档到独立存储')
    return files, total


def backup_workspace(store, destination):
    """Called only while API writes/capture/model tasks are reserved inactive."""
    database = store.path.resolve()
    files, total = workspace_inventory(database)
    if total + database.stat().st_size > MAX_BYTES: raise ValueError('工作空间超过单次备份 20 GiB 上限')
    stamps = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in files}
    destination = Path(destination)
    with tempfile.TemporaryDirectory(prefix='spark-snapshot-') as temporary:
        snapshot = Path(temporary) / database.name
        store.backup(snapshot)
        manifest = {'schema_version': 1, 'database': database.name, 'created': time.time(),
                    'scope': '会话数据库、受管数据集、采集留存、上游结果、复核研究、视觉资产、模型配置及旧会话归档',
                    'excluded': ['项目源码与 Python/Node 依赖', '外部原始数据和视频', '官方语言模型 GGUF 缓存与 Ollama 运行时/驻留库', '进程 PID、运行日志和浏览器草稿'],
                    'files': {}}
        with ZipFile(destination, 'x', compression=ZIP_DEFLATED, compresslevel=1) as archive:
            for path in [snapshot, *files]:
                relative = database.name if path == snapshot else path.relative_to(database.parent).as_posix()
                checksum, length = hashlib.sha256(), 0
                with path.open('rb') as stream, archive.open('workspace/' + relative, 'w', force_zip64=True) as output:
                    while chunk := stream.read(1024**2):
                        checksum.update(chunk); length += len(chunk); output.write(chunk)
                manifest['files'][relative] = {'sha256': checksum.hexdigest(), 'bytes': length}
            current, _ = workspace_inventory(database)
            if set(current) != set(files) or any((p.stat().st_size, p.stat().st_mtime_ns) != stamps[p] for p in files):
                raise RuntimeError('备份期间受管文件发生变化，未发布备份；请暂停其他终端写入后重试')
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, allow_nan=False))
    return manifest


def restore_workspace(source, destination):
    """Extract into an exclusive new directory, validate all hashes before use."""
    destination = Path(destination).expanduser().resolve()
    if destination.exists(): raise ValueError('恢复目标已存在；请选择不存在的新工作空间目录')
    with ZipFile(source) as archive:
        if len(archive.infolist()) > MAX_FILES + 2: raise ValueError('备份文件数超过上限')
        if len(set(archive.namelist())) != len(archive.namelist()): raise ValueError('备份包含重复路径')
        if archive.getinfo('manifest.json').file_size > 16 * 1024**2: raise ValueError('备份清单过大')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), dict): raise ValueError('工作空间备份版本或清单无效')
        name = manifest['database']
        if not isinstance(name, str) or Path(name).name != name or any(c in name for c in '\\:/\0') or name in ('', '.', '..', 'manifest.json'): raise ValueError('备份数据库名称无效')
        expected = {'manifest.json', *('workspace/' + p for p in manifest['files'])}
        if set(archive.namelist()) != expected or name not in manifest['files']: raise ValueError('备份清单与实际文件不一致')
        total = 0
        for relative, record in manifest['files'].items():
            path = PurePosixPath(relative)
            allowed = (*DATA_DIRECTORIES, 'archives', name + '-vision-models', name + '-model.json', name)
            if path.is_absolute() or '..' in path.parts or '\\' in relative or not path.parts or path.parts[0] not in allowed:
                raise ValueError('备份路径越界')
            info = archive.getinfo('workspace/' + relative)
            if ((info.external_attr >> 16) & 0o170000) == 0o120000: raise ValueError('备份包含符号链接')
            if info.file_size != record['bytes']: raise ValueError('备份文件大小不一致')
            total += info.file_size
        if total > MAX_BYTES: raise ValueError('备份解压后超过 20 GiB 上限')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(destination.parent).free < total + 64 * 1024**2: raise ValueError('恢复目标磁盘空间不足')
        destination.mkdir()  # Exclusive creation; never overwrite or attach an existing workspace.
        try:
            for relative, record in manifest['files'].items():
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open('workspace/' + relative) as stream, target.open('xb') as output:
                    shutil.copyfileobj(stream, output, 1024**2)
                if file_digest(target) != record['sha256']: raise ValueError('备份文件摘要不一致')
            with closing(sqlite3.connect(destination / name)) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('恢复数据库完整性检查失败')
            # Reuse evidence validation, including JSON and schema checks.
            check = destination / '.verified.sqlite'
            restore_evidence(destination / name, check); check.unlink()
            config = destination / (name + '-model.json')
            if config.is_file():
                settings = json.loads(config.read_bytes())
                settings.setdefault('policy', {}).update(autostart=False, auto_restart=False)
                write_json(config, settings)
            write_json(destination / 'restoration.json', {'source_manifest': manifest, 'restored': time.time(),
                'runtime': 'inactive; external executable/cache paths must be checked on destination device',
                'automatic_model_actions_disabled': True})
        except Exception:
            shutil.rmtree(destination)
            raise
    return {'database': str(destination / name), 'source_preserved': True, 'files': len(manifest['files']),
            'excluded': manifest['excluded'], 'automatic_model_actions_disabled': True}


def retention_preview(store, current_session, before, keep_latest):
    with store.connect() as db:
        rows = db.execute('SELECT session,MIN(created),MAX(created),COUNT(*),MAX(id),SUM(LENGTH(payload)) FROM events GROUP BY session ORDER BY MAX(created) DESC,session').fetchall()
    protected = {r[0] for r in rows[:keep_latest]} | {current_session}
    selected = [{'session': r[0], 'started': r[1], 'last_event': r[2], 'count': r[3], 'revision': r[4], 'payload_bytes': r[5]}
                for r in rows if r[0] not in protected and r[2] < before]
    return {'sessions': selected, 'token': digest({'sessions': selected, 'current': current_session, 'before': before, 'keep_latest': keep_latest}),
            'events': sum(r['count'] for r in selected), 'payload_bytes': sum(r['payload_bytes'] for r in selected),
            'protected_current': current_session, 'keep_latest': keep_latest, 'before': before}


def archive_sessions(store, preview):
    if not preview['sessions']: raise ValueError('当前保留规则没有可归档的旧会话')
    root = store.path.parent / 'archives'
    if root.is_symlink(): raise ValueError('归档目录不能是符号链接')
    root.mkdir(exist_ok=True)
    target = root / (uuid.uuid4().hex + '.sqlite')
    archive = EvidenceStore(target)
    try:
        with store.connect() as source, archive.connect() as output:
            source.execute('BEGIN IMMEDIATE')
            for record in preview['sessions']:
                session = record['session']
                counts = source.execute('SELECT COUNT(*),MAX(id),MAX(created) FROM events WHERE session=?', (session,)).fetchone()
                if counts != (record['count'], record['revision'], record['last_event']): raise RuntimeError('会话在预览后发生变化，请重新预览')
                for rows in source.execute('SELECT id,session,kind,created,payload FROM events WHERE session=? ORDER BY id', (session,)):
                    output.execute('INSERT INTO events VALUES (?,?,?,?,?)', rows)
            output.commit()
            output.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            if output.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise RuntimeError('归档完整性检查失败')
            count = output.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            if count != preview['events']: raise RuntimeError('归档数量不一致')
            # Verify content, not only row count, before removing any active evidence.
            # Sessions can have interleaved ids; compare each session independently.
            for record in preview['sessions']:
                def content(db):
                    checksum = hashlib.sha256()
                    for row in db.execute('SELECT * FROM events WHERE session=? ORDER BY id', (record['session'],)):
                        checksum.update(json.dumps(row, ensure_ascii=False).encode())
                    return checksum.hexdigest()
                if content(source) != content(output): raise RuntimeError('归档内容不一致')
            with target.open('r+b') as stream: os.fsync(stream.fileno())
            write_json(target.with_suffix('.json'), {'schema_version': 1, 'preview': preview, 'created': time.time(), 'sha256': file_digest(target)})
            for record in preview['sessions']: source.execute('DELETE FROM events WHERE session=?', (record['session'],))
    except Exception:
        # A verified archive remains recoverable even if final deletion fails.
        if not target.with_suffix('.json').exists(): target.unlink(missing_ok=True)
        raise
    return {'archive': str(target), 'events': preview['events'], 'sessions': len(preview['sessions']),
            'scope': '旧会话已归档；活动数据库空页可复用，归档保留原图和记录，受管数据/模型不清理'}


def compact_store(store):
    deadline = time.monotonic() + 60
    with store.connect() as db:
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        db.execute('VACUUM')
    return store.storage_info()
