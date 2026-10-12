"""CLI entry point with reliable subprocess exit codes."""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--benchmark", action="store_true", help="Run the real-model benchmark")
    parser.add_argument("--api-only", action="store_true", help="Start the API for Vite development")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--database", type=Path, help="Use a separate evidence database, including a restored backup")
    args = parser.parse_args()
    if args.test:
        command = [sys.executable, "-X", "utf8", "-m", "pytest", "tests", "-q"]
    elif args.benchmark:
        command = [sys.executable, "-X", "utf8", "scripts/benchmark.py"]
    else:
        if not 1 <= args.port <= 65535:
            parser.error("port must be between 1 and 65535")
        if not args.api_only and not (ROOT / "frontend/dist/index.html").is_file():
            parser.error("Build the frontend first: npm ci --prefix frontend && npm run build --prefix frontend")
        port = args.port
        while port < 65535:
            with socket.socket() as listener:
                try:
                    listener.bind(("127.0.0.1", port))
                    break
                except OSError:
                    port += 1
        if port >= 65535:
            raise RuntimeError("No available local port")
        print(f"Spark Guard: http://127.0.0.1:{port}", flush=True)
        command = [sys.executable, "-m", "uvicorn", "src.api.app:app",
                   "--host", "127.0.0.1", "--port", str(port), "--workers", "1"]
    environment = dict(os.environ)
    if args.database:
        environment['SPARK_DATABASE'] = str(args.database.expanduser().resolve())
    return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
