"""Verified, resumable local asset preparation shared by UI and CLI."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import zipfile
import httpx
from src.acquisition import write_json
from . import deployment
from .deployment import verify_weight
from .faults import check_cancel, ModelFault


def file_sha(path, cancel=None):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(1024**2):
            check_cancel(cancel); digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def asset_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        try:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ModelFault('asset_busy', '部署文件正被另一个操作使用', '等待另一工作台或下载完成后重试。') from exc
        try: yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def download_asset(manifest, target, cancel=None, progress=lambda value: None, params=None):
    target = Path(target)
    with asset_lock(target.with_name(target.name+'.lock')):
        check_cancel(cancel)
        if target.exists():
            if verify_weight(target, manifest, cancel): return target
            raise ModelFault('integrity', '已有部署文件校验失败', '请在维护详情确认文件路径，将损坏文件移走后重试；工作台不会覆盖它。', str(target))
        part = target.with_name(target.name+'.part')
        offset = part.stat().st_size if part.exists() else 0
        if offset > manifest['size']: part.unlink(); offset = 0
        reserve = max(0, manifest['size']-offset) + 64*1024**2
        if shutil.disk_usage(target.parent).free < reserve:
            raise ModelFault('disk_full', '下载空间不足', '释放磁盘空间后重试。')
        if offset < manifest['size']:
            with httpx.Client(follow_redirects=True, timeout=30, trust_env=False) as client:
                headers = {'Range':f'bytes={offset}-'} if offset else {}
                with client.stream('GET', manifest['url'], params=params, headers=headers) as response:
                    response.raise_for_status()
                    if response.status_code == 206:
                        expected = f'bytes {offset}-{manifest["size"]-1}/{manifest["size"]}'
                        if response.headers.get('content-range') != expected:
                            raise ModelFault('range_mismatch','下载续传响应不匹配','重试下载；已有片段保留。')
                    elif response.status_code == 200: offset = 0
                    else: raise ValueError('Unsupported download response')
                    with part.open('ab' if offset else 'wb') as handle:
                        for chunk in response.iter_bytes(1024**2):
                            check_cancel(cancel)
                            if offset+len(chunk)>manifest['size']: raise ValueError('Download exceeds expected size')
                            handle.write(chunk); offset += len(chunk)
                            progress({'phase':'下载', 'completed_bytes':offset, 'total_bytes':manifest['size']})
        progress({'phase':'完整性校验', 'completed_bytes':offset, 'total_bytes':manifest['size']})
        if not verify_weight(part, manifest, cancel):
            part.unlink(missing_ok=True)
            raise ModelFault('integrity', '下载文件校验失败', '未发布此文件；请重新下载。')
        check_cancel(cancel)
        if target.exists(): raise RuntimeError('Deployment target appeared during download')
        part.replace(target)
        return target


class ZipArchive:
    def __init__(self, path): self.zip = zipfile.ZipFile(path)
    def __iter__(self):
        for entry in self.zip.infolist():
            item = tarfile.TarInfo(entry.filename); item.size = entry.file_size
            item.type = tarfile.DIRTYPE if entry.is_dir() else tarfile.REGTYPE
            mode = entry.external_attr >> 16
            if mode & 0o170000 == 0o120000: raise ValueError('Zip symlinks unsupported')
            item.mode = 0o755
            yield item
    def extractfile(self, item): return self.zip.open(item.name)


@contextmanager
def open_archive(path, manifest):
    if manifest.get('url','').endswith('.zip'):
        archive = ZipArchive(path)
        try: yield archive
        finally: archive.zip.close()
    elif manifest.get('url','').endswith('.zst'):
        import zstandard
        with path.open('rb') as handle, zstandard.ZstdDecompressor().stream_reader(handle) as stream, tarfile.open(fileobj=stream,mode='r|') as archive:
            yield archive
    else:
        with tarfile.open(path,'r:gz') as archive: yield archive


def unpack(archive_path, output, manifest, cancel=None):
    if output.exists(): raise ValueError('Runtime installation exists; preserve it')
    if archive_path.stat().st_size != manifest['size']:
        raise ValueError('Official runtime archive size mismatch')
    if not verify_weight(archive_path, manifest, cancel):
            raise ValueError('Official runtime archive SHA-256 mismatch')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ollama-install-',dir=output.parent) as temporary, open_archive(archive_path, manifest) as archive:
        root = Path(temporary)/'runtime'; root.mkdir()
        members = archive
        expanded = 0
        count = 0
        names = set()
        links = []
        for member in members:
            check_cancel(cancel)
            count += 1; expanded += member.size
            if count > 10000 or expanded > 8 * 1024**3: raise ValueError('Runtime expanded resource limit')
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or '\\' in member.name or ':' in member.name or path.as_posix().casefold() in names:
                raise ValueError('Unsafe or duplicate runtime member')
            names.add(path.as_posix().casefold())
            if not path.parts: continue
            destination = root.joinpath(*path.parts)
            if member.isdir(): destination.mkdir(parents=True,exist_ok=True)
            elif member.isfile():
                if shutil.disk_usage(root).free < member.size + 64*1024**2: raise ModelFault('disk_full','安装空间不足','释放磁盘空间后重试。')
                destination.parent.mkdir(parents=True,exist_ok=True)
                with destination.open('wb') as target:
                    with archive.extractfile(member) as source:
                        while data := source.read(1024**2):
                            check_cancel(cancel)
                            target.write(data)
                destination.chmod(member.mode & 0o755)
            elif member.issym():
                target = PurePosixPath(member.linkname)
                if target.is_absolute() or '..' in target.parts or '\\' in member.linkname:
                    raise ValueError('Unsafe runtime link')
                links.append((destination,member.linkname))
            else:
                raise ValueError('Runtime archive special entries are unsupported')
        for destination,target in links:
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.symlink_to(target)
        for destination,_ in links:
            if not destination.resolve().is_relative_to(root.resolve()) or not destination.is_file():
                raise ValueError('Runtime link escapes installation or has no regular target')
        candidates = list(root.rglob('ollama')) + list(root.rglob('ollama.exe'))
        candidates = [p for p in candidates if p.is_file()]
        if len(candidates) != 1: raise ValueError('Expected one official Ollama CLI')
        cli = candidates[0].relative_to(root).as_posix()
        write_json(root/'installation.json',{'source':manifest,'cli':cli,
            'files':{p.relative_to(root).as_posix():file_sha(p, cancel)
                     for p in root.rglob('*') if p.is_file() and not p.is_symlink()},
            'links':{p.relative_to(root).as_posix():target for p,target in links}})
        check_cancel(cancel)
        if output.exists(): raise ValueError('Runtime output appeared during installation')
        root.rename(output)
    return output/cli



def install_runtime(cancel=None, progress=lambda value:None):
    manifest = deployment.host_runtime_manifest()
    if manifest is None: raise ValueError('当前主机不支持项目内安装，请使用官方运行时。')
    output = deployment.runtime_directory(manifest)
    with asset_lock(output.with_name(output.name+'.lock')):
        if output.exists(): return deployment.runtime_cli()
        cache = deployment.ROOT/'runtime/downloads'/manifest['sha256']
        archive = download_asset(manifest, cache/Path(manifest['url']).name, cancel, progress)
        progress({'phase':'安装运行时'})
        return unpack(archive, output, manifest, cancel)


def prepare_model(size, executable=None, cancel=None, progress=lambda value:None):
    manifest = deployment.model_manifest(size)
    params = {'Revision':manifest['revision'],'FilePath':Path(manifest['file']).name}
    download_asset({**manifest,'url':'https://www.modelscope.cn/api/v1/models/'+manifest['repository']+'/repo'},
                   deployment.ROOT/'models'/manifest['file'], cancel, progress, params)
    check_cancel(cancel)
    try: deployment.runtime_cli(executable)
    except (ValueError, OSError):
        if executable: raise
        install_runtime(cancel, progress)
    progress({'phase':'部署检查'})
    return deployment.preflight(size, executable, cancel)
