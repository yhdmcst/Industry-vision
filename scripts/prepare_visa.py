"""Fetch a bounded VisA PCB subset from the official tar using verified HTTP byte ranges.

No upstream source is cloned or copied. The fixed official CSV is read as data.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import json
from pathlib import Path
from pathlib import PurePosixPath
import sys
import tarfile
import tempfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json

REVISION = '2a692ab575001cbde74d402d897a7286086c6199'
URL = 'https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar'
ETAG = '"05c830591a1172938cb714895c9e0cfb-113"'
SIZE = 1929840640
CSV_URL = f'https://raw.githubusercontent.com/amazon-science/spot-diff/{REVISION}/split_csv/1cls.csv'
CSV_SHA256 = 'a48557e6033318cb90556f706196bc9d247a776a23ea51aecee5a80dd0332995'
CACHE = ROOT / 'data/public-datasets/visa-ranges' / ETAG.strip('"')


def fetch(start, size):
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f'{start}-{size}.bin'
    checksum = cached.with_suffix('.sha256')
    if cached.is_file() and checksum.is_file() and cached.stat().st_size == size:
        content = cached.read_bytes()
        if hashlib.sha256(content).hexdigest() == checksum.read_text().strip():
            return content
    for attempt in range(3):
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                response = client.get(URL, headers={'Range': f'bytes={start}-{start+size-1}', 'If-Match': ETAG})
                response.raise_for_status()
                if (response.status_code != 206 or response.headers.get('etag') != ETAG
                        or response.headers.get('content-range') != f'bytes {start}-{start+size-1}/{SIZE}'
                        or len(response.content) != size):
                    raise ValueError('Official archive range/version mismatch')
                with tempfile.NamedTemporaryFile(prefix='.range-', dir=CACHE, delete=False) as handle:
                    handle.write(response.content)
                    temporary = Path(handle.name)
                try:
                    temporary.replace(cached)
                finally:
                    temporary.unlink(missing_ok=True)
                checksum.write_text(hashlib.sha256(response.content).hexdigest())
                return response.content
        except httpx.HTTPError:
            if attempt == 2: raise


def indexed_read(offset, size):
    """Read from existing 4MiB ranges without retaining the entire tar in memory."""
    origin, chunk = 850*1024**2, 4*1024**2
    if offset < origin or size < 0 or offset+size > SIZE:
        raise ValueError('Archive member outside bounded PCB scan')
    result = []
    while size:
        start = origin + ((offset-origin)//chunk)*chunk
        block = fetch(start, min(chunk, SIZE-start))
        within = offset-start
        take = min(size, len(block)-within)
        if take <= 0:
            raise ValueError('Truncated archive range')
        result.append(block[within:within+take])
        size -= take; offset += take
    return b''.join(result)


def index_category(expected, category):
    start = 850*1024**2
    first = fetch(start, 4*1024**2)
    for shift in range(0, len(first)-512, 512):
        try:
            member = tarfile.TarInfo.frombuf(first[shift:shift+512], 'utf-8', 'strict')
            if member.name:
                offset = start+shift; break
        except (tarfile.HeaderError, UnicodeError):
            pass
    else:
        raise ValueError('Cannot locate archive scan header')
    index, entered = {}, False
    while offset+512 <= SIZE:
        member = tarfile.TarInfo.frombuf(indexed_read(offset, 512), 'utf-8', 'strict')
        if member.name.startswith(category+'/') or member.name == category:
            if not entered:
                print(f'Entered {category} at byte {offset}', flush=True)
            entered = True
        elif entered:
            break
        if member.name in expected:
            if member.name in index or not member.isfile() or not 0 < member.size <= 256*1024**2:
                raise ValueError('Invalid or duplicate selected tar member')
            index[member.name] = {'offset': offset+512, 'size': member.size}
        offset += 512 + ((member.size+511)//512)*512
        if set(index) == expected:
            return index
    raise ValueError(f'Missing {len(expected-set(index))} selected {category} members')


def prepare(output: Path, train_count=100, normal_count=100, anomaly_count=100, category='pcb1'):
    if output.exists():
        raise ValueError('Output exists; choose a new directory to preserve evidence')
    response = httpx.get(CSV_URL, follow_redirects=True, timeout=60)
    response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != CSV_SHA256:
        raise ValueError('Official split CSV digest mismatch')
    if category not in ('pcb1', 'pcb2', 'pcb3', 'pcb4'):
        raise ValueError('Expected a supported PCB category')
    rows = [r for r in csv.DictReader(io.StringIO(response.text)) if r['object'] == category]
    selected = []
    for split, label, count in [('train', 'normal', train_count), ('test', 'normal', normal_count), ('test', 'anomaly', anomaly_count)]:
        candidates = sorted((r for r in rows if r['split'] == split and r['label'] == label), key=lambda r:r['image'])
        if not 1 <= count <= len(candidates): raise ValueError('Requested subset exceeds official partition')
        selected.extend(candidates[:count])
    expected = {r['image'] for r in selected}
    if any(PurePosixPath(p).is_absolute() or '..' in PurePosixPath(p).parts or '\\' in p
           or not p.startswith(category+'/Data/Images/') for p in expected):
        raise ValueError('Official split contains an invalid image path')
    if category != 'pcb1':
        print(f'Indexing official {category} with bounded cached range reads', flush=True)
        index = index_category(expected, category)
        return publish(output, response, selected, index, train_count, normal_count, anomaly_count, category,
                       lambda entry: indexed_read(entry['offset'], entry['size']))
    index = {}
    # This window precedes PCB1 in the fixed 2022 archive. Validate tar checksums and exact names;
    # never assume filenames or infer annotations from byte offsets.
    block_start = 850 * 1024**2
    chunk_size = 4 * 1024**2
    starts = list(range(block_start, 1150 * 1024**2, chunk_size))
    print('Indexing official PCB1 archive region (cached HTTP ranges)', flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        block = b''.join(pool.map(lambda start: fetch(start, chunk_size), starts))
    offset = block_start
    for shift in range(0, len(block)-512, 512):
        try:
            member = tarfile.TarInfo.frombuf(block[shift:shift+512], 'utf-8', 'strict')
            if member.name: offset = block_start + shift; break
        except (tarfile.HeaderError, UnicodeError): pass
    else: raise ValueError('Cannot locate a valid tar header in official PCB archive region')
    entered = False
    while offset < SIZE:
        if offset > block_start + len(block) - 512:
            raise ValueError('Selected PCB1 files exceed indexed archive region')
        header = block[offset-block_start:offset-block_start+512]
        member = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
        if member.name.startswith('pcb1/') or member.name == 'pcb1': entered = True
        elif entered: break
        if member.name in expected:
            if not member.isfile() or member.size > 256*1024**2: raise ValueError('Invalid tar member')
            index[member.name] = {'offset': offset+512, 'size': member.size}
        offset += 512 + ((member.size + 511)//512)*512
        if len(index) == len(expected): break
    if set(index) != expected: raise ValueError(f'Missing {len(expected-set(index))} selected members')
    return publish(output, response, selected, index, train_count, normal_count, anomaly_count, category,
                   lambda entry: block[entry['offset']-block_start:entry['offset']-block_start+entry['size']])


def publish(output, response, selected, index, train_count, normal_count, anomaly_count, category, read):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.visa-', dir=output.parent) as temporary:
        root = Path(temporary) / 'dataset'
        root.mkdir()
        def download(row):
            entry = index[row['image']]
            content = read(entry)
            if len(content) != entry['size']:
                raise ValueError('Archive member exceeds verified range')
            destination = root / row['image']
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            return {**row, **entry, 'sha256': hashlib.sha256(content).hexdigest()}
        with ThreadPoolExecutor(max_workers=8) as pool:
            records = list(pool.map(download, selected))
        (root / 'official-1cls.csv').write_bytes(response.content)
        report = {'dataset': 'VisA', 'category': category, 'url': URL, 'etag': ETAG, 'archive_bytes': SIZE,
                  'repository': 'amazon-science/spot-diff', 'revision': REVISION, 'split_file': 'split_csv/1cls.csv',
                  'split_sha256': hashlib.sha256(response.content).hexdigest(), 'license': 'CC BY 4.0',
                  'selection': 'Lexicographically first requested counts within fixed official partitions',
                  'counts': {'train_normal': train_count, 'test_normal': normal_count, 'test_anomaly': anomaly_count},
                  'limitations': ['Bounded PCB subset, not full VisA', 'train/test are official partitions, not known factory batch IDs',
                                  'No masks downloaded; image-level evaluation only'], 'files': records}
        write_json(root / 'source.json', report)
        if output.exists():
            raise ValueError('Output appeared during preparation; preserve existing evidence')
        root.rename(output)
    print(json.dumps({k:v for k,v in report.items() if k!='files'}, ensure_ascii=False), flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/public-datasets/visa-pcb1')
    parser.add_argument('--train', type=int, default=100)
    parser.add_argument('--normal', type=int, default=100)
    parser.add_argument('--anomaly', type=int, default=100)
    parser.add_argument('--category', choices=['pcb1', 'pcb2', 'pcb3', 'pcb4'], default='pcb1')
    args=parser.parse_args()
    prepare(args.output, args.train, args.normal, args.anomaly, args.category)


if __name__ == '__main__': main()
