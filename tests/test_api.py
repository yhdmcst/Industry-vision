from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest
import numpy as np

from src.api.app import create_app
from src.monitoring import DetectionRecord


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        yield client


def test_observe_sample_and_background_capture(client):
    state = client.get('/api/state').json()
    assert state['latest']['synthetic'] and state['frame_count'] == 12
    assert client.get('/api/images/current').headers['content-type'] == 'image/png'
    assert client.post('/api/capture', json={'action': 'sample'}).status_code == 200
    assert client.get('/api/state').json()['frame_count'] == 13
    client.post('/api/capture', json={'action': 'start'})
    deadline = time.monotonic() + 3
    while client.get('/api/state').json()['frame_count'] == 13 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.get('/api/state').json()['frame_count'] > 13
    client.post('/api/capture', json={'action': 'pause'})
    assert not client.get('/api/state').json()['running']


def test_local_path_listing_is_bounded_and_reports_missing(client, tmp_path):
    (tmp_path / 'image.png').write_bytes(b'fixture')
    (tmp_path / 'folder').mkdir()
    response = client.get('/api/local/paths', params={'path': str(tmp_path)}).json()
    assert response['path'] == str(tmp_path.resolve())
    assert response['entries'][0]['directory']
    assert any(entry['name'] == 'image.png' for entry in response['entries'])
    assert client.get('/api/local/paths', params={'path': str(tmp_path / 'missing')}).status_code == 400


def test_incident_review_export_and_reset(client):
    session = client.get('/api/state').json()['session']
    client.post('/api/scenario', json={'scenario': 'focus_change', 'intensity': 0.8})
    client.post('/api/capture', json={'action': 'sample'})
    events = client.get(f'/api/sessions/{session}/incidents').json()
    assert events[0]['drift_type'] == 'optical'
    url = f"/api/sessions/{session}/incidents/{events[0]['id']}"
    before = client.get(url).json()['event']
    assert before['payload']['images']['current'] != before['payload']['images']['baseline']
    assert client.post(url + '/assessment', json={'outcome': 'insufficient_evidence', 'note': '待核验'}).status_code == 200
    assert client.get(url).json()['assessments']
    assert client.post(url + '/review', json={'context': ''}).status_code == 409
    assert client.get('/api/export').json()['events']
    client.delete('/api/baseline')
    assert client.post('/api/capture', json={'action': 'start'}).status_code == 409
    assert client.get('/api/images/current').status_code == 404
    assert client.get(url).json()['event'] == before
    assert client.post('/api/baseline', json={'count': 10, 'note': '新的工况'}).status_code == 200
    assert client.get('/api/state').json()['baseline']['sample_count'] == 10
    assert client.get(f"/api/sessions/other/incidents/{events[0]['id']}").status_code == 404


def test_validation_origin_and_model_failure(client):
    assert client.post('/api/scenario', json={'scenario': 'invented'}).status_code == 422
    assert client.post('/api/baseline', json={'count': 1}).status_code == 422
    assert client.post('/api/source', json={'mode': 'video', 'video': '/missing.mp4'}).status_code == 400
    assert client.post('/api/capture', json={'action': 'sample'}, headers={'origin': 'https://evil.test'}).status_code == 403
    assert client.post('/api/model/connect', json={'name': 'x', 'endpoint': 'https://example.org'}).status_code == 400
    assert not client.get('/api/state').json()['model']['connected']
    assert client.get('/api/state').json()['model']['error']
    assert client.get('/api/health', headers={'host': 'evil.test'}).status_code == 400


def test_model_metadata_is_last_probe_evidence_and_clears_on_rejection(client, monkeypatch):
    class ClientFixture:
        details = {'family': 'spark2_5', 'weight_sha256': 'fixture', 'runtime_version': 'fixture'}
        def __init__(self, *args, **kwargs): pass
        def initialize(self): return True
    monkeypatch.setattr('src.api.app.SparkXClient', ClientFixture)
    assert client.post('/api/model/connect', json={'name': 'spark-drift:4b-q4',
                       'endpoint': 'http://127.0.0.1:11435'}).status_code == 200
    state = client.get('/api/state').json()['model']
    assert state['connected'] and state['details'] == ClientFixture.details
    assert state['checked_at'] and not state['pending']
    def fail(*args, **kwargs): raise ValueError('rejected fixture')
    monkeypatch.setattr('src.api.app.SparkXClient', fail)
    assert client.post('/api/model/connect', json={'name': 'spark-drift:4b-q4',
                       'endpoint': 'http://127.0.0.1:11435'}).status_code == 400
    state = client.get('/api/state').json()['model']
    assert not state['connected'] and state['details'] == {} and state['error']


def test_capture_error_does_not_return_normal(client, monkeypatch):
    station = client.app.state.station
    previous = client.get('/api/state').json()['latest']
    def fail():
        raise RuntimeError('camera disconnected')
    monkeypatch.setattr(station.monitor, 'read', fail)
    assert client.post('/api/capture', json={'action': 'sample'}).status_code == 409
    state = client.get('/api/state').json()
    assert state['latest'] == previous
    assert state['capture_error'] == 'camera disconnected'
    assert state['alert']['state'] == 'unavailable'


def test_rejected_baseline_keeps_old_evidence_and_can_retry(client, monkeypatch):
    station = client.app.state.station
    client.post('/api/scenario', json={'scenario': 'focus_change', 'intensity': .8})
    client.post('/api/capture', json={'action': 'sample'})
    before = client.get('/api/state').json()
    original = station.monitor.read
    monkeypatch.setattr(station.monitor, 'read', lambda: np.zeros((480, 640, 3), np.uint8))
    response = client.post('/api/baseline', json={'count': 10})
    assert response.status_code == 409
    after = client.get('/api/state').json()
    for key in ('baseline', 'baseline_generation', 'latest', 'history', 'alert', 'capture_error'):
        assert after[key] == before[key]
    assert after['baseline_attempt']['valid_samples'] == 0
    assert after['baseline_attempt']['status'] == 'rejected'
    assert not after['running']
    monkeypatch.setattr(station.monitor, 'read', original)
    assert client.post('/api/baseline', json={'count': 10}).status_code == 200
    after = client.get('/api/state').json()
    assert after['baseline_attempt']['status'] == 'passed'
    assert after['baseline_generation'] == before['baseline_generation'] + 1
    assert not after['alert']['active']
    events = client.get(f"/api/sessions/{before['session']}/incidents").json()
    assert events[0]['lifecycle']['state'] == 'closed'
    assert events[0]['lifecycle']['reason'] == 'baseline_replaced'


def test_capture_gap_breaks_recovery_and_lifecycle_survives_restart(client, monkeypatch, tmp_path):
    monitor = client.app.state.station.monitor
    # Keep synthetic detector records stable to isolate image and lifecycle behavior.
    monkeypatch.setattr(monitor, 'detection', lambda frame: DetectionRecord(0, True, 1, False))
    session = monitor.session
    client.post('/api/scenario', json={'scenario': 'focus_change', 'intensity': .8})
    client.post('/api/capture', json={'action': 'sample'})
    events = client.get(f'/api/sessions/{session}/incidents').json()
    incident_id = events[0]['id']
    url = f'/api/sessions/{session}/incidents/{incident_id}'
    frozen = client.get(url).json()['event']
    assert events[0]['lifecycle']['state'] == 'active'
    bookmark = client.post('/api/capture', json={'action': 'bookmark'}).json()['id']
    assert monitor.alerts.episode['incident_id'] == incident_id
    assert client.get(f'/api/sessions/{session}/incidents/{bookmark}').json()['lifecycle']['state'] == 'bookmark'
    client.post('/api/scenario', json={'scenario': 'none'})
    for _ in range(2):
        client.post('/api/capture', json={'action': 'sample'})
    assert monitor.alerts.recovery_streak == 2
    original = monitor.read
    def fail():
        raise RuntimeError('camera gap fixture')
    monkeypatch.setattr(monitor, 'read', fail)
    for _ in range(2):
        assert client.post('/api/capture', json={'action': 'sample'}).status_code == 409
    assert monitor.alerts.recovery_streak == 0
    assert len(monitor.store.events(session, kind='capture_error')) == 1
    monkeypatch.setattr(monitor, 'read', original)
    for _ in range(3):
        client.post('/api/capture', json={'action': 'sample'})
    bundle = client.get(url).json()
    assert bundle['event'] == frozen
    assert bundle['lifecycle']['state'] == 'recovered'
    assert len(bundle['lifecycle_events']) == 1
    assert bundle['lifecycle_events'][0]['payload']['snapshot']['detection_availability']['ready']
    assert client.get('/api/state').json()['capture_error'] == ''
    with TestClient(create_app(monitor.store.path, serve_frontend=False)) as restarted:
        assert restarted.get(url).json() == bundle
        assert restarted.get(f'/api/sessions/{session}/incidents').json()[-1]['lifecycle']['state'] == 'recovered'


def test_switching_source_closes_episode_without_recovery(client):
    session = client.get('/api/state').json()['session']
    client.post('/api/scenario', json={'scenario': 'light_fade', 'intensity': .8})
    client.post('/api/capture', json={'action': 'sample'})
    event = client.get(f'/api/sessions/{session}/incidents').json()[0]
    assert client.post('/api/source', json={'mode': 'synthetic'}).status_code == 200
    bundle = client.get(f"/api/sessions/{session}/incidents/{event['id']}").json()
    assert bundle['lifecycle'] == {**bundle['lifecycle'], 'state': 'closed', 'reason': 'source_changed'}
    assert not client.app.state.station.monitor.store.events(session, kind='incident_recovered')


def test_storage_failure_also_prevents_error_journal_without_hiding_state(client):
    monitor = client.app.state.station.monitor
    previous = client.get('/api/state').json()['latest']
    with monitor.store.connect() as db:
        db.execute("""CREATE TRIGGER fail_all BEFORE INSERT ON events
                      BEGIN SELECT RAISE(ABORT, 'read-only fixture'); END""")
    response = client.post('/api/capture', json={'action': 'sample'})
    assert response.status_code == 409 and '失败记录也无法保存' in response.text
    state = client.get('/api/state').json()
    assert state['latest'] == previous
    assert state['alert']['state'] == 'unavailable'
    assert state['capture_error'] and not state['running']
    with monitor.store.connect() as db:
        db.execute('DROP TRIGGER fail_all')
    assert client.post('/api/capture', json={'action': 'sample'}).status_code == 200
    state = client.get('/api/state').json()
    assert state['latest']['warmup'] and state['alert']['state'] == 'warming'
    assert not state['capture_error']
