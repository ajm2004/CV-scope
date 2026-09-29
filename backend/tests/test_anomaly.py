"""Anomaly Assistant: deterministic detection on synthetic scenes, evidence, subjects and the model prompt."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from anomaly_scenes import H, W, box_object, place, room, run

from pathscope.anomaly import AnomalyAssistant, AnomalySettings, AnomalyZoneSettings, EvidenceWriter
from pathscope.anomaly.config import PRESETS
from pathscope.anomaly.llm.prompt import build_user_text, choose_pictures, parse_answer
from pathscope.anomaly.subjects import SubjectBook, generic_names, subject_phrase
from pathscope.domain.entities import EntityRef

FPS = 5.0
BED = [(400 / W, 220 / H), (610 / W, 220 / H), (610 / W, 340 / H), (400 / W, 340 / H)]


def secs(s: float) -> int:
    return int(s * FPS)


def frame_assistant(**zone) -> AnomalyAssistant:
    z = AnomalyZoneSettings(id="frame", name="Room", **zone)
    return AnomalyAssistant(AnomalySettings(enabled=True, zones=[z], lighting_events=True), (W, H))


def bed_assistant(**zone) -> AnomalyAssistant:
    z = AnomalyZoneSettings(id="bed", name="Bed", **zone)
    return AnomalyAssistant(AnomalySettings(enabled=True, zones=[z]), (W, H), zones={"bed": BED})


@pytest.fixture(scope="module")
def bg() -> np.ndarray:
    return room()


@pytest.fixture(scope="module")
def with_bag(bg) -> np.ndarray:
    return place(bg, box_object(), 280, 360)


# ---------------------------------------------------------------------------- noise is not an anomaly
def test_a_quiet_noisy_camera_raises_nothing_and_learns_first(bg):
    a = frame_assistant()
    assert a.state == "learning"
    assert run(a, [(bg, 1.0)] * secs(60), FPS) == []
    assert a.state == "watching"
    zone = a.status()["zones"][0]
    assert zone["state"] == "idle" and zone["confirmed"] == 0


@pytest.mark.parametrize("name", ["exposure", "shadow", "flash", "insect", "slow_drift"])
def test_insignificant_changes_are_filtered(bg, with_bag, name):
    frames = [(bg, 1.0)] * secs(20)
    if name == "exposure":  # automatic exposure / a cloud: the whole picture 20 % brighter
        frames += [(bg, 1.2)] * secs(30)
    elif name == "shadow":  # a shadow over textured wall and floor
        s = bg.copy()
        s[150:330, 250:400] *= 0.72
        frames += [(s, 1.0)] * secs(30)
    elif name == "flash":  # something for half a second
        frames += [(with_bag, 1.0)] * 2 + [(bg, 1.0)] * secs(20)
    elif name == "insect":  # a few pixels moving
        for i in range(secs(20)):
            s = bg.copy()
            cv2.circle(s, (100 + i * 4, 100 + i % 30), 2, (10, 10, 10), -1)
            frames.append((s, 1.0))
    else:  # sunlight creeping over the floor for four minutes
        n = secs(240)
        for i in range(n):
            s = bg.copy()
            s[320:460, 100:300] *= 1.0 + 0.6 * i / n
            frames.append((s, 1.0))
    assert run(frame_assistant(), frames, FPS) == []


# ---------------------------------------------------------------------------- real changes
def test_an_object_that_appears_is_confirmed_then_accepted_as_the_new_normal(bg, with_bag):
    a = frame_assistant(accept_after_s=20)
    ups = run(a, [(bg, 1.0)] * secs(20) + [(with_bag, 1.0)] * secs(50), FPS)
    assert [u.phase for u in ups] == ["confirmed", "ended"]
    c, e = ups
    assert c.kind == "appeared" and e.kind == "appeared" and e.end_reason == "accepted"
    # confirmed after the persistence time (medium: 2.5 s), not on the first frame
    assert PRESETS["medium"]["persistence_s"] <= c.confirmed_t - c.started_t <= PRESETS["medium"]["persistence_s"] + 1.0
    assert c.confidence >= PRESETS["medium"]["min_confidence"]
    # the changed area is where the bag is (x 280-350, y 360-420 of 640 x 480)
    x1, y1, x2, y2 = c.bbox
    assert 0.40 < x1 < 0.46 and 0.52 < x2 < 0.58 and 0.72 < y1 < 0.78 and 0.84 < y2 < 0.9
    assert set(c.frames) == {"before", "event"} and set(e.frames) == {"after"}
    assert "appeared" in c.summary and "lasted" in e.summary and "accepted as the new normal" in e.summary
    # once accepted, the bag is normal: nothing more happens
    assert run(a, [(with_bag, 1.0)] * secs(20), FPS, t0=200.0) == []


def test_removed_and_moved_objects_are_told_apart(bg, with_bag):
    removed = run(frame_assistant(accept_after_s=20), [(with_bag, 1.0)] * secs(20) + [(bg, 1.0)] * secs(30), FPS)
    assert removed[0].kind == "disappeared"
    moved_scene = place(bg, box_object(), 120, 380)
    moved = run(frame_assistant(accept_after_s=20), [(with_bag, 1.0)] * secs(20) + [(moved_scene, 1.0)] * secs(30), FPS)
    assert moved[0].kind == "moved" and moved[0].metrics["static"]["moved_match"] > 0.4


def test_a_flat_grey_object_on_a_flat_wall_is_not_mistaken_for_a_shadow(bg):
    scene = bg.copy()
    cv2.rectangle(scene, (470, 40), (560, 150), (95, 100, 105), -1)  # a dark poster on the plain wall
    wall = room().copy()
    wall[:] = (150, 160, 170)  # a wall without texture
    wall_with = wall.copy()
    cv2.rectangle(wall_with, (270, 150), (370, 260), (100, 106, 112), -1)
    ups = run(frame_assistant(), [(wall, 1.0)] * secs(20) + [(wall_with, 1.0)] * secs(10), FPS)
    assert ups and ups[0].phase == "confirmed"


def test_lights_switched_off_is_a_lighting_event_and_the_scene_is_learned_again(bg, with_bag):
    a = frame_assistant()
    ups = run(a, [(bg, 1.0)] * secs(20) + [(bg, 0.35)] * secs(8), FPS)
    assert [u.kind for u in ups] == ["lighting"] and ups[0].instant
    assert a.state == "learning"
    # after learning the dark room again, a change in the dark is still found
    later = run(a, [(bg, 0.35)] * secs(12) + [(with_bag, 0.35)] * secs(10), FPS, t0=40.0)
    assert later and later[0].kind == "appeared"


def test_zone_presence_with_detections_and_duration(bg):
    dog = place(bg, box_object((50, 40), seed=4), 450, 280)

    def objects(t):
        return [{"track_id": 7, "class_name": "dog", "confidence": 0.8, "box": (450, 280, 500, 320)}] if 20 <= t < 38 else []

    ups = run(bed_assistant(), [(bg, 1.0)] * secs(20) + [(dog, 1.0)] * secs(18) + [(bg, 1.0)] * secs(15), FPS, objects_at=objects)
    assert [u.phase for u in ups] == ["confirmed", "ended"]
    c, e = ups
    assert c.kind == "presence" and c.objects == [{"track_id": 7, "object_class": "dog", "confidence": 0.8}]
    assert c.subjects[0]["alias"] == "Animal A"
    assert e.end_reason == "cleared" and 16.0 <= e.duration_s <= 19.5
    assert e.summary.startswith("A dog entered Bed; lasted 1")


def test_objects_outside_the_zone_or_of_other_classes_do_not_count(bg):
    def objects(t):
        return [{"track_id": 3, "class_name": "person", "confidence": 0.9, "box": (40, 100, 120, 300)}]  # far left, outside the bed

    a = bed_assistant(detect=["presence"])
    assert run(a, [(bg, 1.0)] * secs(30), FPS, objects_at=objects) == []
    b = bed_assistant(detect=["presence"], presence_classes=["dog"])

    def person_on_bed(t):
        return [{"track_id": 4, "class_name": "person", "confidence": 0.9, "box": (450, 200, 520, 330)}] if t > 15 else []

    assert run(b, [(bg, 1.0)] * secs(30), FPS, objects_at=person_on_bed) == []


def test_pixel_changes_are_ignored_when_only_presence_is_watched(bg):
    shifted = bg.copy()
    shifted[240:270, 455:600] = bg[240:270, 430:575]
    assert run(bed_assistant(detect=["presence"]), [(bg, 1.0)] * secs(20) + [(shifted, 1.0)] * secs(20), FPS) == []
    found = run(bed_assistant(), [(bg, 1.0)] * secs(20) + [(shifted, 1.0)] * secs(20), FPS)
    assert found and found[0].zone_name == "Bed"


def test_sensitivity_and_persistence_are_per_zone(bg, with_bag):
    # "low" wants 2 % of the zone: a bag of 1.4 % of the picture does not count in the whole frame
    assert run(frame_assistant(sensitivity="low"), [(bg, 1.0)] * secs(20) + [(with_bag, 1.0)] * secs(15), FPS) == []
    # a custom persistence of 8 s delays the confirmation accordingly
    ups = run(frame_assistant(persistence_s=8.0), [(bg, 1.0)] * secs(20) + [(with_bag, 1.0)] * secs(15), FPS)
    assert ups and ups[0].confirmed_t - ups[0].started_t >= 8.0


def test_finish_and_rebaseline_end_open_anomalies(bg, with_bag):
    a = frame_assistant(accept_after_s=0)
    run(a, [(bg, 1.0)] * secs(20) + [(with_bag, 1.0)] * secs(10), FPS)
    assert a.status()["zones"][0]["state"] == "active"
    ended = a.finish()
    assert len(ended) == 1 and ended[0].end_reason == "run_ended"
    b = frame_assistant(accept_after_s=0)
    run(b, [(bg, 1.0)] * secs(20) + [(with_bag, 1.0)] * secs(10), FPS)
    b.rebaseline()
    assert b.state == "learning" and b.status()["zones"][0]["state"] == "idle"


def test_analysis_is_rate_limited_and_cheap(bg):
    a = frame_assistant()
    run(a, [(bg, 1.0)] * 300, fps=30.0)  # 10 s of a 30 fps camera
    assert 38 <= a.stats["analyses"] <= 42  # 4 analyses per second
    assert a.analysis_ms < 60.0


# ---------------------------------------------------------------------------- evidence
def test_evidence_pictures_are_written(tmp_path, bg, with_bag):
    ups = run(frame_assistant(accept_after_s=15), [(bg, 1.0)] * secs(20) + [(with_bag, 1.0)] * secs(30), FPS)
    writer = EvidenceWriter(tmp_path)
    first = writer.write(ups[0], [("person #3", (10, 10, 60, 120))])
    assert set(first) == {"before", "event", "overlay", "crop_event", "crop_before"}
    last = writer.write(ups[1])
    assert set(last) == {"after", "crop_after", "overlay_after"}
    for rel in {**first, **last}.values():
        img = cv2.imread(str(tmp_path / rel))
        assert img is not None and img.shape[1] <= 1280
    json.dumps(ups[0].to_dict())  # the update travels between processes as plain data


# ---------------------------------------------------------------------------- subjects, prompt
class FakeResolver:
    def resolve(self, track_id, object_class):
        if track_id == 1:
            return EntityRef("enrolled_person", 1, "person", identity_id="p_17", display_name="Alice Example", confidence=0.93, status="recognized", settled=True)
        if track_id == 2:
            return EntityRef("anonymous_person", 2, "person", status="unknown", settled=True)
        return EntityRef("registered_vehicle", track_id, "car", vehicle_id="v_9", plate="ABC123", vehicle_label="Van", status="recognized", settled=True)

    def provides(self):
        return {"face", "plate"}

    def forget(self, track_id):
        return None


def test_subjects_carry_ids_and_status_but_never_names_or_plates():
    subjects = SubjectBook(FakeResolver()).describe([
        {"track_id": 1, "object_class": "person", "confidence": 0.9},
        {"track_id": 2, "object_class": "person", "confidence": 0.8},
        {"track_id": 5, "object_class": "car", "confidence": 0.7},
    ])
    assert [s["alias"] for s in subjects] == ["Person A", "Person B", "Vehicle A"]
    assert subjects[0]["identity_id"] == "p_17" and subjects[2]["vehicle_id"] == "v_9"
    blob = json.dumps(subjects)
    assert "Alice" not in blob and "ABC123" not in blob and "Van" not in blob
    assert subject_phrase(subjects[0]) == "[Person A] (recognized person)"
    assert subject_phrase(subjects[1]) == "an unknown person"
    assert generic_names("[Person A] entered the vault with [Vehicle A].", subjects) == "A recognized person entered the vault with a registered vehicle."
    assert generic_names("[Person A] (recognized person) entered Vault.", subjects) == "A recognized person entered Vault."


def test_the_prompt_gives_observations_and_aliases_only():
    subjects = SubjectBook(FakeResolver()).describe([{"track_id": 1, "object_class": "person", "confidence": 0.9}])
    record = {
        "camera_name": "Vault cam", "zone_id": "z1", "zone_name": "Vault", "expected_state": "Nobody inside at night.", "kind": "presence", "confidence": 0.95,
        "area_pct": 12.0, "bbox": [0.1, 0.2, 0.3, 0.9], "started_at": 1_790_000_000.0, "confirmed_after_s": 2.5, "duration_s": 18.0, "end_reason": "cleared",
        "subjects": subjects, "metrics": {}, "summary": "[Person A] (recognized person) entered Vault; lasted 18 s, back to normal.",
    }
    text = build_user_text(record, ["before", "overlay"])
    assert "Vault" in text and "Nobody inside at night." in text and "[Person A]: an enrolled person recognized" in text
    assert "18 s" in text and "1) the normal picture" in text and "Alice" not in text
    assert choose_pictures({"before": "a", "event": "b", "overlay": "c", "crop_before": "d", "crop_event": "e", "after": "f", "crop_after": "g", "overlay_after": "h"}, True, True) == ["before", "overlay_after", "crop_before", "crop_after"]
    assert choose_pictures({"before": "a", "overlay": "c"}, False, False) == ["before", "overlay"]


def test_answers_are_read_tolerantly():
    a = parse_answer('```json\n{"verdict": "Confirmed", "category": "animal", "description": "An animal entered  the barn.", "confidence": 87, "evidence": "fur"}\n```')
    assert a == {"verdict": "confirmed", "category": "animal", "description": "An animal entered the barn.", "confidence": 0.87, "evidence": "fur"}
    assert parse_answer('{"verdict": "maybe", "category": "x", "description": "d"}')["verdict"] == "uncertain"
    with pytest.raises(ValueError):
        parse_answer("I think something happened.")
