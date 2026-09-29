"""Temporal relations between intervals and instants.

Time is explicit in every relationship (a start and, once known, an end).
This module classifies how two of them relate and names the relation with
the registry's temporal types:

    a ends before b starts          a PRECEDED b          (gap = b.start - a.end)
    b starts within X s after a     b FOLLOWED_WITHIN a
    they share time                 a OVERLAPPED_WITH b
    a starts after b starts         a STARTED_AFTER b
    a ends before b ends            a ENDED_BEFORE b

Correlation rules use ``within`` / ``after`` checks from here, and store the
temporal relations between their supporting observations explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

EPS = 1e-6


@dataclass(frozen=True)
class Interval:
    start: float
    end: float | None = None  # None: still open (use start for instants)

    @property
    def stop(self) -> float:
        return self.start if self.end is None else self.end

    @property
    def instant(self) -> bool:
        return self.end is None or abs(self.end - self.start) < EPS


def allen(a: Interval, b: Interval) -> str:
    """Allen's interval relation of a to b (instants are zero-length intervals)."""
    a0, a1, b0, b1 = a.start, a.stop, b.start, b.stop
    if a1 < b0 - EPS:
        return "before"
    if b1 < a0 - EPS:
        return "after"
    if abs(a0 - b0) < EPS and abs(a1 - b1) < EPS:
        return "equals"
    if abs(a1 - b0) < EPS:
        return "meets"
    if abs(b1 - a0) < EPS:
        return "met_by"
    if abs(a0 - b0) < EPS:
        return "starts" if a1 < b1 else "started_by"
    if abs(a1 - b1) < EPS:
        return "finishes" if a0 > b0 else "finished_by"
    if a0 > b0 and a1 < b1:
        return "during"
    if a0 < b0 and a1 > b1:
        return "contains"
    return "overlaps" if a0 < b0 else "overlapped_by"


def gap(a: Interval, b: Interval) -> float:
    """Seconds from the end of a to the start of b (negative when they overlap)."""
    return b.start - a.stop


def relations_between(a: Interval, b: Interval, within_s: float | None = None) -> list[tuple[str, float]]:
    """Registry types that hold from a to b, with the gap in seconds."""
    out: list[tuple[str, float]] = []
    rel = allen(a, b)
    g = gap(a, b)
    if rel in ("before", "meets"):
        out.append(("PRECEDED", round(g, 3)))
    elif rel in ("after", "met_by"):
        out.append(("FOLLOWED_AFTER", round(a.start - b.stop, 3)))
        if within_s is not None and a.start - b.stop <= within_s + EPS:
            out.append(("FOLLOWED_WITHIN", round(a.start - b.stop, 3)))
    else:
        out.append(("OVERLAPPED_WITH", round(min(a.stop, b.stop) - max(a.start, b.start), 3)))
    if a.start > b.start + EPS:
        out.append(("STARTED_AFTER", round(a.start - b.start, 3)))
    if a.end is not None and b.end is not None and a.end < b.end - EPS:
        out.append(("ENDED_BEFORE", round(b.end - a.end, 3)))
    return out


def within(t_prev: float, t: float, max_s: float | None, allow_equal: bool = True) -> bool:
    """t is after t_prev (or at the same moment) and no more than max_s later."""
    if t < t_prev - (EPS if allow_equal else -EPS):
        return False
    return max_s is None or t - t_prev <= max_s + EPS


def close_in_time(t1: float, t2: float, max_s: float) -> bool:
    return abs(t1 - t2) <= max_s + EPS
