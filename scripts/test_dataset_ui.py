"""Browser acceptance for dataset import, browsing and repeatable replay (synthetic only)."""

import argparse
import json
from pathlib import Path
import tempfile
import time

from playwright.sync_api import expect, sync_playwright

from create_demo_dataset import create_demo

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8501")
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/ui-replay")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="spark-replay-") as temporary, sync_playwright() as pw:
        manifest = create_demo(Path(temporary) / "dataset")
        browser = pw.chromium.launch(channel=None if args.channel == "chromium" else args.channel, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url + "/#settings")
        expect(page.get_by_role("heading", name="样本管理与回放", exact=True)).to_be_visible()
        state = page.request.get(args.url + "/api/state").json()
        assert state["source"] == "synthetic", "Use a dedicated synthetic workstation"
        page.request.post(args.url + "/api/capture", data={"action": "pause"})
        page.get_by_label("数据集清单路径", exact=True).fill(str(manifest))
        page.get_by_role("button", name="导入数据集", exact=True).click()
        expect(page.get_by_role("heading", name="PCB 合成回放示例", exact=True)).to_be_visible(timeout=30000)
        page.get_by_label("样本分组", exact=True).select_option("evaluation")
        page.get_by_label("批次筛选", exact=True).select_option("evaluation")
        page.get_by_role("button", name="下一页", exact=True).click()
        page.get_by_role("button", name="sample-020", exact=True).click()
        expect(page.get_by_role("button", name="放大样本预览", exact=True)).to_be_visible()
        page.route("**/api/datasets/*/images/21", lambda route: route.abort())
        page.get_by_role("button", name="sample-021", exact=True).click()
        expect(page.get_by_text("图像不可用，请检查文件或服务", exact=True)).to_be_visible()
        page.unroute("**/api/datasets/*/images/21")
        page.get_by_role("button", name="sample-020", exact=True).click()
        expect(page.get_by_role("button", name="放大样本预览", exact=True)).to_be_visible()
        page.get_by_role("button", name="sample-021", exact=True).click()
        expect(page.get_by_text("图像不可用，请检查文件或服务", exact=True)).to_have_count(0)
        page.wait_for_function("document.querySelector('img[alt=\"样本预览\"]')?.naturalWidth > 0")
        page.get_by_role("button", name="sample-020", exact=True).click()
        page.get_by_role("button", name="建立回放", exact=True).click()
        expect(page.get_by_test_id("replay-progress")).to_contain_text("0/30")
        page.get_by_role("button", name="回放下一帧", exact=True).click()
        expect(page.get_by_test_id("replay-progress")).to_contain_text("1/30")
        with page.expect_download() as download:
            page.get_by_role("link", name="导出回放结果", exact=True).click()
        partial = args.output / "partial.json"
        download.value.save_as(str(partial))
        assert len(json.loads(partial.read_text())["results"]) == 1
        page.get_by_role("button", name="连续回放", exact=True).click()
        page.get_by_role("button", name="暂停回放", exact=True).click()
        expect(page.get_by_role("button", name="回放下一帧", exact=True)).to_be_enabled()
        page.get_by_role("button", name="连续回放", exact=True).click()
        expect(page.get_by_test_id("replay-progress")).to_contain_text("回放完成", timeout=40000)
        expect(page.get_by_role("button", name="回放下一帧", exact=True)).to_be_disabled()
        first = page.request.get(args.url + "/api/replay/export").json()
        assert len(first["results"]) == 30 and first["replay"]["completed"]
        assert first["results"][-1]["sample"]["perturbation"] == "light_fade"
        expect(page.get_by_label("采集源", exact=True)).to_have_value("dataset")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(args.output / "desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(400)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
        page.get_by_role("button", name="建立回放", exact=True).click()
        expect(page.get_by_test_id("replay-progress")).to_contain_text("0/30")
        page.get_by_role("button", name="连续回放", exact=True).click()
        expect(page.get_by_test_id("replay-progress")).to_contain_text("回放完成", timeout=40000)
        second = page.request.get(args.url + "/api/replay/export").json()
        assert first["session"] != second["session"]
        assert first["results_sha256"] == second["results_sha256"]
        assert first["replay"]["fingerprint"] == second["replay"]["fingerprint"]
        page.get_by_label("历史回放", exact=True).select_option(first["session"])
        with page.expect_download() as download:
            page.get_by_role("link", name="导出所选回放", exact=True).click()
        historical = args.output / "historical.json"
        download.value.save_as(str(historical))
        assert json.loads(historical.read_text())["results_sha256"] == first["results_sha256"]
        assert not errors, errors
        report = {"observed": time.time(), "scope": "Synthetic dataset, no real model or camera",
                  "checks": ["import", "split/batch filters and pagination", "sample preview",
                             "image failure feedback", "step/pause/continuous/completion", "partial/historical export", "independent sessions",
                             "identical repeat result digest", "390px layout"],
                  "results_sha256": first["results_sha256"], "console_errors": errors}
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        # Return the dedicated workstation to its initial source for other acceptance suites.
        assert page.request.post(args.url + "/api/source", data={"mode": "synthetic"}).ok
        assert page.request.post(args.url + "/api/baseline", data={"count": 20}).ok
        browser.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
