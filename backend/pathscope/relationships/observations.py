"""Normalized observations: the only input of the relationship engine.

Detectors, trackers, the recognition modules and external sensors do not
talk to the engine directly; each publishes observations in this one shape
(an entity did something at a time, seen by a source, with a confidence).
The engine keeps them as the evidence its relationships point to, so a
relationship can always be traced back to what was actually observed.

Position samples are not stored as observations (they would dwarf every
other table); a spatial relationship keeps the measured summary instead
(valid samples, minimum and mean distance, calibration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class ObservationType:
    id: str
    label: str
    description: str = ""


_TYPES: dict[str, ObservationType] = {}


def register_observation_type(t: ObservationType) -> ObservationType:
    _TYPES[t.id] = t
    return t


for _t in (
    ObservationType("appeared", "appeared", "A track started."),
    ObservationType("disappeared", "disappeared", "A track ended (last seen)."),
    ObservationType("entered", "entered", "Entered a zone or checkpoint."),
    ObservationType("exited", "exited", "Left a zone or checkpoint."),
    ObservationType("crossed", "crossed", "Crossed a line or gate."),
    ObservationType("route_completed", "completed route", "Completed a route."),
    ObservationType("stopped", "stopped", "Stopped moving (below the rule's speed) for a while."),
    ObservationType("recognized", "recognized as", "The face module matched an enrolled identity."),
    ObservationType("possible_match", "possibly matched", "The face module found a possible (not confirmed) match."),
    ObservationType("plate_read", "plate read", "The plate module read a plate."),
    ObservationType("registered_vehicle", "registered vehicle", "The plate belongs to a registered vehicle."),
    ObservationType("sensor", "sensor measurement", "A measurement published by an external sensor."),
    ObservationType("event", "event", "An ordinary CV-Scope event (for example an anomaly)."),
):
    register_observation_type(_t)


def observation_type(type_id: str) -> ObservationType:
    return _TYPES.get(type_id) or ObservationType(type_id, type_id.replace("_", " "))


def observation_types() -> list[ObservationType]:
    return list(_TYPES.values())


def new_uid() -> str:
    return uuid4().hex


@dataclass
class Observation:
    type: str
    subject: str  # entity key
    t: float  # media time of the run (s)
    wall: float  # epoch seconds
    source: str = "rgb"  # rgb | face | plate | depth | radar | thermal | registry | ...
    object: str | None = None  # entity key (zone, gate, identity, other track)
    confidence: float | None = None
    value: dict = field(default_factory=dict)
    uid: str = field(default_factory=new_uid)

    def to_dict(self) -> dict:
        return {
            "uid": self.uid, "type": self.type, "subject": self.subject, "object": self.object, "t": round(self.t, 3), "wall": self.wall,
            "source": self.source, "confidence": None if self.confidence is None else round(float(self.confidence), 4), "value": self.value,
        }
