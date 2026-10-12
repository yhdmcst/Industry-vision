import hashlib
import io
import json
import threading
import tarfile
import zipfile
import httpx
import pytest
from src.llm import preparation, deployment
from src.llm.faults import OperationCancelled, ModelFault


def manifest(data): return {'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'url':'https://official.invalid/file'}


REAL_CLIENT = httpx.Client

def mock_http(monkeypatch, responder):
    original = REAL_CLIENT
    monkeypatch.setattr(preparation.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(responder), **kw))


@pytest.mark.parametrize('resume_response',[200,206])
def test_resume_or_safe_full_restart(tmp_path, monkeypatch, resume_response):
    data = b'official bytes'
    target = tmp_path/'weight'; target.with_name('weight.part').write_bytes(data[:4])
    def response(request):
        assert request.headers['Range'] == 'bytes=4-'
        return httpx.Response(resume_response, content=data[4:] if resume_response==206 else data,
                              headers={'content-range':f'bytes 4-{len(data)-1}/{len(data)}'})
    mock_http(monkeypatch,response)
    preparation.download_asset(manifest(data),target)
    assert target.read_bytes()==data and not target.with_name('weight.part').exists()


def test_range_mismatch_preserves_partial_and_never_publishes(tmp_path, monkeypatch):
    target = tmp_path/'weight'; part=tmp_path/'weight.part'; part.write_bytes(b'abc')
    mock_http(monkeypatch,lambda r:httpx.Response(206, content=b'new',headers={'content-range':'bytes 1-3/9'}))
    with pytest.raises(ModelFault, match='不匹配'): preparation.download_asset(manifest(b'abcdefghi'),target)
    assert part.read_bytes()==b'abc' and not target.exists()


def test_cancel_preserves_partial_and_lock_can_be_reused(tmp_path, monkeypatch):
    cancel=threading.Event(); target=tmp_path/'weight'
    data=b'x'*(2*1024**2)
    mock_http(monkeypatch,lambda r:httpx.Response(200,content=data))
    def progress(value): cancel.set()
    with pytest.raises(OperationCancelled): preparation.download_asset(manifest(data),target,cancel,progress)
    assert not target.exists() and (tmp_path/'weight.part').stat().st_size==1024**2
    cancel.clear()
    mock_http(monkeypatch,lambda r:httpx.Response(200,content=data))
    preparation.download_asset(manifest(data),target,cancel)
    assert target.read_bytes()==data


def test_integrity_failure_and_existing_corruption_are_not_published(tmp_path, monkeypatch):
    target=tmp_path/'weight'
    mock_http(monkeypatch,lambda r:httpx.Response(200,content=b'bad'))
    with pytest.raises(ModelFault): preparation.download_asset(manifest(b'yes'),target)
    assert not target.exists()
    target.write_bytes(b'bad')
    with pytest.raises(ModelFault): preparation.download_asset(manifest(b'yes'),target)
    assert target.read_bytes()==b'bad'


def test_asset_lock_serializes_other_workstations(tmp_path):
    with preparation.asset_lock(tmp_path/'weight.lock'):
        with pytest.raises(ModelFault,match='另一个'): 
            with preparation.asset_lock(tmp_path/'weight.lock'): pass
    with preparation.asset_lock(tmp_path/'weight.lock'): pass


@pytest.mark.parametrize('kind',['zip','zst'])
def test_cross_platform_archives_publish_verified_receipt(tmp_path,kind):
    path=tmp_path/('runtime.zip' if kind=='zip' else 'runtime.tar.zst')
    if kind=='zip':
        with zipfile.ZipFile(path,'w') as archive: archive.writestr('ollama.exe',b'cli'); archive.writestr('lib/runner.dll',b'lib')
    else:
        import zstandard
        raw=io.BytesIO()
        with tarfile.open(fileobj=raw,mode='w') as archive:
            member=tarfile.TarInfo('bin/ollama'); member.size=3; member.mode=0o755; archive.addfile(member,io.BytesIO(b'cli'))
        path.write_bytes(zstandard.ZstdCompressor().compress(raw.getvalue()))
    info=manifest(path.read_bytes());info['url']='https://official.invalid/'+path.name
    cli=preparation.unpack(path,tmp_path/'runtime',info)
    assert cli.read_bytes()==b'cli'
    receipt=json.loads((tmp_path/'runtime/installation.json').read_bytes())
    assert receipt['source']==info and receipt['files'][cli.relative_to(tmp_path/'runtime').as_posix()]==hashlib.sha256(b'cli').hexdigest()


def test_zip_traversal_cannot_leave_partial_install(tmp_path):
    path=tmp_path/'runtime.zip'
    with zipfile.ZipFile(path,'w') as archive: archive.writestr('../escape',b'bad')
    info=manifest(path.read_bytes());info['url']='https://official.invalid/runtime.zip'
    with pytest.raises(ValueError,match='Unsafe'): preparation.unpack(path,tmp_path/'runtime',info)
    assert not (tmp_path/'escape').exists() and not (tmp_path/'runtime').exists()


@pytest.mark.parametrize('system,arch',[('Windows','AMD64'),('Windows','ARM64'),('Linux','x86_64'),('Linux','aarch64')])
def test_platform_asset_has_pinned_official_identity(monkeypatch,system,arch):
    monkeypatch.setattr(deployment.platform,'system',lambda:system)
    monkeypatch.setattr(deployment.platform,'machine',lambda:arch)
    info=deployment.host_runtime_manifest()
    assert info['version']=='0.40.2' and len(info['sha256'])==64 and info['url'].startswith('https://github.com/ollama/ollama/releases/download/v0.40.2/')
    assert deployment.runtime_plan()['prepare_supported']
