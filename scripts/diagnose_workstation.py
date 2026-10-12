"""Read the same diagnostic package as the UI, or inspect installed dependencies offline."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from src.diagnostics import workstation_diagnostics
from src.llm.spark_client import SparkXClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', help='Running loopback workstation, e.g. http://127.0.0.1:8501; omit for offline dependencies')
    parser.add_argument('--output', type=Path, help='New JSON file; existing files are never overwritten')
    args = parser.parse_args()
    if args.endpoint:
        endpoint = SparkXClient(base_url=args.endpoint).base_url
        with httpx.Client(trust_env=False, timeout=20) as client:
            response = client.get(endpoint + '/api/diagnostics'); response.raise_for_status(); report = response.json()
    else: report = workstation_diagnostics()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        with args.output.open('x', encoding='utf-8') as output: output.write(encoded)
    else: print(encoded)

if __name__ == '__main__': main()
