"""Scene document: the geometry a user draws over a camera frame.

All coordinates are normalized to the source frame (0..1 on both axes) so the
configuration is independent of the display size and survives changes of the
capture resolution.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

# Object classes users can select. Detector providers map their own label sets
# onto these canonical names (see vision/classes.py).
CANONICAL_CLASSES = [
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "bus",
    "truck",
    "train",
    "boat",
    "dog",
    "cat",
    "horse",
    "backpack",
    "suitcase",
]

VEHICLE_CLASSES = ["car", "motorcycle", "bus", "truck"]

Direction = Literal["both", "forward", "reverse"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


class Point(BaseModel):
    x: float = Field(ge=-0.5, le=1.5)
    y: float = Field(ge=-0.5, le=1.5)


class SceneObjectBase(BaseModel):
    id: str = Field(default_factory=lambda: new_id("obj"))
    name: str = ""
    enabled: bool = True
    locked: bool = False
    visible: bool = True
    color: str | None = None
    notes: str = ""
    # Object classes this element applies to. Empty means every tracked class.
    classes: list[str] = Field(default_factory=list)


class LineObject(SceneObjectBase):
    """A counting line or a route gate. Two points, A and B.

    ``forward`` is the crossing direction along the left-hand normal of A->B
    (drawn as an arrow on the canvas). ``reverse`` is the opposite.
    """

    type: Literal["line", "gate"] = "line"
    points: list[Point]
    direction: Direction = "both"
    actions: list[Literal["count", "record"]] = Field(default_factory=lambda: ["count", "record"])
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    min_track_age: int = Field(default=2, ge=0, description="Frames a track must exist first")
    debounce_s: float = Field(default=1.0, ge=0.0)
    # The camera cannot see past the line (a door into a room, a wall edge): an
    # object that walks up to it and disappears there, or appears there and
    # walks away, has crossed it although its ground point was never seen on
    # the far side.
    doorway: bool = Field(default=False, description="Count objects that disappear or appear at the line")

    @field_validator("points")
    @classmethod
    def _two_points(cls, v: list[Point]) -> list[Point]:
        if len(v) != 2:
            raise ValueError("a line needs exactly two points")
        return v


ZoneMeasure = Literal["entry", "exit", "occupancy", "dwell"]


class ZoneObject(SceneObjectBase):
    """A polygon: monitored zone, route checkpoint or ignore region."""

    type: Literal["zone", "checkpoint", "ignore"] = "zone"
    points: list[Point]
    measures: list[ZoneMeasure] = Field(
        default_factory=lambda: ["entry", "exit", "occupancy", "dwell"]
    )
    min_dwell_s: float = Field(default=0.0, ge=0.0, description="Ignore shorter visits")
    max_dwell_s: float | None = Field(default=None, description="Flag visits longer than this")
    max_objects: int | None = Field(default=None, description="Flag occupancy above this")
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    min_track_age: int = Field(default=2, ge=0)
    debounce_s: float = Field(default=0.5, ge=0.0)

    @field_validator("points")
    @classmethod
    def _polygon(cls, v: list[Point]) -> list[Point]:
        if len(v) < 3:
            raise ValueError("a zone needs at least three points")
        return v


SceneObject = Annotated[LineObject | ZoneObject, Field(discriminator="type")]


class RouteDefinition(BaseModel):
    """A logical path: start gate -> ordered checkpoints -> end gate."""

    id: str = Field(default_factory=lambda: new_id("route"))
    name: str
    enabled: bool = True
    color: str | None = None
    start: str = Field(description="Scene object id the route starts at")
    sequence: list[str] = Field(default_factory=list, description="Intermediate object ids")
    end: str = Field(description="Scene object id that completes the route")
    classes: list[str] = Field(default_factory=list)
    timeout_s: float = Field(default=60.0, gt=0)
    # When strict, reaching the end without passing every checkpoint is UNKNOWN.
    strict_sequence: bool = True


class CalibrationPoint(BaseModel):
    image: Point
    ground_x: float
    ground_y: float


class KnownDistance(BaseModel):
    a: Point
    b: Point
    distance: float = Field(gt=0)


class Calibration(BaseModel):
    unit: str = "m"
    points: list[CalibrationPoint] = Field(default_factory=list)
    known_distance: KnownDistance | None = None
    notes: str = ""

    @property
    def mode(self) -> str:
        if len(self.points) >= 4:
            return "homography"
        if self.known_distance is not None:
            return "scale"
        return "none"


class SceneDocument(BaseModel):
    version: int = 1
    frame_width: int = Field(gt=0)
    frame_height: int = Field(gt=0)
    objects: list[SceneObject] = Field(default_factory=list)
    routes: list[RouteDefinition] = Field(default_factory=list)
    calibration: Calibration | None = None

    @model_validator(mode="after")
    def _unique_ids_and_refs(self) -> SceneDocument:
        ids = [o.id for o in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("scene object ids must be unique")
        known = set(ids)
        for r in self.routes:
            for ref in (r.start, *r.sequence, r.end):
                if ref not in known:
                    raise ValueError(f"route '{r.name}' references unknown object '{ref}'")
        return self

    def object_by_id(self, object_id: str) -> LineObject | ZoneObject | None:
        for o in self.objects:
            if o.id == object_id:
                return o
        return None

    def lines(self) -> list[LineObject]:
        return [o for o in self.objects if isinstance(o, LineObject)]

    def zones(self) -> list[ZoneObject]:
        return [o for o in self.objects if isinstance(o, ZoneObject)]

    def ignore_regions(self) -> list[ZoneObject]:
        return [o for o in self.zones() if o.type == "ignore" and o.enabled]

    def all_classes(self) -> set[str]:
        out: set[str] = set()
        for o in self.objects:
            out.update(o.classes)
        for r in self.routes:
            out.update(r.classes)
        return out


def empty_scene(width: int, height: int) -> SceneDocument:
    return SceneDocument(frame_width=width, frame_height=height)
