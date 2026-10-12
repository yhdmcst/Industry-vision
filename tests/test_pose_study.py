import hashlib
import json

import cv2
import numpy as np
import pytest

from scripts.run_pose_study import study, unseen_rows
from src.inspection.padim import PaDiM


def test_exclusion_uses_original_identity_and_requires_both_new_classes():
    rows = [{'image': str(i), 'split': 'test', 'label': 'normal' if i % 2 == 0 else 'anomaly'} for i in range(6)]
    observed = {'samples': [{'split': 'evaluation', 'conditions': {'original_file': str(i)}} for i in (0, 1)]}
    fresh, excluded = unseen_rows(rows, observed)
    assert [r['image'] for r in fresh] == ['2', '3', '4', '5'] and excluded == ['0', '1']
    with pytest.raises(ValueError, match='both official classes'):
        unseen_rows(rows[:3], observed)


def test_model_reload_preserves_scores_and_rejects_invalid_statistics(tmp_path):
    model = PaDiM(); model.fit(np.random.default_rng(3).normal(size=(10, 3, 4, 3)))
    path = tmp_path / 'model.npz'; model.save(path)
    embedding = np.ones((3, 4, 3))
    assert PaDiM.load(path).predict(embedding)[0] == model.predict(embedding)[0]
    np.savez(path, mean=model.mean, precision=np.zeros_like(model.precision))
    with pytest.raises(np.linalg.LinAlgError): PaDiM.load(path)


def test_paired_study_keeps_originals_excludes_observed_and_publishes_atomically(tmp_path, monkeypatch):
    source = tmp_path / 'source'; source.mkdir()
    rng = np.random.default_rng(3)
    base = cv2.GaussianBlur(rng.integers(30, 220, (480, 640, 3), dtype=np.uint8), (5, 5), 0)
    rows = []
    for index in range(36):
        frame = base.copy(); frame[200:240, 200:240] = index * 5
        path = source / f'{index:04d}.png'; assert cv2.imwrite(str(path), frame)
        rows.append({'image': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'split': 'train' if index < 30 else 'test', 'label': 'normal' if index < 33 else 'anomaly'})
    (source / 'source.json').write_text(json.dumps({'files': rows, 'category': 'fixture'}))
    observed = tmp_path / 'observed.json'
    observed.write_text(json.dumps({'samples': [{'split': 'evaluation', 'conditions': {'original_file': rows[i]['image']}} for i in (30, 33)]}))
    class Features:
        def __call__(self, frames):
            return np.stack([cv2.resize(f.astype(np.float32) / 255, (4, 3)) for f in frames])
    output = tmp_path / 'study'
    report = study(source, observed, tmp_path / 'unused', output, Features())
    assert len(report['fresh_evaluation_files']) == 4
    for mode in ('raw', 'aligned'):
        paired = report['paired'][mode]
        assert len(paired['predictions']) == 8
        assert {r['input_kind'] for r in paired['predictions']} == {'real_original', 'controlled_transform'}
        assert paired['original_metrics'] == json.loads((output / 'detectors/experiment.json').read_bytes())['variants'][mode]['metrics']
    assert (output / 'manifest.json').is_file() and not list(tmp_path.glob('.pose-study-*'))
    with pytest.raises(ValueError, match='Output exists'):
        study(source, observed, tmp_path / 'unused', output, Features())
    monkeypatch.setattr('scripts.run_pose_study.cv2.imwrite', lambda *a, **kw: False)
    with pytest.raises(OSError): study(source, observed, tmp_path / 'unused', tmp_path / 'failed', Features())
    assert not (tmp_path / 'failed').exists() and not list(tmp_path.glob('.pose-study-*'))
