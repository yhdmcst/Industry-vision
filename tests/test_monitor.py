from concurrent.futures import Future
import json
import math

import cv2
import numpy as np
import pytest

from src.inspection.simulator import DriftScenario, create_simulator
from src.llm import ResponseParser, SparkXClient, build_review_prompt
from src.monitoring import DetectionRecord, DriftDetector
from src.monitoring.image_analyzer import ImageQualityAnalyzer
from src.monitoring.consistency_tracker import ConsistencyTracker
from src.pipeline import CalibrationError, Monitor, ReviewFailure, review_snapshot
from src.storage import EvidenceStore
from src.llm.evidence_guard import evidence_warnings


@pytest.fixture
def image():
    result = np.full((480, 640, 3), 130, dtype=np.uint8)
    cv2.rectangle(result, (200, 150), (410, 320), (50, 190, 110), -1)
    cv2.putText(result, "PCB-42", (220, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (240, 240, 240), 2)
    return result


@pytest.fixture
def monitor(tmp_path):
    instance = Monitor(tmp_path / "evidence.db")
    instance.open_source("synthetic")
    instance.calibrate()
    yield instance
    instance.close()


def test_flat_baseline_is_finite():
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    detector = DriftDetector()
    detector.set_baseline([image] * 10, [DetectionRecord(i, False, 0) for i in range(10)])
    for i in range(10):
        report = detector.analyze(image, DetectionRecord(i, False, 0))
    assert math.isfinite(report.confidence_score)
    json.dumps(report.metrics, allow_nan=False)
    assert not report.metrics["image_drift"]["drift_detected"]


def test_zero_variance_confidence_baseline():
    tracker = ConsistencyTracker(20)
    tracker.set_baseline([DetectionRecord(i, True, 1) for i in range(10)])
    for i in range(10):
        tracker.add_record(DetectionRecord(i, True, 1, is_ng=i == 0))
    report = tracker.detect_drift()
    assert not report["drift_detected"]
    json.dumps(report, allow_nan=False)


def test_normal_baseline_no_false_alarm(monitor):
    for _ in range(30):
        result = monitor.process(monitor.read())
    assert not result["rule_report"]["drift_detected"]
    assert result["source"] == "synthetic"
    assert result["synthetic"] is True


@pytest.mark.parametrize("scenario,expected", [
    ("focus_change", "optical"), ("light_fade", "illumination"), ("position_shift", "mechanical"),
])
def test_drift_classification(monitor, scenario, expected):
    for _ in range(30):
        result = monitor.process(monitor.read(), scenario, 0.8)
    assert result["rule_report"]["drift_detected"]
    assert result["rule_report"]["drift_type"] == expected


def test_model_snapshot_withholds_scenario(monitor):
    monitor.process(monitor.read(), "focus_change", 0.8)
    snapshot = monitor.snapshot()
    assert "scenario" not in snapshot and "intensity" not in snapshot
    assert "rule_report" not in snapshot
    assert snapshot["warmup"]
    assert snapshot["current_metrics"]["relative_changes"]["sharpness_change"] < -0.3


def test_simulator_intensity_updates(monitor):
    frame = monitor.read()
    monitor.process(frame, "focus_change", 0.3)
    first = monitor.latest["rule_report"]["metrics"]["image_quality"]["sharpness"]
    monitor.process(frame, "focus_change", 1)
    second = monitor.latest["rule_report"]["metrics"]["image_quality"]["sharpness"]
    assert second < first


@pytest.mark.parametrize("scenario", list(DriftScenario))
def test_simulators_keep_image_contract(image, scenario):
    simulator = create_simulator(scenario, 0)
    output = simulator.apply(image)
    assert output.shape == image.shape and output.dtype == image.dtype


def test_uneven_light(image):
    result = create_simulator(DriftScenario.AMBIENT_CHANGE, 0.7, mode="uneven").apply(image)
    assert result.shape == image.shape


def test_model_output_rejects_fake_success():
    with pytest.raises(ValueError):
        ResponseParser.parse_drift_analysis("not JSON")
    with pytest.raises(ValueError):
        ResponseParser.parse_drift_analysis('{"drift_detected": "false"}')
    assert ResponseParser.parse_json_response("[]") is None


def test_parser_valid_schema():
    data = {
        "confidence_score": 65, "drift_detected": True, "drift_type": "unknown",
        "root_cause": "Insufficient evidence", "evidence": ["sharpness down"],
        "recommendations": ["human review"], "urgency": "medium",
        "alternative_causes": ["focus", "contamination"], "verification_steps": ["inspect lens"],
        "requires_human_review": True,
    }
    assert ResponseParser.parse_drift_analysis("```json\n" + json.dumps(data) + "\n```") == data
    data["confidence_score"] = float("nan")
    with pytest.raises(ValueError):
        ResponseParser.parse_drift_analysis(json.dumps(data))


@pytest.mark.parametrize("endpoint", ["https://example.org", "http://192.168.1.2:1234",
                                     "http://localhost@evil.test", "http://127.0.0.1:1/?x=1"])
def test_client_rejects_nonlocal_endpoint(endpoint):
    with pytest.raises(ValueError):
        SparkXClient(base_url=endpoint)


def test_client_never_falls_back_to_mock(monkeypatch):
    client = SparkXClient()
    monkeypatch.setattr(client, "initialize", lambda: False)
    with pytest.raises(RuntimeError):
        client.generate("test")


def test_prompt_has_only_safe_measurement_fields(monitor):
    monitor.process(monitor.read())
    snapshot = monitor.snapshot()
    snapshot["label"] = "SECRET_LABEL"
    snapshot["scenario"] = "SECRET_SCENARIO"
    prompt = build_review_prompt(snapshot, "operator note")
    assert "SECRET_LABEL" not in prompt and "SECRET_SCENARIO" not in prompt
    assert "operator note" in prompt
    assert "nan" not in prompt and "inf" not in prompt


def test_evidence_session_isolation(tmp_path):
    store = EvidenceStore(tmp_path / "evidence.db")
    store.append("one", "frame", 1, {"value": 1})
    store.append("two", "frame", 2, {"value": 2})
    assert store.events("one")[0]["payload"] == {"value": 1}
    with pytest.raises(ValueError):
        store.append("one", "frame", 3, {"value": float("nan")})


def test_export_and_reset(monitor):
    monitor.process(monitor.read())
    bundle = json.loads(monitor.export())
    assert bundle["baseline"]["sample_count"] == 20
    assert any(e["kind"] == "frame" for e in bundle["events"])
    monitor.reset_baseline()
    assert monitor.baseline is None and monitor.latest is None
    with pytest.raises(RuntimeError):
        monitor.process(monitor.read())


def test_stale_review_discarded(monitor):
    monitor.pending_generation = monitor.baseline_generation
    monitor.pending = Future()
    monitor.pending.set_result({"created": 0})
    monitor.reset_baseline()
    monitor.poll_review()
    assert monitor.review is None
    assert "stale" in monitor.review_error


def test_invalid_image():
    with pytest.raises(ValueError):
        ImageQualityAnalyzer().analyze(np.zeros((0, 0), dtype=np.uint8))


def test_evidence_guard_flags_missed_measured_drift(monitor):
    monitor.process(monitor.read(), "focus_change", 0.8)
    warnings = evidence_warnings(monitor.snapshot(), {
        "drift_detected": False, "drift_type": "none",
        "root_cause": "未见异常", "evidence": ["所有指标正常"],
    })
    assert any("漏报" in warning for warning in warnings)


def test_evidence_guard_does_not_rewrite_model(monitor):
    monitor.process(monitor.read(), "light_fade", 0.8)
    analysis = {
        "drift_detected": True, "drift_type": "optical",
        "root_cause": "NG率上升且镜头污染", "evidence": ["NG上升"],
    }
    warnings = evidence_warnings(monitor.snapshot(), analysis)
    assert warnings
    assert analysis["drift_type"] == "optical"


def test_evidence_guard_allows_normal_evidence(monitor):
    for _ in range(10):
        monitor.process(monitor.read())
    assert evidence_warnings(monitor.snapshot(), {
        "drift_detected": False, "drift_type": "none",
        "root_cause": "未见异常", "evidence": ["指标稳定"],
    }) == []


def test_unknown_reason_does_not_require_a_positive_drift_flag(monitor):
    monitor.process(monitor.read())
    assert not any('相互矛盾' in warning for warning in evidence_warnings(monitor.snapshot(), {
        'drift_detected': False, 'drift_type': 'unknown', 'root_cause': '暂时证据不足', 'evidence': ['待核验']}))


@pytest.mark.parametrize('detected,category', [(True, 'none'), (False, 'optical')])
def test_evidence_guard_keeps_internally_conflicting_model_answer(monitor, detected, category):
    monitor.process(monitor.read(), "focus_change", .8)
    analysis = {"drift_detected": detected, "drift_type": category,
                "root_cause": "模型矛盾回答夹具", "evidence": ["清晰度下降"]}
    warnings = evidence_warnings(monitor.snapshot(), analysis)
    assert any("相互矛盾" in warning for warning in warnings)
    assert any("漏报" in warning for warning in warnings)
    assert analysis['drift_detected'] == detected and analysis['drift_type'] == category


def test_client_rejects_spark_label_with_wrong_weights(monkeypatch):
    client = SparkXClient()
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: {
        "details": {"family": "spark2_5"}, "modelfile": "FROM /blob/sha256-unverified",
    })
    assert not client.initialize()
    assert "verified official" in client.last_error


def test_client_verifies_official_import(monkeypatch):
    from src.llm.spark_client import OFFICIAL_WEIGHT_DIGESTS

    client = SparkXClient()
    def request(method, path, **kwargs):
        if path == "/api/version":
            return {"version": "test"}
        return {"details": {"family": "spark2_5"},
                "modelfile": "FROM /blob/sha256-" + OFFICIAL_WEIGHT_DIGESTS[client.model_name]}
    monkeypatch.setattr(client, "_request", request)
    assert client.initialize()
    assert client.details["weight_sha256"] == OFFICIAL_WEIGHT_DIGESTS[client.model_name]


def test_invalid_source_never_becomes_camera(monitor):
    for mode in ("missing", "video"):
        with pytest.raises(ValueError):
            monitor.open_source(mode)
    assert monitor.source == "synthetic"


def test_failed_json_review_keeps_raw_evidence(monitor, monkeypatch):
    monitor.process(monitor.read())
    def generate(client, *args, **kwargs):
        client.last_response = "malformed answer"
        client.last_metrics = {"output_tokens": 2}
        return client.last_response
    monkeypatch.setattr(SparkXClient, "generate", generate)
    with pytest.raises(ReviewFailure) as error:
        review_snapshot(monitor.snapshot(), "operator note", "spark-drift:1.7b-q4", "http://127.0.0.1:11435")
    assert error.value.evidence["raw_response"] == "malformed answer"
    assert error.value.evidence["inference"]["output_tokens"] == 2
    assert "operator note" in error.value.evidence["prompt"]


def test_failed_review_is_persisted(monitor):
    monitor.pending = Future()
    monitor.pending.set_exception(ReviewFailure("invalid answer", {"raw_response": "bad", "error": "invalid answer"}))
    monitor.poll_review()
    assert monitor.review is None
    assert monitor.store.events(monitor.session, kind="model_error")[0]["payload"]["raw_response"] == "bad"


def test_operator_review_is_bound_to_model_snapshot(monitor):
    monitor.process(monitor.read())
    snapshot = monitor.snapshot()
    monitor.review = {"review_id": "fixed-review", "snapshot": snapshot}
    monitor.record_assessment("not_supported", "brightness was unchanged")
    saved = monitor.store.events(monitor.session, kind="human_review")[0]["payload"]
    assert saved["review_id"] == "fixed-review" and saved["frame"] == snapshot["frame"]
    assert saved["provenance"] == "operator_supplied_not_independently_verified"
    with pytest.raises(ValueError):
        monitor.record_assessment("automatic_release", "")


def test_operator_review_requires_model(monitor):
    with pytest.raises(RuntimeError):
        monitor.record_assessment("supported", "test")


def test_storage_sessions_and_filtered_history(tmp_path):
    store = EvidenceStore(tmp_path / "history.db")
    store.append("earlier", "model_review", 1, {"value": "review"})
    store.append("later", "frame", 3, {"value": "frame"})
    store.append("earlier", "frame", 2, {"value": "earlier"})
    assert store.count("earlier") == 2
    assert store.sessions()[0]["session"] == "later"
    assert store.events("earlier", kind="model_review")[0]["payload"]["value"] == "review"


def test_export_preserves_all_records_beyond_former_limit(monitor):
    for i in range(1001):
        monitor.store.append(monitor.session, "fixture", i, {})
    exported = json.loads(monitor.export())
    assert exported["truncated"] is False and exported['event_limit'] is None
    assert exported["total_events"] == len(exported["events"]) > 1000


@pytest.mark.parametrize("scenario", list(DriftScenario))
def test_zero_simulation_is_identity(image, scenario):
    assert np.array_equal(create_simulator(scenario, 0).apply(image), image)


def test_ambient_darkening_never_reflects_black(image):
    dark = np.zeros_like(image)
    assert np.array_equal(create_simulator(DriftScenario.AMBIENT_CHANGE, 1, mode="decrease").apply(dark), dark)


def test_dark_capture_cannot_be_used_as_baseline(monitor, monkeypatch):
    previous = monitor.baseline
    generation = monitor.baseline_generation
    monkeypatch.setattr(monitor, "read", lambda: np.zeros((480, 640, 3), dtype=np.uint8))
    with pytest.raises(CalibrationError) as error:
        monitor.calibrate()
    assert error.value.metrics["brightness"] == 0
    assert monitor.baseline is previous
    assert monitor.baseline_generation == generation


def test_mechanical_answer_requires_reliable_registration(monitor):
    monitor.process(monitor.read())
    snapshot = monitor.snapshot()
    snapshot["current_metrics"]["registration"] = {"shift_x": 90, "shift_y": 0, "response": 0.01}
    assert any("不可靠" in text for text in evidence_warnings(snapshot, {
        "drift_type": "mechanical", "drift_detected": True, "root_cause": "位置偏移",
        "evidence": ["90px"],
    }))


def test_thinking_flag_is_forwarded_and_truncation_keeps_evidence(monkeypatch):
    client = SparkXClient()
    client._initialized = True
    request_data = {}
    def request(method, path, **kwargs):
        request_data.update(kwargs["json"])
        return {
            "message": {"content": "", "thinking": "partial model reasoning"},
            "done_reason": "length", "eval_count": 100, "eval_duration": 1_000_000_000,
        }
    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(RuntimeError):
        client.generate("test", max_tokens=2048, thinking=True)
    assert request_data["think"] is True
    assert client.last_thinking
    assert client.last_metrics["finish_reason"] == "length"
    assert client.last_metrics["request_settings"]["thinking"] is True
