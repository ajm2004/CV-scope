"""Structured rules built with the rule builder (no code).

A rule reads like a sentence:

    WHEN <classes> [<subject>] <trigger: CROSSES|ENTERS|EXITS> <object>
    [THEN <CROSSES|ENTERS|EXITS> <object> WITHIN <n> s]...
    [AND REMAINS FOR more than <n> s]
    [AND HAS RELATIONSHIP <type> WITH <other>]            (relationship engine)
    RECORD AS <label> / COUNT AS <label> / CREATE EVENT <label>

The optional subject clause is provided by the licensed recognition modules:

    Recognized Person is Employee-017 / Vehicle Plate equals ABC12345 /
    Registered Vehicle belongs to group Delivery Fleet

Internally the rule engine turns each rule into a per-track state machine; the
subject is evaluated against the entity the track resolves to (see
``pathscope.domain.entities``) when the event would be emitted.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from pathscope.domain.entities import STATUS_RECOGNIZED, EntityRef
from pathscope.domain.scene import VEHICLE_CLASSES, Direction, new_id

InteractionKind = Literal["crosses", "enters", "exits"]
ActionKind = Literal["count", "record_event", "webhook", "log"]

# any:        no recognition condition (the open-source default)
# anonymous:  nobody / no plate was recognized for the track
# recognized: a person was matched to an enrolled identity, or a plate was read
# registered: the plate belongs to a registered vehicle (optionally in groups)
# specific:   one of the listed identities, plates or vehicles
SubjectMode = Literal["any", "anonymous", "recognized", "registered", "specific"]

_PLATE_CLEAN = re.compile(r"[^A-Z0-9]")


def normalize_plate_text(text: str) -> str:
    return _PLATE_CLEAN.sub("", (text or "").upper())


class RuleTrigger(BaseModel):
    kind: InteractionKind = "crosses"
    object_id: str
    direction: Direction = "both"


class RuleStep(BaseModel):
    kind: InteractionKind = "crosses"
    object_id: str
    direction: Direction = "both"
    within_s: float | None = Field(default=None, gt=0, description="Deadline from previous step")


class RuleAction(BaseModel):
    kind: ActionKind = "record_event"
    label: str | None = None
    url: str | None = None  # webhook target


class RuleSubject(BaseModel):
    """Recognition condition on the tracked object (licensed modules).

    For people the identity comes from the face module, for vehicles from the
    plate module. A rule whose subject is not ``any`` stays inactive when the
    module it needs is not licensed or enabled: recognition fails closed."""

    mode: SubjectMode = "any"
    identity_ids: list[str] = Field(default_factory=list, description="Enrolled person ids")
    plates: list[str] = Field(default_factory=list, description="Normalized plate texts")
    vehicle_ids: list[str] = Field(default_factory=list, description="Registered vehicle ids")
    groups: list[str] = Field(default_factory=list, description="Registered vehicle groups")

    @field_validator("plates")
    @classmethod
    def _normalize_plates(cls, v: list[str]) -> list[str]:
        return [p for p in (normalize_plate_text(x) for x in v) if p]

    @model_validator(mode="after")
    def _specific_needs_targets(self) -> RuleSubject:
        if self.mode == "specific" and not (self.identity_ids or self.plates or self.vehicle_ids):
            raise ValueError("a 'specific' subject needs at least one identity, plate or vehicle")
        return self

    @property
    def active(self) -> bool:
        return self.mode != "any"

    def evaluate(self, entity: EntityRef) -> bool | None:
        """``True`` when the entity satisfies the subject, ``False`` when it
        definitely does not, ``None`` while the module has not decided yet."""
        if self.mode == "any":
            return True
        if self.mode == "anonymous":
            if entity.recognized:
                return False
            return True if entity.settled else None
        if self.mode == "recognized":
            if entity.recognized and entity.status == STATUS_RECOGNIZED:
                return True
            return False if entity.settled else None
        if self.mode == "registered":
            if entity.kind == "registered_vehicle" and entity.status == STATUS_RECOGNIZED:
                return not self.groups or bool(set(self.groups) & set(entity.groups))
            return False if entity.settled else None
        # specific
        if entity.recognized and entity.status == STATUS_RECOGNIZED:
            if entity.identity_id and entity.identity_id in self.identity_ids:
                return True
            if entity.vehicle_id and entity.vehicle_id in self.vehicle_ids:
                return True
            if entity.plate and entity.plate in self.plates:
                return True
            return False
        return False if entity.settled else None


def modules_for_classes(classes: list[str]) -> set[str]:
    """Recognition modules a subject clause needs for the given object classes."""
    if not classes:
        return {"face", "plate"}
    out: set[str] = set()
    for c in classes:
        if c == "person":
            out.add("face")
        elif c in VEHICLE_CLASSES:
            out.add("plate")
    return out


class RuleRelation(BaseModel):
    """HAS RELATIONSHIP clause: the track (or the identity it resolves to) has,
    or recently had, a relationship formed by the relationship engine.

        Registered Vehicle 'Delivery Van 04' ENTERS Restricted Parking
        AND HAS RELATIONSHIP ASSOCIATED_WITH Recognized Person 'Employee-017'

    Evaluated when the event would be emitted, like the subject clause; a
    relationship that forms shortly after the trigger (often by the same
    crossing) is waited for during the same grace period as recognition. The
    rule stays inactive when relationships are off for the experiment."""

    relation: str = Field(min_length=2, max_length=60)
    direction: Literal["any", "outgoing", "incoming"] = "any"
    other_classes: list[str] = Field(default_factory=list, description="Classes of the other entity; empty = any")
    other: RuleSubject = Field(default_factory=RuleSubject)
    other_places: list[str] = Field(default_factory=list, description="The other side is one of these zones or gates")
    min_state: Literal["possible", "likely", "confirmed"] = "likely"
    recent_s: float | None = Field(default=300.0, gt=0, description="Still holds, or ended at most this long ago; None = any time in the run")

    @field_validator("relation")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class Rule(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rule"))
    name: str = ""
    enabled: bool = True
    classes: list[str] = Field(default_factory=list, description="Empty = every tracked class")
    subject: RuleSubject = Field(default_factory=RuleSubject)
    relation: RuleRelation | None = None
    trigger: RuleTrigger
    then: list[RuleStep] = Field(default_factory=list)
    remains_for_s: float | None = Field(default=None, gt=0)
    record_as: str = ""
    actions: list[RuleAction] = Field(
        default_factory=lambda: [RuleAction(kind="count"), RuleAction(kind="record_event")]
    )
    timeout_s: float | None = Field(default=None, gt=0, description="Whole-sequence deadline")

    @model_validator(mode="after")
    def _dwell_needs_zone_trigger(self) -> Rule:
        if self.remains_for_s is not None and self.trigger.kind != "enters":
            raise ValueError("a 'remains for' rule must start with ENTERS <zone>")
        if self.remains_for_s is not None and self.then:
            raise ValueError("a 'remains for' rule cannot also have THEN steps")
        return self

    @property
    def label(self) -> str:
        return self.record_as or self.name or self.id

    @property
    def modules_needed(self) -> set[str]:
        """Recognition modules this rule needs (empty for ordinary rules)."""
        out = modules_for_classes(self.classes) if self.subject.active else set()
        if self.relation is not None and self.relation.other.active:
            out |= modules_for_classes(self.relation.other_classes)
        return out

    @property
    def conditional(self) -> bool:
        """Evaluated when the event would be emitted (subject or relationship clause)."""
        return self.subject.active or self.relation is not None
