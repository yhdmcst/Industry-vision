"""Isolated synthetic browser checks for model operation UX; no model calls or camera."""

import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.storage import EvidenceStore
from src.workspace import restore_workspace
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--channel', default='chrome', help='Installed chrome or msedge browser')
    parser.add_argument('--vision-model', type=Path, help='Optional real frozen recipe: verify registration/loading only, no effect experiment')
    parser.add_argument('--release-protocol', type=Path, help='Optional intact research protocol; checks controlled deployment without final evaluation')
    parser.add_argument('--visual-weights', type=Path, default=ROOT / 'data/models/resnet18-f37072fd.pth')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    errors = []
    with tempfile.TemporaryDirectory(prefix='spark-operations-ui-') as temporary:
        store = EvidenceStore(Path(temporary) / 'evidence.db')
        store.append('old-browser-fixture', 'incident', 1, {'frame': 1, 'source': 'synthetic', 'injected': False, 'baseline_generation': 1,
            'trigger': 'operator_bookmark', 'rule_report': {'drift_type': 'unknown'}})
        with (args.output / 'api.log').open('wb') as log:
            server = subprocess.Popen([sys.executable, '-c',
                'import sys; from pathlib import Path; import uvicorn; from src.api.app import create_app; '
                'uvicorn.run(create_app(Path(sys.argv[1])),host="127.0.0.1",port=int(sys.argv[2]),log_level="warning",access_log=False)',
                str(Path(temporary) / 'evidence.db'), str(port)], cwd=ROOT, stdout=log, stderr=log)
            try:
                with httpx.Client(trust_env=False, timeout=1) as client:
                    for _ in range(150):
                        if server.poll() is not None: raise RuntimeError('Isolated API exited')
                        try:
                            if client.get(url + '/api/health').is_success: break
                        except httpx.HTTPError: pass
                        time.sleep(.2)
                    else: raise RuntimeError('Isolated API did not start')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel=args.channel, headless=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(url)
                    page.get_by_role('button', name='标记待复核', exact=True).click()
                    expect(page.locator('.mini-events button').first).to_be_visible()
                    page.locator('.mini-events button').first.click()
                    expect(page.get_by_role('heading', name='人工结论', exact=True)).to_be_visible()
                    draft = page.get_by_placeholder('记录检查方法、观察结果与仍缺少的证据。')
                    draft.fill('未保存草稿：核查光源')
                    page.get_by_placeholder('例如：近期调整过光源，曝光参数尚未检查。').fill('独立补充记录')
                    page.wait_for_timeout(1800)
                    expect(draft).to_have_value('未保存草稿：核查光源')
                    page.get_by_label('同步缩放', exact=True).fill('2')
                    assert page.locator('.image-comparison img').count() == 2
                    assert all('scale(2)' in value for value in page.locator('.image-comparison img').evaluate_all('(images) => images.map(img => img.style.transform)'))
                    page.goto(url + '/#monitor')
                    expect(page.get_by_role('heading', name='监测工作台', exact=True)).to_be_visible()
                    page.get_by_role('button', name='标记待复核', exact=True).click()
                    expect(page.locator('.mini-events button')).to_have_count(2)
                    page.locator('.mini-events button').first.click()
                    expect(draft).to_have_value('')
                    page.locator('.event-card').last.click()
                    expect(draft).to_have_value('未保存草稿：核查光源')
                    page.reload()
                    expect(draft).to_have_value('未保存草稿：核查光源')
                    page.get_by_role('button', name='记录人工复核', exact=True).click()
                    expect(page.get_by_text('已记录：证据不足', exact=True)).to_be_visible()
                    page.get_by_role('button', name='清空此事件草稿', exact=True).click()
                    expect(draft).to_have_value('')
                    for width, label in [(1440, 'desktop'), (390, 'mobile')]:
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.evaluate('window.scrollTo(0, 0)')
                        page.wait_for_timeout(300)
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        page.screenshot(path=str(args.output / f'review-{label}.png'), full_page=True, animations='disabled')
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    # Controlled queue fixtures; no fabricated predictions or quality metrics.
                    live = page.request.get(url + '/api/state').json()['session']
                    frozen = page.request.get(url + f'/api/sessions/{live}/incidents').json()[0]
                    payload = page.request.get(url + f'/api/sessions/{live}/incidents/{frozen["id"]}').json()['event']['payload']
                    store.append_many(live, [('incident', time.time(), payload) for _ in range(55)])
                    expect(page.get_by_role('button', name='下一页', exact=True)).to_be_enabled(timeout=15000)
                    page.get_by_role('button', name='下一页', exact=True).click()
                    expect(page.get_by_text('第 2 页 · 7 条', exact=True)).to_be_visible()
                    page.get_by_role('button', name='上一页', exact=True).click()
                    expect(page.get_by_text('第 1 页 · 50 条', exact=True)).to_be_visible()
                    page.get_by_role('button', name='已记录', exact=True).click()
                    expect(page.locator('.event-card')).to_have_count(1)
                    page.get_by_role('button', name='全部', exact=True).click()
                    page.goto(url + '/#models')
                    expect(page.get_by_role('heading', name='本地模型', exact=True)).to_be_visible()
                    expect(page.get_by_label('模型状态概览')).to_be_visible()
                    expect(page.get_by_text('最近文件检查', exact=True)).to_be_visible()
                    expect(page.get_by_text('周期连接探测', exact=True)).to_be_visible()
                    expect(page.get_by_role('button', name='重启服务', exact=True)).to_be_disabled()
                    page.get_by_text('连接与运行时设置', exact=True).click()
                    page.get_by_label('本地服务', exact=True).fill('http://example.org:11435')
                    page.get_by_role('button', name='保存模型选择', exact=True).click()
                    expect(page.get_by_role('alert').filter(has_text='服务地址须为本机 HTTP 地址')).to_be_visible()
                    page.get_by_label('本地服务', exact=True).fill('http://127.0.0.1:11435')
                    page.get_by_role('button', name='关闭错误', exact=True).click()
                    page.get_by_role('button', name='检查部署条件', exact=True).click()
                    page.get_by_text('最近操作记录', exact=True).click()
                    records = page.locator('.panel').filter(has=page.get_by_role('heading', name='维护详情', exact=True)).locator('.operation-record')
                    expect(records.first).to_contain_text('部署检查')
                    expect(records.first).to_contain_text('已完成', timeout=30000)
                    page.reload()
                    page.get_by_text('最近操作记录', exact=True).click()
                    expect(records.first).to_contain_text('已完成')
                    expect(page.get_by_label('复核模型资产')).to_contain_text('Spark-X2.5-1.7B')
                    expect(page.get_by_label('复核模型资产')).to_contain_text('Spark-X2.5-4B')
                    page.get_by_text('登记视觉模型目录', exact=True).click()
                    page.get_by_label('视觉模型显示名称', exact=True).fill('无效目录功能检查')
                    page.get_by_label('视觉模型目录', exact=True).fill(str(Path(temporary) / 'missing'))
                    page.get_by_role('button', name='校验并登记视觉模型', exact=True).click()
                    expect(page.get_by_role('alert').filter(has_text='视觉模型登记失败')).to_be_visible()
                    if args.vision_model:
                        initial = page.request.get(url + '/api/state').json()['baseline_generation']
                        page.get_by_label('视觉模型显示名称', exact=True).fill('公开配方工程检查')
                        page.get_by_label('视觉模型目录', exact=True).fill(str(args.vision_model.resolve()))
                        page.get_by_role('button', name='校验并登记视觉模型', exact=True).click()
                        expect(page.get_by_label('已登记视觉模型')).to_contain_text('公开配方工程检查', timeout=90000)
                        assert page.request.get(url + '/api/state').json()['baseline_generation'] == initial
                        page.get_by_label('单帧推理时限', exact=True).fill('1.5')
                        page.get_by_role('button', name='连接／重载视觉模型', exact=True).click()
                        expect(page.get_by_text('已就绪', exact=True)).to_be_visible(timeout=90000)
                        assert page.request.get(url + '/api/state').json()['baseline'] is None
                        page.reload()
                        expect(page.get_by_label('单帧推理时限', exact=True)).to_have_value('1.5')
                        page.get_by_role('button', name='停用视觉模型，切回演示检测', exact=True).click()
                        expect(page.get_by_role('button', name='恢复最近保存的视觉配置', exact=True)).to_be_enabled()
                        page.get_by_role('button', name='恢复最近保存的视觉配置', exact=True).click()
                        expect(page.get_by_text('已就绪', exact=True)).to_be_visible(timeout=90000)
                        assert page.request.get(url + '/api/state').json()['vision_runtime']['timeout_seconds'] == 1.5
                        page.get_by_role('button', name='停用视觉模型，切回演示检测', exact=True).click()
                        expect(page.get_by_text('未连接', exact=True).last).to_be_visible()
                        page.get_by_text('修复与卸载所选视觉版本', exact=True).click()
                        page.get_by_label('同版本修复配方目录', exact=True).fill(str(args.vision_model.resolve()))
                        model_id = page.get_by_label('已登记视觉模型', exact=True).input_value()
                        managed = Path(temporary) / ('evidence.db-vision-models') / model_id / 'reference.png'
                        managed.write_bytes(b'controlled corruption; source recipe stays intact')
                        page.get_by_role('button', name='刷新视觉资产', exact=True).click()
                        expect(page.get_by_text('文件变化', exact=False)).to_be_visible()
                        page.get_by_role('button', name='校验并修复此版本', exact=True).click()
                        expect(page.get_by_text('视觉资产已按原身份修复', exact=False)).to_be_visible()
                        page.get_by_role('button', name='预览卸载此版本', exact=True).click()
                        expect(page.get_by_role('button', name='确认移至回收区', exact=True)).to_be_enabled()
                        page.get_by_role('button', name='确认移至回收区', exact=True).click()
                        page.get_by_text('视觉版本回收区 · 1', exact=True).click()
                        page.get_by_role('button', name='恢复此视觉版本', exact=True).click()
                        expect(page.get_by_text('视觉版本已恢复到可选目录，尚未加载。', exact=True)).to_be_visible()
                    if args.release_protocol:
                        page.get_by_text('从研发封存协议登记', exact=True).click()
                        page.get_by_label('封存模型显示名称', exact=True).fill('PCB4 封存部署工程检查')
                        page.get_by_label('研发封存协议目录', exact=True).fill(str(args.release_protocol.resolve()))
                        page.get_by_label('官方视觉权重文件', exact=True).fill(str(args.visual_weights.resolve()))
                        page.get_by_role('button', name='校验封存协议并登记', exact=True).click()
                        expect(page.get_by_label('已登记视觉模型', exact=True)).to_contain_text('PCB4 封存部署工程检查', timeout=90000)
                        page.get_by_role('button', name='连接／重载视觉模型', exact=True).click()
                        expect(page.get_by_text('已就绪', exact=True)).to_be_visible(timeout=90000)
                        page.get_by_role('button', name='停用视觉模型，切回演示检测', exact=True).click()
                    expect(page.get_by_role('heading', name='环境与部署帮助', exact=True)).to_be_visible()
                    with page.expect_download() as diagnostic:
                        page.get_by_role('link', name='下载工作台诊断包', exact=True).click()
                    diagnostic.value.save_as(args.output / 'diagnostics.json')
                    assert json.loads((args.output / 'diagnostics.json').read_bytes())['format'] == 'spark-workstation-diagnostics-v1'
                    subprocess.run([sys.executable, str(ROOT / 'scripts/diagnose_workstation.py'), '--endpoint', url,
                        '--output', str(args.output / 'terminal-diagnostics.json')], check=True, cwd=ROOT)
                    for width, label in [(1440, 'desktop'), (390, 'mobile')]:
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.evaluate('window.scrollTo(0, 0)')
                        page.wait_for_timeout(300)
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        page.screenshot(path=str(args.output / f'model-{label}.png'), full_page=True, animations='disabled')
                    page.set_viewport_size({'width': 1440, 'height': 1000})
                    page.goto(url + '/#settings')
                    page.get_by_label('采集源', exact=True).select_option('video')
                    page.get_by_role('button', name='浏览本机文件', exact=True).first.click()
                    expect(page.get_by_label('本地视频路径路径选择')).to_contain_text(str(ROOT))
                    page.get_by_role('button', name='关闭路径选择', exact=True).click()
                    expect(page.get_by_role('heading', name='证据存储与备份', exact=True)).to_be_visible()
                    with page.expect_download() as download:
                        page.get_by_role('button', name='下载会话证据备份', exact=True).click()
                    download.value.save_as(args.output / 'evidence.sqlite')
                    assert (args.output / 'evidence.sqlite').read_bytes().startswith(b'SQLite format 3')
                    with page.expect_download() as download:
                        page.get_by_role('button', name='下载工作空间备份', exact=True).click()
                    download.value.save_as(args.output / 'workspace.zip')
                    restored = restore_workspace(args.output / 'workspace.zip', args.output / 'restored-workspace')
                    assert EvidenceStore(restored['database']).count('old-browser-fixture') == 1
                    page.get_by_text('旧会话归档与空间管理', exact=True).click()
                    page.get_by_label('保留会话数', exact=True).fill('1')
                    page.get_by_role('button', name='预览保留范围', exact=True).click()
                    expect(page.get_by_text('将归档 1 个会话', exact=False)).to_be_visible()
                    page.get_by_role('button', name='确认归档并释放旧会话', exact=True).click()
                    expect(page.get_by_text('下载归档 ·', exact=False)).to_be_visible()
                    page.get_by_role('button', name='回收数据库未使用空间', exact=True).click()
                    expect(page.get_by_text('活动数据库未使用空间已回收，原记录保留。', exact=True)).to_be_visible()
                    page.route('**/api/state*', lambda route: route.abort())
                    expect(page.get_by_role('alert').filter(has_text='当前数据显示可能已过期')).to_be_visible(timeout=15000)
                    page.unroute('**/api/state*')
                    expect(page.get_by_role('alert').filter(has_text='当前数据显示可能已过期')).to_have_count(0, timeout=15000)
                    browser.close()
                assert not errors, errors
                (args.output / 'report.json').write_text(json.dumps({'data': 'synthetic',
                    'model_calls': False, 'real_visual_recipe_loaded': bool(args.vision_model), 'research_release_loaded': bool(args.release_protocol), 'page_errors': errors, 'checks': ['status provenance',
                    'event drafts survive polling/navigation/reload and remain isolated', 'synchronized image zoom', 'local path navigation',
                    'external service controls disabled', 'invalid configuration preserved',
                    'desktop and 390px layout', 'operation result survives reload', 'SQLite backup download',
                    'offline and recovery with incremental polling', 'per-model asset status', 'visual registry error feedback',
                    'server pagination and assessment filter', 'workspace download and restoration',
                    'retention preview and verified archive', 'database compaction', 'shared terminal/page diagnostics',
                    'same-version visual repair and recycle/restore when requested',
                    'controlled sealed release registration/loading when requested']}, ensure_ascii=False, indent=2))
                print('Model operation browser checks passed')
            finally:
                server.terminate()
                try: server.wait(40)
                except subprocess.TimeoutExpired: server.kill(); server.wait(10)


if __name__ == '__main__': main()
