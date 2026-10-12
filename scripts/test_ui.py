"""React browser acceptance. Uses a local MOCK workstation and preserves historical evidence."""

import argparse
import json
from pathlib import Path
import platform
import time

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8501')
    parser.add_argument('--channel', default='chrome', help='Installed chrome/msedge, or chromium')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/ui-react')
    parser.add_argument('--model-review', action='store_true', help='Requires a real local Spark model')
    parser.add_argument('--model', default='spark-drift:1.7b-q4')
    parser.add_argument('--endpoint', default='http://127.0.0.1:11435')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=None if args.channel == 'chromium' else args.channel, headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100}, device_scale_factor=1)
        page.on('pageerror', lambda error: errors.append(str(error)))

        def navigate(name):
            if page.get_by_role('button', name='打开导航', exact=True).is_visible():
                page.get_by_role('button', name='打开导航', exact=True).click()
            page.get_by_role('navigation', name='主导航').get_by_role('button', name=name).click()
            page.get_by_role('heading', name=name, exact=True).wait_for()

        def screenshot(name):
            expect(page.locator('.toast')).to_have_count(0, timeout=6000)
            page.evaluate('window.scrollTo(0, 0)')
            page.wait_for_timeout(300)
            page.screenshot(path=str(args.output / name), full_page=True)

        page.goto(args.url)
        page.get_by_role('heading', name='监测工作台', exact=True).wait_for(timeout=30000)
        # Refuse to change a real acquisition source during this synthetic acceptance run.
        state = page.request.get(args.url + '/api/state').json()
        assert state['source'] == 'synthetic', 'Run acceptance against a dedicated synthetic workstation'
        page.request.post(args.url + '/api/capture', data={'action': 'pause'})
        page.request.post(args.url + '/api/scenario', data={'scenario': 'none', 'intensity': .8})
        page.request.post(args.url + '/api/baseline', data={'count': 20, 'note': 'React browser acceptance'})
        page.request.post(args.url + '/api/capture', data={'action': 'sample'})
        page.reload()
        frame_counter = page.get_by_test_id('frame-count')
        frame = page.request.get(args.url + '/api/state').json()['frame_count']
        expect(frame_counter).to_have_text(str(frame))
        page.get_by_role('button', name='采样一帧', exact=True).click()
        expect(frame_counter).to_have_text(str(frame + 1))
        page.get_by_role('button', name='开始监测', exact=True).click()
        page.wait_for_function("n => Number(document.querySelector('[data-testid=frame-count]')?.textContent) > n", arg=frame + 2)
        navigate('设置与演示')
        before = page.request.get(args.url + '/api/state').json()['frame_count']
        page.wait_for_timeout(1600)
        assert page.request.get(args.url + '/api/state').json()['frame_count'] > before
        navigate('监测工作台')
        page.get_by_role('button', name='暂停监测', exact=True).click()
        expect(page.get_by_role('button', name='采样一帧', exact=True)).to_be_enabled()
        page.get_by_role('button', name='放大当前画面', exact=True).click()
        expect(page.get_by_role('dialog')).to_be_visible()
        page.keyboard.press('Tab')
        expect(page.get_by_role('button', name='关闭图像', exact=True)).to_be_focused()
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).to_have_count(0)
        expect(page.get_by_role('button', name='放大当前画面', exact=True)).to_be_focused()
        page.locator('.metric').nth(1).click()
        expect(page.get_by_role('heading', name='亮度趋势', exact=True)).to_be_visible()
        page.locator('.metric').first.click()
        checks.append('capture, continuous backend sampling across navigation, pause, metric switching and accessible image modal')

        navigate('设置与演示')
        page.get_by_label('演示场景', exact=True).select_option('focus_change')
        page.get_by_role('button', name='应用演示场景', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='演示场景已应用')).to_be_visible()
        navigate('监测工作台')
        page.get_by_role('button', name='采样一帧', exact=True).click()
        expect(page.locator('.observation-status')).to_have_text('光学变化')
        screenshot('desktop.png')
        checks.append('synthetic blur measured by real vision pipeline and automatically frozen as incident')

        navigate('事件复核')
        expect(page.get_by_role('heading', name='测量事实', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='请求模型复核', exact=True)).to_be_disabled()
        page.get_by_label('复核记录', exact=True).fill('浏览器验收：合成样本，尚无真实工位证据。')
        page.get_by_role('button', name='记录人工复核', exact=True).click()
        expect(page.get_by_text('已记录：证据不足', exact=True)).to_be_visible(timeout=10000)
        screenshot('review.png')
        with page.expect_download() as event:
            page.get_by_role('button', name='导出事件证据', exact=True).click()
        event.value.save_as(str(args.output / 'event.json'))
        evidence = json.loads((args.output / 'event.json').read_text())
        assert evidence['event']['payload']['synthetic']
        assert evidence['event']['payload']['images']['current']
        assert evidence['assessments'][-1]['payload']['outcome'] == 'insufficient_evidence'
        selected_id = evidence['event']['id']
        page.get_by_label('搜索事件', exact=True).fill(str(selected_id))
        page.get_by_role('button', name='待复核', exact=True).click()
        expect(page.get_by_text('暂无匹配事件', exact=True)).to_be_visible()
        page.get_by_role('button', name='全部', exact=True).click()
        expect(page.locator('.event-card')).to_have_count(1)
        checks.append('immutable event images, human review without model, search/status filters and JSON download')

        navigate('基线与漂移')
        screenshot('baseline.png')
        page.get_by_text('清空当前基线', exact=True).click()
        page.get_by_role('button', name='重置基线', exact=True).click()
        expect(page.get_by_text('未建立基线。请先确认取景与工况，再采集正常参考样本。', exact=True)).to_be_visible()
        navigate('监测工作台')
        expect(page.get_by_role('button', name='开始监测', exact=True)).to_be_disabled()
        expect(page.get_by_role('button', name='采样一帧', exact=True)).to_be_disabled()
        navigate('基线与漂移')
        page.get_by_label('确认当前取景适合作为参考基线', exact=True).check()
        page.get_by_role('button', name='建立新基线', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='新基线已建立')).to_be_visible()
        navigate('事件复核')
        expect(page.get_by_text('已记录：证据不足', exact=True)).to_be_visible()
        checks.append('baseline reset/rebuild gates and preservation of historical event evidence')

        navigate('本地模型')
        page.get_by_text('连接与运行时设置', exact=True).click()
        page.get_by_label('本地服务', exact=True).fill('http://example.org:11435')
        page.get_by_role('button', name='保存模型选择', exact=True).click()
        expect(page.get_by_role('alert').filter(has_text='服务地址须为本机 HTTP 地址')).to_be_visible()
        page.get_by_role('button', name='关闭错误', exact=True).click()
        checks.append('nonlocal model endpoint rejected without synthetic model response')
        if args.model_review:
            page.get_by_label('模型名称', exact=True).select_option(args.model)
            page.get_by_label('本地服务', exact=True).fill(args.endpoint)
            save = page.get_by_role('button', name='保存模型选择', exact=True)
            if save.is_enabled():
                save.click()
                expect(save).to_be_disabled()
            page.get_by_role('button', name='核验连接', exact=True).click()
            expect(page.get_by_text('服务可用', exact=True)).to_be_visible(timeout=15000)
            navigate('事件复核')
            page.get_by_role('button', name='请求模型复核', exact=True).click()
            page.get_by_text('竞争解释与验证', exact=True).wait_for(timeout=180000)
            screenshot('model-review.png')
            with page.expect_download() as download:
                page.get_by_role('button', name='导出事件证据', exact=True).click()
            download.value.save_as(args.output / 'real-model-incident.json')
            actual = json.loads((args.output / 'real-model-incident.json').read_bytes())
            assert actual['reviews'] and actual['assessments']
            payload = actual['reviews'][-1]['payload']
            assert payload['provenance'] == 'local_official_model'
            assert payload['snapshot'] == actual['event']['payload']['snapshot']
            assert payload['inference']['runtime']['weight_sha256']
            if (payload['analysis']['drift_type'] == 'none') == payload['analysis']['drift_detected']:
                assert any('相互矛盾' in warning for warning in payload['evidence_warnings'])
                expect(page.get_by_text('模型漂移标记与原因分类相互矛盾；保留原始回答，需人工核查。',exact=True)).to_be_visible()
            checks.append('real local model inference against frozen incident')

        for name, filename in [('监测工作台', 'mobile.png'), ('事件复核', 'mobile-review.png'),
                               ('基线与漂移', 'mobile-baseline.png'), ('设置与演示', 'mobile-settings.png')]:
            page.set_viewport_size({'width': 390, 'height': 844})
            navigate(name)
            if name == '监测工作台':
                page.get_by_role('button', name='采样一帧', exact=True).click()
                expect(page.locator('.observation-status')).to_have_text('光学变化')
            page.wait_for_timeout(500)
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), name
            screenshot(filename)
        checks.append('four pages and navigation at 390px without horizontal document overflow')

        page.route('**/api/state*', lambda route: route.abort())
        expect(page.get_by_role('alert').filter(has_text='当前数据显示可能已过期')).to_be_visible(timeout=10000)
        page.unroute('**/api/state*')
        expect(page.get_by_role('alert').filter(has_text='当前数据显示可能已过期')).to_have_count(0, timeout=10000)
        checks.append('API disconnection visibly marks stale state and recovers')
        # Test-only transport fixture: exercise model-result rendering without a model
        # or writing invented model output to the evidence store.
        if not args.model_review:
            fixture = json.loads(json.dumps(evidence))
            fixture['reviews'] = [{'id': -1, 'kind': 'model_review', 'created': time.time(), 'payload': {
                'analysis': {'drift_type': 'none', 'root_cause': '测试夹具：模型分类与测量可能冲突。',
                             'evidence': ['测试夹具：清晰度下降 99.9%'],
                             'alternative_causes': ['测试夹具：光学变化'],
                             'verification_steps': ['测试夹具：人工检查焦点'],
                             'recommendations': ['测试夹具：现场核验']},
                'evidence_warnings': ['测试夹具：保留模型与测量冲突'],
                'raw_response': 'TEST FIXTURE ONLY — NOT MODEL INFERENCE'}}]
            fixture['errors'] = [{'id': -2, 'kind': 'model_error', 'created': time.time(),
                                  'payload': {'error': '测试夹具：此前推理失败'}}]
            page.route('**/api/sessions/*/incidents/*', lambda route: route.fulfill(json=fixture))
            navigate('事件复核')
            expect(page.get_by_text('测试夹具：保留模型与测量冲突', exact=True)).to_be_visible(timeout=10000)
            expect(page.get_by_text('测试夹具：此前推理失败', exact=True)).to_be_visible()
            expect(page.get_by_text('模型假设：未触发规则', exact=True)).to_be_visible()
            page.get_by_text('原始模型响应', exact=True).click()
            expect(page.get_by_text('TEST FIXTURE ONLY — NOT MODEL INFERENCE', exact=True)).to_be_visible()
            page.unroute('**/api/sessions/*/incidents/*')
            checks.append('test-only model response fixture: conflict, failure and raw-output rendering; no inference or persistence')
        assert not errors, errors
        browser_version = browser.version
        browser.close()
    report = {'observed': time.time(), 'platform': platform.platform(), 'browser': args.channel,
              'browser_version': browser_version, 'results': checks, 'page_errors': errors,
              'data_source': 'synthetic', 'real_model_tested': args.model_review,
              'visual_inspection_performed': False}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
