"""Persist recognition events from workers; retention sweeps; exports.

Events arrive as plain dicts from the worker process (see the face and plate
pipelines). Embeddings never travel with them and are never logged.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from pathscope.db.session import get_session_factory
from pathscope.logging_setup import get_logger
from pathscope.recognition.registry.models import (
    RecognitionAudit,
    RecognitionEvent,
    RecognitionPerson,
    RecognitionVehicle,
)
from pathscope.recognition.registry.store import get_store

log = get_logger(__name__)

EXPORT_COLUMNS = [
    "id", "wall_time", "run_id", "experiment_id", "camera_id", "track_id", "object_class", "module", "kind", "status",
    "person_id", "display_name", "vehicle_id", "vehicle_label", "plate_raw", "plate_normalized", "plate_format", "plate_region",
    "similarity", "second_similarity", "confidence", "quality", "n_observations", "usable_observations", "best_frame_index",
    "model_version", "frame_index", "media_time_s", "context",
]


def _dt(ts) -> datetime:
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def record_events(run_id: int | None, experiment_id: int | None, camera_id: int | None, events: list[dict]) -> list[int]:
    """Store a batch of worker events; returns the new ids (in order)."""
    if not events:
        return []
    Session = get_session_factory()
    session = Session()
    ids: list[int] = []
    try:
        rows: list[tuple[RecognitionEvent, bytes | None]] = []
        for e in events:
            row = RecognitionEvent(
                run_id=run_id, experiment_id=experiment_id, camera_id=camera_id, track_id=int(e.get("track_id", 0)), object_class=str(e.get("object_class") or ""),
                module=str(e.get("module") or ""), kind=str(e.get("kind") or ""), status=str(e.get("status") or ""),
                person_id=e.get("person_id"), vehicle_id=e.get("vehicle_id"),
                plate_raw=e.get("plate_raw"), plate_normalized=e.get("plate_normalized"), plate_format=e.get("plate_format"), plate_region=e.get("plate_region"),
                plate_fields=e.get("plate_fields") or {}, similarity=e.get("similarity"), second_similarity=e.get("second_similarity"),
                confidence=e.get("confidence"), quality=e.get("quality"), n_observations=int(e.get("n_observations") or 0), usable_observations=int(e.get("usable_observations") or 0),
                best_frame_index=e.get("best_frame_index"), model_version=str(e.get("model_version") or ""), frame_index=int(e.get("frame_index") or 0),
                media_time_s=float(e.get("media_time_s") or 0.0), wall_time=_dt(e.get("wall_time")), context=e.get("context") or {},
            )
            session.add(row)
            rows.append((row, e.get("crop_jpeg")))
        session.flush()
        store = get_store()
        for row, crop in rows:
            if crop:
                try:
                    row.crop_path = str(store.write_crop(row.id, crop))
                except Exception as exc:  # noqa: BLE001
                    log.warning("crop not stored", event_id=row.id, error=str(exc)[:200])
            ids.append(row.id)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log.warning("recognition events not stored", error=str(exc)[:200], count=len(events))
    finally:
        session.close()
    return ids


def event_to_dict(e: RecognitionEvent, names: dict[str, str] | None = None, vehicles: dict[str, str] | None = None) -> dict:
    return {
        "id": e.id, "run_id": e.run_id, "experiment_id": e.experiment_id, "camera_id": e.camera_id, "track_id": e.track_id, "object_class": e.object_class,
        "module": e.module, "kind": e.kind, "status": e.status, "person_id": e.person_id, "display_name": (names or {}).get(e.person_id or ""),
        "vehicle_id": e.vehicle_id, "vehicle_label": (vehicles or {}).get(e.vehicle_id or ""),
        "plate_raw": e.plate_raw, "plate_normalized": e.plate_normalized, "plate_format": e.plate_format, "plate_region": e.plate_region, "plate_fields": e.plate_fields or {},
        "similarity": e.similarity, "second_similarity": e.second_similarity, "confidence": e.confidence, "quality": e.quality,
        "n_observations": e.n_observations, "usable_observations": e.usable_observations, "best_frame_index": e.best_frame_index,
        "model_version": e.model_version, "frame_index": e.frame_index, "media_time_s": e.media_time_s,
        "wall_time": e.wall_time.isoformat() if e.wall_time else None, "context": e.context or {}, "has_crop": bool(e.crop_path),
    }


def name_maps(session: Session, events: list[RecognitionEvent]) -> tuple[dict[str, str], dict[str, str]]:
    pids = {e.person_id for e in events if e.person_id}
    vids = {e.vehicle_id for e in events if e.vehicle_id}
    names = {p.id: p.display_name for p in session.scalars(select(RecognitionPerson).where(RecognitionPerson.id.in_(pids)))} if pids else {}
    vehicles = {v.id: (v.description or v.owner_ref or v.plate) for v in session.scalars(select(RecognitionVehicle).where(RecognitionVehicle.id.in_(vids)))} if vids else {}
    return names, vehicles


def apply_filters(q: Select, f: dict) -> Select:
    if f.get("run_id") is not None:
        q = q.where(RecognitionEvent.run_id == int(f["run_id"]))
    if f.get("experiment_id") is not None:
        q = q.where(RecognitionEvent.experiment_id == int(f["experiment_id"]))
    if f.get("camera_id") is not None:
        q = q.where(RecognitionEvent.camera_id == int(f["camera_id"]))
    if f.get("module"):
        q = q.where(RecognitionEvent.module == f["module"])
    if f.get("kind"):
        q = q.where(RecognitionEvent.kind.in_([k.strip() for k in str(f["kind"]).split(",") if k.strip()]))
    if f.get("person_id"):
        q = q.where(RecognitionEvent.person_id == f["person_id"])
    if f.get("vehicle_id"):
        q = q.where(RecognitionEvent.vehicle_id == f["vehicle_id"])
    if f.get("plate"):
        q = q.where(RecognitionEvent.plate_normalized == str(f["plate"]).upper())
    if f.get("track_id") is not None:
        q = q.where(RecognitionEvent.track_id == int(f["track_id"]))
    if f.get("from_time") is not None:
        q = q.where(RecognitionEvent.wall_time >= f["from_time"])
    if f.get("to_time") is not None:
        q = q.where(RecognitionEvent.wall_time <= f["to_time"])
    return q


def export_events(session: Session, filters: dict, fmt: str = "csv") -> tuple[bytes, str, str]:
    q = apply_filters(select(RecognitionEvent), filters).order_by(RecognitionEvent.id.asc())
    events = list(session.scalars(q))
    names, vehicles = name_maps(session, events)
    rows = []
    for e in events:
        d = event_to_dict(e, names, vehicles)
        rows.append({c: d.get(c) for c in EXPORT_COLUMNS})
    if fmt == "json":
        return json.dumps(rows, default=str, indent=2).encode("utf-8"), "application/json", "json"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    w.writeheader()
    for r in rows:
        r = dict(r)
        r["context"] = json.dumps(r["context"] or {})
        w.writerow(r)
    return buf.getvalue().encode("utf-8"), "text/csv", "csv"


def delete_events(session: Session, ids: list[int] | None = None, filters: dict | None = None) -> int:
    store = get_store()
    q = select(RecognitionEvent)
    if ids:
        q = q.where(RecognitionEvent.id.in_(ids))
    elif filters:
        q = apply_filters(q, filters)
    else:
        return 0
    n = 0
    for e in session.scalars(q):
        if e.crop_path:
            store.delete_crop(e.id)
        session.delete(e)
        n += 1
    session.flush()
    return n


def sweep_retention(session: Session, values: dict) -> dict:
    """Apply the configured retention: old recognition events, old unregistered
    plate reads, old audit rows and quarantined media past their grace period."""
    now = datetime.now(UTC)
    result = {"events": 0, "unknown_plates": 0, "audit": 0, "quarantine": 0}
    store = get_store()
    days = int(values.get("recognition.retention.events_days", 30) or 0)
    if days > 0:
        cutoff = now - timedelta(days=days)
        old = list(session.scalars(select(RecognitionEvent).where(RecognitionEvent.wall_time < cutoff)))
        for e in old:
            if e.crop_path:
                store.delete_crop(e.id)
            session.delete(e)
        result["events"] = len(old)
    udays = int(values.get("recognition.retention.unknown_plate_days", 7) or 0)
    if udays > 0:
        cutoff = now - timedelta(days=udays)
        old = list(session.scalars(select(RecognitionEvent).where(RecognitionEvent.module == "plate", RecognitionEvent.vehicle_id.is_(None), RecognitionEvent.wall_time < cutoff)))
        for e in old:
            if e.crop_path:
                store.delete_crop(e.id)
            session.delete(e)
        result["unknown_plates"] = len(old)
    adays = int(values.get("recognition.retention.audit_days", 365) or 0)
    if adays > 0:
        cutoff = now - timedelta(days=adays)
        res = session.execute(delete(RecognitionAudit).where(RecognitionAudit.at < cutoff))
        result["audit"] = int(res.rowcount or 0)
    grace = int(values.get("recognition.retention.deleted_media_grace_days", 0) or 0)
    result["quarantine"] = store.purge_quarantine(grace)
    session.commit()
    return result


def count_events(session: Session) -> int:
    return int(session.scalar(select(func.count(RecognitionEvent.id))) or 0)
