"""Coordinates of the Location Engine.

GPS is optional. A node is placed by logical coordinates (``x``, ``y``) in
the *layout frame* of its nearest ancestor that has a layout (a floor plan,
a schematic or a map), in that layout's unit: metres when the plan is drawn
to scale, plain units otherwise. Outdoor nodes may also carry ``lat``/``lon``.

Distances are physical only when they can be: the same metric frame, or two
GPS positions. Anything else is "unknown", never a guess in pixels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_R = 6371008.8


@dataclass(frozen=True)
class Distance:
    value: float
    unit: str  # "m" or "units"
    how: str  # "plan" | "gps" | "link"

    @property
    def metres(self) -> float | None:
        return self.value if self.unit == "m" else None


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def centroid(points: list[list[float]]) -> tuple[float, float] | None:
    pts = [(float(p[0]), float(p[1])) for p in points or [] if len(p) >= 2]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def project(lat: float, lon: float, lat0: float, lon0: float) -> tuple[float, float]:
    """Local equirectangular projection in metres (east, south) around lat0/lon0:
    good to a fraction of a percent over a campus or a road network."""
    x = math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0))
    y = -math.radians(lat - lat0) * EARTH_R
    return x, y
