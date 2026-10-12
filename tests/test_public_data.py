"""Offline detector label isolation, rank metrics and source integrity using generated fixtures."""

import hashlib
import json

import cv2
import numpy as np
import pytest

from scripts.benchmark_public_data import PatchGaussian, auroc, run


def test_auroc_ties_and_zero_denominator():
    assert auroc([False,False,True,True],[0,1,2,3])==1
    assert auroc([False,True],[1,1])==.5
    assert auroc([False,False],[0,1]) is None
    assert auroc([False,True],[2,1])==0


def test_normal_only_detector_responds_to_local_change():
    normal=np.zeros((240,320,3),np.uint8)+100
    normal[50:150,80:220]=[60,120,70]
    detector=PatchGaussian();detector.fit([normal.copy() for _ in range(12)])
    changed=normal.copy();changed[90:120,140:170]=255
    assert detector.score(normal)==pytest.approx(0, abs=1e-9)
    assert detector.score(changed)>0


def make_source(path):
    path.mkdir()
    records=[]
    rng=np.random.default_rng(1)
    for index in range(34):
        frame=np.zeros((240,320,3),np.uint8)+100
        frame[50:150,80:220]=[60,120,70]
        frame[5:8,5:8]=rng.integers(80,120,(3,3,3),dtype=np.uint8)
        if index>=32: frame[90:120,140:170]=255
        filename=f'{index}.png'
        assert cv2.imwrite(str(path/filename),frame)
        records.append({'image':filename,'sha256':hashlib.sha256((path/filename).read_bytes()).hexdigest(),
                        'split':'train' if index<30 else 'test','label':'normal' if index<32 else 'anomaly'})
    (path/'source.json').write_text(json.dumps({'files':records,'revision':'test-fixture'}))
    return records


def test_labels_do_not_change_predictions_and_corruption_aborts(tmp_path):
    source=tmp_path/'source';make_source(source)
    first=run(source,tmp_path/'first')
    metadata=json.loads((source/'source.json').read_bytes())
    for row in metadata['files']:
        if row['split']=='test': row['label']='normal' if row['label']=='anomaly' else 'anomaly'
    (source/'source.json').write_text(json.dumps(metadata))
    second=run(source,tmp_path/'second')
    assert [r['score'] for r in first['predictions']]==[r['score'] for r in second['predictions']]
    assert first['threshold']==second['threshold']
    assert first['metrics']['image_auroc']==1
    assert second['metrics']['image_auroc']==0
    (source/'0.png').write_bytes(b'broken')
    with pytest.raises(ValueError,match='digest'):
        run(source,tmp_path/'failed')
    assert not (tmp_path/'failed').exists()


def test_report_publication_failure_cleans_partial_output(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    make_source(source)
    monkeypatch.setattr('scripts.benchmark_public_data.cv2.imwrite', lambda *a, **kw: False)
    output = tmp_path / 'failed'
    with pytest.raises(OSError, match='normalized public image'):
        run(source, output)
    assert not output.exists()
    assert not list(tmp_path.glob('.public-benchmark-*'))
