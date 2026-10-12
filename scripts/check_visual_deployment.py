"""Check sealed recipe process parity on its observed fit reference; no accuracy evaluation."""
import argparse
import json
from pathlib import Path
import sys
import math

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
from src.inspection.deployment_assets import load_asset
from src.inspection.runtime import VisionRuntime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    frame = cv2.imread(str(args.model / 'reference.png'))
    model = load_asset(args.model)
    direct = model.predict(frame)
    runtime = VisionRuntime(args.model, 5.)
    try:
        result = runtime.infer(frame)
        prediction = result.metadata['result']
        assert direct['status'] == 'ok' and result.status == 'ok'
        assert runtime.id == model.id and math.isclose(direct['anomaly_score'], prediction['anomaly_score'], rel_tol=1e-6)
        assert direct['is_ng'] == prediction['is_ng'] and result.confidence is None
        report = {'scope': 'deployment/process parity on observed fit reference; no final data or accuracy estimate',
                  'model_id': model.id, 'recipe': model.recipe, 'direct': direct, 'process': prediction}
        with args.output.open('x', encoding='utf-8') as output: json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
    finally: runtime.close()

if __name__ == '__main__': main()
