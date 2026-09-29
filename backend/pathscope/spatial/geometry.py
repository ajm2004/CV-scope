"""Pure 2-D geometry helpers on normalized coordinates."""

from __future__ import annotations

import math
from collections.abc import Sequence

Vec = tuple[float, float]


def cross(ax: float, ay: float, bx: float, by: float) -> float:
    return ax * by - ay * bx


def side_of_line(a: Vec, b: Vec, p: Vec) -> float:
    """Signed area sign: >0 when p is on the left-hand normal side of A->B."""
    return cross(b[0] - a[0], b[1] - a[1], p[0] - a[0], p[1] - a[1])


def forward_normal(a: Vec, b: Vec) -> Vec:
    """Unit vector pointing to the positive side of A->B (the 'forward' direction)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n == 0:
        return (0.0, 0.0)
    return (-dy / n, dx / n)


def segment_crossing(a: Vec, b: Vec, p0: Vec, p1: Vec) -> tuple[bool, str, float]:
    """Does the movement p0->p1 cross the finite segment A-B?

    Returns (crossed, direction, u) where direction is ``forward`` when the
    movement goes from the negative side to the positive side of A->B and
    ``reverse`` otherwise, and ``u`` is the parametric position of the
    intersection along A-B (0..1).
    """
    s0 = side_of_line(a, b, p0)
    s1 = side_of_line(a, b, p1)
    if s0 == 0.0 and s1 == 0.0:
        return (False, "", 0.0)
    if (s0 < 0 and s1 < 0) or (s0 > 0 and s1 > 0):
        return (False, "", 0.0)
    # Intersection parameter along A-B
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = p1[0] - p0[0], p1[1] - p0[1]
    denom = cross(rx, ry, sx, sy)
    if abs(denom) < 1e-12:
        return (False, "", 0.0)
    qpx, qpy = p0[0] - a[0], p0[1] - a[1]
    u = cross(qpx, qpy, sx, sy) / denom  # along A-B
    t = cross(qpx, qpy, rx, ry) / denom  # along p0-p1
    if u < 0.0 or u > 1.0 or t < 0.0 or t > 1.0:
        return (False, "", 0.0)
    direction = "forward" if s1 > s0 else "reverse"
    return (True, direction, u)


def point_segment_distance(p: Vec, a: Vec, b: Vec) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n2 = dx * dx + dy * dy
    u = 0.0 if n2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n2))
    return math.hypot(p[0] - (a[0] + u * dx), p[1] - (a[1] + u * dy))


def segment_distance(a: Vec, b: Vec, c: Vec, d: Vec) -> float:
    """Shortest distance between the segments A-B and C-D (0 when they touch)."""
    d1, d2 = side_of_line(a, b, c), side_of_line(a, b, d)
    d3, d4 = side_of_line(c, d, a), side_of_line(c, d, b)
    if ((d1 <= 0 <= d2) or (d2 <= 0 <= d1)) and ((d3 <= 0 <= d4) or (d4 <= 0 <= d3)) and not (d1 == d2 == 0):
        return 0.0
    return min(point_segment_distance(c, a, b), point_segment_distance(d, a, b),
               point_segment_distance(a, c, d), point_segment_distance(b, c, d))


def point_in_polygon(p: Vec, polygon: Sequence[Vec]) -> bool:
    """Ray casting test."""
    x, y = p
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersect = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        if intersect:
            inside = not inside
        j = i
    return inside


def polygon_area(polygon: Sequence[Vec]) -> float:
    n = len(polygon)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def polygon_centroid(polygon: Sequence[Vec]) -> Vec:
    n = len(polygon)
    if n == 0:
        return (0.0, 0.0)
    return (sum(p[0] for p in polygon) / n, sum(p[1] for p in polygon) / n)


def distance(a: Vec, b: Vec) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def path_length(points: Sequence[Vec]) -> float:
    return sum(distance(points[i - 1], points[i]) for i in range(1, len(points)))


def box_iou_matrix(boxes_a, boxes_b):
    """Vectorised IoU between two (N,4) and (M,4) xyxy arrays."""
    import numpy as np

    a = np.asarray(boxes_a, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(boxes_b, dtype=np.float64).reshape(-1, 4)
    if a.shape[0] == 0 or b.shape[0] == 0:
        return np.zeros((a.shape[0], b.shape[0]), dtype=np.float64)
    ix1 = np.maximum(a[:, None, 0], b[None, :, 0])
    iy1 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix2 = np.minimum(a[:, None, 2], b[None, :, 2])
    iy2 = np.minimum(a[:, None, 3], b[None, :, 3])
    iw = np.clip(ix2 - ix1, 0, None)
    ih = np.clip(iy2 - iy1, 0, None)
    inter = iw * ih
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)
