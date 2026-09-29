"""API smoke tests against a temporary SQLite database."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SCENE = {
    "frame_width": 768,
    "frame_height": 432,
    "objects": [
        {"id": "g1", "type": "gate", "name": "Entrance", "points": [{"x": 0.5, "y": 0.4}, {"x": 0.5, "y": 1.0}], "classes": ["person"]},
        {"id": "g2", "type": "gate", "name": "Exit", "points": [{"x": 0.1, "y": 0.4}, {"x": 0.1, "y": 1.0}], "classes": ["person"]},
    ],
    "routes": [{"id": "r1", "name": "Route A", "start": "g1", "sequence": [], "end": "g2", "timeout_s": 30}],
}


def test_status_and_setup(client):
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    assert body["database"]["ok"] is True and body["version"]
    assert client.post("/api/system/setup-complete").json()["ok"] is True
    assert client.get("/api/system/status").json()["setup_completed"] is True


def test_hardware_models_settings(client):
    hw = client.get("/api/hardware").json()
    assert "cpu" in hw and "memory" in hw and isinstance(hw["gpus"], list)
    recs = client.get("/api/hardware/recommendations").json()
    assert recs["tiers"] and recs["default_tier"] in {t["tier"] for t in recs["tiers"]}
    models = client.get("/api/models").json()
    assert any(m["id"] == "yolo11n" for m in models["models"])
    assert all("license" in m and "installed" in m for m in models["models"])
    s = client.put("/api/settings", json={"values": {"preview_fps": 8, "default_preset": "fast"}}).json()
    assert s["values"]["preview_fps"] == 8.0 and s["values"]["default_preset"] == "fast"
    assert client.put("/api/settings", json={"values": {"default_preset": "bogus"}}).status_code == 400
    priv = client.get("/api/system/privacy").json()
    assert any(item["item"].startswith("Faces") and item["stored"] is False for item in priv["stored"])


def test_project_camera_scene_experiment_flow(client, sample_video: Path | None):
    p = client.post("/api/projects", json={"name": "Study", "description": "d", "tags": ["a"]})
    assert p.status_code == 201
    pid = p.json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["name"] == "Study"
    site = client.post(f"/api/projects/{pid}/sites", json={"name": "Entrance hall"})
    assert site.status_code == 201

    cam_body = {"project_id": pid, "name": "CAM-01", "source_type": "rtsp", "source_uri": "rtsp://example/stream"}
    if sample_video:
        v = client.post("/api/videos/register", params={"path": str(sample_video)})
        assert v.status_code == 201, v.text
        cam_body = {"project_id": pid, "name": "CAM-01", "source_type": "file", "video_id": v.json()["id"]}
    cam = client.post("/api/cameras", json=cam_body)
    assert cam.status_code == 201, cam.text
    cid = cam.json()["id"]
    assert client.post("/api/cameras", json={**cam_body, "rotation": 45}).status_code == 400

    latest = client.get(f"/api/cameras/{cid}/scenes/latest").json()
    assert latest["version"] == 1 and latest["document"]["objects"] == []
    saved = client.post(f"/api/cameras/{cid}/scenes", json={"name": "v1", "document": SCENE})
    assert saved.status_code == 201 and saved.json()["version"] == 1  # latest was not frozen: updated in place
    assert client.post(f"/api/cameras/{cid}/scenes", json={"document": SCENE, "new_version": True}).json()["version"] == 2
    bad = dict(SCENE, routes=[{"id": "r", "name": "x", "start": "nope", "sequence": [], "end": "g2"}])
    assert client.post("/api/scenes/validate", json=bad).status_code == 422

    exp = client.post("/api/experiments", json={"project_id": pid, "camera_id": cid, "name": "Baseline", "object_classes": ["person"], "rules": [
        {"name": "seq", "classes": ["person"], "trigger": {"kind": "crosses", "object_id": "g1"}, "then": [{"kind": "crosses", "object_id": "g2", "within_s": 20}], "record_as": "Route A"}
    ]})
    assert exp.status_code == 201, exp.text
    eid = exp.json()["id"]
    dup = client.post(f"/api/experiments/{eid}/duplicate", params={"name": "Signage"})
    assert dup.status_code == 201 and dup.json()["name"] == "Signage" and len(dup.json()["rules"]) == 1
    assert client.put(f"/api/experiments/{eid}", json={"condition_notes": "no signage"}).json()["condition_notes"] == "no signage"
    assert client.get(f"/api/experiments?project_id={pid}").json().__len__() == 2

    ev = client.get(f"/api/events?experiment_id={eid}").json()
    assert ev["total"] == 0 and ev["items"] == []
    csv = client.get(f"/api/events/export?experiment_id={eid}&format=csv")
    assert csv.status_code == 200 and csv.text.startswith("id,run_id")
    assert client.get(f"/api/analytics/experiments/{eid}/summary").json()["event_count"] == 0
    assert client.get("/api/analytics/dashboard").json()["experiments"] >= 2

    if not sample_video:
        r = client.post(f"/api/experiments/{eid}/start", json={})
        assert r.status_code == 400  # rtsp://example is not reachable / model may be missing

    assert client.delete(f"/api/projects/{pid}").status_code == 204
    assert client.get(f"/api/experiments/{eid}").status_code == 404


def test_scene_document_validation():
    from pydantic import ValidationError

    from pathscope.domain.scene import SceneDocument

    with pytest.raises(ValidationError):
        SceneDocument.model_validate({"frame_width": 10, "frame_height": 10, "objects": [{"id": "a", "type": "line", "name": "x", "points": [{"x": 0, "y": 0}]}]})
    doc = SceneDocument.model_validate(json.loads(json.dumps(SCENE)))
    assert doc.object_by_id("g1").name == "Entrance" and doc.all_classes() == {"person"}


def test_botsort_is_offered_validated_and_checked_before_a_run(client):
    models = client.get("/api/models").json()
    bot = next(t for t in models["trackers"] if t["id"] == "botsort")
    assert bot["available"] is True
    assert {s["key"] for s in bot["settings"]} >= {"gmc_method", "appearance", "appearance_thresh"}
    assert any(m["id"] == "appearance-resnet18" and m["task"] == "appearance" for m in models["models"])
    r = client.post("/api/models/appearance-resnet18/benchmark", json={})
    assert r.status_code == 400 and "Only detectors" in r.json()["detail"]

    p = client.post("/api/projects", json={"name": "Tracker test"}).json()
    cam = client.post("/api/cameras", json={"project_id": p["id"], "name": "C", "source_type": "rtsp", "source_uri": "rtsp://example/stream"}).json()
    assert client.post(f"/api/cameras/{cam['id']}/scenes", json={"document": SCENE}).status_code == 201
    base = {"project_id": p["id"], "camera_id": cam["id"], "name": "BoT-SORT", "tracker_id": "botsort"}

    bad = client.post("/api/experiments", json={**base, "tracker_settings": {"gmc_method": "sift"}})
    assert bad.status_code == 400 and "camera motion compensation" in bad.json()["detail"]

    exp = client.post("/api/experiments", json={**base, "tracker_settings": {"appearance": "cnn"}})
    assert exp.status_code == 201, exp.text
    eid = exp.json()["id"]
    assert client.put(f"/api/experiments/{eid}", json={"tracker_settings": {"track_buffer": 0}}).status_code == 400
    # The ResNet-18 weights are not installed in the test data directory: refuse to start, with a clear message.
    start = client.post(f"/api/experiments/{eid}/start", json={})
    assert start.status_code == 400 and "ResNet-18" in start.json()["detail"]
    assert client.get(f"/api/runs?experiment_id={eid}").json() == []
    client.delete(f"/api/projects/{p['id']}")


def test_camera_can_be_moved_to_another_project(client):
    a = client.post("/api/projects", json={"name": "A"}).json()
    b = client.post("/api/projects", json={"name": "B"}).json()
    cam = client.post("/api/cameras", json={"project_id": a["id"], "name": "Webcam", "source_type": "usb", "source_uri": "9"}).json()
    moved = client.put(f"/api/cameras/{cam['id']}", json={"project_id": b["id"]})
    assert moved.status_code == 200 and moved.json()["project_id"] == b["id"]
    assert client.put(f"/api/cameras/{cam['id']}", json={"project_id": 999999}).status_code == 404
    assert [c["id"] for c in client.get(f"/api/cameras?project_id={b['id']}").json()] == [cam["id"]]
    for p in (a, b):
        client.delete(f"/api/projects/{p['id']}")


def test_an_experiment_can_use_a_camera_from_another_project(client):
    a = client.post("/api/projects", json={"name": "Cams"}).json()
    b = client.post("/api/projects", json={"name": "Study"}).json()
    cam = client.post("/api/cameras", json={"project_id": a["id"], "name": "Webcam", "source_type": "usb", "source_uri": "9"}).json()
    e = client.post("/api/experiments", json={"project_id": b["id"], "name": "Screen time"}).json()
    r = client.put(f"/api/experiments/{e['id']}", json={"camera_id": cam["id"]})
    assert r.status_code == 200 and r.json()["camera_id"] == cam["id"]
    assert client.put(f"/api/experiments/{e['id']}", json={"camera_id": 999999}).status_code == 404
    assert client.put(f"/api/experiments/{e['id']}", json={"scene_config_id": 999999}).status_code == 404
    for p in (b, a):
        client.delete(f"/api/projects/{p['id']}")


def test_an_experiment_on_latest_follows_scene_edits_and_a_pin_holds(client):
    from pathscope.db.models import Camera, Experiment
    from pathscope.db.session import get_session_factory
    from pathscope.services.run_launcher import scene_for_run

    p = client.post("/api/projects", json={"name": "Scenes"}).json()
    cam = client.post("/api/cameras", json={"project_id": p["id"], "name": "Cam", "source_type": "usb", "source_uri": "9"}).json()
    v1 = client.post(f"/api/cameras/{cam['id']}/scenes", json={"document": SCENE}).json()
    e = client.post("/api/experiments", json={"project_id": p["id"], "camera_id": cam["id"], "name": "Latest"}).json()
    pinned = client.post("/api/experiments", json={"project_id": p["id"], "camera_id": cam["id"], "name": "Pinned", "scene_config_id": v1["id"]}).json()
    v2 = client.post(f"/api/cameras/{cam['id']}/scenes", json={"document": SCENE, "new_version": True}).json()
    assert v2["version"] == v1["version"] + 1
    session = get_session_factory()()
    try:
        camera = session.get(Camera, cam["id"])
        assert scene_for_run(session, session.get(Experiment, e["id"]), camera).id == v2["id"]
        assert scene_for_run(session, session.get(Experiment, pinned["id"]), camera).id == v1["id"]
    finally:
        session.close()
    client.delete(f"/api/projects/{p['id']}")


def test_the_frontend_route_never_serves_files_outside_the_build(client):
    """An encoded ../ in the single-page-app route must not reach the repository or the data folder."""
    for path in ("/..%2F..%2FREADME.md", "/%2E%2E/%2E%2E/README.md", "/..%2F..%2Fbackend%2Fpyproject.toml"):
        r = client.get(path)
        assert b"CV-Scope is an open-sour" not in r.content and b"[project]" not in r.content
