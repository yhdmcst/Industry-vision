"""HTTP archive selection uses fixed official identities and never extracts paths."""

import pytest
import hashlib
import io
import tarfile

from scripts.prepare_visa import ETAG, SIZE, fetch, prepare


def test_fixed_archive_pins_etag_revision_and_range_size(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.prepare_visa.CACHE",tmp_path)
    class Response:
        status_code=206
        headers={'etag':ETAG,'content-range':'bytes 10-13/'+str(SIZE)}
        content=b'data'
        def raise_for_status(self): pass
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,headers):
            assert headers=={'Range':'bytes=10-13','If-Match':ETAG}
            return Response()
    monkeypatch.setattr('scripts.prepare_visa.httpx.Client',Client)
    assert fetch(10,4)==b'data'
    assert fetch(10,4)==b'data'
    (tmp_path/'10-4.bin').write_bytes(b'bad!')
    assert fetch(10,4)==b'data'


def test_range_rejects_version_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr("scripts.prepare_visa.CACHE",tmp_path)
    class Response:
        status_code=206
        headers={'etag':'wrong','content-range':f'bytes 0-3/{SIZE}'}
        content=b'data'
        def raise_for_status(self): pass
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,*args,**kwargs): return Response()
    monkeypatch.setattr('scripts.prepare_visa.httpx.Client',Client)
    with pytest.raises(ValueError,match='mismatch'):
        fetch(0,4)


def test_preparation_failure_cleans_partial_output_and_can_retry(monkeypatch, tmp_path):
    csv_content = b'object,split,label,image\npcb1,train,normal,pcb1/Data/Images/a.jpg\npcb1,test,normal,pcb1/Data/Images/b.jpg\npcb1,test,anomaly,pcb1/Data/Images/c.jpg\n'
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        for filename in ('a.jpg', 'b.jpg', 'c.jpg'):
            entry = tarfile.TarInfo('pcb1/Data/Images/' + filename)
            entry.size = 4
            tar.addfile(entry, io.BytesIO(b'data'))
    class Response:
        content = csv_content
        text = csv_content.decode()
        def raise_for_status(self): pass
    monkeypatch.setattr('scripts.prepare_visa.httpx.get', lambda *a, **kw: Response())
    monkeypatch.setattr('scripts.prepare_visa.CSV_SHA256', hashlib.sha256(csv_content).hexdigest())
    monkeypatch.setattr('scripts.prepare_visa.fetch', lambda start, size: archive.getvalue() if start == 850 * 1024**2 else b'')
    from scripts import prepare_visa
    original = prepare_visa.write_json
    def fail(*a, **kw): raise OSError('disk fixture')
    monkeypatch.setattr(prepare_visa, 'write_json', fail)
    output = tmp_path / 'dataset'
    with pytest.raises(OSError, match='disk fixture'):
        prepare(output, 1, 1, 1)
    assert not output.exists()
    assert not list(tmp_path.glob('.visa-*'))
    monkeypatch.setattr(prepare_visa, 'write_json', original)
    prepare(output, 1, 1, 1)
    assert (output / 'source.json').is_file()
    with pytest.raises(ValueError, match='Output exists'):
        prepare(output, 1, 1, 1)


def test_generic_pcb_index_reads_exact_members_and_crosses_cached_chunks(monkeypatch):
    from scripts import prepare_visa as module
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        for name in ['pcb1/unused', 'pcb2/Data/Images/a.jpg', 'pcb3/unused']:
            member = tarfile.TarInfo(name); member.size = 4
            tar.addfile(member, io.BytesIO(b'data'))
    content = archive.getvalue()
    origin = 850*1024**2
    monkeypatch.setattr(module,'fetch',lambda start,size:content+(b'\0'*(size-len(content))))
    expected = {'pcb2/Data/Images/a.jpg'}
    index = module.index_category(expected,'pcb2')
    assert index['pcb2/Data/Images/a.jpg']['offset'] == origin+1536
    assert module.indexed_read(index['pcb2/Data/Images/a.jpg']['offset'],4) == b'data'
    with pytest.raises(ValueError,match='Missing'): module.index_category({'pcb2/absent'},'pcb2')
