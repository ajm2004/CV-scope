"""Settings of cross-camera correlation (one set per installation)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from pathscope.db.models import Setting

SETTINGS_KEY = "location.crosscam"


class CrossCameraSettings(BaseModel):
    enabled: bool = Field(default=True, description="Correlate recognized people and plates across cameras")
    min_identity_state: Literal["confirmed", "likely"] = Field(default="likely", description="Identity links weaker than this never join sightings")
    lookback_hours: float = Field(default=24.0, gt=0, le=24 * 30, description="How far back the previous sighting may be")
    journey_break_s: float = Field(default=4 * 3600.0, gt=0, le=7 * 86400, description="A longer gap between two sightings starts a new journey (no transition)")
    overlap_tolerance_s: float = Field(default=3.0, ge=0, le=120, description="Clock and hand-over tolerance: how early the next camera may see the entity")
    default_max_s: float = Field(default=900.0, gt=0, le=86400, description="Assumed longest travel time where the topology gives none")
    too_fast_factor: float = Field(default=0.5, gt=0, lt=1, description="A move faster than this share of the shortest expected time is reported as implausible")
    anonymous: bool = Field(default=False, description="Also link anonymous tracks between directly connected cameras by timing alone (never above 'possible')")
    anonymous_max_candidates: int = Field(default=1, ge=1, le=1, description="Only a single unambiguous candidate is linked")
    anomalies: bool = Field(default=True, description="Report topology deviations (implausible timing, unknown connection, one-way, restricted place without entry, unusual camera sequence)")
    publish_anomalies: bool = Field(default=True, description="Also record topology deviations as ordinary events of the destination run")
    history_min_journeys: int = Field(default=5, ge=2, le=1000, description="Earlier journeys needed before a camera sequence can be called unusual")
    history_rare_share: float = Field(default=0.1, gt=0, lt=1, description="A move seen in fewer than this share of earlier journeys is unusual")

    @model_validator(mode="after")
    def _check(self) -> CrossCameraSettings:
        if self.journey_break_s > self.lookback_hours * 3600:
            self.journey_break_s = self.lookback_hours * 3600
        return self


def load_crosscam_settings(session: Session) -> CrossCameraSettings:
    row = session.get(Setting, SETTINGS_KEY)
    if row is None or not isinstance(row.value, dict):
        return CrossCameraSettings()
    try:
        return CrossCameraSettings.model_validate(row.value)
    except ValueError:
        return CrossCameraSettings()


def save_crosscam_settings(session: Session, s: CrossCameraSettings) -> None:
    row = session.get(Setting, SETTINGS_KEY)
    if row is None:
        session.add(Setting(key=SETTINGS_KEY, value=s.model_dump()))
    else:
        row.value = s.model_dump()
    session.commit()
