"""Chrome acceptance of actual isolated PaDiM inference on a generated video of public images."""

import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8503')
    parser.add_argument('--model', type=Path, default=ROOT / 'data/models/padim-pcb1-aligned')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'artifacts/pose-study-pcb1/manifest.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/ui-visual-live')
    parser.add_argument('--model-review', action='store_true', help='Requires real local Spark; never uses a response fixture')
    parser.add_argument('--spark-model', default='spark-drift:4b-q4')
    parser.add_argument('--endpoint', default='http://127.0.0.1:11435')
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    declared = json.loads(args.manifest.read_bytes())
    reference = cv2.imread(str(args.manifest.parent / declared['samples'][0]['path']))
    evaluations = [s for s in declared['samples'] if s['split'] == 'evaluation']
    frames = [cv2.imread(str(args.manifest.parent / s['path'])) for s in evaluations[:3]]
    video = args.output / 'public-workflow.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 5, (640,480))
    assert writer.isOpened()
    for frame in [reference] * 10 + frames + [np.zeros_like(reference)] + frames[:1]: writer.write(frame)
    writer.release()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':1100})
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url + '/#settings')
        assert page.request.get(args.url + '/api/state').json()['source'] == 'synthetic', 'Dedicated workstation required'
        assert page.request.post(args.url + '/api/capture', data={'action':'pause'}).ok
        page.get_by_label('采集源', exact=True).select_option('video')
        page.get_by_label('本地视频路径', exact=True).fill(str(video.resolve()))
        with page.expect_response('**/api/source') as connected:
            page.get_by_role('button',name='连接采集源',exact=True).click()
        assert connected.value.ok
        page.goto(args.url + '/#models')
        page.get_by_text('登记视觉模型目录', exact=True).click()
        page.get_by_label('视觉模型显示名称',exact=True).fill('公开图像视觉工程检查')
        page.get_by_label('视觉模型目录',exact=True).fill(str(args.model.resolve()))
        with page.expect_response('**/api/vision/models/import', timeout=90000) as imported:
            page.get_by_role('button',name='校验并登记视觉模型',exact=True).click()
        assert imported.value.ok, imported.value.text()
        with page.expect_response('**/api/vision/connect', timeout=60000) as connected:
            page.get_by_role('button',name='连接／重载视觉模型',exact=True).click()
        assert connected.value.ok, connected.value.text()
        expect(page.get_by_text('已就绪',exact=True)).to_be_visible(timeout=10000)
        # Ten repeated public frames verify baseline mechanics, not scene stability or independent training.
        response = page.request.post(args.url + '/api/baseline',data={'count':10},timeout=30000)
        assert response.ok, response.text()
        baseline = page.request.get(args.url + '/api/state').json()['baseline']
        assert baseline['consistency']['confidence_mean'] is None
        page.goto(args.url + '/#monitor')
        records = []
        for index in range(5):
            expect(page.get_by_role('button',name='采样一帧',exact=True)).to_be_enabled(timeout=10000)
            page.get_by_role('button',name='采样一帧',exact=True).click()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                state = page.request.get(args.url + '/api/state').json()
                if not state['vision_runtime']['pending'] and state['latest'] and state['latest']['frame'] == 13+index: break
                time.sleep(.03)
            assert state['latest']['frame'] == 13+index, state
            records.append(state['latest']['detection'])
            if index == 3:
                assert records[-1]['status'] == 'error' and records[-1]['is_ng'] is None
                expect(page.get_by_text('姿态对齐：拒绝',exact=True)).to_be_visible(timeout=10000)
                page.locator('.toast').wait_for(state='detached')
                page.screenshot(path=str(args.output/'rejection.png'),full_page=True)
        assert records[-1]['status'] == 'ok'
        assert all(r['confidence'] is None for r in records)
        expect(page.get_by_text('本地视觉推理',exact=True)).to_be_visible()
        expect(page.get_by_text('姿态对齐：通过',exact=True)).to_be_visible()
        page.locator('.toast').wait_for(state='detached')
        page.screenshot(path=str(args.output/'desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.output/'mobile.png'),full_page=True)
        page.goto(args.url + '/#models')
        expect(page.get_by_text('已就绪',exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(args.output/'settings-mobile.png'),full_page=True)
        assert not errors, errors
        evidence = page.request.get(args.url + '/api/export').json()
        (args.output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
        if args.model_review:
            page.set_viewport_size({'width':1440,'height':1100})
            current = page.request.get(args.url + '/api/state').json()
            event = page.request.post(args.url + '/api/capture',data={'action':'bookmark'}).json()['id']
            event_url = args.url + f"/api/sessions/{current['session']}/incidents/{event}"
            frozen = page.request.get(event_url).json()['event']
            assert frozen['payload']['snapshot']['inspection_source']['kind'] == 'local_visual'
            page.goto(args.url + '/#models')
            page.get_by_label('模型名称',exact=True).select_option(args.spark_model)
            page.get_by_text('连接与运行时设置',exact=True).click()
            page.get_by_label('本地服务',exact=True).fill(args.endpoint)
            save = page.get_by_role('button',name='保存模型选择',exact=True)
            if save.is_enabled():
                save.click()
                expect(save).to_be_disabled()
            page.get_by_role('button',name='核验连接',exact=True).click()
            expect(page.get_by_text('服务可用',exact=True)).to_be_visible(timeout=15000)
            page.goto(args.url + '/#review')
            page.get_by_role('button',name='请求模型复核',exact=True).click()
            page.get_by_text('竞争解释与验证',exact=True).wait_for(timeout=180000)
            page.get_by_label('复核记录',exact=True).fill('公开图像真实视觉与语言模型推理；没有现场原因真值，记录证据不足。')
            page.get_by_role('button',name='记录人工复核',exact=True).click()
            expect(page.get_by_text('已记录：证据不足',exact=True)).to_be_visible()
            with page.expect_download() as downloaded:
                page.get_by_role('button',name='导出事件证据',exact=True).click()
            downloaded.value.save_as(args.output/'real-model-incident.json')
            bundle = json.loads((args.output/'real-model-incident.json').read_bytes())
            assert bundle['event'] == frozen and bundle['assessments'] and bundle['reviews']
            result = bundle['reviews'][-1]['payload']
            assert result['snapshot'] == frozen['payload']['snapshot']
            assert result['provenance'] == 'local_official_model' and result['inference']['runtime']['weight_sha256']
            page.locator('.toast').wait_for(state='detached')
            page.screenshot(path=str(args.output/'real-review-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(args.output/'real-review-mobile.png'),full_page=True)
        # End-of-video preserves the last observation and explicitly pauses acquisition.
        ended = page.request.post(args.url + '/api/capture',data={'action':'sample'})
        assert ended.status == 409
        assert page.request.get(args.url + '/api/state').json()['capture_error']
        # Reconnect the same local video and verify continuous processing across navigation.
        assert page.request.post(args.url + '/api/source',data={'mode':'video','video':str(video.resolve())}).ok
        assert page.request.post(args.url + '/api/baseline',data={'count':10},timeout=30000).ok
        assert page.request.post(args.url + '/api/capture',data={'action':'start'}).ok
        page.goto(args.url + '/#baseline')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = page.request.get(args.url + '/api/state').json()
            if not state['running'] and state['capture_error']: break
            time.sleep(.05)
        assert not state['running'] and state['capture_error']
        assert len(state['history']) == 5
        assert [r['detection']['status'] for r in state['history']] == ['ok','ok','ok','error','ok']
        assert page.request.delete(args.url + '/api/vision').ok
        assert page.request.get(args.url + '/api/state').json()['baseline'] is None
        assert page.request.post(args.url + '/api/source',data={'mode':'synthetic'}).ok
        assert page.request.post(args.url + '/api/baseline',data={'count':20}).ok
        report = {'scope':'Actual ResNet18/PaDiM process; generated MJPG from public images, repeated baseline frames and synthetic blank; no physical camera or factory validation',
                  'checks':['model load','visual baseline','live video frame identity','alignment rejection remains unavailable','next-frame recovery','null confidence','continuous inference across navigation','video EOF pauses capture','model switch resets baseline','desktop/390px layout'],
                  'statuses':[r['status'] for r in records],'console_errors':errors,
                  'real_spark_review':args.model_review}
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        browser.close(); print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__': main()
