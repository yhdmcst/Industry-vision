"""External predictions must align to samples and never turn unavailable data into OK."""

import copy
import json

from fastapi.testclient import TestClient
import pytest

from scripts.create_demo_dataset import create_demo
from scripts.create_demo_results import create_results
from src.api.app import create_app
from src.datasets import digest
from src.pipeline import ReviewFailure, review_snapshot


@pytest.fixture
def setup(tmp_path):
    path = create_demo(tmp_path / "input")
    with TestClient(create_app(tmp_path / "external.db", serve_frontend=False)) as client:
        dataset_id = client.post('/api/datasets/import', json={'path': str(path)}).json()['id']
        dataset = client.get(f'/api/datasets/{dataset_id}').json()
        package = {
            'schema_version': 1, 'dataset_id': dataset_id,
            'producer': {'name': 'Detector SENTINEL', 'version': '1.0', 'provenance': 'synthetic_fixture',
                         'score_semantics': 'decision_confidence'},
            'results': [{'sample_id': sample['id'], 'image_sha256': sample['sha256'], 'status': 'ok',
                         'detected': True, 'confidence': 0.95, 'is_ng': i >= 10,
                         'defect_types': ['scratch SENTINEL'] if i >= 10 else []}
                        for i, sample in enumerate(dataset['samples'])],
        }
        result_path = tmp_path / 'results.json'
        yield client, dataset_id, package, result_path


def import_package(client, package, path):
    path.write_text(json.dumps(package), encoding='utf-8')
    return client.post('/api/inspection-results/import', json={'path': str(path)})


def test_upstream_ng_is_used_without_proxy_and_repeats(setup, monkeypatch):
    client, dataset_id, package, path = setup
    response = import_package(client, package, path)
    assert response.status_code == 200, response.text
    result_id = response.json()['id']
    assert response.json()['counts']['ok'] == 40
    assert response.json()['baseline_ready']
    command = {'dataset_id': dataset_id, 'result_id': result_id}
    assert client.post('/api/replay', json=command).status_code == 200
    monitor = client.app.state.station.monitor
    def fail(*args):
        raise AssertionError('External mode must never call residual proxy')
    monkeypatch.setattr(monitor, 'detection', fail)
    for _ in range(10):
        assert client.post('/api/capture', json={'action': 'sample'}).status_code == 200
    state = client.get('/api/state').json()
    assert state['latest']['rule_report']['drift_type'] == 'product'
    assert state['latest']['rule_report']['metrics']['consistency']['ng_rate'] == 1
    assert state['latest']['detection']['metadata']['result']['defect_types'] == ['scratch SENTINEL']
    assert 'SENTINEL' not in json.dumps(monitor.snapshot())
    first = client.get('/api/replay/export').json()
    assert first['config']['inspection_source']['result_id'] == result_id
    assert digest(first['inspection_results']) == result_id
    assert len(first['inspection_results']['results']) == 40
    assert client.post('/api/replay', json=command).status_code == 200
    for _ in range(10):
        client.post('/api/capture', json={'action': 'sample'})
    second = client.get('/api/replay/export').json()
    assert first['results_sha256'] == second['results_sha256']
    assert first['replay']['fingerprint'] == second['replay']['fingerprint']
    assert client.get(f'/api/sessions/{first["session"]}/replay').json() == first
    client.post('/api/replay', json={'dataset_id': dataset_id})
    assert client.get('/api/state').json()['inspection_source']['kind'] == 'reference_residual_demo'


def test_missing_failure_timeout_keep_null_and_do_not_reuse_statistics(setup, monkeypatch):
    client, dataset_id, package, path = setup
    # Ten valid evaluation records, then missing, timeout, error, then valid.
    del package['results'][20]
    for index, status in [(20, 'timeout'), (21, 'error')]:
        old = package['results'][index]
        package['results'][index] = {k: old[k] for k in ('sample_id', 'image_sha256')}
        package['results'][index].update(status=status, error='untrusted SENTINEL')
    result = import_package(client, package, path).json()
    assert result['counts'] == {'ok': 37, 'missing': 1, 'timeout': 1, 'error': 1}
    assert client.post('/api/replay', json={'dataset_id': dataset_id, 'result_id': result['id']}).status_code == 200
    for _ in range(10):
        client.post('/api/capture', json={'action': 'sample'})
    monitor = client.app.state.station.monitor
    assert monitor.latest['rule_report']['metrics']['consistency']['ng_rate'] == 1
    for status in ('missing', 'timeout', 'error'):
        client.post('/api/capture', json={'action': 'sample'})
        latest = monitor.latest
        assert latest['detection']['status'] == status
        assert latest['detection']['confidence'] is None and latest['detection']['is_ng'] is None
        assert latest['rule_report']['metrics']['consistency'] == {}
        assert latest['rule_report']['confidence_score'] is None
        assert latest['warmup']
    # Unavailable statuses enrich the ongoing episode instead of creating duplicate incidents.
    incidents = monitor.store.events(monitor.session, kind='incident')
    assert len(incidents) == 1
    incident = monitor.store.events(monitor.session, kind='incident_updated')[-1]['payload']
    assert incident['incident_id'] == incidents[0]['id']
    assert incident['trigger'] == 'inspection_unavailable'
    assert incident['detection']['metadata']['result']['error'] == 'untrusted SENTINEL'
    assert 'SENTINEL' not in json.dumps(incident['snapshot'])
    captured = {}
    def generate(self, prompt, **kwargs):
        captured['prompt'] = prompt
        raise RuntimeError('test stop before inference')
    monkeypatch.setattr('src.pipeline.SparkXClient.generate', generate)
    with pytest.raises(ReviewFailure):
        review_snapshot(monitor.snapshot(), '', 'test', 'http://127.0.0.1:11435')
    assert 'SENTINEL' not in captured['prompt']
    assert '"NG百分数当前与基线": [null, 0.0]' in captured['prompt']
    assert '外部文件中的上游判定' in captured['prompt']
    assert '当前检测状态": "error"' in captured['prompt']


@pytest.mark.parametrize('mutation', ['duplicate', 'unknown_sample', 'wrong_image', 'nan', 'failed_verdict',
                                     'missing_score', 'ok_defects', 'unknown_field', 'wrong_dataset', 'score_type'])
def test_invalid_result_import_is_atomic(setup, mutation):
    client, dataset_id, package, path = setup
    before = client.get('/api/state').json()
    record = package['results'][0]
    if mutation == 'duplicate': package['results'].append(copy.deepcopy(record))
    elif mutation == 'unknown_sample': record['sample_id'] = 'unknown'
    elif mutation == 'wrong_image': record['image_sha256'] = '0' * 64
    elif mutation == 'nan': record['confidence'] = float('nan')
    elif mutation == 'failed_verdict': record['status'] = 'timeout'
    elif mutation == 'missing_score': del record['confidence']
    elif mutation == 'ok_defects': record['defect_types'] = ['scratch']
    elif mutation == 'unknown_field': record['ground_truth'] = 'normal'
    elif mutation == 'wrong_dataset': package['dataset_id'] = '0' * 64
    else: package['producer']['score_semantics'] = 'anomaly_score'
    response = import_package(client, package, path)
    assert response.status_code == 400, response.text
    assert client.get('/api/state').json() == before
    assert client.get(f'/api/datasets/{dataset_id}/inspection-results').json() == []


def test_baseline_failure_keeps_old_session_and_versioning_is_stable(setup):
    client, dataset_id, package, path = setup
    first = import_package(client, package, path).json()
    package['results'].reverse()
    assert import_package(client, package, path).json()['id'] == first['id']
    package['results'] = [r for r in package['results'] if r['sample_id'] != 'sample-000']
    second = import_package(client, package, path).json()
    assert not second['baseline_ready'] and second['id'] != first['id']
    before = client.get('/api/state').json()
    assert client.post('/api/replay', json={'dataset_id': dataset_id, 'result_id': second['id']}).status_code == 400
    assert client.get('/api/state').json() == before
    assert len(client.get(f'/api/datasets/{dataset_id}/inspection-results').json()) == 2


def test_unavailable_window_ages_out_and_baseline_is_preserved():
    from src.monitoring import DetectionRecord
    from src.monitoring.consistency_tracker import ConsistencyTracker
    tracker = ConsistencyTracker(window_size=10)
    tracker.set_baseline([DetectionRecord(i, True, .9, False) for i in range(10)])
    tracker.add_record(DetectionRecord(0, None, None, None, status='missing'))
    for i in range(9): tracker.add_record(DetectionRecord(i, True, .9, True))
    assert tracker.calculate_metrics() is None
    tracker.add_record(DetectionRecord(10, True, .9, True))
    assert tracker.calculate_metrics().ng_rate == 1
    assert tracker.baseline.ng_rate == 0


def test_baseline_uses_all_samples_and_invalid_update_is_atomic():
    from src.monitoring import DetectionRecord
    from src.monitoring.consistency_tracker import ConsistencyTracker
    tracker = ConsistencyTracker(window_size=10)
    tracker.add_record(DetectionRecord(0, True, .8, False))
    records = [DetectionRecord(i, True, .9, i < 10) for i in range(20)]
    baseline = tracker.set_baseline(records)
    assert baseline.ng_rate == .5
    assert len(tracker.records) == 1 and tracker.get_summary()['total_count'] == 1
    records[-1].confidence = None
    with pytest.raises(ValueError):
        tracker.set_baseline(records)
    assert tracker.baseline is baseline
    assert len(tracker.records) == 1 and tracker.get_summary()['total_count'] == 1
    with pytest.raises(ValueError, match='verdict'):
        tracker.add_record(DetectionRecord(1, None, .9, None))


def test_fixture_unknown_state_and_historical_export_after_restart(setup, tmp_path):
    client, dataset_id, _, path = setup
    dataset = client.get(f'/api/datasets/{dataset_id}').json()
    create_results(dataset, path)
    result_id = client.post('/api/inspection-results/import', json={'path': str(path)}).json()['id']
    client.post('/api/replay', json={'dataset_id': dataset_id, 'result_id': result_id})
    client.post('/api/capture', json={'action': 'sample'})
    latest = client.get('/api/state').json()['latest']
    assert latest['detection']['status'] == 'missing'
    assert latest['rule_report']['drift_type'] == 'unknown'
    assert latest['rule_report']['confidence_score'] is None
    assert latest['rule_report']['metrics']['image_drift']['drift_detected'] is False
    exported = client.get('/api/replay/export').json()
    assert digest(exported['inspection_results']) == result_id
    with TestClient(create_app(tmp_path / 'external.db', serve_frontend=False)) as restarted:
        assert restarted.get(f'/api/sessions/{exported["session"]}/replay').json() == exported
        assert restarted.get(f'/api/inspection-results/{result_id}').status_code == 200
    with pytest.raises(FileExistsError):
        create_results(dataset, path)


def test_missing_corrupt_and_mismatched_versions_keep_session(setup, tmp_path):
    client, dataset_id, package, path = setup
    package['producer']['provenance'] = 'upstream'
    result_id = import_package(client, package, path).json()['id']
    assert client.post('/api/replay', json={'dataset_id': dataset_id, 'result_id': result_id}).status_code == 200
    assert client.get('/api/state').json()['inspection_source']['provenance'] == 'upstream'
    other_path = create_demo(tmp_path / 'other')
    other = json.loads(other_path.read_text(encoding='utf-8'))
    other['name'] = 'Another dataset'
    other_path.write_text(json.dumps(other), encoding='utf-8')
    other_id = client.post('/api/datasets/import', json={'path': str(other_path)}).json()['id']
    before = client.get('/api/state').json()
    response = client.post('/api/replay', json={'dataset_id': other_id, 'result_id': result_id})
    assert response.status_code == 400 and '不匹配' in response.text
    assert client.post('/api/replay', json={'dataset_id': dataset_id, 'result_id': '0' * 64}).status_code == 400
    stored = tmp_path / 'inspection-results' / f'{result_id}.json'
    modified = json.loads(stored.read_text(encoding='utf-8'))
    modified['producer']['version'] = 'modified'
    stored.write_text(json.dumps(modified), encoding='utf-8')
    assert client.get(f'/api/inspection-results/{result_id}').status_code == 400
    assert client.get('/api/replay/export').status_code == 400
    assert client.post('/api/replay', json={'dataset_id': dataset_id, 'result_id': result_id}).status_code == 400
    assert client.get('/api/state').json() == before
    # Current replay retains its immutable loaded package despite registry corruption.
    assert client.post('/api/capture', json={'action': 'sample'}).status_code == 200
    assert client.get('/api/state').json()['latest']['inspection_source']['producer']['version'] == '1.0'
