"""Identities a reviewer established (annotation, study ground truth) are shown as such:
the identity link, the cross-camera move and its explanation never claim a recognition
module found them."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from pathscope.db.models import Run, SceneConfig, TrackSummary, Trajectory
from pathscope.db.session import get_session_factory

W = 1000
ZONE = {"id": "z_main", "type": "zone", "name": "Hall", "points": [{"x": 0.3, "y": 0.0}, {"x": 0.7, "y": 0.0}, {"x": 0.7, "y": 1.0}, {"x": 0.3, "y": 1.0}]}
PEOPLE = ("idp-annotated", "idp-recognized")


def _token() -> dict:
    from pathscope.recognition.common.access import create_token

    with get_session_factory()() as s:
        _row, secret = create_token(s, "provenance test admin", "admin")
    return {"X-Recognition-Token": secret}


def _run(s, rid, eid, cid, scid, t0, person, method):
    from pathscope.recognition.registry.models import RecognitionEvent

    # explicit ids: other modules delete their runs, and reused ids would inherit their leftover relationship rows
    run = Run(id=rid, experiment_id=eid, camera_id=cid, scene_config_id=scid, status="completed", snapshot={"recognition": {"modules": ["face"]}}, stats={},
              started_at=t0, ended_at=t0 + timedelta(seconds=20))
    s.add(run)
    s.flush()
    pts = [[round(i / 10, 3), round(0.05 + 0.9 * i / 200, 4), 0.6] for i in range(201)]
    s.add(Trajectory(run_id=run.id, track_id=1, object_class="person", points=pts, n_points=len(pts)))
    s.add(TrackSummary(run_id=run.id, track_id=1, object_class="person", first_seen_s=0.0, last_seen_s=20.0, first_seen_at=t0,
                       last_seen_at=t0 + timedelta(seconds=20), n_frames=len(pts), mean_confidence=0.9))
    s.add(RecognitionEvent(run_id=run.id, experiment_id=eid, camera_id=cid, track_id=1, object_class="person", module="face", kind="recognized", status="recognized",
                           person_id=person, confidence=0.93, media_time_s=2.0, wall_time=t0 + timedelta(seconds=2),
                           context={"method": method} if method else {}))
    s.flush()
    return run.id


@pytest.fixture(scope="module")
def two_cameras(client):
    from pathscope.recognition.registry.models import RecognitionPerson

    admin = _token()
    pid = client.post("/api/projects", json={"name": "Provenance"}).json()["id"]
    cams = [client.post("/api/cameras", json={"project_id": pid, "name": n, "source_type": "rtsp", "source_uri": f"rtsp://example/p{i}"}).json()["id"]
            for i, n in enumerate(("Door cam", "Hall cam"))]
    with get_session_factory()() as s:
        scenes = []
        for cid in cams:
            sc = SceneConfig(camera_id=cid, version=1, name="v1", document={"frame_width": W, "frame_height": W, "objects": [ZONE]}, frozen=True)
            s.add(sc)
            s.flush()
            scenes.append(sc.id)
        for p, name in zip(PEOPLE, ("Annotated person", "Recognized person"), strict=True):
            if s.get(RecognitionPerson, p) is None:
                s.add(RecognitionPerson(id=p, display_name=name))
        s.commit()
    exps = [client.post("/api/experiments", json={"project_id": pid, "camera_id": c, "name": f"e{c}", "object_classes": ["person"],
                                                   "relations": {"enabled": True, "rules": []}}).json()["id"] for c in cams]
    site = client.post("/api/locations/nodes", json={"kind": "site", "name": "Provenance site", "layout": {"mode": "plan", "width": 50, "height": 20, "unit": "m"}}, headers=admin).json()["id"]
    nodes = [client.post("/api/locations/nodes", json={"kind": "camera", "name": n, "camera_id": c, "parent_id": site, "x": x, "y": 10}, headers=admin).json()["id"]
             for n, c, x in (("Door cam", cams[0], 5), ("Hall cam", cams[1], 40))]
    assert client.post("/api/locations/links", json={"source_id": nodes[0], "target_id": nodes[1], "kind": "CONNECTED_TO", "travel_min_s": 5, "travel_max_s": 60},
                       headers=admin).status_code == 201
    t0 = datetime.now(UTC) - timedelta(hours=1)
    with get_session_factory()() as s:
        runs = [_run(s, 910001, exps[0], cams[0], scenes[0], t0, PEOPLE[0], "annotation"),
                _run(s, 910002, exps[1], cams[1], scenes[1], t0 + timedelta(seconds=40), PEOPLE[0], "annotation"),
                _run(s, 910003, exps[0], cams[0], scenes[0], t0 + timedelta(minutes=10), PEOPLE[1], None),
                _run(s, 910004, exps[1], cams[1], scenes[1], t0 + timedelta(minutes=10, seconds=40), PEOPLE[1], None)]
        s.commit()
    for rid in runs:
        aid = client.post(f"/api/relationships/runs/{rid}/analyse", json={"rules": []}, headers=admin).json()["id"]
        for _ in range(300):
            if client.get(f"/api/relationships/analyses/{aid}").json()["status"] != "running":
                break
            time.sleep(0.05)
    from pathscope.crosscam.service import get_crosscam_service

    get_crosscam_service().flush()
    yield {"admin": admin}
    for rid in runs:
        client.delete(f"/api/relationships/runs/{rid}", headers=admin)
    with get_session_factory()() as s:
        from pathscope.recognition.common.access import RecognitionAccessToken
        from pathscope.recognition.registry.models import RecognitionEvent

        s.query(RecognitionEvent).filter(RecognitionEvent.person_id.in_(PEOPLE)).delete(synchronize_session=False)
        s.query(RecognitionAccessToken).filter(RecognitionAccessToken.name == "provenance test admin").delete(synchronize_session=False)
        s.commit()
    client.delete(f"/api/locations/nodes/{site}", headers=admin)
    client.delete(f"/api/projects/{pid}")
    with get_session_factory()() as s:
        for p in PEOPLE:
            row = s.get(RecognitionPerson, p)
            if row is not None:
                s.delete(row)
        s.commit()


def _move(client, admin, person):
    items = client.get("/api/locations/transitions", params={"key": f"recognized_person:{person}"}, headers=admin).json()
    assert len(items) == 1
    return items[0]


def test_an_annotated_identity_is_not_reported_as_face_recognition(client, two_cameras):
    admin = two_cameras["admin"]
    t = _move(client, admin, PEOPLE[0])
    assert t["basis"] == "face" and t["components"]["identity_method"] == "annotation"
    assert "a reviewer identified the same person on both cameras" in t["reason"] and "face module" not in t["reason"]
    ident = [r for r in client.get("/api/relationships/list", params={"types": "IDENTIFIED_AS"}, headers=admin).json()["items"]
             if (r["object"] or {}).get("key") == f"recognized_person:{PEOPLE[0]}"]
    assert len(ident) == 2
    for r in ident:
        full = client.get(f"/api/relationships/relationship/{r['id']}", headers=admin).json()
        assert full["sources"] == ["annotation"] and "A reviewer identified" in full["reason"] and "face module" not in full["reason"]


def test_a_module_identity_keeps_its_wording(client, two_cameras):
    t = _move(client, two_cameras["admin"], PEOPLE[1])
    assert "identity_method" not in t["components"] and "the face module identified the same enrolled person" in t["reason"]
