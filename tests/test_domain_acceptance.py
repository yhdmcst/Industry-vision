import pytest
import cv2
import numpy as np
import hashlib
import io
import json
import tarfile

from src.acceptance import evaluate_domains
from scripts import fetch_mvtec_ad2 as fetcher
from scripts import prepare_mvtec_ad2 as adapter
from scripts.run_domain_study import run
from src.acquisition import write_json


def samples():
    return [{'sample_id':f'{domain}/{label}/{i}', 'domain':domain, 'label':label, 'status':'ok',
             'is_ng':label == 'defect', 'anomaly_score':2. if label == 'defect' else 0.}
            for domain in ('same','illumination') for label in ('normal','defect') for i in range(40)]


def gate(rows,kind='real_public'):
    return evaluate_domains(rows,expected_domains=('same','illumination'),reference_domain='same',input_kind=kind)


def test_only_real_domains_with_both_classes_and_coverage_can_pass():
    rows = samples()
    assert gate(rows)['accepted'] and not gate(rows)['workstation_accepted']
    assert gate(rows,'real_workstation')['workstation_accepted']
    assert not gate(rows,'controlled_transform')['accepted']
    assert not gate(rows,'fixture')['accepted']
    reduced = [r for r in rows if not (r['domain'] == 'illumination' and r['label'] == 'normal')]
    assert gate(reduced)['status'] == 'insufficient_evidence'
    rows[-1].update(status='timeout',is_ng=None,anomaly_score=None)
    assert gate(rows)['status'] == 'failed'  # class coverage 39/40 is below 98%
    with pytest.raises(ValueError,match='Repeated'): gate(rows+rows[:1])
    duplicated = [dict(r) for r in samples()]
    duplicated[1]['root_id'] = duplicated[0]['sample_id']
    with pytest.raises(ValueError,match='root within'): gate(duplicated)


def test_per_domain_recall_drop_and_mixed_domain_names_do_not_imply_cause_accuracy():
    rows = samples()
    for r in rows[-4:]: r['is_ng'] = False
    assert gate(rows)['accepted']  # exactly 90% recall and ten percentage point drop
    rows[-5]['is_ng'] = False
    assert gate(rows)['status'] == 'failed'
    with pytest.raises(ValueError,match='Unexpected'):
        gate([{**r,'domain':'invented'} for r in rows])


def test_official_ad2_ranges_reject_etag_and_use_checksum_cache(monkeypatch,tmp_path):
    monkeypatch.setattr(fetcher,'SIZE',4)
    class Response:
        content=b'data'; status_code=206
        headers={'etag':fetcher.ETAG,'content-range':'bytes 0-3/4'}
        def raise_for_status(self): pass
    class Client:
        def __init__(self,**kw): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url,headers):
            assert headers == {'Range':'bytes=0-3','If-Match':fetcher.ETAG}
            return Response()
    monkeypatch.setattr(fetcher.httpx,'Client',Client)
    path = fetcher.fetch_range(0,tmp_path)
    assert path.read_bytes() == b'data'
    path.write_bytes(b'bad!')
    assert fetcher.fetch_range(0,tmp_path).read_bytes() == b'data'
    Response.headers['etag'] = 'changed'
    path.write_bytes(b'bad!')
    with pytest.raises(ValueError,match='version'): fetcher.fetch_range(0,tmp_path)


def test_public_adapter_preserves_paired_roots_and_never_reads_private_labels(tmp_path,monkeypatch):
    rng = np.random.default_rng(9)
    entries = [(f'vial/train/good/{i:03d}_regular.png',False) for i in range(40)]
    entries += [(f'vial/validation/good/{i:03d}_regular.png',False) for i in range(20)]
    entries += [(f'vial/test_public/{label}/{i:03d}_{domain}.png',label == 'bad')
                for label in ('good','bad') for i in range(2) for domain in adapter.DOMAINS]
    path = tmp_path/'vial.tar.gz'
    with tarfile.open(path,'w:gz') as archive:
        for name,bad in entries:
            frame = rng.integers(30,220,(48,64,3),np.uint8)
            def add(name,frame):
                data = cv2.imencode('.png',frame)[1].tobytes()
                member = tarfile.TarInfo(name); member.size = len(data)
                archive.addfile(member,io.BytesIO(data))
            add(name,frame)
            if bad:
                mask = np.zeros((48,64),np.uint8); mask[10:15,10:15] = 255
                add(name.replace('/bad/','/ground_truth/bad/').replace('.png','_mask.png'),mask)
        private = tarfile.TarInfo('vial/test_private/000_regular.png'); private.type = tarfile.SYMTYPE
        private.linkname = '/private/never-read'; archive.addfile(private)
    monkeypatch.setattr(adapter,'SIZE',path.stat().st_size)
    write_json(path.with_suffix('.source.json'),{'url':adapter.URL,'etag':adapter.ETAG,
        'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    output = adapter.prepare(path,tmp_path/'prepared')
    source = json.loads((output/'domains.json').read_bytes())
    rows = [r for r in source['files'] if r['partition'] == 'evaluation']
    assert len(rows) == 28 and len({r['root_id'] for r in rows}) == 4
    assert all('/test_private/' not in r['original_file'] for r in source['files'])
    assert all('ground_truth_sha256' in r for r in rows if r['label'] == 'defect')
    class Features:
        def __call__(self,frames): return np.stack([cv2.resize(f.astype(np.float32)/255,(4,3)) for f in frames])
    report = run(output,tmp_path/'unused',tmp_path/'report',Features())
    assert report['gate']['input_kind'] == 'fixture' and not report['gate']['accepted']
    assert report['independent_root_count'] == 4
    assert all(v['paired_roots'] == 4 for v in report['paired_reference'].values())
    path.write_bytes(b'tampered')
    with pytest.raises(ValueError,match='digest'): adapter.prepare(path,tmp_path/'bad')
    assert not list(tmp_path.glob('.ad2-prepare-*'))
