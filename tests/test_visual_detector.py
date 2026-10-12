"""Numerical covariance and controlled pose tests, without downloaded neural weights."""

import cv2
import numpy as np
import pytest

from src.inspection.alignment import PoseAligner
from src.inspection.padim import PaDiM, ResNetFeatures


def textured_frame():
    rng = np.random.default_rng(42)
    frame = rng.integers(30, 200, (480, 640, 3), dtype=np.uint8)
    for i in range(12):
        cv2.circle(frame, (50 + i * 40, 100 + i % 3 * 120), 15, (255, 230, 100), 3)
    return frame


def test_rotation_alignment_is_image_only_and_rejects_insufficient_evidence():
    frame = textured_frame()
    aligner = PoseAligner(frame)
    rotated = cv2.rotate(frame, cv2.ROTATE_180)
    aligned, evidence = aligner.align(rotated)
    assert evidence['status'] == 'passed', evidence
    assert abs(evidence['angle_deg']) == pytest.approx(180, abs=1)
    # A subpixel warp interpolates high-frequency noise; assess coarse structural alignment.
    assert np.mean(np.abs(cv2.resize(aligned, (32, 24), interpolation=cv2.INTER_AREA).astype(float)
                          - cv2.resize(frame, (32, 24), interpolation=cv2.INTER_AREA).astype(float))) < 4
    failed, reason = aligner.align(np.zeros_like(frame))
    assert failed is None and reason['status'] == 'rejected' and reason['error']
    assert aligner.align(frame[:100])[0] is None
    with pytest.raises(ValueError, match='足够'):
        PoseAligner(np.zeros_like(frame))


def test_full_covariance_mahalanobis_and_anomaly_response(tmp_path):
    rng = np.random.default_rng(3)
    data = rng.normal(0, .1, (20, 3, 4, 5)).astype(np.float32)
    model = PaDiM(); model.fit(data)
    expected = np.cov(data[:, 1, 2], rowvar=False) + .01 * np.eye(5)
    assert model.precision[1, 2] == pytest.approx(np.linalg.inv(expected), rel=1e-5)
    normal, heatmap = model.predict(model.mean)
    assert normal == pytest.approx(0)
    altered = model.mean.copy(); altered[1, 2, 0] += 10
    assert model.predict(altered)[0] > normal
    assert heatmap.shape == (224, 224)
    model.save(tmp_path / 'normal.npz')
    saved = np.load(tmp_path / 'normal.npz', allow_pickle=False)
    assert np.array_equal(saved['mean'], model.mean)
    with pytest.raises(ValueError): model.predict(altered * float('nan'))
    with pytest.raises(ValueError): PaDiM().fit(data[:2])


def test_bad_weights_reject_before_optional_framework_import(tmp_path):
    path = tmp_path / 'bad.pth'; path.write_bytes(b'broken')
    with pytest.raises(ValueError, match='SHA-256'):
        ResNetFeatures(path, '0' * 64)
