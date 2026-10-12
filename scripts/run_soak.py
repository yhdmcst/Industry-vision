"""Isolated synthetic API soak; snapshots code, never uses the daily database or model service."""

import argparse
import json
import os
from pathlib import Path
import platform
import signal
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json

POLICY = {'id': 'synthetic-soak-v1', 'minimum_seconds': 8*3600,
          'maximum_rss_mib': 1536, 'maximum_rss_growth_mib': 256,
          'maximum_disk_mib': 1024, 'minimum_free_disk_mib': 2048,
          'maximum_state_ms': 2000, 'maximum_stall_seconds': 30,
          'maximum_history': 300, 'maximum_cpu_percent_one_core': 200}


def snapshot(output):
    """Archive committed HEAD; uncommitted product development is excluded from the run."""
    dirty = subprocess.check_output(['git', 'status', '--porcelain', '--', 'scripts/run_soak.py'], cwd=ROOT)
    if dirty:
        raise ValueError('Commit the soak runner before launching a reproducible soak')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    source = output/'source'; source.mkdir()
    archive = subprocess.check_output(['git', 'archive', revision], cwd=ROOT)
    # The archive is generated from this local repository, never an untrusted download.
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(source, filter='data')
    return revision, source


def decision(report):
    if report['errors'] or not report.get('shutdown_clean'):
        return 'failed'
    return 'passed' if report['elapsed_seconds'] >= POLICY['minimum_seconds'] else 'smoke_only'


def serve(database, port):
    import uvicorn
    from src.api.app import create_app
    # Uvicorn handles shutdown and then re-raises the original signal to this handler.
    # Let run() return after lifespan cleanup so the parent can distinguish it from a kill.
    signal.signal(signal.SIGTERM, lambda *_: None)
    uvicorn.run(create_app(database, serve_frontend=False), host='127.0.0.1', port=port,
                workers=1, log_level='warning', access_log=False)


def run(output, seconds, port, interval):
    output = output.resolve()
    if output.exists():
        raise ValueError('Output exists; preserve previous soak evidence')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    output.mkdir(parents=True)
    revision, source = snapshot(output)
    database = output/'evidence.db'
    report = {'schema_version': 1, 'policy': POLICY, 'status': 'starting', 'revision': revision,
              'platform': platform.platform(), 'python': sys.version, 'runner_pid': os.getpid(),
              'started': time.time(), 'requested_seconds': seconds, 'port': port,
              'scope': 'Synthetic continuous capture plus API reads; no camera, real vision or model inference. Not the entire P0 acceptance.',
              'errors': [], 'samples': 0, 'elapsed_seconds': 0, 'frames': 0,
              'peak_rss_mib': 0, 'peak_cpu_percent_one_core': 0, 'peak_state_ms': 0,
              'peak_disk_mib': 0, 'shutdown_clean': False}
    cancelled = False
    def cancel(*_):
        nonlocal cancelled
        cancelled = True
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    child = None
    started = time.monotonic()
    try:
        with (output/'server.log').open('xb') as log:
            child = subprocess.Popen([sys.executable, str(source/'scripts/run_soak.py'), 'serve',
                                      '--database', str(database), '--port', str(port)],
                                     cwd=source, stdout=log, stderr=subprocess.STDOUT)
        report['server_pid'] = child.pid
        process = psutil.Process(child.pid); process.cpu_percent()
        origin = f'http://127.0.0.1:{port}'
        with httpx.Client(base_url=origin, timeout=10, trust_env=False) as client:
            deadline = time.monotonic()+45
            while True:
                if cancelled or child.poll() is not None:
                    raise RuntimeError('Startup interrupted or server exited')
                try:
                    response = client.get('/api/health'); response.raise_for_status(); break
                except httpx.HTTPError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Server startup timed out')
                    time.sleep(.2)
            response = client.post('/api/capture', json={'action': 'start'}); response.raise_for_status()
            baseline_rss = None; last_frames = None; advanced = time.monotonic()
            active_started = time.monotonic()
            report['status'] = 'running'
            while time.monotonic()-active_started < seconds and not cancelled:
                tick = time.monotonic()
                response = client.get('/api/state'); response.raise_for_status(); state = response.json()
                latency = (time.monotonic()-tick)*1000
                rss = process.memory_info().rss/1024**2
                cpu = process.cpu_percent()
                disk = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())/1024**2
                report.update(samples=report['samples']+1, elapsed_seconds=time.monotonic()-active_started,
                              heartbeat=time.time(), frames=state['frame_count'], session=state['session'])
                for key, value in [('peak_rss_mib', rss), ('peak_cpu_percent_one_core', cpu),
                                   ('peak_state_ms', latency), ('peak_disk_mib', disk)]:
                    report[key] = max(report[key], value)
                if state['frame_count'] != last_frames:
                    advanced = time.monotonic(); last_frames = state['frame_count']
                if baseline_rss is None and report['elapsed_seconds'] >= 600:
                    baseline_rss = rss; report['warm_rss_mib'] = rss
                violations = []
                if not state['running'] or state['capture_error']: violations.append('Capture stopped or failed')
                if time.monotonic()-advanced > POLICY['maximum_stall_seconds']: violations.append('Capture stalled')
                if len(state['history']) > POLICY['maximum_history']: violations.append('History exceeded bound')
                if rss > POLICY['maximum_rss_mib']: violations.append('RSS exceeded budget')
                if baseline_rss is not None and rss-baseline_rss > POLICY['maximum_rss_growth_mib']: violations.append('Warm RSS growth exceeded budget')
                if cpu > POLICY['maximum_cpu_percent_one_core']: violations.append('CPU exceeded budget')
                if disk > POLICY['maximum_disk_mib']: violations.append('Disk exceeded budget')
                if psutil.disk_usage(output).free/1024**2 < POLICY['minimum_free_disk_mib']: violations.append('Free disk below reserve')
                if latency > POLICY['maximum_state_ms']: violations.append('State request exceeded budget')
                if child.poll() is not None: violations.append('Server exited')
                report['errors'].extend(violations)
                write_json(output/'report.json', report)
                if violations: break
                # Bounded polling; interruptible stop without waiting for a full interval.
                while not cancelled and time.monotonic()-tick < interval:
                    time.sleep(min(.2, max(0, interval-(time.monotonic()-tick))))
            report['elapsed_seconds'] = time.monotonic()-active_started
            if cancelled: report['errors'].append('Run interrupted before completion')
            response = client.post('/api/capture', json={'action': 'pause'}); response.raise_for_status()
    except Exception as exc:
        report['errors'].append(f'{type(exc).__name__}: {exc}'[:2000])
    finally:
        if child is not None:
            descendants = []
            try:
                if child.poll() is None: descendants = psutil.Process(child.pid).children(recursive=True)
            except (psutil.Error, OSError) as exc:
                report['errors'].append(f'Cannot inspect child processes: {exc}'[:2000])
            if child.poll() is None: child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(); report['errors'].append('Server required forced shutdown')
            report['shutdown_clean'] = child.returncode == 0 and not any(p.is_running() for p in descendants)
        if database.is_file():
            try:
                with sqlite3.connect(database) as db:
                    report['integrity_check'] = db.execute('PRAGMA integrity_check').fetchone()[0]
                    report['stored_events'] = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
                    # Parse every payload without loading the entire journal into memory.
                    for (payload,) in db.execute('SELECT payload FROM events'): json.loads(payload)
                if report['integrity_check'] != 'ok': report['errors'].append('SQLite integrity failed')
            except (sqlite3.Error, ValueError) as exc: report['errors'].append(str(exc)[:2000])
        report.update(status=decision(report), finished=time.time(), wall_seconds=time.monotonic()-started)
        write_json(output/'report.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] in ('passed', 'smoke_only') else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('run')
    start.add_argument('--output', type=Path, required=True)
    start.add_argument('--seconds', type=float, default=8*3600)
    start.add_argument('--interval', type=float, default=10)
    start.add_argument('--port', type=int, default=8504)
    server = commands.add_parser('serve')
    server.add_argument('--database', type=Path, required=True)
    server.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535: parser.error('port must be 1024..65535')
    if args.command == 'serve': serve(args.database, args.port); return 0
    if not 1 <= args.seconds <= 24*3600 or not 1 <= args.interval <= 60:
        parser.error('seconds must be 1..86400 and interval 1..60')
    return run(args.output, args.seconds, args.port, args.interval)


if __name__ == '__main__': raise SystemExit(main())
