"""Cross-camera correlation: sightings, transitions, journeys, topology deviations.

A *sighting* is one track on one camera: when it was first and last seen,
which place it entered first and left last, and what it was identified as
(an enrolled person, a plate, a registered vehicle) with which confidence.
Continuous visual tracking between cameras is never assumed.

Consecutive sightings of the same identity on different cameras form a
*transition*, scored from independent evidence:

* ``recognition`` - the weaker of the two identity links (a face match, a
                    plate read);
* ``temporal``    - the time between the sightings against the expected
                    travel time (configured on the link, estimated from the
                    plan's metric distances, or unknown);
* ``spatial``     - what the location graph says about the move: directly
                    connected cameras, a path through N places, overlapping
                    views, a one-way link used backwards, or no connection;
* ``sensor``      - sensors placed on the way that reported presence or
                    movement in between;
* ``tracking``    - the detection quality of both tracks.

The combination and the states (confirmed / likely / possible /
insufficient) are the relationship engine's (``confidence.py``). Anonymous
tracks are linked only when switched on, only between directly connected
cameras with a known travel time, only when exactly one candidate fits on
both sides, and never above ``possible``.

Results are written as ``crosscam_transitions`` rows (the full provenance)
and mirrored into the relationship graph: MOVED_FROM / MOVED_TO /
MOVED_THROUGH / SEEN_AT / ENTERED_SITE_AT / EXITED_SITE_AT / CONTINUED_AS,
with rule key ``crosscam``. Everything is recomputed deterministically for a
set of runs, so a re-analysis or a topology edit never leaves stale links.

Deviations (implausible travel time, unknown connection, one-way link used
backwards, a restricted place reached without passing an entry point, an
unusual camera sequence for this identity) are stored as correlated events
of kind ``deviation``. They describe what was observed, never intent.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pathscope.db.models import Camera
from pathscope.location.models import CrossCameraTransition, LocationNode
from pathscope.location.settings import CrossCameraSettings
from pathscope.location.topology import LocationGraph, TopologyEvidence, Travel
from pathscope.relationships import entities as E
from pathscope.relationships.confidence import Components, at_least, combine, state_for
from pathscope.relationships.models import (
    RelationAnalysis,
    RelationCorrelated,
    RelationEntity,
    RelationObservation,
    RelationRelationship,
    RelationSupport,
)
from pathscope.relationships.store import _link_support, ensure_entities

RULE_KEY = "crosscam"
RULE_NAME = "Cross-camera correlation"
IDENTITY_LINKS = ("IDENTIFIED_AS", "IDENTIFIED_BY_PLATE")
ENTRY_TYPES = ("ENTERED", "CROSSED")
EXIT_TYPES = ("EXITED", "CROSSED")
JOURNEY_TYPES = ("ENTERED", "EXITED", "CROSSED", "PARKED_IN", "REMAINED_IN", "USED_ROUTE", "STOPPED_NEAR", "OCCUPIED")
ANON_CAP = 0.64  # anonymous transitions never reach 'likely'
SOURCE_CERTAINTY = {"link": 1.0, "path": 1.0, "distance": 0.9, "partial": 0.8, "unknown": 0.7}
DEVIATION_LABELS = {
    "implausible_time": "Implausible travel time",
    "unconnected": "Move between unconnected cameras",
    "wrong_way": "One-way link used backwards",
    "simultaneous": "Seen by two cameras at once",
    "restricted_without_entry": "Restricted place without an entry",
    "unusual_sequence": "Unusual camera sequence",
}


def _utc(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def stable_uid(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:32]


def _current(q, model):
    cur = select(RelationAnalysis.id).where(RelationAnalysis.current.is_(True))
    return q.where(or_(model.analysis_id.is_(None), model.analysis_id.in_(cur)))


# ---------------------------------------------------------------------------- sightings
@dataclass
class IdentityLink:
    subject_id: int
    basis: str  # face | plate | registered
    confidence: float
    link_ids: list[int]
    link_uids: list[str]
    method: str = "module"  # module | annotation (a reviewer identified the track)


@dataclass
class Sighting:
    track: RelationEntity
    identity: IdentityLink | None
    camera_id: int | None
    run_id: int | None
    experiment_id: int | None
    object_class: str
    first_at: datetime
    last_at: datetime
    first_media: float | None
    last_media: float | None
    places: list[RelationRelationship] = field(default_factory=list)
    entry_rel: RelationRelationship | None = None
    exit_rel: RelationRelationship | None = None
    entry_key: str | None = None
    exit_key: str | None = None
    entry_node: int | None = None
    exit_node: int | None = None
    appeared: RelationObservation | None = None
    disappeared: RelationObservation | None = None
    nodes: set[int] = field(default_factory=set)  # every location node the sighting touched

    @property
    def subject_id(self) -> int:
        return self.identity.subject_id if self.identity else self.track.id

    @property
    def basis(self) -> str:
        return self.identity.basis if self.identity else "anonymous"

    @property
    def track_conf(self) -> float:
        return float(self.track.confidence) if self.track.confidence is not None else 0.8


def identity_map(session: Session, track_ids: set[int], min_state: str = "likely") -> dict[int, IdentityLink]:
    """Track entity id -> what it was identified as (face first, else registered vehicle, else plate)."""
    if not track_ids:
        return {}
    R = RelationRelationship
    rows = [r for r in session.scalars(_current(select(R).where(R.subject_id.in_(track_ids), R.relation_type.in_(IDENTITY_LINKS)), R)) if at_least(r.state, min_state)]
    plates = {r.object_id for r in rows if r.relation_type == "IDENTIFIED_BY_PLATE"}
    registered: dict[int, int] = {}
    if plates:
        for r in session.scalars(_current(select(R).where(R.subject_id.in_(plates), R.relation_type == "REGISTERED_AS"), R)):
            if at_least(r.state, "likely"):
                registered[r.subject_id] = r.object_id
    out: dict[int, IdentityLink] = {}
    for r in sorted(rows, key=lambda x: (x.relation_type != "IDENTIFIED_AS", -x.confidence)):
        cur = out.get(r.subject_id)
        if r.relation_type == "IDENTIFIED_AS":
            target, basis = r.object_id, "face"
        else:
            target = registered.get(r.object_id, r.object_id)
            basis = "registered" if r.object_id in registered else "plate"
        if cur is None:
            out[r.subject_id] = IdentityLink(target, basis, float(r.confidence), [r.id], [r.uid], "annotation" if "annotation" in (r.sources or []) else "module")
        elif cur.subject_id == target:
            cur.link_ids.append(r.id)
            cur.link_uids.append(r.uid)
            cur.confidence = max(cur.confidence, float(r.confidence))
    return out


def build_sightings(session: Session, tracks: list[RelationEntity], idents: dict[int, IdentityLink], loc: LocationGraph) -> list[Sighting]:
    ids = {t.id for t in tracks}
    if not ids:
        return []
    R, Ob = RelationRelationship, RelationObservation
    places: dict[int, list[RelationRelationship]] = defaultdict(list)
    for r in session.scalars(_current(select(R).where(R.subject_id.in_(ids), R.relation_type.in_(JOURNEY_TYPES)), R).order_by(R.start_at, R.id)):
        if at_least(r.state, "possible"):
            places[r.subject_id].append(r)
    obj_ids = {r.object_id for rs in places.values() for r in rs}
    keys = {e.id: e.key for e in session.scalars(select(RelationEntity).where(RelationEntity.id.in_(obj_ids)))} if obj_ids else {}
    appeared: dict[int, RelationObservation] = {}
    gone: dict[int, RelationObservation] = {}
    for o in session.scalars(_current(select(Ob).where(Ob.entity_id.in_(ids), Ob.observation_type.in_(("appeared", "disappeared"))), Ob).order_by(Ob.at, Ob.id)):
        if o.observation_type == "appeared":
            appeared.setdefault(o.entity_id, o)
        else:
            gone[o.entity_id] = o
    out: list[Sighting] = []
    for t in tracks:
        if t.first_seen is None or t.last_seen is None:
            continue
        s = Sighting(track=t, identity=idents.get(t.id), camera_id=t.camera_id, run_id=t.run_id, experiment_id=t.experiment_id,
                     object_class=(t.meta or {}).get("object_class", ""), first_at=_utc(t.first_seen), last_at=_utc(t.last_seen),
                     first_media=t.first_media_s, last_media=t.last_media_s, places=places.get(t.id, []), appeared=appeared.get(t.id), disappeared=gone.get(t.id))
        entries = [r for r in s.places if r.relation_type in ENTRY_TYPES]
        exits = [r for r in s.places if r.relation_type in EXIT_TYPES]
        if entries:
            s.entry_rel = entries[0]
            s.entry_key = keys.get(entries[0].object_id)
            s.entry_node = loc.resolve_key(s.entry_key)
        if exits:
            s.exit_rel = exits[-1]
            s.exit_key = keys.get(exits[-1].object_id)
            s.exit_node = loc.resolve_key(s.exit_key)
        for r in s.places:
            n = loc.resolve_key(keys.get(r.object_id))
            if n is not None:
                s.nodes.add(n)
        cn = loc.by_camera.get(s.camera_id) if s.camera_id is not None else None
        if cn is not None and not s.nodes:
            s.nodes |= loc.coverage(s.camera_id)
        out.append(s)
    out.sort(key=lambda x: (x.first_at, x.track.id))
    return out


# ---------------------------------------------------------------------------- scoring
@dataclass
class TimeFit:
    certainty: float
    lo: float | None
    hi: float | None
    source: str
    flags: list[str]


def time_fit(gap: float, travel: Travel, s: CrossCameraSettings, overlap: bool = False) -> TimeFit:
    tol = s.overlap_tolerance_s
    if travel.known:
        lo, hi, src = float(travel.min_s), float(travel.max_s), travel.source
    elif travel.min_s is not None:
        lo, hi, src = float(travel.min_s), max(s.default_max_s, float(travel.min_s) * 3), "partial"
    else:
        lo, hi, src = 0.0, s.default_max_s, "unknown"
    if overlap:
        lo = min(lo, 0.0)
    known = SOURCE_CERTAINTY.get(src, 0.7)
    early = 30.0 if overlap else tol
    flags: list[str] = []
    if gap < -early:
        flags.append("simultaneous")
        c = 0.1
    elif lo > tol and gap < lo * s.too_fast_factor:
        flags.append("implausible_time")
        c = 0.15
    elif lo > tol and gap < lo - tol:
        flags.append("faster_than_expected")
        c = 0.5 + 0.5 * max(0.0, gap) / lo
    elif gap <= hi + tol:
        c = 1.0
    else:
        flags.append("slower_than_expected")
        c = max(0.25, hi / max(gap, 1e-6))
    return TimeFit(round(min(1.0, c * known), 4), lo, hi, src, flags)


@dataclass
class TransitionResult:
    a: Sighting
    b: Sighting
    gap: float
    topo: TopologyEvidence
    fit: TimeFit
    components: Components
    confidence: float
    state: str
    sensors: list[dict]
    flags: list[str]
    uid: str

    @property
    def basis(self) -> str:
        return self.b.basis if self.b.identity else "anonymous"

    @property
    def annotated(self) -> bool:
        """A reviewer, not a recognition module, identified at least one of the two sightings."""
        return bool(self.a.identity and self.b.identity and "annotation" in (self.a.identity.method, self.b.identity.method))


def _sensor_evidence(session: Session, loc: LocationGraph, topo: TopologyEvidence, start: datetime, end: datetime) -> tuple[list[dict], list[str]]:
    """Presence or movement reported by sensors placed on the way between the two cameras."""
    on_way = set(topo.path) | set(topo.via)
    sensors = {}
    for nid, n in loc.nodes.items():
        if n.kind == "sensor" and n.sensor_id and (nid in on_way or n.parent_id in on_way):
            sensors[E.sensor_key(n.sensor_id)] = n
    if not sensors:
        return [], []
    ents = {e.id: e for e in session.scalars(select(RelationEntity).where(RelationEntity.key.in_(list(sensors))))}
    if not ents:
        return [], []
    Ob = RelationObservation
    out, uids = [], []
    for o in session.scalars(select(Ob).where(Ob.entity_id.in_(list(ents)), Ob.observation_type == "sensor", Ob.at >= start - timedelta(seconds=2), Ob.at <= end + timedelta(seconds=2)).order_by(Ob.at)):
        v = o.value or {}
        if v.get("kind") in ("presence", "movement") and v.get("value"):
            node = sensors[ents[o.entity_id].key]
            out.append({"observation_id": o.id, "sensor_id": v.get("sensor_id"), "node_id": node.id, "node": node.name, "at": o.at.isoformat(), "kind": v.get("kind"), "value": v.get("value")})
            uids.append(o.uid)
    return out[:20], uids[:20]


def score(session: Session, loc: LocationGraph, s: CrossCameraSettings, a: Sighting, b: Sighting) -> TransitionResult:
    gap = (b.first_at - a.last_at).total_seconds()
    topo = loc.camera_transition(a.camera_id, b.camera_id, a.exit_node, b.entry_node, b.object_class or a.object_class)
    fit = time_fit(gap, topo.travel, s, overlap=topo.kind == "overlap")
    sensors, _ = _sensor_evidence(session, loc, topo, a.last_at, b.first_at)
    anonymous = a.identity is None or b.identity is None
    recog = None if anonymous else min(a.identity.confidence, b.identity.confidence)
    comp = Components(tracking=min(a.track_conf, b.track_conf), recognition=recog, spatial=topo.certainty, temporal=fit.certainty,
                      sensor=0.95 if sensors else None, support=(2 if anonymous else 8) + 2 * len(sensors))
    conf = combine(comp)
    if anonymous:
        conf = min(conf, ANON_CAP)
    flags = list(fit.flags)
    if topo.wrong_way:
        flags.append("wrong_way")
    if topo.kind == "unconnected":
        flags.append("unconnected")
    return TransitionResult(a, b, gap, topo, fit, comp, conf, state_for(conf), sensors, flags, stable_uid("cc", a.track.key, b.track.key))


# ---------------------------------------------------------------------------- text
class Namer:
    """Anonymous names for stored text: never a person's name or a plate."""

    def __init__(self, session: Session, loc: LocationGraph) -> None:
        self.loc = loc
        self.cameras = {c.id: c.name for c in session.scalars(select(Camera))}

    def camera(self, cid: int | None) -> str:
        if cid is None:
            return "an unknown camera"
        return self.cameras.get(cid) or f"camera {cid}"

    def node(self, nid: int | None) -> str:
        if nid is None or nid not in self.loc.nodes:
            return ""
        return self.loc.nodes[nid].name

    def where(self, cid: int | None, nid: int | None) -> str:
        n = self.node(nid)
        return f"{self.camera(cid)} / {n}" if n else self.camera(cid)

    @staticmethod
    def who(s: Sighting) -> str:
        if s.identity is None:
            return s.track.label or "An object"
        if s.identity.method == "annotation":
            return "An annotated person" if s.identity.basis == "face" else "An annotated vehicle"
        return {"face": "A recognized person", "plate": "A vehicle with a read plate", "registered": "A registered vehicle"}.get(s.identity.basis, "An identity")


def _range(lo: float | None, hi: float | None) -> str:
    if lo is None and hi is None:
        return "unknown"
    return f"{(lo or 0):.0f}–{hi:.0f} s" if hi is not None else f"at least {(lo or 0):.0f} s"


def transition_reason(t: TransitionResult, nm: Namer) -> str:
    basis = {"face": "the face module identified the same enrolled person on both cameras", "plate": "the plate module read the same plate on both cameras",
             "registered": "both plate reads belong to the same registered vehicle", "anonymous": "timing alone (a single candidate on both sides, no identity)"}[t.basis]
    if t.annotated:
        basis = f"a reviewer identified the same {'person' if t.basis == 'face' else 'vehicle'} on both cameras (manual annotation, not a recognition module)"
    src = {"link": "configured on the link", "path": "sum of the links on the way", "distance": "estimated from the plan distance", "partial": "partly configured",
           "unknown": "no travel time configured"}.get(t.fit.source, t.fit.source)
    gap = f"{t.gap:.0f} s later" if t.gap >= 0 else f"{-t.gap:.0f} s before the first camera lost it"
    parts = [f"Linked because {basis}.", f"Seen on {nm.where(t.b.camera_id, t.b.entry_node)} {gap} than on {nm.where(t.a.camera_id, t.a.exit_node)}.",
             f"Expected travel time: {_range(t.fit.lo, t.fit.hi)} ({src}).", f"Topology: {t.topo.note or t.topo.kind}."]
    if t.topo.via:
        parts.append("On the way: " + ", ".join(nm.node(v) for v in t.topo.via) + ".")
    if t.sensors:
        parts.append(f"{len(t.sensors)} sensor report{'s' if len(t.sensors) != 1 else ''} on the way agree{'s' if len(t.sensors) == 1 else ''}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------- rebuild
@dataclass
class RebuildResult:
    transitions: int = 0
    withdrawn: int = 0
    relationships: int = 0
    deviations: int = 0
    new_deviations: list[int] = field(default_factory=list)
    subjects: int = 0

    def to_dict(self) -> dict:
        return {"transitions": self.transitions, "withdrawn": self.withdrawn, "relationships": self.relationships, "deviations": self.deviations, "subjects": self.subjects}


def _journeys(sightings: list[Sighting], brk: float) -> list[list[Sighting]]:
    out: list[list[Sighting]] = []
    end: datetime | None = None
    for s in sightings:
        if not out or end is None or (s.first_at - end).total_seconds() > brk:
            out.append([s])
            end = s.last_at
        else:
            out[-1].append(s)
            end = max(end, s.last_at)
    return out


def _predecessor(prev: list[Sighting], s: Sighting) -> Sighting | None:
    """The sighting just before this one: the latest last-seen among those that started earlier."""
    best = None
    for p in prev:
        if p.track.id == s.track.id or p.first_at > s.first_at or (p.first_at == s.first_at and p.track.id > s.track.id):
            continue
        if best is None or p.last_at > best.last_at:
            best = p
    return best


class Correlator:
    """Recomputes the cross-camera results of a set of runs."""

    def __init__(self, session: Session, loc: LocationGraph, settings: CrossCameraSettings, now: datetime | None = None) -> None:
        self.s = session
        self.loc = loc
        self.cfg = settings
        self.now = now or datetime.now(UTC)
        self.nm = Namer(session, loc)
        self.res = RebuildResult()
        self._rels: dict[str, dict] = {}
        self._devs: dict[str, dict] = {}
        self._trans: dict[str, TransitionResult] = {}
        self._mentions: dict[str, dict] = {}

    # ------------------------------------------------------------ scope
    def _tracks_of_runs(self, run_ids: set[int]) -> list[RelationEntity]:
        if not run_ids:
            return []
        return list(self.s.scalars(select(RelationEntity).where(RelationEntity.run_id.in_(run_ids), RelationEntity.entity_type.in_(list(E.TRACK_TYPES)))))

    def _tracks_of_subject(self, subject_id: int, t0: datetime, t1: datetime) -> list[RelationEntity]:
        """Tracks identified as this subject (face link, plate link, plate of a registered vehicle) in a window."""
        R = RelationRelationship
        targets = {subject_id}
        subj = self.s.get(RelationEntity, subject_id)
        if subj is not None and subj.entity_type == "registered_vehicle":
            targets |= set(self.s.scalars(_current(select(R.subject_id).where(R.object_id == subject_id, R.relation_type == "REGISTERED_AS"), R)))
        track_ids = set(self.s.scalars(_current(select(R.subject_id).where(R.object_id.in_(targets), R.relation_type.in_(IDENTITY_LINKS)), R)))
        if not track_ids:
            return []
        E_ = RelationEntity
        return list(self.s.scalars(select(E_).where(E_.id.in_(track_ids), E_.last_seen >= t0, E_.first_seen <= t1)))

    # ------------------------------------------------------------ main
    def rebuild(self, run_ids: set[int], subjects: set[int] | None = None) -> RebuildResult:
        cfg = self.cfg
        if not cfg.enabled:
            return self.res  # switched off: stored results stay as they are
        base_tracks = self._tracks_of_runs(run_ids)
        idents = identity_map(self.s, {t.id for t in base_tracks}, cfg.min_identity_state)
        scope_subjects = set(subjects) if subjects is not None else {i.subject_id for i in idents.values()}
        anchored_runs = set(run_ids)
        # transitions that start in these runs end in later runs: those depend on them too
        T = CrossCameraTransition
        dep_times: list[datetime] = []
        for to_run, subj, left, arrived in self.s.execute(select(T.to_run_id, T.subject_id, T.left_at, T.arrived_at).where(T.from_run_id.in_(run_ids), T.status == "active")).all():
            if to_run is not None and (subjects is None or subj in subjects):
                anchored_runs.add(to_run)
                scope_subjects.add(subj)
                dep_times += [_utc(left), _utc(arrived)]
        per_subject: dict[int, list[Sighting]] = {}
        if cfg.enabled:
            firsts = [_utc(t.first_seen) for t in base_tracks if t.first_seen] + dep_times
            lasts = [_utc(t.last_seen) for t in base_tracks if t.last_seen] + dep_times
            if firsts:
                t0 = min(firsts) - timedelta(hours=cfg.lookback_hours)
                t1 = max(lasts) + timedelta(seconds=cfg.journey_break_s)
                for sid in sorted(scope_subjects):
                    tracks = self._tracks_of_subject(sid, t0, t1)
                    ids = identity_map(self.s, {t.id for t in tracks}, cfg.min_identity_state)
                    tracks = [t for t in tracks if t.id in ids and ids[t.id].subject_id == sid]
                    sights = build_sightings(self.s, tracks, ids, self.loc)
                    per_subject[sid] = sights
                    # later runs of this subject depend on these sightings (their predecessor may change)
                    base_first = min(firsts)
                    anchored_runs |= {x.run_id for x in sights if x.run_id is not None and x.first_at >= base_first}
        self.res.subjects = len(per_subject)
        for sid, sights in per_subject.items():
            self._subject(sid, sights, anchored_runs)
        if cfg.enabled and cfg.anonymous and subjects is None:
            self._anonymous(base_tracks, idents, set(run_ids))
        # a whole-run rebuild also drops rows of identities the run no longer has
        self._write(anchored_runs, scope_subjects, set(run_ids) if subjects is None else set())
        return self.res

    # ------------------------------------------------------------ one identity
    def _subject(self, sid: int, sights: list[Sighting], anchored_runs: set[int]) -> None:
        cfg = self.cfg
        journeys = _journeys(sights, cfg.journey_break_s)
        for journey in journeys:
            history = self._history(sid, journey[0].first_at) if cfg.anomalies else {"journeys": 0}
            entered_ok = False
            reported_restricted = False
            for i, s in enumerate(journey):
                anchored = s.run_id in anchored_runs
                prev = _predecessor(journey[:i], s)
                if anchored:
                    self._seen_at(s)
                entry = self._entry_node(s)
                if entry is not None:
                    entered_ok = True
                if i == 0 and entry is not None and anchored:
                    self._site_rel(s, "ENTERED_SITE_AT", entry, s.first_at, s.first_media)
                if i == len(journey) - 1 and anchored:
                    ex = s.exit_node if s.exit_node is not None and self.loc.nodes[s.exit_node].is_entry else None
                    if ex is not None and (self.now - s.last_at).total_seconds() > 0:
                        self._site_rel(s, "EXITED_SITE_AT", ex, s.last_at, s.last_media)
                if cfg.anomalies and anchored and not reported_restricted and not entered_ok:
                    r = self._restricted(s)
                    if r is not None:
                        reported_restricted = True
                        self._deviation("restricted_without_entry", s, None, None, r,
                                        f"{self.nm.who(s)} was observed in {self.nm.node(r)} (restricted) on {self.nm.camera(s.camera_id)} without an earlier sighting at an entry point of the site in this journey.",
                                        {"node_id": r})
                if prev is None or not anchored or prev.camera_id == s.camera_id:
                    continue
                t = score(self.s, self.loc, cfg, prev, s)
                self._transition(t)
                if cfg.anomalies:
                    self._transition_deviations(t, history)

    def _entry_node(self, s: Sighting) -> int | None:
        for n in ([s.entry_node] if s.entry_node is not None else []) + sorted(s.nodes):
            if n in self.loc.nodes and self.loc.nodes[n].is_entry:
                return n
        return None

    def _restricted(self, s: Sighting) -> int | None:
        for n in sorted(s.nodes):
            chain = self.loc.ancestors(n)
            hit = next((x for x in reversed(chain) if self.loc.nodes[x].restricted), None)
            if hit is None:
                continue
            site = self.loc.site_of(hit)
            scope = self.loc.subtree(site) if site is not None else set(self.loc.nodes)
            if any(self.loc.nodes[x].is_entry for x in scope):
                return hit
        return None

    def _history(self, sid: int, before: datetime) -> dict:
        """Earlier journeys of this identity: which camera followed which."""
        T = CrossCameraTransition
        rows = list(self.s.scalars(select(T).where(T.subject_id == sid, T.status == "active", T.arrived_at < before).order_by(T.arrived_at)))
        journeys: list[set[tuple]] = []
        last: datetime | None = None
        for r in rows:
            if last is None or (_utc(r.left_at) - last).total_seconds() > self.cfg.journey_break_s:
                journeys.append(set())
            journeys[-1].add((r.from_camera_id, r.to_camera_id))
            last = _utc(r.arrived_at)
        pairs: dict[tuple, int] = defaultdict(int)
        nexts: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        for j in journeys:
            for p in j:
                pairs[p] += 1
                nexts[p[0]][p[1]] += 1
        return {"journeys": len(journeys), "pairs": pairs, "nexts": nexts}

    # ------------------------------------------------------------ anonymous
    def _anonymous(self, tracks: list[RelationEntity], idents: dict[int, IdentityLink], run_ids: set[int]) -> None:
        anon = [t for t in tracks if t.id not in idents]
        if not anon:
            return
        placed = set(self.loc.by_camera)
        cams_b = {t.camera_id for t in anon if t.camera_id in placed}
        if not cams_b:
            return
        # candidates: anonymous tracks on cameras directly linked to these, in the travel window
        firsts = [_utc(t.first_seen) for t in anon if t.first_seen]
        if not firsts:
            return
        t0 = min(firsts) - timedelta(seconds=self.cfg.default_max_s)
        t1 = max(_utc(t.last_seen) for t in anon if t.last_seen) + timedelta(seconds=self.cfg.default_max_s)
        E_ = RelationEntity
        pool = list(self.s.scalars(select(E_).where(E_.entity_type.in_(list(E.TRACK_TYPES)), E_.camera_id.in_(list(placed)), E_.last_seen >= t0, E_.first_seen <= t1)))
        pool_ident = identity_map(self.s, {t.id for t in pool}, "possible")
        pool = [t for t in pool if t.id not in pool_ident]
        sights = {s.track.id: s for s in build_sightings(self.s, pool, {}, self.loc)}
        by_cam: dict[int, list[Sighting]] = defaultdict(list)
        for s in sights.values():
            by_cam[s.camera_id].append(s)

        def window(a: Sighting, b_cam: int) -> tuple[TopologyEvidence, float, float] | None:
            topo = self.loc.camera_transition(a.camera_id, b_cam, object_class=a.object_class)
            if topo.kind not in ("direct", "overlap") or topo.wrong_way or not topo.travel.known:
                return None
            tol = self.cfg.overlap_tolerance_s
            lo = (topo.travel.min_s or 0.0) - (30.0 if topo.kind == "overlap" else tol)
            return topo, lo, (topo.travel.max_s or 0.0) + tol

        def compatible(a: Sighting, b: Sighting) -> bool:
            return E.track_type(a.object_class) == E.track_type(b.object_class)

        for tb in anon:
            b = sights.get(tb.id)
            if b is None or b.run_id not in run_ids:
                continue
            cands = []
            for cam, items in by_cam.items():
                if cam == b.camera_id:
                    continue
                for a in items:
                    if not compatible(a, b):
                        continue
                    w = window(a, b.camera_id)
                    if w is None:
                        continue
                    gap = (b.first_at - a.last_at).total_seconds()
                    if w[1] <= gap <= w[2]:
                        cands.append(a)
            if len(cands) != 1:
                continue
            a = cands[0]
            # the other side must be unambiguous too
            w = window(a, b.camera_id)
            rivals = [x for x in by_cam.get(b.camera_id, []) if compatible(a, x) and w[1] <= (x.first_at - a.last_at).total_seconds() <= w[2]]
            if len(rivals) != 1:
                continue
            t = score(self.s, self.loc, self.cfg, a, b)
            self._transition(t)

    # ------------------------------------------------------------ records
    def _mention_place(self, cid: int | None, nid: int | None) -> str:
        if nid is not None and nid in self.loc.nodes:
            n = self.loc.nodes[nid]
            if n.kind == "camera" and n.camera_id is not None:
                return self._mention_camera(n.camera_id)
            key = E.location_key(nid)
            self._mentions[key] = {"key": key, "type": "location", "source": "location", "label": n.name, "metadata": {"node_id": nid, "kind": n.kind, "path": self.loc.path_label(nid)}}
            return key
        return self._mention_camera(cid)

    def _mention_camera(self, cid: int | None) -> str:
        key = E.camera_key(cid or 0)
        cn = self.loc.by_camera.get(cid) if cid is not None else None
        meta = {"camera_id": cid}
        if cn is not None:
            meta.update({"node_id": cn, "path": self.loc.path_label(cn)})
        self._mentions[key] = {"key": key, "type": "camera", "source": "camera", "label": self.nm.camera(cid), "metadata": meta}
        return key

    def _rel(self, uid: str, rtype: str, subject_key: str, object_key: str, start: datetime, end: datetime | None, s: Sighting, comp: Components, conf: float, reason: str,
             metrics: dict, support_obs: list[str], support_rels: list[str], sources: list[str], start_media: float | None = None, end_media: float | None = None) -> None:
        self._rels[uid] = {
            "uid": uid, "type": rtype, "subject": subject_key, "object": object_key, "start_at": start, "end_at": end, "start_media_s": start_media, "end_media_s": end_media,
            "run_id": s.run_id, "experiment_id": s.experiment_id, "camera_id": s.camera_id, "components": comp.to_dict(), "confidence": conf, "state": state_for(conf),
            "reason": reason, "metrics": {**metrics, "anchor_track": s.track.id}, "sources": sources, "support": [u for u in support_obs if u], "support_relations": [u for u in support_rels if u],
        }

    def _subject_key(self, s: Sighting) -> str:
        return self.s.get(RelationEntity, s.subject_id).key

    def _seen_at(self, s: Sighting) -> None:
        if s.identity is None:
            return
        comp = Components(tracking=s.track_conf, recognition=s.identity.confidence, support=8)
        conf = combine(comp)
        cam = self._mention_camera(s.camera_id)
        where = self.nm.where(s.camera_id, s.entry_node)
        self._rel(stable_uid("seen", s.track.key), "SEEN_AT", self._subject_key(s), cam, s.first_at, s.last_at, s, comp, conf,
                  f"{self.nm.who(s)} was seen by {where} ({s.track.label}) from {s.first_at:%H:%M:%S} to {s.last_at:%H:%M:%S} UTC.",
                  {"track": s.track.key, "camera_id": s.camera_id, "node_id": self.loc.by_camera.get(s.camera_id)},
                  [s.appeared.uid if s.appeared else "", s.disappeared.uid if s.disappeared else ""], s.identity.link_uids, [s.basis], s.first_media, s.last_media)

    def _site_rel(self, s: Sighting, rtype: str, node: int, at: datetime, media: float | None) -> None:
        if s.identity is None:
            return
        comp = Components(tracking=s.track_conf, recognition=s.identity.confidence, spatial=0.95, support=8)
        conf = combine(comp)
        place = self._mention_place(s.camera_id, node)
        verb = "entered" if rtype == "ENTERED_SITE_AT" else "left"
        rel = s.entry_rel if rtype == "ENTERED_SITE_AT" else s.exit_rel
        self._rel(stable_uid(rtype, s.track.key), rtype, self._subject_key(s), place, at, at, s, comp, conf,
                  f"First sighting of the journey at {self.nm.node(node)}, an entry point of the location model: {self.nm.who(s).lower()} {verb} the site there." if rtype == "ENTERED_SITE_AT"
                  else f"Last sighting of the journey at {self.nm.node(node)}, an entry point of the location model.",
                  {"node_id": node, "track": s.track.key}, [], [*(s.identity.link_uids), rel.uid if rel else ""], [s.basis, "topology"], media, media)

    def _transition(self, t: TransitionResult) -> None:
        self._trans[t.uid] = t
        a, b = t.a, t.b
        reason = transition_reason(t, self.nm)
        m = {"transition_uid": t.uid, "from_camera_id": a.camera_id, "to_camera_id": b.camera_id, "gap_s": round(t.gap, 2), "expected_min_s": t.fit.lo, "expected_max_s": t.fit.hi,
             "expected_source": t.fit.source, "topology": t.topo.kind, "hops": t.topo.hops, "flags": t.flags, "from_track": a.track.key, "to_track": b.track.key}
        subj = self._subject_key(b) if b.identity else a.track.key
        src = self._mention_place(a.camera_id, a.exit_node)
        dst = self._mention_place(b.camera_id, b.entry_node)
        sources = [t.basis, "topology", *(["sensor"] if t.sensors else [])]
        sup_obs = [a.disappeared.uid if a.disappeared else "", b.appeared.uid if b.appeared else ""]
        _, sensor_uids = _sensor_evidence(self.s, self.loc, t.topo, a.last_at, b.first_at) if t.sensors else ([], [])
        sup_rels = [*(a.identity.link_uids if a.identity else []), *(b.identity.link_uids if b.identity else []), a.exit_rel.uid if a.exit_rel else "", b.entry_rel.uid if b.entry_rel else ""]
        conf = t.confidence
        self._rel(stable_uid("from", t.uid), "MOVED_FROM", subj, src, a.last_at, b.first_at, b, t.components, conf, reason, m, sup_obs + sensor_uids, sup_rels, sources, a.last_media, b.first_media)
        self._rel(stable_uid("to", t.uid), "MOVED_TO", subj, dst, a.last_at, b.first_at, b, t.components, conf, reason, m, sup_obs + sensor_uids, sup_rels, sources, a.last_media, b.first_media)
        for v in t.topo.via:
            if v in self.loc.nodes and self.loc.nodes[v].kind != "camera":
                place = self._mention_place(None, v)
                self._rel(stable_uid("through", t.uid, v), "MOVED_THROUGH", subj, place, a.last_at, b.first_at, b, t.components, conf,
                          f"{self.nm.node(v)} lies on the way from {self.nm.camera(a.camera_id)} to {self.nm.camera(b.camera_id)} in the location model; the entity was not observed there directly. " + reason,
                          {**m, "node_id": v}, sup_obs + sensor_uids, sup_rels, [*sources, "inferred-path"], a.last_media, b.first_media)
        if t.basis == "anonymous":
            self._rel(stable_uid("cont", t.uid), "CONTINUED_AS", a.track.key, b.track.key, a.last_at, b.first_at, b, t.components, conf, reason, m, sup_obs, sup_rels, sources, a.last_media, b.first_media)

    def _transition_deviations(self, t: TransitionResult, history: dict) -> None:
        a, b = t.a, t.b
        who = self.nm.who(b)
        base = {"from_camera_id": a.camera_id, "to_camera_id": b.camera_id, "gap_s": round(t.gap, 1), "transition_uid": t.uid}
        if "implausible_time" in t.flags:
            self._deviation("implausible_time", b, a, t, None,
                            f"{who} was seen on {self.nm.where(b.camera_id, b.entry_node)} {t.gap:.0f} s after {self.nm.where(a.camera_id, a.exit_node)}; the expected travel time is {_range(t.fit.lo, t.fit.hi)}.",
                            {**base, "expected_min_s": t.fit.lo, "expected_max_s": t.fit.hi, "expected_source": t.fit.source})
        if "unconnected" in t.flags:
            self._deviation("unconnected", b, a, t, None, f"{who} moved from {self.nm.camera(a.camera_id)} to {self.nm.camera(b.camera_id)}, which the location model does not connect.", base)
        if "wrong_way" in t.flags:
            self._deviation("wrong_way", b, a, t, None, f"{who} moved from {self.nm.camera(a.camera_id)} to {self.nm.camera(b.camera_id)} against a one-way link of the location model.", base)
        if "simultaneous" in t.flags:
            self._deviation("simultaneous", b, a, t, None,
                            f"{who} was on {self.nm.camera(b.camera_id)} {-t.gap:.0f} s before {self.nm.camera(a.camera_id)} lost it, and the cameras' views do not overlap: one of the two identifications may be wrong.", base)
        n = history["journeys"]
        if b.identity is not None and n >= self.cfg.history_min_journeys:
            pair = (a.camera_id, b.camera_id)
            k = history["pairs"].get(pair, 0)
            if k / n < self.cfg.history_rare_share:
                nexts = history["nexts"].get(a.camera_id) or {}
                usual = max(nexts.items(), key=lambda kv: kv[1]) if nexts else None
                tail = f" After {self.nm.camera(a.camera_id)} it usually went to {self.nm.camera(usual[0])} ({usual[1]} of {n})." if usual else ""
                self._deviation("unusual_sequence", b, a, t, None,
                                f"{who} moved {self.nm.camera(a.camera_id)} → {self.nm.camera(b.camera_id)}, a move seen in {k} of {n} earlier journeys.{tail}",
                                {**base, "journeys": n, "count": k, "usual_camera_id": usual[0] if usual else None})

    def _deviation(self, kind: str, s: Sighting, prev: Sighting | None, t: TransitionResult | None, node: int | None, text: str, metrics: dict) -> None:
        recog = s.identity.confidence if s.identity else None
        spatial = 0.9 if kind in ("unconnected", "wrong_way", "restricted_without_entry") else (t.topo.certainty if t else 0.8)
        temporal = SOURCE_CERTAINTY.get(t.fit.source, 0.7) if (t and kind == "implausible_time") else 1.0
        comp = Components(tracking=s.track_conf, recognition=recog, spatial=max(spatial, 0.6), temporal=temporal, support=6)
        conf = combine(comp)
        if s.identity is None:
            conf = min(conf, ANON_CAP)
        roles = {"subject": self._subject_key(s)}
        if prev is not None:
            roles["from"] = self._mention_place(prev.camera_id, prev.exit_node)
        roles["to"] = self._mention_place(s.camera_id, node if node is not None else s.entry_node)
        uid = stable_uid("dev", kind, t.uid if t else s.track.key)
        start = prev.last_at if prev is not None else s.first_at
        self._devs[uid] = {
            "uid": uid, "kind": kind, "label": DEVIATION_LABELS[kind], "run_id": s.run_id, "experiment_id": s.experiment_id, "camera_id": s.camera_id, "start_at": start, "end_at": s.first_at,
            "start_media_s": prev.last_media if prev is not None and prev.run_id == s.run_id else s.first_media, "end_media_s": s.first_media, "confidence": conf, "state": state_for(conf),
            "description": text, "roles": roles, "metrics": {**metrics, "type": kind, "basis": s.basis, "anchor_track": s.track.id, "subject_id": s.subject_id, "track_id": E.parse_track_ref(s.track.ref)[1] if E.parse_track_ref(s.track.ref) else None},
            "support_relations": [u for u in ([stable_uid("to", t.uid)] if t else []) + (s.identity.link_uids if s.identity else [])],
            "support": [u for u in [s.appeared.uid if s.appeared else ""] if u],
        }

    # ------------------------------------------------------------ write
    def _write(self, anchored_runs: set[int], subjects: set[int], full_runs: set[int]) -> None:
        s = self.s
        keys = set(self._mentions)
        for r in self._rels.values():
            keys |= {r["subject"], r["object"]}
        for d in self._devs.values():
            keys |= set(d["roles"].values())
        ids = ensure_entities(s, list(self._mentions.values()), keys, {})
        R, C, T = RelationRelationship, RelationCorrelated, CrossCameraTransition

        def in_scope(run_id: int | None, subject_id: int | None) -> bool:
            if run_id in full_runs:
                return True
            return run_id in anchored_runs and subject_id in subjects

        # relationships: replace everything this rebuild owns
        existing = {r.uid: r for r in s.scalars(select(R).where(R.rule_key == RULE_KEY, R.run_id.in_(anchored_runs)))} if anchored_runs else {}
        for uid, row in list(existing.items()):
            if uid not in self._rels and in_scope(row.run_id, row.subject_id):
                s.delete(row)
        for uid, r in self._rels.items():
            row = existing.get(uid)
            if row is None:
                row = s.scalar(select(R).where(R.uid == uid))
            if row is None:
                row = R(uid=uid, analysis_id=None, subject_id=ids[r["subject"]], relation_type=r["type"], object_id=ids[r["object"]])
                s.add(row)
            row.subject_id, row.object_id, row.relation_type = ids[r["subject"]], ids[r["object"]], r["type"]
            row.run_id, row.experiment_id, row.camera_id = r["run_id"], r["experiment_id"], r["camera_id"]
            row.start_at, row.end_at, row.start_media_s, row.end_media_s = r["start_at"], r["end_at"], r["start_media_s"], r["end_media_s"]
            row.status = "closed"
            row.confidence, row.state, row.components = r["confidence"], r["state"], r["components"]
            row.rule_key, row.rule_version, row.rule_name = RULE_KEY, 1, RULE_NAME
            row.reason, row.metrics, row.sources = r["reason"], r["metrics"], r["sources"]
            row.calibration = {"mode": "topology", "measure": "topology"}
            row.zone_id = None
        s.flush()
        self.res.relationships = len(self._rels)
        rel_ids = dict(s.execute(select(R.uid, R.id).where(R.uid.in_(list(self._rels)))).all()) if self._rels else {}
        _link_support(s, [(rel_ids[u], None, r["support"], r["support_relations"]) for u, r in self._rels.items() if u in rel_ids])

        # transitions: upsert; ones no longer supported are withdrawn (kept, with the reason)
        old = {t.uid: t for t in s.scalars(select(T).where(T.to_run_id.in_(anchored_runs)))} if anchored_runs else {}
        for uid, row in old.items():
            if uid not in self._trans and row.status == "active" and in_scope(row.to_run_id, row.subject_id):
                row.status = "withdrawn"
                row.reason = f"Withdrawn {self.now:%Y-%m-%d %H:%M} UTC: the sightings no longer support it (re-analysis, identity or topology change). Was: {row.reason}"[:4000]
                self.res.withdrawn += 1
        for uid, t in self._trans.items():
            row = old.get(uid) or s.scalar(select(T).where(T.uid == uid))
            subj = t.b.identity.subject_id if (t.b.identity and t.a.identity) else t.a.track.id
            vals = dict(
                subject_id=subj, basis=t.basis, from_track_id=t.a.track.id, to_track_id=t.b.track.id, from_camera_id=t.a.camera_id, to_camera_id=t.b.camera_id,
                from_run_id=t.a.run_id, to_run_id=t.b.run_id, from_node_id=t.a.exit_node, to_node_id=t.b.entry_node, from_place=t.a.exit_key, to_place=t.b.entry_key,
                left_at=t.a.last_at, arrived_at=t.b.first_at, left_media_s=t.a.last_media, arrived_media_s=t.b.first_media, gap_s=round(t.gap, 3),
                expected_min_s=t.fit.lo, expected_max_s=t.fit.hi if t.fit.source != "unknown" else None, expected_source=t.fit.source, topology=t.topo.kind,
                path=t.topo.path, hops=t.topo.hops, identity_confidence=(min(t.a.identity.confidence, t.b.identity.confidence) if (t.a.identity and t.b.identity) else None),
                components={**t.components.to_dict(), **({"identity_method": "annotation"} if t.annotated else {})},
                confidence=t.confidence, state=t.state, sensor_evidence=t.sensors, flags=t.flags,
                reason=transition_reason(t, self.nm), status="active",
            )
            if row is None:
                row = T(uid=uid, **vals)
                s.add(row)
            else:
                for k, v in vals.items():
                    setattr(row, k, v)
        self.res.transitions = len(self._trans)

        # deviations: replaced like relationships; new ones are reported
        old_devs = {c.uid: c for c in s.scalars(select(C).where(C.rule_key.like(f"{RULE_KEY}.%"), C.run_id.in_(anchored_runs)))} if anchored_runs else {}
        for uid, row in old_devs.items():
            if uid not in self._devs and in_scope(row.run_id, (row.metrics or {}).get("subject_id")):
                s.delete(row)
        s.flush()
        for uid, d in self._devs.items():
            row = old_devs.get(uid) or s.scalar(select(C).where(C.uid == uid))
            roles = {k: ids.get(v) for k, v in d["roles"].items()}
            if row is None:
                row = C(uid=uid, analysis_id=None, kind="deviation", published=False)
                s.add(row)
                s.flush()
                self.res.new_deviations.append(row.id)
            row.run_id, row.experiment_id, row.camera_id = d["run_id"], d["experiment_id"], d["camera_id"]
            row.event_type = row.label = d["label"]
            row.start_at, row.end_at, row.start_media_s, row.end_media_s = d["start_at"], d["end_at"], d["start_media_s"], d["end_media_s"]
            row.confidence, row.state, row.description = d["confidence"], d["state"], d["description"]
            row.rule_key, row.rule_version, row.rule_name = f"{RULE_KEY}.{d['kind']}", 1, "Cross-camera topology"
            row.roles, row.metrics, row.temporal = roles, d["metrics"], []
        s.flush()
        self.res.deviations = len(self._devs)
        dev_ids = dict(s.execute(select(C.uid, C.id).where(C.uid.in_(list(self._devs)))).all()) if self._devs else {}
        _link_support(s, [(None, dev_ids[u], d["support"], d["support_relations"]) for u, d in self._devs.items() if u in dev_ids])


def cleanup(session: Session) -> int:
    """Cross-camera rows whose tracks are gone (a deleted analysis or run)."""
    R = RelationRelationship
    T = CrossCameraTransition
    alive = set(session.scalars(select(T.uid)))
    n = 0
    for r in session.scalars(select(R).where(R.rule_key == RULE_KEY)):
        tu = (r.metrics or {}).get("transition_uid")
        anchor = (r.metrics or {}).get("anchor_track")
        if (tu and tu not in alive) or (anchor and session.get(RelationEntity, anchor) is None):
            session.delete(r)
            n += 1
    for c in session.scalars(select(RelationCorrelated).where(RelationCorrelated.rule_key.like(f"{RULE_KEY}.%"))):
        anchor = (c.metrics or {}).get("anchor_track")
        if anchor and session.get(RelationEntity, anchor) is None:
            session.delete(c)
            n += 1
    session.flush()
    return n


_ = (RelationSupport, LocationNode)
