"""UI acceptance for a supplied real study; rating/write failures use clearly labeled test fixtures."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8503')
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(args.url+'/#evaluation')
        expect(page.get_by_role('heading', name='回放评估', exact=True)).to_be_visible()
        assert page.request.get(args.url+'/api/state').json()['source'] == 'synthetic', 'Dedicated workstation required'
        panel = page.locator('section').filter(has=page.get_by_role('heading', name='模型复核评估', exact=True))
        page.get_by_label('复核实验文件路径', exact=True).fill(str(args.study.resolve()))
        with page.expect_response('**/api/review-studies/import') as imported:
            page.get_by_role('button', name='导入复核实验', exact=True).click()
        assert imported.value.ok, imported.value.text()
        report = imported.value.json(); initial_id = report['report_sha256']
        expect(page.get_by_label('复核报告版本', exact=True)).to_have_value(initial_id)
        expect(panel.get_by_text('效果尚未验收', exact=True)).to_be_visible()
        expect(panel.get_by_text('规则观测', exact=True)).to_be_visible()
        expect(panel.get_by_text('Spark 4B · 有上下文', exact=True)).to_be_visible()
        assert panel.locator('table tbody tr').count() == len(report['summaries'])
        if any(s['id'] == 'qwen3_4b_with_context' for s in report['summaries']):
            expect(panel.get_by_text('Qwen3 4B · 有上下文', exact=True)).to_be_visible()
        page.get_by_text('同题增益与退化', exact=True).click()
        expect(panel.get_by_text('危害建议从“有”变“无”计为改善', exact=False)).to_be_visible()
        assert all(p['human']['unsafe_action']['paired_rated'] == 0 for p in report['pairs'])
        expect(panel.get_by_text('存在危害建议：待评，待配对 '+str(report['summaries'][0]['planned']), exact=False).first).to_be_visible()
        page.screenshot(path=str(args.output/'desktop-pairs.png'), full_page=True)
        page.get_by_text('同题增益与退化', exact=True).click()
        with page.expect_download() as saved: page.get_by_role('button', name='下载复核报告', exact=True).click()
        saved.value.save_as(args.output/'report.json')
        assert json.loads((args.output/'report.json').read_bytes()) == report
        page.screenshot(path=str(args.output/'desktop.png'), full_page=True)

        # Failure is a separate experiment copy, never mixed into the measured source report.
        source = json.loads(args.study.read_bytes()); fixture = deepcopy(source)
        fixture['runtime_scope'] += '; UI TEST COPY WITH ONE INJECTED FAILURE; NOT ORIGINAL EXPERIMENT'
        row = next(r for r in fixture['results'] if r['candidate_id'] != 'rules')
        row.update(status='error', analysis=None, error='UI TEST FIXTURE: inference unavailable', raw_response='')
        path = args.output/'fault-fixture.json'; path.write_text(json.dumps(fixture, ensure_ascii=False))
        page.get_by_label('复核实验文件路径', exact=True).fill(str(path.resolve()))
        page.get_by_role('button', name='导入复核实验', exact=True).click()
        expect(page.get_by_role('status').filter(has_text='复核实验已导入')).to_be_visible()
        page.get_by_text('逐项结果与失败', exact=True).click()
        expect(page.get_by_text('UI TEST FIXTURE: inference unavailable', exact=True)).to_be_visible()
        page.get_by_label('复核报告版本', exact=True).select_option(initial_id)
        expect(panel.get_by_text('规则观测', exact=True)).to_be_visible()
        page.get_by_role('button', name='进入匿名评分', exact=True).click()
        expect(panel.get_by_text('规则观测', exact=True)).to_have_count(0)
        with page.expect_download() as cards: page.get_by_role('button', name='下载匿名评分卡', exact=True).click()
        cards.value.save_as(args.output/'human-cards.json')
        assert all('candidate_id' not in c for c in json.loads((args.output/'human-cards.json').read_bytes())['cards'])
        # This is UI state verification, not a real human quality/safety judgment.
        page.get_by_label('实际复核人', exact=True).fill('UI TEST FIXTURE: NOT HUMAN ACCEPTANCE')
        page.get_by_label('证据忠实', exact=True).select_option('false')
        page.get_by_label('步骤可执行', exact=True).select_option('false')
        page.get_by_label('存在危害建议', exact=True).select_option('unknown')
        expect(page.get_by_role('button', name='保存评分版本', exact=True)).to_be_disabled()
        page.get_by_label('评分依据', exact=True).fill('明确浏览器夹具；只测试保存与待评语义，不评价模型实际质量。')
        expect(page.get_by_label('复核报告版本', exact=True)).to_be_disabled()
        page.route('**/api/review-studies/*/ratings', lambda route: route.fulfill(status=409, json={'detail':'UI TEST FIXTURE: ratings save failed'}))
        page.get_by_role('button', name='保存评分版本', exact=True).click()
        expect(page.get_by_role('alert').filter(has_text='UI TEST FIXTURE: ratings save failed')).to_be_visible()
        expect(page.get_by_label('评分依据', exact=True)).not_to_be_empty()
        page.unroute('**/api/review-studies/*/ratings')
        with page.expect_response('**/api/review-studies/*/ratings') as updated:
            page.get_by_role('button', name='保存评分版本', exact=True).click()
        assert updated.value.ok
        updated_report = updated.value.json()
        assert not updated_report['accepted']
        assert updated_report['annotation']['independent_reviewer_declared'] is False
        expect(page.get_by_role('status').filter(has_text='评分已保存为报告版本')).to_be_visible()
        page.reload()
        page.get_by_label('复核报告版本', exact=True).select_option(updated_report['report_sha256'])
        page.get_by_role('button', name='进入匿名评分', exact=True).click()
        expect(page.get_by_label('实际复核人', exact=True)).to_have_value('UI TEST FIXTURE: NOT HUMAN ACCEPTANCE')
        expect(page.get_by_label('存在危害建议', exact=True)).to_have_value('unknown')
        page.get_by_label('复核报告版本', exact=True).select_option(initial_id)
        expect(page.get_by_label('实际复核人', exact=True)).to_have_value('')
        page.get_by_role('button', name='退出匿名评分', exact=True).click()
        page.set_viewport_size({'width':390, 'height':844})
        page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        table_wrap = panel.locator('.evaluation-table-wrap')
        assert table_wrap.evaluate('(el) => el.scrollWidth > el.clientWidth'), 'Narrow table must scroll rather than squeeze columns'
        assert panel.locator('table th').first.evaluate('(el) => el.getBoundingClientRect().width >= 75')
        assert table_wrap.evaluate('(el) => { el.scrollLeft = 100; return el.scrollLeft > 0; }')
        table_wrap.evaluate('(el) => { el.scrollLeft = 0; }')
        page.screenshot(path=str(args.output/'mobile.png'), full_page=True)
        page.get_by_text('同题增益与退化', exact=True).click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.output/'mobile-pairs.png'), full_page=True)
        page.get_by_text('同题增益与退化', exact=True).click()
        page.get_by_role('button', name='进入匿名评分', exact=True).click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.output/'mobile-rating.png'), full_page=True)
        page.route('**/api/review-studies/*', lambda route: route.fulfill(status=409, json={'detail':'UI TEST FIXTURE: report read failed'}))
        page.reload()
        expect(page.get_by_role('alert').filter(has_text='UI TEST FIXTURE: report read failed')).to_be_visible()
        page.unroute('**/api/review-studies/*'); page.reload()
        expect(page.get_by_role('button', name='下载复核报告', exact=True)).to_be_visible()
        assert not errors, errors
        browser.close()
    result = {'observed': time.time(), 'source_study': report['study_id'], 'real_source_report': initial_id,
              'checks': ['real study import and report export', 'planned failure fixture stays unavailable',
                         'anonymous cards', 'strict unknown human rating', 'save failure then retry',
                         'new report version and old report preservation', 'reload recovery', 'desktop and 390px layout'],
              'page_errors': errors, 'scope': 'Real study results displayed; human scoring and fault checks are explicit UI fixtures, never real acceptance'}
    (args.output/'ui-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
