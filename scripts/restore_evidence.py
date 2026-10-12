"""Restore a validated session backup into a new database, without overwriting evidence."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.storage import restore_evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore_evidence(args.source, args.destination), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
