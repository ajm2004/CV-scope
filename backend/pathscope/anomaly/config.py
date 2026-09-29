"""Settings of the Anomaly Assistant: what to watch and how strict to be.

The assistant watches the whole picture and/or zones of the scene. Every zone
has its own sensitivity (a preset, or custom thresholds), its own persistence
rule ("only when the change stays for X seconds"), what counts as an anomaly
there, and how a vision language model takes part:

* ``deterministic`` - computer vision alone decides; no model is asked
* ``assisted``      - the event is raised at once; a model adds a description
* ``confirmed``     - the event is raised only when the model agrees that the
                      evidence shows a real change (policy for model failures:
                      ``on_llm_failure``)

These models are plain pydantic, independent of the rest of CV-Scope, so
another application can build them from its own configuration.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

FRAME_ZONE_ID = "frame"  # the whole picture, watched like a zone

Sensitivity = Literal["low", "medium", "high", "custom"]
ValidationMode = Literal["deterministic", "assisted", "confirmed"]
InterpretAt = Literal["confirm", "end"]

# What the assistant reports (deterministic classification)
AnomalyKind = Literal["presence", "motion", "appeared", "disappeared", "moved", "changed"]
ALL_KINDS: list[str] = ["presence", "motion", "appeared", "disappeared", "moved", "changed"]
# Whole-picture events that are not about one zone
GLOBAL_KINDS = ("lighting", "tamper")

KIND_LABELS = {
    "presence": "presence in the zone",
    "motion": "movement",
    "appeared": "object appeared",
    "disappeared": "object removed",
    "moved": "object moved",
    "changed": "scene changed",
    "lighting": "lighting changed",
    "tamper": "camera view blocked or moved",
}

# Thresholds behind the presets. Units: min_contrast in Lab lightness levels
# (0-255 scale), min_area_pct in percent of the zone, persistence_s in seconds.
PRESETS: dict[str, dict[str, float]] = {
    "low": {"k_sigma": 5.0, "min_contrast": 28.0, "min_area_pct": 2.0, "persistence_s": 4.0, "min_confidence": 0.6},
    "medium": {"k_sigma": 3.5, "min_contrast": 20.0, "min_area_pct": 0.8, "persistence_s": 2.5, "min_confidence": 0.5},
    "high": {"k_sigma": 2.5, "min_contrast": 14.0, "min_area_pct": 0.3, "persistence_s": 1.5, "min_confidence": 0.4},
}


class ResolvedThresholds(BaseModel):
    k_sigma: float  # a pixel differs when it is this many noise deviations away from normal ...
    min_contrast: float  # ... and at least this much brighter / darker
    min_area_pct: float  # changed part of the zone that counts
    persistence_s: float  # how long the change must last
    min_confidence: float


class AnomalyZoneSettings(BaseModel):
    """One watched area: a zone of the scene (by id) or the whole picture."""

    id: str = Field(description="Scene zone id, or 'frame' for the whole picture")
    name: str = ""
    enabled: bool = True
    # Plain words about the normal state ("the stall is empty", "the bed is made").
    # Shown with every event and given to the vision model as context.
    expected_state: str = ""
    sensitivity: Sensitivity = "medium"
    # Custom thresholds (used with sensitivity "custom"; a value set here also
    # overrides the preset of the other levels)
    k_sigma: float | None = Field(default=None, ge=1.0, le=12.0)
    min_contrast: float | None = Field(default=None, ge=4.0, le=120.0)
    min_area_pct: float | None = Field(default=None, ge=0.05, le=80.0)
    persistence_s: float | None = Field(default=None, ge=0.0, le=600.0)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # What counts as an anomaly here
    detect: list[AnomalyKind] = Field(default_factory=lambda: list(ALL_KINDS))
    # Detector classes whose presence alone is an anomaly (a normally empty
    # zone). Empty: every class the experiment tracks.
    presence_classes: list[str] = Field(default_factory=list)
    # A change that stays still this long becomes the new normal (0 = never)
    accept_after_s: float = Field(default=120.0, ge=0.0, le=86400.0)
    # Quiet time after an event before the zone raises the next one
    cooldown_s: float = Field(default=10.0, ge=0.0, le=3600.0)
    # Vision language model
    validation: ValidationMode = "deterministic"
    interpret_at: InterpretAt = "confirm"
    # Alert actions
    webhooks: list[str] = Field(default_factory=list)
    record_clip: bool = True  # start a video clip (when the experiment records events)

    @field_validator("webhooks")
    @classmethod
    def _urls(cls, v: list[str]) -> list[str]:
        out = [u.strip() for u in v if u and u.strip()]
        for u in out:
            if not (u.startswith("http://") or u.startswith("https://")):
                raise ValueError(f"webhook '{u}' must start with http:// or https://")
        return out

    def thresholds(self) -> ResolvedThresholds:
        base = dict(PRESETS["medium" if self.sensitivity == "custom" else self.sensitivity])
        for key in base:
            value = getattr(self, key)
            if value is not None:
                base[key] = float(value)
        return ResolvedThresholds(**base)

    @property
    def effective_interpret_at(self) -> InterpretAt:
        # A model-confirmed event must be judged before it is raised
        return "confirm" if self.validation == "confirmed" else self.interpret_at


class AnomalySettings(BaseModel):
    """Anomaly Assistant settings of one experiment (one camera)."""

    enabled: bool = False
    zones: list[AnomalyZoneSettings] = Field(default_factory=list)
    # Analyses per second (independent of the detector's processing rate)
    analysis_fps: float = Field(default=4.0, ge=0.5, le=15.0)
    # Seconds of normal picture learned at the start of a run
    learn_s: float = Field(default=8.0, ge=2.0, le=300.0)
    # How fast the normal picture follows slow daylight changes (time constant)
    adapt_minutes: float = Field(default=10.0, ge=0.5, le=240.0)
    # Width of the analysed picture in pixels (smaller is faster and ignores finer detail)
    working_width: int = Field(default=320, ge=160, le=960)
    # The scene's ignore regions are not watched (a TV, a window with trees)
    use_ignore_regions: bool = True
    # Whole-picture events
    lighting_events: bool = False  # report lights switched on or off
    tamper_events: bool = True  # report a covered, blinded or turned camera
    # Pass recognition results (known / unknown person, registered vehicle) along
    recognition: bool = True
    # What happens to a "confirmed" zone's event when the model cannot be asked
    on_llm_failure: Literal["raise", "hold"] = "raise"

    @property
    def active(self) -> bool:
        return self.enabled and any(z.enabled for z in self.zones)

    def zone(self, zone_id: str) -> AnomalyZoneSettings | None:
        return next((z for z in self.zones if z.id == zone_id), None)


def anomaly_settings(value: dict | None) -> AnomalySettings:
    """Tolerant reader for stored experiments (None or old rows mean off)."""
    try:
        return AnomalySettings.model_validate(value or {})
    except Exception:  # noqa: BLE001 - a damaged setting must never block a run
        return AnomalySettings()
