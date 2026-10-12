"""Experiment partition integrity, held-out label isolation and atomic publication with lightweight features."""

import hashlib
import json

import cv2
import numpy as np
import pytest

from scripts.run_padim import run


class Features:
    def __call__(self, frames):
        return np.stack([cv2.resize(f.astype(np.float32) / 255, (4, 3)) for f in frames])


def source_files(root):
    root.mkdir()
    rng = np.random.default_rng(5)
    base = cv2.GaussianBlur(rng.integers(30, 230, (480, 640, 3), dtype=np.uint8), (5, 5), 0)
    for i in range(20):
        cv2.circle(base, (30 + (i % 8) * 70, 50 + (i % 4) * 100), 12, (250, 240, 220), 2)
    records, samples = [], []
    for index in range(34):
        filename = f'{index:04d}.png'
        image = base.copy()
        image[200:230, 200:230] = 40 + index * 3
        assert cv2.imwrite(str(root / filename), image)
        records.append({'image': filename, 'split': 'train' if index < 30 else 'test',
                        'label': 'normal' if index < 32 else 'anomaly',
                        'sha256': hashlib.sha256((root / filename).read_bytes()).hexdigest()})
        if index < 10 or index >= 30:
            samples.append({'id': str(index), 'path': filename, 'batch': 'train' if index < 10 else 'test',
                            'split': 'baseline' if index < 10 else 'evaluation', 'origin': 'synthetic',
                            'conditions': {'original_file': filename},
                            'label': {'defect': 'normal' if index < 32 else 'defect', 'cause': 'unknown'}})
    (root / 'source.json').write_text(json.dumps({'files': records}))
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'name': 'Generated PaDiM experiment', 'samples': samples}))
    return manifest


def test_test_labels_cannot_change_thresholds_scores_or_alignment_and_failures_leave_no_report(tmp_path, monkeypatch):
    from src.inspection.padim import PaDiM
    original_fit = PaDiM.fit
    fit_counts = []
    def check_fit(model, embeddings):
        fit_counts.append(len(embeddings))
        assert len(embeddings) == 10  # A partial feature batch must not spill into evaluation/calibration.
        original_fit(model, embeddings)
    monkeypatch.setattr(PaDiM, 'fit', check_fit)
    source = tmp_path / 'source'
    manifest = source_files(source)
    first = run(manifest, source, tmp_path / 'unused-weights', tmp_path / 'first', Features())
    document = json.loads(manifest.read_bytes())
    for sample in document['samples']:
        if sample['split'] == 'evaluation':
            sample['label']['defect'] = 'normal' if sample['label']['defect'] == 'defect' else 'defect'
    manifest.write_text(json.dumps(document))
    second = run(manifest, source, tmp_path / 'unused-weights', tmp_path / 'second', Features())
    assert fit_counts == [10, 10, 10, 10]
    for mode in ('raw', 'aligned'):
        assert first['variants'][mode]['threshold'] == second['variants'][mode]['threshold']
        rows1, rows2 = first['variants'][mode]['predictions'], second['variants'][mode]['predictions']
        assert [r['anomaly_score'] for r in rows1] == [r['anomaly_score'] for r in rows2]
        assert [r['alignment'] for r in rows1] == [r['alignment'] for r in rows2]
    # Claimed filename alone cannot align model results to different pixels.
    cv2.imwrite(str(source / '0000.png'), np.zeros((480, 640, 3), np.uint8))
    with pytest.raises(ValueError, match='digest'):
        run(manifest, source, tmp_path / 'unused', tmp_path / 'bad-source', Features())
    assert not (tmp_path / 'bad-source').exists()
    assert not list(tmp_path.glob('.padim-*'))


def test_output_error_preserves_prior_evidence(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    manifest = source_files(source)
    monkeypatch.setattr('scripts.run_padim.cv2.imwrite', lambda *a, **kw: False)
    output = tmp_path / 'failed'
    with pytest.raises(OSError):
        run(manifest, source, tmp_path / 'unused', output, Features())
    assert not output.exists() and not list(tmp_path.glob('.padim-*'))


def test_individual_inference_failure_is_exported_without_fake_score(tmp_path):
    source = tmp_path / 'source'
    manifest = source_files(source)
    class FailingFeatures(Features):
        def __call__(self, frames):
            if len(frames) == 1 and int(frames[0][210, 210, 0]) == 139:
                raise RuntimeError('scripted inference failure')
            return super().__call__(frames)
    report = run(manifest, source, tmp_path / 'unused', tmp_path / 'report', FailingFeatures())
    for mode in ('raw', 'aligned'):
        assert report['variants'][mode]['metrics']['unavailable_labeled'] == 1
        package = json.loads((tmp_path / 'report' / mode / 'inspection-results.json').read_bytes())
        failed = next(r for r in package['results'] if r['sample_id'] == '33')
        assert failed['status'] == 'error' and 'scripted inference failure' in failed['error']
        assert failed['confidence'] is None and failed['anomaly_score'] is None and failed['is_ng'] is None
