"""Local Spark deployment facts; static manifests never claim machine-local verification."""

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

import psutil
from .faults import check_cancel

ROOT = Path(__file__).resolve().parents[2]
MIN_OLLAMA_VERSION = (0, 34, 1)


def host_runtime_manifest():
    system, architecture = platform.system(), platform.machine().lower()
    normalized = 'arm64' if architecture in ('arm64', 'aarch64') else 'amd64' if architecture in ('amd64','x86_64') else None
    if system == 'Darwin' and normalized == 'arm64':
        return json.loads((ROOT/'models/runtime-macos.json').read_bytes())
    path = ROOT/'models/runtime-platforms.json'
    return json.loads(path.read_bytes()).get(f'{system}-{normalized}') if path.is_file() else None


def runtime_directory(manifest):
    suffix = '' if manifest['platform'] == 'Darwin' else f'-{manifest["platform"].lower()}-{manifest["architecture"]}'
    return ROOT/'runtime'/f'ollama-{manifest["version"]}{suffix}'


def runtime_plan(explicit=None):
    """Describe host capabilities and preparation; never claim installation verification."""
    system, architecture = platform.system(), platform.machine()
    normalized = architecture.lower()
    supported = system in ('Darwin', 'Windows', 'Linux') and normalized in ('arm64', 'aarch64', 'amd64', 'x86_64')
    manifest = host_runtime_manifest()
    pinned = not explicit and manifest is not None and (system == 'Darwin' or runtime_directory(manifest).is_dir())
    candidate = str(Path(explicit).expanduser().resolve()) if explicit else None
    commands = []
    version = None
    if pinned:
        version = manifest['version']
        candidate = str(runtime_directory(manifest) / ('ollama.exe' if system == 'Windows' else 'ollama'))
        commands = ['python scripts/install_model_runtime.py']
    elif not explicit and supported:
        candidate = shutil.which('ollama')
        if not candidate and system == 'Windows':
            local_app_data = os.environ.get('LOCALAPPDATA')
            if local_app_data:
                installed = Path(local_app_data) / 'Programs' / 'Ollama' / 'ollama.exe'
                try:
                    if installed.is_file():
                        candidate = str(installed)
                except OSError:
                    # A protected user-install path must not make the API state
                    # endpoint fail. The runtime remains an unknown candidate.
                    candidate = None
    slug = {'Darwin': 'mac', 'Windows': 'windows', 'Linux': 'linux'}.get(system)
    return {'system': system, 'architecture': architecture,
            'label': f'{"macOS" if system == "Darwin" else system} / {architecture}',
            'start_supported': supported, 'prepare_supported': supported and (manifest is not None or candidate is not None), 'source': 'project_pinned' if pinned else 'explicit' if explicit else 'system',
            'candidate': candidate, 'pinned_version': version, 'minimum_version': '.'.join(map(str, MIN_OLLAMA_VERSION)),
            'install_url': f'https://ollama.com/download/{slug}' if slug else None,
            'install_commands': commands,
            'integrity': '项目包文件大小、SHA-256 与版本' if pinned else '本机可执行性与版本；不宣称包摘要已核验',
            'guidance': ('当前系统／架构不支持页面启动，可连接已有本地服务。' if not supported else
                         '项目固定官方运行包；缺失时执行下方准备命令。' if pinned else
                         '从官方页面安装兼容运行时；自动发现 PATH，Windows 另查用户安装目录。也可填写完整可执行文件路径。')}


def model_manifest(size):
    if size not in ('1.7b','4b'): raise ValueError('Expected official 1.7b or 4b import')
    return json.loads((ROOT/'models'/('manifest-4b.json' if size == '4b' else 'manifest.json')).read_bytes())


def verify_weight(path, manifest, cancel=None):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != manifest['size']: return False
    with path.open('rb') as handle:
        digest = hashlib.sha256()
        while chunk := handle.read(4 * 1024 * 1024):
            check_cancel(cancel)
            digest.update(chunk)
        check_cancel(cancel)
        return digest.hexdigest() == manifest['sha256']


def weight_stamp(path):
    try:
        stat = Path(path).stat()
        return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    except OSError:
        return None


def runtime_cli(explicit=None):
    plan = runtime_plan(explicit)
    if not plan['start_supported']:
        raise ValueError(f'Unsupported local runtime platform: {plan["label"]}')
    if explicit:
        path = Path(explicit).expanduser().resolve()
    elif plan['source'] == 'project_pinned':
        manifest = host_runtime_manifest()
        directory = runtime_directory(manifest)
        receipt_path = directory/'installation.json'
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_bytes())
            if receipt['source'] != manifest: raise ValueError('Pinned runtime installation version mismatch')
            for name,target in receipt['links'].items():
                link = directory/name
                if (not link.is_symlink() or link.readlink().as_posix() != target
                        or not link.resolve().is_relative_to(directory.resolve())):
                    raise ValueError('Installed runtime library link mismatch')
            for name,checksum in receipt['files'].items():
                candidate = (directory/name).resolve()
                if not candidate.is_relative_to(directory.resolve()) or not candidate.is_file():
                    raise ValueError('Runtime installation receipt path invalid')
                with candidate.open('rb') as handle:
                    if hashlib.file_digest(handle,'sha256').hexdigest() != checksum:
                        raise ValueError('Installed runtime SHA-256 mismatch')
            path = (directory/receipt['cli']).resolve()
            if not path.is_relative_to(directory.resolve()): raise ValueError('Runtime CLI path escapes installation')
        else:
            raise ValueError('Install pinned runtime: python scripts/install_model_runtime.py')
    else:
        found = plan['candidate']
        if not found: raise ValueError('Install official Ollama or supply --ollama-exe')
        path = Path(found).resolve()
    if not path.is_file() or (os.name != 'nt' and not os.access(path,os.X_OK)):
        raise ValueError('Ollama executable missing or not executable')
    result = subprocess.run([str(path),'--version'],capture_output=True,text=True,timeout=15,check=False)
    if result.returncode != 0: raise ValueError(f'Ollama executable failed: {result.stderr[-1000:]}')
    versions = re.findall(r'(?:client version is|ollama version is|ollama version|ollama)\s+v?(\d+)\.(\d+)\.(\d+)',
                          result.stdout + '\n' + result.stderr, flags=re.IGNORECASE)
    if not versions or tuple(map(int, versions[-1])) < MIN_OLLAMA_VERSION:
        raise ValueError('Expected Ollama client version >= ' + plan['minimum_version'])
    return path


def resource_snapshot():
    report = {'platform':platform.platform(),'architecture':platform.machine(),
              'disk_free_bytes':shutil.disk_usage(ROOT).free}
    try:
        memory = psutil.virtual_memory(); swap = psutil.swap_memory()
        report.update(memory_total_bytes=memory.total,memory_available_bytes=memory.available,swap_used_bytes=swap.used)
    except (OSError,PermissionError):
        report.update(memory_total_bytes=None,memory_available_bytes=None,swap_used_bytes=None)
    return report


def serving_environment(port):
    if not 1024 <= port <= 65535: raise ValueError('Local port must be 1024..65535')
    environment = os.environ.copy()
    environment.update(OLLAMA_HOST=f'127.0.0.1:{port}',OLLAMA_MODELS=str(ROOT/'models/ollama'),
        OLLAMA_CONTEXT_LENGTH='4096',OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',
        OLLAMA_NO_CLOUD='1',OLLAMA_KEEP_ALIVE='10m')
    return environment


def preflight(size, executable=None, cancel=None):
    manifest = model_manifest(size)
    path = ROOT / 'models' / manifest['file']
    before = weight_stamp(path)
    verified = verify_weight(path, manifest, cancel)
    stamp = weight_stamp(path)
    verified = verified and before == stamp
    check_cancel(cancel)
    cli = None
    error = ''
    try:
        cli = runtime_cli(executable)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        error = str(exc)
    return {'model': manifest['model_name'], 'weight_path': str(path), 'weight_verified': verified,
            'weight_stamp': stamp,
            'expected_weight_sha256': manifest['sha256'], 'runtime_cli': str(cli) if cli else None,
            'runtime_error': error, 'runtime_plan': runtime_plan(executable),
            'resources': resource_snapshot(), 'ready': verified and cli is not None,
            'checked_at': time.time(),
            'scope': 'Deployment readiness only; no inference or factory accuracy validation'}
