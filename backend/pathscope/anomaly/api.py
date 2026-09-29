"""HTTP API of the Anomaly Assistant: model settings, anomalies and their evidence."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pathscope.anomaly import service
from pathscope.anomaly.llm.client import (
    TEST_RECORD,
    LLMError,
    interpret,
    list_models,
    sample_pictures,
)
from pathscope.anomaly.llm.settings import (
    LOCAL_MODELS,
    LOCAL_WARNING,
    PROVIDERS,
    LLMSettings,
    load_settings,
    save_settings,
)
from pathscope.anomaly.models import AnomalyEvent
from pathscope.api.deps import db_session, get_or_404
from pathscope.db.models import Camera, Run
from pathscope.workers.supervisor import get_supervisor

router = APIRouter(tags=["anomalies"])


# ---------------------------------------------------------------------------- model settings
class AssistantIn(LLMSettings):
    # None: keep the stored key; "": delete it; text: store it (never returned)
    api_key: str | None = Field(default=None, max_length=500)


def _assistant_view(session: Session) -> dict:
    s = load_settings(session)
    keys = service.key_store()
    return {
        "settings": s.model_dump(),
        "resolved": {"model": s.resolved_model, "base_url": s.resolved_base_url, "vision": s.info.vision, "local": s.info.local},
        "keys": {p.id: keys.describe(p.id) for p in PROVIDERS if p.needs_key or p.id in ("local", "custom")},
        "providers": [p.model_dump() for p in PROVIDERS],
        "local_models": LOCAL_MODELS,
        "local_warning": LOCAL_WARNING,
        "queue": service.get_anomaly_service().queue_state(),
    }


@router.get("/anomaly/assistant")
def get_assistant(session: Session = Depends(db_session)) -> dict:
    return _assistant_view(session)


@router.put("/anomaly/assistant")
def put_assistant(body: AssistantIn, session: Session = Depends(db_session)) -> dict:
    data = body.model_dump(exclude={"api_key"})
    save_settings(session, LLMSettings.model_validate(data))
    if body.api_key is not None:
        service.key_store().set(body.provider, body.api_key or None)
    return _assistant_view(session)


@router.post("/anomaly/assistant/test")
def test_assistant(session: Session = Depends(db_session)) -> dict:
    """Send a tiny synthetic before/after pair to the selected model."""
    s = load_settings(session)
    key, _ = service.key_store().get(s.provider)
    try:
        result = interpret(s, key, dict(TEST_RECORD), sample_pictures())
    except LLMError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "result": result.to_dict(), "expected": "verdict 'confirmed', an orange box on the floor"}


@router.get("/anomaly/assistant/models")
def assistant_models(session: Session = Depends(db_session)) -> dict:
    s = load_settings(session)
    key, _ = service.key_store().get(s.provider)
    try:
        return {"models": list_models(s, key)}
    except LLMError as exc:
        raise HTTPException(422, str(exc)) from exc


# ---------------------------------------------------------------------------- local model setup
def _local_root(session: Session) -> str:
    from pathscope.anomaly.llm.local import ollama_root

    s = load_settings(session)
    return ollama_root(s.base_url if s.provider == "local" else None)


def _same_machine(request: Request) -> None:
    """Installing programs and downloading gigabytes: only from this computer."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "Set up local models from a browser on the CV-Scope computer itself.")


@router.get("/anomaly/local")
def local_status(session: Session = Depends(db_session)) -> dict:
    from pathscope.anomaly.llm.local import get_local_models

    lm = get_local_models()
    return {"ollama": lm.status(_local_root(session)), "catalog": LOCAL_MODELS, "jobs": lm.jobs()}


@router.post("/anomaly/local/install")
def local_install(request: Request, session: Session = Depends(db_session)) -> dict:
    from pathscope.anomaly.llm.local import get_local_models
    from pathscope.config import get_settings

    _same_machine(request)
    try:
        job = get_local_models().install(_local_root(session), get_settings().resolved_data_dir / "anomaly" / "downloads")
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc
    return job.to_dict()


@router.post("/anomaly/local/start")
def local_start(request: Request, session: Session = Depends(db_session)) -> dict:
    from pathscope.anomaly.llm.local import get_local_models

    _same_machine(request)
    try:
        return get_local_models().start(_local_root(session))
    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc


class LocalModelIn(BaseModel):
    model: str = Field(min_length=1, max_length=120)


@router.post("/anomaly/local/pull")
def local_pull(body: LocalModelIn, request: Request, session: Session = Depends(db_session)) -> dict:
    from pathscope.anomaly.llm.local import get_local_models

    _same_machine(request)
    try:
        return get_local_models().pull(_local_root(session), body.model.strip()).to_dict()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/anomaly/local/delete")
def local_delete(body: LocalModelIn, request: Request, session: Session = Depends(db_session)) -> dict:
    from pathscope.anomaly.llm.local import get_local_models

    _same_machine(request)
    try:
        get_local_models().delete(_local_root(session), body.model.strip())
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"deleted": body.model}


@router.post("/anomaly/local/unload")
def local_unload(body: LocalModelIn, request: Request, session: Session = Depends(db_session)) -> dict:
    from pathscope.anomaly.llm.local import get_local_models

    _same_machine(request)
    get_local_models().unload(_local_root(session), body.model.strip())
    return {"unloaded": body.model}


@router.post("/anomaly/local/use")
def local_use(body: LocalModelIn, session: Session = Depends(db_session)) -> dict:
    """Make a downloaded local model the Anomaly Assistant's model."""
    s = load_settings(session)
    keep_url = s.base_url if s.provider == "local" else ""
    save_settings(session, s.model_copy(update={"provider": "local", "model": body.model.strip(), "base_url": keep_url}))
    return _assistant_view(session)


# ---------------------------------------------------------------------------- anomalies
def _camera_names(session: Session, rows: list[AnomalyEvent]) -> dict[int, str]:
    ids = {r.camera_id for r in rows if r.camera_id}
    if not ids:
        return {}
    return {c.id: c.name for c in session.scalars(select(Camera).where(Camera.id.in_(ids)))}


@router.get("/anomalies")
def list_anomalies(
    run_id: int | None = Query(default=None),
    experiment_id: int | None = Query(default=None),
    camera_id: int | None = Query(default=None),
    status: str | None = Query(default=None, description="raised | awaiting_model | dismissed | held"),
    kind: str | None = Query(default=None),
    feedback: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(db_session),
) -> dict:
    q = select(AnomalyEvent)
    if run_id is not None:
        q = q.where(AnomalyEvent.run_id == run_id)
    if experiment_id is not None:
        q = q.where(AnomalyEvent.experiment_id == experiment_id)
    if camera_id is not None:
        q = q.where(AnomalyEvent.camera_id == camera_id)
    if status:
        q = q.where(AnomalyEvent.status == status)
    if kind:
        q = q.where(AnomalyEvent.kind == kind)
    if feedback:
        q = q.where(AnomalyEvent.feedback == (None if feedback == "none" else feedback))
    total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = list(session.scalars(q.order_by(AnomalyEvent.confirmed_at.desc(), AnomalyEvent.id.desc()).offset(offset).limit(limit)))
    names = _camera_names(session, rows)
    return {"items": [service.anomaly_out(r, names.get(r.camera_id or 0)) for r in rows], "total": total}


@router.get("/anomalies/{anomaly_id}")
def get_anomaly(anomaly_id: int, session: Session = Depends(db_session)) -> dict:
    row = get_or_404(session, AnomalyEvent, anomaly_id, "Anomaly")
    return service.anomaly_out(row, _camera_names(session, [row]).get(row.camera_id or 0))


@router.get("/anomalies/{anomaly_id}/evidence/{name}")
def anomaly_evidence(anomaly_id: int, name: str, session: Session = Depends(db_session)):
    row = get_or_404(session, AnomalyEvent, anomaly_id, "Anomaly")
    path = service.evidence_path(row, name)
    if path is None or not path.is_file():
        raise HTTPException(404, "This picture is not available (it may have been deleted with its run or by retention).")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


class FeedbackIn(BaseModel):
    feedback: Literal["true_positive", "false_alarm"] | None = None
    note: str | None = Field(default=None, max_length=2000)
    # A false alarm on a live run: take the current picture of this zone as normal
    rebaseline: bool = False


@router.post("/anomalies/{anomaly_id}/feedback")
def anomaly_feedback(anomaly_id: int, body: FeedbackIn, session: Session = Depends(db_session)) -> dict:
    row = get_or_404(session, AnomalyEvent, anomaly_id, "Anomaly")
    row.feedback = body.feedback
    if body.note is not None:
        row.note = body.note
    session.commit()
    rebaselined = False
    if body.rebaseline:
        rebaselined = get_supervisor().send(row.run_id, "anomaly_rebaseline", {"zone_id": row.zone_id})
    out = service.anomaly_out(row, _camera_names(session, [row]).get(row.camera_id or 0))
    out["rebaselined"] = rebaselined
    return out


@router.post("/anomalies/{anomaly_id}/describe")
def describe_anomaly(anomaly_id: int, session: Session = Depends(db_session)) -> dict:
    """Ask the selected model now (for example for a deterministic zone, or after changing models)."""
    row = get_or_404(session, AnomalyEvent, anomaly_id, "Anomaly")
    try:
        service.get_anomaly_service().describe_again(session, row)
    except LLMError as exc:
        raise HTTPException(422, str(exc)) from exc
    return service.anomaly_out(row, _camera_names(session, [row]).get(row.camera_id or 0))


@router.post("/anomalies/{anomaly_id}/raise")
def raise_anomaly(anomaly_id: int, session: Session = Depends(db_session)) -> dict:
    """Raise a held or dismissed anomaly as an alert event."""
    row = get_or_404(session, AnomalyEvent, anomaly_id, "Anomaly")
    if row.published:
        raise HTTPException(409, "This anomaly was raised already.")
    service.get_anomaly_service().raise_now(session, row)
    return service.anomaly_out(row, _camera_names(session, [row]).get(row.camera_id or 0))


@router.delete("/anomalies/{anomaly_id}", status_code=204)
def delete_anomaly(anomaly_id: int, session: Session = Depends(db_session)):
    row = get_or_404(session, AnomalyEvent, anomaly_id, "Anomaly")
    service.delete_evidence(row)
    session.delete(row)
    session.commit()


class RebaselineIn(BaseModel):
    zone_id: str | None = None  # None: learn the whole normal picture again


@router.post("/runs/{run_id}/anomaly/rebaseline")
def rebaseline(run_id: int, body: RebaselineIn, session: Session = Depends(db_session)) -> dict:
    get_or_404(session, Run, run_id, "Run")
    h = get_supervisor().get(run_id)
    if h is None or h.finished:
        raise HTTPException(409, "The run is not active.")
    if not h.spec.anomaly:
        raise HTTPException(409, "This run does not use the Anomaly Assistant.")
    return {"sent": get_supervisor().send(run_id, "anomaly_rebaseline", {"zone_id": body.zone_id})}
