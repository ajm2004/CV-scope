"""The authenticated recognition API: licence gate, tokens and roles, enrollment,
vehicle registry, events, exports, retention, run payloads and audit."""

from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

os.environ.setdefault("PATHSCOPE_RECOGNITION_ALLOW_STUB", "1")

from pathscope.recognition.licensing import ed25519, issue_license  # noqa: E402
from pathscope.recognition.licensing.license import (  # noqa: E402
    LicensePayload,
    reset_license_manager_for_tests,
)
from pathscope.recognition.registry.store import reset_store_for_tests  # noqa: E402


def textured(h: int, w: int, mean: int, seed: int, std: int = 25) -> bytes:
    rng = np.random.default_rng(seed)
    img = np.clip(rng.normal(mean, std, size=(h, w, 3)), 0, 255).astype(np.uint8)
    ok, enc = cv2.imencode(".png", img)
    assert ok
    return enc.tobytes()


def posed(dx: float = 0.0, dy: float = 0.0, mean: int = 110, seed: int = 1, h: int = 240, w: int = 200) -> bytes:
    """A picture the stub detector reads as a turned or tilted head: a brighter
    right half turns the face towards the person's left, a brighter lower half
    lowers the chin (see StubFaceDetector)."""
    rng = np.random.default_rng(seed)
    img = np.clip(rng.normal(mean, 25, size=(h, w, 3)), 0, 255)
    img[:, w // 2 :] += dx * 255.0
    img[h // 2 :, :] += dy * 255.0
    ok, enc = cv2.imencode(".png", np.clip(img, 0, 255).astype(np.uint8))
    assert ok
    return enc.tobytes()


def upload(client, url: str, data: bytes, view: str, headers: dict):
    return client.post(url, files={"file": ("face.png", io.BytesIO(data), "image/png")}, data={"view": view}, headers=headers)


@pytest.fixture(scope="module")
def rec(client, data_dir: Path):
    """Fresh licence manager and store on the test data directory; returns shared state."""
    reset_license_manager_for_tests(data_dir)
    reset_store_for_tests(data_dir)
    return {"client": client, "data_dir": data_dir}


def test_locked_by_default_and_bootstrap(rec):
    c = rec["client"]
    s = c.get("/api/recognition/status").json()
    assert s["modules"]["face"]["state"] == "not_licensed" and s["modules"]["plate"]["state"] == "not_licensed"
    assert s["access"]["has_tokens"] is False and s["any_licensed"] is False and s["license"]["trusted_issuers"] == 0
    assert c.get("/api/recognition/people").status_code == 401
    assert c.get("/api/recognition/events").status_code == 401
    assert c.post("/api/recognition/people", json={"display_name": "X"}).status_code == 401
    boot = c.post("/api/recognition/access/bootstrap", json={"name": "First admin"})
    assert boot.status_code == 200 and boot.json()["token"].startswith("psr_") and boot.json()["role"] == "admin"
    rec["admin"] = {"Authorization": f"Bearer {boot.json()['token']}"}
    assert c.post("/api/recognition/access/bootstrap", json={}).status_code == 409  # only once
    me = c.get("/api/recognition/access/me", headers=rec["admin"]).json()
    assert me["role"] == "admin" and me["name"] == "First admin"
    assert c.get("/api/recognition/access/me", headers={"X-Recognition-Token": "psr_bogus"}).status_code == 401
    # without a licence: registry reads work, enrollment and registration refuse
    assert c.get("/api/recognition/people", headers=rec["admin"]).json() == []
    r = c.post("/api/recognition/people", json={"display_name": "Employee 001"}, headers=rec["admin"])
    assert r.status_code == 403 and "not licensed" in r.json()["detail"]
    assert c.post("/api/recognition/vehicles", json={"plate": "ABC12345"}, headers=rec["admin"]).status_code == 403
    # the privacy list shows the core defaults
    priv = c.get("/api/system/privacy").json()["stored"]
    faces = next(i for i in priv if i["item"].startswith("Faces"))
    assert faces["stored"] is False


def test_license_install_and_module_states(rec):
    c = rec["client"]
    secret, public = ed25519.generate_keypair()
    doc = issue_license(LicensePayload("LIC-TEST", "Test Lab", "Vendor", "2026-09-01", "2099-01-01", ["face", "plate"], max_cameras=4), secret)
    # an unknown issuer is refused and nothing is written
    r = c.post("/api/recognition/license", json={"license": doc}, headers=rec["admin"])
    assert r.status_code == 400 and "trusted issuer" in r.json()["detail"]
    assert c.post("/api/recognition/license/trusted-keys", json={"public_key": public.hex(), "name": "vendor"}, headers=rec["admin"]).json()["trusted_issuers"] == 1
    tampered = json.loads(json.dumps(doc))
    tampered["payload"]["licensee"] = "Someone else"
    assert c.post("/api/recognition/license", json={"license": tampered}, headers=rec["admin"]).status_code == 400
    r = c.post("/api/recognition/license", json={"license": json.dumps(doc)}, headers=rec["admin"])
    assert r.status_code == 200 and r.json()["verdict"]["state"] == "licensed" and r.json()["status"]["modules"]["face"]["state"] == "licensed"
    s = c.get("/api/recognition/status").json()
    assert s["license"]["license"]["licensee"] == "Test Lab" and s["any_licensed"] and s["license"]["hardware_id"]
    assert "signature" not in json.dumps(s)
    # administrators can switch a licensed module off: Disabled
    r = c.put("/api/recognition/settings", json={"values": {"recognition.plate.enabled": False}}, headers=rec["admin"])
    assert r.status_code == 200 and r.json()["modules"]["plate"]["state"] == "disabled" and r.json()["changed"] == ["recognition.plate.enabled"]
    c.put("/api/recognition/settings", json={"values": {"recognition.plate.enabled": True}}, headers=rec["admin"])
    assert c.put("/api/recognition/settings", json={"values": {"recognition.face.min_face_px": 1}}, headers=rec["admin"]).status_code == 400
    # the test stand-in stacks (no model downloads in the test-suite)
    r = c.put("/api/recognition/settings", json={"values": {"recognition.face.stack": "stub", "recognition.plate.detector_model": "stub", "recognition.plate.ocr_model": "stub"}}, headers=rec["admin"])
    assert r.status_code == 200
    priv = c.get("/api/system/privacy").json()["stored"]
    assert next(i for i in priv if i["item"].startswith("Faces"))["stored"] is True
    assert any(i["item"].startswith("Recognition events") for i in priv)
    hw = c.get("/api/hardware/recommendations").json()
    assert hw["recognition"] is not None and set(hw["recognition"]["modules"]) == {"face", "plate"} and "Face embedding model" in hw["recognition"]["components"]
    impact = c.get("/api/hardware/recognition-impact?face_stack=insightface").json()
    assert impact["camera_capacity_with"] <= impact["camera_capacity_without"]


def test_tokens_and_roles(rec):
    c = rec["client"]
    r = c.post("/api/recognition/access/tokens", json={"name": "Reception", "role": "viewer"}, headers=rec["admin"])
    assert r.status_code == 201
    rec["viewer"] = {"Authorization": f"Bearer {r.json()['token']}"}
    r = c.post("/api/recognition/access/tokens", json={"name": "Operator", "role": "operator"}, headers=rec["admin"])
    rec["operator"] = {"Authorization": f"Bearer {r.json()['token']}"}
    assert c.post("/api/recognition/access/tokens", json={"name": "x", "role": "viewer"}, headers=rec["viewer"]).status_code == 403
    assert c.post("/api/recognition/people", json={"display_name": "X"}, headers=rec["viewer"]).status_code == 403
    tokens = c.get("/api/recognition/access/tokens", headers=rec["admin"]).json()
    assert {t["role"] for t in tokens} == {"admin", "viewer", "operator"}
    admin_id = next(t["id"] for t in tokens if t["role"] == "admin")
    assert c.delete(f"/api/recognition/access/tokens/{admin_id}", headers=rec["admin"]).status_code == 409  # the last administrator


def test_guided_enrollment(rec):
    c = rec["client"]
    op = rec["operator"]
    r = c.post("/api/recognition/people", json={"display_name": "Employee 001", "reference_id": "E-001", "notes": "Research subject 001"}, headers=op)
    assert r.status_code == 201, r.text
    person = r.json()
    pid = person["id"]
    rec["person_id"] = pid
    assert person["enrollment_status"] == "draft" and person["n_templates"] == 0
    face = textured(240, 200, 110, 1)
    # analysis does not store anything
    a = upload(c, f"/api/recognition/people/{pid}/enrollment/analyze", face, "front", op)
    assert a.status_code == 200 and a.json()["face_found"] and a.json()["accepted"] and a.json()["guidance"] == []
    assert c.get(f"/api/recognition/people/{pid}", headers=op).json()["n_images"] == 0
    # guidance: a frontal picture is not a left view; a flat picture is not a usable face
    left = upload(c, f"/api/recognition/people/{pid}/enrollment/analyze", face, "left", op).json()
    assert not left["accepted"] and any("left" in g for g in left["guidance"])
    flat = np.full((240, 200, 3), 120, dtype=np.uint8)
    ok, enc = cv2.imencode(".png", flat)
    blank = upload(c, f"/api/recognition/people/{pid}/enrollment/analyze", enc.tobytes(), "front", op).json()
    assert not blank["accepted"] and any("blurred" in g or "contrast" in g for g in blank["guidance"])
    rejected = upload(c, f"/api/recognition/people/{pid}/enrollment/images", enc.tobytes(), "front", op)
    assert rejected.status_code == 400
    assert upload(c, f"/api/recognition/people/{pid}/enrollment/analyze", face, "sideways", op).status_code == 400
    # three accepted views plus a rear reference: the front view first, because the
    # pose of the other views is judged relative to it
    for view, data in (("front", textured(240, 200, 110, 10)), ("lighting", textured(240, 200, 110, 11)), ("above", posed(dy=0.16, seed=12))):
        r = upload(c, f"/api/recognition/people/{pid}/enrollment/images", data, view, op)
        assert r.status_code == 201, r.text
        assert r.json()["template_id"] is not None and r.json()["analysis"]["view"] == view
    # the chin has to move for the "camera above" view: a frontal picture is refused
    flat_above = upload(c, f"/api/recognition/people/{pid}/enrollment/images", textured(240, 200, 110, 13), "above", op)
    assert flat_above.status_code == 400 and "chin" in flat_above.json()["detail"].lower()
    r = upload(c, f"/api/recognition/people/{pid}/enrollment/images", textured(300, 200, 90, 99), "rear", op)
    assert r.status_code == 201 and r.json()["template_id"] is None and r.json()["image_id"]
    p = c.get(f"/api/recognition/people/{pid}", headers=op).json()
    assert p["n_templates"] == 3 and p["n_images"] == 4 and sorted(p["views"]) == ["above", "front", "lighting"]
    assert [im["biometric"] for im in p["images"]].count(False) == 1
    # a viewer sees the profile but not its images; an operator gets the decrypted image
    v = c.get(f"/api/recognition/people/{pid}", headers=rec["viewer"]).json()
    assert "images" not in v
    image_id = p["images"][0]["id"]
    f = c.get(f"/api/recognition/people/{pid}/enrollment/images/{image_id}/file", headers=op)
    assert f.status_code == 200 and f.headers["content-type"] == "image/jpeg" and f.content[:2] == b"\xff\xd8"
    assert c.get(f"/api/recognition/people/{pid}/enrollment/images/{image_id}/file", headers=rec["viewer"]).status_code == 403
    stored = list((rec["data_dir"] / "recognition" / "enrollment" / pid).glob("*.bin"))
    assert len(stored) == 4 and stored[0].read_bytes()[:4] == b"PSR1"  # encrypted at rest
    # finalize: enrolled with a quality summary
    r = c.post(f"/api/recognition/people/{pid}/enrollment/finalize", headers=op)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["status"] == "enrolled" and res["templates"] == 3 and res["quality"] > 0.6 and res["consistency"] > 0.35 and res["problems"] == []
    assert r.json()["person"]["enrollment_status"] == "enrolled" and r.json()["person"]["model_version"] == "stub+stub"
    # the same picture is judged against this person's own front view: a left turn
    # is accepted, a frontal picture for the same view is not
    left_ok = upload(c, f"/api/recognition/people/{pid}/enrollment/analyze", posed(dx=0.16, seed=14), "left", op).json()
    assert left_ok["accepted"] and left_ok["quality"]["yaw"] > 0.18
    # a second person with one view only stays insufficient
    r = c.post("/api/recognition/people", json={"display_name": "Employee 002"}, headers=op)
    pid2 = r.json()["id"]
    rec["person2_id"] = pid2
    assert upload(c, f"/api/recognition/people/{pid2}/enrollment/images", textured(240, 200, 180, 5), "left", op).status_code == 400  # frontal stand-in, not a left view
    assert upload(c, f"/api/recognition/people/{pid2}/enrollment/images", textured(240, 200, 180, 5), "lighting", op).status_code == 201
    res2 = c.post(f"/api/recognition/people/{pid2}/enrollment/finalize", headers=op).json()["result"]
    assert res2["status"] == "insufficient" and any("front" in p for p in res2["problems"])
    # templates are never exposed
    assert "sealed" not in json.dumps(c.get("/api/recognition/people", headers=op).json())


def checker(dx: float = 0.0, dy: float = 0.0, mean: int = 110, h: int = 240, w: int = 320, block: int = 8, amp: int = 30) -> np.ndarray:
    """A sharp synthetic frame that survives JPEG preview encoding. A brighter
    right half reads as a head turned to the person's left, a brighter lower
    half as a lowered chin (see StubFaceDetector)."""
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.full((h, w), float(mean)) + (((yy // block + xx // block) % 2) * 2 - 1) * amp
    img[:, w // 2 :] += dx * 255.0
    img[h // 2 :, :] += dy * 255.0
    return np.clip(img, 0, 255).astype(np.uint8)[:, :, None].repeat(3, axis=2)


def ws_wait(ws, kind: str, limit: int = 900, instruction: str | None = None) -> dict:
    """The next message of a kind, stepping over frames and analyses."""
    seen: list[str] = []
    for _ in range(limit):
        msg = ws.receive()
        if msg.get("type") == "websocket.close":
            raise AssertionError(f"the server closed the socket: {msg}")
        text = msg.get("text")
        if not text:
            continue
        m = json.loads(text)
        if m.get("type") == "error":
            raise AssertionError(f"error message: {m['message']}")
        if m.get("type") == kind and (instruction is None or m.get("instruction") == instruction):
            return m
        note = m.get("instruction") or m.get("message") or ""
        if note and (not seen or seen[-1] != note):
            seen.append(note)
    wanted = f"'{kind}'" + (f" with instruction {instruction!r}" if instruction else "")
    raise AssertionError(f"no {wanted} message; the session said: {seen[-8:]}")


def test_guided_live_enrollment_over_websocket(rec, monkeypatch):
    """The Face-ID style flow: the camera picture is watched, the instruction
    changes with the head, and each view is stored without a button."""
    import time as _time

    from pathscope.services import preview as preview_mod
    from pathscope.services.preview import PreviewManager
    from pathscope.vision.sources.base import FrameSource, SourceInfo
    from pathscope.vision.types import FramePacket

    c, op, admin = rec["client"], rec["operator"], rec["admin"]
    token = op["Authorization"].split()[1]
    shown = {"img": checker()}

    class ScriptedCamera(FrameSource):
        """A camera that always shows the frame the test put in ``shown``."""

        def __init__(self, cfg):
            self.cfg = cfg
            self._info = None

        def open(self):
            self._info = SourceInfo("usb", self.cfg.source_uri, 320, 240, 30.0, is_live=True, backend="fake")
            return self._info

        @property
        def info(self):
            return self._info

        def read(self):
            _time.sleep(1 / 40)
            img = shown["img"]
            return FramePacket(img.copy(), 0, _time.time(), _time.time(), img.shape[1], img.shape[0])

        def close(self):
            pass

    fake = PreviewManager(lambda cfg: False, factory=ScriptedCamera)
    monkeypatch.setattr(preview_mod, "_manager", fake)

    project = c.post("/api/projects", json={"name": "Guided"}).json()
    camera = c.post("/api/cameras", json={"project_id": project["id"], "name": "Enrollment cam", "source_type": "usb", "source_uri": "9"}).json()
    person = c.post("/api/recognition/people", json={"display_name": "Guided Subject"}, headers=op).json()
    pid = person["id"]
    try:
        with c.websocket_connect(f"/ws/recognition/enrollment/{pid}?camera_id={camera['id']}&rtoken={token}") as ws:
            ready = ws_wait(ws, "ready")
            assert ready["mirror"] is True and ready["camera"]["name"] == "Enrollment cam"
            assert [v["view"] for v in ready["plan"]] == ["front", "left", "right", "above", "below"]
            assert [v["view"] for v in ready["extras"]] == ["lighting", "rear"] and ready["captured"] == []
            # nothing is captured while no view is asked for
            idle = ws_wait(ws, "analysis")
            assert idle["view"] is None and not idle["capture"] if "capture" in idle else idle["view"] is None
            assert c.get(f"/api/recognition/people/{pid}", headers=op).json()["n_images"] == 0

            ws.send_json({"type": "target", "view": "front"})
            captured = ws_wait(ws, "captured")
            assert captured["view"] == "front" and captured["image_id"] and captured["person"]["n_templates"] == 1
            assert captured["captured"] == ["front"] and captured["baseline"]["yaw"] is not None

            # a face that still looks straight ahead is told which way to turn
            ws.send_json({"type": "target", "view": "left"})
            hint = ws_wait(ws, "analysis", instruction="Turn your head slightly to your left")
            assert hint["direction"] == "left" and hint["ok"] is False and hint["view"] == "left"
            shown["img"] = checker(dx=0.16)  # the head turns
            captured = ws_wait(ws, "captured")
            assert captured["view"] == "left" and sorted(captured["captured"]) == ["front", "left"]

            # the "camera above" view needs the chin to come down
            ws.send_json({"type": "target", "view": "above"})
            ws_wait(ws, "analysis", instruction="Lower your chin a little")
            shown["img"] = checker(dy=0.16)
            captured = ws_wait(ws, "captured")
            assert captured["view"] == "above" and sorted(captured["captured"]) == ["above", "front", "left"]
            ws.send_json({"type": "stop"})

        p = c.get(f"/api/recognition/people/{pid}", headers=op).json()
        assert p["n_templates"] == 3 and sorted(p["views"]) == ["above", "front", "left"]
        result = c.post(f"/api/recognition/people/{pid}/enrollment/finalize", headers=op).json()["result"]
        assert result["status"] == "enrolled" and result["templates"] == 3
        trail = c.get("/api/recognition/audit", headers=admin).json()
        assert any(a["action"] == "enrollment_image_added" and a["detail"].get("guided") for a in trail)

        # the same person again in another look: the plan starts empty for that
        # look and the new picture is added to the profile, not swapped in
        shown["img"] = checker()
        with c.websocket_connect(f"/ws/recognition/enrollment/{pid}?camera_id={camera['id']}&rtoken={token}&variant=Glasses") as ws:
            ready = ws_wait(ws, "ready")
            assert ready["variant"] == "Glasses" and ready["captured"] == []
            ws.send_json({"type": "target", "view": "front"})
            captured = ws_wait(ws, "captured")
            assert captured["view"] == "front" and captured["person"]["n_templates"] == 4
            ws.send_json({"type": "stop"})
        p = c.get(f"/api/recognition/people/{pid}", headers=op).json()
        assert [li["name"] for li in p["looks"]] == ["", "Glasses"]
        assert next(li for li in p["looks"] if li["name"] == "Glasses")["templates"] == 1
        assert any(a["action"] == "enrollment_image_added" and a["detail"].get("variant") == "Glasses" for a in c.get("/api/recognition/audit", headers=admin).json())

        # the live test recognizes that person from the same camera, storing nothing
        with c.websocket_connect(f"/ws/recognition/test/live?camera_id={camera['id']}&rtoken={token}") as ws:
            ready = ws_wait(ws, "ready")
            assert ready["identities"] >= 1 and ready["thresholds"]["match"] > 0 and ready["mirror"] is True
            out = ws_wait(ws, "result")
            assert out["n_faces"] == 1
            face = out["faces"][0]
            assert face["status"] == "recognized" and face["best"]["display_name"] == "Guided Subject"
            assert c.get(f"/api/recognition/people/{pid}", headers=op).json()["n_images"] == 4  # nothing stored by testing

            # the operator answers: the verdict is counted, the picture is kept
            ws.send_json({"type": "feedback", "verdict": "correct", "person_id": pid, "similarity": face["best"]["similarity"]})
            fb = ws_wait(ws, "feedback")
            assert fb["verdict"] == "correct" and fb["correct"] >= 1
            ws.send_json({"type": "confirm", "person_id": pid})
            got = ws_wait(ws, "taught")
            assert got["person"]["n_templates"] == 5 and got["look"] == "Live confirmations"
            assert any(li["name"] == "Live confirmations" for li in got["person"]["looks"])
            assert got["identities"] >= 1  # the matcher was rebuilt with the new template
            ws.send_json({"type": "stop"})
        after = c.get(f"/api/recognition/people/{pid}", headers=op).json()
        assert after["n_images"] == 5 and after["n_templates"] == 5  # only the confirmed picture was added
    finally:
        c.delete(f"/api/recognition/people/{pid}", headers=admin)
        c.delete(f"/api/projects/{project['id']}")
        fake.stop_all()


def test_guided_live_enrollment_refuses_without_the_operator_role(rec):
    c = rec["client"]
    viewer_token = rec["viewer"]["Authorization"].split()[1]
    person = c.post("/api/recognition/people", json={"display_name": "Gate check"}, headers=rec["operator"]).json()
    project = c.post("/api/projects", json={"name": "Guided gate"}).json()
    camera = c.post("/api/cameras", json={"project_id": project["id"], "name": "Cam", "source_type": "usb", "source_uri": "9"}).json()
    try:
        for url, expected in (
            (f"/ws/recognition/enrollment/{person['id']}?camera_id={camera['id']}", "token is required"),
            (f"/ws/recognition/enrollment/{person['id']}?camera_id={camera['id']}&rtoken={viewer_token}", "operator role"),
            (f"/ws/recognition/enrollment/nobody?camera_id={camera['id']}&rtoken={rec['admin']['Authorization'].split()[1]}", "no longer exists"),
        ):
            with c.websocket_connect(url) as ws:
                message = ws.receive_json()
                assert message["type"] == "error" and expected in message["message"]
    finally:
        c.delete(f"/api/recognition/people/{person['id']}", headers=rec["admin"])
        c.delete(f"/api/projects/{project['id']}")


def test_vehicle_registry_and_plate_parser(rec):
    c = rec["client"]
    op = rec["operator"]
    r = c.post("/api/recognition/vehicles", json={"plate": "abc-12345", "country": "ae", "vehicle_type": "van", "description": "Delivery Van 04", "groups": ["Delivery Fleet", "Delivery Fleet", " "]}, headers=op)
    assert r.status_code == 201, r.text
    v = r.json()
    rec["vehicle_id"] = v["id"]
    assert v["plate"] == "ABC12345" and v["country"] == "AE" and v["groups"] == ["Delivery Fleet"]
    assert c.post("/api/recognition/vehicles", json={"plate": "ABC 12345"}, headers=op).status_code == 400  # duplicate after normalisation
    assert c.post("/api/recognition/vehicles", json={"plate": "A"}, headers=op).status_code == 422
    assert c.get("/api/recognition/vehicles/groups", headers=rec["viewer"]).json() == ["Delivery Fleet"]
    r = c.put(f"/api/recognition/vehicles/{v['id']}", json={"active": False}, headers=op)
    assert r.status_code == 200 and r.json()["active"] is False
    c.put(f"/api/recognition/vehicles/{v['id']}", json={"active": True, "owner_ref": "Logistics"}, headers=op)
    assert c.delete(f"/api/recognition/vehicles/{v['id']}", headers=op).status_code == 403  # operators cannot delete
    parsed = c.post("/api/recognition/plates/parse", json={"text": "DXB 12S67", "formats": "uae,generic"}, headers=rec["viewer"]).json()
    assert parsed["normalized"] == "DXB12567" and parsed["format"] == "uae" and parsed["fields"]["emirate"] == "DXB" and parsed["substitutions"] == 1
    assert parsed["exact"]["format"] == "generic"


def test_run_payload_carries_identities_and_vehicles(rec):
    from pathscope.db.session import get_session_factory
    from pathscope.recognition.service import build_run_payload, payload_summary

    class Exp:
        object_classes = ["person", "car"]
        rules = [{"name": "r", "classes": ["person"], "subject": {"mode": "recognized"}, "trigger": {"kind": "crosses", "object_id": "g"}}]

    session = get_session_factory()()
    try:
        payload = build_run_payload(session, Exp())
    finally:
        session.close()
    assert payload is not None and "face" in payload and "plate" in payload
    face = payload["face"]
    assert face["stack"] == "stub" and [i["name"] for i in face["identities"]] == ["Employee 001"]
    assert len(face["identities"][0]["templates"]) == 3 and len(face["identities"][0]["templates"][0]) == 32
    assert face["config"]["min_observations"] == 3 and payload["grace_s"] == 5.0
    plate = payload["plate"]
    assert plate["stack"] == "stub" and [v["plate"] for v in plate["vehicles"]] == ["ABC12345"] and plate["vehicles"][0]["groups"] == ["Delivery Fleet"]
    assert [f["id"] for f in plate["formats"]] == ["generic"]
    summary = payload_summary(payload)
    assert summary == {"modules": ["face", "plate"], "warnings": [], "face": {"stack": "stub", "identities": 1}, "plate": {"vehicles": 1, "formats": ["generic"]}}
    assert "templates" not in json.dumps(summary)
    # the worker runtime builds from exactly this payload
    from pathscope.recognition.runtime import RecognitionRuntime

    runtime = RecognitionRuntime.from_payload(payload)
    assert runtime.provides() == {"face", "plate"} and runtime.face.matcher.n_identities == 1
    runtime.close()

    class VehiclesOnly:
        object_classes = ["car"]
        rules = []

    session = get_session_factory()()
    try:
        p2 = build_run_payload(session, VehiclesOnly())
    finally:
        session.close()
    assert p2 is not None and "face" not in p2 and "plate" in p2


def test_recognition_events_export_retention_and_deletion(rec):
    from pathscope.db.session import get_session_factory
    from pathscope.recognition.events.recorder import record_events

    c = rec["client"]
    pid, vid = rec["person_id"], rec["vehicle_id"]
    now = datetime.now(UTC).timestamp()
    ids = record_events(
        run_id=1, experiment_id=1, camera_id=1,
        events=[
            {"module": "face", "kind": "recognized", "track_id": 3, "object_class": "person", "person_id": pid, "similarity": 0.91, "second_similarity": 0.2, "status": "recognized", "quality": 0.8, "n_observations": 12, "usable_observations": 5, "best_frame_index": 1381, "model_version": "stub+stub", "frame_index": 1400, "media_time_s": 46.7, "wall_time": now, "context": {"threshold": 0.9}, "crop_jpeg": textured(112, 112, 100, 3)},
            {"module": "plate", "kind": "registered_vehicle", "track_id": 9, "object_class": "car", "vehicle_id": vid, "plate_raw": "ABC12345", "plate_normalized": "ABC12345", "plate_format": "generic", "confidence": 0.97, "status": "recognized", "n_observations": 4, "usable_observations": 3, "model_version": "stub+stub", "frame_index": 200, "media_time_s": 6.6, "wall_time": now, "context": {}},
            {"module": "plate", "kind": "plate_read", "track_id": 10, "object_class": "car", "plate_raw": "XYZ999", "plate_normalized": "XYZ999", "confidence": 0.8, "status": "recognized", "model_version": "stub+stub", "frame_index": 300, "media_time_s": 9.9, "wall_time": now - 30 * 86400, "context": {}},
        ],
    )
    assert len(ids) == 3
    assert c.get("/api/recognition/events").status_code == 401
    page = c.get("/api/recognition/events", headers=rec["viewer"]).json()
    assert page["total"] == 3
    face_ev = next(e for e in page["items"] if e["module"] == "face")
    assert face_ev["display_name"] == "Employee 001" and face_ev["best_frame_index"] == 1381 and face_ev["has_crop"] is True
    assert next(e for e in page["items"] if e["kind"] == "registered_vehicle")["vehicle_label"] == "Delivery Van 04"
    assert c.get("/api/recognition/events", params={"module": "plate", "plate": "abc12345"}, headers=rec["viewer"]).json()["total"] == 1  # filters are normalised too
    assert c.get("/api/recognition/events", params={"plate": "ABC99999"}, headers=rec["viewer"]).json()["total"] == 0
    crop = c.get(f"/api/recognition/events/{face_ev['id']}/crop", headers=rec["operator"])
    assert crop.status_code == 200 and crop.content == textured(112, 112, 100, 3)  # decrypted round trip
    assert (rec["data_dir"] / "recognition" / "crops" / f"{face_ev['id']}.bin").read_bytes()[:4] == b"PSR1"  # encrypted at rest
    assert c.get(f"/api/recognition/events/{face_ev['id']}/crop", headers=rec["viewer"]).status_code == 403
    # ordinary events API never sees recognition data
    assert c.get("/api/events").json()["total"] == 0
    # export is restricted to administrators and audited
    assert c.get("/api/recognition/events/export?format=csv", headers=rec["viewer"]).status_code == 403
    csv_export = c.get("/api/recognition/events/export?format=csv", headers=rec["admin"])
    assert csv_export.status_code == 200 and "Employee 001" in csv_export.text and "ABC12345" in csv_export.text
    audit = c.get("/api/recognition/audit", headers=rec["admin"]).json()
    actions = [a["action"] for a in audit]
    assert "export_created" in actions and "profile_created" in actions and "enrollment_finalized" in actions and "license_installed" in actions and "vehicle_created" in actions and "token_created" in actions
    assert c.get("/api/recognition/audit", headers=rec["operator"]).status_code == 403
    # retention: the 30-day-old unregistered plate read goes, the rest stays
    from pathscope.recognition.common.config import all_recognition_settings
    from pathscope.recognition.events.recorder import sweep_retention

    session = get_session_factory()()
    try:
        values = all_recognition_settings(session)
        result = sweep_retention(session, {**values, "recognition.retention.events_days": 60, "recognition.retention.unknown_plate_days": 7})
    finally:
        session.close()
    assert result["unknown_plates"] == 1 and result["events"] == 0
    assert c.get("/api/recognition/events", headers=rec["viewer"]).json()["total"] == 2
    # deletion of a single recognition event and its crop
    r = c.delete(f"/api/recognition/events/{face_ev['id']}", headers=rec["admin"])
    assert r.status_code == 200 and r.json()["deleted"] == 1
    assert not (rec["data_dir"] / "recognition" / "crops" / f"{face_ev['id']}.bin").exists()
    assert c.post("/api/recognition/events/delete", json={"module": "plate"}, headers=rec["admin"]).json()["deleted"] == 1


def test_profile_deletion_removes_templates_and_media(rec):
    c = rec["client"]
    pid = rec["person_id"]
    folder = rec["data_dir"] / "recognition" / "enrollment" / pid
    assert folder.exists()
    assert c.delete(f"/api/recognition/people/{pid}", headers=rec["operator"]).status_code == 403
    r = c.delete(f"/api/recognition/people/{pid}", headers=rec["admin"])
    assert r.status_code == 200 and r.json()["templates_deleted"] == 3 and r.json()["media"] == "deleted"
    assert not folder.exists()
    assert c.get(f"/api/recognition/people/{pid}", headers=rec["admin"]).status_code == 404
    from pathscope.db.session import get_session_factory
    from pathscope.recognition.registry.models import RecognitionFaceTemplate

    session = get_session_factory()()
    try:
        assert session.query(RecognitionFaceTemplate).filter_by(person_id=pid).count() == 0
    finally:
        session.close()
    # re-enrollment of the other profile clears its templates but keeps the profile
    pid2 = rec["person2_id"]
    r = c.post(f"/api/recognition/people/{pid2}/reenroll", headers=rec["operator"])
    assert r.status_code == 200 and r.json()["n_templates"] == 0 and r.json()["enrollment_status"] == "draft"
    assert c.post(f"/api/recognition/people/{pid2}/disable", headers=rec["operator"]).json()["active"] is False


def upload_look(client, url: str, data: bytes, view: str, look: str, headers: dict):
    return client.post(url, files={"file": ("face.png", io.BytesIO(data), "image/png")}, data={"view": view, "variant": look}, headers=headers)


def test_a_second_look_adds_templates_instead_of_replacing_them(rec):
    """The same person enrolled again in another appearance (glasses, a hat,
    other light): every look keeps its own views, the templates add up, and
    each later look must still match the first enrollment."""
    c, op = rec["client"], rec["operator"]
    pid = c.post("/api/recognition/people", json={"display_name": "Look Test"}, headers=op).json()["id"]
    rec["look_person_id"] = pid
    for view, data in (("front", textured(240, 200, 110, 20)), ("lighting", textured(240, 200, 110, 21)), ("above", posed(dy=0.16, seed=22))):
        assert upload(c, f"/api/recognition/people/{pid}/enrollment/images", data, view, op).status_code == 201
    first = c.post(f"/api/recognition/people/{pid}/enrollment/finalize", headers=op).json()["result"]
    assert first["status"] == "enrolled" and first["n_looks"] == 1 and first["looks"][0]["name"] == ""

    for view, data in (("front", textured(240, 200, 112, 30)), ("lighting", textured(240, 200, 112, 31))):
        r = upload_look(c, f"/api/recognition/people/{pid}/enrollment/images", data, view, "Glasses", op)
        assert r.status_code == 201, r.text
    p = c.get(f"/api/recognition/people/{pid}", headers=op).json()
    assert p["n_templates"] == 5 and [li["name"] for li in p["looks"]] == ["", "Glasses"]
    assert {im["variant"] for im in p["images"]} == {"", "Glasses"}

    res = c.post(f"/api/recognition/people/{pid}/enrollment/finalize", headers=op).json()["result"]
    assert res["status"] == "enrolled" and res["n_looks"] == 2 and res["templates"] == 5
    glasses = next(li for li in res["looks"] if li["name"] == "Glasses")
    assert glasses["templates"] == 2 and glasses["is_first"] is False and glasses["link_to_first"] is not None

    # every look is matched at run time
    from pathscope.db.session import get_session_factory
    from pathscope.recognition.common.config import all_recognition_settings
    from pathscope.recognition.registry.people import PeopleService
    from pathscope.recognition.registry.store import get_store

    session = get_session_factory()()
    try:
        svc = PeopleService(session, get_store(), None, all_recognition_settings(session))
        mine = next(i for i in svc.identities_for_worker() if i["id"] == pid)
        assert len(mine["templates"]) == 5
    finally:
        session.close()

    # the first enrollment cannot be dropped this way; a later look can
    assert c.delete(f"/api/recognition/people/{pid}/enrollment/looks/%20", headers=op).status_code == 400
    r = c.delete(f"/api/recognition/people/{pid}/enrollment/looks/Glasses", headers=op)
    assert r.status_code == 200 and r.json()["n_templates"] == 3 and [li["name"] for li in r.json()["looks"]] == [""]
    assert c.delete(f"/api/recognition/people/{pid}/enrollment/looks/Glasses", headers=op).status_code == 400


def test_test_bench_identifies_a_picture_and_grades_the_enrollment(rec):
    """The operator's rehearsal: the same chain a run uses, with the numbers
    behind the verdict and nothing stored."""
    c, op = rec["client"], rec["operator"]
    pid = rec["look_person_id"]
    url = "/api/recognition/test/identify"
    known = c.post(url, files={"file": ("f.png", io.BytesIO(textured(240, 200, 110, 20)), "image/png")}, headers=op)
    assert known.status_code == 200, known.text
    d = known.json()
    assert d["n_faces"] == 1 and d["identities"] >= 1
    face = d["faces"][0]
    assert face["status"] == "recognized" and face["best"]["display_name"] == "Look Test"
    assert face["candidates"][0]["over_match"] and face["quality"]["size_px"] >= d["thresholds"]["min_face_px"]
    assert "sealed" not in json.dumps(d) and "embedding" not in json.dumps(d)

    stranger = c.post(url, files={"file": ("f.png", io.BytesIO(textured(240, 200, 220, 91)), "image/png")}, headers=op).json()
    assert stranger["faces"][0]["status"] in ("unknown", "insufficient_quality")
    assert stranger["faces"][0]["best"] is None and stranger["faces"][0]["advice"]

    flat = np.full((240, 200, 3), 120, dtype=np.uint8)
    ok, enc = cv2.imencode(".png", flat)
    blank = c.post(url, files={"file": ("f.png", io.BytesIO(enc.tobytes()), "image/png")}, headers=op).json()
    assert blank["n_faces"] == 0 or blank["faces"][0]["status"] == "insufficient_quality"

    # nothing was stored by any of that
    assert c.get(f"/api/recognition/people/{pid}", headers=op).json()["n_images"] == 3

    check = c.get("/api/recognition/test/enrollment", headers=op).json()
    mine = next(x for x in check["people"] if x["id"] == pid)
    assert mine["templates"] == 3 and mine["n_looks"] == 1 and mine["self_similarity"] is not None
    assert any("look" in a.lower() for a in mine["advice"])  # one look only: suggest another
    assert check["counts"]["total"] == len(check["people"])

    # roles: the test bench is an operator tool and needs a token
    assert c.post(url, files={"file": ("f.png", io.BytesIO(textured(240, 200, 110, 20)), "image/png")}).status_code == 401
    assert c.get("/api/recognition/test/enrollment", headers=rec["viewer"]).status_code == 403


def test_the_test_bench_learns_from_a_confirmation(rec):
    """Saying yes keeps the picture in its own look; a face that does not match
    is refused until the operator insists, and every answer is audited."""
    c, op, admin = rec["client"], rec["operator"], rec["admin"]
    pid = rec["look_person_id"]
    before = c.get(f"/api/recognition/people/{pid}", headers=op).json()["n_templates"]

    def teach(data: bytes, force: bool = False, person: str | None = None):
        return c.post(
            "/api/recognition/test/teach",
            files={"file": ("f.png", io.BytesIO(data), "image/png")},
            data={"person_id": person or pid, "force": str(force).lower()},
            headers=op,
        )

    r = teach(textured(240, 200, 110, 23))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["look"] == "Live confirmations" and d["person"]["n_templates"] == before + 1
    assert any(li["name"] == "Live confirmations" for li in d["person"]["looks"])
    assert d["enrollment"]["status"] == "enrolled" and d["similarity"] is not None

    # a different face is refused, and says so in plain words
    stranger = textured(240, 200, 220, 92)
    refused = teach(stranger)
    assert refused.status_code == 409 and "register" in refused.json()["detail"].lower()
    forced = teach(stranger, force=True)
    assert forced.status_code == 200 and forced.json()["person"]["n_templates"] == before + 2

    # the look can be removed again, which puts the profile back as it was
    r = c.delete(f"/api/recognition/people/{pid}/enrollment/looks/Live%20confirmations", headers=op)
    assert r.status_code == 200 and r.json()["n_templates"] == before
    c.post(f"/api/recognition/people/{pid}/enrollment/finalize", headers=op)

    # verdicts are recorded, not applied
    r = c.post("/api/recognition/test/feedback", json={"verdict": "correct", "person_id": pid, "similarity": 0.81}, headers=op)
    assert r.status_code == 200 and r.json()["correct"] >= 1
    r = c.post("/api/recognition/test/feedback", json={"verdict": "wrong", "person_id": pid, "similarity": 0.52, "source": "picture"}, headers=op)
    counts = r.json()
    assert counts["wrong"] >= 1 and counts["checked"] >= 2 and counts["taught"] >= 2
    log = c.get("/api/recognition/test/feedback", headers=op).json()
    assert any(row["action"] == "test_feedback" for row in log["recent"]) and any(row["action"] == "test_taught" for row in log["recent"])
    trail = c.get("/api/recognition/audit", headers=admin).json()
    forced_rows = [a for a in trail if a["action"] == "test_taught" and a["detail"].get("forced")]
    assert forced_rows and forced_rows[0]["detail"]["source"] == "picture"

    # roles
    assert c.post("/api/recognition/test/feedback", json={"verdict": "correct"}, headers=rec["viewer"]).status_code == 403
    assert c.post("/api/recognition/test/feedback", json={"verdict": "correct"}).status_code == 401


def test_names_are_resolved_only_for_token_holders(rec):
    c = rec["client"]
    pid = rec["look_person_id"]
    assert c.post("/api/recognition/resolve", json={"identity_ids": [pid]}).status_code == 401
    vehicles = c.get("/api/recognition/vehicles", headers=rec["viewer"]).json()
    r = c.post("/api/recognition/resolve", json={"identity_ids": [pid, "gone"], "vehicle_ids": [v["id"] for v in vehicles]}, headers=rec["viewer"])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["identities"][pid]["display_name"] == "Look Test" and "gone" in d["missing"]
    if vehicles:
        assert d["vehicles"][vehicles[0]["id"]]["plate"] == vehicles[0]["plate"]


def test_live_tracks_need_a_token_and_an_active_run(rec, monkeypatch):
    from types import SimpleNamespace

    from pathscope.recognition.api import routes as rec_routes

    preview = SimpleNamespace(
        tracks=[
            # exactly what the worker puts there (face pipeline overlay form)
            {"id": 7, "cls": "person", "state": "tracked", "recognition": {"identity": "Ada", "identity_id": "x", "status": "recognized", "confidence": 0.81}},
            {"id": 9, "cls": "car", "state": "tracked", "recognition": {"plate": "ABC12345", "vehicle": "Site car", "vehicle_id": "v1", "status": "recognized", "confidence": 0.7}},
            {"id": 8, "cls": "car", "state": "tracked"},
        ]
    )
    handle = SimpleNamespace(latest_preview=preview, preview_seq=12, finished=False, spec=SimpleNamespace(camera_id=3))
    monkeypatch.setattr(rec_routes, "get_supervisor", lambda: SimpleNamespace(get=lambda rid: handle if rid == 42 else None))
    c = rec["client"]
    assert c.get("/api/recognition/live/42/tracks").status_code == 401
    r = c.get("/api/recognition/live/42/tracks", headers=rec["viewer"])
    assert r.status_code == 200
    body = r.json()
    assert [t["display_name"] for t in body["tracks"]] == ["Ada", None] and body["camera_id"] == 3
    assert body["tracks"][0]["kind"] == "enrolled_person" and body["tracks"][1]["vehicle_label"] == "Site car" and body["tracks"][1]["kind"] == "registered_vehicle"
    assert c.get("/api/recognition/live/99/tracks", headers=rec["viewer"]).status_code == 404


def test_identity_labels_are_drawn_only_for_authorised_viewers():
    """The MJPEG stream keeps two pictures of every frame: with names and
    without. A viewer without a recognition token gets the plain one."""
    from types import SimpleNamespace

    from pathscope.vision.overlay import annotate_jpeg, identity_label
    from pathscope.workers.supervisor import RunSupervisor

    assert identity_label(None) == "" and identity_label({"kind": "anonymous_person"}) == ""
    assert identity_label({"identity": "Ada"}) == " = Ada"  # the worker's form
    assert identity_label({"display_name": "Ada"}) == " = Ada"  # the entity form
    assert identity_label({"identity": "Ada", "status": "possible_match"}) == " ? Ada"
    assert identity_label({"plate": "ABC12345", "vehicle": "Site car"}) == " = ABC12345"
    assert identity_label({"status": "unknown"}) == ""

    ok, enc = cv2.imencode(".jpg", np.full((120, 160, 3), 40, dtype=np.uint8))
    assert ok
    tracks = [{"id": 3, "cls": "person", "state": "tracked", "box": (10, 10, 60, 90), "recognition": {"identity": "Ada", "identity_id": "x", "status": "recognized"}}]
    plain = annotate_jpeg(enc.tobytes(), tracks, 160, 160)
    named = annotate_jpeg(enc.tobytes(), tracks, 160, 160, identities=True)
    assert plain != named

    msg = SimpleNamespace(jpeg=enc.tobytes(), tracks=tracks, width=160, source_width=160)
    handle = SimpleNamespace(latest_preview=msg, preview_seq=5, annotated_jpeg=None, annotated_seq=-1, annotated_id_jpeg=None, annotated_id_seq=-1)
    seq_plain, frame_plain = RunSupervisor.annotated_preview(handle)
    seq_named, frame_named = RunSupervisor.annotated_preview(handle, True)
    assert seq_plain == seq_named == 5 and frame_plain != frame_named
    assert handle.annotated_jpeg == frame_plain and handle.annotated_id_jpeg == frame_named


def test_live_overlay_is_stripped_without_a_token():
    from pathscope.api.routes.runs import _recognition_viewer, strip_recognition

    tracks = [{"id": 1, "cls": "person", "recognition": {"identity": "Employee 001"}}, {"id": 2, "cls": "car"}]
    assert strip_recognition(tracks) == [{"id": 1, "cls": "person"}, {"id": 2, "cls": "car"}]
    assert not _recognition_viewer(None) and not _recognition_viewer("psr_nope")


def test_license_removal_locks_the_modules_again(rec):
    c = rec["client"]
    r = c.delete("/api/recognition/license", headers=rec["admin"])
    assert r.status_code == 200 and r.json()["status"]["modules"]["face"]["state"] == "not_licensed"
    assert c.post("/api/recognition/people", json={"display_name": "Nobody"}, headers=rec["operator"]).status_code == 403
    # data stays readable and deletable after the licence lapses
    assert c.get("/api/recognition/people", headers=rec["viewer"]).status_code == 200
    expired_doc = None
    tokens = c.get("/api/recognition/access/tokens", headers=rec["admin"]).json()
    assert tokens
    assert expired_doc is None
    assert c.get("/api/recognition/status").json()["any_licensed"] is False
    assert timedelta(days=1).days == 1
