"""Manual accuracy validation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.analytics import evaluation_metrics
from pathscope.api.deps import db_session, get_or_404
from pathscope.api.schemas import EvaluationIn, EvaluationOut, GroundTruthIn, GroundTruthOut
from pathscope.db.models import Evaluation, Event, GroundTruthCount, Run

router = APIRouter(prefix="/evaluations", tags=["evaluation"])


@router.get("", response_model=list[EvaluationOut])
def list_evaluations(run_id: int = Query(), session: Session = Depends(db_session)):
    return list(session.scalars(select(Evaluation).where(Evaluation.run_id == run_id).order_by(Evaluation.id.desc())))


@router.post("", response_model=EvaluationOut, status_code=201)
def create_evaluation(body: EvaluationIn, session: Session = Depends(db_session)):
    get_or_404(session, Run, body.run_id, "Run")
    if body.event_id is not None:
        ev = get_or_404(session, Event, body.event_id, "Event")
        if ev.run_id != body.run_id:
            raise HTTPException(400, "event belongs to a different run")
        existing = session.scalar(select(Evaluation).where(Evaluation.event_id == body.event_id))
        if existing is not None:
            existing.verdict, existing.expected, existing.note = body.verdict, body.expected, body.note
            session.commit()
            session.refresh(existing)
            return existing
    e = Evaluation(**body.model_dump())
    session.add(e)
    session.commit()
    session.refresh(e)
    return e


@router.delete("/{evaluation_id}", status_code=204)
def delete_evaluation(evaluation_id: int, session: Session = Depends(db_session)):
    e = get_or_404(session, Evaluation, evaluation_id, "Evaluation")
    session.delete(e)
    session.commit()


@router.get("/metrics")
def metrics(run_id: int = Query(), session: Session = Depends(db_session)) -> dict:
    get_or_404(session, Run, run_id, "Run")
    return evaluation_metrics(session, run_id)


@router.get("/ground-truth", response_model=list[GroundTruthOut])
def list_ground_truth(run_id: int = Query(), session: Session = Depends(db_session)):
    return list(session.scalars(select(GroundTruthCount).where(GroundTruthCount.run_id == run_id)))


@router.post("/ground-truth", response_model=GroundTruthOut, status_code=201)
def set_ground_truth(body: GroundTruthIn, session: Session = Depends(db_session)):
    get_or_404(session, Run, body.run_id, "Run")
    existing = session.scalar(select(GroundTruthCount).where(GroundTruthCount.run_id == body.run_id, GroundTruthCount.object_id == body.object_id))
    if existing is not None:
        existing.count, existing.label, existing.note = body.count, body.label, body.note
        session.commit()
        session.refresh(existing)
        return existing
    g = GroundTruthCount(**body.model_dump())
    session.add(g)
    session.commit()
    session.refresh(g)
    return g


@router.delete("/ground-truth/{gt_id}", status_code=204)
def delete_ground_truth(gt_id: int, session: Session = Depends(db_session)):
    g = get_or_404(session, GroundTruthCount, gt_id, "Ground truth")
    session.delete(g)
    session.commit()
