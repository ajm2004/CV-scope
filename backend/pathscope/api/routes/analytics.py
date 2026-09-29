"""Analytics: run and experiment summaries, tracks, trajectories, dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pathscope.analytics import (
    experiment_summary,
    heatmap_for_run,
    run_summary,
    trajectories_for_run,
)
from pathscope.analytics.aggregation import media_time_series
from pathscope.api.deps import db_session, get_or_404
from pathscope.api.schemas import TrackSummaryOut
from pathscope.db.models import Camera, Event, Experiment, Run, TrackSummary
from pathscope.workers.supervisor import get_supervisor

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/runs/{run_id}/summary")
def run_summary_route(run_id: int, session: Session = Depends(db_session)) -> dict:
    try:
        return run_summary(session, run_id)
    except KeyError as exc:
        raise HTTPException(404, "run not found") from exc


@router.get("/runs/{run_id}/series")
def run_series(run_id: int, bucket_s: float = Query(default=60.0, gt=0), event_type: str | None = None, session: Session = Depends(db_session)) -> dict:
    get_or_404(session, Run, run_id, "Run")
    events = list(session.scalars(select(Event).where(Event.run_id == run_id)))
    return {"run_id": run_id, "bucket_s": bucket_s, "series": media_time_series(events, bucket_s, event_type)}


@router.get("/runs/{run_id}/tracks", response_model=list[TrackSummaryOut])
def run_tracks(run_id: int, limit: int = Query(default=2000, le=20000), session: Session = Depends(db_session)):
    get_or_404(session, Run, run_id, "Run")
    return list(session.scalars(select(TrackSummary).where(TrackSummary.run_id == run_id).order_by(TrackSummary.first_seen_s).limit(limit)))


@router.get("/runs/{run_id}/trajectories")
def run_trajectories(run_id: int, limit: int = Query(default=2000, le=20000), session: Session = Depends(db_session)) -> dict:
    get_or_404(session, Run, run_id, "Run")
    return {"run_id": run_id, "trajectories": trajectories_for_run(session, run_id, limit)}


@router.get("/runs/{run_id}/heatmap")
def run_heatmap(run_id: int, grid: int = Query(default=48, ge=8, le=200), session: Session = Depends(db_session)) -> dict:
    get_or_404(session, Run, run_id, "Run")
    return heatmap_for_run(session, run_id, grid)


@router.get("/experiments/{experiment_id}/summary")
def experiment_summary_route(experiment_id: int, session: Session = Depends(db_session)) -> dict:
    get_or_404(session, Experiment, experiment_id, "Experiment")
    return experiment_summary(session, experiment_id)


@router.get("/compare")
def compare(experiment_ids: str = Query(description="Comma separated experiment ids"), session: Session = Depends(db_session)) -> dict:
    ids = [int(x) for x in experiment_ids.split(",") if x.strip().isdigit()]
    out = []
    for eid in ids:
        e = session.get(Experiment, eid)
        if e is None:
            continue
        s = experiment_summary(session, eid)
        out.append({"experiment_id": eid, "name": e.name, "condition_notes": e.condition_notes, "tags": e.tags, "routes": s["routes"], "crossings": s["crossings"], "zones": s["zones"], "event_count": s["event_count"]})
    return {"experiments": out}


@router.get("/dashboard")
def dashboard(session: Session = Depends(db_session)) -> dict:
    sup = get_supervisor()
    active = []
    for h in sup.active():
        st = h.status or {}
        cam = session.get(Camera, h.spec.camera_id)
        exp = session.get(Experiment, h.spec.experiment_id)
        active.append(
            {
                "run_id": h.run_id,
                "camera_id": h.spec.camera_id,
                "camera_name": cam.name if cam else None,
                "experiment_id": h.spec.experiment_id,
                "experiment_name": exp.name if exp else None,
                "state": st.get("state"),
                "pipeline_fps": st.get("pipeline_fps"),
                "active_tracks": st.get("active_tracks"),
                "counters": st.get("counters"),
                "zone_occupancy": st.get("zone_occupancy"),
                "progress": st.get("progress"),
                "media_time_s": st.get("media_time_s"),
                "recording": st.get("recording") or None,
                "anomaly": ({**st["anomaly"], "enabled": True} if st.get("anomaly") else ({"enabled": True, "state": "starting"} if h.spec.anomaly else None)),
                "model": h.spec.model_id,
                "device": h.spec.device,
                "recent_events": list(h.recent_events)[-10:],
            }
        )
    recent = session.scalars(select(Event).order_by(Event.id.desc()).limit(25))
    recent_events = [
        {"id": e.id, "run_id": e.run_id, "wall_time": e.wall_time, "media_time_s": e.media_time_s, "event_type": e.event_type, "route": e.route, "object_name": e.object_name, "object_class": e.object_class, "track_id": e.track_id, "duration_s": e.duration_s, "context": e.context or {}}
        for e in recent
    ]
    latest_runs = list(session.scalars(select(Run).order_by(Run.id.desc()).limit(8)))
    run_rows = []
    for r in latest_runs:
        exp = session.get(Experiment, r.experiment_id)
        n = session.scalar(select(func.count(Event.id)).where(Event.run_id == r.id)) or 0
        routes = session.execute(select(Event.route, func.count()).where(Event.run_id == r.id, Event.event_type == "route").group_by(Event.route)).all()
        run_rows.append({"id": r.id, "experiment_id": r.experiment_id, "experiment_name": exp.name if exp else None, "status": r.status, "started_at": r.started_at, "ended_at": r.ended_at, "events": n, "routes": {k or "UNKNOWN": v for k, v in routes}})
    return {"active_runs": active, "recent_events": recent_events, "recent_runs": run_rows, "cameras": session.scalar(select(func.count(Camera.id))) or 0, "experiments": session.scalar(select(func.count(Experiment.id))) or 0}
