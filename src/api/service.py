"""One local workstation per process, with serialized capture and explicit lifecycle."""

from pathlib import Path
from datetime import datetime, timezone
import hashlib
import math
import platform
import sqlite3
import threading
import time
import uuid

import cv2
import numpy as np

from src.pipeline import Monitor, ROOT
from src.datasets import DatasetStore, digest
from src.acquisition import AcquisitionStore
from src.composition import Composition
from src.review_study import ReviewStudyStore
from src.inspection.results import ResultStore, detection_record
from src.inspection.quality_gate import quality_reasons
from src.monitoring.image_analyzer import ImageQualityAnalyzer
from src.llm.management import ModelManager
from src.inspection.catalog import VisionCatalog

MEASUREMENT_FILES = [ROOT / path for path in ("src/pipeline.py", "src/datasets.py", "src/api/service.py", "src/config.py")]
MEASUREMENT_FILES.extend(sorted((ROOT / "src/monitoring").glob("*.py")))
MEASUREMENT_FILES.append(ROOT / "src/inspection/results.py")
MEASUREMENT_FILES.append(ROOT / "src/inspection/quality_gate.py")
MEASUREMENT_FILES.extend(ROOT / path for path in ('src/inspection/runtime.py', 'src/inspection/vision_model.py'))
MEASUREMENT_SOURCE_SHA256 = digest({p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in MEASUREMENT_FILES})


class Workstation:
    def __init__(self, database: Path | None = None):
        self.monitor = Monitor(database)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.running = False
        self.maintenance_busy = False
        self.write_requests = 0
        self.scenario = "none"
        self.intensity = 0.8
        self.models = ModelManager(self.monitor.store.path, self.monitor.settings['model'],
                                   self.lock, lambda: self.monitor.pending is not None or self.maintenance_busy)
        self.datasets = DatasetStore(self.monitor.store.path.parent / "datasets")
        self.acquisition = AcquisitionStore(self.monitor.store.path.parent / "acquisition", self.datasets)
        self.composition = Composition(self.datasets, self.acquisition)
        self.review_studies = ReviewStudyStore(self.monitor.store.path.parent / 'review-studies')
        self.preview = None
        self.preview_content: bytes | None = None
        self.preview_deadline = 0.0
        self.preview_error = ""
        self.acquisition_revision = 0
        self.results = ResultStore(self.monitor.store.path.parent / "inspection-results", self.datasets)
        self.replay = None
        self.vision_frame = None
        self.vision_loading = False
        self.vision_management_error = ''
        self.vision_catalog = VisionCatalog(self.monitor.store.path)
        self.monitor.open_source("synthetic")
        self.monitor.calibrate()
        for _ in range(12):
            self.sample()
        self.thread = threading.Thread(target=self._loop, name="workstation", daemon=True)

    def start(self):
        self.models.start_health()
        self.thread.start()

    def begin_maintenance(self):
        with self.lock:
            if (self.maintenance_busy or self.write_requests > 1 or self.running or self.vision_loading or
                    self.vision_frame is not None or self.monitor.pending is not None or self.models.operation):
                raise RuntimeError('请先暂停采集并等待其他保存、加载、复核或模型任务结束，再执行存储维护')
            self.maintenance_busy = True

    def end_maintenance(self):
        with self.lock: self.maintenance_busy = False

    def _loop(self):
        interval = self.monitor.settings["monitoring"]["refresh_seconds"]
        next_capture = time.monotonic()
        while not self.stop.wait(0.03):
            with self.lock:
                self.monitor.poll_review()
                if self.vision_frame is not None:
                    try:
                        self.finish_vision()
                    except (RuntimeError, ValueError, cv2.error):
                        self.running = False
                if self.running and self.vision_frame is None and time.monotonic() >= next_capture:
                    try:
                        self.sample()
                    except (RuntimeError, ValueError, cv2.error):
                        pass  # sample preserves the capture failure in state
                    next_capture = time.monotonic() + interval

    def sample(self):
        if self.vision_loading or self.vision_frame is not None:
            raise RuntimeError('视觉模型加载或上一帧推理进行中，请等待完成')
        self.clear_preview()
        try:
            if self.replay is None:
                frame = self.monitor.read()
                if self.monitor.vision is not None:
                    self.monitor.vision.submit(frame)
                    self.vision_frame = frame.copy()
                else:
                    self.monitor.process(frame, self.scenario, self.intensity)
            else:
                replay = self.replay
                if replay["position"] >= len(replay["samples"]):
                    raise RuntimeError("回放已完成，请在样本管理中重新建立回放")
                sample = replay["samples"][replay["position"]]
                frame = self.datasets.image(replay["dataset_id"], sample)
                package = replay.get("inspection_results")
                record = detection_record(package, sample, replay["position"]) if package else None
                self.monitor.process(frame, sample={**sample, "dataset_id": replay["dataset_id"]}, detection_record=record)
                replay["position"] += 1
                if replay["position"] == len(replay["samples"]):
                    self.running = False
            self.monitor.capture_error = ""
        except (RuntimeError, ValueError, cv2.error, sqlite3.Error, OSError) as exc:
            self.running = False
            self.monitor.alerts.interrupt()
            try:
                if self.monitor.capture_error != str(exc):
                    self.monitor.store.append(self.monitor.session, "capture_error", time.time(), {
                        "error": str(exc), "frame": self.monitor.frame_count,
                        "baseline_generation": self.monitor.baseline_generation,
                        "alert": self.monitor.alerts.snapshot(),
                    })
            except (sqlite3.Error, OSError) as storage_error:
                self.monitor.capture_error = f"{exc}；失败记录也无法保存：{storage_error}"
                raise RuntimeError(self.monitor.capture_error) from exc
            self.monitor.capture_error = str(exc)
            raise RuntimeError(str(exc)) from exc

    def finish_vision(self):
        record = self.monitor.vision.poll()
        if record is None: return
        frame, self.vision_frame = self.vision_frame, None
        try:
            self.monitor.process(frame, detection_record=record)
            self.monitor.capture_error = ''
        except (RuntimeError, ValueError, cv2.error, sqlite3.Error, OSError) as exc:
            self.running = False
            self.monitor.capture_error = str(exc)
            self.monitor.alerts.interrupt()
            raise RuntimeError(str(exc)) from exc

    def require_vision_idle(self):
        if self.vision_loading or self.vision_frame is not None:
            raise RuntimeError('请等待当前视觉模型加载／推理完成后操作')

    def activate_vision(self, runtime):
        self.require_vision_idle()
        if self.running or self.replay is not None:
            raise RuntimeError('请暂停监测并切回普通采集源，再连接视觉模型')
        if self.monitor.pending is not None:
            raise RuntimeError('语言模型复核进行中，请等待完成')
        self.monitor.reset_baseline('visual_detector_changed')
        previous = self.monitor.vision
        self.monitor.vision = runtime
        self.monitor.inspection_source = ({'kind': 'local_visual', 'provenance': runtime.producer['provenance'],
            'producer': runtime.producer, 'model_id': runtime.id} if runtime else
            {'kind': 'reference_residual_demo', 'provenance': 'synthetic_fixture'})
        self.scenario = 'none'; self.clear_preview()
        if previous is not None: previous.close()

    def clear_preview(self):
        self.preview = None
        self.preview_content = None
        self.preview_deadline = 0.0
        self.preview_error = ""

    def preview_capture(self):
        self.require_vision_idle()
        if self.running or self.replay is not None:
            raise RuntimeError("请暂停监测并切回普通采集源，再进行取景预检")
        self.clear_preview()
        try:
            frame = self.monitor.read()
            quality = ImageQualityAnalyzer().analyze(frame).to_dict()
            reasons = quality_reasons(quality)
            if any(not math.isfinite(value) for value in quality.values()):
                raise RuntimeError("取景指标无效")
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                raise RuntimeError("预检图像编码失败")
            properties = self.monitor.camera.get_properties()
            properties = {key: value if isinstance(value, (int, float)) and math.isfinite(value) else None
                          for key, value in properties.items()}
            preview = {"token": uuid.uuid4().hex, "created": datetime.now(timezone.utc).isoformat(),
                       "captured_timestamp": time.time(), "session": self.monitor.session,
                       "generation": self.monitor.baseline_generation, "source": self.monitor.source,
                       "source_properties": properties, "image_quality": quality,
                       "quality_reasons": reasons, "usable_for_baseline": not reasons,
                       "remaining_seconds": 60.0,
                       "normalization": "640x480 BGR; INTER_AREA; PNG"}
            self.preview_content = encoded.tobytes()
            self.preview_deadline = time.monotonic() + 60
            self.preview = preview
            return preview
        except (RuntimeError, ValueError, cv2.error, OSError) as exc:
            self.preview_error = str(exc)
            raise RuntimeError(str(exc)) from exc

    def save_preview(self, batch_id: str, token: str, split: str, origin: str, conditions: dict, label: dict):
        if self.running or self.replay is not None:
            raise RuntimeError("请暂停监测并切回普通采集源，再留存预览")
        preview = self.preview
        if (preview is None or token != preview["token"] or self.preview_content is None or
                preview["session"] != self.monitor.session or preview["generation"] != self.monitor.baseline_generation
                or time.monotonic() > self.preview_deadline):
            raise RuntimeError("预览已失效，请重新采集一帧再留存")
        if preview["source"] == "synthetic":
            origin = "synthetic"
        elif preview["source"] == "camera":
            origin = "real"
        record = self.acquisition.save(batch_id, preview, self.preview_content, split=split,
                                       origin=origin, conditions=conditions, label=label)
        self.acquisition_revision += 1
        return record

    def prepare_replay(self, dataset_id: str, result_id: str | None = None):
        """Validate before replacing the workstation; failure leaves the old session usable."""
        self.require_vision_idle()
        if self.running:
            raise RuntimeError("请先暂停当前监测，再建立回放")
        self.monitor.poll_review()
        if self.monitor.pending is not None:
            raise RuntimeError("模型复核进行中，请等待完成后切换回放")
        manifest = self.datasets.load(dataset_id)
        references = [s for s in manifest["samples"] if s["split"] == "baseline"]
        evaluations = [s for s in manifest["samples"] if s["split"] == "evaluation"]
        package = self.results.load(result_id) if result_id else None
        reference_records = None
        if package:
            if package["dataset_id"] != dataset_id:
                raise ValueError("检测结果包与所选数据集不匹配")
            reference_records = [detection_record(package, sample, i) for i, sample in enumerate(references)]
            if any(record.status != "ok" for record in reference_records):
                raise ValueError("基线检测结果不完整或存在失败，不能建立外部检测回放")
        # Preflight all assets, including evaluation frames, before changing the source.
        images = []
        for sample in manifest["samples"]:
            frame = self.datasets.image(dataset_id, sample)
            if sample["split"] == "baseline":
                images.append(frame)
        candidate = Monitor(self.monitor.store.path)
        candidate.source = "dataset"
        if package:
            candidate.inspection_source = {"kind": "external_results", "result_id": result_id,
                                           "provenance": package["producer"]["provenance"],
                                           "producer": package["producer"]}
        config = {
            "dataset_id": dataset_id, "baseline_ids": [s["id"] for s in references],
            "evaluation_ids": [s["id"] for s in evaluations],
            "window_size": candidate.settings["monitoring"]["window_size"],
            "alert_policy": {"recovery_samples": candidate.settings["monitoring"]["alert_recovery_samples"],
                             "complete_detection_window_required": True},
            "thresholds": candidate.detector.thresholds,
            "detector": candidate.inspection_source["kind"], "inspection_source": candidate.inspection_source,
            "normalization": manifest["normalization"],
            "software": {"python": platform.python_version(), "opencv": cv2.__version__, "numpy": np.__version__},
            "measurement_source_sha256": MEASUREMENT_SOURCE_SHA256,
        }
        fingerprint = digest(config)
        try:
            candidate.calibrate(reference_images=images, reference_records=reference_records,
                                provenance={"config": config, "fingerprint": fingerprint})
        except Exception:
            candidate.close()
            raise
        try:
            self.monitor.store.append_many(self.monitor.session, self.monitor.alert_closure("replay_replaced"))
        except Exception:
            candidate.close()
            raise
        self.monitor.close()
        self.monitor = candidate
        self.clear_preview()
        self.scenario = "none"
        self.replay = {"dataset_id": dataset_id, "manifest": manifest, "samples": evaluations,
                       "position": 0, "config": config, "fingerprint": fingerprint, "inspection_results": package}

    def open_source(self, mode: str, device: int, path: Path | None):
        self.require_vision_idle()
        if self.replay is not None:
            self.monitor.poll_review()
            if self.monitor.pending is not None:
                raise RuntimeError("模型复核进行中，请等待完成后切换采集源")
            candidate = Monitor(self.monitor.store.path)
            try:
                candidate.open_source(mode, device, path)
                self.monitor.store.append_many(self.monitor.session, self.monitor.alert_closure("source_changed"))
            except Exception:
                candidate.close()
                raise
            self.monitor.close()
            self.monitor = candidate
        else:
            self.monitor.open_source(mode, device, path)
        self.running = False
        self.clear_preview()
        self.replay = None
        self.scenario = "none"

    def replay_state(self):
        if self.replay is None:
            return None
        r = self.replay
        return {"dataset_id": r["dataset_id"], "name": r["manifest"]["name"],
                "position": r["position"], "total": len(r["samples"]),
                "completed": r["position"] == len(r["samples"]), "fingerprint": r["fingerprint"]}

    def replay_history(self):
        history = []
        for session in self.monitor.store.sessions(limit=100):
            baselines = self.monitor.store.events(session["session"], kind="baseline", limit=1)
            if baselines and "replay" in baselines[0]["payload"]:
                replay = baselines[0]["payload"]["replay"]
                history.append({**session, "dataset_id": replay["config"]["dataset_id"],
                                "fingerprint": replay["fingerprint"],
                                "inspection_source": replay["config"].get("inspection_source", {
                                    "kind": "reference_residual_demo", "provenance": "synthetic_fixture"})})
        return history

    def export_replay(self, session: str | None = None):
        session = session or self.monitor.session
        baselines = self.monitor.store.events(session, limit=1, kind="baseline")
        if not baselines or "replay" not in baselines[0]["payload"]:
            raise ValueError("此会话没有数据集回放")
        provenance = baselines[0]["payload"]["replay"]
        config = provenance["config"]
        manifest = self.datasets.load(config["dataset_id"])
        results = []
        for event in self.monitor.store.all_events(session, kind="frame"):
            payload = event["payload"]
            # Wall-clock timestamps and elapsed time are deliberately excluded from the comparison digest.
            measured = {"sample_id": payload["sample"]["id"], "image_sha256": payload["sample"]["sha256"],
                        "rule_report": payload["rule_report"], "warmup": payload["warmup"],
                        "window_count": payload["window_count"],
                        "detection": {k: v for k, v in payload["detection"].items() if k != "timestamp"}}
            results.append({**measured, "measurement_sha256": digest(measured),
                            "sample": payload["sample"], "vision_ms": payload["vision_ms"]})
        total = len(config["evaluation_ids"])
        return {"schema_version": 1, "session": session,
                "replay": {"dataset_id": config["dataset_id"], "name": manifest["name"],
                           "position": len(results), "total": total, "completed": len(results) == total,
                           "fingerprint": provenance["fingerprint"]},
                "config": config, "dataset": manifest, "results": results,
                "inspection_results": (self.results.load(config["inspection_source"]["result_id"])
                                       if config.get("inspection_source", {}).get("kind") == "external_results" else None),
                "results_sha256": digest([r["measurement_sha256"] for r in results]),
                "label_provenance": "imported_user_annotations_not_independently_verified",
                "scope": "Fixed input/order/config; no claim of ground-truth accuracy or deterministic model output."}

    def state(self, history_token=None):
        m = self.monitor
        token = f'{m.session}:{m.baseline_generation}:{m.frame_count}:{len(m.history)}'
        result = {
            "session": m.session, "running": self.running, "source": m.source,
            "maintenance_busy": self.maintenance_busy,
            "scenario": self.scenario, "intensity": self.intensity,
            "frame_count": m.frame_count, "baseline": m.baseline, "latest": m.latest,
            "history_token": token, "event_revision": m.store.revision(m.session), "capture_error": m.capture_error,
            "replay": self.replay_state(),
            "inspection_source": m.inspection_source,
            "vision_management_error": self.vision_management_error,
            "vision_runtime": {'status': 'loading', 'pending': False, 'error': ''} if self.vision_loading else
                              m.vision.state() if m.vision else {'status': 'disabled', 'pending': False, 'error': ''},
            "acquisition": {"preview": None if self.preview is None else {
                                **self.preview, "remaining_seconds": max(0.0, self.preview_deadline - time.monotonic())},
                            "error": self.preview_error,
                            "revision": self.acquisition_revision},
            "alert": m.alerts.snapshot(), "baseline_attempt": m.baseline_attempt,
            "thresholds": m.detector.thresholds, "baseline_generation": m.baseline_generation,
            "model": {**self.models.snapshot(), "pending": m.pending is not None,
                      "review_error": m.review_error},
        }
        if history_token != token: result['history'] = list(m.history)
        return result

    def close(self):
        self.stop.set()
        try:
            self.models.close()
        finally:
            if self.thread.is_alive():
                self.thread.join(timeout=10)
            with self.lock:
                self.running = False
                self.monitor.close()
