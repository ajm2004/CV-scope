"""Multi-event correlation.

Two detectors work on *facts* (observations and relationships the engine
has already established), never on pixels:

* ``SequenceMatcher`` - a correlation rule: roles A and B, ordered steps,
  each at most ``within_s`` after the previous one, the whole match within
  ``window_s``. When every step is matched the rule creates its relationship
  (A -> B) and/or a correlated event, linked to the facts that support it;
  the lower-level facts stay as they are.
* ``RouteFollower`` - "B follows A through N checkpoints": B reaches the same
  places as A, in the same order, each time at most ``max_lag_s`` after A.

Both are deterministic: a correlated event exists only because its steps
were observed within the configured times.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathscope.relationships.confidence import at_least
from pathscope.relationships.rules import RelationRuleDefinition, SequenceStep
from pathscope.relationships.temporal import Interval, relations_between, within


@dataclass
class Fact:
    kind: str  # relation | place | appears | disappears | event
    t: float
    wall: float
    tid: int  # the track the fact is about (relation: subject)
    object_class: str = ""
    other_tid: int | None = None  # relation: the object track
    other_class: str = ""
    relation: str | None = None
    state: str | None = None
    confidence: float | None = None
    place_event: str | None = None  # enters | exits | crosses | uses_route
    place_id: str | None = None
    event_type: str | None = None
    uid: str = ""
    is_relation: bool = False
    end_t: float | None = None


@dataclass
class Match:
    """A completed correlation."""

    rule_index: int
    bindings: dict[str, int]
    classes: dict[str, str]
    facts: list[tuple[int, Fact]]  # (step index, fact)
    first_t: float
    last_t: float
    first_wall: float
    last_wall: float

    def temporal_links(self) -> list[dict]:
        out: list[dict] = []
        for (_i, a), (j, b) in zip(self.facts, self.facts[1:], strict=False):
            rels = relations_between(Interval(b.t, b.end_t), Interval(a.t, a.end_t))
            for rel, gap_s in rels:
                if rel in ("FOLLOWED_AFTER", "OVERLAPPED_WITH", "STARTED_AFTER"):
                    out.append({"a": b.uid, "relation": rel, "b": a.uid, "gap_s": gap_s, "step": j + 1})
                    break
        return out


@dataclass
class _Partial:
    bindings: dict[str, int]
    classes: dict[str, str]
    step: int
    first_t: float
    last_t: float
    first_wall: float
    last_wall: float
    facts: list[tuple[int, Fact]] = field(default_factory=list)
    both: dict[str, Fact] = field(default_factory=dict)  # role both: the half already seen


class SequenceMatcher:
    MAX_PARTIALS = 400

    def __init__(self, rule_index: int, rule: RelationRuleDefinition, role_ok) -> None:
        """``role_ok(role, tid, object_class) -> bool`` checks classes (and identities that are already known)."""
        self.rule_index = rule_index
        self.rule = rule
        self.steps: list[SequenceStep] = rule.steps
        self.role_ok = role_ok
        self.partials: list[_Partial] = []
        self._done: dict[tuple[int, int], float] = {}  # bindings -> last completion time

    # ------------------------------------------------------------ matching one step
    def _roles_of(self, step: SequenceStep) -> list[str]:
        return ["A", "B"] if step.role == "both" else [step.role]

    def _match(self, step: SequenceStep, f: Fact, role: str, bindings: dict[str, int]) -> dict[str, int] | None:
        """New bindings if the fact satisfies the step for this role, else None."""
        if step.what == "relation":
            if f.kind != "relation" or f.relation != step.relation or not at_least(f.state or "insufficient", step.min_state):
                return None
            pairs = [(f.tid, f.object_class, f.other_tid, f.other_class)]
            if step.any_direction and f.other_tid is not None:
                pairs.append((f.other_tid, f.other_class, f.tid, f.object_class))
            for a, a_cls, b, b_cls in pairs:
                if b is None:
                    continue
                nb = self._bind(bindings, "A", a, a_cls)
                if nb is None:
                    continue
                nb = self._bind(nb, "B", b, b_cls)
                if nb is not None:
                    return nb
            return None
        if step.what == "place":
            if f.kind != "place" or f.place_event != step.place_event:
                return None
            if step.places and f.place_id not in step.places:
                return None
        elif step.what in ("appears", "disappears"):
            if f.kind != step.what:
                return None
        elif step.what == "event":
            if f.kind != "event" or f.event_type != step.event_type:
                return None
        return self._bind(bindings, role, f.tid, f.object_class)

    def _bind(self, bindings: dict[str, int], role: str, tid: int, object_class: str) -> dict[str, int] | None:
        cur = bindings.get(role)
        if cur is not None:
            return bindings if cur == tid else None
        other = "B" if role == "A" else "A"
        if bindings.get(other) == tid:
            return None  # A and B are different entities
        if not self.role_ok(role, tid, object_class):
            return None
        return {**bindings, role: tid}

    # ------------------------------------------------------------ feeding facts
    def feed(self, f: Fact) -> list[Match]:
        done: list[Match] = []
        keep: list[_Partial] = []
        for p in self.partials:
            if f.t - p.first_t > self.rule.window_s:
                continue  # expired
            advanced = self._advance(p, f)
            if advanced is not None:
                if advanced.step >= len(self.steps):
                    m = self._complete(advanced)
                    if m is not None:
                        done.append(m)
                    continue
                keep.append(advanced)
                # the unadvanced partial may still match a later, better fact
                if advanced is not p:
                    keep.append(p)
            else:
                keep.append(p)
        self.partials = keep
        # start a new partial with this fact?
        first = self.steps[0]
        for role in self._roles_of(first):
            nb = self._match(first, f, role, {})
            if nb is None:
                continue
            p = _Partial(nb, {}, 0, f.t, f.t, f.wall, f.wall)
            p.classes = self._classes(nb, f)
            if first.role == "both":
                p.both = {role: f}
                self.partials.append(p)
            else:
                p.facts = [(0, f)]
                p.step = 1
                if p.step >= len(self.steps):
                    m = self._complete(p)
                    if m is not None:
                        done.append(m)
                else:
                    self.partials.append(p)
            break
        if len(self.partials) > self.MAX_PARTIALS:
            self.partials = self.partials[-self.MAX_PARTIALS:]
        return done

    @staticmethod
    def _classes(bindings: dict[str, int], f: Fact) -> dict[str, str]:
        out: dict[str, str] = {}
        for role, tid in bindings.items():
            if tid == f.tid:
                out[role] = f.object_class
            elif tid == f.other_tid:
                out[role] = f.other_class
        return out

    def _advance(self, p: _Partial, f: Fact) -> _Partial | None:
        step = self.steps[p.step]
        if step.role == "both":
            for role in ("A", "B"):
                if role in p.both:
                    continue
                if p.facts and not within(p.last_t, f.t, step.within_s):
                    return None
                nb = self._match(step, f, role, p.bindings)
                if nb is None:
                    continue
                q = _Partial(nb, {**p.classes, **self._classes(nb, f)}, p.step, p.first_t, p.last_t, p.first_wall, p.last_wall, list(p.facts), {**p.both, role: f})
                if len(q.both) == 2:
                    a, b = q.both["A"], q.both["B"]
                    if abs(a.t - b.t) > step.together_s:
                        return None
                    later = a if a.t >= b.t else b
                    q.facts += [(p.step, a), (p.step, b)]
                    q.both = {}
                    q.step += 1
                    q.last_t, q.last_wall = later.t, later.wall
                    if q.first_t > min(a.t, b.t):
                        q.first_t = min(a.t, b.t)
                return q
            return None
        if p.facts and not within(p.last_t, f.t, step.within_s):
            return None
        nb = self._match(step, f, step.role, p.bindings)
        if nb is None:
            return None
        return _Partial(nb, {**p.classes, **self._classes(nb, f)}, p.step + 1, p.first_t, f.t, p.first_wall, f.wall, [*p.facts, (p.step, f)])

    def _complete(self, p: _Partial) -> Match | None:
        key = (p.bindings.get("A", 0), p.bindings.get("B", 0))
        last = self._done.get(key)
        if last is not None and p.first_t <= last:
            return None  # the same pair already matched over these facts
        self._done[key] = p.last_t
        return Match(self.rule_index, dict(p.bindings), dict(p.classes), list(p.facts), p.first_t, p.last_t, p.first_wall, p.last_wall)

    def forget(self, tid: int) -> None:
        """A track ended: partials still waiting for its facts can never complete."""
        self.partials = [p for p in self.partials if tid not in p.bindings.values() or self._can_continue_without(p, tid)]

    def _can_continue_without(self, p: _Partial, tid: int) -> bool:
        # A step that needs the ended track (other than 'disappears') can no longer be observed
        for step in self.steps[p.step:]:
            roles = self._roles_of(step)
            for role in roles:
                if p.bindings.get(role) == tid and step.what != "disappears":
                    return False
        return True


@dataclass
class _Visit:
    place_id: str
    t: float
    wall: float
    uid: str


@dataclass
class FollowMatch:
    leader: int
    follower: int
    visits: list[tuple[_Visit, _Visit]]  # (leader visit, follower visit)

    @property
    def lags(self) -> list[float]:
        return [round(b.t - a.t, 3) for a, b in self.visits]


class RouteFollower:
    """B reaches the same places as A in the same order, each at most max_lag_s later."""

    def __init__(self, rule: RelationRuleDefinition, role_ok) -> None:
        self.rule = rule
        self.role_ok = role_ok
        self.history: dict[int, list[_Visit]] = {}
        self.classes: dict[int, str] = {}
        self.chains: dict[tuple[int, int], list[tuple[_Visit, _Visit]]] = {}  # (leader, follower)
        self.reported: dict[tuple[int, int], int] = {}

    def feed(self, f: Fact) -> list[FollowMatch]:
        if f.kind != "place" or f.place_event not in ("enters", "crosses") or not f.place_id:
            return []
        if self.rule.places and f.place_id not in self.rule.places:
            return []
        v = _Visit(f.place_id, f.t, f.wall, f.uid)
        self.classes[f.tid] = f.object_class
        out: list[FollowMatch] = []
        for leader, visits in self.history.items():
            if leader == f.tid:
                continue
            match = None
            for lv in reversed(visits):
                if lv.place_id == f.place_id and 0 < f.t - lv.t <= self.rule.max_lag_s:
                    match = lv
                    break
            if match is None:
                continue
            if not (self.role_ok("A", f.tid, f.object_class) and self.role_ok("B", leader, self.classes.get(leader, ""))):
                continue
            key = (leader, f.tid)
            chain = self.chains.setdefault(key, [])
            if chain:
                last_l, last_f = chain[-1]
                if match.t <= last_l.t or f.t <= last_f.t or match.place_id == last_l.place_id:
                    continue
            chain.append((match, v))
            while chain and chain[-1][1].t - chain[0][0].t > self.rule.window_s:
                chain.pop(0)
            if len(chain) >= self.rule.min_checkpoints and len(chain) > self.reported.get(key, 0):
                self.reported[key] = len(chain)
                out.append(FollowMatch(leader, f.tid, list(chain)))
        hist = self.history.setdefault(f.tid, [])
        hist.append(v)
        while hist and f.t - hist[0].t > self.rule.window_s:
            hist.pop(0)
        return out

    def prune(self, t: float) -> None:
        """Drop tracks whose path nobody can still follow (ended tracks stay for max_lag_s)."""
        horizon = self.rule.window_s + self.rule.max_lag_s
        for tid in [k for k, v in self.history.items() if not v or t - v[-1].t > horizon]:
            del self.history[tid]
        for key in [k for k, v in self.chains.items() if not v or t - v[-1][1].t > horizon]:
            del self.chains[key]
            self.reported.pop(key, None)
