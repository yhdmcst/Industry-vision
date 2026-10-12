"""Persistent model selection, asynchronous deployment and live local health facts."""

import copy
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

from src.acquisition import write_json
from .deployment import preflight, resource_snapshot, runtime_plan, model_manifest, weight_stamp
from . import deployment
from .runtime import OwnedRuntime
from .preparation import prepare_model
from .validation import validate_model
from .policy import DEFAULT_POLICY, PRESETS, validate_policy
from .faults import check_cancel, describe_fault, ModelFault
from .spark_client import SparkXClient, OFFICIAL_WEIGHT_DIGESTS
from .tasks import ModelTasks
from .faults import OperationCancelled

HEALTH_INTERVAL = 5
STALE_AFTER = 15


def validate_selection(name, endpoint):
    try:
        SparkXClient(name, base_url=endpoint)  # validate loopback origin, including port syntax
    except ValueError as exc:
        raise ValueError('服务地址须为本机 HTTP 地址，不能包含账号、路径或查询参数') from exc
    parsed = urlsplit(endpoint)
    port = parsed.port or 80
    if name not in OFFICIAL_WEIGHT_DIGESTS:
        raise ValueError('只支持官方 1.7B / 4B Q4 模型')
    if not 1024 <= port <= 65535:
        raise ValueError('模型服务端口须为 1024..65535')
    return endpoint.rstrip('/')


def validate_executable(value):
    if not isinstance(value, str) or len(value) > 2000 or '\0' in value:
        raise ValueError('运行时路径无效')
    if value and not Path(value).expanduser().is_absolute():
        raise ValueError('请填写运行时的完整绝对路径，留空则自动发现')
    return str(Path(value).expanduser()) if value else ''


class ModelManager:
    def __init__(self, database: Path, defaults: dict, lock, pending):
        self.lock = lock
        self.pending = pending
        self.config_path = database.with_name(database.name + '-model.json')
        self.directory = database.parent / (database.name + '-model-runtime')
        self.name, self.endpoint = defaults['name'], defaults['endpoint']
        self.executable = ''
        self.validations = []
        self.previous_name = None
        self.policy = dict(DEFAULT_POLICY)
        self.want_owned = False
        self.recovery_attempts = []
        self.health_failures = 0
        self.recovery_message = ''
        self.connected = False
        self.details = {}
        self.checked_at = None
        self.error = ''
        self.config_read_error = False
        self.health_error = ''
        self.loaded = []
        self.resident_checked_at = None
        self.resources = {}
        self.resources_checked_at = None
        self.deployment = None
        self.deployments = {}
        self.operation = None
        self.tasks = ModelTasks(database)
        self.task_id = None
        self.task_error = ''
        self.cancel_event = threading.Event()
        self.fault = None
        self.progress = None
        self.revision = 0
        self.runtime = OwnedRuntime(self.directory)
        self.stop_event = threading.Event()
        self.worker = None
        self.health_thread = threading.Thread(target=self._health_loop, name='model-health', daemon=True)
        if self.config_path.is_file():
            try:
                config = json.loads(self.config_path.read_bytes())
                endpoint = validate_selection(config['name'], config['endpoint'])
                executable = validate_executable(config.get('executable', ''))
                validations = config.get('validations', [])
                if not isinstance(validations, list) or any(not isinstance(record,dict) for record in validations):
                    raise ValueError('模型验收记录格式无效')
                policy = validate_policy(config.get('policy', DEFAULT_POLICY))
                previous_name = config.get('previous_name')
                deployments = config.get('deployments', {})
                if not isinstance(deployments, dict) or any(name not in OFFICIAL_WEIGHT_DIGESTS or not isinstance(report,dict) or report.get('model') != name for name,report in deployments.items()):
                    raise ValueError('模型文件检查记录格式无效')
                if previous_name is not None and previous_name not in OFFICIAL_WEIGHT_DIGESTS:
                    raise ValueError('上一模型版本无效')
                self.name, self.endpoint, self.executable = config['name'], endpoint, executable
                self.validations, self.policy, self.previous_name = validations[-10:], policy, previous_name
                self.deployments = deployments
                self.deployment = deployments.get(self.name)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.error = f'模型配置读取失败，使用默认选择：{exc}'
                self.config_read_error = True

    def start_health(self):
        self.health_thread.start()
        if self.policy['autostart']:
            try: self.launch('start')
            except (ValueError, RuntimeError) as exc:
                with self.lock: self.error = str(exc); self.fault = describe_fault(exc)

    def _require_idle(self):
        if self.stop_event.is_set(): raise RuntimeError('应用正在关闭')
        if self.operation is not None: raise RuntimeError('模型管理操作进行中，请等待完成')
        if self.pending(): raise RuntimeError('模型复核进行中，请等待完成后操作')

    def _persist(self, name, endpoint, executable, validations=None, previous_name=None, policy=None, deployments=None):
        write_json(self.config_path, {'name':name, 'endpoint':endpoint, 'executable':executable,
            'validations':self.validations if validations is None else validations,
            'previous_name':self.previous_name if previous_name is None else previous_name,
            'policy':self.policy if policy is None else policy,
            'deployments':self.deployments if deployments is None else deployments})

    def _save(self, name, endpoint, executable=None):
        endpoint = validate_selection(name, endpoint)
        executable = self.executable if executable is None else validate_executable(executable)
        if self.validations and name != self.name:
            raise RuntimeError('已验收模型须通过候选自检后切换')
        if self.runtime.owned and (name, endpoint, executable) != (self.name, self.endpoint, self.executable):
            raise RuntimeError('请先停止本应用的服务，再切换模型或端口')
        try:
            self._persist(name, endpoint, executable)
        except OSError as exc:
            raise RuntimeError(f'模型配置保存失败，原选择保留：{exc}') from exc
        if (name, endpoint, executable) != (self.name, self.endpoint, self.executable):
            self.connected = False
            self.details = {}
            self.checked_at = None
            self.loaded = []
            self.resident_checked_at = None
            self.deployment = self.deployments.get(name)
            self.health_error = ''
            self.want_owned = False
            self.recovery_attempts = []
            self.recovery_message = ''
        self.name, self.endpoint = name, endpoint
        self.config_read_error = False
        self.executable = executable
        self.error = ''
        self.fault = None

    def set_policy(self, value):
        policy = validate_policy(value)
        with self.lock:
            self._require_idle()
            self._persist(self.name, self.endpoint, self.executable, policy=policy)
            self.policy = policy
            self.revision += 1
            self.error = ''
            self.fault = None

    def configure(self, name, endpoint, executable=None):
        with self.lock:
            self._require_idle()
            self._save(name, endpoint, executable)
            self.revision += 1

    def connect(self, name, endpoint, client_factory=SparkXClient, executable=None):
        with self.lock:
            self._require_idle()
            try:
                self._save(name, endpoint, executable)
            except (ValueError, RuntimeError) as exc:
                self.error = str(exc)
                raise
            if not self.runtime.owned: self.want_owned = False
            self.task_id = self.tasks.begin('connect', name)
            self.operation = 'connect'
            self.revision += 1
            self.loaded = []
            self.resident_checked_at = None
        outcome, task_error = 'succeeded', ''
        try:
            client = client_factory(name, base_url=self.endpoint)
            if not client.initialize(): raise RuntimeError(client.last_error)
            with self.lock:
                self.connected = True
                self.details = dict(client.details)
                self.checked_at = time.time()
                self.health_error = ''
        except (ValueError, RuntimeError) as exc:
            outcome, task_error = 'failed', str(exc)
            with self.lock:
                self.connected = False
                self.details = {}
                self.checked_at = time.time()
                self.error = str(exc)
                self.fault = describe_fault(exc)
            raise
        finally:
            with self.lock:
                self._finish_task(outcome, task_error)
                self.operation = None

    def launch(self, action, name=None, automatic=False):
        if action not in ('check', 'start', 'stop', 'restart', 'prepare', 'validate', 'switch', 'rollback'): raise ValueError('不支持的模型管理操作')
        with self.lock:
            self._require_idle()
            target = self.previous_name if action == 'rollback' else name or self.name
            validate_selection(target, self.endpoint)
            if action in ('validate','switch','rollback') and not self.snapshot()['connected']:
                raise RuntimeError('请先启动服务或核验连接')
            if action == 'switch' and target == self.name: raise ValueError('请选择不同的候选模型')
            if action == 'rollback' and not self.previous_name: raise ValueError('尚无可恢复版本')
            if action not in ('prepare','switch','rollback') and target != self.name: raise ValueError('此操作仅支持当前模型')
            if action == 'start' and self.runtime.owned: raise RuntimeError('本应用的服务已启动')
            if action == 'start' and not runtime_plan(self.executable or None)['start_supported']:
                raise ValueError('当前系统／架构不支持本地启动')
            if action in ('stop', 'restart') and not self.runtime.owned: raise RuntimeError('没有本应用拥有的服务；不能停止外部服务')
            if action in ('start', 'restart') and urlsplit(self.endpoint).hostname != '127.0.0.1':
                raise ValueError('页面启动服务须使用 http://127.0.0.1:<端口>')
            if action == 'stop': self.want_owned = False
            if action in ('start','restart') and not automatic:
                self.recovery_attempts = []
                self.recovery_message = ''
            self.task_id = self.tasks.begin(action, target)
            self.operation, self.error = action, ''
            self.fault = None
            self.progress = None
            self.cancel_event = threading.Event()
            self.revision += 1
            self.worker = threading.Thread(target=self._operate, args=(action, target), name='model-operation', daemon=True)
            self.worker.start()

    def _operate(self, action, target):
        outcome, task_error = 'succeeded', ''
        try:
            if action == 'restart':
                self.runtime.close()
                with self.lock: self.connected = False
            check_cancel(self.cancel_event)
            if action in ('validate','switch','rollback'):
                self._validate_and_select(action, target)
            elif action == 'prepare':
                report = prepare_model('4b' if target == 'spark-drift:4b-q4' else '1.7b', self.executable or None, self.cancel_event, self._set_progress)
                check_cancel(self.cancel_event)
                self._record_deployment(report, target)
            elif action == 'stop':
                self.runtime.close()
                with self.lock:
                    self.connected = False
                    self.details = {}
                    self.loaded = []
                    self.resident_checked_at = None
                    self.checked_at = time.time()
                    self.health_error = ''
            else:
                report = preflight('4b' if self.name == 'spark-drift:4b-q4' else '1.7b', self.executable or None, self.cancel_event)
                self._record_deployment(report, target)
                check_cancel(self.cancel_event)
                if self.stop_event.is_set(): raise OperationCancelled('工作台正在关闭')
                if action in ('start', 'restart'):
                    if not report['ready']:
                        raise ModelFault('not_prepared','部署文件尚未准备完成','点击下载并准备模型，再重新检查部署条件。',report.get('runtime_error',''))
                    with self.lock:
                        if self.stop_event.is_set(): raise OperationCancelled('工作台正在关闭')
                        check_cancel(self.cancel_event)
                        self.runtime = OwnedRuntime(self.directory)
                        self.runtime.cancel = self.cancel_event
                    client = self.runtime.start('4b' if self.name == 'spark-drift:4b-q4' else '1.7b',
                                                urlsplit(self.endpoint).port, report=report)
                    with self.lock:
                        self.connected = True
                        self.want_owned = True
                        self.health_failures = 0
                        self.recovery_message = ''
                        self.details = dict(client.details)
                        self.checked_at = time.time()
                        self.health_error = ''
                        self.loaded = []
                        self.resident_checked_at = None
        except Exception as exc:
            outcome = 'cancelled' if isinstance(exc, OperationCancelled) else 'failed'
            task_error = str(exc)
            with self.lock:
                self.error = str(exc)
                self.fault = describe_fault(exc)
                self.fault['impact'] = '采集和人工核验可继续；请重新检查模型可用状态。'
                if action in ('start', 'stop', 'restart'):
                    self.connected = False
                    self.details = {}
                    self.loaded = []
                    self.resident_checked_at = None
        finally:
            with self.lock:
                self._finish_task(outcome, task_error)
                self.operation = None

    def _finish_task(self, outcome, error):
        try:
            self.tasks.update(self.task_id, status=outcome, finished=time.time(),
                              stage={'succeeded':'操作完成', 'failed':'操作失败', 'cancelled':'操作已取消'}[outcome], error=error)
            self.task_error = ''
        except Exception as exc:
            # An operation may already have changed the runtime; journal failure is a separate fact.
            self.task_error = f'操作结果未能保存：{exc}'
            record = next((record for record in self.tasks.records if record['id'] == self.task_id), None)
            if record is not None:
                record.update(status=outcome, finished=time.time(), stage='结果未保存', error=error)
        finally:
            self.task_id = None

    def _record_deployment(self, report, target):
        with self.lock:
            if self.config_read_error: raise RuntimeError('模型配置读取失败，原文件已保留；请先保存有效模型选择，再执行部署检查。')
            checks = {**self.deployments, target: {**report, 'model': target}}
            self._persist(self.name, self.endpoint, self.executable, deployments=checks)
            self.deployments = checks
            if target == self.name: self.deployment = checks[target]

    def _validate_and_select(self, action, target):
        if target != self.name and self.runtime.owned:
            report = preflight('4b' if '4b' in target else '1.7b', self.executable or None, self.cancel_event)
            self._record_deployment(report, target)
            self._set_progress({'phase':'导入候选模型'})
            self.runtime.import_model('4b' if '4b' in target else '1.7b', report, self.cancel_event)
        self._set_progress({'phase':'真实推理自检'})
        record = validate_model(target, self.endpoint, self.cancel_event, self.policy)
        with self.lock:
            check_cancel(self.cancel_event)
            if self.stop_event.is_set(): raise OperationCancelled('工作台正在关闭')
            records = (self.validations + [record])[-10:]
            previous = self.name if target != self.name else self.previous_name
            # Publish configuration only after real inference and durable atomic save succeed.
            self._persist(target, self.endpoint, self.executable, records, previous)
            self.validations, self.previous_name = records, previous
            self.name = target
            self.connected = True
            self.checked_at = time.time()
            self.details = record['details']
            self.loaded = []
            self.resident_checked_at = None
            self.health_error = ''
            self.deployment = self.deployments.get(target)

    def active_validation(self):
        for record in reversed(self.validations):
            if (record.get('name'), record.get('endpoint')) == (self.name, self.endpoint):
                return record
        return None

    def _set_progress(self, value):
        with self.lock:
            self.progress = value
            if self.task_id and value.get('phase') != self.tasks.records[0]['stage']:
                self.tasks.update(self.task_id, stage=value['phase'])

    def cancel_operation(self):
        with self.lock:
            if self.operation not in ('check', 'start', 'restart', 'prepare', 'validate', 'switch', 'rollback'):
                raise RuntimeError('当前操作不能取消')
            self.tasks.update(self.task_id, status='cancelling', stage='等待当前操作取消')
            self.cancel_event.set()
            self.progress = {'phase':'正在取消；已完成文件保留，当前操作结束后可重试'}
            # Runtime uses the same event for startup, preventing a late spawn.
            if self.operation in ('start', 'restart'):
                self.want_owned = False
                self.runtime.cancel.set()

    def diagnostics(self):
        # Explicit export: no camera images, operator notes, environment or review prompts.
        return {'format': 'spark-model-diagnostics-v1', 'created': time.time(),
                'model': self.snapshot(), 'logs': self.log_tail()}

    def refresh_health(self):
        resources = resource_snapshot()
        with self.lock:
            self.resources = resources
            self.resources_checked_at = time.time()
            if self.operation is not None or self.checked_at is None: return
            selection = self.name, self.endpoint
            revision = self.revision
        client = SparkXClient(selection[0], base_url=selection[1])
        connected = client.initialize()
        loaded = []
        resident_checked_at = None
        health_error = client.last_error
        if connected:
            try:
                data = client._request('GET', '/api/ps', timeout=2)
                if not isinstance(data.get('models'), list): raise ValueError('Invalid resident model response')
                loaded = [{key: model.get(key) for key in ('name', 'size', 'size_vram', 'context_length', 'expires_at')}
                          for model in data['models'] if model.get('name') == selection[0]]
                resident_checked_at = time.time()
            except Exception as exc:
                health_error = f'驻留状态读取失败：{exc}'
        with self.lock:
            # Ignore probes superseded by an operation or changed selection.
            if self.operation is not None or revision != self.revision or self.stop_event.is_set(): return
            self.connected, self.checked_at = connected, time.time()
            self.details = dict(client.details) if connected else {}
            self.loaded, self.health_error = loaded, health_error
            self.resident_checked_at = resident_checked_at

    def recover_if_needed(self):
        with self.lock:
            if not self.policy['auto_restart'] or not self.want_owned or self.operation or self.pending() or self.stop_event.is_set(): return
            if self.connected and self.runtime.owned:
                self.health_failures = 0
                return
            self.health_failures += 1
            if self.health_failures < 3: return
            now = time.monotonic()
            self.recovery_attempts = [stamp for stamp in self.recovery_attempts if now-stamp < 600]
            if len(self.recovery_attempts) >= 3:
                self.recovery_message = '10 分钟内已尝试恢复 3 次，请人工检查并重启服务。'
                return
            if self.recovery_attempts and now-self.recovery_attempts[-1] < 30: return
            self.recovery_attempts.append(now)
            self.recovery_message = '正在尝试恢复本工作台的服务；失败复核不会自动重发。'
            self.launch('restart' if self.runtime.owned else 'start', automatic=True)

    def _health_loop(self):
        while not self.stop_event.wait(HEALTH_INTERVAL):
            try:
                self.refresh_health()
                self.recover_if_needed()
            except Exception as exc:
                with self.lock:
                    self.connected = False
                    self.health_error = str(exc)

    def snapshot(self):
        with self.lock:
            stale = self.checked_at is not None and time.time() - self.checked_at > STALE_AFTER
            return copy.deepcopy({'name': self.name, 'endpoint': self.endpoint,
                'connected': self.connected and (not self.want_owned or self.runtime.owned) and not stale and self.operation not in ('start', 'stop', 'restart'),
                'details': self.details, 'checked_at': self.checked_at, 'stale': stale,
                'error': self.error, 'log_error': self.runtime.log.error if self.runtime.log else '', 'fault': self.fault, 'progress': self.progress, 'health_error': self.health_error, 'operation': self.operation,
                'tasks': self.tasks.snapshot(), 'task_error': self.task_error,
                'catalog': self.asset_catalog(),
                'owned': self.runtime.owned, 'pid': self.runtime.process.pid if self.runtime.owned else None,
                'loaded': self.loaded, 'resident_checked_at': self.resident_checked_at,
                'resources': self.resources, 'resources_checked_at': self.resources_checked_at, 'deployment': self.deployment,
                'executable': self.executable, 'runtime_plan': runtime_plan(self.executable or None),
                'policy': self.policy, 'policy_presets': PRESETS, 'recovery': {'attempts_in_window':len(self.recovery_attempts), 'message':self.recovery_message},
                'validation': self.active_validation(), 'previous_name': self.previous_name, 'validations': self.validations,
                'config_path': str(self.config_path), 'health_interval_seconds': HEALTH_INTERVAL})

    def asset_catalog(self):
        assets = []
        for size in ('1.7b', '4b'):
            manifest = model_manifest(size)
            name = manifest['model_name']
            stamp = weight_stamp(deployment.ROOT / 'models' / manifest['file'])
            checked = self.deployments.get(name)
            status = 'missing' if stamp is None else 'incomplete' if stamp['size'] != manifest['size'] else 'changed' if checked and checked.get('weight_stamp') != stamp else 'checked' if checked and checked.get('weight_verified') else 'invalid' if checked else 'unchecked'
            assets.append({'name': name, 'title': manifest['official_model'], 'size_bytes': manifest['size'],
                'file_status': status, 'checked_at': checked.get('checked_at') if checked else None,
                'selected': name == self.name, 'revision': manifest['revision'], 'license': manifest['license'],
                'source': manifest['source'], 'quantization': 'Q4_K_M', 'purpose': '文本指标复核'})
        return assets

    def log_tail(self):
        try: return {'text': self.runtime.log_tail(), 'path': str(self.runtime.log_path or ''), 'limit_bytes': 16384, 'write_error': self.runtime.log.error if self.runtime.log else ''}
        except OSError as exc: raise RuntimeError(f'日志读取失败：{exc}') from exc

    def close(self):
        self.stop_event.set()
        self.cancel_event.set()
        try:
            self.runtime.close()
        finally:
            if self.worker is not None: self.worker.join(timeout=30)
            # A startup that completed preflight concurrently also observes cancellation.
            try:
                self.runtime.close()
            finally:
                if self.health_thread.is_alive(): self.health_thread.join(timeout=15)
