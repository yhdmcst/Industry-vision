"""Cross-source selection, provenance, stale checks and immutable publication."""

import json

from fastapi.testclient import TestClient
import pytest

from src.api.app import create_app
from src.dataset_checks import batch_key


@pytest.fixture
def station(tmp_path):
    with TestClient(create_app(tmp_path / 'composition.db', serve_frontend=False)) as client:
        sources = []
        for name in ('same display name', 'same display name'):
            batch = client.post('/api/acquisition/batches', json={'name': name}).json()
            samples = []
            for index in range(11):
                preview = client.post('/api/acquisition/preview').json()
                response = client.post(f'/api/acquisition/batches/{batch["id"]}/samples', json={
                    'token': preview['token'], 'split': 'baseline' if index < 10 else 'evaluation', 'origin': 'synthetic'})
                assert response.status_code == 200, response.text
                samples.append(response.json())
            sources.append({'id': batch['id'], 'samples': samples})
        yield client, sources


def command(sources):
    return {'name': 'Cross batch', 'description': 'LABEL_WITHHELD', 'selections': [
        {'kind': 'capture', 'source_id': sources[0]['id'], 'sample_id': s['id'], 'split': 'baseline'}
        for s in sources[0]['samples'][:10]] + [
        {'kind': 'capture', 'source_id': sources[1]['id'], 'sample_id': sources[1]['samples'][-1]['id'], 'split': 'evaluation'}]}


def publish(client, payload):
    checked = client.post('/api/composition/preflight', json=payload)
    assert checked.status_code == 200, checked.text
    result = client.post('/api/composition/publish', json=payload | {'checked_sha256': checked.json()['checked_sha256']})
    assert result.status_code == 200, result.text
    return result.json(), checked.json()


def test_publish_cross_capture_batches_preserves_evidence_and_session(station):
    client, sources = station
    payload = command(sources)
    before = client.get('/api/state').json()
    result, checked = publish(client, payload)
    assert not checked['checks']['shared_batch_keys']
    assert checked['checks']['shared_batches'] == ['same display name']
    assert checked['checks']['baseline_duplicate_ids']  # synthetic fixture, not statistical evidence
    manifest = client.get(f'/api/datasets/{result["id"]}').json()
    assert manifest['samples'][-1]['lineage']['sample_id'] == sources[1]['samples'][-1]['id']
    assert manifest['samples'][-1]['conditions']['capture_batch_id'] == sources[1]['id']
    assert manifest['samples'][0]['batch'] == sources[0]['samples'][0]['batch']
    after = client.get('/api/state').json()
    for key in ('session', 'baseline', 'latest', 'frame_count', 'alert', 'replay'):
        assert after[key] == before[key]
    assert publish(client, payload)[0] == result
    assert client.post('/api/replay', json={'dataset_id': result['id']}).status_code == 200
    assert client.post('/api/capture', json={'action': 'sample'}).status_code == 200
    snapshot = client.app.state.station.monitor.snapshot()
    assert 'LABEL_WITHHELD' not in json.dumps(snapshot)
    report = client.get(f'/api/sessions/{after["session"]}/evaluation')
    assert report.status_code != 200  # publication did not create a replay in the old session
    session = client.get('/api/state').json()['session']
    assert not client.get(f'/api/sessions/{session}/evaluation').json()['leakage']['shared_batch_keys']


def test_stale_annotation_or_command_cannot_publish(station):
    client, sources = station
    payload = command(sources)
    checked = client.post('/api/composition/preflight', json=payload).json()
    record = sources[1]['samples'][-1]
    assert client.patch(f'/api/acquisition/batches/{sources[1]["id"]}/samples/{record["id"]}', json={
        'split': 'evaluation', 'label': {'defect': 'defect', 'cause': 'product'}}).status_code == 200
    assert client.post('/api/composition/publish', json=payload | {'checked_sha256': checked['checked_sha256']}).status_code == 409
    assert client.post('/api/composition/publish', json=payload | {'name': 'Changed', 'checked_sha256': checked['checked_sha256']}).status_code == 409
    assert client.get('/api/datasets').json() == []
    result, _ = publish(client, payload)
    assert client.get(f'/api/datasets/{result["id"]}').json()['samples'][-1]['label']['defect'] == 'defect'


@pytest.mark.parametrize('mutation', ['duplicate', 'missing_sample', 'missing_source', 'invalid_source', 'baseline_defect', 'baseline_count'])
def test_bad_selection_publishes_nothing(station, mutation):
    client, sources = station
    payload = command(sources)
    if mutation == 'duplicate': payload['selections'][-1] = payload['selections'][0]
    elif mutation == 'missing_sample': payload['selections'][-1]['sample_id'] = 'missing'
    elif mutation == 'missing_source': payload['selections'][-1]['source_id'] = '0' * 32
    elif mutation == 'invalid_source': payload['selections'][-1]['source_id'] = '0' * 64
    elif mutation == 'baseline_count': payload['selections'][0]['split'] = 'evaluation'
    else:
        sample = sources[1]['samples'][-1]
        client.patch(f'/api/acquisition/batches/{sources[1]["id"]}/samples/{sample["id"]}', json={
            'split': 'evaluation', 'label': {'defect': 'defect'}})
        payload['selections'][-1]['split'] = 'baseline'
    assert client.post('/api/composition/preflight', json=payload).status_code in (400, 422)
    assert client.get('/api/datasets').json() == []


def test_nested_dataset_preserves_original_identity_and_rejects_reselection(station):
    client, sources = station
    result, _ = publish(client, command(sources))
    manifest = client.get(f'/api/datasets/{result["id"]}').json()
    payload = {'name': 'Nested', 'selections': [{'kind': 'dataset', 'source_id': result['id'],
               'sample_id': s['id'], 'split': s['split']} for s in manifest['samples']]}
    nested, _ = publish(client, payload)
    second = client.get(f'/api/datasets/{nested["id"]}').json()
    assert [s['lineage'] for s in second['samples']] == [s['lineage'] for s in manifest['samples']]
    payload['selections'].append(command(sources)['selections'][-1])
    response = client.post('/api/composition/preflight', json=payload)
    assert response.status_code == 400 and '原始样本' in response.text


def test_capture_dataset_publication_maps_back_to_capture_identity(station):
    client, sources = station
    dataset = client.post(f'/api/acquisition/batches/{sources[0]["id"]}/publish').json()
    manifest = client.get(f'/api/datasets/{dataset["id"]}').json()
    payload = command(sources)
    payload['selections'].append({'kind': 'dataset', 'source_id': dataset['id'], 'sample_id': manifest['samples'][0]['id'], 'split': 'evaluation'})
    response = client.post('/api/composition/preflight', json=payload)
    assert response.status_code == 400 and '原始样本' in response.text


def test_bad_pixels_and_storage_failure_leave_sources_and_versions_unchanged(station, monkeypatch):
    client, sources = station
    payload = command(sources)
    checked = client.post('/api/composition/preflight', json=payload).json()
    record = sources[1]['samples'][-1]
    path = client.app.state.station.acquisition.directory(sources[1]['id']) / record['id'] / 'image.png'
    original = path.read_bytes()
    path.write_bytes(b'corrupt')
    assert client.post('/api/composition/publish', json=payload | {'checked_sha256': checked['checked_sha256']}).status_code == 400
    path.write_bytes(original)
    def fail(*args, **kwargs): raise OSError('disk fixture')
    monkeypatch.setattr(client.app.state.station.datasets, 'import_manifest', fail)
    assert client.post('/api/composition/publish', json=payload | {'checked_sha256': checked['checked_sha256']}).status_code == 409
    assert not client.get('/api/datasets').json()
    assert not list(client.app.state.station.datasets.root.glob('.compose-*'))
    assert client.get(f'/api/acquisition/batches/{sources[1]["id"]}').json()['samples'][-1] == record


def test_batch_identity_uses_recorded_id_not_name():
    first = {'batch': 'new name', 'conditions': {'capture_batch_id': 'a'}}
    second = {'batch': 'old name', 'conditions': {'capture_batch_id': 'a'}}
    assert batch_key(first) == batch_key(second)
    assert batch_key(first) != batch_key({'batch': 'new name', 'conditions': {'capture_batch_id': 'b'}})


def test_historical_composition_survives_restart_and_source_label_changes(station):
    client,sources=station
    result,_=publish(client,command(sources))
    manifest=client.get(f'/api/datasets/{result["id"]}').json()
    record=sources[1]['samples'][-1]
    client.patch(f'/api/acquisition/batches/{sources[1]["id"]}/samples/{record["id"]}',json={
        'split':'evaluation','label':{'defect':'defect','cause':'product'}})
    second,_=publish(client,command(sources))
    assert second['id']!=result['id']
    assert client.get(f'/api/datasets/{result["id"]}').json()==manifest
    with TestClient(create_app(client.app.state.station.monitor.store.path,serve_frontend=False)) as restarted:
        assert restarted.get(f'/api/datasets/{result["id"]}').json()==manifest
        assert restarted.post('/api/replay',json={'dataset_id':result['id']}).status_code==200
        restarted.post('/api/capture',json={'action':'sample'})
        assert restarted.get('/api/replay/export').json()['dataset']['samples'][-1]['lineage']==manifest['samples'][-1]['lineage']
