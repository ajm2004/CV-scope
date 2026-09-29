"""Relationship formation rules (structured, versioned).

A rule reads like the sentence the rule editor shows:

    pair          WHEN <subject> <is within | approaches | moves away from | moves together with |
                  follows | disappears near | appears near | stops near> <object>
                  [DISTANCE 2 m (uncalibrated: 0.06 frame widths)] [FOR 5 s] [AND <extra conditions>]
                  CREATE RELATIONSHIP <type>
    place         WHEN <subject> <enters | exits | crosses | uses route | remains in | stops in |
                  moves from .. to> <places> [FOR n s]  CREATE RELATIONSHIP <type>
    follow_route  WHEN <subject> follows <object> through <n> checkpoints within <T> s
                  (each at most <lag> s behind)  CREATE RELATIONSHIP FOLLOWED
    sequence      WHEN <step 1> THEN <step 2> WITHIN n s THEN ...      (roles A and B)
                  CREATE RELATIONSHIP <type> (A -> B) and/or CREATE EVENT <label>

Subjects and objects are role filters: object classes plus the same
recognition clause the rule builder uses (any, anonymous, recognized,
registered, specific identities / plates / vehicles / groups).

Rules are stored immutably by (key, version); editing a rule stores a new
version, and every relationship records the version that created it, so a
changed threshold never re-interprets past data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from pathscope.domain.entities import EntityRef, anonymous_entity
from pathscope.domain.rules import RuleSubject, modules_for_classes
from pathscope.domain.scene import new_id
from pathscope.relationships.relations import check_rule_output

RuleKind = Literal["pair", "place", "follow_route", "sequence"]
PairCondition = Literal["near", "approaches", "moves_away", "moves_together", "follows", "disappears_near", "appears_near", "stopped_near"]
PlaceEvent = Literal["enters", "exits", "crosses", "uses_route", "remains_in", "stops_in", "moves_between"]
StateName = Literal["confirmed", "likely", "possible", "insufficient"]

DEFAULT_PAIR_RELATION = {
    "near": "NEAR", "approaches": "APPROACHED", "moves_away": "MOVED_AWAY_FROM", "moves_together": "TRAVELLED_WITH", "follows": "FOLLOWED",
    "disappears_near": "ENTERED_VEHICLE", "appears_near": "EXITED_VEHICLE", "stopped_near": "STOPPED_NEAR",
}
DEFAULT_PLACE_RELATION = {
    "enters": "ENTERED", "exits": "EXITED", "crosses": "CROSSED", "uses_route": "USED_ROUTE", "remains_in": "REMAINED_IN", "stops_in": "PARKED_IN", "moves_between": "MOVED_TO",
}
NEEDS_DISTANCE = {"near", "approaches", "moves_away", "moves_together", "follows", "disappears_near", "appears_near", "stopped_near"}


class RoleFilter(BaseModel):
    """Which entities may take a role: classes plus a recognition condition."""

    classes: list[str] = Field(default_factory=list, description="Empty = any tracked class")
    subject: RuleSubject = Field(default_factory=RuleSubject)

    def class_ok(self, object_class: str) -> bool:
        return not self.classes or object_class in self.classes

    def evaluate(self, entity: EntityRef | None, track_id: int = 0, object_class: str = "") -> bool | None:
        if not self.subject.active:
            return True
        return self.subject.evaluate(entity or anonymous_entity(track_id, object_class))

    @property
    def modules_needed(self) -> set[str]:
        return modules_for_classes(self.classes) if self.subject.active else set()


class DistanceSpec(BaseModel):
    value: float = Field(gt=0, description="In metres (unit m) or frame widths (unit fw)")
    unit: Literal["m", "fw"] = "m"
    fallback_fw: float | None = Field(default=None, gt=0, description="Used when the scene is not calibrated")


class ExtraCondition(BaseModel):
    kind: Literal["in_zone", "not_in_zone", "speed_below", "speed_above"]
    role: Literal["subject", "object", "both"] = "both"
    zone_ids: list[str] = Field(default_factory=list)
    value: float | None = Field(default=None, ge=0, description="Speed in m/s (calibrated scenes)")
    value_fw: float | None = Field(default=None, ge=0, description="Speed in frame widths/s (uncalibrated scenes)")

    @model_validator(mode="after")
    def _complete(self) -> ExtraCondition:
        if self.kind in ("in_zone", "not_in_zone") and not self.zone_ids:
            raise ValueError("a zone condition needs at least one zone")
        if self.kind in ("speed_below", "speed_above") and self.value is None and self.value_fw is None:
            raise ValueError("a speed condition needs a speed")
        return self


class RuleAction(BaseModel):
    kind: Literal["record_event", "webhook"] = "record_event"
    url: str | None = None


class SequenceStep(BaseModel):
    """One step of a correlation rule. Roles: A = the rule's subject, B = its object."""

    role: Literal["A", "B", "both"] = "A"
    what: Literal["relation", "place", "appears", "disappears", "event"] = "relation"
    relation: str | None = Field(default=None, description="A <relation> B (either direction when any_direction)")
    any_direction: bool = True
    place_event: Literal["enters", "exits", "crosses", "uses_route"] | None = None
    places: list[str] = Field(default_factory=list, description="Scene object or route ids; empty = any")
    event_type: str | None = Field(default=None, description="Ordinary event type, for example anomaly")
    within_s: float | None = Field(default=None, gt=0, description="At most this long after the previous step")
    together_s: float = Field(default=15.0, gt=0, description="Role both: A and B within this of each other")
    min_state: StateName = "possible"

    @model_validator(mode="after")
    def _complete(self) -> SequenceStep:
        if self.what == "relation":
            if not self.relation:
                raise ValueError("a relationship step needs a relationship type")
            if self.role == "both":
                self.role = "A"
        if self.what == "place" and not self.place_event:
            raise ValueError("a place step needs enters / exits / crosses / uses route")
        if self.what == "event" and not self.event_type:
            raise ValueError("an event step needs an event type")
        return self


class RelationRuleDefinition(BaseModel):
    kind: RuleKind = "pair"
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    subject: RoleFilter = Field(default_factory=RoleFilter)
    object: RoleFilter | None = None
    # pair
    condition: PairCondition | None = None
    distance: DistanceSpec | None = None
    from_distance: DistanceSpec | None = Field(default=None, description="approaches: started at least this far; moves away: ended at least this far")
    for_s: float = Field(default=0.0, ge=0, le=86400)
    gap_s: float = Field(default=1.0, ge=0, le=60, description="Short interruptions that do not end the condition")
    min_speed: float = Field(default=0.3, ge=0, description="Moving: at least this fast (m/s)")
    min_speed_fw: float = Field(default=0.03, ge=0, description="Moving on uncalibrated scenes (frame widths/s)")
    stop_speed: float = Field(default=0.2, ge=0, description="Standing still: slower than this (m/s)")
    stop_speed_fw: float = Field(default=0.01, ge=0, description="Standing still on uncalibrated scenes (frame widths/s)")
    max_heading_deg: float = Field(default=40.0, gt=0, le=180)
    lag_min_s: float = Field(default=1.0, ge=0)
    lag_max_s: float = Field(default=10.0, gt=0, le=300)
    conditions: list[ExtraCondition] = Field(default_factory=list)
    # place
    place_event: PlaceEvent | None = None
    places: list[str] = Field(default_factory=list, description="Scene object ids (routes for uses_route); empty = any")
    to_places: list[str] = Field(default_factory=list, description="moves_between: destination places")
    # follow_route
    min_checkpoints: int = Field(default=3, ge=2, le=50)
    max_lag_s: float = Field(default=20.0, gt=0, le=600)
    # sequence (and follow_route: whole movement)
    steps: list[SequenceStep] = Field(default_factory=list)
    window_s: float = Field(default=60.0, gt=0, le=86400)
    # output
    relation: str | None = None
    event_label: str | None = Field(default=None, max_length=200)
    act_min_state: StateName = "likely"
    actions: list[RuleAction] = Field(default_factory=list)

    @field_validator("relation")
    @classmethod
    def _relation_ok(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip().upper()
        check_rule_output(v)
        return v

    @model_validator(mode="after")
    def _by_kind(self) -> RelationRuleDefinition:
        if self.kind == "pair":
            if self.object is None:
                raise ValueError("a pair rule needs an object")
            if self.condition is None:
                raise ValueError("a pair rule needs a condition")
            if self.condition in NEEDS_DISTANCE and self.distance is None:
                raise ValueError("this condition needs a distance")
            if self.condition in ("approaches", "moves_away") and self.from_distance is not None and self.distance is not None and self.from_distance.unit == self.distance.unit and self.from_distance.value <= self.distance.value:
                raise ValueError("the starting distance must be larger than the distance")
            if self.lag_max_s <= self.lag_min_s:
                raise ValueError("the longest lag must be larger than the shortest")
            if self.relation is None:
                self.relation = DEFAULT_PAIR_RELATION[self.condition]
        elif self.kind == "place":
            if self.place_event is None:
                raise ValueError("a place rule needs enters / exits / crosses / uses route / remains in / stops in / moves between")
            if self.place_event == "moves_between" and not (self.places and self.to_places):
                raise ValueError("moves between needs the places it leaves and the places it reaches")
            if self.place_event in ("remains_in", "stops_in") and self.for_s <= 0:
                raise ValueError("remains in / stops in need a time (FOR n s)")
            if self.relation is None:
                self.relation = DEFAULT_PLACE_RELATION[self.place_event]
        elif self.kind == "follow_route":
            if self.object is None:
                raise ValueError("a follow rule needs the entity that is followed")
            if self.relation is None:
                self.relation = "FOLLOWED"
        elif self.kind == "sequence":
            if not self.steps:
                raise ValueError("a sequence rule needs at least one step")
            uses_b = any(s.role in ("B", "both") or s.what == "relation" for s in self.steps)
            if uses_b and self.object is None:
                self.object = RoleFilter()
            if not self.relation and not self.event_label:
                raise ValueError("a sequence rule creates a relationship, an event, or both")
            if self.relation and self.object is None:
                raise ValueError("a relationship needs role B")
        return self

    @property
    def modules_needed(self) -> set[str]:
        out = set(self.subject.modules_needed)
        if self.object is not None:
            out |= self.object.modules_needed
        return out

    @property
    def uses_distance(self) -> bool:
        return self.kind == "pair" and self.condition in NEEDS_DISTANCE

    def summary(self) -> str:
        """The rule as one sentence (for lists and provenance)."""
        who = _role_text(self.subject)
        other = _role_text(self.object) if self.object else "another entity"
        out = f"CREATE {self.relation}" if self.relation else ""
        if self.event_label:
            out = (out + " and " if out else "") + f"EVENT '{self.event_label}'"
        if self.kind == "pair":
            d = self.distance
            dist = f" {d.value:g} {'m' if d.unit == 'm' else 'frame widths'}" if d else ""
            cond = {
                "near": f"is within{dist} of", "approaches": f"approaches (to{dist})", "moves_away": f"moves away from (beyond{dist})",
                "moves_together": f"moves together with (within{dist})", "follows": f"follows (path within{dist})", "disappears_near": f"disappears within{dist} of",
                "appears_near": f"appears within{dist} of", "stopped_near": f"stops within{dist} of",
            }[self.condition or "near"]
            dur = f" for {self.for_s:g} s" if self.for_s > 0 else ""
            return f"WHEN {who} {cond} {other}{dur} {out}".strip()
        if self.kind == "place":
            where = ", ".join(self.places) or "any place"
            dur = f" for {self.for_s:g} s" if self.for_s > 0 else ""
            return f"WHEN {who} {(self.place_event or '').replace('_', ' ')} {where}{dur} {out}".strip()
        if self.kind == "follow_route":
            return f"WHEN {who} follows {other} through {self.min_checkpoints} checkpoints within {self.window_s:g} s {out}".strip()
        return f"WHEN {len(self.steps)} steps of A={who}, B={other} within {self.window_s:g} s {out}".strip()


def _role_text(r: RoleFilter | None) -> str:
    if r is None:
        return "anything"
    classes = "/".join(r.classes) if r.classes else "any object"
    if not r.subject.active:
        return classes
    return f"{classes} ({r.subject.mode})"


class CompiledRule(BaseModel):
    """A stored rule version as the engine uses it."""

    key: str
    version: int
    definition: RelationRuleDefinition


def new_rule_key() -> str:
    return new_id("rel")


# ---------------------------------------------------------------------------- experiment settings
class RuleRef(BaseModel):
    key: str
    version: int | None = Field(default=None, description="None = the latest version when a run starts")


class Expectation(BaseModel):
    """A configured pattern: where entities of a kind are expected (or not)."""

    id: str = Field(default_factory=lambda: new_id("exp"))
    name: str = ""
    enabled: bool = True
    subject: RoleFilter = Field(default_factory=RoleFilter)
    relation: Literal["ENTERED", "CROSSED", "USED_ROUTE", "PARKED_IN", "REMAINED_IN"] = "ENTERED"
    allowed_places: list[str] = Field(default_factory=list, description="Only these places are expected")
    forbidden_places: list[str] = Field(default_factory=list, description="These places are not expected")

    @model_validator(mode="after")
    def _some_places(self) -> Expectation:
        if not self.allowed_places and not self.forbidden_places:
            raise ValueError("an expectation lists the expected or the unexpected places")
        return self


class RelationExperimentSettings(BaseModel):
    enabled: bool = False
    rules: list[RuleRef] = Field(default_factory=list)
    identity: bool = Field(default=True, description="IDENTIFIED_AS / IDENTIFIED_BY_PLATE / REGISTERED_AS from recognition results")
    places: bool = Field(default=True, description="ENTERED / EXITED / CROSSED / USED_ROUTE / REMAINED_IN / MOVED_FROM / MOVED_TO")
    occupied: bool = Field(default=False, description="Also OCCUPIED (entry to exit) for every zone visit")
    remained_min_s: float = Field(default=10.0, ge=0)
    transition_s: float = Field(default=30.0, gt=0, description="MOVED_FROM / MOVED_TO when the next place is reached within this time")
    sample_s: float = Field(default=0.2, ge=0.05, le=2.0, description="Spatial conditions are measured this often")
    max_tracks: int = Field(default=60, ge=2, le=500, description="Pairs are measured among at most this many tracks")
    expectations: list[Expectation] = Field(default_factory=list)
    learn_patterns: bool = Field(default=True, description="Report deviations from the entity's own history")
    pattern_min_sessions: int = Field(default=5, ge=2, le=1000)
    pattern_rare_share: float = Field(default=0.1, gt=0, lt=1)
    publish_deviations: bool = Field(default=True, description="Deviations become ordinary events of the run")


def relation_settings(raw: dict | None) -> RelationExperimentSettings:
    """Stored settings (tolerant: an unreadable value means off)."""
    if not raw:
        return RelationExperimentSettings()
    try:
        return RelationExperimentSettings.model_validate(raw)
    except ValueError:
        return RelationExperimentSettings()


# ---------------------------------------------------------------------------- templates
def templates() -> list[dict]:
    """Starting points offered by the rule editor (not added to the library by themselves)."""
    person = {"classes": ["person"]}
    vehicle = {"classes": ["car", "truck", "bus", "motorcycle"]}
    t = [
        {"id": "person_near_vehicle", "title": "Person stays beside a vehicle", "definition": {
            "kind": "pair", "name": "Person beside vehicle", "subject": person, "object": vehicle, "condition": "near",
            "distance": {"value": 2.0, "unit": "m", "fallback_fw": 0.06}, "for_s": 5, "relation": "ASSOCIATED_WITH"}},
        {"id": "person_approaches_vehicle", "title": "Person approaches a vehicle", "definition": {
            "kind": "pair", "name": "Approached vehicle", "subject": person, "object": vehicle, "condition": "approaches",
            "distance": {"value": 2.0, "unit": "m", "fallback_fw": 0.06}, "from_distance": {"value": 6.0, "unit": "m", "fallback_fw": 0.18}, "relation": "APPROACHED"}},
        {"id": "people_near", "title": "Two people remain near each other", "definition": {
            "kind": "pair", "name": "People near each other", "subject": person, "object": person, "condition": "near",
            "distance": {"value": 2.0, "unit": "m", "fallback_fw": 0.06}, "for_s": 10, "relation": "NEAR"}},
        {"id": "walking_together", "title": "People walk together", "definition": {
            "kind": "pair", "name": "Walking together", "subject": person, "object": person, "condition": "moves_together",
            "distance": {"value": 1.5, "unit": "m", "fallback_fw": 0.05}, "for_s": 5, "relation": "TRAVELLED_WITH"}},
        {"id": "following", "title": "One track follows another", "definition": {
            "kind": "pair", "name": "Following", "subject": person, "object": person, "condition": "follows",
            "distance": {"value": 1.5, "unit": "m", "fallback_fw": 0.05}, "for_s": 6, "lag_min_s": 1.5, "lag_max_s": 10, "relation": "FOLLOWED"}},
        {"id": "entered_vehicle", "title": "Person gets into a vehicle", "definition": {
            "kind": "pair", "name": "Entered vehicle", "subject": person, "object": vehicle, "condition": "disappears_near",
            "distance": {"value": 1.5, "unit": "m", "fallback_fw": 0.05}, "relation": "ENTERED_VEHICLE"}},
        {"id": "exited_vehicle", "title": "Person gets out of a vehicle", "definition": {
            "kind": "pair", "name": "Exited vehicle", "subject": person, "object": vehicle, "condition": "appears_near",
            "distance": {"value": 1.5, "unit": "m", "fallback_fw": 0.05}, "relation": "EXITED_VEHICLE"}},
        {"id": "convoy", "title": "Vehicles travel together", "definition": {
            "kind": "pair", "name": "Vehicles together", "subject": vehicle, "object": vehicle, "condition": "moves_together",
            "distance": {"value": 15.0, "unit": "m", "fallback_fw": 0.3}, "for_s": 8, "relation": "TRAVELLED_WITH"}},
        {"id": "parked", "title": "Vehicle parks in a zone", "definition": {
            "kind": "place", "name": "Parked", "subject": vehicle, "place_event": "stops_in", "for_s": 30, "relation": "PARKED_IN"}},
        {"id": "departed_with", "title": "Person leaves with a vehicle", "definition": {
            "kind": "sequence", "name": "Departed with vehicle", "subject": person, "object": vehicle, "window_s": 180,
            "steps": [
                {"role": "A", "what": "relation", "relation": "ASSOCIATED_WITH", "min_state": "likely"},
                {"role": "A", "what": "relation", "relation": "ENTERED_VEHICLE", "within_s": 120},
                {"role": "B", "what": "disappears", "within_s": 60},
            ],
            "relation": "DEPARTED_WITH", "event_label": "Departed with vehicle"}},
        {"id": "arrived_with", "title": "Person arrives with a vehicle", "definition": {
            "kind": "sequence", "name": "Arrived with vehicle", "subject": person, "object": vehicle, "window_s": 120,
            "steps": [
                {"role": "B", "what": "appears"},
                {"role": "A", "what": "relation", "relation": "EXITED_VEHICLE", "within_s": 90},
            ],
            "relation": "ARRIVED_WITH"}},
        {"id": "shared_route", "title": "Shared route movement", "definition": {
            "kind": "follow_route", "name": "Shared route movement", "subject": person, "object": person,
            "min_checkpoints": 3, "max_lag_s": 20, "window_s": 60, "relation": "FOLLOWED", "event_label": "Shared route movement"}},
    ]
    return t
