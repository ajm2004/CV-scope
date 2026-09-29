"""Rule engine: turns geometric interactions into semantic events.

Three kinds of logic run here, all as per-track state machines:

* implicit rules derived from the scene itself (a counting line counts, a
  zone reports entries/exits/dwell),
* route groups: routes that share a start object; the group decides
  ROUTE_<name>, UNKNOWN, ABANDONED or LOST_TRACK for every track that starts,
* explicit rules from the rule builder (single trigger, THEN sequences and
  "remains for" dwell rules).

The engine never forces a track into a route: when the evidence is incomplete
the outcome is UNKNOWN, ABANDONED (timeout) or LOST_TRACK.

Recognition (licensed modules) enters through the ``EntityResolver`` interface
only: a rule with a subject clause ("Recognized Person is Employee-017",
"Vehicle Plate equals ABC12345") is evaluated against the entity the track
resolves to at the moment the event would be emitted. Recognition often
arrives a little after the geometric trigger (the face is matched two seconds
after the person crossed the line), so an undecided event waits up to
``subject_grace_s`` and is emitted with its original timestamps once the
identity is known, or dropped. Rules whose module is not active stay inactive.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

from pathscope.domain.entities import EntityRef, EntityResolver, NullEntityResolver
from pathscope.domain.rules import Rule, RuleStep
from pathscope.domain.scene import LineObject, RouteDefinition, SceneDocument, ZoneObject
from pathscope.spatial.engine import Interaction, SpatialEngine

ROUTE_UNKNOWN = "UNKNOWN"
ROUTE_ABANDONED = "ABANDONED"
ROUTE_LOST = "LOST_TRACK"


@dataclass
class EventRecord:
    track_id: int
    object_class: str
    event_type: str
    label: str
    frame_index: int
    media_time_s: float
    wall_time: float
    rule_id: str | None = None
    rule_name: str | None = None
    route: str | None = None
    object_id: str | None = None
    object_name: str | None = None
    direction: str | None = None
    entered_at_s: float | None = None
    completed_at_s: float | None = None
    duration_s: float | None = None
    avg_speed: float | None = None
    speed_unit: str | None = None
    confidence: float | None = None
    context: dict = field(default_factory=dict)
    record: bool = True  # store in the database
    count: bool = True  # increment a counter
    webhooks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "object_class": self.object_class,
            "event_type": self.event_type,
            "label": self.label,
            "frame_index": self.frame_index,
            "media_time_s": round(self.media_time_s, 3),
            "wall_time": self.wall_time,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "route": self.route,
            "object_id": self.object_id,
            "object_name": self.object_name,
            "direction": self.direction,
            "entered_at_s": self.entered_at_s,
            "completed_at_s": self.completed_at_s,
            "duration_s": round(self.duration_s, 3) if self.duration_s is not None else None,
            "avg_speed": round(self.avg_speed, 3) if self.avg_speed is not None else None,
            "speed_unit": self.speed_unit,
            "confidence": round(self.confidence, 3) if self.confidence is not None else None,
            "context": self.context,
            "record": self.record,
            "count": self.count,
            "webhooks": self.webhooks,
        }


@dataclass
class RouteGroup:
    id: str
    start_id: str
    start_name: str
    routes: list[RouteDefinition]
    timeout_s: float
    classes: set[str]
    # track_id -> progress
    progress: dict[int, dict] = field(default_factory=dict)
    last_outcome: str | None = None
    completed: int = 0

    @property
    def label(self) -> str:
        return self.start_name or self.start_id


@dataclass
class SequenceState:
    rule: Rule
    track_id: int
    start_t: float
    start_frame: int
    step_index: int = 0
    last_t: float = 0.0
    passed: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class PendingEvent:
    """An event of a rule with a subject clause, waiting for recognition."""

    event: EventRecord
    rule: Rule
    track_id: int
    deadline_t: float


class RuleEngine:
    def __init__(
        self,
        scene: SceneDocument,
        rules: list[Rule],
        spatial: SpatialEngine,
        tracked_classes: list[str] | None = None,
        entities: EntityResolver | None = None,
        subject_grace_s: float = 5.0,
        relations_available: bool = False,
    ) -> None:
        self.scene = scene
        self.spatial = spatial
        self.tracked_classes = set(tracked_classes or [])
        self.entities: EntityResolver = entities or NullEntityResolver()
        self.subject_grace_s = max(0.0, float(subject_grace_s))
        provided = set(self.entities.provides())
        enabled = [r for r in rules if r.enabled]
        # A rule with a recognition subject stays inactive without its module:
        # recognition fails closed instead of matching everyone.
        self.inactive_rules = [r for r in enabled if (r.subject.active and not (r.modules_needed & provided)) or (r.relation is not None and not relations_available)]
        # The run's relationship engine (set by the worker when relationships are on);
        # answers the HAS RELATIONSHIP clause.
        self.relations = None
        self.rules = [r for r in enabled if r not in self.inactive_rules]
        self.objects = {o.id: o for o in scene.objects}
        self.counters: OrderedDict[str, dict] = OrderedDict()
        self.route_groups: list[RouteGroup] = self._build_route_groups()
        self._sequences: dict[tuple[str, int], SequenceState] = {}
        self._dwell_watch: dict[tuple[str, int], dict] = {}
        self._dwell_exceeded: set[tuple[str, int]] = set()
        self._occupancy_exceeded: set[str] = set()
        self._track_classes: dict[int, str] = {}
        self._pending: list[PendingEvent] = []
        self.stats = {
            "events": 0,
            "route_completions": 0,
            "route_unknown": 0,
            "route_abandoned": 0,
            "route_lost": 0,
            "end_without_start": 0,
            "sequence_expired": 0,
            "sequence_track_lost": 0,
            "subject_unmatched": 0,
            "subject_pending_dropped": 0,
        }
        self._init_counters()

    # ------------------------------------------------------------------ setup
    def _build_route_groups(self) -> list[RouteGroup]:
        groups: dict[str, RouteGroup] = {}
        for r in self.scene.routes:
            if not r.enabled:
                continue
            g = groups.get(r.start)
            if g is None:
                start = self.objects.get(r.start)
                g = RouteGroup(
                    id=f"group_{r.start}",
                    start_id=r.start,
                    start_name=start.name if start else r.start,
                    routes=[],
                    timeout_s=r.timeout_s,
                    classes=set(),
                )
                groups[r.start] = g
            g.routes.append(r)
            g.timeout_s = max(g.timeout_s, r.timeout_s)
            g.classes.update(r.classes)
        return list(groups.values())

    def _counter(self, key: str, label: str, group: str, kind: str) -> dict:
        c = self.counters.get(key)
        if c is None:
            c = {"key": key, "label": label, "group": group, "kind": kind, "value": 0}
            self.counters[key] = c
        return c

    def _init_counters(self) -> None:
        for ln in self.scene.lines():
            if ln.enabled and "count" in ln.actions:
                if ln.direction in ("both", "forward"):
                    self._counter(f"line:{ln.id}:forward", f"{ln.name} forward", ln.name, "crossing")
                if ln.direction in ("both", "reverse"):
                    self._counter(f"line:{ln.id}:reverse", f"{ln.name} reverse", ln.name, "crossing")
        for z in self.scene.zones():
            if z.enabled and z.type == "zone":
                if "entry" in z.measures:
                    self._counter(f"zone:{z.id}:entries", f"{z.name} entries", z.name, "zone")
                if "exit" in z.measures:
                    self._counter(f"zone:{z.id}:exits", f"{z.name} exits", z.name, "zone")
        for g in self.route_groups:
            for r in g.routes:
                self._counter(f"route:{r.id}", r.name, g.label, "route")
            for outcome in (ROUTE_UNKNOWN, ROUTE_ABANDONED, ROUTE_LOST):
                self._counter(f"route:{g.id}:{outcome}", outcome.replace("_", " ").title(), g.label, "route_outcome")
        for rule in self.rules:
            if any(a.kind == "count" for a in rule.actions):
                self._counter(f"rule:{rule.id}", rule.label, "Rules", "rule")

    # ------------------------------------------------------------------ helpers
    def _class_ok(self, classes, class_name: str) -> bool:
        return not classes or class_name in classes

    def _interaction_matches(self, ia: Interaction, kind: str, object_id: str, direction: str) -> bool:
        if ia.object_id != object_id:
            return False
        if kind == "crosses":
            if ia.kind != "line_crossed":
                return False
            return direction == "both" or ia.direction == direction
        if kind == "enters":
            return ia.kind == "zone_entered"
        if kind == "exits":
            return ia.kind == "zone_exited"
        return False

    def _natural_kind(self, object_id: str) -> str:
        obj = self.objects.get(object_id)
        if isinstance(obj, LineObject):
            return "crosses"
        return "enters"

    def _speed(self, track_id: int, t0: float, t1: float) -> tuple[float | None, str]:
        return self.spatial.speed_between(track_id, t0, t1), self.spatial.mapper.speed_unit

    def _confidence(self, track_id: int) -> float | None:
        rec = self.spatial.records.get(track_id)
        return rec.mean_confidence if rec else None

    def _bump(self, key: str) -> None:
        c = self.counters.get(key)
        if c is not None:
            c["value"] += 1

    def counters_list(self) -> list[dict]:
        return list(self.counters.values())

    def routes_in_progress(self) -> int:
        return sum(len(g.progress) for g in self.route_groups)

    # ------------------------------------------------------------------ main entry
    def process(self, interactions: list[Interaction], t: float, frame_index: int, wall_time: float | None = None) -> list[EventRecord]:
        wall_now = wall_time or time.time()
        events: list[EventRecord] = []
        for ia in interactions:
            if self.tracked_classes and ia.class_name not in self.tracked_classes:
                continue
            # An interaction may describe an earlier moment (a visit that ended when the
            # object was last seen, before the lost-track buffer ran out): date it then.
            wall = wall_now - max(0.0, t - ia.t)
            self._track_classes[ia.track_id] = ia.class_name
            if ia.kind == "line_crossed":
                events.extend(self._implicit_line(ia, wall))
            elif ia.kind in ("zone_entered", "zone_exited"):
                events.extend(self._implicit_zone(ia, wall))
            if ia.kind in ("line_crossed", "zone_entered", "zone_exited"):
                events.extend(self._routes(ia, wall))
                events.extend(self._explicit(ia, wall))
            elif ia.kind == "track_ended":
                events.extend(self._track_ended(ia, wall))
        events.extend(self.tick(t, frame_index, wall_now))
        self._enrich(events)
        self.stats["events"] += len(events)
        return events

    # ------------------------------------------------------------------ recognition subjects
    def _verdict(self, rule: Rule, track_id: int, object_class: str, final: bool) -> tuple[bool, EntityRef] | tuple[None, EntityRef]:
        entity = self.entities.resolve(track_id, object_class or self._track_classes.get(track_id, ""))
        res = rule.subject.evaluate(entity)
        if res is None and final:
            # Grace over, nothing recognized: only "anonymous" is satisfied.
            res = rule.subject.mode == "anonymous"
        if rule.relation is not None and res is not False:
            rel = self._relation_verdict(rule, track_id)
            if rel is False and not final and self.relations is not None:
                # The relationship may form a moment later (it is often made by the
                # same crossing that triggers the rule): wait like for recognition.
                rel = None
            if rel is None and final:
                rel = False
            if rel is False:
                return False, entity
            if rel is None:
                res = None
        return res, entity

    def _relation_verdict(self, rule: Rule, track_id: int) -> bool | None:
        """The HAS RELATIONSHIP clause, asked of the run's relationship engine."""
        if self.relations is None or rule.relation is None:
            return False
        from pathscope.relationships.rules import RoleFilter

        c = rule.relation
        other = RoleFilter(classes=c.other_classes, subject=c.other) if (c.other_classes or c.other.active) else None
        try:
            return self.relations.has_relation(track_id, c.relation, c.direction, other, c.other_places or None, c.min_state, c.recent_s)
        except Exception:  # noqa: BLE001 - a failing clause never matches
            return False

    def _emit(self, ev: EventRecord, rule: Rule, track_id: int) -> list[EventRecord]:
        """Apply the rule's subject clause; count the rule only when the event is emitted."""
        if rule.conditional:
            verdict, entity = self._verdict(rule, track_id, ev.object_class, final=False)
            if verdict is None:
                self._pending.append(PendingEvent(ev, rule, track_id, ev.media_time_s + self.subject_grace_s))
                return []
            if verdict is False:
                self.stats["subject_unmatched"] += 1
                return []
            ev.context["entity"] = entity.to_context()
        if ev.count:
            self._bump(f"rule:{rule.id}")
        return [ev]

    def _flush_pending(self, t: float, track_id: int | None = None, final: bool = False) -> list[EventRecord]:
        """Re-evaluate waiting events: emit those whose subject is now satisfied,
        drop those that failed or timed out."""
        out: list[EventRecord] = []
        keep: list[PendingEvent] = []
        for p in self._pending:
            if track_id is not None and p.track_id != track_id:
                keep.append(p)
                continue
            is_final = final or t >= p.deadline_t
            verdict, entity = self._verdict(p.rule, p.track_id, p.event.object_class, final=is_final)
            if verdict is None:
                keep.append(p)
                continue
            if verdict:
                p.event.context["entity"] = entity.to_context()
                if p.event.count:
                    self._bump(f"rule:{p.rule.id}")
                out.append(p.event)
            else:
                self.stats["subject_pending_dropped"] += 1
        self._pending = keep
        return out

    def _enrich(self, events: list[EventRecord]) -> None:
        """Attach the opaque entity reference to every event of a recognized track."""
        if not self.entities.provides():
            return
        for ev in events:
            if ev.track_id <= 0 or "entity" in ev.context:
                continue
            entity = self.entities.resolve(ev.track_id, ev.object_class or self._track_classes.get(ev.track_id, ""))
            if entity.recognized:
                ev.context["entity"] = entity.to_context()

    def pending_count(self) -> int:
        return len(self._pending)

    def tick(self, t: float, frame_index: int, wall_time: float | None = None) -> list[EventRecord]:
        """Time-based checks: route timeouts, dwell thresholds, sequence deadlines."""
        wall = wall_time or time.time()
        events: list[EventRecord] = []
        if self._pending:
            events.extend(self._flush_pending(t))
        # route timeouts
        for g in self.route_groups:
            for tid, prog in list(g.progress.items()):
                if t - prog["start_t"] > g.timeout_s:
                    events.append(self._route_outcome(g, tid, ROUTE_ABANDONED, t, frame_index, wall, prog))
                    del g.progress[tid]
        # sequence deadlines
        for key, st in list(self._sequences.items()):
            rule = st.rule
            step = rule.then[st.step_index] if st.step_index < len(rule.then) else None
            expired = False
            if step and step.within_s is not None and t - st.last_t > step.within_s:
                expired = True
            if rule.timeout_s is not None and t - st.start_t > rule.timeout_s:
                expired = True
            if expired:
                self.stats["sequence_expired"] += 1
                del self._sequences[key]
        # dwell watches (explicit "remains for" rules)
        for key, w in list(self._dwell_watch.items()):
            rule: Rule = w["rule"]
            if w["fired"]:
                continue
            dwell = self.spatial.dwell_time(rule.trigger.object_id, w["track_id"], t)
            if dwell is None:
                del self._dwell_watch[key]
                continue
            if rule.remains_for_s is not None and dwell >= rule.remains_for_s:
                w["fired"] = True
                obj = self.objects.get(rule.trigger.object_id)
                ev = EventRecord(
                    track_id=w["track_id"], object_class=w["class_name"], event_type="dwell",
                    label=rule.label, frame_index=frame_index, media_time_s=t, wall_time=wall,
                    rule_id=rule.id, rule_name=rule.name or rule.label, object_id=rule.trigger.object_id,
                    object_name=obj.name if obj else None, entered_at_s=w["since"], completed_at_s=t,
                    duration_s=dwell, confidence=self._confidence(w["track_id"]),
                    context={"zone_occupancy": self.spatial.zone_occupancy().get(rule.trigger.object_id)},
                )
                self._apply_actions(ev, rule)
                events.extend(self._emit(ev, rule, w["track_id"]))
        # implicit max-dwell and max-occupancy flags
        occ = self.spatial.zone_occupancy()
        for z in self.spatial.zones:
            if z.type != "zone":
                continue
            if z.max_objects is not None:
                n = occ.get(z.id, 0)
                if n > z.max_objects and z.id not in self._occupancy_exceeded:
                    self._occupancy_exceeded.add(z.id)
                    events.append(
                        EventRecord(
                            track_id=0, object_class="", event_type="occupancy_exceeded",
                            label=f"{z.name} occupancy above {z.max_objects}", frame_index=frame_index,
                            media_time_s=t, wall_time=wall, object_id=z.id, object_name=z.name,
                            context={"occupancy": n, "max_objects": z.max_objects}, count=False,
                        )
                    )
                elif n <= z.max_objects and z.id in self._occupancy_exceeded:
                    self._occupancy_exceeded.discard(z.id)
            if z.max_dwell_s is not None:
                for tid in self.spatial.tracks_in_zone(z.id):
                    key = (z.id, tid)
                    dwell = self.spatial.dwell_time(z.id, tid, t) or 0.0
                    if dwell > z.max_dwell_s and key not in self._dwell_exceeded:
                        self._dwell_exceeded.add(key)
                        events.append(
                            EventRecord(
                                track_id=tid, object_class=self._track_classes.get(tid, ""),
                                event_type="dwell_exceeded", label=f"{z.name} dwell above {z.max_dwell_s:g} s",
                                frame_index=frame_index, media_time_s=t, wall_time=wall, object_id=z.id,
                                object_name=z.name, entered_at_s=t - dwell, duration_s=dwell,
                                confidence=self._confidence(tid), count=False,
                            )
                        )
        return events

    # ------------------------------------------------------------------ implicit rules
    def _implicit_line(self, ia: Interaction, wall: float) -> list[EventRecord]:
        ln = self.objects.get(ia.object_id or "")
        if not isinstance(ln, LineObject):
            return []
        if "count" not in ln.actions and "record" not in ln.actions:
            return []
        ev = EventRecord(
            track_id=ia.track_id, object_class=ia.class_name, event_type="crossing",
            label=f"{ln.name} {ia.direction}", frame_index=ia.frame_index, media_time_s=ia.t, wall_time=wall,
            object_id=ln.id, object_name=ln.name, direction=ia.direction,
            confidence=self._confidence(ia.track_id),
            record="record" in ln.actions, count="count" in ln.actions,
            context={"object_type": ln.type},
        )
        if ia.extra.get("inferred"):
            # Doorway line: the object disappeared or appeared at the line
            ev.context["inferred"] = ia.extra["inferred"]
        if ev.count:
            self._bump(f"line:{ln.id}:{ia.direction}")
        return [ev]

    def _implicit_zone(self, ia: Interaction, wall: float) -> list[EventRecord]:
        z = self.objects.get(ia.object_id or "")
        if not isinstance(z, ZoneObject) or z.type != "zone":
            return []
        occ = self.spatial.zone_occupancy().get(z.id, 0)
        if ia.kind == "zone_entered":
            if "entry" not in z.measures:
                return []
            self._bump(f"zone:{z.id}:entries")
            return [
                EventRecord(
                    track_id=ia.track_id, object_class=ia.class_name, event_type="zone_entry",
                    label=f"{z.name} entry", frame_index=ia.frame_index, media_time_s=ia.t, wall_time=wall,
                    object_id=z.id, object_name=z.name, entered_at_s=ia.t,
                    confidence=self._confidence(ia.track_id), context={"zone_occupancy": occ},
                )
            ]
        if "exit" not in z.measures and "dwell" not in z.measures:
            return []
        self._bump(f"zone:{z.id}:exits")
        self._dwell_exceeded.discard((z.id, ia.track_id))
        dwell = ia.dwell_s or 0.0
        speed, unit = self._speed(ia.track_id, ia.t - dwell, ia.t)
        return [
            EventRecord(
                track_id=ia.track_id, object_class=ia.class_name, event_type="zone_exit",
                label=f"{z.name} exit", frame_index=ia.frame_index, media_time_s=ia.t, wall_time=wall,
                object_id=z.id, object_name=z.name, entered_at_s=ia.t - dwell, completed_at_s=ia.t,
                duration_s=dwell, avg_speed=speed, speed_unit=unit,
                confidence=self._confidence(ia.track_id),
                context={"zone_occupancy": occ, "reason": ia.extra.get("reason", "left_zone")},
            )
        ]

    # ------------------------------------------------------------------ routes
    def _routes(self, ia: Interaction, wall: float) -> list[EventRecord]:
        events: list[EventRecord] = []
        for g in self.route_groups:
            if g.classes and ia.class_name not in g.classes:
                continue
            start_kind = self._natural_kind(g.start_id)
            if ia.object_id == g.start_id and self._interaction_matches(ia, start_kind, g.start_id, "both"):
                prog = g.progress.get(ia.track_id)
                if prog is not None:
                    prog["restarts"] += 1
                    prog["start_t"] = ia.t
                    prog["start_frame"] = ia.frame_index
                    prog["routes"] = {r.id: 0 for r in g.routes}
                    prog["passed"] = []
                    continue
                g.progress[ia.track_id] = {
                    "start_t": ia.t,
                    "start_frame": ia.frame_index,
                    "start_direction": ia.direction,
                    "routes": {r.id: 0 for r in g.routes},
                    "passed": [],
                    "restarts": 0,
                    "occupancy_at_decision": len(g.progress),
                    "previous_route": g.last_outcome,
                    "zone_occupancy_at_start": self.spatial.zone_occupancy(),
                }
                continue
            prog = g.progress.get(ia.track_id)
            if prog is None:
                # An end gate reached without a start: count for diagnostics only
                if any(ia.object_id == r.end for r in g.routes) and self._interaction_matches(
                    ia, self._natural_kind(ia.object_id or ""), ia.object_id or "", "both"
                ):
                    self.stats["end_without_start"] += 1
                continue
            oid = ia.object_id or ""
            kind = self._natural_kind(oid)
            if not self._interaction_matches(ia, kind, oid, "both"):
                continue
            prog["passed"].append((oid, ia.t))
            completed: list[tuple[RouteDefinition, list[str]]] = []
            reached_end_strict: list[RouteDefinition] = []
            for r in g.routes:
                if r.classes and ia.class_name not in r.classes:
                    continue
                idx = prog["routes"][r.id]
                if idx < len(r.sequence) and oid == r.sequence[idx]:
                    prog["routes"][r.id] = idx + 1
                    if r.end == oid and idx + 1 >= len(r.sequence):
                        completed.append((r, []))
                    continue
                if oid == r.end:
                    if idx >= len(r.sequence):
                        completed.append((r, []))
                    elif not r.strict_sequence:
                        completed.append((r, list(r.sequence[idx:])))
                    else:
                        reached_end_strict.append(r)
            if completed:
                # Prefer the route with the most checkpoints satisfied
                completed.sort(key=lambda rc: prog["routes"][rc[0].id], reverse=True)
                route, missed = completed[0]
                events.append(self._route_outcome(g, ia.track_id, route.name, ia.t, ia.frame_index, wall, prog, route=route, missed=missed, end_object=oid))
                del g.progress[ia.track_id]
            elif reached_end_strict:
                names = [r.name for r in reached_end_strict]
                events.append(
                    self._route_outcome(
                        g, ia.track_id, ROUTE_UNKNOWN, ia.t, ia.frame_index, wall, prog,
                        end_object=oid, extra={"reached_end_of": names, "reason": "checkpoints_missing"},
                    )
                )
                del g.progress[ia.track_id]
        return events

    def _route_outcome(
        self,
        g: RouteGroup,
        track_id: int,
        outcome: str,
        t: float,
        frame_index: int,
        wall: float,
        prog: dict,
        route: RouteDefinition | None = None,
        missed: list[str] | None = None,
        end_object: str | None = None,
        extra: dict | None = None,
    ) -> EventRecord:
        start_t = prog["start_t"]
        speed, unit = self._speed(track_id, start_t, t)
        farthest = None
        best = -1
        for r in g.routes:
            idx = prog["routes"].get(r.id, 0)
            if idx > best:
                best, farthest = idx, r
        switched_from = [
            r.name for r in g.routes if route is not None and r.id != route.id and prog["routes"].get(r.id, 0) > 0
        ]
        context = {
            "group": g.label,
            "start_object": g.start_id,
            "start_direction": prog.get("start_direction"),
            "end_object": end_object,
            "checkpoints": [oid for oid, _ in prog["passed"]],
            "checkpoint_times": [round(tt - start_t, 3) for _, tt in prog["passed"]],
            "occupancy_at_decision": prog.get("occupancy_at_decision"),
            "previous_route": prog.get("previous_route"),
            "zone_occupancy_at_start": prog.get("zone_occupancy_at_start"),
            "restarts": prog.get("restarts", 0),
            "partial_progress": {"route": farthest.name, "checkpoints_passed": best} if farthest and best > 0 else None,
        }
        if switched_from:
            context["switched_from"] = switched_from
        if missed:
            context["missed_checkpoints"] = missed
        if extra:
            context.update(extra)
        # hesitation proxy: time from start to first checkpoint or end
        if prog["passed"]:
            context["decision_time_s"] = round(prog["passed"][0][1] - start_t, 3)
        if outcome in (ROUTE_UNKNOWN, ROUTE_ABANDONED, ROUTE_LOST):
            self._bump(f"route:{g.id}:{outcome}")
            key = {ROUTE_UNKNOWN: "route_unknown", ROUTE_ABANDONED: "route_abandoned", ROUTE_LOST: "route_lost"}[outcome]
            self.stats[key] += 1
        else:
            assert route is not None
            self._bump(f"route:{route.id}")
            self.stats["route_completions"] += 1
            g.completed += 1
            g.last_outcome = route.name
        return EventRecord(
            track_id=track_id,
            object_class=self._track_classes.get(track_id, ""),
            event_type="route",
            label=outcome if route is None else route.name,
            frame_index=frame_index,
            media_time_s=t,
            wall_time=wall,
            rule_id=route.id if route else g.id,
            rule_name=route.name if route else g.label,
            route=outcome if route is None else route.name,
            object_id=end_object,
            object_name=(self.objects[end_object].name if end_object and end_object in self.objects else None),
            entered_at_s=start_t,
            completed_at_s=t,
            duration_s=t - start_t,
            avg_speed=speed,
            speed_unit=unit,
            confidence=self._confidence(track_id),
            context=context,
        )

    def _track_ended(self, ia: Interaction, wall: float) -> list[EventRecord]:
        events: list[EventRecord] = []
        for g in self.route_groups:
            prog = g.progress.pop(ia.track_id, None)
            if prog is not None:
                events.append(self._route_outcome(g, ia.track_id, ROUTE_LOST, ia.t, ia.frame_index, wall, prog))
        for key in [k for k in self._sequences if k[1] == ia.track_id]:
            self.stats["sequence_track_lost"] += 1
            del self._sequences[key]
        for key in [k for k in self._dwell_watch if k[1] == ia.track_id]:
            del self._dwell_watch[key]
        for key in [k for k in self._dwell_exceeded if k[1] == ia.track_id]:
            self._dwell_exceeded.discard(key)
        if self._pending:
            # The track is gone: whatever was recognized by now is final.
            events.extend(self._flush_pending(ia.t, track_id=ia.track_id, final=True))
        self._enrich(events)
        self.entities.forget(ia.track_id)
        return events

    # ------------------------------------------------------------------ explicit rules
    def _apply_actions(self, ev: EventRecord, rule: Rule) -> None:
        ev.record = any(a.kind == "record_event" for a in rule.actions)
        ev.count = any(a.kind == "count" for a in rule.actions)
        ev.webhooks = [a.url for a in rule.actions if a.kind == "webhook" and a.url]

    def _explicit(self, ia: Interaction, wall: float) -> list[EventRecord]:
        events: list[EventRecord] = []
        for rule in self.rules:
            if not self._class_ok(rule.classes, ia.class_name):
                continue
            trig = rule.trigger
            key = (rule.id, ia.track_id)
            # advance an existing sequence?
            st = self._sequences.get(key)
            if st is not None and st.step_index < len(rule.then):
                step: RuleStep = rule.then[st.step_index]
                if self._interaction_matches(ia, step.kind, step.object_id, step.direction):
                    if step.within_s is not None and ia.t - st.last_t > step.within_s:
                        del self._sequences[key]
                        self.stats["sequence_expired"] += 1
                    else:
                        st.step_index += 1
                        st.last_t = ia.t
                        st.passed.append((step.object_id, ia.t))
                        if st.step_index >= len(rule.then):
                            speed, unit = self._speed(ia.track_id, st.start_t, ia.t)
                            obj = self.objects.get(step.object_id)
                            ev = EventRecord(
                                track_id=ia.track_id, object_class=ia.class_name, event_type="sequence",
                                label=rule.label, frame_index=ia.frame_index, media_time_s=ia.t, wall_time=wall,
                                rule_id=rule.id, rule_name=rule.name or rule.label, route=rule.record_as or None,
                                object_id=step.object_id, object_name=obj.name if obj else None,
                                direction=ia.direction, entered_at_s=st.start_t, completed_at_s=ia.t,
                                duration_s=ia.t - st.start_t, avg_speed=speed, speed_unit=unit,
                                confidence=self._confidence(ia.track_id),
                                context={"steps": [oid for oid, _ in st.passed], "step_times": [round(tt - st.start_t, 3) for _, tt in st.passed]},
                            )
                            if ia.extra.get("inferred"):
                                ev.context["inferred"] = ia.extra["inferred"]
                            self._apply_actions(ev, rule)
                            events.extend(self._emit(ev, rule, ia.track_id))
                            del self._sequences[key]
                        continue
            # trigger?
            if not self._interaction_matches(ia, trig.kind, trig.object_id, trig.direction):
                if rule.remains_for_s is not None and ia.kind == "zone_exited" and ia.object_id == trig.object_id:
                    self._dwell_watch.pop(key, None)
                continue
            if rule.remains_for_s is not None:
                self._dwell_watch[key] = {"rule": rule, "track_id": ia.track_id, "class_name": ia.class_name, "since": ia.t, "fired": False}
                continue
            if rule.then:
                self._sequences[key] = SequenceState(rule, ia.track_id, ia.t, ia.frame_index, 0, ia.t, [(trig.object_id, ia.t)])
                continue
            obj = self.objects.get(trig.object_id)
            ev = EventRecord(
                track_id=ia.track_id, object_class=ia.class_name, event_type="rule",
                label=rule.label, frame_index=ia.frame_index, media_time_s=ia.t, wall_time=wall,
                rule_id=rule.id, rule_name=rule.name or rule.label, object_id=trig.object_id,
                object_name=obj.name if obj else None, direction=ia.direction,
                confidence=self._confidence(ia.track_id), duration_s=ia.dwell_s,
            )
            self._apply_actions(ev, rule)
            events.extend(self._emit(ev, rule, ia.track_id))
        return events

    def describe(self) -> dict:
        return {
            "implicit_lines": len([ln for ln in self.scene.lines() if ln.enabled]),
            "implicit_zones": len([z for z in self.scene.zones() if z.enabled and z.type == "zone"]),
            "route_groups": [
                {"id": g.id, "start": g.label, "routes": [r.name for r in g.routes], "timeout_s": g.timeout_s}
                for g in self.route_groups
            ],
            "explicit_rules": len(self.rules),
            "subject_rules": len([r for r in self.rules if r.subject.active]),
            "relation_rules": len([r for r in self.rules if r.relation is not None]),
            "recognition_modules": sorted(self.entities.provides()),
            "inactive_rules": [
                {"id": r.id, "name": r.label, "needs": sorted(r.modules_needed) + (["relationships"] if r.relation is not None else [])} for r in self.inactive_rules
            ],
            "subject_grace_s": self.subject_grace_s,
        }
