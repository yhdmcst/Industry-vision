"""Browser acceptance for external inspection files; synthetic images and predictions only."""

import argparse
import json
from pathlib import Path
import tempfile
import time

from playwright.sync_api import expect, sync_playwright

from create_demo_dataset import create_demo
from create_demo_results import create_results

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8501')
    parser.add_argument('--channel', default='chrome')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/ui-inspection')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='spark-inspection-') as temporary, sync_playwright() as pw:
        manifest = create_demo(Path(temporary) / 'dataset')
        browser = pw.chromium.launch(channel=None if args.channel == 'chromium' else args.channel, headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def navigate(name):
            if page.get_by_role('button', name='打开导航', exact=True).is_visible():
                page.get_by_role('button', name='打开导航', exact=True).click()
            page.get_by_role('navigation', name='主导航').get_by_role('button', name=name).click()
            expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()

        def screenshot(name):
            expect(page.locator('.toast')).to_have_count(0, timeout=6000)
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(args.output / name), full_page=True)

        page.goto(args.url + '/#settings')
        expect(page.get_by_role('heading', name='样本管理与回放', exact=True)).to_be_visible()
        assert page.request.get(args.url + '/api/state').json()['source'] == 'synthetic', 'Use a dedicated synthetic workstation'
        assert page.request.post(args.url + '/api/capture', data={'action': 'pause'}).ok
        page.get_by_label('数据集清单路径', exact=True).fill(str(manifest))
        page.get_by_role('button', name='导入数据集', exact=True).click()
        expect(page.get_by_role('heading', name='PCB 合成回放示例', exact=True)).to_be_visible(timeout=30000)
        catalog = page.request.get(args.url + '/api/datasets').json()
        dataset_id = next(d['id'] for d in catalog if d['name'] == 'PCB 合成回放示例')
        dataset = page.request.get(args.url + f'/api/datasets/{dataset_id}').json()
        result_path = create_results(dataset, Path(temporary) / 'results.json')
        page.get_by_label('检测结果文件路径', exact=True).fill(str(result_path))
        page.get_by_role('button', name='导入检测结果', exact=True).click()
        expect(page.locator('.inspection-input')).to_contain_text('成功 37')
        result_id = page.get_by_label('检测结果来源', exact=True).input_value()
        assert len(result_id) == 64
        page.get_by_label('样本分组', exact=True).select_option('evaluation')
        page.get_by_role('button', name='sample-010', exact=True).click()
        expect(page.locator('.inspection-input')).to_contain_text('缺失（结果包未提供）')
        page.get_by_role('button', name='建立回放', exact=True).click()
        expect(page.get_by_test_id('replay-progress')).to_contain_text('0/30')
        navigate('监测工作台')
        panel = page.locator('.inspection-evidence')
        for status, label in [('missing', '缺失'), ('timeout', '超时'), ('error', '失败')]:
            page.get_by_role('button', name='采样一帧', exact=True).click()
            expect(panel.locator('dd').first).to_have_text(label)
            expect(panel).to_contain_text('不可用')
            expect(panel).to_contain_text('合成结果夹具')
            latest = page.request.get(args.url + '/api/state').json()['latest']
            assert latest['detection']['status'] == status
            assert latest['detection']['confidence'] is None and latest['detection']['is_ng'] is None
            assert latest['rule_report']['metrics']['consistency'] == {}
            assert latest['rule_report']['drift_type'] == 'unknown'
            expect(page.locator('.observation-status')).to_have_class('observation-status warning')
        screenshot('unavailable-desktop.png')
        navigate('事件复核')
        expect(page.locator('.inspection-evidence')).to_contain_text('检测状态缺失')
        expect(page.get_by_text('合成测试：推理失败', exact=False)).to_be_visible()
        expect(page.get_by_role('button', name='请求模型复核', exact=True)).to_be_disabled()
        with page.expect_download() as download:
            page.get_by_role('button', name='导出事件证据', exact=True).click()
        event_path = args.output / 'event.json'
        download.value.save_as(str(event_path))
        bundle = json.loads(event_path.read_text())
        event = bundle['event']['payload']
        assert event['detection']['status'] == 'missing'
        assert [update['payload']['detection']['status'] for update in bundle['updates']] == ['timeout', 'error']
        assert bundle['updates'][-1]['payload']['detection']['metadata']['result']['error'] == '合成测试：推理失败'
        session = page.request.get(args.url + '/api/state').json()['session']
        assert len(page.request.get(args.url + f'/api/sessions/{session}/incidents').json()) == 1
        assert event['inspection_source']['result_id'] == result_id
        assert '合成测试' not in json.dumps(event['snapshot'], ensure_ascii=False)
        assert all('合成测试' not in json.dumps(update['payload']['snapshot'], ensure_ascii=False)
                   for update in bundle['updates'])
        screenshot('review-desktop.png')
        navigate('监测工作台')
        page.get_by_role('button', name='采样一帧', exact=True).click()
        expect(panel.locator('dd').first).to_have_text('成功')
        expect(panel.locator('dd').nth(1)).to_have_text('NG')
        expect(panel).to_contain_text('0.930')
        expect(panel).to_contain_text('demo_scratch')
        expect(panel).to_contain_text('一致性统计暂停')
        screenshot('ng-desktop.png')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        screenshot('monitor-mobile.png')
        navigate('设置与演示')
        expect(page.get_by_label('检测结果来源', exact=True)).to_have_value(result_id)
        page.route('**/api/inspection-results/' + result_id, lambda route: route.fulfill(
            status=400, content_type='application/json', body='{"detail":"读取测试：结果文件损坏"}'))
        page.get_by_label('检测结果来源', exact=True).select_option('')
        page.get_by_label('检测结果来源', exact=True).select_option(result_id)
        expect(page.locator('.inspection-input')).to_contain_text('结果读取失败')
        expect(page.locator('.inspection-input')).to_contain_text('结果文件损坏')
        page.unroute('**/api/inspection-results/' + result_id)
        page.get_by_label('检测结果来源', exact=True).select_option('')
        page.get_by_label('检测结果来源', exact=True).select_option(result_id)
        expect(page.locator('.inspection-input')).not_to_contain_text('结果读取失败')
        page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        screenshot('settings-mobile.png')
        with page.expect_download() as download:
            page.get_by_role('link', name='导出回放结果', exact=True).click()
        export_path = args.output / 'replay.json'
        download.value.save_as(str(export_path))
        exported = json.loads(export_path.read_text())
        assert exported['config']['inspection_source']['result_id'] == result_id
        assert len(exported['inspection_results']['results']) == 39 and len(exported['results']) == 4
        assert exported['results'][0]['detection']['status'] == 'missing'
        # Explicitly choose the proxy and create a fresh session; old evidence stays unchanged.
        page.get_by_label('检测结果来源', exact=True).select_option('')
        page.get_by_role('button', name='建立回放', exact=True).click()
        expect(page.get_by_test_id('replay-progress')).to_contain_text('0/30')
        state = page.request.get(args.url + '/api/state').json()
        assert state['session'] != exported['session']
        assert state['inspection_source']['kind'] == 'reference_residual_demo'
        assert page.request.get(args.url + f'/api/sessions/{exported["session"]}/replay').json() == exported
        assert not errors, errors
        report = {'observed': time.time(), 'scope': 'Synthetic images and predictions; no model or camera',
                  'checks': ['UI import and aligned sample preview', 'missing/timeout/error stay unavailable',
                             'frozen missing event, additive failure evidence and isolated model snapshots', 'high-confidence NG',
                             'active version selection and result read failure/recovery',
                             'full package export', 'explicit proxy switch and historical evidence',
                             '390px monitor/settings layout'], 'result_id': result_id, 'console_errors': errors}
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        assert page.request.post(args.url + '/api/source', data={'mode': 'synthetic'}).ok
        assert page.request.post(args.url + '/api/baseline', data={'count': 20}).ok
        browser.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
