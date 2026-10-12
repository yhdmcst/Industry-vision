"""Incidents are durable snapshots, not references to mutable live frames."""

from concurrent.futures import Future

import pytest

from src.pipeline import Monitor
from src.storage import EvidenceStore


@pytest.fixture
def monitor(tmp_path):
    instance = Monitor(tmp_path / "incidents.db")
    instance.open_source("synthetic")
    instance.calibrate()
    yield instance
    instance.close()


def test_transition_deduplication_and_recovery(monitor):
    for _ in range(12):
        monitor.process(monitor.read(), "focus_change", 0.8)
    incidents = monitor.store.events(monitor.session, kind="incident")
    assert len(incidents) == 1
    assert incidents[0]["payload"]["synthetic"]
    assert incidents[0]["payload"]["images"]["current"] != incidents[0]["payload"]["images"]["baseline"]
    for _ in range(35):
        monitor.process(monitor.read())
    count = len(monitor.store.events(monitor.session, kind="incident"))
    monitor.process(monitor.read(), "focus_change", 0.8)
    assert len(monitor.store.events(monitor.session, kind="incident")) == count + 1


def test_evidence_survives_baseline_reset_and_store_reopen(monitor):
    monitor.process(monitor.read(), "light_fade", 0.8)
    event = monitor.store.events(monitor.session, kind="incident")[0]
    monitor.calibrate()
    reopened = EvidenceStore(monitor.store.path)
    assert reopened.event(monitor.session, event["id"]) == event
    monitor.record_incident_assessment(monitor.session, event["id"], "insufficient_evidence", "待现场检查")
    saved = reopened.events(monitor.session, kind="incident_assessment")[0]["payload"]
    assert saved["baseline_generation"] == event["payload"]["baseline_generation"]
    assert saved["baseline_generation"] != monitor.baseline_generation
    with pytest.raises(ValueError):
        monitor.record_incident_assessment("another-session", event["id"], "false_alarm", "test")
    with pytest.raises(ValueError):
        monitor.record_incident_assessment(monitor.session, event["id"], "confirmed_change", " ")


def test_model_receives_selected_event_snapshot(monitor, monkeypatch):
    monitor.process(monitor.read(), "focus_change", 0.8)
    event = monitor.store.events(monitor.session, kind="incident")[0]
    monitor.process(monitor.read())
    submitted = {}
    def submit(fn, snapshot, *args):
        submitted.update(snapshot)
        future = Future()
        future.set_exception(RuntimeError("model offline"))
        return future
    monkeypatch.setattr("src.pipeline.REVIEW_POOL.submit", submit)
    monitor.request_review("", "test", "http://127.0.0.1:11435", incident_id=event["id"])
    assert submitted == event["payload"]["snapshot"]
    assert "scenario" not in submitted
    monitor.poll_review()
    failure = monitor.store.events(monitor.session, kind="model_error")[0]["payload"]
    assert failure["incident_id"] == event["id"]
    assert "offline" in failure["error"]
    assert monitor.review is None


def test_review_is_not_published_when_storage_and_error_journal_fail(monitor):
    monitor.process(monitor.read(), "focus_change", .8)
    incident = monitor.store.events(monitor.session, kind="incident")[0]["id"]
    monitor.pending_incident_id = incident
    monitor.pending_generation = monitor.baseline_generation
    monitor.pending = Future()
    monitor.pending.set_result({"created": 1, "review_id": "fixture-only"})
    with monitor.store.connect() as db:
        db.execute("""CREATE TRIGGER fail_review BEFORE INSERT ON events
                      BEGIN SELECT RAISE(ABORT, 'storage failure fixture'); END""")
    monitor.poll_review()
    assert monitor.review is None and monitor.pending is None
    assert "失败记录也无法保存" in monitor.review_error
    assert monitor.review_failure["incident_id"] == incident
    assert not monitor.store.events(monitor.session, kind="model_review")
    with monitor.store.connect() as db: db.execute('DROP TRIGGER fail_review')
    monitor.pending = Future()
    monitor.pending.set_result({"created": 2, "review_id": "retry-fixture-only"})
    monitor.poll_review()
    assert monitor.review['review_id'] == 'retry-fixture-only'
    assert len(monitor.store.events(monitor.session, kind="model_review")) == 1
