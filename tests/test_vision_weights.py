"""Checkpoint download never publishes unchecked or partial weights."""

import hashlib

import pytest

from scripts.fetch_vision_weights import fetch


def test_checkpoint_hash_publication_and_existing_evidence(monkeypatch, tmp_path):
    content = b'fixed fixture checkpoint'
    monkeypatch.setattr('scripts.fetch_vision_weights.WEIGHTS_SHA256', hashlib.sha256(content).hexdigest())
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_bytes(self): yield content
    monkeypatch.setattr('scripts.fetch_vision_weights.httpx.stream', lambda *a, **kw: Response())
    path = tmp_path / 'model.pth'
    assert fetch(path) == path and path.read_bytes() == content
    assert fetch(path) == path
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='Existing'):
        fetch(path)
    assert path.read_bytes() == b'corrupt'
    monkeypatch.setattr('scripts.fetch_vision_weights.WEIGHTS_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='digest'):
        fetch(tmp_path / 'bad.pth')
    assert not (tmp_path / 'bad.pth').exists() and not list(tmp_path.glob('.weights-*'))
