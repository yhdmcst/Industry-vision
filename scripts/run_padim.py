"""Opt-in PaDiM raw/aligned ablation on verified VisA images; exports real result packages.

Predict on the exact immutable workstation pixels. Fit and threshold calibration use
disjoint official normal train files; no test labels select alignment or parameters.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json
from src.datasets import DatasetStore, digest
from src.inspection.alignment import PoseAligner
from src.inspection.padim import PaDiM, ResNetFeatures
from src.inspection.results import ResultPackage
from scripts.benchmark_public_data import auroc

WEIGHTS_SHA256 = 'f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec'


def metrics(predictions):
    labeled = [r for r in predictions if r['label'] in ('normal', 'defect')]
    valid = [r for r in labeled if r['status'] == 'ok']
    tp = sum(r['is_ng'] and r['label'] == 'defect' for r in valid)
    tn = sum(not r['is_ng'] and r['label'] == 'normal' for r in valid)
    fp = sum(r['is_ng'] and r['label'] == 'normal' for r in valid)
    fn = sum(not r['is_ng'] and r['label'] == 'defect' for r in valid)
    return {'planned': len(predictions), 'assessed': len(valid), 'unavailable_labeled': len(labeled) - len(valid),
            'tp': int(tp), 'tn': int(tn), 'fp': int(fp), 'fn': int(fn),
            'image_auroc': auroc([r['label'] == 'defect' for r in valid], [r['anomaly_score'] for r in valid]) if valid else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'false_positive_rate': fp / (fp + tn) if fp + tn else None}


def run(manifest_path: Path, source: Path, weights: Path, output: Path, features=None):
    if output.exists():
        raise ValueError('Output exists; use a new directory to preserve evidence')
    metadata = json.loads((source / 'source.json').read_bytes())
    records = metadata['files']
    if len({r['image'] for r in records}) != len(records):
        raise ValueError('Duplicate official source file identities')
    normal_train = sorted([r for r in records if r['split'] == 'train' and r['label'] == 'normal'], key=lambda r: r['image'])
    if len(normal_train) < 30:
        raise ValueError('At least 30 official normal training images required')
    fit_rows, calibration_rows = normal_train[:-20], normal_train[-20:]
    if len({r['sha256'] for r in normal_train}) != len(normal_train):
        raise ValueError('Duplicate normal fit/calibration images cannot be independent calibration')
    originals = {}
    for row in records:
        path = (source / row['image']).resolve()
        if not path.is_relative_to(source.resolve()):
            raise ValueError('Source path escapes source root')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row['sha256']:
            raise ValueError('Source image digest mismatch')
        frame = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError('Source image decode failed')
        originals[row['image']] = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)
    train_pixel_hashes = [hashlib.sha256(originals[r['image']].tobytes()).hexdigest() for r in normal_train]
    if len(set(train_pixel_hashes)) != len(train_pixel_hashes):
        raise ValueError('Normal fit/calibration partitions contain duplicate normalized pixels')
    calibration = [originals[r['image']] for r in calibration_rows]
    features = features or ResNetFeatures(weights, WEIGHTS_SHA256)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.padim-', dir=output.parent) as temporary:
        root = Path(temporary) / 'experiment'
        root.mkdir()
        store = DatasetStore(root / 'datasets')
        imported = store.import_manifest(manifest_path)
        manifest = store.load(imported['id'])
        references = [s for s in manifest['samples'] if s['split'] == 'baseline']
        samples = [s for s in manifest['samples'] if s['split'] == 'evaluation']
        expected = {r['image'] for r in fit_rows}
        if {s['conditions'].get('original_file') for s in references} != expected or len(references) != len(fit_rows):
            raise ValueError('Dataset baseline must exactly match fixed normal fit partition')
        if any(s['conditions'].get('original_file') not in {r['image'] for r in records if r['split'] == 'test'} for s in samples):
            raise ValueError('Evaluation samples must retain official test file identities')
        frames = [store.image(imported['id'], s) for s in references + samples]
        if any(not np.array_equal(frame, originals[s['conditions']['original_file']]) for frame, s in zip(frames, references + samples)):
            raise ValueError('Dataset pixels do not match verified official source images')
        aligner = PoseAligner(frames[0])
        aligned = [aligner.align(f) for f in frames + calibration]
        report = {'dataset_id': imported['id'], 'source_sha256': hashlib.sha256((source / 'source.json').read_bytes()).hexdigest(),
                  'method': 'PaDiM ResNet18 ImageNet V1; full spatial covariance, independently implemented',
                  'method_source_sha256': digest({p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in
                                                 ['src/inspection/padim.py', 'src/inspection/alignment.py', 'scripts/run_padim.py']}),
                  'weights_sha256': WEIGHTS_SHA256, 'platform': platform.platform(),
                  'parameters': {'resize': [224, 224], 'channels': 100, 'channel_seed': 0, 'covariance_regularization': .01,
                                 'smooth_sigma': 4, 'image_score': 'max smoothed Mahalanobis map', 'alignment': aligner.policy},
                  'fit_ids': [r['image'] for r in fit_rows], 'calibration_ids': [r['image'] for r in calibration_rows],
                  'alignment_reference': references[0]['id'], 'variants': {},
                  'limitations': ['Fixed PCB1 subset, not factory validation or full VisA', 'ImageNet features, no new foundation model',
                                  'No masks or segmentation accuracy', 'Anomaly scores are not calibrated confidence',
                                  'Raw image drift remains independent of detector alignment', 'No Spark inference or fault cause labels']}
        from importlib.metadata import version
        report['software'] = {name: version(name) for name in ('numpy', 'scipy', 'opencv-python-headless')}
        if isinstance(features, ResNetFeatures):
            report['software'].update({name: version(name) for name in ('torch', 'torchvision')})
        for mode in ('raw', 'aligned'):
            begin = time.perf_counter()
            directory = root / mode
            directory.mkdir()
            mode_frames = frames + calibration if mode == 'raw' else [item[0] for item in aligned]
            # Failed fit or calibration cannot silently change training data, threshold or baseline.
            if any(f is None for f in mode_frames[:len(references)]) or any(f is None for f in mode_frames[len(frames):]):
                report['variants'][mode] = {'status': 'error', 'error': 'Fit or calibration alignment rejected; no package published',
                                            'alignment': [item[1] for item in aligned]}
                continue
            normal_embeddings = np.concatenate([features(mode_frames[i:min(i+8, len(references))])
                                                for i in range(0, len(references), 8)])
            model = PaDiM()
            model.fit(normal_embeddings)
            calibration_embeddings = np.concatenate([features(mode_frames[len(frames)+i:len(frames)+i+8]) for i in range(0, len(calibration), 8)])
            calibration_scores = [model.predict(e)[0] for e in calibration_embeddings]
            threshold = float(np.quantile(calibration_scores, .95, method='higher'))
            results = []
            for index, (sample, frame) in enumerate(zip(references + samples, mode_frames[:len(frames)])):
                alignment = aligned[index][1] if mode == 'aligned' else {'status': 'disabled', 'inliers': 0, 'error': ''}
                result = {'sample_id': sample['id'], 'image_sha256': sample['sha256'], 'alignment': alignment}
                if frame is None:
                    result.update(status='error', error=alignment['error'])
                else:
                    started = time.perf_counter()
                    try:
                        score, anomaly_map = model.predict(features([frame])[0])
                    except (RuntimeError, ValueError, cv2.error, FloatingPointError) as exc:
                        result.update(status='error', error=f'视觉推理失败：{type(exc).__name__}: {exc}'[:2000])
                        results.append(result)
                        continue
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    result.update(status='ok', detected=True, confidence=None, anomaly_score=score, is_ng=score > threshold, defect_types=[])
                    # Visualization scale is the fixed normal calibration threshold, not test extrema.
                    heat = cv2.applyColorMap(np.clip(anomaly_map / max(threshold, 1e-12) * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
                    preview = cv2.addWeighted(cv2.resize(frame, (224, 224)), .5, heat, .5, 0)
                    if not cv2.imwrite(str(directory / f'{index:04d}-heatmap.png'), preview):
                        raise OSError('Failed to save anomaly heatmap')
                    result['elapsed_ms'] = elapsed_ms
                results.append(result)
            identity = {'method': report['method_source_sha256'], 'weights': WEIGHTS_SHA256, 'mode': mode,
                        'dataset_id': imported['id'], 'calibration_scores': calibration_scores, 'threshold': threshold}
            package = ResultPackage.model_validate({'schema_version': 2, 'dataset_id': imported['id'],
                       'producer': {'name': 'PaDiM ResNet18', 'version': mode + '-' + digest(identity), 'provenance': 'upstream',
                                    'score_semantics': 'anomaly_score', 'decision_threshold': threshold},
                       'results': [{k: v for k, v in r.items() if k != 'elapsed_ms'} for r in results]}).model_dump()
            write_json(directory / 'inspection-results.json', package)
            model.save(directory / 'normal-model.npz')
            # Attach independent test labels only after every score and threshold is fixed.
            evaluated = [{**r, 'label': s['label']['defect'], 'pose_group':
                          'unavailable' if aligned[i+len(references)][1]['status'] != 'passed' else
                          'rotated' if abs(aligned[i+len(references)][1]['angle_deg']) > 90 else 'near_reference'}
                         for i, (r, s) in enumerate(zip(results[len(references):], samples))]
            valid_times = [r['elapsed_ms'] for r in results[len(references):] if r['status'] == 'ok']
            report['variants'][mode] = {'status': 'ok', 'threshold': threshold, 'calibration_scores': calibration_scores,
                    'threshold_policy': '95th percentile (higher) of 20 held-out normal train scores; fixed before test',
                    'alignment_counts': dict(Counter(r['alignment']['status'] for r in results)),
                    'metrics': metrics(evaluated), 'pose_groups': {group: metrics([r for r in evaluated if r['pose_group'] == group])
                                                               for group in ('near_reference', 'rotated', 'unavailable')},
                    'prediction_ms_p50': float(np.median(valid_times)) if valid_times else None,
                    'prediction_timing_scope': 'CPU feature extraction and anomaly scoring; excludes alignment, decode, training and visualization I/O',
                    'experiment_seconds': time.perf_counter() - begin, 'predictions': evaluated}
            print(json.dumps({'variant': mode, 'metrics': report['variants'][mode]['metrics']}, ensure_ascii=False), flush=True)
        write_json(root / 'experiment.json', report)
        write_json(root / 'import.json', imported)
        if output.exists():
            raise ValueError('Output appeared during experiment; preserve evidence')
        root.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'artifacts/public-data-visa-pcb1-final/manifest.json')
    parser.add_argument('--source', type=Path, default=ROOT / 'data/public-datasets/visa-pcb1')
    parser.add_argument('--weights', type=Path, default=ROOT / 'data/models/resnet18-f37072fd.pth')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/padim-visa-pcb1')
    args = parser.parse_args()
    run(args.manifest, args.source, args.weights, args.output)


if __name__ == '__main__':
    main()
