"""Per-model file identities and immutable visual asset publication."""

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.datasets import digest
from src.inspection.catalog import VisionCatalog
from src.inspection.vision_model import method_digest, validated_files
from src.llm import deployment, management

FIRST, SECOND = 'spark-drift:1.7b-q4', 'spark-drift:4b-q4'


def test_unsupported_visual_format_is_actionable_and_preserves_baseline(tmp_path):
    source = tmp_path/'research'; source.mkdir()
    (source/'recipe.json').write_text('{"schema_version":1,"method":"aligned_roi_padim"}')
    with TestClient(create_app(tmp_path/'api.db', serve_frontend=False)) as client:
        before = client.get('/api/state').json()['baseline_generation']
        response = client.post('/api/vision/models/import', json={'path':str(source), 'name':'unsupported'})
        assert response.status_code == 400 and '部署配方目录' in response.json()['detail']
        assert 'extra_forbidden' not in response.text
        assert client.get('/api/state').json()['baseline_generation'] == before
        assert client.get('/api/vision/models').json()['assets'] == []


def test_deployment_check_cannot_overwrite_corrupt_model_configuration(tmp_path, monkeypatch):
    path = tmp_path/'test.db-model.json'; path.write_text('{broken')
    m = management.ModelManager(tmp_path/'test.db', {'name':FIRST,'endpoint':'http://127.0.0.1:11439'}, threading.RLock(), lambda:False)
    monkeypatch.setattr(management, 'preflight', lambda *_: {'ready':False})
    m.launch('check'); m.worker.join(3)
    assert path.read_text() == '{broken' and '原文件已保留' in m.error
    assert m.snapshot()['tasks'][0]['status'] == 'failed'
    m.close()


def fixture_recipe(tmp_path, mode='raw'):
    root = tmp_path / mode; root.mkdir(exist_ok=True)
    # Fixed identity/file verification fixture only, never load invented weights for inference.
    for name in ('weights.pth', 'statistics.npz', 'reference.png'):
        (root / name).write_bytes((name + mode).encode())
    weight = hashlib.sha256((root / 'weights.pth').read_bytes()).hexdigest()
    recipe = {'schema_version': 1, 'method': 'padim-resnet18-v1', 'method_sha256': method_digest(),
        'weights_sha256': weight, 'statistics_sha256': hashlib.sha256((root/'statistics.npz').read_bytes()).hexdigest(),
        'reference_sha256': hashlib.sha256((root/'reference.png').read_bytes()).hexdigest(),
        'experiment_sha256': 'a'*64, 'mode': mode, 'decision_threshold': 2., 'dataset_id': 'b'*64,
        'fit_ids': [f'fit-{i}' for i in range(10)], 'calibration_ids': [f'cal-{i}' for i in range(20)]}
    (root / 'recipe.json').write_text(json.dumps(recipe))
    return root, recipe, weight


def test_candidate_prepare_does_not_replace_active_file_check(tmp_path, monkeypatch):
    m = management.ModelManager(tmp_path/'test.db', {'name':FIRST,'endpoint':'http://127.0.0.1:11439'}, threading.RLock(), lambda:False)
    reports = {name: {'model': name, 'ready': True, 'weight_verified': True, 'checked_at': time.time()} for name in (FIRST,SECOND)}
    monkeypatch.setattr(management, 'preflight', lambda *_: reports[FIRST])
    monkeypatch.setattr(management, 'prepare_model', lambda *_: reports[SECOND])
    m.launch('check'); m.worker.join(3)
    m.launch('prepare', SECOND); m.worker.join(3)
    assert m.snapshot()['deployment']['model'] == FIRST
    restored = management.ModelManager(tmp_path/'test.db', {'name':FIRST,'endpoint':m.endpoint}, threading.RLock(), lambda:False)
    assert restored.deployments[SECOND]['ready'] and restored.deployment['model'] == FIRST
    assert not restored.connected
    m.close(); restored.close()


def test_weight_change_and_missing_file_invalidate_asset_status(tmp_path, monkeypatch):
    monkeypatch.setattr(deployment, 'ROOT', tmp_path)
    manifest = {'model_name': FIRST, 'file':'one.gguf', 'size': 4, 'official_model':'fixture',
                'source':'fixture', 'revision':'fixed', 'license':'fixture'}
    monkeypatch.setattr(management, 'model_manifest', lambda size: {**manifest, 'model_name': FIRST if size=='1.7b' else SECOND})
    (tmp_path/'models').mkdir(); path = tmp_path/'models/one.gguf'; path.write_bytes(b'1234')
    m = management.ModelManager(tmp_path/'test.db', {'name':FIRST,'endpoint':'http://127.0.0.1:11439'}, threading.RLock(), lambda:False)
    m.deployments[FIRST] = {'weight_verified':True, 'weight_stamp':deployment.weight_stamp(path)}
    assert m.asset_catalog()[0]['file_status'] == 'checked'
    path.write_bytes(b'5678')
    assert m.asset_catalog()[0]['file_status'] == 'changed'
    path.unlink(); assert m.asset_catalog()[0]['file_status'] == 'missing'
    m.close()


def test_visual_registration_copies_verified_assets_and_recovers_selection(tmp_path, monkeypatch):
    source, recipe, weight = fixture_recipe(tmp_path)
    monkeypatch.setattr('src.inspection.vision_model.WEIGHTS_SHA256', weight)
    catalog = VisionCatalog(tmp_path/'workspace.db')
    asset = catalog.register(source, 'Fixture only')
    assert asset['id'] == digest(recipe) and catalog.snapshot()['assets'][0]['file_status'] == 'compatible'
    assert catalog.register(source, 'Another display name')['id'] == asset['id']
    assert len(catalog.snapshot()['assets']) == 1
    catalog.record_selection(asset['id'], 1.5)
    restored = VisionCatalog(tmp_path/'workspace.db')
    assert restored.snapshot()['selections'][0]['timeout_seconds'] == 1.5
    (source/'weights.pth').unlink()
    validated_files(restored.asset_path(asset['id']))
    target = restored.asset_path(asset['id']) / 'statistics.npz'; target.write_bytes(b'corrupt fixture')
    assert restored.snapshot()['assets'][0]['file_status'] == 'changed'
    with pytest.raises(ValueError, match='摘要'): validated_files(restored.asset_path(asset['id']))


def test_failed_visual_publication_leaves_no_catalog_or_partial_asset(tmp_path, monkeypatch):
    source, _, weight = fixture_recipe(tmp_path)
    monkeypatch.setattr('src.inspection.vision_model.WEIGHTS_SHA256', weight)
    catalog = VisionCatalog(tmp_path/'workspace.db')
    def fail(*_): raise OSError('disk full fixture')
    monkeypatch.setattr('src.inspection.catalog.write_json', fail)
    with pytest.raises(OSError): catalog.register(source, 'Fixture')
    assert catalog.snapshot()['assets'] == [] and list(catalog.root.iterdir()) == []
    assert (source/'recipe.json').exists()


def test_bad_catalog_is_preserved_and_cannot_be_overwritten(tmp_path):
    catalog = VisionCatalog(tmp_path/'workspace.db'); catalog.path.write_text('{broken')
    restored = VisionCatalog(tmp_path/'workspace.db')
    assert restored.snapshot()['error']
    with pytest.raises(RuntimeError, match='原文件已保留'): restored.register(tmp_path/'anything', 'name')
    assert restored.path.read_text() == '{broken'


def test_registered_api_load_and_failure_preserve_old_model_and_configuration(tmp_path, monkeypatch):
    source, recipe, weight = fixture_recipe(tmp_path)
    monkeypatch.setattr('src.inspection.vision_model.WEIGHTS_SHA256', weight)
    class Runtime:
        id = digest(recipe); producer={'provenance':'synthetic_fixture'}
        closed = False
        def __init__(self, root, timeout):
            self.timeout = timeout
        def state(self): return {'status':'ready', 'model_id':self.id, 'pending':False, 'error':''}
        def close(self): self.closed = True
    monkeypatch.setattr('src.inspection.runtime.VisionRuntime', Runtime)
    database = tmp_path/'workspace.db'
    with TestClient(create_app(database, serve_frontend=False)) as client:
        before = client.get('/api/state').json()['baseline_generation']
        imported = client.post('/api/vision/models/import', json={'path':str(source), 'name':'Fixture'}).json()
        assert imported['id'] == digest(recipe) and client.get('/api/state').json()['baseline_generation'] == before
        assert client.post('/api/vision/connect', json={'model_id':imported['id'], 'timeout_seconds':1.5}).status_code == 200
        assert client.post(f"/api/vision/models/{imported['id']}/repair", json={'path': str(source)}).status_code == 409
        assert client.get(f"/api/vision/models/{imported['id']}/removal-preview").status_code == 409
        runtime = client.app.state.station.monitor.vision
        selections = client.get('/api/vision/models').json()['selections']
        def fail(*_): raise RuntimeError('candidate fixture failure')
        monkeypatch.setattr('src.inspection.runtime.VisionRuntime', fail)
        assert client.post('/api/vision/connect', json={'model_id':imported['id']}).status_code == 409
        assert client.app.state.station.monitor.vision is runtime and not runtime.closed
        assert client.get('/api/vision/models').json()['selections'] == selections
        assert client.get('/api/state').json()['vision_management_error'] == 'candidate fixture failure'
        assert client.post('/api/vision/connect', json={'model_id':imported['id'], 'path':'extra'}).status_code == 422
    with TestClient(create_app(database, serve_frontend=False)) as client:
        assert client.get('/api/state').json()['vision_runtime']['status'] == 'disabled'
        assert client.get('/api/vision/models').json()['selections'] == selections


def test_asset_repair_retirement_and_restore_preserve_originals_and_identity(tmp_path, monkeypatch):
    source, recipe, weight = fixture_recipe(tmp_path)
    monkeypatch.setattr('src.inspection.vision_model.WEIGHTS_SHA256', weight)
    catalog = VisionCatalog(tmp_path / 'workspace.db')
    asset = catalog.register(source, 'fixture')
    target = catalog.asset_path(asset['id']); (target / 'statistics.npz').write_bytes(b'broken')
    repaired = catalog.repair(asset['id'], source)
    assert repaired['id'] == asset['id'] and repaired['preserved_previous']
    assert (Path(repaired['preserved_previous']) / 'statistics.npz').read_bytes() == b'broken'
    assert validated_files(target)[1] == recipe
    preview = catalog.removal_preview(asset['id'])
    catalog.record_selection(asset['id'], 1.5)
    with pytest.raises(RuntimeError, match='变化'): catalog.retire(asset['id'], preview['token'])
    result = catalog.retire(asset['id'], catalog.removal_preview(asset['id'])['token'])
    assert not target.exists() and catalog.snapshot()['assets'] == []
    assert (source / 'recipe.json').exists()
    restored_catalog = VisionCatalog(tmp_path / 'workspace.db')
    restored = restored_catalog.restore(result['retirement_id'])
    assert restored['id'] == asset['id'] and target.exists() and restored_catalog.snapshot()['retired'] == []


def test_repair_persistence_failure_rolls_back_damaged_original(tmp_path, monkeypatch):
    source, recipe, weight = fixture_recipe(tmp_path)
    monkeypatch.setattr('src.inspection.vision_model.WEIGHTS_SHA256', weight)
    catalog = VisionCatalog(tmp_path / 'workspace.db'); asset = catalog.register(source, 'fixture')
    target = catalog.asset_path(asset['id']); (target / 'statistics.npz').write_bytes(b'broken')
    def fail(*_): raise OSError('full fixture')
    monkeypatch.setattr('src.inspection.catalog.write_json', fail)
    with pytest.raises(OSError): catalog.repair(asset['id'], source)
    assert (target / 'statistics.npz').read_bytes() == b'broken'
    assert (source / 'statistics.npz').read_bytes() != b'broken'
