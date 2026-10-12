"""Restore an owned workspace into an exclusive new directory, with models inactive."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.workspace import restore_workspace

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore_workspace(args.source, args.destination), ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
