"""Plate components: OCR config parsing, format layer, temporal consensus and the per-track pipeline with stand-ins."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("PATHSCOPE_RECOGNITION_ALLOW_STUB", "1")

from pathscope.domain.entities import STATUS_INSUFFICIENT  # noqa: E402
from pathscope.recognition.common.types import PlateRead  # noqa: E402
from pathscope.recognition.plate.ocr.base import PlateOcrConfig, parse_simple_yaml  # noqa: E402
from pathscope.recognition.plate.parser import (  # noqa: E402
    PlateFormat,
    PlateParser,
    available_formats,
    candidates,
    load_formats,
    normalize_text,
)
from pathscope.recognition.plate.pipeline import (  # noqa: E402
    PlatePipelineConfig,
    PlateRecognitionPipeline,
    VehicleEntry,
    VehicleIndex,
)
from pathscope.recognition.plate.stack import (  # noqa: E402
    PlateStack,
    ScriptedPlateOcr,
    StubPlateDetector,
)
from pathscope.recognition.plate.temporal import PlateConsensus  # noqa: E402
from pathscope.vision.types import Track  # noqa: E402

V2_CONFIG = """# Config for Latin-alphabet plates

# Max number of plate slots supported. This represents the number of model classification heads.
max_plate_slots: 10
# All the possible character set for the model output.
alphabet: '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_'
pad_char: '_'
img_height: 64
img_width: 128
keep_aspect_ratio: false
interpolation: linear
image_color_mode: rgb
plate_regions: [ 'Albania', 'Andorra', 'Argentina',
                 'United Kingdom', 'Vietnam',
                 'Unknown' ]
"""


def test_plate_config_yaml_parsing():
    d = parse_simple_yaml(V2_CONFIG)
    assert d["max_plate_slots"] == 10 and d["alphabet"].endswith("Z_") and d["keep_aspect_ratio"] is False and d["image_color_mode"] == "rgb"
    assert d["plate_regions"] == ["Albania", "Andorra", "Argentina", "United Kingdom", "Vietnam", "Unknown"]
    cfg = PlateOcrConfig.from_yaml_text(V2_CONFIG)
    assert cfg.padding_color == (114, 114, 114) and cfg.plate_regions[-1] == "Unknown" and cfg.to_dict()["img_width"] == 128
    assert parse_simple_yaml("padding_color: (0, 0, 0)\nx: 'a # not a comment'  # comment\n") == {"padding_color": [0, 0, 0], "x": "a # not a comment"}


def read(text: str, confs: list[float] | None = None, region: str | None = None) -> PlateRead:
    chars = list(text)
    return PlateRead(chars, confs or [0.95] * len(chars), region, 0.8 if region else None)


def test_plate_read_masking_and_normalisation():
    r = read("DUB4567", [0.99, 0.98, 0.97, 0.9, 0.3, 0.95, 0.96])
    assert r.text == "DUB4567" and r.masked(0.5) == "DUB4?67" and round(r.min_confidence, 2) == 0.3
    assert normalize_text("dxb 12s-67 ") == "DXB12S67"
    cands = list(candidates("DXB12S67", 1))
    assert cands[0] == ("DXB12S67", 0) and ("DXB12567", 1) in cands and ("0XB12S67", 1) in cands


def test_format_layer_repairs_confusables_and_reports_fields():
    parser = PlateParser(load_formats(None, "uae,uk,generic"))
    p = parser.parse("DXB 12S67")
    assert p.valid and p.normalized == "DXB12567" and p.format_id == "uae" and p.country == "AE" and p.substitutions == 1
    assert p.fields == {"emirate": "DXB", "number": "12567"} and p.region == "DXB"
    q = parser.parse("AB12CDE")
    assert q.valid and q.format_id == "uk" and q.fields == {"area": "AB", "age": "12", "random": "CDE"}
    g = parser.parse("ZZ99ZZ99")  # neither UAE nor UK: generic fallback
    assert g.valid and g.format_id == "generic" and g.normalized == "ZZ99ZZ99"
    # an earlier format may repair a text that a later one accepts as read: order matters
    assert parser.parse("DUB4567").normalized == "DU84567" and parser.parse_exact("DUB4567").format_id == "generic"
    assert not parser.parse("DUB4?67").valid and parser.parse("").normalized == ""
    strict = PlateParser(load_formats(None, ["uk"]))
    assert not strict.parse("ABC12345").valid
    default_region = PlateParser(load_formats(None, ["us_generic"]), default_region="CA")
    assert default_region.parse("7ABC123").region == "CA"
    assert load_formats(None, "")[0].id == "generic" and load_formats(None, ["nope"])[0].id == "generic"


def test_custom_plate_formats_from_json(tmp_path: Path):
    rec = tmp_path / "recognition"
    rec.mkdir()
    (rec / "plate_formats.json").write_text(json.dumps([{"id": "site", "name": "Site pass", "country": "AE", "pattern": r"^(?P<prefix>SITE)(?P<number>[0-9]{3})$"}]), encoding="utf-8")
    fmts = available_formats(tmp_path)
    assert any(f.id == "site" and not f.builtin for f in fmts)
    parser = PlateParser(load_formats(tmp_path, "site,generic"))
    p = parser.parse("SITE 0O1")  # O -> 0 in the number
    assert p.valid and p.format_id == "site" and p.normalized == "SITE001" and p.substitutions == 1
    (rec / "plate_formats.json").write_text("not json", encoding="utf-8")
    assert [f.id for f in available_formats(tmp_path)] == [f.id for f in available_formats(None)]  # broken file: built-ins only
    with pytest.raises(re.error):
        PlateFormat.from_dict({"id": "bad", "pattern": "([unclosed"})


def test_temporal_consensus_combines_reads_without_inventing_characters():
    c = PlateConsensus(min_char_confidence=0.5, agreement=0.6)
    c.add(read("DUB4567", [0.99, 0.98, 0.97, 0.9, 0.3, 0.95, 0.96]), weight=0.8, t=0.0)  # DUB4?67
    assert c.result().text == "DUB4?67" and not c.result().complete
    c.add(read("DUB4567"), weight=0.9, t=0.1)
    c.add(read("DUB4567"), weight=0.9, t=0.2)
    r = c.result()
    assert r.text == "DUB4567" and r.complete and r.n_observations == 3 and r.confidence > 0.8
    # persistent disagreement leaves the position open
    d = PlateConsensus(agreement=0.6)
    d.add(read("ABC1234"), 1.0, 0)
    d.add(read("ABC7234"), 1.0, 0.1)
    assert d.result().text == "ABC?234"
    d.add(read("ABC1234"), 1.0, 0.2)
    assert d.result().text == "ABC1234"
    # the dominant length wins; a read of another length is ignored
    e = PlateConsensus()
    e.add(read("XY123"), 1.0, 0)
    e.add(read("XY1234"), 1.0, 0.1)
    e.add(read("XY1234"), 1.0, 0.2)
    assert e.result().text == "XY1234" and e.result().n_observations == 2
    assert PlateConsensus().result().text == "" and PlateConsensus().region() == (None, 0.0)
    f = PlateConsensus()
    f.add(read("AB12CDE", region="United Kingdom"), 1.0, 0)
    f.add(read("AB12CDE", region="United Kingdom"), 1.0, 0.1)
    f.add(read("AB12CDE", region="Ireland"), 1.0, 0.2)
    assert f.region() == ("United Kingdom", pytest.approx(2 / 3))


def car(tid, x1, y1, x2, y2, frame, t, cls="car"):
    return Track(track_id=tid, class_name=cls, confidence=0.9, box=(x1, y1, x2, y2), state="tracked", hits=10, age=10, first_frame=0, last_frame=frame, first_time=0.0, last_time=t, mean_confidence=0.9)


def textured_frame(seed=1):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(120, 30, size=(480, 640, 3)), 0, 255).astype(np.uint8)


def make_pipeline(reads, vehicles=None, **cfg):
    stack = PlateStack(StubPlateDetector(), ScriptedPlateOcr(reads))
    parser = PlateParser(load_formats(None, "uae,generic"))
    return PlateRecognitionPipeline(stack, parser, VehicleIndex(vehicles), PlatePipelineConfig(interval_s=0.25, min_observations=2, decision_timeout_s=2.0, **cfg))


def test_pipeline_reads_plate_over_frames_and_matches_registry():
    reads = [read("DUB4567", [0.99, 0.98, 0.97, 0.9, 0.3, 0.95, 0.96]), read("DUB4567"), read("DUB4567")]
    van = VehicleEntry("veh-04", "DUB4567", "Delivery Van 04", ["Delivery Fleet"])
    pipe = make_pipeline(reads, [van])
    frame = textured_frame()
    events = []
    for i in range(20):
        t = i / 10.0
        events.extend(pipe.observe(frame, [car(7, 200, 200, 440, 380, i, t)], t, i, 1000.0 + t).events)
    assert [e["kind"] for e in events] == ["registered_vehicle"]
    ev = events[0]
    assert ev["plate_normalized"] == "DUB4567" and ev["vehicle_id"] == "veh-04" and ev["plate_format"] == "generic"
    assert ev["usable_observations"] >= 2 and ev["confidence"] > 0.6 and ev["model_version"] == "stub+stub"
    ent = pipe.resolve(7, "car")
    assert ent.kind == "registered_vehicle" and ent.plate == "DUB4567" and ent.groups == ["Delivery Fleet"] and ent.vehicle_label == "Delivery Van 04"
    assert pipe.overlay(7)["vehicle"] == "Delivery Van 04"
    d = pipe.diagnostics()["tracks"][0]
    assert d["plate_detected"] and d["consensus"]["text"] == "DUB4567" and d["normalized"] == "DUB4567" and d["raw_ocr"] == "DUB4567"
    # a person track is ignored by the plate module
    assert pipe.observe(frame, [car(8, 200, 200, 440, 380, 21, 2.1, cls="person")], 2.1, 21).attempts == 0


def test_pipeline_records_unknown_plates_only_when_policy_allows():
    reads = [read("ABC12345"), read("ABC12345")]
    pipe = make_pipeline(reads, [])
    frame = textured_frame()
    events = []
    for i in range(10):
        t = i / 10.0
        events.extend(pipe.observe(frame, [car(1, 200, 200, 440, 380, i, t)], t, i).events)
    assert [e["kind"] for e in events] == ["plate_read"] and events[0]["vehicle_id"] is None and events[0]["plate_normalized"] == "ABC12345"
    assert pipe.resolve(1, "car").kind == "recognized_plate"
    quiet = make_pipeline(reads, [], record_unknown_plates=False)
    ev2 = []
    for i in range(10):
        t = i / 10.0
        ev2.extend(quiet.observe(frame, [car(1, 200, 200, 440, 380, i, t)], t, i).events)
    assert ev2 == [] and quiet.resolve(1, "car").plate == "ABC12345"


def test_pipeline_gives_up_without_readable_plate_and_handles_incomplete_reads():
    pipe = make_pipeline([None])
    frame = textured_frame()
    for i in range(30):
        t = i / 10.0
        pipe.observe(frame, [car(1, 200, 200, 440, 380, i, t)], t, i)
    ent = pipe.resolve(1, "car")
    assert ent.status == STATUS_INSUFFICIENT and ent.settled and not ent.recognized
    # persistently undecided characters never produce a plate
    flaky = make_pipeline([read("AB1234", [0.9, 0.9, 0.2, 0.9, 0.9, 0.9])] * 10)
    for i in range(30):
        t = i / 10.0
        flaky.observe(frame, [car(2, 200, 200, 440, 380, i, t)], t, i)
    ent2 = flaky.resolve(2, "car")
    assert ent2.plate is None and ent2.settled and ent2.status == "unknown"
    assert flaky.diagnostics()["tracks"][0]["consensus"]["text"] == "AB?234"
