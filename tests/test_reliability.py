"""Reliability contracts exercised with synthetic images, never field evidence."""

import json

import cv2
import numpy as np
import pytest
import yaml

from src.config import load_settings
from src.monitoring import DetectionRecord
from src.pipeline import CalibrationError, Monitor


@pytest.fixture
def monitor(tmp_path):
    instance = Monitor(tmp_path / "reliability.db")
    instance.open_source("synthetic")
    instance.calibrate()
    for _ in range(10):
        instance.process(instance.read())
    yield instance
    instance.close()


def measure(monitor, scenario="none", status="ok"):
    record = (DetectionRecord(0, True, 1, False) if status == "ok" else
              DetectionRecord(0, None, None, None, status=status))
    return monitor.process(monitor.read(), scenario, .8, detection_record=record)


def active_state(monitor):
    return {"baseline": monitor.baseline, "generation": monitor.baseline_generation,
            "detector": monitor.detector, "latest": monitor.latest,
            "history": list(monitor.history), "alert": monitor.alerts.snapshot(),
            "reference": monitor.reference_gray.copy(), "frame": monitor.last_frame.copy(),
            "baseline_frame": monitor.baseline_frame.copy()}


def assert_preserved(monitor, previous):
    assert monitor.baseline is previous["baseline"]
    assert monitor.detector is previous["detector"]
    assert monitor.baseline_generation == previous["generation"]
    assert monitor.latest == previous["latest"]
    assert list(monitor.history) == previous["history"]
    assert monitor.alerts.snapshot() == previous["alert"]
    assert np.array_equal(monitor.reference_gray, previous["reference"])
    assert np.array_equal(monitor.last_frame, previous["frame"])
    assert np.array_equal(monitor.baseline_frame, previous["baseline_frame"])


@pytest.mark.parametrize("kind", ["dark", "bright", "flat", "dimensions", "capture", "encoding", "record"])
def test_invalid_candidate_preserves_live_baseline_and_alert(monitor, monkeypatch, kind):
    measure(monitor, "focus_change")
    previous = active_state(monitor)
    images = [monitor.read() for _ in range(10)]
    records = None
    if kind in ("dark", "bright", "flat"):
        images[-1] = np.full_like(images[0], {"dark": 0, "bright": 255, "flat": 128}[kind])
    elif kind == "dimensions":
        images[-1] = images[-1][:-1]
    elif kind == "capture":
        def fail():
            raise RuntimeError("camera disconnected")
        monkeypatch.setattr(monitor, "read", fail)
        images = None
    elif kind == "encoding":
        monkeypatch.setattr(cv2, "imencode", lambda *args: (False, None))
    else:
        records = [DetectionRecord(i, True, 1, False) for i in range(10)]
        records[-1].confidence = None
    with pytest.raises((RuntimeError, ValueError)):
        monitor.calibrate(10, reference_images=images, reference_records=records)
    assert_preserved(monitor, previous)
    assert monitor.baseline_attempt["status"] == "rejected"
    assert len(monitor.store.events(monitor.session, kind="baseline")) == 1
    assert not monitor.store.events(monitor.session, kind="incident_closed")
    if kind in ("dark", "bright", "flat"):
        assert monitor.baseline_attempt["valid_samples"] == 9
        assert monitor.baseline_attempt["rejected_samples"][0]["index"] == 10
    assert monitor.store.events(monitor.session, kind="baseline_rejected")


def test_initial_quality_rejection_has_no_baseline(tmp_path):
    monitor = Monitor(tmp_path / "empty.db")
    images = [np.zeros((32, 32, 3), np.uint8)] * 10
    with pytest.raises(CalibrationError):
        monitor.calibrate(reference_images=images)
    assert monitor.baseline is None and monitor.baseline_generation == 0
    assert monitor.reference_gray is None
    assert monitor.baseline_attempt["retained_generation"] is None


def test_baseline_and_episode_closure_are_one_transaction(monitor):
    measure(monitor, "focus_change")
    previous = active_state(monitor)
    with monitor.store.connect() as db:
        db.execute("""CREATE TRIGGER fail_baseline BEFORE INSERT ON events
                      WHEN NEW.kind = 'baseline' BEGIN SELECT RAISE(ABORT, 'disk failure fixture'); END""")
    with pytest.raises(RuntimeError, match="证据保存失败"):
        monitor.calibrate()
    assert_preserved(monitor, previous)
    assert not monitor.store.events(monitor.session, kind="incident_closed")
    assert len(monitor.store.events(monitor.session, kind="baseline")) == 1
    with monitor.store.connect() as db:
        db.execute("DROP TRIGGER fail_baseline")
    monitor.calibrate()
    assert monitor.baseline_generation == previous["generation"] + 1
    assert monitor.baseline["quality_gate"]["valid_samples"] == 20
    assert monitor.latest is None and not monitor.history and not monitor.alerts.active
    closure = monitor.store.events(monitor.session, kind="incident_closed")[0]["payload"]
    assert closure["reason"] == "baseline_replaced"
    assert closure["incident_id"] == previous["alert"]["episode"]["incident_id"]
    assert closure["baseline_generation"] == previous["generation"]
    assert not monitor.store.events(monitor.session, kind="incident_recovered")


@pytest.mark.parametrize("target", ["incident", "frame", "incident_recovered", "incident_updated", "encoding"])
def test_measurement_and_lifecycle_publication_are_atomic(monitor, monkeypatch, target):
    if target in ("incident_recovered", "incident_updated"):
        measure(monitor, "focus_change")
    if target == "incident_recovered":
        measure(monitor)
        measure(monitor)
    previous = monitor.latest
    count = monitor.store.count(monitor.session)
    previous_episode = monitor.alerts.snapshot()["episode"]
    # target is a fixed test parameter; this trigger deliberately aborts journal publication.
    with monkeypatch.context() as patch:
        if target == "encoding":
            def fail(*args):
                raise cv2.error("encode fixture")
            patch.setattr(cv2, "imencode", fail)
        else:
            with monitor.store.connect() as db:
                db.execute(f"""CREATE TRIGGER fail_event BEFORE INSERT ON events
                               WHEN NEW.kind = '{target}' BEGIN SELECT RAISE(ABORT, 'storage fixture'); END""")
        scenario = "none" if target == "incident_recovered" else "light_fade"
        with pytest.raises(RuntimeError, match="证据保存失败"):
            measure(monitor, scenario)
    assert monitor.store.count(monitor.session) == count
    assert monitor.latest is previous
    assert monitor.alerts.snapshot()["episode"] == previous_episode
    assert monitor.alerts.recovery_streak == 0
    assert not monitor.detector.consistency_tracker.records
    if target != "encoding":
        with monitor.store.connect() as db:
            db.execute("DROP TRIGGER fail_event")
    measure(monitor, "focus_change")
    assert len(monitor.store.events(monitor.session, kind="incident")) == 1
    for _ in range(12):
        measure(monitor)
    assert monitor.alerts.snapshot()["state"] == "recovered"
    assert len(monitor.store.events(monitor.session, kind="incident_recovered")) == 1


def test_type_changes_and_brief_clear_frames_share_one_episode(monitor):
    measure(monitor, "focus_change")
    episode = monitor.alerts.snapshot()["episode"]
    measure(monitor, "light_fade")
    measure(monitor)
    assert monitor.alerts.snapshot()["recovery_streak"] == 1
    measure(monitor, "position_shift")
    assert monitor.alerts.snapshot()["recovery_streak"] == 0
    assert len(monitor.store.events(monitor.session, kind="incident")) == 1
    for _ in range(2):
        measure(monitor)
        assert not monitor.store.events(monitor.session, kind="incident_recovered")
    result = measure(monitor)
    assert result["alert"]["state"] == "recovered"
    recovery = monitor.store.events(monitor.session, kind="incident_recovered")[0]["payload"]
    assert recovery["incident_id"] == episode["incident_id"]
    assert recovery["baseline_generation"] == monitor.baseline_generation
    assert recovery["frame"] == result["frame"]
    assert recovery["alert"]["episode"]["drift_types"] == ["optical", "illumination", "mechanical"]
    assert recovery["snapshot"]["detection_availability"]["ready"]
    assert "scenario" not in json.dumps(recovery["snapshot"])
    saved = monitor.store.events(monitor.session, kind="frame")[-1]["payload"]
    assert saved["alert"] == result["alert"]
    for _ in range(3):
        measure(monitor)
    assert len(monitor.store.events(monitor.session, kind="incident_recovered")) == 1
    measure(monitor, "focus_change")
    assert len(monitor.store.events(monitor.session, kind="incident")) == 2
    assert monitor.alerts.episode["number"] == 2


@pytest.mark.parametrize("status", ["missing", "error", "timeout"])
def test_unavailable_window_blocks_recovery_and_never_duplicates_episode(monitor, status):
    measure(monitor, "focus_change")
    measure(monitor)
    assert monitor.alerts.recovery_streak == 1
    result = measure(monitor, status=status)
    assert result["detection"]["confidence"] is None
    assert monitor.alerts.recovery_streak == 0
    for _ in range(29):
        result = measure(monitor)
        assert result["alert"]["state"] == "blocked"
    assert not monitor.store.events(monitor.session, kind="incident_recovered")
    for _ in range(3):
        result = measure(monitor)
    assert result["alert"]["state"] == "recovered"
    assert len(monitor.store.events(monitor.session, kind="incident")) == 1


def test_warmup_is_not_clear_recovery(monitor):
    monitor.calibrate()
    measure(monitor, "focus_change")
    for _ in range(8):
        result = measure(monitor)
        assert result["alert"]["recovery_streak"] == 0
    for _ in range(3):
        result = measure(monitor)
    assert result["alert"]["state"] == "recovered"


@pytest.mark.parametrize("value", [0, 101, True, 1.5, "3"])
def test_invalid_recovery_policy_is_rejected(monkeypatch, value):
    original = yaml.safe_load
    def settings(stream):
        config = original(stream)
        config["monitoring"]["alert_recovery_samples"] = value
        return config
    monkeypatch.setattr(yaml, "safe_load", settings)
    with pytest.raises(ValueError, match="recovery"):
        load_settings()
