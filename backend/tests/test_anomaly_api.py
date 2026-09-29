"""Anomaly Assistant wiring: experiment settings, run configuration, publication modes, the model queue and the API."""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from pathscope.anomaly import service
from pathscope.anomaly.llm.client import Interpretation, LLMError
from pathscope.anomaly.models import AnomalyEvent
from pathscope.db.models import Event, Experiment, Run
from pathscope.db.session import get_session_factory
from pathscope.domain.scene import SceneDocument
from pathscope.services.run_launcher import LaunchError, anomaly_for_run

ZONE = {"id": "zone_vault", "name": "Vault", "sensitivity": "medium"}


class FakeSupervisor:
    def __init__(self) -> None:
        self.published: list[dict] = []
        self.notified: list[tuple[list[str], dict]] = []

    def publish_events(self, handle, events):
        self.published.extend(events)

    def notify(self, handle, urls, payload):
        self.notified.append((urls, payload))


def _setup(client, anomaly: dict | None = None) -> tuple[int, int, int]:
    pid = client.post("/api/projects", json={"name": "Vault watch"}).json()["id"]
    cid = client.post("/api/cameras", json={"project_id": pid, "name": "Vault cam", "source_type": "usb", "source_uri": "0"}).json()["id"]
    body = {"project_id": pid, "camera_id": cid, "name": "Vault", "anomaly": anomaly or {"enabled": True, "zones": [ZONE]}}
    eid = client.post("/api/experiments", json=body).json()["id"]
    return pid, cid, eid


def _run(eid: int, cid: int) -> int:
    with get_session_factory()() as s:
        run = Run(experiment_id=eid, camera_id=cid, status="running", snapshot={}, stats={})
        s.add(run)
        s.commit()
        return run.id


def _handle(run_id: int, eid: int, cid: int, policy: str = "raise"):
    spec = SimpleNamespace(experiment_id=eid, camera_id=cid, anomaly={"settings": {"on_llm_failure": policy}}, webhooks_enabled=True)
    return SimpleNamespace(run_id=run_id, spec=spec, finished=False)


def _evidence(run_id: int, uid: str) -> dict:
    folder = service.run_dir(run_id) / uid
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in ("before", "overlay", "crop_before", "crop_event"):
        cv2.imwrite(str(folder / f"{name}.jpg"), np.full((60, 80, 3), 120, np.uint8))
        out[name] = f"{uid}/{name}.jpg"
    return out


def _update(run_id: int, uid: str, validation: str = "deterministic", phase: str = "confirmed", interpret_at: str = "confirm", **extra) -> dict:
    now = time.time()
    d = {
        "phase": phase, "uid": uid, "zone_id": "zone_vault", "zone_name": "Vault", "kind": "presence", "confidence": 0.93, "area_pct": 12.5,
        "bbox": [0.1, 0.2, 0.4, 0.9], "started_t": 10.0, "confirmed_t": 12.5, "ended_t": None, "wall_started": now - 5, "wall_confirmed": now - 2.5,
        "wall_ended": None, "duration_s": None, "end_reason": None, "objects": [{"track_id": 3, "object_class": "person", "confidence": 0.9}],
        "subjects": [{"alias": "Person A", "track_id": 3, "object_class": "person", "kind": "enrolled_person", "identity_id": "p_1", "status": "recognized"}],
        "metrics": {"area_pct": 12.5}, "summary": "[Person A] (recognized person) entered Vault.",
        "zone": {"validation": validation, "interpret_at": interpret_at, "webhooks": ["http://127.0.0.1:9/hook"], "record_clip": True, "expected_state": "Nobody inside."},
        "instant": False, "evidence": _evidence(run_id, uid) if phase == "confirmed" else {},
    }
    d.update(extra)
    return d


def _ended(uid: str, duration: float = 18.0) -> dict:
    now = time.time()
    return {"phase": "ended", "uid": uid, "kind": "presence", "confidence": 0.95, "ended_t": 10.0 + duration, "wall_ended": now, "duration_s": duration,
            "end_reason": "cleared", "summary": "[Person A] (recognized person) entered Vault; lasted 18 s, back to normal.", "subjects": [], "metrics": {"peak_area_pct": 14.0},
            "evidence": {}, "instant": False}


def _row(uid: str) -> AnomalyEvent:
    with get_session_factory()() as s:
        return s.query(AnomalyEvent).filter_by(uid=uid).one()


def _wait(uid: str, states=("done", "failed", "skipped")) -> AnomalyEvent:
    deadline = time.time() + 10
    while time.time() < deadline:
        row = _row(uid)
        if row.llm_status in states:
            return row
        time.sleep(0.05)
    raise AssertionError(f"model job of {uid} did not finish: {row.llm_status}")


@pytest.fixture
def model(client, monkeypatch):
    """A selected local model whose answers the test decides."""
    client.put("/api/anomaly/assistant", json={"provider": "local", "model": "qwen2.5vl:3b"})
    answers: list = []

    def fake(settings, key, record, pictures, http=None):
        answer = answers.pop(0) if answers else "confirmed"
        if isinstance(answer, Exception):
            raise answer
        assert "Alice" not in str(record) and [n for n, _ in pictures][:2] == ["before", "overlay"]
        return Interpretation(answer, "person", "[Person A] entered the normally empty Vault.", 0.8, "a person by the door", settings.provider, settings.resolved_model, 12.0, len(pictures))

    monkeypatch.setattr(service, "interpret", fake)
    yield answers
    client.put("/api/anomaly/assistant", json={"provider": "none"})


# ---------------------------------------------------------------------------- settings and run configuration
def test_experiments_keep_their_anomaly_settings(client):
    _, _, eid = _setup(client, {"enabled": True, "zones": [{**ZONE, "validation": "confirmed", "persistence_s": 6, "webhooks": ["https://example.org/alert"]}], "lighting_events": True})
    e = client.get(f"/api/experiments/{eid}").json()
    z = e["anomaly"]["zones"][0]
    assert e["anomaly"]["enabled"] and z["validation"] == "confirmed" and z["persistence_s"] == 6 and e["anomaly"]["lighting_events"]
    assert client.post(f"/api/experiments/{eid}/duplicate").json()["anomaly"]["zones"][0]["id"] == "zone_vault"
    assert client.put(f"/api/experiments/{eid}", json={"anomaly": {"enabled": True, "zones": [{**ZONE, "webhooks": ["ftp://x"]}]}}).status_code == 422
    assert client.put(f"/api/experiments/{eid}", json={"anomaly": {"enabled": False}}).json()["anomaly"]["enabled"] is False


def test_run_configuration_takes_polygons_from_the_scene_version():
    doc = SceneDocument.model_validate({"frame_width": 640, "frame_height": 480, "objects": [
        {"id": "zone_vault", "type": "zone", "name": "Vault", "points": [{"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.6}]},
        {"id": "tv", "type": "ignore", "name": "TV", "points": [{"x": 0.7, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.3}]},
    ]})
    exp = Experiment(name="x", anomaly={"enabled": True, "zones": [{"id": "zone_vault"}, {"id": "gone", "name": "Old zone"}, {"id": "frame"}]})
    cfg, warnings = anomaly_for_run(exp, doc)
    assert list(cfg["zones"]) == ["zone_vault"] and cfg["zones"]["zone_vault"][1] == [0.5, 0.1]
    assert cfg["ignore"] == [[[0.7, 0.1], [0.9, 0.1], [0.9, 0.3]]]
    assert cfg["settings"]["zones"][0]["name"] == "Vault"  # the scene's name fills an empty one
    assert warnings == ["Anomaly zone 'Old zone' is not a zone of this scene version and is not watched."]
    with pytest.raises(LaunchError, match="none of its zones"):
        anomaly_for_run(Experiment(name="y", anomaly={"enabled": True, "zones": [{"id": "gone"}]}), doc)
    assert anomaly_for_run(Experiment(name="z", anomaly={}), doc) == (None, [])


# ---------------------------------------------------------------------------- publication modes
def test_deterministic_anomalies_are_raised_at_once_without_names(client):
    _, cid, eid = _setup(client)
    run_id = _run(eid, cid)
    sup, handle = FakeSupervisor(), _handle(run_id, eid, cid)
    service.get_anomaly_service().handle_updates(handle, [_update(run_id, "det1")], sup)
    row = _row("det1")
    assert row.status == "raised" and row.published and row.llm_status == "off"
    ev = sup.published[0]
    assert ev["event_type"] == "anomaly" and ev["label"] == "Anomaly · Vault: presence in the zone" and ev["object_id"] == "zone_vault"
    assert ev["context"]["summary"] == "A recognized person entered Vault." and ev["context"]["entity"]["identity_id"] == "p_1"
    assert ev["webhooks"] == ["http://127.0.0.1:9/hook"] and ev["track_id"] == 3
    service.get_anomaly_service().handle_updates(handle, [_ended("det1")], sup)
    row = _row("det1")
    assert row.duration_s == 18.0 and row.end_reason == "cleared" and row.metrics["peak_area_pct"] == 14.0
    assert row.subjects[0]["identity_id"] == "p_1"  # an empty list at the end keeps the confirmed subjects
    assert sup.notified[-1][1]["type"] == "anomaly.ended" and sup.notified[-1][1]["duration_s"] == 18.0


def test_assisted_anomalies_are_raised_then_described(client, model):
    _, cid, eid = _setup(client)
    run_id = _run(eid, cid)
    sup, handle = FakeSupervisor(), _handle(run_id, eid, cid)
    service.get_anomaly_service().handle_updates(handle, [_update(run_id, "as1", validation="assisted")], sup)
    assert len(sup.published) == 1  # before the model answered
    row = _wait("as1")
    assert row.llm_verdict == "confirmed" and row.llm_description.startswith("[Person A]") and row.llm_provider == "local"
    deadline = time.time() + 5
    while not sup.notified and time.time() < deadline:
        time.sleep(0.02)
    payload = sup.notified[0][1]
    assert payload["type"] == "anomaly.described" and payload["description"] == "A recognized person entered the normally empty Vault."


def test_assisted_at_end_waits_for_the_end(client, model):
    _, cid, eid = _setup(client)
    run_id = _run(eid, cid)
    sup, handle = FakeSupervisor(), _handle(run_id, eid, cid)
    svc = service.get_anomaly_service()
    svc.handle_updates(handle, [_update(run_id, "as2", validation="assisted", interpret_at="end")], sup)
    assert _row("as2").llm_status == "pending_end" and len(sup.published) == 1
    svc.handle_updates(handle, [_ended("as2")], sup)
    assert _wait("as2").llm_status == "done"


@pytest.mark.parametrize(("answer", "policy", "status", "published"), [
    ("confirmed", "raise", "raised", True),
    ("uncertain", "raise", "raised", True),
    ("rejected", "raise", "dismissed", False),
    (LLMError("server down"), "raise", "raised", True),
    (LLMError("server down"), "hold", "held", False),
])
def test_model_confirmed_zones_follow_the_verdict_and_the_policy(client, model, answer, policy, status, published):
    _, cid, eid = _setup(client)
    run_id = _run(eid, cid)
    sup, handle = FakeSupervisor(), _handle(run_id, eid, cid, policy)
    model.append(answer)
    uid = f"mc-{uuid.uuid4().hex[:10]}"
    service.get_anomaly_service().handle_updates(handle, [_update(run_id, uid, validation="confirmed")], sup)
    row = _wait(uid)
    deadline = time.time() + 5
    while row.status == "awaiting_model" and time.time() < deadline:
        time.sleep(0.02)
        row = _row(uid)
    assert row.status == status and row.published is published and len(sup.published) == (1 if published else 0)
    if isinstance(answer, Exception):
        assert row.llm_status == "failed" and "server down" in row.llm_error


def test_without_a_model_confirmed_zones_use_the_policy(client):
    client.put("/api/anomaly/assistant", json={"provider": "none"})
    _, cid, eid = _setup(client)
    run_id = _run(eid, cid)
    sup = FakeSupervisor()
    service.get_anomaly_service().handle_updates(_handle(run_id, eid, cid, "hold"), [_update(run_id, "nomodel", validation="confirmed")], sup)
    row = _row("nomodel")
    assert row.status == "held" and row.llm_status == "skipped" and "No vision language model" in row.llm_error and not sup.published


# ---------------------------------------------------------------------------- API
def test_anomaly_api_lists_serves_evidence_and_takes_feedback(client, model):
    _, cid, eid = _setup(client)
    run_id = _run(eid, cid)
    sup = FakeSupervisor()
    service.get_anomaly_service().handle_updates(_handle(run_id, eid, cid, "hold"), [_update(run_id, "api1", validation="confirmed")], sup)
    model.append(LLMError("offline"))
    # (the first answer queued above was consumed already or is the default "confirmed")
    _wait("api1")
    listing = client.get(f"/api/anomalies?run_id={run_id}").json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert item["camera_name"] == "Vault cam" and item["kind_label"] == "presence in the zone" and item["expected_state"] == "Nobody inside."
    assert item["evidence"]["before"] == f"/api/anomalies/{item['id']}/evidence/before"
    img = client.get(item["evidence"]["overlay"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    sneaky = client.get(f"/api/anomalies/{item['id']}/evidence/..%2F..%2F..%2Fpathscope.db")
    assert sneaky.headers["content-type"] != "image/jpeg" and b"SQLite" not in sneaky.content
    assert client.get(f"/api/anomalies/{item['id']}/evidence/after").status_code == 404  # not written (yet)
    fb = client.post(f"/api/anomalies/{item['id']}/feedback", json={"feedback": "false_alarm", "note": "cleaner", "rebaseline": True}).json()
    assert fb["feedback"] == "false_alarm" and fb["note"] == "cleaner" and fb["rebaselined"] is False  # the run is not live
    assert client.get("/api/anomalies?feedback=false_alarm").json()["total"] >= 1
    described = client.post(f"/api/anomalies/{item['id']}/describe").json()
    assert described["llm"]["status"] == "done" and described["llm"]["verdict"] == "confirmed"
    model.append(LLMError("model not loaded"))
    failed = client.post(f"/api/anomalies/{item['id']}/describe")
    assert failed.status_code == 422 and "model not loaded" in failed.json()["detail"]


def test_held_anomalies_can_be_raised_later_and_deleted(client):
    client.put("/api/anomaly/assistant", json={"provider": "none"})
    _, cid, eid = _setup(client)
    run_id = _run(eid, cid)
    service.get_anomaly_service().handle_updates(_handle(run_id, eid, cid, "hold"), [_update(run_id, "held1", validation="confirmed")], FakeSupervisor())
    aid = _row("held1").id
    raised = client.post(f"/api/anomalies/{aid}/raise").json()
    assert raised["status"] == "raised" and raised["published"]
    with get_session_factory()() as s:
        ev = s.query(Event).filter_by(run_id=run_id, event_type="anomaly").one()
        assert ev.context["anomaly_id"] == aid and "Person A" not in str(ev.context)
    assert client.post(f"/api/anomalies/{aid}/raise").status_code == 409
    folder = service.run_dir(run_id) / "held1"
    assert folder.is_dir()
    assert client.delete(f"/api/anomalies/{aid}").status_code == 204
    assert not folder.exists() and client.get(f"/api/anomalies/{aid}").status_code == 404
    assert client.post(f"/api/runs/{run_id}/anomaly/rebaseline", json={}).status_code == 409
    # leave the shared test database without ordinary events (other modules count them)
    with get_session_factory()() as s:
        s.get(Run, run_id).status = "completed"
        s.commit()
    assert client.delete(f"/api/runs/{run_id}").status_code == 204


def test_assistant_settings_never_return_the_key(client, monkeypatch):
    for name in ("PATHSCOPE_LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    view = client.put("/api/anomaly/assistant", json={"provider": "openai", "model": "gpt-5-mini", "api_key": "sk-secret-value-9876", "max_calls_per_hour": 30}).json()
    assert view["settings"]["provider"] == "openai" and view["settings"]["max_calls_per_hour"] == 30 and "api_key" not in view["settings"]
    assert view["keys"]["openai"] == {"set": True, "source": "file", "hint": "…9876"}
    assert "sk-secret-value" not in client.get("/api/anomaly/assistant").text
    assert {p["id"] for p in view["providers"]} >= {"none", "local", "openai", "anthropic", "gemini", "openrouter", "deepseek", "custom"}
    assert view["local_models"][0]["tier"] == "light" and "VRAM" in view["local_warning"]
    # keep the key when it is not sent, delete it with an empty string
    assert client.put("/api/anomaly/assistant", json={"provider": "openai"}).json()["keys"]["openai"]["set"] is True
    assert client.put("/api/anomaly/assistant", json={"provider": "openai", "api_key": ""}).json()["keys"]["openai"]["set"] is False
    test = client.post("/api/anomaly/assistant/test")
    assert test.status_code == 422 and "needs an API key" in test.json()["detail"]
    privacy = client.get("/api/system/privacy").json()["stored"]
    llm_item = next(i for i in privacy if i["item"] == "Vision language model")
    assert llm_item["stored"] and "OpenAI" in llm_item["detail"] and "never names" in llm_item["detail"]
    assert any(i["item"] == "Anomaly evidence pictures" for i in privacy)
    client.put("/api/anomaly/assistant", json={"provider": "none"})


def test_run_deletion_and_the_sweep_remove_evidence(client):
    _, cid, eid = _setup(client)
    run_id = _run(eid, cid)
    service.get_anomaly_service().handle_updates(_handle(run_id, eid, cid), [_update(run_id, "del1")], FakeSupervisor())
    assert service.run_dir(run_id).is_dir()
    with get_session_factory()() as s:
        s.get(Run, run_id).status = "completed"
        s.commit()
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert not service.run_dir(run_id).exists()
    orphan = service.run_dir(987654)
    orphan.mkdir(parents=True)
    assert service.sweep()["removed_dirs"] >= 1 and not orphan.exists()
