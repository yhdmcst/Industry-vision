"""Independent research runner rejects stale evidence and cleans up its owned service."""
from types import SimpleNamespace

import pytest

from scripts import run_review_experiment as runner


@pytest.fixture
def setup(monkeypatch, tmp_path):
    suite = tmp_path/'suite.json'
    suite.write_text('{}')
    output = tmp_path/'experiment'
    monkeypatch.setattr('sys.argv', ['experiment', '--suite', str(suite), '--output', str(output)])
    frozen = {'schema_version': 2, 'source_sha256': {}, 'source': {}}
    monkeypatch.setattr(runner, 'load_suite', lambda _: {'suite': frozen})
    monkeypatch.setattr(runner, 'source_digests', lambda: {})
    monkeypatch.setattr(runner, 'verify_weight', lambda *_: True)
    monkeypatch.setattr(runner.signal, 'signal', lambda *_: None)
    calls = []
    runtime = SimpleNamespace(report={'runtime_cli': 'test-cli'}, cancel=None,
                              start=lambda *_: calls.append('start'),
                              import_model=lambda *_: calls.append('import'),
                              close=lambda: calls.append('close'))
    monkeypatch.setattr(runner, 'OwnedRuntime', lambda _: runtime)
    monkeypatch.setattr(runner, 'preflight', lambda *_: {})
    return suite, output, frozen, calls, runtime


@pytest.mark.parametrize('fault', ['version', 'source', 'consumed'])
def test_invalid_suite_rejected_before_start(setup, fault):
    suite, output, frozen, calls, _ = setup
    if fault == 'version': frozen['schema_version'] = 1
    elif fault == 'source': frozen['source_sha256'] = {'changed': 'digest'}
    else:
        frozen['source']['single_use'] = True
        suite.with_name('suite.json.consumed.json').write_text('original receipt')
    with pytest.raises(ValueError): runner.main()
    assert not calls and not output.exists()


def test_failed_import_closes_owned_runtime(setup, monkeypatch):
    _, _, _, calls, runtime = setup
    runtime.import_model = lambda *_: (_ for _ in ()).throw(RuntimeError('import failed'))
    with pytest.raises(RuntimeError, match='import failed'): runner.main()
    assert calls == ['start', 'close']


def test_interrupted_inference_closes_owned_runtime(setup, monkeypatch):
    _, _, _, calls, _ = setup
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *_, **__: SimpleNamespace(
        wait=lambda **_: None, returncode=0))
    monkeypatch.setattr(runner, 'ResearchClient', lambda *_, **__: SimpleNamespace(initialize=lambda: True))
    monkeypatch.setattr(runner, 'run', lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt): runner.main()
    assert calls == ['start', 'import', 'close']
