"""Browser acceptance of real offline PaDiM result packages and explicitly injected failure feedback."""

import argparse
import json
from pathlib import Path
import tempfile
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8501')
    parser.add_argument('--channel', default='chrome')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/ui-anomaly')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    experiment = json.loads((args.experiment / 'experiment.json').read_bytes())
    total = experiment['variants']['raw']['metrics']['planned']
    with tempfile.TemporaryDirectory(prefix='spark-anomaly-ui-') as temporary, sync_playwright() as pw:
        browser = pw.chromium.launch(channel=None if args.channel == 'chromium' else args.channel, headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url + '/#settings')
        assert page.request.get(args.url + '/api/state').json()['source'] == 'synthetic', 'Use a dedicated synthetic workstation'
        assert page.request.post(args.url + '/api/capture', data={'action': 'pause'}).ok
        page.get_by_label('数据集清单路径', exact=True).fill(str(args.manifest.resolve()))
        with page.expect_response('**/api/datasets/import') as imported:
            page.get_by_role('button', name='导入数据集', exact=True).click()
        assert imported.value.ok and imported.value.json()['id'] == experiment['dataset_id']
        reports = {}
        sessions = {}
        for mode in ('raw', 'aligned'):
            page.get_by_label('检测结果文件路径', exact=True).fill(str((args.experiment / mode / 'inspection-results.json').resolve()))
            with page.expect_response('**/api/inspection-results/import') as imported:
                page.get_by_role('button', name='导入检测结果', exact=True).click()
            assert imported.value.ok
            result_id = imported.value.json()['id']
            expect(page.get_by_label('检测结果来源', exact=True)).to_have_value(result_id)
            expect(page.get_by_text('异常分数不是置信度，高于阈值判 NG。', exact=False)).to_be_visible()
            page.get_by_role('button', name='建立回放', exact=True).click()
            expect(page.get_by_test_id('replay-progress')).to_contain_text(f'0/{total}')
            for _ in range(total):
                response = page.request.post(args.url + '/api/capture', data={'action': 'sample'})
                assert response.ok, response.text()
            replay = page.request.get(args.url + '/api/replay/export').json()
            assert replay['replay']['completed']
            assert all(r['detection']['confidence'] is None for r in replay['results'])
            sessions[mode] = replay['session']
            reports[mode] = page.request.get(args.url + '/api/sessions/' + replay['session'] + '/evaluation').json()
            expected = experiment['variants'][mode]['metrics']
            measured = reports[mode]['summary']['inspection']
            for key in ('tp', 'tn', 'fp', 'fn', 'recall', 'false_positive_rate'):
                assert measured[key] == expected[key], (mode, key, measured[key], expected[key])
            (args.output / f'{mode}-evaluation.json').write_text(json.dumps(reports[mode], ensure_ascii=False, indent=2))
        page.goto(args.url + '/#evaluation')
        page.get_by_label('评估会话', exact=True).select_option(sessions['aligned'])
        page.get_by_label('对比会话', exact=True).select_option(sessions['raw'])
        expect(page.get_by_text(f'已配对 {total} 个', exact=True)).to_be_visible()
        page.get_by_label('核对筛选', exact=True).select_option('issue')
        fn = next(r['sample_id'] for r in reports['aligned']['samples'] if r['defect_label'] == 'defect' and r['is_ng'] is False)
        page.get_by_role('button', name=fn, exact=True).click()
        expect(page.get_by_text('姿态对齐：通过', exact=True)).to_be_visible()
        page.wait_for_function("document.querySelector('img[alt=\"评估样本\"]')?.naturalWidth === 640")
        page.locator('.toast').wait_for(state='detached')
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(args.output / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.output / 'mobile.png'), full_page=True)
        # Failure feedback is a separate synthetic result package, never added to actual accuracy metrics.
        injected = json.loads((args.experiment / 'aligned/inspection-results.json').read_bytes())
        injected['producer']['name'] = 'Injected alignment failure'
        injected['producer']['provenance'] = 'synthetic_fixture'
        sample = reports['aligned']['samples'][0]
        row = next(r for r in injected['results'] if r['sample_id'] == sample['sample_id'])
        injected['results'][injected['results'].index(row)] = {'sample_id': row['sample_id'], 'image_sha256': row['image_sha256'],
            'status': 'error', 'error': 'Injected alignment rejection', 'alignment': {'status': 'rejected', 'error': 'Injected alignment rejection'}}
        path = Path(temporary) / 'failure.json'; path.write_text(json.dumps(injected))
        response = page.request.post(args.url + '/api/inspection-results/import', data={'path': str(path)})
        assert response.ok
        assert page.request.post(args.url + '/api/replay', data={'dataset_id': experiment['dataset_id'], 'result_id': response.json()['id']}).ok
        assert page.request.post(args.url + '/api/capture', data={'action': 'sample'}).ok
        page.goto(args.url + '/#monitor')
        expect(page.get_by_text('Injected alignment rejection', exact=True).first).to_be_visible()
        expect(page.get_by_text('姿态对齐：拒绝', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.output / 'mobile-rejection.png'), full_page=True)
        assert not errors, errors
        assert page.request.post(args.url + '/api/source', data={'mode': 'synthetic'}).ok
        assert page.request.post(args.url + '/api/baseline', data={'count': 20}).ok
        report = {'observed': time.time(), 'dataset_id': experiment['dataset_id'],
                  'scope': 'Real VisA images and real ResNet18/PaDiM output; separate synthetic rejection injection; no camera or Spark inference',
                  'checks': ['raw/aligned result import', 'complete replay matches offline metrics', 'null confidence',
                             'version comparison', 'alignment evidence', 'failure remains unavailable', '1440px/390px layout'],
                  'console_errors': errors}
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
