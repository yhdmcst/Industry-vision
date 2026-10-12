import json
import threading
import time
import pytest
from src.llm import management, validation
from src.llm.spark_client import OFFICIAL_WEIGHT_DIGESTS
from src.llm.faults import OperationCancelled

FIRST='spark-drift:1.7b-q4'; SECOND='spark-drift:4b-q4'


def manager(tmp_path):
    m=management.ModelManager(tmp_path/'test.db',{'name':FIRST,'endpoint':'http://127.0.0.1:11439'},threading.RLock(),lambda:False)
    m.connected=True; m.checked_at=time.time(); m.details={'original':True}
    m.configure(FIRST,m.endpoint)
    return m


def record(name,endpoint,*args):
    return {'id':name,'name':name,'endpoint':endpoint,'created':time.time(),'status':'passed',
            'details':{'weight_sha256':OFFICIAL_WEIGHT_DIGESTS[name],'runtime_version':'fixture'}}


def test_validation_then_switch_and_rollback_persist_versions(tmp_path,monkeypatch):
    m=manager(tmp_path)
    monkeypatch.setattr(management,'validate_model',record)
    for action,target in [('validate',FIRST),('switch',SECOND),('rollback',FIRST)]:
        m.launch(action,target if action=='switch' else None); m.worker.join(3)
        assert not m.error and m.name==target and m.snapshot()['validation']['name']==target
    assert m.previous_name==SECOND and len(m.validations)==3
    restored=management.ModelManager(tmp_path/'test.db',{'name':FIRST,'endpoint':m.endpoint},threading.RLock(),lambda:False)
    assert restored.previous_name==SECOND and restored.active_validation()['name']==FIRST and not restored.connected
    with pytest.raises(RuntimeError,match='候选自检'): restored.configure(SECOND,m.endpoint)


@pytest.mark.parametrize('failure',['generation','save','cancel'])
def test_failed_candidate_keeps_original_config_and_availability(tmp_path,monkeypatch,failure):
    m=manager(tmp_path); before=m.config_path.read_bytes()
    def candidate(name,endpoint,*args):
        if failure=='generation': raise RuntimeError('malformed response')
        if failure=='cancel': m.cancel_event.set()
        return record(name,endpoint)
    monkeypatch.setattr(management,'validate_model',candidate)
    if failure=='save':
        def fail(*args): raise OSError('full disk')
        monkeypatch.setattr(management,'write_json',fail)
    m.launch('switch',SECOND); m.worker.join(3)
    assert m.error and m.name==FIRST and m.connected and m.details=={'original':True}
    assert m.config_path.read_bytes()==before and m.previous_name is None and not m.validations


def test_gate_requires_actual_generation_and_parseable_contract(monkeypatch):
    calls=[]
    class Client:
        details={'runtime_version':'fixture'};last_error='';last_metrics={};policy={}
        def __init__(self,*args,**kw): pass
        def initialize(self): return True
        def generate(self,*args,**kw): calls.append('generation');return '{}'
    monkeypatch.setattr(validation,'SparkXClient',Client)
    with pytest.raises(ValueError,match='Invalid'): validation.validate_model(FIRST,'http://127.0.0.1:11439')
    assert calls==['generation']


def test_deployment_evidence_is_frozen_before_async_review(tmp_path,monkeypatch):
    from concurrent.futures import Future
    from src.pipeline import Monitor
    m=Monitor(tmp_path/'evidence.db'); captured=[]
    monkeypatch.setattr(m,'snapshot',lambda:{'fixture':'frozen measurement'})
    def submit(*args): captured.append(args); return Future()
    monkeypatch.setattr('src.pipeline.REVIEW_POOL.submit',submit)
    proof={'id':'version-1','details':{'weight':'original'}}
    m.request_review('',FIRST,'http://127.0.0.1:11439',deployment=proof)
    proof['details']['weight']='changed'
    assert captured[0][-2]['details']['weight']=='original'
    m.pending=None;m.close()
