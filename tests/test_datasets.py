"""Dataset import isolation, fixed replay, provenance and inference label boundaries."""

from concurrent.futures import Future
import json

import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.api.app import create_app
from src.datasets import DatasetStore
from src.inspection.camera import DummyCamera


@pytest.fixture
def dataset_manifest(tmp_path):
    directory = tmp_path / "input"
    directory.mkdir()
    camera = DummyCamera()
    camera.open()
    _, image = camera.read()
    camera.close()
    samples = []
    for index in range(23):
        path = directory / f"{index}.png"
        frame = image if index < 20 else cv2.GaussianBlur(image, (31, 31), 8)
        cv2.imwrite(str(path), frame)
        samples.append({"id": f"sample-{index}", "batch": "batch-a" if index < 10 else "batch-b",
                        "path": path.name, "split": "baseline" if index < 10 else "evaluation",
                        "origin": "synthetic", "perturbation": "blur" if index >= 20 else "none",
                        "conditions": {"fixture": "PCB synthetic"},
                        "label": {"defect": "unknown", "cause": "optical" if index >= 20 else "none",
                                  "note": "WITHHELD_LABEL_SENTINEL"}})
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "name": "Test dataset", "samples": samples}))
    return manifest


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "test.db", serve_frontend=False)) as client:
        yield client


def import_and_prepare(client, path):
    response = client.post("/api/datasets/import", json={"path": str(path)})
    assert response.status_code == 200, response.text
    dataset_id = response.json()["id"]
    response = client.post("/api/replay", json={"dataset_id": dataset_id})
    assert response.status_code == 200, response.text
    return dataset_id


def run_to_end(client):
    total = client.get("/api/state").json()["replay"]["total"]
    for _ in range(total):
        result = client.post("/api/capture", json={"action": "sample"})
        assert result.status_code == 200, result.text
    return client.get("/api/replay/export").json()


def test_repeat_replay_is_identical_and_labels_do_not_reach_model(client, dataset_manifest, monkeypatch):
    dataset_id = import_and_prepare(client, dataset_manifest)
    first = run_to_end(client)
    state = client.get("/api/state").json()
    assert state["replay"]["completed"] and not state["running"] and not state["capture_error"]
    assert state["latest"]["synthetic"] and state["latest"]["injected"]
    assert first["results"][-1]["rule_report"]["drift_type"] == "optical"
    assert [r["sample_id"] for r in first["results"]] == [f"sample-{i}" for i in range(10, 23)]
    assert client.post("/api/capture", json={"action": "start"}).status_code == 409
    assert client.post("/api/capture", json={"action": "sample"}).status_code == 409
    assert client.get("/api/state").json() == state
    monitor = client.app.state.station.monitor
    snapshot = monitor.snapshot()
    assert "sample" not in snapshot
    assert "WITHHELD_LABEL_SENTINEL" not in json.dumps(snapshot)
    incident = monitor.store.events(monitor.session, kind="incident")[-1]
    assert incident["payload"]["sample"]["label"]["cause"] == "optical"
    assert "WITHHELD_LABEL_SENTINEL" not in json.dumps(incident["payload"]["snapshot"])
    submitted = {}
    def submit(fn, snapshot, *args):
        submitted.update(snapshot)
        future = Future()
        future.set_exception(RuntimeError("offline"))
        return future
    monkeypatch.setattr("src.pipeline.REVIEW_POOL.submit", submit)
    monitor.request_review("", "test", "http://localhost", incident_id=incident["id"])
    assert "WITHHELD_LABEL_SENTINEL" not in json.dumps(submitted)
    monitor.poll_review()
    # Imported copies survive changes to the originals.
    (dataset_manifest.parent / "22.png").write_bytes(b"changed original")
    assert client.post("/api/replay", json={"dataset_id": dataset_id}).status_code == 200
    second = run_to_end(client)
    assert first["session"] != second["session"]
    assert first["replay"]["fingerprint"] == second["replay"]["fingerprint"]
    assert first["results_sha256"] == second["results_sha256"]
    assert monitor.store.events(first["session"], kind="incident")
    assert client.get(f'/api/sessions/{first["session"]}/replay').json() == first
    assert len(client.get('/api/replays').json()) == 2


@pytest.mark.parametrize("change", ["missing", "escape", "duplicate", "baseline_defect", "count", "unknown_field", "bad_image"])
def test_invalid_import_preserves_session_and_publishes_nothing(client, dataset_manifest, change):
    manifest = json.loads(dataset_manifest.read_text())
    if change == "missing":
        manifest["samples"][-1]["path"] = "missing.png"
    elif change == "escape":
        manifest["samples"][-1]["path"] = "../outside.png"
    elif change == "duplicate":
        manifest["samples"][-1]["id"] = manifest["samples"][0]["id"]
    elif change == "baseline_defect":
        manifest["samples"][0]["label"]["defect"] = "defect"
    elif change == "count":
        manifest["samples"][0]["split"] = "evaluation"
    elif change == "unknown_field":
        manifest["samples"][0]["typo"] = True
    else:
        (dataset_manifest.parent / "22.png").write_bytes(b"broken")
    dataset_manifest.write_text(json.dumps(manifest))
    before = client.get("/api/state").json()
    response = client.post("/api/datasets/import", json={"path": str(dataset_manifest)})
    assert response.status_code == 400, response.text
    assert client.get("/api/state").json() == before
    assert client.get("/api/datasets").json() == []
    assert not list(client.app.state.station.datasets.root.glob(".import-*"))


def test_replay_guards_corruption_pause_and_failed_preparation(client, dataset_manifest):
    dataset_id = import_and_prepare(client, dataset_manifest)
    for method, endpoint, body in [("post", "/api/baseline", {"count": 10}),
                                   ("delete", "/api/baseline", None),
                                   ("post", "/api/scenario", {"scenario": "focus_change"})]:
        response = client.request(method, endpoint, json=body)
        assert response.status_code == 409
    client.post("/api/capture", json={"action": "sample"})
    before = client.get("/api/state").json()
    dataset = client.app.state.station.datasets
    saved = dataset.load(dataset_id)
    target = next(s for s in saved["samples"] if s["id"] == "sample-11")
    (dataset.directory(dataset_id) / target["asset"]).write_bytes(b"corrupted")
    assert client.post("/api/replay", json={"dataset_id": dataset_id}).status_code == 409
    assert client.get("/api/state").json() == before
    assert client.post("/api/capture", json={"action": "sample"}).status_code == 409
    state = client.get("/api/state").json()
    assert state["latest"] == before["latest"] and state["replay"]["position"] == 1
    assert state["capture_error"] and not state["running"]
    assert client.post("/api/source", json={"mode": "synthetic"}).status_code == 200
    assert client.get("/api/state").json()["replay"] is None


def test_catalog_persists_and_duplicate_import_is_idempotent(tmp_path, dataset_manifest):
    store = DatasetStore(tmp_path / "catalog")
    first = store.import_manifest(dataset_manifest)
    assert store.import_manifest(dataset_manifest) == first
    assert DatasetStore(store.root).catalog() == [first]
    assert len(list(store.root.iterdir())) == 1


def test_history_export_survives_source_change_and_service_restart(tmp_path, dataset_manifest):
    db = tmp_path / "history.db"
    with TestClient(create_app(db, serve_frontend=False)) as client:
        dataset_id = import_and_prepare(client, dataset_manifest)
        assert client.get(f"/api/datasets/{dataset_id}/images/10").status_code == 200
        assert client.get(f"/api/datasets/{dataset_id}/images/500").status_code == 404
        client.post("/api/capture", json={"action": "sample"})
        partial = client.get("/api/replay/export").json()
        client.post("/api/source", json={"mode": "synthetic"})
        assert client.get("/api/state").json()["session"] != partial["session"]
        client.post("/api/baseline", json={"count": 10})
        client.post("/api/capture", json={"action": "sample"})
    with TestClient(create_app(db, serve_frontend=False)) as client:
        assert client.get(f'/api/sessions/{partial["session"]}/replay').json() == partial
        assert len(client.get("/api/replays").json()) == 1


def test_failed_calibration_and_busy_run_do_not_replace_session(client, dataset_manifest):
    station = client.app.state.station
    before = client.get('/api/state').json()
    for index in range(10):
        cv2.imwrite(str(dataset_manifest.parent / f'{index}.png'), np.zeros((480, 640, 3), np.uint8))
    dataset_id = client.post('/api/datasets/import', json={'path': str(dataset_manifest)}).json()['id']
    assert client.post('/api/replay', json={'dataset_id': dataset_id}).status_code == 409
    assert client.get('/api/state').json() == before
    with station.lock:
        station.running = True
        assert station.monitor.session == before['session']
        with pytest.raises(RuntimeError, match='暂停'):
            station.prepare_replay(dataset_id)
        station.running = False
        station.monitor.pending = Future()
        with pytest.raises(RuntimeError, match='模型复核'):
            station.prepare_replay(dataset_id)
        station.monitor.pending = None


def test_limits_and_symlink_escape_are_rejected(tmp_path, dataset_manifest, monkeypatch):
    store = DatasetStore(tmp_path / 'catalog')
    monkeypatch.setattr('src.datasets.MAX_MEDIA_BYTES', 1)
    with pytest.raises(ValueError, match='256 MiB'):
        store.import_manifest(dataset_manifest)
    monkeypatch.undo()
    outside = tmp_path / 'outside.png'
    outside.write_bytes((dataset_manifest.parent / '22.png').read_bytes())
    (dataset_manifest.parent / '22.png').unlink()
    (dataset_manifest.parent / '22.png').symlink_to(outside)
    with pytest.raises(ValueError, match='清单目录'):
        store.import_manifest(dataset_manifest)
    assert not store.catalog()


def test_video_frames_are_frozen_by_index(tmp_path):
    video = tmp_path / "sequence.avi"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (80, 60))
    assert writer.isOpened()
    for index in range(12):
        writer.write(np.full((60, 80, 3), 20 + index * 10, dtype=np.uint8))
    writer.release()
    manifest = {"schema_version": 1, "name": "Video", "samples": [
        {"id": str(i), "batch": "b1", "path": video.name, "frame_index": i,
         "split": "baseline" if i < 10 else "evaluation", "origin": "synthetic"} for i in range(12)]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    store = DatasetStore(tmp_path / "catalog")
    dataset_id = store.import_manifest(path)["id"]
    samples = store.load(dataset_id)["samples"]
    assert abs(store.image(dataset_id, samples[11]).mean() - 130) < 3
    assert abs(store.image(dataset_id, samples[0]).mean() - 20) < 3
    manifest["samples"][-1]["frame_index"] = 500
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="视频帧"):
        store.import_manifest(path)
