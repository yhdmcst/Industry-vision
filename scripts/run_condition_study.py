"""Fixed detector evaluation of declared imaging conditions; controlled and real domains stay separate."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json
from src.datasets import DatasetStore
from src.inspection.vision_model import VisionModel
from src.monitoring import DetectionRecord, DriftDetector
from scripts.run_padim import metrics

CONDITIONS = ('original', 'dim_70', 'bright_130', 'blur_5', 'shift_12')


def transform(frame, condition):
    if condition == 'original': return frame.copy()
    if condition in ('dim_70', 'bright_130'):
        return np.clip(frame.astype(np.float32) * (.7 if condition == 'dim_70' else 1.3), 0, 255).astype(np.uint8)
    if condition == 'blur_5': return cv2.GaussianBlur(frame, (5, 5), 0)
    if condition == 'shift_12':
        return cv2.warpAffine(frame, np.float32([[1, 0, 12], [0, 1, 0]]), (640, 480), borderMode=cv2.BORDER_REFLECT_101)
    raise ValueError('Unknown fixed condition')


def study(model_root, manifest, output, model=None):
    if output.exists(): raise ValueError('Output exists; preserve measurements')
    model = model or VisionModel(model_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.condition-study-', dir=output.parent) as temporary:
        root = Path(temporary) / 'study'; root.mkdir()
        store = DatasetStore(Path(temporary) / 'datasets')
        imported = store.import_manifest(manifest)
        declared = store.load(imported['id'])
        references = [s for s in declared['samples'] if s['split'] == 'baseline']
        samples = [s for s in declared['samples'] if s['split'] == 'evaluation']
        if imported['id'] != model.recipe['dataset_id']:
            raise ValueError('Controlled study must use the exact detector dataset')
        normal_frames = [store.image(imported['id'], s) for s in references]
        baseline_records = []
        for frame in normal_frames:
            prediction = model.predict(frame)
            if prediction['status'] != 'ok': raise ValueError('Baseline prediction unavailable')
            baseline_records.append(record(model, prediction))
        report = {'schema_version': 1, 'model_id': model.id, 'dataset_id': imported['id'],
                  'scope': 'Real VisA originals; paired software transformations, not real imaging-domain changes',
                  'policy': 'Frozen fit/calibration/threshold and condition recipes; labels attached after predictions',
                  'conditions': {}, 'limitations': ['Dependent transformed views do not increase independent sample count',
                      'Brightness scaling is not physical exposure control; blur and shift are software proxies',
                      'Ordered replay is not a camera time series; alert counts are replay episodes, not hourly rates',
                      'No AeBAD or MVTec AD 2 images in this controlled study']}
        predictions = {}
        for condition in CONDITIONS:
            detector = DriftDetector()
            detector.set_baseline(normal_frames, baseline_records)
            rows = []
            for index, sample in enumerate(samples):
                frame = transform(store.image(imported['id'], sample), condition)
                try:
                    prediction = model.predict(frame)
                except (RuntimeError, ValueError, cv2.error, FloatingPointError) as exc:
                    prediction = {'status': 'error', 'error': str(exc)[:2000]}
                observation = detector.analyze(frame, record(model, prediction))
                rows.append({**prediction, 'sample_id': sample['id'], 'root_image_sha256': sample['sha256'],
                             'input_sha256': hashlib.sha256(frame.tobytes()).hexdigest(),
                             'input_kind': 'real_original' if condition == 'original' else 'controlled_transform',
                             'rule_change': observation.drift_detected, 'rule_type': observation.drift_type.value,
                             'image_issues': [r['type'] for r in observation.metrics['image_drift']['issues']],
                             'detection_window_ready': observation.metrics['detection_availability']['ready']})
            predictions[condition] = rows
        # Only now join independent annotations, after all conditions were predicted.
        labels = {s['id']: s['label']['defect'] for s in samples}
        for condition, rows in predictions.items():
            for row in rows: row['label'] = labels[row['sample_id']]
            normal = [r for r in rows if r['label'] == 'normal']
            defects = [r for r in rows if r['label'] == 'defect']
            report['conditions'][condition] = {'metrics': metrics(rows),
                'unavailable_normal': sum(r['status'] != 'ok' for r in normal),
                'unavailable_defect': sum(r['status'] != 'ok' for r in defects),
                'detection_coverage': sum(r['status'] == 'ok' for r in rows) / len(rows),
                'defect_found_over_all_labeled_defects': sum(r.get('is_ng') is True for r in defects) / len(defects) if defects else None,
                'normal_image_rule_count': sum(bool(r['image_issues']) for r in normal),
                'normal_rule_change_count': sum(r['rule_change'] for r in normal),
                'image_issues': dict(Counter(issue for r in rows for issue in r['image_issues'])),
                'verdict_flips_from_original': sum(a.get('is_ng') != b.get('is_ng') for a,b in zip(predictions['original'], rows)
                    if a['status'] == b['status'] == 'ok'), 'predictions': rows}
        write_json(root / 'condition-study.json', report)
        if output.exists(): raise ValueError('Output appeared during study')
        root.rename(output)
    print(json.dumps({k:{key:value for key,value in v.items() if key != 'predictions'} for k,v in report['conditions'].items()}, ensure_ascii=False), flush=True)
    return report


def record(model, prediction):
    return DetectionRecord(0., prediction.get('detected'), prediction.get('confidence'), prediction.get('is_ng'),
                           {'producer': model.producer, 'result': prediction}, status=prediction['status'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'artifacts/pose-study-pcb1/manifest.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); study(args.model, args.manifest, args.output)
