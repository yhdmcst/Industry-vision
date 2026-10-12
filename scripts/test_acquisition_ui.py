"""Browser acceptance for acquisition drafts and publication; synthetic pixels only."""

import argparse
import hashlib
import json
from pathlib import Path
import time
import tempfile

import cv2
import numpy as np

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8501')
    parser.add_argument('--channel', default='chrome')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/ui-acquisition')
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
        assert page.request.delete(args.url + '/api/baseline').ok
        panel = page.locator('.acquisition-panel')
        expect(panel.get_by_role('heading', name='采集预检与样本留存')).to_be_visible()
        panel.get_by_label('新批次名称', exact=True).fill('合成采集验收')
        panel.get_by_label('采集计划', exact=True).fill('合成夹具，无现场准确率结论')
        panel.get_by_role('button', name='创建采集批次', exact=True).click()
        expect(panel.get_by_label('留存批次', exact=True)).not_to_have_value('')
        batch_id = panel.get_by_label('留存批次', exact=True).input_value()
        panel.get_by_role('button', name='采集预览帧', exact=True).click()
        expect(panel.get_by_test_id('capture-quality')).to_contain_text('取景质量门通过')
        expect(panel.get_by_role('button', name='放大取景预览', exact=True)).to_be_visible()
        item = page.request.get(args.url + '/api/state').json()['acquisition']['preview']
        image = page.request.get(args.url + '/api/acquisition/preview/image?token=' + item['token']).body()
        panel.get_by_label('留存分组', exact=True).select_option('baseline')
        panel.get_by_role('button', name='留存预览样本', exact=True).click()
        expect(panel.get_by_test_id('capture-counts')).to_contain_text('共 1/500')
        expect(panel.get_by_role('button', name='留存预览样本', exact=True)).to_be_disabled()
        first = page.request.get(args.url + '/api/acquisition/batches/' + batch_id).json()['samples'][0]
        assert first['sha256'] == hashlib.sha256(image).hexdigest()
        assert first['label']['defect'] == 'unknown' and first['origin'] == 'synthetic'
        for index in range(10):
            response = page.request.post(args.url + '/api/acquisition/preview')
            assert response.ok
            response = page.request.post(args.url + f'/api/acquisition/batches/{batch_id}/samples', data={
                'token': response.json()['token'], 'split': 'baseline' if index < 9 else 'evaluation', 'origin': 'synthetic'})
            assert response.ok, response.text()
        expect(panel.get_by_test_id('capture-counts')).to_contain_text('参考 10 · 评估 1')
        panel.get_by_label('独立缺陷标签', exact=True).select_option('normal')
        panel.get_by_label('独立原因标签', exact=True).select_option('none')
        panel.get_by_label('标注依据', exact=True).fill('UI_LABEL_WITHHELD')
        panel.get_by_role('button', name='保存样本标注', exact=True).click()
        expect(panel.get_by_role('status')).to_contain_text('独立核验标注已保存')
        with page.expect_response('**/api/acquisition/batches/*/publish') as publication:
            panel.get_by_role('button', name='发布为回放数据集', exact=True).click()
        expect(panel.get_by_test_id('published-capture')).to_contain_text('合成采集验收')
        dataset_id = publication.value.json()['id']
        original = page.request.get(args.url + '/api/datasets/' + dataset_id).json()
        assert original['samples'][-1]['label']['note'] == 'UI_LABEL_WITHHELD'
        # Published confirmation must survive the state revision poll.
        page.wait_for_timeout(1200)
        expect(panel.get_by_test_id('published-capture')).to_be_visible()
        expect(page.get_by_label('已导入数据集', exact=True).locator(f'option[value="{dataset_id}"]')).to_have_count(1)
        panel.get_by_label('独立缺陷标签', exact=True).select_option('defect')
        panel.get_by_label('独立原因标签', exact=True).select_option('product')
        panel.get_by_role('button', name='保存样本标注', exact=True).click()
        expect(panel.get_by_role('status')).to_contain_text('独立核验标注已保存')
        with page.expect_response('**/api/acquisition/batches/*/publish') as publication:
            panel.get_by_role('button', name='发布为回放数据集', exact=True).click()
        second_id = publication.value.json()['id']
        assert second_id != dataset_id
        assert page.request.get(args.url + '/api/datasets/' + dataset_id).json() == original
        page.reload()
        panel.get_by_label('留存批次', exact=True).select_option(batch_id)
        expect(panel.get_by_test_id('capture-counts')).to_contain_text('共 11/500')
        expect(panel.get_by_label('独立缺陷标签', exact=True)).to_have_value('defect')
        page.screenshot(path=str(args.output / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        panel.get_by_role('button', name='采集预览帧', exact=True).click()
        expect(panel.get_by_role('button', name='放大取景预览', exact=True)).to_be_visible()
        page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.output / 'mobile.png'), full_page=True)
        page.get_by_label('已导入数据集', exact=True).select_option(second_id)
        page.get_by_role('button', name='建立回放', exact=True).click()
        expect(page.get_by_test_id('replay-progress')).to_contain_text('0/1')
        expect(panel.get_by_role('button', name='采集预览帧', exact=True)).to_be_disabled()
        page.get_by_role('button', name='回放下一帧', exact=True).click()
        expect(page.get_by_test_id('replay-progress')).to_contain_text('回放完成')
        exported = page.request.get(args.url + '/api/replay/export').json()
        assert exported['results'][0]['sample']['label']['defect'] == 'defect'
        assert page.request.post(args.url + '/api/source', data={'mode': 'synthetic'}).ok
        page.set_viewport_size({'width': 1440, 'height': 1100})
        page.reload()
        panel.get_by_label('留存批次', exact=True).select_option(batch_id)
        with tempfile.TemporaryDirectory(prefix='spark-acquisition-ui-') as temporary:
            video = Path(temporary) / 'dark.avi'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (640, 480))
            assert writer.isOpened()
            writer.write(np.zeros((480, 640, 3), np.uint8))
            writer.release()
            assert page.request.post(args.url + '/api/source', data={'mode': 'video', 'video': str(video)}).ok
            panel.get_by_role('button', name='采集预览帧', exact=True).click()
            expect(panel.get_by_test_id('capture-quality')).to_contain_text('取景质量门拒绝')
            panel.get_by_label('留存分组', exact=True).select_option('baseline')
            expect(panel.get_by_role('button', name='留存预览样本', exact=True)).to_be_disabled()
            panel.get_by_label('留存分组', exact=True).select_option('evaluation')
            panel.get_by_role('button', name='留存预览样本', exact=True).click()
            expect(panel.get_by_role('status')).to_contain_text('预览像素已留存')
            panel.get_by_role('button', name='采集预览帧', exact=True).click()
            expect(panel.get_by_role('alert')).to_be_visible()
            expect(panel.get_by_role('status')).to_have_count(0)
            expect(panel.get_by_role('button', name='放大取景预览', exact=True)).to_have_count(0)
            expect(panel.get_by_role('button', name='留存预览样本', exact=True)).to_be_disabled()
        assert page.request.post(args.url + '/api/source', data={'mode': 'synthetic'}).ok
        panel.get_by_role('button', name='采集预览帧', exact=True).click()
        expect(panel.get_by_role('alert')).to_have_count(0)
        # Inject an API failure, not a storage failure, to exercise browser feedback.
        page.route('**/api/acquisition/batches/*/samples', lambda route: route.fulfill(
            status=409, content_type='application/json', body='{"detail":"留存失败验收夹具"}'))
        panel.get_by_role('button', name='留存预览样本', exact=True).click()
        expect(page.get_by_role('alert').filter(has_text='留存失败验收夹具')).to_be_visible()
        expect(panel.get_by_role('status')).to_have_count(0)
        page.unroute('**/api/acquisition/batches/*/samples')
        assert not errors, errors
        assert page.request.post(args.url + '/api/source', data={'mode': 'synthetic'}).ok
        assert page.request.post(args.url + '/api/baseline', data={'count': 20}).ok
        report = {'observed': time.time(), 'scope': 'Synthetic source; no physical camera or model inference',
                  'checks': ['preview without baseline', 'exact retained pixels', 'unknown initial labels',
                             'duplicate preview rejection', 'annotation', 'immutable publication and revision refresh',
                             'draft reload', 'published dataset replay', 'quality rejection/evaluation retention',
                             'video EOF clears old preview', 'failed save feedback', '1440px/390px layout'], 'console_errors': errors}
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        browser.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
