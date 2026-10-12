"""Dedicated loopback browser-acceptance server; temporary database never touches normal runtime evidence."""

import argparse
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import uvicorn
    from src.api.app import create_app
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8503)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535: parser.error('port must be 1024..65535')
    with tempfile.TemporaryDirectory(prefix='spark-acceptance-') as temporary:
        uvicorn.run(create_app(Path(temporary) / 'evidence.db'), host='127.0.0.1', port=args.port,
                    log_level='warning', access_log=False)


if __name__ == '__main__': main()
