import pytest

from src.llm.research_client import BASELINE, ResearchClient
from src.llm.spark_client import SparkXClient


@pytest.mark.parametrize('fault', [None, 'family', 'digest', 'name', 'family_suffix'])
def test_pinned_research_identity_never_widens_workstation_models(monkeypatch, fault):
    name = 'unplanned:model' if fault == 'name' else BASELINE['model_name']
    family = 'spark2_5' if fault == 'family' else BASELINE['family']+'-unknown' if fault == 'family_suffix' else BASELINE['family']
    weight = 'unverified' if fault == 'digest' else BASELINE['sha256']
    def request(method, path, **kwargs):
        if path == '/api/version': return {'version': 'explicit-fixture'}
        return {'details': {'family': family}, 'modelfile': 'FROM /blob/sha256-'+weight}
    research = ResearchClient(name)
    monkeypatch.setattr(research, '_request', request)
    assert research.initialize() is (fault is None)
    production = SparkXClient(BASELINE['model_name'])
    monkeypatch.setattr(production, '_request', request)
    assert not production.initialize()
