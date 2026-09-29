"""Aggregations over stored events. Reads only; no interpretation."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pathscope.db.models import Camera, Event, Run, TrackSummary, Trajectory
from pathscope.rules.engine import ROUTE_ABANDONED, ROUTE_LOST, ROUTE_UNKNOWN

OUTCOMES = (ROUTE_UNKNOWN, ROUTE_ABANDONED, ROUTE_LOST)


def _mean(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _pct(x: float | None, digits: int = 1) -> float | None:
    return round(x, digits) if x is not None else None


def route_summary(events: list[Event]) -> dict:
    routes = [e for e in events if e.event_type == "route"]
    total = len(routes)
    by_route: Counter[str] = Counter(e.route or "UNKNOWN" for e in routes)
    completed = [e for e in routes if e.route not in OUTCOMES]
    valid = len(completed)
    dist = []
    for name, n in by_route.most_common():
        durations = [e.duration_s for e in routes if (e.route or "UNKNOWN") == name and e.duration_s is not None]
        speeds = [e.avg_speed for e in routes if (e.route or "UNKNOWN") == name and e.avg_speed is not None]
        dist.append(
            {
                "route": name,
                "count": n,
                "share_of_all": _pct(100.0 * n / total) if total else None,
                "share_of_valid": _pct(100.0 * n / valid) if (valid and name not in OUTCOMES) else None,
                "is_outcome": name in OUTCOMES,
                "mean_duration_s": _pct(_mean(durations), 2),
                "median_duration_s": _pct(_median(durations), 2),
                "mean_speed": _pct(_mean(speeds), 3),
            }
        )
    speed_unit = next((e.speed_unit for e in routes if e.speed_unit), None)
    decision = [e.context.get("decision_time_s") for e in completed if isinstance(e.context, dict) and e.context.get("decision_time_s") is not None]
    switched = sum(1 for e in completed if isinstance(e.context, dict) and e.context.get("switched_from"))
    prev_pairs: Counter[tuple[str, str]] = Counter()
    for e in completed:
        prev = e.context.get("previous_route") if isinstance(e.context, dict) else None
        if prev:
            prev_pairs[(prev, e.route or "")] += 1
    following = [
        {"previous": p, "route": r, "count": n} for (p, r), n in prev_pairs.most_common()
    ]
    same_as_previous = sum(n for (p, r), n in prev_pairs.items() if p == r)
    with_previous = sum(prev_pairs.values())
    occ_by_route: dict[str, list[int]] = defaultdict(list)
    for e in completed:
        occ = e.context.get("occupancy_at_decision") if isinstance(e.context, dict) else None
        if occ is not None:
            occ_by_route[e.route or ""].append(int(occ))
    return {
        "total_observations": total,
        "valid_observations": valid,
        "unknown": by_route.get(ROUTE_UNKNOWN, 0),
        "abandoned": by_route.get(ROUTE_ABANDONED, 0),
        "lost_track": by_route.get(ROUTE_LOST, 0),
        "distribution": dist,
        "speed_unit": speed_unit,
        "mean_decision_time_s": _pct(_mean(decision), 2),
        "route_switches": switched,
        "following": {
            "pairs": following,
            "same_as_previous": same_as_previous,
            "with_previous": with_previous,
            "same_share": _pct(100.0 * same_as_previous / with_previous) if with_previous else None,
        },
        "occupancy_at_decision": {
            r: {"mean": _pct(_mean(v), 2), "n": len(v)} for r, v in occ_by_route.items()
        },
    }


def crossing_summary(events: list[Event]) -> list[dict]:
    rows: dict[tuple[str, str], dict] = {}
    for e in events:
        if e.event_type != "crossing":
            continue
        key = (e.object_id or "", e.object_name or "")
        row = rows.setdefault(key, {"object_id": key[0], "object_name": key[1], "total": 0, "forward": 0, "reverse": 0, "by_class": Counter()})
        row["total"] += 1
        if e.direction in ("forward", "reverse"):
            row[e.direction] += 1
        row["by_class"][e.object_class] += 1
    out = []
    for row in rows.values():
        row["by_class"] = dict(row["by_class"])
        out.append(row)
    return sorted(out, key=lambda r: -r["total"])


def _union_length(intervals: list[tuple[float, float]]) -> float:
    total = 0.0
    end = None
    start = None
    for a, b in sorted(intervals):
        if end is None or a > end:
            if end is not None:
                total += end - start
            start, end = a, b
        else:
            end = max(end, b)
    if end is not None:
        total += end - start
    return total


def _by_hour(intervals: list[tuple[float, float]]) -> list[dict]:
    """Seconds of occupancy per UTC hour for (start, end) epoch intervals (merged first)."""
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    buckets: dict[int, float] = defaultdict(float)
    for a, b in merged:
        cur = a
        while cur < b:
            hour = int(cur // 3600) * 3600
            nxt = min(b, hour + 3600)
            buckets[hour] += nxt - cur
            cur = nxt
    return [
        {"hour": datetime.fromtimestamp(h, tz=UTC).isoformat(), "seconds": round(s, 1)}
        for h, s in sorted(buckets.items())
    ]


def zone_summary(events: list[Event], live_run_ids: set[int] | None = None) -> list[dict]:
    """Per zone: entries, exits (completed visits), dwell statistics, total time
    spent by all objects, and occupied time (at least one object inside).

    Occupied time is merged per run, because media time starts again at zero
    in every run. The split by clock hour uses only runs of live cameras
    (``live_run_ids``; None = all runs): for a recorded video the wall clock is
    the processing time, not the time the video was filmed.
    """
    zones: dict[str, dict] = {}
    visits: dict[tuple[str, int | None], list[tuple[float, float]]] = defaultdict(list)
    visits_wall: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for e in events:
        if e.event_type not in ("zone_entry", "zone_exit", "dwell", "dwell_exceeded", "occupancy_exceeded"):
            continue
        z = zones.setdefault(e.object_id or "", {"object_id": e.object_id, "object_name": e.object_name, "entries": 0, "exits": 0, "dwell_s": [], "dwell_exceeded": 0, "occupancy_exceeded": 0, "max_occupancy": 0})
        if e.event_type == "zone_entry":
            z["entries"] += 1
            occ = e.context.get("zone_occupancy") if isinstance(e.context, dict) else None
            if occ is not None:
                z["max_occupancy"] = max(z["max_occupancy"], int(occ))
        elif e.event_type == "zone_exit":
            z["exits"] += 1
            if e.duration_s is not None:
                z["dwell_s"].append(e.duration_s)
                end = e.completed_at_s if e.completed_at_s is not None else e.media_time_s
                visits[(e.object_id or "", e.run_id)].append((end - e.duration_s, end))
                if e.wall_time is not None and (live_run_ids is None or e.run_id in live_run_ids):
                    w_end = e.wall_time.timestamp()
                    visits_wall[e.object_id or ""].append((w_end - e.duration_s, w_end))
        elif e.event_type == "dwell_exceeded":
            z["dwell_exceeded"] += 1
        elif e.event_type == "occupancy_exceeded":
            z["occupancy_exceeded"] += 1
    out = []
    for key, z in zones.items():
        d = z.pop("dwell_s")
        z["mean_dwell_s"] = _pct(_mean(d), 2)
        z["median_dwell_s"] = _pct(_median(d), 2)
        z["max_dwell_s"] = _pct(max(d), 2) if d else None
        z["total_dwell_s"] = _pct(sum(d), 1) if d else 0.0
        z["occupied_s"] = _pct(sum(_union_length(v) for (zid, _run), v in visits.items() if zid == key), 1)
        z["occupied_by_hour"] = _by_hour(visits_wall[key])
        out.append(z)
    return out


def class_distribution(events: list[Event], tracks: list[TrackSummary]) -> dict:
    by_event = Counter(e.object_class for e in events if e.object_class)
    by_track = Counter(t.object_class for t in tracks)
    return {"events": dict(by_event), "tracks": dict(by_track)}


def hourly_series(events: list[Event], event_type: str | None = None) -> list[dict]:
    """Events per wall-clock hour, split by route/label."""
    buckets: dict[str, Counter] = defaultdict(Counter)
    for e in events:
        if event_type and e.event_type != event_type:
            continue
        wt = e.wall_time or datetime.now(UTC)
        key = wt.replace(minute=0, second=0, microsecond=0).isoformat()
        label = e.route if e.event_type == "route" else (e.object_name or e.event_type)
        buckets[key][label or "event"] += 1
    return [{"hour": k, "counts": dict(v), "total": sum(v.values())} for k, v in sorted(buckets.items())]


def media_time_series(events: list[Event], bucket_s: float = 60.0, event_type: str | None = None) -> list[dict]:
    """Events per media-time bucket (useful for recorded footage)."""
    buckets: dict[int, Counter] = defaultdict(Counter)
    for e in events:
        if event_type and e.event_type != event_type:
            continue
        if e.event_type in ("occupancy_exceeded",):
            continue
        b = int(e.media_time_s // bucket_s)
        label = e.route if e.event_type == "route" else (e.object_name or e.event_type)
        buckets[b][label or "event"] += 1
    return [{"start_s": b * bucket_s, "counts": dict(v), "total": sum(v.values())} for b, v in sorted(buckets.items())]


def track_stats(tracks: list[TrackSummary]) -> dict:
    if not tracks:
        return {"count": 0}
    lifetimes = [t.last_seen_s - t.first_seen_s for t in tracks]
    speeds = [t.avg_speed for t in tracks if t.avg_speed is not None]
    return {
        "count": len(tracks),
        "mean_lifetime_s": _pct(_mean(lifetimes), 2),
        "median_lifetime_s": _pct(_median(lifetimes), 2),
        "mean_speed": _pct(_mean(speeds), 3),
        "speed_unit": next((t.speed_unit for t in tracks if t.speed_unit), None),
        "lost_reacquired": sum(t.lost_count for t in tracks),
        "active_at_end": sum(1 for t in tracks if t.final_state == "active_at_end"),
        "mean_confidence": _pct(_mean([t.mean_confidence for t in tracks if t.mean_confidence is not None]), 3),
    }


def _live_run_ids(session: Session, runs: list[Run]) -> set[int]:
    """Runs of live cameras. Newer runs record the source type in their
    snapshot; older ones fall back to the camera's current type."""
    out: set[int] = set()
    for r in runs:
        source_type = (r.snapshot or {}).get("source_type")
        if source_type is None and r.camera_id is not None:
            cam = session.get(Camera, r.camera_id)
            source_type = cam.source_type if cam is not None else None
        if source_type is not None and source_type != "file":
            out.add(r.id)
    return out


def run_summary(session: Session, run_id: int) -> dict:
    run = session.get(Run, run_id)
    if run is None:
        raise KeyError(run_id)
    events = list(session.scalars(select(Event).where(Event.run_id == run_id).order_by(Event.media_time_s)))
    tracks = list(session.scalars(select(TrackSummary).where(TrackSummary.run_id == run_id)))
    duration = None
    if run.started_at and run.ended_at:
        duration = (run.ended_at - run.started_at).total_seconds()
    media_span = max((e.media_time_s for e in events), default=0.0)
    per_hour = None
    if media_span > 0:
        crossings = sum(1 for e in events if e.event_type == "crossing")
        per_hour = round(crossings / (media_span / 3600.0), 1)
    return {
        "run_id": run_id,
        "status": run.status,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "duration_s": duration,
        "media_span_s": media_span,
        "event_count": len(events),
        "events_by_type": dict(Counter(e.event_type for e in events)),
        "routes": route_summary(events),
        "crossings": crossing_summary(events),
        "crossings_per_hour_media": per_hour,
        "zones": zone_summary(events, _live_run_ids(session, [run])),
        "classes": class_distribution(events, tracks),
        "tracks": track_stats(tracks),
        "media_series": media_time_series(events, 60.0),
        "hourly": hourly_series(events),
        "stats": run.stats or {},
    }


def experiment_summary(session: Session, experiment_id: int) -> dict:
    runs = list(session.scalars(select(Run).where(Run.experiment_id == experiment_id).order_by(Run.id)))
    events = list(session.scalars(select(Event).where(Event.experiment_id == experiment_id)))
    run_ids = [r.id for r in runs]
    tracks = list(session.scalars(select(TrackSummary).where(TrackSummary.run_id.in_(run_ids)))) if run_ids else []
    return {
        "experiment_id": experiment_id,
        "runs": [
            {"id": r.id, "status": r.status, "started_at": r.started_at, "ended_at": r.ended_at, "events": sum(1 for e in events if e.run_id == r.id), "scene_version": (r.snapshot or {}).get("scene_version")}
            for r in runs
        ],
        "event_count": len(events),
        "events_by_type": dict(Counter(e.event_type for e in events)),
        "routes": route_summary(events),
        "crossings": crossing_summary(events),
        "zones": zone_summary(events, _live_run_ids(session, runs)),
        "classes": class_distribution(events, tracks),
        "tracks": track_stats(tracks),
        "hourly": hourly_series(events),
        "by_run_routes": {r.id: route_summary([e for e in events if e.run_id == r.id])["distribution"] for r in runs},
    }


def trajectories_for_run(session: Session, run_id: int, limit: int = 2000) -> list[dict]:
    rows = session.scalars(select(Trajectory).where(Trajectory.run_id == run_id).limit(limit))
    return [{"track_id": r.track_id, "object_class": r.object_class, "points": r.points} for r in rows]


def heatmap_for_run(session: Session, run_id: int, grid: int = 48) -> dict:
    """Occupancy heatmap over a grid of normalized cells from stored trajectories."""
    cells = [[0] * grid for _ in range(grid)]
    n = 0
    for r in session.scalars(select(Trajectory).where(Trajectory.run_id == run_id)):
        for _t, x, y in r.points:
            gx = min(grid - 1, max(0, int(x * grid)))
            gy = min(grid - 1, max(0, int(y * grid)))
            cells[gy][gx] += 1
            n += 1
    return {"grid": grid, "cells": cells, "samples": n}


def event_count(session: Session, run_id: int) -> int:
    return int(session.scalar(select(func.count(Event.id)).where(Event.run_id == run_id)) or 0)
