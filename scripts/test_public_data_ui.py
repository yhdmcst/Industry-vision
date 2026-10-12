"""Opt-in browser check for an already prepared public dataset, without network downloads."""

import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8501')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--channel', default='chrome')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/ui-public-data')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
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
        assert imported.value.ok
        dataset_id = imported.value.json()['id']
        manifest = page.request.get(args.url + '/api/datasets/' + dataset_id).json()
        evaluation = [s for s in manifest['samples'] if s['split'] == 'evaluation']
        assert evaluation and all(s['origin'] == 'real' for s in manifest['samples'])
        expect(page.get_by_role('heading', name=manifest['name'], exact=True)).to_be_visible()
        page.get_by_label('样本分组', exact=True).select_option('evaluation')
        page.get_by_role('button', name=evaluation[0]['id'], exact=True).click()
        page.wait_for_function("document.querySelector('img[alt=\"样本预览\"]')?.naturalWidth === 640")
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(args.output / 'desktop.png'), full_page=True)
        page.get_by_role('button', name='建立回放', exact=True).click()
        expect(page.get_by_test_id('replay-progress')).to_contain_text('0/' + str(len(evaluation)))
        for _ in evaluation:
            response = page.request.post(args.url + '/api/capture', data={'action': 'sample'})
            assert response.ok, response.text()
        exported = page.request.get(args.url + '/api/replay/export').json()
        assert exported['replay']['completed']
        assert len(exported['results']) == len(evaluation)
        page.goto(args.url + '/#evaluation')
        expect(page.get_by_text('演示检测不计算缺陷分类指标', exact=True)).to_be_visible()
        page.wait_for_function("document.querySelector('img[alt=\"评估样本\"]')?.naturalWidth > 0")
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.output / 'mobile.png'), full_page=True)
        assert not errors, errors
        report = {'observed': time.time(), 'dataset_id': dataset_id, 'evaluated': len(evaluation),
                  'scope': 'Public real images; reference residual demo, no camera or Spark inference',
                  'checks': ['public image import and rendering', 'complete replay', 'proxy metrics isolation', '1440px/390px layout'],
                  'console_errors': errors}
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        assert page.request.post(args.url + '/api/source', data={'mode': 'synthetic'}).ok
        assert page.request.post(args.url + '/api/baseline', data={'count': 20}).ok
        browser.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
