"""Development-only fixed-method comparison and FP/FN hotspot evidence on observed data."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json
from src.acceptance import evaluate
from src.inspection.alignment import PoseAligner
from src.inspection.methods import METHODS, normal_roi, model_for, score_map
from src.inspection.padim import ResNetFeatures
from scripts.run_pose_study import image
from scripts.run_padim import WEIGHTS_SHA256


def implementation_digest():
    paths = ['src/acceptance.py', 'src/inspection/methods.py', 'src/inspection/padim.py',
             'src/inspection/alignment.py', 'scripts/compare_visual_methods.py']
    return hashlib.sha256(json.dumps({p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                                     for p in paths}, sort_keys=True).encode()).hexdigest()


def compare(source, evaluation_ids, output, weights, *, methods=METHODS, features=None):
    if output.exists():
        raise ValueError('Output exists; preserve comparison evidence')
    metadata = json.loads((source/'source.json').read_bytes())
    rows = metadata['files']
    if len({r['image'] for r in rows}) != len(rows):
        raise ValueError('Duplicate official identities')
    training = sorted([r for r in rows if r['split'] == 'train' and r['label'] == 'normal'], key=lambda r: r['image'])
    if not 30 <= len(training) <= 120:
        raise ValueError('Need 10..100 normal fit and 20 independent calibration images')
    fit, calibration = training[:-20], training[-20:]
    tests = [r for r in rows if r['image'] in set(evaluation_ids) and r['split'] == 'test']
    if len(tests) != len(evaluation_ids) or len(set(evaluation_ids)) != len(evaluation_ids):
        raise ValueError('Unknown or repeated evaluation identity')
    selected = training+tests
    frames = {r['image']: image(source, r) for r in selected}
    pixels = [hashlib.sha256(frames[r['image']].tobytes()).hexdigest() for r in selected]
    if len(set(pixels)) != len(pixels):
        raise ValueError('Fit/calibration/evaluation pixels overlap')
    output.mkdir(parents=True)
    features = features or ResNetFeatures(weights, WEIGHTS_SHA256)
    aligner = PoseAligner(frames[fit[0]['image']])
    aligned = {key: aligner.align(frame) for key, frame in frames.items()}
    embeddings = {}
    for mode in {'aligned' if m.startswith('aligned') else 'raw' for m in methods}:
        usable = [r for r in selected if mode == 'raw' or aligned[r['image']][0] is not None]
        embedding = {}
        for i in range(0, len(usable), 8):
            batch = usable[i:i+8]
            inputs = [frames[r['image']] if mode == 'raw' else aligned[r['image']][0] for r in batch]
            for r, e in zip(batch, features(inputs)):
                embedding[r['image']] = e
        embeddings[mode] = embedding
    report = {'schema_version': 1, 'scope': 'observed development data; never final acceptance',
              'method_source_sha256': implementation_digest(), 'source_sha256': hashlib.sha256((source/'source.json').read_bytes()).hexdigest(),
              'weights_sha256': WEIGHTS_SHA256, 'fit_ids': [r['image'] for r in fit],
              'calibration_ids': [r['image'] for r in calibration], 'variants': {}}
    for method in methods:
        model = model_for(method)
        mode = 'aligned' if method.startswith('aligned') else 'raw'
        em = embeddings[mode]
        if any(r['image'] not in em for r in training):
            report['variants'][method] = {'status': 'error', 'error': 'Normal fit/calibration alignment failed'}
            continue
        try:
            mask = normal_roi([aligned[r['image']][0] for r in fit]) if 'roi' in method else None
            model.fit(np.stack([em[r['image']] for r in fit]))
            calibration_scores = [score_map(model.predict(em[r['image']])[1], mask) for r in calibration]
            threshold = float(np.quantile(calibration_scores, .95, method='higher'))
        except (RuntimeError, ValueError, cv2.error, FloatingPointError) as exc:
            report['variants'][method] = {'status': 'error', 'error': f'Normal fit/calibration failed: {exc}'[:2000]}
            continue
        predictions, errors = [], []
        for r in tests:
            identity = r['image']; evidence = aligned[identity][1]
            prediction = {'sample_id': identity, 'group': 'unavailable' if evidence['status'] != 'passed' else
                          'rotated' if abs(evidence['angle_deg']) > 90 else 'near_reference'}
            if identity not in em:
                prediction.update(status='error', error=evidence['error'])
            else:
                started = time.perf_counter()
                try:
                    _, heat = model.predict(em[identity])
                except (RuntimeError, ValueError, cv2.error, FloatingPointError) as exc:
                    prediction.update(status='error', error=str(exc)[:2000])
                    predictions.append(prediction)
                    continue
                score = score_map(heat, mask)
                y, x = np.unravel_index(heat.argmax(), heat.shape)
                prediction.update(status='ok', anomaly_score=score, is_ng=score > threshold,
                                  score_ms=(time.perf_counter()-started)*1000,
                                  hotspot=[int(x), int(y)], hotspot_outside_roi=bool(mask is not None and not mask[y, x]))
                # Labels only classify errors after scores, never select the model input or threshold.
                label = 'defect' if r['label'] == 'anomaly' else 'normal'
                if prediction['is_ng'] != (label == 'defect'):
                    frame = frames[identity] if mode == 'raw' else aligned[identity][0]
                    colored = cv2.applyColorMap(np.clip(heat/max(threshold, 1e-12)*255, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
                    preview = cv2.addWeighted(cv2.resize(frame, (224, 224)), .5, colored, .5, 0)
                    cv2.putText(preview, f'{"FP" if label == "normal" else "FN"} {Path(identity).name}', (4, 18), cv2.FONT_HERSHEY_SIMPLEX, .45, (255,255,255), 1)
                    errors.append(preview)
            predictions.append(prediction)
        for prediction, row in zip(predictions, tests):
            prediction['label'] = 'defect' if row['label'] == 'anomaly' else 'normal'
        directory = output/method; directory.mkdir()
        if errors:
            tiles = errors[:12]
            tiles.extend([np.zeros((224,224,3), np.uint8)] * ((-len(tiles)) % 4))
            sheet = np.vstack([np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)])
            if not cv2.imwrite(str(directory/'error-hotspots.png'), sheet):
                raise OSError('Error preview write failed')
        if mask is not None:
            if not cv2.imwrite(str(directory/'normal-only-roi.png'), mask.astype(np.uint8)*255):
                raise OSError('ROI evidence write failed')
        if hasattr(model, 'save'):
            model.save(directory/'statistics.npz')
        else:
            np.savez_compressed(directory/'statistics.npz', bank=model.bank)
        report['variants'][method] = {'status': 'ok', 'threshold': threshold, 'calibration_scores': calibration_scores,
            'threshold_policy': '95th higher percentile of held-out normal calibration; no test tuning',
            'gate': evaluate(predictions, groups=('near_reference', 'rotated')),
            'error_groups': dict(Counter((r['group'] + '/' + ('unavailable' if r['status'] != 'ok' else
                         'FP' if r['is_ng'] and r['label'] == 'normal' else 'FN' if not r['is_ng'] and r['label'] == 'defect' else 'correct')) for r in predictions)),
            'predictions': predictions}
        print(json.dumps({'method': method, 'gate': report['variants'][method]['gate']['overall']}, ensure_ascii=False), flush=True)
    write_json(output/'comparison.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/public-datasets/visa-pcb1-expanded')
    parser.add_argument('--observed-manifest', type=Path, default=ROOT/'artifacts/pose-study-pcb1/manifest.json')
    parser.add_argument('--weights', type=Path, default=ROOT/'data/models/resnet18-f37072fd.pth')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.observed_manifest.read_bytes())
    compare(args.source, [s['conditions']['original_file'] for s in manifest['samples'] if s['split'] == 'evaluation'], args.output, args.weights)
