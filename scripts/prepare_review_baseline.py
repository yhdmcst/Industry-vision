"""Download and verify the pinned independent research baseline; no workstation model switch."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.llm.preparation import download_asset
from src.llm.deployment import verify_weight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--source', choices=['modelscope', 'huggingface'], default='modelscope')
    args = parser.parse_args()
    manifest = json.loads((ROOT/'models/research-qwen3-4b.json').read_bytes())
    target = ROOT/'models'/manifest['file']
    if args.verify_only: return 0 if verify_weight(target, manifest) else 1
    last = -1
    def progress(value):
        nonlocal last
        percent = int(value['completed_bytes']*100/value['total_bytes'])
        if percent != last:
            print(json.dumps({**value, 'percent': percent}), flush=True); last = percent
    params = None
    if args.source == 'modelscope':
        params = {'Revision': manifest['modelscope_revision'], 'FilePath': Path(manifest['file']).name}
        manifest = {**manifest, 'url': 'https://www.modelscope.cn/api/v1/models/'+manifest['repository']+'/repo'}
    download_asset(manifest, target, progress=progress, params=params)
    return 0


if __name__ == '__main__': raise SystemExit(main())
