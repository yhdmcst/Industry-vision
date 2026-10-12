"""Prepare AD2 vial PUBLIC labels and real lighting views without extracting private data.

Read exact PNG tar members only; fit40 training good, calibrate20 validation good.
Retain paired scene roots, and never infer private labels or count lighting views as new scenes.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
import tempfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.acquisition import write_json
from scripts.fetch_mvtec_ad2 import URL, SIZE, ETAG

DOMAINS = ('regular','overexposed','underexposed','shift_1','shift_2','shift_3','shift_4')


def prepare(archive_path, output):
    if output.exists():
        raise ValueError('Output exists; preserve prepared domain evidence')
    receipt = json.loads(archive_path.with_suffix('.source.json').read_bytes())
    checksum = hashlib.sha256()
    with archive_path.open('rb') as handle:
        for block in iter(lambda:handle.read(4*1024**2),b''): checksum.update(block)
    if (receipt.get('url') != URL or receipt.get('etag') != ETAG or receipt.get('size') != SIZE
            or archive_path.stat().st_size != SIZE or checksum.hexdigest() != receipt.get('sha256')):
        raise ValueError('Official AD2 archive receipt or byte digest mismatch')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive_path,'r:gz') as archive, tempfile.TemporaryDirectory(prefix='.ad2-prepare-',dir=output.parent) as temporary:
        members = archive.getmembers()
        if len({m.name for m in members}) != len(members):
            raise ValueError('Duplicate archive member identity')
        lookup = {m.name:m for m in members}
        def content(member):
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or '\\' in member.name or not member.isfile()
                    or not 0 < member.size <= 32*1024**2):
                raise ValueError('Unsafe or oversized public image member')
            return archive.extractfile(member).read()
        fit = sorted((m for m in members if m.isfile() and m.name.startswith('vial/train/good/') and m.name.endswith('.png')),key=lambda m:m.name)[:40]
        calibration = sorted((m for m in members if m.isfile() and m.name.startswith('vial/validation/good/') and m.name.endswith('.png')),key=lambda m:m.name)[:20]
        if len(fit) != 40 or len(calibration) != 20:
            raise ValueError('Missing independent official normal fit/calibration images')
        selected = [(m,'fit','training','normal',m.name) for m in fit]
        selected += [(m,'calibration','validation','normal',m.name) for m in calibration]
        for label, directory in [('normal','good'),('defect','bad')]:
            tests = sorted((m for m in members if m.isfile() and m.name.startswith(f'vial/test_public/{directory}/') and m.name.endswith('.png')),key=lambda m:m.name)
            for member in tests:
                stem = PurePosixPath(member.name).stem
                scene, _, domain = stem.partition('_')
                if not scene.isdigit() or domain not in DOMAINS:
                    raise ValueError('Unknown official public scene or lighting condition')
                if label == 'defect':
                    mask_name = f'vial/test_public/ground_truth/bad/{stem}_mask.png'
                    if mask_name not in lookup:
                        raise ValueError('Public defect lacks official ground-truth mask')
                    mask = cv2.imdecode(np.frombuffer(content(lookup[mask_name]),np.uint8),cv2.IMREAD_GRAYSCALE)
                    if mask is None or not mask.any():
                        raise ValueError('Public defect ground truth is empty or invalid')
                selected.append((member,'evaluation',domain,label,f'vial/public/{directory}/{scene}'))
        if any({label for _,part,d,label,_ in selected if part == 'evaluation' and d == domain} != {'normal','defect'} for domain in DOMAINS):
            raise ValueError('Each real condition must retain both public classes')
        root = Path(temporary)/'prepared'; root.mkdir()
        rows, pixels = [], set()
        for index,(member,partition,domain,label,root_id) in enumerate(selected):
            data = content(member)
            frame = cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
            if frame is None: raise ValueError('Public image decode failed')
            if label == 'defect':
                mask_member = lookup[f'vial/test_public/ground_truth/bad/{PurePosixPath(member.name).stem}_mask.png']
                mask = cv2.imdecode(np.frombuffer(content(mask_member),np.uint8),cv2.IMREAD_GRAYSCALE)
                if mask is None or mask.shape != frame.shape[:2] or not mask.any():
                    raise ValueError('Ground truth mask does not match public image dimensions')
            frame = cv2.resize(frame,(640,480),interpolation=cv2.INTER_AREA)
            pixel = hashlib.sha256(frame.tobytes()).hexdigest()
            if pixel in pixels: raise ValueError('Duplicate normalized pixels across partitions/conditions')
            pixels.add(pixel)
            filename = f'{index:04d}.png'
            if not cv2.imwrite(str(root/filename),frame): raise OSError('Cannot save public domain pixels')
            row = {'id':member.name, 'root_id':root_id, 'path':filename, 'partition':partition, 'domain':domain,
                   'label':label, 'original_file':member.name, 'original_sha256':hashlib.sha256(data).hexdigest(),
                   'image_sha256':hashlib.sha256((root/filename).read_bytes()).hexdigest(), 'pixel_sha256':pixel}
            if label == 'defect':
                row['ground_truth_sha256'] = hashlib.sha256(content(lookup[f'vial/test_public/ground_truth/bad/{PurePosixPath(member.name).stem}_mask.png'])).hexdigest()
            rows.append(row)
        write_json(root/'domains.json', {'schema_version':1,'dataset':'MVTec AD 2','category':'vial',
            'license':'CC BY-NC-SA 4.0','input_kind':'real_public','expected_domains':list(DOMAINS),'domain_reference':'regular',
            'provenance':'Pinned official vial tar and public good/bad labels, confirmed defect masks; no private images/labels used',
            'archive_receipt':receipt, 'selection':'First40 train good; first20 validation good; every labeled public condition view',
            'limitations':['Only 5 normal and 15 defect scene roots per condition; insufficient research support',
                            'Lighting views share scene roots; 140 public views are only 20 independent scenes',
                            'shift names describe published lighting variants, not physical camera translation',
                            'No segmentation accuracy despite checking defect masks; noncommercial research only'], 'files':rows})
        if output.exists(): raise ValueError('Output appeared during preparation')
        root.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,default=ROOT/'data/public-datasets/mvtec-ad2-vial.tar.gz')
    parser.add_argument('--output',type=Path,default=ROOT/'data/public-datasets/mvtec-ad2-vial-public')
    args = parser.parse_args(); print(prepare(args.archive,args.output))
