import threading
import time
from types import SimpleNamespace
import pytest
from src.llm import management
from src.llm.policy import DEFAULT_POLICY, validate_policy
from src.llm.spark_client import SparkXClient
from fastapi.testclient import TestClient
from src.api.app import create_app


def manager(tmp_path): return management.ModelManager(tmp_path/'test.db',{'name':'spark-drift:1.7b-q4','endpoint':'http://127.0.0.1:11439'},threading.RLock(),lambda:False)


@pytest.mark.parametrize('key,value',[('timeout_seconds',True),('timeout_seconds',601),('timeout_seconds',29),('keep_alive_minutes',-1),('keep_alive_minutes',61),('autostart',1),('auto_restart','true'),('profile','unlimited')])
def test_invalid_policy_is_rejected(key,value):
    with pytest.raises(ValueError): validate_policy({**DEFAULT_POLICY,key:value})


def test_policy_survives_restart_but_does_not_claim_process_ownership(tmp_path):
    m=manager(tmp_path); m.set_policy({**DEFAULT_POLICY,'autostart':True,'auto_restart':True,'keep_alive_minutes':0})
    restored=manager(tmp_path)
    assert restored.policy['autostart'] and restored.policy['keep_alive_minutes']==0
    assert restored.policy['profile']=='custom' and not restored.want_owned and not restored.runtime.owned


def test_failed_policy_save_preserves_prior_settings(tmp_path,monkeypatch):
    m=manager(tmp_path)
    def fail(*args): raise OSError('full disk')
    monkeypatch.setattr(management,'write_json',fail)
    with pytest.raises(OSError): m.set_policy({**DEFAULT_POLICY,'autostart':True})
    assert m.policy==DEFAULT_POLICY


def test_autostart_requires_explicit_opt_in(tmp_path,monkeypatch):
    for enabled in [False,True]:
        m=manager(tmp_path);m.policy['autostart']=enabled; calls=[]
        monkeypatch.setattr(m,'launch',lambda action:calls.append(action))
        m.start_health()
        assert calls==(['start'] if enabled else [])
        m.close()


def test_recovery_is_bounded_and_never_takes_ownership_of_external_service(tmp_path,monkeypatch):
    m=manager(tmp_path);m.policy['auto_restart']=True
    now=[10000.];monkeypatch.setattr(management.time,'monotonic',lambda:now[0]); calls=[]
    monkeypatch.setattr(m,'launch',lambda action,**kw:calls.append(action))
    for _ in range(5):m.recover_if_needed()
    assert not calls
    m.want_owned=True
    for _ in range(6):
        for i in range(3): m.recover_if_needed()
        now[0]+=31
    assert calls==['start']*3 and '3 次' in m.recovery_message
    m.pending=lambda:True;now[0]+=601;m.recover_if_needed();assert len(calls)==3
    m.pending=lambda:False;m.recover_if_needed();assert len(calls)==4


def test_selected_policy_reaches_real_request_and_metrics(monkeypatch):
    c=SparkXClient(policy={**DEFAULT_POLICY,'keep_alive_minutes':0,'timeout_seconds':90})
    c._initialized=True;c.details={'family':'spark2_5'};requests=[]
    def request(method,path,**kw):
        requests.append(kw['json']);return {'message':{'content':'valid fixture'},'done_reason':'stop'}
    monkeypatch.setattr(c,'_request',request)
    assert c.generate('input')=='valid fixture'
    assert requests[0]['keep_alive']=='0m'
    assert 'timeout_seconds' not in requests[0]['options'] and 'keep_alive_minutes' not in requests[0]['options']
    assert c.last_metrics['request_settings']['timeout_seconds']==90
    assert c.last_metrics['request_settings']['keep_alive_minutes']==0


def test_policy_api_rejects_unknown_and_out_of_range_input(tmp_path):
    with TestClient(create_app(tmp_path/'api.db',serve_frontend=False)) as client:
        assert client.post('/api/model/policy',json={**DEFAULT_POLICY,'timeout_seconds':True}).status_code==422
        assert client.post('/api/model/policy',json={**DEFAULT_POLICY,'unknown':True}).status_code==422
        assert client.post('/api/model/policy',json=DEFAULT_POLICY).status_code==200
        assert client.get('/api/state').json()['model']['policy']==DEFAULT_POLICY


def test_explicit_configuration_or_external_connection_clears_recovery_intent(tmp_path):
    m=manager(tmp_path);m.want_owned=True;m.recovery_attempts=[time.monotonic()]
    m.configure(m.name,'http://127.0.0.1:11441')
    assert not m.want_owned and not m.recovery_attempts
    m.want_owned=True
    class Client:
        details={};last_error=''
        def __init__(self,*args,**kw):pass
        def initialize(self):return True
    m.connect(m.name,m.endpoint,client_factory=Client)
    assert not m.want_owned


def test_explicit_empty_policy_is_not_silently_defaulted():
    with pytest.raises(ValueError): SparkXClient(policy={})


def test_known_owned_process_exit_is_immediately_unavailable(tmp_path):
    m=manager(tmp_path);m.connected=True;m.checked_at=time.time();m.want_owned=True
    m.runtime.process=SimpleNamespace(poll=lambda:1)
    assert not m.snapshot()['connected'] and not m.snapshot()['owned']
