"""Measured local inference evidence; synthetic cases are not field validation."""

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import time

import httpx
import numpy as np
import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.pipeline import Monitor, review_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", nargs="+", default=["none", "focus_change", "light_fade", "position_shift"])
    parser.add_argument("--output", default="artifacts/benchmark.json")
    parser.add_argument("--model", default="spark-drift:1.7b-q4")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11435")
    args = parser.parse_args()
    cases = []
    for scenario in args.scenarios:
        monitor = Monitor(ROOT / "artifacts/benchmark.db")
        try:
            monitor.open_source("synthetic")
            monitor.calibrate()
            for _ in range(30):
                monitor.process(monitor.read(), scenario, 0.7)
            snapshot = monitor.snapshot()
            result = review_snapshot(snapshot, "近期没有维护记录；没有温湿度传感器。", args.model, args.endpoint)
            result["scenario_ground_truth"] = scenario
            result["rule_analysis"] = monitor.latest["rule_report"]
            result["vision_latency_ms"] = {
                "p50": float(np.percentile([x["vision_ms"] for x in monitor.history], 50)),
                "p95": float(np.percentile([x["vision_ms"] for x in monitor.history], 95)),
            }
            cases.append(result)
            print(json.dumps({"scenario": scenario, "model_type": result["analysis"]["drift_type"],
                              "inference_ms": result["inference"]["elapsed_ms"],
                              "root_cause": result["analysis"]["root_cause"]}, ensure_ascii=True), flush=True)
        finally:
            monitor.close()
    with httpx.Client(trust_env=False) as client:
        loaded = client.get(args.endpoint + "/api/ps").json()
    evidence = {
        "observed": time.time(), "platform": platform.system(), "python": platform.python_version(),
        "cpu_logical": os.cpu_count(), "memory_total_bytes": psutil.virtual_memory().total,
        "model_manifest": json.loads((ROOT / "models" / ("manifest-4b.json" if "4b" in args.model else "manifest.json")).read_text(encoding="utf-8")),
        "loaded_model_evidence": loaded,
        "cases": cases,
        "limitations": [
            "Synthetic frames and software-injected perturbations only; no factory validation.",
            "One sample per scenario; not an accuracy estimate or latency distribution.",
            "Rule/model comparison is descriptive; no claim of model irreplaceability.",
            "No network-disconnection or physical power measurement performed.",
        ],
    }
    target = ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
