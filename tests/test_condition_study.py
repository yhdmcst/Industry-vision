import hashlib
import json

import cv2
import numpy as np
import pytest

from scripts.create_demo_dataset import create_demo
from scripts.run_condition_study import study, transform, CONDITIONS
from scripts.prepare_aebad import prepare, DOMAINS
from scripts.run_domain_study import run
from scripts.export_vision_model import export
from src.datasets import DatasetStore
from src.inspection.vision_model import VisionModel, validated_files
from src.inspection.padim import PaDiM


def test_fixed_conditions_preserve_input_and_do_not_use_absolute_brightness():
    frame = np.full((480, 640, 3), 120, np.uint8); before = frame.copy()
    assert transform(frame, 'dim_70')[0,0,0] == 84
    assert transform(frame, 'bright_130')[0,0,0] == 156
    for condition in CONDITIONS: assert transform(frame, condition).shape == frame.shape
    assert np.array_equal(frame, before)
    with pytest.raises(ValueError): transform(frame, 'unknown')


def test_condition_labels_do_not_change_prediction_or_rules_and_failures_remain_unavailable(tmp_path):
    manifest = create_demo(tmp_path / 'demo')
    store = DatasetStore(tmp_path / 'datasets'); dataset = store.import_manifest(manifest)
    class Model:
        id = 'fixture'
        recipe = {'dataset_id': dataset['id']}
        producer = {'score_semantics': 'anomaly_score'}
        def predict(self, frame):
            score = float(frame.mean())
            if score < 60: raise RuntimeError('deliberate failure')
            return {'status': 'ok', 'detected': True, 'confidence': None, 'is_ng': score > 130, 'anomaly_score': score}
    first = study(tmp_path / 'unused', manifest, tmp_path / 'first', Model())
    assert any(r['status'] == 'error' for r in first['conditions']['dim_70']['predictions'])
    declared = json.loads(manifest.read_bytes())
    for sample in declared['samples']:
        if sample['split'] == 'evaluation': sample['label']['defect'] = 'defect'
    manifest.write_text(json.dumps(declared)); Model.recipe = {'dataset_id': store.import_manifest(manifest)['id']}
    second = study(tmp_path / 'unused', manifest, tmp_path / 'second', Model())
    for condition in CONDITIONS:
        for a,b in zip(first['conditions'][condition]['predictions'], second['conditions'][condition]['predictions']):
            assert {k:v for k,v in a.items() if k != 'label'} == {k:v for k,v in b.items() if k != 'label'}
    assert not list(tmp_path.glob('.condition-study-*'))


def test_local_domain_partitions_are_frozen_and_duplicate_pixels_rejected(tmp_path):
    source = tmp_path / 'AeBAD_S'
    rng = np.random.default_rng(8)
    paths = [source / 'train/good/background' / f'{i:03d}.png' for i in range(30)]
    paths += [source / 'test' / label / domain / '000.png' for domain in DOMAINS for label in ('good', 'crack')]
    for index,path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = rng.integers(30, 230, (48, 64, 3), dtype=np.uint8)
        frame[10:15,10:15] = index * 6
        assert cv2.imwrite(str(path), frame)
    prepared = prepare(source, tmp_path / 'prepared', fit=10, per_group=1)
    class Features:
        sizes = []
        def __call__(self, frames):
            self.sizes.append(len(frames))
            return np.stack([cv2.resize(f.astype(np.float32)/255, (4,3)) for f in frames])
    features = Features()
    first = run(prepared, tmp_path / 'unused', tmp_path / 'first', features)
    assert features.sizes[:2] == [8,2]
    assert set(first['domains']) == set(DOMAINS)
    document = json.loads((prepared / 'domains.json').read_bytes())
    for row in document['files']:
        if row['partition'] == 'evaluation': row['label'] = 'normal' if row['label'] == 'defect' else 'defect'
    (prepared / 'domains.json').write_text(json.dumps(document))
    second = run(prepared, tmp_path / 'unused', tmp_path / 'second', Features())
    assert first['threshold'] == second['threshold']
    assert [r['anomaly_score'] for r in first['predictions']] == [r['anomaly_score'] for r in second['predictions']]
    paths[-1].write_bytes(paths[0].read_bytes())
    with pytest.raises(ValueError, match='Duplicate'):
        prepare(source, tmp_path / 'bad', fit=10, per_group=1)
    assert not (tmp_path / 'bad').exists() and not list(tmp_path.glob('.aebad-*'))


def test_export_is_self_contained_and_tampering_rejected_before_inference(tmp_path, monkeypatch):
    manifest = create_demo(tmp_path / 'demo')
    document = json.loads(manifest.read_bytes())
    for index,sample in enumerate(document['samples']): sample['conditions'] = {'original_file': str(index)}
    manifest.write_text(json.dumps(document))
    store = DatasetStore(tmp_path / 'datasets'); imported = store.import_manifest(manifest)
    references = [s for s in store.load(imported['id'])['samples'] if s['split'] == 'baseline']
    weights = tmp_path / 'weights'; weights.write_bytes(b'fake weights for fixture')
    checksum = hashlib.sha256(weights.read_bytes()).hexdigest()
    monkeypatch.setattr('scripts.export_vision_model.WEIGHTS_SHA256', checksum)
    monkeypatch.setattr('src.inspection.vision_model.WEIGHTS_SHA256', checksum)
    experiment = tmp_path / 'experiment'; (experiment / 'raw').mkdir(parents=True)
    report = {'dataset_id': imported['id'], 'weights_sha256': checksum,
              'fit_ids': [s['conditions']['original_file'] for s in references],
              'calibration_ids': [f'calibration-{i}' for i in range(20)], 'variants': {'raw': {'status': 'ok', 'threshold': 2.}}}
    (experiment / 'experiment.json').write_text(json.dumps(report))
    model = PaDiM(); model.fit(np.random.default_rng(7).normal(size=(20,3,4,3)))
    model.save(experiment / 'raw/normal-model.npz')
    output = export(experiment, manifest, weights, 'raw', tmp_path / 'bundle')
    class Features:
        def __call__(self, frames): return np.ones((len(frames),3,4,3), np.float32)
    detector = VisionModel(output, Features())
    assert detector.predict(store.image(imported['id'], references[0]))['confidence'] is None
    (output / 'statistics.npz').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='摘要'): validated_files(output)
    assert not list(tmp_path.glob('.vision-export-*'))
