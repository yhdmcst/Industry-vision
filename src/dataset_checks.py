"""Evidence checks shared by dataset composition and offline replay reports."""

from collections import Counter


def batch_key(sample: dict) -> str:
    if sample.get('lineage', {}).get('batch_key'):
        return sample['lineage']['batch_key']
    conditions = sample.get('conditions', {})
    if conditions.get('capture_batch_id'):
        return 'capture:' + conditions['capture_batch_id']
    if conditions.get('source_batch_id'):
        return 'source:' + conditions['source_batch_id']
    return 'declared:' + sample['batch']


def partition_checks(samples: list[dict]) -> dict:
    references = [s for s in samples if s['split'] == 'baseline']
    evaluations = [s for s in samples if s['split'] == 'evaluation']
    hashes = {s['sha256'] for s in references}
    counts = Counter(s['sha256'] for s in evaluations)
    shared = sorted({batch_key(s) for s in references} & {batch_key(s) for s in evaluations})
    return {
        'baseline_duplicate_ids': [s['id'] for s in evaluations if s['sha256'] in hashes],
        'evaluation_duplicate_ids': [s['id'] for s in evaluations if counts[s['sha256']] > 1],
        'shared_batches': sorted({s['batch'] for s in references} & {s['batch'] for s in evaluations}),
        'shared_batch_keys': shared,
        'unique_evaluation_images': len(counts),
        'unlabeled_evaluation_ids': [s['id'] for s in evaluations if s['label']['defect'] == 'unknown'],
        'unknown_cause_ids': [s['id'] for s in evaluations if s['label']['cause'] == 'unknown'],
        'synthetic_ids': [s['id'] for s in samples if s['origin'] == 'synthetic'],
        'perturbed_ids': [s['id'] for s in samples if s['perturbation'] != 'none'],
        'declared_batch_ids': [s['id'] for s in samples if batch_key(s).startswith('declared:')],
    }
