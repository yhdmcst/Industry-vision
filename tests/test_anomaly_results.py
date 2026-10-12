"""Anomaly scores preserve NG semantics without manufacturing confidence or old-version hashes."""

import copy
import json

from fastapi.testclient import TestClient
import pytest

from scripts.create_demo_dataset import create_demo
from src.api.app import create_app
from src.datasets import digest
from src.inspection.results import ResultPackage


@pytest.fixture
def setup(tmp_path):
    path = create_demo(tmp_path / 'dataset')
    declared = json.loads(path.read_bytes())
    for sample in declared['samples']:
        sample['label'] = {'defect': 'normal' if sample['split'] == 'baseline' else 'defect', 'cause': 'unknown'}
    path.write_text(json.dumps(declared))
    with TestClient(create_app(tmp_path / 'anomaly.db', serve_frontend=False)) as client:
        dataset = client.post('/api/datasets/import', json={'path': str(path)}).json()
        manifest = client.get('/api/datasets/' + dataset['id']).json()
        package = {'schema_version': 2, 'dataset_id': dataset['id'], 'producer': {
            'name': 'PaDiM SENTINEL', 'version': 'test', 'provenance': 'synthetic_fixture',
            'score_semantics': 'anomaly_score', 'decision_threshold': 2.},
            'results': [{'sample_id': s['id'], 'image_sha256': s['sha256'], 'status': 'ok',
                         'detected': True, 'is_ng': s['split'] == 'evaluation',
                         'anomaly_score': 3. if s['split'] == 'evaluation' else 1.,
                         'alignment': {'status': 'disabled'}} for s in manifest['samples']]}
        yield client, package, tmp_path / 'results.json'


def publish(client, package, path):
    path.write_text(json.dumps(package))
    return client.post('/api/inspection-results/import', json={'path': str(path)})


def test_real_verdict_window_keeps_confidence_null_and_unknown_data_unavailable(setup):
    client, package, path = setup
    old = package['results'][20]
    package['results'][20] = {'sample_id': old['sample_id'], 'image_sha256': old['image_sha256'],
                              'status': 'error', 'error': 'ALIGNMENT_SENTINEL',
                              'alignment': {'status': 'rejected', 'error': 'ALIGNMENT_SENTINEL'}}
    result = publish(client, package, path)
    assert result.status_code == 200, result.text
    result_id = result.json()['id']
    assert client.post('/api/replay', json={'dataset_id': package['dataset_id'], 'result_id': result_id}).status_code == 200
    for _ in range(10):
        assert client.post('/api/capture', json={'action': 'sample'}).status_code == 200
    monitor = client.app.state.station.monitor
    current = monitor.latest['rule_report']
    assert current['metrics']['consistency']['ng_rate'] == 1
    for key in ('confidence_mean', 'confidence_std', 'confidence_min', 'confidence_max', 'stability_score'):
        assert current['metrics']['consistency'][key] is None
    assert current['confidence_score'] is None
    assert current['drift_type'] == 'product'
    assert 'SENTINEL' not in json.dumps(monitor.snapshot())
    client.post('/api/capture', json={'action': 'sample'})
    assert monitor.latest['detection']['status'] == 'error'
    assert monitor.latest['detection']['is_ng'] is None
    assert monitor.latest['rule_report']['metrics']['consistency'] == {}
    replay = client.get('/api/replay/export').json()
    report = client.get('/api/sessions/' + replay['session'] + '/evaluation').json()
    assert report['samples'][0]['anomaly_score'] == 3.
    assert report['samples'][10]['alignment']['status'] == 'rejected'
    assert report['summary']['inspection']['unavailable_labeled'] == 1
    assert digest(replay['inspection_results']) == result_id


@pytest.mark.parametrize('mutation', ['version', 'confidence', 'missing_score', 'nan', 'verdict', 'threshold',
                                    'confidence_mode', 'failed_score', 'rejected_ok', 'incomplete_alignment'])
def test_invalid_semantics_are_rejected_atomically(setup, mutation):
    client, package, path = setup
    row = package['results'][0]
    if mutation == 'version': package['schema_version'] = 1
    elif mutation == 'confidence': row['confidence'] = .9
    elif mutation == 'missing_score': del row['anomaly_score']
    elif mutation == 'nan': row['anomaly_score'] = float('nan')
    elif mutation == 'verdict': row['is_ng'] = True
    elif mutation == 'threshold': del package['producer']['decision_threshold']
    elif mutation == 'confidence_mode': package['producer']['score_semantics'] = 'decision_confidence'
    elif mutation == 'failed_score': row.update(status='error', error='test')
    elif mutation == 'rejected_ok': row['alignment'] = {'status': 'rejected', 'error': 'test'}
    else: row['alignment'] = {'status': 'passed'}
    before = client.get('/api/state').json()
    assert publish(client, package, path).status_code == 400
    assert client.get('/api/state').json() == before
    assert client.get('/api/datasets/' + package['dataset_id'] + '/inspection-results').json() == []


def test_version_one_canonical_identity_is_preserved(setup):
    client, package, path = setup
    old = copy.deepcopy(package)
    old['schema_version'] = 1
    old['producer'].pop('decision_threshold')
    old['producer']['score_semantics'] = 'decision_confidence'
    for row in old['results']:
        row.pop('anomaly_score'); row.pop('alignment'); row['confidence'] = .9
    result = publish(client, old, path)
    assert result.status_code == 200
    saved = client.get('/api/inspection-results/' + result.json()['id']).json()
    assert 'decision_threshold' not in saved['producer']
    assert all('anomaly_score' not in row and 'alignment' not in row for row in saved['results'])
    canonical = ResultPackage.model_validate(old).model_dump(exclude={
        'producer': {'decision_threshold'}, 'results': {'__all__': {'anomaly_score', 'alignment'}}})
    assert digest(canonical) == result.json()['id']
    assert publish(client, old, path).json()['id'] == result.json()['id']
