"""Spatial + rule engine behaviour with synthetic tracks (no detector needed)."""

from __future__ import annotations

from pathscope.domain.rules import Rule, RuleAction, RuleStep, RuleTrigger
from pathscope.domain.scene import SceneDocument
from pathscope.rules.engine import ROUTE_ABANDONED, ROUTE_LOST, ROUTE_UNKNOWN, RuleEngine
from pathscope.spatial.engine import SpatialEngine
from pathscope.vision.trackers.base import TrackerUpdate
from pathscope.vision.types import Detection, Track

W, H = 1000, 500
FPS = 10.0


def make_scene(**overrides) -> SceneDocument:
    doc = {
        "frame_width": W,
        "frame_height": H,
        "objects": [
            {"id": "entrance", "type": "gate", "name": "Entrance", "points": [{"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 1.0}], "classes": ["person"]},
            {"id": "exit_a", "type": "gate", "name": "Exit A", "points": [{"x": 0.1, "y": 0.0}, {"x": 0.1, "y": 1.0}], "classes": ["person"]},
            {"id": "exit_b", "type": "gate", "name": "Exit B", "points": [{"x": 0.9, "y": 0.0}, {"x": 0.9, "y": 1.0}], "classes": ["person"]},
            {"id": "cp_a", "type": "checkpoint", "name": "CP A", "points": [{"x": 0.25, "y": 0.3}, {"x": 0.35, "y": 0.3}, {"x": 0.35, "y": 0.7}, {"x": 0.25, "y": 0.7}], "classes": ["person"]},
            {"id": "wait", "type": "zone", "name": "Waiting", "points": [{"x": 0.6, "y": 0.1}, {"x": 0.8, "y": 0.1}, {"x": 0.8, "y": 0.9}, {"x": 0.6, "y": 0.9}], "classes": ["person"]},
            {"id": "ign", "type": "ignore", "name": "Ignore", "points": [{"x": 0.0, "y": 0.0}, {"x": 0.05, "y": 0.0}, {"x": 0.05, "y": 0.05}, {"x": 0.0, "y": 0.05}]},
        ],
        "routes": [
            {"id": "ra", "name": "Route A", "start": "entrance", "sequence": ["cp_a"], "end": "exit_a", "timeout_s": 5.0, "strict_sequence": True},
            {"id": "rb", "name": "Route B", "start": "entrance", "sequence": [], "end": "exit_b", "timeout_s": 5.0},
        ],
    }
    doc.update(overrides)
    return SceneDocument.model_validate(doc)


def track(tid: int, x: float, y: float, frame: int, t: float, cls: str = "person") -> Track:
    px, py = x * W, y * H
    return Track(track_id=tid, class_name=cls, confidence=0.9, box=(px - 20, py - 60, px + 20, py), state="tracked", hits=50, age=50,
                 first_frame=0, last_frame=frame, first_time=0.0, last_time=t, mean_confidence=0.9)


class Sim:
    def __init__(self, scene: SceneDocument, rules: list[Rule] | None = None):
        self.spatial = SpatialEngine(scene, W, H, ["person"])
        self.rules = RuleEngine(scene, rules or [], self.spatial, ["person"])
        self.frame = 0
        self.events = []

    def step(self, positions: dict[int, tuple[float, float]], removed: list[int] | None = None, dt: float = 1.0 / FPS):
        t = self.frame / FPS
        tracks = [track(tid, x, y, self.frame, t) for tid, (x, y) in positions.items()]
        rem = [track(tid, 0.5, 0.5, self.frame, t) for tid in (removed or [])]
        upd = TrackerUpdate(tracks=tracks, started=[], reacquired=[], lost=[], removed=rem)
        interactions = self.spatial.update(upd, t, self.frame)
        evs = self.rules.process(interactions, t, self.frame, 1000.0 + t)
        self.events.extend(evs)
        self.frame += 1
        return evs

    def walk(self, tid: int, path: list[tuple[float, float]]):
        for p in path:
            self.step({tid: p})

    def idle(self, seconds: float, positions: dict[int, tuple[float, float]] | None = None):
        for _ in range(int(seconds * FPS)):
            self.step(positions or {})

    def route_events(self):
        return [e for e in self.events if e.event_type == "route"]


def straight(x0: float, x1: float, y: float, n: int = 20):
    return [(x0 + (x1 - x0) * i / (n - 1), y) for i in range(n)]


def test_route_b_completed_and_counted():
    sim = Sim(make_scene())
    sim.walk(1, straight(0.45, 0.95, 0.5))
    routes = sim.route_events()
    assert len(routes) == 1
    ev = routes[0]
    assert ev.route == "Route B" and ev.track_id == 1
    assert ev.entered_at_s is not None and ev.completed_at_s is not None and ev.duration_s > 0
    assert ev.context["start_object"] == "entrance" and ev.context["end_object"] == "exit_b"
    counters = {c["label"]: c["value"] for c in sim.rules.counters_list()}
    assert counters["Route B"] == 1 and counters["Entrance forward"] + counters["Entrance reverse"] == 1
    crossings = [e for e in sim.events if e.event_type == "crossing"]
    assert {e.object_name for e in crossings} == {"Entrance", "Exit B"}


def test_route_a_requires_checkpoint_when_strict():
    sim = Sim(make_scene())
    # Straight to Exit A along y=0.9: misses the checkpoint polygon (y 0.3..0.7)
    sim.walk(1, straight(0.55, 0.05, 0.9))
    ev = sim.route_events()[0]
    assert ev.route == ROUTE_UNKNOWN
    assert ev.context["reason"] == "checkpoints_missing" and "Route A" in ev.context["reached_end_of"]

    sim2 = Sim(make_scene())
    sim2.walk(2, straight(0.55, 0.05, 0.5))  # passes through the checkpoint
    ev2 = sim2.route_events()[0]
    assert ev2.route == "Route A" and ev2.context["checkpoints"] == ["cp_a", "exit_a"]
    assert ev2.context["decision_time_s"] > 0


def test_route_abandoned_on_timeout_and_lost_track():
    sim = Sim(make_scene())
    sim.walk(1, straight(0.45, 0.55, 0.5, n=5))  # crosses the entrance, then lingers
    sim.idle(6.0, {1: (0.55, 0.5)})
    ev = sim.route_events()[0]
    assert ev.route == ROUTE_ABANDONED and ev.context["group"] == "Entrance"

    sim2 = Sim(make_scene())
    sim2.walk(2, straight(0.45, 0.55, 0.5, n=5))
    sim2.step({}, removed=[2])
    ev2 = sim2.route_events()[0]
    assert ev2.route == ROUTE_LOST


def test_previous_route_and_occupancy_context():
    sim = Sim(make_scene())
    sim.walk(1, straight(0.45, 0.95, 0.5))
    sim.walk(2, straight(0.45, 0.55, 0.5, n=3))  # track 2 starts and stays in progress
    sim.walk(3, straight(0.45, 0.95, 0.5))
    evs = sim.route_events()
    third = [e for e in evs if e.track_id == 3][0]
    assert third.context["previous_route"] == "Route B"
    assert third.context["occupancy_at_decision"] == 1  # track 2 was in progress


def test_zone_entry_exit_and_dwell_rule():
    rule = Rule(name="Long wait", classes=["person"], trigger=RuleTrigger(kind="enters", object_id="wait"), remains_for_s=1.0, record_as="Long wait",
                actions=[RuleAction(kind="count"), RuleAction(kind="record_event")])
    sim = Sim(make_scene(), [rule])
    sim.step({1: (0.55, 0.5)})
    sim.idle(2.0, {1: (0.7, 0.5)})  # inside the zone for 2 s
    sim.idle(0.6, {1: (0.85, 0.5)})  # leaves, for longer than the zone's 0.5 s allowance
    types = [e.event_type for e in sim.events]
    assert "zone_entry" in types and "zone_exit" in types and "dwell" in types
    exit_ev = [e for e in sim.events if e.event_type == "zone_exit"][0]
    assert 1.8 <= exit_ev.duration_s <= 2.3
    dwell = [e for e in sim.events if e.event_type == "dwell"][0]
    assert dwell.label == "Long wait" and dwell.duration_s >= 1.0
    assert {c["label"]: c["value"] for c in sim.rules.counters_list()}["Long wait"] == 1


def test_explicit_sequence_rule_with_deadline():
    rule = Rule(name="Fast B", classes=["person"], trigger=RuleTrigger(kind="crosses", object_id="entrance"),
                then=[RuleStep(kind="crosses", object_id="exit_b", within_s=1.0)], record_as="Fast to B")
    sim = Sim(make_scene(), [rule])
    sim.walk(1, straight(0.45, 0.95, 0.5, n=8))  # 0.8 s: within the deadline
    seq = [e for e in sim.events if e.event_type == "sequence"]
    assert len(seq) == 1 and seq[0].route == "Fast to B"
    sim2 = Sim(make_scene(), [rule])
    sim2.walk(2, straight(0.45, 0.95, 0.5, n=30))  # 3 s: too slow
    assert not [e for e in sim2.events if e.event_type == "sequence"]
    assert sim2.rules.stats["sequence_expired"] == 1


def test_ignore_region_filters_detections():
    spatial = SpatialEngine(make_scene(), W, H, ["person"])
    inside = Detection("person", 0.9, (10, 10, 30, 20))  # bottom-centre (20, 20) -> (0.02, 0.04): inside ignore
    outside = Detection("person", 0.9, (500, 200, 540, 300))
    kept = spatial.filter_detections([inside, outside])
    assert kept == [outside]


def test_line_direction_filter_and_debounce():
    scene = make_scene(objects=[{"id": "l", "type": "line", "name": "L", "points": [{"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 1.0}], "classes": ["person"], "direction": "forward", "debounce_s": 1.0}], routes=[])
    sim = Sim(scene)
    sim.walk(1, straight(0.45, 0.55, 0.5, n=3))
    sim.walk(1, straight(0.55, 0.45, 0.5, n=3))
    crossings = [e for e in sim.events if e.event_type == "crossing"]
    # One direction is filtered out; within debounce the second crossing in the allowed direction is also suppressed
    assert len(crossings) <= 1
    for e in crossings:
        assert e.direction == "forward"


def test_person_at_the_bottom_edge_counts_inside_a_full_frame_zone():
    """A webcam at a desk sees a seated person whose box ends at the frame bottom."""
    scene = make_scene(objects=[{"id": "desk", "type": "zone", "name": "Desk", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}], "classes": ["person"], "min_dwell_s": 0.5}], routes=[])
    sim = Sim(scene)
    sim.idle(2.0, {1: (0.5, 1.0)})  # bottom-centre exactly on the bottom edge
    assert [e.event_type for e in sim.events].count("zone_entry") == 1


# The zone of a user's room camera, drawn by hand before corners snapped to the
# frame border: it stops 1 to 6 pixels short of every edge of a 640 x 480 picture.
HAND_DRAWN_ROOM = [
    {"x": 0.004651162790697674, "y": 0.0069767441860465115},
    {"x": 0.9930232558139535, "y": 0.0007751937984496124},
    {"x": 0.9906976744186047, "y": 0.9930232558139535},
    {"x": 0.004651162790697674, "y": 0.9961240310077519},
]


def room_zone(**fields) -> dict:
    return {"id": "room", "type": "zone", "name": "Room", "points": HAND_DRAWN_ROOM, "classes": ["person"], **fields}


def test_a_zone_drawn_a_few_pixels_short_of_the_frame_edge_reaches_it():
    """People close to the camera are cut off by the frame: their feet are on the bottom edge."""
    sim = Sim(make_scene(objects=[room_zone(min_dwell_s=0.5)], routes=[]))
    sim.idle(3.0, {1: (0.7, 1.0)})
    sim.step({}, removed=[1])
    types = [e.event_type for e in sim.events]
    assert types.count("zone_entry") == 1 and types.count("zone_exit") == 1
    assert 2.8 <= next(e for e in sim.events if e.event_type == "zone_exit").duration_s <= 3.0


def test_a_thin_zone_along_the_edge_is_not_collapsed():
    strip = [{"x": 0.2, "y": 0.992}, {"x": 0.8, "y": 0.992}, {"x": 0.8, "y": 0.999}, {"x": 0.2, "y": 0.999}]
    sim = Sim(make_scene(objects=[{"id": "s", "type": "zone", "name": "Strip", "points": strip, "classes": ["person"]}], routes=[]))
    sim.idle(1.0, {1: (0.5, 0.995)})
    assert [e.event_type for e in sim.events].count("zone_entry") == 1


def test_short_exits_from_a_zone_keep_one_visit():
    """Standing on the edge of a zone: out for a few frames, back in, several times."""
    square = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
    sim = Sim(make_scene(objects=[{"id": "z", "type": "zone", "name": "Z", "points": square, "classes": ["person"], "debounce_s": 1.0}], routes=[]))
    for _ in range(4):
        sim.idle(1.0, {1: (0.5, 0.79)})  # inside
        sim.idle(0.3, {1: (0.5, 0.81)})  # just outside
    sim.idle(2.0, {1: (0.5, 0.95)})  # stays out: the last exit, at 4.9 s, is final
    exits = [e for e in sim.events if e.event_type == "zone_exit"]
    assert [e.event_type for e in sim.events].count("zone_entry") == 1 and len(exits) == 1
    # the visit ends when the object left, not when the allowance ran out
    assert abs(exits[0].media_time_s - 4.9) < 0.11 and abs(exits[0].duration_s - 4.9) < 0.11
    assert exits[0].context["reason"] == "left_zone"


def test_an_exit_longer_than_the_allowance_ends_the_visit():
    square = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
    sim = Sim(make_scene(objects=[{"id": "z", "type": "zone", "name": "Z", "points": square, "classes": ["person"], "debounce_s": 0.5}], routes=[]))
    sim.idle(1.0, {1: (0.5, 0.5)})
    sim.idle(1.0, {1: (0.5, 0.9)})  # out for 1 s
    sim.idle(1.0, {1: (0.5, 0.5)})  # a second visit
    sim.idle(1.0, {1: (0.5, 0.9)})
    exits = [e for e in sim.events if e.event_type == "zone_exit"]
    assert [e.event_type for e in sim.events].count("zone_entry") == 2 and len(exits) == 2
    assert [round(e.duration_s, 1) for e in exits] == [1.0, 1.0]


def test_short_exits_do_not_restart_the_minimum_visit():
    square = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
    sim = Sim(make_scene(objects=[{"id": "z", "type": "zone", "name": "Z", "points": square, "classes": ["person"], "min_dwell_s": 2.0, "debounce_s": 1.0}], routes=[]))
    for _ in range(3):
        sim.idle(0.8, {1: (0.5, 0.79)})
        sim.idle(0.2, {1: (0.5, 0.81)})
    entries = [e for e in sim.events if e.event_type == "zone_entry"]
    assert len(entries) == 1 and entries[0].media_time_s == 0.0


def test_a_track_given_up_after_stepping_out_ends_its_visit_when_it_left():
    square = [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]
    rule = Rule(name="Long", classes=["person"], trigger=RuleTrigger(kind="enters", object_id="z"), remains_for_s=2.5, record_as="Long")
    sim = Sim(make_scene(objects=[{"id": "z", "type": "zone", "name": "Z", "points": square, "classes": ["person"], "debounce_s": 3.0}], routes=[]), [rule])
    sim.idle(2.0, {1: (0.5, 0.5)})
    sim.idle(1.0, {1: (0.5, 0.9)})  # steps out at 2.0 s, within the allowance
    assert [e for e in sim.events if e.event_type == "dwell"] == []  # time outside does not count
    sim.step({}, removed=[1])
    exit_ev = next(e for e in sim.events if e.event_type == "zone_exit")
    assert abs(exit_ev.media_time_s - 2.0) < 1e-6 and abs(exit_ev.duration_s - 2.0) < 1e-6
    assert exit_ev.context["reason"] == "left_zone"


def test_stopping_a_run_records_the_open_visit():
    scene = make_scene(objects=[{"id": "desk", "type": "zone", "name": "Desk", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}], "classes": ["person"]}], routes=[])
    sim = Sim(scene)
    sim.idle(3.0, {1: (0.5, 0.9)})
    t_last = (sim.frame - 1) / FPS
    live = [track(1, 0.5, 0.9, sim.frame - 1, t_last)]
    interactions = sim.spatial.end_tracks(live, sim.frame, reason="run_ended")
    events = sim.rules.process(interactions, t_last, sim.frame, 5000.0)
    exits = [e for e in events if e.event_type == "zone_exit"]
    assert len(exits) == 1
    assert exits[0].context["reason"] == "run_ended"
    assert 2.7 <= exits[0].duration_s <= 3.0


def test_a_dwell_rule_counts_only_until_the_object_was_last_seen():
    scene = make_scene(objects=[{"id": "desk", "type": "zone", "name": "Desk", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}], "classes": ["person"]}], routes=[])
    rule = Rule(name="Long", classes=["person"], trigger=RuleTrigger(kind="enters", object_id="desk"), remains_for_s=5.0, record_as="Long")
    sim = Sim(scene, [rule])
    sim.idle(3.0, {1: (0.5, 0.9)})  # seen for 3 s
    sim.idle(4.0, {})  # out of view, not yet given up by the tracker
    assert [e for e in sim.events if e.event_type == "dwell"] == []
    assert abs(sim.spatial.dwell_time("desk", 1, sim.frame / FPS) - 2.9) < 0.11
    sim.idle(1.0, {1: (0.5, 0.9)})  # back again: the time in between counts
    dwell = [e for e in sim.events if e.event_type == "dwell"]
    assert len(dwell) == 1 and dwell[0].label == "Long"


def test_a_sequence_whose_object_leaves_the_view_is_counted():
    rule = Rule(name="seq", classes=["person"], trigger=RuleTrigger(kind="crosses", object_id="entrance"),
                then=[RuleStep(kind="crosses", object_id="exit_b", within_s=20)], record_as="B")
    sim = Sim(make_scene(), [rule])
    sim.step({1: (0.45, 0.5)})
    sim.step({1: (0.55, 0.5)})  # crosses the entrance: the sequence starts
    sim.step({}, removed=[1])  # the person leaves the view before the exit
    assert sim.rules.stats["sequence_track_lost"] == 1
    assert sim.rules.stats["sequence_expired"] == 0


def test_lost_and_reacquired_counts_only_tracks_found_again():
    sp = SpatialEngine(make_scene(objects=[], routes=[]), W, H, ["person"])
    t0 = track(1, 0.5, 0.5, 0, 0.0)
    sp.update(TrackerUpdate(tracks=[t0], started=[t0], reacquired=[], lost=[], removed=[]), 0.0, 0)
    back = track(1, 0.5, 0.5, 5, 0.5)
    sp.update(TrackerUpdate(tracks=[back], started=[], reacquired=[back], lost=[], removed=[]), 0.5, 5)
    gone = track(1, 0.5, 0.5, 9, 0.9)
    gone.lost_count = 2  # the tracker also counts the final loss
    sp.update(TrackerUpdate(tracks=[], started=[], reacquired=[], lost=[], removed=[gone]), 1.2, 12)
    assert sp.records[1].lost_count == 1


def test_event_wall_time_is_the_time_of_the_observation():
    scene = make_scene(objects=[{"id": "desk", "type": "zone", "name": "Desk", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}], "classes": ["person"]}], routes=[])
    sim = Sim(scene)
    sim.idle(2.0, {1: (0.5, 0.9)})
    live = [track(1, 0.5, 0.9, sim.frame - 1, 1.9)]
    # the run stops 6 s after the object was last seen (lost-track buffer)
    events = sim.rules.process(sim.spatial.end_tracks(live, sim.frame, reason="run_ended"), 7.9, sim.frame, 10_000.0)
    exit_ev = next(e for e in events if e.event_type == "zone_exit")
    assert abs(exit_ev.wall_time - (10_000.0 - 6.0)) < 1e-6


def test_zone_summary_totals_and_occupied_time():
    from datetime import UTC, datetime

    from pathscope.analytics.aggregation import zone_summary
    from pathscope.db.models import Event

    base = datetime(2026, 9, 22, 9, 50, tzinfo=UTC).timestamp()

    def exit_event(start, end, track):
        return Event(event_type="zone_exit", object_id="desk", object_name="Desk", track_id=track, object_class="person",
                     media_time_s=end, completed_at_s=end, entered_at_s=start, duration_s=end - start,
                     wall_time=datetime.fromtimestamp(base + end, tz=UTC), context={})

    # two people overlap for 5 min; a third visit crosses the 10:00 hour boundary
    events = [exit_event(0, 600, 1), exit_event(300, 900, 2), exit_event(1200, 1500, 3)]
    z = zone_summary(events)[0]
    assert z["exits"] == 3
    assert z["total_dwell_s"] == 1500.0  # 600 + 600 + 300 seconds summed over visits
    assert z["occupied_s"] == 1200.0  # 0-900 and 1200-1500: time with anyone inside
    hours = {h["hour"][11:16]: h["seconds"] for h in z["occupied_by_hour"]}
    assert hours == {"09:00": 600.0, "10:00": 600.0}


def test_occupied_time_adds_up_over_runs_and_clock_hours_come_from_live_runs():
    from datetime import UTC, datetime

    from pathscope.analytics.aggregation import zone_summary
    from pathscope.db.models import Event

    day1 = datetime(2026, 9, 21, 20, 0, tzinfo=UTC).timestamp()
    day2 = datetime(2026, 9, 22, 20, 0, tzinfo=UTC).timestamp()

    def visit(run_id, start, end, wall0):
        return Event(event_type="zone_exit", run_id=run_id, object_id="desk", object_name="Desk", track_id=1, object_class="person",
                     media_time_s=end, completed_at_s=end, entered_at_s=start, duration_s=end - start,
                     wall_time=datetime.fromtimestamp(wall0 + end, tz=UTC), context={})

    # Media time restarts at 0 in each run: both evenings have a 0-1800 s visit.
    events = [visit(1, 0, 1800, day1), visit(2, 0, 1800, day2), visit(3, 0, 600, day2)]
    z = zone_summary(events, live_run_ids={1, 2})[0]
    assert z["occupied_s"] == 4200.0  # 1800 + 1800 + 600: not merged across runs
    by_hour = {h["hour"][:13]: h["seconds"] for h in z["occupied_by_hour"]}
    assert by_hour == {"2026-09-21T20": 1800.0, "2026-09-22T20": 1800.0}  # run 3 is a recorded video
