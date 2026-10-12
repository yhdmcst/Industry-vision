import json
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.inspection.runtime import VisionRuntime


def fixture_worker(connection, mode):
    producer = {'name': 'Controlled process fixture', 'version': 'fixture', 'provenance': 'synthetic_fixture',
                'score_semantics': 'anomaly_score', 'decision_threshold': 2.}
    connection.send({'ready': True, 'id': 'a'*64, 'producer': producer, 'mode': 'raw'})
    try:
        while True:
            sequence, frame = connection.recv()
            if mode == 'timeout': time.sleep(5)
            if mode == 'exit': return
            prediction = {'status': 'ok', 'detected': True, 'confidence': None,
                          'anomaly_score': 3. if frame.mean() > 120 else 1.,
                          'is_ng': bool(frame.mean() > 120), 'defect_types': []}
            if mode == 'bad': prediction['confidence'] = .9
            if mode == 'recover' and frame.mean() > 200:
                prediction = {'status': 'error', 'error': 'deliberate per-frame failure'}
            connection.send({'sequence': sequence, 'prediction': prediction})
    except EOFError:
        pass
    finally: connection.close()


@pytest.mark.parametrize('mode,status', [('normal','ok'), ('timeout','timeout'), ('exit','error'), ('bad','error')])
def test_isolated_runtime_verifies_outcomes_and_terminates_timeout(mode, status):
    runtime = VisionRuntime(mode, .3, worker=fixture_worker)
    try:
        record = runtime.infer(np.full((480,640,3), 130, np.uint8))
        assert record.status == status
        if status == 'ok':
            assert record.is_ng is True and record.confidence is None
            assert record.metadata['result']['anomaly_score'] == 3.
        else:
            assert record.is_ng is None and record.confidence is None
            assert record.metadata['result'].get('anomaly_score') is None
            assert runtime.infer(np.zeros((480,640,3), np.uint8)).status == 'error'
    finally: runtime.close()
    assert not runtime.process.is_alive()


def test_single_pending_frame_and_per_frame_error_recovery():
    runtime = VisionRuntime('recover', 1., worker=fixture_worker)
    try:
        runtime.submit(np.full((480,640,3), 220, np.uint8))
        with pytest.raises(RuntimeError, match='上一帧'): runtime.submit(np.zeros((480,640,3), np.uint8))
        deadline = time.monotonic() + 2
        while (record := runtime.poll()) is None and time.monotonic() < deadline: time.sleep(.01)
        assert record.status == 'error' and runtime.state()['status'] == 'ready'
        assert runtime.infer(np.full((480,640,3), 100, np.uint8)).status == 'ok'
    finally: runtime.close()


def test_live_api_remains_responsive_pending_blocks_mutation_and_failure_is_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr('src.inspection.runtime.VisionRuntime',
                        lambda root, timeout: VisionRuntime(root.name, timeout, worker=fixture_worker))
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        assert client.post('/api/vision/connect', json={'path': 'normal', 'timeout_seconds': 1.}).status_code == 200
        assert client.get('/api/state').json()['baseline'] is None
        assert client.post('/api/baseline', json={'count': 10}).status_code == 200
        assert client.get('/api/state').json()['baseline']['consistency']['confidence_mean'] is None
        assert client.post('/api/scenario', json={'scenario': 'focus_change'}).status_code == 409
        original = client.app.state.station.monitor.read
        monkeypatch.setattr(client.app.state.station.monitor, 'read', lambda: np.full((480,640,3),130,np.uint8))
        assert client.post('/api/capture', json={'action': 'sample'}).status_code == 200
        deadline = time.monotonic() + 3
        while client.get('/api/state').json()['vision_runtime']['pending'] and time.monotonic() < deadline: time.sleep(.01)
        state = client.get('/api/state').json()
        assert state['latest']['detection']['is_ng'] is True
        snapshot = client.app.state.station.monitor.snapshot()
        assert 'anomaly_score' not in snapshot['detection'] and 'metadata' not in snapshot['detection']
        assert 'Controlled process fixture' not in json.dumps(snapshot)
        assert client.delete('/api/vision').status_code == 200
        assert client.get('/api/state').json()['baseline'] is None
        monkeypatch.setattr(client.app.state.station.monitor, 'read', original)
        assert client.post('/api/baseline', json={'count': 10}).status_code == 200


def test_pending_timeout_does_not_hold_workstation_lock_and_baseline_failure_keeps_old(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        station = client.app.state.station
        runtime = VisionRuntime('normal', 1., worker=fixture_worker)
        with station.lock: station.activate_vision(runtime)
        assert client.post('/api/baseline', json={'count':10}).status_code == 200
        baseline = client.get('/api/state').json()['baseline']
        runtime.close()
        slow = VisionRuntime('timeout', .8, worker=fixture_worker)
        with station.lock:
            station.monitor.vision = slow
            station.monitor.inspection_source['producer'] = slow.producer
        assert client.post('/api/capture', json={'action':'sample'}).status_code == 200
        begin = time.monotonic(); state = client.get('/api/state').json()
        assert time.monotonic() - begin < .4 and state['vision_runtime']['pending']
        assert client.post('/api/capture',json={'action':'sample'}).status_code == 409
        assert client.delete('/api/baseline').status_code == 409
        assert client.post('/api/source',json={'mode':'synthetic'}).status_code == 409
        assert client.post('/api/capture',json={'action':'pause'}).status_code == 200
        deadline = time.monotonic() + 3
        while client.get('/api/state').json()['vision_runtime']['pending'] and time.monotonic() < deadline: time.sleep(.01)
        state = client.get('/api/state').json()
        assert state['latest']['detection']['status'] == 'timeout'
        assert state['latest']['detection']['is_ng'] is None
        assert state['alert']['active']
        assert client.post('/api/baseline',json={'count':10}).status_code == 409
        assert client.get('/api/state').json()['baseline'] == baseline
        assert client.get('/api/export').json()['events']
    assert not slow.process.is_alive()
