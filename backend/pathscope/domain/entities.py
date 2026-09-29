"""Entity layer: what a tracked object resolves to.

The open-source core knows only anonymous entities: a track is an anonymous
person, an anonymous vehicle or an anonymous object of some other class. The
licensed recognition modules (``pathscope.recognition``) provide an
``EntityResolver`` that can resolve a track to an enrolled person, a recognized
plate or a registered vehicle. The rule engine evaluates the subject clause of
a rule against the resolved entity through this interface only, so the core
never imports recognition code.

    Track #382  ->  Object: person   Identity: Employee-017   (enrolled_person)
    Track #917  ->  Object: car      Plate: ABC12345          (recognized_plate)
                                     Vehicle: Delivery Van 04 (registered_vehicle)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from pathscope.domain.scene import VEHICLE_CLASSES

EntityKind = Literal[
    "anonymous_person",
    "enrolled_person",
    "anonymous_vehicle",
    "recognized_plate",
    "registered_vehicle",
    "anonymous_object",
]

# Recognition status of a track for one module.
STATUS_UNRESOLVED = "unresolved"  # no usable observation yet
STATUS_RECOGNIZED = "recognized"
STATUS_POSSIBLE = "possible_match"
STATUS_UNKNOWN = "unknown"  # observed well enough, matched nothing
STATUS_INSUFFICIENT = "insufficient_quality"

RECOGNIZED_KINDS = {"enrolled_person", "recognized_plate", "registered_vehicle"}


@dataclass(slots=True)
class EntityRef:
    """What one track currently resolves to. Names and plate text are only
    exposed to authenticated viewers (``to_overlay``); stored events carry the
    opaque form (``to_context``)."""

    kind: EntityKind
    track_id: int
    object_class: str
    identity_id: str | None = None
    display_name: str | None = None
    plate: str | None = None
    vehicle_id: str | None = None
    vehicle_label: str | None = None
    groups: list[str] = field(default_factory=list)
    confidence: float | None = None
    status: str = STATUS_UNRESOLVED
    # The module has reached a decision for now (recognized, unknown or
    # insufficient quality). It may still change with new observations.
    settled: bool = False
    resolved_at: float | None = None
    recognition_event_id: int | None = None
    # How the identity was established when a person did it rather than a
    # module: "annotation" (a reviewer identified the track, for example ground
    # truth of a study). None = the face or plate module.
    method: str | None = None

    @property
    def recognized(self) -> bool:
        return self.kind in RECOGNIZED_KINDS

    def to_context(self) -> dict:
        """Opaque form stored with ordinary events: kind and stable ids, never
        a name or a plate number."""
        d: dict = {"kind": self.kind}
        if self.identity_id:
            d["identity_id"] = self.identity_id
        if self.vehicle_id:
            d["vehicle_id"] = self.vehicle_id
        if self.confidence is not None:
            d["confidence"] = round(float(self.confidence), 3)
        if self.status != STATUS_UNRESOLVED:
            d["status"] = self.status
        if self.recognition_event_id is not None:
            d["recognition_event_id"] = self.recognition_event_id
        return d

    def to_overlay(self) -> dict:
        """Form for live overlays of authenticated recognition viewers."""
        d = self.to_context()
        if self.display_name:
            d["display_name"] = self.display_name
        if self.plate:
            d["plate"] = self.plate
        if self.vehicle_label:
            d["vehicle_label"] = self.vehicle_label
        if self.groups:
            d["groups"] = list(self.groups)
        return d


def anonymous_kind(object_class: str) -> EntityKind:
    if object_class == "person":
        return "anonymous_person"
    if object_class in VEHICLE_CLASSES:
        return "anonymous_vehicle"
    return "anonymous_object"


def anonymous_entity(track_id: int, object_class: str, status: str = STATUS_UNRESOLVED, settled: bool = False) -> EntityRef:
    return EntityRef(anonymous_kind(object_class), track_id, object_class, status=status, settled=settled)


def module_for_class(object_class: str) -> str | None:
    """Which recognition module can identify objects of this class."""
    if object_class == "person":
        return "face"
    if object_class in VEHICLE_CLASSES:
        return "plate"
    return None


@runtime_checkable
class EntityResolver(Protocol):
    """Implemented by the licensed recognition runtime."""

    def resolve(self, track_id: int, object_class: str) -> EntityRef:
        """The entity a track currently resolves to (never raises)."""

    def provides(self) -> set[str]:
        """Modules that are active: a subset of {"face", "plate"}."""

    def forget(self, track_id: int) -> None:
        """The track ended; drop its state."""


class NullEntityResolver:
    """The open-source default: every track stays anonymous."""

    def resolve(self, track_id: int, object_class: str) -> EntityRef:
        return anonymous_entity(track_id, object_class)

    def provides(self) -> set[str]:
        return set()

    def forget(self, track_id: int) -> None:
        return None
