"""Generic entity model of the relationship graph.

Every node of the graph is an *entity*: something observed (a person track,
a vehicle track), something an observation resolved to (a recognized person,
a license plate, a registered vehicle), a place (zone, gate, route), a piece
of context (camera, sensor, experiment) or an event.

Entities are addressed by a stable key ``<type>:<ref>``. Keys never contain
names or plate text: a recognized person is ``recognized_person:<enrolled
id>``, a plate is ``license_plate:<keyed hash of the plate>``. Names and
plate text are resolved at read time for viewers that may see them.

New entity types can be registered at runtime (``register_entity_type``);
nothing in the engine depends on the list being closed.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Literal

from pathscope.domain.scene import VEHICLE_CLASSES

EntityCategory = Literal["track", "identity", "place", "context", "event"]


@dataclass(frozen=True)
class EntityType:
    id: str
    label: str
    category: EntityCategory
    # Sensitive entities (identities, plates) are shown by name only to
    # viewers with recognition access; everyone else sees the type label.
    sensitive: bool = False
    description: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "category": self.category, "sensitive": self.sensitive, "description": self.description}


_TYPES: dict[str, EntityType] = {}


def register_entity_type(t: EntityType) -> EntityType:
    _TYPES[t.id] = t
    return t


for _t in (
    EntityType("person_track", "Person track", "track", description="An anonymous tracked person in one run."),
    EntityType("vehicle_track", "Vehicle track", "track", description="An anonymous tracked vehicle in one run."),
    EntityType("object_track", "Object", "track", description="Any other tracked object in one run."),
    EntityType("recognized_person", "Recognized person", "identity", sensitive=True, description="An enrolled identity (face recognition module)."),
    EntityType("license_plate", "License plate", "identity", sensitive=True, description="A plate read by the plate module."),
    EntityType("registered_vehicle", "Registered vehicle", "identity", sensitive=True, description="A vehicle of the vehicle registry."),
    EntityType("zone", "Zone", "place", description="A zone or checkpoint of a camera's scene."),
    EntityType("gate", "Gate", "place", description="A counting line or route gate of a camera's scene."),
    EntityType("route", "Route", "place", description="A route definition of a camera's scene."),
    EntityType("location", "Location", "place", description="A node of the location model (site, building, floor, area, road, junction, gate...)."),
    EntityType("camera", "Camera", "context"),
    EntityType("sensor", "Sensor", "context", description="An external sensor that publishes observations (depth, radar, thermal...)."),
    EntityType("experiment", "Experiment", "context"),
    EntityType("event", "Event", "event", description="A correlated or ordinary event used as a node."),
):
    register_entity_type(_t)

TRACK_TYPES = frozenset({"person_track", "vehicle_track", "object_track"})
IDENTITY_TYPES = frozenset({"recognized_person", "license_plate", "registered_vehicle"})
PLACE_TYPES = frozenset({"zone", "gate", "route", "location"})


def entity_type(type_id: str) -> EntityType:
    t = _TYPES.get(type_id)
    if t is None:
        return EntityType(type_id, type_id.replace("_", " ").capitalize(), "context")
    return t


def entity_types() -> list[EntityType]:
    return list(_TYPES.values())


def is_sensitive(type_id: str) -> bool:
    return entity_type(type_id).sensitive


# ---------------------------------------------------------------------------- keys
def make_key(type_id: str, ref: str) -> str:
    return f"{type_id}:{ref}"


def split_key(key: str) -> tuple[str, str]:
    t, _, ref = key.partition(":")
    return t, ref


def track_type(object_class: str) -> str:
    if object_class == "person":
        return "person_track"
    if object_class in VEHICLE_CLASSES:
        return "vehicle_track"
    return "object_track"


def track_key(run_id: int, track_id: int, object_class: str) -> str:
    return make_key(track_type(object_class), f"r{run_id}.t{track_id}")


def parse_track_ref(ref: str) -> tuple[int, int] | None:
    """``r12.t7`` -> (12, 7)."""
    try:
        r, t = ref.split(".")
        return int(r[1:]), int(t[1:])
    except (ValueError, IndexError):
        return None


def place_key(camera_id: int | None, object_id: str, object_type: str | None) -> str:
    kind = "gate" if object_type in ("line", "gate") else "zone"
    return make_key(kind, f"c{camera_id or 0}.{object_id}")


def route_key(camera_id: int | None, route_id: str) -> str:
    return make_key("route", f"c{camera_id or 0}.{route_id}")


def location_key(node_id: int) -> str:
    return make_key("location", str(node_id))


def camera_key(camera_id: int) -> str:
    return make_key("camera", str(camera_id))


def experiment_key(experiment_id: int) -> str:
    return make_key("experiment", str(experiment_id))


def sensor_key(sensor_id: str) -> str:
    return make_key("sensor", sensor_id)


def identity_key(identity_id: str) -> str:
    return make_key("recognized_person", identity_id)


def vehicle_key(vehicle_id: str) -> str:
    return make_key("registered_vehicle", vehicle_id)


def plate_ref(plate: str, salt: bytes) -> str:
    """A keyed hash of the normalized plate: stable, but not the plate itself."""
    return hmac.new(salt, plate.encode("utf-8"), hashlib.sha256).hexdigest()[:20]


def plate_key(plate: str, salt: bytes) -> str:
    return make_key("license_plate", plate_ref(plate, salt))


# ---------------------------------------------------------------------------- mentions
@dataclass
class EntityMention:
    """What the engine knows about one entity in one run (merged into the
    stored entity by the service)."""

    key: str
    type: str
    source: str
    label: str = ""  # non-sensitive display label ("Person track #182", "Gate North")
    secret_label: str | None = None  # sensitive text (plate); never shown without permission
    run_id: int | None = None
    camera_id: int | None = None
    experiment_id: int | None = None
    confidence: float | None = None
    first_t: float | None = None
    last_t: float | None = None
    first_wall: float | None = None
    last_wall: float | None = None
    metadata: dict = field(default_factory=dict)

    def seen(self, t: float, wall: float) -> None:
        if self.first_t is None or t < self.first_t:
            self.first_t, self.first_wall = t, wall
        if self.last_t is None or t > self.last_t:
            self.last_t, self.last_wall = t, wall

    def to_dict(self) -> dict:
        return {
            "key": self.key, "type": self.type, "source": self.source, "label": self.label, "secret_label": self.secret_label,
            "run_id": self.run_id, "camera_id": self.camera_id, "experiment_id": self.experiment_id,
            "confidence": None if self.confidence is None else round(float(self.confidence), 4),
            "first_t": self.first_t, "last_t": self.last_t, "first_wall": self.first_wall, "last_wall": self.last_wall,
            "metadata": self.metadata,
        }
