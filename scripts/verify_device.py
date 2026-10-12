"""Real camera/local inference evidence, without storing camera pixels."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline import CalibrationError, Monitor, ReviewFailure, review_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--models", nargs="+", default=["spark-drift:1.7b-q4", "spark-drift:4b-q4"])
    args = parser.parse_args()
    monitor = Monitor(ROOT / "artifacts/device-validation.db")
    results = []
    try:
        backend = "dshow" if platform.system() == "Windows" else "auto"
        monitor.open_source("camera", device=args.device, backend=backend)
        # Give exposure time to settle before collecting the normal reference.
        for _ in range(10):
            monitor.read()
        monitor.calibrate(20)
        acquisition = []
        for _ in range(30):
            start = time.perf_counter()
            monitor.process(monitor.read())
            acquisition.append((time.perf_counter() - start) * 1000)
        snapshot = monitor.snapshot()
        for model in args.models:
            try:
                result = review_snapshot(
                    snapshot, "真实摄像头采集，无独立产品标签或环境传感器。只核验采集与推理链路。",
                    model, "http://127.0.0.1:11435",
                )
                results.append(result)
            except ReviewFailure as exc:
                results.append({"status": "error", "model": model, **exc.evidence})
        with httpx.Client(trust_env=False, timeout=10) as client:
            loaded = client.get("http://127.0.0.1:11435/api/ps")
            loaded.raise_for_status()
        evidence = {
            "observed": time.time(), "source": "camera", "software_injection": False,
            "camera_index": args.device, "backend": backend, "frame_dimensions": [640, 480],
            "baseline_samples": 20, "measurement_samples": 30,
            "acquisition_and_analysis_ms": {
                "p50": float(np.percentile(acquisition, 50)),
                "p95": float(np.percentile(acquisition, 95)),
            },
            "reviews": results, "loaded_models": loaded.json(),
            "saved_camera_pixels": False,
            "limitations": [
                "Camera content has not been visually reviewed or independently labeled.",
                "This proves acquisition/local inference, not product-defect or factory performance.",
                "No physical fault was applied; no disconnected-network or power measurement.",
            ],
        }
        destination = ROOT / "artifacts/device-camera.json"
        destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps({
            "source": "camera", "frames": 30, "pixel_files_saved": False,
            "reviews": [
                {"model": review.get("inference", {}).get("model", review.get("model")),
                 "status": review.get("status", "completed"),
                 "elapsed_ms": review.get("inference", {}).get("elapsed_ms"),
                 "evidence_warnings": len(review.get("evidence_warnings", []))}
                for review in results
            ],
            "evidence_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }, ensure_ascii=True))
        return int(any(review.get("status") == "error" for review in results))
    except CalibrationError as exc:
        evidence = {
            "observed": time.time(), "source": "camera", "camera_index": args.device,
            "backend": backend, "camera_opened": True, "frames_received": True,
            "source_signal_usable": False, "status": "calibration_rejected",
            "baseline_metrics": exc.metrics, "error": str(exc),
            "saved_camera_pixels": False, "reviews": [],
            "limitations": [
                "Camera acquisition is available but the sampled scene is too dark or lacks texture.",
                "No valid calibrated camera/model workflow or industrial evaluation was established.",
            ],
        }
        (ROOT / "artifacts/device-camera.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(json.dumps(evidence, ensure_ascii=True))
        return 2
    finally:
        monitor.close()


if __name__ == "__main__":
    raise SystemExit(main())
