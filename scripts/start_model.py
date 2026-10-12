"""Run a foreground loopback Ollama service using the shared ownership controller."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.llm.deployment import preflight
from src.llm.runtime import OwnedRuntime


def serve(size, port, executable=None):
    runtime = OwnedRuntime(ROOT / 'runtime')
    try:
        runtime.start(size, port, executable)
        print(json.dumps(runtime.report, ensure_ascii=False, indent=2), flush=True)
        print('Local Spark ready. Keep this terminal open; Ctrl+C stops this service.', flush=True)
        code = runtime.process.wait()
        if code: raise RuntimeError(f'Ollama exited with code {code}; inspect {runtime.log_path}')
    finally:
        runtime.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', choices=['1.7b', '4b'], default='1.7b')
    parser.add_argument('--port', type=int, default=11435)
    parser.add_argument('--ollama-exe', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        if args.check:
            result = preflight(args.size, args.ollama_exe)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(0 if result['ready'] else 1)
        serve(args.size, args.port, args.ollama_exe)
    except KeyboardInterrupt:
        pass
