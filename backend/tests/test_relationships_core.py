"""The relationship engine on synthetic scenes (no database)."""

from __future__ import annotations

import pytest
from relationship_scenes import FakeResolver, Sim, rule, zone

from pathscope.relationships import entities as E
from pathscope.relationships.confidence import Components, combine, state_for
from pathscope.relationships.relations import (
    RelationType,
    check_rule_output,
    register_relation_type,
    unregister_relation_type,
)
from pathscope.relationships.rules import RelationRuleDefinition, templates
from pathscope.relationships.temporal import Interval, allen, relations_between
from pathscope.spatial.engine import Interaction

PERSON = {"classes": ["person"]}
VEHICLE = {"classes": ["car"]}


def near_rule(**kw):
    d = {"kind": "pair", "name": "Beside vehicle", "subject": PERSON, "object": VEHICLE, "condition": "near",
         "distance": {"value": 2.0, "unit": "m", "fallback_fw": 0.04}, "for_s": 5, "relation": "ASSOCIATED_WITH"}
    d.update(kw)
    return rule("rel_near", **d)


# ---------------------------------------------------------------------------- registry, rules, confidence
def test_non_observable_relations_are_refused():
    for bad in ("OWNS", "FRIEND", "FAMILY", "COWORKER", "PARTNER"):
        with pytest.raises(ValueError):
            check_rule_output(bad)
        with pytest.raises(ValueError):
            RelationRuleDefinition.model_validate({"kind": "place", "subject": PERSON, "place_event": "enters", "relation": bad})
    with pytest.raises(ValueError):
        register_relation_type(RelationType("FRIEND", "friend of", "friend of", "external", builtin=False))
    # only as an externally supplied (registry) type, and never as a rule output
    register_relation_type(RelationType("FRIEND", "friend of", "friend of", "external", inferable=False, external_only=True, builtin=False))
    try:
        with pytest.raises(ValueError):
            check_rule_output("FRIEND")
    finally:
        unregister_relation_type("FRIEND")
    assert check_rule_output("ASSOCIATED_WITH").id == "ASSOCIATED_WITH"
    with pytest.raises(ValueError):
        check_rule_output("IDENTIFIED_AS")  # only from recognition results


def test_rule_validation_and_defaults():
    d = RelationRuleDefinition.model_validate({"kind": "pair", "subject": PERSON, "object": VEHICLE, "condition": "approaches", "distance": {"value": 2}})
    assert d.relation == "APPROACHED"
    with pytest.raises(ValueError):
        RelationRuleDefinition.model_validate({"kind": "pair", "subject": PERSON, "object": VEHICLE, "condition": "near"})  # no distance
    with pytest.raises(ValueError):
        RelationRuleDefinition.model_validate({"kind": "place", "subject": VEHICLE, "place_event": "stops_in"})  # no time
    with pytest.raises(ValueError):
        RelationRuleDefinition.model_validate({"kind": "sequence", "subject": PERSON, "steps": [{"what": "appears"}]})  # no output
    for t in templates():
        RelationRuleDefinition.model_validate(t["definition"])


def test_confidence_states():
    strong = combine(Components(tracking=0.95, spatial=1.0, temporal=0.95, support=30))
    weak = combine(Components(tracking=0.5, spatial=0.65, temporal=0.4, support=2))
    assert state_for(strong) == "confirmed"
    assert state_for(weak) in ("possible", "insufficient")
    assert combine(Components(tracking=0.95, spatial=1.0, temporal=0.95, support=1)) < strong  # less support, less certain
    assert combine(Components(tracking=0.95, recognition=0.3, spatial=1.0, temporal=1.0, support=30)) < 0.65  # weak recognition pulls it down


def test_temporal_relations():
    assert allen(Interval(0, 2), Interval(5, 6)) == "before"
    rels = dict(relations_between(Interval(10, 12), Interval(0, 5), within_s=6))
    assert rels["FOLLOWED_AFTER"] == 5 and rels["FOLLOWED_WITHIN"] == 5 and "STARTED_AFTER" in rels
    assert "OVERLAPPED_WITH" in dict(relations_between(Interval(0, 5), Interval(3, 8)))


# ---------------------------------------------------------------------------- spatial pairs
def _person_to_car(sim: Sim, stay_s: float = 8.0, stand_x: float = 20.0) -> None:
    """Car parked at x=20..24 m (centre 22), person walks from x=5 to beside the car and stands."""
    t_walk = 6.0
    n = int((t_walk + stay_s) * 10)
    for i in range(n):
        t = i / 10
        x = 5 + (stand_x - 5) * min(1.0, t / t_walk)
        sim.step({1: ("person", x, 30.0), 2: ("car", 22.0, 30.0)})


def test_person_beside_vehicle_calibrated():
    sim = Sim([near_rule()])
    _person_to_car(sim)
    sim.finish()
    rels = sim.rels("ASSOCIATED_WITH")
    assert len(rels) == 1
    r = rels[0]
    assert r["subject"] == E.track_key(1, 1, "person") and r["object"] == E.track_key(1, 2, "car")
    # measured to the car's side (its box edge at x=20), not its centre 2 m further
    assert r["metrics"]["min_distance"] < 0.2
    assert r["calibration"]["measure"] == "physical" and r["calibration"]["unit"] == "m"
    assert r["status"] == "closed" and r["end_t"] - r["start_t"] >= 5
    assert r["state"] in ("likely", "confirmed")
    assert "within 2.00 m" in r["reason"] and "samples met the condition" in r["reason"]
    assert r["rule_key"] == "rel_near" and r["rule_version"] == 1


def test_uncalibrated_uses_frame_widths_and_says_so():
    sim = Sim([near_rule()], calibrated=False)
    _person_to_car(sim)
    sim.finish()
    r = sim.rels("ASSOCIATED_WITH")[0]
    assert r["calibration"]["measure"] == "scene-relative" and r["calibration"]["unit"] == "fw"
    assert "frame widths" in r["reason"] and "not metres" in r["reason"]
    assert r["components"]["spatial"] < 0.8  # less certain than a calibrated measurement


def test_uncalibrated_rule_without_fallback_stays_inactive():
    r = near_rule(distance={"value": 2.0, "unit": "m"})
    sim = Sim([r], calibrated=False)
    assert sim.engine.rules == []
    assert "not calibrated" in sim.engine.inactive[0]["reason"]


def test_short_contact_is_not_an_association():
    sim = Sim([near_rule()])
    _person_to_car(sim, stay_s=2.0)
    for _ in range(30):  # walks away
        sim.step({1: ("person", 5.0, 30.0), 2: ("car", 22.0, 30.0)})
    sim.finish()
    assert sim.rels("ASSOCIATED_WITH") == []


def test_approach_needs_the_subjects_own_movement():
    approach = rule("rel_app", kind="pair", name="Approached", subject=PERSON, object=VEHICLE, condition="approaches",
                    distance={"value": 2.0, "unit": "m"}, from_distance={"value": 6.0, "unit": "m"})
    sim = Sim([approach])
    _person_to_car(sim, stay_s=1.0)
    sim.finish()
    rels = sim.rels("APPROACHED")
    assert len(rels) == 1 and rels[0]["metrics"]["subject_share"] > 0.9
    # a car driving up to a person standing still: the person did not approach
    sim2 = Sim([approach])
    for i in range(80):
        x = 40 - 19 * min(1.0, i / 60)
        sim2.step({1: ("person", 15.0, 30.0), 2: ("car", x, 30.0)})
    sim2.finish()
    assert sim2.rels("APPROACHED") == []


def test_entered_vehicle_and_frame_edge():
    entered = rule("rel_in", kind="pair", name="Entered vehicle", subject=PERSON, object=VEHICLE, condition="disappears_near", distance={"value": 1.5, "unit": "m"})
    sim = Sim([entered])
    _person_to_car(sim, stay_s=2.0)
    sim.step({2: ("car", 22.0, 30.0)}, ended=[1])
    for _ in range(5):
        sim.step({2: ("car", 22.0, 30.0)})
    sim.finish()
    r = sim.rels("ENTERED_VEHICLE")
    assert len(r) == 1 and not r[0]["metrics"]["at_frame_edge"]
    obs = [o for o in sim.out["observations"] if o["type"] == "disappeared"]
    assert r[0]["support"] == [obs[0]["uid"]]
    # the same at the picture's edge: kept, but less certain
    sim2 = Sim([entered])
    for i in range(40):
        sim2.step({1: ("person", 0.3 + i * 0.001, 30.0), 2: ("car", 1.5, 30.0)})
    sim2.step({2: ("car", 1.5, 30.0)}, ended=[1])
    sim2.finish()
    edge = sim2.rels("ENTERED_VEHICLE")
    assert len(edge) == 1 and edge[0]["metrics"]["at_frame_edge"] and edge[0]["confidence"] < r[0]["confidence"]


def test_walking_together_is_not_following():
    together = rule("rel_tw", kind="pair", name="Together", subject=PERSON, object=PERSON, condition="moves_together", distance={"value": 1.5, "unit": "m"}, for_s=4)
    follows = rule("rel_fo", kind="pair", name="Following", subject=PERSON, object=PERSON, condition="follows", distance={"value": 1.0, "unit": "m"},
                   for_s=4, lag_min_s=1.0, lag_max_s=8.0)
    # side by side
    sim = Sim([together, follows])
    for i in range(100):
        x = 2 + i * 0.12
        sim.step({1: ("person", x, 20.0), 2: ("person", x, 21.0)})
    sim.finish()
    assert len(sim.rels("TRAVELLED_WITH")) == 1  # symmetric: one relationship for the pair
    assert sim.rels("FOLLOWED") == []
    # one walking the same path 3 s behind the other
    sim2 = Sim([together, follows])
    for i in range(160):
        t = i / 10
        objs = {1: ("person", 2 + t * 1.2, 20.0 + 0.5 * (t > 6))}
        if t >= 3:
            tb = t - 3
            objs[2] = ("person", 2 + tb * 1.2, 20.0 + 0.5 * (tb > 6))
        sim2.step(objs)
    sim2.finish()
    f = sim2.rels("FOLLOWED")
    assert len(f) == 1 and f[0]["subject"] == E.track_key(1, 2, "person") and f[0]["object"] == E.track_key(1, 1, "person")
    assert 2.0 <= f[0]["metrics"]["mean_lag_s"] <= 4.0
    assert sim2.rels("TRAVELLED_WITH") == []


# ---------------------------------------------------------------------------- identities and places
def test_identity_resolution_keeps_tracks_and_hides_plates():
    res = FakeResolver()
    res.person(1, 1.0, "emp17")
    res.vehicle(2, 2.0, "ABC12345", vehicle_id="veh04", groups=["Delivery"])
    sim = Sim([near_rule(subject={"classes": ["person"], "subject": {"mode": "specific", "identity_ids": ["emp17"]}})], resolver=res)
    _person_to_car(sim)
    sim.finish()
    ident = sim.rels("IDENTIFIED_AS")
    assert len(ident) == 1 and ident[0]["subject"] == E.track_key(1, 1, "person") and ident[0]["object"] == "recognized_person:emp17"
    plate = sim.rels("IDENTIFIED_BY_PLATE")[0]
    assert plate["object"].startswith("license_plate:") and "ABC12345" not in plate["object"]
    reg = sim.rels("REGISTERED_AS")[0]
    assert reg["subject"] == plate["object"] and reg["object"] == "registered_vehicle:veh04" and reg["state"] == "confirmed"
    ents = {e["key"]: e for e in sim.out["entities"]}
    assert ents[plate["object"]]["secret_label"] == "ABC12345" and ents[plate["object"]]["label"] == "License plate"
    assert E.track_key(1, 1, "person") in ents  # the track is kept next to the identity
    a = sim.rels("ASSOCIATED_WITH")[0]
    assert a["components"]["recognition"] == pytest.approx(0.93)


def test_identity_rule_waits_for_recognition_and_drops_others():
    res = FakeResolver()
    res.person(1, 9.0, "emp99")  # recognized late, and as somebody else
    sim = Sim([near_rule(subject={"classes": ["person"], "subject": {"mode": "specific", "identity_ids": ["emp17"]}})], resolver=res)
    _person_to_car(sim, stay_s=10)
    sim.finish()
    assert sim.rels("ASSOCIATED_WITH") == []
    res2 = FakeResolver()
    res2.person(1, 13.0, "emp17")  # after the condition was met: it waits for the decision
    sim2 = Sim([near_rule(subject={"classes": ["person"], "subject": {"mode": "specific", "identity_ids": ["emp17"]}})], resolver=res2)
    _person_to_car(sim2, stay_s=10)
    sim2.finish()
    assert len(sim2.rels("ASSOCIATED_WITH")) == 1


def test_rule_needing_recognition_is_inactive_without_it():
    sim = Sim([near_rule(subject={"classes": ["person"], "subject": {"mode": "recognized"}})])
    assert sim.engine.rules == [] and "face recognition" in sim.engine.inactive[0]["reason"]


def test_place_relationships():
    objs = [zone("zA", "Parking", 0.0, 0.0, 0.5, 1.0), zone("zB", "Entrance", 0.5, 0.0, 1.0, 1.0)]
    sim = Sim([], settings={"remained_min_s": 3, "transition_s": 10}, objects=objs)
    sim.step({1: ("person", 10.0, 30.0)}, interactions=[Interaction("zone_entered", 1, "person", 0.0, 0, (0.2, 0.6), object_id="zA", object_type="zone", object_name="Parking")])
    for _ in range(50):
        sim.step({1: ("person", 10.0, 30.0)})
    t_exit = sim.t
    sim.step({1: ("person", 26.0, 30.0)}, interactions=[Interaction("zone_exited", 1, "person", t_exit, 0, (0.5, 0.6), object_id="zA", object_type="zone", dwell_s=t_exit)])
    sim.step({1: ("person", 27.0, 30.0)}, interactions=[Interaction("zone_entered", 1, "person", sim.t, 0, (0.55, 0.6), object_id="zB", object_type="zone")])
    sim.finish()
    types = sorted(r["type"] for r in sim.rels())
    assert types == ["ENTERED", "ENTERED", "EXITED", "MOVED_FROM", "MOVED_TO", "REMAINED_IN"]
    remained = sim.rels("REMAINED_IN")[0]
    assert remained["object"] == E.place_key(1, "zA", "zone") and remained["end_t"] == pytest.approx(t_exit)
    ents = {e["key"]: e for e in sim.out["entities"]}
    assert ents[E.place_key(1, "zA", "zone")]["label"] == "Parking"


def test_parked_in_zone():
    parked = rule("rel_park", kind="place", name="Parked", subject=VEHICLE, place_event="stops_in", for_s=5)
    sim = Sim([parked], objects=[zone("zP", "Parking 2", 0.0, 0.0, 0.6, 1.0)])
    for i in range(120):
        t = i / 10
        x = 40 - 25 * min(1.0, t / 4)  # drives in, then stands
        sim.step({1: ("car", x, 30.0)})
    sim.finish()
    p = sim.rels("PARKED_IN")
    assert len(p) == 1 and p[0]["object"] == E.place_key(1, "zP", "zone") and p[0]["start_t"] >= 3.5


# ---------------------------------------------------------------------------- correlation
def test_departed_with_vehicle_correlation():
    tpl = next(t for t in templates() if t["id"] == "departed_with")["definition"]
    rules = [
        near_rule(),
        rule("rel_in", kind="pair", name="Entered vehicle", subject=PERSON, object=VEHICLE, condition="disappears_near", distance={"value": 1.5, "unit": "m"}),
        rule("rel_dep", **tpl),
    ]
    sim = Sim(rules)
    _person_to_car(sim, stay_s=8)
    sim.step({2: ("car", 22.0, 30.0)}, ended=[1])
    for i in range(40):  # drives away and is gone
        sim.step({2: ("car", 22.0 + i * 0.5, 30.0)})
    sim.step({}, ended=[2])
    sim.finish()
    dep = sim.rels("DEPARTED_WITH")
    assert len(dep) == 1
    cor = sim.out["correlated"]
    assert len(cor) == 1 and cor[0]["label"] == "Departed with vehicle"
    assert cor[0]["roles"] == {"A": E.track_key(1, 1, "person"), "B": E.track_key(1, 2, "car")}
    assoc = sim.rels("ASSOCIATED_WITH")[0]
    entered = sim.rels("ENTERED_VEHICLE")[0]
    assert assoc["uid"] in cor[0]["support_relations"] and entered["uid"] in cor[0]["support_relations"]
    assert dep[0]["uid"] in cor[0]["support_relations"]
    assert cor[0]["temporal"]  # explicit order of the supporting facts
    # the lower-level relationships are still there
    assert assoc["status"] == "closed" and entered["status"] == "closed"


def test_follow_through_checkpoints():
    lines = [{"id": f"g{i}", "name": f"Gate {i}", "type": "line", "points": [{"x": 0.1 + 0.2 * i, "y": 0.1}, {"x": 0.1 + 0.2 * i, "y": 0.9}]} for i in range(4)]
    shared = rule("rel_shared", **next(t for t in templates() if t["id"] == "shared_route")["definition"])
    sim = Sim([shared], objects=lines)
    for i in range(4):
        t_a = 5.0 + 10 * i
        t_b = t_a + 4.0
        for tid, tt in ((1, t_a), (2, t_b)):
            while sim.t < tt - 1e-9:
                sim.step({1: ("person", 5.0, 20.0), 2: ("person", 3.0, 22.0)})
            sim.step({1: ("person", 5.0, 20.0), 2: ("person", 3.0, 22.0)},
                     interactions=[Interaction("line_crossed", tid, "person", sim.t, 0, (0.1, 0.5), object_id=f"g{i}", object_type="line", direction="forward")])
    sim.finish()
    f = sim.rels("FOLLOWED")
    assert len(f) == 1 and f[0]["subject"] == E.track_key(1, 2, "person") and len(f[0]["metrics"]["checkpoints"]) >= 3
    assert all(3.5 <= lag <= 4.5 for lag in f[0]["metrics"]["lags_s"])
    assert [c["label"] for c in sim.out["correlated"]] == ["Shared route movement"]


def test_has_relation_for_rule_clauses():
    sim = Sim([near_rule()])
    _person_to_car(sim)
    eng = sim.engine
    from pathscope.relationships.rules import RoleFilter

    assert eng.has_relation(2, "ASSOCIATED_WITH", other=RoleFilter(classes=["person"])) is True
    assert eng.has_relation(2, "ASSOCIATED_WITH", direction="outgoing") is False
    assert eng.has_relation(2, "NEAR") is False


def test_actions_only_at_the_required_state():
    sim = Sim([near_rule(actions=[{"kind": "record_event"}], act_min_state="confirmed", event_label="Beside the van")])
    _person_to_car(sim, stay_s=20)
    sim.finish()
    published = [r for r in sim.out["relationships"] if r.get("publish")]
    final = sim.rels("ASSOCIATED_WITH")[0]
    if final["state"] == "confirmed":
        assert len(published) == 1 and published[0]["publish"]["label"] == "Beside the van" and published[0]["state"] == "confirmed"
    else:
        assert published == []


# ---------------------------------------------------------------------------- rule builder clause
def test_rule_engine_has_relationship_clause():
    from relationship_scenes import scene

    from pathscope.domain.rules import Rule
    from pathscope.rules.engine import RuleEngine
    from pathscope.spatial.engine import SpatialEngine

    doc = scene(objects=[zone("zR", "Restricted Parking", 0.5, 0.0, 1.0, 1.0)])
    rule = Rule.model_validate({"name": "Van with employee", "classes": ["car"], "trigger": {"kind": "enters", "object_id": "zR"},
                                "relation": {"relation": "associated_with", "other_classes": ["person"]}, "record_as": "Restricted Vehicle Association"})
    assert rule.relation.relation == "ASSOCIATED_WITH"

    class Rel:
        def __init__(self, answer):
            self.answer, self.asked = answer, []

        def has_relation(self, track_id, relation, direction, other, places, min_state, recent_s):
            self.asked.append((track_id, relation, other.classes if other else None, min_state))
            return self.answer

    def run(answer, available=True):
        eng = RuleEngine(doc, [rule], SpatialEngine(doc, 1000, 1000), relations_available=available)
        if not available:
            return eng, []
        eng.relations = Rel(answer)
        ia = Interaction("zone_entered", 7, "car", 1.0, 1, (0.7, 0.5), object_id="zR", object_type="zone", object_name="Restricted Parking")
        return eng, [e for e in eng.process([ia], 1.0, 1) if e.rule_id == rule.id]

    eng, evs = run(True)
    assert [e.label for e in evs] == ["Restricted Vehicle Association"] and eng.relations.asked == [(7, "ASSOCIATED_WITH", ["person"], "likely")]
    assert run(False)[1] == []
    eng, _ = run(None, available=False)
    assert eng.rules == [] and eng.describe()["inactive_rules"][0]["needs"] == ["relationships"]


def test_has_relationship_waits_for_a_relationship_formed_a_moment_later():
    from relationship_scenes import scene

    from pathscope.domain.rules import Rule
    from pathscope.rules.engine import RuleEngine
    from pathscope.spatial.engine import SpatialEngine

    doc = scene(objects=[zone("zR", "Restricted", 0.5, 0.0, 1.0, 1.0)])
    rule = Rule.model_validate({"classes": ["person"], "trigger": {"kind": "enters", "object_id": "zR"}, "relation": {"relation": "FOLLOWED"}, "record_as": "Followed in"})

    class Late:
        answer = False

        def has_relation(self, *a, **k):
            return self.answer

    eng = RuleEngine(doc, [rule], SpatialEngine(doc, 1000, 1000), relations_available=True)
    eng.relations = Late()
    ia = Interaction("zone_entered", 3, "person", 1.0, 1, (0.7, 0.5), object_id="zR", object_type="zone")
    assert [e for e in eng.process([ia], 1.0, 1) if e.rule_id == rule.id] == []  # not yet
    eng.relations.answer = True  # formed on the next frame
    assert [e.label for e in eng.process([], 1.2, 2) if e.rule_id == rule.id] == ["Followed in"]
    # never forms: dropped after the grace period
    eng2 = RuleEngine(doc, [rule], SpatialEngine(doc, 1000, 1000), relations_available=True)
    eng2.relations = Late()
    eng2.process([ia], 1.0, 1)
    assert [e for e in eng2.process([], 7.0, 3) if e.rule_id == rule.id] == [] and eng2.pending_count() == 0
