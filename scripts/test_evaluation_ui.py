"""Replay evaluation acceptance with scripted synthetic labels, never defect ground truth."""

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
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/ui-evaluation')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='spark-evaluation-') as temporary, sync_playwright() as pw:
        browser = pw.chromium.launch(channel=None if args.channel == 'chromium' else args.channel, headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url + '/#evaluation')
        expect(page.get_by_role('heading', name='回放评估', exact=True)).to_be_visible()
        assert page.request.get(args.url + '/api/state').json()['source'] == 'synthetic', 'Use a dedicated synthetic workstation'
        if not page.request.get(args.url + '/api/replays').json():
            expect(page.get_by_text('暂无回放会话。先在“设置与演示”导入数据集并建立回放。', exact=True)).to_be_visible()

        def post(endpoint, body):
            response = page.request.post(args.url + '/api' + endpoint, data=body)
            assert response.ok, response.text()
            return response.json()

        def prepare(dataset_id, result_id, count):
            post('/replay', {'dataset_id': dataset_id, 'result_id': result_id})
            for _ in range(count): post('/capture', {'action': 'sample'})
            return page.request.get(args.url + '/api/state').json()['session']

        def screenshot(name):
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(args.output / name), full_page=True)

        manifest_path = create_demo(Path(temporary) / 'input')
        manifest = json.loads(manifest_path.read_text())
        for i, sample in enumerate(manifest['samples'][10:], 10):
            sample['label']['defect'] = 'normal' if i % 2 == 0 else 'defect'
            sample['label']['note'] = 'Scripted UI fixture only; arbitrary labels, no independently observed defect'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False))
        dataset_id = post('/datasets/import', {'path': str(manifest_path)})['id']
        dataset = page.request.get(args.url + f'/api/datasets/{dataset_id}').json()
        result_path = create_results(dataset, Path(temporary) / 'a.json')
        a_id = post('/inspection-results/import', {'path': str(result_path)})['id']
        left = prepare(dataset_id, a_id, 30)
        package = json.loads(result_path.read_text())
        package['producer']['version'] = '2.0'
        sample = dataset['samples'][10]
        package['results'].append({'sample_id': sample['id'], 'image_sha256': sample['sha256'],
                                   'status': 'ok', 'detected': True, 'confidence': .9, 'is_ng': False})
        for record in package['results']:
            if record['sample_id'] in ('sample-011', 'sample-014'):
                record.update(status='ok', detected=True, confidence=.9, is_ng=False, defect_types=[])
                record.pop('error', None)
        b_path = Path(temporary) / 'b.json'
        b_path.write_text(json.dumps(package, ensure_ascii=False))
        b_id = post('/inspection-results/import', {'path': str(b_path)})['id']
        right = prepare(dataset_id, b_id, 30)
        partial = prepare(dataset_id, a_id, 4)
        manifest['name'] = 'Different evaluation input'
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False))
        other_id = post('/datasets/import', {'path': str(manifest_path)})['id']
        other = prepare(other_id, None, 0)
        page.reload()
        page.get_by_label('评估会话', exact=True).select_option(left)
        expect(page.locator('.evaluation-metrics').get_by_text('27/30', exact=True)).to_have_count(2)
        expect(page.get_by_text('90.0%', exact=False).filter(has_text='覆盖率')).to_be_visible()
        expect(page.get_by_text('标签匹配率', exact=True)).to_be_visible()
        inspection_panel = page.locator('section').filter(has=page.get_by_role('heading', name='上游判定与缺陷标签', exact=True))
        expect(inspection_panel.locator('.fact-list > div').filter(has_text='标签匹配率')).to_contain_text('51.9%')
        expect(page.get_by_text('10 个评估样本与基线图像摘要重复；不能据此宣称盲测效果。', exact=True)).to_be_visible()
        page.get_by_label('核对筛选', exact=True).select_option('issue')
        page.get_by_role('button', name='sample-014', exact=True).click()
        expect(page.get_by_role('button', name='放大评估样本', exact=True)).to_be_visible()
        expect(page.locator('.evaluation-samples .fact-list')).to_contain_text('正常')
        expect(page.locator('.evaluation-samples .fact-list')).to_contain_text('NG')
        page.get_by_label('核对筛选', exact=True).select_option('not_run')
        expect(page.get_by_text('暂无匹配样本。', exact=True)).to_be_visible()
        page.get_by_label('核对筛选', exact=True).select_option('')
        page.get_by_label('评估来源', exact=True).select_option('real_unmodified')
        expect(page.get_by_text('暂无匹配样本。', exact=True)).to_be_visible()
        page.get_by_label('评估来源', exact=True).select_option('synthetic')
        with page.expect_download() as download:
            page.get_by_role('button', name='导出评估报告', exact=True).click()
        report_path = args.output / 'evaluation.json'
        download.value.save_as(str(report_path))
        report = json.loads(report_path.read_text())
        assert report['summary']['inspection']['fp'] == 13 and report['summary']['inspection']['fn'] == 0
        assert report['summary']['inspection']['coverage'] == .9
        assert report['summary']['inspection']['unavailable_labeled'] == 3
        page.get_by_label('对比会话', exact=True).select_option(right)
        expect(page.get_by_text('已配对 30 个', exact=True)).to_be_visible()
        expect(page.get_by_text('状态变化 2 · 判定变化 1/27 个双侧成功结果 · 规则观测变化', exact=False)).to_be_visible()
        with page.expect_download() as download:
            page.get_by_role('button', name='导出版本对比', exact=True).click()
        compare_path = args.output / 'comparison.json'
        download.value.save_as(str(compare_path))
        comparison = json.loads(compare_path.read_text())
        assert comparison['status_changes'] == 2 and comparison['verdict_changes'] == 1
        assert comparison['paired_summaries'][1]['inspection']['fp'] == 12
        assert comparison['paired_summaries'][1]['inspection']['fn'] == 1
        screenshot('desktop.png')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        screenshot('mobile.png')
        page.get_by_label('对比会话', exact=True).select_option(partial)
        expect(page.get_by_text('已配对 4 个', exact=True)).to_be_visible()
        expect(page.get_by_text('至少一个回放未完成，仅比较共同已运行样本；完整报告的匹配率不能直接用于版本优劣排名。', exact=True)).to_be_visible()
        page.get_by_label('对比会话', exact=True).select_option(other)
        expect(page.get_by_role('alert').filter(has_text='不能进行同条件对比')).to_be_visible()
        expect(page.get_by_role('button', name='导出版本对比', exact=True)).to_have_count(0)
        page.get_by_label('评估会话', exact=True).select_option(partial)
        expect(page.get_by_text('部分回放', exact=True)).to_be_visible()
        expect(page.locator('.evaluation-metrics').get_by_text('4/30', exact=True)).to_be_visible()
        page.get_by_label('核对筛选', exact=True).select_option('not_run')
        expect(page.get_by_role('button', name='sample-014', exact=True)).to_be_visible()
        page.get_by_role('button', name='sample-014', exact=True).click()
        expect(page.locator('.evaluation-samples .fact-list')).to_contain_text('未运行')
        # Failed evidence requests must remove the previous report and recover after refresh.
        pattern = '**/api/sessions/' + partial + '/evaluation'
        page.route(pattern, lambda route: route.fulfill(status=400, content_type='application/json', body='{"detail":"Fixture read failure"}'))
        page.get_by_role('button', name='刷新报告', exact=True).click()
        expect(page.get_by_role('alert').filter(has_text='Fixture read failure')).to_be_visible()
        expect(page.get_by_role('button', name='导出评估报告', exact=True)).to_have_count(0)
        page.unroute(pattern)
        page.get_by_role('button', name='刷新报告', exact=True).click()
        expect(page.get_by_role('button', name='导出评估报告', exact=True)).to_be_visible()
        page.get_by_label('评估会话', exact=True).select_option('')
        expect(page.get_by_role('button', name='刷新报告', exact=True)).to_be_enabled()
        assert not errors, errors
        checks = {'observed': time.time(), 'scope': 'Synthetic images, scripted annotations and predictions; no real model or camera',
                  'checks': ['evaluation entry', 'explicit confusion counts and coverage', 'leakage warning',
                             'sample filters and preview', 'snapshot JSON downloads', 'paired versions and status recovery',
                             'partial and incompatible runs', 'read failure and recovery', '390px layout'], 'console_errors': errors}
        (args.output / 'report.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
        post('/source', {'mode': 'synthetic'})
        post('/baseline', {'count': 20})
        browser.close()
        print(json.dumps(checks, ensure_ascii=False))


if __name__ == '__main__':
    main()
