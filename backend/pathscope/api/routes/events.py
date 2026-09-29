"""Event explorer and export."""

from __future__ import annotations

import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from pathscope.analytics.export import export_events
from pathscope.api.deps import db_session
from pathscope.api.schemas import EventOut, Page
from pathscope.db.models import Event, Experiment, Run

router = APIRouter(prefix="/events", tags=["events"])

SORTABLE = {
    "wall_time": Event.wall_time,
    "media_time_s": Event.media_time_s,
    "event_type": Event.event_type,
    "route": Event.route,
    "object_class": Event.object_class,
    "duration_s": Event.duration_s,
    "avg_speed": Event.avg_speed,
    "confidence": Event.confidence,
    "track_id": Event.track_id,
    "id": Event.id,
}


def _filters(
    q: Select,
    run_id: int | None,
    experiment_id: int | None,
    camera_id: int | None,
    project_id: int | None,
    object_class: str | None,
    event_type: str | None,
    route: str | None,
    object_id: str | None,
    track_id: int | None,
    from_s: float | None,
    to_s: float | None,
    from_time: datetime | None,
    to_time: datetime | None,
    search: str | None,
) -> Select:
    if run_id is not None:
        q = q.where(Event.run_id == run_id)
    if experiment_id is not None:
        q = q.where(Event.experiment_id == experiment_id)
    if camera_id is not None:
        q = q.where(Event.camera_id == camera_id)
    if project_id is not None:
        q = q.where(Event.experiment_id.in_(select(Experiment.id).where(Experiment.project_id == project_id)))
    if object_class:
        q = q.where(Event.object_class.in_([c.strip() for c in object_class.split(",") if c.strip()]))
    if event_type:
        q = q.where(Event.event_type.in_([c.strip() for c in event_type.split(",") if c.strip()]))
    if route:
        q = q.where(Event.route.in_([c.strip() for c in route.split(",") if c.strip()]))
    if object_id:
        q = q.where(Event.object_id == object_id)
    if track_id is not None:
        q = q.where(Event.track_id == track_id)
    if from_s is not None:
        q = q.where(Event.media_time_s >= from_s)
    if to_s is not None:
        q = q.where(Event.media_time_s <= to_s)
    if from_time is not None:
        q = q.where(Event.wall_time >= from_time)
    if to_time is not None:
        q = q.where(Event.wall_time <= to_time)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Event.object_name.ilike(like), Event.route.ilike(like), Event.rule_name.ilike(like), Event.event_type.ilike(like), Event.object_class.ilike(like)))
    return q


@router.get("", response_model=Page)
def list_events(
    run_id: int | None = None,
    experiment_id: int | None = None,
    camera_id: int | None = None,
    project_id: int | None = None,
    object_class: str | None = None,
    event_type: str | None = None,
    route: str | None = None,
    object_id: str | None = None,
    track_id: int | None = None,
    from_s: float | None = None,
    to_s: float | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    search: str | None = None,
    sort: str = Query(default="id"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    session: Session = Depends(db_session),
):
    base = _filters(select(Event), run_id, experiment_id, camera_id, project_id, object_class, event_type, route, object_id, track_id, from_s, to_s, from_time, to_time, search)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    col = SORTABLE.get(sort, Event.id)
    q = base.order_by(col.desc() if order == "desc" else col.asc()).offset((page - 1) * page_size).limit(page_size)
    items = [EventOut.model_validate(e) for e in session.scalars(q)]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/facets")
def facets(run_id: int | None = None, experiment_id: int | None = None, project_id: int | None = None, session: Session = Depends(db_session)) -> dict:
    base = _filters(select(Event), run_id, experiment_id, None, project_id, None, None, None, None, None, None, None, None, None, None)
    sub = base.subquery()

    def _vals(col):
        rows = session.execute(select(getattr(sub.c, col), func.count()).group_by(getattr(sub.c, col))).all()
        return [{"value": r[0], "count": r[1]} for r in rows if r[0] is not None]

    return {"event_type": _vals("event_type"), "route": _vals("route"), "object_class": _vals("object_class"), "object_name": _vals("object_name")}


@router.get("/export")
def export(
    format: str = Query(default="csv", pattern="^(csv|json|parquet)$"),
    run_id: int | None = None,
    experiment_id: int | None = None,
    camera_id: int | None = None,
    project_id: int | None = None,
    object_class: str | None = None,
    event_type: str | None = None,
    route: str | None = None,
    object_id: str | None = None,
    track_id: int | None = None,
    from_s: float | None = None,
    to_s: float | None = None,
    from_time: datetime | None = None,
    to_time: datetime | None = None,
    search: str | None = None,
    session: Session = Depends(db_session),
):
    q = _filters(select(Event), run_id, experiment_id, camera_id, project_id, object_class, event_type, route, object_id, track_id, from_s, to_s, from_time, to_time, search).order_by(Event.id.asc())
    events = list(session.scalars(q))
    try:
        payload, media_type, ext = export_events(events, format)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    scope = f"run{run_id}" if run_id else (f"experiment{experiment_id}" if experiment_id else "events")
    filename = f"cvscope_{scope}_{int(time.time())}.{ext}"
    return Response(content=payload, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int, session: Session = Depends(db_session)):
    e = session.get(Event, event_id)
    if e is None:
        raise HTTPException(404, "event not found")
    return e


@router.get("/runs/{run_id}/timeline")
def timeline(run_id: int, session: Session = Depends(db_session)) -> dict:
    """Compact event markers for the review timeline."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    rows = session.execute(select(Event.id, Event.media_time_s, Event.event_type, Event.route, Event.object_name, Event.track_id, Event.object_class, Event.context).where(Event.run_id == run_id).order_by(Event.media_time_s)).all()
    # ``entity`` is the opaque reference (kind and ids, never a name); a viewer
    # with a recognition token resolves it to a name in the browser.
    return {
        "run_id": run_id,
        "markers": [
            {"id": r[0], "t": r[1], "type": r[2], "route": r[3], "object": r[4], "track_id": r[5], "cls": r[6], **({"entity": (r[7] or {}).get("entity")} if (r[7] or {}).get("entity") else {})}
            for r in rows
        ],
    }
