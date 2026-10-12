"""Lifecycle ownership, persistence and concurrent health/operation contracts."""

from concurrent.futures import Future
import json
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient
import pytest

from src.api.app import create_app
from src.llm import management, runtime

DEFAULTS = {'name': 'spark-drift:1.7b-q4', 'endpoint': 'http://127.0.0.1:11435'}


def manager(tmp_path):
    return management.ModelManager(tmp_path / 'test.db', DEFAULTS, threading.RLock(), lambda: False)


class ClientFixture:
    details = {'family': 'spark2_5', 'runtime_version': 'fixture'}
    last_error = ''
    def __init__(self, *args, **kwargs): pass
    def initialize(self): return True
    def _request(self, *args, **kwargs):
        return {'models': [{'name': DEFAULTS['name'], 'size': 100, 'context_length': 4096}]}


def test_selection_survives_restart_without_claiming_connected(tmp_path):
    database = tmp_path / 'api.db'
    with TestClient(create_app(database, serve_frontend=False)) as client:
        assert client.post('/api/model/configure', json={'name': 'spark-drift:4b-q4',
                   'endpoint': 'http://127.0.0.1:11439', 'executable': str(tmp_path / 'custom ollama')}).status_code == 200
        assert client.get('/api/state').json()['model']['name'] == 'spark-drift:4b-q4'
    with TestClient(create_app(database, serve_frontend=False)) as client:
        model = client.get('/api/state').json()['model']
        assert model['name'] == 'spark-drift:4b-q4' and model['endpoint'].endswith(':11439')
        assert not model['connected'] and not model['owned'] and model['checked_at'] is None
        assert model['executable'] == str(tmp_path / 'custom ollama') and model['runtime_plan']['source'] == 'explicit'


def test_runtime_path_rejects_relative_path_without_mutating_configuration(tmp_path):
    m = manager(tmp_path)
    with pytest.raises(ValueError, match='绝对路径'): m.configure(**DEFAULTS, executable='relative/ollama')
    assert not m.config_path.exists()


def test_bad_config_is_preserved_and_disclosed(tmp_path):
    path = tmp_path / 'test.db-model.json'
    path.write_text('{broken')
    m = manager(tmp_path)
    assert m.snapshot()['error'] and m.name == DEFAULTS['name']
    assert path.read_text() == '{broken'


def test_distinct_database_suffixes_have_separate_model_configuration(tmp_path):
    first = manager(tmp_path)
    second = management.ModelManager(tmp_path / 'test.sqlite', DEFAULTS, threading.RLock(), lambda: False)
    first.configure('spark-drift:4b-q4', DEFAULTS['endpoint'])
    assert first.config_path != second.config_path and first.directory != second.directory
    assert not second.config_path.exists() and second.name == DEFAULTS['name']


def test_persistence_failure_keeps_selection_and_file(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.configure(**DEFAULTS)
    before = m.config_path.read_bytes()
    def fail(*args): raise OSError('disk fixture')
    monkeypatch.setattr(management, 'write_json', fail)
    with pytest.raises(RuntimeError, match='原选择保留'):
        m.configure('spark-drift:4b-q4', 'http://127.0.0.1:11439')
    assert m.name == DEFAULTS['name'] and m.config_path.read_bytes() == before


@pytest.mark.parametrize('endpoint', ['http://example.org:11435', 'http://127.0.0.1:80',
    'http://user:pass@localhost:11435', 'http://localhost:11435/path', 'http://localhost:65536'])
def test_invalid_selection_does_not_write(tmp_path, endpoint):
    m = manager(tmp_path)
    with pytest.raises(ValueError): m.configure(DEFAULTS['name'], endpoint)
    assert not m.config_path.exists()


def test_external_connection_is_not_a_process_ownership_claim(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.connect(**DEFAULTS, client_factory=ClientFixture)
    assert m.snapshot()['resident_checked_at'] is None and m.snapshot()['loaded'] == []
    assert m.snapshot()['connected'] and not m.snapshot()['owned']
    with pytest.raises(RuntimeError, match='外部服务'): m.launch('stop')
    m.close()
    assert m.runtime.process is None


def test_health_failure_and_staleness_never_reuse_connected_or_loaded(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.connect(**DEFAULTS, client_factory=ClientFixture)
    monkeypatch.setattr(management, 'SparkXClient', ClientFixture)
    m.refresh_health()
    assert m.snapshot()['loaded'][0]['context_length'] == 4096
    assert m.snapshot()['resident_checked_at']
    m.checked_at = time.time() - 16
    assert not m.snapshot()['connected'] and m.snapshot()['stale']
    class Failed(ClientFixture):
        last_error = 'disconnected fixture'
        def initialize(self): return False
    monkeypatch.setattr(management, 'SparkXClient', Failed)
    m.refresh_health()
    state = m.snapshot()
    assert not state['connected'] and state['details'] == {} and state['loaded'] == []
    assert state['health_error'] == 'disconnected fixture'
    assert state['resident_checked_at'] is None


def test_slow_probe_cannot_restore_superseded_connection(tmp_path, monkeypatch):
    m = manager(tmp_path)
    m.connect(**DEFAULTS, client_factory=ClientFixture)
    entered, release = threading.Event(), threading.Event()
    class Slow(ClientFixture):
        def initialize(self):
            entered.set()
            assert release.wait(3)
            return True
    monkeypatch.setattr(management, 'SparkXClient', Slow)
    thread = threading.Thread(target=m.refresh_health)
    thread.start()
    assert entered.wait(3)
    m.configure('spark-drift:4b-q4', DEFAULTS['endpoint'])
    release.set(); thread.join(3)
    assert not m.snapshot()['connected'] and m.details == {} and not thread.is_alive()


def test_async_check_does_not_block_capture_and_serializes_model_mutations(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def slow(*args):
        entered.set()
        assert release.wait(3)
        return {'ready': False, 'weight_verified': False}
    monkeypatch.setattr(management, 'preflight', slow)
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        try:
            assert client.post('/api/model/check').status_code == 202
            assert entered.wait(3)
            assert client.get('/api/state').json()['model']['operation'] == 'check'
            assert client.post('/api/model/start').status_code == 409
            assert client.post('/api/model/configure', json=DEFAULTS).status_code == 409
            assert client.post('/api/capture', json={'action': 'sample'}).status_code == 200
        finally:
            release.set()
        m = client.app.state.station.models
        m.worker.join(3)
        assert m.snapshot()['operation'] is None and not m.deployment['ready']


def test_failed_start_keeps_reason_and_can_retry(tmp_path, monkeypatch):
    m = manager(tmp_path)
    monkeypatch.setattr(management, 'preflight', lambda *args: {'ready': False})
    for _ in range(2):
        m.launch('start'); m.worker.join(3)
        assert m.error and m.operation is None and not m.snapshot()['connected']
    m.close()


def test_review_in_flight_prevents_stop_switch_and_check(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        station = client.app.state.station
        with station.lock: station.monitor.pending = Future()
        try:
            for action in ('check', 'start', 'stop'):
                assert client.post('/api/model/' + action).status_code == 409
            assert client.post('/api/model/configure', json=DEFAULTS).status_code == 409
            assert client.post('/api/model/connect', json=DEFAULTS).status_code == 409
        finally:
            with station.lock: station.monitor.pending = None


def test_api_cannot_stop_external_process_and_cross_origin_cannot_start(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        assert client.post('/api/model/stop').status_code == 409
        assert client.post('/api/model/start', headers={'origin': 'http://evil.test'}).status_code == 403
        assert client.post('/api/model/unknown').status_code == 422


def test_runtime_log_tail_is_bounded_and_never_reads_receipt_pid(tmp_path):
    r = runtime.OwnedRuntime(tmp_path)
    r.log_path = tmp_path / 'log'
    r.log_path.write_bytes(b'a' * 20000 + b'tail')
    assert len(r.log_tail().encode()) == 16384 and r.log_tail().endswith('tail')
    (tmp_path / 'ollama-11435.json').write_text(json.dumps({'child_pid': 1, 'status': 'ready'}))
    r.close()
    assert not r.owned and r.process is None


def test_start_metadata_failure_cleans_only_created_process(tmp_path, monkeypatch):
    processes = []
    class Process:
        pid = 999
        returncode = None
        def __init__(self, command, **kwargs):
            import io
            self.stdout = io.BytesIO(b"fixture log")
            self.returncode = 0 if 'create' in command else None
            self.terminated = False
            processes.append(self)
        def poll(self): return self.returncode
        def terminate(self): self.terminated = True; self.returncode = 0
        def wait(self, **kwargs): return self.returncode
    class Http:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args): return self
        def raise_for_status(self): pass
        def json(self): return {'version': 'fixture'}
    class Failed(ClientFixture):
        last_error = 'wrong architecture fixture'
        def initialize(self): return False
    monkeypatch.setattr(runtime.subprocess, 'Popen', Process)
    monkeypatch.setattr(runtime.httpx, 'Client', Http)
    monkeypatch.setattr(runtime, 'SparkXClient', Failed)
    report = {'ready': True, 'runtime_cli': '/fixture', 'model': DEFAULTS['name']}
    # Reserve a free loopback port; the fake process never binds it.
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    r = runtime.OwnedRuntime(tmp_path)
    with pytest.raises(RuntimeError, match='wrong architecture'): r.start('1.7b', port, report=report)
    assert len(processes) == 2 and processes[0].terminated and not processes[1].terminated
    assert not r.owned and json.loads(r.receipt.read_bytes())['status'] == 'stopped'
    assert json.loads(r.receipt.read_bytes())['child_pid'] == 999


def test_close_during_preflight_cannot_spawn_a_late_service(tmp_path, monkeypatch):
    m = manager(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def preflight(*args):
        entered.set()
        assert release.wait(3)
        return {'ready': True}
    monkeypatch.setattr(management, 'preflight', preflight)
    def forbidden(*args, **kwargs): raise AssertionError('No late subprocess allowed')
    monkeypatch.setattr(runtime.subprocess, 'Popen', forbidden)
    m.launch('start'); assert entered.wait(3)
    shutdown = threading.Thread(target=m.close)
    shutdown.start()
    assert m.stop_event.wait(3)
    release.set(); shutdown.join(3)
    assert not shutdown.is_alive() and m.operation is None and not m.runtime.owned


def test_workstation_closes_capture_even_when_runtime_receipt_cannot_be_saved(tmp_path, monkeypatch):
    from src.api.service import Workstation
    station = Workstation(tmp_path / 'close.db')
    closed = []
    original = station.monitor.close
    def capture_close():
        closed.append(True)
        original()
    def fail(): raise OSError('receipt write fixture')
    monkeypatch.setattr(station.monitor, 'close', capture_close)
    monkeypatch.setattr(station.models, 'close', fail)
    with pytest.raises(OSError, match='receipt write'): station.close()
    assert closed and station.stop.is_set() and not station.running


def test_bad_policy_does_not_partially_apply_other_configuration(tmp_path):
    path=tmp_path/'test.db-model.json'
    path.write_text(json.dumps({'name':'spark-drift:4b-q4','endpoint':'http://127.0.0.1:11439','policy':{'invalid':True}}))
    m=manager(tmp_path)
    assert m.name==DEFAULTS['name'] and m.endpoint==DEFAULTS['endpoint'] and m.error
    assert json.loads(path.read_bytes())['name']=='spark-drift:4b-q4'


def test_operator_facing_address_error_uses_actionable_chinese(tmp_path):
    m=manager(tmp_path)
    with pytest.raises(ValueError,match='服务地址须为本机 HTTP 地址'): m.configure(DEFAULTS['name'],'http://example.org:11435')
