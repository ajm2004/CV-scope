"""Location Engine and cross-camera correlation: topology, transitions with provenance,
journeys, topology deviations, the visual graph, privacy."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from pathscope.db.models import Run, SceneConfig, TrackSummary, Trajectory
from pathscope.db.session import get_session_factory
from pathscope.location.topology import LocationGraph

W = 1000
ZONE = {"id": "z_main", "type": "zone", "points": [{"x": 0.3, "y": 0.0}, {"x": 0.7, "y": 0.0}, {"x": 0.7, "y": 1.0}, {"x": 0.3, "y": 1.0}]}
CAL = {"unit": "m", "known_distance": {"a": {"x": 0.0, "y": 0.5}, "b": {"x": 1.0, "y": 0.5}, "distance": 50.0}}


def _token(role: str) -> dict:
    from pathscope.recognition.common.access import create_token

    with get_session_factory()() as s:
        _row, secret = create_token(s, f"crosscam test {role}", role)
    return {"X-Recognition-Token": secret}


def _scene(name: str) -> dict:
    return {"frame_width": W, "frame_height": W, "objects": [{**ZONE, "name": name}], "calibration": CAL}


def _run(s, eid: int, cid: int, scid: int, t0: datetime, people: list[tuple[int, str | None, float]], duration: float = 20.0) -> int:
    """One run: each person walks left to right through the zone in ``duration`` seconds."""
    from pathscope.recognition.registry.models import RecognitionEvent

    run = Run(experiment_id=eid, camera_id=cid, scene_config_id=scid, status="completed", snapshot={"recognition": {"modules": ["face"]}}, stats={}, started_at=t0, ended_at=t0 + timedelta(seconds=duration))
    s.add(run)
    s.flush()
    for tid, person, conf in people:
        pts = [[round(i / 10, 3), round(0.05 + 0.9 * (i / 10) / duration, 4), 0.6] for i in range(int(duration * 10) + 1)]
        s.add(Trajectory(run_id=run.id, track_id=tid, object_class="person", points=pts, n_points=len(pts)))
        s.add(TrackSummary(run_id=run.id, track_id=tid, object_class="person", first_seen_s=0.0, last_seen_s=duration, first_seen_at=t0,
                           last_seen_at=t0 + timedelta(seconds=duration), n_frames=len(pts), mean_confidence=0.9))
        if person:
            s.add(RecognitionEvent(run_id=run.id, experiment_id=eid, camera_id=cid, track_id=tid, object_class="person", module="face", kind="recognized",
                                   status="recognized", person_id=person, confidence=conf, media_time_s=2.0, wall_time=t0 + timedelta(seconds=2)))
    s.flush()
    return run.id


def _analyse(client, run_id: int, admin: dict) -> None:
    r = client.post(f"/api/relationships/runs/{run_id}/analyse", json={"rules": []}, headers=admin)
    assert r.status_code == 202, r.text
    aid = r.json()["id"]
    for _ in range(300):
        a = client.get(f"/api/relationships/analyses/{aid}").json()
        if a["status"] != "running":
            break
        time.sleep(0.05)
    assert a["status"] == "done", a


def _node(client, admin, **body) -> int:
    r = client.post("/api/locations/nodes", json=body, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def site(client):
    from pathscope.recognition.registry.models import RecognitionPerson

    admin, viewer = _token("admin"), _token("viewer")
    pid = client.post("/api/projects", json={"name": "Campus"}).json()["id"]
    names = ["Gate cam", "Corridor cam", "Parking cam", "Lab cam"]
    cams = [client.post("/api/cameras", json={"project_id": pid, "name": n, "source_type": "rtsp", "source_uri": f"rtsp://example/{i}"}).json()["id"] for i, n in enumerate(names)]
    zone_names = ["Gate A", "Corridor B", "Parking 4", "Lab"]
    exps, scenes = [], []
    with get_session_factory()() as s:
        for cid, zn in zip(cams, zone_names, strict=True):
            sc = SceneConfig(camera_id=cid, version=1, name="v1", document=_scene(zn), frozen=True)
            s.add(sc)
            s.flush()
            scenes.append(sc.id)
        for pid_, name in (("ccp1", "Employee-017"), ("ccp2", "Visitor-2"), ("ccp3", "Contractor-3")):
            if s.get(RecognitionPerson, pid_) is None:
                s.add(RecognitionPerson(id=pid_, display_name=name))
        s.commit()
    for cid in cams:
        body = {"project_id": pid, "camera_id": cid, "name": f"exp {cid}", "object_classes": ["person"], "relations": {"enabled": True, "rules": []}}
        exps.append(client.post("/api/experiments", json=body).json()["id"])

    # location model: Campus (200 x 100 m plan) with a gate, a corridor, a parking area, a restricted lab and four cameras
    campus = _node(client, admin, kind="site", name="Campus", layout={"mode": "plan", "width": 200, "height": 100, "unit": "m"})
    gate = _node(client, admin, kind="gate", name="Gate North", parent_id=campus, x=10, y=50, is_entry=True)
    corridor = _node(client, admin, kind="corridor", name="Corridor B", parent_id=campus, x=60, y=50)
    parking = _node(client, admin, kind="parking", name="Parking Zone 4", parent_id=campus, x=150, y=50)
    lab = _node(client, admin, kind="room", name="Lab", parent_id=campus, x=100, y=90, restricted=True)
    cam_nodes = [_node(client, admin, kind="camera", name=n, camera_id=c, parent_id=campus, x=x, y=40, orientation_deg=90, fov_deg=70, view_range=20)
                 for n, c, x in zip(names, cams, (10, 60, 150, 100), strict=True)]
    links = [
        {"source_id": cam_nodes[0], "target_id": cam_nodes[1], "kind": "CONNECTED_TO", "travel_min_s": 30, "travel_max_s": 90, "via_id": corridor},
        {"source_id": cam_nodes[1], "target_id": cam_nodes[2], "kind": "LEADS_TO", "one_way": True, "travel_min_s": 60, "travel_max_s": 125},
        {"source_id": gate, "target_id": corridor, "kind": "CONNECTED_TO"},
    ]
    for lk in links:
        r = client.post("/api/locations/links", json=lk, headers=admin)
        assert r.status_code == 201, r.text
    for cid, node in zip(cams, (gate, corridor, parking, lab), strict=True):
        r = client.put(f"/api/locations/cameras/{cid}/zones", json=[{"object_id": "z_main", "object_kind": "zone", "node_id": node}], headers=admin)
        assert r.status_code == 200 and r.json()["items"][0]["node_id"] == node

    t0 = datetime.now(UTC) - timedelta(hours=2)
    with get_session_factory()() as s:
        # Employee-017: Gate cam -> Corridor cam (40 s later) -> Parking cam (120 s later)
        r1 = _run(s, exps[0], cams[0], scenes[0], t0, [(1, "ccp1", 0.96)])
        r2 = _run(s, exps[1], cams[1], scenes[1], t0 + timedelta(seconds=60), [(1, "ccp1", 0.95)])
        r3 = _run(s, exps[2], cams[2], scenes[2], t0 + timedelta(seconds=200), [(1, "ccp1", 0.94)])
        # Visitor-2: Parking cam, then Corridor cam only 10 s later (the link is one-way and takes 60-125 s)
        t1 = t0 + timedelta(minutes=20)
        r4 = _run(s, exps[2], cams[2], scenes[2], t1, [(1, "ccp2", 0.95)])
        r5 = _run(s, exps[1], cams[1], scenes[1], t1 + timedelta(seconds=30), [(1, "ccp2", 0.95)])
        # Contractor-3: seen only in the restricted lab, never at the gate
        r6 = _run(s, exps[3], cams[3], scenes[3], t0 + timedelta(minutes=40), [(1, "ccp3", 0.95)])
        s.commit()
    runs = [r1, r2, r3, r4, r5, r6]
    for rid in runs:
        _analyse(client, rid, admin)
    from pathscope.crosscam.service import get_crosscam_service

    get_crosscam_service().flush()  # the analyses queued their runs
    yield {"admin": admin, "viewer": viewer, "cams": cams, "runs": runs, "nodes": {"campus": campus, "gate": gate, "corridor": corridor, "parking": parking, "lab": lab},
           "cam_nodes": cam_nodes, "pid": pid, "t0": t0}
    with get_session_factory()() as s:
        from pathscope.recognition.common.access import RecognitionAccessToken
        from pathscope.recognition.registry.models import RecognitionEvent

        people = ["ccp1", "ccp2", "ccp3"]
        s.query(RecognitionEvent).filter(RecognitionEvent.person_id.in_(people)).delete(synchronize_session=False)
        s.query(RecognitionAccessToken).filter(RecognitionAccessToken.name.like("crosscam test%")).delete(synchronize_session=False)
        s.commit()
    client.delete(f"/api/locations/nodes/{campus}", headers=admin)
    client.delete(f"/api/projects/{pid}")
    with get_session_factory()() as s:
        for p in people:
            row = s.get(RecognitionPerson, p)
            if row is not None:
                s.delete(row)
        s.commit()


def test_topology_reasoning(client, site):
    n, cams = site["nodes"], site["cams"]
    with get_session_factory()() as s:
        g = LocationGraph.load(s)
    assert g.path_label(n["gate"]) == "Campus / Gate North"
    assert g.cameras_in(n["campus"]) == set(cams)
    assert g.resolve_key(f"zone:c{cams[0]}.z_main") == n["gate"]
    direct = g.camera_transition(cams[0], cams[1])
    assert direct.kind == "direct" and direct.travel.min_s == 30 and direct.via == [n["corridor"]]
    back = g.camera_transition(cams[2], cams[1])
    assert back.wrong_way  # LEADS_TO is one-way
    assert g.camera_transition(cams[0], cams[3]).kind == "unconnected"
    chk = client.get("/api/locations/check", params={"from_camera": cams[0], "to_camera": cams[2]}).json()
    assert chk["kind"] == "path" and chk["travel"]["min_s"] == 90 and chk["travel"]["max_s"] == 215
    bad = client.post("/api/locations/nodes", json={"kind": "camera", "name": "dup", "camera_id": cams[0], "parent_id": n["campus"]}, headers=site["admin"])
    assert bad.status_code == 409
    loop = client.put(f"/api/locations/nodes/{n['campus']}", json={"kind": "site", "name": "Campus", "parent_id": n["gate"]}, headers=site["admin"])
    assert loop.status_code == 422


def test_transitions_with_provenance(client, site):
    v = site["viewer"]
    items = client.get("/api/locations/transitions", params={"key": "recognized_person:ccp1"}, headers=v).json()
    assert len(items) == 2
    by_from = {t["from"]["camera"]["id"]: t for t in items}
    a = by_from[site["cams"][0]]
    assert a["to"]["camera"]["id"] == site["cams"][1]
    assert a["gap_s"] == pytest.approx(40, abs=1.0)
    assert a["expected"] == {"min_s": 30.0, "max_s": 90.0, "source": "link"}
    assert a["topology"]["kind"] == "direct" and 0.85 < a["identity_confidence"] < 0.97  # the identity links' own confidence
    assert a["state"] in ("confirmed", "likely") and a["basis"] == "face" and not a["flags"]
    assert a["from"]["node"]["name"] == "Gate North" and a["to"]["node"]["name"] == "Corridor B"
    assert "Expected travel time: 30–90 s" in a["reason"] and "Employee-017" not in a["reason"]
    assert a["subject"]["label"] == "Employee-017"
    b = by_from[site["cams"][1]]
    assert b["gap_s"] == pytest.approx(120, abs=1.0) and b["to"]["node"]["name"] == "Parking Zone 4"
    # mirrored into the relationship graph, with evidence back to both identity links
    rid = a["relationships"]["moved_to"]
    rel = client.get(f"/api/relationships/relationship/{rid}", headers=v).json()
    assert rel["type"] == "MOVED_TO" and rel["rule"]["key"] == "crosscam" and rel["object"]["label"] == "Corridor B"
    assert sum(1 for r in rel["evidence"]["relationships"] if r["type"] == "IDENTIFIED_AS") == 2
    types = {r["type"] for r in client.get("/api/relationships/list", params={"types": "ENTERED_SITE_AT,SEEN_AT,MOVED_FROM,MOVED_THROUGH"}, headers=v).json()["items"]
             if (r["subject"] or {}).get("key") == "recognized_person:ccp1"}
    assert types == {"ENTERED_SITE_AT", "SEEN_AT", "MOVED_FROM", "MOVED_THROUGH"}


def test_journey_and_last_seen(client, site):
    v = site["viewer"]
    j = client.get("/api/locations/journey", params={"key": "recognized_person:ccp1"}, headers=v).json()
    assert [s["camera"]["name"] for s in j["sightings"]] == ["Gate cam", "Corridor cam", "Parking cam"]
    assert [p["node"]["name"] for p in j["path"]] == ["Gate North", "Corridor B", "Parking Zone 4"]
    assert j["sightings"][0]["events"][0]["verb"] == "Entered" and j["sightings"][0]["events"][0]["place"] == "Gate A"
    assert [(t["from_index"], t["to_index"]) for t in j["transitions"]] == [(0, 1), (1, 2)]
    last = client.get("/api/locations/last-seen", params={"key": "recognized_person:ccp1"}, headers=v).json()
    assert last["last"]["camera"]["name"] == "Parking cam" and last["last"]["node"]["name"] == "Parking Zone 4"


def test_topology_deviations(client, site):
    v = site["viewer"]
    devs = client.get("/api/locations/deviations", headers=v).json()
    kinds = {d["metrics"]["type"] for d in devs}
    assert {"implausible_time", "wrong_way", "restricted_without_entry"} <= kinds
    fast = next(d for d in devs if d["metrics"]["type"] == "implausible_time")
    assert "10 s after" in fast["description"] and "60–125 s" in fast["description"]
    assert "Visitor-2" not in fast["description"]  # stored text never holds a name
    restricted = next(d for d in devs if d["metrics"]["type"] == "restricted_without_entry")
    assert "Lab" in restricted["description"]
    # the Visitor's transition itself stays, with a low confidence and its flags
    t = next(t for t in client.get("/api/locations/transitions", params={"key": "recognized_person:ccp2"}, headers=v).json())
    assert set(t["flags"]) >= {"implausible_time", "wrong_way"} and t["state"] in ("insufficient", "possible")
    # published as ordinary events of the run they anchor to
    ev = client.get("/api/events", params={"run_id": site["runs"][4]}).json()
    items = ev["items"] if isinstance(ev, dict) else ev
    assert any(e["event_type"] == "location_anomaly" for e in items)


def test_visual_graph_time_and_path(client, site):
    v = site["viewer"]
    g = client.get("/api/relationships/visual", params={"key": "recognized_person:ccp1"}, headers=v).json()
    natures = {e["nature"] for e in g["edges"]}
    assert {"cross_camera", "observed", "context"} <= natures
    moved = [e for e in g["edges"] if e["type"] == "MOVED_TO"]
    assert moved and all(e["intervals"][0]["start"] for e in moved)
    assert g["time_range"]["start"] and g["time_range"]["end"] and g["center"] == "recognized_person:ccp1"
    klass = {n["klass"] for n in g["nodes"]}
    assert {"identity", "location", "camera"} <= klass
    # the tracks are merged into the identity unless asked otherwise
    raw = client.get("/api/relationships/visual", params={"key": "recognized_person:ccp1", "project": False}, headers=v).json()
    assert any(n["klass"] == "track" for n in raw["nodes"]) and not any(n["klass"] == "track" for n in g["nodes"])
    parking = f"location:{site['nodes']['parking']}"
    p = client.get("/api/relationships/visual/path", params={"from_key": "recognized_person:ccp1", "to_key": parking}, headers=v).json()
    assert p["found"] and parking in p["path_nodes"]
    # a location filter narrows everything to the cameras inside it
    scoped = client.get("/api/relationships/visual", params={"location_id": site["nodes"]["campus"]}, headers=v).json()
    assert scoped["nodes"]
    assert client.get("/api/relationships/visual").status_code == 422


def test_privacy_of_identity_transitions(client, site):
    assert client.get("/api/locations/transitions").json() == []  # identity-based moves are not shown anonymously
    assert client.get("/api/locations/journey", params={"key": "recognized_person:ccp1"}).status_code == 401
    anon = client.get("/api/relationships/list", params={"types": "MOVED_TO"}).json()["items"]
    assert anon and all(r["subject"]["redacted"] for r in anon if r["rule"]["key"] == "crosscam")
    assert "Employee-017" not in str(client.get("/api/locations/live", params={"root_id": site["nodes"]["campus"]}).json())


def test_time_fit():
    from pathscope.crosscam.engine import time_fit
    from pathscope.location.settings import CrossCameraSettings
    from pathscope.location.topology import Travel

    s = CrossCameraSettings()
    link = Travel(30.0, 90.0, "link")
    assert time_fit(40, link, s).certainty == 1.0
    assert time_fit(10, link, s).flags == ["implausible_time"]
    assert time_fit(20, link, s).flags == ["faster_than_expected"]
    assert time_fit(300, link, s).flags == ["slower_than_expected"] and time_fit(300, link, s).certainty == pytest.approx(0.3)
    assert time_fit(-10, link, s).flags == ["simultaneous"]
    assert time_fit(-10, link, s, overlap=True).flags == []
    unknown = time_fit(100, Travel(None, None, "unknown"), s)
    assert unknown.certainty == pytest.approx(0.7) and unknown.hi == s.default_max_s


def _settings(client, admin, **changes) -> dict:
    cur = client.get("/api/locations/settings").json()["settings"]
    r = client.put("/api/locations/settings", json={**cur, **changes}, headers=admin)
    assert r.status_code == 200, r.text
    return cur


def test_anonymous_transitions_are_opt_in_and_capped(client, site):
    from pathscope.crosscam.service import get_crosscam_service

    admin, cams = site["admin"], site["cams"]
    exps = {r["camera_id"]: r["id"] for r in client.get("/api/experiments", params={"project_id": site["pid"]}).json()}
    t = datetime.now(UTC) - timedelta(hours=6)
    with get_session_factory()() as s:
        sc = {c: s.query(SceneConfig).filter(SceneConfig.camera_id == c).one().id for c in cams[:2]}
        a = _run(s, exps[cams[0]], cams[0], sc[cams[0]], t, [(7, None, 0.0)])
        b = _run(s, exps[cams[1]], cams[1], sc[cams[1]], t + timedelta(seconds=60), [(9, None, 0.0)])
        s.commit()
    for rid in (a, b):
        _analyse(client, rid, admin)
    get_crosscam_service().flush()
    key = f"person_track:r{a}.t7"
    assert client.get("/api/locations/transitions", params={"key": key}).json() == []  # off by default
    old = _settings(client, admin, anonymous=True)
    try:
        get_crosscam_service().correlate({a, b})
        items = client.get("/api/locations/transitions", params={"key": key}).json()
        assert len(items) == 1 and items[0]["basis"] == "anonymous" and items[0]["confidence"] <= 0.64 and items[0]["state"] in ("possible", "insufficient")
        assert "timing alone" in items[0]["reason"]
        j = client.get("/api/locations/journey", params={"key": key}).json()
        assert [x["camera"]["name"] for x in j["sightings"]] == ["Gate cam", "Corridor cam"]
        cont = client.get("/api/relationships/list", params={"types": "CONTINUED_AS"}).json()["items"]
        assert any(r["subject"]["key"] == key and r["object"]["key"] == f"person_track:r{b}.t9" for r in cont)
    finally:
        _settings(client, admin, **{**old, "anonymous": False})


def test_unusual_camera_sequence(client, site):
    from pathscope.crosscam.service import get_crosscam_service

    admin, cams = site["admin"], site["cams"]
    exps = {r["camera_id"]: r["id"] for r in client.get("/api/experiments", params={"project_id": site["pid"]}).json()}
    old = _settings(client, admin, history_min_journeys=2, journey_break_s=1800)
    try:
        with get_session_factory()() as s:
            sc = {c: s.query(SceneConfig).filter(SceneConfig.camera_id == c).one().id for c in cams}
            earlier = datetime.now(UTC) - timedelta(days=1, hours=2)
            j0 = [_run(s, exps[cams[0]], cams[0], sc[cams[0]], earlier, [(1, "ccp1", 0.95)]),
                  _run(s, exps[cams[1]], cams[1], sc[cams[1]], earlier + timedelta(seconds=60), [(1, "ccp1", 0.95)])]
            later = datetime.now(UTC) - timedelta(minutes=30)
            j2 = [_run(s, exps[cams[0]], cams[0], sc[cams[0]], later, [(1, "ccp1", 0.95)]),
                  _run(s, exps[cams[3]], cams[3], sc[cams[3]], later + timedelta(seconds=50), [(1, "ccp1", 0.95)])]
            s.commit()
        for rid in j0 + j2:
            _analyse(client, rid, admin)
        svc = get_crosscam_service()
        svc.flush()
        svc.correlate(set(j2))  # now that the earlier journeys are stored
        devs = [d for d in client.get("/api/locations/deviations", headers=site["viewer"]).json() if d["run_id"] == j2[1]]
        kinds = {d["metrics"]["type"] for d in devs}
        assert {"unusual_sequence", "unconnected"} <= kinds
        unusual = next(d for d in devs if d["metrics"]["type"] == "unusual_sequence")
        assert "0 of 2 earlier journeys" in unusual["description"] and "usually went to Corridor cam" in unusual["description"]
    finally:
        _settings(client, admin, **old)


def test_rebuild_is_idempotent_and_follows_reanalysis(client, site):
    from pathscope.crosscam.service import get_crosscam_service
    from pathscope.location.models import CrossCameraTransition

    svc = get_crosscam_service()
    before = svc.correlate(set(site["runs"]))
    again = svc.correlate(set(site["runs"]))
    assert again["transitions"] == before["transitions"] and again["withdrawn"] == 0
    with get_session_factory()() as s:
        active = s.query(CrossCameraTransition).filter(CrossCameraTransition.status == "active").count()
    assert active >= 3
    # removing the corridor run's analysis withdraws the moves through it
    runs = client.get("/api/relationships/analyses", params={"run_id": site["runs"][1]}).json()
    for a in runs:
        assert client.delete(f"/api/relationships/analyses/{a['id']}", headers=site["admin"]).status_code == 204
    svc.flush()
    window = {"time_from": (site["t0"] - timedelta(minutes=1)).isoformat(), "time_to": (site["t0"] + timedelta(minutes=10)).isoformat()}
    items = client.get("/api/locations/transitions", params={"key": "recognized_person:ccp1", **window}, headers=site["viewer"]).json()
    moves = {(t["from"]["camera"]["name"], t["to"]["camera"]["name"]): t for t in items}
    assert ("Gate cam", "Parking cam") in moves and ("Gate cam", "Corridor cam") not in moves and ("Corridor cam", "Parking cam") not in moves
    assert moves[("Gate cam", "Parking cam")]["topology"]["kind"] == "path"  # through the corridor camera's links
