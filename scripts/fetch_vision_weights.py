"""Download only the fixed official torchvision ResNet18 checkpoint; never load unverified bytes."""

import argparse
import hashlib
from pathlib import Path
import sys
import tempfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_padim import WEIGHTS_SHA256

URL = 'https://download.pytorch.org/models/resnet18-f37072fd.pth'


def fetch(output):
    if output.exists():
        if hashlib.sha256(output.read_bytes()).hexdigest() != WEIGHTS_SHA256:
            raise ValueError('Existing weights are corrupt; preserve them and choose a new output')
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.weights-', dir=output.parent) as temporary:
        candidate = Path(temporary) / 'checkpoint.pth'
        checksum = hashlib.sha256()
        with httpx.stream('GET', URL, follow_redirects=True, timeout=60) as response, candidate.open('wb') as stream:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                checksum.update(chunk)
                stream.write(chunk)
                if stream.tell() > 64 * 1024**2:
                    raise ValueError('Checkpoint exceeds expected size bound')
        if checksum.hexdigest() != WEIGHTS_SHA256:
            raise ValueError('Official ResNet18 checkpoint digest mismatch')
        if output.exists():
            raise ValueError('Output appeared during download; preserve existing file')
        candidate.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/models/resnet18-f37072fd.pth')
    print(fetch(parser.parse_args().output))
