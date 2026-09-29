"""Tracker interface. A tracker turns per-frame detections into anonymous,
session-scoped tracks. It knows nothing about scene geometry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from pathscope.vision.types import Detection, Track


@dataclass
class TrackerStats:
    total_tracks: int = 0
    active_tracks: int = 0
    lost_tracks: int = 0
    lost_events: int = 0
    reacquisitions: int = 0
    removed_tracks: int = 0
    lifetimes_frames: list[int] = field(default_factory=list)
    # Tracker-specific diagnostics (camera motion, appearance matching, timings)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        lifetimes = self.lifetimes_frames
        mean_life = sum(lifetimes) / len(lifetimes) if lifetimes else 0.0
        return {
            "total_tracks": self.total_tracks,
            "active_tracks": self.active_tracks,
            "lost_tracks": self.lost_tracks,
            "lost_events": self.lost_events,
            "reacquisitions": self.reacquisitions,
            "removed_tracks": self.removed_tracks,
            "mean_lifetime_frames": round(mean_life, 1),
            **self.extra,
        }


@dataclass
class TrackerUpdate:
    """Result of one tracker step."""

    tracks: list[Track]  # all live tracks (tracked, tentative and lost)
    started: list[Track]  # tracks confirmed for the first time this frame
    reacquired: list[Track]  # lost -> tracked this frame
    lost: list[Track]  # tracked -> lost this frame
    removed: list[Track]  # deleted this frame (final state)


class Tracker(ABC):
    id: str = "base"
    name: str = "Base tracker"

    @abstractmethod
    def update(
        self,
        detections: list[Detection],
        frame_index: int,
        t: float,
        frame: np.ndarray | None = None,
    ) -> TrackerUpdate:
        """Advance one processed frame.

        ``frame`` is the BGR image the detections refer to. Trackers that do
        not need pixels (ByteTrack) ignore it; BoT-SORT uses it for camera
        motion compensation and appearance features.
        """

    @abstractmethod
    def stats(self) -> TrackerStats: ...

    @abstractmethod
    def reset(self) -> None: ...

    def describe(self) -> dict:
        return {"id": self.id, "name": self.name}

    def close(self) -> None:  # pragma: no cover - resource cleanup
        pass
