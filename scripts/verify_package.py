"""Historical source-root ZIP verifier, not the current competition bundle verifier.

This legacy format rejects prebuilt dist files and expects source at ZIP root.
It cannot validate the current single-top-directory competition materials ZIP.
Use the current outer file manifest and submission instructions instead.
"""

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", dest="bundle")
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".uv-cache")
    parser.add_argument("--npm-cache", type=Path, default=ROOT / ".cache/npm")
    parser.add_argument("--online", action="store_true", help="Allow missing dependencies to be downloaded")
    args = parser.parse_args()
    if args.bundle:
        bundle = Path(args.bundle)
    else:
        report = json.loads((ROOT / "artifacts/submission/build-report.json").read_text(encoding="utf-8"))
        bundle = ROOT / "artifacts/submission" / report["zip"]
    destination = ROOT / "artifacts/reproduction" / uuid.uuid4().hex[:12]
    destination.mkdir(parents=True, exist_ok=False)
    if not destination.resolve().is_relative_to(ROOT.resolve()):
        raise RuntimeError("Reproduction directory escaped the project")
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("ZIP failed its CRC check")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("ZIP has duplicate entries")
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename:
                raise RuntimeError("Unsafe ZIP path")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise RuntimeError("ZIP contains a symlink")
            if any(part in {".venv", "runtime", "__pycache__", "node_modules", "dist"} for part in path.parts):
                raise RuntimeError("ZIP contains runtime/cache data")
            if path.suffix.lower() in {".gguf", ".db", ".log", ".pyc", ".part"}:
                raise RuntimeError("ZIP contains a weight/database/log")
            source = ROOT / entry.filename
            if not source.is_file() or archive.read(entry) != source.read_bytes():
                raise RuntimeError(f"Stale or unrecognized packaged source: {entry.filename}")
        if archive.read("requirements-lock.txt") != (ROOT / "requirements-lock.txt").read_bytes():
            raise RuntimeError("Dependency lock does not match the project")
        for required in ("frontend/package-lock.json", "frontend/package.json", "frontend/src/App.tsx"):
            if required not in names:
                raise RuntimeError(f"Missing frontend source: {required}")
        archive.extractall(destination)
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for this offline reproduction check")
    cache_args = ["--cache-dir", str(args.cache_dir.resolve())]
    network_args = [] if args.online else ["--offline"]
    subprocess.run([uv, *cache_args, "venv", "--python", sys.executable, ".venv"],
                   cwd=destination, check=True)
    python = destination / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    subprocess.run([uv, *cache_args, "pip", "sync", *network_args, "--python", str(python),
                    "requirements-lock.txt"], cwd=destination, check=True)
    subprocess.run([uv, *cache_args, "pip", "check", "--python", str(python)],
                   cwd=destination, check=True)
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("Node.js and npm are required to reproduce the frontend")
    subprocess.run([npm, "ci", "--prefix", "frontend", "--cache", str(args.npm_cache.resolve()),
                    *network_args, "--no-audit", "--no-fund"], cwd=destination, check=True)
    subprocess.run([npm, "run", "build", "--prefix", "frontend"], cwd=destination, check=True)
    junit = ROOT / "artifacts/reproduction-tests.xml"
    result = subprocess.run([str(python), "-B", "-X", "utf8", "-m", "pytest", "tests",
                             "-q", "-p", "no:cacheprovider", "--junitxml=" + str(junit)],
                            cwd=destination, check=False)
    suites = ElementTree.parse(junit).getroot()
    counters = {key: sum(int(suite.get(key, "0")) for suite in suites.iter("testsuite"))
                for key in ("tests", "failures", "errors", "skipped")}
    evidence = {
        "observed": time.time(), "zip": bundle.name, "zip_integrity": True,
        "source_files_current": True, "weight_cache_database_excluded": True,
        "fresh_environment": True, "dependency_install": "network allowed" if args.online else "offline uv/npm caches",
        "frontend_build": True,
        "test_result": counters, "test_exit_code": result.returncode,
        "reproduction_directory": destination.relative_to(ROOT).as_posix(),
        "scope": "Fresh Python/npm dependencies, frontend build and tests from isolated ZIP source; not a second-device, browser or offline-model test.",
    }
    (ROOT / "artifacts/package-verification.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=True))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
