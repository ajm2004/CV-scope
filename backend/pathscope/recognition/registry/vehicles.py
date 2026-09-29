"""Vehicle registry helpers. Registration is optional: OCR works without it."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.domain.rules import normalize_plate_text
from pathscope.recognition.registry.models import RecognitionVehicle

VEHICLE_TYPES = ("", "car", "truck", "bus", "motorcycle", "van", "other")


class VehicleError(ValueError):
    pass


def vehicle_to_dict(v: RecognitionVehicle) -> dict:
    return {
        "id": v.id, "plate": v.plate, "country": v.country, "region": v.region, "vehicle_type": v.vehicle_type, "description": v.description,
        "owner_ref": v.owner_ref, "groups": list(v.groups or []), "active": v.active, "notes": v.notes,
        "created_at": v.created_at.isoformat() if v.created_at else None, "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


def normalize_groups(groups: list[str] | None) -> list[str]:
    out: list[str] = []
    for g in groups or []:
        g = str(g).strip()
        if g and g not in out:
            out.append(g)
    return out


def create_vehicle(session: Session, data: dict) -> RecognitionVehicle:
    plate = normalize_plate_text(str(data.get("plate", "")))
    if len(plate) < 2:
        raise VehicleError("A plate needs at least two letters or digits.")
    if session.scalar(select(RecognitionVehicle).where(RecognitionVehicle.plate == plate)) is not None:
        raise VehicleError(f"Plate {plate} is already registered.")
    v = RecognitionVehicle(
        plate=plate, country=str(data.get("country") or "").upper()[:10], region=str(data.get("region") or "")[:50], vehicle_type=str(data.get("vehicle_type") or "")[:30],
        description=str(data.get("description") or ""), owner_ref=str(data.get("owner_ref") or "")[:200], groups=normalize_groups(data.get("groups")),
        active=bool(data.get("active", True)), notes=str(data.get("notes") or ""),
    )
    session.add(v)
    session.flush()
    return v


def update_vehicle(session: Session, v: RecognitionVehicle, data: dict) -> RecognitionVehicle:
    if "plate" in data and data["plate"] is not None:
        plate = normalize_plate_text(str(data["plate"]))
        if len(plate) < 2:
            raise VehicleError("A plate needs at least two letters or digits.")
        other = session.scalar(select(RecognitionVehicle).where(RecognitionVehicle.plate == plate, RecognitionVehicle.id != v.id))
        if other is not None:
            raise VehicleError(f"Plate {plate} is already registered.")
        v.plate = plate
    for key in ("country", "region", "vehicle_type", "description", "owner_ref", "notes"):
        if key in data and data[key] is not None:
            v.__setattr__(key, str(data[key]).upper() if key == "country" else str(data[key]))
    if "groups" in data and data["groups"] is not None:
        v.groups = normalize_groups(data["groups"])
    if "active" in data and data["active"] is not None:
        v.active = bool(data["active"])
    session.flush()
    return v


def all_groups(session: Session) -> list[str]:
    groups: set[str] = set()
    for v in session.scalars(select(RecognitionVehicle)):
        groups.update(v.groups or [])
    return sorted(groups)


def vehicles_for_worker(session: Session) -> list[dict]:
    return [
        {"id": v.id, "plate": v.plate, "label": v.description or v.owner_ref or v.plate, "groups": list(v.groups or []), "active": True}
        for v in session.scalars(select(RecognitionVehicle).where(RecognitionVehicle.active.is_(True)))
    ]
