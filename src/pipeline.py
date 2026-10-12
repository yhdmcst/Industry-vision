"""Local measurement pipeline. Model review never controls a physical device."""

from collections import deque
from copy import deepcopy
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
import base64
import hashlib
import json
import sqlite3
from pathlib import Path
import threading
import time
import uuid
from typing import Any

import cv2
import numpy as np

from src.inspection.camera import Camera, CameraConfig, DummyCamera, VideoFileCamera
from src.inspection.simulator import DriftScenario, create_simulator
from src.inspection.quality_gate import quality_reasons
from src.llm import SparkXClient, ResponseParser
from src.llm.prompt_builder import build_review_prompt
from src.llm.evidence_guard import evidence_warnings
from src.monitoring import DetectionRecord, DriftDetector
from src.monitoring.alert_tracker import AlertTracker
from src.storage import EvidenceStore
from src.config import load_settings

ROOT = Path(__file__).resolve().parent.parent
MODEL_LOCK = threading.Lock()
REVIEW_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spark-review")


class ReviewFailure(RuntimeError):
    def __init__(self, message: str, evidence: dict[str, Any]):
        super().__init__(message)
        self.evidence = evidence


class CalibrationError(RuntimeError):
    def __init__(self, message: str, metrics: dict[str, float]):
        super().__init__(message)
        self.metrics = metrics


def report_dict(report) -> dict[str, Any]:
    result = asdict(report)
    result["drift_type"] = report.drift_type.value
    return result


def review_snapshot(snapshot: dict[str, Any], context: str, model: str, endpoint: str,
                    thinking: bool = False, deployment: dict | None = None, policy: dict | None = None) -> dict[str, Any]:
    prompt = build_review_prompt(snapshot, context)
    with MODEL_LOCK:
        client = SparkXClient(model, base_url=endpoint, policy=policy)
        prompt_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        try:
            raw = client.generate(prompt, max_tokens=2048 if thinking else 1024,
                                  temperature=0.2, thinking=thinking)
            result = ResponseParser.parse_drift_analysis(raw)
        except (ValueError, RuntimeError) as exc:
            raise ReviewFailure(str(exc), {
                "error": str(exc), "snapshot": snapshot, "operator_context": context[:2000],
                "raw_response": client.last_response, "inference": client.last_metrics, "deployment": deployment, "policy": deepcopy(client.policy),
                "prompt": prompt, "prompt_sha256": prompt_digest, "created": time.time(),
            }) from exc
        return {"analysis": result, "raw_response": raw, "inference": client.last_metrics,
                "snapshot": snapshot, "operator_context": context[:2000], "deployment": deployment, "policy": deepcopy(client.policy),
                "created": time.time(), "provenance": "local_official_model",
                "evidence_warnings": evidence_warnings(snapshot, result),
                "prompt": prompt, "prompt_sha256": prompt_digest, "review_id": uuid.uuid4().hex}


class Monitor:
    def __init__(self, db_path: Path | None = None):
        self.settings = load_settings()
        self.store = EvidenceStore(db_path or ROOT / self.settings["storage"]["database"])
        self.session = uuid.uuid4().hex
        self.camera: Camera | None = None
        self.source = "synthetic"
        self.injected = False
        self.detector = DriftDetector({"window_size": self.settings["monitoring"]["window_size"]})
        self.baseline: dict[str, Any] | None = None
        self.baseline_frame: np.ndarray | None = None
        self.reference_gray: np.ndarray | None = None
        self.last_frame: np.ndarray | None = None
        self.latest: dict[str, Any] | None = None
        self.history: deque = deque(maxlen=300)
        self.frame_count = 0
        self.review: dict[str, Any] | None = None
        self.review_error = ""
        self.review_failure: dict[str, Any] | None = None
        self.capture_error = ""
        self.assessment: dict[str, Any] | None = None
        self.pending: Future | None = None
        self.simulator = None
        self.simulator_key = None
        self.baseline_generation = 0
        self.pending_generation = 0
        self.pending_incident_id: int | None = None
        self.previous_frame: np.ndarray | None = None
        self.alerts = AlertTracker(self.settings["monitoring"]["alert_recovery_samples"])
        self.baseline_attempt: dict[str, Any] | None = None
        self.inspection_source = {"kind": "reference_residual_demo", "provenance": "synthetic_fixture"}
        self.vision = None

    def open_source(self, mode: str, device: int = 0, video: Path | None = None,
                    backend: str = "auto") -> None:
        if mode not in ("synthetic", "video", "camera") or (mode == "video" and video is None):
            raise ValueError("Choose a valid capture source; video mode requires a file")
        candidate = DummyCamera() if mode == "synthetic" else (
            VideoFileCamera(video, loop=False) if mode == "video" and video else Camera(CameraConfig(device_id=device, backend=backend))
        )
        if not candidate.open():
            candidate.close()
            raise RuntimeError("Cannot open the selected camera/video source")
        try:
            self.reset_baseline("source_changed")
        except Exception:
            candidate.close()
            raise
        if self.camera:
            self.camera.close()
        self.camera = candidate
        self.source = mode

    def alert_closure(self, reason: str) -> list[tuple[str, float, dict]]:
        if not self.alerts.active:
            return []
        return [("incident_closed", time.time(), {**self.alerts.snapshot(),
                 "incident_id": self.alerts.episode["incident_id"], "reason": reason,
                 "frame": self.frame_count, "baseline_generation": self.baseline_generation})]

    def reset_baseline(self, reason: str = "baseline_reset") -> None:
        self.store.append_many(self.session, self.alert_closure(reason))
        self._clear_baseline()

    def _clear_baseline(self) -> None:
        self.baseline_generation += 1
        self.baseline = None
        self.baseline_frame = None
        self.last_frame = None
        self.latest = None
        self.review = None
        self.review_error = ""
        self.review_failure = None
        self.capture_error = ""
        self.assessment = None
        self.previous_frame = None
        self.alerts = AlertTracker(self.settings["monitoring"]["alert_recovery_samples"])
        self.baseline_attempt = None
        self.history.clear()
        self.reference_gray = None
        self.detector = DriftDetector({"window_size": self.settings["monitoring"]["window_size"]})

    def read(self) -> np.ndarray:
        if not self.camera:
            raise RuntimeError("No capture source is open")
        ok, image = self.camera.read()
        if not ok or image is None:
            raise RuntimeError("Capture ended or camera disconnected")
        return cv2.resize(image, (640, 480), interpolation=cv2.INTER_AREA)

    def detection(self, frame: np.ndarray) -> DetectionRecord:
        if self.vision is not None:
            return self.vision.infer(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if self.reference_gray is None:
            self.reference_gray = gray.copy()
        return self._reference_detection(gray, self.reference_gray)

    @staticmethod
    def _reference_detection(gray: np.ndarray, reference: np.ndarray) -> DetectionRecord:
        # Full-frame reference residual is a demo proxy, not a trained defect classifier.
        delta = float(np.mean(cv2.absdiff(gray, reference))) / 255
        score = float(np.clip(1 - delta * 4, 0, 1))
        return DetectionRecord(time.time(), score >= 0.75, score, score < 0.75,
                               {"detector": "reference_residual_demo", "residual": delta})

    def calibrate(self, count: int = 20, note: str = "", *,
                  reference_images: list[np.ndarray] | None = None,
                  provenance: dict[str, Any] | None = None,
                  reference_records: list[DetectionRecord] | None = None) -> None:
        if reference_images is not None:
            count = len(reference_images)
        if not 10 <= count <= 100:
            raise ValueError("Baseline sample count must be 10..100")
        if reference_records is not None and (len(reference_records) != count or any(r.status != "ok" for r in reference_records)):
            raise ValueError("外部基线结果必须逐样本对齐且全部成功")
        if self.inspection_source["kind"] == "external_results" and reference_records is None:
            raise ValueError("外部检测模式必须提供基线检测结果")
        images, records, sample_metrics, rejected = [], [], [], []
        candidate = DriftDetector({"window_size": self.settings["monitoring"]["window_size"]})
        attempt = {"created": time.time(), "requested_samples": count, "valid_samples": 0,
                   "rejected_samples": rejected, "status": "rejected", "error": "",
                   "retained_generation": self.baseline_generation if self.baseline else None}
        try:
            for index in range(count):
                image = self.read() if reference_images is None else reference_images[index]
                if image is None or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or not image.size:
                    raise ValueError("Baseline requires non-empty uint8 BGR images")
                if images and image.shape != images[0].shape:
                    raise ValueError("Baseline frame dimensions must match")
                image = image.copy()
                quality = candidate.image_analyzer.analyze(image).to_dict()
                reasons = quality_reasons(quality)
                if reasons:
                    rejected.append({"index": index + 1, "reasons": reasons, "image_quality": quality})
                else:
                    attempt["valid_samples"] += 1
                images.append(image)
                sample_metrics.append(quality)
            if rejected:
                raise CalibrationError(
                    f"基线质量门拒绝 {len(rejected)}/{count} 帧：过暗、过曝或缺少纹理；旧基线保持不变。",
                    rejected[0]["image_quality"],
                )
            reference_gray = cv2.cvtColor(images[0], cv2.COLOR_BGR2GRAY)
            records = (reference_records if reference_records is not None else
                       [self.detection(image) for image in images] if self.vision is not None else
                       [self._reference_detection(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), reference_gray)
                        for image in images])
            if any(record.status != 'ok' for record in records):
                raise RuntimeError('视觉基线检测失败／超时，旧基线保持不变；核验模型后重试')
            candidate.set_baseline(images, records)
            ok, encoded = cv2.imencode(".png", images[0])
            if not ok:
                raise RuntimeError("Unable to encode baseline")
        except (RuntimeError, ValueError, cv2.error) as exc:
            attempt["error"] = str(exc)
            self.baseline_attempt = attempt
            try:
                self.store.append(self.session, "baseline_rejected", attempt["created"], attempt)
            except (sqlite3.Error, OSError) as storage_error:
                attempt["error"] += f"；拒绝记录无法保存：{storage_error}"
                raise RuntimeError(attempt["error"]) from exc
            raise
        baseline = {
            "sample_count": len(images), "source": self.source, "injected": False,
            "image_quality": candidate.image_analyzer.baseline.to_dict(),
            "consistency": candidate.consistency_tracker.baseline.to_dict(),
            "frame_sha256": hashlib.sha256(encoded.tobytes()).hexdigest(),
            "created": time.time(), "generation": self.baseline_generation + 1,
            "quality_samples": sample_metrics, "operator_note": note.strip()[:2000],
            "inspection_source": self.inspection_source,
            "quality_gate": {"status": "passed", "valid_samples": count, "rejected_samples": 0,
                             "policy": "all_samples", "brightness_range_exclusive": [10, 245],
                             "minimum_contrast": 1},
        }
        if provenance is not None:
            baseline["replay"] = provenance
        # Persist the candidate and supersession together before publishing live state.
        try:
            self.store.append_many(self.session, self.alert_closure("baseline_replaced") +
                                   [("baseline", baseline["created"], baseline)])
        except (sqlite3.Error, OSError) as exc:
            attempt["error"] = f"基线证据保存失败，旧基线保持不变：{exc}"
            self.baseline_attempt = attempt
            raise RuntimeError(attempt["error"]) from exc
        self._clear_baseline()
        self.detector = candidate
        self.reference_gray = reference_gray.copy()
        self.baseline_frame = images[0]
        self.last_frame = images[-1]
        self.baseline = baseline
        self.baseline_attempt = {**attempt, "status": "passed", "retained_generation": None,
                                 "generation": self.baseline_generation}

    def process(self, frame: np.ndarray, scenario: str = "none", intensity: float = 0.5,
                *, sample: dict[str, Any] | None = None,
                detection_record: DetectionRecord | None = None) -> dict[str, Any]:
        if not self.baseline:
            raise RuntimeError("A baseline is required")
        if self.inspection_source["kind"] == "external_results" and detection_record is None:
            raise RuntimeError("外部检测结果不可用，禁止回退至演示代理")
        if self.vision is not None and scenario != 'none':
            raise RuntimeError('实时视觉模式不允许叠加未对齐的演示扰动')
        start = time.perf_counter()
        self.injected = scenario != "none" and intensity > 0
        if self.injected:
            key = (scenario, intensity)
            if self.simulator_key != key:
                options = {"direction": "right"} if scenario == "position_shift" else {}
                self.simulator = create_simulator(DriftScenario(scenario), intensity, **options)
                self.simulator_key = key
            frame = self.simulator.apply(frame)
        if sample is not None:
            self.injected = sample["perturbation"] != "none"
        record = self.detection(frame) if detection_record is None else detection_record
        report = self.detector.analyze(frame, record)
        availability = self.detector.consistency_tracker.availability()
        previous = (self.frame_count, self.previous_frame, self.last_frame, self.latest)
        previous_alerts = deepcopy(self.alerts)
        self.frame_count += 1
        self.previous_frame = self.last_frame
        self.last_frame = frame
        self.latest = {
            "frame": self.frame_count, "created": time.time(), "source": self.source,
            "synthetic": sample["origin"] == "synthetic" if sample else self.source == "synthetic",
            "injected": self.injected,
            "scenario": sample["perturbation"] if sample else scenario if self.injected else "none",
            "intensity": None if sample and self.injected else intensity if self.injected else 0,
            "baseline_generation": self.baseline_generation,
            "window_count": len(self.detector.consistency_tracker.records),
            "warmup": not availability["ready"],
            "detection_availability": availability,
            "inspection_source": self.inspection_source,
            "rule_report": report_dict(report),
            "vision_ms": round((time.perf_counter() - start) * 1000, 2),
            "detection": asdict(record),
        }
        if sample is not None:
            # Metadata and labels are retained separately from the model snapshot.
            self.latest["sample"] = sample
        transition = self.alerts.observe(self.frame_count, self.baseline_generation, report.drift_type.value,
                                         report.drift_detected, record.status, availability["ready"])
        self.latest["alert"] = self.alerts.snapshot()
        try:
            with self.store.connect() as db:
                if transition == "opened":
                    trigger = "inspection_unavailable" if record.status != "ok" else "rule_transition"
                    incident_id = self.capture_incident(trigger, connection=db)
                    self.alerts.episode["incident_id"] = incident_id
                    self.latest["alert"] = self.alerts.snapshot()
                elif transition == "recovered":
                    self.store.append(self.session, "incident_recovered", self.latest["created"], {
                        "incident_id": self.alerts.episode["incident_id"], "frame": self.frame_count,
                        "baseline_generation": self.baseline_generation, "reason": "consecutive_clear_frames",
                        "alert": self.alerts.snapshot(), "snapshot": self.snapshot(),
                    }, connection=db)
                elif transition == "updated":
                    self.store.append(self.session, "incident_updated", self.latest["created"], {
                        "incident_id": self.alerts.episode["incident_id"], "frame": self.frame_count,
                        "baseline_generation": self.baseline_generation, "reason": "new_evidence_kind",
                        "trigger": "inspection_unavailable" if record.status != "ok" else "rule_transition",
                        "alert": self.alerts.snapshot(), "snapshot": self.snapshot(),
                        "rule_report": self.latest["rule_report"], "detection": self.latest["detection"],
                    }, connection=db)
                self.store.append(self.session, "frame", self.latest["created"], self.latest, connection=db)
        except (RuntimeError, ValueError, cv2.error, sqlite3.Error, OSError) as exc:
            self.frame_count, self.previous_frame, self.last_frame, self.latest = previous
            self.alerts = previous_alerts
            self.alerts.interrupt()
            # A failed observation breaks continuity; do not reuse its window as complete evidence.
            self.detector.consistency_tracker.records.clear()
            raise RuntimeError(f"测量证据保存失败，监测已暂停：{exc}") from exc
        self.history.append(self.latest)
        return self.latest

    def capture_incident(self, trigger: str = "operator_bookmark", *,
                         connection: sqlite3.Connection | None = None) -> int:
        if self.latest is None or self.baseline is None:
            raise RuntimeError("A measured frame and baseline are required")
        def encode(frame):
            if frame is None:
                return None
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                raise RuntimeError("Unable to encode incident evidence")
            return base64.b64encode(encoded).decode("ascii")
        payload = {
            "trigger": trigger, "frame": self.latest["frame"],
            "baseline_generation": self.baseline_generation,
            "source": self.source, "synthetic": self.latest["synthetic"],
            "injected": self.latest["injected"], "scenario": self.latest["scenario"],
            "snapshot": self.snapshot(), "rule_report": self.latest["rule_report"],
            "detection": self.latest["detection"], "inspection_source": self.inspection_source,
            "detection_availability": self.latest["detection_availability"],
            "images": {"current": encode(self.last_frame), "previous": encode(self.previous_frame),
                       "baseline": encode(self.baseline_frame)},
        }
        if "sample" in self.latest:
            payload["sample"] = self.latest["sample"]
        return self.store.append(self.session, "incident", time.time(), payload, connection=connection)

    def record_incident_assessment(self, session: str, incident_id: int, outcome: str, note: str) -> int:
        incident = self.store.event(session, incident_id)
        if incident["kind"] != "incident":
            raise ValueError("Assessment must reference an incident")
        if outcome not in ("confirmed_change", "false_alarm", "insufficient_evidence"):
            raise ValueError("Unknown incident outcome")
        if not note.strip():
            raise ValueError("请填写核验依据，不能只保存状态。")
        return self.store.append(session, "incident_assessment", time.time(), {
            "incident_id": incident_id, "outcome": outcome, "note": note.strip()[:2000],
            "frame": incident["payload"]["frame"],
            "baseline_generation": incident["payload"]["baseline_generation"],
            "provenance": "operator_supplied_not_independently_verified",
        })

    def snapshot(self) -> dict[str, Any]:
        if not self.latest:
            raise RuntimeError("No measurement is available")
        # Ground-truth scenario labels are withheld from model inference.
        safe = {k: v for k, v in self.latest.items()
                if k not in ("scenario", "intensity", "rule_report", "sample")}
        safe["detection"] = {k: self.latest["detection"][k]
                             for k in ("detected", "confidence", "is_ng", "status")}
        safe["inspection_source"] = {k: self.inspection_source[k] for k in ("kind", "provenance")}
        if self.inspection_source.get('producer'):
            safe['inspection_source']['score_semantics'] = self.inspection_source['producer']['score_semantics']
        metrics = self.latest["rule_report"]["metrics"]
        safe["current_metrics"] = {
            "image_quality": metrics["image_quality"],
            "consistency": metrics["consistency"],
            "relative_changes": metrics["image_drift"].get("changes", {}),
            "registration": metrics["image_drift"].get("registration", {}),
        }
        safe["baseline"] = {
            key: self.baseline[key] for key in ("sample_count", "image_quality", "consistency")
        }
        safe["recent_trend"] = [
            {"frame": item["frame"], "confidence": item["detection"]["confidence"],
             "sharpness": item["rule_report"]["metrics"]["image_quality"]["sharpness"],
             "brightness": item["rule_report"]["metrics"]["image_quality"]["brightness"]}
            for item in (list(self.history) if self.history and self.history[-1] is self.latest
                         else [*self.history, self.latest])[-5:]
        ]
        safe["limitation"] = ("Imported upstream predictions, not independent ground truth; no environmental sensors."
                              if self.inspection_source["kind"] in ("external_results", "local_visual") else
                              "Reference-residual demo detector; no product defect ground truth or environmental sensors.")
        return json.loads(json.dumps(safe, allow_nan=False))

    def request_review(self, context: str, model: str, endpoint: str, thinking: bool = False,
                       incident_id: int | None = None, deployment: dict | None = None, policy: dict | None = None) -> None:
        if self.pending and not self.pending.done():
            raise RuntimeError("A review is already pending")
        snapshot = self.snapshot() if incident_id is None else self.store.event(self.session, incident_id)
        if incident_id is not None:
            if snapshot["kind"] != "incident":
                raise ValueError("Model review must reference an incident")
            snapshot = snapshot["payload"]["snapshot"]
        self.review = None
        self.review_error = ""
        self.review_failure = None
        self.assessment = None
        self.pending_generation = self.baseline_generation
        self.pending_incident_id = incident_id
        self.pending = REVIEW_POOL.submit(review_snapshot, snapshot, context, model, endpoint, thinking, deepcopy(deployment), deepcopy(policy))

    def poll_review(self) -> None:
        if not self.pending or not self.pending.done():
            return
        pending, self.pending = self.pending, None
        try:
            result = pending.result()
            if self.pending_generation != self.baseline_generation:
                self.review_error = "Baseline changed; stale model answer was discarded."
                return
            result["incident_id"] = self.pending_incident_id
            self.store.append(self.session, "model_review", result["created"], result)
            self.review = result
        except Exception as exc:
            self.review_error = str(exc)
            self.review_failure = exc.evidence if isinstance(exc, ReviewFailure) else {"error": str(exc)}
            self.review_failure["incident_id"] = self.pending_incident_id
            try:
                self.store.append(self.session, "model_error", time.time(), self.review_failure)
            except sqlite3.Error as storage_error:
                self.review_error += f"; 失败记录也无法保存: {storage_error}"

    def record_assessment(self, outcome: str, note: str) -> None:
        if self.review is None:
            raise RuntimeError("A completed model review is required")
        if outcome not in ("supported", "not_supported", "insufficient_evidence"):
            raise ValueError("Unknown human review outcome")
        self.assessment = {
            "review_id": self.review["review_id"], "frame": self.review["snapshot"]["frame"],
            "baseline_generation": self.review["snapshot"]["baseline_generation"],
            "outcome": outcome, "note": note[:2000], "created": time.time(),
            "provenance": "operator_supplied_not_independently_verified",
        }
        self.store.append(self.session, "human_review", self.assessment["created"], self.assessment)

    def export(self) -> bytes:
        metadata = {
            "baseline": self.baseline, "exported": time.time(),
            "disclaimer": "Synthetic/injected records are not field validation. Scores are heuristic; no automatic actuation.",
        }
        return b''.join(self.store.export_session(self.session, metadata))

    def close(self) -> None:
        if self.vision is not None:
            self.vision.close()
        if self.camera:
            self.camera.close()
