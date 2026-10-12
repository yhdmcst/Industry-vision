"""Sealed deployment preserves identity/ROI and never reads or consumes the final cohort."""
import hashlib
import json
import shutil
from importlib.metadata import version

import cv2
import numpy as np
import pytest

from src.acceptance import POLICY
from src.acquisition import write_json
from src.datasets import file_digest, digest
from src.inspection import release_deployment as deployment
from src.inspection.catalog import VisionCatalog
from src.inspection.padim import PaDiM
from src.inspection.deployment_assets import checked_asset, load_asset
from scripts.validate_visual_release import code_digest


def sealed_fixture(tmp_path, monkeypatch, method='aligned_roi_padim'):
    protocol = tmp_path / 'protocol'; frozen = protocol / 'frozen'; frozen.mkdir(parents=True)
    weights = tmp_path / 'weights.pth'; weights.write_bytes(b'controlled fixture, not official weights')
    checksum = file_digest(weights); monkeypatch.setattr(deployment, 'WEIGHTS_SHA256', checksum)
    model = PaDiM(); model.mean = np.zeros((2, 2, 1), np.float32); model.precision = np.ones((2, 2, 1, 1), np.float32)
    model.save(frozen / 'statistics.npz')
    cv2.imwrite(str(frozen / 'reference.png'), np.zeros((480, 640, 3), np.uint8))
    if 'roi' in method:
        mask = np.zeros((224, 224), np.uint8); mask[30:190, 30:190] = 255
        cv2.imwrite(str(frozen / 'roi.png'), mask)
    for name in deployment.SOURCE_FILES:
        target = frozen / 'method-source' / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(deployment.ROOT / name, target)
    write_json(protocol / 'split.json', {'source_sha256': 'a' * 64, 'files': [{'partition': 'final', 'image': 'does-not-exist.JPG'}]})
    write_json(protocol / 'validation-selection.json', {'split_sha256': file_digest(protocol / 'split.json'), 'method_source_sha256': code_digest(),
        'candidates': {method: {'status': 'passed', 'selected': {'threshold': 2.}, 'statistics_sha256': file_digest(frozen / 'statistics.npz')}}})
    recipe = {'schema_version': 1, 'method': method, 'threshold': 2., 'method_source_sha256': code_digest(),
        'split_sha256': file_digest(protocol / 'split.json'), 'validation_sha256': file_digest(protocol / 'validation-selection.json'),
        'source_sha256': 'a' * 64, 'weights_sha256': checksum, 'policy': dict(POLICY),
        'files': {p.relative_to(frozen).as_posix(): file_digest(p) for p in frozen.rglob('*') if p.is_file()},
        'software': {name: 'fixture' for name in ('numpy', 'scipy', 'opencv-python-headless', 'torch', 'torchvision')}}
    write_json(frozen / 'recipe.json', recipe)
    write_json(protocol / 'freeze-receipt.json', {'recipe_sha256': file_digest(frozen / 'recipe.json')})
    (protocol / 'final-consumed.json').write_text('preserve old consumption receipt')
    return protocol, weights


def test_release_export_preserves_seal_threshold_sources_and_never_consumes_images(tmp_path, monkeypatch):
    protocol, weights = sealed_fixture(tmp_path, monkeypatch)
    before = {p.relative_to(protocol).as_posix(): file_digest(p) for p in protocol.rglob('*') if p.is_file()}
    output = tmp_path / 'deployment'
    recipe = deployment.export_release(protocol, weights, output)
    assert recipe['decision_threshold'] == 2. and recipe['research_method'] == 'aligned_roi_padim'
    assert recipe['frozen_recipe_sha256'] == file_digest(protocol / 'frozen/recipe.json')
    assert (output / 'sealed-recipe.json').read_bytes() == (protocol / 'frozen/recipe.json').read_bytes()
    assert (output / 'roi.png').read_bytes() == (protocol / 'frozen/roi.png').read_bytes()
    assert checked_asset(output)[1] == recipe
    assert before == {p.relative_to(protocol).as_posix(): file_digest(p) for p in protocol.rglob('*') if p.is_file()}
    catalog = VisionCatalog(tmp_path / 'workspace.db')
    asset = catalog.register(output, 'sealed fixture')
    assert asset['id'] == digest(recipe) and 'roi.png' in asset['files']
    assert catalog.snapshot()['assets'][0]['file_status'] == 'compatible'
    with pytest.raises(ValueError, match='已存在'): deployment.export_release(protocol, weights, output)


def test_frozen_inference_uses_roi_and_preserves_failed_alignment(tmp_path, monkeypatch):
    protocol, weights = sealed_fixture(tmp_path, monkeypatch)
    output = tmp_path / 'deployment'; deployment.export_release(protocol, weights, output)
    class Aligner:
        fail = False
        def __init__(self, frame): pass
        def align(self, frame): return (None if self.fail else frame), {'status': 'fixture', 'error': 'alignment fixture failure'}
    monkeypatch.setattr(deployment, 'PoseAligner', Aligner)
    model = load_asset(output, features=lambda frames: [np.zeros((2, 2, 1), np.float32)])
    heat = np.ones((224, 224), np.float32); heat[0, 0] = 100.
    monkeypatch.setattr(model.model, 'predict', lambda _: (100., heat))
    result = model.predict(np.zeros((480, 640, 3), np.uint8))
    assert result['anomaly_score'] == 1. and not result['is_ng'] and result['confidence'] is None
    model.aligner.fail = True
    assert model.predict(np.zeros((480, 640, 3), np.uint8))['status'] == 'error'
    with pytest.raises(ValueError, match='640'): model.predict(np.zeros((3, 3, 3), np.uint8))


@pytest.mark.parametrize('target', ['threshold', 'file', 'receipt', 'source', 'selection'])
def test_modified_seals_or_deployments_are_rejected(tmp_path, monkeypatch, target):
    protocol, weights = sealed_fixture(tmp_path, monkeypatch)
    output = tmp_path / 'deployment'; deployment.export_release(protocol, weights, output)
    if target == 'threshold':
        recipe = json.loads((output / 'recipe.json').read_bytes()); recipe['decision_threshold'] = 9.
        write_json(output / 'recipe.json', recipe)
    elif target == 'file': (output / 'roi.png').write_bytes(b'changed')
    elif target == 'receipt': write_json(output / 'freeze-receipt.json', {'recipe_sha256': 'b' * 64})
    elif target == 'source': (output / 'method-source/src/inspection/methods.py').write_text('changed source')
    else: write_json(output / 'validation-selection.json', {'candidates': {}})
    with pytest.raises(ValueError): checked_asset(output)


def test_unmatched_dependencies_cannot_be_reported_as_ready():
    with pytest.raises(ValueError, match='依赖版本不匹配'): deployment.check_dependencies({'software': {'numpy': 'impossible'}})
