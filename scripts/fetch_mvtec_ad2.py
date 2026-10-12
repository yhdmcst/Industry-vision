"""Fetch the official AD2 vial research archive with bounded, version-pinned ranges.

No repository clone, login or redistribution. Dataset CC BY-NC-SA 4.0.
The SHA identifies downloaded bytes; it is not a publisher-signed checksum.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sys
import tempfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.acquisition import write_json

PAGE = 'https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2/downloads'
URL = 'https://www.mydrive.ch/shares/121506/739dc6459c939fe464c0d26acc6c2d55/download/466654885-1743167505/vial.tar.gz'
SIZE = 812067164
ETAG = '"67e6a011-3067295c"'
CHUNK = 4*1024**2


def fetch_range(start, cache):
    size = min(CHUNK, SIZE-start)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache/f'{start}-{size}.bin'
    checksum = path.with_suffix('.sha256')
    if path.is_file() and checksum.is_file() and path.stat().st_size == size:
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == checksum.read_text().strip():
            return path
    for attempt in range(3):
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                response = client.get(URL, headers={'Range':f'bytes={start}-{start+size-1}', 'If-Match':ETAG})
                response.raise_for_status()
            if (response.status_code != 206 or response.headers.get('etag') != ETAG
                    or response.headers.get('content-range') != f'bytes {start}-{start+size-1}/{SIZE}'
                    or len(response.content) != size):
                raise ValueError('Official AD2 archive version or range mismatch')
            with tempfile.NamedTemporaryFile(prefix='.range-',dir=cache,delete=False) as handle:
                handle.write(response.content); temporary = Path(handle.name)
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            checksum.write_text(hashlib.sha256(response.content).hexdigest())
            return path
        except httpx.HTTPError:
            if attempt == 2: raise


def download(output, cache, workers=8):
    if output.exists():
        raise ValueError('Archive output exists; preserve bytes and receipt')
    if not 1 <= workers <= 16:
        raise ValueError('Expected 1..16 range workers')
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i,path in enumerate(pool.map(lambda start:fetch_range(start,cache),range(0,SIZE,CHUNK))):
            paths.append(path)
            if i%10 == 0: print(f'Verified AD2 chunks {i+1}/{(SIZE+CHUNK-1)//CHUNK}',flush=True)
    with tempfile.NamedTemporaryFile(prefix='.ad2-',dir=output.parent,delete=False) as handle:
        temporary = Path(handle.name)
        checksum = hashlib.sha256()
        try:
            for path in paths:
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != path.with_suffix('.sha256').read_text().strip():
                    raise ValueError('Cached AD2 range changed during assembly')
                handle.write(content); checksum.update(content)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        if temporary.stat().st_size != SIZE or output.exists():
            raise ValueError('Archive size or output race')
        temporary.rename(output)
    finally:
        temporary.unlink(missing_ok=True)
    receipt = {'dataset':'MVTec AD 2', 'category':'vial', 'official_page':PAGE, 'url':URL,
               'etag':ETAG, 'size':SIZE, 'sha256':checksum.hexdigest(), 'license':'CC BY-NC-SA 4.0',
               'checksum_scope':'Local downloaded bytes; no official SHA was published on the accessed page'}
    write_json(output.with_suffix('.source.json'),receipt)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'data/public-datasets/mvtec-ad2-vial.tar.gz')
    parser.add_argument('--cache',type=Path,default=ROOT/'data/public-datasets/ad2-ranges'/ETAG.strip('"'))
    parser.add_argument('--workers',type=int,default=8)
    args = parser.parse_args(); print(download(args.output,args.cache,args.workers))
