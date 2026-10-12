"""Exercise baseline rollback and alert evidence using a dedicated synthetic workstation."""

import argparse
import json
from pathlib import Path
import tempfile
import time

import cv2
import numpy as np
from playwright.sync_api import expect, sync_playwright

from create_demo_dataset import create_demo
from create_demo_results import create_results


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8501')
    parser.add_argument('--channel', default='chrome')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/ui-reliability')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    with tempfile.TemporaryDirectory(prefix='spark-reliability-ui-') as temporary, sync_playwright() as pw:
        browser = pw.chromium.launch(channel=None if args.channel == 'chromium' else args.channel, headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        page.on('pageerror', lambda error: errors.append(str(error)))

        def state():
            return page.request.get(args.url + '/api/state').json()

        def post(endpoint, body):
            response = page.request.post(args.url + '/api' + endpoint, data=body)
            assert response.ok, response.text()
            return response.json()

        def navigate(name):
            if page.get_by_role('button', name='打开导航', exact=True).is_visible():
                page.get_by_role('button', name='打开导航', exact=True).click()
            page.get_by_role('navigation', name='主导航').get_by_role('button', name=name).click()
            expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()

        def sample():
            post('/capture', {'action': 'sample'})
            return state()

        def screenshot(name):
            expect(page.locator('.toast')).to_have_count(0, timeout=6000)
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(args.output / name), full_page=True)

        page.goto(args.url)
        expect(page.get_by_role('heading', name='监测工作台', exact=True)).to_be_visible()
        assert state()['source'] == 'synthetic', 'Use a dedicated synthetic workstation'
        post('/capture', {'action': 'pause'})
        post('/scenario', {'scenario': 'none'})
        post('/baseline', {'count': 10})
        for _ in range(10): sample()
        existing_ids = {e['id'] for e in page.request.get(args.url + f'/api/sessions/{state()["session"]}/incidents').json()}
        page.reload()
        expect(page.get_by_test_id('alert-state')).to_contain_text('未触发规则')
        post('/scenario', {'scenario': 'focus_change', 'intensity': .8})
        first = sample()
        episode = first['alert']['episode']
        session = first['session']
        frozen = page.request.get(args.url + f'/api/sessions/{session}/incidents/{episode["incident_id"]}').json()['event']
        post('/scenario', {'scenario': 'light_fade', 'intensity': .8})
        for _ in range(3): sample()
        events = page.request.get(args.url + f'/api/sessions/{session}/incidents').json()
        assert [e['id'] for e in events if e['id'] not in existing_ids] == [episode['incident_id']]
        assert state()['alert']['episode']['incident_id'] == episode['incident_id']
        expect(page.get_by_test_id('alert-state')).to_contain_text('告警持续')
        screenshot('active.png')
        post('/scenario', {'scenario': 'none'})
        for _ in range(60):
            current = sample()
            if current['alert']['state'] == 'recovering':
                assert current['alert']['recovery_streak'] == 1
                break
        else:
            raise AssertionError('No recovery candidate within 60 frames')
        expect(page.get_by_test_id('alert-state')).to_contain_text('恢复确认中')
        expect(page.get_by_test_id('recovery-streak')).to_contain_text('1/3')
        sample()
        assert sample()['alert']['state'] == 'recovered'
        expect(page.get_by_test_id('alert-state')).to_contain_text('规则已恢复')
        navigate('事件复核')
        page.get_by_label('搜索事件', exact=True).fill(str(episode['incident_id']))
        page.locator('.event-card').filter(has_text=f'#{episode["incident_id"]}').click()
        expect(page.get_by_role('heading', name='告警生命周期', exact=True)).to_be_visible()
        expect(page.get_by_text('连续帧满足恢复规则', exact=False)).to_be_visible()
        expect(page.get_by_text('新增证据', exact=False).first).to_be_visible()
        expect(page.get_by_test_id('episode-timeline').locator('p').first).to_contain_text('新增证据')
        expect(page.get_by_test_id('episode-timeline').locator('p').last).to_contain_text('连续帧满足恢复规则')
        with page.expect_download() as download:
            page.get_by_role('button', name='导出事件证据', exact=True).click()
        evidence_path = args.output / 'recovered-event.json'
        download.value.save_as(str(evidence_path))
        evidence = json.loads(evidence_path.read_text())
        assert evidence['event'] == frozen
        assert evidence['lifecycle']['state'] == 'recovered' and evidence['updates']
        assert evidence['lifecycle_events'][0]['payload']['snapshot']['detection_availability']['ready']
        screenshot('recovered.png')
        checks.append('one episode across changing rules, consecutive recovery, frozen initial event and additive evidence download')

        # An actual decoded video supplies valid reference frames followed by unusably dark frames.
        manifest_path = create_demo(Path(temporary) / 'input')
        reference = cv2.imread(str(manifest_path.parent / 'sample-000.png'))
        video_path = Path(temporary) / 'quality-gate.avi'
        writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (640, 480))
        assert writer.isOpened()
        for image in [reference] * 10 + [np.zeros_like(reference)] * 10:
            writer.write(image)
        writer.release()
        post('/source', {'mode': 'video', 'video': str(video_path)})
        navigate('基线与漂移')
        page.get_by_label('样本数量', exact=True).fill('10')
        page.get_by_label('确认当前取景适合作为参考基线', exact=True).check()
        page.get_by_role('button', name='建立新基线', exact=True).click()
        expect(page.get_by_text('全部样本通过', exact=True)).to_be_visible()
        before = state()
        page.get_by_label('确认当前取景适合作为参考基线', exact=True).check()
        page.get_by_role('button', name='建立新基线', exact=True).click()
        expect(page.get_by_test_id('baseline-rejected')).to_contain_text('基线未替换')
        expect(page.locator('.toast')).to_have_count(0)
        after = state()
        assert after['baseline'] == before['baseline']
        assert after['baseline_generation'] == before['baseline_generation']
        assert after['baseline_attempt']['valid_samples'] == 0
        page.get_by_text('查看拒绝样本', exact=True).click()
        expect(page.get_by_test_id('baseline-rejected')).to_contain_text('第 10 帧：过暗 / 缺少纹理')
        screenshot('baseline-rejected.png')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        screenshot('mobile-baseline.png')
        navigate('监测工作台')
        page.get_by_role('button', name='采样一帧', exact=True).click()
        expect(page.get_by_test_id('alert-state')).to_contain_text('采集不可用')
        assert state()['capture_error']
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        screenshot('capture-unavailable.png')
        checks.append('decoded synthetic video, quality rejection with old baseline retained, failed capture and 390px layouts')

        post('/source', {'mode': 'synthetic'})
        dataset_id = post('/datasets/import', {'path': str(manifest_path)})['id']
        dataset = page.request.get(args.url + f'/api/datasets/{dataset_id}').json()
        result_path = create_results(dataset, Path(temporary) / 'results.json')
        result_id = post('/inspection-results/import', {'path': str(result_path)})['id']
        post('/replay', {'dataset_id': dataset_id, 'result_id': result_id})
        sample()  # Fixture's first evaluation result is deliberately missing.
        expect(page.get_by_test_id('alert-state')).to_contain_text('告警持续')
        assert sample()['latest']['detection']['status'] == 'timeout'
        assert sample()['latest']['detection']['status'] == 'error'
        sample()
        expect(page.get_by_test_id('alert-state')).to_contain_text('恢复证据不足')
        assert state()['alert']['recovery_streak'] == 0
        navigate('基线与漂移')
        expect(page.get_by_test_id('alert-state')).to_contain_text('恢复证据不足')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        checks.append('missing upstream result starts an episode; subsequent incomplete window cannot recover it')
        assert not errors, errors
        report = {'observed': time.time(), 'scope': 'Synthetic PCB images, generated video and scripted upstream predictions; no camera or model',
                  'checks': checks, 'console_errors': errors}
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        post('/source', {'mode': 'synthetic'})
        post('/baseline', {'count': 20})
        browser.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
