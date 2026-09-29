"""The relationship engine: observations in, relationships and correlated events out.

One engine runs per run (inside the camera worker for live runs, or in the
API process when a stored run is analysed again). It is independent of the
detector, tracker and recognition models: it receives tracked positions,
the spatial engine's interactions, the rule engine's events and, through the
``EntityResolver`` interface, what a track resolved to. From those it

1. publishes normalized observations (appeared, entered, crossed, recognized...)
2. resolves identities without discarding tracks
   (``Track #182 IDENTIFIED_AS Employee-017``, ``Vehicle track #91
   IDENTIFIED_BY_PLATE <plate>``, ``<plate> REGISTERED_AS <vehicle>``)
3. forms place relationships (ENTERED, EXITED, CROSSED, USED_ROUTE,
   REMAINED_IN, MOVED_FROM / MOVED_TO, optionally OCCUPIED)
4. evaluates the configured relationship rules (spatial pairs, places,
   following through checkpoints, multi-step correlations)
5. scores every inferred relationship (``confidence``) and keeps its provenance.

Relationships are time-bounded: ``start`` when the condition was first met,
``end`` when it stopped (``None`` while it still holds). Everything the
engine produces is buffered and taken with ``drain()``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from pathscope.domain.entities import (
    STATUS_POSSIBLE,
    STATUS_RECOGNIZED,
    EntityRef,
)
from pathscope.domain.scene import VEHICLE_CLASSES, SceneDocument, ZoneObject
from pathscope.relationships import entities as E
from pathscope.relationships.confidence import (
    Components,
    at_least,
    combine,
    spatial_certainty,
    state_for,
)
from pathscope.relationships.correlation import (
    Fact,
    FollowMatch,
    Match,
    RouteFollower,
    SequenceMatcher,
)
from pathscope.relationships.observations import Observation, new_uid
from pathscope.relationships.relations import relation_type
from pathscope.relationships.rules import (
    CompiledRule,
    RelationExperimentSettings,
    RelationRuleDefinition,
    RoleFilter,
)
from pathscope.relationships.spatial import (
    Footprint,
    Metric,
    MotionHistory,
    closing_share,
    heading_difference,
)
from pathscope.spatial.engine import _snap_to_frame
from pathscope.spatial.geometry import point_in_polygon

BUILTIN_IDENTITY = ("builtin.identity", 1)
BUILTIN_PLACES = ("builtin.places", 1)
BUILTIN_NAMES = {"builtin.identity": "Identity resolution (built in)", "builtin.places": "Place relationships (built in)"}

ROUTE_OUTCOMES = {"UNKNOWN", "ABANDONED", "LOST_TRACK"}
GRACE_S = 10.0  # recognition may decide a few seconds after a condition was met
EDGE = 0.025  # a track that ends this close to the frame border may simply have walked out of view
KEEP_CLOSED_S = 900.0
MOVE_OVERLAP_S = 2.0  # entering the next zone this long before leaving the last still counts as moving on


@dataclass
class EngineContext:
    run_id: int
    camera_id: int | None
    experiment_id: int | None
    frame_width: int
    frame_height: int
    scene: SceneDocument | None = None
    scene_config_id: int | None = None
    scene_version: int | None = None
    plate_salt: bytes = b"pathscope"
    source: str = "live"  # live | replay
    # How vehicles are measured: box edge (live), stored width (replay) or a point
    footprint: str = "box edge"


@dataclass
class RelationRecord:
    uid: str
    type: str
    subject: str
    object: str
    start_t: float
    start_wall: float
    rule_key: str
    rule_version: int
    rule_name: str
    end_t: float | None = None
    end_wall: float | None = None
    status: str = "open"  # open | closed
    confidence: float = 0.0
    state: str = "insufficient"
    components: dict = field(default_factory=dict)
    reason: str = ""
    zone_id: str | None = None
    sources: list[str] = field(default_factory=lambda: ["rgb"])
    calibration: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    support: list[str] = field(default_factory=list)  # observation uids
    support_relations: list[str] = field(default_factory=list)  # relationship uids
    subject_tid: int | None = None
    object_tid: int | None = None
    # actions (record an ordinary event, webhooks) once the state is good enough
    act_min_state: str = "likely"
    act_label: str | None = None
    webhooks: list[str] = field(default_factory=list)
    record_event: bool = False
    acted: bool = False
    publish: dict | None = None
    fed_state: str | None = None  # the best state already given to correlation rules
    dirty: bool = True
    last_emit: float = -1e9

    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "type": self.type, "subject": self.subject, "object": self.object,
            "start_t": round(self.start_t, 3), "end_t": None if self.end_t is None else round(self.end_t, 3),
            "start_wall": self.start_wall, "end_wall": self.end_wall, "status": self.status,
            "confidence": round(self.confidence, 4), "state": self.state, "components": self.components,
            "rule_key": self.rule_key, "rule_version": self.rule_version, "rule_name": self.rule_name, "reason": self.reason,
            "zone_id": self.zone_id, "sources": list(self.sources), "calibration": self.calibration, "metrics": self.metrics,
            "support": list(self.support), "support_relations": list(self.support_relations), "publish": self.publish,
        }


@dataclass
class CorrelatedRecord:
    uid: str
    kind: str  # correlated | deviation
    label: str
    rule_key: str
    rule_version: int
    rule_name: str
    start_t: float
    end_t: float
    start_wall: float
    end_wall: float
    confidence: float
    state: str
    roles: dict[str, str]
    description: str
    support: list[str] = field(default_factory=list)
    support_relations: list[str] = field(default_factory=list)
    temporal: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    publish: dict | None = None

    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "kind": self.kind, "label": self.label, "rule_key": self.rule_key, "rule_version": self.rule_version, "rule_name": self.rule_name,
            "start_t": round(self.start_t, 3), "end_t": round(self.end_t, 3), "start_wall": self.start_wall, "end_wall": self.end_wall,
            "confidence": round(self.confidence, 4), "state": self.state, "roles": self.roles, "description": self.description,
            "support": list(self.support), "support_relations": list(self.support_relations), "temporal": self.temporal, "metrics": self.metrics,
            "publish": self.publish,
        }


@dataclass
class _Track:
    tid: int
    cls: str
    key: str
    first_t: float
    first_wall: float
    last_t: float
    last_wall: float
    fp: Footprint
    motion: MotionHistory = field(default_factory=MotionHistory)
    conf_sum: float = 0.0
    n: int = 0
    reacquired: int = 0
    hws: list[float] = field(default_factory=list)
    alive: bool = True
    entity: EntityRef | None = None
    entity_sig: tuple | None = None
    identity_rel: RelationRecord | None = None
    plate_rel: RelationRecord | None = None
    last_resolve: float = -1e9
    seen_now: bool = False

    @property
    def conf(self) -> float:
        return self.conf_sum / self.n if self.n else 0.5

    @property
    def label(self) -> str:
        kind = {"person_track": "Person", "vehicle_track": "Vehicle"}.get(E.track_type(self.cls), self.cls.capitalize() or "Object")
        return f"{kind} track #{self.tid}"

    @property
    def is_vehicle(self) -> bool:
        return self.cls in VEHICLE_CLASSES


@dataclass
class _Interval:
    """A condition held over time, tolerating short gaps."""

    start_t: float
    start_wall: float
    last_ok_t: float
    last_ok_wall: float
    n_ok: int = 0
    n_total: int = 0
    sum_d: float = 0.0
    min_d: float = math.inf
    max_d: float = 0.0
    lag_sum: float = 0.0
    record: RelationRecord | None = None
    touched: bool = False

    @property
    def duration(self) -> float:
        return self.last_ok_t - self.start_t

    @property
    def mean_d(self) -> float:
        return self.sum_d / self.n_ok if self.n_ok else math.inf


@dataclass
class _Edge:
    """Approach / move-away memory of one pair."""

    armed: bool = False
    ref_t: float = 0.0
    ref_wall: float = 0.0
    ref_d: float = 0.0
    ref_s: tuple[float, float] = (0.0, 0.0)
    ref_o: tuple[float, float] = (0.0, 0.0)


@dataclass
class _Pending:
    deadline_t: float
    check: Any  # (final: bool) -> bool | None
    emit: Any  # () -> None


@dataclass
class _RuleState:
    index: int
    rule: CompiledRule
    distance: float | None = None
    far: float | None = None
    pairs: dict[tuple[int, int], _Interval] = field(default_factory=dict)
    edges: dict[tuple[int, int], _Edge] = field(default_factory=dict)
    places: dict[tuple[int, str], _Interval] = field(default_factory=dict)
    dwell: dict[tuple[int, str], tuple[float, float, RelationRecord | None]] = field(default_factory=dict)
    left: dict[int, tuple[str, float]] = field(default_factory=dict)
    follows: dict[tuple[int, int], RelationRecord] = field(default_factory=dict)
    matcher: SequenceMatcher | None = None
    follower: RouteFollower | None = None
    symmetric_same: bool = False
    matches: int = 0

    @property
    def d(self) -> RelationRuleDefinition:
        return self.rule.definition


def _ev(e, name: str, default=None):
    if isinstance(e, dict):
        return e.get(name, default)
    return getattr(e, name, default)


class RelationEngine:
    def __init__(self, ctx: EngineContext, rules: list[CompiledRule], settings: RelationExperimentSettings, resolver=None) -> None:
        self.ctx = ctx
        self.settings = settings
        self.resolver = resolver
        self.metric = Metric(ctx.scene, ctx.frame_width, ctx.frame_height)
        self.sample_s = float(settings.sample_s)
        provided = set(resolver.provides()) if resolver is not None else set()
        self.rules: list[_RuleState] = []
        self.inactive: list[dict] = []
        for r in rules:
            d = r.definition
            if not d.enabled:
                continue
            missing = d.modules_needed - provided
            if missing:
                self.inactive.append({"key": r.key, "version": r.version, "name": d.name, "reason": f"needs {' and '.join(sorted(m + ' recognition' for m in missing))}, which is not active for this run"})
                continue
            st = _RuleState(len(self.rules), r)
            if d.uses_distance and d.distance is not None:
                st.distance = self.metric.threshold(d.distance.value, d.distance.unit, d.distance.fallback_fw)
                if st.distance is None:
                    self.inactive.append({"key": r.key, "version": r.version, "name": d.name, "reason": "the camera is not calibrated and the rule has no distance in frame widths for uncalibrated scenes"})
                    continue
                fd = d.from_distance
                st.far = self.metric.threshold(fd.value, fd.unit, fd.fallback_fw) if fd is not None else None
                if st.far is None:
                    st.far = st.distance * 2.5
            if d.kind == "sequence":
                st.matcher = SequenceMatcher(st.index, d, self._role_checker(d))
            elif d.kind == "follow_route":
                # the subject (A) follows the object (B)
                st.follower = RouteFollower(d, self._role_checker(d))
            if d.kind == "pair" and d.object is not None and d.subject.model_dump() == d.object.model_dump():
                rt = relation_type(d.relation or "")
                st.symmetric_same = bool(rt and rt.symmetric)
            self.rules.append(st)
        # zones for "in zone" conditions and "stops in"
        self._zones: dict[str, list[tuple[float, float]]] = {}
        self._objects: dict[str, Any] = {}
        self._routes: dict[str, Any] = {}
        if ctx.scene is not None:
            for o in ctx.scene.objects:
                self._objects[o.id] = o
                if isinstance(o, ZoneObject) and o.type != "ignore" and o.enabled:
                    self._zones[o.id] = _snap_to_frame([(p.x, p.y) for p in o.points])
            for r in ctx.scene.routes:
                self._routes[r.id] = r
        self._tracks: dict[int, _Track] = {}
        self._by_track: dict[int, list[RelationRecord]] = {}
        self._open_place: dict[tuple[int, str, str], RelationRecord] = {}  # (tid, zone, type) -> OCCUPIED / REMAINED_IN
        self._in_zone: dict[tuple[int, str], float] = {}  # built-in visits: entry time
        self._last_exit: dict[int, tuple[str, float, float]] = {}  # tid -> (zone, t, wall)
        self._registered: set[tuple[str, str]] = set()
        self._moves: set[tuple] = set()
        self._pending: list[_Pending] = []
        self._last_sample = -1e9
        self._last_prune = 0.0
        self._t = 0.0
        self._wall = 0.0
        # output buffers
        self._entities: dict[str, E.EntityMention] = {}
        self._dirty_entities: set[str] = set()
        self._observations: list[Observation] = []
        self._records: dict[str, RelationRecord] = {}
        self._correlated: list[CorrelatedRecord] = []
        self.stats: dict[str, Any] = {"observations": 0, "relationships": 0, "correlated": 0, "pairs_measured": 0, "tracks_capped": 0, "by_type": {}}
        self._place_entities()

    # ================================================================== helpers
    def _role_checker(self, d: RelationRuleDefinition):
        def ok(role: str, tid: int, object_class: str) -> bool:
            flt = d.subject if role == "A" else (d.object or RoleFilter())
            if not flt.class_ok(object_class):
                return False
            tr = self._tracks.get(tid)
            return self._verdict(flt, tr, tid, object_class, final=False) is not False

        return ok

    def _verdict(self, flt: RoleFilter, tr: _Track | None, tid: int = 0, cls: str = "", final: bool = False) -> bool | None:
        if not flt.subject.active:
            return True
        entity = tr.entity if tr is not None else None
        res = flt.evaluate(entity, tid or (tr.tid if tr else 0), cls or (tr.cls if tr else ""))
        if res is None and final:
            return flt.subject.mode == "anonymous"
        return res

    def _mention(self, key: str, type_id: str, source: str, label: str, t: float | None = None, wall: float | None = None, **kw) -> E.EntityMention:
        m = self._entities.get(key)
        if m is None:
            m = E.EntityMention(key=key, type=type_id, source=source, label=label, run_id=self.ctx.run_id if type_id in E.TRACK_TYPES else None,
                                camera_id=self.ctx.camera_id, experiment_id=self.ctx.experiment_id)
            self._entities[key] = m
            self._dirty_entities.add(key)
        for k, v in kw.items():
            if v is not None and getattr(m, k, None) != v:
                setattr(m, k, v)
                self._dirty_entities.add(key)
        if t is not None and wall is not None:
            before = (m.first_t, m.last_t)
            m.seen(t, wall)
            if before[0] is None:
                self._dirty_entities.add(key)
        return m

    def _place_entities(self) -> None:
        for oid, o in self._objects.items():
            if getattr(o, "type", "") == "ignore":
                continue
            key = E.place_key(self.ctx.camera_id, oid, o.type)
            self._mention(key, E.split_key(key)[0], "scene", o.name or oid, metadata={"object_id": oid, "object_type": o.type})
        for rid, r in self._routes.items():
            self._mention(E.route_key(self.ctx.camera_id, rid), "route", "scene", r.name or rid, metadata={"route_id": rid})

    def _place_key(self, object_id: str | None, object_type: str | None = None) -> str:
        o = self._objects.get(object_id or "")
        return E.place_key(self.ctx.camera_id, object_id or "", object_type or (o.type if o else "zone"))

    def _place_name(self, object_id: str | None) -> str:
        o = self._objects.get(object_id or "")
        return (o.name if o and o.name else object_id) or "?"

    def _observe(self, type_id: str, subject: str, t: float, wall: float, source: str = "rgb", obj: str | None = None, confidence: float | None = None, value: dict | None = None) -> Observation:
        o = Observation(type_id, subject, t, wall, source, obj, confidence, value or {})
        self._observations.append(o)
        self.stats["observations"] += 1
        return o

    def _calibration(self, points_only: bool = False) -> dict:
        return {**self.metric.describe(), "scene_config_id": self.ctx.scene_config_id, "scene_version": self.ctx.scene_version, "footprint": "point" if points_only else self.ctx.footprint}

    def _new_record(self, type_id: str, subject: str, obj: str, t: float, wall: float, rule: tuple[str, int, str], components: Components, reason: str, *, end_t: float | None = None, end_wall: float | None = None,
                    closed: bool = False, sources: list[str] | None = None, metrics: dict | None = None, support: list[str] | None = None, support_relations: list[str] | None = None,
                    subject_tid: int | None = None, object_tid: int | None = None, zone_id: str | None = None, calibration: dict | None = None,
                    definition: RelationRuleDefinition | None = None) -> RelationRecord:
        conf = combine(components)
        rec = RelationRecord(
            uid=new_uid(), type=type_id, subject=subject, object=obj, start_t=t, start_wall=wall, rule_key=rule[0], rule_version=rule[1], rule_name=rule[2],
            end_t=end_t, end_wall=end_wall, status="closed" if closed else "open", confidence=conf, state=state_for(conf), components=components.to_dict(),
            reason=reason, zone_id=zone_id, sources=sources or ["rgb"], calibration=calibration or {}, metrics=metrics or {}, support=support or [],
            support_relations=support_relations or [], subject_tid=subject_tid, object_tid=object_tid,
        )
        if definition is not None:
            rec.act_min_state = definition.act_min_state
            rec.act_label = definition.event_label or definition.name or rec.type
            rec.record_event = any(a.kind == "record_event" for a in definition.actions)
            rec.webhooks = [a.url for a in definition.actions if a.kind == "webhook" and a.url]
        self._records[rec.uid] = rec
        for tid in (subject_tid, object_tid):
            if tid is not None:
                self._by_track.setdefault(tid, []).append(rec)
        self.stats["relationships"] += 1
        self.stats["by_type"][type_id] = self.stats["by_type"].get(type_id, 0) + 1
        self._after_change(rec)
        return rec

    def _update_record(self, rec: RelationRecord, components: Components | None = None, reason: str | None = None, end_t: float | None = None, end_wall: float | None = None,
                       close: bool = False, metrics: dict | None = None) -> None:
        if components is not None:
            rec.confidence = combine(components)
            rec.state = state_for(rec.confidence)
            rec.components = components.to_dict()
        if reason is not None:
            rec.reason = reason
        if end_t is not None:
            rec.end_t, rec.end_wall = end_t, end_wall
        if metrics:
            rec.metrics = {**rec.metrics, **metrics}
        if close:
            rec.status = "closed"
            if rec.end_t is None:
                rec.end_t, rec.end_wall = self._t, self._wall
        rec.dirty = True
        self._after_change(rec)

    def _after_change(self, rec: RelationRecord) -> None:
        rec.dirty = True
        if not rec.acted and (rec.record_event or rec.webhooks) and at_least(rec.state, rec.act_min_state):
            rec.acted = True
            rec.publish = {"label": rec.act_label or rec.type, "record": rec.record_event, "webhooks": list(rec.webhooks)}
        # correlation rules see a relationship once, and again when its state improves
        if rec.subject_tid is not None and rec.object_tid is not None and (rec.fed_state is None or at_least(rec.state, rec.fed_state) and rec.state != rec.fed_state):
            rec.fed_state = rec.state
            s, o = self._tracks.get(rec.subject_tid), self._tracks.get(rec.object_tid)
            self._fact(Fact("relation", rec.start_t, rec.start_wall, rec.subject_tid, s.cls if s else "", rec.object_tid, o.cls if o else "", relation=rec.type,
                            state=rec.state, confidence=rec.confidence, uid=rec.uid, is_relation=True, end_t=rec.end_t))

    # ================================================================== input
    def step(self, t: float, wall: float, tracks: list, interactions: list | None = None, events: list | None = None) -> None:
        """One processed frame: tracked objects, spatial interactions and rule events."""
        self._t, self._wall = t, wall
        for tr in self._tracks.values():
            tr.seen_now = False
        for trk in tracks:
            if getattr(trk, "state", "tracked") != "tracked" or not getattr(trk, "updated", True):
                continue
            self._track_seen(trk, t, wall)
        for ia in interactions or []:
            kind = _ev(ia, "kind")
            if kind == "track_reacquired":
                tr = self._tracks.get(int(_ev(ia, "track_id", 0)))
                if tr is not None:
                    tr.reacquired += 1
            elif kind in ("zone_entered", "zone_exited", "line_crossed"):
                self._place_interaction(ia, t, wall)
            elif kind == "track_ended":
                self._track_ended(int(_ev(ia, "track_id", 0)), t, wall)
        for ev in events or []:
            self._event(ev, t, wall)
        if self.resolver is not None and self.settings.identity:
            self._resolve_identities(t, wall)
        if t - self._last_sample >= self.sample_s - 1e-9:
            self._last_sample = t
            self._sample(t, wall)
        self._dwell_tick(t, wall)
        self._run_pending(t, final=False)
        if t - self._last_prune > 30.0:
            self._last_prune = t
            self._prune(t)

    def finish(self, t: float | None = None, wall: float | None = None) -> None:
        """The run ended: close everything that is still open."""
        t = self._t if t is None else t
        wall = self._wall if wall is None else wall
        self._t, self._wall = t, wall
        for tid in [k for k, tr in self._tracks.items() if tr.alive]:
            self._track_ended(tid, t, wall, run_end=True)
        self._run_pending(t, final=True)
        for rec in list(self._records.values()):
            if rec.status == "open":
                self._update_record(rec, close=True)

    # ------------------------------------------------------------------ tracks
    def _track_seen(self, trk, t: float, wall: float) -> None:
        tid = int(trk.track_id)
        x1, y1, x2, y2 = trk.box
        w, h = self.ctx.frame_width, self.ctx.frame_height
        x = min(max(((x1 + x2) / 2.0) / w, 0.0), 1.0)
        y = min(max(y2 / h, 0.0), 1.0)
        hw = max(0.0, (x2 - x1) / 2.0 / w)
        tr = self._tracks.get(tid)
        cls = trk.class_name
        use_hw = hw if (cls in VEHICLE_CLASSES and self.ctx.footprint != "point") else 0.0
        fp = Footprint(x, y, use_hw)
        if tr is None:
            tr = _Track(tid, cls, E.track_key(self.ctx.run_id, tid, cls), t, wall, t, wall, fp)
            self._tracks[tid] = tr
            self._mention(tr.key, E.track_type(cls), "tracker", tr.label, t, wall, metadata={"object_class": cls, "track_id": tid})
            tr.motion.add(t, self.metric.ground(x, y))
            tr.conf_sum, tr.n = float(trk.confidence), 1
            tr.seen_now = True
            obs = self._observe("appeared", tr.key, t, wall, value={"x": round(x, 4), "y": round(y, 4)}, confidence=float(trk.confidence))
            self._fact(Fact("appears", t, wall, tid, cls, uid=obs.uid))
            self._appears_near(tr, t, wall, obs.uid)
            return
        tr.fp = fp
        tr.last_t, tr.last_wall = t, wall
        tr.conf_sum += float(trk.confidence)
        tr.n += 1
        tr.seen_now = True
        if hw > 0 and len(tr.hws) < 400:
            tr.hws.append(hw)
        tr.motion.add(t, self.metric.ground(x, y))

    def _track_ended(self, tid: int, t: float, wall: float, run_end: bool = False) -> None:
        tr = self._tracks.get(tid)
        if tr is None or not tr.alive:
            return
        tr.alive = False
        end_t, end_wall = tr.last_t, tr.last_wall
        m = self._entities.get(tr.key)
        if m is not None:
            m.seen(end_t, end_wall)
            m.confidence = round(tr.conf, 4)
            m.metadata = {**m.metadata, "frames": tr.n, "reacquired": tr.reacquired, "mean_confidence": round(tr.conf, 4)}
            if tr.hws:
                m.metadata["footprint_hw"] = round(median(tr.hws), 5)
            self._dirty_entities.add(tr.key)
        at_edge = tr.fp.x < EDGE or tr.fp.x > 1 - EDGE or tr.fp.y > 1 - EDGE or tr.fp.y < EDGE
        obs = self._observe("disappeared", tr.key, end_t, end_wall, value={"x": round(tr.fp.x, 4), "y": round(tr.fp.y, 4), "at_frame_edge": at_edge, "run_ended": run_end})
        if not run_end:
            self._disappears_near(tr, end_t, end_wall, obs.uid, at_edge)
            self._fact(Fact("disappears", end_t, end_wall, tid, tr.cls, uid=obs.uid))
        # close what this track held open
        for st in self.rules:
            for key in [k for k in st.pairs if tid in k]:
                self._close_pair(st, key, final=True)
            for key in [k for k in st.edges if tid in k]:
                del st.edges[key]
            for key in [k for k in st.places if k[0] == tid]:
                self._close_stop(st, key, final=True)
            for key in [k for k in st.dwell if k[0] == tid]:
                since, since_wall, rec = st.dwell.pop(key)
                if rec is not None:
                    self._update_record(rec, end_t=end_t, end_wall=end_wall, close=True)
            st.left.pop(tid, None)
            if st.matcher is not None:
                st.matcher.forget(tid)
        for key in [k for k in self._open_place if k[0] == tid]:
            self._update_record(self._open_place.pop(key), end_t=end_t, end_wall=end_wall, close=True)
        for key in [k for k in self._in_zone if k[0] == tid]:
            del self._in_zone[key]
        for rec in (tr.identity_rel, tr.plate_rel):
            if rec is not None and rec.status == "open":
                self._update_record(rec, end_t=end_t, end_wall=end_wall, close=True)
        self._run_pending(t, final=False, track=tid)

    # ------------------------------------------------------------------ identities
    def _resolve_identities(self, t: float, wall: float) -> None:
        for tr in self._tracks.values():
            if not tr.alive or not tr.seen_now or t - tr.last_resolve < 0.5:
                continue
            tr.last_resolve = t
            try:
                ent = self.resolver.resolve(tr.tid, tr.cls)
            except Exception:  # noqa: BLE001 - a resolver problem never stops the engine
                continue
            sig = (ent.kind, ent.identity_id, ent.vehicle_id, ent.plate, ent.status)
            if sig == tr.entity_sig:
                tr.entity = ent
                continue
            tr.entity_sig = sig
            prev = tr.entity
            tr.entity = ent
            self._identity_changed(tr, prev, ent, t, wall)

    def _identity_changed(self, tr: _Track, prev: EntityRef | None, ent: EntityRef, t: float, wall: float) -> None:
        conf = float(ent.confidence) if ent.confidence is not None else None
        # face: IDENTIFIED_AS (a possible match is recorded, never as more than 'possible')
        if ent.identity_id and ent.status in (STATUS_RECOGNIZED, STATUS_POSSIBLE):
            same = prev is not None and prev.identity_id == ent.identity_id and tr.identity_rel is not None and tr.identity_rel.status == "open"
            ikey = E.identity_key(ent.identity_id)
            src = "annotation" if ent.method == "annotation" else "face"
            self._mention(ikey, "recognized_person", src, "Recognized person", t, wall)
            possible = ent.status == STATUS_POSSIBLE
            obs = self._observe("possible_match" if possible else "recognized", tr.key, t, wall, source=src, obj=ikey, confidence=conf, value={"status": ent.status})
            recog = (conf or 0.5) * (0.55 if possible else 1.0)
            comp = Components(tracking=tr.conf, recognition=recog, support=max(1, tr.n))
            if src == "annotation":
                reason = f"A reviewer identified {tr.label} as this person (manual annotation, not face recognition)" + (f", certainty {conf:.2f}" if conf is not None else "") + "."
            else:
                reason = f"The face module {'found a possible match (not a confirmed identity) for' if possible else 'matched'} {tr.label}" + (f" with confidence {conf:.2f}" if conf is not None else "") + "."
            if same:
                self._update_record(tr.identity_rel, components=comp, reason=reason, metrics={"status": ent.status})
                tr.identity_rel.support.append(obs.uid)
            else:
                if tr.identity_rel is not None and tr.identity_rel.status == "open":
                    self._update_record(tr.identity_rel, end_t=t, end_wall=wall, close=True)
                tr.identity_rel = self._new_record("IDENTIFIED_AS", tr.key, ikey, t, wall, (*BUILTIN_IDENTITY, BUILTIN_NAMES["builtin.identity"]), comp, reason,
                                                   sources=[src], metrics={"status": ent.status}, support=[obs.uid], subject_tid=tr.tid,
                                                   calibration={"mode": "registry"})
        elif prev is not None and prev.identity_id and tr.identity_rel is not None and tr.identity_rel.status == "open":
            self._update_record(tr.identity_rel, end_t=t, end_wall=wall, close=True, metrics={"cleared": True})
        # plates: IDENTIFIED_BY_PLATE and REGISTERED_AS
        if ent.plate:
            pkey = E.plate_key(ent.plate, self.ctx.plate_salt)
            self._mention(pkey, "license_plate", "plate", "License plate", t, wall, secret_label=ent.plate)
            same = prev is not None and prev.plate == ent.plate and tr.plate_rel is not None and tr.plate_rel.status == "open"
            psrc = "annotation" if ent.method == "annotation" else "plate"
            obs = self._observe("plate_read", tr.key, t, wall, source=psrc, obj=pkey, confidence=conf, value={"status": ent.status})
            comp = Components(tracking=tr.conf, recognition=conf if conf is not None else 0.6, support=max(1, tr.n))
            if psrc == "annotation":
                reason = f"A reviewer identified the vehicle of {tr.label} (manual annotation, not plate recognition)" + (f", certainty {conf:.2f}" if conf is not None else "") + "."
            else:
                reason = f"The plate module read the plate of {tr.label}" + (f" with confidence {conf:.2f}" if conf is not None else "") + "."
            if same:
                self._update_record(tr.plate_rel, components=comp, reason=reason)
                tr.plate_rel.support.append(obs.uid)
            else:
                if tr.plate_rel is not None and tr.plate_rel.status == "open":
                    self._update_record(tr.plate_rel, end_t=t, end_wall=wall, close=True)
                tr.plate_rel = self._new_record("IDENTIFIED_BY_PLATE", tr.key, pkey, t, wall, (*BUILTIN_IDENTITY, BUILTIN_NAMES["builtin.identity"]), comp, reason,
                                                sources=[psrc], support=[obs.uid], subject_tid=tr.tid, calibration={"mode": "registry"})
            if ent.vehicle_id and (pkey, ent.vehicle_id) not in self._registered:
                self._registered.add((pkey, ent.vehicle_id))
                vkey = E.vehicle_key(ent.vehicle_id)
                self._mention(vkey, "registered_vehicle", "registry", "Registered vehicle", t, wall, metadata={"groups": list(ent.groups)})
                robs = self._observe("registered_vehicle", pkey, t, wall, source="registry", obj=vkey, confidence=1.0)
                self._new_record("REGISTERED_AS", pkey, vkey, t, wall, (*BUILTIN_IDENTITY, BUILTIN_NAMES["builtin.identity"]), Components(recognition=1.0, support=8),
                                 "The plate belongs to a vehicle of the vehicle registry.", sources=["registry"], support=[robs.uid], calibration={"mode": "registry"})
        elif prev is not None and prev.plate and tr.plate_rel is not None and tr.plate_rel.status == "open":
            self._update_record(tr.plate_rel, end_t=t, end_wall=wall, close=True, metrics={"cleared": True})

    # ------------------------------------------------------------------ places
    def _place_interaction(self, ia, t_now: float, wall_now: float) -> None:
        tid = int(_ev(ia, "track_id", 0))
        tr = self._tracks.get(tid)
        if tr is None:
            return
        kind = _ev(ia, "kind")
        t = float(_ev(ia, "t", t_now))
        wall = wall_now - max(0.0, t_now - t)
        oid = _ev(ia, "object_id") or ""
        otype = _ev(ia, "object_type") or ("line" if kind == "line_crossed" else "zone")
        pkey = self._place_key(oid, otype)
        name = self._place_name(oid)
        comp = Components(tracking=tr.conf, spatial=0.95, support=max(1, tr.n))
        builtin = (*BUILTIN_PLACES, BUILTIN_NAMES["builtin.places"])
        if kind == "line_crossed":
            direction = _ev(ia, "direction")
            obs = self._observe("crossed", tr.key, t, wall, obj=pkey, confidence=tr.conf, value={"direction": direction, "object_id": oid})
            if self.settings.places:
                self._new_record("CROSSED", tr.key, pkey, t, wall, builtin, comp, f"{tr.label} crossed {name} ({direction}).", end_t=t, end_wall=wall, closed=True,
                                 metrics={"direction": direction}, support=[obs.uid], subject_tid=tr.tid, zone_id=oid)
            self._fact(Fact("place", t, wall, tid, tr.cls, place_event="crosses", place_id=oid, uid=obs.uid))
            self._place_rules("crosses", tr, oid, pkey, t, wall, obs.uid, {"direction": direction})
        elif kind == "zone_entered":
            obs = self._observe("entered", tr.key, t, wall, obj=pkey, confidence=tr.conf, value={"object_id": oid})
            self._in_zone[(tid, oid)] = t
            if self.settings.places:
                self._new_record("ENTERED", tr.key, pkey, t, wall, builtin, comp, f"{tr.label} entered {name}.", end_t=t, end_wall=wall, closed=True,
                                 support=[obs.uid], subject_tid=tr.tid, zone_id=oid)
                if self.settings.occupied:
                    self._open_place[(tid, oid, "OCCUPIED")] = self._new_record("OCCUPIED", tr.key, pkey, t, wall, builtin, comp, f"{tr.label} was in {name}.",
                                                                               support=[obs.uid], subject_tid=tr.tid, zone_id=oid)
                last = self._last_exit.get(tid)
                if last is not None and last[0] != oid and 0 <= t - last[1] <= self.settings.transition_s:
                    self._moved(tr, last[0], last[1], last[2], oid, t, wall, comp, obs.uid)
            self._fact(Fact("place", t, wall, tid, tr.cls, place_event="enters", place_id=oid, uid=obs.uid))
            self._place_rules("enters", tr, oid, pkey, t, wall, obs.uid, {})
        elif kind == "zone_exited":
            dwell = _ev(ia, "dwell_s")
            obs = self._observe("exited", tr.key, t, wall, obj=pkey, confidence=tr.conf, value={"object_id": oid, "dwell_s": None if dwell is None else round(float(dwell), 3)})
            since = self._in_zone.pop((tid, oid), None)
            self._last_exit[tid] = (oid, t, wall)
            if self.settings.places:
                # Adjacent zones: the next zone's entry is reported before this exit
                # (the exit waits for the zone's short-exit allowance).
                for (vt, other), entry_t in list(self._in_zone.items()):
                    if vt == tid and other != oid and t - MOVE_OVERLAP_S <= entry_t <= t + self.settings.transition_s:
                        self._moved(tr, oid, t, wall, other, entry_t, wall_now - max(0.0, t_now - entry_t), comp, obs.uid)
            if self.settings.places:
                self._new_record("EXITED", tr.key, pkey, t, wall, builtin, comp, f"{tr.label} left {name}" + (f" after {float(dwell):.1f} s." if dwell is not None else "."),
                                 end_t=t, end_wall=wall, closed=True, metrics={"dwell_s": dwell}, support=[obs.uid], subject_tid=tr.tid, zone_id=oid)
                for rel in ("OCCUPIED", "REMAINED_IN"):
                    rec = self._open_place.pop((tid, oid, rel), None)
                    if rec is not None:
                        rec.support.append(obs.uid)
                        stay = t - rec.start_t
                        self._update_record(rec, end_t=t, end_wall=wall, close=True, reason=f"{tr.label} stayed in {name} for {stay:.1f} s.", metrics={"duration_s": round(stay, 3)})
            _ = since
            self._fact(Fact("place", t, wall, tid, tr.cls, place_event="exits", place_id=oid, uid=obs.uid))
            self._place_rules("exits", tr, oid, pkey, t, wall, obs.uid, {"dwell_s": dwell})

    def _moved(self, tr: _Track, src: str, src_t: float, src_wall: float, dst: str, dst_t: float, dst_wall: float, comp: Components, obs_uid: str) -> None:
        key = (tr.tid, src, dst, round(dst_t, 3))
        if key in self._moves:
            return
        self._moves.add(key)
        builtin = (*BUILTIN_PLACES, BUILTIN_NAMES["builtin.places"])
        gap = dst_t - src_t
        m = {"from": src, "to": dst, "gap_s": round(gap, 3)}
        why = f"{tr.label} left {self._place_name(src)} and entered {self._place_name(dst)}" + (f" {gap:.1f} s later." if gap > 0.05 else " at the same moment.")
        start_t, start_wall = min(src_t, dst_t), min(src_wall, dst_wall)
        end_t, end_wall = max(src_t, dst_t), max(src_wall, dst_wall)
        self._new_record("MOVED_FROM", tr.key, self._place_key(src), start_t, start_wall, builtin, comp, why, end_t=end_t, end_wall=end_wall, closed=True, metrics=m, support=[obs_uid], subject_tid=tr.tid, zone_id=src)
        self._new_record("MOVED_TO", tr.key, self._place_key(dst), start_t, start_wall, builtin, comp, why, end_t=end_t, end_wall=end_wall, closed=True, metrics=m, support=[obs_uid], subject_tid=tr.tid, zone_id=dst)

    def _event(self, ev, t_now: float, wall_now: float) -> None:
        etype = _ev(ev, "event_type")
        tid = int(_ev(ev, "track_id", 0) or 0)
        tr = self._tracks.get(tid)
        t = float(_ev(ev, "media_time_s", t_now) or t_now)
        wall = float(_ev(ev, "wall_time", wall_now) or wall_now)
        if etype == "route":
            route_name = _ev(ev, "route") or ""
            if tr is None or route_name in ROUTE_OUTCOMES:
                return
            rid = _ev(ev, "rule_id") or ""
            rkey = E.route_key(self.ctx.camera_id, rid)
            self._mention(rkey, "route", "scene", route_name or rid, metadata={"route_id": rid})
            start = _ev(ev, "entered_at_s")
            start = float(start) if start is not None else t
            obs = self._observe("route_completed", tr.key, t, wall, obj=rkey, confidence=tr.conf, value={"route_id": rid, "route": route_name, "started_s": round(start, 3)})
            if self.settings.places:
                self._new_record("USED_ROUTE", tr.key, rkey, start, wall - (t - start), (*BUILTIN_PLACES, BUILTIN_NAMES["builtin.places"]),
                                 Components(tracking=tr.conf, spatial=0.95, support=max(1, tr.n)), f"{tr.label} completed route {route_name} in {t - start:.1f} s.",
                                 end_t=t, end_wall=wall, closed=True, metrics={"duration_s": round(t - start, 3)}, support=[obs.uid], subject_tid=tr.tid)
            self._fact(Fact("place", t, wall, tid, tr.cls, place_event="uses_route", place_id=rid, uid=obs.uid))
            self._place_rules("uses_route", tr, rid, rkey, t, wall, obs.uid, {"started_s": start})
            return
        if etype in ("crossing", "zone_entry", "zone_exit", "dwell", "sequence", "rule", "occupancy_exceeded", "dwell_exceeded", "relationship", "correlated", "relation_deviation"):
            return  # geometric facts come from the interactions; our own events never feed back
        subject = tr.key if tr is not None else E.camera_key(self.ctx.camera_id or 0)
        obs = self._observe("event", subject, t, wall, value={"event_type": etype, "label": _ev(ev, "label"), "object_id": _ev(ev, "object_id")})
        if tr is not None:
            self._fact(Fact("event", t, wall, tid, tr.cls, event_type=etype, uid=obs.uid))

    def _place_rules(self, event: str, tr: _Track, place_id: str, pkey: str, t: float, wall: float, obs_uid: str, extra: dict) -> None:
        for st in self.rules:
            d = st.d
            if d.kind != "place" or not d.subject.class_ok(tr.cls):
                continue
            if d.place_event == "remains_in" and event == "enters" and (not d.places or place_id in d.places):
                st.dwell[(tr.tid, place_id)] = (t, wall, None)
                continue
            if d.place_event == "remains_in" and event == "exits":
                entry = st.dwell.pop((tr.tid, place_id), None)
                if entry is not None and entry[2] is not None:
                    entry[2].support.append(obs_uid)
                    self._update_record(entry[2], end_t=t, end_wall=wall, close=True, metrics={"duration_s": round(t - entry[0], 3)},
                                        reason=f"{tr.label} remained in {self._place_name(place_id)} for {t - entry[0]:.1f} s.")
                continue
            if d.place_event == "moves_between":
                if event in ("exits", "crosses") and place_id in d.places:
                    st.left[tr.tid] = (place_id, t)
                elif event in ("enters", "crosses") and place_id in d.to_places:
                    src = st.left.get(tr.tid)
                    limit = d.for_s if d.for_s > 0 else 60.0
                    if src is not None and 0 <= t - src[1] <= limit:
                        st.left.pop(tr.tid, None)
                        comp = Components(tracking=tr.conf, spatial=0.95, temporal=1.0, support=max(1, tr.n))
                        why = f"{tr.label} left {self._place_name(src[0])} and reached {self._place_name(place_id)} {t - src[1]:.1f} s later."
                        self._emit_when_known(st, tr, None, t, lambda st=st, tr=tr, src=src, comp=comp, why=why: self._new_record(
                            st.d.relation or "MOVED_TO", tr.key, pkey, src[1], wall - (t - src[1]), self._rule_tuple(st), comp, why, end_t=t, end_wall=wall, closed=True,
                            metrics={"from": src[0], "gap_s": round(t - src[1], 3)}, support=[obs_uid], subject_tid=tr.tid, zone_id=place_id, definition=st.d))
                continue
            wanted = {"enters": "enters", "exits": "exits", "crosses": "crosses", "uses_route": "uses_route"}.get(d.place_event or "")
            if wanted != event or (d.places and place_id not in d.places):
                continue
            comp = Components(tracking=tr.conf, spatial=0.95, support=max(1, tr.n))
            why = f"{tr.label} {event.replace('_', ' ')} {self._place_name(place_id) if event != 'uses_route' else (self._routes[place_id].name if place_id in self._routes else place_id)}."
            start = float(extra.get("started_s", t))
            self._emit_when_known(st, tr, None, t, lambda st=st, tr=tr, comp=comp, why=why, start=start: self._new_record(
                st.d.relation or "ENTERED", tr.key, pkey, start, wall - (t - start), self._rule_tuple(st), comp, why, end_t=t, end_wall=wall, closed=True,
                metrics={k: v for k, v in extra.items() if v is not None}, support=[obs_uid], subject_tid=tr.tid, zone_id=place_id if event != "uses_route" else None, definition=st.d))

    def _dwell_tick(self, t: float, wall: float) -> None:
        # built-in REMAINED_IN once a visit lasts remained_min_s
        if self.settings.places and self.settings.remained_min_s > 0:
            for (tid, oid), since in self._in_zone.items():
                if (tid, oid, "REMAINED_IN") in self._open_place or t - since < self.settings.remained_min_s:
                    continue
                tr = self._tracks.get(tid)
                if tr is None or not tr.alive:
                    continue
                pkey = self._place_key(oid)
                self._open_place[(tid, oid, "REMAINED_IN")] = self._new_record(
                    "REMAINED_IN", tr.key, pkey, since, wall - (t - since), (*BUILTIN_PLACES, BUILTIN_NAMES["builtin.places"]),
                    Components(tracking=tr.conf, spatial=0.95, temporal=1.0, support=max(1, tr.n)),
                    f"{tr.label} has been in {self._place_name(oid)} for at least {self.settings.remained_min_s:g} s.", subject_tid=tid, zone_id=oid)
        # rule 'remains in'
        for st in self.rules:
            if st.d.kind != "place" or st.d.place_event != "remains_in":
                continue
            for key, (since, since_wall, rec) in list(st.dwell.items()):
                if rec is not None or t - since < st.d.for_s:
                    continue
                tr = self._tracks.get(key[0])
                if tr is None:
                    continue
                verdict = self._verdict(st.d.subject, tr)
                if verdict is False:
                    del st.dwell[key]
                    continue
                if verdict is None:
                    continue
                pkey = self._place_key(key[1])
                rec = self._new_record(st.d.relation or "REMAINED_IN", tr.key, pkey, since, since_wall, self._rule_tuple(st),
                                       Components(tracking=tr.conf, spatial=0.95, temporal=1.0, support=max(1, tr.n)),
                                       f"{tr.label} remained in {self._place_name(key[1])} for at least {st.d.for_s:g} s.", subject_tid=tr.tid, zone_id=key[1], definition=st.d)
                st.dwell[key] = (since, since_wall, rec)

    # ------------------------------------------------------------------ spatial sampling
    def _rule_tuple(self, st: _RuleState) -> tuple[str, int, str]:
        return (st.rule.key, st.rule.version, st.d.name or st.rule.key)

    def _speed(self, tr: _Track, t: float) -> tuple[float, tuple[float, float]]:
        vx, vy, sp = tr.motion.velocity(t, 1.0)
        return sp, (vx, vy)

    def _thresh(self, calibrated: float, fw: float) -> float:
        return calibrated if self.metric.physical else fw

    def _in_zones(self, tr: _Track, zone_ids: list[str]) -> bool:
        p = (min(tr.fp.x, 1 - 1e-6), min(tr.fp.y, 1 - 1e-6))
        return any(point_in_polygon(p, self._zones[z]) for z in zone_ids if z in self._zones)

    def _extra_ok(self, d: RelationRuleDefinition, s: _Track, o: _Track | None, t: float) -> bool:
        for c in d.conditions:
            roles = [s] if c.role == "subject" else [o] if c.role == "object" else [s, o]
            for tr in roles:
                if tr is None:
                    continue
                if c.kind == "in_zone" and not self._in_zones(tr, c.zone_ids):
                    return False
                if c.kind == "not_in_zone" and self._in_zones(tr, c.zone_ids):
                    return False
                if c.kind in ("speed_below", "speed_above"):
                    limit = c.value if self.metric.physical else c.value_fw
                    if limit is None:
                        continue
                    sp, _ = self._speed(tr, t)
                    if (c.kind == "speed_below" and sp > limit) or (c.kind == "speed_above" and sp < limit):
                        return False
        return True

    def _sample(self, t: float, wall: float) -> None:
        seen = [tr for tr in self._tracks.values() if tr.alive and tr.seen_now]
        if len(seen) > self.settings.max_tracks:
            self.stats["tracks_capped"] += 1
            seen = sorted(seen, key=lambda tr: -tr.last_t)[: self.settings.max_tracks]
        for st in self.rules:
            d = st.d
            if d.kind == "pair" and d.condition not in ("disappears_near", "appears_near"):
                for s in seen:
                    if not d.subject.class_ok(s.cls):
                        continue
                    for o in seen:
                        if o is s or not d.object.class_ok(o.cls):
                            continue
                        if st.symmetric_same and s.tid > o.tid:
                            continue
                        self._measure_pair(st, s, o, t, wall)
                for key in list(st.pairs):
                    iv = st.pairs[key]
                    if not iv.touched:
                        iv.n_total += 1
                        if t - iv.last_ok_t > d.gap_s:
                            self._close_pair(st, key)
                    iv.touched = False
            elif d.kind == "place" and d.place_event == "stops_in":
                for s in seen:
                    if d.subject.class_ok(s.cls):
                        self._measure_stop(st, s, t, wall)
                for key in list(st.places):
                    iv = st.places[key]
                    if not iv.touched:
                        iv.n_total += 1
                        if t - iv.last_ok_t > d.gap_s:
                            self._close_stop(st, key)
                    iv.touched = False

    def _measure_pair(self, st: _RuleState, s: _Track, o: _Track, t: float, wall: float) -> None:
        d = st.d
        dist = self.metric.distance(s.fp, o.fp)
        self.stats["pairs_measured"] += 1
        key = (s.tid, o.tid)
        cond = d.condition
        D = st.distance or 0.0
        if cond in ("approaches", "moves_away"):
            self._edge(st, key, s, o, dist, t, wall)
            return
        ok = dist <= D
        lag = None
        if ok or cond == "follows":
            s_speed, s_v = self._speed(s, t)
            o_speed, o_v = self._speed(o, t)
            moving = self._thresh(d.min_speed, d.min_speed_fw)
            if cond == "moves_together":
                ok = ok and s_speed >= moving and o_speed >= moving and heading_difference(s_v, o_v) <= d.max_heading_deg
            elif cond == "stopped_near":
                ok = ok and s_speed <= self._thresh(d.stop_speed, d.stop_speed_fw)
            elif cond == "follows":
                ok = False
                if dist > D and s_speed >= moving and o_speed >= moving and heading_difference(s_v, o_v) <= d.max_heading_deg:
                    best = None
                    g = self.metric.ground(s.fp.x, s.fp.y)
                    step = max(self.sample_s, 0.5)
                    lag_t = d.lag_min_s
                    while lag_t <= d.lag_max_s + 1e-9:
                        p = o.motion.at(t - lag_t)
                        if p is not None:
                            dd = math.hypot(g[0] - p[0], g[1] - p[1])
                            if best is None or dd < best[0]:
                                best = (dd, lag_t)
                        lag_t += step
                    if best is not None and best[0] <= D:
                        ok, lag = True, best[1]
                        dist = best[0]  # distance to the leader's path
        if ok and not self._extra_ok(d, s, o, t):
            ok = False
        iv = st.pairs.get(key)
        if iv is None:
            if not ok:
                return
            if self._verdict(d.subject, s) is False or self._verdict(d.object, o) is False:
                return
            iv = st.pairs[key] = _Interval(t, wall, t, wall)
        iv.touched = True
        iv.n_total += 1
        if ok:
            iv.n_ok += 1
            iv.last_ok_t, iv.last_ok_wall = t, wall
            iv.sum_d += dist
            iv.min_d = min(iv.min_d, dist)
            iv.max_d = max(iv.max_d, dist)
            if lag is not None:
                iv.lag_sum += lag
        elif t - iv.last_ok_t > d.gap_s:
            self._close_pair(st, key)
            return
        if iv.duration >= d.for_s and iv.n_ok >= 2 or (d.for_s <= 0 and iv.n_ok >= 1):
            self._pair_record(st, key, s, o, iv, t)

    def _pair_components(self, st: _RuleState, s: _Track, o: _Track, iv: _Interval) -> Components:
        d = st.d
        recog = []
        for flt, tr in ((d.subject, s), (d.object, o)):
            if flt is not None and flt.subject.active and flt.subject.mode != "anonymous" and tr.entity is not None and tr.entity.confidence is not None:
                recog.append(float(tr.entity.confidence))
        points = self.ctx.footprint == "point" and (s.is_vehicle or o.is_vehicle)
        spatial = spatial_certainty(self.metric.mode, iv.mean_d, st.distance) * (0.85 if points else 1.0)
        tracking = ((s.conf + o.conf) / 2.0) * (0.9 ** min(3, s.reacquired + o.reacquired))
        return Components(tracking=tracking, recognition=min(recog) if recog else None, spatial=spatial, temporal=iv.n_ok / max(1, iv.n_total), support=iv.n_ok)

    def _pair_reason(self, st: _RuleState, s: _Track, o: _Track, iv: _Interval) -> str:
        d = st.d
        u = self.metric.unit_label
        dur = iv.duration
        base = {
            "near": f"{s.label} remained within {st.distance:.2f} {u} of {o.label}",
            "moves_together": f"{s.label} moved together with {o.label} (within {st.distance:.2f} {u}, same direction, both moving)",
            "stopped_near": f"{s.label} stood still within {st.distance:.2f} {u} of {o.label}",
            "follows": f"{s.label} moved along {o.label}'s path about {iv.lag_sum / max(1, iv.n_ok):.1f} s behind it (within {st.distance:.2f} {u} of the path)",
        }.get(d.condition or "near", f"{s.label} and {o.label}")
        txt = f"{base} for {dur:.1f} s (closest {iv.min_d:.2f} {u}, mean {iv.mean_d:.2f} {u}); {iv.n_ok} of {iv.n_total} samples met the condition."
        if not self.metric.physical:
            txt += " The camera is not calibrated: distances are in frame widths, not metres."
        return txt

    def _pair_record(self, st: _RuleState, key: tuple[int, int], s: _Track, o: _Track, iv: _Interval, t: float) -> None:
        comp = self._pair_components(st, s, o, iv)
        metrics = {"min_distance": round(iv.min_d, 4), "mean_distance": round(iv.mean_d, 4), "max_distance": round(iv.max_d, 4), "threshold": round(st.distance or 0.0, 4),
                   "unit": self.metric.unit, "duration_s": round(iv.duration, 3), "valid_samples": iv.n_ok, "samples": iv.n_total}
        if st.d.condition == "follows" and iv.n_ok:
            metrics["mean_lag_s"] = round(iv.lag_sum / iv.n_ok, 3)
        if iv.record is None:
            if self._verdict(st.d.subject, s) is not True or self._verdict(st.d.object, o) is not True:
                return  # identities not decided yet: keep measuring
            iv.record = self._new_record(st.d.relation or "NEAR", s.key, o.key, iv.start_t, iv.start_wall, self._rule_tuple(st), comp, self._pair_reason(st, s, o, iv),
                                         end_t=iv.last_ok_t, end_wall=iv.last_ok_wall, metrics=metrics, subject_tid=s.tid, object_tid=o.tid,
                                         calibration=self._calibration(points_only=self.ctx.footprint == "point"), definition=st.d)
            return
        rec = iv.record
        if t - rec.last_emit >= 2.0 or state_for(combine(comp)) != rec.state:
            rec.last_emit = t
            self._update_record(rec, components=comp, reason=self._pair_reason(st, s, o, iv), end_t=iv.last_ok_t, end_wall=iv.last_ok_wall, metrics=metrics)
        else:
            rec.end_t, rec.end_wall = iv.last_ok_t, iv.last_ok_wall

    def _close_pair(self, st: _RuleState, key: tuple[int, int], final: bool = False) -> None:
        iv = st.pairs.pop(key, None)
        if iv is None:
            return
        s, o = self._tracks.get(key[0]), self._tracks.get(key[1])
        if s is None or o is None:
            return
        if iv.record is not None:
            comp = self._pair_components(st, s, o, iv)
            self._update_record(iv.record, components=comp, reason=self._pair_reason(st, s, o, iv), end_t=iv.last_ok_t, end_wall=iv.last_ok_wall, close=True,
                                metrics={"duration_s": round(iv.duration, 3), "valid_samples": iv.n_ok, "samples": iv.n_total, "min_distance": round(iv.min_d, 4), "mean_distance": round(iv.mean_d, 4)})
            return
        if iv.duration >= st.d.for_s and iv.n_ok >= (2 if st.d.for_s > 0 else 1):
            # condition met, identities undecided: decide within the grace period
            def check(final: bool, st=st, s=s, o=o) -> bool | None:
                a, b = self._verdict(st.d.subject, s, final=final), self._verdict(st.d.object, o, final=final)
                if a is False or b is False:
                    return False
                return True if (a and b) else None

            def emit(st=st, s=s, o=o, iv=iv) -> None:
                comp = self._pair_components(st, s, o, iv)
                self._new_record(st.d.relation or "NEAR", s.key, o.key, iv.start_t, iv.start_wall, self._rule_tuple(st), comp, self._pair_reason(st, s, o, iv),
                                 end_t=iv.last_ok_t, end_wall=iv.last_ok_wall, closed=True, metrics={"min_distance": round(iv.min_d, 4), "mean_distance": round(iv.mean_d, 4),
                                 "threshold": round(st.distance or 0.0, 4), "unit": self.metric.unit, "duration_s": round(iv.duration, 3), "valid_samples": iv.n_ok, "samples": iv.n_total},
                                 subject_tid=s.tid, object_tid=o.tid, calibration=self._calibration(points_only=self.ctx.footprint == "point"), definition=st.d)

            self._pending.append(_Pending(self._t + (0.0 if final else GRACE_S), check, emit))

    def _edge(self, st: _RuleState, key: tuple[int, int], s: _Track, o: _Track, dist: float, t: float, wall: float) -> None:
        """approaches: was at least 'far' away, now within the distance, mostly by the subject's own movement."""
        d = st.d
        D, far = st.distance or 0.0, st.far or 0.0
        e = st.edges.get(key)
        if e is None:
            e = st.edges[key] = _Edge()
        gs, go = self.metric.ground(s.fp.x, s.fp.y), self.metric.ground(o.fp.x, o.fp.y)
        approach = d.condition == "approaches"
        at_ref = dist >= far if approach else dist <= D
        at_goal = dist <= D if approach else dist >= far
        if at_ref:
            e.armed, e.ref_t, e.ref_wall, e.ref_d, e.ref_s, e.ref_o = True, t, wall, dist, gs, go
            return
        if not (e.armed and at_goal):
            if e.armed and t - e.ref_t > max(d.window_s, 1.0):
                e.armed = False
            return
        if t - e.ref_t > d.window_s or not self._extra_ok(d, s, o, t):
            e.armed = False
            return
        share = closing_share(e.ref_s, gs, e.ref_o, go)
        if share < 0.5:
            e.armed = False  # the other one did the moving
            return
        e.armed = False
        u = self.metric.unit_label
        verb = "approached" if approach else "moved away from"
        why = (f"{s.label} {verb} {o.label}: {e.ref_d:.2f} {u} at the start, {dist:.2f} {u} {t - e.ref_t:.1f} s later; "
               f"{share * 100:.0f}% of the change came from {s.label}'s own movement.")
        if not self.metric.physical:
            why += " The camera is not calibrated: distances are in frame widths, not metres."
        comp = Components(tracking=(s.conf + o.conf) / 2.0, spatial=spatial_certainty(self.metric.mode, dist, D if approach else far, below=approach), temporal=0.6 + 0.4 * share, support=4)
        metrics = {"from_distance": round(e.ref_d, 4), "to_distance": round(dist, 4), "unit": self.metric.unit, "duration_s": round(t - e.ref_t, 3), "subject_share": round(share, 3)}
        ref_t, ref_wall = e.ref_t, e.ref_wall

        def check(final: bool, st=st, s=s, o=o) -> bool | None:
            a, b = self._verdict(st.d.subject, s, final=final), self._verdict(st.d.object, o, final=final)
            if a is False or b is False:
                return False
            return True if (a and b) else None

        def emit() -> None:
            self._new_record(d.relation or "APPROACHED", s.key, o.key, ref_t, ref_wall, self._rule_tuple(st), comp, why, end_t=t, end_wall=wall, closed=True, metrics=metrics,
                             subject_tid=s.tid, object_tid=o.tid, calibration=self._calibration(points_only=self.ctx.footprint == "point"), definition=d)

        self._decide(t, check, emit)

    def _measure_stop(self, st: _RuleState, s: _Track, t: float, wall: float) -> None:
        d = st.d
        zones = d.places or list(self._zones)
        inside = [z for z in zones if z in self._zones and point_in_polygon((min(s.fp.x, 1 - 1e-6), min(s.fp.y, 1 - 1e-6)), self._zones[z])]
        sp, _ = self._speed(s, t)
        still = sp <= self._thresh(d.stop_speed, d.stop_speed_fw) and len(s.motion.points) >= 3
        for z in inside:
            key = (s.tid, z)
            iv = st.places.get(key)
            ok = still and self._extra_ok(d, s, None, t)
            if iv is None:
                if not ok:
                    continue
                iv = st.places[key] = _Interval(t, wall, t, wall)
            iv.touched = True
            iv.n_total += 1
            if ok:
                iv.n_ok += 1
                iv.last_ok_t, iv.last_ok_wall = t, wall
            elif t - iv.last_ok_t > d.gap_s:
                self._close_stop(st, key)
                continue
            if iv.record is None and iv.duration >= d.for_s and self._verdict(d.subject, s) is True:
                obs = self._observe("stopped", s.key, iv.start_t, iv.start_wall, obj=self._place_key(z), confidence=s.conf, value={"object_id": z})
                iv.record = self._new_record(d.relation or "PARKED_IN", s.key, self._place_key(z), iv.start_t, iv.start_wall, self._rule_tuple(st),
                                             Components(tracking=s.conf, spatial=spatial_certainty(self.metric.mode), temporal=iv.n_ok / max(1, iv.n_total), support=iv.n_ok),
                                             f"{s.label} stood still in {self._place_name(z)} for at least {d.for_s:g} s.", end_t=iv.last_ok_t, end_wall=iv.last_ok_wall,
                                             support=[obs.uid], subject_tid=s.tid, zone_id=z, calibration=self._calibration(), definition=d)
            elif iv.record is not None and t - iv.record.last_emit >= 2.0:
                iv.record.last_emit = t
                self._update_record(iv.record, end_t=iv.last_ok_t, end_wall=iv.last_ok_wall, metrics={"duration_s": round(iv.duration, 3)},
                                    components=Components(tracking=s.conf, spatial=spatial_certainty(self.metric.mode), temporal=iv.n_ok / max(1, iv.n_total), support=iv.n_ok))

    def _close_stop(self, st: _RuleState, key: tuple[int, str], final: bool = False) -> None:
        iv = st.places.pop(key, None)
        if iv is None or iv.record is None:
            return
        s = self._tracks.get(key[0])
        self._update_record(iv.record, end_t=iv.last_ok_t, end_wall=iv.last_ok_wall, close=True, metrics={"duration_s": round(iv.duration, 3)},
                            reason=f"{s.label if s else 'The track'} stood still in {self._place_name(key[1])} for {iv.duration:.1f} s.")

    def _appears_near(self, s: _Track, t: float, wall: float, obs_uid: str) -> None:
        for st in self.rules:
            d = st.d
            if d.kind != "pair" or d.condition != "appears_near" or not d.subject.class_ok(s.cls):
                continue
            best = None
            for o in self._tracks.values():
                if o is s or not o.alive or not d.object.class_ok(o.cls) or t - o.first_t < 2.0 or t - o.last_t > 1.0:
                    continue
                dist = self.metric.distance(s.fp, o.fp)
                if dist <= (st.distance or 0.0) and (best is None or dist < best[0]):
                    best = (dist, o)
            if best is None:
                continue
            dist, o = best
            at_edge = s.fp.x < EDGE or s.fp.x > 1 - EDGE or s.fp.y > 1 - EDGE
            u = self.metric.unit_label
            why = f"{s.label} first appeared {dist:.2f} {u} from {o.label}, which had been in view for {t - o.first_t:.1f} s."
            if at_edge:
                why += " It appeared at the edge of the picture, so it may simply have walked into view."
            comp = Components(tracking=(s.conf + o.conf) / 2.0, spatial=spatial_certainty(self.metric.mode, dist, st.distance) * (0.6 if at_edge else 1.0), temporal=1.0, support=3)
            self._decide(t, self._pair_check(st, s, o), lambda st=st, s=s, o=o, comp=comp, why=why, dist=dist, at_edge=at_edge: self._new_record(
                st.d.relation or "EXITED_VEHICLE", s.key, o.key, t, wall, self._rule_tuple(st), comp, why, end_t=t, end_wall=wall, closed=True,
                metrics={"distance": round(dist, 4), "unit": self.metric.unit, "at_frame_edge": at_edge}, support=[obs_uid], subject_tid=s.tid, object_tid=o.tid,
                calibration=self._calibration(points_only=self.ctx.footprint == "point"), definition=st.d))

    def _disappears_near(self, s: _Track, t: float, wall: float, obs_uid: str, at_edge: bool) -> None:
        for st in self.rules:
            d = st.d
            if d.kind != "pair" or d.condition != "disappears_near" or not d.subject.class_ok(s.cls) or t - s.first_t < 1.0:
                continue
            best = None
            for o in self._tracks.values():
                if o is s or not o.alive or not d.object.class_ok(o.cls) or o.last_t < t - 1.0:
                    continue
                dist = self.metric.distance(s.fp, o.fp)
                if dist <= (st.distance or 0.0) and (best is None or dist < best[0]):
                    best = (dist, o)
            if best is None:
                continue
            dist, o = best
            u = self.metric.unit_label
            why = f"{s.label} was last seen {dist:.2f} {u} from {o.label}, which stayed in view."
            if at_edge:
                why += " It ended at the edge of the picture, so it may simply have walked out of view."
            comp = Components(tracking=(s.conf + o.conf) / 2.0, spatial=spatial_certainty(self.metric.mode, dist, st.distance) * (0.6 if at_edge else 1.0), temporal=1.0, support=3)
            self._decide(self._t, self._pair_check(st, s, o, final=True), lambda st=st, s=s, o=o, comp=comp, why=why, dist=dist, at_edge=at_edge: self._new_record(
                st.d.relation or "ENTERED_VEHICLE", s.key, o.key, t, wall, self._rule_tuple(st), comp, why, end_t=t, end_wall=wall, closed=True,
                metrics={"distance": round(dist, 4), "unit": self.metric.unit, "at_frame_edge": at_edge}, support=[obs_uid], subject_tid=s.tid, object_tid=o.tid,
                calibration=self._calibration(points_only=self.ctx.footprint == "point"), definition=st.d))

    def _pair_check(self, st: _RuleState, s: _Track, o: _Track, final: bool = False):
        def check(is_final: bool) -> bool | None:
            a = self._verdict(st.d.subject, s, final=is_final or final or not s.alive)
            b = self._verdict(st.d.object, o, final=is_final or not o.alive)
            if a is False or b is False:
                return False
            return True if (a and b) else None

        return check

    def _emit_when_known(self, st: _RuleState, s: _Track, o: _Track | None, t: float, emit) -> None:
        def check(final: bool) -> bool | None:
            a = self._verdict(st.d.subject, s, final=final or not s.alive)
            if o is None:
                return a
            b = self._verdict(st.d.object or RoleFilter(), o, final=final or not o.alive)
            if a is False or b is False:
                return False
            return True if (a and b) else None

        self._decide(t, check, emit)

    def _decide(self, t: float, check, emit) -> None:
        verdict = check(False)
        if verdict is True:
            emit()
        elif verdict is None:
            self._pending.append(_Pending(t + GRACE_S, check, emit))

    def _run_pending(self, t: float, final: bool, track: int | None = None) -> None:
        if not self._pending:
            return
        keep: list[_Pending] = []
        for p in self._pending:
            is_final = final or t >= p.deadline_t
            verdict = p.check(is_final)
            if verdict is True:
                p.emit()
            elif verdict is None and not is_final:
                keep.append(p)
        self._pending = keep

    # ------------------------------------------------------------------ correlation
    def _fact(self, f: Fact) -> None:
        for st in self.rules:
            if st.matcher is not None:
                for m in st.matcher.feed(f):
                    self._sequence_done(st, m)
            elif st.follower is not None:
                for fm in st.follower.feed(f):
                    self._follow_done(st, fm)

    def _sequence_done(self, st: _RuleState, m: Match) -> None:
        d = st.d
        a, b = self._tracks.get(m.bindings.get("A", -1)), self._tracks.get(m.bindings.get("B", -1))
        if a is None:
            return
        st.matches += 1
        obs = [f.uid for _i, f in m.facts if not f.is_relation]
        rels = [f.uid for _i, f in m.facts if f.is_relation]
        rel_conf = [f.confidence for _i, f in m.facts if f.is_relation and f.confidence is not None]
        tracks = [x for x in (a, b) if x is not None]
        comp = Components(tracking=sum(x.conf for x in tracks) / len(tracks), spatial=min(rel_conf) if rel_conf else None, temporal=1.0, support=len(m.facts) + 2)
        steps_txt = "; ".join(self._fact_text(i, f) for i, f in m.facts)
        who = a.label + (f" and {b.label}" if b is not None else "")
        why = f"All {len(d.steps)} steps of '{d.name or st.rule.key}' were observed for {who} within {m.last_t - m.first_t:.1f} s: {steps_txt}."
        temporal = m.temporal_links()

        def emit() -> None:
            rec = None
            if d.relation and b is not None:
                rec = self._new_record(d.relation, a.key, b.key, m.first_t, m.first_wall, self._rule_tuple(st), comp, why, end_t=m.last_t, end_wall=m.last_wall, closed=True,
                                       metrics={"steps": len(m.facts), "window_s": round(m.last_t - m.first_t, 3)}, support=obs, support_relations=rels,
                                       subject_tid=a.tid, object_tid=b.tid, definition=d if not d.event_label else None)
            if d.event_label:
                self._correlated_record(st, d.event_label, m.first_t, m.last_t, m.first_wall, m.last_wall, comp, {"A": a.key, **({"B": b.key} if b else {})}, why,
                                        obs, rels + ([rec.uid] if rec else []), temporal, {"steps": len(m.facts)})

        roles = [(d.subject, a)] + ([(d.object, b)] if b is not None and d.object is not None else [])

        def check(final: bool) -> bool | None:
            out: bool | None = True
            for flt, tr in roles:
                v = self._verdict(flt, tr, final=final or not tr.alive)
                if v is False:
                    return False
                if v is None:
                    out = None
            return out

        self._decide(self._t, check, emit)

    def _follow_done(self, st: _RuleState, fm: FollowMatch) -> None:
        d = st.d
        follower, leader = self._tracks.get(fm.follower), self._tracks.get(fm.leader)
        if follower is None or leader is None:
            return
        st.matches += 1
        places = [self._place_name(lv.place_id) if lv.place_id in self._objects else (self._routes[lv.place_id].name if lv.place_id in self._routes else lv.place_id) for lv, _fv in fm.visits]
        lags = fm.lags
        first_t, first_wall = fm.visits[0][0].t, fm.visits[0][0].wall
        last_t, last_wall = fm.visits[-1][1].t, fm.visits[-1][1].wall
        why = (f"{follower.label} passed the same {len(fm.visits)} places as {leader.label}, in the same order, each {min(lags):.1f}-{max(lags):.1f} s after it "
               f"({' -> '.join(places)}), within {last_t - first_t:.1f} s.")
        comp = Components(tracking=(follower.conf + leader.conf) / 2.0, spatial=0.95, temporal=1.0, support=len(fm.visits) * 2)
        support = [v.uid for pair in fm.visits for v in pair]
        metrics = {"checkpoints": [lv.place_id for lv, _ in fm.visits], "lags_s": lags}
        key = (fm.leader, fm.follower)
        existing = st.follows.get(key)

        def emit() -> None:
            if existing is not None:
                self._update_record(existing, components=comp, reason=why, end_t=last_t, end_wall=last_wall, metrics=metrics)
                existing.support = support
                return
            rec = self._new_record(d.relation or "FOLLOWED", follower.key, leader.key, first_t, first_wall, self._rule_tuple(st), comp, why, end_t=last_t, end_wall=last_wall, closed=True,
                                   metrics=metrics, support=support, subject_tid=follower.tid, object_tid=leader.tid, definition=d if not d.event_label else None)
            st.follows[key] = rec
            if d.event_label:
                self._correlated_record(st, d.event_label, first_t, last_t, first_wall, last_wall, comp, {"A": follower.key, "B": leader.key}, why, support, [rec.uid], [], metrics)

        self._decide(self._t, self._pair_check(st, follower, leader), emit)

    def _fact_text(self, step: int, f: Fact) -> str:
        tr = self._tracks.get(f.tid)
        who = tr.label if tr else f"track #{f.tid}"
        if f.kind == "relation":
            other = self._tracks.get(f.other_tid or -1)
            return f"({step + 1}) {who} {f.relation} {other.label if other else ''} at {f.t:.1f} s"
        if f.kind == "place":
            where = self._routes[f.place_id].name if f.place_event == "uses_route" and f.place_id in self._routes else self._place_name(f.place_id)
            return f"({step + 1}) {who} {(f.place_event or '').replace('_', ' ')} {where} at {f.t:.1f} s"
        if f.kind == "event":
            return f"({step + 1}) {f.event_type} of {who} at {f.t:.1f} s"
        return f"({step + 1}) {who} {f.kind} at {f.t:.1f} s"

    def _correlated_record(self, st: _RuleState, label: str, start_t: float, end_t: float, start_wall: float, end_wall: float, comp: Components, roles: dict[str, str],
                           description: str, support: list[str], support_relations: list[str], temporal: list[dict], metrics: dict) -> CorrelatedRecord:
        d = st.d
        conf = combine(comp)
        state = state_for(conf)
        rec = CorrelatedRecord(new_uid(), "correlated", label, st.rule.key, st.rule.version, d.name or st.rule.key, start_t, end_t, start_wall, end_wall, conf, state, roles, description,
                               support, support_relations, temporal, {**metrics, "components": comp.to_dict()})
        if (any(a.kind == "record_event" for a in d.actions) or any(a.kind == "webhook" for a in d.actions)) and at_least(state, d.act_min_state):
            rec.publish = {"label": label, "record": any(a.kind == "record_event" for a in d.actions), "webhooks": [a.url for a in d.actions if a.kind == "webhook" and a.url]}
        self._correlated.append(rec)
        self.stats["correlated"] += 1
        return rec

    # ------------------------------------------------------------------ relation clause of ordinary rules
    def has_relation(self, track_id: int, relation: str, direction: str = "any", other: RoleFilter | None = None, other_places: list[str] | None = None,
                     min_state: str = "possible", recent_s: float | None = None, t: float | None = None) -> bool | None:
        """Does the track have (or recently had) this relationship? Used by the rule
        builder's HAS RELATIONSHIP clause. ``None`` while the other entity's identity is undecided."""
        t = self._t if t is None else t
        undecided = False
        for rec in self._by_track.get(track_id, []):
            if rec.type != relation or not at_least(rec.state, min_state):
                continue
            if rec.status == "closed" and recent_s is not None and rec.end_t is not None and t - rec.end_t > recent_s:
                continue
            if direction == "outgoing" and rec.subject_tid != track_id:
                continue
            if direction == "incoming" and rec.object_tid != track_id and rec.subject_tid == track_id:
                continue
            other_tid = rec.object_tid if rec.subject_tid == track_id else rec.subject_tid
            if other_places:
                if rec.zone_id not in other_places:
                    continue
                return True
            if other is None:
                return True
            if other_tid is None:
                continue
            tr = self._tracks.get(other_tid)
            if tr is None or not other.class_ok(tr.cls):
                continue
            v = self._verdict(other, tr, final=not tr.alive)
            if v is True:
                return True
            if v is None:
                undecided = True
        return None if undecided else False

    # ------------------------------------------------------------------ output
    def _prune(self, t: float) -> None:
        for tid in [k for k, tr in self._tracks.items() if not tr.alive and t - tr.last_t > KEEP_CLOSED_S]:
            del self._tracks[tid]
            self._by_track.pop(tid, None)
            self._last_exit.pop(tid, None)
        for tid, recs in list(self._by_track.items()):
            self._by_track[tid] = [r for r in recs if r.status == "open" or r.end_t is None or t - r.end_t <= KEEP_CLOSED_S]
        for uid in [u for u, r in self._records.items() if r.status == "closed" and not r.dirty and (r.end_t is None or t - r.end_t > KEEP_CLOSED_S)]:
            del self._records[uid]
        for st in self.rules:
            if st.follower is not None:
                st.follower.prune(t)

    def drain(self) -> dict | None:
        """Everything produced since the last drain (None when nothing)."""
        ents = [self._entities[k].to_dict() for k in self._dirty_entities if k in self._entities]
        self._dirty_entities.clear()
        obs = [o.to_dict() for o in self._observations]
        self._observations = []
        rels = []
        for r in self._records.values():
            if r.dirty:
                rels.append(r.to_dict())
                r.dirty = False
                r.publish = None
        cor = [c.to_dict() for c in self._correlated]
        self._correlated = []
        if not (ents or obs or rels or cor):
            return None
        return {"entities": ents, "observations": obs, "relationships": rels, "correlated": cor}

    def describe(self) -> dict:
        return {
            "rules": [{"key": st.rule.key, "version": st.rule.version, "name": st.d.name, "kind": st.d.kind, "distance": None if st.distance is None else round(st.distance, 4)} for st in self.rules],
            "inactive_rules": self.inactive,
            "calibration": self.metric.describe(),
            "identity": bool(self.settings.identity and self.resolver is not None and self.resolver.provides()),
            "places": self.settings.places,
            "sample_s": self.sample_s,
            "footprint": self.ctx.footprint,
        }

    def status(self) -> dict:
        return {
            "tracks": sum(1 for tr in self._tracks.values() if tr.alive),
            "open_relationships": sum(1 for r in self._records.values() if r.status == "open"),
            "pending": len(self._pending),
            **{k: v for k, v in self.stats.items() if k != "by_type"},
            "by_type": dict(self.stats["by_type"]),
        }
