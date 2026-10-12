"""Evaluate prepared real public domains with one normal fit and frozen calibration threshold."""

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
from src.acceptance import evaluate_domains
from src.inspection.padim import PaDiM, ResNetFeatures
from src.inspection.vision_model import WEIGHTS_SHA256
from src.monitoring.image_analyzer import ImageQualityAnalyzer
from scripts.run_padim import metrics
from scripts.prepare_aebad import DOMAINS


def run(source, weights, output, features=None):
    if output.exists(): raise ValueError('Output exists; preserve domain evidence')
    metadata = json.loads((source / 'domains.json').read_bytes())
    rows = metadata['files']
    if metadata.get('dataset') not in ('AeBAD-S', 'MVTec AD 2'):
        raise ValueError('Expected supported declared public domains')
    if metadata.get('input_kind') != 'real_public':
        raise ValueError('Prepared source must explicitly declare real public provenance')
    domains = tuple(metadata.get('expected_domains', DOMAINS))
    reference_domain = metadata.get('domain_reference', 'same')
    if not domains or reference_domain not in domains or len(set(domains)) != len(domains):
        raise ValueError('Invalid declared physical domains')
    from scripts.prepare_mvtec_ad2 import DOMAINS as AD2_DOMAINS
    expected = DOMAINS if metadata['dataset'] == 'AeBAD-S' else AD2_DOMAINS
    if set(domains) != set(expected) or reference_domain != ('same' if metadata['dataset'] == 'AeBAD-S' else 'regular'):
        raise ValueError('Declared domains must match the dataset reference contract')
    fit = [r for r in rows if r['partition'] == 'fit']
    calibration = [r for r in rows if r['partition'] == 'calibration']
    tests = [r for r in rows if r['partition'] == 'evaluation']
    if len(fit) < 10 or len(calibration) != 20 or any(r['label'] != 'normal' for r in fit+calibration):
        raise ValueError('Normal-only fit and 20 independent calibration samples required')
    if len({r['id'] for r in rows}) != len(rows): raise ValueError('Duplicate domain image identity')
    frames = {}
    hashes = set()
    for row in rows:
        path = (source / row['path']).resolve()
        if not path.is_relative_to(source.resolve()): raise ValueError('Domain path escapes source root')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row['image_sha256']: raise ValueError('Domain image digest mismatch')
        frame = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.shape != (480, 640, 3): raise ValueError('Invalid normalized domain image')
        identity = hashlib.sha256(frame.tobytes()).hexdigest()
        if identity in hashes: raise ValueError('Duplicate normalized domain image')
        hashes.add(identity); frames[row['id']] = frame
    if set(r['domain'] for r in tests) != set(domains): raise ValueError('Missing or unknown domain')
    if any({r['label'] for r in tests if r['domain'] == domain} != {'normal', 'defect'} for domain in domains):
        raise ValueError('Every declared domain needs both classes')
    features = features or ResNetFeatures(weights, WEIGHTS_SHA256)
    def embeddings(selected):
        return np.concatenate([features([frames[r['id']] for r in selected[i:i+8]]) for i in range(0, len(selected), 8)])
    model = PaDiM(); model.fit(embeddings(fit))
    calibration_scores = [model.predict(e)[0] for e in embeddings(calibration)]
    threshold = float(np.quantile(calibration_scores, .95, method='higher'))
    analyzer = ImageQualityAnalyzer(); analyzer.set_baseline([frames[r['id']] for r in fit])
    predictions = []
    for row in tests:
        frame = frames[row['id']]
        result = {'sample_id': row['id'], 'root_id': row.get('root_id',row['id']), 'domain': row['domain']}
        try:
            score, _ = model.predict(features([frame])[0])
            result.update(status='ok', anomaly_score=score, is_ng=score > threshold)
        except (RuntimeError, ValueError, cv2.error, FloatingPointError) as exc:
            result.update(status='error', error=str(exc)[:2000])
        image_drift = analyzer.detect_drift(analyzer.analyze(frame))
        result['image_issues'] = [i['type'] for i in image_drift['issues']]
        predictions.append(result)
    labels = {r['id']: r['label'] for r in tests}
    for result in predictions: result['label'] = labels[result['sample_id']]
    report = {'schema_version': 1, 'dataset': metadata['dataset'], 'provenance': metadata['provenance'],
        'source_sha256': hashlib.sha256((source / 'domains.json').read_bytes()).hexdigest(),
        'method': 'Raw ResNet18 PaDiM; no domain-specific fitting, alignment or test normalization',
        'fit_ids': [r['id'] for r in fit], 'calibration_ids': [r['id'] for r in calibration],
        'calibration_scores': calibration_scores, 'threshold': threshold,
        'domains': {domain: {'metrics': metrics([r for r in predictions if r['domain'] == domain]),
            'normal_image_rule_count': sum(bool(r['image_issues']) for r in predictions if r['domain'] == domain and r['label'] == 'normal'),
            'image_issues': dict(Counter(i for r in predictions if r['domain'] == domain for i in r['image_issues']))} for domain in domains},
        'predictions': predictions, 'limitations': ['Public blade/vial domains are not PCB workstations',
            'Domain names do not prove one isolated physical cause; no independent cause-accuracy evaluation',
            'Image-level evaluation only; no segmentation, camera or per-hour alert measurements']}
    report['gate'] = evaluate_domains(predictions, expected_domains=domains, reference_domain=reference_domain,
                                     input_kind=metadata['input_kind'] if isinstance(features, ResNetFeatures) else 'fixture')
    references = {r['root_id']:r for r in predictions if r['domain'] == reference_domain}
    report['paired_reference'] = {}
    for domain in domains:
        pairs = [(references[r['root_id']],r) for r in predictions if r['domain'] == domain and r['root_id'] in references]
        valid = [(a,b) for a,b in pairs if a['status'] == b['status'] == 'ok']
        report['paired_reference'][domain] = {'paired_roots':len(pairs), 'assessed_pairs':len(valid),
                                            'verdict_flips':sum(a['is_ng'] != b['is_ng'] for a,b in valid)}
    report['independent_root_count'] = len({r['root_id'] for r in predictions})
    report['method_source_sha256'] = hashlib.sha256(b''.join((ROOT/path).read_bytes() for path in
        ('src/inspection/padim.py', 'src/acceptance.py', 'scripts/run_domain_study.py'))).hexdigest()
    report['weights_sha256'] = WEIGHTS_SHA256
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.domain-study-', dir=output.parent) as temporary:
        root = Path(temporary) / 'study'; root.mkdir()
        write_json(root / 'domain-study.json', report); model.save(root / 'normal-model.npz')
        if output.exists(): raise ValueError('Output appeared during study')
        root.rename(output)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--weights', type=Path, default=ROOT / 'data/models/resnet18-f37072fd.pth')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); report = run(args.source, args.weights, args.output)
    print(json.dumps(report['domains'], ensure_ascii=False))
