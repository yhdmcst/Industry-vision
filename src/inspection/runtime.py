"""One isolated vision process and at most one in-flight frame; no stale-result fallback."""

import hashlib
import multiprocessing as mp
import time

import cv2

from src.datasets import digest
from src.inspection.results import ResultPackage
from src.monitoring import DetectionRecord


def vision_worker(connection, root):
    try:
        from src.inspection.deployment_assets import load_asset
        model = load_asset(root)
        connection.send({'ready': True, 'id': model.id, 'producer': model.producer, 'mode': model.recipe['mode']})
        while True:
            sequence, frame = connection.recv()
            try:
                prediction = model.predict(frame)
            except (RuntimeError, ValueError, cv2.error, FloatingPointError) as exc:
                prediction = {'status': 'error', 'error': f'视觉推理失败：{type(exc).__name__}: {exc}'[:2000]}
            connection.send({'sequence': sequence, 'prediction': prediction})
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try: connection.send({'ready': False, 'error': f'视觉进程失败：{type(exc).__name__}: {exc}'[:2000]})
        except (EOFError, BrokenPipeError, OSError): pass
    finally:
        connection.close()


class VisionRuntime:
    def __init__(self, root, timeout_seconds=2., *, startup_seconds=45., worker=vision_worker):
        if not .1 <= timeout_seconds <= 10: raise ValueError('视觉推理时限必须为 0.1–10 秒')
        self.timeout_seconds = timeout_seconds
        self.pending = None
        self.sequence = 0
        self.error = ''
        self.last_ms = None
        context = mp.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=worker, args=(child, str(root)), name='spark-vision', daemon=True)
        try:
            self.process.start(); child.close()
            if not self.connection.poll(startup_seconds): raise RuntimeError('视觉模型加载超时')
            ready = self.connection.recv()
            if not ready.get('ready'): raise RuntimeError(ready.get('error', '视觉模型未就绪'))
            self.id, self.producer, self.mode = ready['id'], ready['producer'], ready['mode']
        except Exception:
            child.close(); self.close(); raise

    def submit(self, frame):
        if self.pending is not None: raise RuntimeError('上一帧视觉推理尚未完成')
        ok, encoded = cv2.imencode('.png', frame)
        if not ok: raise RuntimeError('视觉输入无法编码')
        self.sequence += 1
        self.pending = {'sequence': self.sequence, 'started': time.monotonic(),
                        'image_sha256': hashlib.sha256(encoded.tobytes()).hexdigest()}
        if not self.error:
            try: self.connection.send((self.sequence, frame.copy()))
            except (OSError, EOFError, BrokenPipeError): self.error = '视觉进程不可用，请显式重载模型'

    def poll(self):
        pending = self.pending
        if pending is None: return None
        elapsed = time.monotonic() - pending['started']
        prediction = None
        try:
            if self.error:
                prediction = {'status': 'error', 'error': self.error}
            elif elapsed >= self.timeout_seconds:
                self.error = '视觉推理超时，进程已终止；请显式重载模型'
                prediction = {'status': 'timeout', 'error': self.error}
                self._terminate()
            elif self.connection.poll():
                response = self.connection.recv()
                if response.get('sequence') != pending['sequence']:
                    raise ValueError('视觉响应与当前帧身份不匹配')
                prediction = response['prediction']
            elif not self.process.is_alive():
                self.error = '视觉进程退出，请显式重载模型'
                prediction = {'status': 'error', 'error': self.error}
        except (EOFError, BrokenPipeError, OSError, ValueError, KeyError) as exc:
            self.error = f'视觉响应不可用：{exc}'[:2000]
            self._terminate()
            prediction = {'status': 'error', 'error': self.error}
        if prediction is None: return None
        try:
            package = ResultPackage.model_validate({'schema_version': 2, 'dataset_id': '0'*64,
                'producer': self.producer, 'results': [{**prediction, 'sample_id': str(pending['sequence']),
                                                       'image_sha256': pending['image_sha256']}]}).model_dump()
            result = package['results'][0]
        except ValueError as exc:
            self.error = f'视觉结果协议拒绝：{exc}'[:2000]; self._terminate()
            result = {'status': 'error', 'error': self.error, 'sample_id': str(pending['sequence']),
                      'image_sha256': pending['image_sha256'], 'detected': None, 'confidence': None,
                      'is_ng': None, 'defect_types': []}
        self.last_ms = round(elapsed * 1000, 2)
        self.pending = None
        return DetectionRecord(time.time(), result.get('detected'), result.get('confidence'), result.get('is_ng'),
            {'detector': 'local_visual', 'producer': self.producer, 'result': result,
             'elapsed_ms': self.last_ms, 'timing_scope': 'submit to observation; process communication and scheduler included'}, status=result['status'])

    def infer(self, frame):
        self.submit(frame)
        while True:
            result = self.poll()
            if result is not None: return result
            time.sleep(.005)

    def state(self):
        if not self.error and not self.process.is_alive():
            self.error = '视觉进程退出，请显式重载模型'
        return {'status': 'failed' if self.error else 'processing' if self.pending else 'ready',
                'model_id': self.id, 'mode': self.mode, 'timeout_seconds': self.timeout_seconds,
                'pending': self.pending is not None, 'last_ms': self.last_ms, 'error': self.error}

    def _terminate(self):
        if self.process.pid is not None:
            if self.process.is_alive(): self.process.terminate()
            self.process.join(timeout=.3)
            if self.process.is_alive(): self.process.kill(); self.process.join(timeout=.3)

    def close(self):
        self._terminate()
        self.connection.close()
        self.pending = None
