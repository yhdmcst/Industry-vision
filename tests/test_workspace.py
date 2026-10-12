"""Lossless retention, untruncated history, and safe workspace restoration."""
import json
import sqlite3
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.storage import EvidenceStore
from src.workspace import backup_workspace, restore_workspace, retention_preview, archive_sessions, compact_store
from src.llm.policy import DEFAULT_POLICY


def incident(frame=1):
    return {'frame': frame, 'source': 'synthetic', 'injected': False, 'baseline_generation': 1,
            'trigger': 'operator_bookmark', 'rule_report': {'drift_type': 'unknown'}}


def test_history_pages_and_related_evidence_have_no_old_limit(tmp_path):
    store = EvidenceStore(tmp_path / 'events.db')
    ids = store.append_many('s', [('incident', i, incident(i)) for i in range(230)])
    store.append_many('s', [('incident_assessment', i, {'incident_id': ids[0], 'note': str(i)}) for i in range(10005)])
    store.append('s', 'incident_assessment', 20000, {'incident_id': ids[-1], 'note': 'latest'})
    assert len(store.all_events('s', kind='incident_assessment', incident_id=ids[0])) == 10005
    seen, before = [], None
    while True:
        page = store.incident_page('s', limit=50, before=before)
        seen.extend(item['id'] for item in page['items'])
        before = page['next_before']
        if before is None: break
    assert seen == ids[::-1]
    done = store.incident_page('s', status='done')['items']
    assert [r['id'] for r in done] == [ids[-1], ids[0]]
    assert done[-1]['assessment']['note'] == '10004'
    assert len(store.incident_page('s', status='pending', limit=200)['items']) == 200
    assert store.incident_page('s', search='%')['items'] == []
    store.append('s', 'incident_updated', 20001, {'incident_id': ids[0], 'frame': 999})
    assert store.incident_page('s', frame=999)['items'][0]['id'] == ids[0]
    assert store.incident_page('s', frame=999, baseline_generation=2)['items'] == []


def test_retention_archives_every_row_before_deletion_and_protects_recent(tmp_path):
    store = EvidenceStore(tmp_path / 'events.db')
    for session, date in [('old', 1), ('retained', 2), ('current', .5)]:
        store.append(session, 'incident', date, incident())
        store.append(session, 'model_error', date, {'incident_id': 1, 'error': 'preserved'})
    original = store.all_events('old')
    preview = retention_preview(store, 'current', 10, 1)
    assert [s['session'] for s in preview['sessions']] == ['old']
    result = archive_sessions(store, preview)
    assert store.all_events('old') == []
    assert EvidenceStore(result['archive']).all_events('old') == original
    assert store.count('current') == 2 and store.count('retained') == 2
    compact_store(store)
    assert store.count('current') == 2


def test_stale_retention_does_not_remove_evidence(tmp_path):
    store = EvidenceStore(tmp_path / 'events.db')
    store.append('old', 'incident', 1, incident()); store.append('current', 'frame', 2, {})
    preview = retention_preview(store, 'current', 10, 1)
    store.append('old', 'incident_assessment', 3, {'incident_id': 1, 'note': 'late'})
    with pytest.raises(RuntimeError, match='变化'): archive_sessions(store, preview)
    assert store.count('old') == 2


def test_workspace_backup_restores_managed_pixels_configuration_and_models_inactive(tmp_path):
    database = tmp_path / 'source' / 'evidence.db'
    store = EvidenceStore(database)
    store.append('s', 'incident', 1, {'images': {'current': 'fixture'}, 'unknown': True})
    for name in ('datasets', 'acquisition', 'inspection-results', 'review-studies', 'evidence.db-vision-models'):
        directory = database.parent / name; directory.mkdir()
        (directory / 'pixel.png').write_bytes(b'pixel identity')
    config = database.with_name(database.name + '-model.json')
    config.write_text(json.dumps({'policy': {**DEFAULT_POLICY, 'autostart': True, 'auto_restart': True}}))
    target = tmp_path / 'workspace.zip'
    manifest = backup_workspace(store, target)
    result = restore_workspace(target, tmp_path / 'restored')
    assert EvidenceStore(result['database']).all_events('s') == store.all_events('s')
    for name in ('datasets', 'acquisition', 'inspection-results', 'review-studies', 'evidence.db-vision-models'):
        assert (tmp_path / 'restored' / name / 'pixel.png').read_bytes() == b'pixel identity'
    policy = json.loads((tmp_path / 'restored' / config.name).read_bytes())['policy']
    assert not policy['autostart'] and not policy['auto_restart']
    assert manifest['excluded'] and target.exists() and config.exists()
    with pytest.raises(ValueError, match='已存在'): restore_workspace(target, tmp_path / 'restored')


def test_corrupt_and_traversal_archive_cannot_publish_workspace(tmp_path):
    store = EvidenceStore(tmp_path / 'source' / 'evidence.db')
    store.append('s', 'incident', 1, incident())
    original = tmp_path / 'original.zip'; backup_workspace(store, original)
    broken = tmp_path / 'broken.zip'
    with ZipFile(original) as source, ZipFile(broken, 'w') as target:
            for name in source.namelist():
                data = source.read(name)
                target.writestr(name, bytes([data[0] ^ 1]) + data[1:] if name.startswith('workspace/') else data)
    with pytest.raises(ValueError, match='摘要'): restore_workspace(broken, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()
    traversal = tmp_path / 'traversal.zip'
    with ZipFile(traversal, 'w') as target:
        target.writestr('manifest.json', json.dumps({'schema_version': 1, 'database': 'evidence.db', 'files': {'../evidence.db': {'bytes': 0}, 'evidence.db': {'bytes': 0}}}))
        target.writestr('workspace/../evidence.db', b''); target.writestr('workspace/evidence.db', b'')
    with pytest.raises(ValueError, match='越界'): restore_workspace(traversal, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def test_api_pagination_archive_download_backup_and_busy_guard(tmp_path):
    with TestClient(create_app(tmp_path / 'api.db', serve_frontend=False)) as client:
        station = client.app.state.station
        for i in range(205): station.monitor.store.append('old', 'incident', i + 1, incident(i))
        page = client.get('/api/sessions/old/incidents', params={'page': True, 'limit': 50}).json()
        assert len(page['items']) == 50 and page['next_before']
        client.post('/api/capture', json={'action': 'start'}).raise_for_status()
        assert client.post('/api/maintenance/workspace-backup').status_code == 409
        client.post('/api/capture', json={'action': 'pause'}).raise_for_status()
        response = client.post('/api/maintenance/workspace-backup')
        assert response.status_code == 200 and response.content.startswith(b'PK')
        command = {'before': 999, 'keep_latest': 1}
        preview = client.post('/api/maintenance/retention-preview', json=command).json()
        assert preview['events'] == 205
        assert client.post('/api/maintenance/archive', json=command).status_code == 409
        result = client.post('/api/maintenance/archive', json={**command, 'token': preview['token']})
        assert result.status_code == 200
        assert client.get('/api/sessions/old/incidents').json() == []
        archive = client.get('/api/maintenance/archives').json()[0]
        assert client.get('/api/maintenance/archives/' + archive['id']).content.startswith(b'SQLite format 3')
        station.maintenance_busy = True
        assert client.post('/api/capture', json={'action': 'start'}).status_code == 409
        assert client.get('/api/state').status_code == 200
        station.maintenance_busy = False
