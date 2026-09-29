"""Spatial engine: converts track movement into geometric interactions.

The engine knows lines, polygons and calibration. It emits interactions such
as ``line_crossed`` or ``zone_entered`` and keeps per-track trajectories; it
assigns no research meaning to any of them (that is the rule engine's job).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathscope.domain.scene import LineObject, SceneDocument, ZoneObject
from pathscope.spatial.calibration import GroundMapper
from pathscope.spatial.geometry import (
    forward_normal,
    point_in_polygon,
    polygon_area,
    segment_crossing,
    segment_distance,
    side_of_line,
)
from pathscope.vision.trackers.base import TrackerUpdate
from pathscope.vision.types import Detection, Track, TrackPoint


@dataclass(slots=True)
class Interaction:
    # line_crossed | zone_entered | zone_exited | track_started | track_lost |
    # track_reacquired | track_ended
    kind: str
    track_id: int
    class_name: str
    t: float
    frame_index: int
    position: tuple[float, float]
    object_id: str | None = None
    object_type: str | None = None
    object_name: str | None = None
    direction: str | None = None
    dwell_s: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class TrackRecord:
    track_id: int
    class_name: str
    first_t: float
    first_frame: int
    last_t: float
    last_frame: int
    n_frames: int = 0
    points: list[TrackPoint] = field(default_factory=list)
    conf_sum: float = 0.0
    lost_count: int = 0
    final_state: str = "tracked"

    @property
    def mean_confidence(self) -> float:
        return self.conf_sum / max(self.n_frames, 1)


@dataclass(slots=True)
class _Visit:
    """One object's stay in one zone.

    ``out_since`` is set while the object is outside the zone but may still come
    back within the zone's allowance (its ``debounce_s``)."""

    enter_t: float
    announced: bool = False
    out_since: float | None = None
    out_frame: int = 0
    out_pos: tuple[float, float] = (0.0, 0.0)


@dataclass(slots=True)
class _Seen:
    """One observation of a track: its ground point and its footprint (the
    bottom edge of its box, left and right end), normalized."""

    t: float
    frame: int
    pos: tuple[float, float]
    foot: tuple[tuple[float, float], tuple[float, float]]


_EDGE = 1.0 - 1e-6
# Polygon corners this close to the frame border count as on it, as the Scene
# Builder snaps them. A zone that stops a few pixels short of the bottom edge
# would otherwise miss every person the frame cuts off: their feet are on it.
_EDGE_SNAP = 0.012

# Doorway lines. Someone walking through a door the camera cannot see through
# is hidden by the door frame from the side they walk into: their box shrinks
# to the part still in view, so its bottom centre stops short of the line
# (half a body width) and then the detections end. A doorway passage is
# counted from the footprint instead: it must reach the line (distances are
# fractions of the longer frame side) ...
_DOOR_REACH = 0.025
# ... with the ground point moving across the line, towards it when the object
# disappears and away from it when it appears, by this much within a second.
_DOOR_MIN_MOVE = 0.01
_DOOR_WINDOW_S = 1.0
# Only a track seen this long (and this often) tells a passage: a detector
# flicker on a curtain or a door leaf next to the line lives a few frames.
_DOOR_MIN_SEEN_S = 1.0
_DOOR_MIN_FRAMES = 5
# A new track that has not moved away from the doorway by then did not come
# through it.
_DOOR_APPEAR_S = 2.0
# A track found again after at least this long out of view may have gone
# through a doorway and come back.
_DOOR_GAP_S = 1.0
# A passage counted by one track is not counted again by a new track of the
# same object (the tracker lost it at the door and started another).
_DOOR_SAME_OBJECT_S = 2.0
_DOOR_LOG_S = 10.0


def _snap_to_frame(poly: list[tuple[float, float]]) -> list[tuple[float, float]]:
    def snap(v: float) -> float:
        if 0.0 < v < _EDGE_SNAP:
            return 0.0
        if 1.0 - _EDGE_SNAP < v < 1.0:
            return 1.0
        return v

    snapped = [(snap(x), snap(y)) for x, y in poly]
    # A thin strip along an edge would collapse: keep it as drawn.
    return snapped if polygon_area(snapped) >= 0.5 * polygon_area(poly) else poly


class SpatialEngine:
    def __init__(
        self,
        scene: SceneDocument,
        frame_width: int,
        frame_height: int,
        tracked_classes: list[str] | None = None,
        trajectory_sample_s: float = 0.1,
    ) -> None:
        self.scene = scene
        self.width = frame_width
        self.height = frame_height
        self.tracked_classes = set(tracked_classes or [])
        self.sample_interval = trajectory_sample_s
        self.mapper = GroundMapper.from_calibration(scene.calibration, frame_width, frame_height)

        self.lines: list[LineObject] = [o for o in scene.lines() if o.enabled]
        self.zones: list[ZoneObject] = [o for o in scene.zones() if o.enabled and o.type != "ignore"]
        self.ignore: list[ZoneObject] = scene.ignore_regions()
        self._line_pts = {ln.id: ((ln.points[0].x, ln.points[0].y), (ln.points[1].x, ln.points[1].y)) for ln in self.lines}
        self._zone_polys = {z.id: _snap_to_frame([(p.x, p.y) for p in z.points]) for z in self.zones}
        self._ignore_polys = [_snap_to_frame([(p.x, p.y) for p in z.points]) for z in self.ignore]

        self._last_pos: dict[int, tuple[float, float]] = {}
        self._last_hits: dict[int, int] = {}  # track hits when _last_pos was observed
        self._presence: dict[tuple[str, int], _Visit] = {}  # (zone_id, track_id)
        self._last_cross: dict[tuple[str, int], float] = {}
        self._last_cross_any: dict[str, float] = {}
        self.records: dict[int, TrackRecord] = {}
        self.max_occupancy: dict[str, int] = {z.id: 0 for z in self.zones}

        self._doorways: list[LineObject] = [ln for ln in self.lines if ln.doorway]
        side = float(max(frame_width, frame_height))
        self._iso_scale = (frame_width / side, frame_height / side)
        self._seen: dict[int, _Seen] = {}  # last observation of each track
        # (line_id, track_id) -> where a track appeared at a doorway, until it moves away
        self._appear: dict[tuple[str, int], _Seen] = {}
        # line_id -> counted crossings (t, direction, track_id, track first_t)
        self._door_log: dict[str, list[tuple[float, str, int, float]]] = {ln.id: [] for ln in self._doorways}

    # ------------------------------------------------------------------ helpers
    def normalize(self, x_px: float, y_px: float) -> tuple[float, float]:
        # Pixels run from 0 to width/height *exclusive*: a box clipped by the frame
        # (a person sitting in front of a webcam) has its bottom exactly at the
        # height. Keep ground points strictly inside [0, 1) so a zone drawn to the
        # frame edge contains them.
        return (min(max(x_px / self.width, 0.0), _EDGE), min(max(y_px / self.height, 0.0), _EDGE))

    def _class_ok(self, obj_classes: list[str], class_name: str) -> bool:
        return not obj_classes or class_name in obj_classes

    def filter_detections(self, detections: list[Detection]) -> list[Detection]:
        """Drop detections whose ground point lies in an ignore region."""
        if not self._ignore_polys:
            return detections
        out: list[Detection] = []
        for d in detections:
            p = self.normalize(*d.bottom_center)
            if any(point_in_polygon(p, poly) for poly in self._ignore_polys):
                continue
            out.append(d)
        return out

    def zone_occupancy(self) -> dict[str, int]:
        occ = {z.id: 0 for z in self.zones}
        for (zone_id, _tid), visit in self._presence.items():
            if visit.announced:
                occ[zone_id] = occ.get(zone_id, 0) + 1
        return occ

    def dwell_time(self, zone_id: str, track_id: int, t: float) -> float | None:
        """Time from entering the zone to the last time the object was seen.

        A lost track keeps its presence until the tracker gives it up, so an
        object that walked out of view does not keep adding dwell time (and
        cannot trigger a dwell rule) after it was last seen. An object that has
        stepped out stops adding time when it left, even while it may still come
        back within the zone's allowance."""
        visit = self._presence.get((zone_id, track_id))
        if visit is None:
            return None
        rec = self.records.get(track_id)
        seen = min(t, rec.last_t) if rec is not None else t
        if visit.out_since is not None:
            seen = min(seen, visit.out_since)
        return max(0.0, seen - visit.enter_t)

    def tracks_in_zone(self, zone_id: str) -> list[int]:
        return [tid for (zid, tid), visit in self._presence.items() if zid == zone_id and visit.announced]

    def zones_of(self, track_id: int) -> list[str]:
        """Zones in which the track has a reported visit."""
        return [zid for (zid, tid), visit in self._presence.items() if tid == track_id and visit.announced]

    def trajectory(self, track_id: int) -> list[TrackPoint]:
        rec = self.records.get(track_id)
        return rec.points if rec else []

    def speed_between(self, track_id: int, t0: float, t1: float) -> float | None:
        """Average speed of a track between two media times (calibration unit / s)."""
        pts = [p for p in self.trajectory(track_id) if t0 - 1e-6 <= p.t <= t1 + 1e-6]
        if len(pts) < 2:
            return None
        dist = 0.0
        for a, b in zip(pts, pts[1:], strict=False):
            dist += self.mapper.distance((a.x, a.y), (b.x, b.y))
        dur = pts[-1].t - pts[0].t
        return dist / dur if dur > 0 else None

    def path_length(self, track_id: int) -> float | None:
        pts = self.trajectory(track_id)
        if len(pts) < 2:
            return None
        return sum(self.mapper.distance((a.x, a.y), (b.x, b.y)) for a, b in zip(pts, pts[1:], strict=False))

    # ------------------------------------------------------------------ update
    def update(self, upd: TrackerUpdate, t: float, frame_index: int) -> list[Interaction]:
        out: list[Interaction] = []

        for tr in upd.started:
            self._ensure_record(tr, t, frame_index)
            out.append(self._lifecycle("track_started", tr, t, frame_index))
        back_at_door: set[int] = set()
        for tr in upd.reacquired:
            rec = self.records.get(tr.track_id)
            if rec:
                rec.lost_count += 1
            out.append(self._lifecycle("track_reacquired", tr, t, frame_index))
            seen = self._seen.get(tr.track_id)
            if self._doorways and seen is not None and t - seen.t >= _DOOR_GAP_S:
                # Out of view for a while: it may have gone through a doorway and come back.
                out.extend(self._doorway_vanished(tr, seen))
                back_at_door.add(tr.track_id)
        for tr in upd.lost:
            out.append(self._lifecycle("track_lost", tr, t, frame_index))

        for tr in upd.tracks:
            if tr.state != "tracked" or not tr.updated:
                continue
            if self.tracked_classes and tr.class_name not in self.tracked_classes:
                continue
            pos = self.normalize(*tr.bottom_center)
            rec = self._ensure_record(tr, t, frame_index)
            rec.last_t, rec.last_frame = t, frame_index
            rec.n_frames += 1
            rec.conf_sum += tr.confidence
            rec.class_name = tr.class_name
            if not rec.points or (t - rec.points[-1].t) >= self.sample_interval:
                rec.points.append(TrackPoint(t, pos[0], pos[1]))
            prev = self._last_pos.get(tr.track_id)
            prev_hits = self._last_hits.get(tr.track_id, 0)
            self._last_pos[tr.track_id] = pos
            self._last_hits[tr.track_id] = tr.hits
            if prev is not None:
                out.extend(self._check_lines(tr, prev, prev_hits, pos, t, frame_index))
            if self._doorways:
                x1, _y1, x2, y2 = tr.box
                seen = _Seen(t, frame_index, pos, (self.normalize(x1, y2), self.normalize(x2, y2)))
                if tr.track_id not in self._seen or tr.track_id in back_at_door:
                    self._doorway_candidates(tr, seen)
                self._seen[tr.track_id] = seen
                out.extend(self._doorway_appeared(tr, seen))
            out.extend(self._check_zones(tr, pos, t, frame_index))

        for tr in upd.removed:
            out.extend(self._end_track(tr, t, frame_index))
        return out

    # ------------------------------------------------------------------ internals
    def _ensure_record(self, tr: Track, t: float, frame_index: int) -> TrackRecord:
        rec = self.records.get(tr.track_id)
        if rec is None:
            rec = TrackRecord(tr.track_id, tr.class_name, tr.first_time, tr.first_frame, t, frame_index)
            self.records[tr.track_id] = rec
        return rec

    def _lifecycle(self, kind: str, tr: Track, t: float, frame_index: int) -> Interaction:
        return Interaction(kind, tr.track_id, tr.class_name, t, frame_index, self.normalize(*tr.bottom_center))

    def _line_applies(self, ln: LineObject, tr: Track) -> bool:
        return self._class_ok(ln.classes, tr.class_name) and tr.hits >= ln.min_track_age and tr.mean_confidence >= ln.min_confidence

    def _check_lines(self, tr: Track, prev: tuple[float, float], prev_hits: int, pos: tuple[float, float], t: float, frame_index: int) -> list[Interaction]:
        out: list[Interaction] = []
        for ln in self.lines:
            # The movement must start where the track was already old enough: the
            # first box of a new track is often only part of the object (someone
            # stepping in from under the camera), and its bottom is not their feet.
            if not self._line_applies(ln, tr) or prev_hits < ln.min_track_age:
                continue
            a, b = self._line_pts[ln.id]
            crossed, direction, _u = segment_crossing(a, b, prev, pos)
            if not crossed:
                continue
            ia = self._count_crossing(ln, tr, direction, t, frame_index, pos)
            if ia is not None:
                out.append(ia)
        return out

    def _count_crossing(
        self, ln: LineObject, tr: Track, direction: str, t: float, frame_index: int, pos: tuple[float, float], inferred: str | None = None,
    ) -> Interaction | None:
        if ln.direction != "both" and direction != ln.direction:
            return None
        key = (ln.id, tr.track_id)
        last = self._last_cross.get(key)
        if last is not None and abs(t - last) < ln.debounce_s:
            return None
        self._last_cross[key] = t
        log = self._door_log.get(ln.id)
        if log is not None:
            rec = self.records.get(tr.track_id)
            log.append((t, direction, tr.track_id, rec.first_t if rec else t))
            log[:] = [e for e in log if e[0] >= t - _DOOR_LOG_S]
        return Interaction(
            "line_crossed", tr.track_id, tr.class_name, t, frame_index, pos,
            object_id=ln.id, object_type=ln.type, object_name=ln.name, direction=direction,
            extra={"inferred": inferred} if inferred else {},
        )

    # ------------------------------------------------------------------ doorways
    def _iso(self, p: tuple[float, float]) -> tuple[float, float]:
        """Normalized point in units of the longer frame side (distances are the same in x and y)."""
        return (p[0] * self._iso_scale[0], p[1] * self._iso_scale[1])

    def _reaches(self, ln: LineObject, foot: tuple[tuple[float, float], tuple[float, float]]) -> bool:
        a, b = self._line_pts[ln.id]
        return segment_distance(self._iso(foot[0]), self._iso(foot[1]), self._iso(a), self._iso(b)) <= _DOOR_REACH

    def _across(self, ln: LineObject, p0: tuple[float, float], p1: tuple[float, float]) -> float:
        """Movement p0 -> p1 across the line; positive towards its forward side."""
        a, b = self._line_pts[ln.id]
        n = forward_normal(self._iso(a), self._iso(b))
        q0, q1 = self._iso(p0), self._iso(p1)
        return (q1[0] - q0[0]) * n[0] + (q1[1] - q0[1]) * n[1]

    def _doorway_vanished(self, tr: Track, seen: _Seen) -> list[Interaction]:
        """The track went out of view: did it walk through a doorway?"""
        rec = self.records.get(tr.track_id)
        if rec is None or seen.t - rec.first_t < _DOOR_MIN_SEEN_S or rec.n_frames < _DOOR_MIN_FRAMES:
            return []
        start = next((p for p in rec.points if p.t >= seen.t - _DOOR_WINDOW_S), None)
        p0 = (start.x, start.y) if start is not None else seen.pos
        out: list[Interaction] = []
        for ln in self._doorways:
            if not self._line_applies(ln, tr) or not self._reaches(ln, seen.foot):
                continue
            move = self._across(ln, p0, seen.pos)
            if abs(move) < _DOOR_MIN_MOVE:
                continue
            a, b = self._line_pts[ln.id]
            if side_of_line(a, b, seen.pos) * move > 0:
                continue  # its ground point got across: that crossing was counted when seen
            direction = "forward" if move > 0 else "reverse"
            if self._counted_by_successor(ln, direction, tr.track_id, seen.t):
                continue
            ia = self._count_crossing(ln, tr, direction, seen.t, seen.frame, seen.pos, inferred="disappeared")
            if ia is not None:
                out.append(ia)
        return out

    def _doorway_candidates(self, tr: Track, seen: _Seen) -> None:
        for ln in self._doorways:
            if self._reaches(ln, seen.foot):
                self._appear[(ln.id, tr.track_id)] = seen

    def _doorway_appeared(self, tr: Track, seen: _Seen) -> list[Interaction]:
        """A track that came into view at a doorway: did it come through it?"""
        out: list[Interaction] = []
        for ln in self._doorways:
            key = (ln.id, tr.track_id)
            first = self._appear.get(key)
            if first is None:
                continue
            crossed = self._last_cross.get(key)
            if (crossed is not None and crossed >= first.t) or seen.t - first.t > _DOOR_APPEAR_S:
                del self._appear[key]  # crossed in view (counted), or never left the door
                continue
            rec = self.records.get(tr.track_id)
            if seen.t - first.t < _DOOR_MIN_SEEN_S or rec is None or rec.n_frames < _DOOR_MIN_FRAMES:
                continue  # not followed long enough yet to tell
            move = self._across(ln, first.pos, seen.pos)
            if abs(move) < _DOOR_MIN_MOVE:
                continue
            del self._appear[key]
            a, b = self._line_pts[ln.id]
            if side_of_line(a, b, first.pos) * move < 0 or not self._line_applies(ln, tr):
                continue  # heading for the door, not coming from it
            direction = "forward" if move > 0 else "reverse"
            if self._counted_by_predecessor(ln, direction, tr.track_id, first.t):
                continue
            ia = self._count_crossing(ln, tr, direction, first.t, first.frame, first.pos, inferred="appeared")
            if ia is not None:
                out.append(ia)
        return out

    def _counted_by_successor(self, ln: LineObject, direction: str, track_id: int, last_t: float) -> bool:
        """A track that started after this one was last seen already counted the passage."""
        return any(
            other != track_id and d == direction and other_first >= last_t - 1e-6 and t <= last_t + _DOOR_SAME_OBJECT_S
            for t, d, other, other_first in self._door_log.get(ln.id, ())
        )

    def _counted_by_predecessor(self, ln: LineObject, direction: str, track_id: int, first_t: float) -> bool:
        """A track that was out of view when this one appeared counted the passage just before."""
        for t, d, other, _first in self._door_log.get(ln.id, ()):
            if other == track_id or d != direction or not first_t - _DOOR_SAME_OBJECT_S <= t <= first_t:
                continue
            other_seen = self._seen.get(other)
            if other_seen is None or other_seen.t < first_t:
                return True
        return False

    def _check_zones(self, tr: Track, pos: tuple[float, float], t: float, frame_index: int) -> list[Interaction]:
        """Zone visits with an allowance for short exits.

        An object that leaves a zone and comes back within the zone's
        ``debounce_s`` keeps its visit, so someone standing on the edge is not
        counted again and again. A longer exit ends the visit at the moment the
        object left."""
        out: list[Interaction] = []
        for z in self.zones:
            if not self._class_ok(z.classes, tr.class_name):
                continue
            key = (z.id, tr.track_id)
            visit = self._presence.get(key)
            if point_in_polygon(pos, self._zone_polys[z.id]):
                if visit is not None and visit.out_since is not None and t - visit.out_since >= z.debounce_s:
                    # Back only after the allowance (the track was lost meanwhile):
                    # the earlier visit ended when the object left.
                    out.extend(self._close_visit(z, key, visit, tr))
                    visit = None
                if visit is None:
                    if tr.hits < z.min_track_age or tr.mean_confidence < z.min_confidence:
                        continue
                    visit = self._presence[key] = _Visit(t)
                visit.out_since = None
                if not visit.announced and (t - visit.enter_t) >= z.min_dwell_s:
                    visit.announced = True
                    out.append(
                        Interaction(
                            "zone_entered", tr.track_id, tr.class_name, visit.enter_t, frame_index, pos,
                            object_id=z.id, object_type=z.type, object_name=z.name,
                        )
                    )
                    occ = self.zone_occupancy()[z.id]
                    self.max_occupancy[z.id] = max(self.max_occupancy.get(z.id, 0), occ)
            elif visit is not None:
                if visit.out_since is None:
                    visit.out_since, visit.out_frame, visit.out_pos = t, frame_index, pos
                if t - visit.out_since >= z.debounce_s:
                    out.extend(self._close_visit(z, key, visit, tr))
        return out

    def _close_visit(self, z: ZoneObject, key: tuple[str, int], visit: _Visit, tr: Track) -> list[Interaction]:
        del self._presence[key]
        if not visit.announced or visit.out_since is None:
            return []
        return [
            Interaction(
                "zone_exited", tr.track_id, tr.class_name, visit.out_since, visit.out_frame, visit.out_pos,
                object_id=z.id, object_type=z.type, object_name=z.name, dwell_s=visit.out_since - visit.enter_t,
            )
        ]

    def end_tracks(self, tracks: list[Track], frame_index: int, reason: str = "run_ended") -> list[Interaction]:
        """Close every open zone visit of the given tracks (for example when a run stops)."""
        out: list[Interaction] = []
        for tr in tracks:
            out.extend(self._end_track(tr, tr.last_time, frame_index, reason=reason))
        return out

    def _end_track(self, tr: Track, t: float, frame_index: int, reason: str = "track_lost") -> list[Interaction]:
        out: list[Interaction] = []
        seen = self._seen.get(tr.track_id)
        # Given up by the tracker, or already out of view when the run stopped
        if seen is not None and (reason == "track_lost" or not tr.updated or tr.state == "lost"):
            out.extend(self._doorway_vanished(tr, seen))
        self._seen.pop(tr.track_id, None)
        for key in [k for k in self._appear if k[1] == tr.track_id]:
            del self._appear[key]
        self._last_hits.pop(tr.track_id, None)
        pos = self._last_pos.pop(tr.track_id, self.normalize(*tr.bottom_center))
        for (zone_id, tid), visit in list(self._presence.items()):
            if tid != tr.track_id:
                continue
            del self._presence[(zone_id, tid)]
            if visit.announced:
                z = next((zz for zz in self.zones if zz.id == zone_id), None)
                if visit.out_since is not None:
                    # It had already stepped out: the visit ended when it left.
                    end_t, end_frame, end_pos, why = visit.out_since, visit.out_frame, visit.out_pos, "left_zone"
                else:
                    end_t, end_frame, end_pos, why = tr.last_time, frame_index, pos, reason
                out.append(
                    Interaction(
                        "zone_exited", tr.track_id, tr.class_name, end_t, end_frame, end_pos,
                        object_id=zone_id, object_type=z.type if z else "zone",
                        object_name=z.name if z else zone_id, dwell_s=end_t - visit.enter_t,
                        extra={"reason": why},
                    )
                )
        for key in [k for k in self._last_cross if k[1] == tr.track_id]:
            del self._last_cross[key]
        rec = self.records.get(tr.track_id)
        if rec is not None:
            rec.final_state = "removed"  # rec.lost_count counts re-acquisitions only
        out.append(
            Interaction(
                "track_ended", tr.track_id, tr.class_name, tr.last_time, frame_index, pos,
                extra={"first_t": tr.first_time, "last_t": tr.last_time},
            )
        )
        return out

    def pop_record(self, track_id: int) -> TrackRecord | None:
        return self.records.pop(track_id, None)

    def describe(self) -> dict:
        return {
            "lines": len(self.lines),
            "zones": len(self.zones),
            "ignore_regions": len(self.ignore),
            "calibration": self.mapper.describe(),
        }
