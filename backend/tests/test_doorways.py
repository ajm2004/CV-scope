"""Doorway lines: objects that walk through a door the camera cannot see through.

The door frame hides a person from the side they walk into, so their box
shrinks to the part still in view: its bottom centre stops about half a body
width short of the line, and then the detections end. These tests move boxes
the way the Brio webcam runs of 2026-09-23 did (right edge held by the door
frame at x = 0.62, bottom centre last seen at x = 0.54 to 0.55).
"""

from __future__ import annotations

from pathscope.domain.rules import Rule, RuleStep, RuleTrigger
from pathscope.domain.scene import SceneDocument
from pathscope.rules.engine import RuleEngine
from pathscope.spatial.engine import SpatialEngine
from pathscope.vision.trackers.base import TrackerUpdate
from pathscope.vision.types import Track

W, H = 640, 480
FPS = 10.0
DOOR_X = 0.61


def scene(doorway: bool = True, direction: str = "forward") -> SceneDocument:
    return SceneDocument.model_validate({
        "frame_width": W,
        "frame_height": H,
        "objects": [
            # drawn bottom to top: forward points right, into the room behind the door frame
            {"id": "door", "type": "line", "name": "Bedroom", "points": [{"x": DOOR_X, "y": 0.85}, {"x": DOOR_X, "y": 0.40}],
             "direction": direction, "doorway": doorway},
            {"id": "hall", "type": "zone", "name": "Hall", "points": [{"x": 0.1, "y": 0.5}, {"x": 0.6, "y": 0.5}, {"x": 0.6, "y": 0.85}, {"x": 0.1, "y": 0.85}]},
        ],
    })


def box_track(tid: int, x1: float, x2: float, y: float, frame: int, hits: int = 20, updated: bool = True, state: str = "tracked") -> Track:
    t = frame / FPS
    return Track(track_id=tid, class_name="person", confidence=0.9, box=(x1 * W, 0.0, x2 * W, y * H), state=state, hits=hits, age=hits,
                 first_frame=0, last_frame=frame, first_time=0.0, last_time=t, mean_confidence=0.9, updated=updated)


class Sim:
    def __init__(self, doc: SceneDocument, rules: list[Rule] | None = None):
        self.spatial = SpatialEngine(doc, W, H, ["person"])
        self.rules = RuleEngine(doc, rules or [], self.spatial, ["person"])
        self.frame = 0
        self.events = []
        self.first: dict[int, float] = {}

    def step(self, tracks: list[Track], removed: list[Track] | None = None, started: list[Track] | None = None, reacquired: list[Track] | None = None):
        t = self.frame / FPS
        for tr in [*tracks, *(removed or [])]:
            tr.first_time = self.first.setdefault(tr.track_id, t)
        upd = TrackerUpdate(tracks=tracks, started=started or [], reacquired=reacquired or [], lost=[], removed=removed or [])
        interactions = self.spatial.update(upd, t, self.frame)
        self.events.extend(self.rules.process(interactions, t, self.frame, 1000.0 + t))
        self.frame += 1

    def idle(self, frames: int):
        for _ in range(frames):
            self.step([])

    def crossings(self):
        return [e for e in self.events if e.event_type == "crossing"]


def walk_into_door(sim: Sim, tid: int = 1) -> None:
    """Walk right towards the door frame, get hidden by it, disappear."""
    # a whole body in view, walking right (for over a second, as real walks do)
    for x in (0.18, 0.22, 0.26, 0.30, 0.34, 0.38, 0.42, 0.46):
        sim.step([box_track(tid, x - 0.08, x + 0.08, 0.62, sim.frame)])
    # the door frame at 0.62 hides the leading side: the box shrinks from the left
    for x1 in (0.44, 0.46, 0.48, 0.50):
        sim.step([box_track(tid, x1, 0.62, 0.61, sim.frame)])


def remove(sim: Sim, tid: int = 1, after: int = 30) -> None:
    sim.idle(after)
    sim.step([], removed=[box_track(tid, 0.5, 0.62, 0.61, sim.frame, updated=False, state="removed")])


def test_a_doorway_counts_someone_who_disappears_through_it():
    sim = Sim(scene())
    walk_into_door(sim)
    assert sim.crossings() == []  # the bottom centre (x 0.56) never reached the line
    remove(sim)
    [ev] = sim.crossings()
    assert (ev.object_id, ev.direction, ev.context.get("inferred")) == ("door", "forward", "disappeared")
    assert abs(ev.media_time_s - 1.1) < 1e-6  # dated when last seen, not when the tracker gave up


def test_an_ordinary_line_does_not():
    sim = Sim(scene(doorway=False))
    walk_into_door(sim)
    remove(sim)
    assert sim.crossings() == []


def test_a_sequence_rule_completes_through_a_doorway():
    rule = Rule(id="r", name="Bedroom visit", trigger=RuleTrigger(kind="enters", object_id="hall"),
                then=[RuleStep(kind="crosses", object_id="door", direction="forward", within_s=20.0)], record_as="Bedroom entered")
    sim = Sim(scene(), [rule])
    walk_into_door(sim)
    remove(sim)
    seq = [e for e in sim.events if e.event_type == "sequence"]
    assert len(seq) == 1 and seq[0].context.get("inferred") == "disappeared"


def test_no_count_for_someone_who_stops_at_the_door_or_walks_along_it():
    sim = Sim(scene())
    for _ in range(12):  # standing in the doorway, half hidden
        sim.step([box_track(1, 0.50, 0.62, 0.61, sim.frame)])
    remove(sim)
    for y in (0.80, 0.75, 0.70, 0.65, 0.60, 0.55, 0.50):  # walking along the door frame, not into it
        sim.step([box_track(2, 0.48, 0.60, y, sim.frame)])
    remove(sim, tid=2)
    assert sim.crossings() == []


def test_a_brief_false_detection_at_the_door_does_not_count():
    # Run 9, 2026-09-23: three frames of a "person" on the curtain beside the
    # bathroom door, drifting towards the line, while the real person walked past.
    sim = Sim(scene(direction="both"))
    for x1 in (0.50, 0.51, 0.52):
        sim.step([box_track(1, x1, 0.62, 0.61, sim.frame)])
    remove(sim)
    for x1 in (0.52, 0.51, 0.50):  # nor a flicker that appears there and moves away
        sim.step([box_track(2, x1 - 0.04, 0.62, 0.61, sim.frame)])
    remove(sim, tid=2)
    assert sim.crossings() == []


def test_no_count_when_the_object_disappears_away_from_the_door():
    sim = Sim(scene())
    for x in (0.30, 0.32, 0.34, 0.36, 0.38):
        sim.step([box_track(1, x - 0.08, x + 0.08, 0.62, sim.frame)])
    remove(sim)
    assert sim.crossings() == []


def test_a_crossing_seen_in_full_is_not_counted_again_when_the_object_disappears():
    sim = Sim(scene())
    for x in (0.50, 0.55, 0.60, 0.65, 0.70):  # the bottom centre itself crosses the line
        sim.step([box_track(1, x - 0.06, x + 0.06, 0.62, sim.frame)])
    remove(sim)
    [ev] = sim.crossings()
    assert ev.context.get("inferred") is None


def test_someone_coming_out_of_the_door_counts_in_reverse():
    sim = Sim(scene(direction="both"))
    for i, x1 in enumerate((0.50, 0.48, 0.46, 0.44, 0.42, 0.40, 0.38, 0.36, 0.34, 0.32, 0.30, 0.28)):  # appears at the door frame, walks left
        x2 = 0.62 if i < 3 else x1 + 0.16
        sim.step([box_track(1, x1, x2, 0.62, sim.frame)])
    [ev] = sim.crossings()
    assert (ev.direction, ev.context.get("inferred"), ev.media_time_s) == ("reverse", "appeared", 0.0)


def test_someone_appearing_at_the_door_and_walking_into_it_is_not_coming_out():
    sim = Sim(scene(direction="both"))
    for x1 in (0.31, 0.33, 0.35, 0.37, 0.39, 0.41, 0.43, 0.45, 0.47, 0.49, 0.51, 0.53):
        sim.step([box_track(1, x1, 0.62, 0.62, sim.frame)])
    remove(sim)
    [ev] = sim.crossings()  # only the disappearance
    assert (ev.direction, ev.context.get("inferred")) == ("forward", "disappeared")


def test_a_passage_split_over_two_tracks_counts_once():
    sim = Sim(scene(direction="both"))
    walk_into_door(sim, tid=1)  # lost at the door ...
    for x1 in (0.61, 0.63, 0.65, 0.67, 0.69, 0.71, 0.73, 0.75, 0.77, 0.79, 0.81):  # ... and found again beyond it as a new track
        sim.step([box_track(2, x1, x1 + 0.12, 0.62, sim.frame)])
    remove(sim, tid=1)
    evs = sim.crossings()
    assert [(e.track_id, e.direction) for e in evs] == [(2, "forward")]


def test_out_of_view_behind_the_door_and_back_counts_both_ways():
    sim = Sim(scene(direction="both"))
    walk_into_door(sim)
    sim.idle(20)  # two seconds in the room, the tracker keeps the track
    back = [box_track(1, 0.50, 0.62, 0.61, sim.frame)]
    sim.step(back, reacquired=back)
    for x1 in (0.48, 0.46, 0.44, 0.42, 0.40, 0.38, 0.36, 0.34, 0.32, 0.30, 0.28):
        sim.step([box_track(1, x1, 0.62 if x1 > 0.44 else x1 + 0.16, 0.62, sim.frame)])
    assert [(e.direction, e.context.get("inferred")) for e in sim.crossings()] == [("forward", "disappeared"), ("reverse", "appeared")]


def test_a_new_tracks_first_movement_counts_only_from_the_minimum_track_age():
    doc = SceneDocument.model_validate({
        "frame_width": W, "frame_height": H,
        "objects": [{"id": "l", "type": "line", "name": "Bottom", "points": [{"x": 0.0, "y": 0.87}, {"x": 1.0, "y": 0.87}], "min_track_age": 3}],
    })
    sim = Sim(doc)
    # someone stepping in from under the camera: first only an arm (box bottom 0.66), then the legs
    sim.step([box_track(1, 0.0, 0.30, 0.66, sim.frame, hits=2)])
    sim.step([box_track(1, 0.0, 0.30, 0.94, sim.frame, hits=3)])
    sim.step([box_track(1, 0.0, 0.30, 0.99, sim.frame, hits=4)])
    assert sim.crossings() == []
    # an established track still counts
    sim.step([box_track(2, 0.4, 0.5, 0.80, sim.frame, hits=5)])
    sim.step([box_track(2, 0.4, 0.5, 0.90, sim.frame, hits=6)])
    assert [e.track_id for e in sim.crossings()] == [2]
