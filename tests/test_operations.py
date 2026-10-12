"""Operation outcomes, incremental state and lossless evidence snapshot contracts."""

import json
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.llm import management
from src.llm.tasks import ModelTasks
from src.storage import EvidenceStore, restore_evidence

DEFAULTS = {'name': 'spark-drift:1.7b-q4', 'endpoint': 'http://127.0.0.1:11435'}


def test_store_connection_closes_and_rolls_back_on_exception(tmp_path):
    store = EvidenceStore(tmp_path/'store.db')
    with pytest.raises(RuntimeError, match='rollback fixture'):
        with store.connect() as db:
            store.append('s', 'frame', 1, {}, connection=db)
            raise RuntimeError('rollback fixture')
    assert store.count('s') == 0
    with pytest.raises(sqlite3.ProgrammingError, match='closed'): db.execute('SELECT 1')


def test_operation_failure_and_cancellation_are_durable(tmp_path, monkeypatch):
    database = tmp_path / 'test.db'
    m = management.ModelManager(database, DEFAULTS, threading.RLock(), lambda: False)
    def fail(*_): raise RuntimeError('file failure fixture')
    monkeypatch.setattr(management, 'preflight', fail)
    m.launch('check'); m.worker.join(3)
    failed = m.snapshot()['tasks'][0]
    assert failed['status'] == 'failed' and failed['finished'] and failed['error'] == 'file failure fixture'
    entered = threading.Event()
    def wait_cancel(size, executable, cancel):
        entered.set()
        assert cancel.wait(3)
        management.check_cancel(cancel)
    monkeypatch.setattr(management, 'preflight', wait_cancel)
    m.launch('check'); assert entered.wait(3)
    m.cancel_operation(); m.worker.join(3)
    records = ModelTasks(database).snapshot()
    assert records[0]['status'] == 'cancelled' and records[0]['target'] == DEFAULTS['name']
    assert records[1] == failed and len({r['id'] for r in records}) == 2
    m.close()


def test_restart_marks_incomplete_task_interrupted_without_relaunch(tmp_path):
    tasks = ModelTasks(tmp_path / 'tasks.db')
    task_id = tasks.begin('start', DEFAULTS['name'])
    tasks.update(task_id, stage='启动中')
    restored = ModelTasks(tmp_path / 'tasks.db').snapshot()[0]
    assert restored['status'] == 'interrupted' and restored['finished']
    assert '不自动重发' in restored['error']
    assert ModelTasks(tmp_path / 'tasks.db').snapshot()[0] == restored


def test_journal_failure_does_not_report_task_as_running_forever(tmp_path, monkeypatch):
    m = management.ModelManager(tmp_path / 'test.db', DEFAULTS, threading.RLock(), lambda: False)
    monkeypatch.setattr(management, 'preflight', lambda *_: {'ready': False})
    def fail(*_, **__): raise sqlite3.OperationalError('full fixture')
    monkeypatch.setattr(m.tasks, 'update', fail)
    m.launch('check'); m.worker.join(3)
    assert m.snapshot()['tasks'][0]['status'] == 'succeeded'
    assert '未能保存' in m.snapshot()['task_error'] and m.operation is None
    m.close()


def test_incremental_history_invalidates_on_frame_and_baseline_change(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        first = client.get('/api/state').json()
        unchanged = client.get('/api/state', params={'history_token': first['history_token']}).json()
        assert 'history' not in unchanged and unchanged['model'] and unchanged['latest']
        client.post('/api/capture', json={'action': 'sample'}).raise_for_status()
        changed = client.get('/api/state', params={'history_token': first['history_token']}).json()
        assert changed['history'] and changed['history_token'] != first['history_token']
        client.delete('/api/baseline').raise_for_status()
        reset = client.get('/api/state', params={'history_token': changed['history_token']}).json()
        assert reset['history'] == [] and reset['history_token'] != changed['history_token']


def test_event_revision_ignores_frames_and_tracks_human_records(tmp_path):
    store = EvidenceStore(tmp_path / 'test.db')
    store.append('s', 'frame', time.time(), {})
    assert store.revision('s') == 0
    revision = store.append('s', 'incident_assessment', time.time(), {'incident_id': 1})
    store.append('s', 'frame', time.time(), {})
    assert store.revision('s') == revision


def test_wal_backup_and_restore_preserve_all_evidence_and_originals(tmp_path):
    store = EvidenceStore(tmp_path / 'live.db')
    with store.connect() as writer:
        writer.execute('BEGIN IMMEDIATE')
        store.append('s', 'frame', time.time(), {'image': 'base64 fixture'}, connection=writer)
        writer.commit()
        original = store.events('s')
        target = tmp_path / 'backup.sqlite'
        store.backup(target)
    restored = tmp_path / 'restored.db'
    assert restore_evidence(target, restored)['events'] == 1
    assert EvidenceStore(restored).events('s') == original
    assert store.events('s') == original and target.is_file()
    before = restored.read_bytes()
    with pytest.raises(ValueError, match='已存在'): restore_evidence(target, restored)
    assert restored.read_bytes() == before
    with pytest.raises(ValueError, match='已存在'): store.backup(target)


@pytest.mark.parametrize('payload', ['null', '{broken', '{"score":NaN}'])
def test_corrupt_backup_cannot_publish_new_database(tmp_path, payload):
    store = EvidenceStore(tmp_path / 'bad.db')
    with store.connect() as db:
        db.execute('INSERT INTO events(session,kind,created,payload) VALUES (?,?,?,?)', ('s', 'frame', 1, payload))
    with pytest.raises(ValueError): restore_evidence(store.path, tmp_path / 'restored.db')
    assert not (tmp_path / 'restored.db').exists()


def test_backup_download_and_cross_origin_protection(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        assert client.post('/api/maintenance/backup', headers={'origin':'http://evil.test'}).status_code == 403
        response = client.post('/api/maintenance/backup')
        assert response.status_code == 200 and response.content.startswith(b'SQLite format 3')
        target = tmp_path / 'download.sqlite'; target.write_bytes(response.content)
        with sqlite3.connect(target) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] > 0
        assert client.get('/api/maintenance/storage').json()['events'] > 0
