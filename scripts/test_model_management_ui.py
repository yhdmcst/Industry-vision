"""Real local 4B management acceptance; isolated DB, owned services and Chrome.

Starts services and performs genuine inference. No camera or factory claims.
"""

import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from playwright.sync_api import sync_playwright, expect
from src.llm.runtime import OwnedRuntime

GATES = {'state_p95_ms_max': 1000, 'start_timeout_seconds': 180, 'stop_timeout_seconds': 30,
         'real_review_timeout_seconds': 90, 'capture_must_advance_during_start': True}


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', default='chrome')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/model-management')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / 'report.json').exists(): parser.error('Choose a fresh --output; existing report is preserved')
    api_port, model_port = free_port(), free_port()
    url = f'http://127.0.0.1:{api_port}'
    endpoint = f'http://127.0.0.1:{model_port}'
    checks, timings, errors = [], [], []
    server = None
    external = None
    with tempfile.TemporaryDirectory(prefix='spark-model-ui-') as temporary:
        database = Path(temporary) / 'evidence.db'
        server_log = (args.output / 'api.log').open('ab')
        def start_api():
            process = subprocess.Popen([sys.executable, '-c',
                'import sys; from pathlib import Path; import uvicorn; from src.api.app import create_app; '
                'uvicorn.run(create_app(Path(sys.argv[1])),host="127.0.0.1",port=int(sys.argv[2]),log_level="warning",access_log=False)',
                str(database), str(api_port)], cwd=ROOT, stdout=server_log, stderr=server_log)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None: raise RuntimeError('Acceptance API exited; inspect api.log')
                try:
                    with httpx.Client(trust_env=False, timeout=1) as client:
                        if client.get(url + '/api/health').status_code == 200: return process
                except httpx.HTTPError: pass
                time.sleep(.2)
            process.terminate(); process.wait(20)
            raise RuntimeError('Acceptance API startup timed out')
        def stop_api(process):
            process.terminate()
            try: process.wait(40)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(5)
                raise RuntimeError('API graceful shutdown failed')
        try:
            server = start_api()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=args.channel, headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1080})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url + '/#models')
                expect(page.get_by_role('heading', name='本地模型', exact=True)).to_be_visible()
                def wait_operation(timeout=180):
                    deadline=time.monotonic()+timeout
                    while time.monotonic()<deadline:
                        result=page.request.get(url+'/api/state').json()
                        if result['model']['operation'] is None:
                            assert not result['model']['error'], result['model']
                            return result
                        page.wait_for_timeout(100)
                    raise RuntimeError('Model operation did not complete')
                def click_operation(label):
                    with page.expect_response(lambda response: response.request.method=='POST' and '/api/model/' in response.url) as submitted:
                        page.get_by_role('button',name=label,exact=True).click()
                    assert submitted.value.ok,submitted.value.text()
                    return wait_operation()
                # Display-only platform fixtures; never count these as actual OS deployment.
                for system, architecture in [('Windows', 'AMD64'), ('Linux', 'x86_64')]:
                    def platform_fixture(route, request, system=system, architecture=architecture):
                        response = route.fetch()
                        data = response.json()
                        data['model']['runtime_plan'].update(system=system, architecture=architecture,
                            label=f'{system} / {architecture}', source='system', candidate=None,
                            pinned_version=None, install_commands=[],
                            install_url=f'https://ollama.com/download/{system.lower()}',
                            guidance=f'{system} fixture: install official runtime', integrity='可执行性与版本')
                        route.fulfill(response=response, json=data)
                    page.route('**/api/state*', platform_fixture)
                    page.reload()
                    expect(page.get_by_text(f'{system} / {architecture}', exact=True)).to_be_visible()
                    assert not page.get_by_text('PID', exact=True).count()
                    page.unroute('**/api/state*', platform_fixture)
                checks.append('display-only Windows/Linux platform fixtures show matching instructions, no macOS command; not actual OS deployment')
                page.reload()
                page.get_by_label('模型名称', exact=True).select_option('spark-drift:4b-q4')
                page.get_by_text('连接与运行时设置', exact=True).click()
                page.get_by_label('本地服务', exact=True).fill(endpoint)
                page.get_by_role('button', name='保存模型选择', exact=True).click()
                expect(page.get_by_role('status').filter(has_text='模型选择已保存')).to_be_visible()
                page.get_by_role('button', name='检查部署条件', exact=True).click()
                expect(page.get_by_text('最近检查通过', exact=True)).to_be_visible(timeout=90000)
                checks.append('real runtime and official GGUF size/SHA-256 preflight')
                assert page.request.post(url + '/api/capture', data={'action': 'start'}).ok
                before = page.request.get(url + '/api/state').json()['frame_count']
                started = time.monotonic()
                page.get_by_role('button', name='启动本地服务', exact=True).click()
                deadline = started + GATES['start_timeout_seconds']
                while time.monotonic() < deadline:
                    tick = time.perf_counter()
                    current = page.request.get(url + '/api/state').json()
                    timings.append((time.perf_counter() - tick) * 1000)
                    if current['model']['connected'] and current['model']['operation'] is None: break
                    if current['model']['error']: raise RuntimeError(current['model']['error'])
                    page.wait_for_timeout(250)
                else: raise RuntimeError('Real model startup did not pass timeout gate')
                assert current['model']['owned'] and current['frame_count'] > before
                start_seconds = time.monotonic() - started
                expect(page.get_by_text('服务可用', exact=True)).to_be_visible()
                page.get_by_role('button', name='查看服务日志', exact=True).click()
                expect(page.get_by_label('服务日志', exact=True)).to_contain_text('ollama', timeout=10000)
                checks.append('UI owned startup, live health and bounded logs; capture advances while starting')
                # Page preparation uses real cached official bytes, not a download mock.
                click_operation('下载并准备模型')
                expect(page.get_by_role('button', name='推理自检', exact=True)).to_be_enabled(timeout=90000)
                assert page.request.get(url+'/api/state').json()['model']['deployment']['ready']
                click_operation('推理自检')
                expect(page.get_by_text('最近推理自检通过', exact=False)).to_be_visible(timeout=90000)
                validation = page.request.get(url+'/api/state').json()['model']['validation']
                assert validation['name']=='spark-drift:4b-q4'
                page.get_by_label('模型名称', exact=True).select_option('spark-drift:1.7b-q4')
                click_operation('验证并切换候选')
                expect(page.get_by_label('模型名称', exact=True)).to_have_value('spark-drift:1.7b-q4', timeout=90000)
                expect(page.get_by_role('button', name='恢复上一版本', exact=True)).to_be_enabled(timeout=90000)
                assert page.request.get(url+'/api/state').json()['model']['name']=='spark-drift:1.7b-q4'
                click_operation('恢复上一版本')
                expect(page.get_by_label('模型名称', exact=True)).to_have_value('spark-drift:4b-q4', timeout=90000)
                expect(page.get_by_role('button', name='重启服务', exact=True)).to_be_enabled(timeout=90000)
                old_pid = page.request.get(url+'/api/state').json()['model']['pid']
                click_operation('重启服务')
                expect(page.get_by_role('button', name='推理自检', exact=True)).to_be_enabled(timeout=180000)
                assert page.request.get(url+'/api/state').json()['model']['pid']!=old_pid
                checks.append('UI cached preparation, real structured self-check, owned candidate import, verified switch, rollback and restart')
                page.get_by_label('运行方案', exact=True).select_option('resource')
                page.get_by_role('button', name='保存运行策略', exact=True).click()
                expect(page.get_by_role('button', name='保存运行策略', exact=True)).to_be_disabled()
                event = page.request.post(url + '/api/capture', data={'action': 'bookmark'}).json()['id']
                session = current['session']
                event_url = url + f'/api/sessions/{session}/incidents/{event}'
                page.goto(url + '/#review')
                page.get_by_role('button', name='请求模型复核', exact=True).click()
                expect(page.get_by_text('竞争解释与验证', exact=True)).to_be_visible(timeout=GATES['real_review_timeout_seconds'] * 1000)
                bundle = page.request.get(event_url).json()
                assert bundle['reviews'] and not bundle['errors']
                review = bundle['reviews'][-1]['payload']
                assert review['provenance'] == 'local_official_model'
                assert review['inference']['runtime']['weight_sha256']
                assert review['deployment']['name']=='spark-drift:4b-q4'
                assert review['inference']['request_settings']['keep_alive_minutes']==0
                assert review['inference']['request_settings']['timeout_seconds']==90
                (args.output / 'real-review.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2))
                checks.append('real 4B structured inference from UI-started service with frozen incident evidence')
                page.goto(url + '/#models')
                expect(page.get_by_text('等待下次复核加载', exact=True)).to_be_visible(timeout=20000)
                diagnostics=page.request.get(url+'/api/model/diagnostics')
                assert diagnostics.ok and diagnostics.json()['model']['validation']
                assert 'images' not in diagnostics.json()
                checks.append('resource policy releases residency; review records policy/version; diagnostic export available')
                page.evaluate('window.scrollTo(0, 0)')
                page.screenshot(path=str(args.output / 'desktop.png'), full_page=True, animations='disabled')
                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
                page.evaluate('window.scrollTo(0, 0)')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(args.output / 'mobile.png'), full_page=True, animations='disabled')
                page.set_viewport_size({'width': 1440, 'height': 1080})
                click_operation('停止本地服务')
                expect(page.get_by_role('button', name='启动本地服务', exact=True)).to_be_enabled(timeout=30000)
                stopped = page.request.get(url + '/api/state').json()['model']
                assert not stopped['owned'] and not stopped['connected'] and not stopped['loaded']
                checks.append('UI stop clears online and resident facts; desktop/mobile have no document overflow')
                # Keep the same isolated DB across an application restart.
                stop_api(server); server = None
                server = start_api()
                page.reload()
                expect(page.get_by_label('模型名称', exact=True)).to_have_value('spark-drift:4b-q4')
                page.get_by_text('连接与运行时设置',exact=True).click()
                expect(page.get_by_label('本地服务', exact=True)).to_have_value(endpoint)
                restored = page.request.get(url + '/api/state').json()['model']
                assert not restored['connected'] and not restored['owned']
                checks.append('saved selection survives API restart without automatic service startup')
                policy=restored['policy']
                assert policy['profile']=='resource'
                policy.update(autostart=True, auto_restart=True)
                assert page.request.post(url+'/api/model/policy', data=policy).ok
                stop_api(server);server=None;server=start_api();page.reload()
                expect(page.get_by_text('服务可用',exact=True)).to_be_visible(timeout=180000)
                active=page.request.get(url+'/api/state').json()['model']
                assert active['owned']
                import os, signal
                os.kill(active['pid'],signal.SIGTERM) # Isolated app-owned test service, never default 11435.
                deadline=time.monotonic()+90
                while time.monotonic()<deadline:
                    active_after=page.request.get(url+'/api/state').json()['model']
                    if active_after['connected'] and active_after['owned'] and active_after['pid']!=active['pid'] and active_after['operation'] is None: break
                    page.wait_for_timeout(500)
                else: raise RuntimeError('Bounded recovery failed to replace crashed owned process')
                assert len(page.request.get(event_url).json()['reviews'])==1
                checks.append('opt-in app autostart, actual child crash recovery, no replay of completed/failed reviews')
                policy.update(autostart=False,auto_restart=False)
                assert page.request.post(url+'/api/model/policy',data=policy).ok
                assert page.request.post(url+'/api/model/stop').ok
                deadline=time.monotonic()+30
                while page.request.get(url+'/api/state').json()['model']['operation'] and time.monotonic()<deadline:page.wait_for_timeout(100)
                external = OwnedRuntime(Path(temporary) / 'external-model')
                external.start('4b', model_port)
                page.get_by_role('button', name='核验连接', exact=True).click()
                expect(page.get_by_text('服务可用', exact=True)).to_be_visible(timeout=20000)
                expect(page.get_by_role('button', name='停止本地服务', exact=True)).to_be_disabled()
                assert page.request.post(url + '/api/model/stop').status == 409
                assert external.owned
                checks.append('external service connects but neither UI nor API can stop it')
                external.close()
                expect(page.get_by_text('服务未连接', exact=True)).to_be_visible(timeout=20000)
                checks.append('external service disappearance clears live connection automatically')
                # Verify application shutdown owns and cleans its child as well.
                page.get_by_role('button', name='启动本地服务', exact=True).click()
                expect(page.get_by_text('服务可用', exact=True)).to_be_visible(timeout=180000)
                stop_api(server); server = None
                with socket.socket() as probe:
                    probe.settimeout(.2)
                    assert probe.connect_ex(('127.0.0.1', model_port))!=0
                checks.append('API shutdown releases its owned model listener')
                browser.close()
            p95 = sorted(timings)[int((len(timings) - 1) * .95)]
            assert p95 <= GATES['state_p95_ms_max'] and not errors
            report = {'gates': GATES, 'checks': checks, 'errors': errors, 'start_seconds': start_seconds,
                      'state_p95_ms': p95, 'review_ms': review['inference']['elapsed_ms'],
                      'real_model': 'spark-drift:4b-q4', 'scope': 'M4 local deployment engineering; synthetic capture; no factory or semantic accuracy acceptance'}
            (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            if external is not None: external.close()
            if server is not None: stop_api(server)
            server_log.close()


if __name__ == '__main__': main()
