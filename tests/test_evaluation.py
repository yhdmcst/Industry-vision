"""Explicit denominators, abstention, source isolation and like-for-like comparisons."""

import copy
import json

from fastapi.testclient import TestClient
import pytest

from scripts.create_demo_dataset import create_demo
from scripts.create_demo_results import create_results
from src.api.app import create_app
from src.datasets import digest
from src.evaluation import evaluate_replay, compare_replays


@pytest.fixture
def replay():
    # Labels and predictions are scripted independently to assert exact confusion counts.
    outcomes = [('defect', True, 'ok'), ('defect', False, 'ok'),
                ('normal', True, 'ok'), ('normal', False, 'ok'),
                ('defect', None, 'error'), ('normal', None, 'timeout'),
                ('unknown', None, 'missing'), ('unknown', True, 'ok')]
    cause_labels = ['product', 'optical', 'none', 'none', 'mechanical', 'illumination', 'unknown', 'none']
    predictions = ['product', 'none', 'product', 'none', 'unknown', 'illumination', 'none', 'none']
    samples = [{'id': 'baseline', 'sha256': 'b' * 64, 'split': 'baseline', 'batch': 'reference', 'origin': 'real', 'perturbation': 'none'}]
    results = []
    for i, ((label, ng, status), expected, predicted) in enumerate(zip(outcomes, cause_labels, predictions)):
        sample = {'id': f's{i}', 'sha256': str(i) * 64, 'split': 'evaluation',
                  'batch': 'batch-a' if i < 4 else 'batch-b',
                  'origin': 'real' if i < 4 else 'synthetic',
                  'perturbation': 'blur' if i == 3 else 'none',
                  'label': {'defect': label, 'cause': expected}}
        samples.append(sample)
        results.append({'sample_id': sample['id'], 'image_sha256': sample['sha256'],
                        'detection': {'status': status, 'is_ng': ng, 'confidence': .93 if status == 'ok' else None},
                        'rule_report': {'drift_type': predicted}, 'warmup': i == 7})
    config = {'dataset_id': 'd' * 64, 'baseline_ids': ['baseline'],
              'evaluation_ids': [s['id'] for s in samples[1:]],
              'thresholds': {'a': 1}, 'window_size': 50, 'measurement_source_sha256': 'f' * 64,
              'normalization': 'fixed', 'software': {'python': '3.12'}, 'detector': 'external_results',
              'inspection_source': {'kind': 'external_results', 'provenance': 'upstream', 'result_id': 'e' * 64}}
    return {'session': 'left', 'dataset': {'name': 'Scripted test', 'samples': samples},
            'config': config, 'results': results, 'results_sha256': digest(results),
            'replay': {'completed': True, 'fingerprint': digest(config)},
            'label_provenance': 'imported_user_annotations_not_independently_verified'}


def test_confusion_denominators_abstention_and_cohorts(replay):
    report = evaluate_replay(replay)
    binary = report['summary']['inspection']
    assert [binary[k] for k in ('tp', 'tn', 'fp', 'fn')] == [1, 1, 1, 1]
    assert binary['labeled'] == 6 and binary['assessed'] == 4
    assert binary['coverage'] == 4 / 6
    assert binary['unavailable_labeled'] == 2 and binary['unlabeled'] == 2
    assert all(binary[k] == .5 for k in ('label_agreement', 'precision', 'recall', 'miss_rate', 'false_positive_rate'))
    rules = report['summary']['rule']
    assert rules['labeled'] == 7 and rules['assessed'] == 5 and rules['abstained'] == 2
    assert rules['correct'] == 3 and rules['label_agreement'] == 3 / 5
    assert rules['matrix']['none']['unknown'] == 1
    assert rules['matrix']['optical']['none'] == 1
    assert [(g['batch'], g['cohort'], g['summary']['total']) for g in report['groups']] == [
        ('batch-a', 'real_perturbed', 1), ('batch-a', 'real_unmodified', 3), ('batch-b', 'synthetic', 4)]
    assert sum(g['summary']['total'] for g in report['groups']) == 8
    assert report['samples'][1]['inspection_mismatch']
    assert report['samples'][1]['rule_mismatch']
    assert not report['samples'][4]['inspection_mismatch']  # failure is not a false negative


def test_no_labels_zero_denominators_and_proxy_do_not_create_accuracy(replay):
    for sample in replay['dataset']['samples'][1:]:
        sample['label'] = {'defect': 'unknown', 'cause': 'unknown'}
    report = evaluate_replay(replay)
    for key in ('coverage', 'label_agreement', 'precision', 'recall', 'false_positive_rate', 'miss_rate'):
        assert report['summary']['inspection'][key] is None
    assert report['summary']['rule']['label_agreement'] is None
    assert report['summary']['rule']['coverage'] is None
    sample = replay['dataset']['samples'][1]
    sample['label']['defect'] = 'normal'
    replay['results'][0]['detection']['is_ng'] = False
    normal_only = evaluate_replay(replay)['summary']['inspection']
    assert normal_only['label_agreement'] == 1 and normal_only['false_positive_rate'] == 0
    assert normal_only['recall'] is None and normal_only['precision'] is None
    replay['config'].pop('inspection_source')  # imported old replay is still a proxy
    proxy = evaluate_replay(replay)
    assert not proxy['summary']['inspection']['enabled']
    assert proxy['summary']['inspection']['assessed'] == 0
    assert proxy['summary']['inspection']['label_agreement'] is None
    assert not any(s['inspection_mismatch'] for s in proxy['samples'])


def test_partial_and_empty_runs_keep_planned_label_denominators(replay):
    replay['results'] = replay['results'][:2]
    replay['replay']['completed'] = False
    report = evaluate_replay(replay)
    assert report['summary']['processed'] == 2 and report['summary']['not_run'] == 6
    assert report['summary']['inspection']['coverage'] == 2 / 6
    assert report['summary']['inspection']['not_run_labeled'] == 4
    assert report['samples'][-1]['detection_status'] is None
    assert report['summary']['rule']['not_run_labeled'] == 5
    replay['results'] = []
    empty = evaluate_replay(replay)['summary']
    assert empty['inspection']['label_agreement'] is None
    assert empty['inspection']['coverage'] == 0
    assert empty['detection_counts'] == dict(ok=0, error=0, timeout=0, missing=0)


def test_leakage_is_reported_by_hash_and_batch_without_dropping_samples(replay):
    samples = replay['dataset']['samples']
    samples[1]['sha256'] = samples[0]['sha256']
    samples[2]['sha256'] = samples[1]['sha256']
    samples[1]['batch'] = 'reference'
    for i in range(2): replay['results'][i]['image_sha256'] = samples[i+1]['sha256']
    report = evaluate_replay(replay)
    assert report['leakage']['baseline_duplicate_ids'] == ['s0', 's1']
    assert report['leakage']['evaluation_duplicate_ids'] == ['s0', 's1']
    assert report['leakage']['shared_batches'] == ['reference']
    assert report['leakage']['unique_evaluation_images'] == 7
    assert report['summary']['total'] == 8


@pytest.mark.parametrize('mutation', ['order', 'sample_id', 'image', 'extra'])
def test_result_alignment_rejected(replay, mutation):
    if mutation == 'order': replay['config']['evaluation_ids'].reverse()
    elif mutation == 'sample_id': replay['results'][0]['sample_id'] = 'unknown'
    elif mutation == 'image': replay['results'][0]['image_sha256'] = 'z' * 64
    else: replay['results'].append(copy.deepcopy(replay['results'][0]))
    with pytest.raises(ValueError): evaluate_replay(replay)


def test_comparison_pairs_only_common_rows_and_retains_failures(replay):
    other = copy.deepcopy(replay)
    other['session'] = 'right'
    other['config']['inspection_source']['result_id'] = 'a' * 64
    other['results'] = other['results'][:6]
    other['replay']['completed'] = False
    other['results'][1]['detection']['is_ng'] = True
    other['results'][4]['detection'] = {'status': 'ok', 'is_ng': True, 'confidence': .8}
    other['results'][0]['rule_report']['drift_type'] = 'unknown'
    result = compare_replays(replay, other)
    assert result['comparable'] and not result['both_completed']
    assert result['paired'] == 6 and result['left_only'] == 2 and result['right_only'] == 0
    assert result['both_ok'] == 4 and result['verdict_changes'] == 1
    assert result['status_changes'] == 1 and result['rule_changes'] == 1
    assert result['samples'][4]['verdict_changed'] is None
    assert result['paired_summaries'][0]['inspection']['assessed'] == 4
    assert result['paired_summaries'][1]['inspection']['assessed'] == 5
    assert result['paired_summaries'][0]['total'] == result['paired_summaries'][1]['total'] == 6


@pytest.mark.parametrize('key', ['dataset_id', 'baseline_ids', 'evaluation_ids', 'window_size', 'thresholds', 'software', 'measurement_source_sha256'])
def test_incomparable_config_never_produces_differences(replay, key):
    other = copy.deepcopy(replay)
    other['session'] = 'right'
    if key == 'evaluation_ids':
        # different valid replay order, rather than a broken export
        other['dataset']['samples'][1:] = reversed(other['dataset']['samples'][1:])
        other['results'].reverse()
        other['config'][key].reverse()
    else: other['config'][key] = 'different'
    result = compare_replays(replay, other)
    assert not result['comparable'] and result['samples'] == []
    assert result['paired_summaries'] is None
    assert any(key in reason for reason in result['reasons'])


def test_same_session_and_missing_implementation_digest_are_not_comparable(replay):
    assert not compare_replays(replay, replay)['comparable']
    other = copy.deepcopy(replay)
    other['session'] = 'right'
    for run in (replay, other): run['config'].pop('measurement_source_sha256')
    assert not compare_replays(replay, other)['comparable']


def test_pairing_rejects_changed_images_even_when_config_claims_the_same_dataset(replay):
    other = copy.deepcopy(replay)
    other['session'] = 'right'
    other['dataset']['samples'][1]['sha256'] = 'a' * 64
    other['results'][0]['image_sha256'] = 'a' * 64
    comparison = compare_replays(replay, other)
    assert not comparison['comparable'] and not comparison['samples']
    assert '样本或图像摘要不一致' in comparison['reasons']


def test_api_evaluation_is_read_only_and_survives_restart(tmp_path):
    manifest = create_demo(tmp_path / 'input')
    database = tmp_path / 'evidence.db'
    with TestClient(create_app(database, serve_frontend=False)) as client:
        dataset_id = client.post('/api/datasets/import', json={'path': str(manifest)}).json()['id']
        dataset = client.get(f'/api/datasets/{dataset_id}').json()
        path = create_results(dataset, tmp_path / 'results.json')
        result_id = client.post('/api/inspection-results/import', json={'path': str(path)}).json()['id']
        client.post('/api/replay', json={'dataset_id': dataset_id, 'result_id': result_id})
        client.post('/api/capture', json={'action': 'sample'})
        before = client.get('/api/state').json()
        session = before['session']
        count = client.app.state.station.monitor.store.count(session)
        first = client.get(f'/api/sessions/{session}/evaluation').json()
        assert first['summary']['detection_counts']['missing'] == 1
        assert first['summary']['inspection']['label_agreement'] is None
        assert first['samples'][0]['rule_prediction'] == 'unknown'
        assert first['leakage']['baseline_duplicate_ids'] == [f'sample-{i:03d}' for i in range(10, 20)]
        assert client.get(f'/api/sessions/{session}/evaluation').json() == first
        assert client.get('/api/state').json() == before
        assert client.app.state.station.monitor.store.count(session) == count
        assert client.get('/api/evaluation/compare', params={'left': session, 'right': session}).json()['comparable'] is False
        assert client.get('/api/sessions/missing/evaluation').status_code == 400
        assert client.get('/api/evaluation/compare', params={'left': '', 'right': session}).status_code == 422
        # The new history descriptor retains detector provenance without changing monitoring snapshots.
        assert client.get('/api/replays').json()[0]['inspection_source']['result_id'] == result_id
        assert 'label' not in json.dumps(client.app.state.station.monitor.snapshot()).replace('unlabeled', '')
        base = {k: v for k, v in first.items() if k != 'report_sha256'}
        assert digest(base) == first['report_sha256']
    with TestClient(create_app(database, serve_frontend=False)) as client:
        assert client.get(f'/api/sessions/{session}/evaluation').json() == first
        client.post('/api/replay', json={'dataset_id': dataset_id})
        right = client.get('/api/state').json()['session']
        compared = client.get('/api/evaluation/compare', params={'left': session, 'right': right}).json()
        assert compared['comparable'] and compared['paired'] == 0
        assert not compared['binary_enabled']
