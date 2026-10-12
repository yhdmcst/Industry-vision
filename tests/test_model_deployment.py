import hashlib
import io
import json
from pathlib import Path
import tarfile

import pytest

from src.llm.preparation import unpack
from src.llm import deployment
from src.llm.deployment import preflight


def archive_fixture(tmp_path,link='libactual.dylib'):
    path = tmp_path/'runtime.tgz'
    with tarfile.open(path,'w:gz') as archive:
        for name,data in [('ollama',b'executable'),('libactual.dylib',b'library')]:
            member = tarfile.TarInfo(name); member.size = len(data); member.mode = 0o755
            archive.addfile(member,io.BytesIO(data))
        member = tarfile.TarInfo('libalias.dylib'); member.type = tarfile.SYMTYPE; member.linkname = link
        archive.addfile(member)
    manifest = {'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return path,manifest


def test_pinned_runtime_unpacks_only_verified_bytes_and_contained_libraries(tmp_path):
    path,manifest = archive_fixture(tmp_path)
    output = tmp_path/'installed'
    executable = unpack(path,output,manifest)
    assert executable.read_bytes() == b'executable'
    assert (output/'libalias.dylib').is_symlink()
    assert (output/'libalias.dylib').read_bytes() == b'library'
    receipt = json.loads((output/'installation.json').read_bytes())
    assert receipt['links'] == {'libalias.dylib':'libactual.dylib'}
    with pytest.raises(ValueError,match='exists'): unpack(path,output,manifest)
    manifest['sha256'] = 'bad'
    with pytest.raises(ValueError,match='SHA'): unpack(path,tmp_path/'bad',manifest)
    assert not (tmp_path/'bad').exists()


@pytest.mark.parametrize('link',['/private/escape','../escape','missing-library.dylib'])
def test_runtime_rejects_library_escape_and_cleans_partial_install(tmp_path,link):
    path,manifest = archive_fixture(tmp_path,link)
    with pytest.raises(ValueError,match='link'): unpack(path,tmp_path/'bad',manifest)
    assert not (tmp_path/'bad').exists() and not list(tmp_path.glob('.ollama-install-*'))


def test_local_preflight_uses_bytes_instead_of_static_verified_flag(tmp_path,monkeypatch):
    root = tmp_path/'project'; (root/'models').mkdir(parents=True)
    data = b'official fixture bytes'
    manifest = {'file':'weights.gguf','size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                'model_name':'spark-drift:4b-q4','verified':True}
    (root/'models/manifest-4b.json').write_text(json.dumps(manifest))
    (root/'models/runtime-macos.json').write_bytes((deployment.ROOT/'models/runtime-macos.json').read_bytes())
    monkeypatch.setattr(deployment,'ROOT',root)
    monkeypatch.setattr(deployment,'runtime_cli',lambda executable:Path('/fixture/ollama'))
    missing = preflight('4b')
    assert not missing['ready'] and not missing['weight_verified']
    (root/'models/weights.gguf').write_bytes(data)
    assert preflight('4b')['ready']
    (root/'models/weights.gguf').write_bytes(b'x'*len(data))
    assert not preflight('4b')['weight_verified']
    with pytest.raises(ValueError): deployment.model_manifest('other')


def test_serving_environment_keeps_other_process_settings_private(monkeypatch):
    monkeypatch.setenv('OLLAMA_HOST','0.0.0.0:1234')
    environment = deployment.serving_environment(11435)
    assert environment['OLLAMA_HOST'] == '127.0.0.1:11435'
    assert environment['OLLAMA_NO_CLOUD'] == '1'
    assert environment['OLLAMA_NUM_PARALLEL'] == environment['OLLAMA_MAX_LOADED_MODELS'] == '1'
    assert environment['OLLAMA_CONTEXT_LENGTH'] == '4096'
    import os
    assert os.environ['OLLAMA_HOST'] == '0.0.0.0:1234'
    with pytest.raises(ValueError): deployment.serving_environment(80)


def test_launcher_refuses_occupied_port_without_starting_a_process(monkeypatch):
    import socket
    from src.llm import runtime
    monkeypatch.setattr(runtime, 'preflight', lambda *a: {'ready': True})
    def unexpected(*a, **kw): raise AssertionError('Existing service must never be taken over')
    monkeypatch.setattr(runtime.subprocess, 'Popen', unexpected)
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0)); occupied.listen()
        with pytest.raises(OSError): runtime.OwnedRuntime(Path('/unused')).start('4b', occupied.getsockname()[1])


def test_inference_failure_never_reuses_previous_raw_answer():
    import httpx
    from src.llm.spark_client import SparkXClient
    client = SparkXClient(); client._initialized = True
    client.details = {'family': 'spark2_5'}
    client.last_response = 'prior valid answer'
    client.last_metrics = {'output_tokens': 123}
    def fail(*a, **kw): raise httpx.ConnectError('transport failure fixture')
    client._request = fail
    with pytest.raises(RuntimeError, match='transport failure'): client.generate('new request')
    assert client.last_response == '' and 'output_tokens' not in client.last_metrics
    assert client.last_metrics['error'] and client.last_metrics['elapsed_ms'] >= 0


@pytest.mark.parametrize('system,architecture', [('Windows', 'AMD64'), ('Linux', 'x86_64'), ('Linux', 'aarch64'), ('Darwin', 'x86_64')])
def test_system_runtime_discovery_and_guidance_are_platform_specific(tmp_path, monkeypatch, system, architecture):
    from types import SimpleNamespace
    executable = tmp_path / 'installed ollama'; executable.write_bytes(b'fixture'); executable.chmod(0o755)
    monkeypatch.setattr(deployment.platform, 'system', lambda: system)
    monkeypatch.setattr(deployment.platform, 'machine', lambda: architecture)
    monkeypatch.setattr(deployment.shutil, 'which', lambda name: str(executable))
    monkeypatch.setattr(deployment.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout='ollama version is 0.40.2', stderr=''))
    plan = deployment.runtime_plan()
    assert plan['start_supported'] and plan['source'] == 'system' and not plan['install_commands']
    assert plan['install_url'].endswith({'Windows': 'windows', 'Linux': 'linux', 'Darwin': 'mac'}[system])
    assert deployment.runtime_cli() == executable
    assert 'SHA-256' not in plan['integrity']


def test_windows_user_install_is_found_without_path(tmp_path, monkeypatch):
    executable = tmp_path / 'Programs/Ollama/ollama.exe'; executable.parent.mkdir(parents=True); executable.touch()
    monkeypatch.setattr(deployment.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(deployment.platform, 'machine', lambda: 'AMD64')
    monkeypatch.setattr(deployment.shutil, 'which', lambda name: None)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert deployment.runtime_plan()['candidate'] == str(executable)


def test_protected_windows_user_install_does_not_break_runtime_plan(tmp_path, monkeypatch):
    executable = tmp_path / 'Programs/Ollama/ollama.exe'
    original = Path.is_file
    def is_file(path):
        if path == executable:
            raise PermissionError('protected user-install path')
        return original(path)
    monkeypatch.setattr(Path, 'is_file', is_file)
    monkeypatch.setattr(deployment.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(deployment.platform, 'machine', lambda: 'AMD64')
    monkeypatch.setattr(deployment.shutil, 'which', lambda name: None)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    plan = deployment.runtime_plan()
    assert plan['start_supported'] and plan['candidate'] is None
    assert plan['source'] == 'system'


def test_pinned_macos_plan_and_explicit_override_have_distinct_integrity(monkeypatch, tmp_path):
    monkeypatch.setattr(deployment.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(deployment.platform, 'machine', lambda: 'arm64')
    pinned = deployment.runtime_plan()
    assert pinned['source'] == 'project_pinned' and pinned['install_commands'] == ['python scripts/install_model_runtime.py']
    assert 'SHA-256' in pinned['integrity']
    explicit = deployment.runtime_plan(tmp_path / 'custom ollama')
    assert explicit['source'] == 'explicit' and not explicit['install_commands']
    assert 'SHA-256' not in explicit['integrity']


@pytest.mark.parametrize('version', ['ollama version is 0.33.0', 'unexpected output'])
def test_runtime_rejects_old_or_unknown_client_versions(tmp_path, monkeypatch, version):
    from types import SimpleNamespace
    executable = tmp_path / 'ollama'; executable.touch(); executable.chmod(0o755)
    monkeypatch.setattr(deployment.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=version, stderr=''))
    with pytest.raises(ValueError, match='>= 0.34.1'): deployment.runtime_cli(executable)


def test_unsupported_platform_has_no_macos_install_instruction(monkeypatch):
    monkeypatch.setattr(deployment.platform, 'system', lambda: 'FreeBSD')
    monkeypatch.setattr(deployment.platform, 'machine', lambda: 'x86_64')
    plan = deployment.runtime_plan()
    assert not plan['start_supported'] and plan['install_url'] is None and not plan['install_commands']
    with pytest.raises(ValueError, match='Unsupported'): deployment.runtime_cli()
