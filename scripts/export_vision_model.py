"""Export a checked, self-contained local detector; never refit or retune on evaluation results."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json
from src.datasets import DatasetStore
from src.inspection.vision_model import method_digest, validated_files, WEIGHTS_SHA256


def export(experiment, manifest, weights, mode, output):
    if output.exists(): raise ValueError('Output exists; preserve model versions')
    report = json.loads((experiment / 'experiment.json').read_bytes())
    variant = report['variants'][mode]
    if variant['status'] != 'ok': raise ValueError('Cannot export a failed variant')
    if report['weights_sha256'] != WEIGHTS_SHA256: raise ValueError('Unsupported weight identity')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.vision-export-', dir=output.parent) as temporary:
        root = Path(temporary) / 'model'; root.mkdir()
        store = DatasetStore(Path(temporary) / 'datasets')
        imported = store.import_manifest(manifest)
        if imported['id'] != report['dataset_id']: raise ValueError('Experiment and manifest mismatch')
        references = [s for s in store.load(imported['id'])['samples'] if s['split'] == 'baseline']
        if [s['conditions']['original_file'] for s in references] != report['fit_ids']:
            raise ValueError('Fit identities do not match experiment')
        shutil.copyfile(weights, root / 'weights.pth')
        shutil.copyfile(experiment / mode / 'normal-model.npz', root / 'statistics.npz')
        shutil.copyfile(store.directory(imported['id']) / references[0]['asset'], root / 'reference.png')
        recipe = {'schema_version': 1, 'method': 'padim-resnet18-v1', 'method_sha256': method_digest(),
                  'mode': mode, 'decision_threshold': variant['threshold'], 'dataset_id': imported['id'],
                  'experiment_sha256': hashlib.sha256((experiment / 'experiment.json').read_bytes()).hexdigest(),
                  'fit_ids': report['fit_ids'], 'calibration_ids': report['calibration_ids']}
        for name, key in [('weights.pth', 'weights_sha256'), ('statistics.npz', 'statistics_sha256'), ('reference.png', 'reference_sha256')]:
            recipe[key] = hashlib.sha256((root / name).read_bytes()).hexdigest()
        write_json(root / 'recipe.json', recipe)
        validated_files(root)
        if output.exists(): raise ValueError('Output appeared during export')
        root.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, default=ROOT / 'artifacts/pose-study-pcb1/detectors')
    parser.add_argument('--manifest', type=Path, default=ROOT / 'artifacts/pose-study-pcb1/manifest.json')
    parser.add_argument('--weights', type=Path, default=ROOT / 'data/models/resnet18-f37072fd.pth')
    parser.add_argument('--mode', choices=['raw', 'aligned'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(export(args.experiment, args.manifest, args.weights, args.mode, args.output))
