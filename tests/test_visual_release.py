import hashlib
import json

import numpy as np
import pytest

from scripts import validate_visual_release as release
from src.acceptance import POLICY
from src.acquisition import write_json
from src.inspection.padim import PaDiM


def fixture(tmp_path, monkeypatch):
    source, observed = tmp_path/'source', tmp_path/'observed'
    source.mkdir(); observed.mkdir()
    files = [{'image': f'pcb2/{group}/{i:03d}', 'split': split, 'label': label, 'sha256': str(i)}
             for group,split,label,count in [('train','train','normal',60), ('normal','test','normal',100), ('anomaly','test','anomaly',100)]
             for i in range(count)]
    metadata = {'dataset':'VisA', 'category':'pcb2', 'revision':release.REVISION, 'split_sha256':release.CSV_SHA256,
                'url':release.URL, 'etag':release.ETAG, 'files':files}
    write_json(source/'source.json',metadata)
    write_json(observed/'source.json', {'category':'pcb1','files':[{'image':'pcb1/old'}]})
    def frame(source, row):
        seed = int(hashlib.sha256(row['image'].encode()).hexdigest()[:8],16)
        return np.random.default_rng(seed).integers(0,255,(32,32,3),np.uint8)
    monkeypatch.setattr(release, 'image', frame)
    return source, observed


def test_split_rejects_observed_category_changed_pixels_and_partition_edits(tmp_path, monkeypatch):
    source, observed = fixture(tmp_path, monkeypatch)
    protocol = tmp_path/'protocol'
    document = release.partition(source, protocol, [observed])
    release.checked_split(source, protocol)
    assert sum(r['partition'] == 'final' for r in document['files']) == 100
    with pytest.raises(ValueError, match='observed category'):
        release.partition(source, tmp_path/'bad', [source])
    document['files'][0]['pixel_sha256'] = 'bad'
    write_json(protocol/'split.json', document)
    with pytest.raises(ValueError, match='changed'): release.checked_split(source,protocol)


def test_threshold_selection_uses_validation_and_refuses_impossible_tradeoff():
    rows = [{'sample_id':f'{label}-{i}', 'label':label, 'status':'ok', 'anomaly_score':score, 'is_ng':False}
            for label,score in [('normal',1.),('defect',2.)] for i in range(50)]
    selected = release.select_threshold(rows)
    assert selected['threshold'] == 1 and selected['gate']['status'] == 'passed'
    for r in rows: r['anomaly_score'] = 1.
    assert release.select_threshold(rows) is None


def frozen_fixture(source, protocol, monkeypatch):
    # Build genuine normal Gaussian statistics; final inference is real PaDiM with fixture features.
    frozen = protocol/'frozen'; frozen.mkdir()
    model = PaDiM(); model.fit(np.random.default_rng(0).normal(size=(40,3,4,3)).astype(np.float32))
    model.save(frozen/'statistics.npz')
    import cv2
    cv2.imwrite(str(frozen/'reference.png'), np.zeros((32,32,3),np.uint8))
    write_json(protocol/'validation-selection.json', {'fixture':True})
    recipe = {'method':'raw_padim','threshold':2., 'method_source_sha256':release.code_digest(), 'policy':dict(POLICY),
              'split_sha256':release.sha(protocol/'split.json'), 'source_sha256':release.sha(source/'source.json'),
              'validation_sha256':release.sha(protocol/'validation-selection.json'), 'weights_sha256':release.WEIGHTS_SHA256,
              'software':{}, 'files':{p.name:release.sha(p) for p in frozen.iterdir()}}
    write_json(frozen/'recipe.json',recipe)
    write_json(protocol/'freeze-receipt.json',{'recipe_sha256':release.sha(frozen/'recipe.json')})
    class Features:
        calls = 0
        def __call__(self,frames):
            self.calls += 1
            if self.calls == 1: raise RuntimeError('fixture unavailable')
            return np.zeros((len(frames),3,4,3),np.float32)
    return Features()


def test_final_consumed_once_errors_remain_and_tampered_recipe_rejected(tmp_path, monkeypatch):
    source, observed = fixture(tmp_path, monkeypatch)
    protocol = tmp_path/'protocol'; release.partition(source,protocol,[observed])
    features = frozen_fixture(source,protocol,monkeypatch)
    recipe_path = protocol/'frozen/recipe.json'
    original = recipe_path.read_bytes()
    altered = json.loads(original); altered['threshold'] = 1000
    write_json(recipe_path,altered)
    with pytest.raises(ValueError,match='changed'): release.final(source,protocol,tmp_path/'unused',features)
    assert not (source/'final-consumed.json').exists()
    recipe_path.write_bytes(original)
    report = release.final(source,protocol,tmp_path/'unused',features)
    assert report['gate']['overall']['coverage'] == .99
    assert len(report['predictions']) == 100
    assert json.loads((source/'final-consumed.json').read_bytes())['status'] == 'completed'
    with pytest.raises(FileExistsError): release.final(source,protocol,tmp_path/'unused',features)
    assert features.calls == 100


def test_no_passing_validation_does_not_consume_final(tmp_path,monkeypatch):
    source,observed = fixture(tmp_path,monkeypatch)
    protocol = tmp_path/'protocol'; release.partition(source,protocol,[observed])
    (protocol/'validation').mkdir()
    write_json(protocol/'validation/comparison.json', {'variants':{}})
    write_json(protocol/'validation-selection.json', {'split_sha256':release.sha(protocol/'split.json'),
       'method_source_sha256':release.code_digest(), 'comparison_sha256':release.sha(protocol/'validation/comparison.json'), 'candidates':{}})
    with pytest.raises(ValueError,match='No candidate'): release.freeze(source,protocol)
    assert not (source/'final-consumed.json').exists()


def test_aborted_final_is_recorded_and_cannot_be_retried(tmp_path,monkeypatch):
    source,observed = fixture(tmp_path,monkeypatch)
    protocol = tmp_path/'protocol'; release.partition(source,protocol,[observed])
    frozen_fixture(source,protocol,monkeypatch)
    class Interrupted:
        def __call__(self,frames): raise KeyboardInterrupt('interrupted final')
    with pytest.raises(KeyboardInterrupt): release.final(source,protocol,tmp_path/'unused',Interrupted())
    assert json.loads((source/'final-consumed.json').read_bytes())['status'] == 'aborted'
    with pytest.raises(FileExistsError): release.final(source,protocol,tmp_path/'unused',Interrupted())


def test_validation_freeze_and_final_end_to_end_preserve_threshold(tmp_path,monkeypatch):
    import cv2
    from scripts import compare_visual_methods as comparison
    source,observed = fixture(tmp_path,monkeypatch)
    def frame(source,row):
        seed = int(hashlib.sha256(row['image'].encode()).hexdigest()[:8],16)
        low, high = (180,220) if '/anomaly/' in row['image'] else (30,70)
        return np.random.default_rng(seed).integers(low,high,(32,32,3),np.uint8)
    monkeypatch.setattr(release,'image',frame)
    monkeypatch.setattr(comparison,'image',frame)
    class Aligner:
        def __init__(self,frame): pass
        def align(self,frame): return frame, {'status':'passed','angle_deg':0}
    monkeypatch.setattr(comparison,'PoseAligner',Aligner)
    class Features:
        def __call__(self,frames): return np.stack([cv2.resize(f.astype(np.float32)/255,(4,3)) for f in frames])
    def compare(source,ids,output,weights,features):
        return comparison.compare(source,ids,output,weights,methods=('raw_padim',),features=features)
    monkeypatch.setattr(release,'compare',compare)
    monkeypatch.setattr(release,'version',lambda p:'fixture')
    protocol = tmp_path/'protocol'; release.partition(source,protocol,[observed])
    selection = release.validate(source,protocol,tmp_path/'unused',Features())
    assert selection['status'] == 'passed'
    recipe = release.freeze(source,protocol)
    assert (protocol/'frozen/method-source/scripts/validate_visual_release.py').is_file()
    with pytest.raises(ValueError,match='exists'): release.freeze(source,protocol)
    report = release.final(source,protocol,tmp_path/'unused',Features())
    assert report['threshold'] == recipe['threshold']
    assert report['gate']['accepted'] and report['gate']['evidence'] == 'independent_final'
