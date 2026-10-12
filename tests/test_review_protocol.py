"""Held-out protocol tests use explicit local fixtures, never real model acceptance."""

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts import compare_review_methods as cli
from scripts.prepare_visa import REVISION, CSV_SHA256, URL, ETAG
from src.llm.prompt_builder import review_checks


@pytest.mark.parametrize('response,shift,expected', [(.25, 16, False), (.2501, 8, False),
                                                   (.99, 16, True), (.1, 100, False)])
def test_arithmetic_checks_respect_registration_reliability_and_strict_boundaries(response, shift, expected):
    snapshot = {'current_metrics': {'relative_changes': {'brightness_change': -.2, 'sharpness_change': -.3},
                                   'registration': {'response': response, 'shift_x': shift, 'shift_y': 0},
                                   'consistency': {'ng_rate': 0}},
                'baseline': {'consistency': {'ng_rate': 0}}, 'warmup': False,
                'detection_availability': {'unavailable': 0}}
    checks = review_checks(snapshot)
    assert checks['可靠位移同时满足两个条件'] is expected
    assert not checks['亮度变化绝对值超过20%'] and not checks['清晰度下降超过30%']
    assert checks['NG当前高于基线'] is False
    snapshot['detection_availability']['unavailable'] = 1
    assert review_checks(snapshot)['NG当前高于基线'] is None
    assert not review_checks(snapshot)['NG当前与基线均可用']
    assert not any(key in checks for key in ('drift_type', 'expected_type', 'root_cause'))


@pytest.fixture
def frozen_run(tmp_path, monkeypatch):
    path = tmp_path/'suite.json'
    sealed = {'suite_id': 'fixture-id', 'suite': {'source_sha256': {'fixture': 'digest'},
                                               'source': {'single_use': True}}}
    path.write_text(json.dumps(sealed))
    monkeypatch.setattr(cli, 'load_suite', lambda value: value)
    monkeypatch.setattr(cli, 'source_digests', lambda: {'fixture': 'digest'})
    return path, tmp_path


def test_held_out_consumption_is_acquired_before_inference_and_refuses_retry(frozen_run, monkeypatch):
    suite, root = frozen_run
    calls = []
    def execute(*args):
        assert json.loads(Path(str(suite)+'.consumed.json').read_bytes())['status'] == 'started'
        calls.append(args)
        return {'study_id': 'explicit-fixture', 'report_sha256': 'fixture-report'}
    monkeypatch.setattr(cli, 'execute_run', execute)
    cli.run(suite, root/'first', 'fixture-endpoint')
    assert json.loads(Path(str(suite)+'.consumed.json').read_bytes())['status'] == 'completed'
    with pytest.raises(FileExistsError): cli.run(suite, root/'second', 'fixture-endpoint')
    assert len(calls) == 1


def test_interrupted_held_out_run_remains_consumed_and_source_mismatch_does_not_consume(frozen_run, monkeypatch):
    suite, root = frozen_run
    monkeypatch.setattr(cli, 'source_digests', lambda: {'fixture': 'changed'})
    with pytest.raises(ValueError, match='Source changed'): cli.run(suite, root/'changed', 'fixture-endpoint')
    assert not Path(str(suite)+'.consumed.json').exists()
    monkeypatch.setattr(cli, 'source_digests', lambda: {'fixture': 'digest'})
    def interrupted(*args): raise KeyboardInterrupt('explicit interruption fixture')
    monkeypatch.setattr(cli, 'execute_run', interrupted)
    with pytest.raises(KeyboardInterrupt): cli.run(suite, root/'aborted', 'fixture-endpoint')
    assert json.loads(Path(str(suite)+'.consumed.json').read_bytes())['status'] == 'aborted'
    with pytest.raises(FileExistsError): cli.run(suite, root/'retry', 'fixture-endpoint')


def test_pinned_source_preparation_verifies_pixels_and_observed_root_exclusion(tmp_path, monkeypatch):
    source = tmp_path/'source'; source.mkdir(); rows = []
    for i in range(11):
        # Explicit deterministic image fixtures, not public data or cause truth.
        frame = np.full((480, 640, 3), 100, dtype=np.uint8)
        cv2.rectangle(frame, (40+i*4, 50), (300+i*4, 250), (200, 130, 80), -1)
        ok, data = cv2.imencode('.png', frame); assert ok
        image = f'{i:04d}.png'; (source/image).write_bytes(data.tobytes())
        rows.append({'split': 'train' if i < 10 else 'test', 'label': 'normal', 'image': image,
                     'sha256': hashlib.sha256(data.tobytes()).hexdigest()})
    metadata = {'dataset': 'VisA', 'category': 'explicit-fixture', 'revision': REVISION,
                'split_sha256': CSV_SHA256, 'url': URL, 'etag': ETAG, 'license': 'CC BY 4.0', 'files': rows}
    (source/'source.json').write_text(json.dumps(metadata))
    observed = tmp_path/'observed.json'; observed.write_text('{}')
    prior = {'sealed_suite': {'suite': {'cases': [{'root_id': '0'*64}]}}}
    monkeypatch.setattr(cli, 'validate_pack', lambda value: prior)
    suite = cli.prepare_source(source, tmp_path/'suite.json', [observed], roots=1)
    assert len(suite['suite']['cases']) == 5
    assert suite['suite']['source']['single_use']
    assert suite['suite']['source']['official_source']['source_sha256']
    assert suite['suite']['cases'][0]['root_id'] == rows[-1]['sha256']
    prior['sealed_suite']['suite']['cases'][0]['root_id'] = rows[-1]['sha256']
    with pytest.raises(ValueError, match='overlap'): cli.prepare_source(source, tmp_path/'overlap.json', [observed], roots=1)
    assert not (tmp_path/'overlap.json').exists()
    (source/rows[-1]['image']).write_bytes(b'corrupt fixture pixels')
    with pytest.raises(ValueError, match='pixels changed'): cli.prepare_source(source, tmp_path/'corrupt.json', [observed], roots=1)
    with pytest.raises(ValueError, match='Declare observed'): cli.prepare_source(source, tmp_path/'undeclared.json', [], roots=1)
