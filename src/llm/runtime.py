"""Owned Ollama subprocesses shared by the CLI and local workstation.

Never reconstruct ownership from a PID receipt or attach to an occupied port.
"""

from pathlib import Path
import socket
import errno
import os
import subprocess
import threading
import time

import httpx

from src.acquisition import write_json
from .deployment import ROOT, preflight, serving_environment
from .spark_client import SparkXClient
from .runtime_log import RuntimeLog
from .faults import check_cancel


class OwnedRuntime:
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.RLock()
        self.close_lock = threading.Lock()
        self.cancel = threading.Event()
        self.process = None
        self.importer = None
        self.log_path = None
        self.receipt = None
        self.log = None
        self.report = {}

    @property
    def owned(self):
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def start(self, size, port, executable=None, report=None):
        if self.owned:
            raise RuntimeError('本应用的服务已启动')
        report = report or preflight(size, executable)
        if not report['ready']:
            raise ValueError('部署条件不足：检查运行时与官方权重校验结果')
        environment = serving_environment(port)
        with socket.socket() as listener_probe:
            listener_probe.settimeout(.2)
            if listener_probe.connect_ex(('127.0.0.1', port)) == 0:
                raise OSError(errno.EADDRINUSE, 'Local service port is occupied')
        with socket.socket() as probe:
            if os.name != 'nt': probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
        endpoint = f'http://127.0.0.1:{port}'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log_path = self.directory / f'ollama-{port}.log'
        self.receipt = self.directory / f'ollama-{port}.json'
        self.report = {**report, 'endpoint': endpoint, 'log': str(self.log_path)}
        try:
            self.log = RuntimeLog(self.log_path)
            with self.lock:
                if self.cancel.is_set():
                    raise RuntimeError('启动已取消')
                if self.owned:
                    raise RuntimeError('本应用的服务已启动')
                self.process = subprocess.Popen([report['runtime_cli'], 'serve'], cwd=ROOT,
                                                env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
                self.report['child_pid'] = self.process.pid
                self.log.attach(self.process)
            deadline = time.monotonic() + 60
            with httpx.Client(timeout=2, trust_env=False) as client:
                while True:
                    check_cancel(self.cancel)
                    if not self.owned: raise RuntimeError('Ollama 已退出，请查看日志')
                    try:
                        response = client.get(endpoint + '/api/version')
                        response.raise_for_status()
                        runtime = response.json()
                        break
                    except (httpx.HTTPError, ValueError):
                        if time.monotonic() >= deadline: raise RuntimeError('服务就绪超时，请查看日志')
                        self.cancel.wait(.25)
            modelfile = ROOT / 'models' / ('Modelfile-4b' if size == '4b' else 'Modelfile')
            with self.lock:
                check_cancel(self.cancel)
                self.importer = subprocess.Popen([report['runtime_cli'], 'create', report['model'],
                    '-f', str(modelfile)], cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
            self.log.attach(self.importer)
            deadline = time.monotonic() + 240
            while self.importer.poll() is None:
                if self.cancel.wait(.1): raise RuntimeError('启动已取消')
                if time.monotonic() >= deadline: raise RuntimeError('模型导入超时，请查看日志')
            if self.importer.returncode: raise RuntimeError('模型导入失败，请查看日志')
            client = SparkXClient(report['model'], base_url=endpoint)
            if not client.initialize(): raise RuntimeError(client.last_error)
            if self.cancel.is_set() or not self.owned: raise RuntimeError('启动已取消或服务退出')
            self.report.update(status='ready', child_pid=self.process.pid, runtime=runtime,
                               model_details=client.details, started=time.time(),
                               settings={k: v for k, v in environment.items() if k.startswith('OLLAMA_')})
            write_json(self.receipt, self.report)
            return client
        except BaseException:
            self.close()
            raise

    def import_model(self, size, report, cancel):
        if not self.owned or not report['ready']: raise RuntimeError('候选模型文件或服务尚未就绪')
        modelfile = ROOT/'models'/('Modelfile-4b' if size == '4b' else 'Modelfile')
        check_cancel(cancel)
        with self.lock:
            if not self.owned or self.cancel.is_set(): raise RuntimeError('服务已停止')
            self.importer = subprocess.Popen([self.report['runtime_cli'], 'create', report['model'], '-f', str(modelfile)],
                cwd=ROOT, env=serving_environment(int(self.report['endpoint'].rsplit(':',1)[1])),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
            process = self.importer
            self.log.attach(process)
        try:
            deadline = time.monotonic()+240
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic() > deadline: raise TimeoutError('候选模型导入超时')
                cancel.wait(.1)
            if process.returncode: raise RuntimeError('候选模型导入失败，请查看服务日志')
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)

    def close(self):
        self.cancel.set()
        with self.close_lock:
            with self.lock:
                processes = self.importer, self.process
            for process in processes:
                if process is not None and process.poll() is None:
                    try: process.terminate()
                    except ProcessLookupError: pass
                    try: process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            if self.log is not None: self.log.finish()
            if self.receipt is not None:
                write_json(self.receipt, {**self.report, 'status': 'stopped', 'stopped': time.time()})

    def log_tail(self, limit=16384):
        if self.log_path is None or not self.log_path.is_file(): return ''
        with self.log_path.open('rb') as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - limit))
            return handle.read(limit).decode('utf-8', errors='replace')
