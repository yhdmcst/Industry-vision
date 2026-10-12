"""Versioned research gates. Failures stay in the defect and coverage denominators."""

import math

POLICY = {
    'id': 'vision-research-v1', 'minimum_normal': 30, 'minimum_defect': 30,
    'minimum_group_normal': 10, 'minimum_group_defect': 10,
    'minimum_recall': .90, 'maximum_false_positive_rate': .10,
    'minimum_coverage': .98, 'maximum_domain_recall_drop': .10,
}


def wilson(successes, total):
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0., center-radius), min(1., center+radius)]


def assess(predictions, *, minimum_normal=30, minimum_defect=30):
    rows = list(predictions)
    if any(r.get('label') not in ('normal', 'defect') for r in rows):
        raise ValueError('Acceptance requires independent binary labels for every planned sample')
    if any(r.get('status') == 'ok' and (type(r.get('is_ng')) is not bool
           or not isinstance(r.get('anomaly_score'), (float, int))
           or not math.isfinite(r['anomaly_score'])) for r in rows):
        raise ValueError('Successful prediction requires a finite score and boolean verdict')
    counts = {label: sum(r['label'] == label for r in rows) for label in ('normal', 'defect')}
    valid = [r for r in rows if r.get('status') == 'ok']
    tp = sum(r['is_ng'] and r['label'] == 'defect' for r in valid)
    fp = sum(r['is_ng'] and r['label'] == 'normal' for r in valid)
    vn = sum(r['label'] == 'normal' for r in valid)
    vd = len(valid) - vn
    recall = tp / counts['defect'] if counts['defect'] else None
    fpr = fp / vn if vn else None
    coverage = len(valid) / len(rows) if rows else None
    class_coverage = {label: n/counts[label] if counts[label] else None
                      for label, n in [('normal', vn), ('defect', vd)]}
    checks = {
        'sample_support': counts['normal'] >= minimum_normal and counts['defect'] >= minimum_defect,
        'recall_all_defects': recall is not None and recall >= POLICY['minimum_recall'],
        'normal_false_positive_rate': fpr is not None and fpr <= POLICY['maximum_false_positive_rate'],
        'coverage': coverage is not None and coverage >= POLICY['minimum_coverage'],
        'class_coverage': all(v is not None and v >= POLICY['minimum_coverage'] for v in class_coverage.values()),
    }
    return {
        'status': 'insufficient_evidence' if not checks['sample_support'] else 'passed' if all(checks.values()) else 'failed',
        'policy_id': POLICY['id'], 'checks': checks, 'planned': len(rows), 'counts': counts,
        'tp': tp, 'fp': fp, 'tn': vn-fp, 'fn': vd-tp,
        'unavailable': {label: counts[label]-n for label, n in [('normal', vn), ('defect', vd)]},
        'recall_all_defects': recall, 'false_positive_rate_assessed_normal': fpr,
        'coverage': coverage, 'class_coverage': class_coverage,
        'recall_wilson_95': wilson(tp, counts['defect']), 'fpr_wilson_95': wilson(fp, vn),
    }


def evaluate(predictions, *, evidence='development', groups=()):
    rows = list(predictions)
    ids = [r['sample_id'] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('Repeated sample identities cannot increase acceptance support')
    if evidence not in ('development', 'independent_final', 'real_domains', 'controlled_transform'):
        raise ValueError('Unknown evidence scope')
    overall = assess(rows)
    grouped = {g: assess([r for r in rows if r.get('group') == g],
                        minimum_normal=POLICY['minimum_group_normal'],
                        minimum_defect=POLICY['minimum_group_defect']) for g in groups}
    states = [overall['status']] + [v['status'] for v in grouped.values()]
    status = 'failed' if 'failed' in states else 'insufficient_evidence' if 'insufficient_evidence' in states else 'passed'
    return {'policy': dict(POLICY), 'evidence': evidence, 'status': status, 'overall': overall,
            'groups': grouped, 'accepted': status == 'passed' and evidence in ('independent_final', 'real_domains')}


def evaluate_domains(predictions, *, expected_domains, reference_domain, input_kind):
    """Every physical domain needs >=30 per class and a fixed-reference recall comparison."""
    rows = list(predictions)
    if input_kind not in ('real_public', 'real_workstation', 'controlled_transform', 'fixture'):
        raise ValueError('Explicit real, controlled or fixture provenance required')
    if len(set(expected_domains)) != len(expected_domains) or reference_domain not in expected_domains:
        raise ValueError('Unique domains and a declared reference domain required')
    if any(r.get('domain') not in expected_domains for r in rows):
        raise ValueError('Unexpected physical domain')
    ids = [r['sample_id'] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('Repeated root identities cannot become independent domain samples')
    roots = [(r['domain'], r.get('root_id',r['sample_id'])) for r in rows]
    if len(set(roots)) != len(roots):
        raise ValueError('Repeated root within a domain cannot increase sample support')
    domains = {d: assess([r for r in rows if r['domain'] == d]) for d in expected_domains}
    reference = domains[reference_domain]['recall_all_defects']
    for domain, gate in domains.items():
        recall = gate['recall_all_defects']
        drop = reference-recall if reference is not None and recall is not None else None
        gate['recall_drop_from_reference'] = drop
        gate['checks']['recall_drop'] = drop is not None and drop <= POLICY['maximum_domain_recall_drop']+1e-12
        if gate['status'] == 'passed' and not gate['checks']['recall_drop']:
            gate['status'] = 'failed'
    states = [g['status'] for g in domains.values()]
    status = 'failed' if 'failed' in states else 'insufficient_evidence' if 'insufficient_evidence' in states else 'passed'
    real = input_kind in ('real_public','real_workstation')
    return {'policy':dict(POLICY), 'status':status if real else 'insufficient_evidence',
            'input_kind':input_kind, 'domains':domains, 'reference_domain':reference_domain,
            'accepted':real and status == 'passed', 'workstation_accepted':input_kind == 'real_workstation' and status == 'passed',
            'limitation':None if real else 'Controlled transforms or fixtures cannot pass real-condition acceptance'}
