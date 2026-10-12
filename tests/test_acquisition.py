"""Synthetic acquisition drafts, immutable publication and truthful failure semantics."""

import hashlib
import json
from datetime import datetime, timezone

import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.api.app import create_app
from src.acquisition import AcquisitionStore


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'acquisition.db', serve_frontend=False)) as client:
        yield client


def batch(client):
    response = client.post('/api/acquisition/batches', json={'name': 'Station A', 'description': 'Unverified fixture'})
    assert response.status_code == 200, response.text
    return response.json()['id']


def preview(client):
    response = client.post('/api/acquisition/preview')
    assert response.status_code == 200, response.text
    return response.json()


def save(client, batch_id, token, split='baseline', **changes):
    return client.post(f'/api/acquisition/batches/{batch_id}/samples', json={
        'token': token, 'split': split, 'origin': 'real',
        'conditions': {'fixture': 'LABEL_WITHHELD'}, **changes})


def collect(client, batch_id):
    records = []
    for index in range(11):
        records.append(save(client, batch_id, preview(client)['token'],
                            split='baseline' if index < 10 else 'evaluation').json())
    return records


def test_no_baseline_preview_does_not_measure_or_apply_software_perturbation(client):
    client.delete('/api/baseline')
    client.post('/api/scenario', json={'scenario': 'light_fade', 'intensity': 1})
    before = client.get('/api/state').json()
    monitor = client.app.state.station.monitor
    count = monitor.store.count(monitor.session)
    result = preview(client)
    assert result['usable_for_baseline'] and result['source'] == 'synthetic'
    image = client.get('/api/acquisition/preview/image', params={'token': result['token']})
    assert image.status_code == 200 and image.headers['content-type'] == 'image/png'
    frame = cv2.imdecode(np.frombuffer(image.content, np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(frame, monitor.read())
    after = client.get('/api/state').json()
    for key in ('latest', 'history', 'baseline', 'frame_count', 'alert', 'capture_error'):
        assert after[key] == before[key]
    assert monitor.store.count(monitor.session) == count
    assert client.post('/api/capture', json={'action': 'sample'}).status_code == 409


def test_save_exact_preview_and_forced_synthetic_origin(client):
    batch_id = batch(client)
    item = preview(client)
    image = client.get('/api/acquisition/preview/image', params={'token': item['token']}).content
    captured = save(client, batch_id, item['token'])
    assert captured.status_code == 200, captured.text
    record = captured.json()
    assert record['origin'] == 'synthetic' and record['perturbation'] == 'none'
    assert record['label'] == {'defect': 'unknown', 'cause': 'unknown', 'note': ''}
    assert record['sha256'] == hashlib.sha256(image).hexdigest()
    assert record['captured_at'] == item['created'] and record['source_properties'] == item['source_properties']
    url = f'/api/acquisition/batches/{batch_id}/samples/{record["id"]}/image'
    assert client.get(url).content == image
    assert save(client, batch_id, item['token']).status_code == 400
    assert client.get('/api/acquisition/batches').json()[0]['sample_count'] == 1
    preview(client)
    assert client.get('/api/acquisition/preview/image', params={'token': item['token']}).status_code == 404
    assert save(client, batch_id, item['token']).status_code == 409


@pytest.mark.parametrize('action', ['expiry', 'source', 'baseline', 'sample', 'start'])
def test_stale_preview_cannot_be_retained(client, action):
    batch_id = batch(client)
    item = preview(client)
    if action == 'expiry':
        client.app.state.station.preview_deadline -= 61
    elif action == 'source':
        client.post('/api/source', json={'mode': 'synthetic'})
    elif action == 'baseline':
        client.post('/api/baseline', json={'count': 10})
    else:
        client.post('/api/capture', json={'action': action})
        client.post('/api/capture', json={'action': 'pause'})
    assert save(client, batch_id, item['token']).status_code == 409
    assert not client.get(f'/api/acquisition/batches/{batch_id}').json()['samples']


@pytest.mark.parametrize('value', [0, 128, 255])
def test_rejected_preview_can_be_evaluation_but_never_reference(client, monkeypatch, value):
    batch_id = batch(client)
    monitor = client.app.state.station.monitor
    monkeypatch.setattr(monitor, 'read', lambda: np.full((480, 640, 3), value, np.uint8))
    item = preview(client)
    assert not item['usable_for_baseline'] and item['quality_reasons']
    assert save(client, batch_id, item['token']).status_code == 400
    result = save(client, batch_id, item['token'], split='evaluation')
    assert result.status_code == 200
    url = f'/api/acquisition/batches/{batch_id}/samples/{result.json()["id"]}'
    assert client.patch(url, json={'split': 'baseline'}).status_code == 400


@pytest.mark.parametrize('failure', ['capture', 'encode', 'nan'])
def test_preview_failure_removes_stale_preview_and_preserves_monitor(client, monkeypatch, failure):
    preview(client)
    before = client.get('/api/state').json()
    if failure == 'capture':
        def fail(): raise RuntimeError('camera disconnected')
        monkeypatch.setattr(client.app.state.station.monitor, 'read', fail)
    elif failure == 'encode':
        monkeypatch.setattr(cv2, 'imencode', lambda *args: (False, None))
    else:
        monkeypatch.setattr('src.monitoring.image_analyzer.ImageQualityAnalyzer._calculate_brightness', lambda *args: float('nan'))
    assert client.post('/api/acquisition/preview').status_code == 409
    after = client.get('/api/state').json()
    assert after['acquisition']['preview'] is None and after['acquisition']['error']
    for key in ('latest', 'history', 'baseline', 'frame_count', 'alert', 'capture_error'):
        assert after[key] == before[key]


def test_publish_is_immutable_idempotent_and_labels_stay_out_of_model(client):
    batch_id = batch(client)
    records = collect(client, batch_id)
    before = client.get('/api/state').json()
    endpoint = f'/api/acquisition/batches/{batch_id}/publish'
    first = client.post(endpoint)
    assert first.status_code == 200, first.text
    dataset_id = first.json()['id']
    assert client.post(endpoint).json() == first.json()
    after = client.get('/api/state').json()
    assert after['session'] == before['session'] and after['baseline'] == before['baseline']
    original = client.get(f'/api/datasets/{dataset_id}').json()
    assert original['samples'][0]['origin'] == 'synthetic'
    assert original['samples'][0]['conditions']['capture_batch_id'] == batch_id
    assert client.get('/api/acquisition/batches').json()[0]['duplicate_images'] == 10
    url = f'/api/acquisition/batches/{batch_id}/samples/{records[-1]["id"]}'
    assert client.patch(url, json={'split': 'evaluation', 'label': {'defect': 'defect', 'cause': 'product', 'note': 'LABEL_WITHHELD'}}).status_code == 200
    second = client.post(endpoint).json()
    assert second['id'] != dataset_id
    assert client.get(f'/api/datasets/{dataset_id}').json() == original
    assert client.post('/api/replay', json={'dataset_id': second['id']}).status_code == 200
    assert client.post('/api/acquisition/preview').status_code == 409
    assert save(client, batch_id, records[-1]['capture_token']).status_code == 409
    client.post('/api/capture', json={'action': 'sample'})
    snapshot = client.app.state.station.monitor.snapshot()
    assert 'LABEL_WITHHELD' not in json.dumps(snapshot) and 'sample' not in snapshot
    assert client.get('/api/replay/export').json()['results'][0]['sample']['label']['defect'] == 'defect'


def test_drafts_and_published_pixels_survive_restart_and_corruption_is_rejected(client):
    batch_id = batch(client)
    records = collect(client, batch_id)
    result = client.post(f'/api/acquisition/batches/{batch_id}/publish').json()
    directory = client.app.state.station.acquisition.directory(batch_id)
    original = client.get(f'/api/acquisition/batches/{batch_id}').json()
    store = AcquisitionStore(client.app.state.station.acquisition.root, client.app.state.station.datasets)
    assert store.load(batch_id) == original
    (directory / records[-1]['id'] / 'image.png').write_bytes(b'corrupt')
    before = client.get('/api/datasets').json()
    assert client.post(f'/api/acquisition/batches/{batch_id}/publish').status_code == 400
    assert client.get('/api/datasets').json() == before
    assert client.get(f'/api/datasets/{result["id"]}/images/10').status_code == 200
    assert not list(directory.glob('.publish-*'))
    with TestClient(create_app(client.app.state.station.monitor.store.path, serve_frontend=False)) as restarted:
        assert restarted.get(f'/api/acquisition/batches/{batch_id}').json() == original
        assert restarted.get(f'/api/datasets/{result["id"]}').status_code == 200


@pytest.mark.parametrize('failure', ['save', 'annotate', 'publish'])
def test_storage_failure_keeps_previous_draft(client, monkeypatch, failure):
    batch_id = batch(client)
    records = collect(client, batch_id)
    before = client.get(f'/api/acquisition/batches/{batch_id}').json()
    def fail(*args, **kwargs): raise OSError('disk fixture')
    if failure == 'publish':
        monkeypatch.setattr(client.app.state.station.datasets, 'import_manifest', fail)
        response = client.post(f'/api/acquisition/batches/{batch_id}/publish')
    else:
        monkeypatch.setattr('src.acquisition.os.replace', fail)
        if failure == 'save':
            response = save(client, batch_id, preview(client)['token'])
        else:
            response = client.patch(f'/api/acquisition/batches/{batch_id}/samples/{records[-1]["id"]}', json={'split': 'baseline'})
    assert response.status_code == 409 and '失败' in response.text
    assert client.get(f'/api/acquisition/batches/{batch_id}').json() == before
    directory = client.app.state.station.acquisition.directory(batch_id)
    assert not list(directory.glob('.sample-*')) and not list(directory.glob('.publish-*'))
    assert not list(directory.rglob('.metadata-*'))


def test_invalid_annotations_counts_and_paths_publish_nothing(client):
    batch_id = batch(client)
    item = preview(client)
    assert save(client, batch_id, item['token'], label={'defect': 'defect'}).status_code == 400
    assert save(client, batch_id, item['token'], surprise=True).status_code == 422
    assert save(client, '../outside', item['token']).status_code != 200
    assert client.post(f'/api/acquisition/batches/{batch_id}/publish').status_code == 400
    assert not client.get('/api/datasets').json()
    client.post('/api/capture', json={'action': 'start'})
    assert client.post('/api/acquisition/preview').status_code == 409
    assert save(client, batch_id, item['token']).status_code == 409
    client.post('/api/capture', json={'action': 'pause'})


def test_video_source_origin_requires_explicit_declaration(client, tmp_path):
    video = tmp_path / 'sequence.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (640, 480))
    assert writer.isOpened()
    frame = client.app.state.station.monitor.read()
    for _ in range(3): writer.write(frame)
    writer.release()
    assert client.post('/api/source', json={'mode': 'video', 'video': str(video)}).status_code == 200
    batch_id = batch(client)
    for origin in ('synthetic', 'real'):
        item = preview(client)
        saved = save(client, batch_id, item['token'], origin=origin)
        assert saved.status_code == 200 and saved.json()['origin'] == origin
        assert saved.json()['source_properties']['width'] == 640
    item = preview(client)
    assert client.post('/api/acquisition/preview').status_code == 409
    assert save(client, batch_id, item['token']).status_code == 409


def test_clock_rollback_preserves_order_and_cannot_extend_preview(client, monkeypatch):
    batch_id = batch(client)
    station = client.app.state.station
    first = save(client, batch_id, preview(client)['token']).json()
    monkeypatch.setattr('src.api.service.time.time', lambda: 0)
    class RolledBackClock:
        @staticmethod
        def now(zone):
            return datetime(2000, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr('src.api.service.datetime', RolledBackClock)
    item = preview(client)
    second = save(client, batch_id, item['token'], split='evaluation').json()
    assert second['captured_at'] < first['captured_at']
    assert [r['id'] for r in station.acquisition.load(batch_id)['samples']] == [first['id'], second['id']]
    station.preview_deadline -= 61
    assert save(client, batch_id, item['token']).status_code == 409


def test_camera_properties_and_origin_are_source_owned(client, monkeypatch):
    monitor = client.app.state.station.monitor
    monitor.source = 'camera'  # Mock source metadata; no physical camera is opened.
    monkeypatch.setattr(monitor.camera, 'get_properties', lambda: {'width': 640, 'exposure': float('nan'), 'fps': 0})
    item = preview(client)
    assert item['source_properties'] == {'width': 640, 'exposure': None, 'fps': 0}
    record = save(client, batch(client), item['token'], origin='synthetic').json()
    assert record['origin'] == 'real' and record['source'] == 'camera'


@pytest.mark.parametrize('field,value', [('sequence', 2), ('image_quality', {'brightness': None, 'contrast': 5}), ('path', '../outside.png')])
def test_corrupt_metadata_is_explicitly_rejected(client, field, value):
    batch_id = batch(client)
    record = save(client, batch_id, preview(client)['token']).json()
    path = client.app.state.station.acquisition.directory(batch_id) / record['id'] / 'sample.json'
    path.write_text(json.dumps(record | {field: value}))
    assert client.get(f'/api/acquisition/batches/{batch_id}').status_code == 400
    assert client.get('/api/acquisition/batches').json()[0]['error']
    assert client.post(f'/api/acquisition/batches/{batch_id}/publish').status_code == 400


def test_batch_and_conditions_limits_fail_before_writes(client, monkeypatch):
    batch_id = batch(client)
    item = preview(client)
    assert save(client, batch_id, item['token'], conditions={str(i): 'value' for i in range(28)}).status_code == 422
    store = client.app.state.station.acquisition
    original = store.load
    monkeypatch.setattr(store, 'load', lambda ident: original(ident) | {'samples': [{}] * 500})
    assert save(client, batch_id, item['token']).status_code == 400
    monkeypatch.setattr(store, 'load', original)
    assert not store.load(batch_id)['samples']
    assert save(client, batch_id, item['token'], conditions={str(i): 'value' for i in range(27)}).status_code == 200


def test_create_io_failure_has_feedback_and_leaves_no_batch(client, monkeypatch):
    def fail(*args, **kwargs): raise OSError('disk fixture')
    monkeypatch.setattr('src.acquisition.os.replace', fail)
    result = client.post('/api/acquisition/batches', json={'name': 'failed'})
    assert result.status_code == 409
    assert client.get('/api/acquisition/batches').json() == []
    assert not list(client.app.state.station.acquisition.root.iterdir())


@pytest.mark.parametrize('field', ['capture_source', 'capture_batch_id', 'capture_session'])
def test_reserved_conditions_are_not_silently_overwritten(client, field):
    batch_id = batch(client)
    item = preview(client)
    assert save(client, batch_id, item['token'], conditions={field: 'operator_value'}).status_code == 422
    assert not client.get(f'/api/acquisition/batches/{batch_id}').json()['samples']
