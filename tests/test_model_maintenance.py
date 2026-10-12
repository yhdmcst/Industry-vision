import io
import threading
import errno
from pathlib import Path
import pytest
from src.llm.runtime_log import RuntimeLog
from src.llm.faults import describe_fault, OperationCancelled
from src.llm import management


def test_rotation_bounds_all_files_and_keeps_recent_tail(tmp_path):
    log = RuntimeLog(tmp_path/'service.log', max_bytes=100, backups=3)
    for i in range(20): log.append(bytes([i])*70)
    files = list(tmp_path.iterdir())
    assert len(files) == 4 and all(p.stat().st_size <= 100 for p in files)
    assert log.tail().encode() == bytes([19])*70


def test_failed_log_write_still_drains_process(tmp_path, monkeypatch):
    log = RuntimeLog(tmp_path/'service.log')
    stream = io.BytesIO(b'x'*20000)
    class Process: stdout = stream
    def fail(data): raise OSError(errno.ENOSPC, 'full')
    monkeypatch.setattr(log, 'append', fail)
    log.attach(Process()); log.finish()
    assert stream.closed and log.error


def test_cancel_preflight_prevents_late_start_and_allows_retry(tmp_path, monkeypatch):
    m = management.ModelManager(tmp_path/'test.db', {'name':'spark-drift:1.7b-q4','endpoint':'http://127.0.0.1:11438'}, threading.RLock(), lambda:False)
    entered, release = threading.Event(), threading.Event()
    def check(*args):
        entered.set(); release.wait(3)
        return {'ready':False}
    monkeypatch.setattr(management, 'preflight', check)
    m.launch('check'); assert entered.wait(3)
    m.cancel_operation(); release.set(); m.worker.join(3)
    assert m.fault['code'] == 'cancelled' and m.operation is None
    m.launch('check'); m.worker.join(3)
    assert not m.error and m.deployment['ready'] is False and m.deployment['model'] == m.name
    m.close()


def test_fault_remedy_has_actionable_port_resolution():
    fault = describe_fault(OSError(errno.EADDRINUSE, 'busy'))
    assert fault['code'] == 'port_busy' and '端口' in fault['remedy']


def test_existing_oversized_logs_adopt_new_retention_limit(tmp_path):
    path = tmp_path/'service.log'
    for index in range(4):
        (path if not index else tmp_path/f'service.log.{index}').write_bytes(b'x'*1000+b'tail')
    log = RuntimeLog(path,max_bytes=100,backups=3)
    assert all(file.stat().st_size==100 for file in tmp_path.iterdir())
    assert log.tail().endswith('tail')
