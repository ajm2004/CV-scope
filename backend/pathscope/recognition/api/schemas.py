"""Request schemas of the recognition API."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class LicenseIn(BaseModel):
    license: str | dict[str, Any] = Field(description="The licence file content (JSON text or object)")


class TrustedKeyIn(BaseModel):
    public_key: str = Field(min_length=64, max_length=64)
    name: str = Field(default="issuer", max_length=60)


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(pattern="^(viewer|operator|admin)$")
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class BootstrapIn(BaseModel):
    name: str = Field(default="Administrator", min_length=1, max_length=200)


class RecognitionSettingsIn(BaseModel):
    values: dict[str, Any]


class PersonIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    reference_id: str | None = Field(default=None, max_length=200)
    notes: str = ""
    valid_from: date | None = None
    valid_until: date | None = None


class PersonUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    reference_id: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    clear_validity: bool = False


class CaptureIn(BaseModel):
    camera_id: int
    view: str = "front"
    store: bool = False
    t: float = 0.0
    # Look the picture belongs to ("" = the first enrollment)
    variant: str = ""


class ResolveIn(BaseModel):
    """Ids seen in stored events, to be shown with their names."""

    identity_ids: list[str] = Field(default_factory=list, max_length=500)
    vehicle_ids: list[str] = Field(default_factory=list, max_length=500)


class IdentifyIn(BaseModel):
    """Test one camera frame against the enrolled identities."""

    camera_id: int
    t: float = 0.0


class TestFeedbackIn(BaseModel):
    """The operator's verdict on one recognition shown by the test bench."""

    verdict: Literal["correct", "wrong", "unknown_person"]
    person_id: str | None = None
    similarity: float | None = None
    # "wrong": who it really was, when the operator knows
    corrected_person_id: str | None = None
    source: Literal["live", "picture"] = "live"
    camera_id: int | None = None
    note: str = ""


class VehicleIn(BaseModel):
    plate: str = Field(min_length=2, max_length=20)
    country: str = ""
    region: str = ""
    vehicle_type: str = ""
    description: str = ""
    owner_ref: str = ""
    groups: list[str] = Field(default_factory=list)
    active: bool = True
    notes: str = ""


class VehicleUpdate(BaseModel):
    plate: str | None = None
    country: str | None = None
    region: str | None = None
    vehicle_type: str | None = None
    description: str | None = None
    owner_ref: str | None = None
    groups: list[str] | None = None
    active: bool | None = None
    notes: str | None = None


class PlateParseIn(BaseModel):
    text: str
    formats: str | None = None
    region_hint: str | None = None


class DeleteEventsIn(BaseModel):
    ids: list[int] | None = None
    run_id: int | None = None
    person_id: str | None = None
    vehicle_id: str | None = None
    module: str | None = None


class BenchmarkIn(BaseModel):
    module: str = Field(pattern="^(face|plate)$")
    device: str = "auto"
    iterations: int = Field(default=30, ge=5, le=300)
