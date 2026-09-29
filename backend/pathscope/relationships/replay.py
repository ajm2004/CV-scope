"""Analyse a stored run again (other rules, other rule versions, or a run
recorded before relationships were switched on).

The stored trajectories (sampled ground points, 10 per second by default)
are played back through the run's own scene version with the same spatial
and rule engines a live run uses, so zones, lines, checkpoints and routes
produce the same interactions; recognition results come from the stored
recognition events. What cannot be replayed is said in the analysis
provenance: box widths were not stored, so vehicles are measured as points
unless an earlier live analysis kept their median width.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.db.models import Event, Run, SceneConfig, TrackSummary, Trajectory
from pathscope.domain.entities import STATUS_RECOGNIZED, STATUS_UNKNOWN, EntityRef, anonymous_entity
from pathscope.domain.scene import SceneDocument
from pathscope.relationships import entities as E
from pathscope.relationships.engine import EngineContext, RelationEngine
from pathscope.relationships.models import RelationEntity
from pathscope.relationships.rules import CompiledRule, RelationExperimentSettings
from pathscope.rules.engine import RuleEngine
from pathscope.spatial.engine import SpatialEngine
from pathscope.vision.trackers.base import TrackerUpdate
from pathscope.vision.types import Track

STEP_S = 0.1
MAX_GAP_S = 1.0  # a longer gap in a stored trajectory counts as 'not seen'


class ReplayError(RuntimeError):
    pass


class StoredRecognition:
    """What each track resolved to, from the run's stored recognition events."""

    def __init__(self, rows: list, groups: dict[str, list[str]], modules: set[str]) -> None:
        self._modules = modules
        self._by_track: dict[int, list[tuple[float, EntityRef]]] = {}
        self.now = 0.0
        for e in rows:
            ref = self._entity(e, groups)
            if ref is not None:
                self._by_track.setdefault(int(e.track_id), []).append((float(e.media_time_s or 0.0), ref))
        for v in self._by_track.values():
            v.sort(key=lambda x: x[0])

    @staticmethod
    def _entity(e, groups: dict[str, list[str]]) -> EntityRef | None:
        tid, cls = int(e.track_id), e.object_class or ""
        # a reviewer's identification (study ground truth) says so in the event
        method = "annotation" if (e.context or {}).get("method") == "annotation" else None
        if e.module == "face":
            if e.kind in ("recognized", "identity_changed") and e.person_id:
                return EntityRef("enrolled_person", tid, cls or "person", identity_id=e.person_id, confidence=e.confidence, status=STATUS_RECOGNIZED, settled=True, method=method)
            if e.kind == "identity_cleared":
                return anonymous_entity(tid, cls or "person", status=STATUS_UNKNOWN, settled=True)
            return None  # a possible match is never an identity (as in live runs)
        if e.module == "plate" and e.plate_normalized:
            vid = e.vehicle_id
            return EntityRef("registered_vehicle" if vid else "recognized_plate", tid, cls or "car", plate=e.plate_normalized, vehicle_id=vid,
                             groups=list(groups.get(vid or "", [])), confidence=e.confidence, status=STATUS_RECOGNIZED, settled=True, method=method)
        return None

    def provides(self) -> set[str]:
        return set(self._modules)

    def resolve(self, track_id: int, object_class: str) -> EntityRef:
        best = None
        for t, ref in self._by_track.get(track_id, []):
            if t <= self.now + 1e-6:
                best = ref
            else:
                break
        if best is not None:
            return best
        # the module never decided for this track: final once the track is over
        return anonymous_entity(track_id, object_class, settled=track_id not in self._by_track)

    def forget(self, track_id: int) -> None:
        return None


@dataclass
class _Stored:
    tid: int
    cls: str
    conf: float
    times: list[float]
    xs: list[float]
    ys: list[float]
    hw: float

    def at(self, t: float) -> tuple[float, float] | None:
        i = bisect_left(self.times, t)
        if i < len(self.times) and abs(self.times[i] - t) < 1e-6:
            return self.xs[i], self.ys[i]
        if i == 0 or i >= len(self.times):
            return None
        t0, t1 = self.times[i - 1], self.times[i]
        if t1 - t0 > MAX_GAP_S:
            return None
        u = (t - t0) / (t1 - t0)
        return self.xs[i - 1] + u * (self.xs[i] - self.xs[i - 1]), self.ys[i - 1] + u * (self.ys[i] - self.ys[i - 1])


def load_scene(session: Session, run: Run) -> tuple[SceneDocument | None, SceneConfig | None]:
    sc = session.get(SceneConfig, run.scene_config_id) if run.scene_config_id else None
    if sc is None:
        return None, None
    try:
        return SceneDocument.model_validate(sc.document), sc
    except ValueError:
        return None, sc


def wall_offset(session: Session, run: Run) -> float:
    """wall epoch = media time + offset."""
    ts = session.scalar(select(TrackSummary).where(TrackSummary.run_id == run.id, TrackSummary.first_seen_at.is_not(None)).limit(1))
    if ts is not None and ts.first_seen_at is not None:
        return ts.first_seen_at.timestamp() - float(ts.first_seen_s)
    ev = session.scalar(select(Event).where(Event.run_id == run.id).limit(1))
    if ev is not None and ev.wall_time is not None:
        return ev.wall_time.timestamp() - float(ev.media_time_s)
    started = run.started_at or run.created_at
    return started.timestamp() if started else 0.0


def replay(session: Session, run: Run, rules: list[CompiledRule], settings: RelationExperimentSettings, salt: bytes, modules: set[str], on_payload, progress=None) -> dict:
    """Play the run through a fresh engine; ``on_payload(dict)`` receives the engine output in batches."""
    doc, sc = load_scene(session, run)
    if doc is None:
        raise ReplayError("The run's scene version is missing, so its zones and calibration are unknown.")
    trajs = list(session.scalars(select(Trajectory).where(Trajectory.run_id == run.id)))
    if not trajs:
        raise ReplayError("This run has no stored trajectories (Settings > Store sampled trajectories must be on while it runs).")
    summaries = {s.track_id: s for s in session.scalars(select(TrackSummary).where(TrackSummary.run_id == run.id))}
    # widths kept by an earlier live analysis
    widths: dict[int, float] = {}
    for ent in session.scalars(select(RelationEntity).where(RelationEntity.run_id == run.id, RelationEntity.entity_type == "vehicle_track")):
        parsed = E.parse_track_ref(ent.ref)
        hw = (ent.meta or {}).get("footprint_hw")
        if parsed and hw:
            widths[parsed[1]] = float(hw)
    tracks: list[_Stored] = []
    for tr in trajs:
        pts = sorted((p for p in tr.points or [] if len(p) >= 3), key=lambda p: p[0])
        if len(pts) < 2:
            continue
        s = summaries.get(tr.track_id)
        tracks.append(_Stored(tr.track_id, tr.object_class, float(s.mean_confidence) if s and s.mean_confidence is not None else 0.5,
                              [float(p[0]) for p in pts], [float(p[1]) for p in pts], [float(p[2]) for p in pts], widths.get(tr.track_id, 0.0)))
    if not tracks:
        raise ReplayError("The stored trajectories of this run are too short to analyse.")
    from pathscope.recognition.registry.models import RecognitionEvent, RecognitionVehicle

    rec_rows = list(session.scalars(select(RecognitionEvent).where(RecognitionEvent.run_id == run.id).order_by(RecognitionEvent.media_time_s)))
    groups = {v.id: list(v.groups or []) for v in session.scalars(select(RecognitionVehicle))}
    used = {e.module for e in rec_rows} | set(((run.snapshot or {}).get("recognition") or {}).get("modules") or [])
    resolver = StoredRecognition(rec_rows, groups, used & modules)
    W, H = doc.frame_width, doc.frame_height
    footprint = "stored width" if widths else "point"
    ctx = EngineContext(run.id, run.camera_id, run.experiment_id, W, H, doc, run.scene_config_id, sc.version if sc else None, salt, source="replay", footprint=footprint)
    engine = RelationEngine(ctx, rules, settings, resolver if resolver.provides() else None)
    spatial = SpatialEngine(doc, W, H, None)
    rule_engine = RuleEngine(doc, [], spatial, None)
    offset = wall_offset(session, run)

    t0 = min(tr.times[0] for tr in tracks)
    t1 = max(tr.times[-1] for tr in tracks)
    n = int((t1 - t0) / STEP_S) + 2
    live: dict[int, Track] = {}
    hits: dict[int, int] = {}
    # A stored trajectory starts where the tracker first reported the object, which
    # was after it had matched it this many times (so minimum track ages act as live).
    try:
        confirmed = max(1, int((((run.snapshot or {}).get("tracker") or {}).get("settings") or {}).get("min_hits", 2)))
    except (TypeError, ValueError):
        confirmed = 2
    frame = 0
    pending = sorted(tracks, key=lambda st: st.times[0])
    nxt = 0
    active: list[_Stored] = []
    for i in range(n):
        t = round(t0 + i * STEP_S, 4)
        resolver.now = t
        started, removed, current = [], [], []
        while nxt < len(pending) and pending[nxt].times[0] <= t + 1e-6:
            active.append(pending[nxt])
            nxt += 1
        still: list[_Stored] = []
        for st in active:
            if t > st.times[-1] + 1e-6:
                if st.tid in live:
                    tr = live.pop(st.tid)
                    tr.state = "removed"
                    removed.append(tr)
                continue
            still.append(st)
        active = still
        for st in active:
            pos = st.at(t)
            if pos is None:
                continue
            hits[st.tid] = hits.get(st.tid, confirmed - 1) + 1
            px, py = pos[0] * W, pos[1] * H
            half = st.hw * W
            prev = live.get(st.tid)
            tr = Track(st.tid, st.cls, st.conf, (px - half, py - 1.0, px + half, py), "tracked", hits[st.tid], hits[st.tid], frame, frame,
                       prev.first_time if prev else t, t, st.conf)
            if prev is None:
                started.append(tr)
            live[st.tid] = tr
            current.append(tr)
        upd = TrackerUpdate(list(live.values()), started, [], [], removed)
        interactions = spatial.update(upd, t, frame)
        events = rule_engine.process(interactions, t, frame, t + offset)
        engine.step(t, t + offset, current, interactions, [e.to_dict() for e in events])
        for tr in removed:
            spatial.pop_record(tr.track_id)
        frame += 1
        if i % 50 == 0:
            p = engine.drain()
            if p:
                on_payload(p)
            if progress is not None:
                progress(i / max(1, n))
    # close everything
    end = spatial.end_tracks(list(live.values()), frame, reason="run_ended")
    events = rule_engine.process(end, t1, frame, t1 + offset)
    engine.step(t1, t1 + offset, [], end, [e.to_dict() for e in events])
    engine.finish(t1, t1 + offset)
    p = engine.drain()
    if p:
        on_payload(p)
    return {"describe": engine.describe(), "status": engine.status(), "tracks": len(tracks), "recognition_events": len(rec_rows), "footprint": footprint, "duration_s": round(t1 - t0, 3)}
