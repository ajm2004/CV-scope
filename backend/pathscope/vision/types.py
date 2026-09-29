"""Data types shared by detectors, trackers and the spatial engine."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(slots=True)
class Detection:
    """One detected object in a frame. Box is in source-frame pixels (x1, y1, x2, y2)."""

    class_name: str
    confidence: float
    box: tuple[float, float, float, float]
    class_id: int = -1

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def bottom_center(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2.0, self.box[3])


@dataclass(slots=True)
class TrackPoint:
    """A sampled trajectory point: media time and normalized ground position."""

    t: float
    x: float
    y: float


@dataclass(slots=True)
class Track:
    """An anonymous, session-scoped tracked object."""

    track_id: int
    class_name: str
    confidence: float
    box: tuple[float, float, float, float]
    # tentative | tracked | lost | removed
    state: str
    hits: int
    age: int
    first_frame: int
    last_frame: int
    first_time: float
    last_time: float
    mean_confidence: float
    lost_count: int = 0
    # Was this track matched to a detection in the current frame?
    updated: bool = True
    trajectory: list[TrackPoint] = field(default_factory=list)

    @property
    def bottom_center(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2.0, self.box[3])

    @property
    def center(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2.0, (self.box[1] + self.box[3]) / 2.0)

    def to_dict(self) -> dict:
        return {
            "id": self.track_id,
            "cls": self.class_name,
            "conf": round(self.confidence, 3),
            "box": [round(v, 1) for v in self.box],
            "state": self.state,
            "age": self.age,
            "updated": self.updated,
        }


@dataclass(slots=True)
class FramePacket:
    """A decoded frame with its timing information."""

    frame: np.ndarray
    frame_index: int
    media_time_s: float
    wall_time: float
    width: int
    height: int
