"""Recognition foundations: licensing, encryption, settings and rule subjects."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pathscope.domain.entities import (
    STATUS_POSSIBLE,
    STATUS_RECOGNIZED,
    STATUS_UNKNOWN,
    EntityRef,
    NullEntityResolver,
    anonymous_entity,
)
from pathscope.domain.rules import Rule, RuleAction, RuleStep, RuleSubject, RuleTrigger
from pathscope.recognition.common import config as rc
from pathscope.recognition.common.crypto import CryptoError, KeyStore, open_sealed, seal
from pathscope.recognition.licensing import ed25519
from pathscope.recognition.licensing.license import (
    STATE_DISABLED,
    STATE_EXPIRED,
    STATE_LICENSED,
    STATE_NOT_LICENSED,
    LicenseError,
    LicenseManager,
    LicensePayload,
    issue_license,
    verify_document,
)
from pathscope.rules.engine import RuleEngine
from pathscope.spatial.engine import SpatialEngine
from pathscope.vision.trackers.base import TrackerUpdate
from pathscope.vision.types import Track

# ----------------------------------------------------------------------------- Ed25519
# RFC 8032 section 7.1, test vectors 1 and 2
RFC_VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
]


@pytest.mark.parametrize("sk,pk,msg,sig", RFC_VECTORS)
def test_ed25519_rfc8032_vectors(sk, pk, msg, sig):
    secret, public, message, signature = bytes.fromhex(sk), bytes.fromhex(pk), bytes.fromhex(msg), bytes.fromhex(sig)
    assert ed25519.public_key(secret) == public
    assert ed25519.sign(secret, message) == signature
    assert ed25519.verify(public, message, signature)
    assert not ed25519.verify(public, message + b"x", signature)
    bad = bytearray(signature)
    bad[3] ^= 1
    assert not ed25519.verify(public, message, bytes(bad))


def test_ed25519_roundtrip_and_doubling_consistency():
    secret, public = ed25519.generate_keypair()
    msg = b"pathscope licence" * 20
    sig = ed25519.sign(secret, msg)
    assert ed25519.verify(public, msg, sig)
    other, _ = ed25519.generate_keypair()
    assert not ed25519.verify(ed25519.public_key(other), msg, sig)
    p = ed25519._mul(12345, ed25519.B)
    assert ed25519.encode_point(ed25519._double(p)) == ed25519.encode_point(ed25519._add(p, p))
    assert not ed25519.verify(public, msg, b"\x00" * 64)


# ----------------------------------------------------------------------------- sealing
def test_seal_and_open_roundtrip_and_tamper_detection(tmp_path: Path):
    store = KeyStore(tmp_path / "keys")
    key = store.key("templates")
    assert store.exists("templates") and store.key("templates") == key and len(key) == 32
    payload = bytes(range(256)) * 300
    blob = seal(key, payload, aad=b"image-1")
    assert blob != payload and open_sealed(key, blob, aad=b"image-1") == payload
    with pytest.raises(CryptoError):
        open_sealed(key, blob, aad=b"image-2")  # wrong associated data
    tampered = bytearray(blob)
    tampered[40] ^= 0x01
    with pytest.raises(CryptoError):
        open_sealed(key, bytes(tampered), aad=b"image-1")
    with pytest.raises(CryptoError):
        open_sealed(KeyStore(tmp_path / "other").key("templates"), blob, aad=b"image-1")
    assert open_sealed(key, seal(key, b"")) == b""
    # two seals of the same data differ (fresh nonce)
    assert seal(key, b"abc") != seal(key, b"abc")


# ----------------------------------------------------------------------------- licences
def _payload(**over) -> LicensePayload:
    base = dict(license_id="LIC-1", licensee="Example Lab", issuer="Vendor", issued_at="2026-09-01", expires_at="2027-09-01", modules=["face", "plate"])
    base.update(over)
    return LicensePayload(**base)


def test_license_verdicts(tmp_path: Path):
    secret, public = ed25519.generate_keypair()
    doc = issue_license(_payload(), secret)
    assert doc["issuer_public_key"] == public.hex()
    today = date(2026, 9, 22)
    v = verify_document(doc, [public], today=today)
    assert v.ok and v.state == STATE_LICENSED and v.payload.licensee == "Example Lab"
    # untrusted issuer
    v2 = verify_document(doc, [ed25519.generate_keypair()[1]], today=today)
    assert not v2.ok and v2.state == STATE_NOT_LICENSED and "does not verify" in v2.reason
    # no trusted key at all (the open-source default)
    assert verify_document(doc, [], today=today).state == STATE_NOT_LICENSED
    # tampered payload
    tampered = json.loads(json.dumps(doc))
    tampered["payload"]["modules"] = ["face", "plate"]
    tampered["payload"]["licensee"] = "Someone else"
    assert verify_document(tampered, [public], today=today).state == STATE_NOT_LICENSED
    # expired
    v3 = verify_document(doc, [public], today=date(2027, 9, 2))
    assert v3.state == STATE_EXPIRED and not v3.ok
    # perpetual
    doc_p = issue_license(_payload(expires_at=None), secret)
    assert verify_document(doc_p, [public], today=date(2099, 1, 1)).state == STATE_LICENSED
    # bound to another machine
    doc_h = issue_license(_payload(hardware_id="abcd"), secret)
    assert "different machine" in verify_document(doc_h, [public], today=today, machine_id="ffff").reason
    assert verify_document(doc_h, [public], today=today, machine_id="abcd").ok
    # malformed
    assert verify_document({"version": 1, "payload": {"licensee": "x"}, "signature": "zz"}, [public]).state == STATE_NOT_LICENSED
    with pytest.raises(LicenseError):
        LicensePayload.from_dict({**_payload().to_dict(), "modules": ["magic"]})


def test_license_manager_module_states(tmp_path: Path):
    secret, public = ed25519.generate_keypair()
    manager = LicenseManager(tmp_path, env={})
    assert manager.module_state("face").state == STATE_NOT_LICENSED
    assert manager.trusted_keys() == []
    doc = issue_license(_payload(modules=["face"]), secret)
    with pytest.raises(LicenseError):
        manager.install(doc)  # no trusted issuer yet: refused, nothing written
    assert not manager.license_path.exists()
    manager.add_trusted_key(public.hex(), "vendor")
    assert manager.trusted_keys() == [public]
    verdict = manager.install(json.dumps(doc))
    assert verdict.ok and manager.license_path.exists()
    face = manager.module_state("face")
    assert face.state == STATE_LICENSED and face.active and face.licensed
    plate = manager.module_state("plate")
    assert plate.state == STATE_NOT_LICENSED and not plate.licensed
    disabled = manager.module_state("face", enabled=False)
    assert disabled.state == STATE_DISABLED and disabled.licensed and not disabled.active
    expired = manager.module_state("face", today=date(2030, 1, 1))
    assert expired.state == STATE_EXPIRED and expired.licensed and not expired.active
    # keys from the environment are trusted too
    env_manager = LicenseManager(tmp_path / "other", env={"PATHSCOPE_RECOGNITION_ISSUER_KEYS": f" {public.hex()} ,bogus"})
    assert env_manager.trusted_keys() == [public]
    summary = manager.describe()
    assert summary["license"]["licensee"] == "Example Lab" and summary["trusted_issuers"] == 1
    assert manager.remove() and manager.module_state("face").state == STATE_NOT_LICENSED


# ----------------------------------------------------------------------------- settings
def test_recognition_setting_coercion():
    assert rc.coerce("recognition.face.min_face_px", "48") == 48
    assert rc.coerce("recognition.face.match_threshold", "") is None
    assert rc.coerce("recognition.face.enabled", 0) is False
    with pytest.raises(ValueError):
        rc.coerce("recognition.face.min_face_px", 2)
    with pytest.raises(ValueError):
        rc.coerce("recognition.face.stack", "cloud")
    with pytest.raises(ValueError):
        rc.coerce("recognition.face.min_observations", "")
    assert rc.module_config({"recognition.face.enabled": True, "recognition.plate.enabled": False}, "face") == {"enabled": True}


# ----------------------------------------------------------------------------- rule subjects
def test_rule_subject_evaluation():
    person = EntityRef("enrolled_person", 1, "person", identity_id="p1", display_name="Employee 001", confidence=0.7, status=STATUS_RECOGNIZED, settled=True)
    unresolved = anonymous_entity(2, "person")
    unknown = anonymous_entity(3, "person", status=STATUS_UNKNOWN, settled=True)
    possible = EntityRef("anonymous_person", 4, "person", identity_id=None, status=STATUS_POSSIBLE)
    assert RuleSubject().evaluate(unresolved) is True
    assert RuleSubject(mode="recognized").evaluate(person) is True
    assert RuleSubject(mode="recognized").evaluate(unresolved) is None
    assert RuleSubject(mode="recognized").evaluate(unknown) is False
    assert RuleSubject(mode="recognized").evaluate(possible) is None
    assert RuleSubject(mode="anonymous").evaluate(person) is False
    assert RuleSubject(mode="anonymous").evaluate(unknown) is True
    assert RuleSubject(mode="anonymous").evaluate(unresolved) is None
    assert RuleSubject(mode="specific", identity_ids=["p1"]).evaluate(person) is True
    assert RuleSubject(mode="specific", identity_ids=["p2"]).evaluate(person) is False
    van = EntityRef("registered_vehicle", 5, "car", plate="ABC12345", vehicle_id="v1", groups=["Delivery Fleet"], status=STATUS_RECOGNIZED, settled=True)
    read = EntityRef("recognized_plate", 6, "car", plate="XYZ999", status=STATUS_RECOGNIZED, settled=True)
    assert RuleSubject(mode="registered").evaluate(van) is True
    assert RuleSubject(mode="registered", groups=["Delivery Fleet"]).evaluate(van) is True
    assert RuleSubject(mode="registered", groups=["Staff"]).evaluate(van) is False
    assert RuleSubject(mode="registered").evaluate(read) is False
    assert RuleSubject(mode="specific", plates=["abc-12345"]).evaluate(van) is True
    assert RuleSubject(mode="specific", plates=["ABC12345"]).plates == ["ABC12345"]
    assert RuleSubject(mode="specific", vehicle_ids=["v1"]).evaluate(van) is True
    assert RuleSubject(mode="recognized").evaluate(read) is True
    with pytest.raises(ValueError):
        RuleSubject(mode="specific")
    assert Rule(classes=["person"], subject=RuleSubject(mode="recognized"), trigger=RuleTrigger(object_id="x")).modules_needed == {"face"}
    assert Rule(classes=["car", "truck"], subject=RuleSubject(mode="registered"), trigger=RuleTrigger(object_id="x")).modules_needed == {"plate"}
    assert Rule(classes=[], subject=RuleSubject(mode="recognized"), trigger=RuleTrigger(object_id="x")).modules_needed == {"face", "plate"}
    assert Rule(classes=["person"], trigger=RuleTrigger(object_id="x")).modules_needed == set()


# A scripted resolver standing in for the recognition runtime
class ScriptedResolver:
    def __init__(self, modules=("face",)):
        self.entities: dict[int, EntityRef] = {}
        self.modules = set(modules)
        self.forgotten: list[int] = []

    def provides(self):
        return set(self.modules)

    def resolve(self, track_id, object_class):
        return self.entities.get(track_id) or anonymous_entity(track_id, object_class)

    def forget(self, track_id):
        self.forgotten.append(track_id)
        self.entities.pop(track_id, None)

    def recognize(self, track_id, identity_id, name, t, cls="person"):
        self.entities[track_id] = EntityRef("enrolled_person", track_id, cls, identity_id=identity_id, display_name=name, confidence=0.72, status=STATUS_RECOGNIZED, settled=True, resolved_at=t)

    def unknown(self, track_id, cls="person"):
        self.entities[track_id] = anonymous_entity(track_id, cls, status=STATUS_UNKNOWN, settled=True)

    def plate(self, track_id, plate, vehicle_id=None, groups=(), cls="car"):
        kind = "registered_vehicle" if vehicle_id else "recognized_plate"
        self.entities[track_id] = EntityRef(kind, track_id, cls, plate=plate, vehicle_id=vehicle_id, groups=list(groups), confidence=0.93, status=STATUS_RECOGNIZED, settled=True)


W, H, FPS = 1000, 500, 10.0


def scene(objects, classes=("person",)):
    from pathscope.domain.scene import SceneDocument

    return SceneDocument.model_validate({"frame_width": W, "frame_height": H, "objects": objects, "routes": []})


ZONE_A = {"id": "zone_a", "type": "zone", "name": "Zone A", "points": [{"x": 0.6, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.6, "y": 0.9}], "classes": ["person"]}
GATE = {"id": "gate", "type": "gate", "name": "Entrance Gate", "points": [{"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 1.0}], "classes": ["car", "person"]}
GATE_B = {"id": "gate_b", "type": "gate", "name": "Checkpoint B", "points": [{"x": 0.8, "y": 0.0}, {"x": 0.8, "y": 1.0}], "classes": ["person"]}


def track(tid, x, y, frame, t, cls="person"):
    px, py = x * W, y * H
    return Track(track_id=tid, class_name=cls, confidence=0.9, box=(px - 20, py - 60, px + 20, py), state="tracked", hits=50, age=50, first_frame=0, last_frame=frame, first_time=0.0, last_time=t, mean_confidence=0.9)


class Sim:
    def __init__(self, doc, rules, resolver, classes=("person",), grace=5.0):
        self.spatial = SpatialEngine(doc, W, H, list(classes))
        self.rules = RuleEngine(doc, rules, self.spatial, list(classes), entities=resolver, subject_grace_s=grace)
        self.frame = 0
        self.events = []

    @property
    def t(self):
        return self.frame / FPS

    def step(self, positions, removed=(), classes=None):
        t = self.t
        classes = classes or {}
        tracks = [track(tid, x, y, self.frame, t, classes.get(tid, "person")) for tid, (x, y) in positions.items()]
        rem = [track(tid, 0.5, 0.5, self.frame, t, classes.get(tid, "person")) for tid in removed]
        upd = TrackerUpdate(tracks=tracks, started=[], reacquired=[], lost=[], removed=rem)
        evs = self.rules.process(self.spatial.update(upd, t, self.frame), t, self.frame, 1000.0 + t)
        self.events.extend(evs)
        self.frame += 1
        return evs

    def idle(self, seconds, positions=None, classes=None):
        for _ in range(int(round(seconds * FPS))):
            self.step(positions or {}, classes=classes)


def dwell_rule(subject, remains=30.0):
    return Rule(name="Extended Zone A presence", classes=["person"], subject=subject, trigger=RuleTrigger(kind="enters", object_id="zone_a"), remains_for_s=remains, record_as="Extended Zone A presence",
                actions=[RuleAction(kind="count"), RuleAction(kind="record_event")])


def test_acceptance_enrolled_person_enters_zone_and_remains():
    """Spec 21: an enrolled person enters Zone A and remains for more than 30 s."""
    resolver = ScriptedResolver()
    rule = dwell_rule(RuleSubject(mode="specific", identity_ids=["emp-001"]))
    sim = Sim(scene([ZONE_A]), [rule], resolver)
    sim.step({1: (0.7, 0.5)})  # the anonymous track enters Zone A at t=0
    sim.idle(2.0, {1: (0.72, 0.5)})
    resolver.recognize(1, "emp-001", "Employee 001", sim.t)  # the face module matches after 2 s
    sim.idle(31.0, {1: (0.75, 0.5)})
    dwell = [e for e in sim.events if e.event_type == "dwell"]
    assert len(dwell) == 1
    ev = dwell[0]
    assert ev.label == "Extended Zone A presence" and ev.track_id == 1 and ev.duration_s >= 30.0
    assert ev.context["entity"] == {"kind": "enrolled_person", "identity_id": "emp-001", "confidence": 0.72, "status": "recognized"}
    assert "display_name" not in json.dumps(ev.context)  # names never enter ordinary events
    assert {c["label"]: c["value"] for c in sim.rules.counters_list()}["Extended Zone A presence"] == 1
    # implicit zone entry of the recognized track is enriched with the opaque reference as well
    entry = next(e for e in sim.events if e.event_type == "zone_entry")
    assert "entity" not in entry.context  # it happened before recognition (t=0)
    # a different enrolled person does not trigger the rule
    resolver2 = ScriptedResolver()
    sim2 = Sim(scene([ZONE_A]), [rule], resolver2)
    sim2.step({2: (0.7, 0.5)})
    resolver2.recognize(2, "emp-002", "Employee 002", 0.1)
    sim2.idle(32.0, {2: (0.75, 0.5)})
    assert [e for e in sim2.events if e.event_type == "dwell"] == []
    assert sim2.rules.stats["subject_unmatched"] == 1


def test_late_recognition_within_grace_emits_the_event_with_original_time():
    """The identity arrives two seconds after the gate crossing: the crossing event is still recorded."""
    resolver = ScriptedResolver()
    rule = Rule(name="Staff at gate", classes=["person"], subject=RuleSubject(mode="recognized"), trigger=RuleTrigger(kind="crosses", object_id="gate"), record_as="Staff crossing")
    sim = Sim(scene([GATE]), [rule], resolver, grace=5.0)
    sim.step({1: (0.45, 0.5)})
    sim.step({1: (0.55, 0.5)})  # crosses at t=0.1
    assert [e for e in sim.events if e.event_type == "rule"] == [] and sim.rules.pending_count() == 1
    sim.idle(2.0, {1: (0.6, 0.5)})
    resolver.recognize(1, "emp-001", "Employee 001", sim.t)
    sim.step({1: (0.62, 0.5)})
    rule_events = [e for e in sim.events if e.event_type == "rule"]
    assert len(rule_events) == 1 and abs(rule_events[0].media_time_s - 0.1) < 1e-6
    assert rule_events[0].context["entity"]["identity_id"] == "emp-001"
    assert sim.rules.pending_count() == 0
    # Without recognition the event is dropped after the grace period
    resolver2 = ScriptedResolver()
    sim2 = Sim(scene([GATE]), [rule], resolver2, grace=1.0)
    sim2.step({1: (0.45, 0.5)})
    sim2.step({1: (0.55, 0.5)})
    sim2.idle(2.0, {1: (0.6, 0.5)})
    assert [e for e in sim2.events if e.event_type == "rule"] == [] and sim2.rules.stats["subject_pending_dropped"] == 1
    assert {c["label"]: c["value"] for c in sim2.rules.counters_list()}["Staff crossing"] == 0


def test_anonymous_subject_fires_only_when_nobody_was_recognized():
    resolver = ScriptedResolver()
    rule = Rule(name="Visitor", classes=["person"], subject=RuleSubject(mode="anonymous"), trigger=RuleTrigger(kind="crosses", object_id="gate"), record_as="Unknown visitor")
    sim = Sim(scene([GATE]), [rule], resolver, grace=1.0)
    sim.step({1: (0.45, 0.5), 2: (0.45, 0.3)})
    sim.step({1: (0.55, 0.5), 2: (0.55, 0.3)})
    resolver.recognize(1, "emp-001", "Employee 001", 0.1)
    resolver.unknown(2)  # the module looked and found nobody
    sim.step({1: (0.6, 0.5), 2: (0.6, 0.3)})
    evs = [e for e in sim.events if e.event_type == "rule"]
    assert [e.track_id for e in evs] == [2]
    # an undecided track becomes anonymous when the grace period ends
    sim.step({3: (0.45, 0.7)})
    sim.step({3: (0.55, 0.7)})
    sim.idle(1.5, {3: (0.6, 0.7)})
    assert [e.track_id for e in sim.events if e.event_type == "rule"] == [2, 3]


def test_track_ending_finalizes_pending_and_forgets_entity():
    resolver = ScriptedResolver()
    rule = Rule(name="Staff", classes=["person"], subject=RuleSubject(mode="recognized"), trigger=RuleTrigger(kind="crosses", object_id="gate"), record_as="Staff")
    sim = Sim(scene([GATE]), [rule], resolver, grace=30.0)
    sim.step({1: (0.45, 0.5)})
    sim.step({1: (0.55, 0.5)})
    sim.step({}, removed=[1])
    assert sim.rules.pending_count() == 0 and sim.rules.stats["subject_pending_dropped"] == 1
    assert resolver.forgotten == [1]


def test_subject_rules_are_inactive_without_their_module():
    rule = Rule(name="Staff", classes=["person"], subject=RuleSubject(mode="recognized"), trigger=RuleTrigger(kind="crosses", object_id="gate"), record_as="Staff")
    plain = Rule(name="Anyone", classes=["person"], trigger=RuleTrigger(kind="crosses", object_id="gate"), record_as="Anyone")
    sim = Sim(scene([GATE]), [rule, plain], NullEntityResolver())
    assert [r.name for r in sim.rules.inactive_rules] == ["Staff"]
    sim.step({1: (0.45, 0.5)})
    sim.step({1: (0.55, 0.5)})
    assert [e.label for e in sim.events if e.event_type == "rule"] == ["Anyone"]
    desc = sim.rules.describe()
    assert desc["inactive_rules"] == [{"id": rule.id, "name": "Staff", "needs": ["face"]}] and desc["recognition_modules"] == []
    # a plate-only runtime does not activate a face rule either
    sim2 = Sim(scene([GATE]), [rule], ScriptedResolver(modules=("plate",)))
    assert len(sim2.rules.inactive_rules) == 1


def test_acceptance_registered_plate_crosses_entrance_gate():
    """Spec 22: plate ABC12345 crosses the Entrance Gate and the crossing is recorded."""
    resolver = ScriptedResolver(modules=("plate",))
    rule = Rule(name="Vehicle Entry", classes=["car", "truck"], subject=RuleSubject(mode="specific", plates=["ABC 12345"]), trigger=RuleTrigger(kind="crosses", object_id="gate"), record_as="Vehicle Entry")
    group_rule = Rule(name="Fleet", classes=["car", "truck"], subject=RuleSubject(mode="registered", groups=["Delivery Fleet"]), trigger=RuleTrigger(kind="crosses", object_id="gate"), record_as="Fleet arrival")
    sim = Sim(scene([GATE]), [rule, group_rule], resolver, classes=("car", "truck", "person"))
    cls = {7: "car", 8: "car"}
    sim.step({7: (0.45, 0.5)}, classes=cls)
    resolver.plate(7, "ABC12345", vehicle_id="veh-1", groups=["Delivery Fleet"])  # read while approaching
    sim.step({7: (0.55, 0.5)}, classes=cls)
    labels = sorted(e.label for e in sim.events if e.event_type == "rule")
    assert labels == ["Fleet arrival", "Vehicle Entry"]
    ev = next(e for e in sim.events if e.label == "Vehicle Entry")
    assert ev.object_class == "car" and ev.context["entity"]["kind"] == "registered_vehicle" and ev.context["entity"]["vehicle_id"] == "veh-1"
    assert "ABC12345" not in json.dumps(ev.context)  # plate text stays in the restricted store
    # implicit crossing of the recognized vehicle carries the opaque reference
    crossing = next(e for e in sim.events if e.event_type == "crossing" and e.track_id == 7)
    assert crossing.context["entity"]["kind"] == "registered_vehicle"
    # another plate: not matched
    sim.step({8: (0.45, 0.3)}, classes=cls)
    resolver.plate(8, "XYZ999")
    sim.step({8: (0.55, 0.3)}, classes=cls)
    assert [e.label for e in sim.events if e.event_type == "rule"] == ["Vehicle Entry", "Fleet arrival"]
    assert sim.rules.stats["subject_unmatched"] == 2


def test_configured_route_sequence_with_identity():
    """Recognized Person X crosses Checkpoint A then Checkpoint B: recorded as a configured route."""
    resolver = ScriptedResolver()
    rule = Rule(name="Route", classes=["person"], subject=RuleSubject(mode="specific", identity_ids=["px"]), trigger=RuleTrigger(kind="crosses", object_id="gate"),
                then=[RuleStep(kind="crosses", object_id="gate_b", within_s=20)], record_as="Configured Route")
    sim = Sim(scene([GATE, GATE_B]), [rule], resolver)
    sim.step({1: (0.45, 0.5)})
    resolver.recognize(1, "px", "Person X", 0.0)
    for x in (0.55, 0.65, 0.75, 0.85):
        sim.step({1: (x, 0.5)})
    seq = [e for e in sim.events if e.event_type == "sequence"]
    assert len(seq) == 1 and seq[0].route == "Configured Route" and seq[0].context["entity"]["identity_id"] == "px"
