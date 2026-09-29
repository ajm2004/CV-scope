"""Spatial measurements between entities.

Distances use the scene calibration when there is one:

* ``homography`` / ``scale`` calibration -> ground-plane distance in metres
  (the calibration unit), marked ``physical``
* no calibration -> the distance between the image ground points expressed
  in *frame widths* (pixels / frame width), marked ``scene-relative``

A scene-relative distance is never presented as metres. A rule states its
distance in metres and, optionally, a fallback in frame widths for
uncalibrated scenes; without the fallback the rule does not run on an
uncalibrated camera (the run reports why).

Positions are the bottom centre of the box (the ground point, as everywhere
in CV-Scope). A vehicle is measured by the bottom edge of its box, so a
person standing at a car's side is close to the car even though the car's
centre is metres away; when only points are known (replaying runs recorded
before relationships were on) the provenance says so.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from pathscope.domain.scene import SceneDocument
from pathscope.spatial.calibration import GroundMapper

Vec = tuple[float, float]


def _point_segment(p: Vec, a: Vec, b: Vec) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    if n <= 1e-18:
        return math.hypot(p[0] - ax, p[1] - ay)
    u = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / n))
    return math.hypot(p[0] - (ax + u * dx), p[1] - (ay + u * dy))


def _segments_intersect(a: Vec, b: Vec, c: Vec, d: Vec) -> bool:
    def orient(p: Vec, q: Vec, r: Vec) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def segment_distance(a0: Vec, a1: Vec, b0: Vec, b1: Vec) -> float:
    if _segments_intersect(a0, a1, b0, b1):
        return 0.0
    return min(_point_segment(a0, b0, b1), _point_segment(a1, b0, b1), _point_segment(b0, a0, a1), _point_segment(b1, a0, a1))


@dataclass(frozen=True)
class Footprint:
    """Ground point (normalized image coordinates) and half the box width."""

    x: float
    y: float
    hw: float = 0.0  # normalized half width; 0 = a point

    def ends(self) -> tuple[Vec, Vec]:
        return (self.x - self.hw, self.y), (self.x + self.hw, self.y)


class Metric:
    """Distances in the scene's best available unit."""

    def __init__(self, scene: SceneDocument | None, frame_width: int, frame_height: int) -> None:
        self.width = max(1, int(frame_width))
        self.height = max(1, int(frame_height))
        self.mapper = GroundMapper.from_calibration(scene.calibration if scene else None, self.width, self.height)
        self.mode = self.mapper.mode  # homography | scale | none
        self.physical = self.mode != "none"
        self.unit = self.mapper.unit if self.physical else "fw"

    @property
    def measure(self) -> str:
        return "physical" if self.physical else "scene-relative"

    @property
    def unit_label(self) -> str:
        return self.unit if self.physical else "frame widths"

    def ground(self, x: float, y: float) -> Vec:
        if self.physical:
            gx, gy = self.mapper.to_ground(x, y)
            if math.isfinite(gx) and math.isfinite(gy):
                return gx, gy
        return x, y * self.height / self.width

    def distance(self, a: Footprint, b: Footprint) -> float:
        if a.hw <= 0 and b.hw <= 0:
            ga, gb = self.ground(a.x, a.y), self.ground(b.x, b.y)
            return math.hypot(ga[0] - gb[0], ga[1] - gb[1])
        a0, a1 = (self.ground(*p) for p in a.ends())
        b0, b1 = (self.ground(*p) for p in b.ends())
        return segment_distance(a0, a1, b0, b1)

    def threshold(self, value: float, unit: str, fallback_fw: float | None) -> float | None:
        """A rule distance in this scene's unit, or None when it cannot be applied."""
        if unit == "fw":
            return value if not self.physical else self._fw_to_physical(value)
        if self.physical:
            return value
        return fallback_fw

    def _fw_to_physical(self, fw: float) -> float:
        """A frame-width distance measured at the image centre, in ground units."""
        a = self.ground(0.5, 0.75)
        b = self.ground(0.5 + fw, 0.75)
        return math.hypot(a[0] - b[0], a[1] - b[1])

    def describe(self) -> dict:
        return {"mode": self.mode, "unit": self.unit, "unit_label": self.unit_label, "measure": self.measure}


@dataclass
class MotionHistory:
    """Recent ground positions of one track, for speed, heading and 'where was it N s ago'."""

    keep_s: float = 90.0
    points: deque = field(default_factory=deque)  # (t, gx, gy)

    def add(self, t: float, g: Vec) -> None:
        self.points.append((t, g[0], g[1]))
        while self.points and t - self.points[0][0] > self.keep_s:
            self.points.popleft()

    def velocity(self, t: float, window_s: float = 1.0) -> tuple[float, float, float]:
        """(vx, vy, speed) over the last window (ground units per second)."""
        if len(self.points) < 2:
            return 0.0, 0.0, 0.0
        last = self.points[-1]
        first = last
        for p in reversed(self.points):
            first = p
            if last[0] - p[0] >= window_s:
                break
        dt = last[0] - first[0]
        if dt <= 1e-6:
            return 0.0, 0.0, 0.0
        vx, vy = (last[1] - first[1]) / dt, (last[2] - first[2]) / dt
        return vx, vy, math.hypot(vx, vy)

    def at(self, t: float) -> Vec | None:
        """Interpolated ground position at time t (None outside the history)."""
        pts = self.points
        if not pts or t < pts[0][0] - 1e-6 or t > pts[-1][0] + 1e-6:
            return None
        prev = pts[0]
        for p in pts:
            if p[0] >= t:
                if p[0] - prev[0] <= 1e-9:
                    return p[1], p[2]
                u = (t - prev[0]) / (p[0] - prev[0])
                return prev[1] + u * (p[1] - prev[1]), prev[2] + u * (p[2] - prev[2])
            prev = p
        return pts[-1][1], pts[-1][2]

    def displacement(self, t0: float, t1: float) -> float:
        a, b = self.at(t0), self.at(t1)
        if a is None or b is None:
            return 0.0
        return math.hypot(b[0] - a[0], b[1] - a[1])


def heading_difference(v1: Vec, v2: Vec) -> float:
    """Angle between two velocity vectors in degrees (180 when either is zero)."""
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 <= 1e-9 or n2 <= 1e-9:
        return 180.0
    c = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(c))


def closing_share(subject_before: Vec, subject_after: Vec, object_before: Vec, object_after: Vec) -> float:
    """Share of the change in distance caused by the subject's own movement (0..1).

    'A approached B' needs A to have moved towards B; a car driving up to a
    person standing still does not make the person approach the car."""
    d_before = math.hypot(subject_before[0] - object_before[0], subject_before[1] - object_before[1])
    # distance change if only the subject had moved, and if only the object had moved
    d_subject = math.hypot(subject_after[0] - object_before[0], subject_after[1] - object_before[1])
    d_object = math.hypot(subject_before[0] - object_after[0], subject_before[1] - object_after[1])
    by_subject = abs(d_before - d_subject)
    by_object = abs(d_before - d_object)
    total = by_subject + by_object
    return by_subject / total if total > 1e-9 else 0.0
