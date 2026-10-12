"""Create an explicitly synthetic dataset for exercising import and replay."""

import argparse
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.inspection.camera import DummyCamera


def create_demo(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=False)
    camera = DummyCamera()
    camera.open()
    _, reference = camera.read()
    camera.close()
    samples = []
    for index in range(40):
        image = reference.copy()
        perturbation, cause = "none", "none"
        if 20 <= index < 30:
            image = cv2.GaussianBlur(image, (31, 31), 8)
            perturbation, cause = "focus_change", "optical"
        elif index >= 30:
            image = cv2.convertScaleAbs(image, alpha=0.5)
            perturbation, cause = "light_fade", "illumination"
        filename = f"sample-{index:03d}.png"
        if not cv2.imwrite(str(output / filename), image):
            raise RuntimeError("Cannot write demo image")
        samples.append({
            "id": f"sample-{index:03d}", "batch": "reference" if index < 10 else "evaluation",
            "path": filename, "split": "baseline" if index < 10 else "evaluation",
            "origin": "synthetic", "perturbation": perturbation,
            "conditions": {"fixture": "DummyCamera PCB", "capture": "generated bitmap"},
            "label": {"defect": "unknown", "cause": cause,
                      "note": "合成场景标签，仅验证工程流程，不构成真实缺陷标注。"},
        })
    path = output / "manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "name": "PCB 合成回放示例",
                               "description": "10 个基线，30 个评估：正常、失焦、光照衰减。",
                               "samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/demo-dataset")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new directory to preserve existing samples")
    print(create_demo(args.output).resolve())
