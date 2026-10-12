"""Prepare pinned official weights, preserving interrupted download progress."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.llm import deployment
from src.llm.preparation import download_asset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', choices=['1.7b','4b'], default='1.7b')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    manifest = deployment.model_manifest(args.size)
    target = deployment.ROOT/'models'/manifest['file']
    if args.verify_only: return 0 if deployment.verify_weight(target,manifest) else 1
    download_asset({**manifest,'url':'https://www.modelscope.cn/api/v1/models/'+manifest['repository']+'/repo'}, target,
                   params={'Revision':manifest['revision'],'FilePath':Path(manifest['file']).name},
                   progress=lambda value: print(value,flush=True))
    return 0

if __name__ == '__main__': raise SystemExit(main())
