"""Prepare a user's local AeBAD-S release without downloading, cloning or inventing domains."""

import argparse
import hashlib
from pathlib import Path
import sys
import tempfile

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json

DOMAINS = ('same', 'background', 'illumination', 'view')


def prepare(source, output, fit=40, calibration=20, per_group=30):
    source = source.expanduser().resolve()
    if output.exists(): raise ValueError('Output exists; preserve source evidence')
    if not (source / 'train/good').is_dir() or not (source / 'test').is_dir():
        raise ValueError('Expected local AeBAD_S with train/good and test directories')
    if not 10 <= fit <= 100 or calibration != 20 or not 1 <= per_group <= 40:
        raise ValueError('Invalid bounded partition sizes')
    train = sorted((source / 'train/good').glob('*/*.png'))
    if len(train) < fit + calibration: raise ValueError('Insufficient normal fit/calibration images')
    selected = [(path, 'fit' if index < fit else 'calibration', 'training', 'normal')
                for index, path in enumerate(train[:fit+calibration])]
    for domain in DOMAINS:
        normal = sorted((source / 'test/good' / domain).glob('*.png'))[:per_group]
        anomaly = sorted(p for p in (source / 'test').glob(f'*/{domain}/*.png') if p.parent.parent.name != 'good')[:per_group]
        if not normal or not anomaly: raise ValueError(f'Missing both classes for official domain {domain}')
        selected.extend((p, 'evaluation', domain, label) for paths,label in [(normal,'normal'), (anomaly,'defect')] for p in paths)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.aebad-', dir=output.parent) as temporary:
        root = Path(temporary) / 'prepared'; root.mkdir()
        rows, hashes = [], set()
        for index, (path, split, domain, label) in enumerate(selected):
            if not path.resolve().is_relative_to(source): raise ValueError('Source path escapes root')
            frame = cv2.imread(str(path))
            if frame is None: raise ValueError('Cannot decode local AeBAD image')
            frame = cv2.resize(frame, (640, 480), interpolation=cv2.INTER_AREA)
            pixel_hash = hashlib.sha256(frame.tobytes()).hexdigest()
            if pixel_hash in hashes: raise ValueError('Duplicate normalized image across AeBAD partitions/domains')
            hashes.add(pixel_hash)
            filename = f'{index:04d}.png'
            if not cv2.imwrite(str(root / filename), frame): raise OSError('Cannot save AeBAD image')
            rows.append({'id': f'aebad-{index:04d}', 'path': filename, 'partition': split, 'domain': domain,
                         'original_file': path.relative_to(source).as_posix(), 'original_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'image_sha256': hashlib.sha256((root / filename).read_bytes()).hexdigest(), 'label': label})
        write_json(root / 'domains.json', {'schema_version': 1, 'dataset': 'AeBAD-S', 'license': 'CC BY 4.0',
            'input_kind': 'real_public', 'domain_reference': 'same', 'expected_domains': list(DOMAINS),
            'reference_repository': 'zhangzilongc/MMR', 'reference_revision': '22d1b171687509024e6f5b53b5a5e772d653d32b',
            'provenance': 'User-provided local release; file digests identify supplied bytes, not official authenticity',
            'selection': 'Fixed sorted normal fit/calibration; sorted bounded test files per domain/class', 'files': rows})
        if output.exists(): raise ValueError('Output appeared during preparation')
        root.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(prepare(args.source, args.output))
