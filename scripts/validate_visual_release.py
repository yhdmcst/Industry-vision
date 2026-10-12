"""Partition untouched VisA, select on validation, freeze, consume final set once.

The seal prevents accidental reuse; it is an auditable local protocol, not access control.
Labels select a validation threshold explicitly. Final labels only join after predictions.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from importlib.metadata import version

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json
from src.acceptance import POLICY, evaluate
from src.inspection.alignment import PoseAligner
from src.inspection.methods import METHODS, load_patch_memory, score_map
from src.inspection.padim import PaDiM, ResNetFeatures
from scripts.compare_visual_methods import compare, implementation_digest
from scripts.prepare_visa import REVISION, CSV_SHA256, URL, ETAG
from scripts.run_pose_study import image
from scripts.run_padim import WEIGHTS_SHA256


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_digest():
    return hashlib.sha256((implementation_digest()+sha(__file__)).encode()).hexdigest()


def partition(source, output, observed_sources):
    if output.exists() or (source/'final-consumed.json').exists():
        raise ValueError('Protocol or final consumption exists; preserve evidence')
    metadata = json.loads((source/'source.json').read_bytes())
    if (metadata.get('dataset') != 'VisA' or metadata.get('revision') != REVISION
            or metadata.get('split_sha256') != CSV_SHA256 or metadata.get('url') != URL or metadata.get('etag') != ETAG):
        raise ValueError('Expected pinned official VisA source')
    if not observed_sources:
        raise ValueError('Observed sources must be declared before sealing')
    forbidden_ids, forbidden_pixels = set(), set()
    for previous in observed_sources:
        declared = json.loads((previous/'source.json').read_bytes())
        if declared['category'] == metadata['category']:
            raise ValueError('Already observed category cannot become an independent final set')
        for row in declared['files']:
            forbidden_ids.add(row['image'])
            forbidden_pixels.add(hashlib.sha256(image(previous, row).tobytes()).hexdigest())
    rows = metadata['files']
    train = sorted([r for r in rows if r['split'] == 'train' and r['label'] == 'normal'], key=lambda r:r['image'])
    if len(train) != 60:
        raise ValueError('Sealed protocol requires exactly 40 fit and 20 normal calibration images')
    selected = [{**r, 'partition': 'fit' if i < 40 else 'calibration'} for i,r in enumerate(train)]
    for label in ('normal', 'anomaly'):
        candidates = [r for r in rows if r['split'] == 'test' and r['label'] == label]
        if len(candidates) != 100:
            raise ValueError('Sealed protocol requires 100 untouched official tests per class')
        candidates.sort(key=lambda r:hashlib.sha256(('spark-final-v1/'+r['image']).encode()).hexdigest())
        selected.extend({**r, 'partition': 'validation' if i < 50 else 'final'} for i,r in enumerate(candidates))
    identities, pixels = set(), set()
    for row in selected:
        pixel = hashlib.sha256(image(source, row).tobytes()).hexdigest()
        if row['image'] in identities|forbidden_ids or pixel in pixels|forbidden_pixels:
            raise ValueError('Partitions overlap observed identities or normalized pixels')
        identities.add(row['image']); pixels.add(pixel)
        row['pixel_sha256'] = pixel
    document = {'schema_version': 1, 'category': metadata['category'], 'source_sha256': sha(source/'source.json'),
                'policy': dict(POLICY), 'selection': 'sha256(spark-final-v1/official_identity), first half validation; split before scoring',
                'observed_sources': [sha(p/'source.json') for p in observed_sources], 'files': selected}
    output.mkdir(parents=True)
    write_json(output/'split.json', document)
    write_json(output/'seal.json', {'split_sha256': sha(output/'split.json')})
    return document


def checked_split(source, protocol):
    document = json.loads((protocol/'split.json').read_bytes())
    if (json.loads((protocol/'seal.json').read_bytes())['split_sha256'] != sha(protocol/'split.json')
            or document['policy'] != POLICY or document['source_sha256'] != sha(source/'source.json')):
        raise ValueError('Source or acceptance policy changed after partition')
    frames, hashes = {}, set()
    for row in document['files']:
        frame = image(source, row)
        pixel = hashlib.sha256(frame.tobytes()).hexdigest()
        if pixel != row['pixel_sha256'] or pixel in hashes or row['image'] in frames:
            raise ValueError('Sealed pixels changed or duplicate partition identity')
        hashes.add(pixel); frames[row['image']] = frame
    if len(document['files']) != 260 or any(sum(r['partition'] == group and r['label'] == label for r in document['files']) != count
           for group,label,count in [('fit','normal',40), ('calibration','normal',20),
               ('validation','normal',50), ('validation','anomaly',50), ('final','normal',50), ('final','anomaly',50)]):
        raise ValueError('Sealed partition counts changed')
    return document, frames


def select_threshold(predictions):
    valid = [r for r in predictions if r['status'] == 'ok']
    scores = sorted({r['anomaly_score'] for r in valid})
    if not scores:
        return None
    candidates = [float(np.nextafter(scores[0], -np.inf))]+scores
    best = None
    for threshold in candidates:
        adjusted = [{**r, 'is_ng': r['anomaly_score'] > threshold} if r['status'] == 'ok' else dict(r) for r in predictions]
        gate = evaluate(adjusted)
        if gate['status'] != 'passed':
            continue
        overall = gate['overall']
        rank = (overall['false_positive_rate_assessed_normal'], -overall['recall_all_defects'], threshold)
        if best is None or rank < best[0]:
            best = (rank, {'threshold': threshold, 'gate': gate})
    return best[1] if best else None


def validate(source, protocol, weights, features=None):
    if (protocol/'validation').exists() or (protocol/'frozen').exists() or (source/'final-consumed.json').exists():
        raise ValueError('Validation or frozen evidence exists; do not retune the same final cohort')
    split, _ = checked_split(source, protocol)
    ids = [r['image'] for r in split['files'] if r['partition'] == 'validation']
    report = compare(source, ids, protocol/'validation', weights, features=features)
    candidates = {}
    for method, variant in report['variants'].items():
        if variant['status'] == 'ok':
            selected = select_threshold(variant['predictions'])
            candidates[method] = {'status': 'passed' if selected else 'failed', 'selected': selected,
                                  'statistics_sha256': sha(protocol/'validation'/method/'statistics.npz')}
    result = {'split_sha256': sha(protocol/'split.json'), 'comparison_sha256': sha(protocol/'validation/comparison.json'),
              'method_source_sha256': code_digest(), 'candidates': candidates,
              'threshold_selection': 'Validation labels explicitly select threshold; minimize FPR then maximize recall among passing candidates',
              'status': 'passed' if any(v['status'] == 'passed' for v in candidates.values()) else 'failed'}
    write_json(protocol/'validation-selection.json', result)
    return result


def freeze(source, protocol):
    if (protocol/'frozen').exists() or (source/'final-consumed.json').exists():
        raise ValueError('Frozen recipe or final consumption exists')
    split, frames = checked_split(source, protocol)
    selected = json.loads((protocol/'validation-selection.json').read_bytes())
    if (selected['split_sha256'] != sha(protocol/'split.json') or selected['method_source_sha256'] != code_digest()
            or selected['comparison_sha256'] != sha(protocol/'validation/comparison.json')):
        raise ValueError('Validation code, split or evidence changed; cannot freeze')
    comparison = json.loads((protocol/'validation/comparison.json').read_bytes())
    passing = []
    for method in METHODS:
        candidate = selected['candidates'].get(method)
        if candidate and candidate['status'] == 'passed':
            recomputed = select_threshold(comparison['variants'][method]['predictions'])
            if recomputed != candidate['selected']:
                raise ValueError('Validation threshold selection changed')
            g = candidate['selected']['gate']['overall']
            passing.append((g['false_positive_rate_assessed_normal'], -g['recall_all_defects'], METHODS.index(method), method))
    if not passing:
        raise ValueError('No candidate passed validation; final set remains unconsumed')
    method = min(passing)[-1]
    stats = protocol/'validation'/method/'statistics.npz'
    if sha(stats) != selected['candidates'][method]['statistics_sha256']:
        raise ValueError('Validation model statistics changed')
    with tempfile.TemporaryDirectory(prefix='.freeze-', dir=protocol) as temporary:
        root = Path(temporary)/'frozen'; root.mkdir()
        shutil.copyfile(stats, root/'statistics.npz')
        fit = [r for r in split['files'] if r['partition'] == 'fit']
        if not cv2.imwrite(str(root/'reference.png'), frames[fit[0]['image']]):
            raise OSError('Cannot save fixed normal reference')
        if 'roi' in method:
            shutil.copyfile(protocol/'validation'/method/'normal-only-roi.png', root/'roi.png')
        # Preserve the precise implementation, not just a digest that becomes opaque after edits.
        for path in ('src/acceptance.py', 'src/inspection/methods.py', 'src/inspection/padim.py',
                     'src/inspection/alignment.py', 'scripts/compare_visual_methods.py', 'scripts/validate_visual_release.py'):
            destination = root/'method-source'/path
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/path,destination)
        recipe = {'schema_version': 1, 'method': method, 'threshold': selected['candidates'][method]['selected']['threshold'],
                  'method_source_sha256': code_digest(), 'split_sha256': sha(protocol/'split.json'),
                  'validation_sha256': sha(protocol/'validation-selection.json'), 'source_sha256': sha(source/'source.json'),
                  'weights_sha256': WEIGHTS_SHA256, 'policy': dict(POLICY),
                  'files': {p.relative_to(root).as_posix(): sha(p) for p in root.rglob('*') if p.is_file()},
                  'software': {p:version(p) for p in ('numpy','scipy','opencv-python-headless','torch','torchvision')}}
        write_json(root/'recipe.json', recipe)
        root.rename(protocol/'frozen')
    write_json(protocol/'freeze-receipt.json', {'recipe_sha256': sha(protocol/'frozen/recipe.json')})
    return recipe


def final(source, protocol, weights, features=None):
    frozen = protocol/'frozen'
    recipe = json.loads((frozen/'recipe.json').read_bytes())
    if (json.loads((protocol/'freeze-receipt.json').read_bytes())['recipe_sha256'] != sha(frozen/'recipe.json')
            or recipe['method_source_sha256'] != code_digest() or recipe['policy'] != POLICY
            or recipe['split_sha256'] != sha(protocol/'split.json') or recipe['source_sha256'] != sha(source/'source.json')
            or recipe['validation_sha256'] != sha(protocol/'validation-selection.json')):
        raise ValueError('Recipe, code or partition changed after freeze')
    if features is None and (sha(weights) != recipe['weights_sha256'] or any(version(k) != v for k,v in recipe['software'].items())):
        raise ValueError('Frozen weights or dependency versions changed')
    if any(sha(frozen/name) != value for name,value in recipe['files'].items()):
        raise ValueError('Frozen model or reference digest mismatch')
    split, frames = checked_split(source, protocol)
    method = recipe['method']
    if method not in METHODS or not np.isfinite(recipe['threshold']):
        raise ValueError('Invalid frozen research recipe')
    if 'patch_memory' in method:
        if (frozen/'statistics.npz').stat().st_size > 5*1024**2:
            raise ValueError('Patch bank resource limit')
        model = load_patch_memory(frozen/'statistics.npz', dense='dense' in method)
    else:
        model = PaDiM.load(frozen/'statistics.npz')
    mask = cv2.imread(str(frozen/'roi.png'), cv2.IMREAD_GRAYSCALE) if 'roi' in method else None
    if 'roi' in method and (mask is None or mask.shape != (224,224) or not mask.any()):
        raise ValueError('Invalid frozen ROI')
    if mask is not None: mask = mask > 0
    aligner = PoseAligner(cv2.imread(str(frozen/'reference.png'))) if method.startswith('aligned') else None
    features = features or ResNetFeatures(weights, WEIGHTS_SHA256)
    consumed = source/'final-consumed.json'
    receipt = {'status': 'started', 'recipe_sha256': sha(frozen/'recipe.json'), 'split_sha256': sha(protocol/'split.json'),
               'protocol': str(protocol.resolve()), 'output': str((protocol/'final-report.json').resolve())}
    # Reserve in the source root before the first final prediction; another output cannot bypass it.
    with consumed.open('x', encoding='utf-8') as handle:
        json.dump(receipt, handle, sort_keys=True)
    try:
        rows = [r for r in split['files'] if r['partition'] == 'final']
        predictions = []
        for row in rows:
            started = time.perf_counter()
            frame = frames[row['image']]
            result = {'sample_id': row['image']}
            try:
                if method.startswith('aligned'):
                    frame, evidence = aligner.align(frame)
                    result['alignment'] = evidence
                    if frame is None: raise ValueError(evidence['error'])
                _, heat = model.predict(features([frame])[0])
                score = score_map(heat, mask)
                result.update(status='ok', anomaly_score=score, is_ng=score > recipe['threshold'])
            except (RuntimeError, ValueError, cv2.error, FloatingPointError) as exc:
                result.update(status='error', error=str(exc)[:2000])
            result['elapsed_ms'] = (time.perf_counter()-started)*1000
            predictions.append(result)
        # Every final score is now fixed; only here do independent final labels join.
        for result, row in zip(predictions, rows):
            result['label'] = 'defect' if row['label'] == 'anomaly' else 'normal'
        report = {'schema_version': 1, 'recipe_sha256': receipt['recipe_sha256'], 'method': method,
                  'threshold': recipe['threshold'], 'gate': evaluate(predictions, evidence='independent_final'),
                  'predictions': predictions, 'limitations': ['Independent image cohort, not independent factory batches',
                    'Category-specific normal fit; does not demonstrate PCB1-to-PCB2 zero-shot generalization',
                    'Frozen research model is separate from deployable runtime recipes; no camera or segmentation acceptance']}
        write_json(protocol/'final-report.json', report)
        write_json(consumed, {**receipt, 'status': 'completed', 'report_sha256': sha(protocol/'final-report.json'),
                              'gate_status': report['gate']['status']})
        return report
    except BaseException as exc:
        write_json(consumed, {**receipt, 'status': 'aborted', 'error': f'{type(exc).__name__}: {exc}'[:2000]})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['partition','validate','freeze','final'])
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--observed-source', type=Path, action='append')
    parser.add_argument('--weights', type=Path, default=ROOT/'data/models/resnet18-f37072fd.pth')
    args = parser.parse_args()
    if args.stage == 'partition': result = partition(args.source, args.protocol, args.observed_source or [])
    elif args.stage == 'validate': result = validate(args.source, args.protocol, args.weights)
    elif args.stage == 'freeze': result = freeze(args.source, args.protocol)
    else: result = final(args.source, args.protocol, args.weights)
    print(json.dumps({k:v for k,v in result.items() if k not in ('files','predictions')}, ensure_ascii=False))
