"""Cross-batch composition, check invalidation and immutable replay browser acceptance."""

import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8501')
    parser.add_argument('--channel',default='chrome')
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/ui-composition')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel=None if args.channel=='chromium' else args.channel,headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1100})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url+'/#settings')
        assert page.request.get(args.url+'/api/state').json()['source']=='synthetic','Use a dedicated synthetic workstation'
        assert page.request.post(args.url+'/api/capture',data={'action':'pause'}).ok
        sources=[]
        for name in ['编排参考批次','编排评估批次']:
            response=page.request.post(args.url+'/api/acquisition/batches',data={'name':name})
            assert response.ok
            batch=response.json()
            records=[]
            for index in range(11):
                preview=page.request.post(args.url+'/api/acquisition/preview').json()
                response=page.request.post(args.url+f'/api/acquisition/batches/{batch["id"]}/samples',data={
                    'token':preview['token'],'origin':'synthetic','split':'baseline' if index<10 else 'evaluation'})
                assert response.ok
                records.append(response.json())
            sources.append({'id':batch['id'],'samples':records})
        panel=page.locator('.composition-panel')
        expect(panel.get_by_role('heading',name='跨批次数据集编排',exact=True)).to_be_visible()
        panel.get_by_label('编排数据集名称',exact=True).fill('跨批次合成验收')
        panel.get_by_label('编排来源',exact=True).select_option(sources[0]['id'])
        panel.get_by_label('加入用途',exact=True).select_option('baseline')
        panel.get_by_role('button',name='加入来源的参考组',exact=True).click()
        expect(panel.get_by_test_id('composition-counts')).to_contain_text('参考 10')
        expect(panel.get_by_role('button',name='放大编排来源预览',exact=True)).to_be_visible()
        panel.get_by_label('编排来源',exact=True).select_option(sources[1]['id'])
        panel.get_by_label('加入用途',exact=True).select_option('evaluation')
        panel.get_by_role('button',name='加入来源的评估组',exact=True).click()
        expect(panel.get_by_test_id('composition-counts')).to_contain_text('参考 10 · 评估 1')
        panel.get_by_role('button',name='检查编排',exact=True).click()
        expect(panel.get_by_test_id('composition-check')).to_contain_text('评估像素与参考重复')
        expect(panel.get_by_test_id('composition-check')).not_to_contain_text('参考与评估存在同一来源批次')
        panel.get_by_label('编排说明',exact=True).fill('独立样本标签，不传模型')
        expect(panel.get_by_role('button',name='发布编排数据集',exact=True)).to_have_count(0)
        panel.get_by_role('button',name='检查编排',exact=True).click()
        expect(panel.get_by_role('button',name='发布编排数据集',exact=True)).to_be_visible()
        # A second tab changes the draft after preflight. Publish must reject it even before UI polls.
        record=sources[1]['samples'][-1]
        page.route('**/api/state',lambda route:route.abort())
        with page.expect_response('**/api/composition/publish') as publication:
            assert page.request.patch(args.url+f'/api/acquisition/batches/{sources[1]["id"]}/samples/{record["id"]}',data={
                'split':'evaluation','label':{'defect':'normal','cause':'none','note':'UI_LABEL_WITHHELD'}}).ok
            # Use a deliberately stale checked payload, exercising the real endpoint and browser error state.
            panel.get_by_role('button',name='发布编排数据集',exact=True).click()
        assert publication.value.status==409
        expect(panel.get_by_role('alert')).to_contain_text('请重新执行发布前检查')
        page.unroute('**/api/state')
        panel.get_by_role('button',name='检查编排',exact=True).click()
        with page.expect_response('**/api/composition/publish') as publication:
            panel.get_by_role('button',name='发布编排数据集',exact=True).click()
        assert publication.value.ok
        dataset_id=publication.value.json()['id']
        expect(panel.get_by_role('status')).to_contain_text('编排数据集已发布')
        page.wait_for_timeout(1200)
        expect(panel.get_by_role('status')).to_contain_text('编排数据集已发布')
        manifest=page.request.get(args.url+'/api/datasets/'+dataset_id).json()
        assert manifest['samples'][-1]['label']['note']=='UI_LABEL_WITHHELD'
        assert manifest['samples'][-1]['lineage']['source_id']==sources[1]['id']
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(args.output/'desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        panel.get_by_role('button',name='移除样本 11',exact=True).click()
        expect(panel.get_by_test_id('composition-counts')).to_contain_text('共 10/500')
        expect(panel.get_by_role('button',name='检查编排',exact=True)).to_be_disabled()
        page.screenshot(path=str(args.output/'mobile.png'),full_page=True)
        assert page.request.post(args.url+'/api/replay',data={'dataset_id':dataset_id}).ok
        assert page.request.post(args.url+'/api/capture',data={'action':'sample'}).ok
        exported=page.request.get(args.url+'/api/replay/export').json()
        assert exported['results'][0]['sample']['label']['note']=='UI_LABEL_WITHHELD'
        assert page.request.get(args.url+'/api/datasets/'+dataset_id).json()==manifest
        assert not errors,errors
        assert page.request.post(args.url+'/api/source',data={'mode':'synthetic'}).ok
        assert page.request.post(args.url+'/api/baseline',data={'count':20}).ok
        report={'observed':time.time(),'scope':'Synthetic capture drafts; no camera or model',
                'checks':['cross-batch selection','source image preview','duplicate warnings','edit invalidates check',
                          'stale draft publish rejection','immutable publication','published replay','1440px/390px layout'],
                'console_errors':errors}
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        browser.close();print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
