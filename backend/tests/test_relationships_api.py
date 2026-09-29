"""Relationship engine wiring: versioned rules, run re-analysis, graph API, privacy, sensors, registry, retention."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from pathscope.db.models import Run, SceneConfig, TrackSummary, Trajectory
from pathscope.db.session import get_session_factory
from pathscope.relationships.models import RelationAudit, RelationEntity, RelationRelationship

PX = 20.0  # px per metre in the synthetic scene (1000 px wide, 0.05 m/px)
PERSON = {"classes": ["person"]}
VEHICLE = {"classes": ["car"]}
NEAR = {"kind": "pair", "name": "Beside vehicle", "subject": PERSON, "object": VEHICLE, "condition": "near",
        "distance": {"value": 2.0, "unit": "m", "fallback_fw": 0.04}, "for_s": 5, "relation": "ASSOCIATED_WITH"}
SCENE = {
    "frame_width": 1000, "frame_height": 1000,
    "objects": [{"id": "z_park", "name": "Parking 2", "type": "zone", "points": [{"x": 0.0, "y": 0.0}, {"x": 0.7, "y": 0.0}, {"x": 0.7, "y": 1.0}, {"x": 0.0, "y": 1.0}]},
                {"id": "z_bldg", "name": "Building A", "type": "zone", "points": [{"x": 0.7, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}, {"x": 0.7, "y": 1.0}]}],
    "calibration": {"unit": "m", "known_distance": {"a": {"x": 0.0, "y": 0.5}, "b": {"x": 1.0, "y": 0.5}, "distance": 50.0}},
}


def _token(role: str) -> dict:
    from pathscope.recognition.common.access import create_token

    with get_session_factory()() as s:
        _row, secret = create_token(s, f"relationships test {role}", role)
    return {"X-Recognition-Token": secret}


@pytest.fixture(scope="module")
def world(client):
    pid = client.post("/api/projects", json={"name": "Relationships"}).json()["id"]
    cid = client.post("/api/cameras", json={"project_id": pid, "name": "Yard cam", "source_type": "rtsp", "source_uri": "rtsp://example/stream"}).json()["id"]
    admin, viewer = _token("admin"), _token("viewer")
    rule = client.post("/api/relationships/rules", json={"definition": NEAR, "note": "first"}, headers=admin)
    assert rule.status_code == 201, rule.text
    key = rule.json()["key"]
    body = {"project_id": pid, "camera_id": cid, "name": "Yard", "object_classes": ["person", "car"], "relations": {"enabled": True, "rules": [{"key": key}], "remained_min_s": 5}}
    eid = client.post("/api/experiments", json=body).json()["id"]
    from pathscope.recognition.registry.models import RecognitionEvent, RecognitionPerson

    t0 = datetime.now(UTC) - timedelta(hours=1)
    with get_session_factory()() as s:
        sc = SceneConfig(camera_id=cid, version=1, name="v1", document=SCENE, frozen=True)
        s.add(sc)
        s.flush()
        run = Run(experiment_id=eid, camera_id=cid, scene_config_id=sc.id, status="completed", snapshot={"recognition": {"modules": ["face"]}}, stats={}, started_at=t0)
        s.add(run)
        s.flush()
        # a car parked at x = 22 m; a person walks from x = 5 m to its side, stays 20 s, then into the building
        person, car = [], []
        for i in range(400):
            t = i / 10
            x = 5 + 15 * min(1.0, t / 6) if t < 26 else 20 + (t - 26) * 1.5
            person.append([round(t, 3), round(x * PX / 1000, 4), 0.6])
            car.append([round(t, 3), 0.44, 0.6])
        for tid, cls, pts in ((1, "person", person), (2, "car", car)):
            s.add(Trajectory(run_id=run.id, track_id=tid, object_class=cls, points=pts, n_points=len(pts)))
            s.add(TrackSummary(run_id=run.id, track_id=tid, object_class=cls, first_seen_s=pts[0][0], last_seen_s=pts[-1][0], first_seen_at=t0, last_seen_at=t0 + timedelta(seconds=40),
                               n_frames=len(pts), mean_confidence=0.9))
        if s.get(RecognitionPerson, "relp1") is None:
            s.add(RecognitionPerson(id="relp1", display_name="Employee-017"))
        s.flush()
        s.add(RecognitionEvent(run_id=run.id, experiment_id=eid, camera_id=cid, track_id=1, object_class="person", module="face", kind="recognized", status="recognized",
                               person_id="relp1", confidence=0.93, media_time_s=2.0, wall_time=t0 + timedelta(seconds=2)))
        s.commit()
        run_id = run.id
    yield {"pid": pid, "cid": cid, "eid": eid, "run_id": run_id, "key": key, "admin": admin, "viewer": viewer}
    with get_session_factory()() as s:
        from pathscope.recognition.common.access import RecognitionAccessToken

        s.query(RecognitionEvent).filter(RecognitionEvent.run_id == run_id).delete()
        s.query(RecognitionAccessToken).filter(RecognitionAccessToken.name.like("relationships test%")).delete(synchronize_session=False)
        s.commit()
    client.delete(f"/api/projects/{pid}")
    with get_session_factory()() as s:
        p = s.get(RecognitionPerson, "relp1")
        if p is not None:
            s.delete(p)
        s.commit()


def _analyse(client, world, rules=None) -> dict:
    r = client.post(f"/api/relationships/runs/{world['run_id']}/analyse", json={"rules": rules}, headers=world["admin"])
    assert r.status_code == 202, r.text
    aid = r.json()["id"]
    for _ in range(200):
        a = client.get(f"/api/relationships/analyses/{aid}").json()
        if a["status"] != "running":
            break
        time.sleep(0.1)
    assert a["status"] == "done", a
    return a


def test_rules_are_versioned_not_overwritten(client, world):
    key, admin = world["key"], world["admin"]
    same = client.put(f"/api/relationships/rules/{key}", json={"definition": NEAR}, headers=admin)
    assert same.status_code == 409
    changed = client.put(f"/api/relationships/rules/{key}", json={"definition": {**NEAR, "for_s": 8}, "note": "stricter"}, headers=admin)
    assert changed.status_code == 200 and changed.json()["version"] == 2
    detail = client.get(f"/api/relationships/rules/{key}").json()
    assert [v["version"] for v in detail["versions"]] == [2, 1]
    assert detail["versions"][1]["definition"]["for_s"] == 5  # version 1 is untouched
    assert detail["latest"]["used_by"][0]["experiment_id"] == world["eid"]
    assert client.post("/api/relationships/rules", json={"definition": {**NEAR, "relation": "OWNS"}}, headers=admin).status_code == 422
    exp = client.get(f"/api/experiments/{world['eid']}").json()
    assert exp["relations"]["enabled"] is True and exp["relations"]["rules"][0]["key"] == key


def test_replay_analysis_and_provenance(client, world):
    a = _analyse(client, world, rules=[{"key": world["key"], "version": 1}])
    assert a["current"] and a["rules"][0]["version"] == 1 and a["calibration"]["measure"] == "physical"
    rels = client.get("/api/relationships/list", params={"run_id": world["run_id"]}).json()["items"]
    types = {r["type"] for r in rels}
    assert {"ASSOCIATED_WITH", "ENTERED", "EXITED", "REMAINED_IN", "MOVED_TO", "IDENTIFIED_AS"} <= types
    assoc = next(r for r in rels if r["type"] == "ASSOCIATED_WITH")
    assert assoc["rule"] == {"key": world["key"], "version": 1, "name": "Beside vehicle"}
    detail = client.get(f"/api/relationships/relationship/{assoc['id']}").json()
    assert "within 2.00 m" in detail["reason"] and detail["calibration"]["unit"] == "m"
    assert detail["rule_definition"]["for_s"] == 5 and detail["analysis"]["source"] == "replay"
    assert detail["components"]["temporal"] > 0.9
    # re-analysis with version 2 keeps version 1's results as a superseded interpretation
    b = _analyse(client, world, rules=[{"key": world["key"], "version": 2}])
    analyses = client.get("/api/relationships/analyses", params={"run_id": world["run_id"]}).json()
    assert [x["current"] for x in analyses if x["id"] in (a["id"], b["id"])] == [True, False]
    old = client.get("/api/relationships/list", params={"run_id": world["run_id"], "analysis_id": a["id"], "types": "ASSOCIATED_WITH"}).json()["items"]
    assert old and old[0]["rule"]["version"] == 1


def test_identities_are_hidden_without_permission(client, world):
    anon = client.get("/api/relationships/list", params={"run_id": world["run_id"], "types": "IDENTIFIED_AS"}).json()["items"]
    assert anon and anon[0]["object"]["redacted"] is True and anon[0]["object"]["key"] is None and anon[0]["object"]["label"] == "Recognized person"
    assert "Employee-017" not in str(anon)
    assert client.get("/api/relationships/entity", params={"key": "recognized_person:relp1"}).status_code == 401
    assert client.get("/api/relationships/entities", params={"type": "recognized_person"}).json() == []
    # an authorized viewer sees the name and the identity's projected neighbourhood
    v = world["viewer"]
    nb = client.get("/api/relationships/entity/neighbors", params={"key": "recognized_person:relp1"}, headers=v).json()
    assert nb["entity"]["label"] == "Employee-017"
    assoc = [g for g in nb["related"] if "ASSOCIATED_WITH" in g["types"]]
    assert assoc and assoc[0]["entity"]["type"] == "vehicle_track"
    assert assoc[0]["relationships"][0]["via"]["type"] == "person_track"  # the original track is kept
    with get_session_factory()() as s:
        assert s.query(RelationAudit).filter(RelationAudit.action == "identity_viewed").count() >= 1
    hist = client.get("/api/relationships/entity/history", params={"key": "recognized_person:relp1"}, headers=v).json()
    assert hist["sessions"] == 1 and hist["tracks"] == 1 and hist["entries"]
    # a name in a timeline only for the authorized viewer
    tl_anon = client.get("/api/relationships/timeline", params={"run_id": world["run_id"]}).json()["items"]
    tl_v = client.get("/api/relationships/timeline", params={"run_id": world["run_id"]}, headers=v).json()["items"]
    assert "Employee-017" not in str(tl_anon) and "Employee-017" in str(tl_v)


def test_timeline_summary_and_search(client, world):
    s = client.post("/api/relationships/summary", json={"run_id": world["run_id"], "tz_offset_min": 240, "min_state": "possible"}).json()
    text = s["deterministic"]["text"]
    assert "entered Parking 2" in text and "associated with Vehicle track #2" in text and s["model"] is None
    parking = next(e for e in client.get("/api/relationships/entities", params={"type": "zone"}).json() if e["label"] == "Building A")
    car_key = next(e["key"] for e in client.get("/api/relationships/entities", params={"run_id": world["run_id"], "type": "vehicle_track"}).json())
    res = client.get("/api/relationships/search", params={"kind": "entered_after", "key": car_key, "zone_key": parking["key"], "window_s": 600}).json()
    assert [i["entity"]["type"] for i in res["items"]] == ["person_track"]
    near = client.get("/api/relationships/search", params={"kind": "near", "key": car_key, "target": "person"}).json()
    assert near["items"] and near["items"][0]["entity"]["type"] == "person_track"
    g = client.get("/api/relationships/entity/graph", params={"key": car_key}).json()
    assert any(e["type"] == "ASSOCIATED_WITH" for e in g["edges"])
    assert client.post("/api/relationships/summary", json={"run_id": world["run_id"], "llm": True}).status_code == 403  # off by default


def test_sensor_corroboration_changes_confidence(client, world):
    assoc = client.get("/api/relationships/list", params={"run_id": world["run_id"], "types": "ASSOCIATED_WITH"}).json()["items"][0]
    before = assoc["confidence"]
    body = {"sensor_id": "depth-01", "sensor_type": "depth", "run_id": world["run_id"], "media_time_s": 15.0,
            "subject": {"track_id": 1}, "object": {"track_id": 2}, "measurement": {"kind": "distance", "value": 0.9, "unit": "m"}}
    r = client.post("/api/relationships/observations", json=body, headers=world["admin"])
    assert r.status_code == 201, r.text
    hit = [c for c in r.json()["corroborated"] if c["relationship_id"] == assoc["id"]]
    assert hit and hit[0]["agrees"]
    after = client.get(f"/api/relationships/relationship/{assoc['id']}").json()
    assert "depth" in after["sources"] and after["components"]["sensor"] == 1.0 and after["confidence"] >= before
    assert any(o["source"] == "depth" for o in after["evidence"]["observations"])


def test_registry_only_for_external_types_and_admins(client, world):
    admin = world["admin"]
    item = {"relation": "COWORKER", "subject": "recognized_person:relp1", "object": "recognized_person:relp2"}
    assert client.post("/api/relationships/registry", json={"source": "HR", "items": [item]}, headers=world["viewer"]).status_code == 403
    assert client.post("/api/relationships/registry", json={"source": "HR", "items": [item]}, headers=admin).status_code == 422
    settings = client.get("/api/relationships/settings").json()["settings"]
    settings["custom_types"] = [{"id": "COWORKER", "label": "works with", "external_only": True}]
    assert client.put("/api/relationships/settings", json=settings, headers=world["viewer"]).status_code == 403
    assert client.put("/api/relationships/settings", json=settings, headers=admin).status_code == 200
    r = client.post("/api/relationships/registry", json={"source": "HR", "items": [item]}, headers=admin)
    assert r.status_code == 201 and r.json()["imported"] == 1
    rid = r.json()["ids"][0]
    rel = client.get(f"/api/relationships/relationship/{rid}", headers=admin).json()
    assert rel["sources"] == ["registry"] and "not inferred from observation" in rel["reason"]
    # a rule still cannot produce it
    assert client.post("/api/relationships/rules", json={"definition": {**NEAR, "relation": "COWORKER"}}, headers=admin).status_code == 422
    assert client.delete(f"/api/relationships/relationship/{rid}", headers=admin).status_code == 204
    settings["custom_types"] = []
    client.put("/api/relationships/settings", json=settings, headers=admin)


def test_export_permissions(client, world):
    r = client.get("/api/relationships/export", params={"run_id": world["run_id"]})
    assert r.status_code == 200 and "Employee-017" not in r.text and "ASSOCIATED_WITH" in r.text
    assert client.get("/api/relationships/export", params={"run_id": world["run_id"], "identities": True}, headers=world["viewer"]).status_code == 403
    r = client.get("/api/relationships/export", params={"run_id": world["run_id"], "identities": True, "format": "json"}, headers=world["admin"])
    assert r.status_code == 200 and "Employee-017" in r.text


def test_identity_retention(client, world):
    from pathscope.relationships.service import get_relationship_service

    settings = client.get("/api/relationships/settings").json()["settings"]
    settings["retention"]["identity_days"] = 1
    assert client.put("/api/relationships/settings", json=settings, headers=world["admin"]).status_code == 200
    out = get_relationship_service().sweep(now=datetime.now(UTC) + timedelta(days=3))
    assert out["identity_links"] >= 1
    with get_session_factory()() as s:
        assert s.query(RelationRelationship).filter(RelationRelationship.relation_type == "IDENTIFIED_AS", RelationRelationship.run_id == world["run_id"]).count() == 0
        assert s.query(RelationEntity).filter(RelationEntity.key == "recognized_person:relp1").count() == 0
        assert s.query(RelationRelationship).filter(RelationRelationship.relation_type == "ASSOCIATED_WITH", RelationRelationship.run_id == world["run_id"]).count() >= 1
    settings["retention"]["identity_days"] = 30
    client.put("/api/relationships/settings", json=settings, headers=world["admin"])
