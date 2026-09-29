"""Experiments: research configurations that pin a scene version, classes,
model, tracker and rules."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404
from pathscope.api.schemas import ExperimentIn, ExperimentOut, ExperimentUpdate, RunOut
from pathscope.db.models import Camera, Experiment, Project, Run, SceneConfig
from pathscope.vision.trackers import validate_tracker_settings
from pathscope.workers.supervisor import get_supervisor

router = APIRouter(prefix="/experiments", tags=["experiments"])


def _check_tracker(tracker_id: str | None, settings: dict | None) -> None:
    try:
        validate_tracker_settings(tracker_id or "bytetrack", settings or {})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _run_out(r: Run) -> RunOut:
    o = RunOut.model_validate(r)
    h = get_supervisor().get(r.id)
    if h is not None and not h.finished:
        o.live = h.status
    return o


def _out(session: Session, e: Experiment) -> ExperimentOut:
    o = ExperimentOut.model_validate(e)
    o.run_count = session.scalar(select(func.count(Run.id)).where(Run.experiment_id == e.id)) or 0
    last = session.scalar(select(Run).where(Run.experiment_id == e.id).order_by(Run.id.desc()).limit(1))
    o.last_run = _run_out(last) if last else None
    if e.camera_id:
        cam = session.get(Camera, e.camera_id)
        o.camera_name = cam.name if cam else None
    return o


@router.get("", response_model=list[ExperimentOut])
def list_experiments(project_id: int | None = Query(default=None), camera_id: int | None = Query(default=None), session: Session = Depends(db_session)):
    q = select(Experiment).order_by(Experiment.updated_at.desc())
    if project_id is not None:
        q = q.where(Experiment.project_id == project_id)
    if camera_id is not None:
        q = q.where(Experiment.camera_id == camera_id)
    return [_out(session, e) for e in session.scalars(q)]


@router.post("", response_model=ExperimentOut, status_code=201)
def create_experiment(body: ExperimentIn, session: Session = Depends(db_session)):
    get_or_404(session, Project, body.project_id, "Project")
    if body.camera_id is not None:
        get_or_404(session, Camera, body.camera_id, "Camera")
    if body.scene_config_id is not None:
        get_or_404(session, SceneConfig, body.scene_config_id, "Scene")
    _check_tracker(body.tracker_id, body.tracker_settings)
    e = Experiment(
        project_id=body.project_id,
        camera_id=body.camera_id,
        scene_config_id=body.scene_config_id,
        name=body.name,
        description=body.description,
        notes=body.notes,
        condition_notes=body.condition_notes,
        tags=body.tags,
        object_classes=body.object_classes,
        model_id=body.model_id,
        tracker_id=body.tracker_id,
        inference=body.inference.model_dump(),
        tracker_settings=body.tracker_settings,
        rules=[r.model_dump() for r in body.rules],
        recording=body.recording.model_dump(),
        anomaly=body.anomaly.model_dump(),
        relations=body.relations.model_dump(),
        status="draft",
    )
    session.add(e)
    session.commit()
    session.refresh(e)
    return _out(session, e)


@router.get("/{experiment_id}", response_model=ExperimentOut)
def get_experiment(experiment_id: int, session: Session = Depends(db_session)):
    return _out(session, get_or_404(session, Experiment, experiment_id, "Experiment"))


@router.put("/{experiment_id}", response_model=ExperimentOut)
def update_experiment(experiment_id: int, body: ExperimentUpdate, session: Session = Depends(db_session)):
    e = get_or_404(session, Experiment, experiment_id, "Experiment")
    h = get_supervisor().get(e.id)
    data = body.model_dump(exclude_unset=True)
    active = any(hh.spec.experiment_id == e.id for hh in get_supervisor().active())
    if active and any(k in data for k in ("camera_id", "scene_config_id", "object_classes", "model_id", "tracker_id", "inference", "tracker_settings", "rules", "recording", "anomaly", "relations")):
        raise HTTPException(409, "Stop the active run before changing the experiment configuration.")
    if data.get("camera_id") is not None:
        get_or_404(session, Camera, data["camera_id"], "Camera")
    if data.get("scene_config_id") is not None:
        get_or_404(session, SceneConfig, data["scene_config_id"], "Scene")
    if "tracker_id" in data or "tracker_settings" in data:
        _check_tracker(data.get("tracker_id") or e.tracker_id, data["tracker_settings"] if data.get("tracker_settings") is not None else e.tracker_settings)
    if "inference" in data and data["inference"] is not None:
        data["inference"] = body.inference.model_dump() if body.inference else {}
    if "rules" in data and data["rules"] is not None:
        data["rules"] = [r.model_dump() for r in body.rules or []]
    if "recording" in data:
        data["recording"] = body.recording.model_dump() if body.recording else {}
    if "anomaly" in data:
        data["anomaly"] = body.anomaly.model_dump() if body.anomaly else {}
    if "relations" in data:
        data["relations"] = body.relations.model_dump() if body.relations else {}
    for k, v in data.items():
        setattr(e, k, v)
    session.commit()
    session.refresh(e)
    _ = h
    return _out(session, e)


@router.delete("/{experiment_id}", status_code=204)
def delete_experiment(experiment_id: int, session: Session = Depends(db_session)):
    e = get_or_404(session, Experiment, experiment_id, "Experiment")
    if any(h.spec.experiment_id == e.id for h in get_supervisor().active()):
        raise HTTPException(409, "Stop the active run before deleting the experiment.")
    session.delete(e)
    session.commit()


@router.post("/{experiment_id}/duplicate", response_model=ExperimentOut, status_code=201)
def duplicate_experiment(experiment_id: int, name: str | None = Query(default=None), session: Session = Depends(db_session)):
    e = get_or_404(session, Experiment, experiment_id, "Experiment")
    copy = Experiment(
        project_id=e.project_id,
        camera_id=e.camera_id,
        scene_config_id=e.scene_config_id,
        name=name or f"{e.name} (copy)",
        description=e.description,
        notes=e.notes,
        condition_notes=e.condition_notes,
        tags=list(e.tags),
        object_classes=list(e.object_classes),
        model_id=e.model_id,
        tracker_id=e.tracker_id,
        inference=dict(e.inference),
        tracker_settings=dict(e.tracker_settings),
        rules=list(e.rules),
        recording=dict(e.recording or {}),
        anomaly=dict(e.anomaly or {}),
        relations=dict(e.relations or {}),
        status="draft",
    )
    session.add(copy)
    session.commit()
    session.refresh(copy)
    return _out(session, copy)


@router.get("/{experiment_id}/runs", response_model=list[RunOut])
def experiment_runs(experiment_id: int, session: Session = Depends(db_session)):
    get_or_404(session, Experiment, experiment_id, "Experiment")
    return [_run_out(r) for r in session.scalars(select(Run).where(Run.experiment_id == experiment_id).order_by(Run.id.desc()))]
