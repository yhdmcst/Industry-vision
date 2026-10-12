"""Real local Spark + PaDiM workflow on public images; isolated DB and explicit HTTP fault injection.

Requires a separately started loopback Spark service. No camera, factory accuracy,
disconnected-network or semantic accuracy claim. Repeated calls test engineering only.
"""

import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

import cv2
import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json
from src.api.app import create_app
from src.llm.deployment import resource_snapshot
from src.llm.spark_client import SparkXClient
from fastapi.testclient import TestClient

# Fixed before inference; engineering gates, not cause/defect accuracy gates.
GATES = {'successful_calls': 3, 'max_review_seconds': 30., 'state_p95_ms': 1000.,
         'min_capture_growth_per_call': 1, 'context_length': 4096}


@contextmanager
def unavailable_chat(endpoint):
    """Forward real metadata, explicitly inject HTTP 503 for inference only."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def respond(self):
            if self.path == '/api/chat':
                body = b'{"error":"TEST FAULT: local inference transport unavailable"}'
                status = 503
            else:
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                with httpx.Client(timeout=10, trust_env=False) as client:
                    response = client.request(self.command, endpoint + self.path, content=body,
                                              headers={'Content-Type': 'application/json'})
                status, body = response.status_code, response.content
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)

        do_GET = do_POST = respond

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def make_video(manifest_path, output):
    manifest = json.loads(manifest_path.read_bytes())
    reference = next(s for s in manifest['samples'] if s['split'] == 'baseline')
    evaluation = next(s for s in manifest['samples'] if s['split'] == 'evaluation')
    paths = [manifest_path.parent / s['path'] for s in (reference, evaluation)]
    frames = [cv2.imread(str(path)) for path in paths]
    if any(f is None for f in frames): raise ValueError('Public images unavailable')
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*'MJPG'), 5, (640, 480))
    if not writer.isOpened(): raise RuntimeError('MJPG encoder unavailable')
    try:
        # Repeats intentionally test continuous inference, never independent scene support.
        for frame in [frames[0]] * 10 + [frames[1]] * 300:
            writer.write(cv2.resize(frame, (640, 480)))
    finally: writer.release()
    return {'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'image_sha256': [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths],
            'scope': 'VisA public images re-encoded as repeated MJPG; not a physical camera or independent batches'}


def validate(args):
    if args.output.exists(): raise ValueError('Choose a fresh output directory; preserve prior evidence')
    args.output.mkdir(parents=True)
    verified = SparkXClient(args.model, base_url=args.endpoint)
    if not verified.initialize(): raise RuntimeError(verified.last_error)
    public = make_video(args.manifest, args.output / 'public-workflow.avi')
    report = {'gates': GATES, 'scope': __doc__, 'public_input': public,
              'before': resource_snapshot(), 'calls': [], 'state_latency_ms': [],
              'resource_samples': [], 'passed': False}
    write_json(args.output / 'report.json', report)
    with tempfile.TemporaryDirectory(prefix='spark-real-review-') as temporary:
        db = Path(temporary) / 'evidence.db'
        with TestClient(create_app(db, serve_frontend=False)) as client:
            def post(path, data):
                response = client.post(path, json=data)
                response.raise_for_status(); return response.json()

            post('/api/source', {'mode': 'video', 'video': str((args.output / 'public-workflow.avi').resolve())})
            post('/api/vision/connect', {'path': str(args.vision.resolve()), 'timeout_seconds': 5})
            post('/api/baseline', {'count': 10, 'note': 'Repeated VisA normal image; engineering validation only'})
            post('/api/capture', {'action': 'sample'})
            deadline = time.monotonic() + 10
            while client.get('/api/state').json()['vision_runtime']['pending']:
                if time.monotonic() > deadline: raise RuntimeError('Initial visual inference timed out')
                time.sleep(.05)
            state = client.get('/api/state').json()
            assert state['latest']['detection']['status'] == 'ok', state['latest']
            event = post('/api/capture', {'action': 'bookmark'})['id']
            url = f"/api/sessions/{state['session']}/incidents/{event}"
            frozen = client.get(url).json()['event']
            assert frozen['payload']['snapshot']['inspection_source']['kind'] == 'local_visual'
            report['visual_runtime'] = state['vision_runtime']

            def run_review(endpoint, expect_failure=False):
                post('/api/model/connect', {'name': args.model, 'endpoint': endpoint})
                before = client.get('/api/state').json()['frame_count']
                old = client.get(url).json()
                start = time.monotonic()
                last_resource = 0
                post(url + '/review', {'context': '公开 PCB 图像重编码回放，无现场原因真值；人工仍需核验。'})
                observations = []
                while True:
                    tick = time.perf_counter(); current = client.get('/api/state').json()
                    report['state_latency_ms'].append((time.perf_counter() - tick) * 1000)
                    observations.append(current['vision_runtime'].get('last_ms'))
                    if time.monotonic() - last_resource >= 1:
                        report['resource_samples'].append(resource_snapshot())
                        last_resource = time.monotonic()
                    if not current['model']['pending']: break
                    if time.monotonic() - start > 180: raise RuntimeError('Review deadline exceeded')
                    time.sleep(.1)
                bundle = client.get(url).json()
                assert bundle['event'] == frozen, 'Frozen event mutated during live capture'
                elapsed = time.monotonic() - start
                if expect_failure:
                    assert len(bundle['errors']) == len(old['errors']) + 1
                    assert len(bundle['reviews']) == len(old['reviews'])
                    error = bundle['errors'][-1]['payload']
                    assert '503' in error['error'] and error['incident_id'] == event
                    assert not error['raw_response']
                    report['fault'] = {'injection': 'Loopback relay HTTP 503, not physical service loss',
                                       'evidence': error, 'seconds': elapsed}
                else:
                    assert not current['model']['review_error'], current['model']['review_error']
                    assert len(bundle['reviews']) == len(old['reviews']) + 1
                    payload = bundle['reviews'][-1]['payload']
                    assert payload['snapshot'] == frozen['payload']['snapshot']
                    assert payload['provenance'] == 'local_official_model'
                    assert payload['raw_response'] and payload['prompt_sha256']
                    assert payload['inference']['runtime']['weight_sha256'] == verified.details['weight_sha256']
                    assert payload['inference']['request_settings']['context_length'] == GATES['context_length']
                    report['calls'].append({'seconds': elapsed, 'frame_growth': current['frame_count'] - before,
                                            'inference': payload['inference'], 'analysis': payload['analysis'],
                                            'warnings': payload['evidence_warnings'],
                                            'visual_ms_during_review': [v for v in observations if v is not None]})
                write_json(args.output / 'report.json', report)

            post('/api/capture', {'action': 'start'})
            run_review(args.endpoint)
            run_review(args.endpoint)
            with unavailable_chat(args.endpoint) as fault: run_review(fault, True)
            run_review(args.endpoint)
            # Capture may have an in-flight vision job; pause does not discard it.
            post('/api/capture', {'action': 'pause'})
            post(url + '/assessment', {'outcome': 'insufficient_evidence',
                                       'note': '真实模型工程贯通通过；公开图像没有现场原因真值。'})
            saved = client.get(url).json()
            write_json(args.output / 'incident.json', saved)
            write_json(args.output / 'export.json', client.get('/api/export').json())
        with TestClient(create_app(db, serve_frontend=False)) as restarted:
            assert restarted.get(url).json() == saved
            report['history_survives_restart'] = True
    with httpx.Client(timeout=10, trust_env=False) as model:
        report['loaded'] = model.get(args.endpoint + '/api/ps').json()
    report['after'] = resource_snapshot()
    report['state_p95_ms'] = float(np.percentile(report['state_latency_ms'], 95))
    report['passed'] = (len(report['calls']) >= GATES['successful_calls']
                        and all(c['seconds'] <= GATES['max_review_seconds']
                                and c['frame_growth'] >= GATES['min_capture_growth_per_call'] for c in report['calls'])
                        and report['state_p95_ms'] <= GATES['state_p95_ms']
                        and report['history_survives_restart']
                        and any(m['name'] == args.model and m['context_length'] == GATES['context_length']
                                for m in report['loaded']['models']))
    write_json(args.output / 'report.json', report)
    print(json.dumps({'passed': report['passed'], 'calls': [(c['seconds'], c['frame_growth']) for c in report['calls']],
                      'state_p95_ms': report['state_p95_ms'], 'resources': report['after']}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='spark-drift:4b-q4')
    parser.add_argument('--endpoint', default='http://127.0.0.1:11435')
    parser.add_argument('--vision', type=Path, default=ROOT / 'data/models/padim-pcb1-aligned-runtime')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'artifacts/pose-study-pcb1/manifest.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/local-review-4b')
    raise SystemExit(validate(parser.parse_args()))
