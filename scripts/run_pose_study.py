"""Exclude previously observed VisA tests and audit pose with fixed paired 180-degree transforms.

Derived rotations remain controlled transformations, never new independent real samples.
All detector recipes and thresholds are fixed before independent labels are attached.
"""

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
from src.inspection.alignment import PoseAligner
from src.inspection.padim import PaDiM, ResNetFeatures
from scripts.run_padim import run, metrics, WEIGHTS_SHA256


def image(source, row):
    path = (source / row['image']).resolve()
    if not path.is_relative_to(source.resolve()):
        raise ValueError('Source path escapes dataset root')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != row['sha256']:
        raise ValueError('Source digest mismatch')
    frame = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError('Cannot decode source image')
    return cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)


def unseen_rows(rows, observed):
    if len({r['image'] for r in rows}) != len(rows):
        raise ValueError('Duplicate source identity')
    excluded = {s['conditions']['original_file'] for s in observed['samples'] if s['split'] == 'evaluation'}
    available = {r['image'] for r in rows if r['split'] == 'test'}
    if not excluded or not excluded <= available:
        raise ValueError('Observed evaluation identities must be present in the expanded source')
    selected = sorted([r for r in rows if r['split'] == 'test' and r['image'] not in excluded], key=lambda r: r['image'])
    if {r['label'] for r in selected} != {'normal', 'anomaly'}:
        raise ValueError('Fresh evaluation must contain both official classes')
    return selected, sorted(excluded)


def pose_groups(predictions):
    groups = {}
    for group in ('near_reference', 'rotated', 'unavailable'):
        rows = [r for r in predictions if r['pose_group'] == group]
        groups[group] = {**metrics(rows), 'labels': dict(Counter(r['label'] for r in rows))}
    return groups


def study(source, observed_manifest, weights, output, features=None):
    if output.exists():
        raise ValueError('Output exists; preserve evidence')
    metadata = json.loads((source / 'source.json').read_bytes())
    observed = json.loads(observed_manifest.read_bytes())
    rows = metadata['files']
    evaluations, excluded = unseen_rows(rows, observed)
    training = sorted([r for r in rows if r['split'] == 'train' and r['label'] == 'normal'], key=lambda r: r['image'])
    references = training[:-20]
    if not 10 <= len(references) <= 100:
        raise ValueError('Need 10..100 fit images and 20 held-out normal calibration images')
    # Excluding file identities alone is insufficient: exclude identical normalized pixels too.
    frames = {r['image']: image(source, r) for r in rows}
    hashes = {key: hashlib.sha256(frame.tobytes()).hexdigest() for key, frame in frames.items()}
    forbidden = {hashes[key] for key in excluded} | {hashes[r['image']] for r in training}
    fresh_hashes = [hashes[r['image']] for r in evaluations]
    if len(set(fresh_hashes)) != len(fresh_hashes) or forbidden.intersection(fresh_hashes):
        raise ValueError('Fresh evaluation duplicates observed or training pixels')
    features = features or ResNetFeatures(weights, WEIGHTS_SHA256)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pose-study-', dir=output.parent) as temporary:
        root = Path(temporary) / 'study'; root.mkdir()
        samples = []
        for index, row in enumerate(references + evaluations):
            path = f'images/{index:04d}.png'
            (root / 'images').mkdir(exist_ok=True)
            if not cv2.imwrite(str(root / path), frames[row['image']]):
                raise OSError('Cannot save study pixels')
            samples.append({'id': f'visa-fresh-{index:04d}', 'path': path,
                'split': 'baseline' if row in references else 'evaluation', 'origin': 'real',
                'batch': f'VisA {metadata.get("category", "pcb1")} official {row["split"]}',
                'conditions': {'original_file': row['image'], 'dataset': 'VisA',
                               'license': metadata.get('license', 'unknown')},
                'label': {'defect': 'defect' if row['label'] == 'anomaly' else 'normal', 'cause': 'unknown'}})
        write_json(root / 'manifest.json', {'schema_version': 1, 'name': 'VisA fresh pose study', 'samples': samples})
        experiment = run(root / 'manifest.json', source, weights, root / 'detectors', features)
        aligner = PoseAligner(frames[references[0]['image']])
        paired = {}
        for mode, variant in experiment['variants'].items():
            if variant['status'] != 'ok':
                paired[mode] = {'status': 'error', 'error': variant['error']}
                continue
            model = PaDiM.load(root / 'detectors' / mode / 'normal-model.npz')
            predictions = []
            for row in evaluations:
                for rotation in (0, 180):
                    frame = frames[row['image']]
                    if rotation: frame = cv2.rotate(frame, cv2.ROTATE_180)
                    aligned, evidence = aligner.align(frame)
                    prediction = {'image': row['image'], 'rotation_deg': rotation,
                        'input_kind': 'real_original' if rotation == 0 else 'controlled_transform',
                        'alignment': evidence, 'pose_group': 'unavailable' if aligned is None else
                            'rotated' if abs(evidence['angle_deg']) > 90 else 'near_reference'}
                    detector_frame = aligned if mode == 'aligned' else frame
                    if detector_frame is None:
                        prediction.update(status='error', error=evidence['error'])
                    else:
                        try:
                            score, _ = model.predict(features([detector_frame])[0])
                            prediction.update(status='ok', anomaly_score=score, is_ng=score > variant['threshold'])
                        except (RuntimeError, ValueError, cv2.error, FloatingPointError) as exc:
                            prediction.update(status='error', error=str(exc)[:2000])
                    predictions.append(prediction)
            labels = {r['image']: 'defect' if r['label'] == 'anomaly' else 'normal' for r in evaluations}
            for prediction in predictions: prediction['label'] = labels[prediction['image']]
            by_rotation = {str(angle): [r for r in predictions if r['rotation_deg'] == angle] for angle in (0, 180)}
            pairs = list(zip(by_rotation['0'], by_rotation['180']))
            valid = [(a, b) for a, b in pairs if a['status'] == b['status'] == 'ok']
            paired[mode] = {'status': 'ok', 'threshold': variant['threshold'],
                'original_metrics': metrics(by_rotation['0']), 'rotated_metrics': metrics(by_rotation['180']),
                'paired_count': len(valid), 'verdict_flips': sum(a['is_ng'] != b['is_ng'] for a, b in valid),
                'median_absolute_score_change': float(np.median([abs(a['anomaly_score']-b['anomaly_score']) for a,b in valid])) if valid else None,
                'pose_groups': pose_groups(predictions), 'predictions': predictions}
        report = {'schema_version': 1, 'dataset_id': experiment['dataset_id'],
            'observed_manifest_sha256': hashlib.sha256(observed_manifest.read_bytes()).hexdigest(),
            'excluded_observed_files': excluded, 'fresh_evaluation_files': [r['image'] for r in evaluations],
            'policy': 'Fixed original/180-degree pair for every image; no label-conditioned transform or test threshold tuning',
            'original_pose_groups': {mode: pose_groups(v['predictions']) for mode, v in experiment['variants'].items() if v['status'] == 'ok'},
            'paired': paired, 'limitations': ['Paired transforms are dependent views, not additional real samples',
                'Both original classes in each pose required for evidence of real pose-independent defect detection',
                'No real camera or independent factory labels; no claim of production defaults']}
        write_json(root / 'pose-study.json', report)
        if output.exists(): raise ValueError('Output appeared during study')
        root.rename(output)
    print(json.dumps({'dataset_id': report['dataset_id'], 'excluded': len(excluded),
                      'fresh_evaluations': len(evaluations), 'output': str(output)}, ensure_ascii=False), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/public-datasets/visa-pcb1-expanded')
    parser.add_argument('--observed', type=Path, default=ROOT / 'artifacts/public-data-visa-pcb1-final/manifest.json')
    parser.add_argument('--weights', type=Path, default=ROOT / 'data/models/resnet18-f37072fd.pth')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/pose-study-pcb1')
    args = parser.parse_args(); study(args.source, args.observed, args.weights, args.output)
