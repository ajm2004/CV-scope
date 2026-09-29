"""Video recording settings of an experiment (live cameras only).

Recording is off by default. When it is on, the run keeps video of the camera:

* ``continuous`` — the whole run in files of ``segment_minutes``
* ``events`` — a short clip around every event, padded by ``pre_s`` / ``post_s``
* ``presence`` — from the entry to the exit of the same object, so the dwell
  between them is in the picture instead of two clips with a hole in between

The files stay in the data directory, are listed in the privacy overview and
are deleted after the video retention time (Settings).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RecordingMode = Literal["off", "continuous", "events", "presence"]


class RecordingSettings(BaseModel):
    mode: RecordingMode = "off"
    # Around events: seconds kept before the event and after the last event
    pre_s: float = Field(default=5.0, ge=0.0, le=60.0)
    post_s: float = Field(default=10.0, ge=0.0, le=600.0)
    # Event types that start a clip (crossing, zone_entry, ...). Empty = every stored event.
    event_types: list[str] = Field(default_factory=list)
    # "From entry to exit": how long an object may stay out of sight before its
    # visit counts as ended (tracker gaps, someone behind a pillar).
    presence_grace_s: float = Field(default=3.0, ge=0.0, le=60.0)
    # Draw boxes, anonymous track numbers, the scene and the time into the video
    overlay: bool = True
    # Frames per second of the video (at most the processing rate). File size grows with it.
    fps: float = Field(default=10.0, ge=1.0, le=30.0)
    segment_minutes: float = Field(default=10.0, ge=1.0, le=60.0)
    max_clip_s: float = Field(default=300.0, ge=10.0, le=3600.0)

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def event_driven(self) -> bool:
        """Modes that wait for events instead of recording everything."""
        return self.mode in ("events", "presence")


def recording_settings(value: dict | None) -> RecordingSettings:
    """Tolerant reader for stored experiments (None or old rows mean off)."""
    try:
        return RecordingSettings.model_validate(value or {})
    except Exception:  # noqa: BLE001 - a damaged setting must never block a run
        return RecordingSettings()
