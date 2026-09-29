"""System status and first-run state."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from pathscope import __version__
from pathscope.api.deps import db_session, settings_dep
from pathscope.api.schemas import LoadEstimateIn
from pathscope.config import Settings
from pathscope.db.models import Camera, Event, Experiment, Project, Run
from pathscope.hardware import estimate_load, live_utilization
from pathscope.hardware.probe import probe_hardware
from pathscope.settings_store import get_setting, set_settings
from pathscope.workers.supervisor import get_supervisor

router = APIRouter(prefix="/system", tags=["system"])

_hw_cache: dict = {"report": None, "at": 0.0}


def cached_hardware(settings: Settings, max_age_s: float = 300.0):
    now = time.time()
    if _hw_cache["report"] is None or now - _hw_cache["at"] > max_age_s:
        _hw_cache["report"] = probe_hardware(settings.resolved_data_dir)
        _hw_cache["at"] = now
    return _hw_cache["report"]


def refresh_hardware(settings: Settings):
    _hw_cache["report"] = probe_hardware(settings.resolved_data_dir)
    _hw_cache["at"] = time.time()
    return _hw_cache["report"]


def _mask(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return url


@router.get("/status")
def status(session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)) -> dict:
    db_ok = True
    db_error = None
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = str(exc)[:200]
    counts = {}
    if db_ok:
        counts = {
            "projects": session.scalar(select(func.count(Project.id))) or 0,
            "cameras": session.scalar(select(func.count(Camera.id))) or 0,
            "experiments": session.scalar(select(func.count(Experiment.id))) or 0,
            "runs": session.scalar(select(func.count(Run.id))) or 0,
            "events": session.scalar(select(func.count(Event.id))) or 0,
        }
    sup = get_supervisor()
    return {
        "version": __version__,
        "setup_completed": bool(get_setting(session, "setup_completed", False)) if db_ok else False,
        "database": {"url": _mask(settings.resolved_database_url), "ok": db_ok, "error": db_error, "dialect": settings.resolved_database_url.split(":", 1)[0]},
        "data_dir": str(settings.resolved_data_dir),
        "models_dir": str(settings.resolved_models_dir),
        "counts": counts,
        "active_runs": [{"run_id": h.run_id, "state": h.state, "camera_id": h.spec.camera_id} for h in sup.active()],
        "time": time.time(),
    }


@router.post("/setup-complete")
def setup_complete(session: Session = Depends(db_session)) -> dict:
    set_settings(session, {"setup_completed": True})
    return {"ok": True}


@router.get("/load")
def system_load(session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)) -> dict:
    sup = get_supervisor()
    streams = []
    for h in sup.active():
        st = h.status or {}
        rec = h.spec.recognition or {}
        streams.append(
            {
                "run_id": h.run_id,
                "model_id": h.spec.model_id,
                "image_size": h.spec.image_size,
                "processing_fps": st.get("pipeline_fps") or h.spec.processing_fps or st.get("source_fps") or 10.0,
                "device": h.spec.device,
                "state": st.get("state"),
                "timings_ms": st.get("timings_ms"),
                "recognition": {m: (rec[m].get("stack") or ("opencv" if m == "face" else "onnx")) for m in ("face", "plate") if rec.get(m)},
            }
        )
    hw = cached_hardware(settings)
    return {"utilization": live_utilization(), "streams": streams, "estimate": estimate_load(hw, streams)}


@router.post("/load-estimate")
def load_estimate(body: LoadEstimateIn, settings: Settings = Depends(settings_dep)) -> dict:
    hw = cached_hardware(settings)
    return estimate_load(hw, body.streams)


@router.get("/privacy")
def privacy(session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)) -> dict:
    """What the platform stores, in plain terms, based on the current settings."""
    store_traj = get_setting(session, "store_trajectories", settings.store_trajectories)
    keep_video = get_setting(session, "keep_source_video", settings.keep_source_video)
    retention = get_setting(session, "retention_days", settings.retention_days)
    return {
        "stored": [
            {"item": "Anonymous track ids", "stored": True, "detail": "Session-scoped integers assigned by the tracker; they cannot be linked across runs."},
            {"item": "Events", "stored": True, "detail": "Crossings, zone entries/exits, dwell and route outcomes with timestamps, class, duration, speed and confidence."},
            {"item": "Track summaries", "stored": True, "detail": "Lifetime, path length, mean speed and final state per anonymous track."},
            {"item": "Sampled trajectories", "stored": bool(store_traj), "detail": "Normalized ground-plane positions, up to 10 per second per track."},
            {"item": "Uploaded source video", "stored": True, "detail": "Kept on disk in the data directory until you delete it; never uploaded anywhere." + ("" if keep_video else " Deleting it after its runs is not implemented yet.")},
            _recording_privacy(session),
            *_anomaly_privacy(session),
            _relationship_privacy(session),
            {"item": "Raw frames or crops", "stored": False, "detail": "Frames are processed in memory and discarded, apart from the video recordings and anomaly evidence pictures above."},
            {"item": "Appearance summaries (BoT-SORT, optional)", "stored": False, "detail": "When appearance matching is switched on, a short numeric summary of each object's appearance is held in memory only while it is tracked, to keep its anonymous id through occlusions in the same run. It is never written to disk, never compared across runs or cameras, and discarded when the track ends."},
            *_recognition_privacy(session),
        ],
        "retention_days": retention,
        "data_dir": str(settings.resolved_data_dir),
    }


def _recording_privacy(session: Session) -> dict:
    """Video of live cameras: off unless an experiment records it."""
    from sqlalchemy import select

    from pathscope.db.models import Experiment
    from pathscope.domain.recording import recording_settings
    from pathscope.storage.recordings import usage

    recording = [e.name for e in session.scalars(select(Experiment)) if recording_settings(e.recording).enabled]
    use = usage(session)
    days = int(get_setting(session, "video_retention_days", 0) or 0)
    if not recording and not use["files"]:
        return {"item": "Live camera video", "stored": False, "detail": "Frames are processed in memory and discarded. No experiment records video."}
    names = ", ".join(recording[:5]) + (f" and {len(recording) - 5} more" if len(recording) > 5 else "")
    detail = (f"Recorded by {len(recording)} experiment{'s' if len(recording) != 1 else ''}: {names}. " if recording else "No experiment records video now. ")
    detail += f"{use['files']} file{'s' if use['files'] != 1 else ''}, {use['bytes'] / 1e6:.1f} MB in the data directory. "
    detail += f"Deleted {days} days after recording." if days > 0 else "Kept until you delete them (Video retention is 0)."
    return {"item": "Live camera video", "stored": True, "detail": detail}


def _relationship_privacy(session: Session) -> dict:
    """Relationship graph: off unless an experiment turns it on."""
    from sqlalchemy import func, select

    from pathscope.db.models import Experiment
    from pathscope.relationships.access import load_settings
    from pathscope.relationships.models import RelationRelationship
    from pathscope.relationships.rules import relation_settings

    on = [e.name for e in session.scalars(select(Experiment)) if relation_settings(e.relations).enabled]
    n = int(session.scalar(select(func.count(RelationRelationship.id))) or 0)
    if not on and not n:
        return {"item": "Relationships", "stored": False, "detail": "No experiment connects tracks, identities and places into relationships."}
    ret = load_settings(session).retention
    detail = (f"Formed by {len(on)} experiment{'s' if len(on) != 1 else ''}. " if on else "No experiment forms them now. ")
    detail += f"{n} relationship{'s' if n != 1 else ''} stored (who or what was near, followed, entered or used what, when, with confidence and evidence). "
    detail += f"Deleted after {ret.days} days; " if ret.days else "Kept until deleted; "
    detail += f"identity links after {ret.identity_days} days." if ret.identity_days else "identity links kept until deleted."
    return {"item": "Relationships", "stored": True, "detail": detail}


def _anomaly_privacy(session: Session) -> list[dict]:
    """Anomaly Assistant: evidence pictures, and what goes to a vision language model."""
    from sqlalchemy import select

    from pathscope.anomaly.config import anomaly_settings
    from pathscope.anomaly.llm.settings import load_settings
    from pathscope.anomaly.service import usage
    from pathscope.db.models import Experiment

    watching = [e.name for e in session.scalars(select(Experiment)) if anomaly_settings(e.anomaly).active]
    use = usage()
    days = int(get_setting(session, "anomaly_retention_days", 0) or 0)
    items = []
    if watching or use["files"]:
        detail = (f"Kept by {len(watching)} experiment{'s' if len(watching) != 1 else ''} with the Anomaly Assistant on. " if watching else "No experiment uses the Anomaly Assistant now. ")
        detail += f"A few pictures per anomaly (normal picture, event, end, close-ups; no names drawn): {use['files']} files, {use['bytes'] / 1e6:.1f} MB. "
        detail += f"Deleted {days} days after the event." if days > 0 else "Kept until you delete them or their run (Anomaly evidence retention is 0)."
        items.append({"item": "Anomaly evidence pictures", "stored": True, "detail": detail})
    else:
        items.append({"item": "Anomaly evidence pictures", "stored": False, "detail": "No experiment uses the Anomaly Assistant."})
    llm = load_settings(session)
    if llm.enabled:
        where = "a model running on this machine or network" if llm.info.local else f"{llm.info.name} (outside this installation)"
        sent = "the evidence pictures and written observations" if (llm.send_images and llm.info.vision) else "the written observations only (no pictures)"
        items.append({"item": "Vision language model", "stored": True, "detail": f"For anomalies of zones that use a model, {sent} of each event are sent to {where} ({llm.resolved_model}). Never the video stream, never names or plate numbers: people and vehicles are aliases such as [Person A]."})
    else:
        items.append({"item": "Vision language model", "stored": False, "detail": "No model is selected: anomaly events are described by computer vision only and nothing is sent anywhere."})
    return items


def _recognition_privacy(session: Session) -> list[dict]:
    """Rows of the licensed recognition modules; the core default when they cannot be consulted."""
    try:
        from pathscope.recognition.service import privacy_items

        return privacy_items(session)
    except Exception:  # noqa: BLE001 - fail closed: report the core defaults
        return [{"item": "Faces or identities", "stored": False, "detail": "No face recognition, identity storage, or matching of people across runs or cameras."}]
